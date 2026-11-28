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

"""The Today queue: one prioritised list of what to do now (today.py)."""

import json
import re
from datetime import timedelta

import pytest

from hermitcrm import followups, routines, today as today_mod
from hermitcrm.today import (BRIEF, DRAFT, DUE, KEEP, MEETING, NUDGE, OVERDUE, PREPARED,
                             REPLY, Item, build)

from conftest import FIXED_NOW

TODAY = FIXED_NOW.date()
CONFIG = {"followup_reply_days": 1, "followup_nudge_days": 5, "keep_in_touch_days": 180}


def days_ago(n: int):
    return FIXED_NOW - timedelta(days=n)


@pytest.fixture
def seeded(store):
    """Three companies with one contact each, no interactions or tasks yet."""
    for name in ("Acme BV", "Borduro", "Calloway Ltd"):
        company = store.create_company(name=name, country="NL")
        store.create_contact(company.slug, first_name="Jane", last_name="Roe",
                             email=f"jane@{company.slug}.example.com")
    return store


def kinds(queue):
    return [i.kind for i in queue.items]


# ------------------------------------------------------------------ basics


def test_an_empty_folder_has_an_empty_queue(store):
    queue = build(store, CONFIG, TODAY)
    assert queue.items == []
    assert queue.total == 0
    assert queue.next_up is None
    assert queue.failed == []


def test_order_table_is_the_one_the_briefing_names():
    order = [kind for kind, _ in today_mod.ORDER]
    assert order == [REPLY, OVERDUE, MEETING, BRIEF, DRAFT, PREPARED, DUE, NUDGE, KEEP]


def test_groups_come_in_table_order(seeded):
    s = seeded
    # a nudge at Acme, a reply owed at Borduro, an overdue and a due task at Calloway
    s.create_interaction("acme", channel="email", direction="out", contact="jane-roe",
                         date=days_ago(9), subject="Proposal", body="Here it is.")
    s.create_interaction("borduro", channel="email", direction="in", contact="jane-roe",
                         date=days_ago(2), subject="Question", body="Can we talk?")
    s.add_task("calloway", "send the deck", due=TODAY - timedelta(days=3))
    s.add_task("calloway", "call back", due=TODAY)

    queue = build(s, CONFIG, TODAY)
    assert kinds(queue) == [REPLY, OVERDUE, DUE, NUDGE]
    assert [i.urgency for i in queue.items] == sorted(i.urgency for i in queue.items)
    assert [g.heading for g in queue.groups()] == [
        "Replies you owe", "Overdue tasks", "Due today", "Waiting on them"]


def test_oldest_first_inside_a_group(seeded):
    s = seeded
    s.create_interaction("acme", channel="email", direction="in", contact="jane-roe",
                         date=days_ago(2), body="Short one.")
    s.create_interaction("borduro", channel="email", direction="in", contact="jane-roe",
                         date=days_ago(7), body="Older one.")
    s.add_task("acme", "newer", due=TODAY - timedelta(days=1))
    s.add_task("borduro", "older", due=TODAY - timedelta(days=10))

    queue = build(s, CONFIG, TODAY)
    replies = [i.company.slug for i in queue.items if i.kind == REPLY]
    overdue = [i.title for i in queue.items if i.kind == OVERDUE]
    assert replies == ["borduro", "acme"]
    assert overdue == ["older", "newer"]


# ------------------------------------------------- one company, once per kind


def test_a_company_appears_once_per_kind_with_a_count(seeded):
    s = seeded
    s.add_task("acme", "second", due=TODAY - timedelta(days=2))
    s.add_task("acme", "first", due=TODAY - timedelta(days=5), contact="jane-roe")
    s.add_task("acme", "third", due=TODAY - timedelta(days=1))

    queue = build(s, CONFIG, TODAY)
    overdue = [i for i in queue.items if i.kind == OVERDUE]
    assert len(overdue) == 1
    item = overdue[0]
    assert item.title == "first"        # the oldest one stands for the rest
    assert item.count == 3
    assert item.contact.slug == "jane-roe"
    assert item.reason.endswith("; and 2 more overdue here: second, third")
    # the group and the queue count tasks, not rows, so they match the Tasks page
    assert queue.groups()[0].count == 3
    assert queue.total == 3


def test_counts_match_the_radar_and_the_tasks_page(seeded):
    s = seeded
    s.create_interaction("acme", channel="email", direction="in", contact="jane-roe",
                         date=days_ago(3), body="Waiting on you.")
    s.create_interaction("borduro", channel="email", direction="out", contact="jane-roe",
                         date=days_ago(8), body="Any news?")
    s.add_task("acme", "overdue one", due=TODAY - timedelta(days=1))
    s.add_task("borduro", "overdue two", due=TODAY - timedelta(days=4))
    s.add_task("borduro", "today", due=TODAY)
    s.add_task("calloway", "later", due=TODAY + timedelta(days=4))
    s.add_task("calloway", "no date")
    s.update_company("calloway", next_step="phone", next_step_due=TODAY)

    queue = build(s, CONFIG, TODAY)
    radar = followups.radar(s, TODAY, reply_after=1, nudge_after=5)
    assert queue.count(REPLY) == sum(1 for r in radar if r.kind == followups.REPLY)
    assert queue.count(NUDGE) == sum(1 for r in radar if r.kind == followups.NUDGE)
    open_todos = [t for c in s.companies.values() for t in c.open_todos()]
    assert queue.count(OVERDUE) == sum(1 for t in open_todos if t.due and t.due < TODAY)
    assert queue.count(DUE) == sum(1 for t in open_todos if t.due == TODAY)
    assert queue.count(DUE) == 2        # the task and the next-step field


