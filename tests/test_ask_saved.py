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

"""Saved questions for Ask the Hermit: the file, the routes and the pages that offer them."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import ask_saved
from hermitcrm.ask_saved import AskSavedError, Saved, question_id
from hermitcrm.datafolder import init_folder
from hermitcrm.enrich import Enricher
from hermitcrm.store import load_config
from hermitcrm.web import create_app

FILE = ask_saved.SAVED_FILE


def text_of(store) -> str:
    return (Path(store.root) / FILE).read_text(encoding="utf-8")


# ------------------------------------------------------------------ module


def test_nothing_saved_is_an_empty_list(store):
    assert ask_saved.read(store.root) == ([], "")


def test_save_writes_newest_first_in_one_commit(store, messages):
    first = ask_saved.save(store, "Who has no open task?")
    second = ask_saved.save(store, "Which deals are stuck?", "crm")
    assert [s.text for s in ask_saved.load(store.root)] == [
        "Which deals are stuck?", "Who has no open task?"]
    assert second.scope == "crm" and first.scope == "auto"
    assert messages == ['ask: saved question "Who has no open task?"',
                        'ask: saved question "Which deals are stuck?"']
    assert store.take_touched() == [FILE]


def test_the_file_is_valid_toml_with_ids_text_and_scope(store):
    saved = ask_saved.save(store, "Who did I write to this week?", "crm")
    data = tomllib.loads(text_of(store))
    assert data == {"question": [{"id": saved.id, "text": "Who did I write to this week?",
                                  "scope": "crm"}]}
    assert re.fullmatch(r"q-[0-9a-f]{6}", saved.id)


def test_the_same_question_again_changes_nothing(store, messages):
    ask_saved.save(store, "Who is silent?")
    before = text_of(store)
    again = ask_saved.save(store, "  who   is silent?  ")   # case and spacing do not make it new
    assert text_of(store) == before and len(messages) == 1
    assert again.text == "Who is silent?"


def test_the_same_question_with_another_scope_only_changes_the_scope(store, messages):
    ask_saved.save(store, "Who is silent?")
    changed = ask_saved.save(store, "Who is silent?", "crm")
    assert changed.scope == "crm" and len(ask_saved.load(store.root)) == 1
    assert messages[-1] == 'ask: saved question "Who is silent?" now crm'


def test_writes_are_deterministic(store, tmp_path):
    ask_saved.save(store, "One?")
    ask_saved.save(store, "Two?")
    before = text_of(store)
    (Path(store.root) / FILE).unlink()
    ask_saved.save(store, "One?")
    ask_saved.save(store, "Two?")
    assert text_of(store) == before


def test_line_breaks_quotes_and_unicode_survive_a_round_trip(store):
    odd = 'Who said "later"?\nAnd on a \\ path, in Zürich 🙂 or Besançon?'
    saved = ask_saved.save(store, odd)
    assert ask_saved.load(store.root) == [saved]
    assert saved.text == odd


def test_control_characters_are_dropped(store):
    saved = ask_saved.save(store, "Who\x00 is\x7f silent?\r\nAnd who is not?")
    assert saved.text == "Who is silent?\nAnd who is not?"


def test_an_empty_or_huge_question_is_refused(store):
    with pytest.raises(AskSavedError):
        ask_saved.save(store, "  \n ")
    with pytest.raises(AskSavedError):
        ask_saved.save(store, "x" * (ask_saved.MAX_TEXT + 1))
    assert not (Path(store.root) / FILE).exists()


def test_an_unknown_scope_is_auto(store):
    assert ask_saved.save(store, "Who?", "deep").scope == "auto"


def test_the_cap_refuses_one_more(store, monkeypatch):
    monkeypatch.setattr(ask_saved, "MAX_SAVED", 3)
    for n in range(3):
        ask_saved.save(store, f"Question {n}?")
    with pytest.raises(AskSavedError, match="limit"):
        ask_saved.save(store, "One too many?")
    ask_saved.save(store, "Question 1?")   # a duplicate is not one more
    assert len(ask_saved.load(store.root)) == 3


def test_remove_by_id(store, messages):
    keep = ask_saved.save(store, "Keep?")
    gone = ask_saved.save(store, "Drop?")
    ask_saved.remove(store, gone.id)
    assert ask_saved.load(store.root) == [keep]
    assert messages[-1] == 'ask: removed saved question "Drop?"'
    with pytest.raises(AskSavedError, match="already gone"):
        ask_saved.remove(store, gone.id)


def test_edit_keeps_the_place_and_makes_a_new_id(store, messages):
    ask_saved.save(store, "Third?")
    middle = ask_saved.save(store, "Middle?")
    ask_saved.save(store, "First?")
    edited = ask_saved.replace(store, middle.id, "Middle, reworded?", "crm")
    assert [s.text for s in ask_saved.load(store.root)] == [
        "First?", "Middle, reworded?", "Third?"]
    assert edited.id == question_id("Middle, reworded?") != middle.id
    assert messages[-1] == 'ask: edited saved question "Middle, reworded?"'


def test_editing_into_an_existing_question_merges_the_two(store):
    ask_saved.save(store, "Alpha?")
    beta = ask_saved.save(store, "Beta?")
    ask_saved.replace(store, beta.id, "alpha?", "crm")
    assert [s.text for s in ask_saved.load(store.root)] == ["alpha?"]
    assert ask_saved.load(store.root)[0].scope == "crm"


def test_editing_to_the_same_text_writes_nothing(store, messages):
    one = ask_saved.save(store, "Same?")
    ask_saved.replace(store, one.id, "Same?")
    assert len(messages) == 1


def test_a_file_that_cannot_be_read_is_never_overwritten(store):
    path = Path(store.root) / FILE
    path.write_text('[[question]]\ntext = "Mine, with a typo\n', encoding="utf-8")
    saved, error = ask_saved.read(store.root)
    assert saved == [] and FILE in error
    for attempt in (lambda: ask_saved.save(store, "New?"),
                    lambda: ask_saved.remove(store, "q-000000"),
                    lambda: ask_saved.replace(store, "q-000000", "New?")):
        with pytest.raises(AskSavedError, match="cannot be read"):
            attempt()
    assert "Mine, with a typo" in path.read_text(encoding="utf-8")


def test_a_hand_edited_file_is_read_leniently(store):
    (Path(store.root) / FILE).write_text(
        '[[question]]\ntext = "Typed by hand?"\n\n'
        '[[question]]\nid = "q-bad"\ntext = "Typed by hand?"\nscope = "weird"\n\n'
        '[[question]]\ntext = ""\n', encoding="utf-8")
    saved = ask_saved.load(store.root)
    assert saved == [Saved(question_id("Typed by hand?"), "Typed by hand?", "auto")]


def test_the_cache_follows_the_file(store):
    ask_saved.save(store, "One?")
    assert len(ask_saved.load(store.root)) == 1
    (Path(store.root) / FILE).write_text(
        '[[question]]\ntext = "A?"\n[[question]]\ntext = "B?"\n', encoding="utf-8")
    assert [s.text for s in ask_saved.load(store.root)] == ["A?", "B?"]


# --------------------------------------------------------------------- web


@pytest.fixture
def app_client(tmp_path: Path):
    folder = init_folder(tmp_path / "demo", demo=True)
    config = {**load_config(folder), "push_enabled": False, "owner_email": "me@example.com"}
    app = create_app(folder, config)
    app.state.calendar_url = lambda refresh=False: ""
    app.state.enricher = Enricher(provider="claude", which=lambda b: f"/usr/local/bin/{b}",
                                  runner=lambda *a, **k: {"answerable": True, "answer": "ok"})
    return app, TestClient(app, follow_redirects=False), folder


def post(app, client, path, **data):
    return client.post(path, data={"csrf_token": app.state.csrf_token, **data})


def git_subjects(folder) -> list[str]:
    out = subprocess.run(["git", "log", "--format=%s"], cwd=folder, capture_output=True,
                         text=True, check=True).stdout
    return out.splitlines()


def test_save_route_commits_and_answers_json_for_the_page_script(app_client):
    app, client, folder = app_client
    r = client.post("/ask/saved", headers={"accept": "application/json"},
                    data={"csrf_token": app.state.csrf_token, "question": "Who is silent?",
                          "scope": "crm", "page": "/companies"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["saved"]["scope"] == "crm"
    assert body["saved"]["id"] == question_id("Who is silent?")
    assert git_subjects(folder)[0] == 'ask: saved question "Who is silent?"'
    assert subprocess.run(["git", "status", "--porcelain"], cwd=folder, capture_output=True,
                          text=True).stdout.strip() == ""


def test_save_route_needs_the_csrf_token(app_client):
    app, client, folder = app_client
    assert client.post("/ask/saved", data={"question": "x"}).status_code == 403
    assert not (folder / FILE).exists()


def test_save_route_without_the_script_shows_the_ask_page_with_the_question(app_client):
    app, client, folder = app_client
    r = post(app, client, "/ask/saved", question="Who is silent?", page="/companies")
    assert r.status_code == 200
    assert "Saved." in r.text and "Who is silent?" in r.text
    assert (folder / FILE).exists()


def test_save_route_refusal_is_a_400_with_the_reason(app_client):
    app, client, folder = app_client
    r = client.post("/ask/saved", headers={"accept": "application/json"},
                    data={"csrf_token": app.state.csrf_token, "question": " "})
    assert r.status_code == 400 and r.json() == {"ok": False, "error": "Type a question to save."}
    r = post(app, client, "/ask/saved", question=" ", page="/")
    assert r.status_code == 400 and "Type a question to save." in r.text


def test_every_page_offers_the_saved_questions(app_client):
    app, client, folder = app_client
    assert "ask-saved-data" not in client.get("/companies").text   # nothing saved, nothing sent
    post(app, client, "/ask/saved", question="Which deals are stuck?", scope="crm")
    page = client.get("/companies").text
    assert 'id="ask-saved-data"' in page and "Which deals are stuck?" in page
    assert 'data-ask-saved' in page and 'data-target="ask-question"' in page
    assert 'formaction="/ask/saved"' in page and "/static/askbook.js" in page


def test_a_hostile_question_cannot_break_out_of_the_page(app_client):
    app, client, folder = app_client
    evil = '</script><img src=x onerror=alert(1)>" \'x\''
    post(app, client, "/ask/saved", question=evil)
    for path in ("/companies", "/ask"):
        page = client.get(path).text
        assert evil not in page and "<img src=x" not in page
        data = re.search(r'id="ask-saved-data">(.*?)</script>', page, re.S).group(1)
        assert "</script" not in data and "<" not in data


def test_the_ask_page_lists_saved_questions_with_edit_and_delete(app_client):
    app, client, folder = app_client
    post(app, client, "/ask/saved", question="Who is silent?")
    page = client.get("/ask?page=/companies").text
    ident = question_id("Who is silent?")
    assert "Saved questions" in page and "Who is silent?" in page
    assert f'/ask/saved/{ident}/delete' in page and f'/ask/saved/{ident}/edit' in page


def test_the_answer_page_offers_to_save_the_question_asked(app_client):
    app, client, folder = app_client
    r = post(app, client, "/ask", question="Who is silent?", page="/companies")
    assert 'formaction="/ask/saved"' in r.text and "Save this question" in r.text
    post(app, client, "/ask/saved", question="Who is silent?")
    r = post(app, client, "/ask", question="Who is silent?", page="/companies")
    assert "Saved &#10003;" in r.text and "Save this question" not in r.text


def test_delete_and_edit_routes(app_client):
    app, client, folder = app_client
    post(app, client, "/ask/saved", question="Old?")
    old = question_id("Old?")
    r = post(app, client, f"/ask/saved/{old}/edit", text="New?", scope="crm", page="/companies")
    assert r.status_code == 303 and "/ask?page=%2Fcompanies" in r.headers["location"]
    saved = ask_saved.load(folder)
    assert [(s.text, s.scope) for s in saved] == [("New?", "crm")]
    r = post(app, client, f"/ask/saved/{saved[0].id}/delete", page="/companies")
    assert r.status_code == 303 and ask_saved.load(folder) == []
    assert git_subjects(folder)[:2] == ['ask: removed saved question "New?"',
                                        'ask: edited saved question "New?"']
    assert post(app, client, "/ask/saved/not-an-id/delete").status_code == 404


def test_delete_of_a_missing_question_says_so(app_client):
    app, client, folder = app_client
    r = post(app, client, "/ask/saved/q-abcdef/delete", page="/")
    assert r.status_code == 303 and "already%20gone" in r.headers["location"]


def test_an_unreadable_file_is_shown_on_the_ask_page_and_not_overwritten(app_client):
    app, client, folder = app_client
    (folder / FILE).write_text("not [valid toml", encoding="utf-8")
    assert "cannot be read" in client.get("/ask").text
    r = post(app, client, "/ask/saved", question="New?")
    assert r.status_code == 400 and "cannot be read" in r.text
    assert (folder / FILE).read_text(encoding="utf-8") == "not [valid toml"
