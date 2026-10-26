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

"""The date format setting (Settings > Appearance): one format for what the
pages show and what a form takes, ISO everywhere in the files."""

from __future__ import annotations

import re
import tomllib
from urllib.parse import unquote_plus
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import dateformat
from hermitcrm.datafolder import init_folder
from hermitcrm.filters import Column, matches
from hermitcrm.models import ValidationError, parse_date, parse_datetime
from hermitcrm.store import load_config
from hermitcrm.web import create_app


@pytest.fixture(autouse=True)
def iso_again():
    """The chosen style is process-wide: put it back for the next test."""
    yield
    dateformat.set_style("iso")


@pytest.fixture
def app_client(tmp_path: Path):
    folder = init_folder(tmp_path / "demo", demo=True)
    config = {**load_config(folder), "push_enabled": False, "owner_email": "me@example.com"}
    app = create_app(folder, config)
    app.state.calendar_url = lambda refresh=False: ""
    return folder, app, TestClient(app, follow_redirects=False)


def choose(app, client, key: str):
    r = client.post("/settings/date-format", data={"csrf_token": app.state.csrf_token,
                                                    "date_format": key})
    assert r.status_code == 303, r.text
    return r


# ---------------------------------------------------------------- the module


@pytest.mark.parametrize("key,shown", [
    ("iso", "2026-12-31"), ("dmy-dash", "31-12-2026"),
    ("dmy", "31/12/2026"), ("mdy", "12/31/2026"),
])
def test_each_style_formats_and_reads_back(key, shown):
    dateformat.set_style(key)
    day = date(2026, 12, 31)
    assert dateformat.fmt(day) == shown == dateformat.STYLES[key][0]
    assert dateformat.fmt_dt(datetime(2026, 12, 31, 9, 5)) == shown + " 09:05"
    assert dateformat.parse(shown) == day
    assert dateformat.parse_dt(shown + " 9:05") == datetime(2026, 12, 31, 9, 5)
    assert dateformat.parse_dt(shown) == datetime(2026, 12, 31)


def test_an_unknown_style_falls_back_to_iso():
    assert dateformat.set_style("martian") == "iso"
    assert dateformat.set_style(None) == "iso"


def test_models_accept_iso_always_and_the_chosen_style_too():
    dateformat.set_style("dmy")
    assert parse_date("2026-12-01") == date(2026, 12, 1)
    assert parse_date("01/12/2026") == date(2026, 12, 1)
    assert parse_datetime("01/12/2026 14:30") == datetime(2026, 12, 1, 14, 30)
    assert parse_datetime("2026-12-01T14:30") == datetime(2026, 12, 1, 14, 30)
    with pytest.raises(ValidationError, match="DD/MM/YYYY"):
        parse_date("12/31/2026")          # month 31 does not exist
    with pytest.raises(ValidationError):
        parse_datetime("01/12/2026 25:00")


def test_another_styles_text_is_not_guessed_at():
    dateformat.set_style("mdy")
    assert parse_date("12/01/2026") == date(2026, 12, 1)   # December 1st, not Jan 12th
    dateformat.set_style("iso")
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        parse_date("12/01/2026")


def test_filters_read_and_match_dates_the_way_they_are_shown():
    dateformat.set_style("dmy")
    col = Column("due", "due", "date")
    due = date(2026, 12, 1)
    assert matches(col, due, ">30/11/2026") and not matches(col, due, ">01/12/2026")
    assert matches(col, due, "<2026-12-02")                 # ISO still works
    assert matches(col, due, "01/12") and matches(col, due, "2026-12")
    assert matches(col, due, "=01/12/2026") and not matches(col, due, "!2026")


# ------------------------------------------------------------------ the pages


def test_settings_lists_the_formats_and_saves_one(app_client):
    folder, app, client = app_client
    page = client.get("/settings").text
    assert 'action="/settings/date-format"' in page
    for label in ("YYYY-MM-DD", "DD-MM-YYYY", "DD/MM/YYYY", "MM/DD/YYYY"):
        assert label in page
    assert re.search(r'value="iso" checked', page)

    choose(app, client, "dmy")
    assert tomllib.loads((folder / "config.toml").read_text())["date_format"] == "dmy"
    page = client.get("/settings").text
    assert re.search(r'value="dmy" checked', page)
    assert 'data-date-style="dmy"' in page

    bad = client.post("/settings/date-format", data={"csrf_token": app.state.csrf_token,
                                                      "date_format": "martian"})
    assert bad.status_code == 400
    assert tomllib.loads((folder / "config.toml").read_text())["date_format"] == "dmy"


