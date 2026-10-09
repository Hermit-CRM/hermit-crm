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

"""Bulk changes with a dry run: `hermitcrm set`.

Changing many records at once is the one write that can do real damage quickly,
so it has two steps and one rule for each:

    plan(store, scope, where, ops)   what would change, per record, before -> after.
                                     Writes nothing, commits nothing.
    apply(store, plan)               writes it through the Store, checks the files
                                     it wrote, then makes ONE commit. If anything
                                     fails the files are put back exactly.

Three decisions hold the module together:

* `--where` is not a new query language. It is the per-column filter syntax of the
  list pages (`filters.py`), run on the very columns and rows those pages use
  (`web.company_columns`, `web.contact_columns`, `web.message_columns`), so a
  filter means here what it means in the browser.
* A plan is worked out by running the real change on a scratch copy of the
  matching companies, through the same Store methods the web forms call. That is
  why stage history, "lost needs a reason", number and date parsing and unknown
  front-matter keys behave exactly as they do on the company page, and why the
  before -> after lines can show side effects (a cleared lost_reason) instead of
  only what was asked for.
* Bodies are never touched, and neither are the fields that name a record.

The module has no files of its own, so it has nothing to validate and builds no
persistent items; `validate` and `built_items` exist so the hub can treat every
feature module alike.
"""

from __future__ import annotations

import dataclasses
import difflib
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import fields as fields_mod
from . import filters, pipeline
from .gitops import GitOps
from .models import (
    Country,
    Role,
    Source,
    ValidationError,
    company_to_frontmatter,
    contact_to_frontmatter,
    interaction_to_frontmatter,
    normalise_country,
    parse_tags,
)
from .stages import DEFAULT_STAGES
from .store import Store, load_config

SCOPES = ("companies", "contacts", "interactions")

# The word fields.toml uses for the same thing (`applies_to`).
_APPLIES_TO = {"companies": "company", "contacts": "contact", "interactions": "interaction"}
_NOUNS = {"companies": ("company", "companies"),
          "contacts": ("contact", "contacts"),
          "interactions": ("interaction", "interactions")}

# The built-in fields a bulk change may set, and whether each can be emptied.
# Everything else a record has is refused (see `_refusal`): names and ids, what
# Hermit keeps itself, and every body.
EDITABLE = {
    "companies": {
        "website": True, "linkedin": True, "country": True, "source": False,
        "lost_reason": True, "requalify_on": True, "value_eur_month": True,
        "product_oneliner": True, "next_step": True, "next_step_due": True,
        "next_step_status": False, "next_step_type": True, "tags": True,
    },
    "contacts": {
        "title": True, "linkedin": True, "email": True, "phone": True,
        "role": True, "language": True,
    },
    # Interactions: front matter that does not move the file. date, channel,
    # direction and contact are in the file name, so they are not here.
    "interactions": {"subject": True, "outcome": True},
}

_IDENTITY = {
    "companies": {"name", "slug"},
    "contacts": {"first_name", "last_name", "name", "slug"},
    "interactions": {"id", "date", "channel", "direction", "contact"},
}
_KEPT_BY_HERMIT = {
    "companies": {"created", "updated", "stage_changed", "stage_history", "tasks",
                  "next_step_done_on"},
    "contacts": {"created", "updated", "tasks"},
    "interactions": {"source", "message_id", "created", "updated"},
}
_BODY_NAMES = {"body", "notes", "message"}

# Fields that change as a side effect and say nothing the user asked for; they are
# compared (a record is changed if they differ) but not listed in the dry run
# unless nothing else differs.
_QUIET = {"updated", "stage_changed", "stage_history", "next_step_done_on"}

# What the Store may change on its own accord while it applies a change, per scope:
# a stage move clears or keeps lost_reason and requalify_on, a new next step is open.
# A change to any other field than the ones asked for is refused, so a bug that
# loses data (a field a write forgets to carry over) stops the change instead of
# running it on every record.
_CASCADE = {
    "companies": {"lost_reason", "requalify_on", "next_step_status", *_QUIET},
    "contacts": {"updated"},
    "interactions": {"updated"},
}


