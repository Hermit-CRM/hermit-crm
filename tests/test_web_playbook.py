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


"""Settings > Playbook: one tab per offer, new / duplicate / delete, the
upgrade button, "Draft it from my website or a document" and "Learn my voice"
(proposals, never writes). All names are made up."""

from __future__ import annotations

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
    return {"csrf_token": token(client), "offer": playbook.DEFAULT_OFFER,
            "name": playbook.DEFAULT_OFFER, **values}


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


def test_page_shows_the_offer_meter_and_what_is_missing(client):
    page = client.get("/settings/playbook")
    assert page.status_code == 200
    assert "My offer: 0 of 10 parts filled" in page.text
    assert "will not use this offer yet" in page.text
    assert 'class="save-bar"' in page.text and "Positive signals" in page.text
    assert 'formaction="/settings/playbook/draft"' in page.text
    settings = client.get("/settings").text
    assert 'href="/settings/playbook"' in settings and "No offer is ready" in settings


def test_save_writes_one_commit_and_keeps_the_rest(client, folder):
    values = form(client, name="Solar for offices",
                  offer_line="We install solar panels on offices.", icp_industries="property",
                  personas="owner: Facility Manager",
                  section_proof="- A made-up office halved its power bill.",
                  lessons_worked="- Asking about the roof first.")
    before = commits(folder)
    r = client.post("/settings/playbook", data=values)
    assert r.status_code == 303 and r.headers["location"].startswith("/settings/playbook?offer=0")
    assert commits(folder) == before + 1
    assert git(folder, "log", "-1", "--format=%s").strip() == "playbook: Solar for offices"
    assert git(folder, "status", "--porcelain") == ""
    assert [o.name for o in playbook.require_ready(folder)] == ["Solar for offices"]
    page = client.get("/settings/playbook").text
    assert "Ready for the outreach bot." in page and "Asking about the roof first." in page
    # The same form again changes nothing and commits nothing.
    client.post("/settings/playbook", data={**values, "offer": "Solar for offices"})
    assert commits(folder) == before + 1


def test_bad_values_are_shown_not_saved(client, folder):
    before = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    r = client.post("/settings/playbook", data=form(client, icp_fte_min="90",
                                                    icp_fte_max="9"))
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
        "csrf_token": token(client), "name": "Team build-out", "copy_from": "My offer"})
    assert r.status_code == 303 and "offer=1" in r.headers["location"]
    pb = playbook.load(folder)
    twin = pb.offer("Team build-out")
    assert twin.offer_line == "We coach founders." and twin.lessons()["failed"] == "- Long mails."
    r = client.post("/settings/playbook/duplicate", data={
        "csrf_token": token(client), "offer": "Team build-out"})
    assert "offer=2" in r.headers["location"]
    assert [o.name for o in playbook.load(folder).offers] == [
        "My offer", "Team build-out", "Copy of Team build-out"]
    page = client.get("/settings/playbook?offer=2").text
    assert 'aria-current="page">Copy of Team build-out' in page
    client.post("/settings/playbook/delete", data={"csrf_token": token(client),
                                                   "offer": "My offer"})
    assert [o.name for o in playbook.load(folder).offers] == [
        "Team build-out", "Copy of Team build-out"]
    r = client.post("/settings/playbook/new", data={
        "csrf_token": token(client), "name": "team BUILD-out"})
    assert "Not+created" in r.headers["location"] or "Not%20created" in r.headers["location"]
    assert git(folder, "status", "--porcelain") == ""


def test_the_last_offer_cannot_be_deleted(client, folder):
    before = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    r = client.post("/settings/playbook/delete", data={"csrf_token": token(client),
                                                       "offer": "My offer"})
    assert r.status_code == 303 and "at%20least%20one" in r.headers["location"]
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == before


def test_an_old_playbook_is_upgraded_only_on_request(client, folder):
    (folder / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    git(folder, "commit", "-qam", "old playbook")
    page = client.get("/settings/playbook").text
    assert "Set up MESSAGING.md" in page and "My offer: 0 of 10" in page
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == MESSAGING  # a look changes nothing
    r = client.post("/settings/playbook/upgrade", data={"csrf_token": token(client)})
    assert r.status_code == 303
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == playbook.upgrade_text(MESSAGING)


def test_saving_an_old_playbook_sets_it_up_and_keeps_its_lines(client, folder):
    (folder / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    client.post("/settings/playbook", data=form(client, offer_line="We coach founders."))
    text = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    assert MESSAGING in text and playbook.parse(text).offers[0].offer_line == "We coach founders."


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


def test_welcome_has_the_offer_step(client):
    page = client.get("/welcome").text
    assert "Say what you sell" in page and 'href="/settings/playbook"' in page
