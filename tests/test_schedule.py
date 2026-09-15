"""owncrm/schedule.py: generated launchd/systemd/schtasks files, remove and status.

Everything runs against a fake HOME and a recording runner; nothing touches
the real LaunchAgents or systemd."""

from __future__ import annotations

import json
import plistlib
import subprocess
from pathlib import Path

import pytest

from owncrm import cli, schedule
from owncrm.datafolder import init_folder

EXE = ["/opt/owncrm/bin/owncrm"]


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
                            runner=runner or Recorder(), env=env or {}, exe=EXE, uid=501)


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
    sync = plistlib.loads((agents / "io.owncrm.sync.plist").read_bytes())
    data = str((tmp_path / "my crm").resolve())
    assert sync["ProgramArguments"] == [*EXE, "--data", data, "sync", "--apply"]
    assert sync["StartCalendarInterval"] == {"Hour": 6, "Minute": 30}
    assert sync["StandardOutPath"] == str(tmp_path / "home/Library/Logs/owncrm-sync.log")
    serve = plistlib.loads((agents / "io.owncrm.serve.plist").read_bytes())
    assert serve["RunAtLoad"] is True and serve["KeepAlive"] is True
    assert serve["ProgramArguments"] == [*EXE, "--data", data, "serve"]
    assert ["launchctl", "bootstrap", "gui/501", str(agents / "io.owncrm.sync.plist")] in rec.calls
    assert "loaded io.owncrm.sync" in lines
    # Deterministic output.
    before = (agents / "io.owncrm.sync.plist").read_bytes()
    schedule.install(c, at="06:30", serve=True)
    assert (agents / "io.owncrm.sync.plist").read_bytes() == before


def test_macos_falls_back_to_load_w(tmp_path):
    rec = Recorder(fail=[("launchctl", "bootstrap")])
    lines = schedule.install(ctx(tmp_path, "darwin", rec))
    assert any(c[:3] == ["launchctl", "load", "-w"] for c in rec.calls)
    assert "loaded io.owncrm.sync (launchctl load -w)" in lines


def test_dry_env_runs_nothing(tmp_path):
    rec = Recorder()
    lines = schedule.install(ctx(tmp_path, "darwin", rec, env={"OWNCRM_DRY_SCHEDULE": "1"}))
    assert rec.calls == []
    assert any(l.startswith("dry run, not running: launchctl bootstrap") for l in lines)
    assert "loaded io.owncrm.sync" not in lines
    assert (tmp_path / "home/Library/LaunchAgents/io.owncrm.sync.plist").exists()


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
    before = (agents / "io.owncrm.sync.plist").read_bytes()
    st = schedule.status(c)
    assert st["installed"] is True
    assert "daily at 07:00, loaded" in st["lines"][0]
    assert (agents / "io.owncrm.sync.plist").read_bytes() == before
    assert any(a[0] == "plutil" for a in calls)
    assert all(a[:2] != ["plutil", "-replace"] for a in calls)
    lines = schedule.remove(c)
    assert not (agents / "io.owncrm.sync.plist").exists()
    assert ["launchctl", "bootout", "gui/501/io.owncrm.sync"] in calls
    assert lines[0].startswith("removed ")
    assert schedule.remove(c) == ["nothing installed"]


def test_linux_units(tmp_path):
    rec = Recorder()
    c = ctx(tmp_path, "linux", rec)
    schedule.install(c, at="07:00", serve=True)
    units = tmp_path / "home/.config/systemd/user"
    data = str((tmp_path / "my crm").resolve())
    service = (units / "owncrm-sync.service").read_text()
    assert f'ExecStart=/opt/owncrm/bin/owncrm --data "{data}" sync --apply' in service
    assert "Type=oneshot" in service
    timer = (units / "owncrm-sync.timer").read_text()
    assert "OnCalendar=*-*-* 07:00:00" in timer and "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer
    serve = (units / "owncrm-serve.service").read_text()
    assert "Restart=always" in serve and "serve" in serve
    assert ["systemctl", "--user", "enable", "--now", "owncrm-sync.timer"] in rec.calls
    assert ["systemctl", "--user", "enable", "--now", "owncrm-serve.service"] in rec.calls
    st = schedule.status(c)
    assert st["installed"] and "(*-*-* 07:00:00)" in st["lines"][0]
    schedule.remove(c)
    assert not any(units.iterdir())
    assert ["systemctl", "--user", "disable", "--now", "owncrm-sync.timer"] in rec.calls
    assert schedule.status(c)["installed"] is False


def test_windows_prints_and_runs_nothing(tmp_path):
    rec = Recorder()
    c = ctx(tmp_path, "win32", rec)
    lines = schedule.install(c, at="07:15", serve=True)
    assert rec.calls == []
    text = "\n".join(lines)
    assert 'schtasks /Create /F /SC DAILY /ST 07:15 /TN "OwnCRM\\sync"' in text
    assert "/SC ONLOGON" in text and "sync --apply" in text
    assert not (tmp_path / "home").exists()
    assert "schtasks /Delete" in "\n".join(schedule.remove(c))
    assert schedule.status(c)["installed"] is False


def test_owncrm_executable(tmp_path):
    exe = tmp_path / "owncrm"
    exe.write_text("#!/bin/sh\n")
    assert schedule.owncrm_executable(str(exe)) == [str(exe.resolve())]
    assert schedule.owncrm_executable("pytest", which=lambda n: None)[1:] == ["-m", "owncrm.cli"]


def test_cli_schedule_commands(tmp_path, monkeypatch, capsys):
    folder = init_folder(tmp_path / "crm")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OWNCRM_DRY_SCHEDULE", "1")
    monkeypatch.setattr(schedule.sys, "platform", "darwin")
    assert cli.main(["schedule", "install", "--at", "08:00", "--serve"], root=folder) == 0
    assert (tmp_path / "home/Library/LaunchAgents/io.owncrm.serve.plist").exists()
    assert cli.main(["schedule", "status"], root=folder) == 0
    assert "installed daily at 08:00" in capsys.readouterr().out
    assert cli.main(["schedule", "install", "--at", "25:00"], root=folder) == 2
    assert cli.main(["schedule", "remove"], root=folder) == 0
    assert not (tmp_path / "home/Library/LaunchAgents/io.owncrm.sync.plist").exists()
