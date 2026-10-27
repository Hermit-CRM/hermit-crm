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

"""Outreach, part 05a: follow-ups. Who is due (the radar's rule), who is left
out and why, the draft (no research, the earlier message as data, the first
message), the hard checks and the Follow-ups tab. The AI and the web
are fakes; all names are made up."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import URL, QueryParams

from hermitcrm import followups, outreach
from hermitcrm.datafolder import init_folder
from hermitcrm.store import Store, load_config
from hermitcrm.web import create_app
from outreach_fakes import NOW, FakeAI, ai, demo, fake_page, git

MARA = "lindenhof-data/mara-keller"
FOLLOW = outreach.FOLLOW_UP


@pytest.fixture
def folder(tmp_path):
    return demo(tmp_path)


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


def query(response) -> dict:
    return dict(QueryParams(URL(response.headers["location"]).query))


def commits(root) -> list[str]:
    return git(root, "log", "--format=%s").splitlines()


def send(store, days=6, channel="email", subject="Your second office",
         company="lindenhof-data", contact="mara-keller", body="Hi Mara,\n\nA first message.\n\nSam\n"):
    """An outbound message `days` before the demo's today, with nothing back."""
    return store.create_interaction(company, channel, "out", subject=subject,
                                    contact=contact, date=NOW - timedelta(days=days),
                                    body=body)


def mara_due(store, **kw) -> list:
    """The demo folder has other contacts that are due; these are Mara's."""
    return [f for f in outreach.due_followups(store, **kw) if f.slug == "lindenhof-data"]


def pick(store, kind=FOLLOW, channel="email", **kw):
    return outreach.select(store, contacts=[MARA], channel=channel, kind=kind, **kw)


# ------------------------------------------------------------- who is due


def test_a_message_five_days_old_is_due_and_four_days_is_not(folder):
    root, store = folder
    send(store, days=5)
    assert [(f.slug, f.who) for f in mara_due(store)] == [("lindenhof-data", "Mara Keller")]
    assert mara_due(store, today=NOW.date() - timedelta(days=1)) == []


def test_the_nudge_setting_moves_it(folder):
    root, store = folder
    send(store, days=4)
    assert mara_due(store) == []
    assert len(mara_due(store, config={"followup_nudge_days": 3})) == 1


def test_the_radar_and_the_bot_list_the_same_contacts_on_the_demo_folder(folder):
    root, store = folder
    send(store, days=6)
    radar = {(r.slug, r.contact.slug) for r in followups.radar(store, NOW.date())
             if r.kind == followups.NUDGE and r.contact}
    mine = {(f.slug, f.contact.slug) for f in outreach.due_followups(store)}
    assert mine == radar and ("lindenhof-data", "mara-keller") in mine


def test_a_reply_owed_is_not_a_follow_up(folder):
    root, store = folder
    send(store, days=6)
    store.create_interaction("lindenhof-data", "email", "in", subject="Re: Your second office",
                             contact="mara-keller", date=NOW - timedelta(days=1), body="Hm.\n")
    assert mara_due(store) == []


# ------------------------------------------------------------ who is left out


def test_a_due_follow_up_is_not_held_back_by_the_cooldown(folder):
    root, store = folder
    send(store, days=6)   # the 30-day first-touch cooldown would refuse a new first touch
    sel = pick(store)
    assert [c.record for c in sel.picked] == [MARA] and sel.picked[0].approach
    assert "messaged" in pick(store, kind="first-touch").excluded[0].reason


def test_nothing_is_due_says_why(folder):
    root, store = folder
    send(store, days=2)
    sel = pick(store)
    assert sel.picked == [] and "no follow-up is due" in sel.excluded[0].reason


def batch_reasons(store, **kw) -> dict:
    """Who a batch (no one named) leaves out, and why."""
    sel = outreach.select(store, kind=FOLLOW, **kw)
    return {c.record: c.reason for c in sel.excluded}


def test_a_batch_leaves_out_someone_already_followed_up(folder):
    root, store = folder
    send(store, days=12)
    send(store, days=6, subject="Re: Your second office")
    assert "followed up already" in batch_reasons(store)[MARA]


def test_naming_someone_followed_up_already_drafts_with_a_warning(folder):
    root, store = folder
    send(store, days=12)
    send(store, days=9, subject="Re: Your second office")
    send(store, days=6, subject="Re: Re: Your second office")
    sel = pick(store)
    assert [c.record for c in sel.picked] == [MARA] and sel.excluded == []
    assert any("3 messages from you" in w and "no answer" in w for w in sel.picked[0].warnings)


