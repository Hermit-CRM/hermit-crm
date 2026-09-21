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

"""`hermitcrm schedule install|remove|status`: a daily `sync --apply`, a `backup`
every few minutes, optionally a long-running `serve`, via launchd (macOS), systemd user units (Linux) or a
printed schtasks command (Windows).

Every file write and command goes through seams (``home``, ``runner``,
``platform``, ``env``) so tests never touch the real LaunchAgents. Set
``HERMITCRM_DRY_SCHEDULE=1`` to write the files but run no launchctl/systemctl.

Reading plist values uses ``plutil -extract KEY json -o - FILE``: plutil
without ``-o`` rewrites the file in place.

systemd user units only outlive a login session when lingering is on
(``loginctl enable-linger``). Without it the timers stop at logout and do not
start at boot, while the unit files still look installed; ``install`` turns it
on (or says how) and ``status`` reports it, so ``doctor`` can warn.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import time
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SYNC_LABEL = "io.hermitcrm.sync"
SERVE_LABEL = "io.hermitcrm.serve"
BACKUP_LABEL = "io.hermitcrm.backup"
LEGACY_LABELS = ("io.owncrm.sync", "io.owncrm.serve")  # before the rename
SYNC_UNIT = "hermitcrm-sync"
SERVE_UNIT = "hermitcrm-serve"
BACKUP_UNIT = "hermitcrm-backup"
WIN_SYNC_TASK = r"Hermit CRM\sync"
WIN_SERVE_TASK = r"Hermit CRM\serve"
WIN_BACKUP_TASK = r"Hermit CRM\backup"
DRY_ENV = "HERMITCRM_DRY_SCHEDULE"
LINGER_DIR = Path("/var/lib/systemd/linger")  # one empty file per lingering user


class ScheduleError(Exception):
    pass


def parse_time(value: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", (value or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ScheduleError(f"--at wants HH:MM (24h), got {value!r}")
    return int(m.group(1)), int(m.group(2))


def parse_every(minutes) -> int:
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        value = 0
    if not 1 <= value <= 1440:
        raise ScheduleError(f"--backup-every wants minutes from 1 to 1440, got {minutes!r}")
    return value


def hermitcrm_executable(argv0: str | None = None, which=shutil.which) -> list[str]:
    """The absolute command that runs this hermitcrm."""
    argv0 = sys.argv[0] if argv0 is None else argv0
    if argv0:
        path = Path(argv0)
        if path.name.startswith("hermitcrm") and path.exists():
            return [str(path.resolve())]
    found = which("hermitcrm")
    if found:
        return [str(Path(found).resolve())]
    return [str(Path(sys.executable).resolve()), "-m", "hermitcrm.cli"]


@dataclass
class Context:
    data_dir: Path
    home: Path
    platform: str
    runner: object = subprocess.run
    env: dict | None = None
    exe: list[str] | None = None
    uid: int | None = None
    linger_dir: Path = LINGER_DIR

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir).expanduser().resolve()
        self.home = Path(self.home)
        self.env = dict(os.environ) if self.env is None else self.env
        self.exe = self.exe or hermitcrm_executable()
        if self.uid is None:
            self.uid = os.getuid() if hasattr(os, "getuid") else 0

    @property
    def dry(self) -> bool:
        return str(self.env.get(DRY_ENV, "")).strip() not in ("", "0")

    def run(self, argv: list[str], lines: list[str]) -> int:
        if self.dry:
            lines.append("dry run, not running: " + " ".join(argv))
            return 0
        try:
            proc = self.runner(argv, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            lines.append(f"{argv[0]} failed: {exc}")
            return -1
        return proc.returncode

    def sync_args(self) -> list[str]:
        return [*self.exe, "--data", str(self.data_dir), "sync", "--apply"]

    def serve_args(self) -> list[str]:
        return [*self.exe, "--data", str(self.data_dir), "serve"]

    def backup_args(self) -> list[str]:
        return [*self.exe, "--data", str(self.data_dir), "backup", "run", "--quiet"]


def _platform_kind(platform: str) -> str:
    if platform == "darwin":
        return "mac"
    if platform.startswith("win"):
        return "windows"
    return "linux"


# ------------------------------------------------------------------- macOS


def agents_dir(ctx: Context) -> Path:
    return ctx.home / "Library" / "LaunchAgents"


def logs_dir(ctx: Context) -> Path:
    return ctx.home / "Library" / "Logs"


# launchd and systemd start jobs with a bare PATH; the enrich CLIs (claude,
# codex, ...) usually live in one of these. hermitcrm/enrich.py searches them too.
JOB_PATH = "/usr/local/bin:/opt/homebrew/bin:~/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def job_path(ctx: Context) -> str:
    return JOB_PATH.replace("~", str(ctx.home))


def sync_plist(ctx: Context, hour: int, minute: int) -> bytes:
    log = str(logs_dir(ctx) / "hermitcrm-sync.log")
    return plistlib.dumps({
        "Label": SYNC_LABEL,
        "ProgramArguments": ctx.sync_args(),
        "EnvironmentVariables": {"PATH": job_path(ctx)},
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "WorkingDirectory": str(ctx.data_dir),
    }, sort_keys=True)


def serve_plist(ctx: Context) -> bytes:
    log = str(logs_dir(ctx) / "hermitcrm-serve.log")
    return plistlib.dumps({
        "Label": SERVE_LABEL,
        "ProgramArguments": ctx.serve_args(),
        "EnvironmentVariables": {"PATH": job_path(ctx)},
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "WorkingDirectory": str(ctx.data_dir),
    }, sort_keys=True)


def backup_plist(ctx: Context, every: int) -> bytes:
    log = str(logs_dir(ctx) / "hermitcrm-backup.log")
    return plistlib.dumps({
        "Label": BACKUP_LABEL,
        "ProgramArguments": ctx.backup_args(),
        "EnvironmentVariables": {"PATH": job_path(ctx)},
        "StartInterval": every * 60,
        "RunAtLoad": True,
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "WorkingDirectory": str(ctx.data_dir),
    }, sort_keys=True)


def _launchctl_load(ctx: Context, path: Path, label: str, lines: list[str]) -> None:
    domain = f"gui/{ctx.uid}"
    ctx.run(["launchctl", "bootout", f"{domain}/{label}"], [])  # ignore: may not be loaded
    # bootout returns before the job is gone; a bootstrap right after it fails
    # with "Input/output error" and the load -w fallback then silently does
    # nothing. Retry a few times.
    for attempt in range(4):
        if ctx.run(["launchctl", "bootstrap", domain, str(path)], lines) == 0:
            if not ctx.dry:
                lines.append(f"loaded {label}")
            return
        if ctx.dry:
            break
        time.sleep(0.5 * (attempt + 1))
    if ctx.run(["launchctl", "load", "-w", str(path)], lines) == 0:
        lines.append(f"loaded {label} (launchctl load -w)")
    else:
        lines.append(f"could not load {label}; try: launchctl bootstrap {domain} {path}")


def job_data_dir(args) -> Path | None:
    """The data folder an installed job serves, read from its own `--data DIR`.

    One machine has one `io.hermitcrm.sync`, so a job installed for another
    folder is the reason `status` can find a plist that has nothing to do with
    the folder being asked about.
    """
    args = [str(a) for a in (args or [])]
    for i, arg in enumerate(args):
        if arg == "--data" and i + 1 < len(args):
            return Path(args[i + 1]).expanduser().resolve()
        if arg.startswith("--data="):
            return Path(arg.split("=", 1)[1]).expanduser().resolve()
    return None


def plist_value(ctx: Context, path: Path, key: str):
    """Read one plist key without modifying the file (note the ``-o -``)."""
    try:
        proc = ctx.runner(["plutil", "-extract", key, "json", "-o", "-", str(path)],
                          capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            return json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    try:
        with open(path, "rb") as fh:
            return plistlib.load(fh).get(key)
    except (OSError, plistlib.InvalidFileException):
        return None


# ------------------------------------------------------------------- Linux


def units_dir(ctx: Context) -> Path:
    return ctx.home / ".config" / "systemd" / "user"


def _exec_line(args: list[str]) -> str:
    return " ".join(f'"{a}"' if re.search(r'[\s"\\]', a) else a
                    for a in (x.replace("\\", "\\\\").replace('"', '\\"') for x in args))


def unit_data_dir(path: Path) -> Path | None:
    """The data folder a systemd unit serves, from its WorkingDirectory."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^WorkingDirectory=(.*)$", text, re.M)
    return Path(m.group(1).strip()).expanduser().resolve() if m else None


