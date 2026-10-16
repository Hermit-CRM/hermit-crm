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

"""history.last_change(): the newest commit of one file, as the dashboard
page shows it with Undo, and the undo that lands back on that page."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import history
from hermitcrm.datafolder import init_folder
from hermitcrm.web import create_app
from test_adjust import commit_file, git, make, token

DASH = 'title = "Partners"\n[[widget]]\ntype = "count"\nscope = "companies"\n'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    folder = tmp_path / "repo"
    folder.mkdir()
    git(folder, "init", "-q")
    commit_file(folder, "README.md", "a folder\n", "init: a folder")
    return folder


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "demo", demo=True)


# ------------------------------------------------------------- last_change


def test_the_newest_commit_of_a_file(repo):
    commit_file(repo, "dashboards/partners.toml", DASH, "ai: adjust: dashboard Partners")
    newest = commit_file(repo, "dashboards/partners.toml", DASH + "# v2\n",
                         "ai: adjust: dashboard Partners, v2")
    commit_file(repo, "other.txt", "x\n", "something else")
    change = history.last_change(repo, "dashboards/partners.toml")
    assert change.sha == newest and change.subject == "ai: adjust: dashboard Partners, v2"
    assert change.can_undo and change.files == ["dashboards/partners.toml"]


def test_nothing_without_a_commit_or_without_git(repo, tmp_path):
    (repo / "dashboards").mkdir()
    (repo / "dashboards" / "loose.toml").write_text(DASH, encoding="utf-8")
    assert history.last_change(repo, "dashboards/loose.toml") is None      # not committed
    assert history.last_change(repo, "dashboards/missing.toml") is None
    plain = tmp_path / "plain"
    (plain / "dashboards").mkdir(parents=True)
    (plain / "dashboards" / "x.toml").write_text(DASH, encoding="utf-8")
    assert history.last_change(plain, "dashboards/x.toml") is None         # no git at all
    assert history.last_change(tmp_path / "gone", "dashboards/x.toml") is None


def test_the_first_commit_and_a_reverted_change_cannot_be_undone(repo):
    first = history.last_change(repo, "README.md")
    assert first.first and not first.can_undo      # undo refuses the folder's first commit
    # a commit touching the dashboard and another file, reverted later by a
    # commit that (after a hand-resolved conflict) only touched the other file
    sha = commit_file(repo, "dashboards/partners.toml", DASH, "ai: adjust: dashboard Partners")
    commit_file(repo, "other.txt", "y\n", f'Revert "x"\n\nThis reverts commit {sha}.')
    change = history.last_change(repo, "dashboards/partners.toml")
    assert change.sha == sha and change.undone and not change.can_undo
    # an ordinary revert touches the file too, so it is the newest change, and undoable
    git(repo, "revert", "--no-edit", sha)
    newest = history.last_change(repo, "dashboards/partners.toml")
    assert newest.subject.startswith('Revert "') and newest.can_undo


# ------------------------------------------------------------- the page


def line_of(page: str) -> str:
    found = re.search(r'<div class="small dashboard-history">.*?</div>', page, re.S)
    return found.group(0) if found else ""


def test_the_dashboard_page_says_where_it_came_from(demo):
    app, client = make(demo)
    made = line_of(client.get("/d/monday-review").text)   # made with the folder: no Undo
    assert "init: Hermit CRM data folder" in made and "Undo" not in made
    text = (demo / "dashboards" / "monday-review.toml").read_text(encoding="utf-8")
    sha = commit_file(demo, "dashboards/monday-review.toml", text.replace(
        'title = "Monday review"', 'title = "Weekly review"'),
        "ai: adjust: monday review dashboard")
    line = line_of(client.get("/d/monday-review").text)
    assert re.search(r"Last changed [^&]+: &ldquo;ai: adjust: monday review dashboard&rdquo;",
                     line)
    assert f'name="sha" value="{sha}"' in line and 'name="back" value="/d/monday-review"' in line
    assert 'href="/yours#changes">All changes' in line
    other = commit_file(demo, "dashboards/partners.toml", DASH, "ai: adjust: dashboard Partners")
    assert other in line_of(client.get("/d/partners").text)


def test_undo_from_the_dashboard_lands_on_it_or_on_the_hub(demo):
    app, client = make(demo)
    path = demo / "dashboards" / "monday-review.toml"
    before = path.read_text(encoding="utf-8")
    sha = commit_file(demo, "dashboards/monday-review.toml",
                      before.replace('title = "Monday review"', 'title = "Weekly review"'),
                      "ai: adjust: monday review dashboard")
    done = client.post("/yours/undo", data={"csrf_token": token(client), "sha": sha,
                                            "back": "/d/monday-review"})
    assert done.status_code == 303 and done.headers["location"].startswith(
        "/d/monday-review?flash=Undone")
    assert path.read_text(encoding="utf-8") == before
    assert "Monday review" in client.get(done.headers["location"]).text
    # undoing a dashboard's creation removes its page: back to the hub
    made = commit_file(demo, "dashboards/partners.toml", DASH, "ai: adjust: dashboard Partners")
    gone = client.post("/yours/undo", data={"csrf_token": token(client), "sha": made,
                                            "back": "/d/partners"})
    assert gone.headers["location"].startswith("/yours?undo=1&flash=Undone")
    assert not (demo / "dashboards" / "partners.toml").exists()
    # anything but a dashboard page of this folder is ignored
    for back in ("//evil.example.com/d/x", "https://example.com/", "/d/../config",
                 "/companies", "/d/monday-review\n"):
        sha = commit_file(demo, "dashboards/x.toml", DASH + f"# {len(back)}\n", "ai: adjust: x")
        out = client.post("/yours/undo", data={"csrf_token": token(client), "sha": sha,
                                               "back": back})
        assert out.headers["location"].startswith("/yours?undo=1"), back


def test_without_git_the_page_still_renders(demo):
    shutil.rmtree(demo / ".git")
    app = create_app(demo, config={"push_enabled": False, "welcome_dismissed": True,
                                   "disclaimer_accepted": "2026-09-01T09:00:00",
                                   "owner_email": "me@example.com"})
    page = TestClient(app, follow_redirects=False).get("/d/monday-review")
    assert page.status_code == 200 and "Monday review" in page.text
    assert not line_of(page.text)
