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


"""Settings > Playbook: one tab per approach, new / duplicate / delete, the
upgrade button, "Draft it from my website or a document" and "Learn my voice"
(proposals, never writes). All names are made up."""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import playbook, textsource
from hermitcrm.datafolder import MESSAGING, init_folder
from hermitcrm.store import load_config
from hermitcrm.web import create_app


def git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=folder, capture_output=True,
                          text=True).stdout


def commits(folder: Path) -> int:
    return int(git(folder, "rev-list", "--count", "HEAD"))


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "crm")


@pytest.fixture
def client(folder: Path) -> TestClient:
    config = {**load_config(folder), "push_enabled": False}
    app = create_app(folder, config)
    app.state.setup_redirected = True
    return TestClient(app, follow_redirects=False)


def token(client):
    return client.app.state.csrf_token


def form(client, **values):
    return {"csrf_token": token(client), "approach": playbook.DEFAULT_APPROACH,
            "name": playbook.DEFAULT_APPROACH, **values}


def fake_ai(client, answer):
    calls = []

    def runner(prompt, schema, tools=None):
        calls.append((prompt, tools))
        return answer

    enricher = client.app.state.enricher
    enricher.provider = type("P", (), {"name": "claude", "no_tools": "--tools \"\""})()
    enricher.error = ""
    enricher.runner = runner
    return calls


def test_page_shows_the_approach_meter_and_what_is_missing(client):
    page = client.get("/settings/playbook")
    assert page.status_code == 200
    assert "0 of 10 parts filled" in page.text and 'value="My approach"' in page.text
    assert "will not use this approach yet" in page.text
    assert 'class="save-bar"' in page.text and "Positive signals" in page.text
    assert 'formaction="/settings/playbook/draft"' in page.text
    # the slow AI buttons say that they are working once clicked (static/busy.js)
    assert 'formaction="/settings/playbook/draft" data-busy="' in page.text
    assert '/static/busy.js' in page.text
    # ... and so does a bar along the top edge: busy.js makes it, style.css draws it
    assert "busy-bar" in client.get("/static/busy.js").text
    assert ".busy-bar" in client.get("/static/style.css").text
    settings = client.get("/settings").text
    assert 'href="/settings/playbook"' in settings and "No approach is ready" in settings


def test_save_writes_one_commit_and_keeps_the_rest(client, folder):
    values = form(client, name="Solar for offices",
                  offer_line="We install solar panels on offices.", icp_industries="property",
                  personas="owner: Facility Manager",
                  section_proof="- A made-up office halved its power bill.",
                  lessons_worked="- Asking about the roof first.")
    before = commits(folder)
    r = client.post("/settings/playbook", data=values)
    assert r.status_code == 303 and r.headers["location"].startswith("/settings/playbook?approach=0")
    assert commits(folder) == before + 1
    assert git(folder, "log", "-1", "--format=%s").strip() == "playbook: Solar for offices"
    assert git(folder, "status", "--porcelain") == ""
    assert [o.name for o in playbook.require_ready(folder)] == ["Solar for offices"]
    page = client.get("/settings/playbook").text
    assert "Ready for the outreach bot." in page and "Asking about the roof first." in page
    # The same form again changes nothing and commits nothing.
    client.post("/settings/playbook", data={**values, "approach": "Solar for offices"})
    assert commits(folder) == before + 1


def test_ranges_offer_the_folders_own_fields(client, folder):
    page = client.get("/settings/playbook").text
    assert "no company fields yet" in page and "Settings &gt; Fields" in page
    (folder / "fields.toml").write_text(
        '[[field]]\nkey = "employees"\nlabel = "Employees"\ntype = "number"\n'
        '[[field]]\nkey = "founded"\ntype = "date"\n', encoding="utf-8")
    client.post("/settings/playbook", data=form(
        client, range_0_field="employees", range_0_min="5", range_0_max="50"))
    assert playbook.load(folder).approaches[0].icp["ranges"] == {"employees": [5, 50]}
    page = client.get("/settings/playbook").text
    assert '<option value="employees" selected>Employees</option>' in page
    assert 'name="range_1_field"' in page            # an empty row to add another
    assert 'value="founded"' not in page             # a date is not a range


def test_not_a_prospect_is_one_box_plus_tags(client):
    page = client.get("/settings/playbook").text
    assert "Reasons a company is not a prospect" in page
    assert "dq_title_present" not in page and 'name="dq_tag_present"' in page