def sync_service(ctx: Context) -> str:
    return ("[Unit]\nDescription=Hermit CRM daily sync (BCC and calendar import)\n\n"
            "[Service]\nType=oneshot\n"
            f"WorkingDirectory={ctx.data_dir}\n"
            f"Environment=PATH={job_path(ctx)}\n"
            f"ExecStart={_exec_line(ctx.sync_args())}\n")


def sync_timer(hour: int, minute: int) -> str:
    return ("[Unit]\nDescription=Run Hermit CRM sync daily\n\n"
            f"[Timer]\nOnCalendar=*-*-* {hour:02d}:{minute:02d}:00\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n")


def serve_service(ctx: Context) -> str:
    return ("[Unit]\nDescription=Hermit CRM web app on 127.0.0.1\n\n"
            f"[Service]\nWorkingDirectory={ctx.data_dir}\n"
            f"Environment=PATH={job_path(ctx)}\n"
            f"ExecStart={_exec_line(ctx.serve_args())}\nRestart=always\nRestartSec=5\n\n"
            "[Install]\nWantedBy=default.target\n")


def backup_service(ctx: Context) -> str:
    return ("[Unit]\nDescription=Hermit CRM backup (a repository that only grows)\n\n"
            "[Service]\nType=oneshot\n"
            f"WorkingDirectory={ctx.data_dir}\n"
            f"Environment=PATH={job_path(ctx)}\n"
            f"ExecStart={_exec_line(ctx.backup_args())}\n")


