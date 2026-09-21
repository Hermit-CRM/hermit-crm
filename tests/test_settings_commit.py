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

"""A settings save commits config.toml (and fields.toml) like any other write.

Commits are scoped to the paths a write announced (store.take_touched), and
set_config_values writes config.toml itself, so a save that is not announced
leaves the data folder dirty forever (` M config.toml`). The same root cause as
the inbox files in test_inbox_commit.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import cli
from hermitcrm import setup as st
from hermitcrm.datafolder import init_folder
from hermitcrm.gitops import GitOps
from hermitcrm.store import load_config
from hermitcrm.web import create_app


def git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True).stdout


def committed(repo: Path) -> str:
    return git(["show", "--name-status", "--no-renames", "--format=", "HEAD"], repo)


def subject(repo: Path) -> str:
    return git(["log", "-1", "--format=%s"], repo).strip()


def dirty(repo: Path) -> str:
    return git(["status", "--porcelain"], repo)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    path = init_folder(tmp_path / "crm")
    assert git(["rev-parse", "HEAD"], path).strip() and not dirty(path)
    return path


@pytest.fixture
def client(folder: Path) -> TestClient:
    config = load_config(folder)
    config["push_enabled"] = False
    app = create_app(folder, config)
    app.state.setup_platform = "linux"
    app.state.setup_push = lambda: (True, "")
    app.state.setup_redirected = True
    return TestClient(app, follow_redirects=False)


def post(client: TestClient, path: str, **form) -> None:
    r = client.post(path, data={"csrf_token": client.app.state.csrf_token, **form})
    assert r.status_code == 303, (path, r.status_code, r.text[:500])


# Every route that writes config.toml, with a form that saves.
CONFIG_ROUTES = [
    ("/settings/you", {"name": "Jane Doe", "addresses": "jane@example.com"}),
    ("/settings/bcc", {"address": "jane+crm@example.com", "imap_host": "imap.example.com",
                       "password": "app-pw-9876"}),
    ("/settings/backup", {"url": "{bare}"}),
    ("/settings/messaging", {"size_field": "", "team_field": ""}),
    ("/settings/enrichment", {"provider": "custom", "command": "my-ai --fast",
                              "timeout": "60"}),
    ("/settings/appearance", {"theme": "dark"}),
    ("/settings/outcomes", {"outcomes": "Replied\nNo reply", "message_window_days": "7",
                            "silent_days": "21"}),
    ("/welcome/tick", {"key": "find", "done": "1"}),
    ("/welcome/dismiss", {"dismissed": "1"}),
    ("/disclaimer/accept", {"accepted": "1"}),
]


@pytest.mark.parametrize("path,form", CONFIG_ROUTES, ids=[p for p, _ in CONFIG_ROUTES])
def test_every_config_save_is_committed(client, folder, tmp_path, path, form):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    form = {k: v.replace("{bare}", str(bare)) for k, v in form.items()}
    before = git(["rev-parse", "HEAD"], folder)
    post(client, path, **form)
    assert git(["rev-parse", "HEAD"], folder) != before, "nothing was committed"
    assert not dirty(folder), dirty(folder)
    assert "M\tconfig.toml" in committed(folder)
    assert subject(folder).startswith("settings: ")


def test_the_message_says_what_changed(client, folder):
    post(client, "/settings/appearance", theme="light")
    post(client, "/settings/appearance", theme="dark")
    assert subject(folder) == "settings: theme light -> dark"
    assert committed(folder).split() == ["M", "config.toml"]


def test_saving_the_same_value_again_makes_no_commit(client, folder):
    post(client, "/settings/appearance", theme="dark")
    head = git(["rev-parse", "HEAD"], folder)
    post(client, "/settings/appearance", theme="dark")
    assert git(["rev-parse", "HEAD"], folder) == head and not dirty(folder)


def test_a_bcc_password_is_never_committed(client, folder):
    post(client, "/settings/bcc", address="jane+crm@example.com",
         imap_host="imap.example.com", password="app-pw-9876")
    assert (folder / ".secrets.toml").exists()
    assert ".secrets.toml" not in git(["ls-files"], folder)
    assert ".secrets.toml" not in committed(folder)
    assert "app-pw-9876" not in (folder / "config.toml").read_text()
    assert "app-pw-9876" not in git(["log", "-p", "--all"], folder)


def test_an_earlier_hand_edit_goes_in_with_the_next_save(client, folder):
    """The state Gijs's folder is in: config.toml already modified by hand."""
    st.set_config_values(folder / "config.toml", {"silent_days": 30})
    post(client, "/settings/appearance", theme="dark")
    assert not dirty(folder)
    assert "silent_days" in subject(folder) and "theme" in subject(folder)


