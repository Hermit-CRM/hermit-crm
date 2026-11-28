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

"""Search everything: one walk over the in-memory store, grouped and ranked.

`search(store, q)` returns `Results`: companies, contacts, interactions (subject,
body and attachment names, with a snippet around the hit), tasks, help topics and
the app's pages. A record matches when every word of the query occurs in it,
case-insensitively, as a substring of any of its fields. Within a group, a title
that starts with the query comes first, then the most recently touched, then the
title alphabetically. Each group keeps at most `limit` hits and counts the rest.

There is no index and no database: the whole folder is in memory already (see
`Store.load`), and a scan of 5,000 interactions takes a few milliseconds. Nothing
here writes, and nothing reads a file except the help pages' titles (once).

`actions(results)` turns hits into palette entries that open existing pages and
forms ("Log a call with ...", "Add a task for ..."); it never adds a write route.
"""

from __future__ import annotations

import functools
from functools import partial
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from urllib.parse import quote, urlencode

from . import help as helpdocs

LIMIT = 8
MAX_QUERY = 200   # characters; a longer query is cut, not refused
MAX_WORDS = 8
SNIPPET_BEFORE = 40
SNIPPET_AFTER = 90

# The sidebar's entries (templates/base.html), in its order, with other words a
# person might type for them. A pin under "Yours" is not listed: it is a page the
# user made, found by its own title on the page itself.
PAGES: tuple[tuple[str, str, str], ...] = (
    ("Home", "/", "start today dashboard"),
    ("Pipeline", "/pipeline", "board deals stages"),
    ("Calendar", "/calendar", "meetings month"),
    ("Tasks", "/tasks", "todo to-do"),
    ("Companies", "/companies", "accounts"),
    ("Contacts", "/contacts", "people persons"),
    ("Messages", "/messages", "sent emails"),
    ("Outreach", "/outreach", "drafts bot"),
    ("Learning", "/learning", "lessons"),
    ("Extension", "/extension", "bookmarklet capture"),
    ("Reports", "/reports", "funnel numbers"),
    ("Make it yours", "/yours", "adjust customise customize"),
    ("Settings", "/settings", "preferences setup"),
    ("Help", "/help", "docs documentation"),
    ("Keyboard shortcuts", "/help/search", "keys palette"),
)

# Group order on the page and in the palette, with each group's heading.
GROUPS: tuple[tuple[str, str], ...] = (
    ("companies", "Companies"),
    ("contacts", "Contacts"),
    ("interactions", "Interactions"),
    ("tasks", "Tasks"),
    ("pages", "Pages"),
    ("help", "Help"),
)
KINDS = tuple(kind for kind, _ in GROUPS)


@dataclass(frozen=True)
class Hit:
    title: str
    url: str
    detail: str = ""                  # the second line: company, email, date
    snippet: tuple = ()               # ((text, is_match), ...) around the hit
    company: str = ""                 # slug, for actions
    contact: str = ""                 # slug, for actions


@dataclass
class Group:
    kind: str
    label: str
    hits: list[Hit] = field(default_factory=list)
    total: int = 0                    # matches before the cap

    @property
    def more(self) -> int:
        return self.total - len(self.hits)


@dataclass
class Results:
    q: str
    words: list[str]
    groups: list[Group]

    @property
    def total(self) -> int:
        return sum(g.total for g in self.groups)

    def group(self, kind: str) -> Group | None:
        return next((g for g in self.groups if g.kind == kind), None)

    def to_json(self) -> dict:
        return {
            "q": self.q,
            "total": self.total,
            "groups": [{"kind": g.kind, "label": g.label, "total": g.total,
                        "hits": [_hit_json(h) for h in g.hits]}
                       for g in self.groups if g.hits],
            "actions": actions(self),
        }


def _hit_json(hit: Hit) -> dict:
    out = asdict(hit)
    out["snippet"] = [[text, bool(match)] for text, match in hit.snippet]
    return out


# ------------------------------------------------------------------- matching


def words_of(q: str) -> list[str]:
    """The query's words, lower case, at most MAX_WORDS, duplicates dropped."""
    seen: list[str] = []
    for word in (q or "")[:MAX_QUERY].lower().split():
        if word not in seen:
            seen.append(word)
    return seen[:MAX_WORDS]


def _matches(words: list[str], *fields: str) -> bool:
    text = "\n".join(f for f in fields if f).lower()
    return all(w in text for w in words)


