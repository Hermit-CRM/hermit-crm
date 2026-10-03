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

"""Routines: small jobs in `routines.toml` that run after the daily sync.

Python decides who a routine is about: the follow-up radar (quiet threads,
replies owed) or the list filters. Only then, for `action = "draft"`, the AI
CLI that Enrich uses writes one message per record, with no tools, and returns
JSON that is checked like an Enrich proposal. A draft is a file in `drafts/`,
shown on Home under "Drafts from routines". Nothing is ever sent: the user
sends it, then clicks "I sent it" to log it, or discards it.
`action = "brief"` uses no AI: a short morning summary shown on Home that day.

The file is optional. Without it nothing runs and nothing shows. New routines
start paused; `preview` shows who would be picked, with no AI and no writes.
Each run that writes is one commit, `routine: <name>: <n> drafts`. The last
run of each routine (and the day's brief) lives in `inbox/.last-routines.json`,
gitignored like the BCC and calendar imports' run files, so a run that wrote
nothing makes no commit.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import filters, followups, messaging, task_types
from . import fields as fields_mod
from .enrich import EnrichError
from .models import (
    ValidationError, fmt_date, fmt_datetime, parse_datetime, slugify, unique_slug,
)
from .store import Store, build_file, load_config, normalise_body, split_file

logger = logging.getLogger("crm.routines")

FILE = "routines.toml"
DRAFTS_DIR = "drafts"
HANDLED_FILE = "handled.tsv"        # drafts closed (sent, discarded) or skipped by the AI
STATE_FILE = ".last-routines.json"  # in inbox/, next to the imports' run files

SELECTORS = ("quiet_threads", "replies_owed", "records")
ACTIONS = ("draft", "brief")
SCOPES = ("companies", "contacts")
DRAFT_CHANNELS = ("email", "linkedin")
KEYS = ("name", "title", "paused", "action", "select", "scope", "channel", "days",
        "filters", "prompt", "limit")
NOT_FOR_BRIEF = ("select", "scope", "channel", "days", "filters", "prompt", "limit")
PROMPT_LIMIT = 2000
DEFAULT_LIMIT = 10
MAX_LIMIT = 50
BODY_LIMIT = 5000
SUBJECT_LIMIT = 200
# What the AI sees of the record, the playbook and the templates, in characters.
RECORD_LIMIT, PLAYBOOK_LIMIT, TEMPLATES_LIMIT = 12_000, 8_000, 4_000
BRIEF_ITEMS = 10  # per section; the rest is a count
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Why a selected record gets no draft this time.
NO_CONTACT = "no contact to write to"
WAITING = "a draft is waiting on Home"
HANDLED = "already drafted for this thread"

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "channel": {"type": "string", "enum": list(DRAFT_CHANNELS),
                    "description": "the channel the message is written for"},
        "subject": {"type": "string",
                    "description": "a short subject for an email; empty for LinkedIn"},
        "body": {"type": "string",
                 "description": "the message itself, plain text, ready to paste; empty "
                                "only when skip says why no message should be sent"},
        "skip": {"type": "string",
                 "description": "empty, or one short line on why no message should be "
                                "sent at all"},
    },
    "required": ["channel", "subject", "body", "skip"],
    "additionalProperties": False,
}


class RoutineError(Exception):
    """A routine cannot run, or routines.toml cannot be changed as asked."""


class Rejected(Exception):
    """The AI's answer is not a usable draft; the record is skipped."""


# ------------------------------------------------------------------ the file


@dataclass
class Routine:
    name: str
    title: str
    action: str
    paused: bool = True
    select: str = ""
    scope: str = "companies"
    channel: str = ""
    days: int | None = None
    filters: dict = field(default_factory=dict)  # as filters.apply takes them
    prompt: str = ""
    limit: int = DEFAULT_LIMIT

    @property
    def state(self) -> str:
        return "paused" if self.paused else "on"


@dataclass
class Loaded:
    routines: list[Routine] = field(default_factory=list)  # the valid ones
    errors: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)  # every name in the file, valid or not
    present: bool = False

    def get(self, name: str) -> Routine | None:
        return next((r for r in self.routines if r.name == name), None)


def path(root: Path | str) -> Path:
    return Path(root) / FILE


def did_you_mean(word, choices) -> str:
    """ " (did you mean X?)" for a near miss, else ""."""
    choices = [str(c) for c in choices]
    close = difflib.get_close_matches(str(word), choices, n=1, cutoff=0.6)
    if not close and str(word):  # a short name for a long one: nudge, nudge-quiet-threads
        close = [c for c in choices if c.startswith(str(word))][:1]
    return f" (did you mean {close[0]}?)" if close else ""


def _toml_where(exc: tomllib.TOMLDecodeError) -> str:
    """"line 3: Invalid value" from tomllib's "Invalid value (at line 3, column 9)"."""
    text = str(exc)
    m = re.search(r"^(.*?)\s*\(at line (\d+), column \d+\)\s*$", text)
    if m:
        return f"line {m.group(2)}: {m.group(1)}"
    m = re.search(r"^(.*?)\s*\(at end of document\)\s*$", text)
    if m:
        return f"end of file: {m.group(1)}"
    return f"syntax: {text}"


def _field_defs(root: Path) -> list:
    """The folder's own fields; a broken fields.toml is check's to report."""
    try:
        return fields_mod.load(root)
    except (fields_mod.FieldError, OSError, tomllib.TOMLDecodeError):
        return []


