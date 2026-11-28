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

"""The Keychain password never appears on a command line (audit S8; 2026-09-18
item 7). `ps` shows every process's arguments to the same user, so the value goes
to `security -i` over standard input, as hex (`-X`), like the Linux path already
sends it to secret-tool. Fake runners only: no test touches a real keychain."""

from __future__ import annotations

import subprocess

import pytest

from hermitcrm import secrets


def split_line(line: str) -> list[str]:
    """How `security -i` splits a line, as observed with its `help` command on
    macOS: whitespace separates words, a word may be in double quotes, and inside
    them a backslash takes the next character literally."""
    words, i = [], 0
    while i < len(line):
        if line[i].isspace():
            i += 1
            continue
        if line[i] == '"':
            i += 1
            word = ""
            while line[i] != '"':
                if line[i] == "\\":
                    i += 1
                word += line[i]
                i += 1
            i += 1
        else:
            j = i
            while j < len(line) and not line[j].isspace():
                j += 1
            word, i = line[i:j], j
        words.append(word)
    return words


class Recorder:
    def __init__(self, code: int = 0):
        self.calls, self.code = [], code

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw.get("input")))
        return subprocess.CompletedProcess(argv, self.code, "", "")


@pytest.mark.parametrize("value", [
    "s3cret",
    "abcd efgh ijkl mnop",          # a Gmail app password has spaces
    'quote" and \\ backslash',
    "line\nbreak",
    "ünïcødé ✓",
    "-w looks like a flag",
])
def test_the_value_goes_over_stdin_never_in_argv(value):
    run = Recorder()
    assert secrets.os_store_save(secrets.KEYCHAIN, "hermitcrm-bcc", "jane@example.com",
                                 value, runner=run)
    ((argv, stdin),) = run.calls
    assert argv == ["security", "-i"]
    assert value not in " ".join(argv)
    assert stdin.endswith("\n") and stdin.count("\n") == 1
    words = split_line(stdin.strip())
    assert words[:6] == ["add-generic-password", "-U", "-s", "hermitcrm-bcc",
                         "-a", "jane@example.com"]
    assert words[6] == "-X" and bytes.fromhex(words[7]).decode("utf-8") == value
    assert len(words) == 8


def test_service_and_account_with_odd_characters_survive_the_split():
    run = Recorder()
    secrets.os_store_save(secrets.KEYCHAIN, 'svc with "quotes"', "a\\b c@example.com", "v",
                          runner=run)
    ((_, stdin),) = run.calls
    words = split_line(stdin.strip())
    assert words[3] == 'svc with "quotes"' and words[5] == "a\\b c@example.com"


def test_a_line_break_in_the_service_or_account_is_refused_unrun():
    run = Recorder()
    assert not secrets.os_store_save(secrets.KEYCHAIN, "svc\nhelp", "me", "v", runner=run)
    assert not secrets.os_store_save(secrets.KEYCHAIN, "svc", "me\r", "v", runner=run)
    assert run.calls == []


def test_a_failed_keychain_write_reads_as_not_saved():
    assert not secrets.os_store_save(secrets.KEYCHAIN, "svc", "me", "v", runner=Recorder(1))


def test_split_line_matches_what_security_showed():
    # Seen on macOS: printf 'help "a b\\" c"\n' | security -i
    #   -> security: help: no such command: a b" c
    assert split_line('help "a b\\" c"') == ["help", 'a b" c']
    assert split_line('help "x\\\\"') == ["help", "x\\"]
