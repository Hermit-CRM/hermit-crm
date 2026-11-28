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

"""Undo from where a change was made: the Undo button under the flash (and in
the toast) and POST /live/undo (pages/live.py)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from conftest import CONFIG, FIXED_NOW
from hermitcrm import history, web
from hermitcrm.pages import live

ROOT = Path(__file__).resolve().parent.parent
FORM = re.compile(r'<form method="post" action="/live/undo" class="flash-undo".*?</form>', re.S)


def git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=folder, check=True, capture_output=True,
                          text=True).stdout.strip()


def commits(folder: Path) -> int:
    return int(git(folder, "rev-list", "--count", "HEAD"))


@pytest.fixture
def folder(repo: Path) -> Path:
    # A first commit of its own: undo refuses the folder's first commit.
    (repo / "README.md").write_text("a folder\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "init: a folder")
    return repo


@pytest.fixture
def now(monkeypatch):
    """The clock undo_offer reads, moved by hand."""
    t = {"now": 1000.0}
    monkeypatch.setattr(live, "clock", lambda: t["now"])
    return t


@pytest.fixture
def client(folder: Path, now) -> TestClient:
    app = web.create_app(folder, config=CONFIG)
    app.state.store.clock = lambda: FIXED_NOW
    client = TestClient(app, follow_redirects=False)
    client.app.state.store.create_company("Acme Tools", stage="prospect")
    return client


def undo_form(page: str) -> dict:
    """The fields of the page's Undo form, or {} when it has none."""
    found = FORM.search(page)
    if not found:
        return {}
    return dict(re.findall(r'name="(\w+)" value="([^"]*)"', found.group(0)))


REFERER = {"referer": "http://testserver/pipeline"}   # as a browser sends after a form


def follow(client: TestClient, response) -> str:
    assert response.status_code == 303, response.text
    return client.get(response.headers["location"], headers=REFERER).text


def press_undo(client: TestClient, fields: dict):
    return client.post("/live/undo", data=fields)


def flash_of(location: str) -> str:
    return parse_qs(urlparse(location).query).get("flash", [""])[0]


# ---------------------------------------------------------------- the stage


def test_a_stage_move_comes_back_with_undo_in_two_commits(client, folder):
    store = client.app.state.store
    before = commits(folder)
    page = follow(client, client.post("/companies/acme-tools/stage",
                                      data={"stage": "engaged", "back": "/pipeline"}))
    assert store.get("acme-tools").stage == "engaged"
    fields = undo_form(page)
    # The move has no flash of its own: the page says in plain words what was done.
    assert '<p class="flash">Stage prospect → engaged.</p>' in page
    assert fields["sha"] == git(folder, "rev-parse", "--short=10", "HEAD")
    assert fields["back"] == "/pipeline"
    assert fields["csrf_token"] == client.app.state.csrf_token

    r = press_undo(client, fields)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/pipeline?flash=")
    assert flash_of(r.headers["location"]) == "Undone: Stage prospect → engaged."
    assert store.get("acme-tools").stage == "prospect"
    assert commits(folder) == before + 2          # the move and its undo
    assert git(folder, "log", "-1", "--format=%s").startswith('Revert "company: acme-tools')
    assert git(folder, "status", "--porcelain") == ""

    # The undo is a commit too, so its own page offers to undo it.
    again = undo_form(client.get(r.headers["location"]).text)
    assert again["sha"] == git(folder, "rev-parse", "--short=10", "HEAD")
    r = press_undo(client, again)
    assert store.get("acme-tools").stage == "engaged"
    assert flash_of(r.headers["location"]).startswith("Undone: Undone: Stage")
    assert commits(folder) == before + 3


# ------------------------------------------------------- a deleted interaction


def test_a_deleted_interaction_comes_back_byte_for_byte(client, folder):
    store = client.app.state.store
    body = "First line  \n\n\tindented with a tab\r\nlast line, no newline é"
    it = store.create_interaction("acme-tools", "email", "out", subject="Proposal",
                                  body=body)
    path = next((folder / "companies" / "acme-tools" / "interactions").glob("*.md"))
    original = path.read_bytes()
    before = commits(folder)

    r = client.post(f"/companies/acme-tools/interactions/{it.id}/delete",
                    headers={"referer": "http://testserver/companies/acme-tools"})
    assert flash_of(r.headers["location"]) == "Interaction deleted"
    page = client.get(r.headers["location"]).text
    assert not path.exists()
    fields = undo_form(page)
    assert fields["back"] == "/companies/acme-tools"

    r = press_undo(client, fields)
    assert r.headers["location"].startswith("/companies/acme-tools?flash=")
    assert flash_of(r.headers["location"]) == "Undone: Interaction deleted."
    assert path.read_bytes() == original
    assert commits(folder) == before + 2
    assert [i.body for i in store.get("acme-tools").interactions] == [it.body]


