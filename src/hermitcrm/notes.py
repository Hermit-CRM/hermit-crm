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

"""A finding is a note. What is known about a person lives on their timeline
as notes (interactions of channel `note`); the Outreach bot writes what it
researches as notes and drafts from the notes it finds
(docs/superpowers/specs/2026-10-20-outreach-notes-and-drafts-design.md, part C).

A note you wrote is plain text. A note the research wrote ends in one line of
fixed text that keeps where it came from:

    Opened a second office in September
    Source: https://example.com/news (trigger, 2026-09, high)

`Item.findings` stays what it was: the snapshot of the notes a draft was
written from, with the `used` marks, so the checks, the critic and learning
need not know where a finding came from.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urlparse

from . import outreach
from .models import ValidationError

NOTE_COUNT = 20     # notes a draft is written from: the newest ones
NOTE_CHARS = 4000   # and their text in all; over it the longest goes first
SOURCE_LINE = re.compile(
    r"^Source: (\S+) \((company|person|trigger), ([0-9-]*), (high|medium)\)\s*$")


def _norm(text: str) -> str:
    return " ".join((text or "").split()).lower()


def contact_notes(company, contact_slug: str) -> list:
    """The notes about one person, newest first."""
    mine = [i for i in company.interactions if i.is_note and i.contact == contact_slug]
    return sorted(mine, key=lambda i: (i.date or datetime.min, i.id), reverse=True)


def company_notes(company) -> list:
    """The notes about the company itself (on no one in particular), newest first.
    A draft to any of its people is written from them too."""
    mine = [i for i in company.interactions if i.is_note and not i.contact]
    return sorted(mine, key=lambda i: (i.date or datetime.min, i.id), reverse=True)


def elsewhere(company, contact_slug: str) -> dict:
    """The notes on a person's page that are not theirs, newest first: the
    company's own, and each other contact's (contacts with no notes left out,
    in the order the company lists them)."""
    others = []
    for slug, person in company.contacts.items():
        if slug == contact_slug:
            continue
        theirs = contact_notes(company, slug)
        if theirs:
            others.append({"slug": slug, "name": person.name, "notes": theirs})
    return {"company": company_notes(company), "others": others}


def notes_for(company, contact_slug: str) -> list:
    """What a draft to this person reads: their notes and the company's, newest first."""
    both = contact_notes(company, contact_slug) + company_notes(company)
    return sorted(both, key=lambda i: (i.date or datetime.min, i.id), reverse=True)


def research_note(finding) -> tuple[str, str]:
    """(subject, body) of the note that keeps a research finding: the text, then
    its origin on a line of its own."""
    host = (urlparse(finding.source).hostname or finding.source).removeprefix("www.")
    return (f"Research: {host}",
            f"{finding.text}\nSource: {finding.source} "
            f"({finding.kind}, {finding.date}, {finding.confidence})")


def finding_of(note, today: date):
    """The finding a note stands for. What you wrote is high confidence, about the
    person, and never stale (you know when it is true); a research note keeps the
    confidence, kind and date of its source line."""
    lines = (note.body or "").strip().splitlines()
    match = SOURCE_LINE.match(lines[-1]) if lines else None
    before = " ".join(" ".join(lines[:-1]).split()) if match else ""
    if match and before:
        url, kind, when, confidence = match.groups()
        return outreach.Finding(text=before, source=url, kind=kind, confidence=confidence,
                                date=when, stale=outreach.is_stale(when, today))
    text = " ".join((note.body or "").split()) or " ".join((note.subject or "").split())
    return outreach.Finding(text=text, source=outreach.YOURS, kind="person",
                            confidence="high",
                            date=f"{note.date:%Y-%m}" if note.date else "")


def snapshot(company, contact_slug: str, today: date) -> list:
    """The findings a draft is written from: the newest notes about the contact and
    about their company, at most NOTE_COUNT, and when their text runs over NOTE_CHARS the longest ones go."""
    found = [f for f in (finding_of(n, today)
                         for n in notes_for(company, contact_slug)[:NOTE_COUNT]) if f.text]
    while found and sum(len(f.text) for f in found) > NOTE_CHARS:
        del found[max(range(len(found)), key=lambda i: len(found[i].text))]
    return found


