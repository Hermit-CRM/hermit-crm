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

"""Live sync and agent activity. Registered by pages.register.

`GET /live/head.json` says what git HEAD is; static/live.js asks every five
seconds while its tab is visible and refreshes the page when the answer
changes. Every write by any Hermit process (the CLI, the MCP server, the daily
sync, an agent's own commit) moves HEAD. The store itself is reloaded where it
always was, by `refresh_if_moved` in web.py on the next page request: this
endpoint only reads, and as it is under /live/ the per-request sweep skips it.

`GET /activity` lists what agents did: recent commits whose subject starts with
"ai:" (what agents are told to write, and what Hermit's own MCP adjust and bulk
tools write) and the undos of those, grouped by day, each with an Undo button
that posts to /yours/undo.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ._ctx import ctx

router = APIRouter()

NO_STORE = {"Cache-Control": "no-store"}


@router.get("/live/head.json")
def live_head(request: Request):
    """{"head": the commit HEAD points at, 10 characters, or "" without one}."""
    return JSONResponse({"head": ctx(request).gitops.head() or ""}, headers=NO_STORE)


# -------------------------------------------------------------- agent activity

SCAN = 400       # commits looked at, newest first
SHOWN = 100      # agent changes listed at most
RECORDS = 8      # records named per change; the rest are counted
AGENT = ("ai:", 'Revert "ai:')
_REVERTS = re.compile(r"This reverts commit ([0-9a-f]{7,40})")
KINDS = (("adjust:", "Adjusted Hermit: "), ("bulk:", "Bulk change: "))
NOUNS = {"company": "companies", "contact": "contacts", "interaction": "interactions"}
VERBS = (("A", "added"), ("M", "changed"), ("D", "removed"))


@dataclass
class Activity:
    sha: str
    when: datetime
    subject: str
    files: list[tuple[str, str]] = field(default_factory=list)   # (status, path)
    merge: bool = False
    first: bool = False
    undone: bool = False

    @property
    def can_undo(self) -> bool:
        return not (self.merge or self.first or self.undone)

    @property
    def said(self) -> str:
        return plain(self.subject)

    @property
    def what(self) -> str:
        return summary(self.files)


def plain(subject: str) -> str:
    """The commit subject as a sentence: "ai: bulk: x" is "Bulk change: x",
    'Revert "ai: x"' is "Undid: X"."""
    if subject.startswith('Revert "') and subject.endswith('"'):
        return "Undid: " + plain(subject[len('Revert "'):-1])
    text = subject[3:].strip() if subject.startswith("ai:") else subject.strip()
    for prefix, said in KINDS:
        if text.startswith(prefix):
            return said + text[len(prefix):].strip()
    return text[:1].upper() + text[1:]


def kind_of(path: str) -> str:
    """"company", "contact", "interaction", "" for PIPELINE.md (generated with
    every record change) or "file" for anything else."""
    parts = path.split("/")
    if path == "PIPELINE.md":
        return ""
    if len(parts) == 3 and parts[0] == "companies" and parts[2] == "company.md":
        return "company"
    if len(parts) == 4 and parts[0] == "companies" and parts[2] in ("contacts", "interactions"):
        return parts[2][:-1]
    return "file"


def summary(files: list[tuple[str, str]]) -> str:
    """What changed, in plain words: "added 2 interactions, changed 1 company,
    changed fields.toml". A rename counts as changed."""
    counts: dict[tuple[str, str], int] = {}
    named: dict[str, list[str]] = {}
    for status, path in files:
        verb = {"A": "added", "D": "removed"}.get(status[:1], "changed")
        kind = kind_of(path)
        if kind == "file":
            named.setdefault(verb, []).append(path)
        elif kind:
            counts[(verb, kind)] = counts.get((verb, kind), 0) + 1
    words = [f"{verb} {n} {kind if n == 1 else NOUNS[kind]}"
             for _, verb in VERBS for kind in NOUNS
             for n in [counts.get((verb, kind), 0)] if n]
    for _, verb in VERBS:
        paths = named.get(verb, [])
        if paths:
            shown = ", ".join(paths[:3]) + (f" and {len(paths) - 3} more" if len(paths) > 3 else "")
            words.append(f"{verb} {shown}")
    return ", ".join(words)


def agent_changes(root: Path, scan: int = SCAN, limit: int = SHOWN) -> list[Activity]:
    """The newest `limit` agent commits among the last `scan`, newest first.
    No git, no commits or a git that fails: an empty list."""
    try:
        proc = subprocess.run(
            ["git", "log", f"--max-count={scan}", "--name-status", "--no-renames",
             "--format=%x1e%H%x1f%ct%x1f%P%x1f%s%x1f%b%x1d"],
            cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
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
        if not subject.startswith(AGENT):
            continue
        files = [tuple(line.split("\t")[:2]) for line in names.splitlines() if "\t" in line]
        changes.append(Activity(sha=sha, when=datetime.fromtimestamp(int(stamp)),
                                subject=subject, files=files,
                                merge=len(parents.split()) > 1, first=not parents.split()))
    for change in changes:
        change.undone = any(change.sha.startswith(s) for s in undone)
    return changes[:limit]


def by_day(entries: list[Activity], today: date) -> list[tuple[str, list[Activity]]]:
    """[(heading, entries)] in the order given: "Today", "Yesterday", then
    "Wednesday 2 September" (with the year when it is not this year's)."""
    days: list[tuple[str, list[Activity]]] = []
    for entry in entries:
        day = entry.when.date()
        gap = (today - day).days
        if gap == 0:
            label = "Today"
        elif gap == 1:
            label = "Yesterday"
        else:
            label = f"{day:%A} {day.day} {day:%B}" + ("" if day.year == today.year
                                                      else f" {day.year}")
        if days and days[-1][0] == label:
            days[-1][1].append(entry)
        else:
            days.append((label, [entry]))
    return days


def records(store, files: list[tuple[str, str]]) -> list[dict]:
    """The companies and contacts a change touched: [{"label", "url"}], with a
    url while the record still exists (else its folder name, unlinked)."""
    seen, out = set(), []
    for _, path in files:
        parts = path.split("/")
        if not kind_of(path) or kind_of(path) == "file":
            continue
        slug = parts[1]
        company = store.companies.get(slug)
        if slug not in seen:
            seen.add(slug)
            out.append({"label": company.name if company else slug,
                        "url": f"/companies/{slug}" if company else ""})
        if parts[2] == "contacts":
            cslug = parts[3].removesuffix(".md")
            if (slug, cslug) in seen:
                continue
            seen.add((slug, cslug))
            person = company.contacts.get(cslug) if company else None
            out.append({"label": (person.name or cslug) if person else cslug,
                        "url": f"/companies/{slug}/contacts/{cslug}" if person else ""})
    return out


@router.get("/activity", response_class=HTMLResponse)
def activity(request: Request):
    c = ctx(request)
    entries = agent_changes(c.root)
    rows = {e.sha: records(c.store, e.files) for e in entries}
    return c.render(request, "activity.html", {
        "days": by_day(entries, datetime.now().date()),
        "rows": rows,
        "records_shown": RECORDS,
        "scan": SCAN,
    })
