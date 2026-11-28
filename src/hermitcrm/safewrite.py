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

"""Crash-safe saving: a record is either the old file or the new one, never half.

`Path.write_text` empties the file first and then writes it; a power cut, a
kill or a full disk in between leaves a cut-off record, and Hermit then treats
that company as unknown until it is restored from git. Here the text goes to a
temporary file in the same folder, is flushed to disk, and is then renamed over
the real name. A rename within one folder is atomic, so a reader (or the next
start after a crash) sees the old bytes or the new ones.

The bytes are the ones `write_text(text, encoding="utf-8")` writes (the same
newline handling), and the file keeps its permissions: a new file gets what
`write_text` would give it, an existing one keeps its own.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path


def temp_name(path: Path) -> Path:
    """A hidden name next to `path` that no loader takes for a record: it starts
    with "." and ends in ".tmp", so `*.md` never matches it."""
    return path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")


def write_text(path: Path | str, text: str) -> None:
    """Write `text` to `path` as UTF-8, replacing the file in one step."""
    path = Path(path)
    if path.is_symlink():  # write the file the link names; keep the link
        path = path.resolve()
    tmp = temp_name(path)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = None
    # O_EXCL: never write into a file someone else made; 0o666 less the umask
    # is what open() and write_text give a new file.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
