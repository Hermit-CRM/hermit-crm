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

"""The Outreach bot and the notes: research is saved as notes, the draft is
written from the notes, a regenerate reads them again
(docs/superpowers/specs/2026-10-20-outreach-notes-and-drafts-design.md, part C).
The AI is a fake; all names are made up."""

from __future__ import annotations

import re
from datetime import timedelta

from hermitcrm import enrich, notes, outreach
from hermitcrm.outreach import Finding
from outreach_client import MARA, client, commits, drafted, post, query, root, fake  # noqa: F401
from outreach_fakes import NOW, FakeAI, git

CO, PERSON = "lindenhof-data", "mara-keller"


def store_of(client):
    return client.app.state.store


def mara_notes(client):
    return notes.contact_notes(store_of(client).get(CO), PERSON)


def prompt_of(fake, n=-1) -> str:
    return fake.of("draft")[n]["prompt"]


# ------------------------------------------------------------ research -> notes


def test_build_saves_research_findings_as_notes_in_the_research_commit(client, root):
    item = drafted(client, root)
    [note] = mara_notes(client)
    assert note.subject.startswith("Research: ")
    assert "Opened a second office this autumn" in note.body and "\nSource: " in note.body
    assert [f.text for f in item.findings] == ["Opened a second office this autumn"]
    assert all(f.source != "crm" for f in item.findings) and item.notes_linked is True
    research = next(line for line in git(root, "log", "--format=%H %s").splitlines()
                    if " outreach: research " in line)
    sha = research.split()[0]
    files = git(root, "show", "--name-only", "--format=", sha).splitlines()
    assert any(note.id in path for path in files) and any(item.path == path for path in files)


def lows_and_highs(prompt):
    url = re.search(r"--- page (\S+) ---", prompt).group(1)
    return {"findings": [
        {"text": "Opened a second office", "source": url, "kind": "trigger",
         "confidence": "high", "date": "2026-09-20"},
        {"text": "Might be raising", "source": url, "kind": "company",
         "confidence": "low", "date": ""}]}


def test_low_confidence_findings_are_dropped_and_counted_in_a_flag(client, root, fake):
    fake.research = lows_and_highs
    item = drafted(client, root)
    assert [n.body.splitlines()[0] for n in mara_notes(client)] == ["Opened a second office"]
    assert any("1 low-confidence finding not saved as a note" in flag for flag in item.flags)


def test_running_research_twice_writes_each_finding_once(client, root):
    drafted(client, root)
    outreach.skip(store_of(client), outreach.items(root)[0].id, "bad-timing")
    drafted(client, root)
    assert len(mara_notes(client)) == 1


# ------------------------------------------------------------ notes -> the draft


def test_a_note_on_the_contact_reaches_the_prompt_numbered_and_citable(client, root, fake):
    store_of(client).create_interaction(CO, "note", "", contact=PERSON,
                                        body="Mara runs the Hamburg office.")
    item = drafted(client, root)
    assert re.search(r"^\d+\. \[person, high, usable; source you\] Mara runs the Hamburg office\.$",
                     prompt_of(fake), re.M)
    assert any(f.text == "Mara runs the Hamburg office." for f in item.findings)
    assert any(f.used for f in item.findings)


def test_the_company_notes_field_goes_to_the_prompt_as_background_only(client, root, fake):
    store_of(client).update_company(CO, notes="Series A closed in June")
    item = drafted(client, root)
    assert "Company notes: Series A closed in June" in prompt_of(fake)
    assert not re.search(r"^\d+\. .*Series A closed", prompt_of(fake), re.M)
    assert all("Series A" not in f.text for f in item.findings)


def test_a_follow_up_gets_notes_as_background_not_as_findings(client, root, fake):
    store = store_of(client)
    store.create_interaction(CO, "email", "out", subject="Your second office", contact=PERSON,
                             date=NOW - timedelta(days=6), body="A first message.\n")
    store.create_interaction(CO, "note", "", contact=PERSON,
                             body="Mara runs the Hamburg office.\nShe dislikes cold calls.")
    response = post(client, "/outreach/build", contact=MARA, kind="follow-up", back="/outreach")
    assert response.status_code == 303
    [item] = outreach.items(root)
    assert item.findings == []
    assert "She dislikes cold calls." in prompt_of(fake)
    assert not re.search(r"^\d+\. \[", prompt_of(fake), re.M)


# --------------------------------------------------- regenerate and mark ready


def test_regenerate_rebuilds_the_snapshot_from_the_notes_as_they_are_now(client, root, fake):
    item = drafted(client, root)
    store_of(client).create_interaction(CO, "note", "", contact=PERSON,
                                        body="Mara is hiring a CFO.")
    assert post(client, f"/outreach/{item.id}/regenerate").status_code == 303
    assert "Mara is hiring a CFO." in prompt_of(fake)
    assert any(f.text == "Mara is hiring a CFO." for f in outreach.get_item(root, item.id).findings)


def test_a_note_deleted_after_the_draft_stays_deleted_on_regenerate(client, root):
    item = drafted(client, root)
    [note] = mara_notes(client)
    store_of(client).delete_interaction(CO, note.id)
    post(client, f"/outreach/{item.id}/regenerate")
    assert mara_notes(client) == []
    assert outreach.get_item(root, item.id).findings == []


def test_mark_ready_writes_no_summary_note(client, root):
    item = drafted(client, root)
    before = [n.id for n in mara_notes(client)]
    assert post(client, f"/outreach/{item.id}/ready").status_code == 303
    assert outreach.get_item(root, item.id).state == "ready"
    assert [n.id for n in mara_notes(client)] == before
    assert not any(n.body.startswith("Outreach research for") for n in mara_notes(client))