def test_tasks_at_closed_companies_count_too_as_on_the_tasks_page(seeded):
    seeded.update_company("acme", stage="lost", lost_reason="no budget")
    seeded.add_task("acme", "send the leaflet", due=TODAY - timedelta(days=2))
    assert kinds(build(seeded, CONFIG, TODAY)) == [OVERDUE]


# --------------------------------------------------------------- the actions


def test_a_task_carries_the_existing_done_form(seeded):
    seeded.add_task("acme", "send the deck", due=TODAY, contact="jane-roe")
    item = build(seeded, CONFIG, TODAY).items[0]
    done = item.actions[0]
    assert done.method == "post"
    assert done.href == "/companies/acme/tasks/0/done"
    assert dict(done.fields) == {"contact": "jane-roe", "text": "send the deck", "done": "1"}
    assert item.href == "/companies/acme/contacts/jane-roe"


def test_a_next_step_carries_the_next_step_form(seeded):
    seeded.update_company("acme", next_step="phone", next_step_due=TODAY)
    item = build(seeded, CONFIG, TODAY).items[0]
    done = item.actions[0]
    assert (done.method, done.href, dict(done.fields)) == (
        "post", "/companies/acme/next-step", {"status": "done"})


def test_a_reply_links_to_logging_one(seeded):
    seeded.create_interaction("acme", channel="email", direction="in", contact="jane-roe",
                              date=days_ago(3), subject="Pricing", body="How much?")
    item = build(seeded, CONFIG, TODAY).items[0]
    assert item.kind == REPLY
    assert item.title == "Pricing"
    assert item.reason == "Jane Roe wrote 3 days ago, no reply from you"
    assert item.due == TODAY - timedelta(days=3)
    log = item.actions[0]
    assert (log.method, log.href) == ("get", "/companies/acme/interactions/new?contact=jane-roe")


def test_every_post_action_is_an_existing_route(seeded):
    """No new write routes: each form a row carries posts to a route web.py
    already has (read from its source, as the routes are nested in create_app)."""
    from hermitcrm import web
    source = open(web.__file__, encoding="utf-8").read()
    patterns = [re.compile("^" + re.sub(r"\\{[^}]+\\}", "[^/]+", re.escape(p)) + "$")
                for p in re.findall(r'@app\.post\("([^"]+)"', source)]
    s = seeded
    s.add_task("acme", "one", due=TODAY, contact="jane-roe")
    s.update_company("borduro", next_step="two", next_step_due=TODAY)
    routines.write_draft(s.root, routines.Draft(
        id="", routine="nudge-old", made=days_ago(1), record="acme/jane-roe",
        company="acme", contact="jane-roe", channel="email", subject="Hi",
        basis="", reason="", body="Hello.\n"))
    posts = [a.href for i in build(s, CONFIG, TODAY).items for a in i.actions
             if a.method == "post"]
    assert len(posts) == 3
    for href in posts:
        assert any(p.match(href) for p in patterns), href


# ----------------------------------------------------- drafts, briefs, meetings


def test_a_routine_draft_waits_for_you(seeded):
    routines.write_draft(seeded.root, routines.Draft(
        id="", routine="nudge-old", made=days_ago(1), record="acme/jane-roe",
        company="acme", contact="jane-roe", channel="email", subject="Checking in",
        basis="", reason="no reply in 9 days", body="Hi Jane,\n\nAny news?\n"))
    queue = build(seeded, CONFIG, TODAY)
    item = next(i for i in queue.items if i.kind == DRAFT)
    assert item.contact.slug == "jane-roe"
    assert "no reply in 9 days" in item.reason
    assert item.href.startswith("/#draft-")
    discard = [a for a in item.actions if a.method == "post"]
    assert discard and discard[0].href.endswith("/discard")


def test_todays_brief_is_on_the_queue(seeded, monkeypatch):
    brief = {"title": "Morning brief", "name": "morning", "date": "2026-09-14",
             "at": "2026-09-14 07:00",
             "sections": [{"title": "Meetings today", "items": [], "more": 0, "count": 1},
                          {"title": "Tasks due", "items": [], "more": 0, "count": 2},
                          {"title": "Replies you owe", "items": [], "more": 0, "count": 0}]}
    monkeypatch.setattr(routines, "home_context",
                        lambda store, config=None: {"routine_drafts": [],
                                                    "routine_briefs": [brief]})
    item = next(i for i in build(seeded, CONFIG, TODAY).items if i.kind == BRIEF)
    assert item.title == "Morning brief"
    assert item.reason == "1 meeting, 2 tasks due, 0 replies owed"
    assert item.href == "/#brief-morning"


