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

"""Phase 2 of the outreach bot: the Outreach page, the Ready list, replies to
interest, the contact page's button, the `interested` outcome and the
playbook's first step offer (spec part 04)."""

from __future__ import annotations

import re
from datetime import datetime

import pytest
import yaml
from fastapi.testclient import TestClient

from hermitcrm import outreach, playbook
from hermitcrm.datafolder import init_folder
from hermitcrm.enrich import Enricher
from hermitcrm.models import INTERESTED
from hermitcrm.store import Store, load_config
from hermitcrm.web import create_app

from outreach_fakes import ALL, NOW, FakeAI, fake_page, git

OFFER = "I work as your fractional Head of Sales: part-time, no minimum term."


def offer_of(root, item) -> str:
    return playbook.load(root).approach(item.approach).offer_line


def reply_draft(prompt):
    """A reply to interest that follows the shape: the offer line, one question."""
    first = re.search(r"^Person: (\S+)", prompt, re.M).group(1)
    offer = re.search(r"--- offer line \(approach \"[^\"]+\"\) ---\n(.+)\n", prompt).group(1)
    step = re.search(r"--- first step offer ---\n(.+)\n", prompt).group(1)
    step = "" if step.startswith("none") else " " + step
    return {"subject": "", "angle": "custom", "pitch": "", "findings_used": [],
            "proof_used": [],
            "body": f"Hi {first},\n\nThanks for asking. {offer}{step}\n"
                    "Where does it hurt most right now: pipeline, conversion or deal size?"
                    "\n\nSam"}


class Runner:
    """FakeAI plus the reply classification and the reply drafts."""

    def __init__(self, verdict="interest"):
        self.fake = FakeAI()
        self.verdict = verdict
        self.calls = self.fake.calls

    def __call__(self, prompt, schema, **kwargs):
        if schema is outreach.CLASSIFY_SCHEMA:
            self.calls.append({"kind": "classify", "prompt": prompt, **kwargs})
            return {"verdict": self.verdict, "why": "They ask what the offer is."}
        if "This is a reply to someone" in prompt:
            self.calls.append({"kind": "reply", "prompt": prompt, **kwargs})
            return reply_draft(prompt)
        return self.fake(prompt, schema, **kwargs)

    def of(self, kind, about=""):
        return [c for c in self.calls if c["kind"] == kind and about in c["prompt"]]


@pytest.fixture
def folder(tmp_path):
    return init_folder(tmp_path / "crm", demo=True, now=NOW)


def make_client(root, runner=None, available=True):
    config = {**load_config(root), "push_enabled": False, "owner_name": "Sam Example"}
    app = create_app(root, config, clock=lambda: NOW)
    app.state.setup_redirected = True
    runner = runner or Runner()
    which = ALL if available else (lambda binary: None)
    app.state.enricher = Enricher(provider="claude", which=which, runner=runner)
    app.state.fetcher = fake_page
    app.state.run_background = lambda fn: fn()   # the build runs before the redirect
    client = TestClient(app, follow_redirects=False)
    client.runner = runner
    return client


@pytest.fixture
def client(folder):
    return make_client(folder)


def token(client):
    return client.app.state.csrf_token


def commits(root) -> list[str]:
    return git(root, "log", "--format=%s").splitlines()


def changed(root, ref="HEAD") -> list[str]:
    return git(root, "show", "--name-only", "--format=", ref).split()


def build(client, limit=3, channel="email"):
    r = client.post("/outreach/build", data={
        "csrf_token": token(client), "where": "stage=prospect", "kind": "first-touch",
        "channel": channel, "limit": str(limit)})
    assert r.status_code == 303, r.text
    return outreach.items(client.app.state.store.root)


def item_for(root, record):
    return next(i for i in outreach.items(root) if i.record == record)


def log_reply(client, slug="kestrel-metrics", contact="daan-visser", outcome="",
              body="Sounds interesting. What exactly do you offer?", subject="Your note"):
    """An outbound message, then their reply (inbound, newest)."""
    store = client.app.state.store
    store.create_interaction(slug, "email", "out", subject=subject, contact=contact,
                             body="Hi, a question for you.\n", date=datetime(2026, 10, 10, 9))
    return store.create_interaction(slug, "email", "in", subject=f"Re: {subject}",
                                    contact=contact, body=body + "\n", outcome=outcome,
                                    date=datetime(2026, 10, 15, 9))


# ------------------------------------------------------------------ the page


