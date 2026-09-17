"""`hermitcrm schedule install|remove|status`: a daily `sync --apply`, optionally a
long-running `serve`, via launchd (macOS), systemd user units (Linux) or a
printed schtasks command (Windows).

Every file write and command goes through seams (``home``, ``runner``,
``platform``, ``env``) so tests never touch the real LaunchAgents. Set
``HERMITCRM_DRY_SCHEDULE=1`` to write the files but run no launchctl/systemctl.

Reading plist values uses ``plutil -extract KEY json -o - FILE``: plutil
without ``-o`` rewrites the file in place.
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
LEGACY_LABELS = ("io.owncrm.sync", "io.owncrm.serve")  # before the rename
SYNC_UNIT = "hermitcrm-sync"
SERVE_UNIT = "hermitcrm-serve"
WIN_SYNC_TASK = r"Hermit CRM\sync"
WIN_SERVE_TASK = r"Hermit CRM\serve"
DRY_ENV = "HERMITCRM_DRY_SCHEDULE"


class ScheduleError(Exception):
    pass


def parse_time(value: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", (value or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ScheduleError(f"--at wants HH:MM (24h), got {value!r}")
    return int(m.group(1)), int(m.group(2))


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


# ----------------------------------------------------------------- Windows


def _win_cmd(args: list[str]) -> str:
    return " ".join(f'\\"{a}\\"' if " " in a else a for a in args)


def windows_commands(ctx: Context, hour: int, minute: int, serve: bool) -> list[str]:
    cmds = [f'schtasks /Create /F /SC DAILY /ST {hour:02d}:{minute:02d} /TN "{WIN_SYNC_TASK}" '
            f'/TR "{_win_cmd(ctx.sync_args())}"']
    if serve:
        cmds.append(f'schtasks /Create /F /SC ONLOGON /TN "{WIN_SERVE_TASK}" '
                    f'/TR "{_win_cmd(ctx.serve_args())}"')
    return cmds


# ---------------------------------------------------------------- commands


def install(ctx: Context, at: str = "07:00", serve: bool = False) -> list[str]:
    hour, minute = parse_time(at)
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
        if serve:
            files.append((agents_dir(ctx) / f"{SERVE_LABEL}.plist", serve_plist(ctx),
                          SERVE_LABEL))
        for path, data, label in files:
            path.write_bytes(data)
            lines.append(f"wrote {path}")
            _launchctl_load(ctx, path, label, lines)
        lines.append(f"sync runs daily at {hour:02d}:{minute:02d}; log: "
                     f"{logs_dir(ctx) / 'hermitcrm-sync.log'}")
    elif kind == "linux":
        units_dir(ctx).mkdir(parents=True, exist_ok=True)
        files = {f"{SYNC_UNIT}.service": sync_service(ctx),
                 f"{SYNC_UNIT}.timer": sync_timer(hour, minute)}
        if serve:
            files[f"{SERVE_UNIT}.service"] = serve_service(ctx)
        for name, text in files.items():
            (units_dir(ctx) / name).write_text(text, encoding="utf-8")
            lines.append(f"wrote {units_dir(ctx) / name}")
        ctx.run(["systemctl", "--user", "daemon-reload"], lines)
        enable = [f"{SYNC_UNIT}.timer"] + ([f"{SERVE_UNIT}.service"] if serve else [])
        for unit in enable:
            code = ctx.run(["systemctl", "--user", "enable", "--now", unit], lines)
            if not ctx.dry:
                lines.append(f"enabled {unit}" if code == 0 else f"could not enable {unit}")
        lines.append(f"sync runs daily at {hour:02d}:{minute:02d}; log: "
                     f"journalctl --user -u {SYNC_UNIT}")
    else:
        lines.append("Windows: run these in a terminal (Hermit CRM does not run them for you):")
        lines += windows_commands(ctx, hour, minute, serve)
    return lines


def remove(ctx: Context) -> list[str]:
    kind = _platform_kind(ctx.platform)
    lines: list[str] = []
    if kind == "mac":
        for label in (SYNC_LABEL, SERVE_LABEL, *LEGACY_LABELS):
            path = agents_dir(ctx) / f"{label}.plist"
            if not path.exists():
                continue
            if ctx.run(["launchctl", "bootout", f"gui/{ctx.uid}/{label}"], []) != 0:
                ctx.run(["launchctl", "unload", "-w", str(path)], [])
            path.unlink()
            lines.append(f"removed {path}")
    elif kind == "linux":
        for unit in (f"{SYNC_UNIT}.timer", f"{SERVE_UNIT}.service"):
            if (units_dir(ctx) / unit).exists():
                ctx.run(["systemctl", "--user", "disable", "--now", unit], lines)
        for name in (f"{SYNC_UNIT}.service", f"{SYNC_UNIT}.timer", f"{SERVE_UNIT}.service"):
            path = units_dir(ctx) / name
            if path.exists():
                path.unlink()
                lines.append(f"removed {path}")
        if lines:
            ctx.run(["systemctl", "--user", "daemon-reload"], lines)
    else:
        lines.append("Windows: run these in a terminal:")
        lines += [f'schtasks /Delete /F /TN "{WIN_SYNC_TASK}"',
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
    elsewhere: Path | None = None
    if kind == "mac":
        for label in (SYNC_LABEL, SERVE_LABEL):
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
            when = plist_value(ctx, path, "StartCalendarInterval") or {}
            at = (f" daily at {int(when.get('Hour', 0)):02d}:{int(when.get('Minute', 0)):02d}"
                  if when else "")
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
        serve = units_dir(ctx) / f"{SERVE_UNIT}.service"
        lines.append(f"{SERVE_UNIT}.service: {'installed' if serve.exists() else 'not installed'}")
    else:
        lines.append(f'Windows: check with: schtasks /Query /TN "{WIN_SYNC_TASK}"')
    return {"installed": installed, "elsewhere": elsewhere, "lines": lines}
