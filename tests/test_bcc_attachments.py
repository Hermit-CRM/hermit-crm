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

"""Attachments of BCC'd and forwarded mail: kept on the logged interaction, or in
the inbox until a person files the mail
(docs/superpowers/plans/2026-10-31-attachments.md, Task 7)."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from email.message import EmailMessage

import pytest

from hermitcrm import bcc
from hermitcrm.attachments import Attachment
from test_bcc import (ME, QUEUE, SETTINGS, FakeBox, client, inbox_for, last_commit,  # noqa: F401
                      raw_mail, repo, seed)
from conftest import FIXED_NOW

PDF = b"%PDF-1.4 proposal\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def mail(*files, to="Jane Doe <jane@acme.de>", frm=ME, mid="<a1@work.example.com>",
         html=None, related=()) -> bytes:
    """A mail with attachments: files are (name or None, bytes, maintype, subtype)."""
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = frm, to, "Proposal"
    msg["Date"], msg["Message-ID"] = "Mon, 14 Sep 2026 10:30:00 -0000", mid
    if html:
        msg.set_content(html, subtype="html")
        for name, data, maintype, subtype, cid in related:
            msg.add_related(data, maintype, subtype, cid=cid, filename=name,
                            disposition="inline")
    else:
        msg.set_content("Hi Jane,\n\nsee the attachment.\n\nSam\n")
    for name, data, maintype, subtype in files:
        kwargs = {"filename": name} if name else {}
        msg.add_attachment(data, maintype=maintype, subtype=subtype, **kwargs)
    return bytes(msg)


PROPOSAL = ("Proposal v2.pdf", PDF, "application", "pdf")


def attachments_of(store, company="acme"):
    return [a for i in store.get(company).interactions for a in i.attachments]


def stored(store, company, att: Attachment):
    return store.attachment_path(company, att.file)


# ------------------------------------------------------------------- parsing


def test_parse_mail_lists_the_attachment():
    parsed = bcc.parse_mail(mail(PROPOSAL), FIXED_NOW)
    assert [(f.name, f.data) for f in parsed.attachments] == [("Proposal v2.pdf", PDF)]
    assert parsed.skipped_attachments == 0


def test_signature_logo_and_calendar_part_are_ignored():
    raw = mail(("invite.ics", b"BEGIN:VCALENDAR\nEND:VCALENDAR\n", "text", "calendar"),
               ("smime.p7s", b"sig", "application", "pkcs7-signature"), PROPOSAL,
               html="<p>Hi Jane</p><img src='cid:logo1'>",
               related=[("logo.png", PNG, "image", "png", "<logo1>")])
    assert [f.name for f in bcc.parse_mail(raw, FIXED_NOW).attachments] == ["Proposal v2.pdf"]


def test_a_named_attachment_that_is_an_image_is_kept():
    raw = mail(("pricing page.png", PNG, "image", "png"))
    assert [f.name for f in bcc.parse_mail(raw, FIXED_NOW).attachments] == ["pricing page.png"]


def test_unnamed_part_gets_a_name_from_its_type():
    raw = mail((None, PNG, "image", "png"), (None, PDF, "application", "pdf"))
    names = [f.name for f in bcc.parse_mail(raw, FIXED_NOW).attachments]
    assert names == ["image.png", "attachment.pdf"]


def test_zero_byte_attachment_is_ignored():
    raw = mail(("empty.pdf", b"", "application", "pdf"), PROPOSAL)
    assert [f.name for f in bcc.parse_mail(raw, FIXED_NOW).attachments] == ["Proposal v2.pdf"]


def test_the_same_file_twice_in_one_mail_is_one_file():
    raw = mail(PROPOSAL, PROPOSAL)
    assert len(bcc.parse_mail(raw, FIXED_NOW).attachments) == 1


def test_oversize_attachments_are_counted_not_kept():
    big = ("big.bin", b"0" * (1024 * 1024 + 1), "application", "octet-stream")
    parsed = bcc.parse_mail(mail(big, PROPOSAL), FIXED_NOW, limit=1024 * 1024)
    assert [f.name for f in parsed.attachments] == ["Proposal v2.pdf"]
    assert parsed.skipped_attachments == 1


def test_modes_off_documents_all():
    logo = [("logo.png", PNG, "image", "png", "<logo1>")]
    big_inline = [("hero.png", PNG + b"\x00" * 30000, "image", "png", "<hero>")]
    raw = mail(PROPOSAL, html="<p>x</p>", related=logo + big_inline)
    names = lambda mode: sorted(  # noqa: E731
        f.name for f in bcc.parse_mail(raw, FIXED_NOW, mode=mode).attachments)
    assert names("off") == []
    assert names("documents") == ["Proposal v2.pdf"]
    assert names("all") == ["Proposal v2.pdf", "hero.png"]   # the 70-byte logo stays out


def test_rfc2231_and_encoded_word_filenames_decode():
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = ME, "jane@acme.de", "x"
    msg.set_content("x")
    msg.add_attachment(PDF, maintype="application", subtype="pdf",
                       filename="Überblick – Angebot.pdf")           # filename*=UTF-8''...
    raw = bytes(msg).replace(b"Content-Type: application/pdf",
                             b"Content-Type: application/pdf", 1)
    assert [f.name for f in bcc.parse_mail(raw, FIXED_NOW).attachments] == [
        "Überblick – Angebot.pdf"]
    word = bytes(msg).decode().replace(
        "filename*=utf-8''%C3%9Cberblick%20%E2%80%93%20Angebot.pdf",
        'filename="=?utf-8?q?Angebot_=C3=9Cberblick.pdf?="').encode()
    assert [f.name for f in bcc.parse_mail(word, FIXED_NOW).attachments] == [
        "Angebot Überblick.pdf"]


def test_settings_read_the_mode_from_config():
    assert bcc.settings_from_config({}).attachments == "documents"
    assert bcc.settings_from_config({"bcc_attachments": "ALL"}).attachments == "all"
    assert bcc.settings_from_config({"bcc_attachments": "off"}).attachments == "off"
    assert bcc.settings_from_config({"bcc_attachments": "nonsense"}).attachments == "documents"


# ------------------------------------------------------------------- logging


def test_pdf_attachment_lands_on_the_logged_interaction(store):
    seed(store)
    result = bcc.import_mails(store, inbox_for(store), [mail(PROPOSAL)], SETTINGS, apply=True)
    (att,) = attachments_of(store)
    assert att.name == "Proposal v2.pdf" and stored(store, "acme", att).read_bytes() == PDF
    assert result.attachments == 1
    assert "1 attachment kept" in result.summary()
    assert "(+1 file)" in result.lines[0]


def test_a_mail_without_attachments_reads_as_before(store):
    seed(store)
    result = bcc.import_mails(store, inbox_for(store), [raw_mail()], SETTINGS, apply=True)
    assert "attachment" not in result.summary() and "file" not in result.lines[0]
    assert not (store.root / "companies" / "acme" / "attachments").exists()


def test_a_dry_run_writes_no_files(store):
    seed(store)
    result = bcc.import_mails(store, inbox_for(store), [mail(PROPOSAL)], SETTINGS, apply=False)
    assert result.logged == 1 and attachments_of(store) == []
    assert not (store.root / "companies" / "acme" / "attachments").exists()


def test_oversize_attachment_skipped_mail_still_logged_and_summary_says_so(store):
    seed(store)
    (store.root / "config.toml").write_text("attachment_max_mb = 1\n")
    big = ("big.bin", b"0" * (1024 * 1024 + 1), "application", "octet-stream")
    result = bcc.import_mails(store, inbox_for(store), [mail(big, PROPOSAL)], SETTINGS,
                              apply=True)
    assert result.logged == 1 and [a.name for a in attachments_of(store)] == ["Proposal v2.pdf"]
    assert "1 attachment skipped (too large)" in result.summary()


def test_one_mail_to_two_contacts_stores_the_file_once(store):
    seed(store)
    store.create_contact("acme", "Bob", "Roe", email="bob@acme.de")
    bcc.import_mails(store, inbox_for(store),
                     [mail(PROPOSAL, to="Jane Doe <jane@acme.de>, Bob Roe <bob@acme.de>")],
                     SETTINGS, apply=True)
    assert len(attachments_of(store)) == 2           # two interactions refer to it
    assert len(list((store.root / "companies/acme/attachments").iterdir())) == 1


def test_dedup_by_message_id_does_not_duplicate_files(store):
    seed(store)
    raw = mail(PROPOSAL)
    bcc.import_mails(store, inbox_for(store), [raw], SETTINGS, apply=True)
    again = bcc.import_mails(store, inbox_for(store), [raw], SETTINGS, apply=True)
    assert again.duplicates == 1 and again.attachments == 0
    assert len(attachments_of(store)) == 1


def test_setting_off_ignores_all_attachments(store):
    seed(store)
    result = bcc.import_mails(store, inbox_for(store), [mail(PROPOSAL)],
                              replace(SETTINGS, attachments="off"), apply=True)
    assert result.logged == 1 and attachments_of(store) == []


def test_a_new_company_from_a_sent_mail_keeps_the_file(store):
    result = bcc.import_mails(store, inbox_for(store),
                              [mail(PROPOSAL, to="Sam Lee <sam@newco.example>")], SETTINGS,
                              apply=True)
    assert result.companies == 1
    (slug,) = store.companies
    assert [a.name for a in attachments_of(store, slug)] == ["Proposal v2.pdf"]


# --------------------------------------------------------------------- inbox


def unmatched(store, **kw):
    seed(store)
    inbox = inbox_for(store)
    bcc.import_mails(store, inbox, [mail(PROPOSAL, to="Ann Lee <ann@nowhere.example>", **kw)],
                     QUEUE, apply=True)
    return inbox


def test_unmatched_mail_keeps_its_files_in_the_inbox_and_assign_moves_them(store, messages):
    inbox = unmatched(store)
    (item,) = inbox.items()
    (att,) = item.attachments
    assert (store.root / "inbox" / "attachments" / att.file).read_bytes() == PDF
    assert "attachments:" in (store.root / "inbox" / f"{item.id}.md").read_text()
    assert inbox.count() == 1                       # the folder is not an item
    del messages[:]
    slug, interaction = bcc.assign(store, inbox, item.id, "acme")
    assert [a.name for a in interaction.attachments] == ["Proposal v2.pdf"]
    assert stored(store, slug, interaction.attachments[0]).read_bytes() == PDF
    assert not (store.root / "inbox" / "attachments").exists() or not list(
        (store.root / "inbox" / "attachments").iterdir())
    assert inbox.count() == 0 and len(messages) == 1   # one commit


def test_discard_removes_inbox_files_only_with_the_last_item_using_them(store):
    seed(store)
    inbox = inbox_for(store)
    bcc.import_mails(store, inbox,
                     [mail(PROPOSAL, to="Ann Lee <ann@nowhere.example>, Bo Li <bo@elsewhere.example>")],
                     QUEUE, apply=True)
    first, second = inbox.items()
    folder = store.root / "inbox" / "attachments"
    assert len(list(folder.iterdir())) == 1          # one file, two items
    bcc.discard(store, inbox, first.id)
    assert len(list(folder.iterdir())) == 1
    bcc.discard(store, inbox, second.id)
    assert not folder.exists() or not list(folder.iterdir())


def test_an_item_with_a_missing_file_is_still_assigned(store):
    inbox = unmatched(store)
    (item,) = inbox.items()
    (store.root / "inbox" / "attachments" / item.attachments[0].file).unlink()
    _, interaction = bcc.assign(store, inbox, item.id, "acme")
    assert interaction.attachments == [] and inbox.count() == 0


def test_inbox_files_cannot_be_a_path(store):
    inbox = unmatched(store)
    (item,) = inbox.items()
    path = store.root / "inbox" / f"{item.id}.md"
    path.write_text(path.read_text().replace(item.attachments[0].file, "../../config.toml"))
    (reread,) = inbox.items()
    assert reread.attachments == []                   # not a stored name: not read


# ------------------------------------------------------- the web app and git


def untracked(repo) -> list[str]:
    """What git still sees as changed, bar the run bookkeeping a real folder ignores."""
    out = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True,
                         text=True).stdout.splitlines()
    return [line for line in out if ".last-run.json" not in line]


def test_the_review_queue_names_the_files_and_git_ends_clean(client, repo):
    client.post("/companies", data={"name": "Acme GmbH", "website": "acme.de",
                                    "source": "other", "stage": "prospect"})
    client.app_state.open_mailbox = lambda: FakeBox(
        [mail(PROPOSAL, to="Ann Lee <ann.lee@gmail.com>")])   # a personal address waits
    client.post("/bcc/import")
    page = client.get("/welcome").text
    assert "Proposal v2.pdf" in page
    item = client.app_state.inbox.items()[0]
    assert (repo / "inbox" / "attachments" / item.attachments[0].file).exists()
    assert untracked(repo) == []                          # the files were committed
    r = client.post(f"/inbox/{item.id}/assign", data={"company": "acme"})
    assert r.status_code == 303
    assert last_commit(repo).startswith(f"bcc: {item.id} assigned to acme/")
    assert untracked(repo) == []
    note = client.app_state.store.get("acme").interactions[0]
    assert [a.name for a in note.attachments] == ["Proposal v2.pdf"]
    assert client.get(f"/companies/acme/attachments/{note.attachments[0].file}").status_code == 200
