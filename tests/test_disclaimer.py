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

"""The one-time disclaimer: hermitcrm/disclaimer.py and the modal over the app."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import disclaimer
from hermitcrm.store import load_config
from hermitcrm.web import create_app
from conftest import FIXED_NOW

FRESH = {"port": 8765, "push_enabled": False, "welcome_dismissed": True}
ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------- fixtures


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True,
                   capture_output=True)
    (tmp_path / "companies").mkdir()
    (tmp_path / "config.toml").write_text("# port = 8765\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(repo: Path):
    app = create_app(repo, config=dict(FRESH), clock=lambda: FIXED_NOW)
    app.state.setup_redirected = True
    return TestClient(app, follow_redirects=False)


def token(client: TestClient) -> str:
    return client.app.state.csrf_token


# ----------------------------------------------------------------------- unit


def test_accepted_is_false_until_a_time_is_written():
    assert not disclaimer.accepted({})
    assert not disclaimer.accepted({disclaimer.KEY: ""})
    assert not disclaimer.accepted({disclaimer.KEY: "   "})
    assert disclaimer.accepted({disclaimer.KEY: "2026-09-01T09:00:00"})


def test_stamp_is_a_local_timestamp_to_the_second():
    assert disclaimer.stamp(datetime(2026, 9, 20, 14, 5, 1, 999)) == "2026-09-20T14:05:01"


def test_there_are_exactly_the_three_points_asked_for():
    headings = [h for h, _ in disclaimer.POINTS]
    assert len(headings) == 3
    joined = " ".join(h + " " + b for h, b in disclaimer.POINTS).lower()
    assert "no warranty" in joined
    assert "backups" in joined
    assert "gdpr" in joined and "keys" in joined


def test_the_module_cannot_send_anything_anywhere():
    """The acknowledgement is local. Nothing in here may reach for the network."""
    source = (ROOT / "src/hermitcrm/disclaimer.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in source.splitlines() if not l.lstrip().startswith("#"))
    for forbidden in ("urllib", "http.client", "requests", "socket", "smtplib"):
        assert forbidden not in body, forbidden


# ---------------------------------------------------------------------- modal


def test_a_fresh_folder_gets_the_modal_on_every_page(client):
    for path in ("/", "/companies", "/settings", "/reports"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert 'role="dialog"' in r.text, path
        assert "Before you start" in r.text, path


def test_the_modal_shows_all_three_points_and_links_the_disclaimer(client):
    text = client.get("/").text
    for heading, _ in disclaimer.POINTS:
        assert heading in text
    # A new tab: the modal covers every page, including the one it links to.
    assert '<a href="/help/disclaimer" target="_blank" rel="noopener">' in text
    # The checkbox is what makes it an acknowledgement, and it is required.
    assert re.search(r'<input type="checkbox" name="accepted" value="1" required>', text)


def test_the_linked_help_page_is_served(client):
    r = client.get("/help/disclaimer")
    assert r.status_code == 200
    assert "No warranty" in r.text or "no warranty" in r.text


# --------------------------------------------------------------------- accept


def test_ticking_the_box_writes_a_timestamp_and_retires_the_modal(client, repo):
    r = client.post("/disclaimer/accept",
                    data={"csrf_token": token(client), "accepted": "1", "back": "/companies"})
    assert r.status_code == 303 and r.headers["location"] == "/companies"

    written = load_config(repo)[disclaimer.KEY]
    assert datetime.fromisoformat(written)          # a real timestamp
    assert disclaimer.KEY in (repo / "config.toml").read_text(encoding="utf-8")

    assert "Before you start" not in client.get("/").text
    assert "Before you start" not in client.get("/companies").text


def test_posting_without_the_box_changes_nothing(client, repo):
    r = client.post("/disclaimer/accept",
                    data={"csrf_token": token(client), "accepted": "", "back": "/"})
    assert r.status_code == 303
    assert not load_config(repo).get(disclaimer.KEY)
    assert "Before you start" in client.get("/").text


def test_a_bad_csrf_token_is_refused(client, repo):
    r = client.post("/disclaimer/accept",
                    data={"csrf_token": "wrong", "accepted": "1", "back": "/"})
    assert r.status_code == 403
    assert not load_config(repo).get(disclaimer.KEY)


@pytest.mark.parametrize("back", ["https://evil.example.com/", "//evil.example.com/",
                                  "/static/style.css", "not-a-path"])
def test_back_cannot_send_the_browser_off_the_app(client, back):
    r = client.post("/disclaimer/accept",
                    data={"csrf_token": token(client), "accepted": "1", "back": back})
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_accepting_twice_is_harmless(client, repo):
    for _ in range(2):
        client.post("/disclaimer/accept",
                    data={"csrf_token": token(client), "accepted": "1", "back": "/"})
    assert datetime.fromisoformat(load_config(repo)[disclaimer.KEY])


# ------------------------------------------------------------- the two copies


def test_the_in_app_page_and_DISCLAIMER_md_do_not_drift():
    """help/disclaimer.md is DISCLAIMER.md with repo-relative links adapted.

    Headings are the cheap check that one was not edited without the other.
    """
    def headings(text: str) -> list[str]:
        return [l.strip() for l in text.splitlines() if l.startswith("## ")]

    root_doc = (ROOT / "DISCLAIMER.md").read_text(encoding="utf-8")
    app_doc = (ROOT / "src/hermitcrm/help/disclaimer.md").read_text(encoding="utf-8")
    assert headings(root_doc) == headings(app_doc)
    # No repo-relative link can survive into the page the app serves.
    assert "](LICENSE" not in app_doc and "](SECURITY.md)" not in app_doc
