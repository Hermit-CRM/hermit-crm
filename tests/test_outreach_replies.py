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

"""Outreach, part 04b: replies to interest. The `interested` outcome (its
place in the order, the offer to existing folders), the replies owed and
Check replies, the reply-to-interest draft and its checks, the Replies to
interest tab and the contact page's choice of draft type. The AI and the
web are fakes; all names are made up."""

from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from hermitcrm import outreach, playbook, reports
from hermitcrm.datafolder import init_folder
from hermitcrm.models import DEFAULT_OUTCOMES, INTERESTED, with_interested
from hermitcrm.store import Store, load_config, split_file
from hermitcrm.web import create_app
from outreach_fakes import NOW, FakeAI, ai, fake_page, git

MARA = "lindenhof-data/mara-keller"
SCALING = "Scaling the sales team"


@pytest.fixture
def root(tmp_path):
    return init_folder(tmp_path / "crm", demo=True, now=NOW)


@pytest.fixture
def fake():
    return FakeAI()


@pytest.fixture
def client(root, fake):
    app = create_app(root, {**load_config(root), "push_enabled": False,
                            "owner_name": "Sam Example"})
    app.state.setup_redirected = True
    app.state.enricher = ai(fake)
    app.state.outreach_fetcher = fake_page
    app.state.store.clock = lambda: NOW
    return TestClient(app, follow_redirects=False)


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.app.state.csrf_token, **data})


def commits(root) -> list[str]:
    return git(root, "log", "--format=%s").splitlines()


def log_reply(client, record=MARA, outcome="", body="Sounds interesting. How would "
              "that work for a team of three?\n"):
    """Mara writes back: an inbound email after the demo's last touch with her."""
    company, contact = record.split("/")
    store = client.app.state.store
    sent = store.create_interaction(company, "email", "out", subject="Your second office",
                                    contact=contact, date=NOW - timedelta(days=3),
                                    body="Hi Mara,\n\nA first message.\n\nSam\n")
    it = store.create_interaction(company, "email", "in", subject="Re: Your second office",
                                  contact=contact, date=NOW - timedelta(days=1),
                                  outcome=outcome, body=body)
    return sent, it


# ------------------------------------------------------------- the outcome


def test_interested_sits_between_reply_and_silence():
    assert DEFAULT_OUTCOMES == ("successful", INTERESTED, "unsuccessful")
    # The first is what a reply counts as, the last what silence counts as.
    assert DEFAULT_OUTCOMES[0] == "successful" and DEFAULT_OUTCOMES[-1] == "unsuccessful"


def test_new_folders_get_it_in_the_middle(root):
    assert load_config(root)["outcomes"] == ["successful", "interested", "unsuccessful"]


def test_reply_rate_unchanged_on_the_demo_folder(root):
    store = Store(root, clock=lambda: NOW)
    store.load()
    today = NOW.date()
    for days in (30, 90, 365):
        period = reports.Period(today - timedelta(days=days - 1), today)
        old = reports.messages(store, period, today, 14, ["successful", "unsuccessful"])
        new = reports.messages(store, period, today, 14, list(DEFAULT_OUTCOMES))
        assert new["total"]["rate"] == old["total"]["rate"]
        assert new["total"]["sent"] == old["total"]["sent"]
        for status in ("successful", "unsuccessful", "unknown"):
            assert new["total"]["counts"][status] == old["total"]["counts"][status]
        assert new["total"]["counts"]["interested"] == 0
        assert ([r["rate"] for r in new["by_channel"]] == [r["rate"] for r in old["by_channel"]])


def test_the_offer_goes_before_the_last_outcome():
    assert with_interested(["successful", "unsuccessful"]) == [
        "successful", "interested", "unsuccessful"]
    assert with_interested(["yes", "maybe", "no"]) == ["yes", "maybe", "interested", "no"]
    assert with_interested(["successful", "interested", "unsuccessful"]) is None
    assert with_interested(["done"]) is None   # no middle: never made the silence value


