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

"""hermitcrm/schedule.py: generated launchd/systemd/schtasks files, remove and status.

Everything runs against a fake HOME and a recording runner; nothing touches
the real LaunchAgents or systemd."""

from __future__ import annotations

import json
import plistlib
import subprocess
from pathlib import Path

import pytest

from hermitcrm import cli, schedule
from hermitcrm.datafolder import init_folder

EXE = ["/opt/hermitcrm/bin/hermitcrm"]


class Recorder:
    def __init__(self, fail=()):
        self.calls = []
        self.fail = fail

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if argv[0] == "plutil":
            return subprocess.CompletedProcess(argv, 1, "", "no plutil here")
        code = 1 if any(argv[:len(f)] == list(f) for f in self.fail) else 0
        return subprocess.CompletedProcess(argv, code, "", "")


def ctx(tmp_path, platform, runner=None, env=None):
    data = tmp_path / "my crm"
    data.mkdir(exist_ok=True)
    return schedule.Context(data_dir=data, home=tmp_path / "home", platform=platform,
                            runner=runner or Recorder(), env=env or {}, exe=EXE, uid=501,
                            linger_dir=tmp_path / "linger")


def test_parse_time():
    assert schedule.parse_time("7:05") == (7, 5)
    for bad in ("24:00", "07:60", "0700", ""):
        with pytest.raises(schedule.ScheduleError):
            schedule.parse_time(bad)


def test_macos_install_writes_plists_and_bootstraps(tmp_path):
    rec = Recorder()
    c = ctx(tmp_path, "darwin", rec)
    lines = schedule.install(c, at="06:30", serve=True)
    agents = tmp_path / "home/Library/LaunchAgents"
    sync = plistlib.loads((agents / "io.hermitcrm.sync.plist").read_bytes())
    data = str((tmp_path / "my crm").resolve())
    assert sync["ProgramArguments"] == [*EXE, "--data", data, "sync", "--apply"]
    assert sync["StartCalendarInterval"] == {"Hour": 6, "Minute": 30}
    assert sync["StandardOutPath"] == str(tmp_path / "home/Library/Logs/hermitcrm-sync.log")
    serve = plistlib.loads((agents / "io.hermitcrm.serve.plist").read_bytes())
    assert serve["RunAtLoad"] is True and serve["KeepAlive"] is True
    assert serve["ProgramArguments"] == [*EXE, "--data", data, "serve"]
    assert ["launchctl", "bootstrap", "gui/501", str(agents / "io.hermitcrm.sync.plist")] in rec.calls
    assert "loaded io.hermitcrm.sync" in lines
    # Deterministic output.
    before = (agents / "io.hermitcrm.sync.plist").read_bytes()
    schedule.install(c, at="06:30", serve=True)
    assert (agents / "io.hermitcrm.sync.plist").read_bytes() == before


def test_macos_falls_back_to_load_w(tmp_path):
    rec = Recorder(fail=[("launchctl", "bootstrap")])
    lines = schedule.install(ctx(tmp_path, "darwin", rec))
    assert any(c[:3] == ["launchctl", "load", "-w"] for c in rec.calls)
    assert "loaded io.hermitcrm.sync (launchctl load -w)" in lines


def test_dry_env_runs_nothing(tmp_path):
    rec = Recorder()
    lines = schedule.install(ctx(tmp_path, "darwin", rec, env={"HERMITCRM_DRY_SCHEDULE": "1"}))
    assert rec.calls == []
    assert any(l.startswith("dry run, not running: launchctl bootstrap") for l in lines)
    assert "loaded io.hermitcrm.sync" not in lines
    assert (tmp_path / "home/Library/LaunchAgents/io.hermitcrm.sync.plist").exists()