def _user_name(ctx: Context) -> str:
    name = ctx.env.get("USER") or ctx.env.get("LOGNAME")
    if not name:
        try:
            import pwd

            name = pwd.getpwuid(ctx.uid).pw_name
        except (ImportError, KeyError):
            name = ""
    return name


def linger_enabled(ctx: Context) -> bool | None:
    """Whether systemd keeps this user's units running with nobody logged in.

    None when it cannot be told. `loginctl show-user` fails for a user with no
    session and no lingering (the very case that matters), so the file logind
    itself reads is the fallback.
    """
    try:
        proc = ctx.runner(["loginctl", "show-user", str(ctx.uid), "--property=Linger",
                           "--value"], capture_output=True, text=True, timeout=10)
        value = (proc.stdout or "").strip().lower() if proc.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        value = ""
    if value in ("yes", "no"):
        return value == "yes"
    name = _user_name(ctx)
    if name and (ctx.linger_dir / name).exists():
        return True
    if name and ctx.linger_dir.is_dir():
        return False
    return None


def _enable_linger(ctx: Context, lines: list[str]) -> None:
    fix = f"sudo loginctl enable-linger {_user_name(ctx) or '$USER'}"
    if ctx.dry:
        ctx.run(["loginctl", "--no-ask-password", "enable-linger"], lines)
        return
    if linger_enabled(ctx):
        lines.append("lingering is on: the jobs run while you are logged out and after a reboot")
        return
    # Allowed without a password for your own active session on most distros;
    # --no-ask-password keeps polkit from prompting inside a captured subprocess.
    ctx.run(["loginctl", "--no-ask-password", "enable-linger"], lines)
    if linger_enabled(ctx):
        lines.append("turned on lingering (loginctl enable-linger): the jobs run while you "
                     "are logged out and after a reboot")
    else:
        lines.append("WARNING: lingering is off, so these jobs stop when you log out and do "
                     f"not start at boot. Run: {fix}")


def backup_timer(every: int) -> str:
    return ("[Unit]\nDescription=Run Hermit CRM backup every few minutes\n\n"
            f"[Timer]\nOnBootSec=2min\nOnUnitActiveSec={every}min\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n")


# ----------------------------------------------------------------- Windows


def _win_cmd(args: list[str]) -> str:
    return " ".join(f'\\"{a}\\"' if " " in a else a for a in args)


def windows_commands(ctx: Context, hour: int, minute: int, serve: bool,
                     backup_every: int | None = None) -> list[str]:
    cmds = [f'schtasks /Create /F /SC DAILY /ST {hour:02d}:{minute:02d} /TN "{WIN_SYNC_TASK}" '
            f'/TR "{_win_cmd(ctx.sync_args())}"']
    if backup_every:
        cmds.append(f'schtasks /Create /F /SC MINUTE /MO {backup_every} /TN "{WIN_BACKUP_TASK}" '
                    f'/TR "{_win_cmd(ctx.backup_args())}"')
    if serve:
        cmds.append(f'schtasks /Create /F /SC ONLOGON /TN "{WIN_SERVE_TASK}" '
                    f'/TR "{_win_cmd(ctx.serve_args())}"')
    return cmds


# ---------------------------------------------------------------- commands


