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

"""Export everything: a zip of CSVs or one JSON file. Read only.

The zip holds companies.csv, contacts.csv, interactions.csv, tasks.csv and
stage_history.csv. A profile renames the company and contact columns to what
HubSpot or Pipedrive call them; the headers chosen are ones `importer.py`
recognises, so an export imports back (`hermitcrm import companies.csv`, then
`contacts.csv`). Fields you defined yourself and keys the app does not know
come after the known columns, sorted, so nothing in the front matter is left
out.

Cells that a spreadsheet would run as a formula (starting with = + - @, a tab
or a carriage return) get a leading apostrophe, the OWASP way; the importer
strips it again (`importer.unescape_cell`).

Output is deterministic: rows sorted by slug (and date or stored order below
that), columns in a fixed order, zip entries with a fixed timestamp. Nothing is
written to the data folder and nothing is committed.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, datetime
from typing import Iterable, Iterator

from .models import (
    Company,
    company_to_frontmatter,
    contact_to_frontmatter,
    fmt_date,
    fmt_datetime,
    interaction_to_frontmatter,
)

PROFILES = ("generic", "hubspot", "pipedrive")
FORMATS = ("csv", "json")
JSON_FORMAT = "hermitcrm-export"
JSON_VERSION = 1

# The first character that makes a spreadsheet read a cell as a formula.
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

# Known columns, in order. Lists of front-matter keys; `notes` is the body.
COMPANY_FIELDS = (
    "slug", "name", "website", "linkedin", "country", "source", "stage",
    "stage_changed", "lost_reason", "requalify_on", "value_eur_month",
    "product_oneliner", "next_step", "next_step_due", "next_step_status",
    "next_step_done_on", "next_step_type", "tags", "created", "updated", "notes",
)
CONTACT_FIELDS = (
    "company_slug", "company", "slug", "first_name", "last_name", "title", "email",
    "phone", "linkedin", "role", "language", "created", "updated", "contact_notes",
)
INTERACTION_FIELDS = (
    "company_slug", "company", "id", "date", "channel", "direction", "contact",
    "subject", "framework", "approach", "outcome", "source",
    "message_id", "body",
)
TASK_FIELDS = (
    "company_slug", "company", "contact", "kind", "index", "text", "due", "done",
    "done_on", "type",
)
STAGE_FIELDS = ("company_slug", "company", "date", "from", "to", "reason")

# Profile headers for the company and contact columns. A column not named here
# keeps its generic name. Every name is one `importer.py` maps back to the same
# field (see COMPANY_COLUMNS and PERSON_COLUMNS there), which the tests check.
PROFILE_HEADERS = {
    "generic": {"companies": {}, "contacts": {}},
    "hubspot": {
        "companies": {
            "name": "Company name", "website": "Website URL",
            "linkedin": "LinkedIn Company Page", "country": "Country/Region",
            "stage": "Deal Stage", "product_oneliner": "Description",
            "value_eur_month": "Value EUR/month", "next_step": "Next step",
            "next_step_due": "Next step due", "tags": "Tags", "notes": "Notes",
        },
        "contacts": {
            "company": "Company Name", "first_name": "First Name",
            "last_name": "Last Name", "title": "Job Title", "email": "Email",
            "phone": "Phone Number", "linkedin": "LinkedIn URL",
        },
    },
    "pipedrive": {
        "companies": {
            "name": "Organization - Name", "website": "Organization - Website",
            "linkedin": "Organization - LinkedIn", "country": "Organization - Country",
            "stage": "Deal - Stage", "product_oneliner": "Organization - Description",
            "value_eur_month": "Deal - Value", "tags": "Organization - Labels",
            "notes": "Organization - Notes",
        },
        "contacts": {
            "company": "Person - Organization", "first_name": "Person - First name",
            "last_name": "Person - Last name", "title": "Person - Job title",
            "email": "Person - Email", "phone": "Person - Phone",
            "linkedin": "Person - LinkedIn",
        },
    },
}


# ------------------------------------------------------------------- cells


def escape_cell(text: str) -> str:
    """A leading apostrophe on anything a spreadsheet would run as a formula."""
    return "'" + text if text.startswith(FORMULA_START) else text


def cell(value) -> str:
    """One front-matter value as CSV text (before escaping)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return fmt_datetime(value)
    if isinstance(value, date):
        return fmt_date(value)
    if isinstance(value, (list, tuple)):
        if all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in value):
            return ", ".join(str(v) for v in value)
        return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)
    if isinstance(value, dict):
        return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)
    return str(value)