def columns(root: Path | str, scope: str, config: dict | None = None) -> list:
    """The list page's filter columns for a scope, the folder's own fields included,
    so `filters` here means exactly what the Companies and Contacts filters mean."""
    from .web import company_columns, contact_columns  # web imports this module

    root = Path(root)
    defs = _field_defs(root)
    if scope == "contacts":
        return contact_columns(defs)
    config = config if config is not None else load_config(root)
    types = task_types.names(task_types.from_config(config.get("task_types")))
    return company_columns(defs, types)


def _check_filters(raw, cols: list) -> tuple[dict, list[str]]:
    """(filters as filters.apply takes them, problems)."""
    if not isinstance(raw, dict):
        return {}, ['filters must be a table, e.g. filters = { stage = "prospect" }']
    by_key = {c.key: c for c in cols}
    active: dict = {}
    problems: list[str] = []
    for key, value in raw.items():
        col = by_key.get(key)
        if col is None:
            problems.append(f"filters: unknown column {key}{did_you_mean(key, by_key)}")
            continue
        if isinstance(value, list) and col.kind != "enum":
            problems.append(f"filters: {key}: a list of values only works for a choice "
                            "column such as stage or country; give one value")
            continue
        values = value if isinstance(value, list) else [value]
        if not values or not all(isinstance(v, str) for v in values):
            problems.append(f'filters: {key}: write the value as text in quotes, e.g. '
                            f'"=70", ">70" or "-"')
            continue
        values = [v.strip() for v in values]
        if any(not v for v in values):
            problems.append(f'filters: {key}: empty value; "-" means empty, "*" any value')
            continue
        if col.kind == "enum":
            # next_type's choices include whatever types the data uses, so any goes.
            bad = [v for v in values if col.options and v not in col.options
                   and key != "next_type"]
            problems += [f"filters: {key}: unknown value {v}{did_you_mean(v, col.options)}"
                         for v in bad]
            if not bad:
                active[key] = values
            continue
        spec = values[0]
        if spec[0] in "<>" and len(spec) > 1 and col.kind in ("number", "date") \
                and filters._comparable(spec[1:].strip(), col.kind) is None:
            wanted = "a number" if col.kind == "number" else "a date as YYYY-MM-DD"
            problems.append(f"filters: {key}: {spec} needs {wanted} after {spec[0]}")
            continue
        active[key] = spec
    return active, problems


def _check(entry: dict, i: int, root: Path, config: dict | None,
           cols: dict) -> tuple[str, Routine | None, list[str]]:
    """(where, the routine or None, problems) for one [[routine]] table."""
    name = entry.get("name")
    where = (f"routine {name.strip()}" if isinstance(name, str) and name.strip()
             else f"routine {i}")
    problems: list[str] = []
    for key in entry:
        if key not in KEYS:
            problems.append(f"unknown key {key}{did_you_mean(key, KEYS)}")
    if not isinstance(name, str) or not name.strip():
        problems.append("needs a name: lowercase letters, digits and dashes, "
                        "e.g. nudge-quiet-threads")
        name = ""
    elif not NAME_RE.match(name):
        problems.append(f"name {name} must be lowercase letters, digits and dashes, "
                        f"e.g. {slugify(name, default='my-routine')}")
    title = entry.get("title", "")
    if not isinstance(title, str):
        problems.append("title must be text")
        title = ""
    paused = entry.get("paused", True)
    if not isinstance(paused, bool):
        problems.append("paused must be true or false")
    action = entry.get("action")
    if action is None:
        problems.append("needs an action: draft or brief")
    elif action not in ACTIONS:
        problems.append(f"unknown action {action}{did_you_mean(action, ACTIONS)}; "
                        "use draft or brief")

    routine = Routine(name=name, action=str(action or ""),
                      title=(title.strip() or name.replace("-", " ").capitalize()),
                      paused=paused if isinstance(paused, bool) else True)
    if action == "brief":
        problems += [f"{key} is not used by a brief; remove it"
                     for key in NOT_FOR_BRIEF if key in entry]
    elif action == "draft":
        select = entry.get("select")
        if select is None:
            problems.append("needs select: quiet_threads, replies_owed or records")
        elif select not in SELECTORS:
            problems.append(f"unknown select {select}{did_you_mean(select, SELECTORS)}; "
                            "use quiet_threads, replies_owed or records")
        routine.select = str(select or "")
        prompt = entry.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            problems.append("needs a prompt: what the AI should write")
        elif len(prompt) > PROMPT_LIMIT:
            problems.append(f"prompt is {len(prompt)} characters; the limit is "
                            f"{PROMPT_LIMIT}")
        routine.prompt = prompt.strip() if isinstance(prompt, str) else ""
        limit = entry.get("limit", DEFAULT_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int) \
                or not 1 <= limit <= MAX_LIMIT:
            problems.append(f"limit must be a whole number from 1 to {MAX_LIMIT}")
        else:
            routine.limit = limit
        channel = entry.get("channel", "")
        if channel and channel not in DRAFT_CHANNELS:
            problems.append(f"unknown channel {channel}"
                            f"{did_you_mean(channel, DRAFT_CHANNELS)}; use email or linkedin")
        routine.channel = channel if channel in DRAFT_CHANNELS else ""
        if "days" in entry:
            days = entry["days"]
            if select == "records":
                problems.append("days is only for quiet_threads and replies_owed")
            elif isinstance(days, bool) or not isinstance(days, int) or days < 0:
                problems.append("days must be a whole number, 0 or more")
            else:
                routine.days = days
        if "scope" in entry:
            scope = entry["scope"]
            if select in ("quiet_threads", "replies_owed"):
                problems.append("scope is only for records (quiet_threads and "
                                "replies_owed always look at companies)")
            elif scope not in SCOPES:
                problems.append(f"unknown scope {scope}{did_you_mean(scope, SCOPES)}; "
                                "use companies or contacts")
            else:
                routine.scope = scope
        if "filters" in entry and select in SELECTORS:
            scope = routine.scope if select == "records" else "companies"
            if scope not in cols:
                cols[scope] = columns(root, scope, config)
            routine.filters, bad = _check_filters(entry["filters"], cols[scope])
            problems += bad
    return where, (None if problems else routine), problems


