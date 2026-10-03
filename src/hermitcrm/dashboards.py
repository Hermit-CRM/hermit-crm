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

"""Dashboards: `dashboards/<slug>.toml` in the data folder, shown at /d/<slug>.

A dashboard is a title and a list of widgets. Nothing in it is new to learn,
for a person or for their AI agent:

    list    rows of one list page (companies, contacts, messages, tasks),
            with that page's filters, columns and sort, and a limit
    count   how many rows that page has for those filters
    group   the rows counted per value of one column, drawn as bars
    report  one section of the Reports page for a period

A widget is a saved query of a list page, so it is evaluated by the page's
own code (`web.company_listing` and friends) and every number links to the
page with the same `f_<key>` query: you land on exactly the records you
counted. Report sections reuse the Reports page and its rows drill-down.

Files are read lazily with an mtime cache, so an edit shows on the next page
load. A file that does not parse, or a widget that names a column that does
not exist, never breaks a page: `check` says what is wrong, line by line, and
the page shows the widgets that are fine.
"""

from __future__ import annotations

import difflib
import logging
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from . import fields as custom
from . import task_types
from .filters import _text  # the text a filter compares: group values must be the same
from .store import DEFAULT_CONFIG, load_config

logger = logging.getLogger("crm.dashboards")

DIR = "dashboards"
TYPES = ("list", "count", "group", "report")
SCOPES = ("companies", "contacts", "messages", "tasks")
# The sections reports.build() produces, in the Reports page's order.
SECTIONS = ("activity", "funnel", "outcomes", "messages", "sources", "hygiene")
# The report periods a widget takes; `all` runs from the first day in the data.
PERIODS = ("7d", "30d", "90d", "quarter", "ytd", "all")
DEFAULT_PERIOD = "30d"
DEFAULT_LIMIT = 20
TOP_KEYS = ("title", "pin", "description", "widget")
WIDGET_KEYS = {
    "list": ("type", "title", "scope", "filters", "columns", "sort", "limit", "when"),
    "count": ("type", "title", "scope", "filters", "when"),
    "group": ("type", "title", "scope", "filters", "by", "limit", "when"),
    "report": ("type", "title", "section", "period"),
}
ALL_WIDGET_KEYS = sorted({k for keys in WIDGET_KEYS.values() for k in keys})
# The Tasks page's date buttons (web.TASK_WHEN), which a tasks widget may use.
WHEN = ("overdue", "today", "week", "later", "none")
LIST_PAGES = {"companies": "/companies", "contacts": "/contacts",
              "messages": "/messages", "tasks": "/tasks"}
# The record a custom field must apply to before a scope can show it.
RECORD_OF_SCOPE = {"companies": "company", "contacts": "contact", "messages": "interaction"}
DEFAULT_COLUMNS = {
    "companies": ["name", "stage", "country", "next_step", "next_step_due"],
    "contacts": ["name", "company_name", "title", "last_touch"],
    "messages": ["date", "company_name", "contact", "channel", "status"],
    "tasks": ["text", "due", "who", "company_name"],
}
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
EMPTY = "(empty)"


# ---------------------------------------------------------------- loading


@dataclass
class Dashboard:
    slug: str
    data: dict = field(default_factory=dict)  # the parsed TOML; {} when it did not parse
    error: str = ""                           # the syntax error, as check() words it

    @property
    def file(self) -> str:
        """The path the messages name, relative to the data folder."""
        return f"{DIR}/{self.slug}.toml"

    @property
    def url(self) -> str:
        return f"/d/{self.slug}"

    @property
    def title(self) -> str:
        title = self.data.get("title")
        return title.strip() if isinstance(title, str) and title.strip() else self.slug

    @property
    def description(self) -> str:
        text = self.data.get("description")
        return text.strip() if isinstance(text, str) else ""

    @property
    def pin(self) -> bool:
        return self.data.get("pin") is True

    @property
    def widgets(self) -> list:
        found = self.data.get("widget")
        return found if isinstance(found, list) else []


_cache: dict[Path, tuple[tuple[int, int], Dashboard]] = {}


def _read(path: Path) -> Dashboard:
    dash = Dashboard(path.stem)
    try:
        with open(path, "rb") as fh:
            dash.data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        dash.error = toml_error(dash.file, exc)
    except UnicodeDecodeError:
        dash.error = f"{dash.file}: file: not UTF-8 text"
    except OSError as exc:
        dash.error = f"{dash.file}: file: cannot be read ({exc.strerror or exc})"
    return dash


