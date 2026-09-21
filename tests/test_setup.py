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

"""hermitcrm/setup.py: config writing, the setup steps and setup_state (no network)."""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from hermitcrm import secrets
from hermitcrm import setup as st
from hermitcrm.bcc import BccError
from hermitcrm.datafolder import init_folder


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "crm")


def cfg(path: Path) -> dict:
    return tomllib.loads((path / "config.toml").read_text(encoding="utf-8"))


# ------------------------------------------------------------ set_config_values


def test_set_config_values_replaces_commented_and_live_lines_and_appends(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("# Your name.\n# owner_name = \"\"\n\nport = 8765  \n# trailing note\n")
    st.set_config_values(path, {"owner_name": 'Jane "J" Doe', "port": 9000,
                                "push_enabled": False, "my_addresses": ["a@example.com"]})
    text = path.read_text()
    assert "# Your name.\n" in text and "# trailing note\n" in text
    assert "# owner_name" not in text
    assert tomllib.loads(text) == {"owner_name": 'Jane "J" Doe', "port": 9000,
                                   "push_enabled": False, "my_addresses": ["a@example.com"]}
    assert text.count("port =") == 1


def test_set_config_values_prefers_live_line_over_commented(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("# remote = \"origin\"\nremote = \"backup\"\n")
    st.set_config_values(path, {"remote": "home"})
    assert path.read_text() == "# remote = \"origin\"\nremote = \"home\"\n"


def test_toml_value_types():
    assert st.toml_value(True) == "true"
    assert st.toml_value(7) == "7"
    assert st.toml_value(["x", 'y"z']) == '["x", "y\\"z"]'
    assert tomllib.loads("k = " + st.toml_value("tab\there\nnewline é"))["k"] == "tab\there\nnewline é"
    with pytest.raises(TypeError):
        st.toml_value(1.5)


def test_rendered_config_keeps_comments_after_save(folder):
    before = (folder / "config.toml").read_text()
    comments = [l for l in before.splitlines() if l.startswith("# ") and " = " not in l]
    st.save_you(folder, "Jane Doe", "jane@example.com")
    after = (folder / "config.toml").read_text()
    assert all(c in after.splitlines() for c in comments)


# ------------------------------------------------------------------- You


def test_plan_you_values_and_freemail_excluded():
    r = st.plan_you(" Jane Doe ", "Jane@Example.com, jane@gmail.com\njd@example.org")
    assert r.ok
    assert r.values == {"owner_name": "Jane Doe", "owner_email": "jane@example.com",
                        "my_addresses": ["jane@example.com", "jane@gmail.com", "jd@example.org"],
                        "bcc_ignore_domains": ["example.com", "example.org"]}


def test_plan_you_errors():
    r = st.plan_you("", "not-an-address")
    assert not r.ok and set(r.errors) == {"name", "addresses"}
    assert not st.plan_you("Jane", "").ok


def test_save_you_writes_config(folder):
    assert st.save_you(folder, "Jane Doe", ["jane@gmail.com"]).ok
    c = cfg(folder)
    assert c["owner_email"] == "jane@gmail.com" and c["bcc_ignore_domains"] == []


# ------------------------------------------------------------------- BCC


def test_bcc_suggestions():
    assert st.suggest_bcc_address("jane.doe@gmail.com") == "jane.doe+crm@gmail.com"
    assert st.suggest_bcc_address("jane+x@googlemail.com") == "jane+crm@googlemail.com"
    assert st.suggest_bcc_address("jane@example.com") == ""
    assert st.imap_host_for("a@gmail.com") == "imap.gmail.com"
    assert st.imap_host_for("a@hotmail.com") == "outlook.office365.com"
    assert st.imap_host_for("a@live.com") == "outlook.office365.com"
    assert st.imap_host_for("a@icloud.com") == "imap.mail.me.com"
    assert st.imap_host_for("a@example.com") == ""
    assert st.gmail_filter_text("jane+crm@gmail.com") == (
        "Matches: to:(jane+crm@gmail.com) → Skip the Inbox, Mark as read, Apply label Hermit CRM")


def test_save_bcc_to_secrets_file(folder):
    r = st.save_bcc(folder, "jane+crm@gmail.com", "", "abcd efgh", platform="linux")
    assert r.ok
    assert "abcd" not in r.text()
    assert "Matches: to:(jane+crm@gmail.com)" in r.text()
    assert cfg(folder)["bcc_imap_host"] == "imap.gmail.com"
    assert secrets.get("bcc_password", folder, env={}, platform="linux") == "abcd efgh"


def test_save_bcc_keychain_through_runner(folder):
    calls = []

    def runner(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    r = st.save_bcc(folder, "jane+crm@gmail.com", "imap.gmail.com", "s3cret",
                    use_keychain=True, runner=runner, platform="darwin")
    assert r.ok and "s3cret" not in r.text()
    assert calls == [["security", "add-generic-password", "-U", "-s", "hermitcrm-bcc",
                      "-a", "jane@gmail.com", "-w", "s3cret"]]
    assert cfg(folder)["bcc_keychain_service"] == "hermitcrm-bcc"
    assert not (folder / ".secrets.toml").exists()


def test_save_bcc_keychain_failure_and_validation(folder):
    fail = lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "denied")  # noqa: E731
    r = st.save_bcc(folder, "jane+crm@gmail.com", "", "pw", use_keychain=True,
                    runner=fail, platform="darwin")
    assert not r.ok and "pw" not in r.errors["password"]
    r = st.save_bcc(folder, "jane@example.com", "", "")
    assert not r.ok and "imap_host" in r.errors


class FakeBox:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def fetch(self):
        return []

    def mark_read(self, uids):
        raise AssertionError("dry run must not mark read")


def test_test_bcc_summary_and_hint(folder):
    st.save_bcc(folder, "jane+crm@gmail.com", "", "pw", platform="linux")
    ok = st.test_bcc(folder, open_mailbox=FakeBox)
    assert ok.ok and "0 mails read" in ok.text()

    def refused():
        raise BccError("Gmail refused the login for jane@gmail.com: [AUTHENTICATIONFAILED]")

    bad = st.test_bcc(folder, open_mailbox=refused)
    assert not bad.ok
    assert "use an app password, not your normal password" in bad.text()


# ---------------------------------------------------------------- Backup


def test_private_warning_hosts():
    assert "PRIVATE" in st.private_warning("git@github.com:me/crm.git")
    assert "PRIVATE" in st.private_warning("https://gitlab.com/me/crm.git")
    assert "PRIVATE" in st.private_warning("ssh://git@bitbucket.org/me/crm.git")
    assert st.private_warning("ssh://git@git.example.com/crm.git") == ""


def test_save_backup_with_local_bare_remote(folder, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    r = st.save_backup(folder, str(bare))
    assert r.ok, r.text()
    assert cfg(folder)["push_enabled"] is True
    assert st.remote_url(folder) == str(bare)
    # Rerun updates the URL (set-url) and a failing push turns pushing off.
    r = st.save_backup(folder, "git@github.com:me/crm.git", push=lambda: (False, "denied"))
    assert not r.ok and "PRIVATE" in r.text() and "denied" in r.text()
    assert st.remote_url(folder) == "git@github.com:me/crm.git"
    assert cfg(folder)["push_enabled"] is False


# -------------------------------------------------------------- Calendar


def test_save_calendar_dry_run_never_echoes_url(folder):
    url = "https://calendar.example.com/private-abc123/basic.ics"
    ics = "BEGIN:VCALENDAR\nEND:VCALENDAR\n"
    r = st.save_calendar(folder, url, fetch=lambda u: ics)
    assert r.ok and "abc123" not in r.text() and "Calendar test OK" in r.text()
    assert secrets.get("calendar_ics_url", folder, env={}, platform="linux") == url

    def boom(u):
        raise OSError(f"cannot fetch {u}")

    r = st.save_calendar(folder, url, fetch=boom)
    assert not r.ok and "abc123" not in r.text()
    assert not st.save_calendar(folder, "ftp://nope").ok


# ----------------------------------------------------------------- state


def test_setup_state(folder, tmp_path):
    from hermitcrm import backup

    home = tmp_path / "home"
    state = st.setup_state(folder, env={}, platform="linux", home=home)
    assert state == {"you": False, "bcc": False, "backup": False, "calendar": False,
                     "remote": False}
    assert st.pending(state)
    st.save_you(folder, "Jane", "jane@gmail.com")
    st.save_bcc(folder, "jane+crm@gmail.com", "", "pw", platform="linux")
    bare = tmp_path / "r.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    st.save_backup(folder, str(bare))
    state = st.setup_state(folder, env={}, platform="linux", home=home)
    # A remote is the optional extra copy; the local backup is what setup asks for.
    assert state == {"you": True, "bcc": True, "backup": False, "calendar": False,
                     "remote": True}
    assert st.pending(state)
    assert backup.run(folder, {}, home=home, push_remote=False).code == 0
    state = st.setup_state(folder, env={}, platform="linux", home=home)
    assert state["backup"] is True and not st.pending(state)
    shutil.rmtree(backup.backup_path(folder, {}, home))  # gone again: not done
    assert st.setup_state(folder, env={}, platform="linux", home=home)["backup"] is False
