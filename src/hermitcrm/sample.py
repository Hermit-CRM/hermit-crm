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

"""The sample account: one made-up company a new user can load, look at and remove.

It lives in the user's own folder, marked `sample: true` in its company.md, so
every page shows a finished account instead of an empty screen. Removing it
deletes only folders that still carry that marker, in one commit; take the key
out by hand and the company is yours. The content is the demo's Northwind
Robotics account (hermitcrm/datafolder.py), dated relative to today.

It also shows what Make it yours builds before the user asks for anything: a
pinned dashboard (`dashboards/monday-review.toml`) and a paused routine
(`nudge-quiet-threads` in `routines.toml`). `init --demo` writes the same two.
Neither overwrites anything: an existing dashboard file, or a routine of that
name, stays as it is. Removing takes out only what is still exactly as the
sample wrote it; a dashboard or routine the user changed is theirs and stays,
and so do their other routines.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import stages as stages_mod
from .models import Company
from .store import Store

ADDED = "sample: added"
REMOVED = "sample: removed"

DASHBOARD = "dashboards/monday-review.toml"
DASHBOARD_TITLE = "Monday review"
DASHBOARD_URL = "/d/monday-review"
ROUTINES = "routines.toml"
ROUTINE = "nudge-quiet-threads"
ROUTINE_TITLE = "Nudge quiet threads"
ROUTINE_URL = f"/yours/routines/{ROUTINE}"

# Built-in columns only, so it passes `check` in any folder, and every widget
# has rows with the sample account alone (an offer with a next step and tasks).
DASHBOARD_TEXT = '''\
# A sample dashboard, written with the sample account to show what a
# dashboard can be. Change anything you like: once you do, it is yours, and
# `hermitcrm sample remove` leaves it. How it works: hermitcrm help adjust-dashboards
title = "Monday review"
pin = true
description = "What to work on this week. The replies you owe are on Home."

[[widget]]
type = "count"
title = "Open deals"
scope = "companies"
filters = { stage = ["engaged", "discovery", "offer"] }

[[widget]]
type = "count"
title = "Tasks due this week"
scope = "tasks"
when = ["overdue", "today", "week"]

[[widget]]
type = "group"
title = "Deals by stage"
scope = "companies"
by = "stage"
filters = { stage = ["prospect", "engaged", "discovery", "offer"] }

[[widget]]
type = "list"
title = "Open deals, next step first"
scope = "companies"
filters = { stage = ["engaged", "discovery", "offer"] }
columns = ["name", "stage", "next_step", "next_step_due"]
sort = "next_step_due"

[[widget]]
type = "report"
title = "Pipeline and its value"
section = "funnel"
period = "30d"
'''

# Any channel, so it also picks up a quiet email thread. `paused = true` is
# written out: turning it on and off again leaves the block as it was.
ROUTINE_BLOCK = '''\
# A sample routine, written with the sample account. It is paused: nothing runs
# until you turn it on (Make it yours, then Routines). It only drafts; nothing is
# ever sent. `hermitcrm sample remove` takes this block out again, unless you
# changed it. How it works: hermitcrm help adjust-routines
[[routine]]
name = "nudge-quiet-threads"
title = "Nudge quiet threads"
paused = true
action = "draft"
select = "quiet_threads"
days = 7
limit = 10
prompt = """
Write a short, friendly follow-up to my last message: two or three sentences,
one easy question, no pressure and no "just checking in". Refer to what we last
talked about. Sign with my first name.
"""
'''

# The first comment line of each: still there, the file came from the sample
# (changed or not); gone, it is the user's own and nothing is said about it.
DASHBOARD_MARK = DASHBOARD_TEXT.splitlines()[0]


def dashboard_text(root: Path | str) -> str:
    """The sample dashboard with its stage lists in this folder's own stages:
    the open stages after the first, and all of them. The default stages give
    DASHBOARD_TEXT exactly, so the text is the same wherever it is compared."""
    stage_set = stages_mod.load(root)
    if stage_set == stages_mod.DEFAULT_STAGES:
        return DASHBOARD_TEXT
    open_ = stage_set.open
    return (DASHBOARD_TEXT
            .replace('["engaged", "discovery", "offer"]', json.dumps(open_[1:] or open_))
            .replace('["prospect", "engaged", "discovery", "offer"]', json.dumps(open_)))
ROUTINE_MARK = ROUTINE_BLOCK.splitlines()[0]

# What the messages call the two files.
LABELS = {DASHBOARD: f"the dashboard {DASHBOARD_TITLE}",
          ROUTINES: f"the routine {ROUTINE_TITLE}"}


class SampleError(Exception):
    pass


@dataclass
class Outcome:
    """What `add` or `remove` did: the sample companies, the files it wrote or
    took out (DASHBOARD, ROUTINES), and one sentence per thing it left alone."""

    companies: list[Company] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)

    @property
    def what(self) -> list[str]:
        """["Northwind Robotics", "the dashboard Monday review", ...]"""
        return [c.name for c in self.companies] + [LABELS[f] for f in self.files]


def samples(store: Store) -> list[Company]:
    return sorted((c for c in store.companies.values() if c.is_sample),
                  key=lambda c: c.name.lower())


def and_list(names: list[str]) -> str:
    """"a", "a and b", "a, b and c"."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