class BulkError(Exception):
    """A request that was refused before anything was written (exit code 2)."""

    code = 2


class ApplyError(BulkError):
    """A write that was tried and rolled back: the files are as they were (exit 1)."""

    code = 1


# ----------------------------------------------------------------- the contract


def validate(root: Path) -> list[str]:
    """Nothing to validate: bulk changes have no files of their own."""
    return []


def built_items(root: Path) -> list[dict]:
    """Nothing persistent to list: what a bulk change did is a `bulk:` commit, which
    the hub shows under Recent changes."""
    return []


# ----------------------------------------------------------------------- types


@dataclass
class Ops:
    """What to do to every matching record.

    `set` maps field -> the text a form would carry ("" clears the field);
    `unset` clears; `add_tags` / `remove_tags` edit a company's tags;
    `stage` moves companies through the normal stage-change path.
    """

    set: dict = field(default_factory=dict)
    unset: list = field(default_factory=list)
    add_tags: list = field(default_factory=list)
    remove_tags: list = field(default_factory=list)
    stage: str | None = None

    def is_empty(self) -> bool:
        return not (self.set or self.unset or self.add_tags or self.remove_tags
                    or self.stage)

    def phrases(self) -> list[str]:
        """Short wording of each operation, for the commit subject and the dry run."""
        out = [f"set {k}={v}" if str(v) != "" else f"clear {k}" for k, v in self.set.items()]
        out += [f"clear {k}" for k in self.unset]
        out += [f"add tag {t}" for t in self.add_tags]
        out += [f"remove tag {t}" for t in self.remove_tags]
        if self.stage:
            out.append(f"stage {self.stage}")
        return out


@dataclass
class FieldChange:
    field: str
    before: str
    after: str


@dataclass
class Change:
    """One record that would change."""

    scope: str
    company: str          # company slug
    key: str              # company slug, contact slug or interaction id
    label: str            # what the dry run calls it: slug, company/contact, company/id
    before: dict          # its front matter now (without `updated`), to spot a stale plan
    fields: list = field(default_factory=list)  # [FieldChange]

    @property
    def path(self) -> str:
        """The file this record lives in, relative to the data folder."""
        base = f"companies/{self.company}"
        if self.scope == "companies":
            return f"{base}/company.md"
        if self.scope == "contacts":
            return f"{base}/contacts/{self.key}.md"
        return f"{base}/interactions/{self.key}.md"


@dataclass
class Plan:
    scope: str
    where: list
    everything: bool
    ops: Ops
    matched: int
    changes: list
    skipped: int
    _resolved: object = field(default=None, repr=False, compare=False)

    @property
    def changed(self) -> int:
        return len(self.changes)

    @property
    def noun(self) -> str:
        return _NOUNS[self.scope][0]

    @property
    def nouns(self) -> str:
        return _NOUNS[self.scope][1]

    def count(self, n: int) -> str:
        """'1 company', '23 companies'."""
        return f"{n} {self.noun if n == 1 else self.nouns}"

    def describe_where(self) -> str:
        return f"all {self.nouns}" if self.everything else ", ".join(self.where)

    def subject(self) -> str:
        """The commit subject: `bulk: add tag priority on 23 companies (stage=prospect)`,
        shortened to 72 characters."""
        what = ", ".join(self.ops.phrases())
        base = f"bulk: {what} on {self.count(self.changed)}"
        full = f"{base} ({self.describe_where()})"
        if len(full) <= 72:
            return full
        if len(base) <= 72:
            return base
        return base[:69].rstrip() + "..."

    def render(self, arrow: str = "→", samples: int = 5) -> str:
        """The dry run, as text."""
        what = ", ".join(self.ops.phrases())
        head = (f"Dry run: {what} on all {self.nouns}" if self.everything
                else f"Dry run: {what} on {self.nouns} where {self.describe_where()}")
        lines = [head,
                 f"{self.count(self.matched)} {'matches' if self.matched == 1 else 'match'}. "
                 f"{self.changed} would change"
                 + (f"; {self.skipped} already look like this and are skipped."
                    if self.skipped else "."),
                 ""]
        for change in self.changes[:samples]:
            for fc in change.fields:
                lines.append(f"  {change.label}: {fc.field}: "
                             f"{_clip(fc.before)} {arrow} {_clip(fc.after)}")
        rest = self.changed - samples
        if rest > 0:
            lines.append(f"  and {rest} more.")
        lines += ["", "Nothing changed. Run again with --apply to change "
                      f"{self.count(self.changed)} in one commit."]
        return "\n".join(lines)

    def result(self, sha: str) -> str:
        """The line printed after --apply."""
        text = (f"{self.count(self.changed)} changed in one commit {sha}. "
                f"Undo: hermitcrm undo {sha}")
        if self.skipped:
            text += f"\n({self.count(self.skipped)} matched and already looked like this.)"
        return text