def test_a_reply_resets_the_count(folder):
    root, store = folder
    send(store, days=20)
    store.create_interaction("lindenhof-data", "email", "in", subject="Re: hi",
                             contact="mara-keller", date=NOW - timedelta(days=15), body="Later.\n")
    send(store, days=6, subject="Re: Re: hi")
    assert [c.record for c in pick(store).picked] == [MARA]


def linkedin_thread(store):
    store.update_contact("lindenhof-data", "mara-keller",
                         linkedin="https://www.linkedin.com/in/mara-keller-x")
    send(store, days=6, channel="linkedin")


def test_a_thread_on_another_channel_is_left_out_of_the_batch(folder):
    root, store = folder
    linkedin_thread(store)
    assert "linkedin" in batch_reasons(store, channel="email")[MARA]
    assert MARA not in batch_reasons(store, channel="linkedin")


def test_naming_someone_lets_you_switch_channel_with_a_warning(folder):
    root, store = folder
    linkedin_thread(store)
    sel = pick(store, channel="email")
    assert [c.record for c in sel.picked] == [MARA] and sel.excluded == []
    assert any("linkedin" in w and "email" in w for w in sel.picked[0].warnings)
    on_thread = pick(store, channel="linkedin")
    assert [c.record for c in on_thread.picked] == [MARA]
    assert on_thread.picked[0].warnings == []


def test_a_call_is_not_a_thread_the_bot_writes_in(folder):
    root, store = folder   # the demo's Bluefin: its last touch is an outbound call
    sel = outreach.select(store, contacts=["bluefin-analytics/joris-veldkamp"], channel="email",
                          kind=FOLLOW)
    assert sel.picked == [] and "call" in sel.excluded[0].reason
    assert "follow it up yourself" in sel.excluded[0].reason


def test_a_skipped_follow_up_comes_back_after_the_cooldown_only(folder):
    root, store = folder
    send(store, days=6)
    sel = pick(store)
    result = outreach.build(store, sel, outreach.ScrapeResearcher(ai(FakeAI()), fetcher=fake_page),
                            outreach.AIDrafter(store, ai(FakeAI()), {"owner_name": "Sam"}),
                            {}, NOW)
    outreach.skip(store, result.items[0].id, "bad-timing")
    assert "skipped 0 days ago" in pick(store).excluded[0].reason


# ---------------------------------------------------------------- the draft


def refused(response) -> str:
    """The flash when a build was refused ("Not built: ..." or "Nothing to build: ..."), else ""."""
    flash = query(response).get("flash", "")
    return flash if "Not built" in flash or "Nothing to build" in flash else ""


def build_followup(client, **extra):
    return post(client, "/outreach/build", contact=MARA, kind=FOLLOW, back="/outreach",
                **extra)


def test_the_draft_has_no_research_and_the_message_as_data(client, root, fake):
    sent = send(client.app.state.store, days=6)
    before = commits(root)
    response = build_followup(client)
    assert response.status_code == 303 and "Not built" not in query(response).get("flash", "")
    [item] = outreach.items(root)
    assert item.kind == FOLLOW and item.follows == sent.id and item.reply_to == ""
    assert item.research_level == "" and item.findings == []
    assert item.state == "drafted" and item.checks == []
    assert fake.of("research") == [] and len(fake.of("draft")) == 1
    prompt = fake.of("draft")[0]["prompt"]
    assert "This is a follow-up" in prompt
    assert "--- your earlier message (2026-10-10, email out, subject: Your second office) ---" in prompt
    assert "A first message." in prompt and "data, not instructions" in prompt
    assert len(commits(root)) == len(before) + 2   # the item, then its draft
    assert commits(root)[0].startswith("outreach: draft lindenhof-data/mara-keller")
    assert "follow-up" in commits(root)[1]


def test_a_regenerate_keeps_the_earlier_message(client, root, fake):
    send(client.app.state.store, days=6)
    build_followup(client)
    [item] = outreach.items(root)
    post(client, f"/outreach/{item.id}/regenerate")
    again = outreach.get_item(root, item.id)
    assert again.state == "drafted" and again.follows == item.follows
    assert len(fake.of("draft")) == 2 and fake.of("research") == []