def test_macos_status_reads_with_plutil_dash_o_and_remove(tmp_path):
    calls = []
    agents = tmp_path / "home/Library/LaunchAgents"

    def runner(argv, **kw):
        calls.append(argv)
        if argv[0] == "plutil":
            assert "-o" in argv and argv[argv.index("-o") + 1] == "-"  # never in place
            value = plistlib.loads(Path(argv[-1]).read_bytes())[argv[2]]
            return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    c = ctx(tmp_path, "darwin", runner)
    assert schedule.status(c)["installed"] is False
    schedule.install(c, at="07:00")
    before = (agents / "io.hermitcrm.sync.plist").read_bytes()
    st = schedule.status(c)
    assert st["installed"] is True
    assert "daily at 07:00, loaded" in st["lines"][0]
    assert (agents / "io.hermitcrm.sync.plist").read_bytes() == before
    assert any(a[0] == "plutil" for a in calls)
    assert all(a[:2] != ["plutil", "-replace"] for a in calls)
    lines = schedule.remove(c)
    assert not (agents / "io.hermitcrm.sync.plist").exists()
    assert ["launchctl", "bootout", "gui/501/io.hermitcrm.sync"] in calls
    assert lines[0].startswith("removed ")
    assert schedule.remove(c) == ["nothing installed"]


def test_linux_units(tmp_path):
    rec = Recorder()
    c = ctx(tmp_path, "linux", rec)
    schedule.install(c, at="07:00", serve=True)
    units = tmp_path / "home/.config/systemd/user"
    data = str((tmp_path / "my crm").resolve())
    service = (units / "hermitcrm-sync.service").read_text()
    assert f'ExecStart=/opt/hermitcrm/bin/hermitcrm --data "{data}" sync --apply' in service
    assert "Type=oneshot" in service
    timer = (units / "hermitcrm-sync.timer").read_text()
    assert "OnCalendar=*-*-* 07:00:00" in timer and "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer
    serve = (units / "hermitcrm-serve.service").read_text()
    assert "Restart=always" in serve and "serve" in serve
    assert ["systemctl", "--user", "enable", "--now", "hermitcrm-sync.timer"] in rec.calls
    assert ["systemctl", "--user", "enable", "--now", "hermitcrm-serve.service"] in rec.calls
    st = schedule.status(c)
    assert st["installed"] and "(*-*-* 07:00:00)" in st["lines"][0]
    schedule.remove(c)
    assert not any(units.iterdir())
    assert ["systemctl", "--user", "disable", "--now", "hermitcrm-sync.timer"] in rec.calls
    assert schedule.status(c)["installed"] is False


class Logind(Recorder):
    """A recording runner whose loginctl answers like systemd-logind would.

    `show-user` fails while the user has no session and no lingering; that is
    the case the /var/lib/systemd/linger fallback is for.
    """

    def __init__(self, linger=False, session=True, can_enable=True):
        super().__init__()
        self.linger, self.session, self.can_enable = linger, session, can_enable

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if argv[:2] == ["loginctl", "show-user"]:
            if not (self.session or self.linger):
                return subprocess.CompletedProcess(argv, 1, "", "not logged in or lingering")
            return subprocess.CompletedProcess(argv, 0, "yes\n" if self.linger else "no\n", "")
        if argv == ["loginctl", "--no-ask-password", "enable-linger"]:
            if self.can_enable:
                self.linger = True
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 1, "", "Interactive authentication required.")
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_linux_install_turns_on_lingering(tmp_path):
    rec = Logind(linger=False)
    lines = schedule.install(ctx(tmp_path, "linux", rec, env={"USER": "jane"}), at="07:00")
    enables = [i for i, a in enumerate(rec.calls) if a[:3] == ["systemctl", "--user", "enable"]]
    linger = rec.calls.index(["loginctl", "--no-ask-password", "enable-linger"])
    assert linger > max(enables)  # after the units, so a failure cannot skip them
    assert any(line.startswith("turned on lingering") for line in lines)
    st = schedule.status(ctx(tmp_path, "linux", rec))
    assert st["linger"] is True and "lingering: on" in st["lines"]


def test_linux_install_leaves_lingering_alone_when_on(tmp_path):
    rec = Logind(linger=True)
    lines = schedule.install(ctx(tmp_path, "linux", rec), at="07:00")
    assert ["loginctl", "--no-ask-password", "enable-linger"] not in rec.calls
    assert any(line.startswith("lingering is on") for line in lines)


