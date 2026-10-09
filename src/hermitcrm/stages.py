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

"""Deal stages: the names and order you choose, and a role for each.

A stage is more than a label. Its *role* tells Hermit what it means, so no name
is special: `open` stages are the board and the funnel, `won` and `lost` close
a deal (lost needs a reason), `closed` is any other end (such as disqualified)
and `parked` is out of the pipeline for now and returns to the entry stage.

Stored as one config.toml line, `stages = [{name = ..., role = ...}]`, and on a
company by name (`stage`, `stage_history[].from/to`), so a rename rewrites the
companies (Store.rename_stage). Without the key the defaults below apply, which
are the stages Hermit always had.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROLES = ("open", "won", "lost", "closed", "parked")
MAX_NAME = 30
# Unquoted, these parse as a bool or null in YAML, so a company file would not
# read back as the name that was written.
YAML_WORDS = ("yes", "no", "on", "off", "true", "false", "null", "~")
# Old stage names still accepted as input (imports, CLI); files were migrated.
ALIASES = {"reached-out": "engaged"}
_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
# Roles whose stage keeps the reason it was entered with, in `lost_reason`.
_REASON_ROLES = ("lost", "closed", "parked")
# Roles that end a deal (the old CLOSED_STAGES): not the parked ones.
_CLOSED_ROLES = ("won", "lost", "closed")


@dataclass(frozen=True)
class Stage:
    name: str
    role: str = "open"
    valued: bool = False          # open only: the PIPELINE.md heading shows EUR/month
    # Keys Hermit does not know (a future `colour`) ride along untouched.
    extra: dict = field(default_factory=dict, hash=False)


class StageSet:
    """The configured stages in order, with every question the code asks of them."""

    def __init__(self, stages):
        self.stages: tuple[Stage, ...] = tuple(stages)
        self._by_name = {s.name: s for s in self.stages}
        if not self.open:
            raise ValueError("a stage set needs at least one open stage")

    def __eq__(self, other) -> bool:
        return isinstance(other, StageSet) and self.stages == other.stages

    def __hash__(self) -> int:
        return hash(tuple(s.name for s in self.stages))

    def __iter__(self):
        return iter(self.stages)

    def __len__(self) -> int:
        return len(self.stages)

    def __contains__(self, name) -> bool:
        return name in self._by_name

    def __repr__(self) -> str:
        return f"StageSet({self.names})"

    # --- lists, in the order the user gave

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.stages]

    def with_role(self, *roles: str) -> list[str]:
        return [s.name for s in self.stages if s.role in roles]

    @property
    def open(self) -> list[str]:
        return self.with_role("open")

    board = open

    @property
    def closed(self) -> list[str]:
        """Stages that end a deal (won, lost, closed); not the parked ones."""
        return self.with_role(*_CLOSED_ROLES)

    @property
    def parked(self) -> list[str]:
        return self.with_role("parked")

    @property
    def closed_lists(self) -> list[str]:
        """Every stage that is not on the board, in order (the board's lists)."""
        return [s.name for s in self.stages if s.role != "open"]

    @property
    def reverse_open(self) -> list[str]:
        """PIPELINE.md shows the furthest stage first."""
        return list(reversed(self.open))

    @property
    def valued_names(self) -> list[str]:
        return [s.name for s in self.stages if s.role == "open" and s.valued]

    @property
    def funnel(self) -> list[str]:
        """The open stages, then the first `won` stage when there is one."""
        won = self.with_role("won")
        return self.open + won[:1]

    # --- the derived stages

    @property
    def entry(self) -> str:
        """Where a new company starts, and where a requalified one goes back to."""
        return self.open[0]

    @property
    def advance_target(self) -> str | None:
        """Where the entry stage moves on the first outbound touch, if anywhere."""
        names = self.names
        nxt = names[names.index(self.entry) + 1] if self.entry != names[-1] else None
        return nxt if nxt is not None and self.is_open(nxt) else None

    # --- questions about one name (unknown names answer "no" to all of them)

    def role_of(self, name) -> str | None:
        stage = self._by_name.get(name)
        return stage.role if stage else None

    def is_known(self, name) -> bool:
        return name in self._by_name

    def is_open(self, name) -> bool:
        return self.role_of(name) == "open"

    def is_closed(self, name) -> bool:
        return self.role_of(name) in _CLOSED_ROLES

    def is_parked(self, name) -> bool:
        return self.role_of(name) == "parked"

    def keeps_reason(self, name) -> bool:
        return self.role_of(name) in _REASON_ROLES

    def requires_reason(self, name) -> bool:
        return self.role_of(name) == "lost"

    def keeps_requalify(self, name) -> bool:
        return self.role_of(name) == "parked"

    def valued(self, name) -> bool:
        stage = self._by_name.get(name)
        return bool(stage and stage.role == "open" and stage.valued)

    def resolve(self, name):
        """`name` with an old alias applied, when its target exists here."""
        target = ALIASES.get(name)
        return target if target and target in self._by_name else name


DEFAULT_STAGES = StageSet([
    Stage("prospect"), Stage("engaged"),
    Stage("discovery", valued=True), Stage("offer", valued=True),
    Stage("won", "won"), Stage("lost", "lost"),
    Stage("disqualified", "closed"), Stage("temp-disqualified", "parked"),
])


# ------------------------------------------------------------------ config


def name_problem(name) -> str | None:
    """Why `name` cannot be a stage name, or None. Names are written into
    company files, so they must read back as the same string."""
    name = str(name or "")
    if not name:
        return "needs a name"
    if len(name) > MAX_NAME:
        return f"{name[:20]}...: at most {MAX_NAME} characters"
    if name in YAML_WORDS:
        return f"{name!r} is a reserved word (it would read back as true, false or null)"
    if not _NAME.fullmatch(name):
        return (f"{name!r}: use only a-z, 0-9 and single hyphens between them")
    try:
        if yaml.safe_load(name) != name:  # 123, 2026-10-09, 0x1f ...
            return f"{name!r} would read back as a number or date; add a letter"
    except yaml.YAMLError:
        return f"{name!r} is not a plain word"
    return None


def clean(name) -> str:
    """What a name typed in a form becomes: lowercase, spaces as hyphens."""
    return "-".join(str(name or "").lower().split())


def _parse(raw) -> tuple[list[Stage], list[str]]:
    if raw is None:
        return list(DEFAULT_STAGES.stages), []
    if not isinstance(raw, list):
        return [], ["config.toml: stages: must be a list, e.g. "
                    'stages = [{name = "prospect", role = "open"}, ...]']
    out: list[Stage] = []
    problems: list[str] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw, 1):
        where = f"config.toml: stages entry {i}"
        if isinstance(entry, str):
            entry = {"name": entry}
        if not isinstance(entry, dict):
            problems.append(f"{where}: must be a table with a name and a role")
            continue
        name = str(entry.get("name") or "").strip()
        bad = name_problem(name)
        if bad:
            problems.append(f"{where}: {bad}")
            continue
        if name in seen:
            problems.append(f"{where}: {name} is there twice")
            continue
        role = str(entry.get("role") or "open").strip().lower()
        if role not in ROLES:
            problems.append(f"{where} ({name}): role {role!r} is not one of "
                            f"{', '.join(ROLES)}")
            continue
        valued = entry.get("valued", False)
        if not isinstance(valued, bool):
            problems.append(f"{where} ({name}): valued must be true or false")
            valued = False
        if valued and role != "open":
            problems.append(f"{where} ({name}): valued only applies to open stages")
            valued = False
        seen.add(name)
        extra = {k: v for k, v in entry.items() if k not in ("name", "role", "valued")}
        out.append(Stage(name, role, valued, extra))
    if not any(s.role == "open" for s in out):
        problems.append("config.toml: stages: needs at least one stage with role open")
        return [], problems
    return out, problems