def test_the_page_renders_on_the_demo_folder_with_every_tab(client):
    r = client.get("/outreach")
    assert r.status_code == 200
    assert 'href="/outreach"' in r.text and "Build queue" in r.text and "Preview" in r.text
    assert '<select name="channel" required>' in r.text
    for tab, label in (("replies", "Replies to interest"), ("followups", "Follow-ups"),
                       ("first", "First touches"), ("ready", "Ready"), ("skipped", "Skipped")):
        page = client.get(f"/outreach?tab={tab}")
        assert page.status_code == 200 and f"{label} (" in page.text
    assert client.runner.calls == []   # rendering never asks the AI


def test_preview_writes_nothing_and_says_who_and_why_not(client, folder):
    before = commits(folder)
    r = client.post("/outreach/preview", data={
        "csrf_token": token(client), "where": "stage=prospect", "kind": "first-touch",
        "channel": "email", "limit": "2"})
    assert r.status_code == 200
    assert "Preview: 2 of up to 2" in r.text and "Not this time" in r.text
    assert "Ravenmoor" in r.text and "do-not-contact" in r.text
    assert commits(folder) == before and not (folder / "outreach").exists()
    assert client.runner.calls == []


def test_the_filter_box_splits_on_semicolons_not_commas():
    from hermitcrm.outreach_web import split_where
    assert split_where("stage=prospect; country=DE,NL\ncontact.title=CEO") == [
        "stage=prospect", "country=DE,NL", "contact.title=CEO"]


def test_build_queue_runs_in_the_background_and_cards_appear(client, folder):
    found = build(client)
    assert len(found) == 3 and all(i.state == "drafted" for i in found)
    job = client.get("/outreach/job").json()
    assert job["running"] is False and job["done"] == 3 and len(job["ids"]) == 3
    page = client.get("/outreach?tab=first").text
    assert page.count('class="card outreach-card') == 3
    first = found[0]
    card = client.get(f"/outreach/card/{first.id}").text
    assert f'id="item-{first.id}"' in card and "Mark ready" in card and "Check again" in card
    assert "Regenerate" in card and "Skip" in card and "data-copy" in card
    assert "Opened a second office this autumn" in card   # a finding, with its source
    assert git(folder, "status", "--porcelain") == ""


def test_build_without_a_channel_or_with_a_later_kind_is_refused(client, folder):
    r = client.post("/outreach/build", data={"csrf_token": token(client), "kind": "first-touch",
                                             "channel": "", "where": "stage=prospect"})
    assert r.status_code == 400 and "use email or linkedin" in r.text
    r = client.post("/outreach/build", data={"csrf_token": token(client), "kind": "follow-up",
                                             "channel": "email", "where": "stage=prospect"})
    assert r.status_code == 400 and "later version" in r.text
    assert not (folder / "outreach").exists()


def test_csrf_is_required(client):
    r = client.post("/outreach/build", data={"kind": "first-touch", "channel": "email"})
    assert r.status_code == 403


# --------------------------------------------------- the card's buttons


def test_a_cards_buttons_change_only_the_item(client, folder):
    found = build(client)
    a, b, c = sorted(found, key=lambda i: i.id)
    t = token(client)
    # Check again: the edited text, checked; one commit touching only the item
    r = client.post(f"/outreach/{a.id}/check", data={
        "csrf_token": t, "subject": a.subject, "body": a.body.replace("deal size?", "deal size.")})
    assert r.status_code == 303
    assert changed(folder) == [a.path]
    again = outreach.get_item(folder, a.id)
    assert again.state == "drafted"
    assert again.checks == ["the message asks 0 questions; it must ask exactly one"]
    # Skip: the state and the reason, nothing else
    client.post(f"/outreach/{b.id}/skip", data={"csrf_token": t, "reason": "bad-timing",
                                                "note": "after the summer"})
    assert changed(folder) == [b.path]
    skipped = outreach.get_item(folder, b.id)
    assert (skipped.state, skipped.skip_reason, skipped.skip_note) == (
        "skipped", "bad-timing", "after the summer")
    # A skip needs a reason from the list
    r = client.post(f"/outreach/{c.id}/skip", data={"csrf_token": t, "reason": "meh"})
    assert outreach.get_item(folder, c.id).state == "drafted"
    # Mark sent on a ready item: the state only, no interaction
    store = client.app.state.store
    touches = sum(len(co.interactions) for co in store.all())
    client.post(f"/outreach/{c.id}/ready", data={"csrf_token": t})
    client.post(f"/outreach/{c.id}/sent", data={"csrf_token": t})
    assert changed(folder) == [c.path]
    assert outreach.get_item(folder, c.id).state == "sent"
    assert sum(len(co.interactions) for co in store.all()) == touches + 1  # the ready note only
    assert "Skipped (1)" in client.get("/outreach?tab=skipped").text


