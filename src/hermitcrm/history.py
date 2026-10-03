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

"""Recent changes and undo: the CRM's own changelog, read from git.

Undo is `git revert`: a new commit that reverses an old one, so history is
only ever added to (the backup rules forbid rewriting it). PIPELINE.md is
generated and committed with every record change, so two changes far apart
nearly always touched it both; a revert whose only conflict is PIPELINE.md
writes it afresh instead of giving up.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import pipeline

# The files an agent may write without asking (contract 4); config.toml counts
# only for the keys it may change, which commit subjects name.
EXTENSION_FILES = ("fields.toml", "layout.toml", "routines.toml", "theme.css",
                   "messages.toml", "MESSAGING.md")
CONFIG_KEYS = ("task_types", "outcomes", "silent_days", "adjust_agent")
# Commit subjects Hermit and agents write for changes worth listing.
SUBJECTS = ("ai: adjust:", "ai: bulk:", "bulk:", "routine:", 'Revert "')
IDENTITY = ["-c", "user.name=hermitcrm", "-c", "user.email=hermitcrm@localhost"]
_REVERTS = re.compile(r"This reverts commit ([0-9a-f]{7,40})")


class UndoError(Exception):
    """An undo that was refused or could not be done; the message says why."""

    def __init__(self, message: str, prompt: str = ""):
        super().__init__(message)
        self.prompt = prompt  # for a conflict: what to ask the agent instead


@dataclass
class Change:
    sha: str
    when: datetime
    subject: str
    files: list[str] = field(default_factory=list)
    merge: bool = False
    undone: bool = False

    @property
    def sha7(self) -> str:
        return self.sha[:7]

    @property
    def can_undo(self) -> bool:
        return not self.merge and not self.undone

    @property
    def touched(self) -> str:
        """Which files, in a few words: the extension files by name, records by count."""
        named = [f for f in self.files if is_extension_file(f) or f == "config.toml"]
        companies = {f.split("/")[1] for f in self.files
                     if f.startswith("companies/") and f.count("/") >= 2}
        parts = named[:3] + ([f"{len(named) - 3} more files"] if len(named) > 3 else [])
        if companies:
            parts.append(f"{len(companies)} compan{'y' if len(companies) == 1 else 'ies'}")
        return ", ".join(parts)


def _git(root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          timeout=60)
    if check and proc.returncode != 0:
        raise UndoError((proc.stderr or proc.stdout).strip() or f"git {args[0]} failed")
    return proc


def is_extension_file(path: str) -> bool:
    return path in EXTENSION_FILES or (path.startswith("dashboards/")
                                       and path.endswith(".toml"))


def counts(subject: str, files: list[str]) -> bool:
    """Whether a commit belongs in Recent changes (contract 3)."""
    if subject.startswith(SUBJECTS):
        return True
    if any(is_extension_file(f) for f in files):
        return True
    return "config.toml" in files and (subject.startswith("ai:")
                                       or any(k in subject for k in CONFIG_KEYS))


def recent_changes(root: Path, limit: int = 20, scan: int = 500) -> list[Change]:
    """The newest `limit` commits that count, among the last `scan`."""
    proc = _git(Path(root), "log", f"--max-count={scan}", "--name-only",
                "--format=%x1e%H%x1f%ct%x1f%P%x1f%s%x1f%b%x1d")
    if proc.returncode != 0:
        return []
    changes, undone = [], set()
    for record in proc.stdout.split("\x1e")[1:]:
        head, _, names = record.partition("\x1d")
        try:
            sha, stamp, parents, subject, body = head.split("\x1f", 4)
        except ValueError:
            continue
        undone.update(_REVERTS.findall(body))
        files = [n.strip() for n in names.splitlines() if n.strip()]
        if not counts(subject, files):
            continue
        changes.append(Change(sha=sha, when=datetime.fromtimestamp(int(stamp)),
                              subject=subject, files=files, merge=len(parents.split()) > 1))
    for change in changes:
        change.undone = any(change.sha.startswith(s) for s in undone)
    return changes[:limit]


def when_text(when: datetime, now: datetime | None = None) -> str:
    """"just now", "12 min ago", "today 14:05", "yesterday", "3 Oct", "3 Oct 2025"."""
    now = now or datetime.now()
    seconds = (now - when).total_seconds()
    if 0 <= seconds < 60:
        return "just now"
    if 0 <= seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    days = (now.date() - when.date()).days
    if days == 0:
        return f"today {when:%H:%M}"
    if days == 1:
        return "yesterday"
    return f"{when.day} {when:%b}" + ("" if when.year == now.year else f" {when.year}")


# ------------------------------------------------------------------------ undo


def undo(store, sha: str) -> tuple[str, str]:
    """Revert one commit in a new commit; (new sha7, its subject).

    Refuses an unknown commit, a merge, the folder's first commit and a working
    tree with uncommitted changes to tracked files. A conflict is aborted, so
    the folder is exactly as it was. Holds the store's write lock throughout,
    so no other write lands in the middle.
    """
    root = Path(store.root)
    sha = (sha or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{4,40}", sha):
        raise UndoError(f"Not undone: {sha or 'no commit'} is not a commit id.")
    with store.lock:
        found = _git(root, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
        if found.returncode != 0:
            raise UndoError(f"Not undone: there is no commit {sha} in this folder.")
        full = found.stdout.strip()
        if _git(root, "merge-base", "--is-ancestor", full, "HEAD").returncode != 0:
            raise UndoError(f"Not undone: commit {full[:7]} is not in this folder's history.")
        parents = _git(root, "rev-list", "--parents", "-n", "1", full).stdout.split()[1:]
        subject = _git(root, "log", "-1", "--format=%s", full).stdout.strip()
        if len(parents) > 1:
            raise UndoError(f"Not undone: {full[:7]} ({subject}) joins two lines of history "
                            "(a merge); undo the commits it brought in instead.")
        if not parents:
            raise UndoError(f"Not undone: {full[:7]} is the folder's first commit; undoing "
                            "it would remove everything.")
        dirty = [line[3:] for line in _git(root, "status", "--porcelain",
                                           "--untracked-files=no").stdout.splitlines()]
        if dirty:
            raise UndoError("Not undone: these files have changes that are not committed "
                            "yet: " + ", ".join(dirty[:5])
                            + (f" and {len(dirty) - 5} more" if len(dirty) > 5 else "")
                            + ". Commit or discard them first, then try again.")
        files = _git(root, "show", "--name-only", "--format=", full).stdout.split()
        records = any(f == "PIPELINE.md" or f.startswith("companies/") for f in files)

        reverted = _git(root, "revert", "--no-commit", full)
        if reverted.returncode != 0:
            unmerged = set(_git(root, "diff", "--name-only", "--diff-filter=U").stdout.split())
            if not unmerged or not unmerged <= {"PIPELINE.md"}:
                _abort(root)
                if unmerged:
                    ask = f"undo commit {full[:7]} ({subject})"
                    raise UndoError("Later changes touched the same lines, so this can't "
                                    f"be undone automatically. Ask your agent: {ask}",
                                    prompt=ask[:1].upper() + ask[1:])
                raise UndoError("Not undone: " + ((reverted.stderr or reverted.stdout)
                                                  .strip().splitlines() or ["git failed"])[0])
        staged = set(_git(root, "diff", "--cached", "--name-only").stdout.split())
        if not staged - {"PIPELINE.md"}:
            _abort(root)
            raise UndoError(f"Nothing to undo: the changes of {full[:7]} ({subject}) "
                            "are already gone.")
        try:
            if records:
                # PIPELINE.md is generated: write it from the records as they now are.
                store.load()
                pipeline.write(store)
                if (root / "PIPELINE.md").exists():
                    _git(root, "add", "PIPELINE.md", check=True)
            message = f'Revert "{subject}"\n\nThis reverts commit {full}.'
            _git(root, *IDENTITY, "commit", "--no-verify", "-q", "-m", message, check=True)
        except Exception as exc:
            _abort(root)
            raise UndoError(f"Not undone: {exc}") from exc
        new = _git(root, "rev-parse", "HEAD").stdout.strip()
    return new[:7], f'Revert "{subject}"'


def _abort(root: Path) -> None:
    """Back to how the folder was before the revert started."""
    if _git(root, "revert", "--abort").returncode != 0:
        _git(root, "revert", "--quit")
