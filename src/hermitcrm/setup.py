# Copyright 2026 Gijs Bos
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Setup and settings: the three steps (You, BCC, Backup), the optional
calendar, and the plain config sections (Enrichment, Outcomes).

Pure functions with seams (``runner``, ``platform``, ``open_mailbox``, ``push``,
``fetch``) so the CLI wizard (``hermitcrm init`` / ``hermitcrm setup``) and the web
page (``/settings``) share one implementation. Secrets are stored through
``hermitcrm.secrets`` or the OS secret store (macOS Keychain, Linux Secret
Service) and are never logged or returned.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tomllib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import backup as local_backup
from . import bcc, calendar_sync, secrets
from .gitops import GitOps
from .store import DEFAULT_CONFIG, Store, load_config

logger = logging.getLogger("hermitcrm.setup")

CONFIG_FILE = "config.toml"
KEYCHAIN_SERVICE = "hermitcrm-bcc"
PRIVATE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")
ENRICH_PROVIDERS = ("auto", "claude", "codex", "gemini", "grok", "custom")
ENRICH_ACCOUNTS = ("subscription", "api")
AI_TIERS = ("medium", "strong")
THEMES = ("light", "dark", "system")
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
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k} = {toml_value(v)}" for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(v if isinstance(v, dict) else str(v))
                               for v in value) + "]"
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


