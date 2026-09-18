"""User-defined fields: a schema for keys Hermit CRM does not know about.

Every record already round-trips front-matter keys it does not recognise --
`Company.extra`, `Contact.extra`, `Interaction.extra` -- so the *values* have
always been safe to store. What was missing was a description of them: a
label, a type, and a decision about which views show them. That description
lives in `fields.toml` beside `messages.toml`, and nowhere else.

This is why user-defined fields are cheap here and expensive in a CRM with a
database. There is no migration to run: the data can already be in the file
before the app knows the name. Adding a field is a display concern.

`config.toml` was the obvious home and is the wrong one: `setup.set_config_values`
is a line-based writer that keeps comments and can only set scalar keys, so it
cannot express an array of tables.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .models import COMPANY_KEYS, CONTACT_KEYS, INTERACTION_KEYS, slugify

FILENAME = "fields.toml"

TYPES = ("text", "number", "date", "select")
SCOPES = ("company", "contact", "interaction")

# Where a field may be shown. "detail" is the record's own page, which every
# field gets anyway; the rest are the tables and the board, where a field
# becomes a sortable, filterable column.
VIEWS_FOR_SCOPE = {
    "company": ("detail", "board", "companies"),
    "contact": ("detail", "contacts"),
    "interaction": ("detail", "messages"),
}
RESERVED = {"company": COMPANY_KEYS, "contact": CONTACT_KEYS,
            "interaction": INTERACTION_KEYS}


class FieldError(Exception):
    """fields.toml cannot be read. Carries one message per offending field."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


