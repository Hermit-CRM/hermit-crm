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

"""Outreach send, M3: bounces, opt-outs and the suppression list. Delivery
reports from Gmail and from a generic MTA are fixtures; SMTP and IMAP are
in-memory doubles. Every address is on example.com, example.org or example.net."""

from __future__ import annotations

import imaplib
import socket
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import URL, QueryParams

from hermitcrm import cli, outreach, send, sendqueue, suppress
from hermitcrm.store import load_config
from hermitcrm.web import create_app
from outreach_fakes import NOW, git
from send_fakes import (GOOD_PASSWORD, MARA, FakeImap, FakeSmtp, imap_error, make_folder,
                        ready_item, raw_mail)

OPT_OUT = "If this is not for you, tell me and I will not write again."
BODY = ("Hi Pat,\n\nThe second office this autumn caught my eye. Where does it hurt most "
        "right now: pipeline, conversion or deal size?\n\nSam\n\n" + OPT_OUT + "\n")
MON = datetime(2026, 10, 19, 8, 0)


def crlf(text: str) -> bytes:
    return text.replace("\n", "\r\n").encode()


GMAIL_DSN = crlf('''From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>
To: sam@mail.example.com
Subject: Delivery Status Notification (Failure)
Message-ID: <dsn-1@mail.gmail.com>
Date: Mon, 19 Oct 2026 09:01:00 -0700
MIME-Version: 1.0
Content-Type: multipart/report; boundary="b0"; report-type=delivery-status

--b0
Content-Type: text/plain; charset="UTF-8"

** Address not found **

Your message wasn't delivered to mara@lindenhof-data.example.com because the address couldn't be found.

--b0
Content-Type: message/delivery-status

Reporting-MTA: dns; googlemail.com
X-Original-Message-ID: <orig-1@mail.example.com>

Final-Recipient: rfc822; mara@lindenhof-data.example.com
Action: failed
Status: 5.1.1
Remote-MTA: dns; mx.lindenhof-data.example.com
Diagnostic-Code: smtp; 550 5.1.1 The email account that you tried to reach does not exist.
Last-Attempt-Date: Mon, 19 Oct 2026 09:01:00 -0700 (PDT)

--b0
Content-Type: message/rfc822

Message-ID: <orig-1@mail.example.com>
Subject: Your second office
From: sam@mail.example.com
To: mara@lindenhof-data.example.com

Hi Mara

--b0--
''')

POSTFIX_DSN = crlf('''From: MAILER-DAEMON@mx.example.org (Mail Delivery System)
To: sam@mail.example.com
Subject: Undelivered Mail Returned to Sender
Message-ID: <dsn-2@mx.example.org>
Date: Mon, 19 Oct 2026 09:05:00 +0000
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="pf"

--pf
Content-Description: Notification
Content-Type: text/plain; charset=us-ascii

This is the mail system at host mx.example.org.

I'm sorry to have to inform you that your message could not be delivered.

--pf
Content-Description: Delivery report
Content-Type: message/delivery-status

Reporting-MTA: dns; mx.example.org
X-Postfix-Queue-ID: 4AB1
Arrival-Date: Mon, 19 Oct 2026 09:04:00 +0000 (UTC)

Final-Recipient: rfc822; Joris.Veldkamp@bluefin-analytics.example.com
Original-Recipient: rfc822;joris@bluefin-analytics.example.com
Action: failed
Status: 5.2.1
Diagnostic-Code: X-Postfix; host mail.bluefin-analytics.example.com said: 550 5.2.1 <joris@bluefin-analytics.example.com>: mailbox disabled (in reply to RCPT TO command)

Final-Recipient: rfc822; other@bluefin-analytics.example.com
Action: failed
Status: 5.1.1
Diagnostic-Code: smtp; 550 5.1.1 no such user

--pf
Content-Description: Undelivered Message Headers
Content-Type: text/rfc822-headers

Return-Path: <sam@mail.example.com>
Message-ID: <orig-2@mail.example.com>
Subject: Your second office
From: sam@mail.example.com
To: joris@bluefin-analytics.example.com

--pf--
''')

DELAY_DSN = crlf('''From: MAILER-DAEMON@mx.example.org
To: sam@mail.example.com
Subject: Delivery Status Notification (Delay)
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="dl"

--dl
Content-Type: text/plain

Still trying.

--dl
Content-Type: message/delivery-status

Reporting-MTA: dns; mx.example.org

Final-Recipient: rfc822; someone@example.org
Action: delayed
Status: 4.4.1
Diagnostic-Code: smtp; 451 4.4.1 connection timed out

--dl--
''')

