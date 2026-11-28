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

"""The history of one company or contact: history.record_history and the
/companies/{slug}/history pages (pages/live.py)."""

from __future__ import annotations

import html
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from conftest import CONFIG, FIXED_NOW
from hermitcrm import history, web


def git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=folder, check=True, capture_output=True,
                          text=True).stdout.strip()


def commit_as_agent(folder: Path, name: str, text: str, message: str) -> None:
    (folder / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-c", "user.name=Agent", "-c", "user.email=agent@example.com",
                    "commit", "-q", "-am", message], cwd=folder, check=True,
                   capture_output=True)


@pytest.fixture
def folder(repo: Path) -> Path:
    (repo / "README.md").write_text("a folder\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "init: a folder")
    return repo


@pytest.fixture
def client(folder: Path) -> TestClient:
    app = web.create_app(folder, config=CONFIG)
    app.state.store.clock = lambda: FIXED_NOW
    store = app.state.store
    store.create_company("Acme Tools", stage="prospect", country="DE")
    store.create_contact("acme-tools", first_name="Ines", last_name="Vega",
                         email="ines@example.com")
    store.update_company("acme-tools", stage="engaged")
    store.create_interaction("acme-tools", "email", "out", subject="Hello",
                             contact="ines-vega", body="Hi Ines")
    store.update_contact("acme-tools", "ines-vega", title="Head of Ops")
    store.create_company("Other Co")              # not Acme's history
    return TestClient(app, follow_redirects=False)


def rows(page: str) -> list[str]:
    body = page.split('<table class="built record-history">')[1].split("</table>")[0]
    return re.findall(r'<tr id="c-[0-9a-f]{7}">(.*?)</tr>', body, re.S)


def text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


# ------------------------------------------------------------- record_history


def test_a_companys_history_is_its_folder_newest_first(client, folder):
    changes, more = history.record_history(folder, ["companies/acme-tools"],
                                           "companies/acme-tools/company.md")
    assert not more
    assert [c.words for c in changes] == [
        "Contact ines-vega changed", "Logged: email out ines-vega",
        "Stage prospect → engaged", "Contact ines-vega added", "Company added"]
    stage = changes[2]
    assert [(f.name, f.before, f.after) for f in stage.fields][:1] == \
        [("stage", "prospect", "engaged")]
    assert all(f.name != "updated" for c in changes for f in c.fields)
    assert changes[-1].added and changes[-1].can_undo
    assert len(changes[1].others) == 1
    assert changes[1].others[0].startswith("Interaction ") \
        and changes[1].others[0].endswith(" added")


def test_a_contacts_history_compares_its_own_file(client, folder):
    main = "companies/acme-tools/contacts/ines-vega.md"
    changes, _ = history.record_history(folder, [main], main)
    assert [c.words for c in changes] == ["Contact ines-vega changed", "Contact ines-vega added"]
    assert [(f.name, f.before, f.after) for f in changes[0].fields] == \
        [("title", "", "Head of Ops")]


def test_a_list_field_shows_the_items_that_came_and_went():
    before = "---\nname: A\ntasks:\n  - {text: Call, due: 2026-09-20}\n---\n"
    after = ("---\nname: A\ntasks:\n  - {text: Call, due: 2026-09-20}\n"
             "  - {text: Send deck}\n---\nNotes\n")
    fields, body = history.field_changes(before, after)
    assert [(f.name, f.before, f.after) for f in fields] == [("tasks", "", "text: Send deck")]
    assert body


def test_paged_at_fifty_with_older(folder):
    path = folder / "companies" / "x.md"
    path.parent.mkdir(exist_ok=True)
    for n in range(7):
        path.write_text(f"---\nn: {n}\n---\n", encoding="utf-8")
        git(folder, "add", "-A")
        git(folder, "commit", "-q", "-m", f"company: x updated {n}")
    first, more = history.record_history(folder, ["companies/x.md"], "companies/x.md",
                                         per_page=3)
    assert more and len(first) == 3 and first[0].fields[0].after == "6"
    last, more = history.record_history(folder, ["companies/x.md"], "companies/x.md",
                                        page=3, per_page=3)
    assert not more and [c.fields[0].after for c in last] == ["0"]
    assert history.PER_PAGE == 50


def test_reverted_and_agent_changes_are_marked(client, folder):
    commit_as_agent(folder, "companies/acme-tools/company.md",
                    (folder / "companies/acme-tools/company.md").read_text(encoding="utf-8")
                    .replace("country: DE", "country: AT"), "ai: company acme-tools enriched")
    agent_sha = git(folder, "rev-parse", "HEAD")
    history.undo(client.app.state.store, agent_sha)
    changes, _ = history.record_history(folder, ["companies/acme-tools"],
                                        "companies/acme-tools/company.md")
    assert changes[0].words == "Undone: Company acme-tools enriched" and changes[0].can_undo
    assert changes[1].agent and changes[1].undone and not changes[1].can_undo
    assert [(f.name, f.before, f.after) for f in changes[1].fields] == [("country", "DE", "AT")]


def test_without_git_there_is_no_history(tmp_path):
    assert history.record_history(tmp_path, ["companies/x"], "companies/x/company.md") \
        == ([], False)


# ------------------------------------------------------------------ the pages


def test_the_company_history_page(client, folder):
    page = client.get("/companies/acme-tools/history")
    assert page.status_code == 200
    found = rows(page.text)
    assert len(found) == 5
    assert "Stage prospect → engaged" in text(found[2])
    assert "stage: prospect → engaged" in text(found[2])
    assert 'action="/live/undo"' in found[2]
    assert 'name="back" value="/companies/acme-tools/history"' in found[2]
    assert '<a href="/companies/acme-tools">' in page.text
    assert "Other Co" not in page.text.split("<h1>")[1]


def test_undo_from_the_history_comes_back_to_it(client, folder):
    store = client.app.state.store
    page = client.get("/companies/acme-tools/history").text
    form = re.findall(r'<form method="post" action="/live/undo" class="inline">.*?</form>',
                      rows(page)[2], re.S)[0]
    fields = dict(re.findall(r'name="(\w+)" value="([^"]*)"', form))
    r = client.post("/live/undo", data=fields)
    location = r.headers["location"]
    assert urlparse(location).path == "/companies/acme-tools/history"
    assert parse_qs(urlparse(location).query)["flash"] == ["Undone: Stage prospect → engaged."]
    assert store.get("acme-tools").stage == "prospect"
    after = rows(client.get(location).text)
    assert "Undone: Stage" in text(after[0])
    assert "undone" in text(after[3]) and 'action="/live/undo"' not in after[3]


def test_the_contact_history_page(client):
    page = client.get("/companies/acme-tools/contacts/ines-vega/history")
    assert page.status_code == 200
    assert "History: Ines Vega (Acme Tools)" in page.text
    found = rows(page.text)
    assert len(found) == 2
    assert "title: empty → Head of Ops" in text(found[0])


def test_an_agent_change_is_marked_on_the_page(client, folder):
    commit_as_agent(folder, "companies/acme-tools/company.md",
                    (folder / "companies/acme-tools/company.md").read_text(encoding="utf-8")
                    .replace("country: DE", "country: AT"), "ai: company acme-tools enriched")
    first = rows(client.get("/companies/acme-tools/history").text)[0]
    assert '<span class="tag"' in first and ">agent</span>" in first


def test_unknown_records_and_pages(client):
    assert client.get("/companies/nobody/history").status_code == 404
    assert client.get("/companies/acme-tools/contacts/nobody/history").status_code == 404
    assert client.get("/companies/acme-tools/history?page=9").status_code == 404
    assert client.get("/companies/acme-tools/history?page=x").status_code == 200


def test_the_record_pages_link_to_their_history(client):
    page = client.get("/companies/acme-tools").text
    assert '<a href="/companies/acme-tools/history">history</a>' in page
    page = client.get("/companies/acme-tools/contacts/ines-vega").text
    assert '<a href="/companies/acme-tools/contacts/ines-vega/history">history</a>' in page
