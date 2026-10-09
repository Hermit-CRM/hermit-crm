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

"""Changing the deal stages: what stops a change, and the order it is written in.

The Settings page and `hermitcrm stages` both go through here, so a rename means
the same on both: the new list is saved to config.toml, then companies are
rewritten (stage and stage_history) or moved, all in ONE commit so a single undo puts
the setting and the records back together.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import setup as setup_steps
from . import stages as stages_mod
from .stages import StageSet
from .store import Store


class StageOpError(Exception):
    """A stage change that was asked for wrongly; the message says how."""


@dataclass
class Change:
    before: StageSet
    after: StageSet
    renames: dict[str, str] = field(default_factory=dict)   # old name -> new name
    removed: list[str] = field(default_factory=list)        # names that are gone
    move_to: str = ""                                       # where their companies go
    reason: str = ""                                        # for a lost target

    @property
    def changes_anything(self) -> bool:
        return self.before != self.after


def blockers(store: Store, change: Change) -> tuple[str, dict | None]:
    """Why `change` cannot be made yet: ("", None) when nothing stops it, else
    (message, ask). `ask` is set when the answer is to say where the companies of
    a removed stage go: {names, count, targets, move_to, needs_reason}."""
    before, after = change.before, change.after
    old_of = {new: old for old, new in change.renames.items()}
    # A stage that becomes `lost` needs a reason on every company already in it.
    for stage in after:
        old = old_of.get(stage.name, stage.name)
        if stage.role == "lost" and old in before and before.role_of(old) != "lost":
            bare = [c for c in store.companies.values()
                    if c.stage == old and not c.lost_reason]
            if bare:
                return (f"{len(bare)} companies in {old} have no reason, and a lost "
                        f"stage needs one. Give them a reason (or move them) first.", None)
    # A removed stage that still has companies: they have to go somewhere.
    counts = store.stage_counts()
    loaded = [n for n in change.removed if counts.get(n)]
    if not loaded:
        return "", None
    target = stages_mod.clean(change.move_to)
    needs_reason = bool(target) and target in after and after.requires_reason(target) and any(
        not c.lost_reason for c in store.companies.values() if c.stage in loaded)
    if target in after and not (needs_reason and not change.reason.strip()):
        return "", None
    why = (f"Choose where the companies in {', '.join(loaded)} go before deleting "
           f"{'it' if len(loaded) == 1 else 'them'}." if not target else
           f"{target} is not a stage you are keeping." if target not in after
           else f"Moving companies to {target} needs a reason.")
    return why, {"names": loaded, "count": sum(counts[n] for n in loaded),
                 "targets": after.names, "move_to": target, "needs_reason": needs_reason}


def _companies(n: int) -> str:
    return f"{n} {'company' if n == 1 else 'companies'}"


def _subject(label: str, change: Change, rewritten: int, moved: dict[str, int]) -> str:
    """The one commit's subject: what the change did to the companies."""
    renames, removed = change.renames, [n for n in change.removed]
    target = stages_mod.clean(change.move_to)
    if len(renames) == 1 and not removed:
        (old, new), = renames.items()
        return f'{label}: stage "{old}" renamed to "{new}" ({_companies(rewritten)})'
    if len(removed) == 1 and not renames:
        gone = removed[0]
        if moved.get(gone):
            return (f'{label}: stage "{gone}" removed, {_companies(moved[gone])} '
                    f'moved to "{target}"')
        return f'{label}: stage "{gone}" removed'
    if not renames and not removed:
        return f"{label}: stages changed"
    parts = [f'renamed "{o}" to "{n}"' for o, n in renames.items()]
    parts += [f'removed "{n}"' for n in removed]
    counts = []
    if renames:
        counts.append(f"{_companies(rewritten)} rewritten")
    if moved:
        counts.append(f"{sum(moved.values())} moved")
    return f"{label}: stages: " + ", ".join(parts) + (f" ({', '.join(counts)})" if counts else "")


