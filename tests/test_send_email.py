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

"""Outreach send, M1: one approved email goes out from the app. The settings,
the message as built, the SMTP errors, the guards, the exactly-once order and
Send now. SMTP and IMAP are in-memory doubles; no test touches the network."""

from __future__ import annotations

import email
import imaplib
import smtplib
import socket
from datetime import datetime, timedelta
from email import policy

import pytest

from hermitcrm import bcc, outreach, send, sendplan, suppress
from hermitcrm.models import valid_email
from hermitcrm.store import load_config
from outreach_fakes import NOW, git
from send_fakes import (GOOD_PASSWORD, MARA, FakeImap, FakeSmtp, auth_error, data_error,
                        imap_error, make_folder, raw_mail, ready_item, recipients_refused)

OPT_OUT = "If this is not for you, tell me and I will not write again."


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Anything that opens a socket fails the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("a test reached for the network")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setenv("HERMITCRM_SEND_PASSWORD", GOOD_PASSWORD)


@pytest.fixture
def folder(tmp_path):
    root, store, settings = make_folder(tmp_path)
    set_opt_out(root, OPT_OUT)
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "setup")
    return root, store, settings


def set_opt_out(root, line):
    path = root / "MESSAGING.md"
    text = path.read_text(encoding="utf-8")
    if "opt_out:" not in text:
        path.write_text(text.replace("approaches:", f"opt_out: {line}\napproaches:", 1),
                        encoding="utf-8")


def deliver(store, settings, item_id, smtp=None, imap=None, scheduled=False, **kw):
    smtp = smtp or FakeSmtp()
    imap = imap or FakeImap()
    kw.setdefault("new_id", lambda domain: f"<fixed.1@{domain}>")
    out = send.deliver(store, item_id, settings=settings, scheduled=scheduled,
                       smtp_factory=smtp.factory, imap_factory=imap.factory, **kw)
    return out, smtp, imap


# ----------------------------------------------------------------- settings


def test_settings_default_to_the_plan_and_read_the_config():
    s = send.settings_from_config({"owner_email": "Sam@Example.com", "owner_name": "Sam Example"})
    assert (s.enabled, s.paused) == (False, False)
    assert s.from_addr == "sam@example.com" and s.smtp_user == "sam@example.com"
    assert s.smtp_host == "smtp.gmail.com" and s.smtp_port == 587
    assert s.imap_host == "imap.gmail.com" and s.daily_cap == 50
    assert s.window == (8 * 60 + 30, 17 * 60 + 30) and s.days == (0, 1, 2, 3, 4)
    assert s.ramp == (10, 20, 30, 40) and s.block_countries == ()
    assert s.domain == "example.com" and not s.problems
    c = {"send_from": "cold@mail.example.net", "send_smtp_user": "login@mail.example.net",
         "send_window": "09:00-12:00", "send_days": ["mon", "tue"], "send_daily_cap": 40,
         "send_ramp": [5, 10], "send_email_block_countries": ["de", " at "]}
    s = send.settings_from_config(c)
    assert (s.from_addr, s.smtp_user) == ("cold@mail.example.net", "login@mail.example.net")
    assert s.window == (540, 720) and s.days == (0, 1) and s.daily_cap == 40
    assert s.ramp == (5, 10) and s.block_countries == ("AT", "DE")
    assert s.plan.daily_cap == 40 and s.plan.window == (540, 720)


def test_unreadable_settings_fall_back_and_are_listed():
    s = send.settings_from_config({"send_window": "late", "send_days": ["funday"],
                                   "send_daily_cap": "lots", "send_ramp": ["x"],
                                   "send_smtp_port": 0})
    assert s.window == (510, 1050) and s.days == (0, 1, 2, 3, 4) and s.daily_cap == 50
    assert s.smtp_port == 587
    assert len(s.problems) == 5 and any("send_window" in p for p in s.problems)


def test_settings_say_what_is_missing():
    assert "no sending address" in send.settings_from_config({}).missing
    s = send.settings_from_config({"send_from": "cold@mail.example.net",
                                   "my_addresses": ["sam@example.com"]})
    assert "my_addresses" in s.missing
    ok = send.settings_from_config({"send_from": "cold@mail.example.net",
                                    "my_addresses": ["cold@mail.example.net"]})
    assert ok.missing == ""


def test_the_cap_warning_is_silent_to_50_and_loud_past_150():
    assert send.cap_warning(50) == "" and send.cap_warning(10) == ""
    assert "above the plan of 50" in send.cap_warning(51)
    assert "above the plan of 50" in send.cap_warning(100)
    assert "third" not in send.cap_warning(150)
    loud = send.cap_warning(200)
    assert "150" in loud and "third" in loud


# ------------------------------------------------------------------- errors


