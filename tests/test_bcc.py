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

"""BCC import (app/bcc.py): parsing, matching, inbox, IMAP, CLI and routes."""

from __future__ import annotations

import imaplib
import subprocess
from dataclasses import replace
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import cli as crm
from hermitcrm import bcc
from hermitcrm.models import interaction_to_frontmatter, Interaction
from hermitcrm.store import split_file
from hermitcrm.web import create_app
from conftest import FIXED_NOW

SETTINGS = bcc.Settings(address="me+bcc@gmail.com",
                        my_addresses=("me@work.example.com",),
                        ignore_domains=("work.example.com",))
ME = "Sam Owner <me@work.example.com>"
# Today's behaviour with bcc_create_companies = false: unknown domains wait for review.
QUEUE = replace(SETTINGS, create_companies=False)


def raw_mail(subject="Intro", frm=ME, to="Jane Doe <jane@acme.de>", cc=None,
             body="Hi Jane,\n\nShort note.\n\nSam\n", html=None,
             date="Mon, 14 Sep 2026 10:30:00 -0000", mid="<m1@work.example.com>") -> bytes:
    msg = EmailMessage()
    msg["From"] = frm
    if to:
        msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg["Date"] = date
    if mid:
        msg["Message-ID"] = mid
    if html is not None:
        msg.set_content(html, subtype="html")
    else:
        msg.set_content(body)
    return bytes(msg)


def seed(store):
    store.create_company("Acme GmbH", website="acme.de")
    store.create_contact("acme", "Jane", "Doe", email="jane@acme.de")
    store.create_company("Beta", website="https://www.beta.io")
    store.create_company("Gamma", website="gamma.fr")


def inbox_for(store) -> bcc.Inbox:
    return bcc.Inbox(store.root)


# ------------------------------------------------------------------ parsing


@pytest.mark.parametrize("quote", [
    "On Mon, 14 Sept 2026 at 10:30, Jane Doe <jane@acme.de> wrote:",
    "On Mon, 14 Sept 2026 at 10:30, Jane Doe <\njane@acme.de> wrote:",
    "Am Mo., 14. Sept. 2026 um 10:30 Uhr schrieb Jane Doe <jane@acme.de>:",
    "Op ma 14 sep 2026 om 10:30 schreef Jane Doe <jane@acme.de>:",
    "Le lun. 14 sept. 2026 à 10:30, Jane Doe <jane@acme.de> a écrit :",
    "________________________________\nVon: Jane Doe <jane@acme.de>\n"
    "Gesendet: Montag, 14. September 2026 10:30\nAn: Sam\nBetreff: Intro",
    "-----Original Message-----\nFrom: Jane",
    "> quoted line\n> another",
])
def test_strip_quoted_cuts_the_thread(quote):
    text = f"Thanks Jane,\n\nsee you Tuesday.\n\nSam\n\n{quote}\n> old text\n> more old\n"
    assert bcc.strip_quoted(text) == "Thanks Jane,\n\nsee you Tuesday.\n\nSam\n"


def test_strip_quoted_keeps_a_plain_mail():
    text = "Hi Jane,\n\nOn Monday we spoke about 3 things.\nFrom: me, with love\n\nSam\n"
    assert bcc.strip_quoted(text) == text


def test_parse_mail_headers_and_html_fallback():
    raw = raw_mail(html="<html><head><style>p{}</style></head><body><div>Hi&nbsp;Jane,"
                        "</div><p>Line two<br>Line three</p></body></html>",
                   to="Jane Doe <JANE@acme.de>, bob@beta.io", cc="Cy <cy@gamma.fr>")
    mail = bcc.parse_mail(raw, FIXED_NOW)
    assert mail.message_id == "<m1@work.example.com>"
    assert mail.date == datetime(2026, 9, 14, 10, 30)
    assert mail.sender == ("Sam Owner", "me@work.example.com")
    assert mail.to == [("Jane Doe", "jane@acme.de"), ("", "bob@beta.io")]
    assert mail.cc == [("Cy", "cy@gamma.fr")]
    assert mail.text == "Hi Jane,\n\nLine two\nLine three"


