"""First-run setup: the three steps (You, BCC, Backup) plus the optional calendar.

Pure functions with seams (``runner``, ``platform``, ``open_mailbox``, ``push``,
``fetch``) so the CLI wizard (``owncrm init`` / ``owncrm setup``) and the web
page (``/setup``) share one implementation. Secrets are stored through
``owncrm.secrets`` or the macOS Keychain and are never logged or returned.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import bcc, calendar_sync, secrets
from .gitops import GitOps
from .store import DEFAULT_CONFIG, Store, load_config

KEYCHAIN_SERVICE = "owncrm-bcc"
PRIVATE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")
IMAP_HOSTS = {
    "gmail.com": "imap.gmail.com",
    "googlemail.com": "imap.gmail.com",
    "outlook.com": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com",
    "live.com": "outlook.office365.com",
    "icloud.com": "imap.mail.me.com",
    "me.com": "imap.mail.me.com",
    "mac.com": "imap.mail.me.com",
}
GMAIL_DOMAINS = ("gmail.com", "googlemail.com")
_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


# ----------------------------------------------------------- config.toml io


def toml_value(value) -> str:
    """TOML literal for str, int, bool and list[str]."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(str(v)) for v in value) + "]"
    if isinstance(value, str):
        # JSON string escapes (\" \\ \n \uXXXX) are valid TOML basic-string escapes.
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f"unsupported config value {value!r}")