def parse(text: str, root: Path | str, config: dict | None = None) -> Loaded:
    """Every routine in the text, and a message per problem."""
    root = Path(root)
    loaded = Loaded(present=True)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        loaded.errors.append(f"{FILE}: {_toml_where(exc)}")
        return loaded
    for key in data:
        if key != "routine":
            loaded.errors.append(f"{FILE}: top level: unknown key {key}"
                                 f"{did_you_mean(key, ['routine'])}")
    entries = data.get("routine", [])
    if isinstance(entries, dict) or not isinstance(entries, list):
        loaded.errors.append(f"{FILE}: top level: write each routine as a [[routine]] "
                             "table")
        entries = []
    cols: dict = {}
    seen: set[str] = set()
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            loaded.errors.append(f"{FILE}: routine {i}: must be a [[routine]] table")
            continue
        where, routine, problems = _check(entry, i, root, config, cols)
        name = entry.get("name")
        if isinstance(name, str) and name.strip():
            if name in seen:
                problems.append(f"the name {name} is used twice; names must be unique")
                routine = None
            seen.add(name)
            loaded.names.append(name)
        loaded.errors += [f"{FILE}: {where}: {p}" for p in problems]
        if routine is not None:
            loaded.routines.append(routine)
    return loaded


def load(root: Path | str, config: dict | None = None) -> Loaded:
    """routines.toml, read fresh: an agent's edit counts on the next call."""
    file = path(root)
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Loaded()
    except OSError as exc:
        return Loaded(errors=[f"{FILE}: cannot be read: {exc}"], present=True)
    return parse(text, root, config)


def validate(root: Path | str) -> list[str]:
    """Problems in routines.toml, one line each (contract for `hermitcrm check`)."""
    return load(root).errors


def problems_for(loaded: Loaded, name: str) -> list[str]:
    """The messages about one routine, plus those about the whole file."""
    mine = f"{FILE}: routine {name}:"
    return [e for e in loaded.errors
            if e.startswith(mine) or not e.startswith(f"{FILE}: routine ")]


def describe(routine: Routine, config: dict | None = None) -> str:
    """What a routine does, in one or two plain sentences."""
    if routine.action == "brief":
        return ("Writes a short morning summary on Home: meetings today, tasks due and "
                "replies you owe. No AI.")
    config = config or {}
    on = f" on {routine.channel}" if routine.channel else ""
    if routine.select == "quiet_threads":
        days = routine.days if routine.days is not None else int(
            config.get("followup_nudge_days", 5))
        who = (f"Picks people you messaged{on} at least {days} "
               f"day{'s' if days != 1 else ''} ago who have not replied")
    elif routine.select == "replies_owed":
        days = routine.days if routine.days is not None else int(
            config.get("followup_reply_days", 1))
        who = (f"Picks people who wrote to you{on} at least {days} "
               f"day{'s' if days != 1 else ''} ago and have no answer from you yet")
    else:
        who = f"Picks {routine.scope}" if routine.filters else \
            f"Picks every one of your {routine.scope}"
    if routine.filters:
        shown = ", ".join(f"{k} {' or '.join(v) if isinstance(v, list) else v}"
                          for k, v in routine.filters.items())
        who += f" where {shown}"
    return (f"{who}. Your AI CLI drafts one message for each, at most {routine.limit} "
            "per run. Drafts wait on Home; nothing is sent.")


# --------------------------------------------------------------- turning on/off


_ROUTINE_HEADER = re.compile(r"^\s*\[\[\s*routine\s*\]\]\s*(#.*)?$")
_ANY_HEADER = re.compile(r"^\s*\[")
_NAME_LINE = re.compile(r"""^(\s*)name\s*=\s*(["'])(.*?)\2\s*(#.*)?$""")
_PAUSED_LINE = re.compile(r"^(\s*paused\s*=\s*)(true|false)(\s*(?:#.*)?)$")


def _top_level_lines(lines: list[str]) -> list[bool]:
    """Per line: True unless it sits inside a multi-line string."""
    out, inside = [], ""
    for line in lines:
        out.append(not inside)
        for quote in ('"""', "'''"):
            if inside in ("", quote) and line.count(quote) % 2 == 1:
                inside = "" if inside else quote
    return out


def with_paused(text: str, name: str, paused: bool) -> str:
    """The text with one routine's `paused` set, every other byte as it was.

    Changes the `paused = ...` line of that routine's [[routine]] table, or adds
    one under its `name` line. The result is parsed and compared with the
    original, so a file this cannot edit safely is refused rather than damaged.
    """
    value = "true" if paused else "false"
    lines = text.splitlines(keepends=True)
    usable = _top_level_lines(lines)
    starts = [i for i, line in enumerate(lines) if usable[i] and _ROUTINE_HEADER.match(line)]
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        body = []  # the routine's own keys: up to its first sub-table
        for i in range(start + 1, end):
            if usable[i] and _ANY_HEADER.match(lines[i]):
                break
            body.append(i)
        name_at = next((i for i in body if usable[i] and (m := _NAME_LINE.match(
            lines[i].rstrip("\r\n"))) and m.group(3) == name), None)
        if name_at is None:
            continue
        paused_at = next((i for i in body if usable[i]
                          and _PAUSED_LINE.match(lines[i].rstrip("\r\n"))), None)
        if paused_at is not None:
            line = lines[paused_at]
            ending = line[len(line.rstrip("\r\n")):]
            m = _PAUSED_LINE.match(line.rstrip("\r\n"))
            lines[paused_at] = m.group(1) + value + m.group(3) + ending
        else:
            line = lines[name_at]
            ending = line[len(line.rstrip("\r\n")):] or "\n"
            indent = _NAME_LINE.match(line.rstrip("\r\n")).group(1)
            if not line.endswith(("\n", "\r")):
                lines[name_at] = line + ending
            lines.insert(name_at + 1, f"{indent}paused = {value}{ending}")
        new = "".join(lines)
        _same_but_paused(text, new, name, paused)
        return new
    raise RoutineError(f"no routine named {name} in {FILE}")


