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

"""clientfiles.py: finding, listing and opening a company's client folder."""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pytest

from hermitcrm import clientfiles


@dataclass
class Co:
    name: str
    slug: str


ACME = Co("Acme GmbH", "acme-gmbh")


def touch(path: Path, data: bytes = b"x", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


# ------------------------------------------------------------------ root


def test_root_unset_is_off():
    assert clientfiles.root({}) is None
    assert clientfiles.root({"client_files_root": "   "}) is None


def test_root_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert clientfiles.root({"client_files_root": "~/Clients"}) == tmp_path / "Clients"


def test_root_inside_data_folder_is_a_problem(tmp_path):
    data = tmp_path / "crm"
    data.mkdir()
    assert clientfiles.root_problem(data / "clients", data)
    assert clientfiles.root_problem(tmp_path, data)        # holds the data folder
    assert clientfiles.root_problem(tmp_path / "clients", data) == ""
    assert clientfiles.root_problem(None, data) == ""


# ------------------------------------------------------------ find_folder


def test_find_exact_name(tmp_path):
    (tmp_path / "Acme GmbH").mkdir()
    assert clientfiles.find_folder(tmp_path, ACME) == tmp_path / "Acme GmbH"


def test_find_slug(tmp_path):
    (tmp_path / "acme-gmbh").mkdir()
    assert clientfiles.find_folder(tmp_path, ACME) == tmp_path / "acme-gmbh"


def test_find_other_case(tmp_path):
    (tmp_path / "acme gmbh").mkdir()
    found = clientfiles.find_folder(tmp_path, ACME)
    assert found is not None and found.name.casefold() == "acme gmbh"


def test_find_other_unicode_form(tmp_path):
    co = Co("Café Example", "cafe-example")
    decomposed = unicodedata.normalize("NFD", "café example")
    (tmp_path / decomposed).mkdir()
    found = clientfiles.find_folder(tmp_path, co)
    assert found is not None
    assert unicodedata.normalize("NFC", found.name).casefold() == "café example"


def test_find_none(tmp_path):
    (tmp_path / "Other BV").mkdir()
    touch(tmp_path / "Acme GmbH.txt")           # a file is not a folder
    assert clientfiles.find_folder(tmp_path, ACME) is None
    assert clientfiles.find_folder(None, ACME) is None
    assert clientfiles.find_folder(tmp_path / "missing", ACME) is None


def test_folder_name_is_safe():
    assert clientfiles.folder_name(Co("Example: A/B", "x")) == "B"
    assert clientfiles.folder_name(Co("Example Labs BV", "x")) == "Example Labs BV"


def test_create_needs_the_root(tmp_path):
    with pytest.raises(ValueError):
        clientfiles.create(tmp_path / "missing", ACME)
    assert not (tmp_path / "missing").exists()
    made = clientfiles.create(tmp_path, ACME)
    assert made == tmp_path / "Acme GmbH" and made.is_dir()
    (tmp_path / "Acme GmbH").rmdir()
    (tmp_path / "acme-gmbh").mkdir()
    assert clientfiles.create(tmp_path, ACME) == tmp_path / "acme-gmbh"  # not a second one


# ---------------------------------------------------------------- resolve


def test_resolve_accepts_nested(tmp_path):
    touch(tmp_path / "a" / "b" / "deck.pptx")
    assert clientfiles.resolve(tmp_path, "a/b/deck.pptx") == (tmp_path / "a/b/deck.pptx").resolve()


@pytest.mark.parametrize("rel", ["../secret.txt", "a/../../secret.txt"])
def test_resolve_refuses_dotdot(tmp_path, rel):
    folder = tmp_path / "Acme GmbH"
    folder.mkdir()
    touch(tmp_path / "secret.txt")
    with pytest.raises(ValueError):
        clientfiles.resolve(folder, rel)


def test_resolve_refuses_absolute(tmp_path):
    folder = tmp_path / "Acme GmbH"
    folder.mkdir()
    secret = touch(tmp_path / "secret.txt")
    with pytest.raises(ValueError):
        clientfiles.resolve(folder, str(secret))


def test_resolve_refuses_symlink_out(tmp_path):
    folder = tmp_path / "Acme GmbH"
    folder.mkdir()
    secret = touch(tmp_path / "secret.txt")
    (folder / "link.txt").symlink_to(secret)
    with pytest.raises(ValueError):
        clientfiles.resolve(folder, "link.txt")


def test_resolve_refuses_missing_and_nul(tmp_path):
    with pytest.raises(ValueError):
        clientfiles.resolve(tmp_path, "nope.md")
    with pytest.raises(ValueError):
        clientfiles.resolve(tmp_path, "a\x00b")


# ------------------------------------------------------------- list_files


def test_list_skips_hidden_lock_and_finder_files(tmp_path):
    touch(tmp_path / "notes.md")
    touch(tmp_path / ".hidden")
    touch(tmp_path / ".DS_Store")
    touch(tmp_path / "~$lock.pptx")
    touch(tmp_path / ".git" / "config")
    touch(tmp_path / "Icon\r")
    names = [f.rel for f in clientfiles.list_files(tmp_path).files]
    assert names == ["notes.md"]


def test_list_depth_is_at_most_three(tmp_path):
    touch(tmp_path / "1" / "2" / "3.md")
    touch(tmp_path / "1" / "2" / "3" / "4.md")
    rels = {f.rel for f in clientfiles.list_files(tmp_path).files}
    assert "1/2/3.md" in rels and "1/2/3" in rels
    assert "1/2/3/4.md" not in rels


def test_list_sorts_newest_first_and_truncates(tmp_path):
    for n in range(5):
        touch(tmp_path / f"f{n}.md", mtime=1_700_000_000 + n * 60)
    listing = clientfiles.list_files(tmp_path, limit=3)
    assert [f.rel for f in listing.files] == ["f4.md", "f3.md", "f2.md"]
    assert listing.truncated and listing.total == 5
    full = clientfiles.list_files(tmp_path)
    assert not full.truncated and len(full.files) == 5


def test_list_marks_folders_and_sizes(tmp_path):
    touch(tmp_path / "deck.pptx", b"12345")
    (tmp_path / "Contracts").mkdir()
    by = {f.rel: f for f in clientfiles.list_files(tmp_path).files}
    assert by["deck.pptx"].size == 5 and not by["deck.pptx"].is_dir
    assert by["Contracts"].is_dir and by["Contracts"].size == 0
    assert by["deck.pptx"].name == "deck.pptx"


def test_list_does_not_follow_symlinked_folders(tmp_path):
    folder = tmp_path / "Acme GmbH"
    touch(folder / "real" / "a.md")
    (folder / "loop").symlink_to(folder / "real")
    outside = tmp_path / "outside"
    touch(outside / "secret.md")
    (folder / "out").symlink_to(outside)
    rels = {f.rel for f in clientfiles.list_files(folder).files}
    assert "loop" in rels and "loop/a.md" not in rels
    assert "out" not in rels and "out/secret.md" not in rels


# ---------------------------------------------------------- open_command


@pytest.mark.parametrize("platform, opener", [("darwin", ["open"]), ("linux", ["xdg-open"])])
@pytest.mark.parametrize("name", ["deck.pptx", "notes.md", "sheet.xlsx"])
def test_documents_open(tmp_path, platform, opener, name):
    path = touch(tmp_path / name)
    path.chmod(0o644)
    assert clientfiles.open_command(path, platform) == [*opener, str(path)]


@pytest.mark.parametrize("name", ["run.command", "x.sh", "Tool.py", "setup.pkg"])
def test_risky_types_are_revealed(tmp_path, name):
    path = touch(tmp_path / name)
    path.chmod(0o644)
    assert clientfiles.open_command(path, "darwin") == ["open", "-R", str(path)]
    assert clientfiles.open_command(path, "linux") == ["xdg-open", str(tmp_path)]


def test_app_bundle_and_folders_are_revealed(tmp_path):
    app = tmp_path / "Example.app"
    (app / "Contents").mkdir(parents=True)
    folder = tmp_path / "Contracts"
    folder.mkdir()
    for path in (app, folder):
        assert clientfiles.open_command(path, "darwin") == ["open", "-R", str(path)]


def test_exec_bit_is_revealed(tmp_path):
    path = touch(tmp_path / "report.pdf")
    path.chmod(0o755)
    assert clientfiles.open_command(path, "darwin") == ["open", "-R", str(path)]


def test_windows_commands(tmp_path):
    path = touch(tmp_path / "deck.pptx")
    assert clientfiles.open_command(path, "win32") == ["startfile", str(path)]
    assert clientfiles.reveal_command(path, "win32") == ["explorer", f"/select,{path}"]


def test_run_has_no_shell_and_no_output(tmp_path):
    calls = []
    clientfiles.run(["open", "x"], runner=lambda cmd, **kw: calls.append((cmd, kw)))
    (cmd, kw), = calls
    assert cmd == ["open", "x"] and "shell" not in kw
    assert kw["stdin"] == kw["stdout"] == kw["stderr"] == clientfiles.subprocess.DEVNULL
