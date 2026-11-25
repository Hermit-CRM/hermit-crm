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

"""Client folders: a normal folder per company, outside the data folder.

One root folder is set in config.toml (`client_files_root`). Each company's
folder is `<root>/<company name>`, the name cleaned the way attachment names
are (`attachments.safe_name`). A folder made by hand as the slug, or with other
upper and lower case, is found too. Nothing about it is stored: no front-matter
key, no file in the data folder, no commit. The pages list the folder as it is
on disk each time they are shown.

Hermit only links to these files. It never copies, moves, deletes or commits
them; it makes a company's folder only when asked (the Create folder button,
`hermitcrm folders --create`), and opens a file in its own app the way a
double-click in Finder would. Anything that could run (an app, a script, a file
with an exec bit) is shown in Finder instead of opened, so a file dropped in a
client folder can never be launched from a web page.

This module knows paths, names and commands. It never touches the store.
"""

from __future__ import annotations

import os
import subprocess
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .attachments import safe_name

CONFIG_KEY = "client_files_root"
LIST_LIMIT = 300
MAX_DEPTH = 3
# Stop counting past this many entries: a root pointed at a whole disk must not
# hang a page.
WALK_CAP = 20000

# Never launched, only shown in Finder: apps, installers, scripts.
RISKY_SUFFIXES = frozenset({
    ".app", ".command", ".sh", ".tool", ".terminal", ".workflow", ".pkg", ".dmg",
    ".scpt", ".applescript", ".jar", ".exe", ".bat", ".cmd", ".ps1", ".py", ".rb",
    ".pl",
})
_SKIP_NAMES = frozenset({".DS_Store", "Icon\r", "Thumbs.db", "desktop.ini"})


@dataclass(frozen=True)
class FileEntry:
    rel: str            # path inside the company folder, "/" between parts
    size: int           # bytes; 0 for a folder
    modified: datetime
    is_dir: bool

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class Listing:
    files: list[FileEntry]
    total: int          # every entry seen (up to WALK_CAP)
    truncated: bool     # more than `files` holds


def root(config: dict) -> Path | None:
    """The root folder, `~` expanded and made absolute; None when unset (off)."""
    raw = str((config or {}).get(CONFIG_KEY) or "").strip()
    if not raw:
        return None
    return Path(os.path.abspath(os.path.expanduser(raw)))


def inside(path: Path, folder: Path) -> bool:
    """`path` is `folder` or somewhere under it, symlinks followed."""
    try:
        return Path(path).resolve().is_relative_to(Path(folder).resolve())
    except (OSError, RuntimeError):
        return False


def root_problem(root_path: Path | None, data_dir: Path) -> str:
    """Why the root cannot be used, or "" when it can (or is unset)."""
    if root_path is None:
        return ""
    if inside(root_path, data_dir) or inside(data_dir, root_path):
        return (f"{root_path} is inside the data folder (or holds it): client files "
                "there would end up in git. Pick a folder outside it.")
    return ""


def folder_name(company) -> str:
    """What the company's folder is called: its name, cleaned to be safe on disk."""
    return safe_name(company.name)


def expected_folder(root_path: Path, company) -> Path:
    """The folder Create makes: `<root>/<folder_name>`."""
    return Path(root_path) / folder_name(company)


def _key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def find_folder(root_path: Path | None, company) -> Path | None:
    """The company's folder if there is one: `<root>/<name>`, else `<root>/<slug>`,
    else a direct child of the root that matches either ignoring case (and
    Unicode normal form)."""
    if root_path is None:
        return None
    root_path = Path(root_path)
    names = [folder_name(company), company.slug]
    for name in names:
        candidate = root_path / name
        if candidate.is_dir():
            return candidate
    wanted = {_key(n) for n in names}
    try:
        children = sorted(root_path.iterdir(), key=lambda p: p.name)
    except OSError:
        return None
    for child in children:
        if _key(child.name) in wanted and child.is_dir():
            return child
    return None


def _skipped(name: str) -> bool:
    return name.startswith(".") or name.startswith("~$") or name in _SKIP_NAMES