def install(ctx: Context, at: str = "07:00", serve: bool = False, backup: bool = True,
            backup_every: int = 5) -> list[str]:
    hour, minute = parse_time(at)
    every = parse_every(backup_every) if backup else None
    kind = _platform_kind(ctx.platform)
    lines: list[str] = []
    if kind == "mac":
        agents_dir(ctx).mkdir(parents=True, exist_ok=True)
        logs_dir(ctx).mkdir(parents=True, exist_ok=True)
        for label in LEGACY_LABELS:  # jobs installed before the rename
            legacy = agents_dir(ctx) / f"{label}.plist"
            if legacy.exists():
                ctx.run(["launchctl", "bootout", f"gui/{ctx.uid}/{label}"], [])
                legacy.unlink()
                lines.append(f"removed {legacy}")
        files = [(agents_dir(ctx) / f"{SYNC_LABEL}.plist", sync_plist(ctx, hour, minute),
                  SYNC_LABEL)]
        if every:
            files.append((agents_dir(ctx) / f"{BACKUP_LABEL}.plist", backup_plist(ctx, every),
                          BACKUP_LABEL))
        if serve:
            files.append((agents_dir(ctx) / f"{SERVE_LABEL}.plist", serve_plist(ctx),
                          SERVE_LABEL))
        for path, data, label in files:
            path.write_bytes(data)
            lines.append(f"wrote {path}")
            _launchctl_load(ctx, path, label, lines)
        lines.append(f"sync runs daily at {hour:02d}:{minute:02d}; log: "
                     f"{logs_dir(ctx) / 'hermitcrm-sync.log'}")
        if every:
            lines.append(f"backup runs every {every} min; log: "
                         f"{logs_dir(ctx) / 'hermitcrm-backup.log'}")
    elif kind == "linux":
        units_dir(ctx).mkdir(parents=True, exist_ok=True)
        files = {f"{SYNC_UNIT}.service": sync_service(ctx),
                 f"{SYNC_UNIT}.timer": sync_timer(hour, minute)}
        if every:
            files[f"{BACKUP_UNIT}.service"] = backup_service(ctx)
            files[f"{BACKUP_UNIT}.timer"] = backup_timer(every)
        if serve:
            files[f"{SERVE_UNIT}.service"] = serve_service(ctx)
        for name, text in files.items():
            (units_dir(ctx) / name).write_text(text, encoding="utf-8")
            lines.append(f"wrote {units_dir(ctx) / name}")
        ctx.run(["systemctl", "--user", "daemon-reload"], lines)
        enable = ([f"{SYNC_UNIT}.timer"] + ([f"{BACKUP_UNIT}.timer"] if every else [])
                  + ([f"{SERVE_UNIT}.service"] if serve else []))
        for unit in enable:
            code = ctx.run(["systemctl", "--user", "enable", "--now", unit], lines)
            if not ctx.dry:
                lines.append(f"enabled {unit}" if code == 0 else f"could not enable {unit}")
        _enable_linger(ctx, lines)
        lines.append(f"sync runs daily at {hour:02d}:{minute:02d}; log: "
                     f"journalctl --user -u {SYNC_UNIT}")
        if every:
            lines.append(f"backup runs every {every} min; log: "
                         f"journalctl --user -u {BACKUP_UNIT}")
    else:
        lines.append("Windows: run these in a terminal (Hermit CRM does not run them for you):")
        lines += windows_commands(ctx, hour, minute, serve, every)
    return lines


def remove(ctx: Context) -> list[str]:
    kind = _platform_kind(ctx.platform)
    lines: list[str] = []
    if kind == "mac":
        for label in (SYNC_LABEL, BACKUP_LABEL, SERVE_LABEL, *LEGACY_LABELS):
            path = agents_dir(ctx) / f"{label}.plist"
            if not path.exists():
                continue
            if ctx.run(["launchctl", "bootout", f"gui/{ctx.uid}/{label}"], []) != 0:
                ctx.run(["launchctl", "unload", "-w", str(path)], [])
            path.unlink()
            lines.append(f"removed {path}")
    elif kind == "linux":
        for unit in (f"{SYNC_UNIT}.timer", f"{BACKUP_UNIT}.timer", f"{SERVE_UNIT}.service"):
            if (units_dir(ctx) / unit).exists():
                ctx.run(["systemctl", "--user", "disable", "--now", unit], lines)
        for name in (f"{SYNC_UNIT}.service", f"{SYNC_UNIT}.timer", f"{BACKUP_UNIT}.service",
                     f"{BACKUP_UNIT}.timer", f"{SERVE_UNIT}.service"):
            path = units_dir(ctx) / name
            if path.exists():
                path.unlink()
                lines.append(f"removed {path}")
        if lines:
            ctx.run(["systemctl", "--user", "daemon-reload"], lines)
    else:
        lines.append("Windows: run these in a terminal:")
        lines += [f'schtasks /Delete /F /TN "{WIN_SYNC_TASK}"',
                  f'schtasks /Delete /F /TN "{WIN_BACKUP_TASK}"',
                  f'schtasks /Delete /F /TN "{WIN_SERVE_TASK}"']
    return lines or ["nothing installed"]