@pytest.mark.parametrize("path,form", [
    ("/settings/fields", {"fields_toml": '[[field]]\nkey = "acv"\ntype = "number"\n'}),
    ("/settings/fields/add", {"key": "acv", "type": "number"}),
])
def test_field_definitions_are_committed(client, folder, path, form):
    post(client, path, **form)
    assert not dirty(folder), dirty(folder)
    assert "A\tfields.toml" in committed(folder)
    assert subject(folder).startswith("settings: field")


def test_removing_every_field_commits_the_removal(client, folder):
    post(client, "/settings/fields/add", key="acv", type="number")
    post(client, "/settings/fields", fields_toml="")
    assert not (folder / "fields.toml").exists() and not dirty(folder)
    assert "D\tfields.toml" in committed(folder)


def test_the_cli_wizard_commits_its_answers(folder):
    answers = iter(["Jane Doe", "jane@example.com", "n", "", "n"])
    code = cli.cmd_setup(folder, ask=lambda prompt="": next(answers),
                         ask_secret=lambda prompt="": "", say=lambda *a: None,
                         platform="linux")
    assert code == 0
    assert not dirty(folder), dirty(folder)
    assert subject(folder).startswith("settings: ") and "owner_name" in subject(folder)


# ------------------------------------------------------------ commit_config


def test_a_config_holding_a_secret_is_not_committed(folder):
    path = folder / "config.toml"
    path.write_text(path.read_text() + 'bcc_password = "oops"\n')
    calls = []
    assert st.commit_config(folder, lambda msg, paths: calls.append(msg)) == ""
    assert calls == []


def test_commit_config_names_only_config_toml(folder):
    st.set_config_values(folder / "config.toml", {"theme": "dark"})
    (folder / ".secrets.toml").write_text('bcc_password = "x"\n')
    (folder / "notes.txt").write_text("mine\n")
    st.commit_config(folder, GitOps(folder, push_enabled=False).commit)
    assert committed(folder).split() == ["M", "config.toml"]
    assert "notes.txt" in dirty(folder)  # the user's own file stays theirs


def test_a_comment_only_edit_is_committed_plainly(folder):
    path = folder / "config.toml"
    path.write_text(path.read_text() + "# a note\n")
    calls = []
    st.commit_config(folder, lambda msg, paths: calls.append((msg, paths)))
    assert calls == [("settings: config.toml", ["config.toml"])]


def test_describe_config_change():
    d = st.describe_config_change
    assert d({"theme": "light"}, {"theme": "dark"}) == "settings: theme light -> dark"
    assert d({}, {"push_enabled": True}) == "settings: push_enabled unset -> true"
    assert d({"a": 1}, {}) == "settings: a removed"
    assert d({"x": 1}, {"x": 1}) == ""
    assert d({}, {"enrich_command": "my-ai --fast"}) == "settings: enrich_command changed"
    assert d({}, {"welcome_done": ["find"]}) == "settings: welcome_done unset -> [find]"
    many = {f"key_number_{i}": "some-long-value-here" for i in range(12)}
    msg = d({}, many)
    assert msg == "settings: key_number_0, key_number_1, key_number_2 and 9 more"
