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

"""Outreach: the research level `none` reads no page and asks no research question;
the draft is written from the notes the contact and company already have. The AI and
the web are fakes; all names are made up."""

from __future__ import annotations

import pytest

from hermitcrm import notes, outreach
from outreach_client import MARA, client, commits, drafted, post, root, fake  # noqa: F401
from outreach_fakes import NOW, FakeAI, ai

CO, PERSON = "lindenhof-data", "mara-keller"


def test_none_is_a_research_level():
    assert "none" in outreach.LEVELS
    assert outreach.research_level({}, "none") == "none"
    assert outreach.research_level({"outreach_research": "none"}) == "none"
    with pytest.raises(outreach.OutreachError, match="scrape, ai-web or none"):
        outreach.research_level({}, "deep")


def test_the_no_research_researcher_reads_nothing_and_finds_nothing(root):
    fake, fetched = FakeAI(), []
    researcher = outreach.researcher_for("none", ai(fake), fetcher=fetched.append,
                                         escalate=True)
    assert type(researcher) is outreach.NoResearcher
    out = researcher.research(object(), object())
    assert out.findings == [] and out.level == "" and out.notes == []
    assert fake.calls == [] and fetched == []


def test_a_build_with_no_research_makes_no_research_call_and_writes_no_notes(client, root, fake):
    before = len(notes.contact_notes(client.app.state.store.get(CO), PERSON))
    response = post(client, "/outreach/build", contact=MARA, back="/outreach", research="none")
    assert response.status_code == 303, response.text
    item = next(i for i in outreach.items(root) if i.record == MARA)
    assert fake.of("research") == []
    assert item.research_level == "" and item.state == "drafted"
    assert len(notes.contact_notes(client.app.state.store.get(CO), PERSON)) == before
    # the draft is still written from the notes that exist: here the company's own
    assert [f.text for f in item.findings] == ["Demo company. Data pipelines for mid-size insurers."]
    assert any(" outreach: research " in line or "outreach: research " in line
               for line in commits(root))


def test_the_research_commit_says_when_no_research_ran(client, root):
    post(client, "/outreach/build", contact=MARA, back="/outreach", research="none")
    [line] = [c for c in commits(root) if c.startswith("outreach: research ")]
    assert "notes only" in line and "(, " not in line


def test_a_gap_note_you_already_have_meets_the_gap_need_without_research(client, root, fake):
    store = client.app.state.store
    store.create_interaction(
        CO, "note", "", subject="Research R04: lindenhof.example.com", contact=PERSON,
        body="Gap: no customer result with a number on the homepage.\n"
             "Source: https://lindenhof.example.com/ (gap, 2026-10-14, medium)")
    (root / "frameworks.toml").write_text(
        '[frameworks.gap-two]\nname = "Gap two"\nsteps = ["Gap"]\nneeds = ["gap"]\n'
        'instructions = "Lead with the gap."\n', encoding="utf-8")
    response = post(client, "/outreach/build", contact=MARA, back="/outreach",
                    research="none")
    assert response.status_code == 303, response.text
    item = next(i for i in outreach.items(root) if i.record == MARA)
    assert fake.of("research") == []
    assert any(f.is_gap and f.usable and not f.stale for f in item.findings)
    assert NOW.year == 2026


def test_the_batch_form_keeps_none(client):
    page = client.get("/outreach", params={"research": "none", "preview": "1"})
    assert page.status_code == 200
    assert '<option value="none" selected>' in page.text


# ------------------------------------------------ when the panel skips research itself


def test_gap_approaches_names_the_ready_approaches_that_need_a_gap(root):
    (root / "frameworks.toml").write_text(
        '[frameworks.gap-two]\nname = "Gap two"\nsteps = ["Gap"]\nneeds = ["gap"]\n'
        'instructions = "Lead with the gap."\n', encoding="utf-8")
    names = [a.name for a in outreach._ready_approaches(root)[0]]
    assert names, "the demo folder has a ready approach"
    assert outreach.gap_approaches(root) == []
    text = (root / "MESSAGING.md").read_text(encoding="utf-8")
    first = names[0]
    marker = f"- name: {first}\n"
    assert marker in text
    (root / "MESSAGING.md").write_text(
        text.replace(marker, marker + "  frameworks:\n    default: gap-two\n", 1),
        encoding="utf-8")
    assert outreach.gap_approaches(root) == [first]


