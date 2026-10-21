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

"""One-click upgrade: install the newest release, then restart this server on it.

Spec: docs/superpowers/specs/2026-10-20-one-click-upgrade-design.md. Three steps,
each of which can stop the whole thing without leaving the app worse off:

1. **install** -- the fixed command from ``updates.upgrade_argv`` (uv, pipx or pip),
   run without a shell.
2. **verify** -- start the *new* files in a child process and ask for their
   version. A broken release must not reach the restart, because under launchd's
   ``KeepAlive`` a server that dies on start is restarted into the same death.
3. **restart** -- the web app is asked to shut down gracefully and ``cmd_serve``
   then replaces itself with the same command line (``os.execv``). Same PID, so
   launchd, systemd and a terminal all see one unbroken process, and a server
   nobody supervises comes back too.

Why this exists: files replaced under a running server are read by old code. A
template that wants a value the old Python never supplies breaks every page, and
no browser reload helps. So while a step runs, :func:`upgrading_page` answers
instead of the app, and the pages that explain or fix the situation here are
built from strings, not templates: the failure they handle is "templates and
code disagree".

This is the one module that starts installers and replaces the process, so it is
kept small. Nothing from the network or from a request is ever put into a
command.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from secrets import token_urlsafe
from typing import Callable, NamedTuple

from . import __version__, updates

LOOPBACK = ("127.0.0.1", "localhost", "::1")
# launchd and systemd start jobs with a bare PATH; the installers usually live in
# one of these (schedule.JOB_PATH is the same idea).
EXTRA_PATH = ("~/.local/bin", "~/.cargo/bin", "/opt/homebrew/bin", "/usr/local/bin")
INSTALL_TIMEOUT = 600
VERIFY_TIMEOUT = 60
GRACE_SECONDS = 10  # how long in-flight requests get to finish before the restart

IDLE = "idle"
INSTALLING = "installing"
VERIFYING = "verifying"
RESTARTING = "restarting"
FAILED = "failed"
BUSY = (INSTALLING, VERIFYING, RESTARTING)

DETAIL = {
    IDLE: "",
    INSTALLING: "Downloading and installing the new version...",
    VERIFYING: "Checking that the new version starts...",
    RESTARTING: "Restarting Hermit CRM...",
}


class Plan(NamedTuple):
    """What a click would run. Empty ``argv`` means it cannot, and ``why_not`` says why."""

    argv: tuple[str, ...] = ()
    why_not: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.argv)


def search_path(environ: dict | None = None) -> str:
    """PATH with the places installers live added on, for a job that started bare."""
    env = os.environ if environ is None else environ
    parts = [p for p in str(env.get("PATH", "")).split(os.pathsep) if p]
    for extra in EXTRA_PATH:
        path = str(Path(extra).expanduser())
        if path not in parts:
            parts.append(path)
    return os.pathsep.join(parts)


def blocked(config: dict, can_restart: bool, platform: str | None = None) -> str:
    """Why a click cannot restart this server, in words for the page; '' when it can."""
    if (platform or sys.platform).startswith("win"):
        return "One-click upgrade is not available on Windows yet."
    if not can_restart:
        return ("This server was not started by `hermitcrm serve`, so it cannot restart "
                "itself.")
    if str(config.get("host") or "127.0.0.1").strip().lower() not in LOOPBACK:
        return ("This server can be reached from the network and Hermit CRM has no "
                "password, so it will not upgrade itself on a click. Upgrade it on the "
                "computer it runs on.")
    return ""


def install_plan(config: dict, can_restart: bool, prefix: str | Path | None = None,
                 platform: str | None = None, which: Callable[..., str | None] = shutil.which,
                 environ: dict | None = None, in_venv: bool | None = None) -> Plan:
    """The install command to run on a click, or the reason there is none."""
    why = blocked(config, can_restart, platform)
    if why:
        return Plan(why_not=why)
    url = updates.source_url(config)
    if updates.host_of(url) != "pypi.org":
        return Plan(why_not=f"Your update source is {updates.host_of(url)}, not PyPI. "
                            f"Download the new version from there.")
    words = updates.upgrade_argv(prefix)
    if words[0] == "pip":
        if in_venv is None:
            in_venv = sys.prefix != sys.base_prefix
        if not in_venv:  # never rewrite the system Python from a web page
            return Plan(why_not="Hermit CRM is installed in the system Python. Run "
                                f"`{' '.join(words)}` yourself.")
        return Plan((sys.executable, "-m", *words))
    program = which(words[0], path=search_path(environ))
    if not program:
        return Plan(why_not=f"`{words[0]}` was not found. Run `{' '.join(words)}` yourself.")
    return Plan((program, *words[1:]))


def previous_version_command(version: str, prefix: str | Path | None = None) -> str:
    """The command that puts the running version back (the package name is last)."""
    return " ".join([*updates.upgrade_argv(prefix)[:-1], f"hermitcrm=={version}"])


def restart_argv(orig_argv: list[str] | None = None, executable: str | None = None) -> list[str]:
    """This process's own command line, with the interpreter spelled out in full."""
    return [executable or sys.executable, *(sys.orig_argv if orig_argv is None else orig_argv)[1:]]