def _snapshot(store: Store, root) -> dict:
    """The bytes of every file a stage change can write: config.toml and each
    company.md (a change touches nothing else)."""
    paths = [Path(root) / "config.toml", *store.companies_dir.glob("*/company.md")]
    return {p: p.read_bytes() for p in paths if p.is_file()}


def _restore(snapshot: dict) -> None:
    for path, data in snapshot.items():
        if path.read_bytes() != data:
            path.write_bytes(data)


def apply(store: Store, root, change: Change, activate, label: str = "settings",
          deactivate=None) -> list[str]:
    """Write `change` as ONE commit, so one undo takes it all back: the start of
    old histories first (it follows the entry stage), config.toml, the rename
    sweep, then the moves out of removed stages. `activate()` makes the saved
    config the live one without committing it (Settings re-reads the file; the
    CLI swaps the set in). If anything fails part-way the files are put back as
    they were, nothing is committed, and `deactivate()` (default: `activate()`
    again) makes the old config the live one. Returns the parts of a summary."""
    counts = store.stage_counts()
    loaded = [n for n in change.removed if counts.get(n)]
    target = stages_mod.clean(change.move_to)
    parts: list[str] = []
    rewritten, moved = 0, {}
    snapshot = _snapshot(store, root)
    try:
        with store.batch(f"{label}: stages changed") as ctx:
            if stages_mod.entry_moves(change.before, change.after, change.renames):
                store.materialise_stage_history(label)
            setup_steps.save_stages(root, change.after)
            if not setup_steps.config_holds_secret(root):    # else it stays uncommitted
                store.notify(ctx["message"], ["config.toml"])
            activate()
            if change.renames:
                rewritten = store.rename_stages(change.renames, label)
                parts.append("renamed " + ", ".join(
                    f"{o} to {n}" for o, n in change.renames.items())
                    + f" ({_companies(rewritten)})")
            for gone in loaded:
                moved[gone] = store.remove_stage(gone, target, change.reason, label)
                parts.append(f"moved {_companies(moved[gone])} from {gone} to {target}")
            ctx["message"] = _subject(label, change, rewritten, moved)
    except Exception:
        _restore(snapshot)
        (deactivate or activate)()
        store.set_stages(change.before)
        store.load()
        raise
    stale = stages_mod.mentions(root, [*change.renames, *change.removed])
    if stale:
        parts.append("still named in " + "; ".join(
            f"{n}: {', '.join(files)}" for n, files in stale.items())
            + " (edit those by hand or ask your agent)")
    return parts


# ------------------------------------------------------------- the command line


def _rows(stage_set: StageSet) -> list[list]:
    """[name, role, valued, old] per stage: the Settings form's rows."""
    return [[s.name, s.role, s.valued, s.name] for s in stage_set]


def _build(store: Store, rows: list[list]) -> Change:
    new, renames, removed, errors = stages_mod.plan_rows(
        [r[0] for r in rows], [r[1] for r in rows],
        [str(i) for i, r in enumerate(rows) if r[2]], [r[3] for r in rows], store.stages)
    if errors:
        raise StageOpError(errors["stages"])
    return Change(store.stages, new, renames, removed)


def _find(rows: list[list], name: str) -> int:
    name = stages_mod.clean(name)
    for i, row in enumerate(rows):
        if row[0] == name:
            return i
    raise StageOpError(f"no stage called {name!r} (stages: {', '.join(r[0] for r in rows)})")