def _same_but_paused(old: str, new: str, name: str, paused: bool) -> None:
    try:
        before, after = tomllib.loads(old), tomllib.loads(new)
    except tomllib.TOMLDecodeError as exc:
        raise RoutineError(f"{FILE}: {_toml_where(exc)}") from None
    for entry in before.get("routine", []):
        if isinstance(entry, dict) and entry.get("name") == name:
            entry["paused"] = paused
    if before != after:
        raise RoutineError(f"could not change paused for {name} safely; edit {FILE} "
                           "by hand")


def set_paused(store: Store, name: str, paused: bool, config: dict | None = None) -> bool:
    """Turn a routine on (paused=False) or off; one commit. False if already so.

    A routine with problems is not turned on: it would only fail every morning.
    """
    root = store.root
    loaded = load(root, config)
    if not loaded.present:
        raise RoutineError(f"there is no {FILE} in the data folder")
    if name not in loaded.names:
        raise RoutineError(f"no routine named {name} in {FILE}"
                           f"{did_you_mean(name, loaded.names)}")
    if not paused:
        problems = problems_for(loaded, name)
        if problems:
            raise RoutineError("fix these first: " + "; ".join(problems))
    file = path(root)
    with store.lock:
        text = file.read_text(encoding="utf-8")
        try:
            entries = tomllib.loads(text).get("routine", [])
        except tomllib.TOMLDecodeError as exc:
            raise RoutineError(f"{FILE}: {_toml_where(exc)}") from None
        entry = next((e for e in entries if isinstance(e, dict) and e.get("name") == name),
                     {})
        if entry.get("paused", True) is paused:  # absent means paused
            return False
        new = with_paused(text, name, paused)
        if new == text:
            return False
        file.write_text(new, encoding="utf-8")
        store.notify(f"routine: {name}: turned {'off' if paused else 'on'}", [FILE])
    return True


# ---------------------------------------------------------------- selection


@dataclass
class Pick:
    """One record a routine selected, and whether it gets a draft this time."""

    company: object               # Company
    contact: object | None        # Contact, or None when there is nobody to write to
    record: str                   # "acme", or "acme/jane-doe" for scope contacts
    basis: str                    # the interaction this follows up; "" for none
    reason: str                   # why it was selected
    channel: str                  # what the draft is written for
    status: str = ""              # "" = gets a draft; else why not

    @property
    def who(self) -> str:
        if self.contact is not None:
            return f"{self.contact.name} ({self.company.name})"
        return self.company.name

    @property
    def url(self) -> str:
        base = f"/companies/{self.company.slug}"
        return f"{base}/contacts/{self.contact.slug}" if self.contact is not None else base


def _person(company, slug: str = ""):
    """The named contact, else the one last in touch, else the first by name."""
    for candidate in (slug, company.latest_contact_slug):
        if candidate and candidate in company.contacts:
            return company.contacts[candidate]
    people = sorted(company.contacts.values(), key=lambda c: c.name.lower())
    return people[0] if people else None


def _channel(routine: Routine, contact, thread: str = "") -> str:
    if routine.channel:
        return routine.channel
    if thread in DRAFT_CHANNELS:
        return thread
    return "email" if contact is not None and contact.email else "linkedin"


def _ago(days: int) -> str:
    return "today" if days == 0 else ("1 day ago" if days == 1 else f"{days} days ago")


def _touch_reason(latest, today: date) -> str:
    if latest is None or latest.date is None:
        return "never contacted"
    return f"last touch {_ago((today - latest.date.date()).days)}"


