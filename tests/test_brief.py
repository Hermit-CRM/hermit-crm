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

"""Pre-meeting briefs, assembled from the last calendar import plus the record."""

from datetime import timedelta

import pytest

from hermitcrm import bcc, brief, calendar_sync
from hermitcrm.models import fmt_datetime

from conftest import FIXED_NOW

TODAY = FIXED_NOW.date()
SOON = FIXED_NOW + timedelta(days=1)


def put_upcoming(store, *rows):
    inbox = bcc.Inbox(store.root)
    calendar_sync.write_upcoming(inbox, list(rows), FIXED_NOW)
    return inbox


def event(slug="acme", name="Acme BV", title="Pricing follow-up", start=None,
          attendees=("Jane Roe",), location="Google Meet"):
    start = start or SOON
    return {
        "start": fmt_datetime(start), "end": fmt_datetime(start + timedelta(hours=1)),
        "all_day": False, "title": title, "location": location,
        "companies": [{"slug": slug, "name": name}],
        "attendees": list(attendees),
    }


@pytest.fixture
def seeded(store):
    company = store.create_company(name="Acme BV", country="NL", stage="discovery",
                                   value_eur_month="1500",
                                   product_oneliner="Churn dashboards",
                                   next_step="Send the case study",
                                   next_step_due=TODAY + timedelta(days=2))
    store.create_contact(company.slug, first_name="Jane", last_name="Roe",
                         title="Founder", email="jane@acme.example.com")
    return store


def test_brief_pulls_the_record_behind_the_meeting(seeded):
    seeded.create_interaction("acme", channel="email", direction="in",
                              contact="jane-roe", date=FIXED_NOW - timedelta(days=3),
                              subject="Re: pricing", body="Two questions.")
    inbox = put_upcoming(seeded, event())

    [b] = brief.briefs(seeded, inbox, FIXED_NOW)
    assert b.title == "Pricing follow-up" and b.attendees == ["Jane Roe"]
    assert [m.company.slug for m in b.companies] == ["acme"]

    text = brief.render([b], TODAY)
    assert "Acme BV (acme) -- discovery" in text and "1500 EUR/month" in text
    assert "Open next step: Send the case study, due 2026-09-16" in text
    assert "Jane Roe (Founder)" in text
    assert "Re: pricing" in text
    assert "Google Meet" in text


def test_only_the_last_three_interactions_make_the_brief(seeded):
    for n in range(6):
        seeded.create_interaction("acme", channel="email", direction="out",
                                  contact="jane-roe",
                                  date=FIXED_NOW - timedelta(days=10 + n),
                                  subject=f"Note {n}")
    inbox = put_upcoming(seeded, event())

    [b] = brief.briefs(seeded, inbox, FIXED_NOW)
    [match] = b.companies
    assert len(match.interactions) == brief.RECENT
    text = brief.render([b], TODAY)
    assert "Note 0" in text and "Note 2" in text  # newest three
    assert "Note 3" not in text and "Note 5" not in text


def test_a_meeting_whose_company_is_gone_is_dropped(seeded):
    inbox = put_upcoming(seeded, event(slug="vanished", name="Gone BV"))
    assert brief.briefs(seeded, inbox, FIXED_NOW) == []


def test_no_meetings_says_how_to_refresh(store):
    inbox = bcc.Inbox(store.root)
    text = brief.render(brief.briefs(store, inbox, FIXED_NOW), TODAY)
    assert "No meetings with known companies" in text
    assert "hermitcrm calendar --apply" in text


def test_a_company_with_no_history_says_so(seeded):
    inbox = put_upcoming(seeded, event())
    text = brief.render(brief.briefs(seeded, inbox, FIXED_NOW), TODAY)
    assert "No interactions logged yet." in text


def test_meetings_come_back_soonest_first(seeded):
    seeded.create_company(name="Borduro", country="NL")
    inbox = put_upcoming(
        seeded,
        event(slug="borduro", name="Borduro", title="Later",
              start=FIXED_NOW + timedelta(days=3)),
        event(title="Sooner"),
    )
    assert [b.title for b in brief.briefs(seeded, inbox, FIXED_NOW)] == ["Sooner", "Later"]
