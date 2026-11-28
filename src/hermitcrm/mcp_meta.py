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

"""MCP tools about Hermit itself rather than one record: the routines.

Running a routine is not here on purpose: a run asks the AI and writes drafts,
which is the user's to start (Make it yours, or `hermitcrm routines run`).
"""

from __future__ import annotations

from .mcp import READS, Folder, Tool, more, page, paging_fields, schema

ROUTINE = {"type": "object", "properties": {
    "name": {"type": "string"}, "title": {"type": "string"},
    "state": {"type": "string", "enum": ["on", "paused", "problem"]},
    "action": {"type": "string"}, "does": {"type": "string"},
    "last_run": {"type": "string"},
}, "required": ["name", "title", "state", "action", "does", "last_run"]}

ROUTINES_OUTPUT = {"type": "object", "properties": {
    "total": {"type": "integer"},
    "routines": {"type": "array", "items": ROUTINE},
    "problems": {"type": "array", "items": {"type": "string"}},
    "drafts_waiting": {"type": "integer"},
    "next_cursor": {"type": "string"},
}, "required": ["total", "routines", "problems", "drafts_waiting"]}


def tools(folder: Folder) -> list[Tool]:
    def routines_tool(args: dict):
        from . import routines
        from .store import load_config

        config = load_config(folder.root)
        loaded = routines.load(folder.root, config)
        state = routines.read_state(folder.root)
        valid = {r.name: r for r in loaded.routines}
        rows = []
        for name in loaded.names:      # in file order, a broken one included
            r = valid.get(name)
            rows.append({"name": name, "title": r.title if r else "",
                         "state": r.state if r else "problem",
                         "action": r.action if r else "",
                         "does": routines.describe(r, config) if r else
                         "Has a problem (see problems); it does not run.",
                         "last_run": routines.last_run_text(state.get(name))})
        shown, cursor = page(rows, args, "list_routines")
        waiting = len(routines.drafts(folder.root))
        data = {"total": len(rows), "routines": shown, "problems": list(loaded.errors),
                "drafts_waiting": waiting}
        if cursor:
            data["next_cursor"] = cursor
        if not loaded.present:
            return ("No routines.toml in this folder, so no routines. adjust_help with "
                    "topic adjust-routines says how to write one."), data
        lines = [f"- {r['name']} | {r['state']} | {r['title']} | {r['does']} | "
                 f"{r['last_run']}" for r in shown]
        lines.append(f"Drafts waiting on Home: {waiting}")
        lines += loaded.errors
        return "\n".join(lines) + more(cursor, len(shown), len(rows)), data

    return [
        Tool("list_routines",
             "The routines in routines.toml: what each does, whether it is on or "
             "paused, and how its last run went, plus how many of their drafts wait "
             "on Home. Turning one on and running it are the user's.",
             schema({**paging_fields()}),
             routines_tool, title="List routines", annotations=READS,
             output_schema=ROUTINES_OUTPUT),
    ]