# ------------------------------------------------------------ the two files


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _routine_names(text: str) -> list[str] | None:
    """The names in a routines.toml, or None when it does not parse."""
    try:
        entries = tomllib.loads(text).get("routine", [])
    except tomllib.TOMLDecodeError:
        return None
    if not isinstance(entries, list):
        return None
    return [e.get("name") for e in entries if isinstance(e, dict)]


def write_extras(root: Path | str) -> tuple[list[str], list[str]]:
    """Write the sample dashboard and routine where nothing is in the way.

    Returns (the files written, one sentence per thing skipped). Commits
    nothing: `add` and `init --demo` commit them with the rest.
    """
    root = Path(root)
    wrote, kept = [], []
    dash = root / DASHBOARD
    if dash.exists():
        kept.append(f"{DASHBOARD} already exists, so the sample dashboard was not added.")
    else:
        try:
            dash.parent.mkdir(exist_ok=True)
            dash.write_text(dashboard_text(root), encoding="utf-8")
            wrote.append(DASHBOARD)
        except OSError as exc:
            kept.append(f"{DASHBOARD} could not be written ({exc.strerror or exc}).")
    file = root / ROUTINES
    text = _text(file) if file.exists() else ""
    names = _routine_names(text) if text is not None else None
    if names is None:
        kept.append(f"{ROUTINES} has a problem (hermitcrm check says which), so the "
                    "sample routine was not added.")
    elif ROUTINE in names:
        kept.append(f"{ROUTINES} already has a routine called {ROUTINE}, so the sample "
                    "routine was not added.")
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        new_text = text + ("\n" if text.strip() else "") + ROUTINE_BLOCK
        # routines.toml may list its routines in a form a `[[routine]]` block
        # cannot join (`routine = [{ ... }]`): then the file would stop parsing
        # and no routine would run. Only write what reads back with one more.
        after = _routine_names(new_text)
        if after is None or len(after) != len(names) + 1 or ROUTINE not in after:
            kept.append(f"{ROUTINES} lists its routines in a way the sample routine cannot "
                        "be added to (a routine = [...] list on one line?), so it was "
                        "not added.")
            return wrote, kept
        try:
            file.write_text(new_text, encoding="utf-8")
            wrote.append(ROUTINES)
        except OSError as exc:
            kept.append(f"{ROUTINES} could not be written ({exc.strerror or exc}).")
    return wrote, kept


def _without_routine(text: str) -> str | None:
    """routines.toml with the sample's block taken out, exactly as `write_extras`
    put it in; None when the block is not there word for word."""
    at = text.find(ROUTINE_BLOCK)
    if at < 0:
        return None
    start = at - 1 if text[:at].endswith("\n\n") else at  # the blank line before it
    return text[:start] + text[at + len(ROUTINE_BLOCK):]