def test_parse_mail_without_message_id_or_date_is_stable():
    msg = EmailMessage()
    msg["From"] = ME
    msg["To"] = "jane@acme.de"
    msg.set_content("x")
    raw = bytes(msg)
    a, b = bcc.parse_mail(raw, FIXED_NOW), bcc.parse_mail(raw, FIXED_NOW)
    assert a.message_id == b.message_id and a.message_id.endswith("@crm.local>")
    assert a.date == FIXED_NOW


def test_parse_forward_gmail_reply():
    text = ("FYI\n\n---------- Forwarded message ---------\n"
            "From: Jane Doe <jane@acme.de>\n"
            "Date: Tue, Sep 15, 2026 at 9:05 AM\n"
            "Subject: Re: Intro\n"
            "To: Sam Owner <me@work.example.com>\n\n"
            "Sounds good, Tuesday works.\n\n"
            "On Mon, 14 Sept 2026 at 10:30, Sam Owner <me@work.example.com> wrote:\n"
            "> Hi Jane\n")
    fwd = bcc.parse_forward(text, "Fwd: Re: Intro")
    assert fwd.sender == ("Jane Doe", "jane@acme.de")
    assert fwd.date == datetime(2026, 9, 15, 9, 5)
    assert fwd.subject == "Re: Intro"
    assert bcc.strip_quoted(fwd.body) == "Sounds good, Tuesday works.\n"


def test_parse_forward_outlook_block_needs_forward_subject():
    text = ("\n________________________________\n"
            "From: Jane Doe [mailto:jane@acme.de]\n"
            "Sent: Tuesday, September 15, 2026 9:05 AM\n"
            "To: Sam Owner; Bob <bob@beta.io>\n"
            "Subject: Re: Intro\n\nYes please.\n")
    fwd = bcc.parse_forward(text, "FW: Re: Intro")
    assert fwd.sender == ("Jane Doe", "jane@acme.de")
    assert fwd.date == datetime(2026, 9, 15, 9, 5)
    assert fwd.to == [("Bob", "bob@beta.io")]
    assert fwd.body == "Yes please."
    assert bcc.parse_forward(text, "Re: Intro") is None


def test_entries_skip_me_bcc_address_colleagues_and_repeats():
    raw = raw_mail(to="Jane <jane@acme.de>, me+bcc@gmail.com, Col <col@work.example.com>",
                   cc="jane@acme.de, bob@beta.io")
    entries = bcc.entries_for_mail(bcc.parse_mail(raw, FIXED_NOW), SETTINGS)
    assert [(e.address, e.direction) for e in entries] == [
        ("jane@acme.de", "out"), ("bob@beta.io", "out")]
    assert entries[0].body == "Hi Jane,\n\nShort note.\n\nSam\n"


def test_entries_own_mail_forwarded_later_is_outbound():
    body = ("---------- Forwarded message ---------\n"
            "From: Sam Owner <me@work.example.com>\n"
            "Date: Mon, Sep 14, 2026 at 8:00 AM\nSubject: Intro\n"
            "To: Jane Doe <jane@acme.de>\n\nHi Jane, forgot the BCC.\n")
    raw = raw_mail(subject="Fwd: Intro", to="me+bcc@gmail.com", body=body)
    [entry] = bcc.entries_for_mail(bcc.parse_mail(raw, FIXED_NOW), SETTINGS)
    assert (entry.direction, entry.address, entry.subject) == ("out", "jane@acme.de", "Intro")
    assert entry.date == datetime(2026, 9, 14, 8, 0)


def test_name_parts():
    assert bcc.name_parts("Doe, Jane", "x@y.z") == ("Jane", "Doe")
    assert bcc.name_parts("", "jan-willem.de.vries@y.nl") == ("Jan", "Willem De Vries")
    assert bcc.name_parts("'jane@acme.de'", "jane@acme.de") == ("Jane", "")


# ----------------------------------------------------------------- matching


