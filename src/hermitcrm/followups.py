"""Follow-up radar: threads waiting on you, and threads you are waiting on.

Two questions a solo seller loses deals to, neither of which PIPELINE.md answers:
*who wrote to me that I have not answered*, and *who did I write to that never
came back*. Both are already in the data -- interactions carry a direction, a
date and a body -- and nothing read them for this before.

This module is the one place that logic lives. `hermitcrm followups`, the web
home page and the MCP server all call `radar()`, so the three front doors cannot
disagree about who is overdue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import Contact, Direction, Interaction
from .store import Store

REPLY = "reply"    # they wrote last; you owe an answer
NUDGE = "nudge"    # you wrote last; nothing came back


@dataclass
class Followup:
    """One row of the radar: a company, and the interaction that put it there."""

    company: object            # Company; annotated loosely to avoid a cycle
    kind: str                  # REPLY | NUDGE
    interaction: Interaction
    days: int                  # since that interaction
    contact: Contact | None    # the person on it, when the interaction names one

    @property
    def slug(self) -> str:
        return self.company.slug

    @property
    def name(self) -> str:
        return self.company.name

    @property
    def who(self) -> str:
        """The person on the interaction, or "" when it names nobody.

        An interaction logged against the company (a BCC with no matching
        contact, say) has no name to show, and "company wrote 3d ago" reads
        like a bug. The reason line says "they" instead.
        """
        if self.contact:
            return self.contact.name
        return self.interaction.contact or ""

    @property
    def summary(self) -> str:
        subject = self.interaction.subject or first_line(self.interaction.body)
        return subject or f"{self.interaction.channel} {self.interaction.direction}"

    @property
    def reason(self) -> str:
        if self.kind == REPLY:
            return f"{self.who or 'they'} wrote {self.days}d ago, no reply from you"
        return f"you wrote {self.who or 'them'} {self.days}d ago, nothing back"


def _is_greeting(line: str) -> bool:
    """A short line ending in a comma, i.e. "Hi Jane,".

    Worth skipping because a LinkedIn message has no subject, so the greeting
    would be the preview for every single row and tell you nothing.
    """
    return len(line) < 30 and line.endswith(",")


def first_line(body: str, limit: int = 90) -> str:
    """The first line of a body worth previewing, greeting skipped."""
    lines = [line.strip() for line in (body or "").splitlines() if line.strip()]
    if len(lines) > 1 and _is_greeting(lines[0]):
        lines = lines[1:]
    if not lines:
        return ""
    line = lines[0]
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def latest(company) -> Interaction | None:
    """The most recent dated interaction, or None when there are none."""
    dated = [i for i in company.interactions if i.date]
    return max(dated, key=lambda i: i.date) if dated else None


def _waiting(company, today: date) -> bool:
    """True when nothing is already planned for this company.

    An open next step with a future due date means you have decided what happens
    next and when; the calendar owns that. Nudging about it as well would put the
    same company on two lists for one decision. An overdue next step is not a
    plan any more, so it does not silence the radar.
    """
    if not company.next_step_open:
        return True
    due = company.next_step_due
    return due is None or due <= today


def radar(store: Store, today: date | None = None, reply_after: int = 1,
          nudge_after: int = 5) -> list[Followup]:
    """The follow-up rows, most overdue first, replies owed before nudges.

    Only active companies: a closed or parked deal is not waiting on anybody.
    A nudge needs an outbound *message* -- a meeting you attended is not a thing
    that failed to get a reply.
    """
    today = today or store.today()
    rows: list[Followup] = []
    for company in store.companies.values():
        if not company.is_active:
            continue
        it = latest(company)
        if it is None:
            continue
        days = (today - it.date.date()).days
        if it.direction == Direction.IN.value:
            kind, threshold = REPLY, reply_after
        elif it.is_message and _waiting(company, today):
            kind, threshold = NUDGE, nudge_after
        else:
            continue
        if days < threshold:
            continue
        rows.append(Followup(company=company, kind=kind, interaction=it, days=days,
                             contact=company.contacts.get(it.contact)))
    rows.sort(key=lambda r: (r.kind != REPLY, -r.days, r.company.name.lower()))
    return rows


def render(rows: list[Followup]) -> str:
    """The radar as text, for the CLI and for an agent reading over MCP."""
    if not rows:
        return "Nothing waiting: no unanswered messages, no unreturned nudges."
    owed = [r for r in rows if r.kind == REPLY]
    waiting = [r for r in rows if r.kind == NUDGE]
    out: list[str] = []
    if owed:
        out.append(f"## You owe a reply ({len(owed)})")
        out += [f"- {r.slug} | {r.who or 'company'} | {r.days}d | {r.summary}" for r in owed]
    if waiting:
        if out:
            out.append("")
        out.append(f"## Waiting on them ({len(waiting)})")
        out += [f"- {r.slug} | {r.who or 'company'} | {r.days}d | {r.summary}" for r in waiting]
    return "\n".join(out)
