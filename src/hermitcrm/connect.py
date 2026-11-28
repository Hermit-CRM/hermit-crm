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

"""Connect your AI (Settings > Advanced): the exact line or block that Claude
Code, Claude Desktop and Cursor each need for this folder.

Every value is filled in with the folder's real path and the real location of
the `hermitcrm` command, because a desktop app starts the MCP server without
the terminal's PATH. This module only builds text for the page to show: it
writes nothing, inside the data folder or outside it.
"""

from __future__ import annotations

import json
import shlex
import shutil
import sys
from pathlib import Path

CURSOR_CONFIG = "~/.cursor/mcp.json"


def command_path(executable: str | None = None, which=shutil.which) -> tuple[str, bool]:
    """The `hermitcrm` command's full path, and whether it was found.

    First the one next to the running Python (a `uv tool` or pip install puts
    it there), then PATH. Not found, it is the bare name, which works in a
    terminal but not in a desktop app; the page says so.
    """
    here = Path(executable or sys.executable).parent
    for name in ("hermitcrm", "hermitcrm.exe"):
        if (here / name).is_file():
            return str(here / name), True
    found = which("hermitcrm")
    return (found, True) if found else ("hermitcrm", False)


def desktop_config_path(platform: str) -> str:
    """Where Claude Desktop keeps its MCP config (Settings > Developer > Edit Config)."""
    if platform.startswith("win"):
        return r"%APPDATA%\Claude\claude_desktop_config.json"
    if platform.startswith("darwin"):
        return "~/Library/Application Support/Claude/claude_desktop_config.json"
    return "~/.config/Claude/claude_desktop_config.json"


def _quote(value: str, platform: str) -> str:
    if platform.startswith("win"):
        return f'"{value}"' if any(c in value for c in ' &()^"') else value
    return shlex.quote(value)


def facts(root: Path | str, command: str, found: bool, platform: str,
          skills: list[tuple[str, str]] = ()) -> dict:
    """What the Connect your AI section shows, for this folder and command.

    `skills` is `datafolder.skill_states(root)`: each Claude Code skill's name
    and whether it is there (ok, yours, missing or old).
    """
    root = str(root)
    server = {"command": command, "args": ["--data", root, "mcp"]}
    block = json.dumps({"mcpServers": {"hermitcrm": server}}, indent=2)
    q = lambda value: _quote(value, platform)  # noqa: E731
    cd = f"cd /d {q(root)}" if platform.startswith("win") else f"cd {q(root)}"
    return {
        "root": root,
        "command": command,
        "found": found,
        "claude_code": {
            "open": f"{cd} && claude",
            "mcp_add": f"claude mcp add --scope user hermitcrm -- {q(command)} "
                       f"--data {q(root)} mcp",
        },
        "desktop": {"config_path": desktop_config_path(platform), "block": block},
        "cursor": {"config_path": CURSOR_CONFIG, "block": block},
        "skills": [{"name": name, "state": state} for name, state in skills],
        "skills_missing": [name for name, state in skills if state in ("missing", "old")],
        "migrate": f"hermitcrm --data {q(root)} migrate",
    }


def for_folder(root: Path | str, platform: str) -> dict:
    """`facts` for this folder, with the command found and the skills checked."""
    from .datafolder import skill_states

    command, found = command_path()
    return facts(root, command, found, platform, skill_states(Path(root)))