def test_match_address(store):
    seed(store)
    store.create_company("Beta Two", website="beta.io")
    assert bcc.match_address(store, "jane@acme.de") == bcc.Match("log", "acme", "jane-doe")
    assert bcc.match_address(store, "new@acme.de").action == "create-contact"
    assert bcc.match_address(store, "x@sales.gamma.fr") == bcc.Match("create-contact", "gamma")
    assert bcc.match_address(store, "x@gmail.com").reason == "personal address (gmail.com)"
    assert bcc.match_address(store, "x@beta.io").reason == "domain beta.io matches beta, beta-two"
    assert bcc.match_address(store, "x@nowhere.org").reason == "no company with domain nowhere.org"


def test_import_logs_creates_and_queues_in_one_commit(store, messages):
    seed(store)
    messages.clear()
    raw = raw_mail(to="Jane Doe <jane@acme.de>, Bob Stone <bob@beta.io>",
                   cc="x@gmail.com, col@work.example.com, y@nowhere.org",
                   body="Hi all,\n\nNote.\n\nOn Sun, 13 Sept 2026 at 9:00, Jane <jane@acme.de> wrote:\n> old\n")
    result = bcc.import_mails(store, inbox_for(store), [raw], SETTINGS, apply=True)
    assert (result.logged, result.companies, result.contacts, result.review,
            result.duplicates) == (3, 1, 2, 1, 0)
    assert messages == ["bcc: imported 1 mail (3 interactions, 1 companies, 2 contacts, "
                        "1 to review)"]

    [jane_it] = store.companies["acme"].interactions
    assert (jane_it.contact, jane_it.source, jane_it.message_id, jane_it.direction) == (
        "jane-doe", "bcc-import", "<m1@work.example.com>", "out")
    assert jane_it.body == "Hi all,\n\nNote.\n"
    assert jane_it.date == datetime(2026, 9, 14, 10, 30)
    meta, body = split_file((store.root / "companies/acme/interactions"
                             / f"{jane_it.id}.md").read_text(encoding="utf-8"))
    assert meta["message_id"] == "<m1@work.example.com>" and meta["source"] == "bcc-import"

    bob = store.companies["beta"].contacts["bob-stone"]
    assert bob.email == "bob@beta.io"
    assert store.companies["beta"].interactions[0].contact == "bob-stone"

    nowhere = store.companies["nowhere"]
    assert (nowhere.name, nowhere.website) == ("Nowhere", "https://nowhere.org")
    assert nowhere.contacts["y"].email == "y@nowhere.org"

    [item] = inbox_for(store).items()
    assert (item.address, item.reason) == ("x@gmail.com", "personal address (gmail.com)")


def test_domain_match_fills_email_of_existing_contact_instead_of_duplicating(store, messages):
    seed(store)
    store.create_contact("gamma", "Ann", "Lee")
    messages.clear()
    raws = [raw_mail(to="Ann Lee <ann@gamma.fr>"),
            raw_mail(to="ann@gamma.fr", mid="<m2@work.example.com>")]
    dry = bcc.import_mails(store, inbox_for(store), raws, SETTINGS)
    assert [line.split(" | ", 3)[3] for line in dry.lines] == [
        "gamma/ann-lee | email added, log", "gamma/ann-lee | log"]
    result = bcc.import_mails(store, inbox_for(store), raws, SETTINGS, apply=True)
    assert (result.logged, result.contacts) == (2, 0)
    assert list(store.companies["gamma"].contacts) == ["ann-lee"]
    assert store.companies["gamma"].contacts["ann-lee"].email == "ann@gamma.fr"
    assert [i.contact for i in store.companies["gamma"].interactions] == ["ann-lee", "ann-lee"]
    assert messages == ["bcc: imported 2 mails (2 interactions, 0 companies, 0 contacts, "
                        "0 to review)"]


