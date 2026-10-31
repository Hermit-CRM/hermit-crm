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

"""attachments.py and the store: files owned by interactions, stored by content
(docs/superpowers/plans/2026-10-31-attachments.md, Task 1)."""

from __future__ import annotations

import unicodedata

import pytest

from hermitcrm import attachments, migrations
from hermitcrm.attachments import Attachment, Incoming
from hermitcrm.models import ValidationError

PDF = b"%PDF-1.4 example proposal\n"


@pytest.fixture
def seeded(store):
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe")
    return store


def folder(store):
    return store.root / "companies" / "acme" / "attachments"


@pytest.mark.parametrize("raw", [
    "../../.git/config", "a\x00.pdf", "CON", "." * 5, "x" * 300 + ".pdf", "/etc/passwd",
    "..\\..\\evil.exe", "report\n.pdf",
])
def test_safe_name_stays_inside(raw):
    name = attachments.safe_name(raw)
    assert "/" not in name and "\\" not in name and "\x00" not in name
    assert "\n" not in name and not name.startswith(".")
    assert 0 < len(name) <= 100
    assert name.upper().split(".")[0] != "CON"


def test_safe_name_keeps_the_extension_of_a_long_name():
    assert attachments.safe_name("x" * 300 + ".pdf").endswith(".pdf")


def test_safe_name_composed_and_decomposed_agree():
    composed = unicodedata.normalize("NFC", "é.pdf")
    decomposed = unicodedata.normalize("NFD", "é.pdf")
    assert attachments.safe_name(composed) == attachments.safe_name(decomposed)


def test_stored_name_is_content_addressed(tmp_path):
    a = attachments.stored_name(PDF, "Proposal v2.pdf")
    assert a == attachments.stored_name(PDF, "Proposal v2.pdf")
    assert a != attachments.stored_name(PDF + b"x", "Proposal v2.pdf")
    assert a.endswith("-Proposal v2.pdf") and len(a.split("-")[0]) == 12
    path = tmp_path / a
    path.write_bytes(PDF)
    assert attachments.intact(path)
    path.write_bytes(PDF + b"!")
    assert not attachments.intact(path)


def test_media_type_ignores_the_client():
    assert attachments.media_type("x.svg") == "image/svg+xml"
    svg = Attachment("f-x.svg", "x.svg", 1, "image/svg+xml")
    png = Attachment("f-x.png", "x.png", 1, "image/png")
    assert attachments.disposition(svg) == "attachment"
    assert attachments.disposition(png) == "inline"
    assert attachments.media_type("noextension") == "application/octet-stream"


def test_meta_round_trip_and_lenient_reader():
    items = [Attachment("abc123abc123-a.pdf", "a.pdf", 5, "application/pdf")]
    meta = attachments.to_meta(items)
    assert list(meta[0]) == ["file", "name", "size", "type"]
    assert attachments.from_meta(meta) == items
    assert attachments.from_meta([{"file": "x"}, "junk", None, {"name": "n"}]) == []
    assert attachments.from_meta("not a list") == []


def test_create_interaction_with_files_round_trips(seeded, tmp_path):
    it = seeded.create_interaction("acme", "note", "", contact="jane-doe", body="Sent it.",
                                   attachments=[Incoming("Proposal v2.pdf", PDF)])
    (att,) = it.attachments
    assert att.name == "Proposal v2.pdf" and att.size == len(PDF)
    assert att.type == "application/pdf"
    assert (folder(seeded) / att.file).read_bytes() == PDF
    path = seeded.interaction_file("acme", it.id)
    text = path.read_text(encoding="utf-8")
    keys = [line.split(":")[0] for line in text.split("---")[1].strip().splitlines()]
    assert keys.index("attachments") == keys.index("source") + 1  # no message_id on a note
    seeded.load()
    again = seeded.get("acme").interactions[0]
    assert again.attachments == [att]
    seeded.write_interaction("acme", again)
    assert path.read_text(encoding="utf-8") == text  # same data, same bytes


