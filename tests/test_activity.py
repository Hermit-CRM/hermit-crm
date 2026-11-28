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

"""GET /activity: what agents did. Recent commits whose subject starts with
"ai:" (and the undos of those), grouped by day, each with what changed in plain
words, the records it touched (linked while they exist) and an Undo button."""

from __future__ import annotations

import re
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest

from hermitcrm.pages import live_sync

COMPANY = "---\nname: {name}\nstage: lead\n---\n"
CONTACT = "---\nfirst_name: {first}\nlast_name: {last}\n---\n"


def git(folder: Path, *args: str, when: str = "") -> str:
    env = None
    if when:
        import os
        env = dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    done = subprocess.run(["git", "-c", "user.name=crm", "-c", "user.email=crm@localhost",
                           *args], cwd=folder, capture_output=True, text=True, check=True,
                          env=env)
    return done.stdout.strip()


def write(folder: Path, rel: str, text: str) -> None:
    path = folder / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(folder: Path, message: str, when: str = "") -> str:
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "--allow-empty", "-m", message, when=when)
    return git(folder, "rev-parse", "HEAD")


def token(client) -> str:
    return client.app.state.csrf_token


@pytest.fixture
def folder(repo: Path) -> Path:
    """The conftest repo with a first commit and two companies."""
    write(repo, "companies/acme-labs/company.md", COMPANY.format(name="Acme Labs"))
    write(repo, "companies/acme-labs/contacts/jane-doe.md",
          CONTACT.format(first="Jane", last="Doe"))
    write(repo, "companies/borealis-ltd/company.md", COMPANY.format(name="Borealis Ltd"))
    commit(repo, "init: a folder", when="2026-09-10T09:00:00")
    return repo


# ------------------------------------------------------------------ plain words


@pytest.mark.parametrize("subject, said", [
    ("ai: adjust: add a Region field", "Adjusted Hermit: add a Region field"),
    ("ai: bulk: retag 12 companies", "Bulk change: retag 12 companies"),
    ("ai: logged the call with Jane", "Logged the call with Jane"),
    ('Revert "ai: bulk: retag 12 companies"', "Undid: Bulk change: retag 12 companies"),
])
def test_the_subject_in_plain_words(subject, said):
    assert live_sync.plain(subject) == said


def test_what_changed_counts_records_and_names_other_files():
    files = [("A", "companies/acme-labs/interactions/2026-09-14T1000-call-out.md"),
             ("A", "companies/acme-labs/interactions/2026-09-14T1100-note-company.md"),
             ("M", "companies/acme-labs/company.md"),
             ("M", "companies/borealis-ltd/company.md"),
             ("D", "companies/acme-labs/contacts/jane-doe.md"),
             ("M", "PIPELINE.md"),
             ("M", "fields.toml")]
    assert live_sync.summary(files) == ("added 2 interactions, changed 2 companies, "
                                        "removed 1 contact, changed fields.toml")


def test_a_rename_counts_as_changed_and_nothing_gives_an_empty_summary():
    assert live_sync.summary([("R100", "companies/acme-labs/contacts/jane.md")]) \
        == "changed 1 contact"
    assert live_sync.summary([("M", "PIPELINE.md")]) == ""
    assert live_sync.summary([]) == ""


# ------------------------------------------------------------------- the commits


def test_only_agent_commits_and_their_undos_are_listed(folder):
    write(folder, "companies/acme-labs/company.md", COMPANY.format(name="Acme Labs Inc"))
    agent = commit(folder, "ai: renamed Acme", when="2026-09-14T10:00:00")
    write(folder, "companies/borealis-ltd/company.md", COMPANY.format(name="Borealis"))
    commit(folder, "company: borealis-ltd updated", when="2026-09-14T11:00:00")
    git(folder, "revert", "--no-edit", agent)    # 'Revert "ai: renamed Acme"'
    got = live_sync.agent_changes(folder)
    assert [c.subject for c in got] == ['Revert "ai: renamed Acme"', "ai: renamed Acme"]
    undo, original = got
    assert original.undone and not original.can_undo
    assert undo.can_undo and not undo.undone
    assert original.sha == agent
    assert original.when == datetime(2026, 9, 14, 10, 0)
    assert original.files == [("M", "companies/acme-labs/company.md")]


