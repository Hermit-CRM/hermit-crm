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

"""Follow-up radar: threads waiting on you, and threads you are waiting on.

Two questions a solo seller loses deals to, neither of which PIPELINE.md answers:
*who wrote to me that I have not answered*, and *who did I write to that never
came back*. Both are already in the data -- interactions carry a direction, a
date and a body -- and nothing read them for this before.

This module is the one place that logic lives. `hermitcrm followups`, the web
home page and the MCP server all call `radar()`, so the three front doors cannot
disagree about who is overdue.

It also holds the radar's slower cousin, `keep_in_touch()`: the people outside
any open deal you have not spoken to in months. The radar is about threads in
the pipeline; this list is about the network around it.

A nudge can be marked **done** (you followed up somewhere else, or let it go).
That is kept in `outreach/followups.json`, keyed by the unanswered message, so
it holds for that silence only: a newer message is a different key and the
normal rule applies again. `radar()` leaves done nudges out, which is why the
CLI, the home page, the MCP server and the Outreach tab all agree.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .models import Contact, Direction, Interaction, do_not_contact
from .store import Store

REPLY = "reply"    # they wrote last; you owe an answer
NUDGE = "nudge"    # you wrote last; nothing came back
KEEP_IN_TOUCH_DAYS = 180  # config.toml `keep_in_touch_days` when unset
DONE_FILE = "outreach/followups.json"


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
    def key(self) -> str:
        """"company/interaction-id": the unanswered message this row is about,
        which is what "done" is remembered against."""
        return f"{self.company.slug}/{self.interaction.id}"

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
        return subject or self.interaction.label

    @property
    def preview(self) -> str:
        """The first words of the message itself, with no subject: what was said."""
        return first_line(self.interaction.body) or self.interaction.subject

    @property
    def speaker(self) -> str:
        """Whose words `preview` are: "you" for a message you sent, otherwise the
        person's name ("they" when the interaction names nobody)."""
        return "you" if self.kind == NUDGE else (self.who or "they")

    @property
    def reason(self) -> str:
        """Why this is on the list. The day count is a column of its own, so it
        is deliberately not repeated here."""
        if self.kind == REPLY:
            return f"{self.who or 'they'} wrote, no reply from you"
        return f"you wrote {self.who or 'them'}, nothing back"


def _is_greeting(line: str) -> bool:
    """A short line ending in a comma, i.e. "Hi Jane,".

    Worth skipping because a LinkedIn message has no subject, so the greeting
    would be the preview for every single row and tell you nothing.
    """
    return len(line) < 30 and line.endswith(",")


# What a mail client puts above a message when you copy it out: the sender, a time
# ("10:12 AM (1 minute ago)", "Mon, Oct 22, 10:12 AM"), then "to Sam".
_MAIL_TIME = re.compile(
    r"^(?:\d{1,2}:\d{2}\b"                                           # 10:12 AM (1 minute ago)
    r"|(?:[A-Za-z]{3,9}\.?,?\s+){1,2}\d{1,2}(?:,?\s+\d{4})?,?\s+\d{1,2}:\d{2}\b"  # Mon, Oct 22, 10:12 AM
    r"|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4},?\s+\d{1,2}:\d{2}\b)")      # 22 Oct 2026 10:12
_MAIL_FIELD = re.compile(r"(?:from|to|cc|bcc|sent|date|subject)\s*:", re.IGNORECASE)


def _strip_mail_header(lines: list[str]) -> list[str]:
    """`lines` without a copied-in mail header at the top.

    Two shapes: header fields ("From: ...", "Subject: ..."), and the short
    sender / time / "to ..." block of a webmail client. Only the very start of
    the body is looked at, so a message that merely contains a time is untouched.
    """
    fields = 0
    while fields < len(lines) and _MAIL_FIELD.match(lines[fields]):
        fields += 1
    if fields:
        return lines[fields:]
    for at in range(min(3, len(lines))):
        if len(lines[at]) < 80 and _MAIL_TIME.match(lines[at]):
            rest = lines[at + 1:]
            if rest and re.match(r"to\s", rest[0], re.IGNORECASE) and len(rest[0]) < 60:
                rest = rest[1:]
            return rest
    return lines


def first_line(body: str, limit: int = 90) -> str:
    """The first line of a body worth previewing: a pasted mail header and a
    greeting are skipped."""
    lines = [line.strip() for line in (body or "").splitlines() if line.strip()]
    stripped = _strip_mail_header(lines)
    if stripped:
        lines = stripped
    if len(lines) > 1 and _is_greeting(lines[0]):
        lines = lines[1:]
    if not lines:
        return ""
    line = lines[0]
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def latest(company) -> Interaction | None:
    """The most recent dated touch (notes are memos, not contact), or None."""
    dated = [i for i in company.interactions if i.date and i.is_touch]
    return max(dated, key=lambda i: i.date) if dated else None


def _waiting(company, today: date) -> bool:
    """True when nothing is already planned for this company.

    An open next step with a future due date means you have decided what happens
    next and when; the calendar owns that. Nudging about it as well would put the
    same company on two lists for one decision. An overdue next step is not a
    plan any more, so it does not silence the radar.
    """
    if not company.next_open:
        return True
    due = company.next_due
    return due is None or due <= today


def _row(company, it: Interaction | None, today: date, reply_after: int,
         nudge_after: int) -> Followup | None:
    """The radar row `it` puts `company` on, or None. The one rule for both
    the radar and a single contact's page: they wrote last and `reply_after`
    days passed, or you sent a message, nothing is planned and `nudge_after`
    days passed."""
    if it is None or not company.is_active:
        return None
    days = (today - it.date.date()).days
    if it.direction == Direction.IN.value:
        kind, threshold = REPLY, reply_after
    elif it.is_message and _waiting(company, today):
        kind, threshold = NUDGE, nudge_after
    else:
        return None
    if days < threshold:
        return None
    return Followup(company=company, kind=kind, interaction=it, days=days,
                    contact=company.contacts.get(it.contact))


