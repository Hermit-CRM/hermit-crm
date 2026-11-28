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

"""Duplicate-send safeguards (audit S2; 2026-10-31 action plan row 8).

Before a mail goes out, its Message-ID is written and committed. After a crash
the sender asks the Sent folder whether that Message-ID is there. Without an
incoming mail server (`send_imap_host` empty) it cannot ask, and it used to send
again. Now the automatic sender holds such an item back to Ready and says why;
a person can still press Send now after looking in Sent. And when Hermit stops
after the mail left (logging failed: a full disk), the item is held with "it may
have gone out" instead of "could not send it". Fake mailboxes only.
"""

from __future__ import annotations

import socket
from datetime import datetime, timedelta

import pytest

from hermitcrm import outreach, send, sendqueue
from hermitcrm.store import load_config
from outreach_fakes import NOW, git
from send_fakes import GOOD_PASSWORD, FakeImap, FakeSmtp, make_folder, raw_mail, ready_item

OPT_OUT = "If this is not for you, tell me and I will not write again."
LOST_ID = "<lost.1@mail.example.com>"


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
    path = root / "MESSAGING.md"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "approaches:", f"opt_out: {OPT_OUT}\napproaches:", 1), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "setup")
    return root, store, settings


def no_imap(root):
    return send.settings_from_config({**load_config(root), "send_imap_host": ""})


def crashed(root, store):
    """An item a previous run wrote the Message-ID on and then stopped."""
    base = ready_item(root, store)
    return ready_item(root, store, state="queued", queued=NOW, send_at=NOW,
                      send_hash=send.text_hash(base.subject, base.body),
                      message_id=LOST_ID, send_tries=1)


def deliver(store, settings, item_id, scheduled, smtp=None, imap=None):
    smtp, imap = smtp or FakeSmtp(), imap or FakeImap()
    out = send.deliver(store, item_id, settings=settings, scheduled=scheduled,
                       smtp_factory=smtp.factory, imap_factory=imap.factory,
                       new_id=lambda domain: f"<fixed.1@{domain}>")
    return out, smtp, imap


# ------------------------------------------- crash after the server accepted it

def test_without_imap_a_scheduled_retry_of_an_attempted_item_is_held_not_sent(folder):
    root, store, _ = folder
    item = crashed(root, store)
    out, smtp, imap = deliver(store, no_imap(root), item.id, scheduled=True)
    assert out.kind == "held" and not smtp.sent and not imap.logins
    after = outreach.get_item(root, item.id)
    assert after.state == "ready" and after.send_at is None
    assert "may have gone out" in after.send_note and "Sent" in after.send_note
    assert after.message_id == LOST_ID                # kept: a later check still knows it


def test_without_imap_send_now_by_a_person_still_sends_with_the_same_message_id(folder):
    root, store, _ = folder
    item = crashed(root, store)
    out, smtp, _ = deliver(store, no_imap(root), item.id, scheduled=False)
    assert out.kind == "sent" and len(smtp.sent) == 1
    assert smtp.sent[0]["Message-ID"] == LOST_ID


def test_with_imap_a_crashed_item_found_in_sent_is_logged_not_sent(folder):
    root, store, settings = folder
    item = crashed(root, store)
    imap = FakeImap()
    imap.deliver("[Gmail]/Sent Mail", raw_mail("sam@mail.example.com",
                                               "mara@lindenhof-data.example.com",
                                               "Your second office", message_id=LOST_ID),
                 datetime(2026, 10, 16, 9, 0))
    out, smtp, _ = deliver(store, settings, item.id, scheduled=True, imap=imap)
    assert out.kind == "recovered" and not smtp.sent


def test_with_imap_a_crashed_item_not_in_sent_is_sent_once_as_before(folder):
    root, store, settings = folder
    item = crashed(root, store)
    out, smtp, _ = deliver(store, settings, item.id, scheduled=True)
    assert out.kind == "sent" and len(smtp.sent) == 1


def test_without_imap_a_first_send_is_unchanged(folder):
    root, store, _ = folder
    item = ready_item(root, store)
    out, smtp, _ = deliver(store, no_imap(root), item.id, scheduled=False)
    assert out.kind == "sent" and len(smtp.sent) == 1


# ------------------------------------------------ logging failed after the send

def _tick(root, store, now, smtp, imap):
    send.SendState.load(root).mark_scan(now)
    return sendqueue.due(root, now=now, store=store, smtp_factory=smtp.factory,
                         imap_factory=imap.factory)


def _queued(root, store, settings):
    item = ready_item(root, store)
    sendqueue.schedule(store, [item.id], settings, NOW)
    return outreach.get_item(root, item.id)


def test_a_logging_failure_after_the_send_says_it_may_have_gone_out(folder, monkeypatch):
    root, store, settings = folder
    item = _queued(root, store, settings)

    def disk_full(self, item_, sent):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(send.OutreachLogger, "log", disk_full)
    smtp, imap = FakeSmtp(), FakeImap()
    out = _tick(root, store, item.send_at + timedelta(minutes=1), smtp, imap)
    assert len(smtp.sent) == 1                        # it did go out
    held = outreach.get_item(root, item.id)
    assert held.state == "ready" and held.message_id
    assert "may have gone out" in held.send_note and "Sent" in held.send_note
    assert "could not send it" not in held.send_note
    assert "may have gone out" in out[-1]


def test_a_failure_before_any_attempt_keeps_the_could_not_send_wording(folder, monkeypatch):
    root, store, settings = folder
    item = _queued(root, store, settings)

    def broken(store_, item_id, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(send, "deliver", broken)
    out = _tick(root, store, item.send_at + timedelta(minutes=1), FakeSmtp(), FakeImap())
    held = outreach.get_item(root, item.id)
    assert held.send_note == "Hermit could not send it (RuntimeError: boom)"
    assert out[-1].endswith("Hermit could not send it (RuntimeError: boom)")