# ------------------------------------------------------------------ small helpers


def _blank(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _same(a, b) -> bool:
    return a == b or (_blank(a) and _blank(b))


def _show(value) -> str:
    """A front-matter value as the dry run prints it."""
    if _blank(value):
        return "(empty)"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return " ".join(str(value).split())


def _clip(text: str, width: int = 60) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


def _key(name: str) -> str:
    return str(name).strip().replace("-", "_")


def _hint(word: str, options) -> str:
    close = difflib.get_close_matches(str(word), [str(o) for o in options], n=1, cutoff=0.6)
    return f" Did you mean {close[0]}?" if close else ""


def parse_pairs(pairs) -> dict:
    """`--set field=value` pairs as a dict; the field's `-` is read as `_`."""
    out: dict = {}
    for pair in pairs or []:
        name, sep, value = str(pair).partition("=")
        name = _key(name)
        if not sep or not name:
            raise BulkError(f"--set wants field=value, got {pair!r}")
        if name in out:
            raise BulkError(f"--set {name} is given twice; give each field once")
        out[name] = value
    return out


# --------------------------------------------------------------- resolving the ops


@dataclass
class _Resolved:
    builtin: dict      # field -> text for the Store ("" clears)
    custom: dict       # field -> coerced value (None clears)
    add_tags: list
    remove_tags: list
    stage: str | None

    def asked(self) -> set:
        """The front-matter fields this change is meant to touch."""
        names = {*self.builtin, *self.custom}
        if self.add_tags or self.remove_tags:
            names.add("tags")
        if self.stage is not None:
            names.add("stage")
        return names


def _refusal(scope: str, name: str) -> str | None:
    """Why this built-in field is not changed in bulk, or None if it may be."""
    if name in _BODY_NAMES:
        if scope == "interactions":
            return ("interaction bodies are the record of what was said and are never "
                    "rewritten; only front-matter fields can change in bulk "
                    "(outcome, subject, and your own fields)")
        return ("text bodies are never changed in bulk; edit the notes on the page "
                "(a note about a person is an interaction)")
    if name in _IDENTITY[scope]:
        return (f"{name} names the record or its file, so it is not changed in bulk; "
                "use the record's own page in the web app")
    if name in _KEPT_BY_HERMIT[scope]:
        return f"{name} is kept by Hermit itself and cannot be set"
    if scope == "companies" and name == "stage":
        return "use --stage S for stages, so the move goes into the stage history"
    return None


def _check_field(scope: str, name: str, scope_defs: dict, other_defs: dict) -> None:
    """Raise a BulkError unless `name` is a field of this scope that may change."""
    editable = EDITABLE[scope]
    if name in scope_defs or name in editable:
        return
    why = _refusal(scope, name)
    if why:
        raise BulkError(f"cannot change {name} in bulk: {why}.")
    if name in other_defs:
        other = other_defs[name].applies_to
        raise BulkError(f"{name} is a {other} field, not a {_APPLIES_TO[scope]} field "
                        f"(see fields.toml); it cannot be set on {scope}.")
    known = [*editable, *scope_defs]
    raise BulkError(
        f"unknown field {name!r} for {scope}.{_hint(name, known)} To use a field of your "
        "own, add it to fields.toml first (hermitcrm help adjust-fields). "
        f"Fields you can change on {scope}: {', '.join(known)}.")


def _check_choice(name: str, value: str) -> str:
    """Early, friendly checks for the fields that take one of a fixed list."""
    if value == "":
        return value
    if name == "country":
        code = normalise_country(value)
        if code not in {c.value for c in Country}:
            raise BulkError(f"country: {value!r} is not a country code (use ISO codes "
                            "such as DE, NL, GB).")
        return value
    options = {
        "source": [s.value for s in Source],
        "role": [r.value for r in Role],
        "next_step_status": ["open", "done"],
    }.get(name)
    if options is not None and value not in options:
        raise BulkError(f"{name}: unknown value {value!r}.{_hint(value.lower(), options)} "
                        f"Allowed: {', '.join(options)}.")
    return value


def _resolve(scope: str, defs: list, ops: Ops, stages=None) -> _Resolved:
    if ops.is_empty():
        raise BulkError("nothing to do. Give --set FIELD=VALUE, --unset FIELD, --add-tag T, "
                        "--remove-tag T or --stage S.")
    mine = {d.key: d for d in fields_mod.for_scope(defs, _APPLIES_TO[scope])}
    other = {d.key: d for d in defs if d.applies_to != _APPLIES_TO[scope]}
    editable = EDITABLE[scope]
    builtin: dict = {}
    custom: dict = {}
    claimed: set = set()

    def claim(name: str) -> None:
        if name in claimed:
            raise BulkError(f"{name} is changed twice in one command; give each field once.")
        claimed.add(name)

    for raw_name, raw_value in ops.set.items():
        name = _key(raw_name)
        claim(name)
        _check_field(scope, name, mine, other)
        if name in mine:
            try:
                custom[name] = mine[name].coerce(raw_value)
            except ValueError as exc:
                raise BulkError(f"{name}: {exc}") from None
        else:
            builtin[name] = _check_choice(name, str(raw_value))
    for raw_name in ops.unset:
        name = _key(raw_name)
        claim(name)
        _check_field(scope, name, mine, other)
        if name in mine:
            custom[name] = None
        elif not editable[name]:
            raise BulkError(f"{name} cannot be empty; use --set {name}=VALUE instead.")
        else:
            builtin[name] = ""

    add = [t for raw in ops.add_tags for t in parse_tags(raw)]
    remove = [t for raw in ops.remove_tags for t in parse_tags(raw)]
    if add or remove:
        if scope != "companies":
            raise BulkError(f"only companies have tags; {scope} do not "
                            "(use --set with a field of your own).")
        claim("tags")
        clash = {t.lower() for t in add} & {t.lower() for t in remove}
        if clash:
            raise BulkError("the same tag is added and removed: " + ", ".join(sorted(clash)))

    stage = None
    if ops.stage:
        if scope != "companies":
            raise BulkError("--stage only works on companies (a stage belongs to a company). "
                            "To change contacts by stage, filter on the company instead.")
        stages = stages or DEFAULT_STAGES
        options = stages.names
        stage = str(ops.stage).strip()
        if stages.resolve(stage) not in options:
            raise BulkError(f"--stage: unknown stage {stage!r}.{_hint(stage.lower(), options)} "
                            f"Allowed: {', '.join(options)}.")
    return _Resolved(builtin, custom, add, remove, stage)


def _store_kwargs(record, resolved: _Resolved) -> dict:
    """The arguments for the Store's update_* call, for one record."""
    kwargs = dict(resolved.builtin)
    if resolved.stage is not None:
        kwargs["stage"] = resolved.stage
    if resolved.add_tags or resolved.remove_tags:
        tags = list(record.tags)
        have = {t.lower() for t in tags}
        for tag in resolved.add_tags:
            if tag.lower() not in have:
                tags.append(tag)
                have.add(tag.lower())
        drop = {t.lower() for t in resolved.remove_tags}
        kwargs["tags"] = [t for t in tags if t.lower() not in drop]
    if resolved.custom:
        kwargs["custom"] = dict(resolved.custom)
    return kwargs


# ------------------------------------------------------------------- the filters


def _custom_defs(root: Path) -> list:
    try:
        return fields_mod.load(root)
    except fields_mod.FieldError as exc:
        raise BulkError(f"fields.toml: {exc}. Fix it first (hermitcrm check).") from None


def _rows_and_columns(store: Store, scope: str, defs: list):
    """The rows and the filter columns of the list page for `scope`.

    The columns come from web.py itself, so a key and an operator mean here what
    they mean on the page. Two deliberate differences: every custom field of the
    scope is a column, shown in the list or not, and parked companies are in the
    rows (the page hides them behind a toggle).
    """
    from . import web  # lazy: the CLI's other commands should not pay for FastAPI

    view = {"companies": "companies", "contacts": "contacts", "interactions": "messages"}[scope]
    mine = [dataclasses.replace(d, show_in=sorted({*d.show_in, view}))
            for d in fields_mod.for_scope(defs, _APPLIES_TO[scope])]
    if scope == "companies":
        types = list(store.task_types)
        types += [n for n in store.type_names_in_use() if n not in types]
        return store.all(), web.company_columns(mine, types, store.stages)
    if scope == "contacts":
        rows = [web.ContactRow(company, contact)
                for company in store.all()
                for contact in sorted(company.contacts.values(), key=lambda c: c.name.lower())]
        return rows, web.contact_columns(mine)
    window = int(load_config(store.root).get("message_window_days", 14))
    today = store.today()
    uses = Counter(web.normalised_body(i.body) for c in store.companies.values()
                   for i in c.interactions if i.is_message)
    rows = [web.MessageRow(company, it, company.message_status(it, today, window, store.outcomes),
                           uses[web.normalised_body(it.body)])
            for company in store.all() for it in company.interactions if it.is_message]
    return rows, web.message_columns(web.message_statuses(store.outcomes), mine,
                                     store.stages)


def _find_column(name: str, cols: list):
    key = _key(name).replace(" ", "_")
    by_key = {c.key: c for c in cols}
    if key in by_key:
        return by_key[key]
    by_label = {c.label.replace(" ", "_"): c for c in cols}  # "last touch", "outcome", "sent"
    if key in by_label:
        return by_label[key]
    lowered = {k.lower(): c for k, c in {**by_label, **by_key}.items()}
    if key.lower() in lowered:
        return lowered[key.lower()]
    raise BulkError(f"unknown filter key {name!r}.{_hint(key, [*by_key, *by_label])} "
                    f"Keys: {', '.join(by_key)}.")


def _parse_where(where, cols: list) -> list:
    """[(column, spec)] from `key=value` texts; every pair has to hold.

    On a choice column a plain value is an exact choice and several of them are
    "any of" (ticking several boxes on the page, or `stage=prospect,engaged`).
    Everything else is the text syntax, so a range is `last_touch=>2026-01-01`
    plus `last_touch=<2026-06-01`.
    """
    conditions: list = []
    choices: dict = {}  # column key -> the one list of chosen values
    for text in where or []:
        name, sep, spec = str(text).partition("=")
        spec = spec.strip()
        if not sep or not name.strip():
            raise BulkError(f"--where wants key=value, got {text!r} "
                            "(for example --where 'country=DE' or --where 'fit_score=>70').")
        if not spec:
            raise BulkError(f"--where {name.strip()}= has no value. Use '-' for empty, "
                            "'*' for not empty.")
        col = _find_column(name, cols)
        if col.kind != "enum":
            _check_spec(col, spec)
            conditions.append((col, spec))
            continue
        for part in (p.strip() for p in (spec.split(",") if col.options else [spec])):
            if not part:
                continue
            if part in ("-", "*") or part[0] in "!=":
                # Empty, not empty, not, equals: the page only offers the choices,
                # but the text syntax is just as meaningful on them.
                conditions.append((dataclasses.replace(col, kind="text"), part))
                continue
            if col.key not in choices:
                choices[col.key] = []
                conditions.append((col, choices[col.key]))
            choices[col.key].append(_enum_value(col, part))
    return conditions


def _enum_value(col, value: str) -> str:
    if not col.options or value in col.options:
        return value
    if col.key == "country" and normalise_country(value) in col.options:
        return normalise_country(value)
    folded = {o.lower(): o for o in col.options}
    if value.lower() in folded:
        return folded[value.lower()]
    shown = ", ".join(col.options) if len(col.options) <= 12 else "ISO codes such as DE, NL"
    raise BulkError(f"{col.key}: {value!r} is not one of the choices.{_hint(value, col.options)} "
                    f"Choices: {shown}.")


def _check_spec(col, spec: str) -> None:
    """A `>` or `<` on a number or date column needs something to compare with;
    the page would show nothing, here that is a mistake worth saying."""
    if spec[0] in "<>" and len(spec) > 1 and col.kind in ("number", "date"):
        if filters._comparable(spec[1:].strip(), col.kind) is None:
            what = "a number" if col.kind == "number" else "a date as YYYY-MM-DD"
            raise BulkError(f"{col.key}: {spec[1:].strip()!r} is not {what}.")


def _match(rows: list, conditions: list) -> list:
    for col, spec in conditions:
        rows = filters.apply(rows, [col], {col.key: spec})
    return rows


def _ref(scope: str, row) -> tuple:
    """(company slug, record key, label) of a list row."""
    if scope == "companies":
        return row.slug, row.slug, row.slug
    if scope == "contacts":
        return row.company_slug, row.slug, f"{row.company_slug}/{row.slug}"
    return row.company_slug, row.id, f"{row.company_slug}/{row.id}"


# ------------------------------------------------------------ records and writing


def _meta(store: Store, scope: str, company_slug: str, key: str) -> dict | None:
    """A record's front matter as the file would carry it, without `updated`."""
    company = store.companies.get(company_slug)
    if company is None:
        return None
    if scope == "companies":
        meta = company_to_frontmatter(company)
    elif scope == "contacts":
        contact = company.contacts.get(key)
        meta = contact_to_frontmatter(contact) if contact else None
    else:
        it = next((i for i in company.interactions if i.id == key), None)
        meta = interaction_to_frontmatter(it) if it else None
    if meta is not None:
        meta.pop("updated", None)
    return meta


def _record(store: Store, scope: str, company_slug: str, key: str):
    company = store.companies.get(company_slug)
    if company is None:
        return None
    if scope == "companies":
        return company
    if scope == "contacts":
        return company.contacts.get(key)
    return next((i for i in company.interactions if i.id == key), None)


def _write_one(store: Store, scope: str, company_slug: str, key: str,
               resolved: _Resolved) -> None:
    """The change itself: the Store call the web form makes."""
    record = _record(store, scope, company_slug, key)
    if record is None:
        raise ValidationError({"record": f"{company_slug}/{key} is not there any more"})
    kwargs = _store_kwargs(record, resolved)
    if scope == "companies":
        store.update_company(company_slug, **kwargs)
    elif scope == "contacts":
        store.update_contact(company_slug, key, **kwargs)
    else:
        store.update_interaction(company_slug, key, **kwargs)


def _diff(before: dict, after: dict) -> tuple:
    """(what to show, every key that differs)."""
    keys = [*after, *(k for k in before if k not in after)]
    differing = [k for k in keys if not _same(before.get(k), after.get(k))]
    shown = [k for k in differing if k not in _QUIET] or differing
    changes = [FieldChange(k, _show(before.get(k)), _show(after.get(k))) for k in shown]
    return changes, differing


def _simulate(store: Store, scope: str, refs: list, resolved: _Resolved):
    """Run the change on a scratch copy of the matching companies.

    Returns (changes, skipped, errors). The copy lives in a temporary directory
    outside the data folder and is thrown away; the data folder is only read.
    """
    changes: list = []
    errors: dict = defaultdict(list)
    skipped = 0
    allowed = resolved.asked() | _CASCADE[scope]
    with tempfile.TemporaryDirectory(prefix="hermitcrm-bulk-") as tmp:
        scratch = Path(tmp)
        (scratch / "companies").mkdir()
        for slug in sorted({company for company, _, _ in refs}):
            shutil.copytree(store.company_dir(slug), scratch / "companies" / slug)
        sim = Store(scratch, silent_days=store.silent_days, outcomes=store.outcomes,
                    task_types=store.task_types, clock=store.clock, stages=store.stages)
        sim.load()
        for company, key, label in refs:
            before = _meta(sim, scope, company, key)
            if before is None:
                errors[("record", "it changed on disk since the lists were read")].append(label)
                continue
            try:
                _write_one(sim, scope, company, key, resolved)
            except ValidationError as exc:
                for name, message in exc.errors.items():
                    errors[(name, message)].append(label)
                continue
            after = _meta(sim, scope, company, key)
            if after is None:  # an interaction whose id is not its date-and-channel name
                errors[("record", "its file would be renamed, which a bulk change "
                                  "never does")].append(label)
                continue
            fields_changed, differing = _diff(before, after)
            if not differing:
                skipped += 1
                continue
            unasked = [k for k in differing if k not in allowed]
            if unasked:
                for name in unasked:
                    errors[(name, "would change without being asked to; this is a bug "
                                  "in Hermit CRM, not in your command")].append(label)
                continue
            changes.append(Change(scope, company, key, label, before, fields_changed))
    return changes, skipped, errors


def _refuse_errors(scope: str, errors: dict) -> BulkError:
    one, many = _NOUNS[scope]
    total = len({label for labels in errors.values() for label in labels})
    lines = [f"refused: {total} {one if total == 1 else many} cannot take this change, "
             "so nothing was written."]
    for (name, message), labels in sorted(errors.items(), key=lambda kv: -len(kv[1])):
        n = len(labels)
        who = (", ".join(labels) if n <= 3 else f"e.g. {', '.join(labels[:3])}")
        lines.append(f"  {name}: {message} ({n} {one if n == 1 else many}: {who})")
    lines.append("Fix the command (or narrow --where) and run the dry run again.")
    return BulkError("\n".join(lines))


# --------------------------------------------------------------------------- plan


def plan(store: Store, scope: str, where=None, ops: Ops | None = None, *,
         everything: bool = False) -> Plan:
    """What the change would do. Reads only; raises BulkError for a refused request.

    `where` is a list of `key=value` filter texts (the list pages' filter syntax).
    Without any, the request is refused unless `everything=True` says that every
    record is meant.
    """
    if scope not in SCOPES:
        singular = {"company": "companies", "contact": "contacts", "interaction": "interactions",
                    "message": "interactions", "messages": "interactions"}
        raise BulkError(f"unknown scope {scope!r}.{_hint(scope, [*SCOPES, *singular])}"
                        + (f" Did you mean {singular[scope]}?" if scope in singular else "")
                        + f" Scopes: {', '.join(SCOPES)}.")
    ops = ops or Ops()
    where = [str(w) for w in (where or [])]
    if where and everything:
        raise BulkError("--all and --where contradict each other: use --where to pick "
                        "records, or --all for every one.")
    if not where and not everything:
        noun = _NOUNS[scope][1]
        raise BulkError(f"this would change every one of your {noun}. Say which with "
                        "--where KEY=VALUE (repeatable, same syntax as the list filters, "
                        f"e.g. --where 'country=DE'), or add --all if you really mean all of them.")
    defs = _custom_defs(store.root)
    resolved = _resolve(scope, defs, ops, store.stages)
    rows, cols = _rows_and_columns(store, scope, defs)
    matched = _match(rows, _parse_where(where, cols))
    refs = [_ref(scope, row) for row in matched]
    changes, skipped, errors = _simulate(store, scope, refs, resolved) if refs else ([], 0, {})
    if errors:
        raise _refuse_errors(scope, errors)
    return Plan(scope, where, everything, ops, len(refs), changes, skipped, resolved)


# -------------------------------------------------------------------------- apply


def _commit_message(plan_: Plan, message: str | None) -> str:
    if message is None:
        subject = plan_.subject()
    else:
        text = " ".join(str(message).split())
        if text.lower().startswith("bulk:"):
            text = text[5:].strip()
        if not text:
            raise BulkError("--message is empty.")
        subject = f"bulk: {text}"
    body = [f"where: {plan_.describe_where()}", f"ops: {', '.join(plan_.ops.phrases())}",
            f"changed: {plan_.count(plan_.changed)}"
            + (f" ({plan_.skipped} more matched and were already like this)"
               if plan_.skipped else "")]
    return subject + "\n\n" + "\n".join(body)


def _restore(store: Store, snapshot: dict, companies: list, paths: list, staged: bool) -> None:
    """Put every file back byte for byte, and the index with it."""
    for rel, data in snapshot.items():
        path = store.root / rel
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(data)
    if staged:  # a commit that failed after `git add`: unstage, never touch history
        subprocess.run(["git", "reset", "-q", "--", *paths], cwd=store.root,
                       capture_output=True)
    store.take_touched()
    for slug in companies:
        store.reload_company(slug)


def _verify(store: Store, plan_: Plan, companies: list, problems_before: set) -> list:
    """Reload what was written and check it the way `hermitcrm check` does, plus
    that every file says what the plan said it would."""
    found = []
    for slug in companies:
        store.reload_company(slug)
    for problem in store.problems:
        if (problem.path, problem.message) not in problems_before:
            found.append(f"{problem.path}: {problem.message}")
    for change in plan_.changes:
        meta = _meta(store, plan_.scope, change.company, change.key)
        if meta is None:
            found.append(f"{change.path}: the record no longer loads")
            continue
        for fc in change.fields:
            now = _show(meta.get(fc.field))
            if now != fc.after:
                found.append(f"{change.path}: {fc.field}: expected {fc.after!r}, "
                             f"the file has {now!r}")
    return found


def apply(store: Store, plan_: Plan, message: str | None = None) -> str:
    """Write the plan: ONE commit, `bulk: <summary>`. Returns the commit sha.

    Under the store's write lock, so no other writer interleaves. Raises
    ApplyError, with every file put back exactly and nothing committed, if the
    folder moved since the plan, a write fails, the written files do not check
    out, or git refuses the commit.
    """
    if not plan_.changes:
        raise BulkError("nothing to apply: no record would change.")
    commit_message = _commit_message(plan_, message)
    scope = plan_.scope
    root = store.root
    config = load_config(root)
    git = GitOps(root, push_enabled=bool(config.get("push_enabled", True)),
                 remote=str(config.get("remote", "origin")))
    paths = sorted({c.path for c in plan_.changes})
    companies = sorted({c.company for c in plan_.changes})
    everything = [*paths, "PIPELINE.md"]

    with store.lock:
        # Start from what is on disk now. A plan older than another process's
        # write (the web app, the daily sync) is refused rather than merged.
        store.take_touched()
        for slug in companies:
            store.reload_company(slug)
        for change in plan_.changes:
            if _meta(store, scope, change.company, change.key) != change.before:
                raise ApplyError(f"{change.label} changed since the dry run, so nothing was "
                                 "written. Run the dry run again.")
        problems_before = {(p.path, p.message) for p in store.problems}
        snapshot = {rel: ((root / rel).read_bytes() if (root / rel).exists() else None)
                    for rel in everything}
        hook, store.on_write = store.on_write, None  # we commit once, below
        staged = False
        try:
            for change in plan_.changes:
                _write_one(store, scope, change.company, change.key, plan_._resolved)
            stray = set(store.take_touched()) - set(paths)
            if stray:
                raise ApplyError("a write touched a file the plan did not name: "
                                 + ", ".join(sorted(stray)))
            problems = _verify(store, plan_, companies, problems_before)
            if problems:
                raise ApplyError("the changed files do not check out: " + "; ".join(problems[:5]))
            pipeline.write(store)
            staged = True
            sha = git.commit(commit_message, everything)
            if not sha:
                raise ApplyError("git could not make the commit (is this folder a git "
                                 "repository with a working git?)")
        except BaseException as exc:
            _restore(store, snapshot, companies, everything, staged)
            if isinstance(exc, ValidationError):
                raise ApplyError("could not write: " + "; ".join(
                    f"{k}: {v}" for k, v in exc.errors.items())) from exc
            if isinstance(exc, ApplyError):
                raise ApplyError(f"rolled back, nothing changed. {exc}") from exc
            raise
        finally:
            store.on_write = hook
    git.push_async()
    return sha