def test_the_delete_confirm_says_it_can_be_undone():
    macros = (ROOT / "src/hermitcrm/templates/macros.html").read_text(encoding="utf-8")
    assert "confirm('Delete this interaction? You can take it back with Undo right after.')" \
        in macros


# ------------------------------------------------------------ when it shows


def test_under_a_flash_undo_lasts_two_minutes(client, now):
    store = client.app.state.store
    it = store.create_interaction("acme-tools", "email", "out", subject="Hello")
    r = client.post(f"/companies/acme-tools/interactions/{it.id}/delete")
    url = r.headers["location"]
    assert undo_form(client.get(url).text)          # a reload still has it
    assert undo_form(client.get(url).text)
    now["now"] += live.UNDO_WINDOW - 1
    assert undo_form(client.get(url).text)
    now["now"] += 2
    page = client.get(url).text
    assert '<p class="flash">Interaction deleted</p>' in page and not undo_form(page)


def test_without_a_flash_only_the_next_page_and_only_soon(client, now):
    client.post("/companies/acme-tools/stage", data={"stage": "engaged", "back": "/pipeline"})
    assert undo_form(client.get("/pipeline", headers=REFERER).text)
    assert not undo_form(client.get("/pipeline", headers=REFERER).text)     # shown once
    client.post("/companies/acme-tools/stage", data={"stage": "prospect", "back": "/pipeline"})
    now["now"] += live.FIRST_PAGE
    assert not undo_form(client.get("/pipeline", headers=REFERER).text)      # too late


def test_without_a_flash_a_page_opened_afresh_has_no_undo(client):
    client.post("/companies/acme-tools/stage", data={"stage": "engaged", "back": "/pipeline"})
    first = client.get("/pipeline").text          # typed in, a bookmark: no referer
    assert not undo_form(first) and "Stage prospect" not in first
    assert undo_form(client.get("/pipeline", headers=REFERER).text)


def test_an_unrelated_flash_does_not_offer_it(client):
    store = client.app.state.store
    it = store.create_interaction("acme-tools", "email", "out", subject="Hello")
    r = client.post(f"/companies/acme-tools/interactions/{it.id}/delete")
    assert undo_form(client.get(r.headers["location"]).text)
    assert not undo_form(client.get("/pipeline?flash=Copied").text)
    assert not undo_form(client.get("/companies/acme-tools?flash=Copied").text)


def test_no_undo_once_another_commit_came_after_it(client, folder):
    client.post("/companies/acme-tools/stage", data={"stage": "engaged", "back": "/pipeline"})
    (folder / "notes.txt").write_text("an agent's note\n", encoding="utf-8")
    git(folder, "add", "notes.txt")
    git(folder, "commit", "-q", "-m", "ai: a note")
    assert not undo_form(client.get("/pipeline", headers=REFERER).text)


def test_a_save_that_commits_nothing_offers_no_older_undo(client):
    state = client.app.state
    live.record_write(state, "abc1234", "company: acme-tools updated")
    live.record_write(state, None, "company: acme-tools updated")
    assert state.last_write is None


def test_pages_without_a_write_have_no_undo(client):
    client.get("/", headers=REFERER)     # the create in the fixture is shown once here
    assert not undo_form(client.get("/pipeline?flash=Hello").text)
    assert not undo_form(client.get("/companies/acme-tools").text)


# ------------------------------------------------------- refusals and safety


def test_undo_needs_the_csrf_token(client, folder):
    before = commits(folder)
    r = client.post("/live/undo", data={"sha": git(folder, "rev-parse", "HEAD"),
                                        "back": "/"})
    assert r.status_code == 403
    assert commits(folder) == before


def test_a_refusal_shows_undos_own_words(client, folder):
    csrf = client.app.state.csrf_token
    r = client.post("/live/undo", data={"csrf_token": csrf, "sha": "nope", "back": "/pipeline"})
    assert r.headers["location"].startswith("/pipeline?flash=")
    assert flash_of(r.headers["location"]) == "Not undone: nope is not a commit id."

    first = git(folder, "rev-list", "--max-parents=0", "HEAD")
    r = client.post("/live/undo", data={"csrf_token": csrf, "sha": first, "back": "/"})
    assert "is the folder's first commit" in flash_of(r.headers["location"])

    head = git(folder, "rev-parse", "HEAD")
    (folder / "README.md").write_text("edited by hand\n", encoding="utf-8")
    before = commits(folder)
    r = client.post("/live/undo", data={"csrf_token": csrf, "sha": head, "back": "/"})
    assert "changes that are not committed yet: README.md" in flash_of(r.headers["location"])
    assert commits(folder) == before