@pytest.mark.parametrize("exc,kind", [
    (auth_error(), send.AUTH),
    (auth_error(534, b"5.7.9 Application-specific password required"), send.AUTH),
    (data_error(550, b"5.4.5 Daily user sending quota exceeded."), send.QUOTA),
    (smtplib.SMTPSenderRefused(550, b"5.4.5 Daily user sending quota exceeded", "a@b.example"),
     send.QUOTA),
    (data_error(421, b"4.7.0 Try again later"), send.TEMPORARY),
    (data_error(451, b"4.3.0 Temporary problem"), send.TEMPORARY),
    (smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), send.TEMPORARY),
    (TimeoutError("timed out"), send.TEMPORARY),
    (OSError("Network is unreachable"), send.TEMPORARY),
    (recipients_refused("x@example.org"), send.RECIPIENT),
    (data_error(550, b"5.7.1 Message rejected as spam"), send.REFUSED),
    (RuntimeError("odd"), send.TEMPORARY),
])
def test_smtp_errors_are_classified(exc, kind):
    err = send.classify_smtp(exc)
    assert err.kind == kind and err.text


def test_the_server_text_is_kept_as_it_is():
    err = send.classify_smtp(auth_error())
    assert err.text.startswith("535 5.7.8 Username and Password not accepted")
    assert "BadCredentials" in err.text and err.code == 535
    assert str(err) == err.text


# ------------------------------------------------------------------ message


def item_for(**kw):
    base = dict(id="x1", company="lindenhof-data", contact="mara-keller", channel="email",
                subject="Your second office", language="en",
                body="Hi Mara,\n\nOne question: where does it hurt most?\n\nSam\n")
    base.update(kw)
    return outreach.Item(**base)


def test_the_message_is_plain_text_exactly_as_approved():
    s = send.settings_from_config({"send_from": "cold@mail.example.net",
                                   "owner_name": "Sam Example"})
    item = item_for()
    msg = send.build_message(item, "mara@example.org", s, message_id="<a.1@mail.example.net>",
                             when=datetime(2026, 10, 19, 9, 0))
    assert msg["From"] == "Sam Example <cold@mail.example.net>"
    assert msg["To"] == "mara@example.org" and msg["Subject"] == "Your second office"
    assert msg["Message-ID"] == "<a.1@mail.example.net>"
    assert msg.get_content_type() == "text/plain" and not msg.is_multipart()
    assert msg.get_content() == item.body
    for header in ("Bcc", "Cc", "List-Unsubscribe", "Reply-To", "X-Mailer", "In-Reply-To"):
        assert msg[header] is None
    assert b"<html" not in msg.as_bytes().lower()


def test_a_non_ascii_text_is_kept_through_utf8():
    s = send.settings_from_config({"send_from": "cold@mail.example.net"})
    item = item_for(subject="Größe der Büros", body="Hallo Mara,\n\nWie läuft die Größe? ✓\n")
    msg = send.build_message(item, "mara@example.org", s, message_id="<a.2@mail.example.net>")
    parsed = email.message_from_bytes(msg.as_bytes(), policy=policy.default)
    assert parsed["Subject"] == "Größe der Büros" and parsed.get_content() == item.body


def test_a_subject_is_one_line_and_a_bad_address_is_refused():
    s = send.settings_from_config({"send_from": "cold@mail.example.net"})
    msg = send.build_message(item_for(subject="Two\n  lines"), "mara@example.org", s,
                             message_id="<a.3@x.example>")
    assert msg["Subject"] == "Two lines"
    for bad in ("", "no-at-sign", "a@b.example, c@d.example", "A <a@b.example>", "a b@c.example"):
        with pytest.raises(send.SendError) as caught:
            send.build_message(item_for(), bad, s, message_id="<a.4@x.example>")
        assert caught.value.kind == send.RECIPIENT


def test_a_follow_up_or_reply_threads_under_the_mail_it_follows(folder):
    root, store, settings = folder
    mine = store.create_interaction(MARA[0], "email", "out", subject="Your second office",
                                    contact=MARA[1], body="Hi\n", source="outreach",
                                    message_id="<first.1@mail.example.com>",
                                    date=NOW - timedelta(days=6))
    theirs = store.create_interaction(MARA[0], "email", "in", subject="Re: Your second office",
                                      contact=MARA[1], body="Tell me more\n",
                                      message_id="<theirs.1@example.org>",
                                      date=NOW - timedelta(days=5))
    company = store.get(MARA[0])
    follow = item_for(kind="follow-up", follows=mine.id, subject="Re: Your second office")
    assert send.thread_refs(company, follow) == ("<first.1@mail.example.com>",) * 2
    reply = item_for(kind="reply-to-interest", reply_to=theirs.id)
    assert send.thread_refs(company, reply) == ("<theirs.1@example.org>",) * 2
    assert send.thread_refs(company, item_for()) == ("", "")
    assert send.thread_refs(company, item_for(follows="unknown")) == ("", "")
    msg = send.build_message(follow, "mara@example.org", settings,
                             message_id="<a.5@mail.example.com>",
                             in_reply_to="<first.1@mail.example.com>",
                             references="<first.1@mail.example.com>")
    assert msg["In-Reply-To"] == "<first.1@mail.example.com>"
    assert msg["References"] == "<first.1@mail.example.com>"
    assert msg["Subject"] == "Re: Your second office"


