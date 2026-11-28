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

"""Today: one prioritised queue that answers "what do I do now?".

The queue is made by *providers*: plain functions `(store, config, today) ->
list[Item]`, each reading one part of the folder. This module ships the ones
for replies owed and nudges (the follow-up radar), tasks overdue and due today,
today's meetings, routine drafts and briefs, and keep in touch. A later feature
adds its own with one call, from its own module:

    today.register(my_provider, kind="call", heading="Calls to make", before=today.DRAFT)

`build` runs every provider, puts the rows in the order of `ORDER` (oldest
first inside each group) and keeps one row per company per kind: a company with
three overdue tasks is one row that says "and 2 more". A provider that fails is
logged and left out; the rest of the queue still shows.

Pure reads: nothing here writes. A row's actions are the app's existing POST
routes (a task's Done, a draft's Discard) and links.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Callable

from . import followups, routines
from .models import fmt_date
from .store import DEFAULT_CONFIG

logger = logging.getLogger(__name__)

# Row kinds.
REPLY = "reply"              # they wrote last; you owe an answer
OVERDUE = "overdue"          # an open task whose date has passed
MEETING = "meeting"          # on the calendar today
BRIEF = "brief"              # today's brief from a brief routine
DRAFT = "draft"              # a routine wrote a draft; you send it
DUE = "due"                  # an open task due today
NUDGE = "nudge"              # you wrote last; nothing came back
KEEP = "keep-in-touch"       # outside an open deal, quiet for a long time

# The order of the queue, most urgent first, with each group's heading. Kinds
# that share a heading show as one group. Change the order here and only here.
ORDER: list[tuple[str, str]] = [
    (REPLY, "Replies you owe"),
    (OVERDUE, "Overdue tasks"),
    (MEETING, "Today"),
    (BRIEF, "Today"),
    (DRAFT, "Drafts waiting for you"),
    (DUE, "Due today"),
    (NUDGE, "Waiting on them"),
    (KEEP, "Keep in touch"),
]
OTHER_HEADING = "More"  # the heading of a kind ORDER does not name


@dataclass(frozen=True)
class Action:
    """One thing a row lets you do. A "get" action is a link; a "post" action
    is a form to an existing route, with `fields` as its hidden inputs (the
    page adds the CSRF token and where to come back to)."""

    label: str
    href: str
    method: str = "get"                     # "get" | "post"
    fields: tuple[tuple[str, str], ...] = ()
    secondary: bool = False


@dataclass
class Item:
    """One row of the queue: who, what and why, and what you can do about it."""

    kind: str
    company: object | None       # Company; loosely typed, as in followups.py
    contact: object | None       # Contact
    title: str                   # what
    reason: str                  # why it is on the list
    due: date | None             # when it fell due or started waiting; sorts the group
    href: str                    # where the row's name links to
    actions: tuple[Action, ...] = ()
    count: int = 1               # how many things this row stands for
    urgency: int = -1            # the group's place in ORDER; build() sets it
    key: str = ""                # unique on the page; the row's anchor

    @property
    def who(self) -> str:
        if self.contact is not None:
            return self.contact.name
        return self.company.name if self.company is not None else ""


@dataclass
class Group:
    heading: str
    kinds: list[str]
    items: list[Item]
    count: int                   # things in the whole group, not rows shown


@dataclass
class Queue:
    items: list[Item]
    next_up: Item | None = None  # the next dated task, for the empty state
    failed: list[str] = field(default_factory=list)  # providers that raised

    @property
    def total(self) -> int:
        return sum(i.count for i in self.items)

    def count(self, kind: str) -> int:
        return sum(i.count for i in self.items if i.kind == kind)

    def more(self, limit: int) -> int:
        """Rows not shown when the page shows `limit`."""
        return max(0, len(self.items) - limit)

    def groups(self, limit: int | None = None) -> list[Group]:
        """The rows under their headings, the first `limit` rows only. A group
        keeps its full count in the heading even when some rows are cut."""
        out: list[Group] = []
        shown = 0
        for item in self.items:
            heading = heading_of(item.kind)
            if not out or out[-1].heading != heading:
                out.append(Group(heading, [], [], 0))
            group = out[-1]
            if item.kind not in group.kinds:
                group.kinds.append(item.kind)
            group.count += item.count
            if limit is None or shown < limit:
                group.items.append(item)
                shown += 1
        return [g for g in out if g.items]


Provider = Callable[[object, dict, date], list[Item]]
PROVIDERS: list[Provider] = []


def register(provider: Provider, kind: str | None = None, heading: str = "",
             before: str | None = None) -> Provider:
    """Add a provider to the queue, and (with `kind`) its group to ORDER,
    before the kind `before` or at the end. Registering twice changes nothing."""
    if provider not in PROVIDERS:
        PROVIDERS.append(provider)
    if kind and kind not in {k for k, _ in ORDER}:
        names = [k for k, _ in ORDER]
        at = names.index(before) if before in names else len(ORDER)
        ORDER.insert(at, (kind, heading or OTHER_HEADING))
    return provider


def heading_of(kind: str) -> str:
    return next((h for k, h in ORDER if k == kind), OTHER_HEADING)


def build(store, config: dict | None = None, today: date | None = None) -> Queue:
    """Run every provider and return the queue, most urgent first."""
    config = config or {}
    today = today or store.today()
    rank = {k: n for n, (k, _) in enumerate(ORDER)}
    items: list[Item] = []
    failed: list[str] = []
    for provider in list(PROVIDERS):
        try:
            got = provider(store, config, today)
        except Exception:
            logger.exception("Today provider %s failed", _name(provider))
            failed.append(_name(provider))
            continue
        items.extend(replace(i, urgency=rank.get(i.kind, len(ORDER))) for i in got)
    items.sort(key=_sort_key)
    return Queue(items=_once_per_company(items), next_up=_next_up(store, today),
                 failed=failed)


def _name(provider) -> str:
    return getattr(provider, "__name__", repr(provider))


def _sort_key(item: Item):
    return (item.urgency, item.due or date.max, item.title.lower(), item.key)


def _once_per_company(items: list[Item]) -> list[Item]:
    """One row per company per kind: the first (oldest) stands for the rest.
    The input is sorted, so the first one seen is the one to keep."""
    out: list[Item] = []
    seen: dict[tuple[str, str], int] = {}
    for item in items:
        slug = getattr(item.company, "slug", None)
        if slug is None:
            out.append(item)
            continue
        at = seen.get((item.kind, slug))
        if at is None:
            seen[(item.kind, slug)] = len(out)
            out.append(item)
        else:
            out[at].count += item.count
    for item in out:
        if item.count > 1 and item.kind in (OVERDUE, DUE):
            extra = item.count - 1
            word = "overdue" if item.kind == OVERDUE else "due today"
            item.reason += f"; and {extra} more {word} here"
    return out


def _ago(days: int) -> str:
    return "today" if days == 0 else ("1 day ago" if days == 1 else f"{days} days ago")


def _days(n: int) -> str:
    return "1 day" if n == 1 else f"{n} days"


def _setting(config: dict, key: str) -> int:
    try:
        return int(config.get(key, DEFAULT_CONFIG[key]))
    except (TypeError, ValueError):
        return int(DEFAULT_CONFIG[key])


def _log_href(company, contact) -> str:
    base = f"/companies/{company.slug}/interactions/new"
    return f"{base}?contact={contact.slug}" if contact is not None else base


def _record_href(company, contact) -> str:
    base = f"/companies/{company.slug}"
    return f"{base}/contacts/{contact.slug}" if contact is not None else base


# ------------------------------------------------------------------ providers


def radar_items(store, config: dict, today: date) -> list[Item]:
    """Replies you owe and nudges: the follow-up radar, as `hermitcrm followups`."""
    rows = followups.radar(store, today,
                           reply_after=_setting(config, "followup_reply_days"),
                           nudge_after=_setting(config, "followup_nudge_days"))
    out = []
    for r in rows:
        if r.kind == followups.REPLY:
            reason = f"{r.who or 'They'} wrote {_ago(r.days)}, no reply from you"
            label = "Log a reply"
        else:
            reason = f"You wrote {r.who or 'them'} {_ago(r.days)}, nothing back"
            label = "Log a follow-up"
        out.append(Item(
            kind=REPLY if r.kind == followups.REPLY else NUDGE,
            company=r.company, contact=r.contact, title=r.summary, reason=reason,
            due=r.interaction.date.date(), href=f"/companies/{r.slug}",
            actions=(Action(label, _log_href(r.company, r.contact)),
                     Action("Open the message",
                            f"/companies/{r.slug}/interactions/{r.interaction.id}/edit",
                            secondary=True)),
            key=f"{r.kind}-{r.slug}"))
    return out


def task_items(store, config: dict, today: date) -> list[Item]:
    """Open tasks overdue or due today, the next-step field included, in every
    company: the same rows as the Tasks page's Overdue and Today chips."""
    out = []
    for company in store.companies.values():
        for todo in company.open_todos():
            if todo.due is None or todo.due > today:
                continue
            overdue = todo.due < today
            if todo.is_field:
                done = Action("Done", f"/companies/{company.slug}/next-step", "post",
                              (("status", "done"),))
                ident = "next"
            else:
                contact = todo.contact.slug if todo.contact else ""
                done = Action("Done", f"/companies/{company.slug}/tasks/{todo.index}/done",
                              "post", (("contact", contact), ("text", todo.text),
                                       ("done", "1")))
                ident = f"{contact or '-'}-{todo.index}"
            late = (today - todo.due).days
            out.append(Item(
                kind=OVERDUE if overdue else DUE, company=company, contact=todo.contact,
                title=todo.text or "(no text)",
                reason=(f"{_days(late)} overdue (due {fmt_date(todo.due)})" if overdue
                        else "Due today"),
                due=todo.due, href=_record_href(company, todo.contact), actions=(done,),
                key=f"task-{company.slug}-{ident}"))
    return out


