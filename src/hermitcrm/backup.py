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

"""`hermitcrm backup`: a second git repository, outside the data folder, that only grows.

The data folder is already git, so every change can be undone -- unless the
history itself is what gets damaged: a `git reset --hard`, a deleted `.git`, a
force-push. Anything with a shell in the folder (a person, a script, an AI
agent) can do that. The backup is a bare repository somewhere else that
refuses to lose anything:

- ``receive.denyNonFastForwards`` and ``receive.denyDeletes``: a push can add
  commits and refs, never move a ref backwards or delete one;
- reflogs and unreachable objects never expire.

Each run (the scheduled job runs one every few minutes):

1. **Snapshot.** If the working tree differs from HEAD (an edit nobody
   committed), its state is written as a commit on top of HEAD *without
   touching the folder's branch or index*: a copy of the index, ``git add -A``
   into that copy, ``write-tree``, ``commit-tree``. It is pushed to
   ``refs/snapshots/<time>``. A half-finished edit stays the user's to commit.
2. **Branch.** The current branch is pushed to the same name when that is a
   fast-forward. When it is not -- the folder's history was rewritten -- the
   new line goes to ``refs/rewritten/<time>/<branch>`` instead, the run warns
   once, and later runs follow the new line. The backup keeps both.
3. **Remote.** If the folder has a git remote with ``push_enabled`` (Settings,
   Backup), commits it does not have yet are pushed there too; never forced.

Size: git stores each file version once and compresses the differences, and a
run that finds nothing new writes nothing. The backup grows with real edits,
not with the number of runs.

State (last run, what it saw) lives in ``.git/hermitcrm-backup.json`` of the
data folder: not tracked, and not in the backup, so a missing backup
repository is noticed rather than silently recreated.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = "hermitcrm-backup.json"
DEFAULT_EVERY = 5  # minutes, the scheduled job's interval
STALE_AFTER = 60 * 60  # seconds without a good run before doctor warns

BARE_CONFIG = {
    "receive.denyNonFastForwards": "true",
    "receive.denyDeletes": "true",
    "core.logAllRefUpdates": "always",
    "gc.reflogExpire": "never",
    "gc.reflogExpireUnreachable": "never",
    "gc.pruneExpire": "never",
    # Housekeeping runs once per run, in the foreground (the `gc --auto` in
    # run()). A push would otherwise start one of its own after receiving, and
    # gc detaches by default: a background gc still writing packs when a
    # restore reads, or the next run pushes, is a race for no benefit.
    "receive.autogc": "false",
    "gc.autoDetach": "false",
    # `backup restore <sha>` fetches a commit by id, which may be reachable only
    # from a snapshot ref.
    "uploadpack.allowAnySHA1InWant": "true",
}

IDENTITY = ["-c", "user.name=hermitcrm", "-c", "user.email=hermitcrm@localhost"]


class BackupError(Exception):
    pass


@dataclass
class Outcome:
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changed: bool = False
    code: int = 0  # 0 ok, 1 ran with warnings, 2 failed


# --------------------------------------------------------------------- git


def _git(args: list[str], cwd: Path, env: dict | None = None,
         timeout: float = 120) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    full_env["GIT_TERMINAL_PROMPT"] = "0"
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):  # a hook's leftovers
        full_env.pop(key, None)
    full_env.update(env or {})
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          env=full_env, timeout=timeout)


def _out(args: list[str], cwd: Path, env: dict | None = None) -> str | None:
    proc = _git(args, cwd, env)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


# ------------------------------------------------------------------- where


def default_path(root: Path, home: Path | None = None) -> Path:
    """~/.hermitcrm/backups/<folder name>-<8 hex of its path>.git

    The hash keeps two folders that share a name (two `crm`s) apart.
    """
    root = Path(root).expanduser().resolve()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-") or "crm"
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:8]
    return Path(home or Path.home()) / ".hermitcrm" / "backups" / f"{name}-{digest}.git"


def backup_path(root: Path, config: dict | None = None, home: Path | None = None) -> Path:
    configured = str((config or {}).get("backup_dir") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return default_path(root, home)


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------- state


def _git_dir(root: Path) -> Path:
    found = _out(["rev-parse", "--absolute-git-dir"], root)
    if not found:
        raise BackupError(f"{root} is not a git repository")
    return Path(found)


def load_state(root: Path) -> dict:
    try:
        return json.loads((_git_dir(root) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, BackupError):
        return {}


def _save_state(root: Path, state: dict) -> None:
    path = _git_dir(root) / STATE_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


# -------------------------------------------------------------- the backup


def ensure_repo(dest: Path, root: Path) -> bool:
    """Create the bare backup repository if needed; returns True when created.

    The protective settings are (re)applied on every run, so a backup made by
    an older Hermit CRM, or one whose config someone loosened, is put right.
    """
    created = False
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        proc = _git(["init", "--bare", "--quiet", str(dest)], dest.parent)
        if proc.returncode != 0:
            raise BackupError(f"could not create {dest}: {proc.stderr.strip()}")
        created = True
    elif _out(["rev-parse", "--is-bare-repository"], dest) != "true":
        raise BackupError(f"{dest} exists but is not a bare git repository; "
                          "move it away or set backup_dir in config.toml")
    for key, value in BARE_CONFIG.items():
        _git(["config", key, value], dest)
    try:
        (dest / "description").write_text(
            f"Hermit CRM backup of {root}. Only ever added to. Do not delete; "
            "see `hermitcrm help backups`.\n", encoding="utf-8")
    except OSError:
        pass
    return created


def _snapshot_tree(root: Path) -> str | None:
    """The tree of the working tree as `git add -A` would stage it, via a copy
    of the index so the folder's own index is never written."""
    git_dir = _git_dir(root)
    with tempfile.TemporaryDirectory(prefix="hermitcrm-backup-") as tmp:
        index = Path(tmp) / "index"
        real = git_dir / "index"
        if real.exists():
            shutil.copyfile(real, index)  # git replaces the index by rename: a copy is whole
        env = {"GIT_INDEX_FILE": str(index)}
        if _git(["add", "-A"], root, env).returncode != 0:
            return None
        return _out(["write-tree"], root, env)