def test_the_message_id_is_on_the_sending_domain():
    assert send.new_message_id("mail.example.com").endswith("@mail.example.com>")


def test_a_hash_changes_with_the_subject_or_the_body():
    a = send.text_hash("S", "body")
    assert a == send.text_hash("S", "body")
    assert a != send.text_hash("S2", "body") and a != send.text_hash("S", "body2")


# ------------------------------------------------------------------ send now


def test_send_now_sends_the_approved_text_once_and_logs_it(folder):
    root, store, settings = folder
    item = ready_item(root, store, framework="trigger-tension-trust")
    out, smtp, imap = deliver(store, settings, item.id)
    assert out.kind == "sent" and out.done
    assert len(smtp.sent) == 1
    msg = smtp.sent[0]
    assert msg["To"] == "mara@lindenhof-data.example.com"
    assert msg["From"] == "Sam Example <sam@mail.example.com>"
    assert msg["Message-ID"] == "<fixed.1@mail.example.com>"
    assert msg.get_content() == item.body
    assert smtp.logins == [("smtp.gmail.com", 587, "sam@mail.example.com",
                            GOOD_PASSWORD.replace(" ", ""))]
    assert smtp.starttls_used
    after = outreach.get_item(root, item.id)
    assert after.state == "sent" and after.message_id == "<fixed.1@mail.example.com>"
    assert after.send_tries == 1 and after.sent == NOW
    logged = [i for i in store.get(MARA[0]).interactions if i.source == "outreach"]
    assert len(logged) == 1 and after.sent_with == logged[0].id
    it = logged[0]
    assert (it.channel, it.direction, it.contact) == ("email", "out", MARA[1])
    assert it.body.rstrip("\n") == item.body.rstrip("\n") and it.subject == item.subject
    assert it.message_id == "<fixed.1@mail.example.com>"
    assert it.angle == "hook" and it.framework == "trigger-tension-trust"
    # written in the order: Message-ID committed first, then the log + the flip together
    log = git(root, "log", "--format=%s", "-3").splitlines()
    assert log[0].startswith("interaction:") and "outreach" in log[0]
    assert log[1].startswith("outreach: sending")
    assert git(root, "status", "--porcelain").strip() == ""


