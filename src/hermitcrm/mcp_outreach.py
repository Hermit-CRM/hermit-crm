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

from .mcp import (READS, Folder, Tool, ToolError, hints, more, page, paging_fields,
                  schema, text)

# Said instead of asking the critic: an edit over MCP never starts an AI call.
NO_CRITIC = "edited over MCP, so the critic was not asked; Check again on the page asks it"

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

    # --- writes: the same outreach calls the Outreach page makes, one commit each

    def committed(before: str, what: str) -> str:
        sha = folder.head()
        if not sha or sha == before:
            return f"{what} Nothing was committed (see the app's log)."
        return f"{what} Committed as {sha[:7]}. Undo: undo({sha[:7]})"

    def edit_tool(args: dict) -> str:
        from .store import load_config

        item = item_or_error(folder.root, args.get("id"))
        parts = {k: str(args[k]) for k in ("subject", "body", "pitch")
                 if args.get(k) is not None}
        if not parts:
            raise ToolError("give the new subject, body or pitch (only those change)")
        store = folder.writable()
        before = folder.head()
        try:
            item, found = outreach.save_text(
                store, item.id, parts.get("subject"), parts.get("body"), parts.get("pitch"),
                critic=None, config=load_config(folder.root), why_not=NO_CRITIC,
                note=str(args.get("note") or ""))
        except outreach.OutreachError as exc:
            raise ToolError(f"Not saved: {exc}") from None
        checks = ("The checks pass." if not found else
                  f"{len(found)} check{'s' if len(found) != 1 else ''} fail: "
                  + "; ".join(found) + ".")
        return committed(before, f"Saved the draft {item.id}. {checks} It stays a draft: "
                                 "the user marks it ready in the web app.")

    def skip_tool(args: dict) -> str:
        item = item_or_error(folder.root, args.get("id"))
        reason = str(args.get("reason") or "").strip().lower()
        if reason not in outreach.MANUAL_SKIP_REASONS:
            raise ToolError("reason is one of " + ", ".join(outreach.MANUAL_SKIP_REASONS)
                            + "; add a note for anything else")
        store = folder.writable()
        before = folder.head()
        try:
            item = outreach.skip(store, item.id, reason, str(args.get("note") or ""))
        except outreach.OutreachError as exc:
            raise ToolError(f"Not skipped: {exc}") from None
        return committed(before, f"Skipped {item.id}: {item.skip_reason}.")

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
             "checks it fails, and the subject and text. edit_outreach_draft changes "
             "the text; marking it ready, scheduling and sending stay with the user in "
             "the web app.",
             schema({"id": text(description="The outreach id, from list_outreach.")},
                    ["id"]),
             show_tool, title="Show an outreach draft", annotations=READS,
             output_schema=SHOW_OUTPUT),
        Tool("edit_outreach_draft",
             "Change the text of a draft that is still a draft: its subject, body or "
             "(LinkedIn) pitch; what you leave out stays. The checks run again and "
             "the change is kept as a tracked edit beside the AI's original, with your "
             "note as its explainer. No AI is asked. It stays a draft: marking it "
             "ready, scheduling and sending are the user's, in the web app. ONE "
             "commit; the answer gives the commit id for undo.",
             schema({"id": text(description="The outreach id, from list_outreach."),
                     "subject": text(), "body": text(description="The whole new text."),
                     "pitch": text(description="LinkedIn: the message after they "
                                               "accept."),
                     "note": text(description="Why you changed it, in a few words; "
                                              "kept with the edit.")},
                    ["id"]),
             edit_tool, title="Edit an outreach draft", annotations=hints(destructive=True)),
        Tool("skip_outreach",
             "Take an open draft out of the queue, with the reason the Outreach page "
             "asks for. ONE commit; the answer gives the commit id for undo.",
             schema({"id": text(description="The outreach id, from list_outreach."),
                     "reason": text(description="Why it is not to be sent.",
                                    enum=list(outreach.MANUAL_SKIP_REASONS)),
                     "note": text(description="Anything else, one line.")},
                    ["id", "reason"]),
             skip_tool, title="Skip an outreach draft",
             annotations=hints(destructive=True, idempotent=True)),
    ]