def test_bad_values_are_shown_not_saved(client, folder):
    before = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    r = client.post("/settings/playbook", data=form(client, range_0_field="ae_count",
                                                    range_0_min="90", range_0_max="9"))
    assert r.status_code == 400 and "Not saved" in r.text
    assert 'data-dirty="1"' in r.text and 'value="90"' in r.text
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == before


def test_csrf_is_required(client):
    for path in ("/settings/playbook", "/settings/playbook/draft", "/settings/playbook/voice",
                 "/settings/playbook/new", "/settings/playbook/duplicate",
                 "/settings/playbook/delete"):
        assert client.post(path, data={"offer_line": "x"}).status_code == 403, path


def test_new_duplicate_and_delete(client, folder):
    client.post("/settings/playbook", data=form(client, offer_line="We coach founders.",
                                                lessons_failed="- Long mails."))
    r = client.post("/settings/playbook/new", data={
        "csrf_token": token(client), "name": "Team build-out", "copy_from": "My approach"})
    assert r.status_code == 303 and "approach=1" in r.headers["location"]
    pb = playbook.load(folder)
    twin = pb.approach("Team build-out")
    assert twin.offer_line == "We coach founders." and twin.lessons()["failed"] == "- Long mails."
    r = client.post("/settings/playbook/duplicate", data={
        "csrf_token": token(client), "approach": "Team build-out"})
    assert "approach=2&rename=1" in r.headers["location"]
    assert [o.name for o in playbook.load(folder).approaches] == [
        "My approach", "Team build-out", "Copy of Team build-out"]
    page = client.get("/settings/playbook?approach=2&rename=1").text
    assert 'aria-current="page">Copy of Team build-out' in page
    # The copy's name sits at the top, focused and selected to type over.
    assert 'value="Copy of Team build-out" required autofocus data-select' in page
    client.post("/settings/playbook", data=form(
        client, approach="Copy of Team build-out", name="Scaling", offer_line="x"))
    assert [o.name for o in playbook.load(folder).approaches] == [
        "My approach", "Team build-out", "Scaling"]
    client.post("/settings/playbook", data=form(
        client, approach="Scaling", name="Copy of Team build-out", offer_line="x"))
    client.post("/settings/playbook/delete", data={"csrf_token": token(client),
                                                   "approach": "My approach"})
    assert [o.name for o in playbook.load(folder).approaches] == [
        "Team build-out", "Copy of Team build-out"]
    r = client.post("/settings/playbook/new", data={
        "csrf_token": token(client), "name": "team BUILD-out"})
    assert "Not+created" in r.headers["location"] or "Not%20created" in r.headers["location"]
    assert git(folder, "status", "--porcelain") == ""


def test_the_last_approach_cannot_be_deleted(client, folder):
    before = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    r = client.post("/settings/playbook/delete", data={"csrf_token": token(client),
                                                       "approach": "My approach"})
    assert r.status_code == 303 and "at%20least%20one" in r.headers["location"]
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == before


