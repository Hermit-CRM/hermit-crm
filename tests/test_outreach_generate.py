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

"""Generate outreach for one contact: /outreach?contact=<company>/<contact> opens
a panel (channel, kind, research, signal, observation, language, the notes the
draft will use); nothing runs until Generate is pressed
(docs/superpowers/specs/2026-10-20-outreach-notes-and-drafts-design.md, part B).
The AI is a fake; all names are made up."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest

from hermitcrm import notes, outreach
from outreach_client import MARA, client, commits, drafted, post, query, root, fake  # noqa: F401
from outreach_fakes import NOW

CO, PERSON = "lindenhof-data", "mara-keller"
PANEL = f"/outreach?contact={MARA}"


def store_of(client):
    return client.app.state.store


def mara_notes(client):
    return notes.contact_notes(store_of(client).get(CO), PERSON)


def panel_html(client, url=PANEL) -> str:
    page = client.get(url).text
    return re.search(r'<section id="generate".*?</section>', page, re.S).group(0)


def no_ai(client):
    client.app.state.enricher = outreach.default_enricher({"enrich_provider": "none"})


# ------------------------------------------------------------------- the panel


def test_the_contact_param_renders_the_panel_and_writes_nothing(client, root, fake):
    before = commits(root)
    response = client.get(PANEL)
    assert response.status_code == 200
    panel = panel_html(client)
    assert "Generate for Mara" in panel
    assert 'action="/outreach/build"' in panel and f'name="contact" value="{MARA}"' in panel
    assert commits(root) == before and fake.calls == []


@pytest.mark.parametrize("value", ["", "nonsense", f"{CO}/nobody", "nobody/mara-keller",
                                   "a/b/c", "../../etc/passwd", f"{CO}/"])
def test_a_malformed_or_unknown_contact_param_renders_no_panel(client, root, fake, value):
    before = commits(root)
    response = client.get("/outreach", params={"contact": value})
    assert response.status_code == 200 and 'id="generate"' not in response.text
    assert commits(root) == before and fake.calls == []


def test_the_panel_preselects_the_draft_type_channel_and_language_and_lists_the_notes(client):
    store_of(client).create_interaction(CO, "note", "", contact=PERSON, body="Mara runs the Hamburg office.")
    panel = panel_html(client)
    assert '<option value="first-touch" selected>' in panel
    assert '<option value="email" selected>' in panel
    assert "German" in re.search(r'<select name="language".*?</select>', panel, re.S).group(0)
    assert "Mara runs the Hamburg office." in panel
    links = re.findall(r'href="([^"]+)"', panel)
    assert "https://lindenhof-data.example.com" in links          # their site, the exact address
    assert any(link.endswith("/insights/") for link in links)     # the LinkedIn insights link


def test_the_panel_offers_a_follow_up_when_the_last_message_went_unanswered(client):
    store_of(client).create_interaction(CO, "email", "out", subject="Hello", contact=PERSON,
                                        date=NOW - timedelta(days=6), body="A first message.\n")
    assert '<option value="follow-up" selected>' in panel_html(client)


def test_a_contact_with_an_open_draft_gets_a_link_to_it_not_a_form(client, root):
    item = drafted(client, root)
    panel = panel_html(client)
    assert f"#item-{item.id}" in panel and 'name="observation"' not in panel


def test_generate_is_disabled_when_the_ai_cannot_run(client):
    no_ai(client)
    panel = panel_html(client)
    assert re.search(r'<button type="submit"[^>]*data-busy[^>]*disabled', panel)


# ----------------------------------------------------------------- note on the panel


def test_the_panels_add_note_form_adds_a_note_and_returns_to_the_panel(client):
    response = post(client, "/outreach/note", contact=MARA, text="Prefers a call",
                    back=PANEL)
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/outreach?contact={MARA.replace('/', '%2F')}") \
        or response.headers["location"].startswith(PANEL)
    assert "Note saved" in query(response)["flash"]
    assert [n.body.strip() for n in mara_notes(client)] == ["Prefers a call"]
    assert "Prefers a call" in panel_html(client)


def test_the_panels_add_note_form_refuses_an_unknown_contact_and_an_empty_note(client, root):
    before = commits(root)
    assert "unknown" in query(post(client, "/outreach/note", contact=f"{CO}/nobody", text="x",
                                   back=PANEL))["flash"]
    assert "write something" in query(post(client, "/outreach/note", contact=MARA, text="  ",
                                           back=PANEL))["flash"]
    assert commits(root) == before


# ------------------------------------------------------- signal and observation


def test_a_build_with_an_observation_and_a_signal_saves_notes_first(client, root, fake):
    response = post(client, "/outreach/build", contact=MARA, back=PANEL, signal="hiring",
                    observation="  Loved the reporting demo  ")
    assert response.status_code == 303
    bodies = [n.body.strip() for n in mara_notes(client)]
    assert "Loved the reporting demo" in bodies
    assert "Signal (LinkedIn insights, checked 2026-10-16): hiring." in bodies
    prompt = fake.of("draft")[0]["prompt"]
    assert re.search(r"^\d+\. \[person, high, usable; source you\] Loved the reporting demo$",
                     prompt, re.M)


def test_an_unknown_signal_and_an_empty_observation_write_no_notes(client, root):
    post(client, "/outreach/build", contact=MARA, back=PANEL, signal="bogus", observation="  ")
    assert all(n.subject.startswith("Research") for n in mara_notes(client))


def test_a_refused_build_writes_no_notes(client, root):
    no_ai(client)
    before = commits(root)
    response = post(client, "/outreach/build", contact=MARA, back=PANEL, signal="hiring",
                    observation="Loved the reporting demo")
    assert "Not built" in query(response)["flash"]
    assert mara_notes(client) == [] and commits(root) == before


# ------------------------------------------------------------------- language


def test_a_picked_language_applies_to_the_draft_and_its_regenerate(client, root, fake):
    post(client, "/outreach/build", contact=MARA, back=PANEL, language="fr")
    item = next(i for i in outreach.items(root) if i.record == MARA)
    assert item.language_pick == "fr" and item.language == "fr"
    assert "Language: French." in fake.of("draft")[0]["prompt"]
    assert store_of(client).get(CO).contacts[PERSON].language == ""   # the record is unchanged
    post(client, f"/outreach/{item.id}/regenerate")
    assert "Language: French." in fake.of("draft")[-1]["prompt"]
    assert outreach.get_item(root, item.id).language == "fr"


def test_without_a_pick_the_language_is_the_companys_and_a_bad_pick_is_ignored(client, root, fake):
    post(client, "/outreach/build", contact=MARA, back=PANEL, language="xx")
    item = next(i for i in outreach.items(root) if i.record == MARA)
    assert item.language_pick == "" and item.language == "de"
    assert "Language: German." in fake.of("draft")[0]["prompt"]


def test_the_batch_form_is_unchanged_and_picks_no_language(client, root):
    response = post(client, "/outreach/build", where="stage=prospect", limit="1")
    assert response.status_code == 303
    assert all(i.language_pick == "" for i in outreach.items(root))


# ----------------------------------------------------- the button on the contact page


CONTACT_PAGE = f"/companies/{CO}/contacts/{PERSON}"


def test_the_contact_page_links_to_the_panel(client):
    page = client.get(CONTACT_PAGE).text
    assert f'href="/outreach?contact={MARA}#generate"' in page and "Generate outreach" in page


def test_an_open_draft_turns_the_button_into_open_outreach_draft(client, root):
    item = drafted(client, root)
    page = client.get(CONTACT_PAGE).text
    assert "Open outreach draft" in page and "Generate outreach" not in page
    assert f"/outreach?tab=drafts#item-{item.id}" in page


def test_the_button_says_why_when_the_ai_cannot_run(client):
    no_ai(client)
    page = client.get(CONTACT_PAGE).text
    assert re.search(r'<a class="button"[^>]*title="[^"]*not available', page)


def test_the_panel_offers_every_signal(client):
    panel = panel_html(client)
    assert '<option value="declining">headcount decline</option>' in panel
