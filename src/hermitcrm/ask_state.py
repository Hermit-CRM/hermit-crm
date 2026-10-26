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

"""What you asked lately and how often: the state behind "most used first" and "Recent".

Kept in ``.git/hermitcrm-ask.json`` (the same tier as ``hermitcrm-send.json``): never a
file in the data, so never committed and never a line in ``git status``. It is a
convenience, not data, so it is allowed to be lost: a missing or damaged file reads as
empty and the next ask writes a fresh one. Nothing here may stop a question being asked.

    {"recent": [{"text": ..., "scope": "auto"|"crm", "at": "2026-10-26T09:30"}, ...],
     "uses":   {"q-1a2b3c": 4, ...}}

``recent`` is newest first, at most ``MAX_RECENT``, one entry per question (compared the
way saved questions are: case and spacing ignored; asking it again moves it to the
front). ``uses`` counts how often each *saved* question was asked; an id that is no
longer saved is dropped the next time the file is written.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import ask_saved, send

logger = logging.getLogger("hermitcrm.ask_state")

STATE_FILE = "hermitcrm-ask.json"
MAX_RECENT = 20

_lock = threading.Lock()


@dataclass(frozen=True)
class Recent:
    id: str
    text: str
    scope: str = "auto"
    at: str = ""

    def as_json(self) -> dict:
        """What the page script needs (the time stays in the file)."""
        return {"id": self.id, "text": self.text, "scope": self.scope}


@dataclass(frozen=True)
class State:
    recent: tuple[Recent, ...] = ()
    uses: dict[str, int] = field(default_factory=dict)


def path(root) -> Path:
    return send.runtime_dir(root) / STATE_FILE


# ------------------------------------------------------------------ reading

_cache: dict[str, tuple[tuple[int, int], State]] = {}


def load(root) -> State:
    """The state, cached on the file's size and modification time (every page asks).
    A missing or damaged file is the empty state; this never raises."""
    file = path(root)
    try:
        stat = file.stat()
    except OSError:
        _cache.pop(str(file), None)
        return State()
    key = (stat.st_mtime_ns, stat.st_size)
    hit = _cache.get(str(file))
    if hit and hit[0] == key:
        return hit[1]
    try:
        state = _parse(json.loads(file.read_text(encoding="utf-8")))
    except (OSError, ValueError):   # UnicodeDecodeError and JSONDecodeError are ValueErrors
        state = State()
    _cache[str(file)] = (key, state)
    return state


def _parse(data: object) -> State:
    if not isinstance(data, dict):
        return State()
    recent: list[Recent] = []
    seen: set[str] = set()
    rows = data.get("recent")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        text = ask_saved.clean(str(row.get("text") or ""))[:ask_saved.MAX_TEXT]
        if not text:
            continue
        ident = ask_saved.question_id(text)   # recomputed, as for saved questions
        if ident in seen:
            continue
        seen.add(ident)
        scope = str(row.get("scope") or "auto")
        recent.append(Recent(ident, text, scope if scope in ask_saved.SCOPES else "auto",
                             str(row.get("at") or "")))
    uses: dict[str, int] = {}
    counts = data.get("uses")
    for ident, count in (counts.items() if isinstance(counts, dict) else []):
        if (isinstance(ident, str) and ask_saved.ID_PATTERN.match(ident)
                and isinstance(count, int) and not isinstance(count, bool) and count > 0):
            uses[ident] = count
    return State(tuple(recent[:MAX_RECENT]), uses)


# ------------------------------------------------------------------ writing


def record(root, text: str, scope: str = "auto", now: datetime | None = None) -> None:
    """Note that a question was asked: it becomes the newest recent, and when it is a
    saved question its use count goes up. Never raises: a state that cannot be written
    is logged and the ask goes on."""
    try:
        _record(root, text, scope, now or datetime.now())
    except Exception:   # noqa: BLE001 - a convenience must never block an ask
        logger.warning("could not update %s", path(root), exc_info=True)


def _record(root, text: str, scope: str, now: datetime) -> None:
    text = ask_saved.clean(text)[:ask_saved.MAX_TEXT].strip()
    if not text:
        return
    scope = "crm" if scope in ("crm", "deep") else "auto"
    ident = ask_saved.question_id(text)
    saved_ids = {s.id for s in ask_saved.load(root)}
    with _lock:
        state = load(root)
        recent = [Recent(ident, text, scope, now.strftime("%Y-%m-%dT%H:%M")),
                  *[r for r in state.recent if r.id != ident]][:MAX_RECENT]
        uses = {i: n for i, n in state.uses.items() if i in saved_ids}
        if ident in saved_ids:
            uses[ident] = uses.get(ident, 0) + 1
        _write(root, recent, uses)


def _write(root, recent: list[Recent], uses: dict[str, int]) -> None:
    file = path(root)
    body = json.dumps({"recent": [{"text": r.text, "scope": r.scope, "at": r.at}
                                  for r in recent],
                       "uses": dict(sorted(uses.items()))},
                      indent=1, ensure_ascii=False) + "\n"
    temp = file.with_name(f"{STATE_FILE}.{os.getpid()}.tmp")
    try:
        temp.write_text(body, encoding="utf-8")
        os.replace(temp, file)
    finally:
        temp.unlink(missing_ok=True)
    _cache.pop(str(file), None)


# ----------------------------------------------------------------- ordering


def ranked(saved: list[ask_saved.Saved], uses: dict[str, int]) -> list[ask_saved.Saved]:
    """Most used first; ties keep the file's order (newest first), the sort is stable."""
    return sorted(saved, key=lambda s: -uses.get(s.id, 0))


def unsaved(state: State, saved: list[ask_saved.Saved]) -> list[Recent]:
    """The recent questions that are not saved (a saved one is already offered as such)."""
    kept = {s.id for s in saved}
    return [r for r in state.recent if r.id not in kept]