def meeting_items(store, config: dict, today: date) -> list[Item]:
    """Today's meetings from the last calendar import (inbox/upcoming.json)."""
    from . import bcc, calendar_sync

    out = []
    for n, row in enumerate(calendar_sync.read_upcoming(bcc.Inbox(store.root),
                                                        store.now(), days=1)):
        if row["start"].date() != today:
            continue
        slugs = [str(e.get("slug", "")) for e in row.get("companies") or []]
        known = [store.companies[s] for s in slugs if s in store.companies]
        when = "All day" if row.get("all_day") else f"{row['start']:%H:%M}"
        company = known[0] if known else None
        others = ", ".join(c.name for c in known[1:])
        out.append(Item(
            kind=MEETING, company=company, contact=None,
            title=f"{when} {row.get('title') or '(no title)'}",
            reason="Meeting today" + (f", also with {others}" if others else ""),
            due=today, href=f"/companies/{company.slug}" if company else "/calendar",
            actions=(Action("Calendar", "/calendar", secondary=True),),
            key=f"meeting-{n}"))
    return out


def routine_items(store, config: dict, today: date) -> list[Item]:
    """Drafts your routines wrote, and today's briefs (routines.home_context)."""
    context = routines.home_context(store, config)
    out = []
    for row in context.get("routine_drafts", []):
        d = row["draft"]
        company = store.companies.get(d.company)
        contact = company.contacts.get(d.contact) if company and d.contact else None
        name = row["contact_name"] or row["company_name"]
        reason = "; ".join(x for x in (d.reason, f"from {row['routine_title']}") if x)
        out.append(Item(
            kind=DRAFT, company=company, contact=contact,
            title=f"{d.channel.capitalize() or 'Message'} draft to {name}",
            reason=reason, due=d.made.date() if d.made else today,
            href=f"/#draft-{d.id}",
            actions=(Action("Open the draft", f"/#draft-{d.id}"),
                     Action("Discard", f"/yours/routines/{d.routine}/drafts/{d.id}/discard",
                            "post", secondary=True)),
            key=f"draft-{d.id}"))
    for b in context.get("routine_briefs", []):
        out.append(Item(
            kind=BRIEF, company=None, contact=None, title=b.get("title") or b["name"],
            reason=routines.brief_summary(b), due=today, href=f"/#brief-{b['name']}",
            actions=(Action("Read the brief", f"/#brief-{b['name']}"),),
            key=f"brief-{b['name']}"))
    return out