def select(store: Store, routine: Routine, config: dict | None = None,
           today: date | None = None) -> list[Pick]:
    """Everyone the routine selects now, in order, each with a status. No AI, no writes."""
    if routine.action != "draft":
        return []
    root = store.root
    config = config if config is not None else load_config(root)
    today = today or store.today()
    picks: list[Pick] = []
    if routine.select in ("quiet_threads", "replies_owed"):
        reply = routine.select == "replies_owed"
        days = routine.days
        rows = followups.radar(
            store, today,
            reply_after=days if reply and days is not None else int(
                config.get("followup_reply_days", 1)),
            nudge_after=days if not reply and days is not None else int(
                config.get("followup_nudge_days", 5)))
        kind = followups.REPLY if reply else followups.NUDGE
        rows = [r for r in rows if r.kind == kind
                and (not routine.channel or r.interaction.channel == routine.channel)]
        if routine.filters:
            keep = {c.slug for c in filters.apply(
                [r.company for r in rows], columns(root, "companies", config),
                routine.filters)}
            rows = [r for r in rows if r.company.slug in keep]
        for r in rows:
            contact = _person(r.company, r.interaction.contact)
            picks.append(Pick(r.company, contact, r.company.slug, r.interaction.id,
                              f"{r.reason}, {_ago(r.days)}",
                              _channel(routine, contact, r.interaction.channel)))
    elif routine.select == "records" and routine.scope == "contacts":
        from .web import ContactRow  # the Contacts page's rows: same filter values

        rows = [ContactRow(c, ct) for c in store.companies.values()
                for ct in c.contacts.values()]
        rows.sort(key=lambda r: (r.name.lower(), r.company_name.lower()))
        rows = filters.apply(rows, columns(root, "contacts", config), routine.filters)
        for row in rows:
            company, contact = row.company, row.contact
            touches = [i for i in company.interactions
                       if i.date and i.is_touch and i.contact == contact.slug]
            latest = max(touches, key=lambda i: i.date) if touches else None
            picks.append(Pick(company, contact, f"{company.slug}/{contact.slug}",
                              latest.id if latest else "", _touch_reason(latest, today),
                              _channel(routine, contact)))
    elif routine.select == "records":
        companies = sorted(store.companies.values(), key=lambda c: c.name.lower())
        companies = filters.apply(companies, columns(root, "companies", config),
                                  routine.filters)
        for company in companies:
            latest = followups.latest(company)
            contact = _person(company)
            picks.append(Pick(company, contact, company.slug, latest.id if latest else "",
                              _touch_reason(latest, today), _channel(routine, contact)))

    waiting = {(d.routine, d.record) for d in drafts(root)}
    done = handled(root)
    fresh = 0
    for p in picks:
        if p.contact is None:
            p.status = NO_CONTACT
        elif (routine.name, p.record) in waiting:
            p.status = WAITING
        elif (routine.name, p.record, p.basis) in done:
            p.status = HANDLED
        elif fresh >= routine.limit:
            p.status = f"over this run's limit of {routine.limit}"
        else:
            fresh += 1
    return picks


# ------------------------------------------------------------------- drafts


@dataclass
class Draft:
    id: str
    routine: str
    made: datetime | None
    record: str
    company: str
    contact: str
    channel: str
    subject: str
    basis: str
    reason: str
    body: str

    @property
    def url(self) -> str:
        base = f"/companies/{self.company}"
        return f"{base}/contacts/{self.contact}" if self.contact else base


def drafts_dir(root: Path | str) -> Path:
    return Path(root) / DRAFTS_DIR


def _draft_path(root: Path | str, draft_id: str) -> Path | None:
    if not re.fullmatch(r"[0-9A-Za-z-]+", draft_id or ""):
        return None
    return drafts_dir(root) / f"{draft_id}.md"


def _read_draft(file: Path) -> Draft:
    meta, body = split_file(file.read_text(encoding="utf-8"))
    text = lambda key: "" if meta.get(key) is None else str(meta.get(key))  # noqa: E731
    return Draft(id=file.stem, routine=text("routine"), made=parse_datetime(meta.get("made")),
                 record=text("record"), company=text("company"), contact=text("contact"),
                 channel=text("channel"), subject=text("subject"), basis=text("basis"),
                 reason=text("reason"), body=body)


def drafts(root: Path | str) -> list[Draft]:
    """Every open draft, newest first."""
    folder = drafts_dir(root)
    out = []
    for file in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        try:
            out.append(_read_draft(file))
        except (ValidationError, ValueError, OSError) as exc:
            logger.warning("unreadable draft %s: %s", file, exc)
    return sorted(out, key=lambda d: (d.made or datetime.min, d.id), reverse=True)


def get_draft(root: Path | str, draft_id: str) -> Draft | None:
    file = _draft_path(root, draft_id)
    if file is None or not file.exists():
        return None
    return _read_draft(file)


def write_draft(root: Path | str, draft: Draft) -> Draft:
    """Write a new draft file; its id comes from when, which routine and whom."""
    folder = drafts_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    when = draft.made or datetime.now()
    base = f"{when:%Y-%m-%dT%H%M}-{draft.routine}-{slugify(draft.record, default='record')}"
    draft.id = unique_slug(base, {p.stem for p in folder.glob("*.md")})
    meta = {"routine": draft.routine, "made": draft.made, "record": draft.record,
            "company": draft.company, "contact": draft.contact, "channel": draft.channel,
            "subject": draft.subject, "basis": draft.basis, "reason": draft.reason}
    (folder / f"{draft.id}.md").write_text(build_file(meta, normalise_body(draft.body)),
                                           encoding="utf-8")
    return draft


def handled(root: Path | str) -> set[tuple[str, str, str]]:
    """(routine, record, basis) of every draft closed, and every record the AI declined."""
    file = drafts_dir(root) / HANDLED_FILE
    if not file.exists():
        return set()
    out = set()
    for line in file.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0] and parts[1]:
            out.add((parts[0], parts[1], parts[2]))
    return out


def _mark_handled(root: Path | str, routine: str, record: str, basis: str, what: str,
                  when: datetime) -> None:
    folder = drafts_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    clean = lambda s: " ".join(str(s).split())  # noqa: E731
    with (folder / HANDLED_FILE).open("a", encoding="utf-8") as fh:
        fh.write("\t".join([routine, record, basis, clean(what), fmt_datetime(when)]) + "\n")


def close_draft(store: Store, draft_id: str, sent: bool, subject: str | None = None,
                body: str | None = None) -> tuple[Draft, object | None]:
    """Log a draft as sent (an outbound interaction) or discard it; one commit.

    Either way the draft leaves Home and is remembered, so the routine does not
    write it again for the same thread. Returns (draft, interaction or None).
    """
    root = store.root
    with store.lock:
        draft = get_draft(root, draft_id)
        if draft is None:
            raise ValidationError({"draft": f"unknown draft {draft_id!r}"})
        what = "sent" if sent else "discarded"
        message = f"routine: {draft.routine}: draft for {draft.record} {what}"
        interaction = None
        with store.batch(message):
            if sent:
                interaction = store.create_interaction(
                    draft.company, channel=draft.channel, direction="out",
                    contact=draft.contact,
                    subject=draft.subject if subject is None else subject,
                    body=draft.body if body is None else body)
            _draft_path(root, draft.id).unlink(missing_ok=True)
            _mark_handled(root, draft.routine, draft.record, draft.basis, what, store.now())
            store.notify(message, [DRAFTS_DIR])
    return draft, interaction