def test_existing_folder_is_offered_it_never_changed_silently(root, client):
    # A folder that set its own list before this version (a folder that never
    # set one follows the default, as for every key in config.toml).
    path = root / "config.toml"
    path.write_text(path.read_text() + '\noutcomes = ["successful", "unsuccessful"]\n')
    git(root, "commit", "-qam", "an older folder")
    client.app.state.store.load()
    page = client.get("/settings").text
    assert "Add interested" in page
    assert load_config(root)["outcomes"] == ["successful", "unsuccessful"]  # unchanged
    offered = re.search(r'class="inline outcomes-offer">.*?name="outcomes" value="([^"]*)"',
                        page, re.S).group(1)
    assert offered == "successful\ninterested\nunsuccessful"
    r = post(client, "/settings/outcomes", outcomes=offered, message_window_days="14",
             silent_days="14")
    assert r.status_code == 303
    assert load_config(root)["outcomes"] == ["successful", "interested", "unsuccessful"]
    assert "Add interested" not in client.get("/settings").text


# ------------------------------------------------------- the replies owed


def test_logged_interested_reply_is_listed_with_no_ai(client, fake, root):
    _, it = log_reply(client, outcome="interested")
    page = client.get("/outreach?tab=replies").text
    assert fake.calls == []
    assert f'id="reply-{it.id}"' in page and "interested (logged)" in page
    assert "Draft a reply" in page
    assert ">Replies to interest (1)<" in page
    # Replies to interest is the first tab.
    assert page.index("Replies to interest (") < page.index(">Drafts (")
    # The Drafts tab points at it.
    assert "1 reply to interest</a> waits" in client.get("/outreach").text


def test_check_replies_asks_once_per_reply_and_waits_for_you(client, fake, root):
    _, it = log_reply(client)
    store = client.app.state.store
    reply, = [r for r in outreach.replies(store) if r.record == MARA]
    assert reply.unchecked and not reply.interested
    before = len(commits(root))
    r = post(client, "/outreach/replies/check")
    assert r.status_code == 303
    asked = fake.of("classify")
    assert len(asked) == len([r for r in outreach.replies(store)
                              if r.interaction.outcome != INTERESTED])
    assert asked[0]["tools"] == ""
    assert "How would that work for a team of three?" in "".join(c["prompt"] for c in asked)
    assert len(commits(root)) == before + 1
    assert commits(root)[0].startswith("outreach: check replies (")
    stored = json.loads((root / "outreach" / "replies.json").read_text())
    assert stored[f"lindenhof-data/{it.id}"]["verdict"] == "interested"
    assert stored[f"lindenhof-data/{it.id}"]["by"] == "ai"
    reply, = [r for r in outreach.replies(store) if r.record == MARA]
    assert reply.to_confirm and not reply.interested   # the AI alone is not enough
    page = client.get("/outreach?tab=replies").text
    assert "AI: interested?" in page and "Confirm: interested" in page
    # Once per reply: a second check asks nothing.
    post(client, "/outreach/replies/check")
    assert len(fake.of("classify")) == len(asked)
    r = post(client, "/outreach/replies/confirm", reply=f"lindenhof-data/{it.id}", answer="yes")
    assert r.status_code == 303 and commits(root)[0] == (
        f"outreach: reply {MARA} interested (you)")
    reply, = [r for r in outreach.replies(store) if r.record == MARA]
    assert reply.interested
    # The interaction itself is not changed.
    assert next(i for i in store.get("lindenhof-data").interactions
                if i.id == it.id).outcome == ""


def test_not_interested_needs_no_draft(client, fake, root):
    _, it = log_reply(client, body="No thanks, not for us.\n")
    fake.classify = {"verdict": "not-interested", "why": "They decline."}
    post(client, "/outreach/replies/check")
    store = client.app.state.store
    reply, = [r for r in outreach.replies(store) if r.record == MARA]
    assert reply.verdict == "not-interested" and not reply.interested
    section = client.get("/outreach?tab=replies").text
    assert f'id="reply-{it.id}" class="outreach-reply quiet"' in section
    r = post(client, "/outreach/build", contact=MARA, kind=outreach.REPLY,
             back="/outreach?tab=replies")
    assert "no reply showing interest" in r.headers["location"].replace("%20", " ")
    assert fake.of("draft") == []


