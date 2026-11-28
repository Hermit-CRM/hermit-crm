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

"""Quick capture (capture_text.py): one sentence in, a proposal out, and the proposal
filed as one commit. The AI is a fake; every date is measured from the store's clock
(conftest FIXED_NOW, Monday 14 September 2026)."""

from datetime import date, datetime

import pytest

from hermitcrm import capture_text as ct
from hermitcrm.enrich import EnrichError, Enricher
from hermitcrm.models import ValidationError

MONDAY = date(2026, 9, 14)


# ------------------------------------------------------------------ dates


@pytest.mark.parametrize("written, expected", [
    ("", None),
    ("today", MONDAY),
    ("Tomorrow", date(2026, 9, 15)),
    ("the day after tomorrow", date(2026, 9, 16)),
    ("Friday", date(2026, 9, 18)),
    ("on Friday", date(2026, 9, 18)),
    ("by friday.", date(2026, 9, 18)),
    ("this Friday", date(2026, 9, 18)),
    ("Monday", date(2026, 9, 21)),           # a bare weekday is never today
    ("this Monday", MONDAY),
    ("next Friday", date(2026, 9, 25)),      # Friday of next week
    ("next week", date(2026, 9, 21)),        # its Monday
    ("end of the week", date(2026, 9, 18)),
    ("end of next week", date(2026, 9, 25)),
    ("next month", date(2026, 10, 1)),
    ("end of the month", date(2026, 9, 30)),
    ("in 3 days", date(2026, 9, 17)),
    ("in two weeks", date(2026, 9, 28)),
    ("in a month", date(2026, 10, 14)),
    ("2026-10-02", date(2026, 10, 2)),
    ("2 October", date(2026, 10, 2)),
    ("October 2nd", date(2026, 10, 2)),
    ("3 Feb", date(2027, 2, 3)),             # a date already past is next year's
    ("Friday 2 October", date(2026, 10, 2)),
    ("whenever suits them", None),
])
def test_due_dates_resolve_forward_from_the_store_clock(written, expected):
    assert ct.resolve_date(written, MONDAY) == expected


@pytest.mark.parametrize("written, expected", [
    ("yesterday", date(2026, 9, 13)),
    ("Friday", date(2026, 9, 11)),
    ("last Friday", date(2026, 9, 11)),
    ("on Monday", date(2026, 9, 7)),
    ("this morning", MONDAY),
    ("2 days ago", date(2026, 9, 12)),
    ("a week ago", date(2026, 9, 7)),
    ("last week", date(2026, 9, 7)),
    ("3 Feb", date(2026, 2, 3)),             # in the past: this year's
    ("10 December", date(2025, 12, 10)),     # not yet this year: last year's
])
def test_when_it_happened_resolves_backward(written, expected):
    assert ct.resolve_date(written, MONDAY, past=True) == expected


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def crm(store, messages):
    """Two companies with people; `messages` cleared, so it counts commits from here."""
    acme = store.create_company("Acme Robotics", website="acme.example.com")
    store.create_contact(acme.slug, "Jane", "Doe", email="jane@example.com")
    store.create_contact(acme.slug, "Piet", "Jansen")
    globex = store.create_company("Globex Logistics")
    store.create_contact(globex.slug, "Sam", "Rivera")
    messages.clear()
    return store


TEXT = "Called Jane at Acme, she wants a proposal by Friday and a demo next week.\n"


def answer(**over):
    data = {"company": "Acme Robotics", "company_slug": "acme-robotics",
            "contact": "Jane Doe", "contact_slug": "jane-doe", "channel": "call",
            "direction": "out", "date": "", "subject": "Proposal and demo",
            "outcome": "", "stage": "",
            "tasks": [{"text": "Send Jane the proposal", "due": "Friday"},
                      {"text": "Book the demo", "due": "next week"}]}
    data.update(over)
    return data