def _remote_ref(dest: Path, ref: str) -> str | None:
    return _out(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], dest) or None


def _is_ancestor(root: Path, old: str, new: str) -> bool:
    """False also when `old` is no longer in the folder at all (a rewrite that was
    then garbage-collected): either way the backup's ref cannot fast-forward."""
    return _git(["merge-base", "--is-ancestor", old, new], root).returncode == 0


def run(root: Path, config: dict | None = None, home: Path | None = None,
        now: datetime | None = None, push_remote: bool = True) -> Outcome:
    root = Path(root).expanduser().resolve()
    config = config or {}
    now = now or datetime.now(timezone.utc)
    out = Outcome()
    stamp = _stamp(now)

    try:
        _git_dir(root)
    except BackupError as exc:
        out.lines.append(str(exc))
        out.code = 2
        return out
    dest = backup_path(root, config, home)
    if _inside(dest, root):
        out.lines.append(f"backup_dir {dest} is inside the data folder; it has to live "
                         "outside it, or losing the folder loses the backup too")
        out.code = 2
        return out

    state = load_state(root)
    try:
        created = ensure_repo(dest, root)
    except BackupError as exc:
        out.lines.append(str(exc))
        out.code = 2
        return out
    moved = bool(state.get("dest")) and state["dest"] != str(dest)
    if created and moved:
        out.lines.append(f"backup_dir changed: starting a new backup at {dest}; the "
                         f"old one stays at {state['dest']}")
    elif created and state.get("last_ok"):
        out.warnings.append(
            f"the backup at {dest} was missing and has been started again; the "
            f"backups up to {state['last_ok']} are gone. If you did not remove it, "
            "find out what did.")
    if created:
        out.lines.append(f"created {dest}")
        state.pop("tracking", None)
        state.pop("snapshot_tree", None)

    refspecs: list[str] = []
    head = _out(["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], root)
    branch = _out(["symbolic-ref", "--quiet", "--short", "HEAD"], root)

    # 1. uncommitted edits
    tree = _snapshot_tree(root)
    head_tree = _out(["rev-parse", "--verify", "--quiet", "HEAD^{tree}"], root) if head else None
    if tree and tree != head_tree and tree != state.get("snapshot_tree"):
        args = ["commit-tree", tree, "-m", f"backup: uncommitted edits at {stamp}"]
        if head:
            args[2:2] = ["-p", head]
        sha = _out([*IDENTITY, *args], root)
        if sha:
            refspecs.append(f"{sha}:refs/snapshots/{stamp}")
            out.lines.append(f"snapshot of uncommitted edits: refs/snapshots/{stamp}")
    if tree:
        state["snapshot_tree"] = tree

    # 2. the branch
    tracking = None
    if head and branch:
        tracking = state.get("tracking")
        if not tracking or tracking.rsplit("/", 1)[-1] != branch.rsplit("/", 1)[-1]:
            tracking = f"refs/heads/{branch}"
        have = _remote_ref(dest, tracking)
        if have != head:
            if have and not _is_ancestor(root, have, head):
                new = f"refs/rewritten/{stamp}/{branch}"
                out.warnings.append(
                    f"the history of {branch} was rewritten: the backup's last "
                    f"{branch} ({have[:10]}) is no longer part of it. Both lines are "
                    f"kept; the new one is {new}. If you did not do this (a reset, "
                    "an amend, a rebase), something else did: see `hermitcrm help "
                    "backups` to compare and roll back.")
                tracking = new
            refspecs.append(f"{head}:{tracking}")
            out.lines.append(f"{branch} at {head[:10]} -> {tracking}")
    elif head and not branch:
        refspecs.append(f"{head}:refs/detached/{stamp}")
        out.lines.append(f"detached HEAD at {head[:10]} -> refs/detached/{stamp}")

    if refspecs:
        proc = _git(["push", "--quiet", "--no-verify", str(dest), *refspecs], root)
        if proc.returncode != 0:
            out.lines.append(f"push to the backup failed: {proc.stderr.strip()}")
            out.code = 2
            state["last_error"] = proc.stderr.strip()[:500]
            state["last_run"] = now.isoformat(timespec="seconds")
            _save_state(root, state)
            return out
        out.changed = True
        _git(["gc", "--auto", "--quiet"], dest)
    if tracking:
        state["tracking"] = tracking
    # So that `git clone <backup>` checks out this branch, whatever
    # init.defaultBranch says. Only when it differs: every write adds a reflog
    # line, and reflogs here never expire.
    if branch and _out(["symbolic-ref", "--quiet", "HEAD"], dest) != f"refs/heads/{branch}":
        _git(["symbolic-ref", "HEAD", f"refs/heads/{branch}"], dest)

    # 3. the folder's own remote, if it has one
    remote = str(config.get("remote") or "origin")
    if push_remote and config.get("push_enabled") and head and branch \
            and _out(["remote", "get-url", remote], root):
        behind = _out(["rev-list", "--count", f"{remote}/{branch}..HEAD"], root)
        if behind is None or behind != "0":
            proc = _git(["push", "--quiet", remote, branch], root, timeout=60)
            if proc.returncode == 0:
                out.lines.append(f"pushed {branch} to {remote}")
                out.changed = True
            else:
                out.warnings.append(f"push to {remote} failed (the local backup is fine): "
                                    f"{proc.stderr.strip()[:300]}")

    state.update({
        "dest": str(dest),
        "last_run": now.isoformat(timespec="seconds"),
        "last_ok": now.isoformat(timespec="seconds"),
        "last_head": head or "",
        "warnings": out.warnings,
    })
    state.pop("last_error", None)
    if out.warnings:
        state["last_warning"] = {"at": now.isoformat(timespec="seconds"),
                                 "text": out.warnings}
    _save_state(root, state)
    if out.warnings and out.code == 0:
        out.code = 1
    if not out.lines and not out.warnings:
        out.lines.append(f"nothing new; backup at {dest}")
    return out


# ----------------------------------------------------------------- reading


def _size(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                pass
    return total


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def status(root: Path, config: dict | None = None, home: Path | None = None,
           now: datetime | None = None) -> dict:
    """{'level': 'ok'|'warn', 'summary': str, 'lines': [...], 'dest': Path,
    'last_ok': str|None, 'age_minutes': int|None, 'size': str}; never raises.

    `summary` and `lines` are for the terminal; the rest lets the Settings page
    say the same in plain words.
    """
    root = Path(root).expanduser().resolve()
    now = now or datetime.now(timezone.utc)
    dest = backup_path(root, config, home)
    state = load_state(root)
    lines = [f"backup: {dest}"]
    level, summary = "ok", ""
    age_minutes: int | None = None
    size = ""
    if not dest.exists():
        level = "warn"
        summary = (f"{dest} is missing, although backups ran until {state['last_ok']}"
                   if state.get("last_ok") else
                   "no backup yet; run hermitcrm backup, then hermitcrm schedule install")
    else:
        refs = _out(["for-each-ref", "--format=%(refname)"], dest) or ""
        refs = refs.splitlines()
        size = _human(_size(dest))
        snaps = sum(1 for r in refs if r.startswith("refs/snapshots/"))
        rewrites = sorted(r for r in refs if r.startswith("refs/rewritten/"))
        lines.append(f"size {size}; {len(refs)} refs, {snaps} snapshot(s) "
                     f"of uncommitted edits, {len(rewrites)} rewritten line(s)")
        last = state.get("last_ok")
        if not last:
            level, summary = "warn", "the backup exists but this folder never ran one"
        else:
            age = (now - datetime.fromisoformat(last)).total_seconds()
            age_minutes = max(0, int(age // 60))
            lines.append(f"last good run {last} ({int(age // 60)} min ago)")
            if age > STALE_AFTER:
                level = "warn"
                summary = (f"last good run {last}, over an hour ago; is the job "
                           "installed (hermitcrm schedule status)?")
            else:
                summary = f"last good run {int(age // 60)} min ago, {size}"
        if state.get("last_error"):
            level = "warn"
            summary = f"the last run failed: {state['last_error'][:200]}"
        warning = state.get("last_warning")
        if warning:
            lines.append(f"last warning {warning['at']}: " + " ".join(warning["text"]))
            if state.get("warnings"):
                level = "warn"
                summary = "the last run warned: " + " ".join(state["warnings"])[:300]
        if rewrites:
            lines.append("rewritten lines kept: " + ", ".join(rewrites[-5:]))
    return {"level": level, "summary": summary, "lines": lines, "dest": dest,
            "last_ok": state.get("last_ok") if dest.exists() else None,
            "age_minutes": age_minutes, "size": size}


def list_versions(root: Path, config: dict | None = None, path: str = "",
                  limit: int = 20, home: Path | None = None,
                  now: datetime | None = None) -> tuple[str, int]:
    """Versions in the backup, newest first, optionally only those touching `path`.

    A backup runs first (it only ever adds), so the list includes what happened
    since the last scheduled run -- usually the very damage being looked into.
    """
    root = Path(root).expanduser().resolve()
    dest = backup_path(root, config, home)
    rel = _relpath(root, path) if path else ""
    fresh = run(root, config, home, now=now, push_remote=False)
    if fresh.code == 2:
        return "\n".join(["could not back up first:", *fresh.lines]), 2
    args = ["log", "--all", f"-n{limit}", "--date=format:%Y-%m-%d %H:%M",
            "--format=%h  %ad  %s%d", "--decorate=short"]
    if rel:
        args += ["--", rel]
    text = _out(args, dest)
    if text is None:
        return f"could not read {dest}", 2
    if not text:
        return f"no versions in the backup touch {path}", 0
    warned = "".join(f"WARNING: {w}\n" for w in fresh.warnings)
    head = (warned + f"Versions in {dest}, newest first{' touching ' + path if path else ''}.\n"
            "Restore one with: hermitcrm backup restore <id> [PATH ...] --apply\n")
    return head + text, 0


# ---------------------------------------------------------------- restoring


def _relpath(root: Path, path: str) -> str:
    """`path` relative to the data folder; refuses anything outside it."""
    candidate = Path(path)
    full = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not _inside(full, root):
        raise BackupError(f"{path} is outside the data folder")
    rel = full.relative_to(root.resolve()).as_posix()
    if rel == ".git" or rel.startswith(".git/"):
        raise BackupError("restore works on the files, not on .git")
    return rel or "."


def resolve(root: Path, dest: Path, ref: str) -> str:
    """A full commit id for `ref`, fetched into the folder if only the backup has it."""
    candidates = [ref]
    if not ref.startswith("refs/") and "/" in ref:
        candidates.append(f"refs/{ref}")  # "snapshots/2026..." as printed by list
    sha = None
    if dest.exists():
        for name in candidates:
            sha = _out(["rev-parse", "--verify", "--quiet", f"{name}^{{commit}}"], dest)
            if sha:
                break
    if sha:
        if _git(["cat-file", "-e", f"{sha}^{{commit}}"], root).returncode != 0:
            proc = _git(["fetch", "--quiet", "--no-tags", "--no-write-fetch-head",
                         str(dest), sha], root)
            if proc.returncode != 0:
                raise BackupError(f"could not fetch {sha[:10]} from {dest}: "
                                  f"{proc.stderr.strip()}")
        return sha
    local = _out(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], root)
    if local:
        return local
    raise BackupError(f"{ref!r} is not a version in the backup or in the folder; "
                      "list them with hermitcrm backup list")


def restore(root: Path, ref: str, paths: list[str] | None = None,
            config: dict | None = None, apply: bool = False, home: Path | None = None,
            now: datetime | None = None) -> tuple[Outcome, str | None]:
    """Put `paths` (default: everything) back as they were at `ref`.

    Returns the outcome and, when applied, the restore commit. It is a new
    commit on top: nothing in the history is removed, so a restore is itself
    undone the same way. With `apply`, a backup run goes first, so the state
    being replaced is in the backup too.
    """
    root = Path(root).expanduser().resolve()
    out = Outcome()
    dest = backup_path(root, config, home)
    try:
        rels = [_relpath(root, p) for p in (paths or ["."])]
        sha = resolve(root, dest, ref)
    except BackupError as exc:
        out.lines.append(str(exc))
        out.code = 2
        return out, None
    when = _out(["log", "-1", "--date=format:%Y-%m-%d %H:%M", "--format=%ad %s", sha], root)
    out.lines.append(f"version {sha[:10]}: {when}")

    missing = [r for r in rels if r != "." and
               _git(["cat-file", "-e", f"{sha}:{r}"], root).returncode != 0]
    if missing:
        out.lines.append("not in that version: " + ", ".join(missing))
        out.code = 2
        return out, None

    diff = _out(["diff", "--stat", "--find-renames", sha, "--", *rels], root)
    untracked = _out(["ls-files", "--others", "--exclude-standard", "--", *rels], root) or ""
    if not diff and not untracked:
        out.lines.append("nothing to restore: the files already match that version")
        return out, None
    if not apply:
        out.lines.append("would change (dry run; add --apply):")
        out.lines += (diff or "").splitlines()
        if untracked:
            out.lines.append("and remove files that are not in that version: "
                             + ", ".join(untracked.splitlines()[:20]))
        return out, None

    before = run(root, config, home, now=now, push_remote=False)
    if before.code == 2:
        out.lines.append("the backup before restoring failed, so nothing was restored:")
        out.lines += before.lines
        out.code = 2
        return out, None
    out.lines.append("backed up the current state first: hermitcrm backup list shows it")

    # `git restore` removes tracked files that are not in the source; files git
    # never tracked it leaves, so those go by hand (they are in the snapshot).
    proc = _git(["restore", f"--source={sha}", "--staged", "--worktree", "--", *rels], root)
    if proc.returncode != 0:
        out.lines.append(f"git restore failed: {proc.stderr.strip()}")
        out.code = 2
        return out, None
    for name in untracked.splitlines():
        try:
            (root / name).unlink()
        except OSError:
            pass
    label = ", ".join(rels) if rels != ["."] else "everything"
    message = f"backup: restore {label} to {sha[:10]} ({(when or '')[:16]})"
    commit = _git([*IDENTITY, "commit", "--quiet", "--no-verify", "-m", message, "--", *rels],
                  root)
    if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
        out.lines.append(f"restored the files, but the commit failed: {commit.stderr.strip()}")
        out.code = 2
        return out, None
    new = _out(["rev-parse", "--short=10", "HEAD"], root)
    out.lines.append(f"restored {label}; commit {new}: {message}")
    out.changed = True
    return out, new