def committed_config_text(data_dir: Path | str) -> str | None:
    """config.toml as the last commit has it; None when there is none."""
    try:
        proc = subprocess.run(["git", "show", f"HEAD:{CONFIG_FILE}"], cwd=data_dir,
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _shown(value) -> str | None:
    """A value short and plain enough to put in a commit message, else None.

    Long strings and anything with spaces (a custom enrich_command, say) are
    named but not quoted: the message is a label, not a copy of the file."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        if not value:
            return '""'
        return value if len(value) <= 40 and not re.search(r"\s", value) else None
    if isinstance(value, list):
        items = [_shown(v) for v in value]
        if all(i is not None for i in items):
            text = "[" + ", ".join(items) + "]"
            return text if len(text) <= 40 else None
    return None


def describe_config_change(old: dict, new: dict, limit: int = 100) -> str:
    """A commit message for config.toml going from `old` to `new`, e.g.
    "settings: theme light -> dark"; '' when no value changed."""
    keys = [k for k in new if old.get(k) != new[k]] + [k for k in old if k not in new]
    if not keys:
        return ""
    parts = []
    for key in keys:
        before, after = _shown(old.get(key)), _shown(new.get(key))
        if key not in new:
            parts.append(f"{key} removed")
        elif key not in old and after is not None:
            parts.append(f"{key} unset -> {after}")
        elif before is not None and after is not None:
            parts.append(f"{key} {before} -> {after}")
        else:
            parts.append(f"{key} changed")
    for message in ("settings: " + "; ".join(parts), "settings: " + ", ".join(keys)):
        if len(message) <= limit:
            return message
    return f"settings: {', '.join(keys[:3])} and {len(keys) - 3} more"


def commit_config(data_dir: Path | str,
                  commit: Callable[[str, list[str]], object]) -> str:
    """Commit config.toml when it differs from the last commit; the message.

    Every settings save calls this after writing, through the web app's
    config_saved() or the CLI wizard. `commit(message, paths)` is
    Store.notify or GitOps.commit: commits are scoped to the paths named, so
    only config.toml goes in (never .secrets.toml). A config.toml holding a
    secret is left uncommitted, with a warning, rather than sent to a remote.
    """
    path = Path(data_dir) / CONFIG_FILE
    try:
        text = path.read_text(encoding="utf-8")
        new = tomllib.loads(text)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("config.toml not committed: %s", exc)
        return ""
    leaked = [name for name in secrets.NAMES if name in new]
    if leaked:
        logger.warning("config.toml not committed: it holds %s, which belongs in "
                       ".secrets.toml or the OS secret store", ", ".join(leaked))
        return ""
    head = committed_config_text(data_dir)
    if head == text:
        return ""
    try:
        old = tomllib.loads(head or "")
    except tomllib.TOMLDecodeError:
        old = {}
    # Only comments or layout changed (a hand edit): still commit, plainly named.
    message = describe_config_change(old, new) or "settings: config.toml"
    commit(message, [CONFIG_FILE])
    return message


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
            "Apply label Hermit CRM")


def save_bcc(data_dir: Path, address: str, imap_host: str, password: str = "",
             use_keychain: bool = False, runner=subprocess.run,
             platform: str | None = None, env: dict | None = None) -> StepResult:
    """Save bcc_address / bcc_imap_host and the app password (never logged).

    use_keychain asks for the OS secret store (the macOS Keychain, or the Secret
    Service on Linux). When there is none, the password goes to .secrets.toml
    and the result says so. After a save to the OS store, a bcc_password left in
    .secrets.toml is removed, because the file is read first and would win."""
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
        store = (secrets.os_store(platform, runner=runner, env=env)
                 if use_keychain else None)
        if store:
            label = secrets.STORE_LABELS[store]
            if not secrets.os_store_save(store, KEYCHAIN_SERVICE, user, password,
                                         label="Hermit CRM app password", runner=runner):
                result.ok = False
                result.errors["password"] = (f"Could not save the password in {label}; "
                                             "try again without that option.")
                return result
            values["bcc_keychain_service"] = KEYCHAIN_SERVICE
            result.messages.append(f"App password saved in {label} "
                                   f"(service {KEYCHAIN_SERVICE}, account {user}).")
            if secrets.unset("bcc_password", data_dir):
                result.messages.append("The old copy in .secrets.toml is removed.")
        else:
            secrets.set("bcc_password", password, data_dir)
            if use_keychain:
                result.messages.append("No system keyring was found, so the app password "
                                       "is saved in .secrets.toml (mode 600).")
            else:
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


# ------------------------------------------------------------- Enrichment


def _positive_int(raw: str, key: str, label: str, errors: dict) -> int | None:
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 0
    if value < 1:
        errors[key] = f"{label} must be a whole number of at least 1."
        return None
    return value


def save_fields(data_dir: Path, text: str) -> StepResult:
    """Replace fields.toml with `text`, refusing anything it cannot honour.

    The textarea holds the file itself, so what you are about to save is what
    you are looking at; there is no separate preview to drift from it.
    """
    from . import fields as custom
    result = StepResult()
    text = (text or "").strip()
    try:
        defs = custom.parse(tomllib.loads(text)) if text else []
    except tomllib.TOMLDecodeError as exc:
        result.ok = False
        result.errors["fields"] = f"That is not valid TOML: {exc}"
        return result
    except custom.FieldError as exc:
        result.ok = False
        result.errors["fields"] = "; ".join(f"{k}: {v}" for k, v in exc.errors.items())
        return result
    custom.write(Path(data_dir), defs)
    result.messages.append(f"Fields saved: {len(defs)}." if defs
                           else "Fields saved: none; fields.toml removed.")
    return result


def add_field(data_dir: Path, key: str, label: str = "", type: str = "text",
              applies_to: str = "company", options: str = "",
              show_in: list[str] | None = None, help: str = "",
              messaging: bool = True) -> StepResult:
    """Append one field to the folder's definitions."""
    from . import fields as custom
    result = StepResult()
    data_dir = Path(data_dir)
    try:
        existing = custom.load(data_dir)
    except custom.FieldError as exc:
        result.ok = False
        result.errors["fields"] = ("The existing fields.toml has a problem; fix it below "
                                   "first: " + "; ".join(exc.errors.values()))
        return result
    entry = {
        "key": key, "label": label, "type": type, "applies_to": applies_to,
        "help": help,
        "options": [o.strip() for o in (options or "").split(",") if o.strip()],
        "show_in": list(show_in or ["detail"]),
        "messaging": bool(messaging),
    }
    try:
        added = custom.parse({"field": [{**e.__dict__} for e in existing] + [entry]})
    except custom.FieldError as exc:
        result.ok = False
        result.errors["field"] = "; ".join(f"{k}: {v}" for k, v in exc.errors.items())
        return result
    custom.write(data_dir, added)
    result.messages.append(f"Field {added[-1].key} added.")
    return result


def save_messaging_fields(data_dir: Path, size_field: str = "",
                          team_field: str = "") -> StepResult:
    """Which of your fields play the two roles the shipped playbook has wording for."""
    from . import fields as custom
    result = StepResult()
    data_dir = Path(data_dir)
    try:
        keys = {d.key for d in custom.load(data_dir) if d.applies_to == "company"}
    except custom.FieldError:
        keys = set()
    values = {}
    for name, value in (("messaging_size_field", size_field),
                        ("messaging_team_field", team_field)):
        value = (value or "").strip()
        if value and value not in keys:
            result.errors[name] = (f"No company field called {value!r}; add it under "
                                   "Fields first, or leave this empty.")
        values[name] = value
    if result.errors:
        result.ok = False
        return result
    result.values = values
    set_config_values(data_dir / "config.toml", values)
    result.messages.append("Drafts saved.")
    return result


def save_enrichment(data_dir: Path, provider: str, command: str = "", model: str = "",
                    timeout: str = "180", model_strong: str = "",
                    tier: str = "medium", account: str = "subscription") -> StepResult:
    """Write enrich_provider / _account / _command / _model / _model_strong / _timeout
    and ai_tier."""
    provider = (provider or "auto").strip().lower()
    account = (account or "subscription").strip().lower()
    result = StepResult()
    if account not in ENRICH_ACCOUNTS:
        result.errors["account"] = ("Account must be one of "
                                    + ", ".join(ENRICH_ACCOUNTS) + ".")
    if provider not in ENRICH_PROVIDERS:
        result.errors["provider"] = ("Unknown provider; use one of "
                                     + ", ".join(ENRICH_PROVIDERS) + ".")
    if provider == "custom" and not (command or "").strip():
        result.errors["command"] = "A custom provider needs a command line."
    tier = (tier or "medium").strip().lower()
    if tier not in AI_TIERS:
        result.errors["tier"] = "Model tier must be medium or strong."
    seconds = _positive_int(timeout, "timeout", "Timeout (seconds)", result.errors)
    if result.errors:
        result.ok = False
        return result
    result.values = {"enrich_provider": provider, "enrich_account": account,
                     "enrich_command": (command or "").strip(),
                     "enrich_model": (model or "").strip(),
                     "enrich_model_strong": (model_strong or "").strip(),
                     "ai_tier": tier, "enrich_timeout": seconds}
    set_config_values(Path(data_dir) / "config.toml", result.values)
    result.messages.append(f"Enrichment saved: provider {provider}.")
    return result


# --------------------------------------------------------------- Outcomes


def parse_outcomes(raw: str | list[str]) -> list[str]:
    """One outcome per line (or list item), stripped, empty lines dropped."""
    items = raw if isinstance(raw, (list, tuple)) else str(raw or "").splitlines()
    return [str(item).strip() for item in items if str(item).strip()]


def plan_outcomes(raw: str | list[str], message_window_days: str = "14",
                  silent_days: str = "14") -> StepResult:
    result = StepResult()
    outcomes = parse_outcomes(raw)
    if not outcomes:
        result.errors["outcomes"] = "Give at least one outcome, one per line."
    seen: set[str] = set()
    for item in outcomes:
        if item.lower() in seen:
            result.errors["outcomes"] = f"Duplicate outcome: {item}."
            break
        seen.add(item.lower())
    window = _positive_int(message_window_days, "message_window_days",
                           "Message window (days)", result.errors)
    silent = _positive_int(silent_days, "silent_days", "Silent after (days)", result.errors)
    if result.errors:
        result.ok = False
        return result
    result.values = {"outcomes": outcomes, "message_window_days": window,
                     "silent_days": silent}
    return result


def save_outcomes(data_dir: Path, raw: str | list[str], message_window_days: str = "14",
                  silent_days: str = "14") -> StepResult:
    """Write outcomes, message_window_days and silent_days to config.toml."""
    result = plan_outcomes(raw, message_window_days, silent_days)
    if result.ok:
        set_config_values(Path(data_dir) / "config.toml", result.values)
        result.messages.append("Outcomes saved: " + ", ".join(result.values["outcomes"]) + ".")
    return result


def save_task_types(data_dir: Path, types) -> None:
    """Write the task types (a list of task_types.TaskType) to config.toml."""
    from hermitcrm import task_types
    set_config_values(Path(data_dir) / "config.toml",
                      {"task_types": task_types.to_config(types)})


def save_theme(data_dir: Path, theme: str) -> StepResult:
    """Write theme (light, dark or system) to config.toml."""
    theme = (theme or "").strip().lower()
    result = StepResult()
    if theme not in THEMES:
        result.ok = False
        result.errors["theme"] = "Theme must be light, dark or system."
        return result
    result.values = {"theme": theme}
    set_config_values(Path(data_dir) / "config.toml", result.values)
    result.messages.append(f"Appearance saved: {theme}.")
    return result


# ------------------------------------------------------------------ state


def setup_state(data_dir: Path, config: dict | None = None, *, env: dict | None = None,
                runner=subprocess.run, platform: str | None = None,
                home: Path | None = None) -> dict[str, bool]:
    """Which steps are done: you, bcc, backup (the three), calendar and remote
    (both optional).

    backup is the local backup having run at least once; a git remote is an
    extra copy on top of it, not what makes the data safe.
    """
    data_dir = Path(data_dir)
    config = dict(DEFAULT_CONFIG, **(config if config is not None else load_config(data_dir)))
    you = bool(str(config.get("owner_email") or "").strip())
    settings = bcc.settings_from_config(config)
    bcc_done = bool(settings.address) and bool(secrets.get(
        "bcc_password", data_dir, config, account=settings.imap_user, env=env,
        runner=runner, platform=platform))
    remote = bool(remote_url(data_dir, str(config.get("remote") or "origin"), runner)) \
        and bool(config.get("push_enabled"))
    backup = bool(local_backup.load_state(data_dir).get("last_ok")) \
        and local_backup.backup_path(data_dir, config, home).exists()
    calendar = bool(secrets.get("calendar_ics_url", data_dir, config, env=env,
                                runner=runner, platform=platform))
    return {"you": you, "bcc": bcc_done, "backup": backup, "calendar": calendar,
            "remote": remote}


def pending(state: dict[str, bool]) -> bool:
    return not all(state.get(k) for k in ("you", "bcc", "backup"))