class FakeRunner:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def __call__(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        if isinstance(self.data, BaseException):
            raise self.data
        return self.data


def enricher(runner):
    return Enricher(provider="claude", which=lambda b: f"/usr/local/bin/{b}", runner=runner)


# ------------------------------------------------------------------ the call


def test_one_light_call_without_tools_gets_the_text_and_the_names(crm):
    runner = FakeRunner(answer())
    found = ct.parse(crm, enricher(runner), TEXT)

    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["tools"] == "" and call["schema"] is ct.SCHEMA
    assert TEXT.strip() in call["prompt"]
    assert "Jane Doe" in call["prompt"] and "Globex Logistics" in call["prompt"]
    assert found["model"] == "claude-haiku-5-5"   # the light tier


def test_the_preview_of_a_sentence_naming_an_existing_contact(crm):
    found = ct.parse(crm, enricher(FakeRunner(answer())), TEXT)

    assert found["company"] == {"slug": "acme-robotics", "name": "Acme Robotics",
                                "written": "Acme Robotics"}
    assert found["contact"] == {"slug": "jane-doe", "name": "Jane Doe", "written": "Jane Doe"}
    it = found["interaction"]
    assert (it["channel"], it["direction"], it["subject"]) == ("call", "out", "Proposal and demo")
    assert it["date"] == "2026-09-14T10:30"     # no date in the text: now
    assert [(t["text"], t["due"], t["written"]) for t in found["tasks"]] == [
        ("Send Jane the proposal", "2026-09-18", "Friday"),
        ("Book the demo", "2026-09-21", "next week")]
    assert found["stage"] is None
    assert found["notes"] == []


def test_a_name_the_model_spelled_differently_still_matches(crm):
    found = ct.parse(crm, enricher(FakeRunner(answer(
        company="acme robotics", company_slug="", contact="jane", contact_slug=""))), TEXT)
    assert found["company"]["slug"] == "acme-robotics"
    assert found["contact"]["slug"] == "jane-doe"


def test_a_person_alone_finds_their_company(crm):
    found = ct.parse(crm, enricher(FakeRunner(answer(
        company="", company_slug="", contact="Sam Rivera", contact_slug=""))), TEXT)
    assert found["company"]["slug"] == "globex-logistics"
    assert found["contact"]["slug"] == "sam-rivera"


def test_a_slug_that_is_not_in_the_crm_is_not_trusted(crm):
    found = ct.parse(crm, enricher(FakeRunner(answer(
        company="Initech", company_slug="initech", contact="Bill Lumbergh",
        contact_slug="bill-lumbergh"))), TEXT)
    assert found["company"] == {"slug": "", "name": "Initech", "written": "Initech"}
    assert found["contact"] == {"slug": "", "name": "Bill Lumbergh", "written": "Bill Lumbergh"}


def test_what_the_model_got_wrong_is_cleaned_not_trusted(crm):
    found = ct.parse(crm, enricher(FakeRunner(answer(
        channel="carrier pigeon", direction="sideways", outcome="Interested",
        stage="unicorn", date="sometime", tasks=[{"text": "  ", "due": ""},
                                                 {"text": "Call back", "due": "soonish"}]))),
        TEXT)
    it = found["interaction"]
    assert it["channel"] == "note" and it["direction"] == ""
    assert it["outcome"] == "interested"          # the configured spelling
    assert it["date"] == "2026-09-14T10:30"
    assert found["stage"] is None
    assert [(t["text"], t["due"]) for t in found["tasks"]] == [("Call back", "")]
    assert any("sometime" in n for n in found["notes"])
    assert any("soonish" in n for n in found["notes"])


def test_a_stage_move_is_proposed_only_when_it_is_one(crm):
    found = ct.parse(crm, enricher(FakeRunner(answer(stage="offer"))), TEXT)
    current = crm.get("acme-robotics").stage
    assert found["stage"] == {"to": "offer", "from": current}

    crm.update_company("acme-robotics", stage="offer")
    found = ct.parse(crm, enricher(FakeRunner(answer(stage="offer"))), TEXT)
    assert found["stage"] is None   # already there


def test_a_past_date_from_the_text_dates_the_interaction(crm):
    found = ct.parse(crm, enricher(FakeRunner(answer(date="yesterday"))), TEXT)
    assert found["interaction"]["date"] == "2026-09-13T12:00"


def test_no_text_or_no_ai_fails_before_any_call(crm):
    runner = FakeRunner(answer())
    with pytest.raises(EnrichError):
        ct.parse(crm, enricher(runner), "   ")
    missing = Enricher(provider="claude", which=lambda b: None, runner=runner)
    with pytest.raises(EnrichError):
        ct.parse(crm, missing, TEXT)
    assert runner.calls == []


# ------------------------------------------------------------------ filing


def values_for(crm, **over):
    found = ct.parse(crm, enricher(FakeRunner(answer())), TEXT)
    values = ct.initial_values(found)
    values.update(over)
    return values


def test_filing_writes_the_interaction_and_tasks_as_one_commit(crm, messages):
    result = ct.file(crm, values_for(crm), TEXT)

    assert len(messages) == 1
    assert messages[0].startswith("capture: acme-robotics")
    company = crm.get("acme-robotics")
    it = next(i for i in company.interactions if i.subject == "Proposal and demo")
    assert it.body == TEXT                       # the typed text, byte for byte
    assert (it.channel, it.direction, it.contact) == ("call", "out", "jane-doe")
    jane = company.contacts["jane-doe"]
    assert [(t.text, t.due) for t in jane.tasks] == [
        ("Send Jane the proposal", date(2026, 9, 18)), ("Book the demo", date(2026, 9, 21))]
    assert result.url == "/companies/acme-robotics/contacts/jane-doe"
    on_disk = crm.interaction_file("acme-robotics", it.id).read_bytes()
    assert on_disk.endswith(TEXT.encode("utf-8"))


def test_the_body_is_the_typed_text_even_when_it_is_odd(crm):
    text = "  Jane said: *ok*  \nNo caps,   two  spaces.\n"
    ct.file(crm, values_for(crm), text)
    it = next(i for i in crm.get("acme-robotics").interactions if i.subject == "Proposal and demo")
    assert it.body == text


def test_unticked_parts_are_not_written(crm, messages):
    values = values_for(crm, do_interaction=False)
    values["tasks"][1]["do"] = False
    ct.file(crm, values, TEXT)
    company = crm.get("acme-robotics")
    assert not any(i.subject == "Proposal and demo" for i in company.interactions)
    assert [t.text for t in company.contacts["jane-doe"].tasks] == ["Send Jane the proposal"]
    assert len(messages) == 1


def test_nothing_ticked_writes_nothing(crm, messages):
    values = values_for(crm, do_interaction=False)
    for task in values["tasks"]:
        task["do"] = False
    with pytest.raises(ValidationError):
        ct.file(crm, values, TEXT)
    assert messages == []


def test_a_bad_value_is_refused_before_anything_is_written(crm, messages):
    values = values_for(crm)
    values["tasks"][0]["due"] = "not a date"
    with pytest.raises(ValidationError) as err:
        ct.file(crm, values, TEXT)
    assert "task 1" in str(err.value)
    assert messages == []
    assert not any(i.subject == "Proposal and demo"
                   for i in crm.get("acme-robotics").interactions)


def test_a_contact_from_another_company_is_refused(crm, messages):
    with pytest.raises(ValidationError):
        ct.file(crm, values_for(crm, company="globex-logistics"), TEXT)
    assert messages == []


def test_creating_the_company_and_person_happens_only_when_asked(crm, messages):
    values = values_for(crm, company=ct.NEW, new_company="Initech",
                        contact=ct.NEW, new_contact="Bill Lumbergh")
    result = ct.file(crm, values, TEXT)

    assert len(messages) == 1
    initech = crm.get("initech")
    assert initech is not None and "bill-lumbergh" in initech.contacts
    assert initech.interactions[0].body == TEXT
    assert result.url == "/companies/initech/contacts/bill-lumbergh"


def test_the_stage_moves_in_the_same_commit(crm, messages):
    values = values_for(crm, do_stage=True, stage="offer")
    ct.file(crm, values, TEXT)
    assert crm.get("acme-robotics").stage == "offer"
    assert len(messages) == 1 and messages[0].endswith("stage prospect -> offer")


def test_the_first_touch_moving_the_stage_is_in_the_message(crm, messages):
    ct.file(crm, values_for(crm), TEXT)
    assert crm.get("acme-robotics").stage == "engaged"
    assert messages == ["capture: acme-robotics call out jane-doe; 2 tasks; "
                        "stage prospect -> engaged"]


def test_a_lost_stage_needs_its_reason_first(crm, messages):
    lost = crm.stages.with_role("lost")[0]
    with pytest.raises(ValidationError):
        ct.file(crm, values_for(crm, do_stage=True, stage=lost), TEXT)
    assert messages == []
    ct.file(crm, values_for(crm, do_stage=True, stage=lost, lost_reason="Went with a rival"),
            TEXT)
    company = crm.get("acme-robotics")
    assert company.stage == lost and company.lost_reason == "Went with a rival"
    assert len(messages) == 1


def test_a_date_typed_in_the_preview_is_read(crm):
    values = values_for(crm, date="2026-09-10T15:45")
    ct.file(crm, values, TEXT)
    it = next(i for i in crm.get("acme-robotics").interactions if i.subject == "Proposal and demo")
    assert it.date == datetime(2026, 9, 10, 15, 45)
