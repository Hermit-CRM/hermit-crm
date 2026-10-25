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

"""Learning, the web surfaces: the Learning page and its actions, the Reports
blocks, the Outreach page's "Since last time" line, "Followed N lessons" and
reason chips, and the Settings switch. The AI is a fake; names are made up."""

from __future__ import annotations

import html
import json
import re
import tomllib
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from hermitcrm import learning, outreach
from hermitcrm.store import load_config
from hermitcrm.web import create_app
from outreach_fakes import ai as fake_ai
from test_learning import (  # noqa: F401  (fixture and builders)
    APPROACH, ai_body, folder, make, shorter,
)
from test_learning_writes import add, ai, log, shortened_batch


def make_client(root, enricher=None, **config):
    app = create_app(root, {**load_config(root), "push_enabled": False,
                            "owner_name": "Sam Example", **config})
    app.state.setup_redirected = True
    app.state.enricher = enricher or fake_ai()
    return TestClient(app, follow_redirects=False)


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.app.state.csrf_token, **data})


def flash(response) -> str:
    assert response.status_code == 303, response.text[:300]
    match = re.search(r"flash=([^&#]*)", response.headers["location"])
    return unquote(match.group(1)) if match else ""


def text(response) -> str:
    return html.unescape(response.text)


@pytest.fixture
def client(folder):
    return make_client(folder[0])


# ------------------------------------------------------------------ the page


def test_the_page_renders_with_no_data(client):
    page = client.get("/learning")
    assert page.status_code == 200
    body = text(page)
    assert "Learning" in body and "No reviewed draft yet" in body
    assert "No proposal waiting" in body
    assert 'href="/learning"' in client.get("/").text   # the nav link


def test_an_unknown_approach_falls_back_to_the_first(client):
    assert client.get("/learning?approach=Nope").status_code == 200


def test_the_page_renders_with_data(folder):
    root, store = folder
    shortened_batch(root)
    client = make_client(root)
    page = client.get(f"/learning?approach={APPROACH}")
    assert page.status_code == 200
    body = text(page)
    assert "6 reviewed drafts" in body and "phase 0" in body
    assert "Lower the word limit" in body and 'action="/learning/apply"' in body
    assert "6 edited drafts to look at" in body
    assert "Run now" in body and "Write evidence pack" not in body
    assert "Worked" in body and "Still testing" in body and "Retire" in body
    assert "Promote to Worked" in body       # learning.move exists
    # Without a promotion hint from the score, moves sit in More and Retire stays out.
    mores = [m.split("</details>", 1)[0] for m in page.text.split('<details class="row-more">')[1:]]
    assert any("Promote to Worked" in m for m in mores)
    assert not any("Retire" in m for m in mores)


def test_run_now_stores_proposals_and_they_can_be_accepted_or_rejected(folder):
    root, store = folder
    shortened_batch(root)
    enricher, runner = ai({"proposals": [add(["t00", "t01", "t02"])]})
    client = make_client(root, enricher)
    sent = flash(post(client, "/learning/run", approach=APPROACH))
    assert sent.startswith("1 new proposal from 6 cards") and len(runner.calls) == 1
    page = text(client.get(f"/learning?approach={APPROACH}"))
    assert "Cut the warm-up line; open with the finding." in page
    assert 'action="/learning/accept"' in page and 'formaction="/learning/reject"' in page
    (p,) = learning.proposals(root, APPROACH, "pending")
    done = flash(post(client, "/learning/accept", approach=APPROACH, proposal=p.id,
                      text="Cut the warm-up; start with the finding."))
    assert done.startswith("Accepted: Cut the warm-up; start")
    assert learning.lessons(root, APPROACH)[-1].text == "Cut the warm-up; start with the finding."
    assert log(root)[0].startswith("learn: added lesson")
    assert "No proposal waiting" in text(client.get(f"/learning?approach={APPROACH}"))