def test_an_answered_reply_drops_off(client):
    _, it = log_reply(client, outcome="interested")
    store = client.app.state.store
    store.create_interaction("lindenhof-data", "email", "out", contact="mara-keller",
                             date=NOW - timedelta(hours=2), body="Hi Mara,\n\nAnswered.\n")
    assert not [r for r in outreach.replies(store) if r.record == MARA]


# ------------------------------------------------- the reply-to-interest draft


def test_reply_draft_from_the_tab(client, fake, root):
    _, it = log_reply(client, outcome="interested")
    before = len(commits(root))
    r = post(client, "/outreach/build", contact=MARA, kind=outreach.REPLY, channel="email",
             back="/outreach?tab=replies")
    assert r.status_code == 303 and "tab=replies" in r.headers["location"]
    item, = [i for i in outreach.items(root) if i.record == MARA]
    assert item.kind == outreach.REPLY and item.reply_to == it.id
    assert item.state == "drafted" and item.checks == [], item.checks
    assert fake.of("research") == []   # they asked: no research
    prompt = fake.of("draft")[0]["prompt"]
    assert "How would that work for a team of three?" in prompt
    approach = playbook.load(root).approach(item.approach)
    assert approach.offer_line in prompt and approach.offer_line in item.body
    if approach.first_step_offer:
        assert approach.first_step_offer in prompt
    assert "--- wording template" in prompt and "--- findings" not in prompt
    assert item.angle == "" and len(item.proof_used) == 1
    assert len(commits(root)) == before + 2
    assert commits(root)[1] == f"outreach: reply to interest {MARA} ({it.id})"
    page = client.get("/outreach?tab=replies").text
    assert f'id="item-{item.id}"' in page and "Their reply" in page
    # It is not a first touch: the Drafts tab does not show it.
    assert f'id="item-{item.id}"' not in client.get("/outreach?tab=drafts").text
    # Regenerate keeps it a reply, with their reply in the prompt again.
    r = post(client, f"/outreach/{item.id}/regenerate")
    assert r.status_code == 303 and "tab=replies" in r.headers["location"]
    assert "How would that work" in fake.of("draft")[-1]["prompt"]


def test_first_step_offer_is_left_out_when_empty(client, fake, root):
    path = root / playbook.FILENAME
    path.write_text(path.read_text().replace(
        "  first_step_offer: The first call is free and all about you, without a sales "
        "pitch.\n", ""))
    git(root, "commit", "-qam", "no free call")
    log_reply(client, outcome="interested")
    post(client, "/outreach/build", contact=MARA, kind=outreach.REPLY,
         back="/outreach?tab=replies")
    prompt = fake.of("draft")[0]["prompt"]
    assert "none: leave it out" in prompt and "first call is free" not in prompt


def test_contact_page_picks_the_kind_from_the_history(client, root):
    page = client.get(f"/companies/{MARA.replace('/', '/contacts/')}").text
    assert '<option value="first-touch" selected>' in page and "Research &amp; draft" in page
    log_reply(client, outcome="interested")
    page = client.get(f"/companies/{MARA.replace('/', '/contacts/')}").text
    assert '<option value="reply-to-interest" selected>' in page and "Draft a reply" in page


def test_select_refuses_a_reply_without_interest(root):
    store = Store(root, clock=lambda: NOW)
    store.load()
    sel = outreach.select(store, contacts=[MARA], kind=outreach.REPLY)
    assert not sel.picked and "no reply showing interest" in sel.excluded[0].reason


def _ctx(**kw):
    return outreach.CheckContext(kind=outreach.REPLY, channel="email",
                                 rules=outreach.channel_rules("email"),
                                 offer_lines=["I work as your fractional Head of Sales."],
                                 proof=["A made-up firm doubled its pipeline."], **kw)