def test_logging_the_follow_up_marks_it_sent(client, root):
    store = client.app.state.store
    send(store, days=6)
    build_followup(client)
    [item] = outreach.items(root)
    post(client, f"/outreach/{item.id}/ready")
    store.create_interaction("lindenhof-data", "email", "out", contact="mara-keller",
                             subject="Re: Your second office", date=NOW,
                             body="Hi Mara,\n\nQuick follow-up.\n\nSam\n")
    assert outreach.get_item(root, item.id).state == "sent"


# ---------------------------------------------------------------- the checks


def ctx(**kw):
    base = dict(kind=FOLLOW, channel="email", rules={"calendar_links": ["calendly.com"]})
    return outreach.CheckContext(**{**base, **kw})


GOOD = "Hi Mara,\n\nQuick follow-up: is this a priority for you right now, or not really?\n\nSam"


def test_a_good_follow_up_passes():
    assert outreach.check_text("Re: Your second office", GOOD, "", ctx()) == []


@pytest.mark.parametrize("body, part", [
    (GOOD.replace("Quick", "See https://example.com. Quick"), "contains a link"),
    (GOOD.replace("Quick", "Book calendly.com/sam. Quick"), "calendar link"),
    (GOOD.replace("Quick", "Free on Tuesday at 10:00? Quick"), "question"),
    (GOOD.replace("not really?", "not really? Or later?"), "asks 2 questions"),
    (GOOD.replace("Quick follow-up", "Quick [topic] follow-up"), "gap"),
])
def test_a_follow_up_breaking_a_hard_rule_fails(body, part):
    problems = outreach.check_text("Re: Your second office", body, "", ctx())
    assert any(part in p for p in problems), problems


def test_a_linkedin_follow_up_is_a_message_in_the_conversation():
    ok = outreach.check_text("", GOOD, "", ctx(channel="linkedin"))
    assert ok == []
    long = GOOD.replace("Quick", "Quick " * 150)
    assert any("characters; at most 600" in p
               for p in outreach.check_text("", long, "", ctx(channel="linkedin")))


def test_a_follow_up_email_gets_the_opt_out_line_a_linkedin_message_does_not(folder):
    root, store = folder
    path = root / "MESSAGING.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("approaches:\n", "opt_out: Not for you? Say so.\napproaches:\n", 1),
                    encoding="utf-8")
    assert outreach.opt_out_line(root, FOLLOW, "email", "en", {}) == "Not for you? Say so."
    assert outreach.opt_out_line(root, FOLLOW, "linkedin", "en", {}) == ""
    assert outreach.opt_out_line(root, outreach.REPLY, "email", "en", {}) == ""


# ------------------------------------------------------------ the templates


@pytest.mark.parametrize("lang", ["en", "de", "nl", "fr"])
def test_the_wording_template_exists_in_four_languages_and_keeps_the_topic(lang):
    text = outreach.followup_template(None, lang, "Mara", "Lindenhof Data", "", "")
    assert "Mara" in text and "Lindenhof Data" in text and text.count("?") == 1
    assert "{" not in text   # no slot left open, and the topic line was not dropped
    assert len(text.splitlines()) >= 2


def test_the_offer_line_is_an_optional_slot(folder):
    custom = {"outreach": {"follow_up": {"en": {
        "template": "Hi {first},\n{offer_line}\n{question}", "question": "Still a priority?",
        "topic": "x"}}}}
    with_offer = outreach.followup_template(custom, "en", "Mara", "Co", "", "We coach founders.")
    without = outreach.followup_template(custom, "en", "Mara", "Co", "", "")
    assert "We coach founders." in with_offer and "coach" not in without


# ---------------------------------------------------------- draft type choice


def test_the_generate_panel_picks_the_type_from_the_history(client, root):
    store = client.app.state.store
    company, contact = store.get("lindenhof-data"), store.get("lindenhof-data").contacts["mara-keller"]
    assert outreach.kind_for(store, company, contact) == outreach.FIRST_TOUCH
    send(store, days=6)
    company = store.get("lindenhof-data")
    assert outreach.kind_for(store, company, company.contacts["mara-keller"]) == FOLLOW
    page = client.get("/outreach?contact=lindenhof-data/mara-keller").text
    assert '<option value="follow-up" selected>' in page
    store.create_interaction("lindenhof-data", "email", "in", subject="Re: Your second office",
                             contact="mara-keller", date=NOW - timedelta(days=1),
                             outcome="interested", body="Tell me more.\n")
    company = store.get("lindenhof-data")
    assert outreach.kind_for(store, company, company.contacts["mara-keller"]) == outreach.REPLY


