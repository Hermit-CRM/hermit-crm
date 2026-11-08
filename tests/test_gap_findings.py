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

"""Value-added prospecting: a finding can be a gap (something the company could
improve), it carries the research rule that found it, and a draft that has a
usable gap to lead with must lead with one. Fictional names only."""

from __future__ import annotations

import pytest

from conftest import FIXED_NOW
from hermitcrm import notes, outreach
from hermitcrm.outreach import Finding

TODAY = FIXED_NOW.date()
SOURCE = "https://acme.example.com/contact"
GOOD = ("Hi Mara,\n\nThe second office this autumn caught my eye.\nWe help founders build "
        "a sales team that sells without them.\nWhere does it hurt most right now: "
        "pipeline, conversion or deal size?\n\nSam")


@pytest.fixture
def seeded(store):
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe", title="CTO")
    return store


def gap(text="The contact form shows no way to book a call", confidence="high",
        date="2026-11-01", rule="r08", **kw) -> Finding:
    return Finding(text=text, source=SOURCE, kind="gap", confidence=confidence, date=date,
                   rule=rule, **kw)


def trigger(**kw) -> Finding:
    return Finding(text="Opened a second office", source="https://acme.example.com/news",
                   kind="trigger", confidence="high", date="2026-10-01", **kw)


# ----------------------------------------------------------------- the kind


def test_gap_is_a_finding_kind():
    assert "gap" in outreach.FINDING_KINDS
    got = Finding.from_dict({"text": "No pricing page", "source": SOURCE, "kind": "gap",
                             "confidence": "high"})
    assert got.kind == "gap"


def test_an_unknown_kind_is_still_a_company_finding():
    got = Finding.from_dict({"text": "x", "source": SOURCE, "kind": "weakness",
                             "confidence": "high"})
    assert got.kind == "company"


def test_a_finding_without_a_rule_is_stored_exactly_as_before():
    assert "rule" not in trigger().to_dict()
    assert gap().to_dict()["rule"] == "r08"


def test_a_stored_rule_is_read_back_lower_case_and_trimmed():
    got = Finding.from_dict({"text": "x", "source": SOURCE, "kind": "gap",
                             "confidence": "high", "rule": " R08 "})
    assert got.rule == "r08"


# ------------------------------------------------------------- as a note


def test_a_gap_note_keeps_its_kind_and_rule(seeded):
    subject, body = notes.research_note(gap())
    assert subject == "Research R08: acme.example.com"
    assert body.endswith(f"Source: {SOURCE} (gap, 2026-11-01, high)")
    note = seeded.create_interaction("acme", "note", "", subject=subject,
                                     contact="jane-doe", body=body)
    back = notes.finding_of(note, TODAY)
    assert (back.kind, back.rule, back.confidence, back.source) == ("gap", "r08", "high", SOURCE)


def test_a_note_titled_by_hand_gives_its_rule(seeded):
    """How the test companies were loaded: 'Research R08: <what the rule checks>'."""
    note = seeded.create_interaction(
        "acme", "note", "", subject="Research R08: Instant booking after the form",
        body=f"Context: only a form, no calendar.\nSource: {SOURCE} (gap, 2026-11-07, high)")
    back = notes.finding_of(note, TODAY)
    assert (back.kind, back.rule) == ("gap", "r08")


def test_a_note_with_another_subject_has_no_rule(seeded):
    subject, body = notes.research_note(trigger())
    note = seeded.create_interaction("acme", "note", "", subject=subject, body=body)
    assert notes.finding_of(note, TODAY).rule == ""


# ----------------------------------------------------- a gap leads the draft


def ctx(findings):
    return outreach.CheckContext(kind="first-touch", channel="email",
                                 rules=outreach.channel_rules("email"), findings=findings)


def answer(used):
    return {"subject": "Your second office", "body": GOOD, "pitch": "",
            "findings_used": list(used), "proof_used": []}


def problems(findings, used):
    return outreach.clean_answer(answer(used), ctx(findings)).problems


def test_a_draft_must_cite_a_usable_gap_when_there_is_one():
    found = problems([trigger(), gap()], used=[1])
    assert any("gap" in p and "finding 2" in p for p in found)


def test_citing_the_gap_passes():
    assert problems([trigger(), gap()], used=[2]) == []
    assert problems([trigger(), gap()], used=[1, 2]) == []


def test_a_low_confidence_gap_does_not_have_to_lead():
    assert problems([trigger(), gap(confidence="low")], used=[1]) == []


def test_a_gap_older_than_the_stale_limit_does_not_have_to_lead():
    assert problems([trigger(), gap(date="2026-01-05", stale=True)], used=[1]) == []


def test_without_any_gap_nothing_changes():
    assert problems([trigger()], used=[1]) == []


def test_a_reply_has_no_findings_and_no_gap_rule():
    reply = outreach.CheckContext(kind=outreach.REPLY, channel="email",
                                  rules=outreach.channel_rules("email"),
                                  findings=[gap()])
    draft = outreach.clean_answer(answer([]), reply)
    assert not any("gap finding" in p for p in draft.problems)
    assert outreach.gap_lead_line(reply) == ""


def test_the_prompt_tells_the_drafter_that_a_gap_leads():
    line = outreach.gap_lead_line(ctx([trigger(), gap()]))
    assert "gap" in line and "2" in line
    assert outreach.gap_lead_line(ctx([trigger()])) == ""
    assert outreach.gap_lead_line(ctx([trigger(), gap(confidence="low")])) == ""


def prompt(findings):
    c = ctx(findings)
    return outreach.draft_prompt("first-touch", outreach.Brief(who="Mara"), c, None, "")


def test_the_draft_prompt_carries_the_gap_line_and_marks_the_kind():
    text = prompt([trigger(), gap()])
    assert "2. [gap, high, usable; source" in text
    assert "A gap leads: open with one of the findings of kind gap (number 2)" in text


def test_the_draft_prompt_has_no_gap_line_without_a_usable_gap():
    assert "A gap leads" not in prompt([trigger()])
    assert "A gap leads" not in prompt([trigger(), gap(confidence="low")])


# -------------------------------------- gaps come from your rules, not the researcher


def test_the_web_researcher_cannot_declare_a_gap():
    kinds = outreach.RESEARCH_SCHEMA["properties"]["findings"]["items"]["properties"]["kind"]
    assert "gap" not in kinds["enum"] and "trigger" in kinds["enum"]


def test_a_gap_in_the_researchers_answer_is_kept_as_a_company_finding():
    raw = [{"text": "No pricing page", "source": SOURCE, "kind": "gap", "confidence": "high",
            "date": "2026-11-01"}]
    kept = outreach.keep_findings(raw, [SOURCE], TODAY)
    assert [f.kind for f in kept] == ["company"]