def test_import_twice_changes_nothing(store, messages):
    seed(store)
    raw = raw_mail(to="jane@acme.de, bob@beta.io, y@nowhere.org")
    inbox = inbox_for(store)
    bcc.import_mails(store, inbox, [raw], SETTINGS, apply=True)
    messages.clear()
    again = bcc.import_mails(store, inbox, [raw], SETTINGS, apply=True)
    assert (again.logged, again.companies, again.contacts, again.review,
            again.duplicates) == (0, 0, 0, 0, 3)
    assert messages == []
    assert len(store.companies["acme"].interactions) == 1
    assert len(store.companies["nowhere"].interactions) == 1
    assert inbox.count() == 0


def test_dry_run_writes_nothing(store, messages):
    seed(store)
    messages.clear()
    raws = [raw_mail(to="bob@beta.io, y@nowhere.org"),
            raw_mail(to="bob@beta.io", mid="<m2@work.example.com>")]
    result = bcc.import_mails(store, inbox_for(store), raws, SETTINGS, apply=False)
    assert (result.logged, result.companies, result.contacts, result.review) == (3, 1, 2, 0)
    assert result.lines == [
        "2026-09-14 10:30 | email out | bob@beta.io | beta | new contact Bob, log",
        "2026-09-14 10:30 | email out | y@nowhere.org | new company from nowhere.org "
        "| new contact Y, log",
        "2026-09-14 10:30 | email out | bob@beta.io | beta (new contact) | log",
    ]
    assert messages == [] and store.companies["beta"].contacts == {}
    assert "nowhere" not in store.companies
    assert not (store.root / "inbox").exists()


def test_unknown_domain_creates_the_company_then_the_contact(store, messages):
    seed(store)
    messages.clear()
    raw = raw_mail(to="Nina Park <nina@parkworks.example>")
    result = bcc.import_mails(store, inbox_for(store), [raw], SETTINGS, apply=True)
    assert (result.logged, result.companies, result.contacts, result.review) == (1, 1, 1, 0)
    assert result.lines == ["2026-09-14 10:30 | email out | nina@parkworks.example "
                            "| parkworks/nina-park | new company, new contact, log"]
    assert messages == ["bcc: imported 1 mail (1 interactions, 1 companies, 1 contacts, "
                        "0 to review)"]
    company = store.companies["parkworks"]
    assert (company.name, company.website, company.stage) == (
        "Parkworks", "https://parkworks.example", "engaged")
    assert company.notes == ("Created by the BCC import from a mail to "
                             "nina@parkworks.example (2026-09-14).\n")
    assert company.contacts["nina-park"].email == "nina@parkworks.example"
    [it] = company.interactions
    assert (it.contact, it.message_id, it.source) == (
        "nina-park", "<m1@work.example.com>", "bcc-import")


def test_two_people_at_one_new_domain_make_one_company(store):
    seed(store)
    raws = [raw_mail(to="nina@parkworks.example, Omar Reed <omar@parkworks.example>")]
    dry = bcc.import_mails(store, inbox_for(store), raws, SETTINGS)
    assert [line.split(" | ", 3)[3] for line in dry.lines] == [
        "new company from parkworks.example | new contact Nina, log",
        "parkworks.example (new company) | new contact Omar Reed, log"]
    assert (dry.companies, dry.contacts, dry.logged) == (1, 2, 2)
    assert "parkworks" not in store.companies
    result = bcc.import_mails(store, inbox_for(store), raws, SETTINGS, apply=True)
    assert (result.companies, result.contacts, result.logged) == (1, 2, 2)
    assert sorted(store.companies["parkworks"].contacts) == ["nina", "omar-reed"]


@pytest.mark.parametrize("raw, settings, reason", [
    (raw_mail(frm="Nina Park <nina@parkworks.example>", to="me+bcc@gmail.com"), SETTINGS,
     "no company with domain parkworks.example (mail not sent by you, so none created)"),
    (raw_mail(to="noreply@parkworks.example"), SETTINGS,
     "no company with domain parkworks.example (no-reply address, so none created)"),
    (raw_mail(to="ann@gamma.com"), SETTINGS,
     "no company with domain gamma.com (Gamma has the same name, so none created)"),
    (raw_mail(to="nina@parkworks.example"), QUEUE, "no company with domain parkworks.example"),
], ids=["not-sent-by-you", "no-reply", "same-name", "switched-off"])
def test_unknown_domain_waits_for_review_when_no_company_is_made(store, raw, settings, reason):
    seed(store)
    result = bcc.import_mails(store, inbox_for(store), [raw], settings, apply=True)
    assert (result.companies, result.review) == (0, 1)
    assert [i.reason for i in inbox_for(store).items()] == [reason]
    assert sorted(store.companies) == ["acme", "beta", "gamma"]