def test_has_fresh_gap_reads_the_notes_only(client):
    store = client.app.state.store
    company = store.get(CO)
    assert outreach.has_fresh_gap(company, PERSON, NOW.date()) is False
    store.create_interaction(
        CO, "note", "", subject="Research R04: lindenhof.example.com", contact=PERSON,
        body="Gap: no customer result with a number.\n"
             "Source: https://lindenhof.example.com/ (gap, 2026-10-14, medium)")
    assert outreach.has_fresh_gap(store.get(CO), PERSON, NOW.date()) is True
    # the same gap, a year later: stale, so research or not it no longer meets the need
    assert outreach.has_fresh_gap(store.get(CO), PERSON, NOW.date().replace(year=2027)) is False


def make_gap_approach(root) -> str:
    """The demo's first ready approach, now with a default framework that needs a gap."""
    (root / "frameworks.toml").write_text(
        '[frameworks.gap-two]\nname = "Gap two"\nsteps = ["Gap"]\nneeds = ["gap"]\n'
        'instructions = "Lead with the gap."\n', encoding="utf-8")
    first = outreach._ready_approaches(root)[0][0].name
    text = (root / "MESSAGING.md").read_text(encoding="utf-8")
    marker = f"- name: {first}\n"
    (root / "MESSAGING.md").write_text(
        text.replace(marker, marker + "  frameworks:\n    default: gap-two\n", 1),
        encoding="utf-8")
    return first


def add_gap(client):
    client.app.state.store.create_interaction(
        CO, "note", "", subject="Research R04: lindenhof.example.com", contact=PERSON,
        body="Gap: no customer result with a number.\n"
             "Source: https://lindenhof.example.com/ (gap, 2026-10-14, medium)")


def research_selected(html: str) -> str:
    import re
    block = re.search(r'<select name="research" id="gen-research">(.*?)</select>', html, re.S)
    return re.search(r'<option value="([^"]+)" selected', block.group(1)).group(1)


def panel(client, **params):
    page = client.get("/outreach", params={"contact": MARA, **params})
    assert page.status_code == 200
    return page.text


def test_the_panel_skips_research_for_a_gap_approach_with_a_gap_on_file(client, root):
    name = make_gap_approach(root)
    add_gap(client)
    html = panel(client, approach=name)
    assert research_selected(html) == "none"
    assert "no page is read: the draft uses the notes below" in html
    assert 'id="gen-gap-warning" hidden' in html


def test_the_panel_leaves_research_alone_without_a_gap_or_for_another_approach(client, root):
    name = make_gap_approach(root)
    assert research_selected(panel(client, approach=name)) == "scrape"    # no gap on file
    add_gap(client)
    assert research_selected(panel(client)) == "scrape"                   # best fit: unknown
    assert research_selected(panel(client, approach="Some other")) == "scrape"


def test_the_panel_warns_when_the_approach_needs_a_gap_nobody_has_noted(client, root):
    name = make_gap_approach(root)
    html = panel(client, approach=name)
    assert 'id="gen-gap-warning" hidden' not in html
    assert "Research cannot find one" in html


def test_a_research_level_in_the_address_wins_over_the_default(client, root):
    name = make_gap_approach(root)
    add_gap(client)
    assert research_selected(panel(client, approach=name, research="scrape")) == "scrape"
    assert research_selected(panel(client, approach=name, refused="1")) == "scrape"


def test_the_panel_hands_the_script_what_it_needs(client, root):
    name = make_gap_approach(root)
    add_gap(client)
    html = panel(client, approach=name)
    assert 'data-gap-ready="1"' in html and "/static/generate.js" in html
    assert name in html.split('data-gap-approaches="', 1)[1].split('"', 1)[0]
