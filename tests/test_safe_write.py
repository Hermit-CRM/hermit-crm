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

"""Crash-safe saving (audit S5, 2026-10-31 action plan row 12; 2026-09-18 item 12).

A record is written to a temporary file next to it and renamed over the real
name, so a write that stops half way leaves the old file whole. The way these
tests stop a write half way: text with a lone surrogate cannot be encoded as
UTF-8, so the write fails after the file was opened. `Path.write_text` has
truncated the real file by then; a temporary file takes the hit instead.
"""

from __future__ import annotations

import os
import stat
import subprocess
import threading
import time
from pathlib import Path

import pytest

from hermitcrm import migrations, safewrite
from hermitcrm import store as store_mod

BROKEN = "---\nname: half\n---\ncut off here \ud800 and the rest never lands\n"


def _files(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


# --------------------------------------------------------------- the helper

@pytest.mark.parametrize("text", [
    "",
    "plain\n",
    "---\nname: Müller & Söhne\n---\n\nNotes — with ünïcode ✓\n",
    "no newline at the end",
    "two\n\nblank\n\n\nlines\n",
    "tab\tand trailing space \n",
])
def test_same_bytes_as_write_text(tmp_path, text):
    plain, safe = tmp_path / "plain.md", tmp_path / "safe.md"
    plain.write_text(text, encoding="utf-8")
    safewrite.write_text(safe, text)
    assert safe.read_bytes() == plain.read_bytes()


def test_replaces_an_existing_file(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("old\n", encoding="utf-8")
    safewrite.write_text(path, "new\n")
    assert path.read_text(encoding="utf-8") == "new\n"
    assert _files(tmp_path) == ["a.md"]


def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("old and whole\n", encoding="utf-8")
    with pytest.raises(UnicodeEncodeError):
        safewrite.write_text(path, BROKEN)
    assert path.read_text(encoding="utf-8") == "old and whole\n"
    assert _files(tmp_path) == ["a.md"]


def test_a_failure_at_the_rename_keeps_the_old_file(tmp_path, monkeypatch):
    path = tmp_path / "a.md"
    path.write_text("old and whole\n", encoding="utf-8")

    def power_cut(src, dst):
        raise OSError("simulated power cut before the rename")
    monkeypatch.setattr(safewrite.os, "replace", power_cut)
    with pytest.raises(OSError):
        safewrite.write_text(path, "new\n")
    assert path.read_text(encoding="utf-8") == "old and whole\n"
    assert _files(tmp_path) == ["a.md"]


def test_a_new_file_gets_the_same_permissions_as_write_text(tmp_path):
    plain, safe = tmp_path / "plain.md", tmp_path / "safe.md"
    plain.write_text("x\n", encoding="utf-8")
    safewrite.write_text(safe, "x\n")
    assert stat.S_IMODE(safe.stat().st_mode) == stat.S_IMODE(plain.stat().st_mode)


def test_an_existing_file_keeps_its_permissions(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("old\n", encoding="utf-8")
    path.chmod(0o640)
    safewrite.write_text(path, "new\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_a_symlinked_record_is_written_through_the_link(tmp_path):
    real = tmp_path / "elsewhere" / "company.md"
    real.parent.mkdir()
    real.write_text("old\n", encoding="utf-8")
    link = tmp_path / "company.md"
    link.symlink_to(real)
    safewrite.write_text(link, "new\n")
    assert link.is_symlink()
    assert real.read_text(encoding="utf-8") == "new\n"


# --------------------------------------------------------- the store writes

def test_interrupted_company_write_keeps_the_old_file(store, monkeypatch):
    c = store.create_company("Example Widgets", website="example.com")
    path = store.company_dir(c.slug) / "company.md"
    before = path.read_bytes()
    monkeypatch.setattr(store_mod, "build_file", lambda meta, body: BROKEN)
    with pytest.raises(UnicodeEncodeError):
        store.write_company(c)
    assert path.read_bytes() == before
    assert not [p for p in path.parent.iterdir() if p.name.startswith(".")]


def test_interrupted_contact_write_keeps_the_old_file(store, monkeypatch):
    c = store.create_company("Example Widgets")
    contact = store.create_contact(c.slug, "Ada", "Example")
    path = store.contact_file(c.slug, contact.slug)
    before = path.read_bytes()
    monkeypatch.setattr(store_mod, "build_file", lambda meta, body: BROKEN)
    with pytest.raises(UnicodeEncodeError):
        store.write_contact(c.slug, contact)
    assert path.read_bytes() == before
    assert not [p for p in path.parent.iterdir() if p.name.startswith(".")]


def test_interrupted_interaction_write_keeps_the_old_file(store, monkeypatch):
    c = store.create_company("Example Widgets")
    it = store.create_interaction(c.slug, channel="call", direction="out",
                                  subject="Intro", body="Talked.\n")
    path = store.interaction_file(c.slug, it.id)
    before = path.read_bytes()
    monkeypatch.setattr(store_mod, "build_file", lambda meta, body: BROKEN)
    with pytest.raises(UnicodeEncodeError):
        store.write_interaction(c.slug, it)
    assert path.read_bytes() == before
    assert not [p for p in path.parent.iterdir() if p.name.startswith(".")]


# ------------------------------------------------------- the migration writes

def test_interrupted_migration_write_keeps_the_old_file(tmp_path, monkeypatch):
    folder = tmp_path / "outreach"
    folder.mkdir()
    path = folder / "item.md"
    path.write_text("---\nstate: draft\n---\nHello.\n", encoding="utf-8")
    before = path.read_bytes()
    step = migrations.Migration(99, "test step", "outreach/*.md",
                                lambda meta: {**meta, "added": "yes"})
    monkeypatch.setattr(migrations, "build_file", lambda meta, body: BROKEN)
    with pytest.raises(UnicodeEncodeError):
        migrations._run([step], tmp_path, write=True)
    assert path.read_bytes() == before
    assert _files(folder) == ["item.md"]


def test_interrupted_note_move_leaves_no_cut_off_interaction(tmp_path, monkeypatch):
    company = tmp_path / "companies" / "example"
    company.mkdir(parents=True)
    path = company / "company.md"
    path.write_text("---\nname: Example\ncreated: 2026-09-01\n---\n\nAn old note.\n",
                    encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(migrations, "build_file", lambda meta, body: BROKEN)
    with pytest.raises(UnicodeEncodeError):
        migrations.m19_company_notes(
            tmp_path, {"companies/example/company.md": {"name": "Example",
                                                        "created": "2026-09-01"}},
            write=True)
    folder = company / "interactions"
    assert not folder.exists() or _files(folder) == []
    assert path.read_bytes() == before


# ----------------------------------------------- migrations take the lock

def test_ensure_current_waits_for_the_store_lock(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "companies").mkdir()
    (tmp_path / migrations.FORMAT_FILE).write_text(f"{migrations.LATEST - 1}\n",
                                                   encoding="utf-8")
    holder = store_mod.WriteLock(tmp_path)
    done = threading.Event()

    def migrate():
        migrations.ensure_current(tmp_path)
        done.set()

    with holder:  # another process (or Store) is writing
        worker = threading.Thread(target=migrate, daemon=True)
        worker.start()
        time.sleep(0.3)
        assert not done.is_set(), "migrated while another writer held the lock"
    worker.join(timeout=10)
    assert done.is_set()
    assert migrations.current_format(tmp_path) == migrations.LATEST


def test_ensure_current_on_a_current_folder_does_not_wait(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "companies").mkdir()
    migrations.write_format(tmp_path)
    holder = store_mod.WriteLock(tmp_path)
    with holder:  # a long write elsewhere must not stall every command
        result: list[str] = []
        worker = threading.Thread(
            target=lambda: result.append(migrations.ensure_current(tmp_path)),
            daemon=True)
        worker.start()
        worker.join(timeout=5)
        assert result == [""]


def test_temp_names_are_hidden_and_never_records(tmp_path):
    # A crash between the write and the rename can leave the temporary file.
    # Its name must not look like a record to `load` (which reads *.md).
    name = safewrite.temp_name(tmp_path / "company.md")
    assert name.name.startswith(".")
    assert not name.name.endswith(".md")
    assert name.parent == tmp_path
    assert os.path.basename(str(name)) != "company.md"