def test_mark_ready_appends_the_findings_to_the_notes_in_the_same_commit(client, folder):
    found = build(client)
    item = item_for(folder, "lindenhof-data/mara-keller")
    before = len(commits(folder))
    r = client.post(f"/outreach/{item.id}/ready", data={
        "csrf_token": token(client), "subject": item.subject, "body": item.body})
    assert r.status_code == 303 and "tab=ready" in r.headers["location"]
    assert len(commits(folder)) == before + 1
    assert commits(folder)[0] == "outreach: ready lindenhof-data/mara-keller (email)"
    files = changed(folder)
    assert item.path in files and any("/interactions/" in f for f in files)
    fresh = Store(folder)
    fresh.load()
    notes = [i for i in fresh.get("lindenhof-data").interactions if i.is_note]
    assert len(notes) == 1 and notes[0].contact == "mara-keller"
    assert notes[0].body == ("### Research 2026-10-16 (scrape)\n"
                             "- Opened a second office this autumn "
                             "(https://lindenhof-data.example.com)\n")
    assert outreach.get_item(folder, item.id).state == "ready"
    assert len(found) == 3


def test_mark_ready_is_deterministic_byte_for_byte(tmp_path):
    texts = []
    for name in ("one", "two"):
        root = init_folder(tmp_path / name, demo=True, now=NOW)
        client = make_client(root)
        build(client)
        item = item_for(root, "lindenhof-data/mara-keller")
        client.post(f"/outreach/{item.id}/ready", data={"csrf_token": token(client)})
        note = next(p for p in changed(root) if "/interactions/" in p)
        texts.append(((root / note).read_bytes(), (root / item.path).read_bytes()))
    assert texts[0] == texts[1]


def test_mark_ready_writes_no_interaction_that_counts_as_a_touch(client, folder):
    build(client)
    item = item_for(folder, "kestrel-metrics/daan-visser")
    store = client.app.state.store
    touches = [i for i in store.get("kestrel-metrics").interactions if i.is_touch]
    client.post(f"/outreach/{item.id}/ready", data={"csrf_token": token(client)})
    after = Store(folder)
    after.load()
    assert [i for i in after.get("kestrel-metrics").interactions if i.is_touch] == touches
    assert all(not i.is_touch for i in after.get("kestrel-metrics").interactions
               if i not in touches)


def test_mark_ready_with_a_failed_check_is_allowed_with_a_warning(client, folder):
    found = build(client)
    item = found[0]
    r = client.post(f"/outreach/{item.id}/ready", data={
        "csrf_token": token(client), "subject": item.subject,
        "body": "I wanted to reach out.\nAny thoughts? Or questions?\n"})
    assert r.status_code == 303 and "Warning" in r.headers["location"].replace("%20", " ")
    ready = outreach.get_item(folder, item.id)
    assert ready.state == "ready" and ready.checks
    assert ready.body == "I wanted to reach out.\nAny thoughts? Or questions?\n"
    page = client.get("/outreach?tab=ready").text
    assert "Marked ready with" in page and "Mark sent" in page and "Copy" in page


def test_the_ready_list_has_copy_and_the_contacts_links(client, folder):
    build(client)
    item = item_for(folder, "lindenhof-data/mara-keller")
    client.post(f"/outreach/{item.id}/ready", data={"csrf_token": token(client)})
    page = client.get("/outreach?tab=ready").text
    contact = client.app.state.store.get("lindenhof-data").contacts["mara-keller"]
    assert f'href="mailto:{contact.email}"' in page and 'data-copy-text="' in page
    assert "Ready (1)" in page


