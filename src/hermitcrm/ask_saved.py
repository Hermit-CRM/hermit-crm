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

"""Saved questions for Ask the Hermit: the ones you keep asking, one click away.

They live in ``ask-questions.toml`` in the data folder, newest first, so they
travel with the git backup. Each is a ``[[question]]`` with an ``id`` (``q-`` and
six hex characters of the SHA-1 of the normalised text, so saving the same
question twice is one entry and editing the text makes a new id), the ``text``
(kept as typed, line breaks included) and a ``scope`` (``auto``, or ``crm`` for
"skip the page, search the whole CRM"). Every change is one commit.

A file that cannot be read is never overwritten: reading it gives an empty list
and the error, and a save refuses with that error, so a hand edit with a typo
is not lost to the next click.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .store import Store

SAVED_FILE = "ask-questions.toml"
MAX_SAVED = 100
MAX_TEXT = 2000
SCOPES = ("auto", "crm")
ID_PATTERN = re.compile(r"^q-[0-9a-f]{6}$")

_HEADER = ("# Questions you saved for Ask the Hermit (the Save button next to Ask, or the\n"
           "# Ask page). Newest first. Edit or delete here or on the Ask page; `scope` is\n"
           "# \"auto\", or \"crm\" to skip the page and search the whole CRM.\n")


class AskSavedError(ValueError):
    """A save, edit or delete that cannot be done; the message says why."""


@dataclass(frozen=True)
class Saved:
    id: str
    text: str
    scope: str = "auto"

    def as_json(self) -> dict:
        return {"id": self.id, "text": self.text, "scope": self.scope}


def normalise(text: str) -> str:
    """The text with white space collapsed: what two questions are compared by."""
    return " ".join((text or "").split())


def clean(text: str) -> str:
    """The question as it is kept: as typed, line breaks as \\n, no control characters."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch in "\n\t" or (ord(ch) >= 32 and ord(ch) != 127))
    return text.strip()


def question_id(text: str) -> str:
    digest = hashlib.sha1(normalise(text).casefold().encode("utf-8")).hexdigest()
    return "q-" + digest[:6]


def _scope(scope: str) -> str:
    return scope if scope in SCOPES else "auto"


# ------------------------------------------------------------------ reading

_cache: dict[str, tuple[tuple[int, int], list[Saved], str]] = {}


def read(root) -> tuple[list[Saved], str]:
    """(the saved questions newest first, the error that stopped the file being
    read or ""). A missing file is an empty list and no error. Cached on the
    file's size and modification time: every page asks."""
    path = Path(root) / SAVED_FILE
    try:
        stat = path.stat()
    except OSError:
        _cache.pop(str(path), None)
        return [], ""
    key = (stat.st_mtime_ns, stat.st_size)
    hit = _cache.get(str(path))
    if hit and hit[0] == key:
        return list(hit[1]), hit[2]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        saved, error = [], f"{SAVED_FILE} cannot be read: {exc}"
    else:
        saved, error = _parse(data), ""
    _cache[str(path)] = (key, saved, error)
    return list(saved), error


def _parse(data: object) -> list[Saved]:
    rows = data.get("question") if isinstance(data, dict) else None
    saved: list[Saved] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        text = clean(str(row.get("text", ""))) if isinstance(row, dict) else ""
        if not text or len(text) > MAX_TEXT:
            continue
        ident = question_id(text)  # recomputed: a hand edit of the text keeps it right
        if ident in seen:
            continue
        seen.add(ident)
        saved.append(Saved(ident, text, _scope(str(row.get("scope", "auto")))))
    return saved[:MAX_SAVED]


def load(root) -> list[Saved]:
    return read(root)[0]


# ------------------------------------------------------------------ writing


def _file_text(saved: list[Saved]) -> str:
    lines = [_HEADER]
    for item in saved:
        lines += ["[[question]]", f"id = {json.dumps(item.id)}",
                  f"text = {json.dumps(item.text, ensure_ascii=False)}",
                  f"scope = {json.dumps(item.scope)}", ""]
    return "\n".join(lines)


def _write(store: Store, saved: list[Saved], message: str) -> None:
    path = Path(store.root) / SAVED_FILE
    temp = path.with_name(SAVED_FILE + ".tmp")
    temp.write_text(_file_text(saved), encoding="utf-8")
    os.replace(temp, path)
    store.notify(message, [SAVED_FILE])


def _quoted(text: str) -> str:
    one_line = normalise(text)
    return one_line if len(one_line) <= 60 else one_line[:59].rstrip() + "…"


def _checked(text: str) -> str:
    text = clean(text)
    if not text:
        raise AskSavedError("Type a question to save.")
    if len(text) > MAX_TEXT:
        raise AskSavedError(f"A saved question is at most {MAX_TEXT} characters.")
    return text


def _current(store: Store) -> list[Saved]:
    saved, error = read(store.root)
    if error:
        raise AskSavedError(error + " Fix or remove the file, then save again.")
    return saved


def save(store: Store, text: str, scope: str = "auto") -> Saved:
    """(writes) Keep a question, newest first. The same question again changes
    nothing, or only its scope. One commit."""
    text, scope = _checked(text), _scope(scope)
    with store.lock:
        saved = _current(store)
        item = Saved(question_id(text), text, scope)
        existing = next((s for s in saved if s.id == item.id), None)
        if existing is not None:
            if existing.scope != scope:
                saved = [Saved(s.id, s.text, scope) if s.id == item.id else s for s in saved]
                _write(store, saved, f'ask: saved question "{_quoted(text)}" now {scope}')
            return next(s for s in saved if s.id == item.id)
        if len(saved) >= MAX_SAVED:
            raise AskSavedError(f"{MAX_SAVED} saved questions is the limit: delete one first.")
        _write(store, [item, *saved], f'ask: saved question "{_quoted(text)}"')
        return item


def remove(store: Store, question: str) -> Saved:
    """(writes) Forget a saved question by id. One commit."""
    with store.lock:
        saved = _current(store)
        gone = next((s for s in saved if s.id == question), None)
        if gone is None:
            raise AskSavedError("That saved question is already gone.")
        _write(store, [s for s in saved if s.id != question],
               f'ask: removed saved question "{_quoted(gone.text)}"')
        return gone


def replace(store: Store, question: str, text: str, scope: str = "auto") -> Saved:
    """(writes) Change a saved question in place. New text is a new id; if that
    question is saved already the two become one. One commit."""
    text, scope = _checked(text), _scope(scope)
    with store.lock:
        saved = _current(store)
        old = next((s for s in saved if s.id == question), None)
        if old is None:
            raise AskSavedError("That saved question is already gone.")
        item = Saved(question_id(text), text, scope)
        merged: list[Saved] = []
        for s in saved:
            if s.id == question:
                merged.append(item)
            elif s.id != item.id:
                merged.append(s)
        if item == old:
            return item
        _write(store, merged, f'ask: edited saved question "{_quoted(text)}"')
        return item