def test_attachments_key_follows_message_id(seeded):
    it = seeded.create_interaction("acme", "email", "in", contact="jane-doe", body="Hi",
                                   message_id="<m1@example.com>",
                                   attachments=[Incoming("a.pdf", PDF)])
    text = seeded.interaction_file("acme", it.id).read_text(encoding="utf-8")
    assert text.index("message_id:") < text.index("attachments:") < text.index("\n---\n", 4)


def test_no_attachments_key_when_empty(seeded):
    it = seeded.create_interaction("acme", "note", "", body="Plain.")
    assert "attachments" not in seeded.interaction_file("acme", it.id).read_text()
    assert not (folder(seeded)).exists()


def test_create_message_mentions_files(seeded, messages):
    seeded.create_interaction("acme", "note", "", body="x",
                              attachments=[Incoming("a.pdf", PDF), Incoming("b.txt", b"b")])
    assert messages[-1].endswith("; 2 files")


def test_too_big_writes_nothing(seeded, messages):
    (seeded.root / "config.toml").write_text("attachment_max_mb = 1\n")
    del messages[:]
    seeded.take_touched()
    with pytest.raises(ValidationError) as exc:
        seeded.create_interaction("acme", "note", "", body="x",
                                  attachments=[Incoming("big.bin", b"0" * (1024 * 1024 + 1))])
    assert "files" in exc.value.errors
    assert not folder(seeded).exists()
    assert seeded.get("acme").interactions == []
    assert not list((seeded.root / "companies" / "acme").glob("interactions/*"))
    assert messages == [] and seeded.take_touched() == []


def test_shared_file_removed_with_last_reference(seeded):
    one = seeded.create_interaction("acme", "note", "", body="one",
                                    attachments=[Incoming("a.pdf", PDF)])
    two = seeded.create_interaction("acme", "note", "", body="two",
                                    attachments=[Incoming("copy of a.pdf", PDF)])
    # Same bytes under two names are two stored files; the same name is one.
    three = seeded.create_interaction("acme", "note", "", body="three",
                                      attachments=[Incoming("a.pdf", PDF)])
    shared = one.attachments[0].file
    assert three.attachments[0].file == shared and two.attachments[0].file != shared
    assert seeded.referenced_files("acme")[shared] == 2
    seeded.delete_interaction("acme", one.id)
    assert (folder(seeded) / shared).exists()
    seeded.delete_interaction("acme", three.id)
    assert not (folder(seeded) / shared).exists()
    assert (folder(seeded) / two.attachments[0].file).exists()


def test_same_name_different_bytes_are_two_files(seeded):
    a = seeded.create_interaction("acme", "note", "", body="a",
                                  attachments=[Incoming("deck.pdf", PDF)])
    b = seeded.create_interaction("acme", "note", "", body="b",
                                  attachments=[Incoming("deck.pdf", PDF + b"v2")])
    assert a.attachments[0].file != b.attachments[0].file
    assert len(list(folder(seeded).iterdir())) == 2


def test_rekeying_the_interaction_keeps_files(seeded):
    it = seeded.create_interaction("acme", "note", "", body="x",
                                   attachments=[Incoming("a.pdf", PDF)])
    moved = seeded.update_interaction("acme", it.id, date="2026-01-02T09:00")
    assert moved.id != it.id
    assert moved.attachments == it.attachments
    assert (folder(seeded) / it.attachments[0].file).exists()
    seeded.load()
    assert seeded.get("acme").interactions[0].attachments == it.attachments


def test_update_adds_and_removes_files(seeded, messages):
    it = seeded.create_interaction("acme", "note", "", body="x")
    del messages[:]
    added = seeded.update_interaction("acme", it.id, add_files=[Incoming("a.pdf", PDF)])
    assert messages == [f"interaction: acme {it.id} files added"]
    file = added.attachments[0].file
    assert (folder(seeded) / file).exists()
    removed = seeded.update_interaction("acme", it.id, remove_files=[file])
    assert removed.attachments == [] and not (folder(seeded) / file).exists()
    assert messages[-1] == f"interaction: acme {it.id} files removed"
    assert "attachments" not in seeded.interaction_file("acme", it.id).read_text()