def set_config_values(path: Path | str, values: dict) -> Path:
    """Set keys in config.toml, keeping every comment and unrelated line.

    An existing ``key = ...`` line is replaced (an uncommented one first, else
    the first ``# key = ...``); a missing key is appended at the end."""
    path = Path(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    for key, value in values.items():
        new = f"{key} = {toml_value(value)}"
        live = re.compile(rf"^\s*{re.escape(key)}\s*=")
        commented = re.compile(rf"^\s*#\s*{re.escape(key)}\s*=")
        idx = next((i for i, l in enumerate(lines) if live.match(l)), None)
        if idx is None:
            idx = next((i for i, l in enumerate(lines) if commented.match(l)), None)
        if idx is None:
            lines.append(new)
        else:
            lines[idx] = new
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- results


@dataclass
class StepResult:
    ok: bool = True
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    values: dict = field(default_factory=dict)

    def text(self) -> str:
        parts = list(self.errors.values()) + self.messages + self.warnings
        return " ".join(p for p in parts if p)


def _domain(address: str) -> str:
    return address.rpartition("@")[2].lower()


def valid_email(address: str) -> bool:
    return bool(_EMAIL.match(address or ""))


def parse_addresses(raw: str | list[str]) -> list[str]:
    items = raw if isinstance(raw, (list, tuple)) else re.split(r"[\s,;]+", raw or "")
    out: list[str] = []
    for item in items:
        item = item.strip().lower()
        if item and item not in out:
            out.append(item)
    return out


# ------------------------------------------------------------- step 1: You


def plan_you(name: str, addresses: str | list[str]) -> StepResult:
    name = (name or "").strip()
    emails = parse_addresses(addresses)
    result = StepResult()
    if not name:
        result.errors["name"] = "Give your name."
    if not emails:
        result.errors["addresses"] = "Give at least one address you send mail from."
    bad = [e for e in emails if not valid_email(e)]
    if bad:
        result.errors["addresses"] = "Not an email address: " + ", ".join(bad)
    if result.errors:
        result.ok = False
        return result
    domains = sorted({_domain(e) for e in emails} - bcc.FREEMAIL)
    result.values = {"owner_name": name, "owner_email": emails[0],
                     "my_addresses": emails, "bcc_ignore_domains": domains}
    return result


def save_you(data_dir: Path, name: str, addresses: str | list[str]) -> StepResult:
    result = plan_you(name, addresses)
    if result.ok:
        set_config_values(Path(data_dir) / "config.toml", result.values)
        result.messages.append(f"Saved: {result.values['owner_name']} "
                               f"<{result.values['owner_email']}>.")
    return result


# ------------------------------------------------------------- step 2: BCC


def suggest_bcc_address(email: str) -> str:
    """you+crm@gmail.com for Gmail; '' (ask) for anything else."""
    email = (email or "").strip().lower()
    local, _, domain = email.partition("@")
    if domain in GMAIL_DOMAINS and local:
        return f"{local.split('+')[0]}+crm@{domain}"
    return ""


def imap_host_for(email: str) -> str:
    """The IMAP host for well-known providers; '' (ask) otherwise."""
    return IMAP_HOSTS.get(_domain(email or ""), "")


def imap_user_for(address: str) -> str:
    return bcc.Settings(address=address).imap_user


def gmail_filter_text(bcc_address: str) -> str:
    return (f"Matches: to:({bcc_address}) → Skip the Inbox, Mark as read, "
            "Apply label OwnCRM")


def save_bcc(data_dir: Path, address: str, imap_host: str, password: str = "",
             use_keychain: bool = False, runner=subprocess.run,
             platform: str | None = None) -> StepResult:
    """Save bcc_address / bcc_imap_host and the app password (never logged)."""
    address = (address or "").strip().lower()
    imap_host = (imap_host or "").strip().lower() or imap_host_for(address)
    result = StepResult()
    if not valid_email(address):
        result.errors["address"] = "Give the BCC address, e.g. you+crm@gmail.com."
    if not imap_host:
        result.errors["imap_host"] = "Give the IMAP server of that mailbox."
    if result.errors:
        result.ok = False
        return result
    data_dir = Path(data_dir)
    values: dict = {"bcc_address": address, "bcc_imap_host": imap_host}
    user = imap_user_for(address)
    if password:
        if use_keychain and (platform or sys.platform) == "darwin":
            try:
                proc = runner(["security", "add-generic-password", "-U", "-s",
                               KEYCHAIN_SERVICE, "-a", user, "-w", password],
                              capture_output=True, text=True, timeout=20)
                code = proc.returncode
            except (OSError, subprocess.TimeoutExpired):
                code = -1
            if code != 0:
                result.ok = False
                result.errors["password"] = ("Could not save the password in the Keychain; "
                                             "try again without the Keychain option.")
                return result
            values["bcc_keychain_service"] = KEYCHAIN_SERVICE
            result.messages.append(f"App password saved in the Keychain "
                                   f"(service {KEYCHAIN_SERVICE}, account {user}).")
        else:
            secrets.set("bcc_password", password, data_dir)
            result.messages.append("App password saved in .secrets.toml.")
    set_config_values(data_dir / "config.toml", values)
    result.values = values
    result.messages.insert(0, f"BCC address saved: {address}.")
    if _domain(address) in GMAIL_DOMAINS:
        result.messages.append("Gmail filter: " + gmail_filter_text(address))
    return result


def login_hint(message: str, imap_host: str = "") -> str:
    low = message.lower()
    if "refused the login" in low or "authenticationfailed" in low or "invalid credentials" in low:
        if "gmail" in imap_host or "gmail" in low:
            return ("Gmail rejected the login: use an app password, not your normal "
                    "password (https://myaccount.google.com/apppasswords).")
        return "The server rejected the login: check the user and the (app) password."
    if "no gmail app password" in low or "no app password" in low:
        return "No app password stored yet: save one in the BCC step."
    if "could not reach" in low or "connection" in low:
        return f"Could not connect to {imap_host or 'the IMAP server'}: check the host name."
    if "not set up" in low:
        return "Save a BCC address first."
    return ""


def test_bcc(data_dir: Path, config: dict | None = None, open_mailbox=None,
             store: Store | None = None) -> StepResult:
    """Connect and run a dry-run import; the summary, or the error with a hint."""
    data_dir = Path(data_dir)
    config = config if config is not None else load_config(data_dir)
    settings = bcc.settings_from_config(config)
    if store is None:
        store = Store(data_dir)
        store.load()
    opener = open_mailbox or (lambda: bcc.open_gmail(settings, data_dir))
    try:
        run = bcc.run_bcc(store, bcc.Inbox(data_dir), settings, False, opener)
    except Exception as exc:
        message = str(exc) if isinstance(exc, bcc.BccError) else f"{type(exc).__name__}: {exc}"
        hint = login_hint(message, settings.imap_host)
        return StepResult(ok=False, errors={"test": f"BCC test failed: {message}"
                                            + (f" Hint: {hint}" if hint else "")})
    return StepResult(messages=[f"BCC test OK (dry run): {run.summary()}"])


# ---------------------------------------------------------- step 3: Backup


def remote_host(url: str) -> str:
    url = (url or "").strip()
    m = re.match(r"^[\w.-]+@([\w.-]+):", url)  # scp-like git@github.com:me/crm.git
    if m:
        return m.group(1).lower()
    return (urlparse(url).hostname or "").lower()


def private_warning(url: str) -> str:
    host = remote_host(url)
    if any(host == h or host.endswith("." + h) for h in PRIVATE_HOSTS):
        return (f"{host} hosts public repositories too: make sure this repository is "
                "PRIVATE, it holds your contacts and mail.")
    return ""


def _git(data_dir: Path, args: list[str], runner=subprocess.run):
    return runner(["git", *args], cwd=data_dir, capture_output=True, text=True, timeout=30)


def remote_url(data_dir: Path, remote: str = "origin", runner=subprocess.run) -> str:
    try:
        proc = _git(Path(data_dir), ["remote", "get-url", remote], runner)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def save_backup(data_dir: Path, url: str, config: dict | None = None,
                runner=subprocess.run, push: Callable[[], tuple[bool, str]] | None = None
                ) -> StepResult:
    """Add or update the git remote, test push, set push_enabled."""
    data_dir = Path(data_dir)
    url = (url or "").strip()
    result = StepResult()
    if not url or " " in url:
        result.ok = False
        result.errors["url"] = "Give a git remote URL, e.g. git@github.com:you/crm.git."
        return result
    config = config if config is not None else load_config(data_dir)
    name = str(config.get("remote") or "origin")
    warning = private_warning(url)
    if warning:
        result.warnings.append(warning)
    verb = "set-url" if remote_url(data_dir, name, runner) else "add"
    proc = _git(data_dir, ["remote", verb, name, url], runner)
    if proc.returncode != 0:
        result.ok = False
        result.errors["url"] = f"git remote {verb} failed: {(proc.stderr or '').strip()}"
        return result
    if push is None:
        def push() -> tuple[bool, str]:
            ops = GitOps(data_dir, remote=name)
            ok = ops.push_sync()
            return ok, (ops.last_push or {}).get("error", "")
    ok, error = push()
    set_config_values(data_dir / "config.toml", {"push_enabled": bool(ok)})
    result.values = {"push_enabled": bool(ok), "remote": name}
    if ok:
        result.messages.append(f"Remote {name} saved and the test push worked; "
                               "every change is pushed from now on.")
    else:
        result.ok = False
        result.errors["push"] = (f"Remote {name} saved, but the test push failed: {error}. "
                                 "Pushing stays off until a push works.")
    return result


# --------------------------------------------------------- step 4: Calendar


def save_calendar(data_dir: Path, url: str, config: dict | None = None,
                  fetch: Callable[[str], str] | None = None,
                  store: Store | None = None) -> StepResult:
    """Store the secret ICS URL and dry-run an import; the URL is never echoed."""
    data_dir = Path(data_dir)
    url = (url or "").strip()
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if not re.match(r"^https?://\S+$", url):
        return StepResult(ok=False, errors={"url": "Give the secret ICS address "
                                            "(https://... or webcal://...)."})
    secrets.set("calendar_ics_url", url, data_dir)
    result = StepResult(messages=["Calendar URL saved in .secrets.toml."])
    config = config if config is not None else load_config(data_dir)
    settings = calendar_sync.settings_from_config(config)
    if store is None:
        store = Store(data_dir)
        store.load()
    fetcher = fetch or calendar_sync.fetch_ics
    try:
        run = calendar_sync.run_calendar(store, bcc.Inbox(data_dir), settings, False,
                                         lambda: fetcher(url))
    except Exception as exc:
        text = str(exc).replace(url, "<calendar URL>")
        result.ok = False
        result.errors["test"] = f"Saved, but the test fetch failed: {text}"
        return result
    result.messages.append(f"Calendar test OK (dry run): {run.summary()}")
    return result


# ------------------------------------------------------------------ state


def setup_state(data_dir: Path, config: dict | None = None, *, env: dict | None = None,
                runner=subprocess.run, platform: str | None = None) -> dict[str, bool]:
    """Which steps are done: you, bcc, backup (the three) and calendar (optional)."""
    data_dir = Path(data_dir)
    config = dict(DEFAULT_CONFIG, **(config if config is not None else load_config(data_dir)))
    you = bool(str(config.get("owner_email") or "").strip())
    settings = bcc.settings_from_config(config)
    bcc_done = bool(settings.address) and bool(secrets.get(
        "bcc_password", data_dir, config, account=settings.imap_user, env=env,
        runner=runner, platform=platform))
    backup = bool(remote_url(data_dir, str(config.get("remote") or "origin"), runner)) \
        and bool(config.get("push_enabled"))
    calendar = bool(secrets.get("calendar_ics_url", data_dir, config, env=env,
                                runner=runner, platform=platform))
    return {"you": you, "bcc": bcc_done, "backup": backup, "calendar": calendar}


def pending(state: dict[str, bool]) -> bool:
    return not all(state.get(k) for k in ("you", "bcc", "backup"))