def test_findings_can_be_removed_and_added_and_proposals_saved(client, folder):
    build(client)
    item = item_for(folder, "lindenhof-data/mara-keller")
    t = token(client)
    client.post(f"/outreach/{item.id}/findings/add", data={
        "csrf_token": t, "text": "Hiring two account executives", "source": ""})
    added = outreach.get_item(folder, item.id).findings[-1]
    assert (added.text, added.source, added.used) == ("Hiring two account executives",
                                                      "you", True)
    n = len(outreach.get_item(folder, item.id).findings)
    client.post(f"/outreach/{item.id}/findings/{n}/remove", data={"csrf_token": t})
    assert len(outreach.get_item(folder, item.id).findings) == n - 1
    assert changed(folder) == [item.path]
    # a proposal is written only on the button, with the item, one commit
    store = client.app.state.store
    fresh = outreach.get_item(folder, item.id)
    fresh.proposals = {"country": "DE"}
    store.get("lindenhof-data").country = ""
    outreach.write_item(folder, fresh)
    r = client.post(f"/outreach/{item.id}/proposals/country", data={"csrf_token": t})
    assert r.status_code == 303
    assert store.get("lindenhof-data").country == "DE"
    assert outreach.get_item(folder, item.id).proposals == {}


def test_regenerate_writes_a_new_draft_on_the_same_findings(client, folder):
    build(client)
    item = item_for(folder, "lindenhof-data/mara-keller")
    calls = len(client.runner.calls)
    r = client.post(f"/outreach/{item.id}/regenerate", data={"csrf_token": token(client),
                                                             "strong": "1"})
    assert r.status_code == 303
    new = client.runner.calls[calls:]
    assert [c["kind"] for c in new] == ["draft"]   # no new research
    assert commits(folder)[0].startswith("outreach: regenerate lindenhof-data/mara-keller")
    assert outreach.get_item(folder, item.id).state == "drafted"


# ------------------------------------------------------- replies to interest


def test_an_interested_reply_appears_with_no_ai_call(client, folder):
    log_reply(client, outcome=INTERESTED)
    page = client.get("/outreach?tab=replies").text
    assert "Daan Visser" in page and "logged as interested" in page
    assert "Draft a reply" in page
    assert client.runner.calls == []


def test_check_replies_asks_once_per_reply_and_the_person_confirms(client, folder):
    it = log_reply(client)
    page = client.get("/outreach?tab=replies").text
    assert "not checked" in page and "Draft a reply" not in page
    client.post("/outreach/replies/check", data={"csrf_token": token(client)})
    mine = client.runner.of("classify", "What exactly do you offer?")
    assert len(mine) == 1 and mine[0]["tools"] == ""
    asked = len(client.runner.of("classify"))   # the demo's own replies too, once each
    stored = yaml.safe_load((folder / outreach.REPLIES_FILE).read_text())
    key = f"kestrel-metrics/{it.id}"
    assert stored[key]["verdict"] == "interest" and len(stored) == asked
    assert re.match(r"outreach: checked \d+ repl", commits(folder)[0])
    assert changed(folder) == [outreach.REPLIES_FILE]
    # stored: a second check asks nothing
    client.post("/outreach/replies/check", data={"csrf_token": token(client)})
    assert len(client.runner.of("classify")) == asked
    page = client.get("/outreach?tab=replies").text
    assert "The AI says interest" in page and "Yes, interest" in page
    # the person confirms: the reply's outcome becomes interested, one commit
    client.post("/outreach/replies/confirm", data={"csrf_token": token(client), "key": key,
                                                   "answer": "yes"})
    store = client.app.state.store
    reply = next(i for i in store.get("kestrel-metrics").interactions if i.id == it.id)
    assert reply.outcome == INTERESTED
    assert set(changed(folder)) == {outreach.REPLIES_FILE,
                                    f"companies/kestrel-metrics/interactions/{it.id}.md"}
    assert "Draft a reply" in client.get("/outreach?tab=replies").text


def test_not_interest_is_hidden_until_asked(folder):
    client = make_client(folder, Runner(verdict="other"))
    log_reply(client, body="No thanks, we are fine.")
    client.post("/outreach/replies/check", data={"csrf_token": token(client)})
    page = client.get("/outreach?tab=replies").text
    assert re.search(r"\d+ more repl(y is|ies are) not interest", page)
    assert "Daan Visser" not in page
    assert "Daan Visser" in client.get("/outreach?tab=replies&all=1").text