def toml_error(file: str, exc: Exception) -> str:
    """`dashboards/x.toml: line 7: Expected '=' ... (column 5)` from tomllib's
    "... (at line 7, column 5)"."""
    text = str(exc)
    m = re.search(r"\s*\(at line (\d+), column (\d+)\)\s*$", text)
    if m:
        return f"{file}: line {m.group(1)}: {text[:m.start()]} (column {m.group(2)})"
    m = re.search(r"\s*\(at end of document\)\s*$", text)
    if m:
        return f"{file}: end of file: {text[:m.start()]}"
    return f"{file}: file: {text}"


def load_all(root: Path | str) -> list[Dashboard]:
    """Every `dashboards/*.toml`, by file name; [] when there is no folder.

    Re-read only when a file's mtime or size changed, so an agent's edit
    shows on the next page load without a restart and an unchanged folder
    costs one stat per file.
    """
    folder = Path(root) / DIR
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.toml")):
        try:
            st = path.stat()
        except OSError:
            continue
        if not path.is_file():
            continue
        stamp = (st.st_mtime_ns, st.st_size)
        hit = _cache.get(path)
        if hit is None or hit[0] != stamp:
            hit = (stamp, _read(path))
            _cache[path] = hit
        out.append(hit[1])
    return out


def get(root: Path | str, slug: str) -> Dashboard | None:
    return next((d for d in load_all(root) if d.slug == slug), None)


def pins(root: Path | str) -> list[dict]:
    """[{title, url}] of the pinned dashboards, by title: the sidebar's links
    (the Jinja global `yours_pins`)."""
    pinned = [{"title": d.title, "url": d.url} for d in load_all(root) if d.pin]
    return sorted(pinned, key=lambda p: (p["title"].casefold(), p["url"]))


# ------------------------------------------------------------- the columns


def columns_for(defs: list, type_options: list[str], statuses: list[str]) -> dict:
    """Scope -> the list page's own Columns (custom fields included), built
    by the same functions the pages use."""
    from . import web  # web imports this module; by the time this runs it is loaded

    return {
        "companies": web.company_columns(defs, type_options),
        "contacts": web.contact_columns(defs),
        "messages": web.message_columns(statuses, defs),
        "tasks": web.task_columns(type_options),
    }


def folder_columns(root: Path, store=None) -> tuple[dict, list]:
    """(columns per scope, field definitions) as the app would build them
    for this folder: fields.toml, the configured task types (plus the ones
    in use, given a loaded store) and the configured outcomes."""
    from . import web

    try:
        config = load_config(root)
    except Exception:
        config = dict(DEFAULT_CONFIG)
    try:
        defs = custom.load(root)
    except Exception:  # FieldError or an unreadable file: `check` says so elsewhere
        defs = []
    types = task_types.names(task_types.from_config(config.get("task_types")))
    if store is not None:
        types += [t for t in store.type_names_in_use() if t not in types]
    outcomes = [str(o) for o in (config.get("outcomes") or DEFAULT_CONFIG["outcomes"])]
    return columns_for(defs, types, web.message_statuses(outcomes)), defs


# -------------------------------------------------------------- validation


def _hint(word, choices) -> str:
    close = difflib.get_close_matches(str(word), [str(c) for c in choices], n=1, cutoff=0.6)
    return f" (did you mean {close[0]}?)" if close else ""


def _one_of(choices) -> str:
    choices = list(choices)
    return ", ".join(choices[:-1]) + f" or {choices[-1]}" if len(choices) > 1 else choices[0]


def _unknown_key(key: str, scope: str, keys: list[str], defs: list, what: str) -> str:
    """"unknown <what> <key>" plus the most useful hint there is: a field of
    your own that this list does not show, a near miss, or the keys there are."""
    record = RECORD_OF_SCOPE.get(scope)
    for d in defs:
        if d.key != key:
            continue
        if d.applies_to == record:
            return (f"unknown {what} {key} ({key} is a {record} field the {scope} list "
                    f"does not show; add \"{scope}\" to its show_in in fields.toml)")
        return (f"unknown {what} {key} ({key} is a {d.applies_to} field; the {scope} "
                f"list cannot show it)")
    hint = _hint(key, keys)
    if hint:
        return f"unknown {what} {key}{hint}"
    return f"unknown {what} {key}; the {scope} list has: {', '.join(keys)}"