def _jsonable(value):
    if isinstance(value, datetime):
        return fmt_datetime(value)
    if isinstance(value, date):
        return fmt_date(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


# ------------------------------------------------------------------- tables


def _companies(store) -> list[Company]:
    # A snapshot: the web app may reload the index while a zip streams.
    return [store.companies[slug] for slug in sorted(store.companies)]


def _extra_columns(records: Iterable[dict], known: Iterable[str], own: list[str]) -> list[str]:
    """Columns after the known ones: your own fields, then unknown keys, each sorted."""
    known = set(known)
    seen = {k for r in records for k in r if k not in known}
    own_keys = sorted(k for k in own if k not in known)
    return own_keys + sorted(seen - set(own_keys), key=str)


def _own(defs, scope: str) -> list[str]:
    return [d.key for d in (defs or []) if d.applies_to == scope]


def _company_notes_text(company) -> str:
    """The `notes` column: the legacy body (when one is left), then the company's
    own notes oldest first, each as written, joined with a blank line. The
    importer reads this header back as company notes."""
    mine = sorted((i for i in company.interactions if i.is_note and not i.contact),
                  key=lambda i: (i.date or datetime.min, i.id))
    parts = [company.notes.strip()] + [(i.body or i.subject or "").strip() for i in mine]
    return "\n\n".join(p for p in parts if p)


def company_rows(store, defs=None) -> tuple[list[str], list[dict]]:
    rows = []
    for c in _companies(store):
        meta = company_to_frontmatter(c)
        # Lists of their own: stage_history.csv and tasks.csv hold them.
        meta.pop("stage_history", None)
        meta.pop("tasks", None)
        meta["notes"] = _company_notes_text(c)
        rows.append(meta)
    columns = list(COMPANY_FIELDS) + _extra_columns(rows, COMPANY_FIELDS + (
        "stage_history", "tasks"), _own(defs, "company"))
    return columns, rows


def contact_rows(store, defs=None) -> tuple[list[str], list[dict]]:
    rows = []
    for c in _companies(store):
        for slug in sorted(c.contacts):
            person = c.contacts[slug]
            meta = contact_to_frontmatter(person)
            meta.pop("tasks", None)
            # Not "notes": the importer reads that header as company notes and
            # would take the file for a companies list. Legacy only (format 7
            # moved contact notes into note interactions).
            rows.append({"company_slug": c.slug, "company": c.name, **meta,
                         "contact_notes": person.notes})
    columns = list(CONTACT_FIELDS) + _extra_columns(rows, CONTACT_FIELDS + ("tasks",),
                                                    _own(defs, "contact"))
    return columns, rows


def interaction_rows(store) -> tuple[list[str], list[dict]]:
    rows = []
    for c in _companies(store):
        for it in sorted(c.interactions, key=lambda i: (i.date or datetime.min, i.id)):
            meta = interaction_to_frontmatter(it)
            rows.append({"company_slug": c.slug, "company": c.name, "id": it.id,
                         **meta, "body": it.body})
    columns = list(INTERACTION_FIELDS) + _extra_columns(rows, INTERACTION_FIELDS, [])
    return columns, rows


def task_rows(store) -> tuple[list[str], list[dict]]:
    """Every to-do: the next_step fields, company tasks and people's tasks."""
    rows = []
    for c in _companies(store):
        for todo in c.todos():
            rows.append({
                "company_slug": c.slug, "company": c.name,
                "contact": todo.contact.slug if todo.contact else "",
                "kind": "next_step" if todo.is_field else "task",
                "index": todo.index, "text": todo.text, "due": todo.due,
                "done": todo.done, "done_on": todo.done_on, "type": todo.type,
            })
    return list(TASK_FIELDS), rows


def stage_rows(store) -> tuple[list[str], list[dict]]:
    rows = [{"company_slug": c.slug, "company": c.name, "date": e.date,
             "from": e.from_stage, "to": e.to_stage, "reason": e.reason}
            for c in _companies(store) for e in c.stage_history]
    return list(STAGE_FIELDS), rows


def csv_text(columns: list[str], rows: list[dict], headers: dict | None = None,
             excel: bool = False) -> str:
    """One table as CSV text; `excel` adds the UTF-8 byte-order mark Excel needs."""
    headers = headers or {}
    out = io.StringIO()
    if excel:
        out.write("﻿")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([escape_cell(headers.get(col, col)) for col in columns])
    for row in rows:
        writer.writerow([escape_cell(cell(row.get(col))) for col in columns])
    return out.getvalue()


def csv_files(store, defs=None, profile: str = "generic",
              excel: bool = False) -> list[tuple[str, str]]:
    """(file name, CSV text) for every table, in a fixed order."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; use " + ", ".join(PROFILES))
    names = PROFILE_HEADERS[profile]
    return [
        ("companies.csv", csv_text(*company_rows(store, defs), names["companies"], excel)),
        ("contacts.csv", csv_text(*contact_rows(store, defs), names["contacts"], excel)),
        ("interactions.csv", csv_text(*interaction_rows(store), None, excel)),
        ("tasks.csv", csv_text(*task_rows(store), None, excel)),
        ("stage_history.csv", csv_text(*stage_rows(store), None, excel)),
    ]


# ------------------------------------------------------------------- zip


def _zip_time(store) -> tuple:
    """The newest `updated` in the folder: fixed for unchanged data, unlike now()."""
    stamps = [c.updated for c in store.companies.values() if c.updated]
    newest = max(stamps) if stamps else None
    if newest is None or newest.year < 1980:
        return (1980, 1, 1, 0, 0, 0)
    return (newest.year, newest.month, newest.day, newest.hour, newest.minute, 0)


class _Sink(io.RawIOBase):
    """A write-only, unseekable buffer: zipfile then streams with data descriptors."""

    def __init__(self):
        self.chunks: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        self.chunks.append(bytes(data))
        return len(data)

    def take(self) -> bytes:
        data, self.chunks = b"".join(self.chunks), []
        return data


def zip_chunks(store, defs=None, profile: str = "generic",
               excel: bool = False) -> Iterator[bytes]:
    """The export zip, a chunk per file, so the web app can stream it.

    The same bytes whether written to a file or sent over HTTP.
    """
    files = csv_files(store, defs, profile, excel)  # read everything up front
    stamp = _zip_time(store)
    sink = _Sink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in files:
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, text.encode("utf-8"))
            yield sink.take()
    yield sink.take()


def zip_bytes(store, defs=None, profile: str = "generic", excel: bool = False) -> bytes:
    return b"".join(zip_chunks(store, defs, profile, excel))


# ------------------------------------------------------------------- json


def json_data(store, defs=None) -> dict:
    """Everything as one nested document: companies with their contacts,
    interactions, tasks and stage history, front-matter keys as stored."""
    companies = []
    for c in _companies(store):
        meta = _jsonable(company_to_frontmatter(c))
        meta["notes"] = _company_notes_text(c)
        meta["contacts"] = []
        for slug in sorted(c.contacts):
            person = c.contacts[slug]
            row = _jsonable(contact_to_frontmatter(person))
            row["notes"] = person.notes
            meta["contacts"].append(row)
        meta["interactions"] = [
            {"id": it.id, **_jsonable(interaction_to_frontmatter(it)), "body": it.body}
            for it in sorted(c.interactions, key=lambda i: (i.date or datetime.min, i.id))
        ]
        companies.append(meta)
    return {
        "format": JSON_FORMAT,
        "version": JSON_VERSION,
        "fields": [{"key": d.key, "label": d.label, "type": d.type,
                    "applies_to": d.applies_to} for d in (defs or [])],
        "companies": companies,
    }


def json_text(store, defs=None) -> str:
    return json.dumps(json_data(store, defs), ensure_ascii=False, indent=2) + "\n"


def default_name(store, fmt: str = "csv") -> str:
    suffix = "json" if fmt == "json" else "zip"
    return f"hermitcrm-export-{store.today().isoformat()}.{suffix}"
