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

"""The Feedback form: the report a tester can send, and what must never be in it."""

from __future__ import annotations

import html
import re
import subprocess
import urllib.parse
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import feedback
from hermitcrm.datafolder import init_folder
from hermitcrm.store import load_config
from hermitcrm.web import create_app

NOW = datetime(2026, 9, 18, 14, 32)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "crm")


def make_client(folder: Path, **config_overrides):
    config = load_config(folder)
    config["push_enabled"] = False
    config.update(config_overrides)
    app = create_app(folder, config)
    app.state.setup_platform = "linux"
    return app, TestClient(app, follow_redirects=False)


def token(client) -> str:
    page = client.get("/help/feedback").text
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


def send(client, **fields):
    data = {"csrf_token": token(client), "kind": "bug", "summary": "It broke",
            "detail": "I pressed the button.", "reporter": ""}
    data.update(fields)
    return client.post("/help/feedback", data=data)


# ------------------------------------------------------------- the pure parts


def test_report_is_markdown_with_front_matter_and_the_facts():
    text = feedback.report("bug", "  Sorting  looked   wrong  ", "Twice.\n",
                           reporter="Robin Vale <robin@example.org>",
                           facts=["Hermit CRM 0.3.0 on Python 3.13 (Linux)"],
                           now=NOW, version="0.3.0")
    assert text.startswith("---\nkind: feedback\nabout: bug\nversion: 0.3.0\n")
    assert "date: 2026-09-18T14:32:00" in text
    assert "# Sorting looked wrong" in text  # whitespace collapsed
    assert "Robin Vale <robin@example.org>" in text
    assert "- Hermit CRM 0.3.0 on Python 3.13 (Linux)" in text


def test_report_survives_an_unknown_kind_and_an_empty_body():
    text = feedback.report("nonsense", "", "", now=NOW)
    assert "about: bug" in text and "# (no summary)" in text
    assert "(nothing else written)" in text
    assert "## From" not in text  # no reporter, no empty section


def test_filename_is_dated_and_slugged():
    assert feedback.filename("Sorting looked wrong", now=NOW) == \
        "feedback/2026-09-18-1432-sorting-looked-wrong.md"
    assert feedback.filename("", now=NOW).endswith("-feedback.md")
    assert len(Path(feedback.filename("x " * 200, now=NOW)).stem) < 80


def test_mailto_needs_an_address_and_stays_short():
    assert feedback.mailto("", "s", "b") == ""
    link = feedback.mailto("hermit@example.org", "It broke", "x" * 5000)
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query)
    assert urllib.parse.unquote(urllib.parse.urlsplit(link).path) == "hermit@example.org"
    assert query["subject"] == ["Hermit CRM feedback: It broke"]
    assert len(query["body"][0]) < 2000 and "the full report is in the file" in query["body"][0]


def test_diagnostics_are_numbers_and_flags_only():
    lines = feedback.diagnostics("0.3.0", "3.13.1", "Linux 6.1 (x86_64)",
                                 {"companies": 12, "contacts": 31, "interactions": 88},
                                 data_format=4, features={"BCC import": "off"})
    assert lines[0] == "Hermit CRM 0.3.0 on Python 3.13.1 (Linux 6.1 (x86_64))"
    assert lines[1] == "Data folder: 12 companies, 31 contacts, 88 interactions, format 4"
    assert lines[2] == "BCC import: off"


# ------------------------------------------------------------------- the page


def test_feedback_is_a_help_topic_with_a_form(folder):
    app, client = make_client(folder)
    page = client.get("/help/feedback")
    assert page.status_code == 200
    assert '/help/feedback">Feedback' in page.text  # in the help sidebar
    assert 'action="/help/feedback"' in page.text and 'name="summary"' in page.text
    assert "Nothing is sent anywhere" in page.text  # the topic prose renders too
    # The facts are shown before anything is written, not hidden behind a checkbox.
    assert "The facts that will be attached" in page.text
    assert "Hermit CRM 0.3.0 on Python" in page.text


def test_saving_writes_a_file_and_commits_it(folder):
    app, client = make_client(folder)
    page = send(client, summary="Sorting looked wrong", detail="I pressed it twice.")
    assert page.status_code == 200
    name = re.search(r"<code>(feedback/[^<]+)</code>", page.text).group(1)
    text = (folder / name).read_text(encoding="utf-8")
    assert "# Sorting looked wrong" in text and "I pressed it twice." in text
    assert text in html.unescape(page.text)  # shown back for copying
    log = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=folder,
                         capture_output=True, text=True).stdout.strip()
    assert log == "feedback: Sorting looked wrong"


def test_the_report_carries_no_paths_and_no_crm_data(folder):
    """A data folder path is /Users/<their name>/...; nobody expects a bug report
    to carry their name, so the diagnostics are numbers and flags only."""
    app, client = make_client(folder)
    client.post("/companies", data={"csrf_token": token(client),
                                    "name": "Blue Heron Analytics", "stage": "prospect"})
    page = send(client, summary="Counts look off")
    name = re.search(r"<code>(feedback/[^<]+)</code>", page.text).group(1)
    text = (folder / name).read_text(encoding="utf-8")
    assert str(folder) not in text and "/Users/" not in text
    assert "Blue Heron" not in text
    assert "Data folder: 1 companies" in text  # the count, not the company


def test_an_empty_report_is_refused(folder):
    app, client = make_client(folder)
    page = send(client, summary="", detail="")
    assert page.status_code == 422
    assert "one-line summary" in page.text and "an empty report cannot be acted on" in page.text
    assert not list((folder / "feedback").glob("*.md")) if (folder / "feedback").exists() else True


def test_the_mail_link_appears_only_when_an_address_is_configured(folder):
    app, client = make_client(folder)
    page = send(client)
    assert "mailto:" not in page.text and "feedback_email" in page.text

    app, client = make_client(folder, feedback_email="hermit@example.org")
    page = send(client)
    link = html.unescape(re.search(r'href="(mailto:[^"]+)"', page.text).group(1))
    assert urllib.parse.unquote(urllib.parse.urlsplit(link).path) == "hermit@example.org"


def test_the_form_needs_a_csrf_token(folder):
    app, client = make_client(folder)
    assert client.post("/help/feedback", data={"csrf_token": "no", "summary": "x",
                                               "detail": "y"}).status_code == 403