def test_queued_or_discarded_mail_never_makes_a_company(store):
    seed(store)
    inbox = inbox_for(store)
    raws = [raw_mail(to="nina@parkworks.example"),
            raw_mail(to="omar@reedco.example", mid="<m2@work.example.com>")]
    bcc.import_mails(store, inbox, raws, QUEUE, apply=True)
    bcc.discard(store, inbox, next(i.id for i in inbox.items()
                                   if i.address == "omar@reedco.example"))
    again = bcc.import_mails(store, inbox, raws, SETTINGS, apply=True)
    assert (again.companies, again.duplicates) == (0, 2)
    assert sorted(store.companies) == ["acme", "beta", "gamma"]


def test_create_companies_is_on_unless_config_says_false():
    assert bcc.settings_from_config({}).create_companies is True
    assert bcc.settings_from_config({"bcc_create_companies": False}).create_companies is False


def test_skipped_mail_without_external_address(store):
    result = bcc.import_mails(store, inbox_for(store),
                              [raw_mail(to="col@work.example.com")], SETTINGS)
    assert result.skipped == 1 and result.lines[0].endswith("skipped: no external address")


def test_forwarded_reply_is_inbound_and_marks_message_success(store):
    seed(store)
    inbox = inbox_for(store)
    bcc.import_mails(store, inbox, [raw_mail()], SETTINGS, apply=True)
    fwd = raw_mail(subject="Fwd: Re: Intro", to="me+bcc@gmail.com", mid="<m2@work.example.com>",
                   date="Tue, 15 Sep 2026 12:00:00 -0000",
                   body="---------- Forwarded message ---------\n"
                        "From: Jane Doe <jane@acme.de>\n"
                        "Date: Tue, Sep 15, 2026 at 9:05 AM\nSubject: Re: Intro\n"
                        "To: Sam Owner <me@work.example.com>\n\nYes, Tuesday.\n")
    bcc.import_mails(store, inbox, [fwd], SETTINGS, apply=True)
    company = store.companies["acme"]
    inbound, outbound = company.interactions
    assert (inbound.direction, inbound.subject, inbound.body) == ("in", "Re: Intro",
                                                                  "Yes, Tuesday.\n")
    assert company.message_status(outbound, FIXED_NOW.date()) == "success"


def test_interaction_frontmatter_has_message_id_only_when_set():
    it = Interaction(id="x", date=FIXED_NOW, channel="email", direction="out")
    assert "message_id" not in interaction_to_frontmatter(it)
    it.message_id = "<a@b>"
    assert list(interaction_to_frontmatter(it))[-1] == "message_id"


# -------------------------------------------------------------------- inbox


def test_assign_creates_contact_and_rerun_skips(store, messages):
    seed(store)
    inbox = inbox_for(store)
    raw = raw_mail(to="Ann Lee <ann@lee-consulting.com>")
    bcc.import_mails(store, inbox, [raw], QUEUE, apply=True)
    [item] = inbox.items()
    assert (item.first_name, item.last_name) == ("Ann", "Lee")
    messages.clear()
    slug, it = bcc.assign(store, inbox, item.id, "Gamma")
    assert slug == "gamma" and it.contact == "ann-lee" and it.source == "bcc-import"
    assert messages == [f"bcc: {item.id} assigned to gamma/ann-lee"]
    assert inbox.count() == 0
    again = bcc.import_mails(store, inbox, [raw], QUEUE, apply=True)
    assert again.duplicates == 1 and inbox.count() == 0


