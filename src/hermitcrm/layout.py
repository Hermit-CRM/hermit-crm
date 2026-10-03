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

"""layout.toml: the order and visibility of page sections, hidden fields, and
the columns of the Companies and Contacts lists.

The file is optional, and so is every table and key in it. Absent, the pages
are what they always were. It is data, not a template: it names sections and
fields that ship with Hermit CRM, so an upgrade cannot break it, and a section
a later version adds is never hidden by a file written before it existed
(sections you do not list keep their default order, after the ones you do).

Hiding a field is a display matter only. The value stays in the file, and a
form that does not show a field does not send it, so saving it keeps the value
(`web.py` drops the keys a form did not carry).

The app reads the file on every request through an mtime cache, so an edit
shows on the next page load. A broken file never breaks a page: a syntax error
means the default layout, and a wrong name or value is skipped while the rest
applies. `validate` says what was wrong, for `hermitcrm check`.
"""

from __future__ import annotations

import difflib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

FILENAME = "layout.toml"

# Each page's sections, in their default order. The name is the section's
# anchor on the page too, except `enrich` (the Enrich and Fetch from URL
# buttons) and `next-step` (the next step line under them).
SECTIONS = {
    "company": ("enrich", "next-step", "details", "contacts", "tasks", "drafts",
                "merge", "timeline"),
    "contact": ("details", "timeline", "quick-add", "tasks", "drafts", "merge",
                "delete"),
    "home": ("doing", "to-file", "owed", "going"),
}

# Built-in fields a record page may hide (its header line, its form and the
# list columns). The page header keeps what it is made of: a company's name
# and stage, a contact's name.
FIELDS = {
    "company": ("website", "linkedin", "country", "source", "lost_reason",
                "requalify_on", "value_eur_month", "product_oneliner", "next_step",
                "next_step_due", "next_step_status", "next_step_type", "tags", "notes"),
    "contact": ("title", "role", "language", "email", "phone", "linkedin"),
}
HEADER_FIELDS = {"company": ("name", "stage"), "contact": ("first_name", "last_name")}

# The built-in columns of the two list pages, in their default order (custom
# fields with `show_in` that list sit after `source` and at the end). Any
# custom field of the list's record type can be a column too.
COLUMNS = {
    "companies": ("name", "country", "stage", "source", "tags", "last_touch",
                  "next_step", "next_type", "next_step_due", "links"),
    "contacts": ("name", "company_name", "title", "email", "linkedin", "last_touch",
                 "interaction_count"),
}
LIST_SCOPE = {"companies": "company", "contacts": "contact"}
COLUMN_OF_FIELD = {"next_step_type": "next_type"}  # a field whose column is named otherwise

KEYS = {
    "company": ("sections", "hide_sections", "hide_fields"),
    "contact": ("sections", "hide_sections", "hide_fields"),
    "home": ("sections", "hide_sections"),
    "companies": ("columns",),
    "contacts": ("columns",),
}

PAGE_NAMES = {"company": "company page", "contact": "contact page", "home": "Home",
              "companies": "Companies list", "contacts": "Contacts list"}


@dataclass(frozen=True)
class Layout:
    """A read layout.toml, with everything invalid already left out."""

    order: dict = field(default_factory=dict)            # page -> listed sections
    hidden_sections: dict = field(default_factory=dict)  # page -> frozenset
    hidden_fields: dict = field(default_factory=dict)    # company|contact -> frozenset
    columns: dict = field(default_factory=dict)          # companies|contacts -> tuple

    def sections(self, page: str) -> list[str]:
        """The page's visible sections in order: the listed ones first, then
        the rest in their default order."""
        listed = list(self.order.get(page, ()))
        rest = [s for s in SECTIONS.get(page, ()) if s not in listed]
        hidden = self.hidden_sections.get(page, frozenset())
        return [s for s in listed + rest if s not in hidden]

    def hidden(self, page: str, errors=None) -> frozenset:
        """The field keys hidden on a record page. A field the form has an
        error for shows anyway, or nobody could correct it."""
        keys = self.hidden_fields.get(page, frozenset())
        if errors:
            keys = frozenset(k for k in keys
                             if k not in errors and f"custom_{k}" not in errors)
        return keys

    def field_hidden(self, page: str, key: str) -> bool:
        return key in self.hidden_fields.get(page, frozenset())

    def hidden_columns(self, view: str) -> set[str]:
        """Column keys of a list that its record page's hide_fields hide."""
        return {COLUMN_OF_FIELD.get(k, k) for k in self.hidden(LIST_SCOPE[view])}