def untouched(root: Path | str) -> set[str]:
    """The sample's files that are still only what the sample wrote: the
    dashboard word for word, routines.toml when it holds nothing else."""
    root = Path(root)
    out = set()
    if _text(root / DASHBOARD) == dashboard_text(root):
        out.add(DASHBOARD)
    text = _text(root / ROUTINES)
    if text is not None:
        rest = _without_routine(text)
        if rest is not None and not rest.strip():
            out.add(ROUTINES)
    return out


def untouched_urls(root: Path | str) -> set[str]:
    """The pages of the sample's dashboard and routine, while they are unchanged
    (the hub marks them)."""
    root = Path(root)
    out = set()
    if _text(root / DASHBOARD) == dashboard_text(root):
        out.add(DASHBOARD_URL)
    text = _text(root / ROUTINES)
    if text is not None and _without_routine(text) is not None:
        out.add(ROUTINE_URL)
    return out


@dataclass
class Removal:
    """What `remove` will do to the two files."""

    delete: list[str] = field(default_factory=list)  # files to delete
    routines_text: str | None = None                  # routines.toml's new text
    kept: list[str] = field(default_factory=list)

    @property
    def files(self) -> list[str]:
        """Every file this changes, the dashboard first."""
        changed = self.delete + ([ROUTINES] if self.routines_text is not None else [])
        return [f for f in (DASHBOARD, ROUTINES) if f in changed]


def plan_removal(root: Path | str) -> Removal:
    """Work out what of the dashboard and the routine is still the sample's."""
    root = Path(root)
    plan = Removal()
    text = _text(root / DASHBOARD)
    if text == dashboard_text(root):
        plan.delete.append(DASHBOARD)
    elif text is not None and DASHBOARD_MARK in text:
        plan.kept.append(f"Kept {DASHBOARD}: it changed since the sample wrote it, so "
                         "it is yours now.")
    text = _text(root / ROUTINES)
    if text is None:
        return plan
    rest = _without_routine(text)
    names = _routine_names(text) or []
    if rest is None:
        if ROUTINE in names and ROUTINE_MARK in text:
            plan.kept.append(f"Kept the routine {ROUTINE} in {ROUTINES}: it changed since "
                             "the sample wrote it (edited, or turned on), so it is yours now.")
        return plan
    if not rest.strip():
        plan.delete.append(ROUTINES)
        return plan
    others = _routine_names(rest)
    if others is None:
        plan.kept.append(f"Kept {ROUTINES} as it is: taking the sample routine out would "
                         "leave a file that does not parse. Take it out by hand.")
        return plan
    plan.routines_text = rest
    if others:
        plan.kept.append(f"Kept your other routine{'s' if len(others) != 1 else ''} in "
                         f"{ROUTINES}: {', '.join(str(n) for n in others)}.")
    return plan


# ------------------------------------------------------------ add and remove


def add(store: Store) -> Outcome:
    """Write the sample account, its dashboard and its routine (one commit).
    Refused while a sample company is loaded."""
    from .datafolder import _Demo

    if loaded := samples(store):
        raise SampleError(f"The sample account is already loaded: {loaded[0].name}.")
    demo = _Demo(store, store.today())
    with store.batch(ADDED), demo.backdated():
        slug = demo.northwind(sample=True)
        wrote, kept = write_extras(store.root)
        if wrote:
            store.notify(ADDED, wrote)
    return Outcome(companies=[store.companies[slug]], files=wrote, kept=kept)


def remove(store: Store) -> Outcome:
    """Delete every company marked as a sample, and the sample's dashboard and
    routine where they are unchanged (one commit). Nothing to do: an Outcome
    with no companies and no files, and no commit."""
    found = samples(store)
    plan = plan_removal(store.root)
    if found or plan.files:
        with store.batch(REMOVED):
            for company in found:
                store.delete_sample(company.slug)
            for name in plan.delete:
                (store.root / name).unlink()
            if plan.routines_text is not None:
                (store.root / ROUTINES).write_text(plan.routines_text, encoding="utf-8")
            folder = (store.root / DASHBOARD).parent
            if DASHBOARD in plan.delete and not any(folder.iterdir()):
                folder.rmdir()  # git keeps no empty folder either
            if plan.files:
                store.notify(REMOVED, plan.files)
    return Outcome(companies=found, files=plan.files, kept=plan.kept)
