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

"""`hermitcrm init` / `hermitcrm setup`: the interactive questions with scripted input."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from hermitcrm import cli, secrets
from hermitcrm.datafolder import init_folder


def scripted(answers):
    it = iter(answers)
    asked = []

    def ask(prompt=""):
        asked.append(prompt)
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    ask.asked = asked
    return ask


class FakeBox:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def fetch(self):
        return []


def cfg(path):
    return tomllib.loads((path / "config.toml").read_text())


@pytest.fixture
def folder(tmp_path):
    return init_folder(tmp_path / "crm")


def test_setup_all_steps(folder, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    out = []
    ask = scripted(["Jane Doe", "jane@gmail.com, jane@example.com",
                    "y", "", "", "y",          # BCC: accept suggestion + host, test
                    str(bare),                 # backup
                    "y"])                      # calendar
    secret = scripted(["app pw 1234", "https://cal.example.com/secret-xyz.ics"])
    code = cli.cmd_setup(folder, ask=ask, ask_secret=secret, say=out.append,
                         platform="linux", open_mailbox=FakeBox,
                         fetch=lambda url: "BEGIN:VCALENDAR\nEND:VCALENDAR\n")
    text = "\n".join(out)
    assert code == 0, text
    c = cfg(folder)
    assert c["owner_email"] == "jane@gmail.com"
    assert c["bcc_address"] == "jane+crm@gmail.com" and c["bcc_imap_host"] == "imap.gmail.com"
    assert c["bcc_ignore_domains"] == ["example.com"] and c["push_enabled"] is True
    assert "Your name: " in ask.asked[0]
    assert "BCC address [jane+crm@gmail.com]: " in ask.asked
    assert "app pw 1234" not in text and "secret-xyz" not in text
    assert "BCC test OK" in text and "Calendar test OK" in text
    # The remote is the optional online copy; the local backup is not started by setup.
    assert "Setup: you done, bcc done, backup pending, calendar done, remote done" in text
    assert "Local backups start with `hermitcrm schedule install`" in text
    assert secrets.get("bcc_password", folder, env={}, platform="linux") == "app pw 1234"


def test_setup_skip_bcc_and_backup_and_retry_invalid(folder):
    out = []
    ask = scripted(["", "", "Jane", "jane@example.com", "n", "", "n"])
    code = cli.cmd_setup(folder, ask=ask, ask_secret=scripted([]), say=out.append,
                         platform="linux")
    assert code == 0
    assert cfg(folder)["owner_name"] == "Jane"
    text = "\n".join(out)
    assert "Give your name." in text and "Skipped." in text
    assert "you done, bcc pending, backup pending" in text


def test_setup_keychain_on_macos_and_github_warning(folder):
    calls, out = [], []

    def runner(argv, **kw):
        calls.append(argv)
        if argv[0] == "git":
            return subprocess.run(argv, **kw)
        return subprocess.CompletedProcess(argv, 0, "", "")

    ask = scripted(["Jane", "jane@example.com", "y", "jane+crm@example.com",
                    "imap.example.com", "", "n", "git@github.com:me/crm.git", "n"])
    code = cli.cmd_setup(folder, ask=ask, ask_secret=scripted(["pw"]), say=out.append,
                         runner=runner, platform="darwin", push=lambda: (False, "no access"))
    text = "\n".join(out)
    assert code == 0
    assert ["security", "add-generic-password", "-U", "-s", "hermitcrm-bcc", "-a",
            "jane@example.com", "-w", "pw"] in calls
    assert "WARNING:" in text and "PRIVATE" in text and "no access" in text
    assert "pw" not in [line for line in out if "Keychain" in line][0].split()


def test_setup_eof_stops(folder):
    out = []
    assert cli.cmd_setup(folder, ask=scripted(["Jane"]), say=out.append) == 1
    assert "Setup stopped" in out[-1]


class Stdin:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


@pytest.mark.parametrize("argv_extra,tty,expected", [
    ([], True, True), (["--no-setup"], True, False), ([], False, False)])
def test_init_asks_setup_only_on_tty(tmp_path, monkeypatch, argv_extra, tty, expected):
    called = []
    monkeypatch.setattr(cli, "cmd_setup", lambda root, **kw: called.append(root) or 0)
    code = cli.main(["init", str(tmp_path / "d"), *argv_extra], stdin=Stdin(tty))
    assert code == 0
    assert bool(called) is expected


def test_setup_command_dispatches(folder, monkeypatch):
    called = []
    monkeypatch.setattr(cli, "cmd_setup", lambda root, **kw: called.append(root) or 0)
    assert cli.main(["setup"], root=folder) == 0
    assert called == [folder]