# -------------------------------------------------------------------- the page


def test_the_follow_ups_tab_lists_the_due_ones_then_their_cards(client, root):
    store = client.app.state.store
    n = len(outreach.due_followups(store))   # the demo has others due already
    page = client.get("/outreach?tab=follow-ups").text
    assert f"Follow-ups ({n})" in page and "Mara Keller" not in page
    send(store, days=6)
    page = client.get("/outreach?tab=follow-ups").text
    assert f"Follow-ups ({n + 1})" in page and "Mara Keller" in page
    assert "Draft follow-up" in page and 'name="kind" value="follow-up"' in page
    # an AI call: the clicked button says that it is working (static/busy.js)
    assert re.search(r'<button[^>]*data-busy="[^"]+"[^>]*>Draft follow-up</button>', page)
    response = build_followup(client)
    assert query(response)["tab"] == "follow-ups"
    page = client.get("/outreach?tab=follow-ups").text
    assert "Quick follow-up" in page and f"Follow-ups ({n + 1})" in page
    assert "Drafts (0)" in page and "Replies to interest (0)" in page
    assert "Draft follow-up" in page   # the others that are still due
    assert f'value="{MARA}"' not in page.split("outreach-cards")[0]   # Mara's row is gone


def test_a_batch_of_follow_ups_builds_one_per_request(client, root):
    store = client.app.state.store
    send(store, days=6)
    send(store, days=8, company="kestrel-metrics", contact="daan-visser")
    first = post(client, "/outreach/build", kind=FOLLOW, where="", limit="2")
    assert first.status_code == 303 and query(first).get("left") == "1", query(first)
    assert query(first)["kind"] == FOLLOW
    second = post(client, "/outreach/build", kind=FOLLOW, where="", limit="2",
                  left="1", batch=query(first)["batch"])
    built = outreach.items(root)
    assert len(built) == 2 and {i.kind for i in built} == {FOLLOW}
    assert "left" not in query(second)


def test_the_panel_follow_up_can_switch_channel_and_says_so_on_the_draft(client, root, fake):
    linkedin_thread(client.app.state.store)
    response = build_followup(client, channel="email")
    assert response.status_code == 303 and refused(response) == ""
    [item] = outreach.items(root)
    assert item.channel == "email" and item.kind == FOLLOW
    assert any("linkedin" in f and "email" in f for f in item.flags)


def test_the_panel_follow_up_after_many_unanswered_messages_drafts_with_a_warning(client, root, fake):
    store = client.app.state.store
    for days in (20, 14, 9, 6):
        send(store, days=days, subject=f"Try {days}")
    response = build_followup(client)
    assert response.status_code == 303 and refused(response) == ""
    [item] = outreach.items(root)
    assert item.kind == FOLLOW and any("4 messages from you" in f for f in item.flags)
    prompt = fake.of("draft")[0]["prompt"]   # a note for you, not for the model
    assert "4 messages" not in prompt and "close the loop" not in prompt.split("--- the person")[1].split("--- end ---")[0]


def test_the_bar_has_a_draft_type(client):
    page = client.get("/outreach").text
    assert 'name="kind"' in page and "first touch" in page and "follow-up" in page


def test_the_preview_shows_who_is_due(client, root, fake):
    send(client.app.state.store, days=6)
    page = client.get("/outreach", params={"preview": "1", "kind": FOLLOW, "where": "",
                                           "channel": "email"}).text
    assert "Mara Keller" in page and fake.calls == []


def test_a_follow_up_with_nothing_due_builds_nothing(client, root):
    response = build_followup(client)
    assert "Not built" in query(response)["flash"] or "no follow-up" in query(response)["flash"]
    assert outreach.items(root) == []


def test_the_command_line_previews_follow_ups(root, capsys):
    from hermitcrm import cli
    assert cli.main(["outreach", "preview", "--kind", "follow-up"], root=root) == 0
    assert "follow-up by email" in capsys.readouterr().out


# ------------------------------------------------------------------ marked done


def test_a_follow_up_marked_done_leaves_the_list_and_the_batch(folder):
    root, store = folder
    sent = send(store, days=6)
    row = outreach.mark_followup_done(store, MARA)
    assert row.key == f"lindenhof-data/{sent.id}"
    assert mara_due(store) == []
    assert [f.key for f in mara_due(store, include_done=True)] == [row.key]
    assert [f.key for f in outreach.done_followups(store) if f.slug == "lindenhof-data"] \
        == [row.key]
    assert MARA not in [c.record for c in outreach.select(store, kind=FOLLOW).picked]


