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

"""The suppression list (spec part 08): addresses that are never mailed again.

`outreach/suppressed.toml` holds one `[[suppressed]]` table per address: the
address, the reason (`bounced`, `opted-out`, `manual`), the date and the
outreach item that led to it. It is a file of its own, not front matter, so it
needs no migration; it is committed like everything else and written
deterministically (sorted, the same entries give the same bytes).

A file that cannot be read is an error, never "nobody is suppressed": sending
fails closed (`SuppressError`) until it is fixed.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .models import normalise_email

FILE = "outreach/suppressed.toml"
REASONS = ("bounced", "opted-out", "manual")
HEADER = ("# Addresses Hermit CRM never mails again (bounced, opted out, or added by you).\n"
          "# One [[suppressed]] table each; delete a table to mail the address again.\n")


class SuppressError(Exception):
    """The list cannot be read; the message says where and why."""


@dataclass(frozen=True)
class Entry:
    address: str
    reason: str = "manual"
    date: str = ""       # YYYY-MM-DD
    item: str = ""       # the outreach item it came from, if any


def path(root: Path | str) -> Path:
    return Path(root) / FILE


def load(root: Path | str) -> list[Entry]:
    """Every entry, sorted by address. SuppressError when the file is broken."""
    file = path(root)
    if not file.exists():
        return []
    try:
        with open(file, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SuppressError(f"{FILE} cannot be read ({exc}); fix or remove it: sending "
                            "stays stopped until it can be") from exc
    rows = data.get("suppressed", [])
    if not isinstance(rows, list):
        raise SuppressError(f"{FILE}: `suppressed` must be a list of [[suppressed]] tables")
    out: dict[str, Entry] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SuppressError(f"{FILE}: every [[suppressed]] must be a table")
        address = normalise_email(str(row.get("address") or ""))
        if not address:
            raise SuppressError(f"{FILE}: a [[suppressed]] table has no address")
        reason = str(row.get("reason") or "manual")
        entry = Entry(address=address, reason=reason if reason in REASONS else "manual",
                      date=str(row.get("date") or ""), item=str(row.get("item") or ""))
        out.setdefault(address, entry)
    return sorted(out.values(), key=lambda e: e.address)


def render(entries) -> str:
    lines = [HEADER]
    for e in sorted(entries, key=lambda e: e.address):
        lines += ["", "[[suppressed]]", f"address = {json.dumps(e.address)}",
                  f"reason = {json.dumps(e.reason)}", f"date = {json.dumps(e.date)}",
                  f"item = {json.dumps(e.item)}"]
    return "\n".join(lines).rstrip("\n") + "\n"


def is_suppressed(root: Path | str, address: str) -> bool:
    key = normalise_email(address)
    return bool(key) and any(e.address == key for e in load(root))


def lookup(root: Path | str, address: str) -> Entry | None:
    key = normalise_email(address)
    return next((e for e in load(root) if e.address == key), None)


def add(root: Path | str, address: str, reason: str, when: str = "", item: str = "") -> Entry:
    """Put `address` on the list (written, not committed: the caller commits
    through the store). An address already on it keeps its first entry."""
    key = normalise_email(address)
    if not key or "@" not in key:
        raise SuppressError(f"{address!r} is not an email address")
    if reason not in REASONS:
        raise SuppressError(f"the reason is one of {', '.join(REASONS)}")
    entries = load(root)
    found = next((e for e in entries if e.address == key), None)
    if found is not None:
        return found
    entry = Entry(address=key, reason=reason, date=when, item=item)
    file = path(root)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(render([*entries, entry]), encoding="utf-8")
    return entry
