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

"""hermitcrm/doctor.py with every outside dependency faked."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hermitcrm import backup, cli, doctor
from hermitcrm import setup as st
from hermitcrm.bcc import BccError
from hermitcrm.datafolder import init_folder


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
                                "schedule", "backup", "agent guard", "git remote", "enrich cli",
                                "update"]
    assert res["owner_email"].status == "warn"
    assert res["schedule"].status == "warn" and res["git remote"].status == "warn"
    assert res["imap login"].detail == "not checked; add --online"
    assert res["enrich cli"].detail == "claude"
    text, code = doctor.report(list(res.values()))
    assert code == 0 and len(text.splitlines()) == 15
    assert res["backup"].status == "warn"
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
    (home / ".config/systemd/user/hermitcrm-sync.timer").write_text("OnCalendar=*-*-* 07:00:00\n")
    (home / ".config/systemd/user/hermitcrm-backup.timer").write_text("OnUnitActiveSec=5min\n")
    assert backup.run(folder, {}, home=home).code == 0
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
    res = checks(folder, tmp_path, env={"HERMITCRM_NO_UPDATE_CHECK": "1"})
    assert res["update"].detail.endswith("update check is off")


def test_doctor_never_claims_to_be_current_on_a_failed_check(folder, tmp_path):
    """Hermit CRM is not on PyPI, so the check 404s. Reporting "v0.3.0 is the latest"
    for a request that never succeeded is the bug this guards."""
    import urllib.error

    from hermitcrm import updates

    def gone():
        raise urllib.error.HTTPError(updates.PYPI_URL, 404, "nope", {}, None)

    res = checks(folder, tmp_path / "a", update_fetcher=gone)
    assert res["update"].status == "ok"  # nothing is wrong on this machine
    assert "is the latest" not in res["update"].detail
    assert res["update"].detail.endswith("no release published at pypi.org yet")

    def offline():
        raise OSError("no network")

    res = checks(folder, tmp_path / "b", update_fetcher=offline)
    assert "is the latest" not in res["update"].detail
    assert res["update"].detail.endswith("could not reach pypi.org to check")


def test_cli_doctor(folder, monkeypatch, capsys):
    seen = {}

    def fake(root, **kw):
        seen.update(kw, root=root)
        return [doctor.Check("python", "ok", "3.12"), doctor.Check("git", "fail", "missing")]

    monkeypatch.setattr(doctor, "run_checks", fake)
    assert cli.main(["doctor", "--online"], root=folder) == 1
    assert seen["online"] is True and seen["root"] == folder
    assert "fail  git: missing" in capsys.readouterr().out


def test_doctor_schedule_names_the_folder_the_job_actually_serves(tmp_path):
    """A schedule installed for another folder is not this folder's schedule."""
    from hermitcrm import schedule

    mine = init_folder(tmp_path / "mine")
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    home = tmp_path / "home"
    runner = lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "")  # noqa: E731
    schedule.install(schedule.Context(data_dir=theirs, home=home, platform="darwin",
                                      runner=runner, env={}, exe=["/bin/hermitcrm"],
                                      uid=501))

    checks = {c.name: c for c in doctor.run_checks(mine, env={}, which=lambda n: "/bin/" + n,
                                                   runner=runner, platform="darwin",
                                                   home=home, update_fetcher=lambda *a: None)}

    assert checks["schedule"].status == "warn"
    assert str(theirs.resolve()) in checks["schedule"].detail



def test_agent_guard_warns_when_a_rule_is_missing(folder, tmp_path):
    from hermitcrm import guard

    assert checks(folder, tmp_path)["agent guard"].status == "ok"
    path = folder / guard.SETTINGS
    path.write_text(path.read_text().replace('"Bash(git rebase:*)",', ""))
    found = checks(folder, tmp_path)["agent guard"]
    assert found.status == "warn" and "1 of" in found.detail
    assert "hermitcrm backup guard" in found.detail
    path.write_text("{oops")
    assert "not valid JSON" in checks(folder, tmp_path)["agent guard"].detail


def test_theme_css_row(folder, tmp_path):
    assert "theme.css" not in checks(folder, tmp_path)
    (folder / "theme.css").write_text(":root { --accent: light-dark(#1E8A60, #6BC49A); }\n"
                                      "body { background: url(data:image/png;base64,AA); }\n")
    row = checks(folder, tmp_path)["theme.css"]
    assert row.status == doctor.OK
    (folder / "theme.css").write_text(":root{}\n@import 'x.css';\nbody{background:url(https://example.com/a.png)}\n")
    row = checks(folder, tmp_path)["theme.css"]
    assert row.status == doctor.WARN
    assert "line 2: @import" in row.detail and "line 3: url(https://example.com/a.png)" in row.detail


def test_doctor_warns_when_systemd_lingering_is_off(folder, tmp_path):
    """Unit files alone are not a working schedule: without lingering the
    timers stop at logout, so doctor must not say OK."""
    import subprocess

    from hermitcrm import schedule

    class Logind:  # loginctl reports Linger=no and refuses enable-linger
        linger = False

        def __call__(self, argv, **kw):
            if argv[:2] == ["loginctl", "show-user"]:
                return subprocess.CompletedProcess(argv, 0, "yes\n" if self.linger else "no\n", "")
            return subprocess.CompletedProcess(argv, int(argv[:2] == ["loginctl", "--no-ask-password"]),
                                               "", "")

    home = tmp_path / "home"
    rec = Logind()
    schedule.install(schedule.Context(data_dir=folder, home=home, platform="linux",
                                      runner=rec, env={}, exe=["/x/hermitcrm"], uid=501,
                                      linger_dir=tmp_path / "linger"))
    res = checks(folder, tmp_path, runner=rec, home=home)
    assert res["schedule"].status == "warn"
    assert "loginctl enable-linger" in res["schedule"].detail

    rec.linger = True
    assert checks(folder, tmp_path, runner=rec, home=home)["schedule"].status == "ok"