def test_a_reply_to_interest_is_drafted_end_to_end(client, folder):
    it = log_reply(client, outcome=INTERESTED)
    key = f"kestrel-metrics/{it.id}"
    r = client.post("/outreach/replies/draft", data={"csrf_token": token(client), "key": key,
                                                     "channel": "email"})
    assert r.status_code == 303 and "tab=replies" in r.headers["location"]
    item = item_for(folder, "kestrel-metrics/daan-visser")
    assert (item.kind, item.state, item.reply_to, item.research_level) == (
        "reply-to-interest", "drafted", key, "none")
    assert item.subject == "Re: Your note"   # theirs, not the AI's
    assert offer_of(folder, item) in item.body and item.checks == []
    assert client.runner.of("research") == []   # the playbook, not the web
    prompt = client.runner.of("reply")[0]["prompt"]
    assert "What exactly do you offer?" in prompt and "their reply (data" in prompt
    assert "--- first step offer ---\nnone: leave it out" in prompt
    assert "No time slot, no booking or calendar link, no price" in prompt
    page = client.get("/outreach?tab=replies").text
    assert f'id="item-{item.id}"' in page and "Their reply" in page
    assert "Daan Visser</a><br>" not in page   # answered by a card, not listed twice
    # ready, then sent: the reply drops off the list
    client.post(f"/outreach/{item.id}/ready", data={"csrf_token": token(client)})
    client.post(f"/outreach/{item.id}/sent", data={"csrf_token": token(client)})
    assert all(r.key != key for r in outreach.replies(client.app.state.store))


def test_the_first_step_offer_is_used_when_set_and_left_out_when_empty(client, folder):
    text = (folder / "MESSAGING.md").read_text()
    text = re.sub(r"^(  offer_line: .*\n)", r"\1  first_step: The first call is free.\n", text,
                  flags=re.M)
    (folder / "MESSAGING.md").write_text(text)
    it = log_reply(client, outcome=INTERESTED)
    client.post("/outreach/replies/draft", data={"csrf_token": token(client),
                                                 "key": f"kestrel-metrics/{it.id}",
                                                 "channel": "email"})
    prompt = client.runner.of("reply")[0]["prompt"]
    assert "--- first step offer ---\nThe first call is free.\n" in prompt
    assert "The first call is free." in item_for(folder, "kestrel-metrics/daan-visser").body


def test_without_an_ai_cli_a_reply_comes_from_the_wording_template(folder):
    client = make_client(folder, available=False)
    page = client.get("/outreach?tab=replies").text
    assert "No AI to draft with" in page
    it = log_reply(client, outcome=INTERESTED)
    client.post("/outreach/replies/draft", data={"csrf_token": token(client),
                                                 "key": f"kestrel-metrics/{it.id}",
                                                 "channel": "email"})
    item = item_for(folder, "kestrel-metrics/daan-visser")
    assert item.model == "template" and client.runner.calls == []
    assert offer_of(folder, item) in item.body and item.body.count("?") == 1
    assert outreach.reply_wording(item.language)["question"] in item.body  # their language
    assert item.language != "en" and item.subject == "Re: Your note"
    assert item.checks == [] and "{" not in item.body


def test_a_folder_with_its_own_outcomes_is_offered_interested_never_given_it(folder):
    with open(folder / "config.toml", "a", encoding="utf-8") as fh:
        fh.write('\noutcomes = ["successful", "unsuccessful"]\n')
    git(folder, "commit", "-qam", "older folder")
    client = make_client(folder)
    assert INTERESTED not in client.app.state.store.outcomes
    page = client.get("/outreach?tab=replies").text
    assert "have no <strong>interested</strong>" in page
    assert git(folder, "status", "--porcelain") == ""
    client.post("/outreach/outcomes/interested", data={"csrf_token": token(client)})
    assert load_config(folder)["outcomes"] == ["successful", INTERESTED, "unsuccessful"]
    assert client.app.state.store.outcomes == ["successful", INTERESTED, "unsuccessful"]
    assert "have no <strong>interested</strong>" not in client.get("/outreach?tab=replies").text


def test_the_default_outcomes_have_interested_between_reply_and_silence(tmp_path):
    root = init_folder(tmp_path / "new")
    assert load_config(root)["outcomes"] == ["successful", INTERESTED, "unsuccessful"]


# ----------------------------------------------------- the contact page


def test_the_contact_page_has_research_and_draft_with_the_suggested_type(client, folder):
    page = client.get("/companies/lindenhof-data/contacts/mara-keller").text
    assert "Research &amp; draft" in page
    assert re.search(r'<option value="first-touch" selected>First touch \(suggested\)', page)
    r = client.post("/companies/lindenhof-data/contacts/mara-keller/outreach", data={
        "csrf_token": token(client), "kind": "first-touch", "channel": "email"})
    assert r.status_code == 303 and "tab=first" in r.headers["location"]
    item = item_for(folder, "lindenhof-data/mara-keller")
    assert item.state == "drafted"
    page = client.get("/companies/lindenhof-data/contacts/mara-keller").text
    assert "Open the card" in page and f"#item-{item.id}" in page
    assert "Research &amp; draft" not in page