DEFAULT = Layout()


# ------------------------------------------------------------------- reading


def _hint(name: str, choices) -> str:
    close = difflib.get_close_matches(name, list(choices), n=1)
    if close:
        return f" (did you mean {close[0]}?)"
    return "; known: " + ", ".join(choices) if choices else ""


def _names(value) -> list[str] | None:
    """A TOML list of strings, stripped; None for anything else."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    return [v.strip() for v in value]


def parse(data: dict, defs: list | None = None) -> tuple[Layout, list[str]]:
    """(the layout, problems) from a loaded layout.toml.

    `defs` are the folder's custom fields. Without them (the app, which must
    not tie this cache to fields.toml) a name that is not built in is kept as
    a possible custom field, and simply matches nothing if it is not one.
    """
    problems: list[str] = []

    def problem(where: str, what: str) -> None:
        problems.append(f"{FILENAME}: {where}: {what}")

    custom = None
    if defs is not None:
        custom = {scope: [d.key for d in defs if d.applies_to == scope]
                  for scope in ("company", "contact")}
    order, hidden_sections, hidden_fields, columns = {}, {}, {}, {}

    for table, body in data.items():
        if table not in KEYS:
            problem(f"[{table}]", "unknown table" + _hint(table, list(KEYS)))
            continue
        if not isinstance(body, dict):
            problem(table, f"must be a table: put [{table}] on a line of its own")
            continue
        for key, value in body.items():
            where = f"[{table}] {key}"
            if key not in KEYS[table]:
                problem(f"[{table}]", f"unknown key {key}" + _hint(key, KEYS[table]))
                continue
            names = _names(value)
            if names is None:
                problem(where, 'must be a list of names in quotes, like ["a", "b"]')
                continue
            if key in ("sections", "hide_sections"):
                known, what = list(SECTIONS[table]), "section"
            elif key == "hide_fields":
                known, what = list(FIELDS[table]) + (custom or {}).get(table, []), "field"
            else:
                scope = LIST_SCOPE[table]
                known, what = list(COLUMNS[table]) + (custom or {}).get(scope, []), "column"
                if not names:
                    problem(where, "the list is empty; leave the key out for the default columns")
                    continue
            kept: list[str] = []
            for name in names:
                if name in kept:
                    problem(where, f"{name} is listed twice")
                elif key == "hide_fields" and name in HEADER_FIELDS[table]:
                    problem(where, f"{name} is part of the page header and cannot be hidden")
                elif name in known:
                    kept.append(name)
                elif custom is None and what != "section" and name:
                    kept.append(name)   # perhaps a custom field; see the docstring
                else:
                    label = name or '""'
                    problem(where, f"unknown {what} {label}" + _hint(name, known))
            if key == "sections":
                order[table] = tuple(kept)
            elif key == "hide_sections":
                hidden_sections[table] = frozenset(kept)
            elif key == "hide_fields":
                hidden_fields[table] = frozenset(kept)
            elif kept:
                columns[table] = tuple(kept)

    for page, listed in order.items():
        for name in listed:
            if name in hidden_sections.get(page, ()):
                problem(f"[{page}]", f"section {name} is in both sections and "
                                     "hide_sections; it stays hidden")
    for view, names in columns.items():
        scope = LIST_SCOPE[view]
        gone = {COLUMN_OF_FIELD.get(k, k) for k in hidden_fields.get(scope, ())}
        for name in names:
            if name in gone:
                problem(f"[{view}] columns", f"{name} is hidden by hide_fields in "
                                             f"[{scope}], so it never shows")
    return Layout(order, hidden_sections, hidden_fields, columns), problems


def _syntax_problem(exc: tomllib.TOMLDecodeError) -> str:
    message = str(exc)
    found = re.search(r"\s*\(at line (\d+), column (\d+)\)", message)
    if found:
        return (f"{FILENAME}: line {found.group(1)}: "
                f"{message[:found.start()]} (column {found.group(2)})")
    found = re.search(r"\s*\(at end of document\)", message)
    if found:
        return f"{FILENAME}: end of file: {message[:found.start()]}"
    return f"{FILENAME}: syntax: {message}"


def read(path: Path, defs: list | None = None) -> tuple[Layout, list[str]]:
    """(the layout, problems) from one file; the default layout when it cannot
    be read at all."""
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        return DEFAULT, [_syntax_problem(exc)]
    except (OSError, UnicodeDecodeError) as exc:
        return DEFAULT, [f"{FILENAME}: file: cannot be read ({exc})"]
    return parse(data, defs)


_cache: dict[Path, tuple[tuple, Layout]] = {}


def load(root: Path | str) -> Layout:
    """The folder's layout, re-read only when the file changed."""
    path = Path(root) / FILENAME
    try:
        st = path.stat()
    except OSError:
        return DEFAULT
    stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
    hit = _cache.get(path)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    layout = read(path)[0]
    _cache[path] = (stamp, layout)
    return layout