def legacy(client, root, item):
    """The item as an older version wrote it: its own list of findings (the CRM's
    line, one the research found, one you added), no link to notes."""
    item.notes_linked = False
    item.findings = [Finding("Does reporting", "crm", "company", "high"),
                     Finding("Hiring an account executive", "https://lindenhof.example.com/jobs",
                             "trigger", "medium", "2026-10-01"),
                     Finding("Likes sailing", outreach.YOURS, "person", "high", "2026-10")]
    outreach.write_item(root, item)


def test_an_old_item_adopts_its_findings_as_notes_on_regenerate(client, root, fake):
    item = drafted(client, root)
    legacy(client, root, item)
    post(client, f"/outreach/{item.id}/regenerate")
    back = outreach.get_item(root, item.id)
    assert back.notes_linked is True
    texts = {f.text for f in back.findings}
    assert {"Hiring an account executive", "Likes sailing"} <= texts and "Does reporting" not in texts
    assert "Likes sailing" in {n.body.strip() for n in mara_notes(client)}


def test_an_old_item_adopts_its_findings_as_notes_on_mark_ready(client, root):
    item = drafted(client, root)
    legacy(client, root, item)
    post(client, f"/outreach/{item.id}/ready")
    bodies = [n.body for n in mara_notes(client)]
    assert any(b.startswith("Hiring an account executive\nSource: https://lindenhof.example.com/jobs")
               for b in bodies) and "Likes sailing" in {b.strip() for b in bodies}
    assert outreach.get_item(root, item.id).notes_linked is True


def test_an_item_file_without_the_new_keys_still_loads(client, root):
    item = drafted(client, root)
    path = root / item.path
    text = re.sub(r"^notes_linked: true\n", "", path.read_text(), flags=re.M)
    path.write_text(text)
    back = outreach.get_item(root, item.id)
    assert back.notes_linked is False and back.language_pick == ""


# ------------------------------------------------------------------- security


def web_only_answer(prompt):
    if "--- page " in prompt:
        return lows_and_highs(prompt)
    return {"findings": [], "sources": []}


def test_the_web_research_prompt_never_contains_note_text(client, root, fake):
    fake.research = web_only_answer
    store_of(client).create_interaction(CO, "note", "", contact=PERSON,
                                        body="SECRET-NOTE-TEXT she dislikes cold email")
    store_of(client).update_company(CO, notes="SECRET-COMPANY-NOTE")
    response = post(client, "/outreach/build", contact=MARA, research="ai-web", back="/outreach")
    assert response.status_code == 303
    web_calls = [c for c in fake.of("research") if c.get("tools") == enrich.WEB_ONLY]
    assert len(web_calls) == 1
    assert "SECRET" not in web_calls[0]["prompt"]
    assert "SECRET-NOTE-TEXT" in prompt_of(fake)   # the drafter has no tools: it may see it


# ------------------------------------------------------------- the card's panel


def card_html(client, item) -> str:
    page = client.get("/outreach").text
    return re.search(rf'<article class="draft outreach-card" id="item-{re.escape(item.id)}">.*?</article>',
                     page, re.S).group(0)


def test_the_card_lists_the_contacts_notes_and_has_no_findings_panel(client, root):
    item = drafted(client, root)
    [note] = mara_notes(client)
    page = client.get("/outreach").text
    card = card_html(client, item)
    assert "Save findings" not in page and 'name="remove"' not in page
    assert 'class="outreach-findings"' not in page
    assert '<details class="outreach-notes" open>' in card
    assert "Opened a second office this autumn" in card and "<strong>used</strong>" in card
    assert f"/companies/{CO}/contacts/{PERSON}#i-{note.id}" in card


def test_adding_a_note_on_the_card_shows_on_the_contact_and_company_pages(client, root):
    item = drafted(client, root)
    response = post(client, f"/outreach/{item.id}/note", add="  Hiring a  second AE ")
    assert response.status_code == 303 and "Note saved" in query(response)["flash"]
    [mine] = [n for n in mara_notes(client) if "second AE" in n.body]
    assert mine.body.strip() == "Hiring a  second AE"
    assert "Hiring a  second AE" in client.get(f"/companies/{CO}/contacts/{PERSON}").text
    assert "Hiring a  second AE" in client.get(f"/companies/{CO}").text
    assert "Hiring a second AE" in card_html(client, item)   # the card shows it on one line


def test_an_empty_note_is_refused_and_nothing_is_written(client, root):
    item = drafted(client, root)
    before = commits(root)
    response = post(client, f"/outreach/{item.id}/note", add="   ")
    assert "write something" in query(response)["flash"]
    assert commits(root) == before


def test_a_note_written_on_the_contact_page_shows_on_the_card_with_a_regenerate_hint(client, root):
    item = drafted(client, root)
    assert "added since this draft was written" not in card_html(client, item)
    response = post(client, f"/companies/{CO}/interactions", channel="note", contact=PERSON,
                    date="2026-10-16T10:00", body="Mara asked about pricing")
    assert response.status_code == 303
    card = card_html(client, item)
    assert "Mara asked about pricing" in card
    assert "1 note added since this draft was written. Regenerate to use it." in card


def test_the_card_shows_company_notes_read_only(client, root):
    store_of(client).update_company(CO, notes="Series A closed in June")
    card = card_html(client, drafted(client, root))
    assert "Company notes" in card and "Series A closed in June" in card
    assert 'name="company_notes"' not in card


def test_an_old_card_lists_its_unsaved_findings_read_only(client, root):
    item = drafted(client, root)
    legacy(client, root, item)
    card = card_html(client, item)
    assert "Likes sailing" in card and "saved as notes when you regenerate or mark ready" in card
    assert "Does reporting" not in card      # the CRM's own line is not a finding