def test_the_contact_button_says_why_not(client, folder):
    r = client.post("/companies/ravenmoor-systems/contacts/" + next(iter(
        client.app.state.store.get("ravenmoor-systems").contacts)) + "/outreach", data={
        "csrf_token": token(client), "kind": "first-touch", "channel": "email"})
    assert r.status_code == 303 and "do-not-contact" in r.headers["location"]
    r = client.post("/companies/lindenhof-data/contacts/mara-keller/outreach", data={
        "csrf_token": token(client), "kind": "follow-up", "channel": "email"})
    assert "later%20version" in r.headers["location"]
    assert not (folder / "outreach").exists()


def test_the_suggested_type_comes_from_the_history(client):
    store = client.app.state.store
    company = store.get("kestrel-metrics")
    assert outreach.suggested_kind(company, "daan-visser") == "first-touch"
    store.create_interaction("kestrel-metrics", "email", "out", subject="Hello",
                             contact="daan-visser", body="Hi\n", date=datetime(2026, 10, 1, 9))
    assert outreach.suggested_kind(store.get("kestrel-metrics"), "daan-visser") == "follow-up"
    store.create_interaction("kestrel-metrics", "email", "in", subject="Re: Hello",
                             contact="daan-visser", body="Tell me more\n",
                             date=datetime(2026, 10, 2, 9))
    assert outreach.suggested_kind(store.get("kestrel-metrics"),
                                   "daan-visser") == "reply-to-interest"


# ------------------------------------------------- the engine underneath


def test_a_reply_on_linkedin_is_a_message_with_one_question():
    ctx = outreach.CheckContext(kind="reply-to-interest", channel="linkedin",
                                rules=outreach.channel_rules("linkedin"),
                                offer_lines=[OFFER])
    body = f"Thanks. {OFFER} " + "More words here. " * 25 + "Where does it hurt most?"
    assert len(body) > 300
    assert outreach.check_text("", body, "", ctx) == []
    assert "the message asks 0 questions; it must ask exactly one" in outreach.check_text(
        "", f"Thanks. {OFFER}", "", ctx)
    # a long "Re:" subject is theirs
    email = outreach.CheckContext(kind="reply-to-interest", channel="email",
                                  rules=outreach.channel_rules("email"), offer_lines=[OFFER])
    assert outreach.check_text("Re: " + "x" * 80, f"Thanks. {OFFER} Where?", "",
                               email) == []


def test_the_wording_template_leaves_empty_slots_out_cleanly():
    text = outreach.fill_reply("{greeting}\n\nThanks. {offer_line} {proof} {first_step}\n\n"
                               "{question}\n\n{signoff}\n{name}\n{unknown}",
                               {"greeting": "Hi Jo,", "offer_line": "We do X.", "proof": "",
                                "first_step": "", "question": "Why?", "signoff": "Best,",
                                "name": ""})
    assert text == "Hi Jo,\n\nThanks. We do X.\n\nWhy?\n\nBest,\n\n{unknown}\n"
    assert outreach.reply_subject(type("R", (), {"subject": "RE: AW: Hello"})) == "Re: Hello"
    for lang in ("en", "de", "nl", "fr"):
        wording = outreach.reply_wording(lang)
        assert "{offer_line}" in wording["text"] and wording["question"].rstrip().endswith("?")


def test_the_playbook_first_step_is_optional_one_line_and_saved_from_the_form(folder):
    text = (folder / "MESSAGING.md").read_text()
    pb = playbook.parse(text)
    assert pb.approach("Scaling the sales team").first_step == ""
    bad = text.replace(f"  offer_line: '{OFFER}'\n",
                       f"  offer_line: '{OFFER}'\n  first_step: [one, two]\n")
    assert any("first_step" in p for p in playbook.validate_front(playbook.parse(bad).front))
    values = playbook.form_values(pb.approach("Scaling the sales team"))
    values["first_step"] = "The first call is free."
    new, errors = playbook.save_form(text, "Scaling the sales team", values)
    assert errors == {}
    assert playbook.parse(new).approach("Scaling the sales team").first_step == \
        "The first call is free."
    assert playbook.validate_front(playbook.parse(new).front) == []
    values["first_step"] = ""
    cleared, _ = playbook.save_form(new, "Scaling the sales team", values)
    assert "first_step" not in cleared
