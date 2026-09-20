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

"""The data folder's `.claude/settings.json`: git commands no agent may run.

Claude Code applies a project's deny rules in every permission mode, bypass
included, so these stop an agent before a history-rewriting command runs.
They match command patterns, so they are a seat belt, not a lock (a script or
`bash -c` still gets past them); the backup (hermitcrm/backup.py) is what
makes that survivable. Other agents (Codex, Gemini, ...) have no equivalent
file and get the written rules in AGENTS.md only.

Rules are merged in, never replaced: whatever else the file holds (allow
rules, other settings, extra deny rules) is kept.
"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS = ".claude/settings.json"

HISTORY = ["reset --hard", "push --force", "push -f", "push --force-with-lease",
           "commit --amend", "rebase", "filter-branch", "filter-repo",
           "update-ref -d", "reflog expire", "gc --prune"]

DENY = (
    [f"Bash(git {cmd}:*)" for cmd in HISTORY]
    + ["Bash(git clean -f:*)", "Bash(git clean -fd:*)", "Bash(git clean -fdx:*)"]
    # `git -C <dir> commit --amend` does not start with `git commit`, so the
    # prefix rules above miss it; a wildcard in the middle catches that form.
    + [f"Bash(git -C * {cmd}*)" for cmd in HISTORY] + ["Bash(git -C * clean -f*)"]
    + ["Bash(rm -rf .git:*)", "Bash(rm -rf companies:*)", "Bash(rm -rf ~/.hermitcrm:*)",
       # Edit rules cover every file-writing tool (Write included); Claude Code
       # warns that a Write(...) rule is never matched.
       "Edit(~/.hermitcrm/**)",
       # An agent that may edit the list may also empty it.
       f"Edit({SETTINGS})"]
)


class GuardError(Exception):
    """The settings file exists but is not a JSON object we can merge into."""


def _read(root: Path) -> dict:
    path = root / SETTINGS
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise GuardError(f"{SETTINGS} is not valid JSON ({exc}); fix it by hand") from None
    if not isinstance(data, dict):
        raise GuardError(f"{SETTINGS} is not a JSON object; fix it by hand")
    return data


def missing(root: Path) -> list[str]:
    """Deny rules the folder's settings do not have (all of them if no file)."""
    deny = (_read(Path(root)).get("permissions") or {}).get("deny") or []
    return [rule for rule in DENY if rule not in deny]


def write(root: Path, apply: bool = True) -> list[str]:
    """Add the missing deny rules; returns what was (or would be) added."""
    root = Path(root)
    data = _read(root)
    permissions = data.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        raise GuardError(f"{SETTINGS}: permissions is not an object; fix it by hand")
    deny = permissions.setdefault("deny", [])
    if not isinstance(deny, list):
        raise GuardError(f"{SETTINGS}: permissions.deny is not a list; fix it by hand")
    added = [rule for rule in DENY if rule not in deny]
    if added and apply:
        deny.extend(added)
        path = root / SETTINGS
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return added
