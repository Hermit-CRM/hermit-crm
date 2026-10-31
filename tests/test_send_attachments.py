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

"""Files on an outreach email: attach to a draft, send them with the approved text,
log what went out (docs/superpowers/plans/2026-10-31-attachments.md, Task 8). SMTP
and IMAP are in-memory doubles; no test touches the network."""

from __future__ import annotations

import hashlib
import socket
from datetime import datetime

import pytest

from hermitcrm import migrations, outreach, send, sendqueue
from hermitcrm.attachments import Incoming
from hermitcrm.setup import set_config_values
from hermitcrm.store import load_config
from outreach_fakes import git
from send_fakes import (GOOD_PASSWORD, MARA, FakeImap, FakeSmtp, data_error, make_folder,
                        ready_item)

PDF = b"%PDF-1.4 one-pager\n"
DECK = b"%PDF-1.4 deck\n" + b"x" * 2000
MON = datetime(2026, 10, 19, 9, 0)
SECOND = "2026-10-19T0801-email-lindenhof-data-mara-keller"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a test reached for the network")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setenv("HERMITCRM_SEND_PASSWORD", GOOD_PASSWORD)


@pytest.fixture
def folder(tmp_path):
    root, store, settings = make_folder(tmp_path)
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "setup")
    return root, store, settings


def deliver(store, settings, item_id, smtp=None, scheduled=False, **kw):
    smtp = smtp or FakeSmtp()
    imap = FakeImap()
    kw.setdefault("new_id", lambda domain: f"<fixed.1@{domain}>")
    out = send.deliver(store, item_id, settings=settings, scheduled=scheduled,
                       smtp_factory=smtp.factory, imap_factory=imap.factory, **kw)
    return out, smtp


def with_files(root, store, *files, **kw):
    item = ready_item(root, store, **kw)
    return outreach.set_attachments(store, item.id, add=[Incoming(n, d) for n, d in files])


def sent_files(msg):
    return [(p.get_filename(), p.get_content_type(), p.get_payload(decode=True))
            for p in msg.iter_attachments()]


def attachments_dir(root):
    return root / "companies" / MARA[0] / "attachments"


# ------------------------------------------------------------------ the hash


def test_text_hash_unchanged_without_attachments():
    assert send.text_hash("Subj", "Body\n") == hashlib.sha256(b"Subj\nBody\n").hexdigest()[:20]
    assert send.text_hash("Subj", "Body\n", ()) == send.text_hash("Subj", "Body\n")


def test_text_hash_follows_the_files(folder):
    root, store, _ = folder
    one = with_files(root, store, ("a.pdf", PDF))
    bare = send.text_hash(one.subject, one.body)
    assert send.text_hash(one.subject, one.body, one.attachments) != bare
    two = outreach.set_attachments(store, one.id, add=[Incoming("b.pdf", DECK)])
    assert send.text_hash(two.subject, two.body, two.attachments) != send.text_hash(
        one.subject, one.body, one.attachments)


# --------------------------------------------------------------- the message


def test_build_message_has_the_attachment_and_the_approved_text(folder):
    root, store, settings = folder
    item = with_files(root, store, ("One pager.pdf", PDF))
    att = item.attachments[0]
    msg = send.build_message(item, "mara@example.com", settings, message_id="<m@example.com>",
                             attachments=[(att, PDF)])
    assert msg.is_multipart()
    assert msg.get_body(("plain",)).get_content() == item.body
    assert sent_files(msg) == [("One pager.pdf", "application/pdf", PDF)]