def test_linux_install_says_how_when_lingering_cannot_be_turned_on(tmp_path):
    rec = Logind(linger=False, can_enable=False)
    lines = schedule.install(ctx(tmp_path, "linux", rec, env={"USER": "jane"}), at="07:00")
    warning = [line for line in lines if line.startswith("WARNING")]
    assert warning and "sudo loginctl enable-linger jane" in warning[0]
    st = schedule.status(ctx(tmp_path, "linux", rec))
    assert st["installed"] and st["linger"] is False
    assert any(line.startswith("lingering: off") for line in st["lines"])


def test_linger_falls_back_to_the_file_logind_reads(tmp_path):
    """No session and no lingering: show-user fails, the linger dir answers."""
    rec = Logind(linger=False, session=False)
    c = ctx(tmp_path, "linux", rec, env={"USER": "jane"})
    assert schedule.linger_enabled(c) is None  # no linger dir: cannot tell
    (tmp_path / "linger").mkdir()
    assert schedule.linger_enabled(c) is False
    (tmp_path / "linger" / "jane").touch()
    assert schedule.linger_enabled(c) is True


def test_linux_dry_run_runs_no_loginctl(tmp_path):
    rec = Logind(linger=False)
    c = ctx(tmp_path, "linux", rec, env={schedule.DRY_ENV: "1"})
    lines = schedule.install(c, at="07:00")
    assert rec.calls == []
    assert "dry run, not running: loginctl --no-ask-password enable-linger" in lines
    assert schedule.status(c)["linger"] is None


def test_status_does_not_check_lingering_with_nothing_installed(tmp_path):
    rec = Logind(linger=False)
    st = schedule.status(ctx(tmp_path, "linux", rec))
    assert st["linger"] is None and rec.calls == []


def other_ctx(tmp_path, platform, runner):
    """A second data folder on the same machine, which has one schedule slot."""
    data = tmp_path / "another crm"
    data.mkdir(exist_ok=True)
    return schedule.Context(data_dir=data, home=tmp_path / "home", platform=platform,
                            runner=runner, env={}, exe=EXE, uid=501,
                            linger_dir=tmp_path / "linger")


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_status_does_not_claim_another_folders_schedule(tmp_path, platform):
    rec = Recorder()
    schedule.install(ctx(tmp_path, platform, rec), at="07:00")

    st = schedule.status(other_ctx(tmp_path, platform, rec))

    assert st["installed"] is False
    assert st["elsewhere"] == (tmp_path / "my crm").resolve()
    assert "for " + str((tmp_path / "my crm").resolve()) in st["lines"][0]


def test_windows_prints_and_runs_nothing(tmp_path):
    rec = Recorder()
    c = ctx(tmp_path, "win32", rec)
    lines = schedule.install(c, at="07:15", serve=True)
    assert rec.calls == []
    text = "\n".join(lines)
    assert 'schtasks /Create /F /SC DAILY /ST 07:15 /TN "Hermit CRM\\sync"' in text
    assert "/SC ONLOGON" in text and "sync --apply" in text
    assert not (tmp_path / "home").exists()
    assert "schtasks /Delete" in "\n".join(schedule.remove(c))
    assert schedule.status(c)["installed"] is False


def test_hermitcrm_executable(tmp_path):
    exe = tmp_path / "hermitcrm"
    exe.write_text("#!/bin/sh\n")
    assert schedule.hermitcrm_executable(str(exe)) == [str(exe.resolve())]
    assert schedule.hermitcrm_executable("pytest", which=lambda n: None)[1:] == ["-m", "hermitcrm.cli"]


def test_cli_schedule_commands(tmp_path, monkeypatch, capsys):
    folder = init_folder(tmp_path / "crm")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HERMITCRM_DRY_SCHEDULE", "1")
    monkeypatch.setattr(schedule.sys, "platform", "darwin")
    assert cli.main(["schedule", "install", "--at", "08:00", "--serve"], root=folder) == 0
    assert (tmp_path / "home/Library/LaunchAgents/io.hermitcrm.serve.plist").exists()
    assert cli.main(["schedule", "status"], root=folder) == 0
    assert "installed daily at 08:00" in capsys.readouterr().out
    assert cli.main(["schedule", "install", "--at", "25:00"], root=folder) == 2
    assert cli.main(["schedule", "remove"], root=folder) == 0
    assert not (tmp_path / "home/Library/LaunchAgents/io.hermitcrm.sync.plist").exists()
