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

"""The follow-up radar: who is waiting on you, and who you are waiting on."""

from datetime import date, timedelta

import pytest

from hermitcrm import followups
from hermitcrm.followups import NUDGE, REPLY

from conftest import FIXED_NOW

TODAY = FIXED_NOW.date()


def days_ago(n: int):
    return FIXED_NOW - timedelta(days=n)


@pytest.fixture
def seeded(store):
    """Two companies with one contact each, no interactions yet."""
    for name in ("Acme BV", "Borduro"):
        company = store.create_company(name=name, country="NL")
        store.create_contact(company.slug, first_name="Jane", last_name="Roe",
                             email=f"jane@{company.slug}.example.com")
    return store


def test_inbound_last_means_you_owe_a_reply(seeded):
    seeded.create_interaction("acme", channel="email", direction="in",
                              contact="jane-roe", date=days_ago(3),
                              subject="Re: your note", body="Sounds interesting.")
    rows = followups.radar(seeded, TODAY)

    assert [(r.slug, r.kind, r.days) for r in rows] == [("acme", REPLY, 3)]
    assert rows[0].who == "Jane Roe"
    assert rows[0].reason == "Jane Roe wrote, no reply from you"


def test_your_own_reply_clears_the_row(seeded):
    seeded.create_interaction("acme", channel="email", direction="in",
                              contact="jane-roe", date=days_ago(3), body="Interested.")
    seeded.create_interaction("acme", channel="email", direction="out",
                              contact="jane-roe", date=days_ago(2), body="Glad to hear it.")

    rows = followups.radar(seeded, TODAY, nudge_after=5)
    assert rows == []


def test_unanswered_outbound_becomes_a_nudge_only_after_the_threshold(seeded):
    seeded.create_interaction("acme", channel="linkedin", direction="out",
                              contact="jane-roe", date=days_ago(6),
                              body="Hi Jane,\n\nSaw you are hiring.")

    assert followups.radar(seeded, TODAY, nudge_after=7) == []
    rows = followups.radar(seeded, TODAY, nudge_after=5)
    assert [(r.slug, r.kind, r.days) for r in rows] == [("acme", NUDGE, 6)]
    # the greeting is skipped, so the preview says something
    assert rows[0].summary == "Saw you are hiring."


def test_a_meeting_is_not_something_that_failed_to_reply(seeded):
    seeded.create_interaction("acme", channel="meeting", direction="out",
                              contact="jane-roe", date=days_ago(20),
                              subject="Intro call", body="Talked about the rollout.")
    assert followups.radar(seeded, TODAY, nudge_after=5) == []


def test_a_planned_next_step_silences_a_nudge_but_not_a_reply(seeded):
    for slug in ("acme", "borduro"):
        seeded.update_company(slug, next_step="send the proposal",
                              next_step_due=TODAY + timedelta(days=4))
    seeded.create_interaction("acme", channel="email", direction="out",
                              contact="jane-roe", date=days_ago(9), body="Proposal follows.")
    seeded.create_interaction("borduro", channel="email", direction="in",
                              contact="jane-roe", date=days_ago(9), body="One question.")

    rows = followups.radar(seeded, TODAY, nudge_after=5)
    assert [(r.slug, r.kind) for r in rows] == [("borduro", REPLY)]


def test_an_overdue_next_step_is_not_a_plan_any_more(seeded):
    seeded.update_company("acme", next_step="send the proposal",
                          next_step_due=TODAY - timedelta(days=1))
    seeded.create_interaction("acme", channel="email", direction="out",
                              contact="jane-roe", date=days_ago(9), body="Proposal follows.")

    assert [r.kind for r in followups.radar(seeded, TODAY, nudge_after=5)] == [NUDGE]


def test_closed_companies_are_waiting_on_nobody(seeded):
    seeded.create_interaction("acme", channel="email", direction="in",
                              contact="jane-roe", date=days_ago(9), body="No thanks.")
    seeded.update_company("acme", stage="lost", lost_reason="no budget")

    assert followups.radar(seeded, TODAY) == []


def test_replies_sort_before_nudges_and_oldest_first(seeded):
    seeded.create_company(name="Cedar Labs", country="NL")
    seeded.create_interaction("acme", channel="email", direction="out",
                              contact="jane-roe", date=days_ago(30), body="Still keen?")
    seeded.create_interaction("borduro", channel="email", direction="in",
                              contact="jane-roe", date=days_ago(2), body="Quick question.")
    seeded.create_interaction("cedar-labs", channel="email", direction="out",
                              date=days_ago(8), body="Worth a chat?")

    rows = followups.radar(seeded, TODAY, nudge_after=5)
    assert [(r.slug, r.kind) for r in rows] == [
        ("borduro", REPLY), ("acme", NUDGE), ("cedar-labs", NUDGE),
    ]


def test_render_says_so_when_there_is_nothing(store):
    assert "Nothing waiting" in followups.render([])


def test_render_splits_the_two_lists(seeded):
    seeded.create_interaction("acme", channel="email", direction="in",
                              contact="jane-roe", date=days_ago(2), body="Question.")
    seeded.create_interaction("borduro", channel="email", direction="out",
                              date=days_ago(9), body="Worth a chat?")

    text = followups.render(followups.radar(seeded, TODAY, nudge_after=5))
    assert "## You owe a reply (1)" in text
    assert "## Waiting on them (1)" in text
    assert text.index("You owe a reply") < text.index("Waiting on them")


def test_first_line_keeps_a_body_that_is_only_a_greeting():
    assert followups.first_line("Hi Jane,") == "Hi Jane,"
    assert followups.first_line("") == ""
    assert followups.first_line("x" * 200).endswith("…")