def test_assign_fills_email_of_same_named_contact(store):
    seed(store)
    store.create_contact("gamma", "Ann", "Lee")
    inbox = inbox_for(store)
    bcc.import_mails(store, inbox, [raw_mail(to="Ann Lee <ann@lee.com>")], QUEUE,
                     apply=True)
    [item] = inbox.items()
    bcc.assign(store, inbox, item.id, "gamma")
    assert list(store.companies["gamma"].contacts) == ["ann-lee"]
    assert store.companies["gamma"].contacts["ann-lee"].email == "ann@lee.com"


def test_assign_to_a_new_name_creates_the_company(store, messages):
    seed(store)
    inbox = inbox_for(store)
    bcc.import_mails(store, inbox, [raw_mail(to="Ann Lee <ann@leeconsult.example>")], QUEUE,
                     apply=True)
    [item] = inbox.items()
    messages.clear()
    slug, it = bcc.assign(store, inbox, item.id, "Lee Consulting")
    company = store.companies[slug]
    assert (slug, company.name, company.website) == (
        "lee-consulting", "Lee Consulting", "https://leeconsult.example")
    assert it.contact == "ann-lee"
    assert company.contacts["ann-lee"].email == "ann@leeconsult.example"
    assert messages == [f"bcc: {item.id} assigned to lee-consulting/ann-lee (new company)"]
    assert inbox.count() == 0


def test_assign_finds_a_name_without_legal_suffix_or_the_mail_domain(store):
    seed(store)
    inbox = inbox_for(store)
    bcc.import_mails(store, inbox, [raw_mail(to="ann@leeconsult.example"),
                                    raw_mail(to="bo@bo.example", mid="<m2@work.example.com>")],
                     QUEUE, apply=True)
    ann, bo = sorted(inbox.items(), key=lambda i: i.address)
    store.create_company("LC Partners", website="leeconsult.example")
    assert bcc.assign(store, inbox, ann.id, "Lee Consult")[0] == "lc-partners"
    assert bcc.assign(store, inbox, bo.id, "gamma gmbh")[0] == "gamma"
    assert sorted(store.companies) == ["acme", "beta", "gamma", "lc-partners"]


def test_assign_new_company_for_a_personal_address_has_no_website(store):
    inbox = inbox_for(store)
    bcc.import_mails(store, inbox, [raw_mail(to="Ann Lee <ann.lee@gmail.com>")], SETTINGS,
                     apply=True)
    [item] = inbox.items()
    with pytest.raises(bcc.ValidationError) as exc:
        bcc.assign(store, inbox, item.id, "  ")
    assert exc.value.errors == {"company": "pick a company"}
    slug, _ = bcc.assign(store, inbox, item.id, "Ann Lee Advisory")
    assert (slug, store.companies[slug].website) == ("ann-lee-advisory", "")


def test_discard_is_remembered(store, messages):
    inbox = inbox_for(store)
    raw = raw_mail(to="y@nowhere.org")
    bcc.import_mails(store, inbox, [raw], QUEUE, apply=True)
    [item] = inbox.items()
    messages.clear()
    bcc.discard(store, inbox, item.id)
    assert messages == [f"bcc: {item.id} discarded"] and inbox.count() == 0
    again = bcc.import_mails(store, inbox, [raw], SETTINGS, apply=True)
    assert again.duplicates == 1 and inbox.count() == 0 and store.companies == {}


def test_inbox_rejects_path_ids(store):
    assert inbox_for(store).get("../companies/acme/company") is None


def test_run_alert():
    now = datetime(2026, 9, 15, 8, 0)
    assert bcc.run_alert(None, now) == ""
    assert bcc.run_alert({"ok": True, "at": "2026-09-15T07:00"}, now) == ""
    assert bcc.run_alert({"ok": True, "at": "2026-09-12T07:00"}, now) == "no BCC import for 3 days"
    assert bcc.run_alert({"ok": False, "at": "2026-09-15T07:00", "error": "boom"},
                         now) == "BCC import failed: boom"


# --------------------------------------------------------------------- imap


