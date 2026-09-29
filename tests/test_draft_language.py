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

"""A contact's own draft language: stored in front matter, set on the contact
form, and overridable per page with ?lang= on the drafts form."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm.web import create_app

CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "owner_email": "me@example.com"}
CONTACT = {"first_name": "", "last_name": "", "title": "", "linkedin": "",
           "email": "", "phone": "", "role": "", "notes": ""}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "CRM Test"], cwd=tmp_path,
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "crm@test.local"], cwd=tmp_path,
                   check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    return tmp_path


@pytest.fixture
def client(repo: Path):
    client = TestClient(create_app(repo, config=CONFIG), follow_redirects=False)
    # No country, so the drafts would be English by default.
    client.post("/companies", data={"name": "Acme"})
    client.post("/companies/acme/contacts",
                data={**CONTACT, "first_name": "Jana", "last_name": "Berg"})
    return client


PAGE = "/companies/acme/contacts/jana-berg"
FILE = Path("companies/acme/contacts/jana-berg.md")


def test_no_language_key_until_one_is_set(client, repo):
    assert "language" not in (repo / FILE).read_text()
    assert "Message drafts for Jana (English)" in client.get(PAGE).text


def test_contact_language_saved_and_used_for_drafts(client, repo):
    r = client.post(PAGE, data={**CONTACT, "first_name": "Jana", "last_name": "Berg",
                                "language": "de"})
    assert r.status_code == 303
    assert "language: de" in (repo / FILE).read_text()
    page = client.get(PAGE).text
    assert "Message drafts for Jana (German)" in page
    assert "Hallo Jana," in page
    assert '<option value="de" selected>' in page


def test_clearing_the_language_removes_the_key(client, repo):
    client.post(PAGE, data={**CONTACT, "first_name": "Jana", "last_name": "Berg",
                            "language": "de"})
    client.post(PAGE, data={**CONTACT, "first_name": "Jana", "last_name": "Berg",
                            "language": ""})
    assert "language" not in (repo / FILE).read_text()


def test_page_override_is_not_saved(client, repo):
    page = client.get(PAGE + "?lang=fr").text
    assert "Message drafts for Jana (French)" in page
    assert "Bonjour Jana," in page
    assert "language" not in (repo / FILE).read_text()


def test_unknown_page_override_is_ignored(client):
    assert "Message drafts for Jana (English)" in client.get(PAGE + "?lang=xx").text


def test_company_page_override(client):
    assert "Message drafts for Jana (German)" in \
        client.get("/companies/acme?lang=de").text


def test_new_contact_with_a_language(client, repo):
    client.post("/companies/acme/contacts",
                data={**CONTACT, "first_name": "Luc", "last_name": "Dupont",
                      "language": "FR"})
    assert "language: fr" in (repo / "companies/acme/contacts/luc-dupont.md").read_text()


def test_hand_written_unknown_code_survives_a_form_save(client, repo):
    path = repo / FILE
    path.write_text(path.read_text().replace("role:", "language: sv\nrole:", 1))
    subprocess.run(["git", "commit", "-qam", "hand edit"], cwd=repo, check=True)
    page = client.get(PAGE).text
    assert '<option value="sv" selected>' in page  # offered, so a save keeps it
    assert "Message drafts for Jana (English)" in page  # no Swedish templates
