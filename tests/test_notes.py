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

"""notes.py: a finding is a note. The note format, the snapshot the draft is
written from, and the rows of the Outreach card's Notes panel
(docs/superpowers/specs/2026-10-20-outreach-notes-and-drafts-design.md, part C)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import FIXED_NOW
from hermitcrm import notes, outreach
from hermitcrm.outreach import Finding

TODAY = FIXED_NOW.date()
SOURCE = "https://acme.example.com/news"


@pytest.fixture
def seeded(store):
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe", title="CTO")
    store.create_contact("acme", "Max", "Roe")
    return store


def finding(text="Opened a second office", source=SOURCE, kind="trigger",
            confidence="high", date="2026-09-20", **kw) -> Finding:
    return Finding(text=text, source=source, kind=kind, confidence=confidence,
                   date=date, **kw)


def mine(store, contact="jane-doe"):
    return notes.contact_notes(store.get("acme"), contact)


def test_research_note_round_trips(seeded):
    f = finding()
    subject, body = notes.research_note(f)
    assert subject == "Research: acme.example.com"
    assert body == f"Opened a second office\nSource: {SOURCE} (trigger, 2026-09-20, high)"
    note = seeded.create_interaction("acme", "note", "", subject=subject,
                                     contact="jane-doe", body=body)
    back = notes.finding_of(note, TODAY)
    assert (back.text, back.source, back.kind, back.confidence, back.date) == (
        f.text, f.source, f.kind, f.confidence, f.date)


def test_a_note_you_wrote_is_high_confidence_person_and_never_stale(seeded):
    old = FIXED_NOW - timedelta(days=400)
    note = seeded.create_interaction("acme", "note", "", contact="jane-doe", date=old,
                                     body="Met her at a   conference.\nShe prefers calls.")
    f = notes.finding_of(note, TODAY)
    assert f.text == "Met her at a conference. She prefers calls."
    assert (f.source, f.kind, f.confidence, f.stale) == (outreach.YOURS, "person", "high", False)


def test_source_in_the_middle_of_a_note_is_a_plain_note(seeded):
    body = f"Source: {SOURCE} (trigger, 2026-09-20, high)\nbut I wrote this myself"
    note = seeded.create_interaction("acme", "note", "", contact="jane-doe", body=body)
    f = notes.finding_of(note, TODAY)
    assert f.source == outreach.YOURS and "but I wrote this myself" in f.text


def test_a_research_note_goes_stale_by_its_date(seeded):
    subject, body = notes.research_note(finding(date="2026-01-05"))
    note = seeded.create_interaction("acme", "note", "", subject=subject,
                                     contact="jane-doe", body=body)
    assert notes.finding_of(note, TODAY).stale is True


def test_save_findings_skips_low_crm_and_duplicates(seeded):
    found = [finding("Hiring an AE"), finding("Maybe moving", confidence="low"),
             finding("Does X", source="crm", confidence="high"),
             finding("Hiring an AE")]
    assert notes.save_findings(seeded, "acme", "jane-doe", found) == (1, 1)
    assert [n.subject for n in mine(seeded)] == ["Research: acme.example.com"]
    assert notes.save_findings(seeded, "acme", "jane-doe", found) == (0, 1)
    assert len(mine(seeded)) == 1


def test_save_findings_notes_show_on_the_company_timeline(seeded):
    notes.save_findings(seeded, "acme", "jane-doe", [finding()])
    timeline = seeded.get("acme").interactions
    assert [(i.channel, i.contact) for i in timeline] == [("note", "jane-doe")]


def test_snapshot_with_no_notes_is_empty(seeded):
    assert notes.snapshot(seeded.get("acme"), "jane-doe", TODAY) == []


def test_snapshot_keeps_the_newest_twenty_notes(seeded):
    for n in range(25):
        seeded.create_interaction("acme", "note", "", contact="jane-doe", body=f"fact {n}",
                                  date=FIXED_NOW - timedelta(days=30 - n))
    texts = [f.text for f in notes.snapshot(seeded.get("acme"), "jane-doe", TODAY)]
    assert len(texts) == notes.NOTE_COUNT == 20
    assert texts[0] == "fact 24" and "fact 4" not in texts and "fact 5" in texts


def test_snapshot_drops_the_longest_note_first_over_the_character_cap(seeded):
    seeded.create_interaction("acme", "note", "", contact="jane-doe", body="x" * 3900,
                              date=FIXED_NOW - timedelta(days=1))
    for n in range(19):
        seeded.create_interaction("acme", "note", "", contact="jane-doe", body=f"short {n:02d} " + "y" * 90,
                                  date=FIXED_NOW - timedelta(days=2 + n))
    got = notes.snapshot(seeded.get("acme"), "jane-doe", TODAY)
    assert len(got) == 19 and not any(f.text.startswith("xxx") for f in got)
    assert sum(len(f.text) for f in got) <= notes.NOTE_CHARS == 4000


def test_snapshot_is_only_this_contacts_notes(seeded):
    seeded.create_interaction("acme", "note", "", contact="max-roe", body="Max likes golf")
    seeded.create_interaction("acme", "note", "", contact="jane-doe", body="Jane likes tea")
    assert [f.text for f in notes.snapshot(seeded.get("acme"), "jane-doe", TODAY)] == ["Jane likes tea"]


def test_add_note_creates_a_note_on_the_contact_and_company_timeline(seeded):
    note = notes.add_note(seeded, "acme", "jane-doe", "  Hiring a second AE \n")
    assert note.is_note and note.contact == "jane-doe" and note.body.strip() == "Hiring a second AE"
    assert note in seeded.get("acme").interactions


def test_add_note_refuses_empty_text_and_unknown_contacts(seeded):
    with pytest.raises(outreach.OutreachError):
        notes.add_note(seeded, "acme", "jane-doe", "   ")
    with pytest.raises(outreach.OutreachError):
        notes.add_note(seeded, "acme", "nobody", "text")


def test_adopt_saves_legacy_findings_once_and_marks_the_item_linked(seeded):
    item = outreach.Item(id="x", company="acme", contact="jane-doe", state="drafted",
                         findings=[finding("Does X", source="crm"),
                                   finding("Hiring an AE"),
                                   finding("Low one", confidence="low"),
                                   finding("Likes sailing", source=outreach.YOURS,
                                           kind="person", date="2026-10")])
    assert notes.adopt(seeded, item) == 2
    assert item.notes_linked is True
    assert sorted(f.text for f in notes.snapshot(seeded.get("acme"), "jane-doe", TODAY)) == [
        "Hiring an AE", "Likes sailing"]
    assert notes.adopt(seeded, item) == 0


def test_adopt_does_not_bring_back_a_note_deleted_after_the_draft(seeded):
    item = outreach.Item(id="x", company="acme", contact="jane-doe", state="drafted",
                         notes_linked=True, findings=[finding("Hiring an AE")])
    assert notes.adopt(seeded, item) == 0
    assert mine(seeded) == []


def test_card_marks_used_notes_counts_newer_ones_and_lists_legacy(seeded):
    notes.save_findings(seeded, "acme", "jane-doe", [finding("Hiring an AE")])
    company = seeded.get("acme")
    item = outreach.Item(id="x", company="acme", contact="jane-doe", state="drafted",
                         drafted=FIXED_NOW, findings=[
                             finding("Hiring an AE", used=True),
                             finding("Only on the card")])
    seeded.create_interaction("acme", "note", "", contact="jane-doe", body="fresh",
                              date=FIXED_NOW + timedelta(minutes=5))
    card = notes.card(seeded.get("acme"), "jane-doe", item, TODAY)
    by_text = {r["text"]: r for r in card["rows"]}
    assert by_text["Hiring an AE"]["used"] is True and by_text["Hiring an AE"]["source_url"] == SOURCE
    assert by_text["fresh"]["used"] is False and by_text["fresh"]["origin"] == "you"
    assert card["newer"] == 1
    assert [f.text for f in card["legacy"]] == ["Only on the card"]
    company.notes = "Series A last year"
    assert notes.card(company, "jane-doe", item, TODAY)["company_notes"] == "Series A last year"
