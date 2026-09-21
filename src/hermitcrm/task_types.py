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

"""Task types: labels you define in Settings and put on a to-do.

A type is only a label with a colour. It changes no date, stage or order.
Stored as one config.toml line, `task_types = [{name = ..., colour = ...}]`,
and on a to-do by name, so a rename rewrites the to-dos (Store.rename_task_type).
"""

from __future__ import annotations

from dataclasses import dataclass

PALETTE = ("green", "blue", "amber", "red", "violet", "grey")
NONE = "(none)"          # the filter value for a to-do without a type
MAX_NAME = 40


@dataclass(frozen=True)
class TaskType:
    name: str
    colour: str = "grey"


def clean(name) -> str:
    return " ".join(str(name or "").split())


def from_config(raw) -> list[TaskType]:
    """The configured types, in order; bad or repeated entries are dropped."""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for entry in raw:
        if isinstance(entry, str):
            entry = {"name": entry}
        if not isinstance(entry, dict):
            continue
        name = clean(entry.get("name"))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        colour = str(entry.get("colour") or "").strip().lower()
        out.append(TaskType(name, colour if colour in PALETTE else "grey"))
    return out


def names(types: list[TaskType]) -> list[str]:
    return [t.name for t in types]


def colour_of(types: list[TaskType], name: str) -> str | None:
    """The colour of `name`, or None when Settings no longer has it."""
    return next((t.colour for t in types if t.name == name), None)


def to_config(types: list[TaskType]) -> list[dict]:
    return [{"name": t.name, "colour": t.colour} for t in types]


def plan_rows(row_names: list[str], colours: list[str], olds: list[str],
              delete: str = "", move: str = ""):
    """Read the Settings form: one row per type plus a blank row to add one.

    `olds` carries each row's saved name, so an edited name is a rename.
    `delete` is a row index; `move` is "<index>-up" or "<index>-down".
    Returns (types, renames {old: new}, errors).
    """
    rows = []
    errors: dict[str, str] = {}
    for i, raw in enumerate(row_names):
        if str(i) == delete:
            continue
        name = clean(raw)
        old = clean(olds[i] if i < len(olds) else "")
        colour = str(colours[i] if i < len(colours) else "").strip().lower()
        if not name:
            if old:
                errors["task_types"] = (f"Give {old!r} a name, or use Delete to "
                                        "remove it.")
            continue
        if len(name) > MAX_NAME:
            errors["task_types"] = f"{name[:20]}...: at most {MAX_NAME} characters."
        rows.append([name, colour if colour in PALETTE else "grey", old])
    seen: set[str] = set()
    for name, _, _ in rows:
        if name.lower() in seen:
            errors["task_types"] = f"Duplicate task type: {name}."
        seen.add(name.lower())
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
    types = [TaskType(name, colour) for name, colour, _ in rows]
    renames = {old: name for name, _, old in rows if old and old != name}
    return types, renames, errors