def test_remove_of_a_file_the_note_does_not_have_is_refused(seeded):
    it = seeded.create_interaction("acme", "note", "", body="x")
    with pytest.raises(ValidationError):
        seeded.update_interaction("acme", it.id, remove_files=["0123456789ab-nope.pdf"])


def test_attachment_path_is_contained(seeded):
    with pytest.raises(ValidationError):
        seeded.attachment_path("acme", "../company.md")


def test_merge_companies_moves_files(seeded):
    seeded.create_company("Acme Software")
    it = seeded.create_interaction("acme-software", "note", "", body="x",
                                   attachments=[Incoming("a.pdf", PDF)])
    seeded.merge_companies("acme", "acme-software")
    moved = seeded.get("acme").interactions[0]
    assert moved.attachments == it.attachments
    assert (folder(seeded) / it.attachments[0].file).read_bytes() == PDF
    assert not (seeded.root / "companies" / "acme-software").exists()


def test_merge_contacts_keeps_files(seeded):
    seeded.create_contact("acme", "Janet", "Doe")
    it = seeded.create_interaction("acme", "note", "", contact="janet-doe", body="x",
                                   attachments=[Incoming("a.pdf", PDF)])
    seeded.merge_contacts("acme", "jane-doe", "janet-doe")
    (moved,) = [i for i in seeded.get("acme").interactions if i.attachments]
    assert moved.contact == "jane-doe" and moved.attachments == it.attachments
    assert (folder(seeded) / it.attachments[0].file).exists()


def test_migration_20_is_a_noop_and_idempotent(tmp_path):
    migration = next(m for m in migrations.MIGRATIONS if m.version == 20)
    meta = {"date": "2026-09-14T10:30", "channel": "note"}
    assert migration.apply(dict(meta)) == meta
    assert migration.apply(migration.apply(dict(meta))) == meta
    assert migrations.LATEST == 20


# ------------------------------------------------- hermitcrm check and the CLI

from hermitcrm import cli as crm


def raw_interaction(store, text: str):
    """Rewrite the front matter of the only interaction, as a hand edit would."""
    path = store.interaction_file("acme", store.get("acme").interactions[0].id)
    path.write_text(text(path.read_text()), encoding="utf-8")


def test_check_reports_a_missing_attachment_as_an_error(seeded):
    it = seeded.create_interaction("acme", "note", "", body="x",
                                   attachments=[Incoming("a.pdf", PDF)])
    seeded.attachment_path("acme", it.attachments[0].file).unlink()
    text, code = crm.cmd_check(seeded)
    assert code == 1
    assert f"companies/acme/interactions/{it.id}.md" in text and "a.pdf" in text
    assert "missing" in text


def test_check_warns_about_an_orphan_and_a_changed_file(seeded):
    it = seeded.create_interaction("acme", "note", "", body="x",
                                   attachments=[Incoming("a.pdf", PDF)])
    seeded.attachment_path("acme", it.attachments[0].file).write_bytes(PDF + b"tampered")
    orphan = seeded.attachment_path("acme", "0123456789ab-orphan.pdf")
    orphan.write_bytes(b"nobody uses me")
    text, code = crm.cmd_check(seeded)
    assert code == 0                       # warnings never change the exit code
    assert f"companies/acme/attachments/{it.attachments[0].file}: content does not match" in text
    assert "companies/acme/attachments/0123456789ab-orphan.pdf: no note uses this file" in text
    assert text.splitlines()[-1].startswith("OK: ")


def test_check_warns_about_a_file_over_the_cap(seeded):
    seeded.create_interaction("acme", "note", "", body="x",
                              attachments=[Incoming("big.bin", b"0" * (1024 * 1024 + 1))])
    (seeded.root / "config.toml").write_text("attachment_max_mb = 1\n")
    text, code = crm.cmd_check(seeded)
    assert code == 0 and "larger than attachment_max_mb (1 MB)" in text


def test_check_reports_an_attachment_entry_it_cannot_read(seeded):
    seeded.create_interaction("acme", "note", "", body="x")
    raw_interaction(seeded, lambda t: t.replace("source: manual\n",
                                                "source: manual\nattachments:\n  - {file: nope}\n"))
    text, code = crm.cmd_check(seeded)
    assert code == 1 and "attachments" in text and "not readable" in text