def _walk(folder: Path):
    """(rel, path, is_dir, stat) for everything list_files may show, in walk order.

    Hidden files, Office lock files (`~$...`) and Finder's own files are left
    out. A symlinked folder is yielded but not walked into, and a symlink that
    points out of the folder is left out. Stops after WALK_CAP entries.
    """
    folder = Path(folder)
    seen = 0
    stack: list[tuple[Path, int]] = [(folder, 1)]
    while stack:
        current, depth = stack.pop()
        try:
            children = list(os.scandir(current))
        except OSError:
            continue
        for entry in children:
            if _skipped(entry.name):
                continue
            path = Path(entry.path)
            try:
                is_link = entry.is_symlink()
                if is_link and not inside(path, folder):
                    continue
                is_dir = entry.is_dir()
                info = entry.stat()
            except OSError:
                continue
            yield path.relative_to(folder).as_posix(), path, is_dir, info
            seen += 1
            if seen >= WALK_CAP:
                return
            if is_dir and not is_link and depth < MAX_DEPTH:
                stack.append((path, depth + 1))


def list_files(folder: Path, limit: int = LIST_LIMIT) -> Listing:
    """What is in the folder, up to MAX_DEPTH levels deep, newest first (see _walk
    for what is left out)."""
    found = [FileEntry(rel, 0 if is_dir else info.st_size,
                       datetime.fromtimestamp(info.st_mtime), is_dir)
             for rel, _, is_dir, info in _walk(folder)]
    found.sort(key=lambda e: (-e.modified.timestamp(), e.rel))
    return Listing(found[:limit], len(found), len(found) > limit)


def resolve(folder: Path, rel: str) -> Path:
    """The entry of the folder that list_files shows as `rel`, or the folder itself
    for "". ValueError for anything else: a path that leaves the folder (`..`, an
    absolute path, a symlink out), a hidden file, or one that is not there.

    The answer is always a path the walk found on disk, never one built from
    `rel`: what a request names can only pick among the listed entries."""
    rel = str(rel or "")
    if rel == "":
        return Path(folder)
    for found, path, _, _ in _walk(folder):
        if found == rel:
            return path
    raise ValueError(f"{rel!r} is not in the folder")


def _risky(path: Path, platform: str) -> bool:
    path = Path(path)
    if path.is_dir() or path.suffix.lower() in RISKY_SUFFIXES:
        return True
    if not platform.startswith("win"):
        try:
            return bool(path.stat().st_mode & 0o111)
        except OSError:
            return True
    return False


def reveal_command(path: Path, platform: str) -> list[str]:
    """Show `path` in the file manager without opening it."""
    path = Path(path)
    if platform == "darwin":
        return ["open", "-R", str(path)]
    if platform.startswith("win"):
        return ["explorer", f"/select,{path}"]
    return ["xdg-open", str(path.parent)]


def open_command(path: Path, platform: str) -> list[str]:
    """Open `path` in its own app, as a double-click would; a folder or anything
    that could run is revealed instead (see reveal_command)."""
    path = Path(path)
    if _risky(path, platform):
        return reveal_command(path, platform)
    if platform == "darwin":
        return ["open", str(path)]
    if platform.startswith("win"):
        return ["startfile", str(path)]     # run() hands this to os.startfile
    return ["xdg-open", str(path)]


def run(cmd: list[str], runner=subprocess.Popen) -> None:
    """Start the command and return at once: no shell, no input, no output."""
    if cmd and cmd[0] == "startfile":
        os.startfile(cmd[1])  # type: ignore[attr-defined]  # Windows only
        return
    runner(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
           stderr=subprocess.DEVNULL)


def create(root_path: Path, company) -> Path:
    """Make the company's folder (one level, under an existing root) and return it.
    An existing folder (found by find_folder) is returned as it is. ValueError
    when the root does not exist: a typo in the root must not grow a stray tree."""
    root_path = Path(root_path)
    if not root_path.is_dir():
        raise ValueError(f"the client folders root {root_path} does not exist")
    found = find_folder(root_path, company)
    if found is not None:
        return found
    target = expected_folder(root_path, company)
    target.mkdir(exist_ok=True)
    return target