# ----------------------------------------------------------------- the AI step


def _templates(root: Path, language: str) -> str:
    """The folder's own messages.toml wording in the draft language, as lines."""
    file = Path(root) / messaging.MESSAGES_FILE
    if not file.exists():
        return ""
    try:
        with open(file, "rb") as fh:
            own = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    table = (own.get("languages") or {}).get(language)
    if not isinstance(table, dict):
        return ""
    lines = []
    for key, value in table.items():
        if isinstance(value, dict):
            lines += [f"{key}.{k}: {v}" for k, v in value.items()]
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)[:TEMPLATES_LIMIT]


def draft_prompt(store: Store, routine: Routine, pick: Pick, config: dict) -> str:
    """Everything the AI needs for one draft: the record, the playbook, the user's
    templates in the draft language, and the routine's own instructions."""
    from .cli import cmd_show  # `hermitcrm show`, the agreed way to read one account

    root = store.root
    company, contact = pick.company, pick.contact
    messages = messaging.load_messages(root)
    language = messaging.draft_language(company, contact, messages=messages)
    language_name = messaging.language_names(messages).get(language, language)
    channel = (f"{pick.channel}: write a short subject line too" if pick.channel == "email"
               else f"{pick.channel}: no subject; keep it short enough for a "
                    "LinkedIn message")
    owner = str(config.get("owner_name") or "").strip()
    person = (f"{contact.name}" + (f", {contact.title}" if contact.title else "")
              + f" at {company.name}")
    record = cmd_show(store, company.slug, bodies=3)[:RECORD_LIMIT]
    parts = [
        "You draft one sales message for a person to review and send themselves. "
        "Nothing you write is sent automatically; it waits in their CRM until they "
        "decide.",
        f"Their instructions (routine \"{routine.title}\"):\n{routine.prompt}",
        f"Write to: {person}.\nWhy now: {pick.reason}.\nChannel: {channel}.\n"
        f"Language: {language_name} (the CRM's choice for this person; if the "
        "conversation so far is in another language, write in that one)."
        + (f"\nSign as: {owner.split()[0]}." if owner else ""),
        f"--- the record (hermitcrm show {company.slug}) ---\n{record}\n--- end ---",
    ]
    playbook = Path(root) / "MESSAGING.md"
    try:
        text = playbook.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    if text:
        parts.append("--- their outreach playbook (MESSAGING.md) ---\n"
                     f"{text[:PLAYBOOK_LIMIT]}\n--- end ---")
    templates = _templates(root, language)
    if templates:
        parts.append(f"--- their message templates in {language_name} (messages.toml), "
                     f"for tone and wording ---\n{templates}\n--- end ---")
    parts.append(
        "Rules: plain text, no Markdown, no placeholders except [square brackets] for "
        "what only they can know; never invent facts, numbers or meetings; keep it "
        "short. If no message should be sent at all (they asked not to be contacted, "
        "the deal is closed), leave body empty and say why in skip.")
    return "\n\n".join(parts) + "\n"


@dataclass
class Answer:
    channel: str = ""
    subject: str = ""
    body: str = ""
    skip: str = ""


def clean_answer(data, routine: Routine, pick: Pick) -> Answer:
    """Check the AI's JSON like an Enrich proposal; Rejected names what was wrong."""
    if not isinstance(data, dict):
        raise Rejected("the AI returned no JSON object")
    skip = data.get("skip") or ""
    body = data.get("body") or ""
    subject = data.get("subject") or ""
    if not all(isinstance(v, str) for v in (skip, body, subject)):
        raise Rejected("the AI returned something other than text")
    skip, body = " ".join(skip.split()), normalise_body(body).strip("\n")
    if not body:
        if skip:
            return Answer(skip=skip[:200])
        raise Rejected("the AI returned an empty message")
    if len(body) > BODY_LIMIT:
        raise Rejected(f"the message is over {BODY_LIMIT} characters")
    if "```" in body or (body.startswith("{") and body.endswith("}")):
        raise Rejected("the answer looks like code, not a message")
    channel = data.get("channel")
    if routine.channel or channel not in DRAFT_CHANNELS:
        channel = pick.channel
    subject = " ".join(subject.split())[:SUBJECT_LIMIT] if channel == "email" else ""
    return Answer(channel=channel, subject=subject, body=body + "\n")


def ask_ai(store: Store, routine: Routine, pick: Pick, enricher, config: dict) -> Answer:
    """One AI run for one record, with no tools. Raises Rejected or EnrichError."""
    data = enricher.runner(draft_prompt(store, routine, pick, config), DRAFT_SCHEMA,
                           tools="")
    return clean_answer(data, routine, pick)


def default_enricher(config: dict):
    """The Enrich CLI from config.toml, on the medium tier whatever ai_tier says."""
    from .web import build_enricher  # web imports this module

    return build_enricher(config).with_tier("medium")


# ------------------------------------------------------------- runs and state


def state_path(root: Path | str) -> Path:
    return Path(root) / "inbox" / STATE_FILE


