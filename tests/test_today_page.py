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

"""The Today queue on Home and on /today (pages/today.py, templates/today.html)."""

from __future__ import annotations

import re
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import today as today_mod
from hermitcrm.web import create_app

from conftest import FIXED_NOW

TODAY = FIXED_NOW.date()
CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "owner_email": "me@example.com",
          "welcome_dismissed": True, "disclaimer_accepted": "2026-09-01T09:00:00"}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for args in (["init", "-b", "main"], ["config", "user.name", "CRM Test"],
                 ["config", "user.email", "crm@test.local"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    return tmp_path


@pytest.fixture
def app(repo: Path):
    return create_app(repo, config=CONFIG, clock=lambda: FIXED_NOW)


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def store(app):
    s = app.state.store
    s.create_company("Acme GmbH", country="DE")
    s.create_contact("acme", "Jane", "Doe", email="jane@acme.example.com")
    return s


def section(page: str) -> str:
    """The Today section of a page."""
    start = page.index('<section class="today" id="next"')
    return page[start:page.index("</section>", start)]


def forms(html: str) -> list[str]:
    return re.findall(r"<form\b.*?</form>", html, re.S)


def test_home_opens_on_the_queue(client, store):
    store.create_interaction("acme", channel="email", direction="in", contact="jane-doe",
                             date=FIXED_NOW - timedelta(days=3), subject="Pricing",
                             body="How much is it?")
    store.add_task("acme", "send the deck", due=TODAY - timedelta(days=2))
    page = client.get("/").text
    queue = section(page)
    assert "What to do now" in queue
    assert queue.index("Replies you owe") < queue.index("Overdue tasks")
    assert "Jane Doe wrote 3 days ago, no reply from you" in queue
    assert "send the deck" in queue and "2 days overdue" in queue
    # the old lists are gone, and so is the pointer to the command line
    assert "What needs doing" not in page and "hermitcrm keep-in-touch" not in page


def test_every_row_form_is_a_plain_post_with_data_live(client, store):
    store.add_task("acme", "send the deck", due=TODAY - timedelta(days=1), contact="jane-doe")
    store.update_company("acme", next_step="phone", next_step_due=TODAY)
    found = forms(section(client.get("/").text))
    assert len(found) == 2
    for form in found:
        assert 'method="post"' in form and "data-live" in form
        assert 'name="csrf_token"' in form and 'name="back" value="/"' in form


def test_done_on_a_row_ticks_the_task_and_comes_back_home(client, store):
    store.add_task("acme", "send the deck", due=TODAY)
    form = forms(section(client.get("/").text))[0]
    action = re.search(r'action="([^"]+)"', form).group(1)
    data = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', form))
    r = client.post(action, data=data)
    assert r.status_code == 303 and r.headers["location"].startswith("/?flash=")
    assert store.companies["acme"].tasks[0].done
    assert "Nothing is waiting" in client.get("/").text


def test_an_empty_queue_names_the_next_dated_task(client, store):
    store.add_task("acme", "quarterly review", due=TODAY + timedelta(days=6))
    queue = section(client.get("/").text)
    assert "Nothing is waiting." in queue
    assert "Next up:" in queue and "quarterly review" in queue
    assert "<ol" not in queue


def test_an_empty_queue_with_nothing_dated_says_so(client, store):
    queue = section(client.get("/").text)
    assert "Nothing is waiting." in queue and "Nothing else is dated either" in queue


def test_home_shows_25_rows_and_show_all_opens_the_rest(client, app):
    store = app.state.store
    for n in range(30):
        company = store.create_company(f"Firm {n:02d}", country="DE")
        store.add_task(company.slug, f"task {n:02d}", due=TODAY - timedelta(days=n + 1))
    home = section(client.get("/").text)
    assert home.count('class="today-row') == 25
    assert 'href="/today?all=1"' in home and "5 more not shown here" in home
    assert '<span class="today-count">30</span>' in home
    everything = section(client.get("/today?all=1").text)
    assert everything.count('class="today-row') == 30
    assert "not shown here" not in everything
    assert 'name="back" value="/today?all=1"' in everything


def test_today_page_is_the_queue_without_the_rest_of_home(client, store):
    store.add_task("acme", "send the deck", due=TODAY)
    r = client.get("/today")
    assert r.status_code == 200
    assert "<title>Today" in r.text
    assert "send the deck" in section(r.text)
    assert "How it is going" not in r.text
    assert 'name="back" value="/today"' in r.text


def test_a_broken_provider_is_named_and_the_rest_shows(client, store, monkeypatch):
    def broken(store, config, today):
        raise ValueError("bad file")
    monkeypatch.setattr(today_mod, "PROVIDERS", [*today_mod.PROVIDERS, broken])
    store.add_task("acme", "send the deck", due=TODAY)
    queue = section(client.get("/").text)
    assert "could not be read (broken)" in queue and "send the deck" in queue


def test_counts_match_the_tasks_page_chips(client, store):
    store.add_task("acme", "one", due=TODAY - timedelta(days=1))
    store.add_task("acme", "two", due=TODAY - timedelta(days=3), contact="jane-doe")
    store.add_task("acme", "three", due=TODAY)
    queue = section(client.get("/").text)
    tasks = client.get("/tasks").text
    overdue = re.search(r'>Overdue <span class="count">(\d+)</span>', tasks).group(1)
    due = re.search(r'>Today <span class="count">(\d+)</span>', tasks).group(1)
    assert re.search(r'Overdue tasks <span class="today-count">(\d+)</span>',
                     queue).group(1) == overdue == "2"
    assert re.search(r'Due today <span class="today-count">(\d+)</span>',
                     queue).group(1) == due == "1"