def plan(store: Store, action: str, name: str = "", new_name: str = "", role: str = "",
         valued: bool | None = None, after: str = "", first: bool = False,
         move_to: str = "", reason: str = "") -> Change:
    """The change `hermitcrm stages <action>` would make; StageOpError if it is
    asked for wrongly. Nothing is written."""
    rows = _rows(store.stages)
    if action == "rename":
        rows[_find(rows, name)][0] = new_name
    elif action == "add":
        role = role or "open"
        if role not in stages_mod.ROLES:
            raise StageOpError(f"role must be one of {', '.join(stages_mod.ROLES)}")
        at = len(rows)
        if after:
            at = _find(rows, after) + 1
        elif role == "open":                      # after the last open stage
            at = max(i for i, r in enumerate(rows) if r[1] == "open") + 1
        rows.insert(at, [new_name or name, role, bool(valued), ""])
    elif action == "move":
        row = rows.pop(_find(rows, name))
        if first:
            rows.insert(0, row)
        elif after:
            rows.insert(_find(rows, after) + 1, row)
        else:
            raise StageOpError("say where: --after STAGE or --first")
    elif action == "set":
        row = rows[_find(rows, name)]
        if role:
            if role not in stages_mod.ROLES:
                raise StageOpError(f"role must be one of {', '.join(stages_mod.ROLES)}")
            row[1] = role
        if valued is not None:
            row[2] = valued
    elif action == "remove":
        rows.pop(_find(rows, name))
    else:
        raise StageOpError(f"unknown action {action!r}")
    change = _build(store, rows)
    change.move_to, change.reason = move_to, reason
    return change


def listing(store: Store) -> str:
    """`hermitcrm stages`: the stages, their roles and how many companies are in each."""
    counts = store.stage_counts()
    width = max(len(n) for n in [*store.stages.names, *counts])
    lines = [f"{'stage'.ljust(width)}  role    companies"]
    for s in store.stages:
        note = " valued" if s.valued else ""
        lines.append(f"{s.name.ljust(width)}  {s.role.ljust(7)} {counts.get(s.name, 0)}{note}")
    off = [(n, c) for n, c in sorted(counts.items()) if n not in store.stages]
    for name, count in off:
        lines.append(f"{name.ljust(width)}  (not in config.toml)  {count}")
    lines.append(f"Entry stage: {store.stages.entry}"
                 + (f"; the first outbound touch moves it to {store.stages.advance_target}"
                    if store.stages.advance_target else ""))
    return "\n".join(lines)


def render(store: Store, change: Change, root) -> str:
    """The dry run: the list as it would be, and what it does to companies."""
    counts = store.stage_counts()
    new_old = {new: old for old, new in change.renames.items()}
    lines = ["Stages after this change:"]
    for s in change.after:
        was = new_old.get(s.name)
        n = counts.get(was or s.name, 0)
        mark = f" (was {was})" if was else (" (new)" if s.name not in change.before else "")
        lines.append(f"  {s.name}  {s.role}{' valued' if s.valued else ''}"
                     f"  {n} {'company' if n == 1 else 'companies'}{mark}")
    for old, new in change.renames.items():
        users = store.stage_users([old])
        now = counts.get(old, 0)
        lines.append(f'Rename "{old}" to "{new}": {len(users)} '
                     f"{'company' if len(users) == 1 else 'companies'} rewritten "
                     f"({now} in it now, the rest only in their stage_history)"
                     + (f", e.g. {', '.join(users[:3])}" if users else ""))
    for gone in change.removed:
        n = counts.get(gone, 0)
        users = store.stage_users([gone])
        if n:
            dest = stages_mod.clean(change.move_to)
            verb = ("moves" if n == 1 else "move")
            lines.append(f'Remove "{gone}": {n} {"company" if n == 1 else "companies"} '
                         f"{verb + ' to ' + dest if dest else 'need somewhere to go (--move-to)'}"
                         + (f", e.g. {', '.join(users[:3])}" if users else ""))
        else:
            lines.append(f'Remove "{gone}": nobody is in it')
    if stages_mod.entry_moves(change.before, change.after, change.renames):
        n = store.unwritten_histories()
        who = "1 company gets its" if n == 1 else f"{n} companies get their"
        lines.append(f"The entry stage changes from {change.before.entry} to "
                     f"{change.after.entry}; {who} start written into stage_history first.")
    stale = stages_mod.mentions(root, [*change.renames, *change.removed])
    if stale:
        lines.append("Still naming a stage that changes (not rewritten, edit by hand): "
                     + "; ".join(f"{n}: {', '.join(files)}" for n, files in stale.items()))
    return "\n".join(lines)