SOFT_DSN = DELAY_DSN.replace(b"Action: delayed", b"Action: failed")
OUT_OF_OFFICE = crlf('''From: Mara Keller <mara@lindenhof-data.example.com>
To: sam@mail.example.com
Subject: Out of office
Auto-Submitted: auto-replied

I am away until Monday.
''')


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a test reached for the network")
    monkeypatch.setattr(socket, "create_connection", refuse)
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


# ------------------------------------------------------------ the list file


def test_the_list_is_written_deterministically_and_sorted(tmp_path):
    suppress.add(tmp_path, "Zed@Example.org", "bounced", "2026-10-19", "item-2")
    suppress.add(tmp_path, "amy@example.org", "opted-out", "2026-10-18")
    first = (tmp_path / suppress.FILE).read_bytes()
    assert [e.address for e in suppress.load(tmp_path)] == ["amy@example.org", "zed@example.org"]
    assert first.decode().startswith("# Addresses Hermit CRM never mails again")
    again = suppress.render(suppress.load(tmp_path)).encode()
    assert again == first                                   # the same entries, the same bytes
    assert suppress.is_suppressed(tmp_path, " ZED@example.org ")
    assert not suppress.is_suppressed(tmp_path, "nobody@example.org")
    assert not suppress.is_suppressed(tmp_path, "")
    kept = suppress.add(tmp_path, "amy@example.org", "bounced", "2026-10-30")      # first one stays
    assert kept.reason == "opted-out" and suppress.lookup(tmp_path, "amy@example.org").date == "2026-10-18"


def test_a_bad_entry_or_a_broken_file_is_an_error_not_an_empty_list(tmp_path):
    with pytest.raises(suppress.SuppressError):
        suppress.add(tmp_path, "not-an-address", "bounced")
    with pytest.raises(suppress.SuppressError):
        suppress.add(tmp_path, "a@example.org", "angry")
    (tmp_path / "outreach").mkdir()
    (tmp_path / suppress.FILE).write_text("[[suppressed\nnope", encoding="utf-8")
    with pytest.raises(suppress.SuppressError, match="sending stays stopped"):
        suppress.load(tmp_path)
    (tmp_path / suppress.FILE).write_text('[[suppressed]]\nreason = "bounced"\n', encoding="utf-8")
    with pytest.raises(suppress.SuppressError, match="no address"):
        suppress.load(tmp_path)


# ---------------------------------------------------------- delivery reports


def test_a_gmail_report_gives_the_address_the_original_id_and_the_servers_words():
    (b,) = suppress.parse_dsn(GMAIL_DSN)
    assert b.address == "mara@lindenhof-data.example.com"
    assert b.message_id == "<orig-1@mail.example.com>"
    assert b.status == "5.1.1"
    assert b.reason == "550 5.1.1 The email account that you tried to reach does not exist."


def test_a_generic_mta_report_with_two_recipients_and_quoted_headers():
    one, two = suppress.parse_dsn(POSTFIX_DSN)
    assert one.address == "joris.veldkamp@bluefin-analytics.example.com"     # Final-Recipient, lower case
    assert one.status == "5.2.1" and "mailbox disabled" in one.reason
    assert one.message_id == "<orig-2@mail.example.com>" == two.message_id
    assert two.address == "other@bluefin-analytics.example.com" and two.status == "5.1.1"


@pytest.mark.parametrize("raw", [DELAY_DSN, SOFT_DSN, OUT_OF_OFFICE, b"", b"not a mail at all",
                                 raw_mail("a@example.org", "b@example.org", "Hello")])
def test_delays_soft_failures_auto_replies_and_garbage_are_not_bounces(raw):
    assert suppress.parse_dsn(raw) == []


def test_the_bounce_rule_is_more_than_3_or_over_5_percent():
    assert not suppress.bounce_pause(50, 0) and not suppress.bounce_pause(50, 2)
    assert suppress.bounce_pause(50, 3)               # 6 %: over 5 %
    assert suppress.bounce_pause(50, 4)               # more than 3
    assert suppress.bounce_pause(100, 4)
    assert not suppress.bounce_pause(100, 3)          # 3 %
    assert not suppress.bounce_pause(10, 1)           # one in the first ten is not a rate
    assert suppress.bounce_pause(20, 2)               # 10 % of 20
    assert not suppress.bounce_pause(20, 1)           # 5 % is not over 5 %


# ---------------------------------------------------------------- scanning