def test_a_config_edit_changes_the_format_after_a_reload(app_client):
    folder, app, client = app_client
    text = (folder / "config.toml").read_text()
    (folder / "config.toml").write_text(text + '\ndate_format = "mdy"\n')
    client.post("/reload")
    assert 'data-date-style="mdy"' in client.get("/tasks").text


def test_no_page_uses_the_browsers_own_date_picker(app_client):
    folder, app, client = app_client
    slug = next(iter(app.state.store.companies))
    for url in ("/tasks", "/reports", "/companies/new", f"/companies/{slug}",
                f"/companies/{slug}/interactions/new"):
        page = client.get(url).text
        assert 'type="date"' not in page and "datetime-local" not in page, url


def test_a_date_typed_in_the_chosen_format_is_stored_as_iso(app_client):
    folder, app, client = app_client
    slug = next(iter(app.state.store.companies))
    choose(app, client, "dmy")

    r = client.post(f"/companies/{slug}/tasks", data={"text": "send the deck",
                                                       "due": "01/12/2026"})
    assert r.status_code == 303
    files = [p for p in folder.rglob("*.md") if "send the deck" in p.read_text()]
    assert files, "the task was not written"
    stored = files[0].read_text()
    assert "2026-12-01" in stored and "01/12/2026" not in stored

    # the same date, shown the way it was chosen, on the page and in the edit field
    tasks = client.get("/tasks").text
    assert "01/12/2026" in tasks and "2026-12-01" not in tasks
    company = client.get(f"/companies/{slug}").text
    assert 'name="due" value="01/12/2026"' in company
    assert 'placeholder="DD/MM/YYYY"' in company

    # ISO is still taken, so a pasted date or an old bookmark works
    r = client.post(f"/companies/{slug}/tasks", data={"text": "iso one", "due": "2026-12-02"})
    assert r.status_code == 303
    assert "02/12/2026" in client.get("/tasks").text


def test_a_bad_date_names_the_format_to_type(app_client):
    folder, app, client = app_client
    slug = next(iter(app.state.store.companies))
    choose(app, client, "mdy")
    r = client.post(f"/companies/{slug}/tasks", data={"text": "x", "due": "31/12/2026"})
    assert r.status_code == 303                     # back to the page, with the reason flashed
    assert "MM/DD/YYYY" in unquote_plus(r.headers["location"])


def test_the_interaction_form_shows_and_takes_date_and_time(app_client):
    folder, app, client = app_client
    slug = next(iter(app.state.store.companies))
    choose(app, client, "dmy-dash")
    page = client.get(f"/companies/{slug}/interactions/new").text
    assert 'placeholder="DD-MM-YYYY HH:MM"' in page
    assert re.search(r'name="date" value="\d\d-\d\d-\d{4} \d\d:\d\d"', page)


def test_reports_period_fields_follow_the_format(app_client):
    folder, app, client = app_client
    choose(app, client, "mdy")
    page = client.get("/reports").text
    assert re.search(r'name="from" value="\d\d/\d\d/\d{4}"', page)
    assert client.get("/reports?period=custom&from=01/01/2026&to=02/01/2026").status_code == 200


def test_every_page_still_renders_in_every_style(app_client):
    folder, app, client = app_client
    slug = next(iter(app.state.store.companies))
    for key in dateformat.STYLES:
        choose(app, client, key)
        for url in ("/", "/pipeline", "/calendar", "/tasks", "/companies", "/contacts",
                    "/messages", "/outreach", "/reports", "/settings", "/yours",
                    f"/companies/{slug}"):
            assert client.get(url, follow_redirects=True).status_code == 200, (key, url)


def test_the_last_touch_line_follows_the_format_but_the_model_text_stays_iso(app_client):
    folder, app, client = app_client
    store = app.state.store
    company = next(c for c in store.companies.values() if c.last_touch)
    iso = company.last_touch_summary
    assert re.search(r"\d{4}-\d\d-\d\d", iso)              # what files and AI text read
    choose(app, client, "dmy")
    page = client.get(f"/companies/{company.slug}").text
    assert re.search(r"last touch: [^<]*\d\d/\d\d/\d{4}", page)
    assert company.last_touch_summary == iso