def keep_in_touch_items(store, config: dict, today: date) -> list[Item]:
    """People outside an open deal you have not spoken to in a long time, one
    row per company (the longest quiet person first, the others named)."""
    rows = followups.keep_in_touch(store, today, after=_setting(config, "keep_in_touch_days"))
    by_company: dict[str, list] = {}
    for r in rows:
        by_company.setdefault(r.company.slug, []).append(r)
    out = []
    for slug, people in by_company.items():
        first = people[0]
        names = ", ".join(p.contact.name for p in people)
        out.append(Item(
            kind=KEEP, company=first.company, contact=first.contact,
            title=f"Keep in touch with {names}",
            reason=f"Last spoke {_ago(first.days)} ({first.summary})",
            due=first.interaction.date.date(), href=first.href,
            actions=(Action("Log a touch", _log_href(first.company, first.contact)),),
            count=len(people), key=f"keep-{slug}"))
    return out


def _next_up(store, today: date) -> Item | None:
    """The first open task dated after today: the empty state's "Next up"."""
    best = None
    for company in store.companies.values():
        for todo in company.open_todos():
            if todo.due and todo.due > today and (best is None or todo.due < best[0].due):
                best = (todo, company)
    if best is None:
        return None
    todo, company = best
    return Item(kind=DUE, company=company, contact=todo.contact,
                title=todo.text or "(no text)", reason=f"Due {fmt_date(todo.due)}",
                due=todo.due, href=_record_href(company, todo.contact), key="next-up")


for _provider in (radar_items, task_items, meeting_items, routine_items,
                  keep_in_touch_items):
    register(_provider)