def test_an_old_playbook_is_upgraded_only_on_request(client, folder):
    (folder / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    git(folder, "commit", "-qam", "old playbook")
    page = client.get("/settings/playbook").text
    assert "Set up MESSAGING.md" in page and 'value="My approach"' in page
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == MESSAGING  # a look changes nothing
    r = client.post("/settings/playbook/upgrade", data={"csrf_token": token(client)})
    assert r.status_code == 303
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == playbook.upgrade_text(MESSAGING)


def test_saving_an_old_playbook_sets_it_up_and_keeps_its_lines(client, folder):
    (folder / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    client.post("/settings/playbook", data=form(client, offer_line="We coach founders."))
    text = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    assert MESSAGING in text and playbook.parse(text).approaches[0].offer_line == "We coach founders."


def test_draft_from_a_website_and_a_file_fills_the_form_and_saves_nothing(
        client, folder, monkeypatch):
    calls = fake_ai(client, {"offer_line": "We translate contracts.", "industries": ["legal"],
                             "proof": ["A made-up firm signed in two languages in a day."]})
    fetched = []
    monkeypatch.setattr(textsource, "read_website",
                        lambda url: fetched.append(url) or "Example Translations, website")
    before = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    r = client.post("/settings/playbook/draft",
                    data=form(client, source_url="translations.example.com",
                              section_why="typed but not saved yet"),
                    files={"source_file": ("deck.txt", b"From the deck", "text/plain")})
    assert r.status_code == 200 and fetched == ["translations.example.com"]
    (prompt, tools), = calls
    assert tools == "" and "From the deck" in prompt and "Example Translations" in prompt
    assert 'value="We translate contracts."' in r.text and "Nothing is saved yet" in r.text
    assert "A made-up firm signed" in r.text
    assert "typed but not saved yet" in r.text  # what was in the form stays
    assert 'data-dirty="1"' in r.text
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == before


def test_draft_says_why_it_could_not_run(client):
    enricher = client.app.state.enricher
    enricher.provider, enricher.error = None, "no AI CLI found"
    r = client.post("/settings/playbook/draft", data=form(client, source_text="text"))
    assert r.status_code == 400 and "no AI CLI found" in r.text
    fake_ai(client, {})
    r = client.post("/settings/playbook/draft", data=form(client),
                    files={"source_file": ("old.doc", b"\xd0\xcf", "application/msword")})
    assert r.status_code == 400 and "old Word files" in r.text


def test_learn_my_voice_from_sent_emails(client, folder):
    store = client.app.state.store
    co = store.create_company(name="Example Bakery")
    store.create_interaction(co.slug, channel="email", direction="out",
                             body="Hi Sam, quick one: who bakes on Sundays? Cheers")
    page = client.get("/settings/playbook").text
    assert "Learn my voice from my sent emails" in page
    calls = fake_ai(client, {"voice": "- Quick, friendly questions."})
    before = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    r = client.post("/settings/playbook/voice", data=form(client, offer_line="kept"))
    assert r.status_code == 200 and "who bakes on Sundays" in calls[0][0]
    assert "- Quick, friendly questions." in r.text and 'value="kept"' in r.text
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == before


def test_welcome_has_the_approach_step(client):
    page = client.get("/welcome").text
    assert "Say what you sell" in page and 'href="/settings/playbook"' in page


def test_a_typo_in_the_address_or_a_broken_file_is_a_message_not_a_500(client):
    fake_ai(client, {"offer_line": "x"})
    r = client.post("/settings/playbook/draft", data=form(client, source_url="https://exa mple.com"))
    assert r.status_code == 400 and "exa mple.com" in r.text
    r = client.post("/settings/playbook/draft", data=form(client),
                    files={"source_file": ("deck.docx", b"PK\x03\x04broken", "application/zip")})
    assert r.status_code == 400 and "not a Word file" in r.text


def test_an_approach_named_with_a_hash_can_be_saved_and_deleted(client, folder):
    r = client.post("/settings/playbook/new", data={"csrf_token": token(client),
                                                    "name": "Training C#"})
    assert r.status_code == 303
    r = client.post("/settings/playbook", data=form(
        client, approach="Training C#", name="Training C#", offer_line="We teach C#."))
    assert r.status_code == 303
    assert playbook.load(folder).approach("Training C#").offer_line == "We teach C#."
    r = client.post("/settings/playbook/delete", data={"csrf_token": token(client),
                                                       "approach": "Training C#"})
    assert r.status_code == 303
    assert [a.name for a in playbook.load(folder).approaches] == ["My approach"]


@pytest.mark.parametrize("name", ["Owner's pitch", "x');alert(1);//", 'Say "hi"',
                                  "a\\b", "R&D <team>"])
def test_the_delete_confirm_is_valid_javascript_for_any_name(client, name):
    made = client.post("/settings/playbook/new",
                       data={"csrf_token": token(client), "name": name})
    assert made.status_code == 303, made.text
    # The page picks an approach by position; the redirect points at the new one.
    page = client.get(made.headers["location"])
    assert page.status_code == 200
    found = re.search(r'<form[^>]*action="/settings/playbook/delete"[^>]*'
                      r'onsubmit="([^"]*)"', page.text)
    assert found, "no Delete form for this approach"
    # The browser decodes the attribute's HTML entities before it runs the JS.
    handler = html.unescape(found.group(1))
    assert handler.startswith("return confirm(") and handler.endswith(")")
    inner = handler[len("return confirm("):-1]
    assert json.loads(inner) == (
        f"Delete the approach {name} and everything in it? It stays in the git history.")
