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

"""GET /search and /search.json (pages/search.py), on a real folder."""

import re
import subprocess

import pytest


@pytest.fixture
def filled(app):
    store = app.state.store
    store.create_company("Acme GmbH", website="https://acme.example.com", tags=["saas"])
    jane = store.create_contact("acme", "Jane", "Doe", title="CTO",
                                email="jane@acme.example.com")
    store.create_interaction(
        "acme", "email", "out", subject="Quarterly numbers", contact=jane.slug,
        date="2026-09-10T09:00",
        body="Hi Jane,\n\nThe flamingo budget is attached, <b>as promised</b>.")
    store.add_task("acme", "Send the pricing page")
    return app


def commits(app) -> int:
    out = subprocess.run(["git", "rev-list", "--count", "--all"], cwd=app.state.root,
                         capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


def test_the_top_bar_search_box_opens_the_results_page(client):
    page = client.get("/pipeline").text
    form = re.search(r'<form class="search" action="([^"]+)"', page)
    assert form and form.group(1) == "/search"


def test_a_word_only_in_a_message_body_is_found(client, filled):
    r = client.get("/search", params={"q": "flamingo"})
    assert r.status_code == 200
    assert '<a href="/companies/acme/contacts/jane-doe#i-' in r.text
    assert "Quarterly numbers" in r.text
    assert "<mark>flamingo</mark>" in r.text
    # the body's own markup is shown as text, never as HTML
    assert "&lt;b&gt;as promised&lt;/b&gt;" in r.text and "<b>as promised</b>" not in r.text
    assert 'value="flamingo"' in r.text   # the box keeps what was searched


def test_the_page_shows_every_group_that_has_hits(client, filled):
    text = client.get("/search", params={"q": "acme"}).text
    for heading in ("Companies", "Contacts"):
        assert f'id="search-{heading.lower()}-h">{heading}' in text
    # the message is Acme's but does not say "acme": every word in the same record
    assert 'id="search-interactions-h"' not in text and 'id="search-tasks-h"' not in text
    text = client.get("/search", params={"q": "pricing"}).text
    assert 'id="search-tasks-h">Tasks' in text and 'href="/companies/acme#tasks"' in text


def test_no_match_and_empty_query(client, filled):
    r = client.get("/search", params={"q": "zebra unicorn"})
    assert r.status_code == 200 and "Nothing matches" in r.text
    r = client.get("/search")
    assert r.status_code == 200 and "Search finds companies" in r.text


def test_show_all_opens_one_group_with_more_rows(client, app):
    for n in range(11):
        app.state.store.create_company(f"Harbour {n:02}")
    text = client.get("/search", params={"q": "harbour"}).text
    assert text.count('<a href="/companies/harbour-') == 8
    assert 'href="/search?q=harbour&amp;only=companies">Show all 11 companies' in text
    text = client.get("/search", params={"q": "harbour", "only": "companies"}).text
    assert text.count('<a href="/companies/harbour-') == 11
    assert "Show all" not in text and 'name="only" value="companies"' in text
    # an unknown group is ignored, not an error
    assert client.get("/search", params={"q": "harbour", "only": "nope"}).status_code == 200


def test_json_for_the_palette(client, filled):
    r = client.get("/search.json", params={"q": "jane"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    data = r.json()
    assert data["q"] == "jane"
    kinds = [g["kind"] for g in data["groups"]]
    assert kinds[:2] == ["contacts", "interactions"]
    contact = data["groups"][0]["hits"][0]
    assert contact["title"] == "Jane Doe"
    assert contact["url"] == "/companies/acme/contacts/jane-doe"
    labels = [a["label"] for a in data["actions"]]
    assert "Log a call with Jane Doe" in labels and labels[-1] == "Ask Hermit: jane"
    empty = client.get("/search.json").json()
    assert empty["groups"] == [] and [a["label"] for a in empty["actions"]][0] == "New company"


def test_every_action_url_is_a_page_that_opens(client, filled):
    data = client.get("/search.json", params={"q": "acme"}).json()
    for action in data["actions"]:
        if action["kind"] == "go":
            path = action["url"].split("#")[0]
            assert client.get(path).status_code == 200, action
    log = next(a for a in data["actions"] if a["label"].startswith("Log a call"))
    form = client.get(log["url"]).text
    assert re.search(r'<option value="call"[^>]*selected', form), "the call is preselected"


def test_search_only_reads(client, filled):
    before = commits(filled)
    for q in ("acme", "flamingo", "pricing", ""):
        client.get("/search", params={"q": q})
        client.get("/search.json", params={"q": q})
    assert commits(filled) == before


def test_the_help_link_on_the_results_page_opens_search_help(client):
    nav = client.get("/search", params={"q": "x"}).text.split("</nav>")[0]
    assert 'href="/help/search"' in nav
    assert client.get("/help/search").status_code == 200
