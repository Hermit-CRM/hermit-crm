"""owncrm/doctor.py with every outside dependency faked."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from owncrm import cli, doctor
from owncrm import setup as st
from owncrm.bcc import BccError
from owncrm.datafolder import init_folder


class FakeEnricher:
    def __init__(self, ok=True):
        self.available = ok
        self.provider_name = "claude" if ok else ""

    def unavailable_reason(self):
        return "no AI CLI on PATH"


class Box:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def checks(folder, tmp_path, **kw):
    base = dict(env={}, which=lambda n: "/usr/bin/git", platform="linux",
                home=tmp_path / "home", enricher=FakeEnricher(),
                update_fetcher=lambda: "0.0.1", update_cache=tmp_path / "update.json")
    base.update(kw)
    return {c.name: c for c in doctor.run_checks(folder, **base)}


@pytest.fixture
def folder(tmp_path):
    return init_folder(tmp_path / "crm")


def test_fresh_folder_warns_but_does_not_fail(folder, tmp_path):
    res = checks(folder, tmp_path)
    assert [c for c in res] == ["python", "git", "data folder", "data format", "config",
                                "owner_email", "bcc password", "imap login", "calendar url",
                                "schedule", "git remote", "enrich cli", "update"]
    assert res["owner_email"].status == "warn"
    assert res["schedule"].status == "warn" and res["git remote"].status == "warn"
    assert res["imap login"].detail == "not checked; add --online"
    assert res["enrich cli"].detail == "claude"
    text, code = doctor.report(list(res.values()))
    assert code == 0 and len(text.splitlines()) == 13
    assert text.splitlines()[0].startswith("ok    python: ")


def test_failures_exit_1(folder, tmp_path):
    (folder / "config.toml").write_text('bcc_address = "jane+crm@gmail.com"\nbroken = [\n')
    res = checks(folder, tmp_path, which=lambda n: None, python=(3, 10, 4))
    assert res["python"].status == "fail" and res["git"].status == "fail"
    assert res["config"].status == "fail"
    _, code = doctor.report(list(res.values()))
    assert code == 1


def test_not_a_data_folder(tmp_path):
    res = checks(tmp_path / "nowhere", tmp_path)
    assert res["data folder"].status == "fail" and "update" not in res


def test_configured_folder_all_ok_and_secret_not_printed(folder, tmp_path):
    st.save_you(folder, "Jane", "jane@gmail.com")
    st.save_bcc(folder, "jane+crm@gmail.com", "", "super-secret-pw", platform="linux")
    st.save_calendar(folder, "https://cal.example.com/hidden.ics",
                     fetch=lambda u: "BEGIN:VCALENDAR\nEND:VCALENDAR\n")
    bare = tmp_path / "r.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    assert st.save_backup(folder, str(bare)).ok
    home = tmp_path / "home"
    (home / ".config/systemd/user").mkdir(parents=True)
    (home / ".config/systemd/user/owncrm-sync.timer").write_text("OnCalendar=*-*-* 07:00:00\n")
    res = checks(folder, tmp_path, online=True, open_mailbox=Box)
    text, code = doctor.report(list(res.values()))
    assert code == 0, text
    assert all(c.status == "ok" for c in res.values()), text
    assert "super-secret-pw" not in text and "hidden.ics" not in text
    assert "last pushed" in res["git remote"].detail


def test_online_login_failure_and_missing_password(folder, tmp_path):
    st.save_bcc(folder, "jane+crm@gmail.com", "", "", platform="linux")

    def refused():
        raise BccError("Gmail refused the login for jane@gmail.com: bad")

    res = checks(folder, tmp_path, online=True, open_mailbox=refused)
    assert res["bcc password"].status == "fail"
    assert res["imap login"].status == "fail" and "app password" in res["imap login"].detail


def test_update_and_enrich_warnings(folder, tmp_path):
    res = checks(folder, tmp_path, update_fetcher=lambda: "99.0.0",
                 enricher=FakeEnricher(False))
    assert res["update"].status == "warn" and "v99.0.0 available" in res["update"].detail
    assert res["enrich cli"].status == "warn"
    res = checks(folder, tmp_path, env={"OWNCRM_NO_UPDATE_CHECK": "1"})
    assert res["update"].detail.endswith("update check is off")


def test_cli_doctor(folder, monkeypatch, capsys):
    seen = {}

    def fake(root, **kw):
        seen.update(kw, root=root)
        return [doctor.Check("python", "ok", "3.12"), doctor.Check("git", "fail", "missing")]

    monkeypatch.setattr(doctor, "run_checks", fake)
    assert cli.main(["doctor", "--online"], root=folder) == 1
    assert seen["online"] is True and seen["root"] == folder
    assert "fail  git: missing" in capsys.readouterr().out