def for_contact(company, cslug: str, today: date, reply_after: int = 1,
                nudge_after: int = 5) -> Followup | None:
    """The radar's verdict on one person: the same rule as `radar()`, applied
    to the latest touch with this contact rather than with the company."""
    dated = [i for i in company.interactions
             if i.date and i.is_touch and i.contact == cslug]
    it = max(dated, key=lambda i: i.date) if dated else None
    return _row(company, it, today, reply_after, nudge_after)


def radar(store: Store, today: date | None = None, reply_after: int = 1,
          nudge_after: int = 5, include_done: bool = False) -> list[Followup]:
    """The follow-up rows, most overdue first, replies owed before nudges.

    Only active companies: a closed or parked deal is not waiting on anybody.
    A nudge needs an outbound *message* -- a meeting you attended is not a thing
    that failed to get a reply. A nudge you marked done is left out unless
    `include_done`; a reply you owe never is.
    """
    today = today or store.today()
    done = set() if include_done else set(load_done(store.root))
    rows: list[Followup] = []
    for company in store.companies.values():
        if not company.is_active:
            continue
        row = _row(company, latest(company), today, reply_after, nudge_after)
        if row is not None and not (row.kind == NUDGE and row.key in done):
            rows.append(row)
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


# ------------------------------------------------------------------ marked done


def done_path(root: Path | str) -> Path:
    return Path(root) / DONE_FILE


def load_done(root: Path | str) -> dict[str, dict]:
    """"company/interaction-id" -> {"done": timestamp}. A file that cannot be
    read counts as nothing done: the rows come back, nothing is lost."""
    try:
        data = json.loads(done_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def _write_done(root: Path | str, done: dict[str, dict]) -> str:
    """Sorted keys, two-space indent: the same marks give the same bytes."""
    path = done_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(done, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return DONE_FILE


def _subject(row: Followup, what: str) -> str:
    who = row.contact.slug if row.contact else ""
    return f"outreach: follow-up {row.slug}{'/' + who if who else ''} {what}"


def mark_done(store: Store, row: Followup) -> None:
    """Remember that this unanswered message needs no follow-up. One commit."""
    with store.lock:
        done = load_done(store.root)
        done[row.key] = {"done": f"{store.now():%Y-%m-%dT%H:%M}"}
        path = _write_done(store.root, done)
        store.notify(_subject(row, "done"), [path])


def reopen(store: Store, key: str, row: Followup | None = None) -> None:
    """Take a done mark away. One commit. `row` only names the commit."""
    with store.lock:
        done = load_done(store.root)
        if done.pop(key, None) is None:
            return
        path = _write_done(store.root, done)
        subject = (_subject(row, "reopened") if row is not None
                   else f"outreach: follow-up {key.split('/')[0]} reopened")
        store.notify(subject, [path])


# ---------------------------------------------------------------- keep in touch


@dataclass
class Lapsed:
    """One row of the keep-in-touch list: a person and your last touch with them."""

    company: object            # Company; annotated loosely to avoid a cycle
    contact: Contact
    interaction: Interaction   # the latest touch with this person, either direction
    days: int                  # since that interaction

    @property
    def href(self) -> str:
        return f"/companies/{self.company.slug}/contacts/{self.contact.slug}"

    @property
    def summary(self) -> str:
        subject = self.interaction.subject or first_line(self.interaction.body)
        return subject or self.interaction.label


def keep_in_touch(store: Store, today: date | None = None,
                  after: int = KEEP_IN_TOUCH_DAYS) -> list[Lapsed]:
    """People you have not spoken to in `after` days or more, longest first.

    Per person, not per company: the last touch is the latest interaction
    logged against that contact, in either direction (notes do not count; they
    are memos). Left out: anyone at a company in an open stage (the pipeline,
    the radar and the silent list own those), anyone tagged do-not-contact
    (on the company or the person), people you never had any contact with
    (nothing to keep up), and the made-up sample account.
    """
    today = today or store.today()
    rows: list[Lapsed] = []
    for company in store.companies.values():
        if company.is_active or company.is_sample:
            continue
        touches: dict[str, Interaction] = {}
        for it in company.interactions:
            if not (it.date and it.is_touch and it.contact):
                continue
            seen = touches.get(it.contact)
            if seen is None or it.date > seen.date:
                touches[it.contact] = it
        for cslug, it in touches.items():
            contact = company.contacts.get(cslug)
            if contact is None or do_not_contact(company, contact):
                continue
            days = (today - it.date.date()).days
            if days >= after:
                rows.append(Lapsed(company=company, contact=contact,
                                   interaction=it, days=days))
    rows.sort(key=lambda r: (-r.days, r.contact.name.lower(), r.company.name.lower()))
    return rows


def render_keep_in_touch(rows: list[Lapsed], after: int) -> str:
    """The keep-in-touch list as text, for the CLI and for an agent over MCP."""
    if not rows:
        return (f"Nobody to catch up with: everyone outside an open deal "
                f"heard from you in the last {after} days.")
    out = [f"## Not spoken to in {after}+ days ({len(rows)})"]
    out += [f"- {r.company.slug}/{r.contact.slug} | {r.contact.name} | {r.company.name} "
            f"({r.company.stage}) | {r.days}d | {r.interaction.label}: {r.summary}"
            for r in rows]
    return "\n".join(out)