def test_the_first_commit_and_a_merge_cannot_be_undone(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, "ai: the very first commit")
    git(tmp_path, "checkout", "-q", "-b", "side")
    commit(tmp_path, "ai: on a side line")
    git(tmp_path, "checkout", "-q", "main")
    commit(tmp_path, "ai: on main")
    git(tmp_path, "merge", "-q", "--no-ff", "-m", "ai: merge the side line", "side")
    got = {c.subject: c for c in live_sync.agent_changes(tmp_path)}
    assert not got["ai: the very first commit"].can_undo
    assert not got["ai: merge the side line"].can_undo
    assert got["ai: on main"].can_undo


def test_no_git_or_no_commits_list_nothing(tmp_path, repo):
    assert live_sync.agent_changes(tmp_path) == []      # not a repository
    assert live_sync.agent_changes(repo) == []          # no commit yet


def test_grouped_by_day_newest_first():
    def at(day, hour):
        return live_sync.Activity(sha="0" * 40, when=datetime(2026, 9, day, hour), subject="ai: x")
    entries = [at(14, 11), at(14, 9), at(13, 18), at(2, 8)]
    days = live_sync.by_day(entries, today=date(2026, 9, 14))
    assert [(label, len(rows)) for label, rows in days] == [
        ("Today", 2), ("Yesterday", 1), ("Wednesday 2 September", 1)]
    last_year = live_sync.by_day([at(2, 8)], today=date(2027, 1, 5))
    assert last_year[0][0] == "Wednesday 2 September 2026"


# ------------------------------------------------------------------ the page


def test_the_page_lists_what_agents_did_with_links_and_undo(client, folder):
    write(folder, "companies/acme-labs/interactions/2026-09-14T1000-note-company.md",
          "---\nchannel: note\ndate: 2026-09-14T10:00\n---\nCalled.\n")
    write(folder, "companies/acme-labs/contacts/jane-doe.md",
          CONTACT.format(first="Jane", last="Doe-Smith"))
    sha = commit(folder, "ai: logged a call with Jane")
    commit(folder, "interaction: borealis-ltd note company")      # not an agent's
    page = client.get("/activity")
    assert page.status_code == 200
    text = page.text
    assert "Logged a call with Jane" in text
    assert "added 1 interaction, changed 1 contact" in text
    assert 'href="/companies/acme-labs">Acme Labs</a>' in text
    assert 'href="/companies/acme-labs/contacts/jane-doe">' in text
    assert "borealis-ltd note company" not in text
    undo = re.search(r'<form method="post" action="/yours/undo"[^>]*>(.*?)</form>', text, re.S)
    assert undo and f'name="sha" value="{sha}"' in undo.group(1)
    assert f'value="{token(client)}"' in undo.group(1)
    assert "<h2>Today</h2>" in text


def test_a_record_that_is_gone_is_named_not_linked(client, folder):
    git(folder, "rm", "-q", "-r", "companies/borealis-ltd")
    commit(folder, "ai: removed Borealis")
    text = client.get("/activity").text
    assert "removed 1 company" in text
    assert "borealis-ltd" in text
    assert 'href="/companies/borealis-ltd"' not in text


def test_undo_from_the_page_reverts_the_commit(client, folder):
    write(folder, "companies/acme-labs/company.md", COMPANY.format(name="Acme Labs Inc"))
    sha = commit(folder, "ai: renamed Acme")
    client.app.state.store.load()
    done = client.post("/yours/undo", data={"csrf_token": token(client), "sha": sha})
    assert done.status_code == 303
    assert git(folder, "log", "-1", "--format=%s") == 'Revert "ai: renamed Acme"'
    text = client.get("/activity").text
    assert "Undid: Renamed Acme" in text
    assert text.count('action="/yours/undo"') == 1     # the undo itself; the original is undone


def test_the_page_without_agent_changes_says_so(client, folder):
    text = client.get("/activity").text
    assert "No agent changes yet" in text


def test_make_it_yours_links_to_the_page(client, folder):
    assert 'href="/activity"' in client.get("/yours").text
