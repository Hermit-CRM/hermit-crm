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


"""Settings > Playbook: the form, the upgrade button and "Draft it from my
website" (a proposal, never a write). All names are made up."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import playbook
from hermitcrm.datafolder import MESSAGING, init_folder
from hermitcrm.store import load_config
from hermitcrm.web import create_app


def git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=folder, capture_output=True,
                          text=True).stdout


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


def test_page_shows_meter_and_what_is_missing(client):
    page = client.get("/settings/playbook")
    assert page.status_code == 200
    assert "0 of 9 parts filled" in page.text and "will not run yet" in page.text
    assert 'action="/settings/playbook/draft"' in page.text
    settings = client.get("/settings").text
    assert 'href="/settings/playbook"' in settings and "not ready" in settings


def test_save_writes_one_commit_and_keeps_the_body(client, folder):
    form = {"csrf_token": token(client), "offer_line": "We install solar panels on offices.",
            "icp_industries": "property", "personas": "owner: Facility Manager",
            "section_proof": "- A made-up office halved its power bill."}
    before = int(git(folder, "rev-list", "--count", "HEAD"))
    r = client.post("/settings/playbook", data=form)
    assert r.status_code == 303
    assert int(git(folder, "rev-list", "--count", "HEAD")) == before + 1
    assert git(folder, "log", "-1", "--format=%s").strip() == "playbook: saved from Settings"
    assert git(folder, "status", "--porcelain") == ""
    text = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    assert all(line in text.splitlines() for line in MESSAGING.splitlines())
    assert playbook.readiness(folder) == []
    page = client.get("/settings/playbook").text
    assert "Ready for the outreach bot." in page
    # The same form again changes nothing and commits nothing.
    client.post("/settings/playbook", data=form)
    assert int(git(folder, "rev-list", "--count", "HEAD")) == before + 1


def test_bad_values_are_shown_not_saved(client, folder):
    before = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    r = client.post("/settings/playbook", data={"csrf_token": token(client),
                                                "icp_fte_min": "90", "icp_fte_max": "9"})
    assert r.status_code == 400 and "Not saved" in r.text
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == before


def test_csrf_is_required(client):
    assert client.post("/settings/playbook", data={"offer_line": "x"}).status_code == 403
    assert client.post("/settings/playbook/draft", data={"source": "x"}).status_code == 403


def test_an_old_playbook_is_upgraded_only_on_request(client, folder):
    (folder / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    git(folder, "commit", "-qam", "old playbook")
    page = client.get("/settings/playbook").text
    assert "Set up MESSAGING.md" in page
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == MESSAGING  # a look changes nothing
    r = client.post("/settings/playbook/upgrade", data={"csrf_token": token(client)})
    assert r.status_code == 303
    upgraded = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    assert upgraded == playbook.upgrade_text(MESSAGING)
    assert git(folder, "log", "-1", "--format=%s").strip().startswith("playbook: ")


def test_draft_fills_the_form_and_saves_nothing(client, folder):
    calls = []

    def runner(prompt, schema, tools=None):
        calls.append(tools)
        return {"offer_line": "We translate contracts.", "industries": ["legal"],
                "proof": ["A made-up firm signed in two languages in a day."]}

    enricher = client.app.state.enricher
    enricher.provider = type("P", (), {"name": "claude", "no_tools": "--tools \"\""})()
    enricher.error = ""
    enricher.runner = runner
    before = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    r = client.post("/settings/playbook/draft",
                    data={"csrf_token": token(client), "source": "Example Translations"})
    assert r.status_code == 200 and calls == [""]
    assert 'value="We translate contracts."' in r.text and "Nothing is saved yet" in r.text
    assert "A made-up firm signed" in r.text
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == before


def test_draft_without_an_ai_says_why(client):
    enricher = client.app.state.enricher
    enricher.provider, enricher.error = None, "no AI CLI found"
    r = client.post("/settings/playbook/draft",
                    data={"csrf_token": token(client), "source": "text"})
    assert r.status_code == 400 and "no AI CLI found" in r.text


def test_welcome_has_the_offer_step(client, folder):
    page = client.get("/welcome").text
    assert "Say what you sell" in page and 'href="/settings/playbook"' in page