def test_reject_and_a_stale_accept_become_flashes_not_errors(folder):
    root, store = folder
    shortened_batch(root)
    enricher, _ = ai({"proposals": [add(["t00", "t01", "t02"])]})
    client = make_client(root, enricher)
    post(client, "/learning/run", approach=APPROACH)
    (p,) = learning.proposals(root, APPROACH, "pending")
    assert flash(post(client, "/learning/reject", approach=APPROACH, proposal=p.id)).startswith(
        "Rejected: Cut the warm-up")
    assert learning.proposals(root, APPROACH)[0].status == "rejected"
    assert "no pending proposal" in flash(
        post(client, "/learning/accept", approach=APPROACH, proposal=p.id))


def test_run_without_an_ai_is_a_flash(folder):
    root, store = folder
    shortened_batch(root)
    client = make_client(root)
    client.app.state.enricher = type(client.app.state.enricher)(
        provider="claude", which=lambda binary: None)
    message = flash(post(client, "/learning/run", approach=APPROACH))
    assert message and "Traceback" not in message
    assert not (root / "learning" / "state.json").exists()


def test_run_with_nothing_new_says_so(client):
    assert flash(post(client, "/learning/run", approach=APPROACH)).startswith("Nothing new")


def test_retire_and_move_a_lesson(folder):
    root, store = folder
    client = make_client(root)
    worked, testing = learning.lessons(root, APPROACH)
    assert flash(post(client, "/learning/move", approach=APPROACH, lesson=testing.id,
                      part="worked")).startswith("Moved to Worked")
    assert [x.part for x in learning.lessons(root, APPROACH)] == ["worked", "worked"]
    assert flash(post(client, "/learning/retire", approach=APPROACH,
                      lesson=worked.id)).startswith("Retired: A question")
    assert [x.id for x in learning.lessons(root, APPROACH)] == [testing.id]
    assert "no lesson" in flash(post(client, "/learning/retire", approach=APPROACH,
                                     lesson=worked.id))
    assert "part is one of" in flash(post(client, "/learning/move", approach=APPROACH,
                                          lesson=testing.id, part="bogus"))


def test_apply_a_suggestion_writes_messages_toml(folder):
    root, store = folder
    shortened_batch(root)
    client = make_client(root)
    sigs = learning.signals(store)
    limit = next(s for s in learning.suggestions(store, sigs, {}) if s.kind == "body_max_words")
    message = flash(post(client, "/learning/apply", approach=APPROACH, suggestion=limit.id))
    assert message.startswith("Applied: You shortened 6 of 6 drafts")
    data = tomllib.loads((root / "messages.toml").read_text())
    assert data["outreach"]["email"]["body_max_words"] == limit.proposed
    assert log(root)[0].startswith("learn: email word limit 120")
    assert "no suggestion" in flash(post(client, "/learning/apply", approach=APPROACH,
                                         suggestion="body_max_words-1"))


def test_handoff_writes_the_pack_and_imports_the_answer(folder):
    root, store = folder
    shortened_batch(root)
    client = make_client(root, learning_distill="handoff")
    page = text(client.get(f"/learning?approach={APPROACH}"))
    assert "Write evidence pack" in page and "Run now" not in page and "Import" in page
    assert "No learning/proposals.json yet" in page    # Import is disabled
    assert "learning/evidence-pack.md" in flash(post(client, "/learning/run",
                                                     approach=APPROACH))
    assert (root / "learning" / "evidence-pack.md").exists()
    assert "no learning/proposals.json" in flash(post(client, "/learning/import",
                                                      approach=APPROACH))
    (root / "learning" / "proposals.json").write_text(json.dumps(
        {"proposals": [add(["t00", "t01", "t02"]), add(["t00", "t01", "zz"], text="X y.")]}))
    message = flash(post(client, "/learning/import", approach=APPROACH))
    assert message.startswith("1 new proposal imported") and "Left out: 1" in message
    assert "Cut the warm-up line" in text(client.get(f"/learning?approach={APPROACH}"))


def test_the_actions_need_the_csrf_token(client):
    for path in ("run", "import", "accept", "reject", "retire", "move", "apply"):
        assert client.post(f"/learning/{path}", data={"approach": APPROACH}).status_code == 403


# ------------------------------------------------------------------- reports


