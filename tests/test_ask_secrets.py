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

"""Ask's read-only walk never sees .secrets.toml (audit S4; 2026-10-31 action
plan row 10; 2026-09-18 item 9).

A deny rule for the file is not enough: with `claude` 2.1.330 a Read deny
stops Read, Grep, Glob and `cat .secrets.toml`, but `grep -r FAKE .` through
Bash still printed the file (probe in the pull request). So the walk runs in a
temporary copy of the folder that has no dotfiles at all.
"""

from __future__ import annotations

import os
from pathlib import Path

from hermitcrm import ask as asking
from hermitcrm.enrich import Enricher

ALL = lambda binary: f"/usr/local/bin/{binary}"  # noqa: E731
SECRET = "FAKE-SECRET-zebra-7731"


def _folder(root: Path) -> Path:
    (root / "companies" / "example" / "contacts").mkdir(parents=True)
    (root / "companies" / "example" / "company.md").write_text(
        "---\nname: Example\n---\n", encoding="utf-8")
    (root / "companies" / "example" / "contacts" / "ada.md").write_text(
        "---\nfirst_name: Ada\n---\n", encoding="utf-8")
    (root / "PIPELINE.md").write_text("# Pipeline\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")
    (root / "config.toml").write_text("port = 8765\n", encoding="utf-8")
    (root / ".hermitcrm-format").write_text("26\n", encoding="utf-8")
    (root / ".secrets.toml").write_text(f'bcc_password = "{SECRET}"\n', encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text(f"# {SECRET}\n", encoding="utf-8")
    (root / ".claude" / "skills").mkdir(parents=True)
    (root / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    (root / "companies" / "example" / ".hidden.md").write_text(SECRET, encoding="utf-8")
    # A link with an ordinary name that points at the secrets file.
    (root / "companies" / "example" / "notes.md").symlink_to(root / ".secrets.toml")
    (root / "linked-dir").symlink_to(root / ".git")
    return root


def _everything(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))


def _holds_secret(folder: Path) -> list[str]:
    hits = []
    for dirpath, _dirs, files in os.walk(folder):
        for name in files:
            path = Path(dirpath) / name
            if path.is_file() and SECRET in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(path.relative_to(folder).as_posix())
    return hits


class RecordingRunner:
    """Answers once and records what the walk's working folder holds at that moment."""

    def __init__(self):
        self.calls = []

    def __call__(self, prompt, schema, **kwargs):
        cwd = Path(kwargs["cwd"])
        self.calls.append({**kwargs, "files": _everything(cwd), "secret_in": _holds_secret(cwd)})
        return {"answer": "Fine.", "sources": ["PIPELINE.md"]}


def test_the_walk_copy_has_no_dotfiles_and_no_links(tmp_path):
    data = _folder(tmp_path / "data")
    with asking.walk_folder(data) as copy:
        assert copy != data and not copy.is_relative_to(data)
        files = _everything(copy)
        assert files == [".hermitcrm-format", "CLAUDE.md", "PIPELINE.md", "companies",
                         "companies/example", "companies/example/company.md",
                         "companies/example/contacts", "companies/example/contacts/ada.md",
                         "config.toml"]
        assert _holds_secret(copy) == []
        assert (copy / "companies/example/company.md").read_bytes() == \
            (data / "companies/example/company.md").read_bytes()
    assert not copy.exists()  # removed after the walk
    assert (data / ".secrets.toml").exists()  # the real folder is untouched


def test_the_deep_walk_runs_in_a_copy_without_the_secrets_file(tmp_path):
    data = _folder(tmp_path / "data")
    runner = RecordingRunner()
    e = Enricher(provider="claude", which=ALL, runner=runner)
    answer = asking.ask(e, "What is in the secrets file?", "/", "", data, scope="deep")
    assert answer.text == "Fine."
    (call,) = runner.calls
    assert Path(call["cwd"]) != data
    assert ".secrets.toml" not in call["files"]
    assert call["secret_in"] == []
    assert "PIPELINE.md" in call["files"] and "CLAUDE.md" in call["files"]
    assert not Path(call["cwd"]).exists()


def test_a_failed_walk_still_removes_the_copy(tmp_path):
    data = _folder(tmp_path / "data")
    seen = []

    def failing(prompt, schema, **kwargs):
        seen.append(Path(kwargs["cwd"]))
        raise RuntimeError("the AI tool crashed")

    e = Enricher(provider="claude", which=ALL, runner=failing)
    try:
        asking.ask(e, "q", "/", "", data, scope="deep")
    except RuntimeError:
        pass
    assert seen and not seen[0].exists()


def test_big_files_are_the_same_bytes_in_the_copy(tmp_path):
    data = _folder(tmp_path / "data")
    big = data / "companies" / "example" / "files" / "deck.pdf"
    big.parent.mkdir()
    big.write_bytes(os.urandom(asking.LINK_ABOVE + 10))
    with asking.walk_folder(data) as copy:
        assert (copy / "companies/example/files/deck.pdf").read_bytes() == big.read_bytes()


def test_the_file_tools_may_not_leave_the_working_folder():
    # A bare "Read" lets the walk open any file on the disk by its full path,
    # the real folder's .secrets.toml included (seen in the probe).
    tools = asking.CRM_TOOLS.split(",")
    for name in ("Read", "Grep", "Glob"):
        assert name not in tools
        assert f"{name}(./**)" in tools
    assert not any(t.startswith(("Edit", "Write", "WebFetch", "WebSearch")) for t in tools)