def from_config(raw) -> StageSet:
    """The configured stages, in order; bad or repeated entries are dropped. An
    absent or unusable setting means the defaults."""
    stages, _ = _parse(raw)
    return StageSet(stages) if stages else DEFAULT_STAGES


def problems(raw) -> list[str]:
    """What `hermitcrm check` says about the `stages` setting (empty when fine)."""
    return _parse(raw)[1]


def to_config(stage_set: StageSet) -> list[dict]:
    out = []
    for s in stage_set:
        entry = {"name": s.name, "role": s.role}
        if s.valued and s.role == "open":
            entry["valued"] = True
        entry.update(s.extra)
        out.append(entry)
    return out


def load(root) -> StageSet:
    """The stages configured for the data folder at `root` (the defaults when
    there is no setting or config.toml cannot be read)."""
    from .store import load_config
    try:
        return from_config(load_config(Path(root)).get("stages"))
    except Exception:  # an unreadable config.toml is `check`'s to report
        return DEFAULT_STAGES


def entry_moves(old: StageSet, new: StageSet, renames: dict[str, str] | None = None) -> bool:
    """Whether a change moves the entry stage (the implied start of every
    history, the requalify target), once renames are applied."""
    return (renames or {}).get(old.entry, old.entry) != new.entry


# ------------------------------------------------------------- settings form