def test_back_never_leaves_the_site(client, folder):
    csrf = client.app.state.csrf_token
    for back in ("https://example.com/", "//example.com/x", "/\\example.com"):
        r = client.post("/live/undo", data={"csrf_token": csrf, "sha": "nope", "back": back})
        assert urlparse(r.headers["location"]).path == "/", back


def test_undoing_a_create_lands_where_the_record_still_is(client, folder):
    fields = {"csrf_token": client.app.state.csrf_token,
              "sha": git(folder, "rev-parse", "HEAD"),      # "company: acme-tools created"
              "back": "/companies/acme-tools"}
    r = press_undo(client, fields)
    assert urlparse(r.headers["location"]).path == "/companies"
    assert flash_of(r.headers["location"]) == "Undone: Company added."
    assert client.app.state.store.get("acme-tools") is None
    assert client.get(r.headers["location"]).status_code == 200


def test_landing_keeps_a_page_whose_record_is_there(client):
    store = client.app.state.store
    assert live.landing(store, "/pipeline?country=DE") == "/pipeline?country=DE"
    assert live.landing(store, "/companies/acme-tools") == "/companies/acme-tools"
    assert live.landing(store, "/companies/gone") == "/companies"
    assert live.landing(store, "/companies/acme-tools/contacts/nobody") == "/companies/acme-tools"
    assert live.landing(store, "/companies/acme-tools/interactions/x/edit") \
        == "/companies/acme-tools"


# ------------------------------------------------------------------ words


@pytest.mark.parametrize("subject, words", [
    ("company: acme stage prospect -> won", "Stage prospect → won"),
    ("company: acme stage lead -> won; stage rule overridden", "Stage lead → won"),
    ("company: acme created", "Company added"),
    ("company: acme updated", "Company details changed"),
    ("company: acme next step done", "Next step done"),
    ("contact: acme/ines-vega deleted", "Contact ines-vega deleted"),
    ("interaction: acme deleted 2026-09-14-email", "Interaction deleted"),
    ("interaction: acme Email out Ines Vega 2026-09-14T10:30", "Logged: Email out Ines Vega"),
    ("task: acme/ines done", "Task done"),
    ("ai: company acme enriched", "Company acme enriched"),
    ('Revert "company: acme created"', "Undone: Company added"),
    ("outreach: notes acme/x from research", "Outreach: notes acme/x from research"),
])
def test_plain_subject(subject, words):
    assert history.plain_subject(subject) == words


def test_by_agent():
    assert history.by_agent("ai: company acme enriched")
    assert not history.by_agent("company: acme updated")


# ---------------------------------------------------------------- the toast


def test_the_toast_takes_the_undo_form_from_the_answer():
    js = (ROOT / "src/hermitcrm/static/live.js").read_text(encoding="utf-8")
    assert 'doc.querySelector("main form.flash-undo")' in js
    assert "function toast(text, undo)" in js
    assert "toast(message, undo" in js
    assert 'undo.setAttribute("data-live", "")' in js
    base = (ROOT / "src/hermitcrm/templates/base.html").read_text(encoding="utf-8")
    assert FLASH_LINE in base.splitlines()


# The one line of base.html this feature changed (coordinator-approved): the
# Undo form right after the flash, inside the same {% if flash %}.
FLASH_LINE = ('  {% if flash %}<p class="flash">{{ flash }}</p>'
              '{% if undo_write %}{% include "undo_form.html" %}{% endif %}{% endif %}')


def test_a_flash_without_undo_write_renders_without_the_form(client):
    # The page as every route renders it, with no write to offer ...
    client.app.state.last_write = None    # the fixture's own "created"
    page = client.get("/pipeline?flash=Hello", headers=REFERER).text
    assert '<p class="flash">Hello</p>' in page and not undo_form(page)
    # ... and the line on its own, where undo_write is not defined at all.
    line = client.app.state.templates.env.from_string(FLASH_LINE.strip())
    assert line.render(flash="Hello") == '<p class="flash">Hello</p>'
    assert line.render() == ""


def test_a_flash_with_undo_write_renders_the_form_right_after_it(client):
    line = client.app.state.templates.env.from_string(FLASH_LINE.strip())
    html = line.render(flash="Task done", csrf_token="t0k3n",
                       undo_write={"sha": "abc1234", "back": "/tasks", "message": "Task done"})
    assert html.startswith('<p class="flash">Task done</p><form method="post" '
                           'action="/live/undo" class="flash-undo"')
    assert undo_form(html) == {"csrf_token": "t0k3n", "sha": "abc1234", "back": "/tasks"}
    # Without a flash there is no form, even with undo_write set.
    assert line.render(flash="", undo_write={"sha": "abc1234"}) == ""
