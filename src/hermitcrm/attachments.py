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

"""Files attached to an interaction (or, before it is sent, to an outreach item).

A file lives at `companies/<slug>/attachments/<stored name>`, where the stored
name is the first 12 hex characters of the SHA-256 of its content, a hyphen and
the cleaned-up name: the same bytes under the same name are one file, a rename
of the interaction that owns it changes nothing, and the prefix is a free
integrity check. The owner lists it in front matter:

    attachments:
      - {file: 3f9a1c2b7d10-Proposal v2.pdf, name: Proposal v2.pdf, size: 183204, type: application/pdf}

This module knows names, types and that format. It never touches the store.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

NAME_MAX = 100
HASH_LEN = 12
_STORED = re.compile(r"^[0-9a-f]{%d}-[^/\\\x00]+$" % HASH_LEN)
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)),
             *(f"LPT{n}" for n in range(1, 10))}
_UNSAFE = re.compile(r'[<>:"|?*]')

# What a browser may show in a tab. Everything else downloads: an .svg or .html
# shown inline would run on the app's own origin.
INLINE_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain",
})
_TYPES = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
    ".svg": "image/svg+xml", ".html": "text/html", ".htm": "text/html",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip", ".eml": "message/rfc822", ".ics": "text/calendar",
}


@dataclass(frozen=True)
class Attachment:
    file: str   # the stored name: "<sha256[:12]>-<cleaned name>"
    name: str   # the cleaned name the person sees and downloads it as
    size: int
    type: str   # from the extension; never from what the upload claimed


@dataclass
class Incoming:
    """A file on its way in: bytes the caller read, under the name it arrived with."""
    name: str
    data: bytes


def safe_name(name: str) -> str:
    """A name that is safe to keep in a folder on any system: no path, no control
    characters, nothing a file system treats specially, at most NAME_MAX
    characters with the extension kept, "file" when nothing is left."""
    text = unicodedata.normalize("NFC", str(name or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    parts = [p for p in re.split(r"[\\/]", text) if p.strip()]
    text = parts[-1] if parts else ""
    text = _UNSAFE.sub("_", text).strip().lstrip(".").rstrip(". ")
    stem, ext = os.path.splitext(text)
    if len(ext) > 20:
        stem, ext = text, ""
    if stem.upper() in _RESERVED:
        stem = "_" + stem
    stem = stem[:max(1, NAME_MAX - len(ext))].rstrip(". ")
    return f"{stem}{ext}" if stem else "file"


def media_type(name: str) -> str:
    ext = os.path.splitext(str(name or ""))[1].lower()
    return _TYPES.get(ext) or mimetypes.guess_type(f"x{ext}")[0] or "application/octet-stream"


def disposition(att: Attachment) -> str:
    """"inline" only for the harmless types, "attachment" for the rest."""
    return "inline" if media_type(att.name) in INLINE_TYPES else "attachment"


def stored_name(data: bytes, name: str) -> str:
    return f"{hashlib.sha256(data).hexdigest()[:HASH_LEN]}-{safe_name(name)}"


def is_stored_name(file: str) -> bool:
    return bool(_STORED.match(file or "")) and file == safe_stored(file)


def safe_stored(file: str) -> str:
    """`file` with its name part cleaned; equal to `file` when it already is."""
    return f"{file[:HASH_LEN]}-{safe_name(file[HASH_LEN + 1:])}"


def intact(path: Path) -> bool:
    """The file exists and its content still hashes to the prefix in its name."""
    path = Path(path)
    try:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest()[:HASH_LEN] == path.name[:HASH_LEN]


def make(data: bytes, name: str) -> Attachment:
    clean = safe_name(name)
    return Attachment(stored_name(data, name), clean, len(data), media_type(clean))


def to_meta(items) -> list[dict]:
    """The list as front matter: key order file, name, size, type."""
    return [{"file": a.file, "name": a.name, "size": a.size, "type": a.type} for a in items]


def from_meta(raw) -> list[Attachment]:
    """Attachments from front matter. Lenient: an entry that is not a map with a
    valid stored name is skipped (`hermitcrm check` reports what it cannot read),
    and the type is worked out from the name again, so a hand-edited `type` cannot
    make a script open inline."""
    out = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        file = str(entry.get("file") or "")
        if not is_stored_name(file):
            continue
        name = safe_name(entry.get("name") or file[HASH_LEN + 1:])
        size = entry.get("size")
        out.append(Attachment(file, name, size if isinstance(size, int) and size >= 0 else 0,
                              media_type(name)))
    return out


def files_of(interactions) -> list[tuple[Attachment, object]]:
    """(attachment, the interaction it came with) for every file once, newest
    first: `interactions` is newest first, so a file used twice shows with the
    newest note."""
    seen, out = set(), []
    for it in interactions:
        for att in getattr(it, "attachments", None) or []:
            if att.file not in seen:
                seen.add(att.file)
                out.append((att, it))
    return out


def audit(store) -> tuple[list[str], list[str]]:
    """(errors, warnings) for `hermitcrm check`, one "<path>: <what>" line each.
    A note that names a file that is gone is an error; a file nobody uses, one
    whose content no longer matches its name, or one over the size limit is a
    warning (the folder still works)."""
    errors, warnings = [], []
    cap = store.attachment_limit()
    for company in store.companies.values():
        slug = company.slug
        folder = store.company_dir(slug) / "attachments"
        for it in company.interactions:
            for att in it.attachments:
                if not (folder / att.file).is_file():
                    errors.append(f"companies/{slug}/interactions/{it.id}.md: attachment "
                                  f"{att.name} is missing (companies/{slug}/attachments/{att.file})")
        if not folder.is_dir():
            continue
        used = store.referenced_files(slug)
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.name.startswith("."):   # ".<name>.part" is scratch
                continue
            where = f"companies/{slug}/attachments/{path.name}"
            if path.name not in used:
                warnings.append(f"{where}: no note uses this file")
                continue
            if not intact(path):
                warnings.append(f"{where}: content does not match its hash")
            if path.stat().st_size > cap:
                warnings.append(f"{where}: larger than attachment_max_mb ({cap >> 20} MB)")
    return errors, warnings


def human_size(n) -> str:
    """"17 B", "1.2 KB", "3.4 MB": for chips and lists."""
    n = max(0, int(n or 0))
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
    return f"{n:.1f} GB"