def sent_item(root, store, settings, item_id="x1", message_id="<orig-1@mail.example.com>",
              company=MARA[0], contact=MARA[1], when=MON - timedelta(hours=1)):
    item = ready_item(root, store, item_id=item_id, company=company, contact=contact)
    it = outreach.get_item(root, item_id)
    it.state, it.message_id, it.sent, it.send_tries = "sent", message_id, when, 1
    outreach.write_item(root, it)
    return it


def test_a_bounce_is_suppressed_noted_flagged_and_committed_once(folder):
    root, store, settings = folder
    sent_item(root, store, settings)
    imap = FakeImap()
    imap.deliver("[Gmail]/All Mail", GMAIL_DSN, MON.date())
    state = send.SendState.load(root)
    head = git(root, "rev-list", "--count", "HEAD")
    lines = sendqueue.scan_bounces(store, settings, state, MON, imap.factory)
    assert lines == ["mara@lindenhof-data.example.com bounced (5.1.1 550 5.1.1 The email "
                     "account that you tried to reach does not exist.)"]
    entry = suppress.lookup(root, "mara@lindenhof-data.example.com")
    assert (entry.reason, entry.item, entry.date) == ("bounced", "x1", "2026-10-19")
    assert outreach.get_item(root, "x1").send_note.startswith("bounced: 5.1.1 550 5.1.1")
    notes = [i for i in store.get(MARA[0]).interactions
             if i.channel == "note" and i.contact == MARA[1]]
    assert len(notes) == 1 and "bounced (5.1.1" in notes[0].body and notes[0].contact == MARA[1]
    assert notes[0].is_touch is False and notes[0].source == "outreach"
    assert int(git(root, "rev-list", "--count", "HEAD")) == int(head) + 1
    assert git(root, "status", "--porcelain").strip() == ""
    assert "outreach/suppressed.toml" in git(root, "show", "--name-only", "--format=", "HEAD")
    assert send.SendState.load(root).bounce_scan == "2026-10-19T08:00"
    # the same report read again changes nothing
    again = sendqueue.scan_bounces(store, settings, send.SendState.load(root),
                                   MON + timedelta(hours=1), imap.factory)
    assert again == [] and int(git(root, "rev-list", "--count", "HEAD")) == int(head) + 1


def test_a_bounce_with_no_original_id_is_matched_by_address(folder):
    root, store, settings = folder
    sent_item(root, store, settings, message_id="<other@mail.example.com>")
    dsn = GMAIL_DSN.replace(b"X-Original-Message-ID: <orig-1@mail.example.com>\r\n", b"") \
                   .replace(b"Message-ID: <orig-1@mail.example.com>\r\nSubject", b"Subject")
    imap = FakeImap()
    imap.deliver("[Gmail]/All Mail", dsn, MON.date())
    sendqueue.scan_bounces(store, settings, send.SendState.load(root), MON, imap.factory)
    assert suppress.lookup(root, "mara@lindenhof-data.example.com").item == "x1"


def test_a_bounce_for_someone_not_in_the_crm_still_goes_on_the_list(folder):
    root, store, settings = folder
    imap = FakeImap()
    imap.deliver("[Gmail]/All Mail", POSTFIX_DSN, MON.date())
    lines = sendqueue.scan_bounces(store, settings, send.SendState.load(root), MON, imap.factory)
    assert len(lines) == 2 and suppress.is_suppressed(root, "other@bluefin-analytics.example.com")
    # joris.veldkamp@... is not joris@..., but it is on the list as the report spelled it
    assert suppress.is_suppressed(root, "joris.veldkamp@bluefin-analytics.example.com")


def test_a_queued_item_for_a_bounced_address_is_held_by_the_worker(folder):
    root, store, settings = folder
    item = ready_item(root, store, item_id="q1")
    sendqueue.schedule(store, ["q1"], settings, MON)
    suppress.add(root, "mara@lindenhof-data.example.com", "bounced", "2026-10-19", "other")
    when = outreach.get_item(root, "q1").send_at
    sendqueue_state = send.SendState.load(root)
    sendqueue_state.mark_scan(when)
    out = sendqueue.due(root, now=when, store=store, smtp_factory=FakeSmtp().factory,
                        imap_factory=FakeImap().factory)
    after = outreach.get_item(root, "q1")
    assert out[0].startswith("held: q1") and "suppression list" in out[0]
    assert after.state == "ready" and "suppression list (bounced" in after.send_note


