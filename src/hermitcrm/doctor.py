"""`hermitcrm doctor`: one line per check (ok / warn / fail); exit 1 on any fail.

Every outside dependency is a seam (``which``, ``runner``, ``env``, ``platform``,
``home``, ``open_mailbox``, ``update_fetcher``, ``enricher``) so tests stay
offline. Secrets are only checked for presence, never printed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import __version__, backup, bcc, migrations, schedule, secrets, updates
from . import setup as setup_steps
from .datafolder import is_data_folder
from .enrich import Enricher
from .store import DEFAULT_CONFIG

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    name: str
    status: str
    detail: str

    def line(self) -> str:
        return f"{self.status:<4}  {self.name}: {self.detail}"


def _git(root: Path, args: list[str], runner) -> tuple[int, str]:
    try:
        proc = runner(["git", *args], cwd=root, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)
    return proc.returncode, (proc.stdout or "").strip()


def run_checks(root: Path, *, online: bool = False, env: dict | None = None,
               which=shutil.which, runner=subprocess.run, platform: str | None = None,
               home: Path | None = None, python: tuple = tuple(sys.version_info[:3]),
               open_mailbox=None, update_fetcher=None, update_cache: Path | None = None,
               enricher: Enricher | None = None) -> list[Check]:
    import os

    root = Path(root)
    env = dict(os.environ) if env is None else env
    platform = platform or sys.platform
    checks: list[Check] = []
    add = lambda name, status, detail: checks.append(Check(name, status, detail))  # noqa: E731

    version = ".".join(str(p) for p in python[:3])
    add("python", OK if tuple(python[:2]) >= (3, 11) else FAIL,
        version if tuple(python[:2]) >= (3, 11) else f"{version}; Hermit CRM needs 3.11 or newer")
    git = which("git")
    add("git", OK if git else FAIL, git or "git is not on PATH")

    if not is_data_folder(root):
        add("data folder", FAIL, f"{root} is not a Hermit CRM data folder (hermitcrm init DIR)")
        return checks
    add("data folder", OK, str(root))

    try:
        current = migrations.current_format(root)
        if current > migrations.LATEST:
            add("data format", FAIL, f"format {current} is newer than this Hermit CRM "
                f"({migrations.LATEST}); upgrade Hermit CRM")
        else:
            todo = migrations.pending(root)
            add("data format", WARN if todo else OK,
                f"{len(todo)} migration(s) pending; run hermitcrm migrate" if todo
                else f"format {current} is current")
    except Exception as exc:
        add("data format", FAIL, f"{type(exc).__name__}: {exc}")

    config = dict(DEFAULT_CONFIG)
    path = root / "config.toml"
    try:
        with open(path, "rb") as fh:
            config.update(tomllib.load(fh))
        add("config", OK, "config.toml parses")
    except (OSError, tomllib.TOMLDecodeError) as exc:
        add("config", FAIL, f"config.toml: {exc}")

    owner = str(config.get("owner_email") or "")
    add("owner_email", OK if owner else WARN, owner or "not set; run hermitcrm setup")

    settings = bcc.settings_from_config(config)
    if not settings.address:
        add("bcc password", WARN, "BCC capture not set up (optional); run hermitcrm setup")
    else:
        found = secrets.get("bcc_password", root, config, account=settings.imap_user,
                            env=env, runner=runner, platform=platform)
        add("bcc password", OK if found else FAIL,
            "found (not shown)" if found else
            f"no app password for {settings.imap_user}; run hermitcrm setup")

    if not online:
        add("imap login", OK, "not checked; add --online")
    elif not settings.address:
        add("imap login", WARN, "skipped: BCC capture not set up")
    else:
        try:
            opener = open_mailbox or (lambda: bcc.open_gmail(settings, root, runner))
            with opener():
                pass
            add("imap login", OK, f"{settings.imap_user} on {settings.imap_host}")
        except Exception as exc:
            message = str(exc) if isinstance(exc, bcc.BccError) else f"{type(exc).__name__}: {exc}"
            hint = setup_steps.login_hint(message, settings.imap_host)
            add("imap login", FAIL, message + (f" Hint: {hint}" if hint else ""))

    calendar = secrets.get("calendar_ics_url", root, config, env=env, runner=runner,
                           platform=platform)
    add("calendar url", OK if calendar else WARN,
        "found (not shown)" if calendar else "not set up (optional)")

    state: dict = {}
    try:
        ctx = schedule.Context(data_dir=root, home=home or Path.home(), platform=platform,
                               runner=runner, env=env)
        state = schedule.status(ctx)
        if state["installed"]:
            add("schedule", OK, "; ".join(state["lines"][:1]))
        elif state.get("elsewhere"):
            add("schedule", WARN,
                f"the daily sync is scheduled for {state['elsewhere']}, not this folder; "
                "a machine has one schedule, and hermitcrm schedule install takes it over")
        else:
            add("schedule", WARN, "daily sync not scheduled; run hermitcrm schedule install")
    except Exception as exc:
        add("schedule", WARN, f"could not check: {exc}")

    try:
        found = backup.status(root, config, home=home)
        job = bool(state.get("backup_installed"))
        if found["level"] != "ok":
            add("backup", WARN, found["summary"] + "; see hermitcrm help backups")
        elif not job:
            add("backup", WARN, f"{found['summary']}, but no job runs it; "
                "run hermitcrm schedule install")
        else:
            add("backup", OK, found["summary"])
    except Exception as exc:
        add("backup", WARN, f"could not check: {exc}")

    remote = str(config.get("remote") or "origin")
    url = setup_steps.remote_url(root, remote, runner)
    if not url:
        add("git remote", WARN, f"no remote {remote!r}: no copy off this machine; run hermitcrm setup")
    else:
        code, when = _git(root, ["log", "-1", "-g", "--format=%cd", "--date=iso",
                                 f"refs/remotes/{remote}/main"], runner)
        if code != 0 or not when:
            add("git remote", WARN, f"{remote} exists but was never pushed")
        else:
            _, ahead = _git(root, ["rev-list", "--count", f"{remote}/main..HEAD"], runner)
            behind = f", {ahead} commit(s) not pushed" if ahead not in ("", "0") else ""
            off = "" if config.get("push_enabled") else " (push_enabled is off)"
            add("git remote", WARN if behind or off else OK,
                f"{remote} last pushed {when}{behind}{off}")

    try:
        enr = enricher or Enricher(provider=str(config.get("enrich_provider", "auto")),
                                   command=str(config.get("enrich_command", "")),
                                   model=str(config.get("enrich_model", "")))
        if enr.available:
            add("enrich cli", OK, enr.provider_name)
        else:
            add("enrich cli", WARN, f"unavailable (optional): {enr.unavailable_reason()}")
    except Exception as exc:
        add("enrich cli", WARN, f"could not check: {exc}")

    # Only a genuinely newer version is a warning. A 404 or an unreachable index is
    # reported as what it is; what doctor must never do is answer "is the latest"
    # for a check that never got an answer.
    result = updates.look(config, fetcher=update_fetcher, cache=update_cache, env=env)
    add("update", WARN if result.state == updates.NEWER else OK, result.sentence())
    return checks


def report(checks: list[Check]) -> tuple[str, int]:
    code = 1 if any(c.status == FAIL for c in checks) else 0
    return "\n".join(c.line() for c in checks), code