def _starts(title: str, words: list[str]) -> bool:
    return title.lower().startswith(" ".join(words))


def _stamp(value) -> float:
    """A sortable number for a date or datetime; 0 for none."""
    if value is None:
        return 0.0
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).timestamp() if value.year > 1970 else 0.0
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day).timestamp() \
            if value.year > 1970 else 0.0
    return 0.0


def _touched(*values) -> float:
    return max((_stamp(v) for v in values), default=0.0)


def snippet(text: str, words: list[str]) -> tuple:
    """A short piece of `text` around the first word found, as ((text, is_match),
    ...) parts, so a page can mark the matches without building HTML from data.
    Empty when no word occurs in `text`."""
    flat = " ".join((text or "").split())
    low = flat.lower()
    hits = [(low.find(w), w) for w in words if w and low.find(w) >= 0]
    if not hits:
        return ()
    first = min(at for at, _ in hits)
    start = max(0, first - SNIPPET_BEFORE)
    end = min(len(flat), first + SNIPPET_AFTER)
    if start > 0:   # start on a word, not inside one
        space = flat.find(" ", start, first)
        start = space + 1 if space >= 0 else start
    if end < len(flat):
        space = flat.rfind(" ", first, end)
        end = space if space > first else end
    piece, low_piece = flat[start:end], low[start:end]
    marks = [False] * len(piece)
    for w in words:
        at = low_piece.find(w)
        while w and at >= 0:
            for i in range(at, at + len(w)):
                marks[i] = True
            at = low_piece.find(w, at + len(w))
    parts: list[tuple[str, bool]] = []
    if start > 0:
        parts.append(("…", False))
    run_start = 0
    for i in range(1, len(piece) + 1):
        if i == len(piece) or marks[i] != marks[run_start]:
            parts.append((piece[run_start:i], marks[run_start]))
            run_start = i
    if end < len(flat):
        parts.append(("…", False))
    return tuple(parts)


@functools.lru_cache(maxsize=1)
def _help_titles() -> tuple[tuple[str, str], ...]:
    """(topic, title) of every help page. The pages ship with the package and do
    not change while the server runs, so they are read once."""
    return tuple(helpdocs.titles())


# --------------------------------------------------------------------- search


def search(store, q: str, limit: int = LIMIT, kinds=None) -> Results:
    """Every record that matches all words of `q`, grouped (see GROUPS) and
    ranked; at most `limit` per group. `kinds` keeps only those groups."""
    words = words_of(q)
    wanted = [k for k in KINDS if kinds is None or k in kinds]
    # Each match is (sort key, make): the Hit (and its snippet) is only built for
    # the rows that are shown, so a common word costs the scan, not 5,000 snippets.
    found: dict[str, list[tuple]] = {k: [] for k in wanted}
    if words:
        _walk_store(store, words, found)
        if "pages" in found:
            for order, (label, url, extra) in enumerate(PAGES):
                if _matches(words, label, extra):
                    found["pages"].append(((not _starts(label, words), order),
                                           partial(Hit, label, url)))
        if "help" in found:
            for order, (topic, title) in enumerate(_help_titles()):
                if _matches(words, title, topic):
                    found["help"].append(((not _starts(title, words), order),
                                          partial(Hit, title, f"/help/{topic}", "Help page")))
    labels = dict(GROUPS)
    groups = []
    for kind in wanted:
        rows = sorted(found[kind], key=lambda row: row[0])
        groups.append(Group(kind, labels[kind], [make() for _, make in rows[:limit]],
                            len(rows)))
    return Results((q or "")[:MAX_QUERY].strip(), words, groups)


def _walk_store(store, words: list[str], found: dict) -> None:
    for company in store.companies.values():
        name = company.name
        last = max((i.date for i in company.interactions if i.date), default=None)
        touched = _touched(company.updated, company.created, last)

        if "companies" in found and _matches(
                words, name, company.slug, company.website, " ".join(company.tags),
                company.product_oneliner):
            found["companies"].append(
                ((not _starts(name, words), -touched, name.lower()),
                 partial(_company_hit, company)))

        if "contacts" in found:
            for person in company.contacts.values():
                if _matches(words, person.name, person.email, person.title):
                    seen = _touched(person.updated, person.created, touched)
                    found["contacts"].append(
                        ((not _starts(person.name, words), -seen, person.name.lower()),
                         partial(_contact_hit, company, person)))

        if "interactions" in found:
            for it in company.interactions:
                files = " ".join(a.name for a in it.attachments or ())
                if _matches(words, it.subject, it.body, files):
                    found["interactions"].append(
                        ((not _starts(it.subject or "", words), -_stamp(it.date), it.id),
                         partial(_interaction_hit, company, it, files, words)))

        if "tasks" in found:
            for todo in company.todos():
                if _matches(words, todo.text):
                    found["tasks"].append(
                        ((todo.done, not _starts(todo.text, words),
                          -_touched(todo.due, todo.done_on, touched), todo.text.lower()),
                         partial(_task_hit, company, todo)))