GOOD = ("Hi Mara,\n\nFair question. I work as your fractional Head of Sales. A made-up firm "
        "doubled its pipeline. The first call is free.\nWhere does it hurt most right now?"
        "\n\nSam\n")


def test_a_reply_without_the_offer_line_is_refused():
    assert outreach.check_text("Re: hi", GOOD, "", _ctx()) == []
    problems = outreach.check_text("Re: hi", GOOD.replace(
        "I work as your fractional Head of Sales. ", ""), "", _ctx())
    assert problems == ["a reply to interest must say the offer line from the playbook"]
    # clean_answer turns that into a refused draft (problems), which the drafter retries.
    answer = {"subject": "Re: hi", "body": GOOD.replace("I work as your fractional Head of "
                                                       "Sales. ", ""),
              "pitch": "", "angle": "custom", "findings_used": [],
              "proof_used": ["A made-up firm doubled its pipeline."]}
    assert "offer line" in " ".join(outreach.clean_answer(answer, _ctx()).problems)


@pytest.mark.parametrize("extra, says", [
    ("It costs €900 a day.", "price"),
    ("Usually 2 days a week.", "workload"),
    ("Book a slot: https://calendly.com/sam", "calendar link"),
    ("See https://example.com/offer", "link"),
    ("How about Tuesday at 14:00", "proposes a time"),
    ("[your result]", "gap"),
])
def test_a_reply_has_no_slot_link_price_or_gap(extra, says):
    problems = outreach.check_text("Re: hi", GOOD.replace("The first call is free.", extra),
                                   "", _ctx())
    assert any(says in p for p in problems), problems


def test_a_reply_cites_one_proof_line():
    answer = {"subject": "Re: hi", "body": GOOD, "pitch": "", "angle": "hook",
              "findings_used": [], "proof_used": []}
    draft = outreach.clean_answer(answer, _ctx())
    assert draft.angle == ""   # no angle on a reply; no complaint about it either
    assert draft.problems == ["a reply to interest cites one proof line from the playbook "
                              "(it cites 0)"]


def test_a_linkedin_reply_is_a_message_not_a_note():
    ctx = outreach.CheckContext(kind=outreach.REPLY, channel="linkedin",
                                rules=outreach.channel_rules("linkedin"),
                                offer_lines=["I work as your fractional Head of Sales."])
    body = GOOD + "x" * 200   # over a note's 300 characters, under a message's 600
    assert outreach.check_text("", body, "", ctx) == []
    assert any("asks 0 questions" in p
               for p in outreach.check_text("", body.replace("?", "."), "", ctx))


def test_reply_templates_in_four_languages():
    messages = outreach.messaging.default_messages()
    for lang in ("en", "de", "nl", "fr"):
        text = outreach.reply_template(messages, lang, "Mara", "OFFER.", "PROOF.", "")
        assert "OFFER." in text and "PROOF." in text and "{" not in text
        assert outreach.count_questions(text) == 1
        assert "\n\n" not in text   # the empty first step offer left no blank line
        assert "STEP." in outreach.reply_template(messages, lang, "Mara", "O.", "P.", "STEP.")
    # A language without one falls back to English.
    assert outreach.reply_template(messages, "sv", "Mara", "O.", "P.", "").startswith("Hi Mara,")


def test_item_file_keeps_reply_to(root, client):
    _, it = log_reply(client, outcome="interested")
    post(client, "/outreach/build", contact=MARA, kind=outreach.REPLY,
         back="/outreach?tab=replies")
    item, = [i for i in outreach.items(root) if i.record == MARA]
    meta, body = split_file((root / item.path).read_text())
    assert meta["reply_to"] == it.id and list(meta) == list(outreach.ITEM_KEYS)
    again = outreach.item_from_text(item.id, (root / item.path).read_text())
    assert outreach.item_text(again) == (root / item.path).read_text()