class FakeIMAP:
    def __init__(self, host, port, timeout=None, mails=(), login_error=None):
        self.calls = [("connect", host, port)]
        self.mails = dict(mails)
        self.login_error = login_error

    def login(self, user, password):
        self.calls.append(("login", user, password))
        if self.login_error:
            raise imaplib.IMAP4.error(self.login_error)

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"',
                      b'(\\All \\HasNoChildren) "/" "[Gmail]/Alle berichten"']

    def select(self, name):
        self.calls.append(("select", name))
        return "OK", [b"3"]

    def uid(self, command, *args):
        self.calls.append(("uid", command) + args)
        if command == "SEARCH":
            return "OK", [b" ".join(self.mails)]
        if command == "FETCH":
            return "OK", [(b"1 (UID " + args[0] + b" BODY[] {9}", self.mails[args[0]]), b")"]
        return "OK", [None]

    def logout(self):
        self.calls.append(("logout",))


def test_gmail_mailbox_reads_all_mail_and_marks_read():
    fake = {}

    def factory(host, port, timeout=None):
        fake["imap"] = FakeIMAP(host, port, timeout, mails={b"7": b"raw7", b"9": b"raw9"})
        return fake["imap"]

    with bcc.GmailMailbox(SETTINGS, "pw", imap_factory=factory) as box:
        assert box.fetch() == [(b"7", b"raw7"), (b"9", b"raw9")]
        box.mark_read([b"7", b"9"])
    calls = fake["imap"].calls
    assert ("login", "me@gmail.com", "pw") in calls
    assert ("select", '"[Gmail]/Alle berichten"') in calls
    assert ("uid", "SEARCH", "X-GM-RAW",
            '"deliveredto:me+bcc@gmail.com newer_than:30d"') in calls
    assert ("uid", "STORE", b"7,9", "+FLAGS", "(\\Seen)") in calls
    assert calls[-1] == ("logout",)


def test_gmail_mailbox_login_failure_is_readable():
    factory = lambda host, port, timeout=None: FakeIMAP(
        host, port, login_error=b"[AUTHENTICATIONFAILED] Invalid credentials")
    with pytest.raises(bcc.BccError, match="Invalid credentials.*app password.*keyring, service 'crm-bcc'"):
        with bcc.GmailMailbox(SETTINGS, "pw", imap_factory=factory):
            pass


class FakeBox:
    def __init__(self, raws=(), error=None):
        self.raws = list(raws)
        self.error = error
        self.marked = None

    def __enter__(self):
        if self.error:
            raise bcc.BccError(self.error)
        return self

    def __exit__(self, *exc):
        return None

    def fetch(self):
        return [(str(i).encode(), raw) for i, raw in enumerate(self.raws)]

    def mark_read(self, uids):
        self.marked = uids


def test_run_bcc_marks_read_and_records_run(store):
    seed(store)
    inbox = inbox_for(store)
    box = FakeBox([raw_mail()])
    result = bcc.run_bcc(store, inbox, SETTINGS, True, lambda: box)
    assert result.logged == 1 and box.marked == [b"0"]
    assert inbox.last_run() == {"at": "2026-09-14T10:30", "ok": True,
                                "summary": result.summary(), "error": ""}
    with pytest.raises(bcc.BccError):
        bcc.run_bcc(store, inbox, SETTINGS, True, lambda: FakeBox(error="no network"))
    assert inbox.last_run()["ok"] is False and inbox.last_run()["error"] == "no network"


def test_run_bcc_dry_run_neither_marks_nor_records(store):
    box = FakeBox([raw_mail()])
    bcc.run_bcc(store, inbox_for(store), SETTINGS, False, lambda: box)
    assert box.marked is None and inbox_for(store).last_run() is None


# ---------------------------------------------------------------------- cli