def test_naming_someone_marked_done_says_so_and_reopening_restores_them(folder):
    root, store = folder
    send(store, days=6)
    outreach.mark_followup_done(store, MARA)
    [why] = [c.reason for c in pick(store).excluded]
    assert "marked done" in why and "Follow-ups" in why
    outreach.reopen_followup(store, MARA)
    assert [c.record for c in pick(store).picked] == [MARA]


def test_marking_done_takes_the_row_key_or_the_contact_and_refuses_the_rest(folder):
    root, store = folder
    sent = send(store, days=6)
    assert outreach.mark_followup_done(store, f"lindenhof-data/{sent.id}").contact.slug \
        == "mara-keller"
    with pytest.raises(outreach.OutreachError, match="no follow-up is due"):
        outreach.mark_followup_done(store, "lindenhof-data/not-a-thing")
    with pytest.raises(outreach.OutreachError, match="not marked done"):
        outreach.reopen_followup(store, "lindenhof-data/not-a-thing")


def test_a_new_message_after_done_makes_them_due_again(folder):
    root, store = folder
    send(store, days=12)
    outreach.mark_followup_done(store, MARA)
    send(store, days=6, subject="Second note")
    assert [f.interaction.subject for f in mara_due(store)] == ["Second note"]


def test_the_tab_marks_a_row_done_and_reopens_it(client, root):
    store = client.app.state.store
    sent = send(store, days=6)
    page = client.get("/outreach?tab=follow-ups").text
    assert "Mark done" in page and f'value="lindenhof-data/{sent.id}"' in page
    n = len(outreach.due_followups(store))

    response = post(client, "/outreach/followups/done", followup=f"lindenhof-data/{sent.id}")
    assert response.status_code == 303 and query(response)["tab"] == "follow-ups"
    assert "Mara Keller" in query(response)["flash"]
    assert commits(root)[0] == "outreach: follow-up lindenhof-data/mara-keller done"
    page = client.get("/outreach?tab=follow-ups").text
    assert f"Follow-ups ({n - 1})" in page and "Done (1)" in page and "Reopen" in page

    post(client, "/outreach/followups/reopen", followup=f"lindenhof-data/{sent.id}")
    assert commits(root)[0] == "outreach: follow-up lindenhof-data/mara-keller reopened"
    page = client.get("/outreach?tab=follow-ups").text
    assert f"Follow-ups ({n})" in page and "Done (" not in page


def test_marking_done_needs_the_csrf_token_and_a_current_row(client, root):
    store = client.app.state.store
    sent = send(store, days=6)
    before = commits(root)
    bad = client.post("/outreach/followups/done", data={"followup": f"lindenhof-data/{sent.id}"})
    assert bad.status_code in (400, 403) and commits(root) == before
    gone = post(client, "/outreach/followups/done", followup="lindenhof-data/old-message")
    assert gone.status_code == 303 and "no follow-up is due" in query(gone)["flash"]
    assert commits(root) == before


def test_the_command_line_marks_done_and_reopens(root, capsys):
    from hermitcrm import cli
    store = Store(root)
    store.load()
    send(store, days=6)
    assert cli.main(["outreach", "followup-done", MARA], root=root) == 0
    assert "marked done" in capsys.readouterr().out
    assert cli.main(["outreach", "followup-done", MARA, "--undo"], root=root) == 0
    assert "reopened" in capsys.readouterr().out


def test_done_also_clears_the_radar_on_the_home_page_and_the_command_line(root, capsys):
    from hermitcrm import cli
    app = create_app(root, {**load_config(root), "push_enabled": False,
                            "welcome_dismissed": True})
    app.state.setup_redirected = True
    app.state.store.clock = lambda: NOW
    home = TestClient(app, follow_redirects=False)
    sent = send(app.state.store, days=6)
    line = "lindenhof-data | Mara Keller"
    assert cli.main(["followups"], root=root) == 0
    assert line in capsys.readouterr().out
    assert "A first message." in home.get("/").text   # the radar row's last message

    post(home, "/outreach/followups/done", followup=f"lindenhof-data/{sent.id}")
    assert cli.main(["followups"], root=root) == 0
    assert line not in capsys.readouterr().out
    assert "A first message." not in home.get("/").text