def pick_columns(layout: Layout, view: str, default: list, extra: list = ()) -> list:
    """The columns a list page shows, in order.

    `default` are the list's columns as they are without a layout; `extra` the
    custom fields of its record type that are not among them. `columns` in
    layout.toml, when set, decides which and in what order (it wins over a
    field's `show_in`); hide_fields of the record page then takes its fields out.
    """
    chosen = list(default)
    names = layout.columns.get(view)
    if names:
        pool = {c.key: c for c in [*default, *extra]}
        chosen = [pool[n] for n in names if n in pool] or chosen
    hidden = layout.hidden_columns(view)
    shown = [c for c in chosen if c.key not in hidden]
    return shown or [c for c in default if c.key not in hidden]


# ----------------------------------------------------- check and the hub


def validate(root: Path | str) -> list[str]:
    """Problems in the folder's layout.toml, one line each; none when absent."""
    path = Path(root) / FILENAME
    if not path.exists():
        return []
    from . import fields
    try:
        defs = fields.load(root)
    except (fields.FieldError, tomllib.TOMLDecodeError, OSError):
        defs = None  # custom field names cannot be judged; fields.toml is the problem
    return read(path, defs)[1]


def describe(layout: Layout) -> str:
    """One line on what the layout changes, e.g. "company page: timeline first,
    merge hidden, 2 fields hidden"."""
    def some(names, noun: str) -> str:
        names = sorted(names)
        return names[0] if len(names) == 1 else f"{len(names)} {noun}s"

    parts = []
    for page in ("company", "contact", "home"):
        bits = []
        hidden = layout.hidden_sections.get(page, frozenset())
        shown = layout.sections(page)
        default = [s for s in SECTIONS[page] if s not in hidden]
        if shown != default:
            bits.append(f"{shown[0]} first" if shown and shown[0] != default[0]
                        else "sections reordered")
        if hidden:
            bits.append(some(hidden, "section") + " hidden")
        if layout.hidden_fields.get(page):
            bits.append(some(layout.hidden_fields[page], "field") + " hidden")
        if bits:
            parts.append(f"{PAGE_NAMES[page]}: {', '.join(bits)}")
    for view in ("companies", "contacts"):
        if layout.columns.get(view):
            parts.append(f"{PAGE_NAMES[view]}: {len(layout.columns[view])} columns chosen")
    return "; ".join(parts)


def built_items(root: Path | str) -> list[dict]:
    """The hub's entry for layout.toml: one item while the file exists."""
    if not (Path(root) / FILENAME).exists():
        return []
    return [{
        "kind": "layout",
        "title": "Page layout",
        "url": "",
        "detail": describe(load(root)) or "layout.toml changes nothing yet",
        "adjust": ("Change my page layout (layout.toml): on the [company] page, show "
                   "[the timeline] first and hide [the Merge section]."),
    }]
