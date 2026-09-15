"""Data format versions and migrations for an OwnCRM data folder.

The folder carries a committed ``.owncrm-format`` file holding one integer.
A folder without it counts as format 0 when it has ``companies/`` (data from
before versioning) and as the latest format otherwise (nothing to migrate).

Migrations are numbered, idempotent and touch front matter only, never
bodies. ``ensure_current`` runs every pending one and records the result in
ONE git commit, so ``git revert <sha>`` undoes an upgrade. A folder newer
than this code is refused with an upgrade hint.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import COUNTRY_CODE_ALIASES
from .store import build_file, split_file

FORMAT_FILE = ".owncrm-format"
GIT_AUTHOR = ["-c", "user.name=owncrm", "-c", "user.email=owncrm@localhost"]


class FormatTooNew(Exception):
    """The data folder was written by a newer OwnCRM."""


@dataclass
class Migration:
    version: int
    title: str
    glob: str                      # files it may touch, relative to the data folder
    apply: Callable[[dict], dict]  # front matter in, (possibly) new front matter out


def _rename_key(meta: dict, old: str, new: str) -> dict:
    """Rename a key in place (same position); an existing `new` wins."""
    if old not in meta:
        return meta
    if new in meta:
        return {k: v for k, v in meta.items() if k != old}
    return {(new if k == old else k): v for k, v in meta.items()}


def m1_my_score(meta: dict) -> dict:
    return _rename_key(meta, "gijs_score", "my_score")


def m2_country_codes(meta: dict) -> dict:
    country = str(meta.get("country") or "").strip()
    code = COUNTRY_CODE_ALIASES.get(country.upper())
    if not code:
        return meta
    return {**meta, "country": code}


MIGRATIONS = [
    Migration(1, "rename gijs_score to my_score", "companies/*/company.md", m1_my_score),
    Migration(2, "country UK→GB, USA→US", "companies/*/company.md", m2_country_codes),
]
LATEST = MIGRATIONS[-1].version


def current_format(data_dir: Path | str) -> int:
    data_dir = Path(data_dir)
    path = data_dir / FORMAT_FILE
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        try:
            return int(text)
        except ValueError:
            raise FormatTooNew(f"{path} does not hold a number: {text!r}") from None
    return 0 if (data_dir / "companies").is_dir() else LATEST


def write_format(data_dir: Path | str, version: int = LATEST) -> Path:
    path = Path(data_dir) / FORMAT_FILE
    path.write_text(f"{version}\n", encoding="utf-8")
    return path


def pending(data_dir: Path | str) -> list[Migration]:
    current = current_format(data_dir)
    if current > LATEST:
        raise FormatTooNew(
            f"This data folder is format {current}, but OwnCRM understands up to "
            f"format {LATEST}. Upgrade OwnCRM first: pipx upgrade owncrm")
    return [m for m in MIGRATIONS if m.version > current]


def _run(migrations: list[Migration], data_dir: Path, write: bool) -> dict[int, list[str]]:
    """Apply in order (in memory when not writing); changed files per version."""
    changed: dict[int, list[str]] = {m.version: [] for m in migrations}
    staged: dict[Path, tuple[dict, str]] = {}
    for m in migrations:
        for path in sorted(data_dir.glob(m.glob)):
            if path in staged:
                meta, body = staged[path]
            else:
                try:
                    meta, body = split_file(path.read_text(encoding="utf-8"))
                except Exception:
                    continue  # `owncrm check` reports unreadable files
            new = m.apply(dict(meta))
            if new != meta or list(new) != list(meta):
                changed[m.version].append(path.relative_to(data_dir).as_posix())
            staged[path] = (new, body)
    if write:
        touched = {p for files in changed.values() for p in files}
        for path, (meta, body) in staged.items():
            if path.relative_to(data_dir).as_posix() in touched:
                path.write_text(build_file(meta, body), encoding="utf-8")
    return changed


def dry_run(data_dir: Path | str) -> str:
    data_dir = Path(data_dir)
    todo = pending(data_dir)
    current = current_format(data_dir)
    if not todo:
        return f"Data format {current} is current; nothing to migrate."
    lines = [f"Data format {current} → {LATEST}:"]
    for version, files in _run(todo, data_dir, write=False).items():
        title = next(m.title for m in todo if m.version == version)
        lines.append(f"  {version}. {title}: {len(files)} file(s)")
        lines += [f"     {f}" for f in files]
    lines.append("Dry run; run any command (or `owncrm migrate`) to apply.")
    return "\n".join(lines)


def _is_git_repo(data_dir: Path) -> bool:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=data_dir,
                          capture_output=True, text=True)
    return proc.returncode == 0 and Path(proc.stdout.strip()).resolve() == data_dir.resolve()


def ensure_current(data_dir: Path | str) -> str:
    """Run pending migrations in one commit; '' when there was nothing to do."""
    data_dir = Path(data_dir)
    todo = pending(data_dir)
    if not todo:
        return ""
    before = current_format(data_dir)
    changed = _run(todo, data_dir, write=True)
    write_format(data_dir, LATEST)
    titles = "; ".join(m.title for m in todo)
    message = f"migrate: data format {before} → {LATEST} ({titles})"
    files = sorted({f for fs in changed.values() for f in fs} | {FORMAT_FILE})
    if _is_git_repo(data_dir):
        subprocess.run(["git", "add", "--", *files], cwd=data_dir, check=True,
                       capture_output=True)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet", "--", *files],
                                cwd=data_dir, capture_output=True)
        if staged.returncode != 0:  # nothing staged means the data was already current
            subprocess.run(["git", *GIT_AUTHOR, "commit", "-q", "-m", message, "--", *files],
                           cwd=data_dir, check=True, capture_output=True)
    count = len(files) - 1
    return f"{message}: {count} file(s) changed"