def exec_restart(execv: Callable[[str, list[str]], None] = os.execv,
                 argv: list[str] | None = None) -> None:
    """Replace this process by itself, reading the code on disk as it is now."""
    argv = argv or restart_argv()
    execv(argv[0], argv)


def _tail(text: str, limit: int = 500) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "..." + text[-limit:]


class Upgrader:
    """One upgrade at a time, run in a thread, observable from the status endpoint."""

    def __init__(self, run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                 version: str = __version__, python: str | None = None,
                 prefix: str | Path | None = None) -> None:
        self._run = run
        self.version = version
        self.python = python or sys.executable
        self.prefix = prefix
        self.boot = token_urlsafe(8)  # changes with every process: tabs compare it
        self.state = IDLE
        self.target = ""
        self.error = ""
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        return self.state in BUSY

    def status(self) -> dict:
        return {"boot": self.boot, "version": self.version, "state": self.state,
                "target": self.target, "detail": DETAIL.get(self.state, ""),
                "error": self.error}

    def start(self, plan: Plan | None, restart: Callable[[], bool],
              target: str = "") -> threading.Thread | None:
        """Begin; None when one is already running. No plan = verify and restart only."""
        with self._lock:
            if self.busy:
                return None
            self.state = INSTALLING if plan else VERIFYING
            self.target, self.error = target, ""
        thread = threading.Thread(target=self._work, args=(plan, restart),
                                  name="hermitcrm-upgrade", daemon=True)
        thread.start()
        return thread

    # -- the steps ------------------------------------------------------------------

    def _work(self, plan: Plan | None, restart: Callable[[], bool]) -> None:
        try:
            if plan:
                problem = self._install(plan)
                if problem:
                    return self._fail(problem)
                self.state = VERIFYING
            problem = self._verify()
            if problem:
                return self._fail(problem)
            self.state = RESTARTING
            if not restart():
                self._fail("This server cannot restart itself. Restart it by hand.")
        except Exception as exc:  # a thread must never die without saying so
            self._fail(f"{type(exc).__name__}: {exc}")

    def _fail(self, message: str) -> None:
        self.error, self.state = message, FAILED

    def _child(self, argv: list[str], timeout: int) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PATH"] = search_path(env)
        # A neutral folder: an installer reads uv.toml and friends from where it runs,
        # and this process runs inside the user's data folder.
        return self._run(argv, capture_output=True, text=True, timeout=timeout, env=env,
                         stdin=subprocess.DEVNULL, cwd=tempfile.gettempdir())

    def _install(self, plan: Plan) -> str:
        try:
            done = self._child(list(plan.argv), INSTALL_TIMEOUT)
        except subprocess.TimeoutExpired:
            return (f"The install did not finish in {INSTALL_TIMEOUT // 60} minutes. "
                    f"Hermit CRM is still running v{self.version}.")
        except OSError as exc:
            return f"Could not run the installer: {exc}"
        if done.returncode != 0:
            return (f"The install failed (exit {done.returncode}): "
                    f"{_tail(done.stderr or done.stdout)} Hermit CRM is still running "
                    f"v{self.version}.")
        return ""

    def _verify(self) -> str:
        undo = previous_version_command(self.version, self.prefix)
        try:
            done = self._child([self.python, "-I", "-m", "hermitcrm.cli", "--version"],
                               VERIFY_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"The new version could not be started ({exc}). To go back: {undo}"
        if done.returncode != 0:
            return (f"The new version does not start: {_tail(done.stderr or done.stdout)} "
                    f"Hermit CRM was left running. To go back: {undo}")
        found = re.search(r"hermitcrm\s+v?(\d+(?:\.\d+)+\S*)", done.stdout or "")
        if not found:
            return f"Could not read the new version from its answer. To go back: {undo}"
        if not updates.is_newer(found.group(1), self.version):
            return (f"The files on disk are v{found.group(1)}, which is not newer than "
                    f"the v{self.version} running. Nothing was restarted.")
        self.target = found.group(1)
        return ""


# -- pages built from strings, so they work when the templates do not ------------------

_STYLE = (
    "body{font:16px/1.5 system-ui,sans-serif;margin:0;min-height:100vh;display:grid;"
    "place-items:center;background:#f6f5f2;color:#1d1d1b}"
    "main{max-width:34rem;margin:1rem;padding:1.5rem 1.75rem;background:#fff;"
    "border:1px solid #d9d6cf;border-radius:10px}"
    "h1{font-size:1.25rem;margin:0 0 .75rem}p{margin:.5rem 0}"
    "button{font:inherit;padding:.5rem 1rem;border-radius:6px;border:1px solid #1d1d1b;"
    "background:#1d1d1b;color:#fff;cursor:pointer}"
    "code{background:#eeece7;padding:.1rem .3rem;border-radius:4px}"
    "@media(prefers-color-scheme:dark){body{background:#161615;color:#ecebe7}"
    "main{background:#1f1f1d;border-color:#3a3935}button{background:#ecebe7;color:#161615;"
    "border-color:#ecebe7}code{background:#2c2b28}}"
)


def notice_page(title: str, paragraphs: list[str], refresh: int = 0,
                form: tuple[str, str, str] | None = None, back: bool = False) -> str:
    """A small self-contained page. ``form`` is (action, csrf token, button label)."""
    esc = html.escape
    again = f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else ""
    body = "".join(f"<p>{esc(p)}</p>" for p in paragraphs)
    if form:
        action, token, label = form
        body += (f'<form method="post" action="{esc(action, quote=True)}">'
                 f'<input type="hidden" name="csrf_token" value="{esc(token, quote=True)}">'
                 f"<p><button type=\"submit\">{esc(label)}</button></p></form>")
    if back:
        body += '<p><a href="/">Back to Hermit CRM</a></p>'
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"{again}<title>{esc(title)}</title><style>{_STYLE}</style></head>"
            f"<body><main><h1>{esc(title)}</h1>{body}</main></body></html>")