def test_a_later_bcc_import_of_the_same_mail_adds_nothing(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    out, smtp, _ = deliver(store, settings, item.id)
    before = len(store.get(MARA[0]).interactions)
    raw = smtp.sent[0].as_bytes()
    result = bcc.import_mails(store, bcc.Inbox(root), [raw],
                              bcc.Settings(address="sam+crm@mail.example.com",
                                           my_addresses=("sam@mail.example.com",)), apply=True)
    assert result.logged == 0 and result.duplicates == 1
    assert len(store.get(MARA[0]).interactions) == before


def test_the_ready_step_still_sends_nothing(folder):
    root, store, settings = folder
    item = ready_item(root, store, state="drafted", ready=None)
    outreach.mark_ready(store, item.id)
    assert outreach.get_item(root, item.id).state == "ready"
    assert outreach.ManualSender().send(item).sent is False


def test_send_now_refuses_when_sending_is_off_paused_or_over_the_cap(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    off = send.settings_from_config({**load_config(root), "send_enabled": False})
    with pytest.raises(outreach.OutreachError, match="sending is off"):
        send.send_now(store, item.id, settings=off)
    paused = send.settings_from_config({**load_config(root), "send_paused": True})
    with pytest.raises(outreach.OutreachError, match="paused"):
        send.send_now(store, item.id, settings=paused)
    nobody = send.settings_from_config({"send_enabled": True})
    with pytest.raises(outreach.OutreachError, match="no sending address"):
        send.send_now(store, item.id, settings=nobody)
    capped = send.settings_from_config({**load_config(root), "send_daily_cap": 1, "send_ramp": []})
    store.create_interaction(MARA[0], "email", "out", subject="Earlier", contact=MARA[1],
                             body="x\n", source="outreach", message_id="<e@mail.example.com>",
                             date=NOW - timedelta(hours=1))
    with pytest.raises(outreach.OutreachError, match="cap of 1"):
        send.send_now(store, item.id, settings=capped)
    assert outreach.get_item(root, item.id).state == "ready"


def test_send_now_goes_through_the_whole_path(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    smtp, imap = FakeSmtp(), FakeImap()
    out = send.send_now(store, item.id, settings=settings, smtp_factory=smtp.factory,
                        imap_factory=imap.factory)
    assert out.kind == "sent" and len(smtp.sent) == 1 and imap.logins


def test_send_now_refuses_the_item_that_is_not_sendable(folder):
    root, store, settings = folder
    item = ready_item(root, store, state="drafted")
    with pytest.raises(outreach.OutreachError, match="only a ready or queued or failed"):
        send.send_now(store, item.id, settings=settings, smtp_factory=FakeSmtp().factory,
                      imap_factory=FakeImap().factory)


def test_a_linkedin_item_is_not_sent_by_email(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    li = outreach.get_item(root, item.id)
    li.channel = "linkedin"
    outreach.write_item(root, li)
    out, smtp, _ = deliver(store, settings, item.id)
    assert out.kind == "held" and "only email" in out.detail and not smtp.sent


# ------------------------------------------------------------------- guards


def test_a_contact_without_a_usable_address_is_held_not_a_crash(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    store.update_contact(MARA[0], MARA[1], email="")
    out, smtp, _ = deliver(store, settings, item.id)
    assert out.kind == "held" and "no email address" in out.detail and not smtp.sent
    assert outreach.get_item(root, item.id).state == "ready"      # Send now changes nothing


def test_a_scheduled_item_that_is_held_goes_back_to_ready_with_the_reason(folder):
    root, store, settings = folder
    item = ready_item(root, store, state="queued", queued=NOW, send_at=NOW,
                      send_hash=send.text_hash("Your second office", ready_item(root, store).body))
    store.create_interaction(MARA[0], "email", "in", subject="Re: hi", contact=MARA[1],
                             body="Not now\n", date=NOW + timedelta(minutes=5))
    store.now = lambda: NOW + timedelta(minutes=10)
    out, smtp, imap = deliver(store, settings, item.id, scheduled=True)
    after = outreach.get_item(root, item.id)
    assert out.kind == "held" and after.state == "ready"
    assert "they wrote to you on 16 Oct" in after.send_note
    assert after.queued is None and after.send_at is None and after.send_hash == ""
    assert not smtp.sent and not imap.logins                  # no mailbox login for a local hold
    assert "outreach: hold" in git(root, "log", "--format=%s", "-1")


@pytest.mark.parametrize("case", ["suppressed", "closed", "dnc", "sample", "country",
                                  "disqualified", "failing-check", "edited", "no-opt-out"])
def test_every_guard_holds_the_item(folder, case):
    root, store, settings = folder
    item = ready_item(root, store)
    scheduled = False
    if case == "suppressed":
        suppress.add(root, "Mara@Lindenhof-Data.example.com", "opted-out", "2026-10-01")
    elif case == "closed":
        store.update_company(MARA[0], stage="won")
    elif case == "dnc":
        store.update_company(MARA[0], tags=["demo", "do-not-contact"])
    elif case == "sample":
        store.get(MARA[0]).extra["sample"] = True
    elif case == "country":
        settings = send.settings_from_config({**load_config(root),
                                              "send_email_block_countries": ["DE"]})
    elif case == "disqualified":
        store.update_company(MARA[0], tags=["demo", "customer"])
        it = outreach.get_item(root, item.id)
        it.approach = "Founder coaching"
        outreach.write_item(root, it)
    elif case == "failing-check":
        it = outreach.get_item(root, item.id)
        it.body += "\nSee https://www.example.com/pricing\n"
        outreach.write_item(root, it)
    elif case == "edited":
        scheduled = True
        it = outreach.get_item(root, item.id)
        it.state, it.queued, it.send_at = "queued", NOW, NOW
        it.send_hash = send.text_hash(it.subject, it.body)
        it.body += "\nP.S. one more thing?\n"
        outreach.write_item(root, it)
    elif case == "no-opt-out":
        scheduled = True
        it = outreach.get_item(root, item.id)
        it.state, it.queued, it.send_at = "queued", NOW, NOW
        it.body = it.body.replace(OPT_OUT, "")
        it.send_hash = send.text_hash(it.subject, it.body)
        outreach.write_item(root, it)
    out, smtp, _ = deliver(store, settings, item.id, scheduled=scheduled)
    why = {"suppressed": "suppression list (opted-out, 2026-10-01)", "closed": "company is won",
           "dnc": "tagged do-not-contact", "sample": "made-up sample account",
           "country": "email to DE is switched off", "disqualified": "disqualified",
           "failing-check": "a check fails now", "edited": "text changed after it was scheduled",
           "no-opt-out": "opt-out line from the playbook is missing"}[case]
    assert out.kind == "held" and why in out.detail, out.detail
    assert not smtp.sent
    assert outreach.get_item(root, item.id).message_id == ""


def test_the_country_guard_is_off_by_default(folder):
    root, store, settings = folder
    assert store.get(MARA[0]).country == "DE" and settings.block_countries == ()
    item = ready_item(root, store)
    out, smtp, _ = deliver(store, settings, item.id)
    assert out.kind == "sent" and len(smtp.sent) == 1


def test_a_check_that_already_failed_when_it_was_approved_does_not_hold_it(folder):
    root, store, settings = folder
    item = ready_item(root, store, body=ready_item(root, store).body + "\nwww.example.com\n",
                      checks=["it contains a link (www.example.com); a first touch has none"])
    out, smtp, _ = deliver(store, settings, item.id)
    assert out.kind == "sent"


def test_a_reply_found_in_the_sending_mailbox_holds_it(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    imap = FakeImap()
    imap.deliver("[Gmail]/All Mail", raw_mail("Mara Keller <mara@lindenhof-data.example.com>",
                                              "sam@mail.example.com", "Re: Hello"),
                 datetime(2026, 10, 16, 8, 0))
    out, smtp, imap = deliver(store, settings, item.id, imap=imap)
    assert out.kind == "held" and "found in the sending mailbox" in out.detail
    assert not smtp.sent
    folder_used, criteria = imap.searches[0]
    assert folder_used == "[Gmail]/All Mail"
    assert criteria == ("FROM", '"mara@lindenhof-data.example.com"', "SINCE", "16-Oct-2026")


def test_mail_from_before_the_approval_day_does_not_hold_it(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    imap = FakeImap()
    imap.deliver("[Gmail]/All Mail", raw_mail("mara@lindenhof-data.example.com",
                                              "sam@mail.example.com", "Old"),
                 datetime(2026, 10, 10, 8, 0))
    out, smtp, _ = deliver(store, settings, item.id, imap=imap)
    assert out.kind == "sent"


def test_without_an_imap_host_the_mailbox_checks_are_skipped(folder):
    root, store, _ = folder
    settings = send.settings_from_config({**load_config(root), "send_imap_host": ""})
    item = ready_item(root, store)
    out, smtp, imap = deliver(store, settings, item.id)
    assert out.kind == "sent" and not imap.logins


def test_send_now_warns_but_allows_a_first_touch_without_the_opt_out_line(folder):
    root, store, settings = folder
    item = ready_item(root, store, body=ready_item(root, store).body.replace(OPT_OUT, ""))
    out, smtp, _ = deliver(store, settings, item.id)
    assert out.kind == "sent" and len(smtp.sent) == 1
    assert out.warnings and "opt-out line" in out.warnings[0]


def drop_opt_out(root):
    """A playbook without an `opt_out` line, as a folder that never set one."""
    path = root / "MESSAGING.md"
    text = path.read_text(encoding="utf-8")
    assert f"opt_out: {OPT_OUT}\n" in text
    path.write_text(text.replace(f"opt_out: {OPT_OUT}\n", "", 1), encoding="utf-8")


def test_the_opt_out_line_is_optional_so_a_playbook_without_one_blocks_nothing(folder):
    root, store, settings = folder
    drop_opt_out(root)
    item = ready_item(root, store, body=ready_item(root, store).body.replace(OPT_OUT, ""))
    assert OPT_OUT not in item.body
    assert send.opt_out_problem(store, outreach.get_item(root, item.id)) == ""
    out, smtp, _ = deliver(store, settings, item.id, scheduled=False)
    assert out.kind == "sent" and len(smtp.sent) == 1 and not out.warnings
    assert OPT_OUT not in smtp.sent[0].get_content()


def test_a_scheduled_first_touch_goes_out_when_the_playbook_has_no_opt_out_line(folder):
    root, store, settings = folder
    drop_opt_out(root)
    item = ready_item(root, store, body=ready_item(root, store).body.replace(OPT_OUT, ""))
    it = outreach.get_item(root, item.id)
    it.state, it.queued, it.send_at = "queued", NOW, NOW
    it.send_hash = send.text_hash(it.subject, it.body)
    outreach.write_item(root, it)
    out, smtp, _ = deliver(store, settings, item.id, scheduled=True)
    assert out.kind == "sent", out.detail
    assert len(smtp.sent) == 1


def test_a_line_the_playbook_has_still_has_to_be_in_the_text_when_scheduled(folder):
    root, store, _ = folder
    plain = ready_item(root, store, body=ready_item(root, store).body.replace(OPT_OUT, ""))
    assert "missing from the text" in send.opt_out_problem(store, plain)


def test_the_opt_out_rule_applies_to_a_cold_first_touch_only(folder):
    root, store, _ = folder
    plain = ready_item(root, store, body=ready_item(root, store).body.replace(OPT_OUT, ""))
    assert "opt-out line" in send.opt_out_problem(store, plain)
    assert send.opt_out_problem(store, outreach.get_item(root, ready_item(root, store).id)) == ""
    reply = outreach.get_item(root, plain.id)
    reply.kind = "reply-to-interest"
    assert send.opt_out_problem(store, reply) == ""


# ------------------------------------------------------------- the errors


def test_a_bad_password_pauses_sending_and_shows_the_servers_own_words(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    smtp = FakeSmtp(login_error=auth_error())
    out, smtp, _ = deliver(store, settings, item.id, smtp=smtp)
    assert out.kind == "paused" and "Username and Password not accepted" in out.detail
    state = send.SendState.load(root)
    assert state.paused and state.kind == send.AUTH and "BadCredentials" in state.message
    assert outreach.get_item(root, item.id).state == "ready"
    assert not smtp.sent
    # the pause is a file in .git: nothing to commit, nothing in the data folder
    assert git(root, "status", "--porcelain").strip() == ""
    with pytest.raises(outreach.OutreachError, match="paused: 535"):
        send.send_now(store, item.id, settings=settings, smtp_factory=FakeSmtp().factory,
                      imap_factory=FakeImap().factory)


def test_a_missing_password_is_an_auth_pause_with_a_clear_message(folder, monkeypatch):
    root, store, settings = folder
    monkeypatch.delenv("HERMITCRM_SEND_PASSWORD")
    item = ready_item(root, store)
    out, smtp, _ = deliver(store, settings, item.id)
    assert out.kind == "paused" and "no app password found" in out.detail


def test_the_quota_pauses_until_the_next_window(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    smtp = FakeSmtp(send_errors=[data_error(550, b"5.4.5 Daily user sending quota exceeded.")])
    out, _, _ = deliver(store, settings, item.id, smtp=smtp)
    assert out.kind == "paused" and "quota" in out.detail
    state = send.SendState.load(root)
    assert state.kind == send.QUOTA and state.until == "2026-10-19T08:30"     # Fri -> Mon
    assert state.is_paused(NOW) and not state.is_paused(datetime(2026, 10, 19, 8, 30))
    assert not send.SendState.load(root).paused                                # it ended by itself


def test_a_temporary_error_retries_in_15_minutes_then_fails_after_3_tries(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    smtp = FakeSmtp(send_errors=[data_error(421, b"4.7.0 Try again later")] * 3)
    ids = []
    for attempt in range(1, 4):
        # a retry asks Sent first (it may have gone out); nothing there
        out, smtp, _ = deliver(store, settings, item.id, smtp=smtp, scheduled=attempt > 1,
                               now=NOW + timedelta(minutes=20 * attempt))
        after = outreach.get_item(root, item.id)
        ids.append(after.message_id)
        assert after.send_tries == attempt
        if attempt < 3:
            assert out.kind == "retry" and after.state == "queued"
            assert after.send_at == NOW + timedelta(minutes=20 * attempt + 15)
            assert after.send_hash == send.text_hash(after.subject, after.body)
        else:
            assert out.kind == "failed" and after.state == "failed"
            assert after.send_error.startswith("gave up after 3 tries: 421")
    assert len(set(ids)) == 1 and ids[0]            # one Message-ID through every try
    assert not smtp.sent


def test_an_unknown_recipient_fails_the_item_and_suppresses_the_address(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    smtp = FakeSmtp(send_errors=[recipients_refused("mara@lindenhof-data.example.com")])
    out, _, _ = deliver(store, settings, item.id, smtp=smtp)
    after = outreach.get_item(root, item.id)
    assert out.kind == "failed" and after.state == "failed"
    assert "5.1.1" in after.send_error
    listed = suppress.lookup(root, "mara@lindenhof-data.example.com")
    assert listed.reason == "bounced" and listed.item == item.id
    assert "outreach/suppressed.toml" in git(root, "show", "--name-only", "--format=", "HEAD")
    again, smtp2, _ = deliver(store, settings, item.id)
    assert again.kind == "held" and "suppression list" in again.detail and not smtp2.sent


def test_a_broken_suppression_file_stops_sending(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    (root / "outreach" / "suppressed.toml").write_text("[[suppressed\nbroken", encoding="utf-8")
    out, smtp, _ = deliver(store, settings, item.id)
    assert out.kind == "paused" and "suppressed.toml" in out.detail and not smtp.sent


# ----------------------------------------------------------- crash recovery


def crashed(root, store, **extra):
    """An item a previous run wrote the Message-ID on and then stopped."""
    base = ready_item(root, store)
    return ready_item(root, store, state="queued", queued=NOW, send_at=NOW,
                      send_hash=send.text_hash(base.subject, base.body),
                      message_id="<lost.1@mail.example.com>", send_tries=1, **extra)


def test_a_mail_found_in_sent_is_logged_not_sent_again(folder):
    root, store, settings = folder
    item = crashed(root, store)
    imap = FakeImap()
    imap.deliver("[Gmail]/Sent Mail", raw_mail("sam@mail.example.com",
                                               "mara@lindenhof-data.example.com", "Your second office",
                                               message_id="<lost.1@mail.example.com>"),
                 datetime(2026, 10, 16, 9, 0))
    out, smtp, imap = deliver(store, settings, item.id, imap=imap, scheduled=True)
    assert out.kind == "recovered" and not smtp.sent
    after = outreach.get_item(root, item.id)
    assert after.state == "sent"
    logged = [i for i in store.get(MARA[0]).interactions if i.source == "outreach"]
    assert len(logged) == 1 and logged[0].message_id == "<lost.1@mail.example.com>"
    assert imap.searches[0][0] == "[Gmail]/Sent Mail"
    assert imap.searches[0][1] == ("HEADER", "Message-ID", '"lost.1@mail.example.com"')


def test_a_mail_not_in_sent_is_sent_again_with_the_same_message_id(folder):
    root, store, settings = folder
    item = crashed(root, store)
    out, smtp, _ = deliver(store, settings, item.id, scheduled=True)
    assert out.kind == "sent" and len(smtp.sent) == 1
    assert smtp.sent[0]["Message-ID"] == "<lost.1@mail.example.com>"
    after = outreach.get_item(root, item.id)
    assert after.send_tries == 2 and after.state == "sent"


def test_a_mail_that_went_out_is_logged_even_if_they_have_replied_since(folder):
    root, store, settings = folder
    item = crashed(root, store)
    store.create_interaction(MARA[0], "email", "in", subject="Re: hi", contact=MARA[1],
                             body="Thanks\n", date=NOW + timedelta(minutes=1))
    imap = FakeImap()
    imap.deliver("[Gmail]/Sent Mail", raw_mail("sam@mail.example.com",
                                               "mara@lindenhof-data.example.com", "Your second office",
                                               message_id="<lost.1@mail.example.com>"),
                 datetime(2026, 10, 16, 9, 0))
    store.now = lambda: NOW + timedelta(minutes=2)
    out, smtp, _ = deliver(store, settings, item.id, imap=imap, scheduled=True)
    assert out.kind == "recovered" and not smtp.sent


def test_a_mailbox_without_a_sent_folder_cannot_confirm_so_it_does_not_resend(folder):
    root, store, settings = folder
    item = crashed(root, store)
    imap = FakeImap()
    imap.flags["[Gmail]/Sent Mail"] = ""
    out, smtp, _ = deliver(store, settings, item.id, imap=imap, scheduled=True)
    assert out.kind == "retry" and "flagged \\Sent" in out.detail and not smtp.sent


def test_an_imap_login_failure_pauses_with_the_servers_text(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    imap = FakeImap(login_error=imap_error(b"[ALERT] IMAP access is disabled for your domain"))
    out, smtp, _ = deliver(store, settings, item.id, imap=imap)
    assert out.kind == "paused" and "IMAP access is disabled" in out.detail and not smtp.sent
    assert send.SendState.load(root).kind == send.AUTH


# ----------------------------------------------------------------- the lock


def test_only_one_send_runs_at_a_time(folder, monkeypatch):
    root, store, settings = folder
    monkeypatch.setattr(send, "SEND_NOW_WAIT", 0.0)
    with send.SendLock(root):
        with pytest.raises(send.SendBusy):
            with send.SendLock(root):
                pass
        item = ready_item(root, store)
        with pytest.raises(outreach.OutreachError, match="another send is running"):
            send.send_now(store, item.id, settings=settings, smtp_factory=FakeSmtp().factory,
                          imap_factory=FakeImap().factory)
    with send.SendLock(root):
        pass                                           # free again once released


# ------------------------------------------------------------- state files


def test_a_damaged_state_file_reads_as_paused_and_resume_repairs_it(tmp_path):
    root, store, settings = make_folder(tmp_path)
    path = send.runtime_dir(root) / send.STATE_FILE
    path.write_text("{not json", encoding="utf-8")
    state = send.SendState.load(root)
    assert state.paused and state.damaged and state.kind == "state"
    assert state.is_paused(NOW)
    state.resume()
    again = send.SendState.load(root)
    assert not again.paused and not again.damaged


def test_the_state_and_lock_live_in_git_not_in_the_data(folder):
    root, store, settings = folder
    assert send.runtime_dir(root) == root / ".git"
    state = send.SendState.load(root)
    state.pause(send.AUTH, "x", NOW)
    assert (root / ".git" / send.STATE_FILE).exists()
    assert git(root, "status", "--porcelain").strip() == ""


# --------------------------------------------------------------------- mailbox


def test_the_sent_and_all_mail_folders_are_found_by_flag_not_by_name():
    lines = [b'(\\HasNoChildren) "/" "INBOX"',
             b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Gesendet"',
             b'(\\All \\HasNoChildren) "/" "[Gmail]/Alle Nachrichten"',
             b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Entw\xc3\xbcrfe"']
    assert send.special_folders(lines) == {"inbox": "INBOX", "sent": "[Gmail]/Gesendet",
                                           "all": "[Gmail]/Alle Nachrichten"}
    assert send.special_folders([b'(\\HasNoChildren) "/" "INBOX"']) == {"inbox": "INBOX"}


def test_imap_dates_are_rfc_3501_dates():
    assert send.imap_date(datetime(2026, 10, 5).date()) == "05-Oct-2026"


def test_an_unreachable_imap_server_is_a_temporary_error(folder):
    root, store, settings = folder
    imap = FakeImap(connect_error=OSError("Network is unreachable"))
    with pytest.raises(send.SendError) as caught:
        with send.Mailbox(settings, "pw", imap.factory):
            pass
    assert caught.value.kind == send.TEMPORARY and settings.imap_host in caught.value.text
    bad = FakeImap(login_error=imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials"))
    with pytest.raises(send.SendError) as caught:
        with send.Mailbox(settings, "pw", bad.factory):
            pass
    assert caught.value.kind == send.AUTH and "Invalid credentials" in caught.value.text


# ------------------------------------------------------------ the test mail


def test_send_a_test_to_myself_shows_success_and_clears_an_auth_pause(folder):
    root, store, settings = folder
    send.SendState.load(root).pause(send.AUTH, "535 old", NOW)
    smtp, imap = FakeSmtp(), FakeImap()
    result = send.send_test(root, load_config(root), smtp_factory=smtp.factory,
                            imap_factory=imap.factory, now=NOW)
    assert result.ok and "Test mail sent to sam@example.com" in result.text()
    assert "IMAP login" in result.text() and "can run again" in result.text()
    assert len(smtp.sent) == 1 and smtp.sent[0]["To"] == "sam@example.com"
    assert not send.SendState.load(root).paused


def test_a_failing_test_shows_googles_exact_reply(folder):
    root, store, settings = folder
    smtp = FakeSmtp(login_error=auth_error())
    result = send.send_test(root, load_config(root), smtp_factory=smtp.factory,
                            imap_factory=FakeImap().factory, now=NOW)
    assert not result.ok
    assert result.text().startswith("The test failed: 535 5.7.8 Username and Password not accepted")
    assert "BadCredentials" in result.text()


def test_a_test_reports_an_imap_problem_after_the_mail_went(folder):
    root, store, settings = folder
    imap = FakeImap(login_error=imap_error(b"[AUTHENTICATIONFAILED] Invalid credentials"))
    result = send.send_test(root, load_config(root), smtp_factory=FakeSmtp().factory,
                            imap_factory=imap.factory, now=NOW)
    assert not result.ok and "Test mail sent" in result.text() and "reply guard" in result.text()


def test_the_login_check_for_doctor_sends_nothing(folder):
    root, store, settings = folder
    smtp, imap = FakeSmtp(), FakeImap()
    rows = send.login_check(root, load_config(root), smtp_factory=smtp.factory,
                            imap_factory=imap.factory)
    assert [r[:2] for r in rows] == [("smtp login", "ok"), ("send imap login", "ok")]
    assert not smtp.sent
    bad = send.login_check(root, load_config(root), smtp_factory=FakeSmtp(
        login_error=auth_error()).factory, imap_factory=imap.factory)
    assert bad[0][1] == "fail" and "535" in bad[0][2]


# ------------------------------------------------------------ history, caps


def test_only_mail_the_app_sent_counts_toward_the_cap(folder):
    root, store, settings = folder
    store.create_interaction(MARA[0], "email", "out", subject="By hand", contact=MARA[1],
                             body="x\n", date=NOW - timedelta(hours=2))
    assert send.sent_history(store) == []
    store.create_interaction(MARA[0], "email", "out", subject="By app", contact=MARA[1],
                             body="x\n", source="outreach", message_id="<c1@mail.example.com>",
                             date=NOW - timedelta(hours=1))
    store.create_interaction(MARA[0], "linkedin", "out", subject="", contact=MARA[1],
                             body="x\n", source="outreach", date=NOW - timedelta(hours=1))
    history = send.sent_history(store)
    assert len(history) == 1 and history[0].domain == "lindenhof-data.example.com"
    assert send.cap_status(store, settings, NOW) == (1, 10)       # week 1 of the ramp
    assert send.next_window_start(NOW, settings) == datetime(2026, 10, 19, 8, 30)
    assert sendplan.SOFT_CEILING == 150 and valid_email("a@b.example")


def test_a_mailbox_that_cannot_be_reached_is_retried_three_times_and_then_the_item_fails(folder):
    root, store, settings = folder
    item = ready_item(root, store)
    offline = FakeImap(connect_error=OSError("Network is unreachable"))
    for attempt in range(1, 4):
        out, smtp, _ = deliver(store, settings, item.id, imap=offline, scheduled=attempt > 1,
                               now=NOW + timedelta(minutes=20 * attempt))
        after = outreach.get_item(root, item.id)
        assert after.send_tries == attempt and not smtp.sent and after.message_id == ""
        assert out.kind == ("retry" if attempt < 3 else "failed")
    assert after.state == "failed" and after.send_error.startswith("gave up after 3 tries: could not reach")


def test_a_hand_edited_framework_cannot_make_send_now_send_twice(folder):
    """A ready item whose file says `framework: our own thing` (not an id) is sent
    once, logged once and ends sent: the log after SMTP must not raise on it."""
    root, store, settings = folder
    item = ready_item(root, store, framework="our own thing")
    assert outreach.get_item(root, item.id).framework == "our own thing"
    out, smtp, imap = deliver(store, settings, item.id)
    assert out.kind == "sent" and out.done
    assert len(smtp.sent) == 1
    after = outreach.get_item(root, item.id)
    assert after.state == "sent"
    logged = [i for i in store.get(MARA[0]).interactions if i.source == "outreach"]
    assert len(logged) == 1 and after.sent_with == logged[0].id