@dataclass
class FieldDef:
    key: str
    label: str = ""
    type: str = "text"
    applies_to: str = "company"
    help: str = ""
    options: list[str] = field(default_factory=list)
    show_in: list[str] = field(default_factory=list)
    enrich: bool = False          # offer it to the AI schema
    description: str = ""         # what to tell the model to look for

    def __post_init__(self):
        self.label = self.label or self.key.replace("_", " ")

    def shows_in(self, view: str) -> bool:
        return view in self.show_in

    def coerce(self, raw):
        """A form string to the stored value. Raises ValueError with a sentence."""
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        if self.type == "number":
            try:
                return int(text)
            except ValueError:
                try:
                    return float(text)
                except ValueError:
                    raise ValueError(f"{self.label} wants a number, got {text!r}") from None
        if self.type == "date":
            from datetime import date, datetime
            if isinstance(raw, date):
                return raw
            try:
                return datetime.strptime(text, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError(f"{self.label} wants a date as YYYY-MM-DD, "
                                 f"got {text!r}") from None
        if self.type == "select":
            if self.options and text not in self.options:
                raise ValueError(f"{self.label} must be one of "
                                 + ", ".join(self.options) + f"; got {text!r}")
            return text
        return text

    def display(self, value) -> str:
        """The stored value as the UI shows it."""
        if value is None or value == "":
            return ""
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return str(value)


def _clean_key(raw: str) -> str:
    """A front-matter key: the same slug rules as everywhere else, underscored.

    `slugify` falls back to "company" for an empty string, which would turn a
    field with no key into a field called `company`, so the empty case is
    answered here instead.
    """
    text = str(raw or "").strip()
    return slugify(text, default="").replace("-", "_") if text else ""


def parse(data: dict) -> list[FieldDef]:
    """Definitions from a loaded `fields.toml`. Raises FieldError on anything
    it cannot honour, because a field it silently drops is a field whose values
    quietly stop being editable."""
    entries = data.get("field") or []
    if isinstance(entries, dict):        # [field.fit_score] style
        entries = [{**v, "key": k} for k, v in entries.items()]
    defs, errors, seen = [], {}, set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors[f"field {i + 1}"] = "each field must be a table"
            continue
        key = _clean_key(entry.get("key", ""))
        where = key or f"field {i + 1}"
        if not key:
            errors[where] = "a field needs a key"
            continue
        scope = str(entry.get("applies_to", "company")).strip().lower()
        if scope not in SCOPES:
            errors[key] = f"applies_to must be one of {', '.join(SCOPES)}"
            continue
        if key in RESERVED[scope]:
            errors[key] = (f"{key!r} is already a built-in {scope} field; "
                           "a custom field with that key would shadow it")
            continue
        if (scope, key) in seen:
            errors[key] = "defined twice"
            continue
        seen.add((scope, key))
        kind = str(entry.get("type", "text")).strip().lower()
        if kind not in TYPES:
            errors[key] = f"type must be one of {', '.join(TYPES)}"
            continue
        options = [str(o) for o in (entry.get("options") or [])]
        if kind == "select" and not options:
            errors[key] = "a select field needs options"
            continue
        allowed = VIEWS_FOR_SCOPE[scope]
        show_in = [str(v).strip().lower() for v in (entry.get("show_in") or ["detail"])]
        bad = [v for v in show_in if v not in allowed]
        if bad:
            errors[key] = (f"show_in {', '.join(bad)} is not a place a {scope} field "
                           f"can appear; use {', '.join(allowed)}")
            continue
        defs.append(FieldDef(
            key=key, label=str(entry.get("label", "")).strip(), type=kind,
            applies_to=scope, help=str(entry.get("help", "")).strip(),
            options=options, show_in=show_in, enrich=bool(entry.get("enrich", False)),
            description=str(entry.get("description", "")).strip(),
        ))
    if errors:
        raise FieldError(errors)
    return defs


def load(root: Path | str) -> list[FieldDef]:
    """The folder's field definitions; an absent file means none."""
    path = Path(root) / FILENAME
    if not path.exists():
        return []
    with open(path, "rb") as fh:
        return parse(tomllib.load(fh))


def _toml(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(defs: list[FieldDef]) -> str:
    """`fields.toml` text for these definitions, written whole."""
    lines = [
        "# Fields you added yourself. Hermit CRM stores their values in the",
        "# front matter of the record they belong to, like any other key.",
        "# type: text, number, date or select. show_in: where the field appears.",
        "",
    ]
    for d in defs:
        lines.append("[[field]]")
        lines.append(f"key = {_toml(d.key)}")
        lines.append(f"label = {_toml(d.label)}")
        lines.append(f"type = {_toml(d.type)}")
        lines.append(f"applies_to = {_toml(d.applies_to)}")
        if d.help:
            lines.append(f"help = {_toml(d.help)}")
        if d.options:
            lines.append(f"options = {_toml(d.options)}")
        lines.append(f"show_in = {_toml(d.show_in)}")
        if d.enrich:
            lines.append("enrich = true")
        if d.description:
            lines.append(f"description = {_toml(d.description)}")
        lines.append("")
    return "\n".join(lines)


def write(root: Path | str, defs: list[FieldDef]) -> Path:
    path = Path(root) / FILENAME
    if defs:
        path.write_text(render(defs), encoding="utf-8")
    elif path.exists():
        path.unlink()
    return path


def for_scope(defs: list[FieldDef], scope: str) -> list[FieldDef]:
    return [d for d in defs if d.applies_to == scope]


def coerce_all(defs: list[FieldDef], raw: dict) -> tuple[dict, dict]:
    """(values, errors) for a form submission.

    Only keys present in `raw` are touched, so a form that does not carry a
    field leaves the stored value alone. An empty value clears it.
    """
    values, errors = {}, {}
    for d in defs:
        if d.key not in raw:
            continue
        try:
            values[d.key] = d.coerce(raw[d.key])
        except ValueError as exc:
            errors[d.key] = str(exc)
    return values, errors


def apply(extra: dict, values: dict) -> dict:
    """Custom values merged into a record's `extra`; None removes the key."""
    out = dict(extra or {})
    for key, value in values.items():
        if value is None or value == "":
            out.pop(key, None)
        else:
            out[key] = value
    return out
