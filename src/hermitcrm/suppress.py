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
import re
import tomllib
from dataclasses import dataclass
from email import message_from_bytes, policy
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


# ------------------------------------------------------ delivery reports (DSN)

BOUNCE_WINDOW = 50      # the last sends the rate is measured over
BOUNCE_MAX = 3          # more than this many bounces in the window pauses sending
BOUNCE_RATE = 0.05      # or a rate over this, once there are MIN_FOR_RATE sends
MIN_FOR_RATE = 20       # one bounce in the first five sends is not a rate


@dataclass(frozen=True)
class Bounce:
    address: str         # who it could not be delivered to
    message_id: str      # the Message-ID of the mail that bounced, when the report has it
    status: str          # 5.1.1
    reason: str          # the server's own words


def _field(block, name: str) -> str:
    return " ".join(str(block.get(name) or "").split())


def _address_of(value: str) -> str:
    """'rfc822; Jane@Example.org' -> 'jane@example.org'."""
    value = value.split(";", 1)[1] if ";" in value else value
    m = re.search(r"[^\s<>\"',;]+@[^\s<>\"',;]+", value)
    return normalise_email(m.group(0)) if m else ""


def _original_id(msg) -> str:
    """The Message-ID of the mail the report is about: the delivery-status block's
    X-Original-Message-ID (Gmail), the quoted message's own header, or the quoted
    headers (Postfix and most others)."""
    for part in msg.walk():
        kind = part.get_content_type()
        if kind == "message/delivery-status":
            blocks = part.get_payload()
            first = blocks[0] if isinstance(blocks, list) and blocks else None
            found = _field(first, "X-Original-Message-ID") if first is not None else ""
            if found:
                return found
        elif kind == "message/rfc822":
            inner = part.get_payload()
            inner = inner[0] if isinstance(inner, list) and inner else None
            found = _field(inner, "Message-ID") if inner is not None else ""
            if found:
                return found
        elif kind in ("text/rfc822-headers", "text/rfc822-headers; charset=utf-8"):
            text = part.get_content() if hasattr(part, "get_content") else ""
            m = re.search(r"^Message-ID:\s*(<[^>\s]+>)", str(text), re.I | re.M)
            if m:
                return m.group(1)
    return ""


def parse_dsn(raw: bytes) -> list[Bounce]:
    """The hard bounces in one raw mail: a multipart/report with a delivery-status
    part, one Bounce per recipient whose Action is `failed` with a 5.x.x Status.
    Delay notices, auto-replies and anything else give []."""
    try:
        msg = message_from_bytes(raw, policy=policy.default)
    except Exception:
        return []
    if msg.get_content_type() != "multipart/report":
        return []
    original = _original_id(msg)
    out = []
    for part in msg.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        blocks = part.get_payload()
        for block in (blocks[1:] if isinstance(blocks, list) else []):
            action = _field(block, "Action").lower()
            status = _field(block, "Status")
            address = _address_of(_field(block, "Final-Recipient")
                                  or _field(block, "Original-Recipient"))
            if action != "failed" or not status.startswith("5") or not address:
                continue
            reason = _field(block, "Diagnostic-Code")
            reason = reason.split(";", 1)[1].strip() if ";" in reason else reason
            out.append(Bounce(address=address, message_id=original, status=status,
                              reason=reason or status))
    return out


def bounce_pause(sends: int, bounces: int) -> bool:
    """Whether the bounces among the last `sends` mails (at most BOUNCE_WINDOW) are
    too many: more than BOUNCE_MAX, or over BOUNCE_RATE once there are enough sends
    for a rate to mean something."""
    if bounces > BOUNCE_MAX:
        return True
    return sends >= MIN_FOR_RATE and bounces / max(sends, 1) > BOUNCE_RATE