def test_reports_show_the_style_profile_and_outreach_quality(folder):
    root, store = folder
    shortened_batch(root)
    for n in range(6):
        make(root, 10 + n, n, state="sent", days=9)
    client = make_client(root)
    page = client.get("/reports")
    assert page.status_code == 200
    body = text(page)
    assert "Style profile" in body and "Outreach quality" in body
    assert "shortened the text" in body and "too few" in body
    link = re.search(r'href="(/reports/rows\?key=learning\.pattern[^"]*)"', page.text)
    assert link
    rows = client.get(html.unescape(link.group(1)))
    assert rows.status_code == 200 and "Lindenhof" in rows.text
    quality = re.search(r'href="(/reports/rows\?key=learning\.rate(?::|%3A)persona[^"]*)"', page.text)
    assert quality and client.get(html.unescape(quality.group(1))).status_code == 200


def test_reports_without_outreach_data_still_render(client):
    body = text(client.get("/reports"))
    assert "Style profile" in body and "Nothing sent through the outreach bot yet" in body


# ------------------------------------------------------------ outreach page


def test_the_outreach_page_has_the_since_line_and_followed_lessons(folder):
    root, store = folder
    lid = learning.lessons(root, APPROACH)[0].id
    for n in range(3):
        make(root, n, n, days=5 - n, minutes=5, edits=[(shorter(ai_body("Mara")), "", ())]
             if n == 0 else [])
    make(root, 5, 3, state="drafted", lessons_used=[lid, "L000000"], days=0)
    client = make_client(root)
    body = text(client.get("/outreach?tab=drafts"))
    assert "Followed 2 lessons" in body
    assert "A question about who closes deals today" in body
    assert "1 since retired or reworded" in body


def test_the_since_line_shows_with_two_batches(folder):
    root, store = folder
    make(root, 0, 0, batch="b1", days=6, edits=[(shorter(ai_body("Mara")), "", ())] * 1)
    make(root, 1, 1, batch="b2", days=1)
    client = make_client(root)
    body = text(client.get("/outreach?tab=ready"))
    assert "Since last time:" in body and "median edit" in body


def test_the_edit_form_offers_reason_chips(folder):
    root, store = folder
    make(root, 0, 0, state="drafted")
    client = make_client(root)
    body = client.get("/outreach?tab=drafts").text
    for tag in outreach.EDIT_TAGS:
        assert f'name="tags" value="{tag}"' in body
    assert f'data-chip-words="{outreach.REASON_CHIP_WORDS}"' in body


def test_chips_are_saved_with_the_edit(folder):
    root, store = folder
    make(root, 0, 0, state="drafted")
    make(root, 1, 1, state="drafted")
    client = make_client(root)
    edited = shorter(ai_body("Mara"))
    response = post(client, "/outreach/t00/check", body=edited, subject="Your second office",
                    note="too long", tags=["too-long", "cliche", "not-a-tag"])
    assert response.status_code == 303
    item = outreach.get_item(root, "t00")
    assert item.edits and item.edits[-1].tags == ["too-long", "cliche"]
    ready = post(client, "/outreach/t01/ready", body=shorter(ai_body("Daan")),
                 subject="Your second office", note="x", tags=["wrong-tone"])
    assert ready.status_code == 303
    assert outreach.get_item(root, "t01").edits[-1].tags == ["wrong-tone"]


# ------------------------------------------------------------------ settings


def test_settings_save_learning_distill(folder):
    root, store = folder
    client = make_client(root)
    page = client.get("/settings")
    assert page.status_code == 200 and 'name="learning_distill"' in page.text
    assert flash(post(client, "/settings/learning", learning_distill="handoff")).startswith(
        "Learning saved: handoff")
    assert load_config(root)["learning_distill"] == "handoff"
    assert 'value="handoff" selected' in client.get("/settings").text
    assert "hermit or handoff" in flash(post(client, "/settings/learning",
                                             learning_distill="telepathy"))
    assert load_config(root)["learning_distill"] == "handoff"
    assert client.post("/settings/learning", data={"learning_distill": "hermit"}
                       ).status_code == 403
