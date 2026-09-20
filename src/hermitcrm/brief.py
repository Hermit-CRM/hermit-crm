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

"""Pre-meeting brief: what you need in your head before a call starts.

The parts were all here already -- the calendar import writes the next week's
meetings to `upcoming.json` with the companies it matched them to, and the store
has the timeline, the stage and the open next step. Nothing assembled them, so
the answer to "who am I about to talk to and where did we leave it" was four
clicks away at the moment you had none.

`briefs()` is the one place that assembly lives; `hermitcrm brief`, the calendar
page and the MCP server all call it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import calendar_sync
from .followups import first_line
from .models import fmt_date
from .store import Store

RECENT = 3  # interactions shown per company: enough to recall the thread


@dataclass
class Match:
    """One company this meeting is with, and the tail of its timeline."""

    company: object            # Company; annotated loosely to avoid a cycle
    interactions: list = field(default_factory=list)


@dataclass
class Brief:
    """One upcoming meeting, with the record behind it."""

    start: datetime
    end: datetime
    title: str
    location: str
    attendees: list[str]
    all_day: bool = False
    companies: list[Match] = field(default_factory=list)

    @property
    def when(self) -> str:
        if self.all_day:
            return f"{self.start:%a %d %b} (all day)"
        return f"{self.start:%a %d %b %H:%M}-{self.end:%H:%M}"


def recent(company, limit: int = RECENT) -> list:
    """The last few dated interactions, newest first."""
    dated = sorted((i for i in company.interactions if i.date),
                   key=lambda i: i.date, reverse=True)
    return dated[:limit]


def briefs(store: Store, inbox, now: datetime | None = None,
           days: int = 7) -> list[Brief]:
    """Briefs for the meetings the last calendar import found, soonest first.

    Reads `upcoming.json` rather than the calendar itself: no network, so this
    stays instant and works offline. A meeting whose companies have since been
    deleted is dropped rather than half-rendered.
    """
    now = now or store.now()
    out = []
    for row in calendar_sync.read_upcoming(inbox, now, days):
        matches = []
        for entry in row.get("companies") or []:
            company = store.get(str(entry.get("slug", "")))
            if company is not None:
                matches.append(Match(company, recent(company)))
        if not matches:
            continue
        out.append(Brief(
            start=row["start"], end=row["end"], title=str(row.get("title") or ""),
            location=str(row.get("location") or ""),
            attendees=[str(a) for a in (row.get("attendees") or [])],
            all_day=bool(row.get("all_day")), companies=matches,
        ))
    return out


def render_one(brief: Brief, today=None) -> str:
    """One meeting as Markdown: the thing you read in the two minutes before."""
    lines = [f"## {brief.when} | {brief.title or '(no title)'}"]
    if brief.location:
        lines.append(f"Where: {brief.location}")
    if brief.attendees:
        lines.append(f"With: {', '.join(brief.attendees)}")

    for match in brief.companies:
        company, interactions = match.company, match.interactions
        lines.append("")
        stage = f"{company.stage}, {company.days_in_stage(today)}d in stage"
        if company.value_eur_month is not None:
            stage += f", {company.value_eur_month} EUR/month"
        lines.append(f"### {company.name} ({company.slug}) -- {stage}")
        if company.product_oneliner:
            lines.append(company.product_oneliner)
        if company.next_step_open:
            due = f", due {fmt_date(company.next_step_due)}" if company.next_step_due else ""
            lines.append(f"Open next step: {company.next_step or '(no text)'}{due}")
        people = [c.name + (f" ({c.title})" if c.title else "")
                  for c in company.contacts.values()]
        if people:
            lines.append("Contacts: " + ", ".join(people))
        if interactions:
            lines.append(f"Last {len(interactions)}:")
            for it in interactions:
                preview = it.subject or first_line(it.body, 70)
                lines.append(f"- {it.date:%Y-%m-%d} {it.channel} {it.direction} "
                             f"({it.contact_label}){': ' + preview if preview else ''}")
        else:
            lines.append("No interactions logged yet.")
        if company.notes.strip():
            lines.append("Notes: " + first_line(company.notes, 200))
    return "\n".join(lines)


def render(items: list[Brief], today=None, days: int = 7) -> str:
    """Every brief as one document, for the CLI and for an agent over MCP."""
    if not items:
        return (f"No meetings with known companies in the next {days} days. "
                "Run hermitcrm calendar --apply to refresh the feed.")
    head = f"# Brief: {len(items)} meeting{'s' if len(items) != 1 else ''}"
    return "\n\n".join([head] + [render_one(b, today) for b in items]) + "\n"