def test_todays_meetings_come_from_the_calendar_import(seeded):
    inbox = seeded.root / "inbox"
    inbox.mkdir(exist_ok=True)
    start = FIXED_NOW + timedelta(hours=2)
    tomorrow = FIXED_NOW + timedelta(days=1)
    events = [
        {"title": "Intro call", "start": start.isoformat(),
         "end": (start + timedelta(hours=1)).isoformat(),
         "companies": [{"slug": "acme"}]},
        {"title": "Tomorrow", "start": tomorrow.isoformat(),
         "end": (tomorrow + timedelta(hours=1)).isoformat()},
    ]
    (inbox / "upcoming.json").write_text(json.dumps({"events": events}), encoding="utf-8")
    meetings = [i for i in build(seeded, CONFIG, TODAY).items if i.kind == MEETING]
    assert [m.title for m in meetings] == ["12:30 Intro call"]
    assert meetings[0].company.slug == "acme"
    assert meetings[0].href == "/companies/acme"


def test_keep_in_touch_is_one_row_per_company(seeded):
    s = seeded
    s.update_company("acme", stage="won")
    s.create_contact("acme", first_name="Bo", last_name="Vance", email="bo@acme.example.com")
    s.create_interaction("acme", channel="email", direction="out", contact="jane-roe",
                         date=days_ago(400), body="Old news.")
    s.create_interaction("acme", channel="email", direction="in", contact="bo-vance",
                         date=days_ago(200), body="Older news.")
    items = [i for i in build(s, CONFIG, TODAY).items if i.kind == KEEP]
    assert len(items) == 1
    assert items[0].count == 2
    assert items[0].contact.slug == "jane-roe"    # the longest quiet first
    assert "Jane Roe" in items[0].title and "Bo Vance" in items[0].title


# ------------------------------------------------------- empty state, limits


def test_next_up_is_the_next_dated_task(seeded):
    seeded.add_task("acme", "far", due=TODAY + timedelta(days=20))
    seeded.add_task("borduro", "near", due=TODAY + timedelta(days=3))
    seeded.add_task("calloway", "undated")
    queue = build(seeded, CONFIG, TODAY)
    assert queue.items == []
    assert queue.next_up.title == "near"
    assert queue.next_up.due == TODAY + timedelta(days=3)


def test_shown_caps_the_rows_and_keeps_the_groups(seeded):
    for n in range(30):
        company = seeded.create_company(name=f"Firm {n:02d}", country="NL")
        seeded.add_task(company.slug, f"task {n}", due=TODAY - timedelta(days=n + 1))
    queue = build(seeded, CONFIG, TODAY)
    groups = queue.groups(limit=25)
    assert sum(len(g.items) for g in groups) == 25
    assert groups[0].count == 30         # the heading still says how many there are
    assert queue.more(25) == 5


# -------------------------------------------------------- the provider seam


def test_a_broken_provider_does_not_break_the_queue(seeded, monkeypatch):
    def boom(store, config, today):
        raise RuntimeError("bad file")
    monkeypatch.setattr(today_mod, "PROVIDERS", [*today_mod.PROVIDERS, boom])
    seeded.add_task("acme", "still here", due=TODAY)
    queue = build(seeded, CONFIG, TODAY)
    assert kinds(queue) == [DUE]
    assert queue.failed == ["boom"]


def test_register_adds_a_provider_and_its_kind_in_one_call(seeded, monkeypatch):
    monkeypatch.setattr(today_mod, "PROVIDERS", list(today_mod.PROVIDERS))
    monkeypatch.setattr(today_mod, "ORDER", list(today_mod.ORDER))

    def calls(store, config, today):
        return [Item(kind="call", company=store.companies["acme"], contact=None,
                     title="Call Acme", reason="they asked", due=today, href="/companies/acme")]

    today_mod.register(calls, kind="call", heading="Calls to make", before=DRAFT)
    today_mod.register(calls, kind="call", heading="Calls to make", before=DRAFT)  # no-op
    seeded.add_task("acme", "overdue", due=TODAY - timedelta(days=1))
    seeded.add_task("borduro", "due", due=TODAY)
    queue = build(seeded, CONFIG, TODAY)
    assert kinds(queue) == [OVERDUE, "call", DUE]
    assert today_mod.PROVIDERS.count(calls) == 1
    assert [g.heading for g in queue.groups()][1] == "Calls to make"


def test_an_unknown_kind_sorts_last(seeded, monkeypatch):
    def odd(store, config, today):
        return [Item(kind="odd", company=None, contact=None, title="?", reason="",
                     due=None, href="/")]
    monkeypatch.setattr(today_mod, "PROVIDERS", [*today_mod.PROVIDERS, odd])
    seeded.add_task("acme", "due", due=TODAY)
    queue = build(seeded, CONFIG, TODAY)
    assert kinds(queue) == [DUE, "odd"]
    assert queue.groups()[-1].heading == "More"
