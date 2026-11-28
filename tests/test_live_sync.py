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

"""Live sync: GitOps.head (HEAD read from the files under .git, no process on
the normal path), GET /live/head.json that static/live.js polls, and the
rules live.js keeps (it only polls while the tab is visible)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hermitcrm import gitops as gitops_module
from hermitcrm import web
from hermitcrm.gitops import GitOps

LIVE_JS = Path(web.__file__).parent / "static" / "live.js"


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "user.name=crm", "-c", "user.email=crm@localhost",
                           *args], cwd=folder, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def commit(folder: Path, message: str = "a change") -> str:
    git(folder, "commit", "--allow-empty", "-q", "-m", message)
    return git(folder, "rev-parse", "HEAD")


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


def no_process(monkeypatch):
    """Fail the test if anything starts a process."""
    def refuse(*args, **kwargs):
        raise AssertionError(f"a process was started: {args[0] if args else kwargs}")
    monkeypatch.setattr(gitops_module.subprocess, "run", refuse)


# --------------------------------------------------------------- GitOps.head


def test_head_reads_the_branch_ref_without_starting_git(folder, monkeypatch):
    sha = commit(folder)
    ops = GitOps(folder, push_enabled=False)
    no_process(monkeypatch)
    assert ops.head() == sha[:10]


def test_head_is_the_same_value_last_commit_sha_gives(folder):
    commit(folder)
    ops = GitOps(folder, push_enabled=False)
    assert ops.head() == ops.last_commit_sha()


def test_head_moves_with_every_commit(folder):
    ops = GitOps(folder, push_enabled=False)
    first = commit(folder)
    assert ops.head() == first[:10]
    second = commit(folder)
    assert ops.head() == second[:10] != first[:10]


def test_a_detached_head_is_read_from_head_itself(folder, monkeypatch):
    first = commit(folder)
    commit(folder)
    git(folder, "checkout", "-q", "--detach", first)
    ops = GitOps(folder, push_enabled=False)
    no_process(monkeypatch)
    assert ops.head() == first[:10]


def test_a_packed_ref_falls_back_to_git(folder):
    sha = commit(folder)
    git(folder, "pack-refs", "--all")
    assert not (folder / ".git" / "refs" / "heads" / "main").exists()
    assert GitOps(folder, push_enabled=False).head() == sha[:10]


def test_no_commit_yet_and_no_git_give_none(folder, tmp_path_factory):
    assert GitOps(folder, push_enabled=False).head() is None        # unborn branch
    bare = tmp_path_factory.mktemp("not-a-repo")
    assert GitOps(bare, push_enabled=False).head() is None


def test_a_ref_outside_refs_is_not_followed(folder, monkeypatch):
    """HEAD naming a path outside refs/ is not read as a file: git decides."""
    sha = commit(folder)
    (folder / ".git" / "HEAD").write_text("ref: ../../outside\n")
    (folder / "outside").write_text("f" * 40 + "\n")
    calls = []
    monkeypatch.setattr(GitOps, "last_commit_sha", lambda self: calls.append(1) or "fallback")
    assert GitOps(folder, push_enabled=False).head() == "fallback"
    assert calls and sha


def test_a_garbled_ref_file_falls_back_to_git(folder, monkeypatch):
    commit(folder)
    (folder / ".git" / "refs" / "heads" / "main").write_text("not a sha\n")
    monkeypatch.setattr(GitOps, "last_commit_sha", lambda self: "fallback")
    assert GitOps(folder, push_enabled=False).head() == "fallback"


# ------------------------------------------------------------ /live/head.json


def test_head_json_answers_the_current_head(client, repo):
    sha = commit(repo, "init")
    got = client.get("/live/head.json")
    assert got.status_code == 200
    assert got.json() == {"head": sha[:10]}
    assert got.headers["cache-control"] == "no-store"
    after = commit(repo, "ai: a change from somewhere else")
    assert client.get("/live/head.json").json() == {"head": after[:10]}


def test_head_json_without_a_commit_is_empty(client):
    assert client.get("/live/head.json").json() == {"head": ""}


def test_polling_head_json_starts_no_process(client, repo, monkeypatch):
    """The poll runs every five seconds per open tab: it must not start git,
    nor run the per-request sweep (which reloads the store when HEAD moved)."""
    commit(repo, "init")
    no_process(monkeypatch)
    assert client.get("/live/head.json").status_code == 200


# ------------------------------------------------------------------- live.js


def sync_part() -> str:
    text = LIVE_JS.read_text(encoding="utf-8")
    start = text.index("Live sync")
    return text[start:]


def test_live_js_polls_head_json_only_while_the_tab_is_visible():
    part = sync_part()
    assert '"/live/head.json"' in part
    assert "visibilitychange" in part
    assert 'document.visibilityState === "visible"' in part
    assert "POLL_MS = 5000" in part


def test_live_js_says_so_when_an_edited_page_changed_underneath():
    part = sync_part()
    assert "This page changed underneath you" in part
    assert '"Refresh"' in part