def test_build_message_without_attachments_is_the_same_plain_mail(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    msg = send.build_message(item, "mara@example.com", settings, message_id="<m@example.com>")
    assert not msg.is_multipart() and msg.get_content_type() == "text/plain"
    assert msg.get_content() == item.body


# ------------------------------------------------------------ set_attachments


def test_attach_stores_the_file_in_one_commit_and_omits_the_key_when_empty(folder):
    root, store, _ = folder
    item = ready_item(root, store)
    assert "attachments" not in (root / item.path).read_text()
    before = int(git(root, "rev-list", "--count", "HEAD"))
    item = outreach.set_attachments(store, item.id, add=[Incoming("One pager.pdf", PDF)])
    (att,) = item.attachments
    assert (attachments_dir(root) / att.file).read_bytes() == PDF
    assert int(git(root, "rev-list", "--count", "HEAD")) == before + 1
    changed = git(root, "show", "--name-only", "--format=%s", "HEAD").splitlines()
    assert changed[0].startswith("outreach: attachments") and item.path in changed[1:]
    assert f"companies/{MARA[0]}/attachments/{att.file}" in changed
    text = (root / item.path).read_text()
    assert "attachments:" in text and "One pager.pdf" in text
    reread = outreach.get_item(root, item.id)
    assert reread.attachments == item.attachments
    assert outreach.item_text(reread) == text                    # stable bytes
    removed = outreach.set_attachments(store, item.id, remove=[att.file])
    assert removed.attachments == [] and "attachments" not in (root / item.path).read_text()
    assert not (attachments_dir(root) / att.file).exists()


def test_attach_again_reuses_a_file_already_on_the_company(folder):
    root, store, _ = folder
    note = store.create_interaction(MARA[0], "note", "", contact=MARA[1], body="x",
                                    attachments=[Incoming("Deck.pdf", DECK)])
    item = ready_item(root, store)
    item = outreach.set_attachments(store, item.id, reuse=[note.attachments[0].file])
    assert item.attachments == note.attachments
    with pytest.raises(outreach.OutreachError):
        outreach.set_attachments(store, item.id, reuse=["0123456789ab-nothing.pdf"])
    store.delete_interaction(MARA[0], note.id)           # the item still holds the file
    assert (attachments_dir(root) / item.attachments[0].file).exists()


def test_attach_only_while_it_is_a_draft_or_ready_email(folder):
    root, store, _ = folder
    queued = ready_item(root, store, state="queued", queued=MON, send_at=MON)
    with pytest.raises(outreach.OutreachError, match="unschedule"):
        outreach.set_attachments(store, queued.id, add=[Incoming("a.pdf", PDF)])
    sent = ready_item(root, store, item_id=SECOND, state="sent")
    with pytest.raises(outreach.OutreachError):
        outreach.set_attachments(store, sent.id, add=[Incoming("a.pdf", PDF)])
    linkedin = ready_item(root, store,
                          item_id="2026-10-19T0802-linkedin-lindenhof-data-mara-keller",
                          state="drafted")
    linkedin.channel = "linkedin"
    outreach.write_item(root, linkedin)
    with pytest.raises(outreach.OutreachError, match="LinkedIn"):
        outreach.set_attachments(store, linkedin.id, add=[Incoming("a.pdf", PDF)])
    assert not attachments_dir(root).exists()


def test_total_over_the_limit_is_refused_and_nothing_is_written(folder):
    root, store, _ = folder
    set_config_values(root / "config.toml", {"send_attachment_max_mb": 1})
    item = ready_item(root, store)
    big = b"0" * (600 * 1024)
    item = outreach.set_attachments(store, item.id, add=[Incoming("a.bin", big)])
    with pytest.raises(outreach.OutreachError, match="1 MB"):
        outreach.set_attachments(store, item.id, add=[Incoming("b.bin", big + b"1")])
    assert len(outreach.get_item(root, item.id).attachments) == 1
    assert len(list(attachments_dir(root).iterdir())) == 1


def test_unready_keeps_the_files(folder):
    root, store, _ = folder
    item = with_files(root, store, ("a.pdf", PDF))
    back = outreach.unready(store, item.id)
    assert back.state == "drafted" and back.attachments == item.attachments


# ------------------------------------------------------------------ delivery


def test_deliver_sends_the_files_and_logs_the_same_references(folder):
    root, store, settings = folder
    item = with_files(root, store, ("One pager.pdf", PDF), ("Deck.pdf", DECK))
    out, smtp = deliver(store, settings, item.id)
    assert out.kind == "sent"
    assert sent_files(smtp.sent[0]) == [("One pager.pdf", "application/pdf", PDF),
                                        ("Deck.pdf", "application/pdf", DECK)]
    logged = [i for i in store.get(MARA[0]).interactions if i.source == "outreach"][0]
    assert logged.attachments == item.attachments          # the same files, not copies
    assert len(list(attachments_dir(root).iterdir())) == 2
    assert logged.body == item.body


def test_a_file_missing_after_scheduling_puts_the_item_back_with_a_note(folder):
    root, store, settings = folder
    item = with_files(root, store, ("a.pdf", PDF))
    sendqueue.schedule(store, [item.id], settings, MON)
    (attachments_dir(root) / item.attachments[0].file).unlink()
    out, smtp = deliver(store, settings, item.id, scheduled=True)
    assert out.kind == "held" and smtp.sent == []
    held = outreach.get_item(root, item.id)
    assert held.state == "ready" and "a.pdf" in held.send_note and "missing" in held.send_note


def test_a_changed_file_list_after_scheduling_trips_the_edited_guard(folder):
    root, store, settings = folder
    item = with_files(root, store, ("a.pdf", PDF))
    sendqueue.schedule(store, [item.id], settings, MON)
    queued = outreach.get_item(root, item.id)
    assert queued.send_hash == send.text_hash(queued.subject, queued.body, queued.attachments)
    queued.attachments = []                        # a hand edit of the file
    outreach.write_item(root, queued)
    out, smtp = deliver(store, settings, item.id, scheduled=True)
    assert out.kind == "held" and "changed after it was scheduled" in out.detail
    assert smtp.sent == []


def test_a_queued_item_without_files_keeps_the_hash_it_was_given_before(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    sendqueue.schedule(store, [item.id], settings, MON)
    queued = outreach.get_item(root, item.id)
    assert queued.send_hash == hashlib.sha256(
        f"{queued.subject}\n{queued.body}".encode()).hexdigest()[:20]


def test_files_over_the_send_limit_hold_the_item(folder):
    root, store, _ = folder
    item = with_files(root, store, ("a.bin", b"0" * (600 * 1024)),
                      ("b.bin", b"1" * (600 * 1024)))               # 1.2 MB, limit 10 MB
    tight = send.settings_from_config({**load_config(root), "send_attachment_max_mb": 1})
    why = send.local_hold(store, outreach.get_item(root, item.id), tight, scheduled=False,
                          config=load_config(root))
    assert "1 MB" in why and "attachments" in why


# ------------------------------------------------------------ SMTP and errors


@pytest.mark.parametrize("code,text", [
    (552, b"5.3.4 Message size exceeds fixed limit"),
    (552, b"5.2.3 Your message exceeded Google's message size limits"),
    (552, b"5.7.0 This message was blocked because its content presents a security issue"),
    (554, b"5.3.4 message too large for this server"),
])
def test_a_message_too_large_is_its_own_kind(code, text):
    err = send.classify_smtp(data_error(code, text))
    assert err.kind == send.TOO_LARGE and err.code == code


def test_other_errors_keep_their_kinds():
    assert send.classify_smtp(data_error(550, b"5.1.1 user unknown")).kind == send.RECIPIENT
    assert send.classify_smtp(data_error(554, b"5.7.1 relay denied")).kind == send.REFUSED
    assert send.classify_smtp(data_error(452, b"4.2.2 mailbox full")).kind == send.TEMPORARY


def test_a_552_fails_that_item_and_does_not_pause_sending(folder):
    root, store, settings = folder
    first = with_files(root, store, ("a.pdf", PDF))
    second = ready_item(root, store, item_id=SECOND)
    smtp = FakeSmtp(send_errors=[data_error(552, b"5.3.4 Message size exceeds fixed limit")])
    out, smtp = deliver(store, settings, first.id, smtp=smtp)
    assert out.kind == "failed" and "5.3.4" in out.detail
    failed = outreach.get_item(root, first.id)
    assert failed.state == "failed" and "size" in failed.send_error
    assert not send.SendState.load(root).paused          # one message, not the account
    out, smtp = deliver(store, settings, second.id, smtp=smtp)
    assert out.kind == "sent"
    assert not (root / "outreach" / "suppressed.toml").exists()   # nobody was suppressed


# ------------------------------------------------------------------- flags


@pytest.mark.parametrize("text", [
    "Hi Mara,\n\nI attached our one-pager.\n", "Hallo Mara,\n\nanbei unser Überblick.\n",
    "Hallo Mara,\n\nIm Anhang finden Sie die Unterlagen.\n",
    "Dag Mara,\n\nin bijlage vind je het voorstel.\n", "Dag Mara,\n\nhierbij bijgevoegd het plan.\n",
    "Bonjour Mara,\n\nvous trouverez ci-joint notre offre.\n",
    "Bonjour Mara,\n\nvoir la pièce jointe.\n",
])
def test_forgot_the_attachment_in_four_languages(folder, text):
    root, store, _ = folder
    item = ready_item(root, store, body=text)
    assert any("no file" in f for f in outreach.attachment_flags(item))
    with_file = outreach.set_attachments(store, item.id, add=[Incoming("a.pdf", PDF)])
    assert not any("no file" in f for f in outreach.attachment_flags(with_file))


def test_no_flag_for_a_plain_mail_and_one_for_a_cold_first_touch_with_a_file(folder):
    root, store, _ = folder
    item = ready_item(root, store, body="Hi Mara,\n\nWhere does it hurt most?\n")
    assert outreach.attachment_flags(item) == []
    cold = outreach.set_attachments(store, item.id, add=[Incoming("a.pdf", PDF)])
    assert any("first email" in f for f in outreach.attachment_flags(cold))
    reply = ready_item(root, store, item_id="2026-10-19T0803-email-lindenhof-data-mara-keller",
                       kind="reply-to-interest", body="Hi Mara,\n\nThanks.\n")
    reply = outreach.set_attachments(store, reply.id, add=[Incoming("a.pdf", PDF)])
    assert outreach.attachment_flags(reply) == []


# ----------------------------------------------------- store, config, migration


def test_a_sent_interaction_and_a_queued_item_share_a_file(folder):
    root, store, settings = folder
    item = with_files(root, store, ("a.pdf", PDF))
    other = ready_item(root, store, item_id=SECOND)
    other = outreach.set_attachments(store, other.id, reuse=[item.attachments[0].file])
    deliver(store, settings, item.id)
    logged = [i for i in store.get(MARA[0]).interactions if i.source == "outreach"][0]
    store.delete_interaction(MARA[0], logged.id)
    assert (attachments_dir(root) / other.attachments[0].file).exists()
    assert store.referenced_files(MARA[0])[other.attachments[0].file] == 2  # both items


def test_the_send_limit_setting():
    assert send.settings_from_config({}).attachment_max_mb == 10
    assert send.settings_from_config({"send_attachment_max_mb": 5}).attachment_max_mb == 5
    assert send.settings_from_config({"send_attachment_max_mb": 99}).attachment_max_mb == 25
    s = send.settings_from_config({"send_attachment_max_mb": "lots"})
    assert s.attachment_max_mb == 10 and any("send_attachment_max_mb" in p for p in s.problems)


def test_migration_21_is_a_noop_and_idempotent():
    migration = next(m for m in migrations.MIGRATIONS if m.version == 21)
    assert migration.glob == "outreach/*.md"
    meta = {"state": "ready", "channel": "email"}
    assert migration.apply(dict(meta)) == meta
    assert migrations.LATEST == 21