def test_cmd_bcc_with_eml_files(store, tmp_path):
    seed(store)
    path = tmp_path / "one.eml"
    path.write_bytes(raw_mail())
    config = {"bcc_address": "me+bcc@gmail.com", "my_addresses": ["me@work.example.com"]}
    text, code = crm.cmd_bcc(store, store.root, config, eml=[path])
    assert code == 0
    assert text.splitlines() == [
        "2026-09-14 10:30 | email out | jane@acme.de | acme/jane-doe | log",
        "1 mails read: 1 interactions logged, 0 companies created, 0 contacts created, "
        "0 to review, 0 already imported, 0 skipped",
        "Dry run; add --apply to write and mark the mails read.",
    ]
    text, code = crm.cmd_bcc(store, store.root, config,
                             open_mailbox=lambda: FakeBox(error="no app password"))
    assert (text, code) == ("BCC import failed: no app password", 1)


# -------------------------------------------------------------------- web


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for args in (["init", "-b", "main"], ["config", "user.name", "CRM Test"],
                 ["config", "user.email", "crm@test.local"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    return tmp_path


@pytest.fixture
def client(repo):
    app = create_app(repo, config={"port": 8765, "silent_days": 14, "push_enabled": False,
                                   "remote": "origin", "bcc_address": "me+bcc@gmail.com",
                                   "my_addresses": ["me@work.example.com"],
                                   "bcc_ignore_domains": ["work.example.com"]})
    c = TestClient(app, follow_redirects=False)
    c.app_state = app.state
    return c


def last_commit(repo: Path) -> str:
    return subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()


def test_inbox_routes_end_to_end(client, repo):
    client.post("/companies", data={"name": "Acme GmbH", "website": "acme.de",
                                    "source": "other", "stage": "prospect"})
    client.app_state.open_mailbox = lambda: FakeBox(
        [raw_mail(to="Jane Doe <jane@acme.de>, Ann Lee <ann.lee@gmail.com>")])

    page = client.get("/settings").text
    assert "No import has run yet." in page and "me+bcc@gmail.com" in page

    r = client.post("/bcc/import")
    assert r.status_code == 303 and "BCC%20import%3A%201%20mails%20read" in r.headers["location"]
    assert last_commit(repo) == ("bcc: imported 1 mail (1 interactions, 0 companies, "
                                 "1 contacts, 1 to review)")
    assert (repo / "companies/acme/contacts/jane-doe.md").exists()

    page = client.get("/settings").text
    assert '<span class="badge">1</span>' in page and "ann.lee@gmail.com" in page and 'value="Ann"' in page
    assert "Last import 2026" not in page or "1 interactions logged" in page
    item_id = client.app_state.inbox.items()[0].id

    r = client.post(f"/inbox/{item_id}/assign", data={"company": ""})
    assert r.status_code == 400 and "pick a company" in r.text

    r = client.post(f"/inbox/{item_id}/assign",
                    data={"company": "Lee Advisory", "first_name": "Ann", "last_name": "Lee"})
    assert r.status_code == 303
    assert "Logged%20at%20lee-advisory%2Fann-lee%20%28new%20company%20Lee%20Advisory%29" \
        in r.headers["location"]
    assert last_commit(repo) == f"bcc: {item_id} assigned to lee-advisory/ann-lee (new company)"
    assert "Settings (1)" not in client.get("/settings").text
    assert client.post("/inbox/nope/discard").status_code == 404


def test_import_now_failure_is_flashed_and_flagged(client):
    client.app_state.open_mailbox = lambda: FakeBox(error="Gmail refused the login")
    r = client.post("/bcc/import")
    assert "refused" in r.headers["location"]
    page = client.get("/calendar").text
    assert 'class="alert" title="BCC import failed: Gmail refused the login"' in page


def test_discard_route(client, repo):
    client.app_state.open_mailbox = lambda: FakeBox([raw_mail(to="y@gmail.com")])
    client.post("/bcc/import")
    item_id = client.app_state.inbox.items()[0].id
    r = client.post(f"/inbox/{item_id}/discard")
    assert r.status_code == 303 and last_commit(repo) == f"bcc: {item_id} discarded"
    assert (repo / "inbox/discarded.tsv").read_text() == "<m1@work.example.com>\ty@gmail.com\n"
