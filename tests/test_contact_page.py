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

"""The contact page: the status strip on top, the action row, the read-only
fields with an Edit box, the contact-page timeline, and the folded boxes
(docs/superpowers/specs/2026-10-15-contact-page-layout-design.md, P1)."""

from __future__ import annotations

import re
import subprocess
from html import unescape
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import followups, layout
from hermitcrm.followups import NUDGE, REPLY
from hermitcrm.web import create_app
from conftest import FIXED_NOW

TODAY = FIXED_NOW.date()
CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "owner_email": "me@example.com",
          "welcome_dismissed": True, "disclaimer_accepted": "2026-09-01T09:00:00"}
JANE = "/companies/acme/contacts/jane-doe"
MAX = "/companies/acme/contacts/max-roe"


def days_ago(n: int):
    return FIXED_NOW - timedelta(days=n)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for args in (["init", "-b", "main"], ["config", "user.name", "CRM Test"],
                 ["config", "user.email", "crm@test.local"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    return tmp_path


@pytest.fixture
def app(repo: Path):
    return create_app(repo, config=CONFIG, clock=lambda: FIXED_NOW)


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def store(app):
    store = app.state.store
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe", title="CTO", email="jane@acme.example")
    store.create_contact("acme", "Max", "Roe")
    return store


def strip(page: str) -> dict[str, str]:
    """The status strip as {label: text}, whitespace collapsed."""
    block = page.split('<dl class="status-strip">', 1)[1].split("</dl>", 1)[0]
    pairs = re.findall(r"<dt>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", block, re.S)
    clean = lambda html: " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())
    return {dt: clean(dd) for dt, dd in pairs}


# ------------------------------------------------------- followups.for_contact


def test_for_contact_is_none_without_touches_and_ignores_notes(store):
    company = store.get("acme")
    assert followups.for_contact(company, "jane-doe", TODAY) is None
    store.create_interaction("acme", channel="note", direction="", contact="jane-doe",
                             date=days_ago(9), body="Prefers mornings.")
    assert followups.for_contact(store.get("acme"), "jane-doe", TODAY) is None


def test_for_contact_uses_the_radar_rule_and_thresholds(store):
    store.create_interaction("acme", channel="email", direction="in", contact="jane-doe",
                             date=days_ago(3), subject="Pricing?", body="Can you send it?")
    company = store.get("acme")
    row = followups.for_contact(company, "jane-doe", TODAY)
    assert (row.kind, row.days, row.summary) == (REPLY, 3, "Pricing?")
    assert followups.for_contact(company, "jane-doe", TODAY, reply_after=4) is None
    # The radar says the same about the company.
    assert [(r.kind, r.days) for r in followups.radar(store, TODAY)] == [(REPLY, 3)]


def test_for_contact_looks_at_this_person_only(store):
    store.create_interaction("acme", channel="linkedin", direction="out", contact="jane-doe",
                             date=days_ago(8), body="Hi Jane,\n\nShall we talk?")
    store.create_interaction("acme", channel="email", direction="in", contact="max-roe",
                             date=days_ago(1), body="Thanks, got it.")
    company = store.get("acme")
    assert followups.for_contact(company, "jane-doe", TODAY).kind == NUDGE
    assert followups.for_contact(company, "max-roe", TODAY).kind == REPLY


def test_a_planned_next_step_silences_the_nudge_as_on_home(store):
    store.create_interaction("acme", channel="linkedin", direction="out", contact="jane-doe",
                             date=days_ago(8), body="Shall we talk?")
    store.add_task("acme", "call Jane", due=TODAY + timedelta(days=2))
    assert followups.for_contact(store.get("acme"), "jane-doe", TODAY) is None


def test_a_closed_company_waits_on_nobody(store):
    store.create_interaction("acme", channel="email", direction="in", contact="jane-doe",
                             date=days_ago(3), body="Hello")
    company = store.get("acme")
    company.stage = company.stages.names[-1]          # a closed stage
    assert not company.is_active
    assert followups.for_contact(company, "jane-doe", TODAY) is None


# ------------------------------------------------------------- the status strip


def test_the_strip_with_nothing_logged(client, store):
    facts = strip(client.get(MAX).text)
    assert facts == {"Last touch": "none yet", "Waiting on": "nobody",
                     "Next for Max": "nothing planned", "History": "no touches yet"}


def test_the_strip_when_a_reply_is_owed(client, store):
    store.create_interaction("acme", channel="linkedin", direction="out", contact="jane-doe",
                             date=days_ago(10), body="Hi Jane,\n\nShall we talk?")
    store.create_interaction("acme", channel="email", direction="in", contact="jane-doe",
                             date=days_ago(3), subject="Pricing?", body="Can you send it?")
    store.create_interaction("acme", channel="note", direction="", contact="jane-doe",
                             date=days_ago(1), body="She reads mail at night.")
    facts = strip(client.get(JANE).text)
    assert facts["Last touch"] == "2026-09-11, email ← in 3 days ago"   # the note is no touch
    assert facts["Waiting on"] == "you: reply owed since 2026-09-11 · Pricing?"
    assert facts["History"] == "2 touches, 1 in / 1 out since 2026-09-04"


def test_the_strip_when_waiting_on_them(client, store):
    store.create_interaction("acme", channel="linkedin", direction="out", contact="jane-doe",
                             date=days_ago(6), body="Hi Jane,\n\nShall we talk next week?")
    facts = strip(client.get(JANE).text)
    assert facts["Waiting on"] == "them: no answer since 2026-09-08 · Shall we talk next week?"
    assert facts["History"] == "1 touch, 0 in / 1 out since 2026-09-08"


def test_next_is_the_persons_open_task_due_first_overdue_in_red(client, store):
    store.add_task("acme", "send the deck", due=TODAY + timedelta(days=5), contact="jane-doe")
    store.add_task("acme", "send the pricing", due=TODAY - timedelta(days=1),
                   contact="jane-doe")
    store.add_task("acme", "company-wide thing", due=TODAY - timedelta(days=9))
    page = client.get(JANE).text
    assert strip(page)["Next for Jane"] == "send the pricing due 2026-09-13"
    assert '<dd class="overdue">send the pricing' in page


# ------------------------------------------------------------ header and fields


def test_the_line_under_the_name_says_nothing_about_missing_fields(client, store):
    jane = client.get(JANE).text
    assert re.search(r"CTO at <a href=\"/companies/acme\">Acme GmbH</a>", jane)
    maxs = client.get(MAX).text
    assert "no title" not in maxs and "no role" not in maxs and "no phone" not in maxs
    assert '<a href="?edit=1#details">+ phone</a>' in maxs


def test_the_action_row_never_offers_to_send(client, store):
    page = client.get(JANE).text
    actions = page.split('<div class="contact-actions">', 1)[1].split("</div>", 1)[0]
    assert "Log interaction" in actions and "Add note" in actions and "Add task" in actions
    assert 'data-copy-email="jane@acme.example"' in actions
    assert "Send" not in actions


def test_add_note_opens_the_log_form_on_note(client, store):
    page = client.get(JANE + "?channel=note").text
    assert '<option value="note" selected>' in page
    assert 'class="interaction-form is-note"' in page


def test_details_are_read_only_until_edit(client, store):
    assert '<details class="edit-box">' in client.get(JANE).text
    assert '<details class="edit-box" open>' in client.get(JANE + "?edit=1").text


def test_a_form_with_errors_comes_back_open(client, store):
    response = client.post(JANE, data={"first_name": "", "last_name": ""})
    assert response.status_code == 400
    assert '<details class="edit-box" open>' in response.text
    assert '<dl class="status-strip">' in response.text


# ----------------------------------------------------------------- the timeline


def test_the_contact_timeline_drops_the_name_and_no_subject(client, store):
    store.create_interaction("acme", channel="linkedin", direction="out", contact="jane-doe",
                             date=days_ago(2), body="Hi Jane,\n\nSaw your post on robots.\nMore.")
    page = client.get(JANE).text
    timeline = page.split('id="timeline"', 1)[1]
    assert "(no subject)" not in timeline and 'class="who"' not in timeline
    assert '<span class="visually-hidden">out</span>' in timeline
    assert '<span class="first-line">Saw your post on robots.</span>' in timeline
    company = client.get("/companies/acme").text            # unchanged there
    assert "(no subject)" in company and 'class="who"' in company


# ------------------------------------------------------------ the folded boxes


def test_drafts_start_open_until_a_first_message_went_out(client, store):
    assert '<details id="drafts" class="drafts-box" open>' in client.get(JANE).text
    store.create_interaction("acme", channel="linkedin", direction="out", contact="jane-doe",
                             date=days_ago(2), body="Hi Jane")
    page = client.get(JANE).text
    assert '<details id="drafts" class="drafts-box">' in page
    assert '<details id="drafts" class="drafts-box" open>' in \
        client.get(JANE + "?signal=hiring").text


def test_merge_and_delete_live_in_the_closed_more_box(client, store):
    page = client.get(JANE).text
    more = page.split('<details class="more-box">', 1)[1].split("</details>", 1)[0]
    assert 'id="merge"' in more and 'id="delete"' in more and "slug jane-doe" in more
    (store.root / layout.FILENAME).write_text('[contact]\nhide_sections = ["delete"]\n')
    page = client.get(JANE).text
    assert "Delete contact" not in page and "More: merge, slug and dates" in page


def test_every_contact_section_still_has_its_anchor(client, store):
    page = client.get(JANE).text
    for name in layout.SECTIONS["contact"]:
        assert f'id="{name}"' in page, name