def status(ctx: Context) -> dict:
    """{'installed': bool, 'elsewhere': Path|None, 'lines': [...]}.

    `installed` means a daily sync is scheduled *for this data folder*. A job
    installed for a different folder leaves `installed` False and names that
    folder in `elsewhere`: the machine has one sync slot, so the two facts are
    not the same question, and answering the first with the second is how
    `doctor` used to call a folder scheduled that was not.
    """
    kind = _platform_kind(ctx.platform)
    lines: list[str] = []
    installed = False
    backup_installed = False
    elsewhere: Path | None = None
    linger: bool | None = None
    if kind == "mac":
        for label in (SYNC_LABEL, BACKUP_LABEL, SERVE_LABEL):
            path = agents_dir(ctx) / f"{label}.plist"
            if not path.exists():
                lines.append(f"{label}: not installed")
                continue
            args = plist_value(ctx, path, "ProgramArguments") or []
            folder = job_data_dir(args)
            other = folder if folder is not None and folder != ctx.data_dir else None
            if label == SYNC_LABEL:
                installed = other is None
                elsewhere = other
            if label == BACKUP_LABEL:
                backup_installed = other is None
            if label == BACKUP_LABEL:
                interval = plist_value(ctx, path, "StartInterval")
                at = f" every {int(interval) // 60} min" if interval else ""
            else:
                when = plist_value(ctx, path, "StartCalendarInterval") or {}
                at = (f" daily at {int(when.get('Hour', 0)):02d}:"
                      f"{int(when.get('Minute', 0)):02d}" if when else "")
            loaded = ""
            if not ctx.dry:
                code = ctx.run(["launchctl", "print", f"gui/{ctx.uid}/{label}"], [])
                loaded = ", loaded" if code == 0 else ", not loaded"
            whose = f", for {other}" if other else ""
            lines.append(f"{label}: installed{at}{loaded}{whose}: {' '.join(map(str, args))}")
    elif kind == "linux":
        timer = units_dir(ctx) / f"{SYNC_UNIT}.timer"
        if timer.exists():
            folder = unit_data_dir(units_dir(ctx) / f"{SYNC_UNIT}.service")
            elsewhere = folder if folder is not None and folder != ctx.data_dir else None
            installed = elsewhere is None
            m = re.search(r"^OnCalendar=(.*)$", timer.read_text(encoding="utf-8"), re.M)
            whose = f", for {elsewhere}" if elsewhere else ""
            lines.append(f"{SYNC_UNIT}.timer: installed ({m.group(1) if m else '?'}){whose}")
        else:
            lines.append(f"{SYNC_UNIT}.timer: not installed")
        btimer = units_dir(ctx) / f"{BACKUP_UNIT}.timer"
        if btimer.exists():
            folder = unit_data_dir(units_dir(ctx) / f"{BACKUP_UNIT}.service")
            other = folder if folder is not None and folder != ctx.data_dir else None
            backup_installed = other is None
            m = re.search(r"^OnUnitActiveSec=(.*)$", btimer.read_text(encoding="utf-8"), re.M)
            whose = f", for {other}" if other else ""
            lines.append(f"{BACKUP_UNIT}.timer: installed (every {m.group(1) if m else '?'})"
                         f"{whose}")
        else:
            lines.append(f"{BACKUP_UNIT}.timer: not installed")
        serve = units_dir(ctx) / f"{SERVE_UNIT}.service"
        lines.append(f"{SERVE_UNIT}.service: {'installed' if serve.exists() else 'not installed'}")
        if timer.exists() or btimer.exists() or serve.exists():
            linger = None if ctx.dry else linger_enabled(ctx)
            lines.append("lingering: " + {True: "on", None: "unknown (loginctl show-user)",
                                          False: "off; the jobs stop when you log out, run: "
                                                 "sudo loginctl enable-linger $USER"}[linger])
    else:
        lines.append(f'Windows: check with: schtasks /Query /TN "{WIN_SYNC_TASK}" and '
                     f'/TN "{WIN_BACKUP_TASK}"')
    return {"installed": installed, "backup_installed": backup_installed,
            "elsewhere": elsewhere, "linger": linger, "lines": lines}