def save_findings(store, company_slug: str, contact_slug: str, findings) -> tuple[int, int]:
    """Keep research findings as notes on the contact: medium and high confidence
    only, one note each, none whose text is already a note. What the CRM already
    knew (`crm`) and what you wrote (`you`) are not research. Returns (notes
    written, low-confidence findings left out). The notes join the caller's
    commit when one is open."""
    company = store.get(company_slug)
    known = {_norm(finding_of(n, store.today()).text)
             for n in contact_notes(company, contact_slug)}
    written = left_out = 0
    with store.batch(f"outreach: notes {company_slug}/{contact_slug} from research"):
        for f in findings:
            if f.source in ("crm", outreach.YOURS):
                continue
            if not f.usable:
                left_out += 1
                continue
            if _norm(f.text) in known:
                continue
            subject, body = research_note(f)
            store.create_interaction(company_slug, "note", "", subject=subject,
                                     contact=contact_slug, body=body)
            known.add(_norm(f.text))
            written += 1
    return written, left_out


def add_note(store, company_slug: str, contact_slug: str, text: str):
    """A note you write about a person, from the Outreach page: the same note you
    would add on their page."""
    text = (text or "").strip()
    if not text:
        raise outreach.OutreachError("write something to add as a note")
    try:
        return store.create_interaction(company_slug, "note", "", contact=contact_slug,
                                        body=text)
    except ValidationError as exc:
        raise outreach.OutreachError("; ".join(exc.errors.values())) from exc


def adopt(store, item) -> int:
    """An item written before findings were notes: save what its card shows as
    notes, once (never the CRM's own line, never low confidence), and mark it
    linked. A linked item's findings are a snapshot of notes: a note deleted
    since stays deleted. Returns how many notes were written."""
    if item.notes_linked:
        return 0
    company = store.get(item.company)
    if company is None or item.contact not in company.contacts:
        return 0
    known = {_norm(finding_of(n, store.today()).text)
             for n in contact_notes(company, item.contact)}
    own = [f for f in item.findings if f.source == outreach.YOURS
           and f.text and _norm(f.text) not in known]
    written = 0
    with store.batch(f"outreach: notes {item.record} from findings"):
        for f in own:
            add_note(store, item.company, item.contact, f.text)
            known.add(_norm(f.text))
            written += 1
        written += save_findings(store, item.company, item.contact, item.findings)[0]
    item.notes_linked = True
    return written


def rows(company, contact_slug: str, today: date, used=frozenset()) -> list[dict]:
    """The contact's notes for a page, newest first: the note, its text on one line,
    where it came from (you, or research with its source link), and whether its text
    is one of `used` (normalised texts the draft cited)."""
    out = []
    for note in notes_for(company, contact_slug):
        f = finding_of(note, today)
        research = f.source.startswith("http")
        origin = "research" if research else "company" if not note.contact else "you"
        out.append({"note": note, "text": f.text, "origin": origin,
                    "source_url": f.source if research else "", "date": f.date,
                    "used": _norm(f.text) in used})
    return out


def card(company, contact_slug: str, item, today: date) -> dict:
    """What the card's Notes panel shows: one row per note (newest first, with
    where it came from and whether the draft used it), how many notes are newer
    than the draft, findings of an older card that are not notes yet, and the
    company's own notes field."""
    listed = notes_for(company, contact_slug)
    shown = rows(company, contact_slug, today, {_norm(f.text) for f in item.findings if f.used})
    texts = {_norm(r["text"]) for r in shown}
    newer = sum(1 for n in listed if item.drafted and n.date and n.date > item.drafted)
    legacy = [] if item.notes_linked else [
        f for f in item.findings if f.source != "crm" and _norm(f.text) not in texts]
    return {"rows": shown, "newer": newer, "legacy": legacy,
            "company_notes": (company.notes or "").strip()}