def test_a_spike_of_bounces_pauses_sending_with_a_list_quality_banner_text(folder):
    root, store, settings = folder
    saved, store.on_write = store.on_write, None
    for k in range(24):                                   # 24 mails went out, 2 already bounced
        company = store.create_company(f"Co {k:02d}", country="NL")
        contact = store.create_contact(company.slug, "Pat", f"N{k:02d}",
                                       email=f"pat{k:02d}@co{k:02d}.example.org")
        sent_item(root, store, settings, item_id=f"s{k:02d}", message_id=f"<s{k}@mail.example.com>",
                  company=company.slug, contact=contact.slug, when=MON - timedelta(hours=k + 1))
    store.on_write = saved
    for k in (3, 4):
        suppress.add(root, f"pat{k:02d}@co{k:02d}.example.org", "bounced", "2026-10-19", f"s{k:02d}")
    assert sendqueue.bounce_counts(root) == (24, 2)
    dsn = GMAIL_DSN.replace(b"mara@lindenhof-data.example.com", b"pat09@co09.example.org") \
                   .replace(b"<orig-1@mail.example.com>", b"<s9@mail.example.com>")
    imap = FakeImap()
    imap.deliver("[Gmail]/All Mail", dsn, MON.date())
    state = send.SendState.load(root)
    lines = sendqueue.scan_bounces(store, settings, state, MON, imap.factory)
    assert lines[-1].startswith("paused: 3 of the last 24 emails bounced")
    assert "list-quality problem" in lines[-1]
    again = send.SendState.load(root)
    assert again.paused and again.kind == "bounces"
    assert sendqueue.bounce_counts(root) == (24, 3)
    # the worker now does nothing, and Resume lifts it
    ready_item(root, store, item_id="q2")
    sendqueue.schedule(store, ["q2"], settings, MON)
    out = sendqueue.due(root, now=MON + timedelta(days=1), store=store,
                        smtp_factory=FakeSmtp().factory, imap_factory=imap.factory)
    assert out[0].startswith("paused (bounces): 3 of the last 24")
    assert sendqueue.resume(store) == [again.message]


def test_the_scan_runs_every_half_hour_while_there_is_something_to_look_after(folder):
    root, store, settings = folder
    state = send.SendState.load(root)
    due = lambda queue, now: sendqueue._scan_due(root, settings, send.SendState.load(root),   # noqa: E731
                                                 queue, now)
    assert not due([], MON)                                      # nothing queued, nothing sent
    sent_item(root, store, settings, when=MON - timedelta(hours=2))
    assert due([], MON)                                          # something went out recently
    assert due([object()], MON)                                  # or something is queued
    state.mark_scan(MON)
    assert not due([object()], MON + timedelta(minutes=29))
    assert due([object()], MON + timedelta(minutes=30))
    assert not due([], MON + timedelta(days=4))                   # the last send is 4 days old
    state.bounce_scan = ""
    state.save()
    assert not sendqueue._scan_due(root, send.settings_from_config({**load_config(root), "send_imap_host": ""}),
                                   send.SendState.load(root), [object()], MON)


def test_a_scan_that_cannot_read_the_mailbox_pauses_on_a_login_and_waits_otherwise(folder):
    root, store, settings = folder
    sent_item(root, store, settings)
    state = send.SendState.load(root)
    bad_login = FakeImap(login_error=imap_error(b"[AUTHENTICATIONFAILED] Invalid credentials"))
    lines = sendqueue._scan(store, settings, state, MON, bad_login.factory, None)
    assert lines[0].startswith("paused: ") and "Invalid credentials" in lines[0]
    assert send.SendState.load(root).kind == send.AUTH
    send.SendState.load(root).resume()
    offline = FakeImap(connect_error=OSError("Network is unreachable"))
    lines = sendqueue._scan(store, settings, send.SendState.load(root), MON, offline.factory, None)
    assert "could not read delivery reports" in lines[0] and "next time" in lines[0]
    assert not send.SendState.load(root).paused and send.SendState.load(root).bounce_scan == ""


def test_the_tick_scans_first_and_then_sends(folder):
    root, store, settings = folder
    sent_item(root, store, settings, item_id="old")
    ready_item(root, store, item_id="q3")
    sendqueue.schedule(store, ["q3"], settings, MON)
    when = outreach.get_item(root, "q3").send_at
    imap = FakeImap()
    imap.deliver("[Gmail]/All Mail", POSTFIX_DSN, when.date())
    smtp = FakeSmtp()
    out = sendqueue.due(root, now=when, store=store, smtp_factory=smtp.factory,
                        imap_factory=imap.factory)
    assert out[0].startswith("joris.veldkamp@bluefin-analytics.example.com bounced")
    assert out[-1].startswith("sent: q3") and len(smtp.sent) == 1
    assert sendqueue.due(root, now=when + timedelta(minutes=5), store=store,
                         smtp_factory=smtp.factory, imap_factory=imap.factory) == ["nothing queued"]
    dry = sendqueue.due(root, now=when + timedelta(hours=1), store=store, dry_run=True,
                        smtp_factory=smtp.factory, imap_factory=imap.factory)
    assert dry == ["would read the sending mailbox for delivery reports", "nothing queued"]