def _inclusive_hint(col, op: str, value: str) -> str:
    """For ">=5": "; for 5 or more write >4" (whole numbers and dates)."""
    from datetime import timedelta

    value = value.strip()
    step = -1 if op == ">" else 1
    word = "or more" if op == ">" else "or less"
    if col.kind == "number":
        try:
            n = int(value)
        except ValueError:
            return f" (no >= or <=); write {op} with a number"
        return f"; for {n} {word} write {op}{n + step}"
    if col.kind == "date":
        try:
            day = date.fromisoformat(value[:10])
        except ValueError:
            return f" (no >= or <=); write {op} with a date as YYYY-MM-DD"
        word = "or later" if op == ">" else "or earlier"
        return f"; for {day} {word} write {op}{day + timedelta(days=step)}"
    return f" (no >= or <=); write {op}{value}"


def spec_problem(col, spec) -> str:
    """Why `spec` is not a filter the list page can apply to `col`, or ""."""
    if col.kind == "enum":
        values = spec if isinstance(spec, list) else [spec]
        if not values:
            return f"{col.key}: an empty list matches nothing; leave the key out"
        for v in values:
            if not isinstance(v, str):
                return f"{col.key}: values must be text in quotes, not {v!r}"
            if v not in col.options:
                listed = f"; one of: {', '.join(col.options)}" if len(col.options) <= 14 else ""
                return f"{col.key}: unknown value {v!r}{_hint(v, col.options)}{listed}"
        return ""
    if isinstance(spec, list):
        return (f"{col.key}: only a column with fixed values (like stage) takes a list; "
                f"write one filter in quotes")
    if not isinstance(spec, str):
        return (f"{col.key}: write the filter in quotes, e.g. \">{spec}\" or \"={spec}\", "
                f"not {spec!r}")
    text = spec.strip()
    if not text:
        return f"{col.key}: empty filter; leave the key out, or use \"-\" for empty"
    if text in ("-", "*"):
        return ""
    if text[0] in "<>":
        rest = text[1:].strip()
        if not rest:
            return f"{col.key}: {text!r} needs a value after {text[0]}"
        if rest[0] in "=<>":
            return f"{col.key}: {text!r}: only > and < exist{_inclusive_hint(col, text[0], rest[1:])}"
        if col.kind == "number":
            try:
                float(rest.lstrip("~").strip())
            except ValueError:
                return f"{col.key}: {text!r}: {col.key} is a number, so compare with a number"
        if col.kind == "date":
            try:
                date.fromisoformat(rest[:10])
            except ValueError:
                return f"{col.key}: {text!r}: {col.key} is a date, so compare with YYYY-MM-DD"
        return ""
    if text[0] in "!=" and not text[1:].strip():
        return f"{col.key}: {text!r} needs text after {text[0]}"
    return ""


def check(dash: Dashboard, columns: dict, defs: list = ()) -> list[tuple[int, str]]:
    """(widget number, message) for every problem in one dashboard; the
    number is 0 for the file as a whole. Messages are shaped
    "<file>: <where>: <what>", ready to paste back to an agent."""
    if dash.error:
        return [(0, dash.error)]
    out: list[tuple[int, str]] = []

    def say(n: int, what: str) -> None:
        out.append((n, f"{dash.file}: {'widget ' + str(n) if n else 'top level'}: {what}"))

    if not SLUG.match(dash.slug):
        out.append((0, f"{dash.file}: file name: use lower-case letters, digits and "
                       f"hyphens, like monday-review.toml (the page is /d/<file name>)"))
    data = dash.data
    for key in data:
        if key not in TOP_KEYS:
            say(0, f"unknown key {key}{_hint(key, TOP_KEYS)}")
    title = data.get("title")
    if title is None or (isinstance(title, str) and not title.strip()):
        say(0, "title is missing (every dashboard needs one)")
    elif not isinstance(title, str):
        say(0, "title must be text in quotes")
    if "pin" in data and not isinstance(data["pin"], bool):
        say(0, "pin must be true or false")
    if "description" in data and not isinstance(data["description"], str):
        say(0, "description must be text in quotes")
    widgets = data.get("widget")
    if widgets is None or widgets == []:
        say(0, "no widgets yet: add one [[widget]] table per widget")
    elif not isinstance(widgets, list):
        say(0, "write each widget as a [[widget]] table (two brackets)")
    else:
        for n, w in enumerate(widgets, 1):
            for what in widget_problems(w, columns, defs):
                say(n, what)
    return out