def test_check_is_quiet_when_all_is_well(seeded):
    seeded.create_interaction("acme", "note", "", body="x", attachments=[Incoming("a.pdf", PDF)])
    text, code = crm.cmd_check(seeded)
    assert code == 0 and text.startswith("OK: 1 companies")


@pytest.fixture
def outside(tmp_path_factory):
    folder = tmp_path_factory.mktemp("downloads")
    (folder / "Proposal v2.pdf").write_bytes(PDF)
    (folder / "notes.txt").write_bytes(b"hello")
    return folder


def test_attach_creates_a_note_with_the_files(seeded, outside, messages):
    del messages[:]
    text, code = crm.cmd_attach(seeded, "acme", [str(outside / "Proposal v2.pdf"),
                                                 str(outside / "notes.txt")],
                                contact="jane-doe")
    assert code == 0 and "2 files" in text
    (note,) = seeded.get("acme").interactions
    assert note.contact == "jane-doe" and note.subject == "Files: Proposal v2.pdf, notes.txt"
    assert all(a.file in text for a in note.attachments)
    assert len(messages) == 1


def test_attach_uses_the_note_text_when_given(seeded, outside):
    crm.cmd_attach(seeded, "acme", [str(outside / "notes.txt")], note="Call notes.")
    (note,) = seeded.get("acme").interactions
    assert note.body == "Call notes.\n" and note.subject == ""


def test_attach_to_an_existing_interaction(seeded, outside):
    it = seeded.create_interaction("acme", "note", "", body="x")
    text, code = crm.cmd_attach(seeded, "acme", [str(outside / "notes.txt")], to=it.id)
    assert code == 0
    assert [a.name for a in seeded.get("acme").interactions[0].attachments] == ["notes.txt"]


def test_attach_refuses_what_it_cannot_keep(seeded, outside, tmp_path):
    (seeded.root / "config.toml").write_text("attachment_max_mb = 1\n")
    big = outside / "big.bin"
    big.write_bytes(b"0" * (1024 * 1024 + 1))
    for args, kw, word in [
        ([str(outside)], {}, "not a file"),
        ([str(outside / "missing.pdf")], {}, "not a file"),
        ([str(big)], {}, "larger than 1 MB"),
        ([str(outside / "notes.txt")], {"contact": "nobody"}, "unknown contact"),
        ([str(outside / "notes.txt")], {"to": "no-such-id"}, "unknown interaction"),
        ([], {}, "no files"),
    ]:
        text, code = crm.cmd_attach(seeded, "acme", args, **kw)
        assert code == 1 and word in text, (args, text)
    text, code = crm.cmd_attach(seeded, "nope", [str(outside / "notes.txt")])
    assert code == 1 and "unknown company" in text
    assert seeded.get("acme").interactions == []


def test_attachments_command_lists_files_by_company(seeded, outside):
    assert crm.cmd_attachments(seeded, "") == ("No attachments yet. Add one with: "
                                               "hermitcrm attach <company> <file>", 0)
    it = seeded.create_interaction("acme", "note", "", body="x",
                                   attachments=[Incoming("a.pdf", PDF)])
    text, code = crm.cmd_attachments(seeded, "")
    assert code == 0
    assert text == f"acme | {it.attachments[0].file} | {len(PDF)} B | {it.id}"
    assert crm.cmd_attachments(seeded, "acme") == (text, 0)
    assert crm.cmd_attachments(seeded, "nope")[1] == 1


def test_attach_commands_are_wired_to_the_parser(seeded, outside, tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=seeded.root, check=True)
    code = crm.main(["attach", "acme", str(outside / "notes.txt")], root=seeded.root)
    assert code == 0
    assert crm.main(["attachments"], root=seeded.root) == 0
    log = subprocess.run(["git", "log", "--format=%s"], cwd=seeded.root, capture_output=True,
                         text=True).stdout
    assert "interaction: acme" in log and "1 file" in log