def _company_url(company) -> str:
    return f"/companies/{quote(company.slug)}"


def _company_hit(company) -> Hit:
    return Hit(company.name, _company_url(company),
               company.product_oneliner or company.website or "", company=company.slug)


def _contact_hit(company, person) -> Hit:
    detail = " \u00b7 ".join(x for x in (person.title, company.name, person.email) if x)
    return Hit(person.name, f"{_company_url(company)}/contacts/{quote(person.slug)}",
               detail, company=company.slug, contact=person.slug)


def _interaction_hit(company, it, files: str, words: list[str]) -> Hit:
    who = company.contacts.get(it.contact) if it.contact else None
    base = f"{_company_url(company)}/contacts/{quote(who.slug)}" if who else _company_url(company)
    subject = (it.subject or "").strip()
    title = subject or f"{it.label} with {who.name if who else company.name}"
    when = f"{it.date:%Y-%m-%d}" if it.date else ""
    detail = " \u00b7 ".join(x for x in (it.label, who.name if who else "", company.name, when)
                            if x)
    return Hit(title, f"{base}#i-{quote(it.id)}", detail,
               snippet(it.body, words) or snippet(subject, words) or snippet(files, words),
               company=company.slug, contact=who.slug if who else "")


def _task_hit(company, todo) -> Hit:
    person = todo.contact
    where = (f"{_company_url(company)}/contacts/{quote(person.slug)}#tasks" if person
             else f"{_company_url(company)}#tasks")
    state = "done" if todo.done else (f"due {todo.due:%Y-%m-%d}" if todo.due else "open")
    detail = " \u00b7 ".join(x for x in (person.name if person else "", company.name, state) if x)
    return Hit(todo.text, where, detail, company=company.slug,
               contact=person.slug if person else "")


# -------------------------------------------------------------------- actions

# Fixed entries: shown for an empty query, and for a query their words match.
COMMANDS: tuple[tuple[str, str, str], ...] = (
    ("New company", "/companies/new", "add create company account"),
    ("New contact", "/contacts/new", "add create contact person"),
    ("Go to Pipeline", "/pipeline", "board"),
    ("Go to Tasks", "/tasks", "todo"),
    ("Go to Outreach", "/outreach", "drafts"),
    ("Go to Settings", "/settings", "preferences"),
)


def actions(results: Results) -> list[dict]:
    """Palette entries that open an existing page or form: the commands the
    query matches (all of them for an empty query), "Log a call with" the first
    contact found, "Add a task for" the first company found, "Capture" (quick
    capture with the query in its box) and "Ask Hermit" with the query. Each is
    {"label", "url"}; "Ask Hermit" has kind "ask" and no url, because it fills the
    Ask box on the page instead."""
    words = results.words
    out = [{"label": label, "url": url, "kind": "go"} for label, url, extra in COMMANDS
           if not words or _matches(words, label, extra)]
    contacts = results.group("contacts")
    if contacts and contacts.hits:
        hit = contacts.hits[0]
        query = urlencode({"contact": hit.contact, "channel": "call"})
        out.append({"label": f"Log a call with {hit.title}", "kind": "go",
                    "url": f"/companies/{quote(hit.company)}/interactions/new?{query}"})
    companies = results.group("companies")
    if companies and companies.hits:
        hit = companies.hits[0]
        out.append({"label": f"Add a task for {hit.title}", "kind": "go",
                    "url": f"/companies/{quote(hit.company)}#tasks"})
    if results.q:
        # Quick capture (pages/capture.py): opens the box with the text in it; the
        # person still presses the button there, so this entry runs nothing.
        out.append({"label": f"Capture: {results.q}", "kind": "go",
                    "url": "/quick-capture?" + urlencode({"text": results.q})})
        out.append({"label": f"Ask Hermit: {results.q}", "kind": "ask", "url": "",
                    "question": results.q})
    return out
