"""A write that removes an inbox file commits that removal with the rest.

Commits are scoped to the paths a write touched (store.take_touched), and the
Inbox writes its files itself, so every inbox change has to be announced to the
store. Forgetting it leaves the data folder dirty forever: the file is gone from
the working tree but its deletion is never staged.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hermitcrm import bcc, pipeline
from hermitcrm.gitops import GitOps
from hermitcrm.store import Store
from conftest import FIXED_NOW


def git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True).stdout


def committed(repo: Path) -> str:
    """The paths of the last commit. --no-renames because the queued mail and
    the interaction it becomes are similar enough for git to pair them as a
    rename, which hides the removal behind an R line."""
    return git(["show", "--name-status", "--no-renames", "--format=", "HEAD"], repo)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for args in (["init", "-b", "main"], ["config", "user.name", "CRM Test"],
                 ["config", "user.email", "crm@test.local"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


@pytest.fixture
def store(repo: Path) -> Store:
    """A store on a real repo, committing each write the way the app does."""
    gitops = GitOps(repo, push_enabled=False)

    def on_write(message: str) -> None:
        paths = s.take_touched()
        pipeline.write(s)
        gitops.commit(message, [*paths, "PIPELINE.md"])

    s = Store(repo, on_write=on_write, clock=lambda: FIXED_NOW)
    s.load()
    return s


def queued(store: Store) -> bcc.InboxItem:
    """One mail in the review queue, committed the way the import commits it."""
    entry = bcc.Entry("<m1@work.example.com>", FIXED_NOW, "out", "ann@lee.com",
                      "Ann Lee", "Intro", "Hi Ann,\n\nShort note.\n")
    item = bcc.Inbox(store.root).add(entry, "no company matches lee.com")
    store.notify(f"bcc: {item.id} to review", ["inbox"])
    return item


def test_assign_commits_the_inbox_file_it_removes(store: Store, repo: Path):
    store.create_company("Acme GmbH", website="acme.de")
    item = queued(store)
    assert git(["status", "--porcelain"], repo).strip() == ""

    bcc.assign(store, bcc.Inbox(store.root), item.id, "Acme GmbH")

    assert not (repo / "inbox" / f"{item.id}.md").exists()
    assert git(["status", "--porcelain"], repo).strip() == ""
    assert f"D\tinbox/{item.id}.md" in committed(repo)


def test_assign_is_one_commit(store: Store, repo: Path):
    store.create_company("Acme GmbH", website="acme.de")
    item = queued(store)
    before = git(["rev-list", "--count", "HEAD"], repo).strip()

    bcc.assign(store, bcc.Inbox(store.root), item.id, "Acme GmbH")

    after = git(["rev-list", "--count", "HEAD"], repo).strip()
    assert int(after) - int(before) == 1
    assert git(["log", "-1", "--format=%s"], repo).strip() == (
        f"bcc: {item.id} assigned to acme/ann-lee")


def test_discard_commits_the_inbox_file_it_removes(store: Store, repo: Path):
    item = queued(store)

    bcc.discard(store, bcc.Inbox(store.root), item.id)

    assert git(["status", "--porcelain"], repo).strip() == ""
    assert f"D\tinbox/{item.id}.md" in committed(repo)
