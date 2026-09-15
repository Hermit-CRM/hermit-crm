"""Per-column filters for the board, companies and contacts views.

A view declares its columns; the query string carries one `f_<key>` value per
column (repeated for multi-select enums). Text-ish columns accept a tiny
operator syntax typed into the box:

    foo      contains "foo" (case-insensitive)
    !foo     does not contain "foo"
    =foo     equals "foo" (case-insensitive)
    >5       larger than 5 (numbers, dates as YYYY-MM-DD, otherwise text order)
    <5       smaller than 5
    -        empty
    *        not empty
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable


@dataclass
class Column:
    key: str
    label: str
    kind: str = "text"  # text | enum | number | date
    options: list[str] = field(default_factory=list)
    getter: Callable | None = None  # obj -> raw value; defaults to attribute

    def value(self, obj):
        if self.getter is not None:
            return self.getter(obj)
        return getattr(obj, self.key, None)


def parse(params, columns: list[Column]) -> dict[str, object]:
    """Read the active filters for `columns` from a query-params mapping."""
    active: dict[str, object] = {}
    for col in columns:
        name = f"f_{col.key}"
        if col.kind == "enum":
            values = [v for v in params.getlist(name) if v]
            if values:
                active[col.key] = values
        else:
            value = (params.get(name) or "").strip()
            if value:
                active[col.key] = value
    return active


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _comparable(value, kind: str):
    """Coerce for > and <; None when the value cannot be compared."""
    if value in (None, "", [], ()):
        return None
    if kind == "number":
        try:
            return float(str(value).lstrip("~").strip())
        except ValueError:
            return None
    if kind == "date":
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return _text(value).lower()


def matches(col: Column, raw, spec) -> bool:
    if col.kind == "enum":
        return _text(raw) in set(spec)
    text = _text(raw)
    spec = str(spec)
    if spec == "-":
        return text == ""
    if spec == "*":
        return text != ""
    if spec[0] in "<>" and len(spec) > 1:
        left = _comparable(raw, col.kind)
        right = _comparable(spec[1:].strip(), col.kind)
        if left is None or right is None:
            return False
        return left > right if spec[0] == ">" else left < right
    if spec.startswith("!"):
        return spec[1:].strip().lower() not in text.lower()
    if spec.startswith("="):
        return spec[1:].strip().lower() == text.lower()
    return spec.lower() in text.lower()


def apply(rows, columns: list[Column], active: dict[str, object]):
    if not active:
        return list(rows)
    by_key = {c.key: c for c in columns}
    kept = []
    for row in rows:
        if all(matches(by_key[k], by_key[k].value(row), spec)
               for k, spec in active.items() if k in by_key):
            kept.append(row)
    return kept


# ------------------------------------------------------------------- sorting


def parse_sort(params, columns: list[Column]) -> tuple[str, str]:
    """Read `sort=<column key>&dir=asc|desc`; unknown keys sort nothing."""
    key = (params.get("sort") or "").strip()
    direction = "desc" if (params.get("dir") or "").strip() == "desc" else "asc"
    if key not in {c.key for c in columns}:
        return "", "asc"
    return key, direction


def sort_rows(rows, columns: list[Column], key: str, direction: str = "asc"):
    """Stable sort on one column; empty values always go last (A to Z is
    `asc`, Z to A is `desc`; numbers and dates sort by value, text
    case-insensitively)."""
    rows = list(rows)
    if not key:
        return rows
    col = next((c for c in columns if c.key == key), None)
    if col is None:
        return rows
    kind = col.kind if col.kind in ("number", "date") else "text"
    keyed = [(_comparable(col.value(r), kind), r) for r in rows]
    present = [(k, r) for k, r in keyed if k is not None]
    absent = [r for k, r in keyed if k is None]
    present.sort(key=lambda kr: kr[0], reverse=(direction == "desc"))
    return [r for _, r in present] + absent