def widget_problems(w, columns: dict, defs: list = ()) -> list[str]:
    if not isinstance(w, dict):
        return ["must be a [[widget]] table"]
    out = []
    kind = w.get("type")
    if kind is None:
        return [f"type is missing ({_one_of(TYPES)})"]
    if kind not in TYPES:
        return [f"unknown type {kind}{_hint(kind, TYPES)}; use {_one_of(TYPES)}"]
    allowed = WIDGET_KEYS[kind]
    for key in w:
        if key in allowed:
            continue
        if key in ALL_WIDGET_KEYS:
            out.append(f"a {kind} widget takes no {key}")
        else:
            out.append(f"unknown key {key}{_hint(key, allowed)}")
    if "title" in w and not isinstance(w["title"], str):
        out.append("title must be text in quotes")
    if "limit" in w and kind in ("list", "group"):
        limit = w["limit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            out.append(f"limit must be a whole number above 0, not {limit!r}")

    if kind == "report":
        section = w.get("section")
        if section is None:
            out.append(f"section is missing ({_one_of(SECTIONS)})")
        elif section not in SECTIONS:
            out.append(f"unknown report section {section}{_hint(section, SECTIONS)}; "
                       f"use {_one_of(SECTIONS)}")
        period = w.get("period", DEFAULT_PERIOD)
        if period not in PERIODS:
            out.append(f"unknown period {period}{_hint(period, PERIODS)}; use {_one_of(PERIODS)}")
        return out

    scope = w.get("scope")
    if scope is None:
        out.append(f"scope is missing ({_one_of(SCOPES)})")
        return out
    if scope not in SCOPES:
        out.append(f"unknown scope {scope}{_hint(scope, SCOPES)}; use {_one_of(SCOPES)}")
        return out
    cols = {c.key: c for c in columns[scope]}
    keys = list(cols)

    filters = w.get("filters", {})
    if not isinstance(filters, dict):
        out.append("filters must be a table, like filters = { stage = \"prospect\" }")
        filters = {}
    for key, spec in filters.items():
        if key not in cols:
            out.append(_unknown_key(key, scope, keys, defs, "filter key"))
            continue
        problem = spec_problem(cols[key], spec)
        if problem:
            out.append(f"filter {problem}")

    if "when" in w:
        when = w["when"] if isinstance(w["when"], list) else [w["when"]]
        if scope != "tasks":
            out.append("when is for tasks widgets only")
        for value in when:
            if value not in WHEN:
                out.append(f"unknown when {value}{_hint(value, WHEN)}; use {_one_of(WHEN)}")

    if kind == "list":
        wanted = w.get("columns", DEFAULT_COLUMNS[scope])
        if not isinstance(wanted, list) or not all(isinstance(c, str) for c in wanted):
            out.append("columns must be a list of column keys in quotes")
        elif not wanted:
            out.append("columns is empty; leave it out for the default columns")
        else:
            for key in wanted:
                if key not in cols:
                    out.append(_unknown_key(key, scope, keys, defs, "column"))
        if "sort" in w:
            sort = w["sort"]
            if not isinstance(sort, str) or not sort.lstrip("-"):
                out.append("sort must be a column key in quotes, \"-\" first for Z to A")
            elif sort.lstrip("-") not in cols:
                out.append(_unknown_key(sort.lstrip("-"), scope, keys, defs, "sort column"))

    if kind == "group":
        by = w.get("by")
        if by is None:
            out.append("by is missing (the column to count per value)")
        elif not isinstance(by, str) or by not in cols:
            out.append(_unknown_key(by, scope, keys, defs, "by column"))
    return out


def validate(root: Path | str, store=None) -> list[str]:
    """Every problem in every dashboard of the folder (contract: `hermitcrm
    check` prints these and fails on any). [] without a dashboards folder."""
    dashes = load_all(root)
    if not dashes:
        return []
    columns, defs = folder_columns(Path(root), store)
    return [msg for d in dashes for _, msg in check(d, columns, defs)]


def built_items(root: Path | str) -> list[dict]:
    """One entry per dashboard for the hub's "What you've built"."""
    dashes = load_all(root)
    if not dashes:
        return []
    columns, defs = folder_columns(Path(root))
    items = []
    for d in dashes:
        n = len(d.widgets)
        detail = f"{n} widget{'' if n == 1 else 's'}, {'pinned' if d.pin else 'not pinned'}"
        problems = len(check(d, columns, defs))
        if d.error:
            detail = "cannot be read; run hermitcrm check"
        elif problems:
            detail += f"; {problems} problem{'' if problems == 1 else 's'}"
        items.append({"kind": "dashboard", "title": d.title, "url": d.url, "detail": detail,
                      "adjust": f"Change the dashboard {d.title}: …"})
    return items


# -------------------------------------------------------------- evaluation


def cell(value) -> str:
    """A value as a dashboard cell shows it."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, datetime):
        return f"{value:%Y-%m-%d %H:%M}"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = " ".join(str(value).split())
    return text if len(text) <= 100 else text[:99] + "…"


def row_href(scope: str, row) -> str:
    """The record page of a list row."""
    if scope == "companies":
        return f"/companies/{row.slug}"
    if scope == "contacts":
        return f"/companies/{row.company_slug}/contacts/{row.slug}"
    if scope == "messages":
        return f"/companies/{row.company_slug}/interactions/{row.id}/edit"
    return row.href


def filter_pairs(w: dict) -> list[tuple[str, str]]:
    """The query a list page needs for this widget's filters: `f_<key>`
    (repeated for a list of values) and `when` for tasks."""
    pairs = []
    for key, spec in (w.get("filters") or {}).items():
        for value in (spec if isinstance(spec, list) else [spec]):
            pairs.append((f"f_{key}", str(value).strip()))
    when = w.get("when", [])
    for value in (when if isinstance(when, list) else [when]):
        pairs.append(("when", value))
    return pairs


def page_url(scope: str, pairs) -> str:
    query = urlencode(list(pairs))
    return LIST_PAGES[scope] + ("?" + query if query else "")


def describe(w: dict, columns: list) -> str:
    """A default title: "Companies: stage prospect, fit score >70"."""
    labels = {c.key: c.label for c in columns}
    parts = []
    for key, spec in (w.get("filters") or {}).items():
        label = labels.get(key, key)
        if isinstance(spec, list):
            parts.append(f"{label} {' or '.join(spec)}")
        elif str(spec).strip() == "-":
            parts.append(f"no {label}")
        elif str(spec).strip() == "*":
            parts.append(f"any {label}")
        else:
            parts.append(f"{label} {str(spec).strip()}")
    when = w.get("when", [])
    parts += [str(v) for v in (when if isinstance(when, list) else [when])]
    head = w["scope"].capitalize()
    return head + (": " + ", ".join(parts) if parts else "")


def _params(pairs):
    from starlette.datastructures import QueryParams

    return QueryParams(urlencode(list(pairs)))


def _list_view(w, scope, columns, listing) -> dict:
    by_key = {c.key: c for c in columns}
    pairs = filter_pairs(w)
    sort = str(w.get("sort", "")).strip()
    if sort:
        pairs += [("sort", sort.lstrip("-")), ("dir", "desc" if sort.startswith("-") else "asc")]
    found = listing(scope, _params(pairs))
    shown = [by_key[k] for k in w.get("columns", DEFAULT_COLUMNS[scope]) if k in by_key]
    limit = int(w.get("limit", DEFAULT_LIMIT))
    rows = [{"href": row_href(scope, r), "cells": [cell(c.value(r)) for c in shown]}
            for r in found.rows[:limit]]
    return {"columns": shown, "rows": rows, "total": len(found.rows),
            "url": page_url(scope, pairs)}


def _count_view(w, scope, listing) -> dict:
    pairs = filter_pairs(w)
    found = listing(scope, _params(pairs))
    return {"count": len(found.rows), "url": page_url(scope, pairs)}


def _group_values(col, rows) -> tuple[dict[str, int], bool]:
    """(value -> how many rows have it, whether the column holds lists).

    Values are the text the filter matcher compares (filters._text), so a
    bar's filter picks exactly its rows. A list value (tags) counts once per
    item. Free text is grouped case-insensitively, as `=text` matches.
    """
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    listed = False
    for r in rows:
        raw = col.value(r)
        if isinstance(raw, (list, tuple, set)):
            listed = True
            values = [_text(v) for v in raw] or [""]
        else:
            values = [_text(raw)]
        for text in values:
            key = text if col.kind == "enum" else text.lower()
            labels.setdefault(key, text)
            counts[labels[key]] = counts.get(labels[key], 0) + 1
    return counts, listed


def _bar_spec(col, value: str, listed: bool):
    """The filter that picks the rows with `value`: what the bar links to.
    None when the list page cannot express it (an empty value of a column
    with fixed values)."""
    if col.kind == "enum":
        return [value] if value else None
    if not value:
        return "-"
    return value if listed else "=" + value


def _group_view(w, scope, columns, listing) -> dict:
    col = next(c for c in columns if c.key == w["by"])
    base_pairs = filter_pairs(w)
    base = listing(scope, _params(base_pairs))
    prelim, listed = _group_values(col, base.rows)
    if col.kind == "enum":
        order = {o: i for i, o in enumerate(col.options)}
        values = sorted(prelim, key=lambda v: (v == "", order.get(v, len(order)), v))
    else:
        values = sorted(prelim, key=lambda v: (v == "", -prelim[v], v.lower()))
    limit = int(w.get("limit", DEFAULT_LIMIT))
    others = [(k, v) for k, v in base_pairs if k != f"f_{col.key}"]
    bars = []
    for value in values[:limit]:
        spec = _bar_spec(col, value, listed)
        if spec is None:
            bars.append({"label": EMPTY, "count": prelim[value], "url": ""})
            continue
        specs = spec if isinstance(spec, list) else [spec]
        pairs = others + [(f"f_{col.key}", s) for s in specs]
        # The count is what the page shows for the bar's link, so a click
        # always lands on exactly that many records.
        count = len(listing(scope, _params(pairs)).rows)
        bars.append({"label": value or EMPTY, "count": count, "url": page_url(scope, pairs)})
    return {"bars": bars, "max": max((b["count"] for b in bars), default=0),
            "total": len(base.rows), "url": page_url(scope, base_pairs),
            "more": max(0, len(values) - limit), "label": col.label}


def first_day(store) -> date | None:
    """The earliest day in the data: a company created or an interaction."""
    days = []
    for c in store.companies.values():
        if c.created:
            days.append(c.created.date() if isinstance(c.created, datetime) else c.created)
        for i in c.interactions:
            if i.date:
                days.append(i.date.date() if isinstance(i.date, datetime) else i.date)
    return min(days) if days else None


def view(dash: Dashboard, columns: dict, defs: list, listing, report_for) -> dict:
    """Everything /d/<slug> shows. `listing(scope, params)` is the list pages'
    own evaluation; `report_for(period)` returns (report, rows query).
    Widgets with a problem are left out and their problems listed; a widget
    that fails while drawing joins them instead of breaking the page."""
    found = check(dash, columns, defs)
    bad = {n for n, _ in found}
    problems = [msg for _, msg in found]
    widgets = []
    for n, w in enumerate(dash.widgets, 1):
        if n in bad or not isinstance(w, dict):
            continue
        kind = w["type"]
        try:
            if kind == "report":
                period = w.get("period", DEFAULT_PERIOD)
                report, query = report_for(period)
                section = w["section"]
                item = {"report": report, "rows_query": query, "section": section,
                        "default_title": f"{section.capitalize()} ({period})",
                        "url": "/reports?" + query + f"#{section}"}
            else:
                scope = w["scope"]
                cols = columns[scope]
                if kind == "list":
                    item = _list_view(w, scope, cols, listing)
                elif kind == "count":
                    item = _count_view(w, scope, listing)
                else:
                    item = _group_view(w, scope, cols, listing)
                item["scope"] = scope
                item["default_title"] = (describe(w, cols) if kind != "group" else
                                         f"{scope.capitalize()} by {item['label']}")
        except Exception as exc:  # a page with one broken widget still shows the rest
            logger.exception("dashboard %s widget %d failed", dash.slug, n)
            problems.append(f"{dash.file}: widget {n}: could not be drawn ({exc})")
            continue
        item.update(type=kind, number=n, title=str(w.get("title") or "").strip()
                    or item["default_title"])
        widgets.append(item)
    return {"dashboard": dash, "problems": problems, "widgets": widgets}