def read_state(root: Path | str) -> dict:
    try:
        data = json.loads(state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_run(root: Path | str, name: str, at: datetime, ok: bool, summary: str = "",
               error: str = "", brief: dict | None = None) -> None:
    """Remember a routine's last run (and the day's brief) without a commit."""
    file = state_path(root)
    file.parent.mkdir(parents=True, exist_ok=True)
    state = read_state(root)
    entry = {"at": fmt_datetime(at), "ok": ok, "summary": summary, "error": error}
    if brief is not None:
        entry["brief"] = brief
    state[name] = entry
    tmp = file.with_name(file.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, file)


def last_run_text(entry: dict | None) -> str:
    if not entry:
        return "never run"
    at = str(entry.get("at", "")).replace("T", " ")
    if not entry.get("ok"):
        return f"last run {at} failed: {entry.get('error', '')}"
    return f"last run {at}: {entry.get('summary', '')}"


@dataclass
class RunResult:
    name: str
    drafts: int = 0
    skipped: int = 0
    lines: list[str] = field(default_factory=list)
    commit: bool = False
    brief: dict | None = None

    def summary(self) -> str:
        if self.brief is not None:
            return brief_summary(self.brief)
        text = "1 draft" if self.drafts == 1 else f"{self.drafts} drafts"
        return text + (f", {self.skipped} skipped" if self.skipped else "")


def run(store: Store, routine: Routine, apply: bool = False, enricher=None,
        config: dict | None = None, now: datetime | None = None) -> RunResult:
    """One routine. Without apply: who it would pick, with no AI and no writes.

    With apply: one AI run per picked record; each usable answer becomes a
    draft, and the run is one commit. A bad answer skips that record with a
    line saying why. Raises RoutineError when the AI CLI is missing.
    """
    root = store.root
    config = config if config is not None else load_config(root)
    now = now or store.now()
    result = RunResult(routine.name)
    if routine.action == "brief":
        result.brief = make_brief(store, config, now)
        result.lines = render_brief(result.brief).splitlines()
        if apply:
            record_run(root, routine.name, now, True, result.summary(), brief=result.brief)
        return result
    selected = select(store, routine, config, now.date())
    picks = [p for p in selected if not p.status]
    result.lines = [f"not this time: {p.who} | {p.status}" for p in selected if p.status]
    if not apply:
        result.lines = [f"would draft: {p.who} | {p.reason} | {p.channel}"
                        for p in picks] + result.lines
        return result
    if picks:
        enricher = enricher if enricher is not None else default_enricher(config)
        if not enricher.available:
            raise RoutineError(enricher.unavailable_reason())
    wrote = False
    try:
        for pick in picks:
            try:
                answer = ask_ai(store, routine, pick, enricher, config)
            except (Rejected, EnrichError) as exc:
                result.skipped += 1
                result.lines.append(f"skipped {pick.who}: {exc}")
                continue
            with store.lock:
                if answer.skip:
                    _mark_handled(root, routine.name, pick.record, pick.basis,
                                  f"skipped: {answer.skip}", now)
                    result.skipped += 1
                    result.lines.append(f"skipped {pick.who}: the AI says {answer.skip}")
                else:
                    draft = write_draft(root, Draft(
                        id="", routine=routine.name, made=now, record=pick.record,
                        company=pick.company.slug,
                        contact=pick.contact.slug if pick.contact is not None else "",
                        channel=answer.channel, subject=answer.subject, basis=pick.basis,
                        reason=pick.reason, body=answer.body))
                    result.drafts += 1
                    result.lines.append(f"drafted: {pick.who} | {answer.channel} | "
                                        f"{draft.id}")
                wrote = True
    finally:  # a crash halfway still commits the drafts already written
        if wrote:
            store.notify(f"routine: {routine.name}: {result.summary()}", [DRAFTS_DIR])
            result.commit = True
    record_run(root, routine.name, now, True, result.summary())
    return result


def try_first(store: Store, routine: Routine, enricher=None, config: dict | None = None,
              now: datetime | None = None) -> tuple[Pick | None, Answer | None]:
    """"Try the AI on the first one": one draft, shown, never saved."""
    config = config if config is not None else load_config(store.root)
    now = now or store.now()
    pick = next((p for p in select(store, routine, config, now.date()) if not p.status), None)
    if pick is None:
        return None, None
    enricher = enricher if enricher is not None else default_enricher(config)
    if not enricher.available:
        raise RoutineError(enricher.unavailable_reason())
    return pick, ask_ai(store, routine, pick, enricher, config)


def run_all(store: Store, config: dict | None = None, apply: bool = False, enricher=None,
            names: list[str] | None = None) -> list[str]:
    """Every routine that is on (or the ones named), each on its own: one that fails
    is one line and the next runs anyway. Returns the report lines; [] without a
    routines.toml. No chaining: a routine's commit never starts another one."""
    root = store.root
    config = config if config is not None else load_config(root)
    loaded = load(root, config)
    if not loaded.present:
        return []
    out = []
    if loaded.errors and names is None:
        out.append(f"{FILE} has {len(loaded.errors)} problem(s); run hermitcrm check. "
                   "Routines with problems do not run.")
    chosen = ([r for r in loaded.routines if r.name in names] if names is not None
              else [r for r in loaded.routines if not r.paused])
    if not chosen and names is None:
        out.append("No routine is on.")
    shared = {"enricher": enricher}

    def ai():
        if shared["enricher"] is None:
            shared["enricher"] = default_enricher(config)
        return shared["enricher"]

    for routine in chosen:
        try:
            needs_ai = apply and routine.action == "draft"
            result = run(store, routine, apply=apply, enricher=ai() if needs_ai else None,
                         config=config)
        except Exception as exc:  # one routine never stops the sync or the others
            message = str(exc) if isinstance(exc, RoutineError) else \
                f"{type(exc).__name__}: {exc}"
            logger.warning("routine %s failed: %s", routine.name, message)
            if apply:
                try:
                    record_run(root, routine.name, store.now(), False, error=message)
                except OSError:
                    pass
            out.append(f"{routine.name}: failed: {message}")
            continue
        if not apply and routine.action == "draft":
            n = sum(1 for line in result.lines if line.startswith("would draft"))
            out.append(f"{routine.name}: would draft for {n} record{'s' if n != 1 else ''} "
                       "(dry run, no AI)")
        else:
            out.append(f"{routine.name}: {result.summary()}")
        out += [f"  {line}" for line in result.lines]
    return out


# -------------------------------------------------------------------- briefs


def make_brief(store: Store, config: dict, now: datetime) -> dict:
    """Meetings today, tasks due and replies owed, as links. No AI."""
    from . import bcc, calendar_sync

    today = now.date()
    meetings = []
    for row in calendar_sync.read_upcoming(bcc.Inbox(store.root), now, days=1):
        if row["start"].date() != today:
            continue
        slugs = [str(e.get("slug", "")) for e in row.get("companies") or []]
        known = [store.companies[s] for s in slugs if s in store.companies]
        title = str(row.get("title") or "(no title)")
        when = "all day" if row.get("all_day") else f"{row['start']:%H:%M}"
        names = f" ({', '.join(c.name for c in known)})" if known else ""
        meetings.append({"text": f"{when} {title}{names}",
                         "url": f"/companies/{known[0].slug}" if known else "/calendar"})
    tasks = []
    for company in sorted(store.companies.values(), key=lambda c: c.name.lower()):
        if company.is_closed:
            continue
        for todo in company.open_todos():
            if todo.due and todo.due <= today:
                who = todo.contact.name if todo.contact else company.name
                late = "overdue: " if todo.due < today else ""
                url = (f"/companies/{company.slug}/contacts/{todo.contact.slug}"
                       if todo.contact else f"/companies/{company.slug}")
                tasks.append({"text": f"{late}{todo.text or '(no text)'} ({who})",
                              "url": url, "due": fmt_date(todo.due)})
    tasks.sort(key=lambda t: t.pop("due"))
    owed = [{"text": f"{r.who or r.name} at {r.name} wrote {_ago(r.days)}: {r.summary}",
             "url": f"/companies/{r.slug}"}
            for r in followups.radar(store, today,
                                     reply_after=int(config.get("followup_reply_days", 1)),
                                     nudge_after=int(config.get("followup_nudge_days", 5)))
            if r.kind == followups.REPLY]
    sections = []
    for title, items in (("Meetings today", meetings), ("Tasks due", tasks),
                         ("Replies you owe", owed)):
        sections.append({"title": title, "items": items[:BRIEF_ITEMS],
                         "more": max(0, len(items) - BRIEF_ITEMS), "count": len(items)})
    return {"date": fmt_date(today), "at": fmt_datetime(now), "sections": sections}


def brief_summary(brief: dict) -> str:
    counts = {s["title"]: s.get("count", 0) for s in brief.get("sections", [])}
    meetings, tasks, owed = (counts.get(t, 0) for t in
                             ("Meetings today", "Tasks due", "Replies you owe"))
    return (f"{meetings} meeting{'' if meetings == 1 else 's'}, "
            f"{tasks} task{'' if tasks == 1 else 's'} due, "
            f"{owed} repl{'y' if owed == 1 else 'ies'} owed")


def render_brief(brief: dict) -> str:
    lines = [f"Brief for {brief.get('date', '')}: {brief_summary(brief)}"]
    for section in brief.get("sections", []):
        if not section.get("items"):
            continue
        lines.append(f"{section['title']}:")
        lines += [f"- {item['text']}" for item in section["items"]]
        if section.get("more"):
            lines.append(f"- and {section['more']} more")
    return "\n".join(lines)


# --------------------------------------------------------------- for the pages


def home_context(store: Store, config: dict | None = None) -> dict:
    """What Home shows: open drafts (with names to show) and today's briefs.

    Without routines.toml and drafts/ both lists are empty and Home is as it was.
    """
    root = store.root
    loaded = load(root, config)
    titles = {r.name: r.title for r in loaded.routines}
    rows = []
    for d in drafts(root):
        company = store.companies.get(d.company)
        contact = company.contacts.get(d.contact) if company and d.contact else None
        rows.append({"draft": d, "routine_title": titles.get(d.routine, d.routine),
                     "company_name": company.name if company else d.company,
                     "contact_name": contact.name if contact else ""})
    briefs = []
    if loaded.present:
        state = read_state(root)
        today = fmt_date(store.today())
        for routine in loaded.routines:
            brief = (state.get(routine.name) or {}).get("brief")
            if routine.action == "brief" and isinstance(brief, dict) \
                    and brief.get("date") == today:
                briefs.append({"title": routine.title, "name": routine.name, **brief})
    return {"routine_drafts": rows, "routine_briefs": briefs}


def built_items(root: Path | str) -> list[dict]:
    """One item per routine for the hub's "What you've built" (contract 1)."""
    loaded = load(root)
    state = read_state(root)
    valid = {r.name: r for r in loaded.routines}
    items = []
    for name in loaded.names:
        routine = valid.get(name)
        if routine is None:
            detail = "has a problem: run hermitcrm check"
            title = name
        else:
            title = routine.title
            detail = f"{routine.state} · {last_run_text(state.get(name))}"
        items.append({"kind": "routine", "title": title, "url": f"/yours/routines/{name}",
                      "detail": detail,
                      "adjust": f"Change the routine {title} ({name}) in routines.toml: "
                                "[what to change]. Keep it paused until I have seen the "
                                "preview."})
    return items