def upgrading_page(status: dict) -> str:
    return notice_page("Hermit CRM is upgrading",
                       [status.get("detail") or "Working...",
                        "This page reloads itself. Your data is not touched."], refresh=2)


def stale_page(running: str, on_disk: str, token: str, why_not: str = "") -> str:
    """What a visitor sees when a page broke because the files are newer than the server."""
    lines = [f"Hermit CRM was upgraded to v{on_disk} while this server was still running "
             f"v{running}. The files and the running program no longer match, which is why "
             "this page broke. Your data is fine.",
             why_not or "Restarting loads the new version and fixes it."]
    return notice_page("Restart needed", lines,
                       form=None if why_not else ("/upgrade/restart", token, "Restart now"))


def status_page(status: dict, available: str, token: str, why_not: str, stale: str) -> str:
    """``/upgrade`` without JavaScript: where we are, refreshing while it runs."""
    state = status["state"]
    if state in BUSY:
        return upgrading_page(status)
    if state == FAILED:
        return notice_page("The upgrade did not finish", [status["error"]], back=True)
    if stale:
        return stale_page(status["version"], stale, token, why_not)
    if available and not why_not:
        return notice_page(f"Upgrade to v{available}",
                           [f"You are on v{status['version']}. This installs v{available}, "
                            "restarts Hermit CRM and asks you to reload."],
                           form=("/upgrade", token, f"Upgrade to v{available}"), back=True)
    if available:
        return notice_page(f"v{available} is available",
                           [why_not, f"Run `{updates.upgrade_command()}` and restart."],
                           back=True)
    return notice_page("Hermit CRM is up to date", [f"You are on v{status['version']}."],
                       back=True)
