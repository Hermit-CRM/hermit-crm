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

"""What the MCP server offers besides record tools: the routines, the
resources (the pipeline, the playbook, one company by slug) and the prompts.

Running a routine is not here on purpose: a run asks the AI and writes drafts,
which is the user's to start (Make it yours, or `hermitcrm routines run`).

A prompt is a short instruction that names the tools to call, not a script:
the agent reads the tool descriptions for the rest. Every tool a prompt names
is in backticks, and a test checks each one exists.
"""

from __future__ import annotations

import re

from .mcp import (READS, Catalog, Folder, Prompt, Resource, ResourceTemplate, Tool, more,
                  page, paging_fields, schema)

SCHEME = "hermitcrm://"
COMPANY_URI = re.compile(r"^hermitcrm://companies/([a-z0-9]+(?:-[a-z0-9]+)*)$")

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


# --------------------------------------------------- resources and prompts


def catalog(folder: Folder) -> Catalog:
    from . import pipeline
    from .cli import cmd_show

    def pipeline_text() -> str:
        return pipeline.render(folder.fresh())

    def playbook_text() -> str:
        path = folder.root / "MESSAGING.md"
        if path.is_file() and not path.is_symlink():
            return path.read_text(encoding="utf-8")
        return ("No MESSAGING.md yet: this folder has no messaging playbook. "
                "adjust_write can write one (path MESSAGING.md); `hermitcrm help "
                "playbook` describes its headings.")

    def company_text(uri: str) -> str | None:
        match = COMPANY_URI.match(uri)
        if match is None:
            return None
        store = folder.fresh()
        if store.get(match.group(1)) is None:
            return None
        return cmd_show(store, match.group(1))

    resources = [
        Resource(f"{SCHEME}pipeline", "pipeline", "Pipeline",
                 "Every open company by stage with its last touch and next step, plus "
                 "overdue, silent and recently closed: PIPELINE.md as it is now.",
                 "text/markdown", pipeline_text),
        Resource(f"{SCHEME}playbook", "playbook", "Playbook (MESSAGING.md)",
                 "The user's messaging playbook: who they sell to, the approaches and "
                 "the proof they may cite. Read it before drafting anything.",
                 "text/markdown", playbook_text),
    ]
    templates = [
        ResourceTemplate(f"{SCHEME}companies/{{slug}}", "company", "One company",
                         "Everything on one company by its slug, as show_company gives "
                         "it: fields, contacts, the timeline, recent bodies.",
                         "text/plain", company_text),
    ]
    return Catalog(resources, templates, PROMPTS)


def arg(name: str, description: str, required: bool = True) -> dict:
    return {"name": name, "description": description, "required": required}


def _morning(args: dict) -> str:
    return ("Run my morning review in Hermit CRM. Call `list_pipeline`, then "
            "`list_tasks` with when overdue and again with when today, then "
            "`followups`, `brief` with days 1, and `list_outreach` for the drafts "
            "waiting on me. Tell me, briefly: what is overdue, what is due today, who "
            "I owe a reply, today's meetings, and how many drafts wait. End with at "
            "most five things to do first, in order. Change nothing until I say so.")


def _prep(args: dict) -> str:
    return (f"Prepare me for a meeting with {args['company']}. If that is a name, not "
            "a slug, find the slug with `search_companies`. Then call `show_company`, "
            "`show_contact` for the people I am likely to meet, and `list_tasks` with "
            "that company. Give me one page: where the deal stands, what happened in "
            "the last three interactions, what is still open, and three questions to "
            "ask. Change nothing.")


def _log_call(args: dict) -> str:
    company = args.get("company", "").strip()
    who = (f" The company is {company}." if company else
           " Find the company and the person with `search` first.")
    return ("Log this call in Hermit CRM." + who + " Call `add_interaction` with "
            "channel call, direction out unless the notes say they called me, the "
            "contact's slug, and my notes as the body, word for word. If the notes "
            "name a follow-up, add it with `add_task` and a due date. If the deal "
            "moved on, say which stage you would move it to and call `move_stage` "
            "only after I agree. Tell me what you wrote and the undo ids.\n\n"
            f"My notes:\n{args['notes']}")


def _weekly(args: dict) -> str:
    return ("Run my weekly review in Hermit CRM. Call `report` with days 7, `digest` "
            "with days 7, `list_pipeline`, `list_tasks` with when overdue and with "
            "when week, and `keep_in_touch`. Tell me what moved this week, which deals "
            "have gone quiet, what is overdue, and who I should catch up with. End "
            "with the five things that matter most next week. Change nothing.")


PROMPTS = [
    Prompt("morning_review", "Morning review",
           "What is overdue, due today, owed a reply and on the calendar, with what to "
           "do first. Reads only.", [], _morning),
    Prompt("prep_meeting", "Prepare a meeting",
           "A one-page brief on one company before you meet them. Reads only.",
           [arg("company", "The company's name or slug.")], _prep),
    Prompt("log_call", "Log a call",
           "Log a call from your notes, with a follow-up task; a stage move only after "
           "you agree.",
           [arg("notes", "What was said and agreed, as you would write it down."),
            arg("company", "The company's name or slug, when the notes do not say.",
                required=False)], _log_call),
    Prompt("weekly_review", "Weekly review",
           "The week in numbers, deals that went quiet, and what matters next week. "
           "Reads only.", [], _weekly),
]
