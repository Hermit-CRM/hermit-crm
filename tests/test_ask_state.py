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

"""Recent and most-used questions for Ask the Hermit: the uncommitted state in .git and
what the pages and the Ask route do with it."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import ask_saved, ask_state
from hermitcrm.ask_saved import Saved, question_id
from hermitcrm.datafolder import init_folder
from hermitcrm.enrich import Enricher, EnrichError
from hermitcrm.store import load_config
from hermitcrm.web import create_app

NOW = datetime(2026, 10, 26, 9, 30)


@pytest.fixture
def root(store) -> Path:
    (Path(store.root) / ".git").mkdir(exist_ok=True)
    return Path(store.root)


def state_file(root: Path) -> Path:
    return root / ".git" / ask_state.STATE_FILE


# ------------------------------------------------------------------ module


def test_nothing_recorded_is_the_empty_state(root):
    assert ask_state.load(root) == ask_state.State()
    assert not state_file(root).exists()


def test_a_question_asked_is_the_newest_recent_in_the_git_folder(root):
    ask_state.record(root, "Who is silent?", "auto", NOW)
    ask_state.record(root, "Which deals are stuck?", "deep", NOW)
    recent = ask_state.load(root).recent
    assert [(r.text, r.scope, r.at) for r in recent] == [
        ("Which deals are stuck?", "crm", "2026-10-26T09:30"),   # "deep" is the whole CRM too
        ("Who is silent?", "auto", "2026-10-26T09:30")]
    data = json.loads(state_file(root).read_text(encoding="utf-8"))
    assert set(data) == {"recent", "uses"} and data["uses"] == {}
    assert not (root / ask_state.STATE_FILE).exists()   # never a file in the data


def test_the_same_question_again_moves_to_the_front_once(root):
    ask_state.record(root, "Who is silent?", "auto", NOW)
    ask_state.record(root, "Which deals are stuck?", "auto", NOW)
    ask_state.record(root, "  who   is SILENT?  ", "crm", NOW)   # case and spacing: same question
    recent = ask_state.load(root).recent
    assert [r.id for r in recent] == [question_id("Who is silent?"),
                                      question_id("Which deals are stuck?")]
    assert recent[0].text == "who   is SILENT?"   # as last typed
    assert recent[0].scope == "crm"   # the latest ask decides


def test_at_most_twenty_recents_the_oldest_fall_off(root):
    for n in range(25):
        ask_state.record(root, f"Question number {n}?", "auto", NOW)
    recent = ask_state.load(root).recent
    assert len(recent) == ask_state.MAX_RECENT == 20
    assert recent[0].text == "Question number 24?" and recent[-1].text == "Question number 5?"


def test_an_empty_question_is_not_recorded(root):
    ask_state.record(root, "   \n ", "auto", NOW)
    assert not state_file(root).exists()


def test_a_very_long_question_is_kept_cut_to_the_limit(root):
    ask_state.record(root, "x" * 5000, "auto", NOW)
    assert len(ask_state.load(root).recent[0].text) == ask_saved.MAX_TEXT


def test_use_counts_only_for_saved_questions(store, root):
    ask_saved.save(store, "Who is silent?")
    ask_state.record(root, "Who is silent?", "auto", NOW)
    ask_state.record(root, "who is   silent?", "auto", NOW)
    ask_state.record(root, "Not saved?", "auto", NOW)
    assert ask_state.load(root).uses == {question_id("Who is silent?"): 2}


def test_uses_of_a_question_no_longer_saved_are_dropped_on_the_next_write(store, root):
    gone = ask_saved.save(store, "Old?")
    ask_saved.save(store, "Kept?")
    for text in ("Old?", "Kept?", "Kept?"):
        ask_state.record(root, text, "auto", NOW)
    assert ask_state.load(root).uses == {gone.id: 1, question_id("Kept?"): 2}
    ask_saved.remove(store, gone.id)
    ask_state.record(root, "Kept?", "auto", NOW)
    assert ask_state.load(root).uses == {question_id("Kept?"): 3}


def test_saved_are_ranked_by_use_then_newest_first():
    a, b, c, d = (Saved(question_id(t), t) for t in ("Newest?", "Used twice?", "Used once?", "Old?"))
    file_order = [a, b, c, d]
    uses = {b.id: 2, c.id: 1, d.id: 1}
    assert ask_state.ranked(file_order, uses) == [b, c, d, a]   # c before d: the file's order
    assert ask_state.ranked(file_order, {}) == file_order       # no uses: unchanged


def test_recents_that_are_saved_are_left_out(store, root):
    ask_saved.save(store, "Saved one?")
    ask_state.record(root, "Saved one?", "auto", NOW)
    ask_state.record(root, "Unsaved one?", "auto", NOW)
    unsaved = ask_state.unsaved(ask_state.load(root), ask_saved.load(root))
    assert [r.text for r in unsaved] == ["Unsaved one?"]


@pytest.mark.parametrize("content", [
    "not json", "", "[]", '{"recent": 3, "uses": []}', '{"recent": [1, null, {"text": null}]}',
    '{"uses": {"q-zzzzzz": 1, "q-abcdef": -2, "q-abcdea": true, "q-abcdeb": "3"}}',
    b"\xff\xfe\x00"])
def test_a_damaged_file_reads_as_empty_and_never_raises(root, content):
    file = state_file(root)
    file.write_bytes(content if isinstance(content, bytes) else content.encode())
    state = ask_state.load(root)
    assert state.recent == () and state.uses == {}


def test_a_damaged_file_is_replaced_by_the_next_ask(root):
    state_file(root).write_text("{broken", encoding="utf-8")
    ask_state.record(root, "Who is silent?", "auto", NOW)
    assert [r.text for r in ask_state.load(root).recent] == ["Who is silent?"]
    json.loads(state_file(root).read_text(encoding="utf-8"))


def test_hand_edited_rows_are_read_leniently(root):
    state_file(root).write_text(json.dumps({"recent": [
        {"text": "One?", "scope": "weird"}, {"text": " one? "}, {"text": ""}, "x"]}),
        encoding="utf-8")
    recent = ask_state.load(root).recent
    assert [(r.text, r.scope) for r in recent] == [("One?", "auto")]


def test_the_cache_follows_the_file(root):
    ask_state.record(root, "One?", "auto", NOW)
    assert len(ask_state.load(root).recent) == 1
    state_file(root).write_text(json.dumps({"recent": [{"text": "A?"}, {"text": "B?"}]}),
                                encoding="utf-8")
    assert [r.text for r in ask_state.load(root).recent] == ["A?", "B?"]
    state_file(root).unlink()
    assert ask_state.load(root).recent == ()


def test_a_write_that_fails_is_logged_not_raised_and_leaves_no_temp_file(root, monkeypatch, caplog):
    ask_state.record(root, "First?", "auto", NOW)

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ask_state.os, "replace", boom)
    ask_state.record(root, "Second?", "auto", NOW)   # no exception
    assert "could not update" in caplog.text
    assert [r.text for r in ask_state.load(root).recent] == ["First?"]
    assert sorted(p.name for p in (root / ".git").iterdir()) == [ask_state.STATE_FILE]


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


def ask(app, client, question, **data):
    return post(app, client, "/ask", question=question, page="/companies", **data)


def porcelain(folder) -> str:
    return subprocess.run(["git", "status", "--porcelain"], cwd=folder, capture_output=True,
                          text=True, check=True).stdout.strip()


def embedded(page: str) -> dict:
    return json.loads(re.search(r'id="ask-data">(.*?)</script>', page, re.S).group(1))


def test_asking_records_a_recent_and_leaves_git_clean(app_client):
    app, client, folder = app_client
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=folder, capture_output=True,
                          text=True).stdout
    assert ask(app, client, "Who is silent?").status_code == 200
    ask(app, client, "Which deals are stuck?", scope="crm")
    assert [(r.text, r.scope) for r in ask_state.load(folder).recent] == [
        ("Which deals are stuck?", "crm"), ("Who is silent?", "auto")]
    assert state_file(folder).is_file()
    assert porcelain(folder) == ""
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=folder, capture_output=True,
                          text=True).stdout == head   # not a commit either


def test_a_failed_ask_is_still_a_recent(app_client):
    app, client, folder = app_client

    def fail(*a, **k):
        raise EnrichError("the model did not answer in time")
    app.state.enricher = Enricher(provider="claude", which=lambda b: f"/usr/local/bin/{b}",
                                  runner=fail)
    r = ask(app, client, "A long question that took minutes and then failed?")
    assert r.status_code == 502
    assert [x.text for x in ask_state.load(folder).recent] == [
        "A long question that took minutes and then failed?"]


def test_an_empty_ask_is_refused_and_not_recorded(app_client):
    app, client, folder = app_client
    assert ask(app, client, "  ").status_code == 400
    assert ask_state.load(folder).recent == ()


def test_asking_a_saved_question_counts_a_use(app_client):
    app, client, folder = app_client
    post(app, client, "/ask/saved", question="Who is silent?")
    ask(app, client, "who is  silent?")
    ask(app, client, "Who is silent?", scope="deep")
    ask(app, client, "Not saved?")
    assert ask_state.load(folder).uses == {question_id("Who is silent?"): 2}
    assert porcelain(folder) == ""


def test_the_ask_works_when_the_state_cannot_be_written(app_client, monkeypatch, caplog):
    app, client, folder = app_client
    monkeypatch.setattr(ask_state.os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    r = ask(app, client, "Who is silent?")
    assert r.status_code == 200 and "ok" in r.text
    assert "could not update" in caplog.text
    assert not state_file(folder).exists() and porcelain(folder) == ""


def test_a_damaged_state_file_does_not_block_an_ask_or_a_page(app_client):
    app, client, folder = app_client
    state_file(folder).write_text("{broken", encoding="utf-8")
    assert client.get("/companies").status_code == 200
    assert ask(app, client, "Who is silent?").status_code == 200
    assert [r.text for r in ask_state.load(folder).recent] == ["Who is silent?"]


def test_pages_send_the_lists_only_when_there_is_something_to_offer(app_client):
    app, client, folder = app_client
    assert "ask-data" not in client.get("/companies").text   # nothing saved or recent
    ask(app, client, "Who is silent?")
    data = embedded(client.get("/companies").text)
    assert data["saved"] == []
    assert data["recent"] == [{"id": question_id("Who is silent?"), "text": "Who is silent?",
                               "scope": "auto"}]
    assert 'class="ask-saved"' not in client.get("/companies").text   # recents are never chips


def test_a_saved_question_is_not_also_offered_as_recent(app_client):
    app, client, folder = app_client
    ask(app, client, "Who is silent?")
    ask(app, client, "Which deals are stuck?")
    post(app, client, "/ask/saved", question="Who is silent?")
    data = embedded(client.get("/companies").text)
    assert [s["text"] for s in data["saved"]] == ["Who is silent?"]
    assert [r["text"] for r in data["recent"]] == ["Which deals are stuck?"]


def test_the_most_used_come_first_in_the_chips_and_the_embedded_list(app_client):
    app, client, folder = app_client
    for text in ("Alpha?", "Bravo?", "Charlie?", "Delta?", "Echo?"):
        post(app, client, "/ask/saved", question=text)   # file order: Echo, Delta, ... Alpha
    for text in ("Bravo?", "Alpha?", "Bravo?"):
        ask(app, client, text)
    page = client.get("/companies").text
    assert [s["text"] for s in embedded(page)["saved"]] == [
        "Bravo?", "Alpha?", "Echo?", "Delta?", "Charlie?"]
    chips = re.findall(r'data-ask-saved data-starter="([^"]*)"', page)
    assert chips == ["Bravo?", "Alpha?", "Echo?", "Delta?"]   # the top four
    assert "All 5 saved" in page
    # The file itself stays newest first: it is the committed order.
    assert [s.text for s in ask_saved.load(folder)] == [
        "Echo?", "Delta?", "Charlie?", "Bravo?", "Alpha?"]


def test_the_ask_page_lists_by_use_and_says_how_often(app_client):
    app, client, folder = app_client
    post(app, client, "/ask/saved", question="Rarely?")
    post(app, client, "/ask/saved", question="Often?")
    ask(app, client, "Rarely?")
    ask(app, client, "Rarely?")
    page = client.get("/ask?page=/companies").text
    assert page.index("Rarely?</span>") < page.index("Often?</span>")
    assert "asked 2&times;" in page


def test_deleting_a_saved_question_makes_it_a_recent_again(app_client):
    app, client, folder = app_client
    post(app, client, "/ask/saved", question="Who is silent?")
    ask(app, client, "Who is silent?")
    post(app, client, f"/ask/saved/{question_id('Who is silent?')}/delete")
    data = embedded(client.get("/companies").text)
    assert data["saved"] == [] and [r["text"] for r in data["recent"]] == ["Who is silent?"]


def test_a_hostile_recent_cannot_break_out_of_the_page(app_client):
    app, client, folder = app_client
    evil = '</script><img src=x onerror=alert(1)>" \'x\' <!-- &amp;'
    ask(app, client, evil)
    for path in ("/companies", "/ask"):
        page = client.get(path).text
        assert evil not in page and "<img src=x" not in page
        raw = re.search(r'id="ask-data">(.*?)</script>', page, re.S).group(1)
        assert "</script" not in raw and "<" not in raw and "<!--" not in raw
        assert embedded(page)["recent"][0]["text"] == evil   # and it round-trips intact
