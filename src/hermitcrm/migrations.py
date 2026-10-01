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

"""Data format versions and migrations for a Hermit CRM data folder.

The folder carries a committed ``.hermitcrm-format`` file holding one integer.
A folder without it counts as format 0 when it has ``companies/`` (data from
before versioning) and as the latest format otherwise (nothing to migrate).

Migrations are numbered and idempotent, and never touch an interaction body;
most change front matter only, a few add a file the folder did not have. ``ensure_current`` runs every pending one and records the result in
ONE git commit, so ``git revert <sha>`` undoes an upgrade. A folder newer
than this code is refused with an upgrade hint.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .models import COUNTRY_CODE_ALIASES, DEFAULT_OUTCOMES
from .store import build_file, split_file

FORMAT_FILE = ".hermitcrm-format"
LEGACY_FORMAT_FILE = ".owncrm-format"  # before the rename to Hermit CRM
GIT_AUTHOR = ["-c", "user.name=hermitcrm", "-c", "user.email=hermitcrm@localhost"]


class FormatTooNew(Exception):
    """The data folder was written by a newer Hermit CRM."""


@dataclass
class Migration:
    version: int
    title: str
    glob: str                      # files it may touch, relative to the data folder
    apply: Callable[[dict], dict] | None = None   # front matter in, front matter out
    # Some changes are not about front matter at all. A folder step runs after
    # every file pass, is handed the front matter as the run will leave it (not
    # as the disk still has it), and returns the paths it wrote so a dry run can
    # list them like any other change.
    folder: Callable[..., list[str]] | None = None


def _noop(meta: dict) -> dict:
    return meta


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


# Legacy spellings of an outcome (matched case-insensitively) and what they
# mean now; "" is "not yet known". Anything else is free text and stays as is.
OUTCOME_ALIASES = {
    "success": "successful", "succesful": "successful", "successful": "successful",
    "unsuccessful": "unsuccessful",
    "pending": "", "unknown": "",
}


def m3_outcome(meta: dict) -> dict:
    """Fold the old `result` verdict (success | unsuccessful) into `outcome`:
    it fills an empty outcome; an outcome already holding a list value wins;
    then `result` goes. Free text in `outcome` is kept verbatim."""
    if "outcome" not in meta and "result" not in meta:
        return meta
    raw = meta.get("outcome")
    outcome = str(raw or "").strip()
    outcome = OUTCOME_ALIASES.get(outcome.lower(), outcome)
    result = str(meta.get("result") or "").strip()
    if result and not outcome:
        outcome = OUTCOME_ALIASES.get(result.lower(), result)
    if outcome == str(raw or "").strip():
        outcome = raw  # unchanged: keep the parsed value (None for an empty key)
    if "outcome" in meta:
        return {k: (outcome if k == "outcome" else v) for k, v in meta.items() if k != "result"}
    # No outcome key at all (hand-written file): it takes the place of `result`.
    return {("outcome" if k == "result" else k): (outcome if k == "result" else v)
            for k, v in meta.items()}


# Stage values renamed since earlier formats (old -> new).
STAGE_RENAMES = {"reached-out": "engaged"}


def m4_stage_engaged(meta: dict) -> dict:
    """Rename the `reached-out` stage to `engaged`, in `stage` and in every
    `stage_history` entry (`from` and `to`)."""
    new = dict(meta)
    stage = str(meta.get("stage") or "").strip()
    if stage in STAGE_RENAMES:
        new["stage"] = STAGE_RENAMES[stage]
    history = meta.get("stage_history")
    if isinstance(history, list):
        entries = []
        for item in history:
            if isinstance(item, dict):
                item = {k: (STAGE_RENAMES.get(v, v) if k in ("from", "to") and isinstance(v, str)
                            else v) for k, v in item.items()}
            entries.append(item)
        if entries != history:
            new["stage_history"] = entries
    return new if new != meta else meta


# The four fields a Hermit CRM used to have built in, with the shape they had.
# A folder that used any of them keeps working because they become definitions:
# the values never move, only the description of them is new.
LEGACY_FIELDS = [
    ("my_score", "my score", "number", ["detail", "board", "companies"],
     "your own 0 to 10"),
    ("fit_score", "fit", "number", ["detail", "board", "companies"], "0 to 100"),
    ("fte_estimate", "FTE estimate", "text", ["detail", "companies"],
     "as written, e.g. ~13"),
    ("ae_count", "AE count", "number", ["detail"], ""),
]


def m5_custom_fields(data_dir: Path, meta_by_path: dict, write: bool) -> list[str]:
    """Describe the four built-in fields this version removed.

    Not one company file is touched: the keys were ordinary YAML before and are
    ordinary YAML now. What changes is that Hermit CRM no longer knows them by
    name, so the folder has to say what they are. A folder that never used them
    gets no fields.toml at all.
    """
    from . import fields as fields_mod

    target = data_dir / fields_mod.FILENAME
    if target.exists():
        return []
    used = set()
    for rel, meta in meta_by_path.items():
        if not rel.endswith("/company.md"):
            continue
        used |= {key for key, _, _, _, _ in LEGACY_FIELDS if key in meta}
    if not used:
        return []
    defs = [fields_mod.FieldDef(key=key, label=label, type=kind, show_in=show_in,
                                help=help_text)
            for key, label, kind, show_in, help_text in LEGACY_FIELDS if key in used]
    if write:
        fields_mod.write(data_dir, defs)
    return [fields_mod.FILENAME]


def _insert_section(text: str, section: str) -> str:
    """Put a section before the first `## ` heading (where people add their own)."""
    at = text.find("\n## ")
    if at == -1:
        return text.rstrip("\n") + "\n\n" + section
    return text[:at].rstrip("\n") + "\n\n" + section + text[at:]


def m6_agent_guard(data_dir: Path, meta_by_path: dict, write: bool) -> list[str]:
    """Block history-rewriting git commands for agents; say so in CLAUDE.md.

    `.claude/settings.json` gets the deny rules merged in (anything else in it
    stays). CLAUDE.md and AGENTS.md written before backups existed get the
    "Backups and undo" rules; a file that already mentions `hermitcrm backup`
    is left alone, and a folder without one does not get one.
    """
    from . import guard
    from .datafolder import AGENT_BACKUP_RULES

    changed = []
    try:
        if guard.write(data_dir, apply=write):
            changed.append(guard.SETTINGS)
    except guard.GuardError:
        pass  # a settings file we cannot parse is left as it is; doctor says so
    for name in ("CLAUDE.md", "AGENTS.md"):
        path = data_dir / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if "hermitcrm backup" in text:
            continue
        if write:
            path.write_text(_insert_section(text, AGENT_BACKUP_RULES), encoding="utf-8")
        changed.append(name)
    return changed


# "01/10/2026: didn't accept invite" -- day first, as a European writes it.
_DATED_NOTE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}):")


def _note_date(meta: dict, key: str) -> datetime | None:
    value = meta.get(key)
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _split_notes(body: str, fallback: datetime) -> list[tuple[datetime, str]]:
    """A contact's notes body as (date, text) notes. A line that starts with a
    day/month/year date is its own note on that day; the lines between those
    are one note dated `fallback`. Text is kept verbatim."""
    notes: list[tuple[datetime, list[str]]] = []
    undated: list[str] = []

    def flush() -> None:
        if any(line.strip() for line in undated):
            notes.append((fallback, list(undated)))
        undated.clear()

    for line in body.replace("\r\n", "\n").split("\n"):
        m = _DATED_NOTE.match(line)
        when = None
        if m:
            day, month, year = (int(g) for g in m.groups())
            try:
                when = datetime(year, month, day)
            except ValueError:
                when = None  # not a real date: an ordinary line
        if when is None:
            undated.append(line)
            continue
        flush()
        notes.append((when, [line]))
    flush()
    return [(when, "\n".join(lines).strip("\n") + "\n") for when, lines in notes]


def m7_contact_notes(data_dir: Path, meta_by_path: dict, write: bool) -> list[str]:
    """Contact notes become note interactions; the contact file loses its body.

    A note is an interaction like any other (channel `note`, no direction,
    `source: migration`), on the contact's timeline. The contact's front matter
    is kept byte for byte; only the text after it goes. Running it again finds
    no body and does nothing.
    """
    from .models import Interaction, interaction_to_frontmatter

    changed: list[str] = []
    claimed: set[Path] = set()  # names taken in this run (a dry run writes none)
    for rel, meta in sorted(meta_by_path.items()):
        if "/contacts/" not in rel:
            continue
        path = data_dir / rel
        text = path.read_text(encoding="utf-8")
        _, body = split_file(text)
        if not body.strip():
            continue
        company_dir, cslug = path.parent.parent, path.stem
        fallback = (_note_date(meta, "created") or _note_date(meta, "updated")
                    or datetime.now().replace(second=0, microsecond=0))
        folder = company_dir / "interactions"
        for when, note in _split_notes(body, fallback):
            it = Interaction(id="", date=when, channel="note", contact=cslug,
                             source="migration", body=note)
            base, n = it.base_id(), 1
            target = folder / f"{base}.md"
            while target.exists() or target in claimed:
                n += 1
                target = folder / f"{base}-{n}.md"
            claimed.add(target)
            if write:
                folder.mkdir(exist_ok=True)
                target.write_text(build_file(interaction_to_frontmatter(it), note),
                                  encoding="utf-8")
            changed.append(target.relative_to(data_dir).as_posix())
        if write:
            path.write_text(text[:len(text) - len(body)], encoding="utf-8")
        changed.append(rel)
    return changed


MIGRATIONS = [
    Migration(1, "rename gijs_score to my_score", "companies/*/company.md", m1_my_score),
    Migration(2, "country UK→GB, USA→US", "companies/*/company.md", m2_country_codes),
    Migration(3, "interaction result folded into outcome",
              "companies/*/interactions/*.md", m3_outcome),
    Migration(4, "stage reached-out renamed to engaged", "companies/*/company.md",
              m4_stage_engaged),
    Migration(5, "scores and team size become fields you define",
              "companies/*/company.md", folder=m5_custom_fields),
    Migration(6, "agents may not rewrite history (.claude/settings.json)", "CLAUDE.md",
              folder=m6_agent_guard),
    Migration(7, "contact notes become note interactions", "companies/*/contacts/*.md",
              folder=m7_contact_notes),
]
LATEST = MIGRATIONS[-1].version


def current_format(data_dir: Path | str) -> int:
    data_dir = Path(data_dir)
    path = data_dir / FORMAT_FILE
    if not path.exists() and (data_dir / LEGACY_FORMAT_FILE).exists():
        path = data_dir / LEGACY_FORMAT_FILE
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
            f"This data folder is format {current}, but Hermit CRM understands up to "
            f"format {LATEST}. Upgrade Hermit CRM first: pipx upgrade hermitcrm")
    return [m for m in MIGRATIONS if m.version > current]


def _run(migrations: list[Migration], data_dir: Path, write: bool) -> dict[int, list[str]]:
    """Apply in order (in memory when not writing); changed files per version."""
    changed: dict[int, list[str]] = {m.version: [] for m in migrations}
    staged: dict[Path, tuple[dict, str]] = {}
    for m in migrations:
        if m.apply is None:
            continue
        for path in sorted(data_dir.glob(m.glob)):
            if path in staged:
                meta, body = staged[path]
            else:
                try:
                    meta, body = split_file(path.read_text(encoding="utf-8"))
                except Exception:
                    continue  # `hermitcrm check` reports unreadable files
            new = m.apply(dict(meta))
            if new != meta or list(new) != list(meta):
                changed[m.version].append(path.relative_to(data_dir).as_posix())
            staged[path] = (new, body)
    if write:
        touched = {p for files in changed.values() for p in files}
        for path, (meta, body) in staged.items():
            if path.relative_to(data_dir).as_posix() in touched:
                path.write_text(build_file(meta, body), encoding="utf-8")
    # Folder steps run last and see the front matter as this run leaves it. A
    # step that read the disk instead would see the state before the file
    # passes, which is a different folder in a dry run and in a real one.
    after = {path.relative_to(data_dir).as_posix(): meta for path, (meta, _) in staged.items()}
    for m in migrations:
        if m.folder is None:
            continue
        # Its glob may name files no other migration in this batch read.
        for path in sorted(data_dir.glob(m.glob)):
            rel = path.relative_to(data_dir).as_posix()
            if rel not in after:
                try:
                    after[rel], _ = split_file(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
        changed[m.version] += m.folder(data_dir, after, write)
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
    lines.append("Dry run; run any command (or `hermitcrm migrate`) to apply.")
    return "\n".join(lines)


def _is_git_repo(data_dir: Path) -> bool:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=data_dir,
                          capture_output=True, text=True)
    return proc.returncode == 0 and Path(proc.stdout.strip()).resolve() == data_dir.resolve()


def _adopt_legacy_format_file(data_dir: Path) -> str:
    """Rename .owncrm-format (pre-rename folders) to .hermitcrm-format, committed."""
    old, new = data_dir / LEGACY_FORMAT_FILE, data_dir / FORMAT_FILE
    if not old.exists() or new.exists():
        return ""
    old.rename(new)
    message = f"migrate: rename {LEGACY_FORMAT_FILE} to {FORMAT_FILE}"
    if _is_git_repo(data_dir):
        paths = [LEGACY_FORMAT_FILE, FORMAT_FILE]
        subprocess.run(["git", "add", "-A", "--", *paths], cwd=data_dir, check=True,
                       capture_output=True)
        subprocess.run(["git", *GIT_AUTHOR, "commit", "-q", "-m", message, "--", *paths],
                       cwd=data_dir, capture_output=True)
    return message


def ensure_current(data_dir: Path | str) -> str:
    """Run pending migrations in one commit; '' when there was nothing to do."""
    data_dir = Path(data_dir)
    renamed = _adopt_legacy_format_file(data_dir)
    todo = pending(data_dir)
    if not todo:
        return renamed
    before = current_format(data_dir)
    changed = _run(todo, data_dir, write=True)
    write_format(data_dir, LATEST)
    titles = "; ".join(m.title for m in todo)
    message = f"migrate: data format {before} → {LATEST} ({titles})"
    files = sorted({f for fs in changed.values() for f in fs} | {FORMAT_FILE})
    count = len(files) - 1
    if _is_git_repo(data_dir):
        # A folder may keep a file a migration wrote out of git (.claude/ in its
        # .gitignore, say); that file is changed on disk, just not committed.
        ignored = subprocess.run(["git", "check-ignore", "--", *files], cwd=data_dir,
                                 capture_output=True, text=True).stdout.splitlines()
        files = [f for f in files if f not in ignored]
        subprocess.run(["git", "add", "--", *files], cwd=data_dir, check=True,
                       capture_output=True)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet", "--", *files],
                                cwd=data_dir, capture_output=True)
        if staged.returncode != 0:  # nothing staged means the data was already current
            subprocess.run(["git", *GIT_AUTHOR, "commit", "-q", "-m", message, "--", *files],
                           cwd=data_dir, check=True, capture_output=True)
    return f"{message}: {count} file(s) changed"