def plan_rows(row_names: list[str], row_roles: list[str], valued_rows: list[str],
              olds: list[str], existing: StageSet | None = None,
              delete: str = "", move: str = ""):
    """Read the Settings form: one row per stage plus a blank row to add one.

    `olds` carries each row's saved name, so an edited name is a rename.
    `valued_rows` holds the indexes of the rows whose box is ticked.
    `delete` is a row index; `move` is "<index>-up" or "<index>-down".
    Returns (StageSet or None when there are errors, renames {old: new},
    removed [names that are gone], errors {"stages": message}).
    """
    rows = []
    errors: dict[str, str] = {}
    for i, raw in enumerate(row_names):
        if str(i) == delete:
            continue
        name = clean(raw)
        old = clean(olds[i] if i < len(olds) else "")
        role = str(row_roles[i] if i < len(row_roles) else "open").strip().lower()
        if not name:
            if old:
                errors["stages"] = f"Give {old!r} a name, or use Delete to remove it."
            continue
        bad = name_problem(name)
        if bad:
            errors["stages"] = bad
        if role not in ROLES:
            errors["stages"] = f"{name}: role must be one of {', '.join(ROLES)}."
            role = "open"
        rows.append([name, role, str(i) in valued_rows and role == "open", old])
    seen: set[str] = set()
    for name, *_ in rows:
        if name in seen:
            errors["stages"] = f"Duplicate stage: {name}."
        seen.add(name)
    if rows and not any(r[1] == "open" for r in rows):
        errors["stages"] = "At least one stage must have the role open."
    elif not rows:
        errors["stages"] = "At least one stage must have the role open."
    index, _, direction = move.partition("-")
    if index.isdigit() and rows:
        # `move` counts rows as the form showed them, before any delete.
        shown = [i for i, raw in enumerate(row_names)
                 if str(i) != delete and clean(raw)]
        if int(index) in shown:
            at = shown.index(int(index))
            to = at - 1 if direction == "up" else at + 1
            if 0 <= to < len(rows):
                rows[at], rows[to] = rows[to], rows[at]
    if errors:
        return None, {}, [], errors
    carried = {s.name: s.extra for s in existing} if existing else {}
    stage_set = StageSet([Stage(name, role, valued, dict(carried.get(old or name, {})))
                          for name, role, valued, old in rows])
    renames = {old: name for name, _, _, old in rows if old and old != name}
    kept = {old for *_, old in rows if old}
    removed = [n for n in (existing.names if existing else [])
               if n not in kept and n not in stage_set]
    return stage_set, renames, removed, errors
