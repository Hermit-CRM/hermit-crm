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

"""MCP tools for the Outreach drafts in `outreach/`.

The line is drawn on purpose: an agent may read a draft, edit its text and
skip it. Marking it ready, scheduling it and sending it are a person's acts in
the web app, so no tool here does any of them, and `tests/test_mcp_protocol.py`
fails if a tool name ever says `send`, `ready` or `schedule`.
"""

from __future__ import annotations

from .mcp import (READS, Folder, Tool, ToolError, more, page, paging_fields, schema,
                  text)

ITEM = {"type": "object", "properties": {
    "id": {"type": "string"}, "state": {"type": "string"},
    "kind": {"type": "string"}, "channel": {"type": "string"},
    "company": {"type": "string"}, "contact": {"type": "string"},
    "subject": {"type": "string"},
    "problems": {"type": "integer", "description": "Checks the text fails now."},
    "created": {"type": "string"},
}, "required": ["id", "state", "kind", "channel", "company", "contact", "subject",
                "problems", "created"]}

LIST_OUTPUT = {"type": "object", "properties": {
    "status": {"type": "string"}, "total": {"type": "integer"},
    "items": {"type": "array", "items": ITEM},
    "next_cursor": {"type": "string"},
}, "required": ["status", "total", "items"]}

SHOW_OUTPUT = {"type": "object", "properties": {
    **ITEM["properties"],
    "language": {"type": "string"}, "approach": {"type": "string"},
    "body": {"type": "string"},
    "pitch": {"type": "string", "description": "LinkedIn: the message after they accept."},
    "checks": {"type": "array", "items": {"type": "string"}},
    "skip_reason": {"type": "string"},
}, "required": [*ITEM["required"], "language", "approach", "body", "pitch", "checks",
                "skip_reason"]}


def statuses() -> tuple[str, ...]:
    from .outreach import STATES

    return ("open", *STATES, "all")


def row(item) -> dict:
    return {"id": item.id, "state": item.state, "kind": item.kind,
            "channel": item.channel, "company": item.company, "contact": item.contact,
            "subject": item.subject, "problems": len(item.checks),
            "created": item.created.isoformat(timespec="minutes") if item.created else ""}


def item_or_error(root, raw):
    from . import outreach

    item_id = str(raw or "").strip()
    if not item_id:
        raise ToolError("id is required: an outreach id, as list_outreach gives it")
    item = outreach.get_item(root, item_id)
    if item is None:
        raise ToolError(f"unknown outreach item {item_id!r}; list_outreach gives the ids")
    return item


def tools(folder: Folder) -> list[Tool]:
    from . import outreach

    def list_tool(args: dict):
        status = str(args.get("status") or "drafted").strip()
        if status not in statuses():
            raise ToolError(f"status is one of {', '.join(statuses())}, not {status!r}")
        rows = [row(i) for i in outreach.items(folder.root)
                if status == "all" or i.state == status
                or (status == "open" and i.is_open)]
        shown, cursor = page(rows, args, "list_outreach")
        data = {"status": status, "total": len(rows), "items": shown}
        if cursor:
            data["next_cursor"] = cursor
        if not rows:
            return f"No outreach items are {status}.", data
        lines = [f"- {r['id']} | {r['state']} | {r['company']}/{r['contact']} | "
                 f"{r['channel']} | {r['subject'] or '-'} | "
                 + ("checks pass" if not r["problems"] else f"{r['problems']} problems")
                 for r in shown]
        return "\n".join(lines) + more(cursor, len(shown), len(rows)), data

    def show_tool(args: dict):
        store = folder.fresh()
        item = item_or_error(folder.root, args.get("id"))
        data = {**row(item), "language": item.language, "approach": item.approach,
                "body": item.body, "pitch": item.pitch, "checks": list(item.checks),
                "skip_reason": item.skip_reason}
        return outreach.render_item(store, item), data

    return [
        Tool("list_outreach",
             "The Outreach drafts by status: drafted (default, the ones waiting on "
             "the user), open (anything not yet sent or skipped), ready, queued, "
             "failed, skipped, sent, logged, researching, or all. Newest first.",
             schema({"status": text(description="Which drafts (default drafted).",
                                    enum=list(statuses())),
                     **paging_fields()}),
             list_tool, title="List outreach drafts", annotations=READS,
             output_schema=LIST_OUTPUT),
        Tool("show_outreach",
             "One outreach draft in full: who it is for, the research findings, the "
             "checks it fails, and the subject and text. Marking it ready, scheduling "
             "and sending stay with the user in the web app.",
             schema({"id": text(description="The outreach id, from list_outreach.")},
                    ["id"]),
             show_tool, title="Show an outreach draft", annotations=READS,
             output_schema=SHOW_OUTPUT),
    ]
