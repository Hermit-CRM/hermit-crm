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
a panel (channel, kind, research, signal, language, a note box, the notes the
draft will use); nothing runs until Generate is pressed.
The AI is a fake; all names are made up."""

from __future__ import annotations

import html
import re
from datetime import timedelta

import pytest

from hermitcrm import messaging, notes, outreach
from outreach_client import MARA, client, commits, drafted, post, query, root, fake  # noqa: F401
from outreach_fakes import NOW

CO, PERSON = "lindenhof-data", "mara-keller"
COMPANY_SITE = "https://lindenhof-data.example.com"   # the company's website, as the fixture stores it
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
    assert any(link == COMPANY_SITE for link in links)            # their site, the exact address
    assert any(link.endswith("/insights/") for link in links)     # the LinkedIn insights link


def test_the_panel_offers_a_follow_up_when_the_last_message_went_unanswered(client):
    store_of(client).create_interaction(CO, "email", "out", subject="Hello", contact=PERSON,
                                        date=NOW - timedelta(days=6), body="A first message.\n")
    assert '<option value="follow-up" selected>' in panel_html(client)


def test_a_contact_with_an_open_draft_gets_a_link_to_it_not_a_form(client, root):
    item = drafted(client, root)
    panel = panel_html(client)
    assert f"#item-{item.id}" in panel and 'action="/outreach/build"' not in panel
    assert 'name="note" form="gen-form"' in panel


def test_generate_is_disabled_when_the_ai_cannot_run(client):
    no_ai(client)
    panel = panel_html(client)
    assert re.search(r'<button type="submit"[^>]*data-busy[^>]*disabled', panel)


# ----------------------------------------------------------------- note on the panel


def test_the_panels_add_note_form_adds_a_note_and_returns_to_the_panel(client):
    response = post(client, "/outreach/note", contact=MARA, note="Prefers a call",
                    back=PANEL)
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/outreach?contact={MARA.replace('/', '%2F')}") \
        or response.headers["location"].startswith(PANEL)
    assert "Note saved" in query(response)["flash"]
    assert [n.body.strip() for n in mara_notes(client)] == ["Prefers a call"]
    assert "Prefers a call" in panel_html(client)


def test_the_panels_add_note_form_refuses_an_unknown_contact_and_an_empty_note(client, root):
    before = commits(root)
    assert "unknown" in query(post(client, "/outreach/note", contact=f"{CO}/nobody", note="x",
                                   back=PANEL))["flash"]
    assert "write something" in query(post(client, "/outreach/note", contact=MARA, note="  ",
                                           back=PANEL))["flash"]
    assert commits(root) == before


# ------------------------------------------------------------ signal and note


def test_a_build_with_a_note_and_a_signal_saves_notes_first(client, root, fake):
    response = post(client, "/outreach/build", contact=MARA, back=PANEL, signal="hiring",
                    note="  Loved the reporting demo  ")
    assert response.status_code == 303
    bodies = [n.body.strip() for n in mara_notes(client)]
    assert "Loved the reporting demo" in bodies
    assert "Signal (LinkedIn insights, checked 2026-10-16): hiring." in bodies
    prompt = fake.of("draft")[0]["prompt"]
    assert re.search(r"^\d+\. \[person, high, usable; source you\] Loved the reporting demo$",
                     prompt, re.M)


def test_an_unknown_signal_and_an_empty_note_write_no_notes(client, root):
    post(client, "/outreach/build", contact=MARA, back=PANEL, signal="bogus", note="  ")
    assert all(n.subject.startswith("Research") for n in mara_notes(client))


def test_a_refused_build_writes_no_notes(client, root):
    no_ai(client)
    before = commits(root)
    response = post(client, "/outreach/build", contact=MARA, back=PANEL, signal="hiring",
                    note="Loved the reporting demo")
    assert "Not built" in query(response)["flash"]
    assert mara_notes(client) == [] and commits(root) == before


def test_the_note_box_is_part_of_the_generate_form_and_there_is_no_observation_field(client):
    panel = panel_html(client)
    assert "observation" not in panel.lower()
    assert 'id="gen-form"' in panel and 'name="note" form="gen-form"' in panel
    assert 'formaction="/outreach/note"' in panel


def test_a_note_typed_in_the_panel_is_saved_once_by_generate_and_drafted_from(client, fake):
    post(client, "/outreach/build", contact=MARA, back=PANEL, note="Loved the reporting demo")
    bodies = [n.body.strip() for n in mara_notes(client)]
    assert bodies.count("Loved the reporting demo") == 1
    assert "Loved the reporting demo" in fake.of("draft")[0]["prompt"]


def test_the_panel_calls_a_company_note_company_not_you(client):
    store_of(client).create_interaction(CO, "note", "", body="Won an award in 2025")
    row = re.search(r"<li>Won an award in 2025.*?</li>", panel_html(client), re.S).group(0)
    assert "company" in row and "you" not in row


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
    assert re.search(r'<a class="button ai"[^>]*title="[^"]*not available', page)


def test_the_panel_offers_every_signal(client):
    panel = panel_html(client)
    assert '<option value="declining">headcount decline</option>' in panel


# ------------------------------------------------------------ the approach picker

APPROACHES = ("Founder coaching", "Scaling the sales team")


def best_fit(client) -> str:
    """The approach the engine would pick for Mara with no pick (no AI, no writes)."""
    sel = outreach.select(store_of(client), contacts=[MARA], config=client.app.state.config)
    return sel.picked[0].approach


def test_the_panel_offers_the_playbook_approaches_and_defaults_to_the_best_fit(client):
    picker = re.search(r'<select name="approach".*?</select>', panel_html(client), re.S).group(0)
    assert '<option value="" selected>the best fit for them</option>' in picker
    for name in APPROACHES:
        assert f">{name}</option>" in picker


def test_a_picked_approach_that_fits_shapes_the_draft_and_is_kept_on_the_item(client, root):
    post(client, "/outreach/build", contact=MARA, back=PANEL, approach="Scaling the sales team")
    item = next(i for i in outreach.items(root) if i.record == MARA)
    assert item.approach == "Scaling the sales team"


def test_a_picked_approach_that_does_not_fit_them_is_refused_with_its_reason(client, root, fake):
    """The pick reaches the selection: the approach's ideal customer still applies to the
    named person, so a pick they do not fit builds nothing and says why."""
    assert best_fit(client) == "Scaling the sales team"
    response = post(client, "/outreach/build", contact=MARA, back=PANEL,
                    approach="Founder coaching")
    assert query(response)["refused"] == "1" and "flash" not in query(response)
    panel = panel_html(client, response.headers["location"])
    assert "Not built" in panel and "Founder coaching" in panel and "Nothing to build" not in panel
    assert outreach.items(root) == [] and fake.calls == []


def test_without_a_pick_the_best_fit_decides(client, root):
    expected = best_fit(client)
    post(client, "/outreach/build", contact=MARA, back=PANEL, approach="")
    item = next(i for i in outreach.items(root) if i.record == MARA)
    assert item.approach == expected


def test_an_unknown_approach_builds_nothing_and_says_so(client, root, fake):
    response = post(client, "/outreach/build", contact=MARA, back=PANEL, approach="Selling ice")
    assert "Not built" in query(response)["flash"] and "Selling ice" in query(response)["flash"]
    assert outreach.items(root) == [] and fake.calls == []


def test_the_panels_pick_is_not_carried_into_the_batch_bar(client):
    response = post(client, "/outreach/build", contact=MARA, back=PANEL,
                    approach="Scaling the sales team")
    assert "approach" not in query(response)


# ------------------------------------------------------------- Generate anyway

MISFIT = "Founder coaching"   # wants 0 account executives; Mara's company has 1


def refused(client, **extra):
    return post(client, "/outreach/build", contact=MARA, back=PANEL, approach=MISFIT, **extra)


def test_a_refused_pick_comes_back_to_the_panel_with_your_choices(client, root, fake):
    store_of(client).update_contact(CO, PERSON, linkedin="https://www.linkedin.com/in/mara-example")
    signal = messaging.SIGNALS[1]
    response = refused(client, channel="linkedin", signal=signal, language="de",
                       note="read the site", strong="1")
    q = query(response)
    assert q["refused"] == "1" and q["contact"] == MARA and q["approach"] == MISFIT
    assert (q["channel"], q["signal"], q["language"]) == ("linkedin", signal, "de")
    assert q["note"] == "read the site" and q["strong"] == "1"
    # One warning, not two: the panel's box carries the reason, so no banner is sent.
    assert "flash" not in q
    assert outreach.items(root) == [] and fake.calls == []


def test_the_refused_panel_shows_the_reason_and_generate_anyway(client):
    store_of(client).update_contact(CO, PERSON, linkedin="https://www.linkedin.com/in/mara-example")
    signal = messaging.SIGNALS[1]
    response = refused(client, channel="linkedin", signal=signal, language="de",
                       note="read the site", strong="1")
    panel = panel_html(client, response.headers["location"])
    assert 'name="override" value="1"' in panel and "Generate anyway" in panel
    assert "ae count 1, wants 0" in panel
    assert f'<option value="{MISFIT}" selected>' in panel
    assert '<option value="linkedin" selected>' in panel
    assert f'<option value="{signal}" selected>' in panel
    assert '<option value="de" selected>' in panel
    assert 'value="read the site"' in panel
    assert re.search(r'name="strong" value="1" checked', panel)


def test_the_refusal_is_one_box_at_the_top_of_the_panel(client):
    store_of(client).update_contact(CO, PERSON, linkedin="https://www.linkedin.com/in/mara-example")
    url = refused(client).headers["location"]
    assert client.get(url).text.count("Not built") == 1   # no banner above the panel too
    panel = panel_html(client, url)
    assert panel.count("generate-refusal") == 1
    # above the form and the notes, with its button still wired to the form below
    assert panel.index("generate-refusal") < panel.index('id="gen-form"')
    assert panel.index("generate-refusal") < panel.index("Notes the draft will use")
    assert 'form="gen-form" name="override" value="1"' in panel


def test_generate_anyway_builds_with_a_warning(client, root, fake):
    response = refused(client, note="read the site", override="1")
    assert response.status_code == 303
    item = next(i for i in outreach.items(root) if i.record == MARA)
    assert item.approach == MISFIT
    assert any("ideal customer" in f and "ae count 1, wants 0" in f for f in item.flags)
    assert fake.calls
    assert "read the site" in [n.body.strip() for n in mara_notes(client)]


def test_override_with_nothing_refused_adds_no_warning(client, root):
    post(client, "/outreach/build", contact=MARA, back=PANEL, approach="", override="1")
    item = next(i for i in outreach.items(root) if i.record == MARA)
    assert not any("ideal customer" in f for f in item.flags)


def test_a_forged_override_cannot_lift_do_not_contact(client, root, fake):
    store_of(client).update_company(CO, tags=["demo", "do-not-contact"])
    response = post(client, "/outreach/build", contact=MARA, back=PANEL, approach="",
                    override="1")
    q = query(response)
    assert "tagged do-not-contact" in q["flash"] and "cannot be overridden" in q["flash"]
    assert outreach.items(root) == [] and fake.calls == []
    assert 'name="override"' not in panel_html(client, response.headers["location"])


def test_a_batch_post_ignores_override(client, root):
    post(client, "/outreach/build", where="stage=prospect", limit="1", approach=MISFIT,
         override="1")
    items = outreach.items(root)
    assert all(i.record != MARA for i in items)
    assert not any("ideal customer" in f for i in items for f in i.flags)


def test_a_hostile_note_round_trips_escaped_and_capped(client):
    note = "x&y#<script>" + "a" * 2000
    response = refused(client, note=note)
    panel = panel_html(client, response.headers["location"])
    assert "<script>" not in panel and "&lt;script&gt;" in panel
    tag = re.search(r'<input[^>]*id="gen-note"[^>]*>', panel).group(0)
    value = html.unescape(re.search(r'value="([^"]*)"', tag).group(1))
    assert value.startswith("x&y#<script>") and len(value) <= 1000


def test_a_recently_messaged_contact_gets_the_button_and_the_retry_builds(client, root):
    store_of(client).create_interaction(
        CO, "email", "out", contact=PERSON,
        date=(NOW - timedelta(days=5)).isoformat(timespec="minutes"),
        subject="Hello", body="Hello Mara.\n")
    response = post(client, "/outreach/build", contact=MARA, back=PANEL)
    q = query(response)
    assert q["refused"] == "1" and "flash" not in q
    panel = panel_html(client, response.headers["location"])
    assert "Not built." in panel and "messaged 5 days ago" in panel
    assert 'name="override" value="1"' in panel
    assert outreach.items(root) == []
    post(client, "/outreach/build", contact=MARA, back=PANEL, override="1")
    item = next(i for i in outreach.items(root) if i.record == MARA)
    assert any("messaged 5 days ago" in f and "drafted anyway" in f for f in item.flags)


def test_a_refused_follow_up_comes_back_as_a_follow_up_not_a_first_touch(client, root):
    store = store_of(client)
    store.create_interaction(CO, "email", "out", contact=PERSON,
                             date=(NOW - timedelta(days=10)).isoformat(timespec="minutes"),
                             subject="Hello", body="Hello Mara.\n")
    outreach.write_item(root, outreach.Item(
        id="2026-11-01T0900-email-lindenhof-data-mara-keller", state="skipped",
        kind="follow-up", company=CO, contact=PERSON, created=NOW, body="Hi.\n",
        skip_reason="bad-timing", skipped=NOW - timedelta(days=3)))
    response = post(client, "/outreach/build", contact=MARA, kind="follow-up",
                    back="/outreach?tab=follow-ups")
    q = query(response)
    assert q["refused"] == "1" and "flash" not in q
    assert q["kind"] == "follow-up"
    panel = panel_html(client, response.headers["location"])
    assert "Not built." in panel and "skipped 3 days ago" in panel
    assert '<option value="follow-up" selected>' in panel and 'name="override"' in panel
    post(client, "/outreach/build", contact=MARA, kind="follow-up", override="1",
         back="/outreach?tab=follow-ups")
    item = next(i for i in outreach.items(root) if i.record == MARA and i.state != "skipped")
    assert item.kind == "follow-up"
    assert any("skipped 3 days ago" in f and "drafted anyway" in f for f in item.flags)


def test_the_refused_panel_lists_every_rule_generate_anyway_will_lift(client):
    store_of(client).create_interaction(
        CO, "email", "out", contact=PERSON,
        date=(NOW - timedelta(days=5)).isoformat(timespec="minutes"),
        subject="Hello", body="Hello Mara.\n")
    response = post(client, "/outreach/build", contact=MARA, back=PANEL)
    panel = panel_html(client, response.headers["location"])
    assert "messaged 5 days ago (cooldown 30 days): drafted anyway" in panel
    assert "already messaged before; not a first touch: drafted anyway" in panel