# ----------------------------------------------------------------- opt-outs


def test_opted_out_suppresses_skips_everything_open_and_notes_it(folder):
    root, store, settings = folder
    a = ready_item(root, store, item_id="a1")
    b = ready_item(root, store, item_id="b1", state="drafted", ready=None)
    other = ready_item(root, store, item_id="c1", company="bluefin-analytics", contact="joris-veldkamp")
    sendqueue.schedule(store, ["a1"], settings, MON)
    text = sendqueue.opt_out(store, *MARA, now=MON)
    assert text == ("Mara Keller opted out: mara@lindenhof-data.example.com is on the "
                    "suppression list, 2 open items skipped.")
    entry = suppress.lookup(root, "mara@lindenhof-data.example.com")
    assert (entry.reason, entry.date) == ("opted-out", "2026-10-19")
    for item_id in ("a1", "b1"):
        item = outreach.get_item(root, item_id)
        assert item.state == "skipped" and item.skip_reason == "other"
        assert item.skip_note == "opted out" and item.send_at is None
    assert outreach.get_item(root, "c1").state == "ready"          # someone else is untouched
    note = [i for i in store.get(MARA[0]).interactions
            if i.channel == "note" and i.contact == MARA[1]][-1]
    assert "opted out" in note.body and "2 open outreach items skipped" in note.body
    assert git(root, "log", "--format=%s", "-1").strip() == "outreach: Mara Keller opted out"
    assert git(root, "status", "--porcelain").strip() == "?? outreach/c1.md"    # only the test's own
    # and the planner never takes them back
    again = ready_item(root, store, item_id="a2")
    result = sendqueue.schedule(store, ["a2"], settings, MON)
    assert "suppression list" in result.refused["a2"]


def test_opted_out_needs_an_email_address_and_a_contact(folder):
    root, store, settings = folder
    store.update_contact(MARA[0], MARA[1], email="")
    with pytest.raises(outreach.OutreachError, match="no email address"):
        sendqueue.opt_out(store, *MARA)
    with pytest.raises(outreach.OutreachError, match="no contact"):
        sendqueue.opt_out(store, "lindenhof-data", "nobody")


def test_opted_out_from_the_cli(folder, capsys):
    root, store, settings = folder
    assert cli.main(["--data", str(root), "outreach", "opt-out", "lindenhof-data/mara-keller"],
                    root=root) == 0
    assert "Mara Keller opted out" in capsys.readouterr().out
    assert suppress.is_suppressed(root, "mara@lindenhof-data.example.com")
    assert cli.main(["--data", str(root), "outreach", "opt-out", "lindenhof-data/nobody"],
                    root=root) == 1
    assert "no contact" in capsys.readouterr().err


def test_opted_out_buttons_on_the_contact_page_and_the_replies_tab(folder):
    root, store, settings = folder
    app = create_app(root, {**load_config(root), "push_enabled": False})
    app.state.setup_redirected = True
    client = TestClient(app, follow_redirects=False)
    page = client.get("/companies/lindenhof-data/contacts/mara-keller").text
    assert 'action="/companies/lindenhof-data/contacts/mara-keller/opt-out"' in page
    assert client.post("/companies/lindenhof-data/contacts/mara-keller/opt-out",
                       data={}).status_code == 403
    resp = client.post("/companies/lindenhof-data/contacts/mara-keller/opt-out",
                       data={"csrf_token": app.state.csrf_token, "back": "https://evil.example/x"})
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/companies/lindenhof-data/contacts/mara-keller")
    assert "opted out" in QueryParams(URL(resp.headers["location"]).query)["flash"]
    assert suppress.is_suppressed(root, "mara@lindenhof-data.example.com")
    # a reply owed shows the button on the Replies tab
    store.create_interaction(MARA[0], "email", "in", subject="Re: hi", contact=MARA[1],
                             body="Please stop.\n", date=NOW + timedelta(hours=1))
    app.state.store.load()
    replies = client.get("/outreach?tab=replies").text
    assert "/opt-out" in replies and "back" in replies
