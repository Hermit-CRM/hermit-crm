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

"""An MCP server for the data folder, spoken over stdio.

Every CRM worth comparing to now ships one, and for Hermit CRM it is the
cheapest of them to build: the tools are the store calls that `hermitcrm add`
and `hermitcrm show` already wrap. It is also the feature where being a folder
of files is an advantage rather than a quirk -- there is no API to mirror, no
sync, no second copy of the data.

Today "AI-agent friendly" means *an agent with a shell in this folder*. This
opens the same reads and writes to Claude Desktop, ChatGPT, Cursor and anything
else that speaks MCP, without one.

The transport is newline-delimited JSON-RPC 2.0 on stdin/stdout, which is all
MCP's stdio transport is, so this costs no dependency. Nothing is printed to
stdout that is not a response: logging goes to stderr, or the stream breaks.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "hermitcrm", "version": __version__}

# JSON-RPC error codes we use; the rest of the space is not ours.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass
class Tool:
    """One MCP tool: what it is called, what it takes, and what runs."""

    name: str
    description: str
    schema: dict
    handler: Callable[[dict], str]

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description,
                "inputSchema": self.schema}


def text(kind: str = "string", description: str = "", **extra) -> dict:
    return {"type": kind, "description": description, **extra}


def schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": required or [], "additionalProperties": False}


# ------------------------------------------------------------------- the tools


def build_tools(root: Path, store) -> list[Tool]:
    """The tool list, bound to one data folder.

    Reads first: an agent that can only read is useful on its own, and it is
    what most MCP clients will be pointed at. The three writes are the same
    `store.create_*` calls the web form and `hermitcrm add` make, so validation,
    slugging, the stage move and the git commit are shared rather than copied.
    """
    from . import brief as briefing
    from . import followups as radar
    from . import pipeline
    from .cli import cmd_digest, cmd_report, cmd_show
    from .models import split_name
    from .store import load_config

    def as_int(value, name: str, default: int) -> int:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ToolError(f"{name} must be a whole number, got {value!r}")

    def fresh():
        """Re-read the folder before answering.

        A long-lived MCP session would otherwise serve a snapshot from whenever
        the client connected, and the web app, the CLI and a git pull all write
        underneath it.
        """
        store.load()
        return store

    def pipeline_tool(args: dict) -> str:
        return pipeline.render(fresh())

    def show_tool(args: dict) -> str:
        slug = str(args.get("slug", "")).strip()
        if not slug:
            raise ToolError("slug is required")
        return cmd_show(fresh(), slug, bodies=as_int(args.get("bodies"), "bodies", 3))

    def search_tool(args: dict) -> str:
        needle = str(args.get("query", "")).strip().lower()
        if not needle:
            raise ToolError("query is required")
        limit = as_int(args.get("limit"), "limit", 20)
        hits = []
        for c in fresh().companies.values():
            haystack = " ".join([c.name, c.slug, c.website, c.linkedin, c.country,
                                 c.product_oneliner, " ".join(c.tags),
                                 " ".join(p.name for p in c.contacts.values())]).lower()
            if needle in haystack:
                hits.append(f"- {c.slug} | {c.name} | {c.stage} | "
                            f"last: {c.last_touch_summary}")
        if not hits:
            return f"No company matches {needle!r}."
        more = f"\n({len(hits)} matches, showing {limit})" if len(hits) > limit else ""
        return "\n".join(hits[:limit]) + more

    def digest_tool(args: dict) -> str:
        return cmd_digest(fresh(), as_int(args.get("days"), "days", 7))

    def report_tool(args: dict) -> str:
        return cmd_report(fresh(), days=as_int(args.get("days"), "days", 30), md=True)

    def followups_tool(args: dict) -> str:
        config = load_config(root)
        rows = radar.radar(
            fresh(),
            reply_after=as_int(args.get("reply_after"), "reply_after",
                               config["followup_reply_days"]),
            nudge_after=as_int(args.get("nudge_after"), "nudge_after",
                               config["followup_nudge_days"]),
        )
        return radar.render(rows)

    def brief_tool(args: dict) -> str:
        from . import bcc

        days = as_int(args.get("days"), "days", 7)
        current = fresh()
        return briefing.render(
            briefing.briefs(current, bcc.Inbox(root), days=days), current.today(), days)

    # --- writes

    def writable():
        """The store with the commit-and-push write path attached."""
        from .cli import _writer

        current = fresh()
        current.on_write = _writer(current, root, load_config(root))
        return current

    def given(args: dict, *names: str) -> dict:
        """Only the fields the caller actually sent, as strings.

        An absent field and an empty one are different: absent means "leave the
        store's default", empty would mean "set it to nothing".
        """
        return {n: str(args[n]) for n in names
                if n in args and args[n] is not None}

    def add_company_tool(args: dict) -> str:
        name = str(args.get("name", "")).strip()
        if not name:
            raise ToolError("name is required")
        fields = given(args, "website", "linkedin", "country", "source", "stage",
                       "value_eur_month", "product_oneliner", "next_step",
                       "next_step_due", "next_step_type", "tags", "notes")
        company = writable().create_company(name=name, **fields)
        return (f"Created {company.name} as {company.slug} "
                f"(companies/{company.slug}/company.md), stage {company.stage}.")

    def add_contact_tool(args: dict) -> str:
        slug = str(args.get("company", "")).strip()
        name = str(args.get("name", "")).strip()
        if not slug or not name:
            raise ToolError("company and name are required")
        first, last = split_name(name)
        fields = given(args, "title", "email", "phone", "linkedin", "role", "notes")
        contact = writable().create_contact(slug, first_name=first, last_name=last,
                                            **fields)
        return (f"Created {contact.name} as {contact.slug} under {slug} "
                f"(companies/{slug}/contacts/{contact.slug}.md).")

    def add_interaction_tool(args: dict) -> str:
        slug = str(args.get("company", "")).strip()
        if not slug:
            raise ToolError("company is required")
        fields = given(args, "channel", "direction", "body", "contact", "subject",
                       "date", "outcome")
        current = writable()
        before = current.get(slug)
        stage_before = before.stage if before else ""
        it = current.create_interaction(slug, **fields)
        after = current.get(slug)
        moved = ""
        if after is not None and after.stage != stage_before:
            moved = f" {slug} moved {stage_before} -> {after.stage}."
        return (f"Logged {it.label} on {slug} as {it.id} "
                f"(companies/{slug}/interactions/{it.id}.md).{moved}")

    days_field = text("integer", "How many days to cover.")

    return [
        Tool("list_pipeline",
             "The whole pipeline as one page: every open company by stage with its "
             "last touch and next step, plus overdue, silent and recently closed. "
             "Read this first; it usually answers the question on its own.",
             schema({}), pipeline_tool),
        Tool("show_company",
             "Everything on one company: fields, notes, contacts, and the timeline "
             "with the most recent message bodies.",
             schema({"slug": text(description="The company's slug, as list_pipeline "
                                              "and search_companies print it."),
                     "bodies": text("integer", "How many recent bodies to include "
                                               "(default 3).")},
                    ["slug"]), show_tool),
        Tool("search_companies",
             "Find companies by name, slug, website, country, tag, one-liner or "
             "contact name. Use this to turn a name into a slug.",
             schema({"query": text(description="Substring to look for; case is ignored."),
                     "limit": text("integer", "Most rows to return (default 20).")},
                    ["query"]), search_tool),
        Tool("digest",
             "Interactions in the last N days, oldest first, with a slice of each "
             "body. What happened recently.",
             schema({"days": days_field}), digest_tool),
        Tool("report",
             "Activity, funnel and conversion, time in stage, message outcomes and "
             "data hygiene over the last N days, as Markdown tables.",
             schema({"days": days_field}), report_tool),
        Tool("followups",
             "Threads waiting on you: messages somebody sent that you have not "
             "answered, then messages you sent that nobody answered.",
             schema({"reply_after": text("integer", "Days before an unanswered "
                                                    "inbound message counts."),
                     "nudge_after": text("integer", "Days before an unanswered "
                                                    "outbound message counts.")}),
             followups_tool),
        Tool("brief",
             "For each upcoming meeting, the company behind it: stage, open next "
             "step, contacts and the last three interactions.",
             schema({"days": days_field}), brief_tool),
        Tool("add_company",
             "Create a company. Writes the file and commits it. Returns the slug, "
             "which is what every other tool takes.",
             schema({"name": text(description='The company name, e.g. "Acme BV".'),
                     "website": text(), "linkedin": text(),
                     "country": text(description="Two-letter code, e.g. NL."),
                     "source": text(), "stage": text(description="Default prospect."),
                     "value_eur_month": text(description="Whole euros per month."),
                     "product_oneliner": text(), "next_step": text(),
                     "next_step_due": text(description="YYYY-MM-DD."),
                     "next_step_type": text(description="A task type from Settings, or empty."),
                     "tags": text(description="Comma-separated."), "notes": text()},
                    ["name"]), add_company_tool),
        Tool("add_contact",
             "Create a contact under a company. Writes the file and commits it.",
             schema({"company": text(description="The company's slug."),
                     "name": text(description='Full name, e.g. "Jane van Doe".'),
                     "title": text(), "email": text(), "phone": text(),
                     "linkedin": text(), "role": text(),
                     "notes": text(description="Logged as a note interaction on "
                                               "the new contact.")},
                    ["company", "name"]), add_contact_tool),
        Tool("add_interaction",
             "Log an email, LinkedIn message, call or meeting, or a note about a "
             "person. Writes the file and commits it. Logging one on a prospect "
             "moves it to engaged (a note does not).",
             schema({"company": text(description="The company's slug."),
                     "channel": text(description="email, linkedin, call, meeting or "
                                                 "note (a memo: no direction).",
                                     enum=["email", "linkedin", "call", "meeting", "note"]),
                     "direction": text(description="in (they contacted you) or out. "
                                                   "Required except for a note.",
                                       enum=["in", "out"]),
                     "body": text(description="The message itself, kept byte for byte."),
                     "contact": text(description="The contact's slug, when it was "
                                                 "with one person."),
                     "subject": text(), "date": text(description="YYYY-MM-DD or "
                                                                 "YYYY-MM-DDTHH:MM."),
                     "outcome": text()},
                    ["company", "channel"]), add_interaction_tool),
    ]


class ToolError(Exception):
    """A tool was called wrongly. Reported to the model, not to the transport."""


# ---------------------------------------------------------------- the protocol


def error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def result(id_, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": payload}


def tool_result(body: str, failed: bool = False) -> dict:
    out = {"content": [{"type": "text", "text": body}]}
    if failed:
        out["isError"] = True
    return out


def handle(message: dict, tools: dict[str, Tool]) -> dict | None:
    """One JSON-RPC message in, one response out -- or None for a notification.

    A notification (no `id`) must never be answered; answering one is the
    classic way to wedge a client that is not expecting a reply.
    """
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 message")
    method = message.get("method")
    id_ = message.get("id")
    is_request = id_ is not None
    params = message.get("params") or {}

    if not isinstance(method, str):
        return error(id_, INVALID_REQUEST, "no method") if is_request else None

    if method == "initialize":
        return result(id_, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "This is one person's CRM: a folder of Markdown files in git. "
                "Start with list_pipeline; it is the cheap summary and usually "
                "enough. Use search_companies to turn a name into a slug, and "
                "show_company for one account. The add_* tools each write a file "
                "and make a git commit, so only call them when the user has asked "
                "for a record to be created or logged."),
        })

    if not is_request:  # notifications/initialized, notifications/cancelled, ...
        return None

    if method == "ping":
        return result(id_, {})

    if method == "tools/list":
        return result(id_, {"tools": [t.spec() for t in tools.values()]})

    if method == "tools/call":
        name = params.get("name")
        tool = tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return error(id_, INVALID_PARAMS, f"unknown tool {name!r}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return error(id_, INVALID_PARAMS, "arguments must be an object")
        try:
            return result(id_, tool_result(tool.handler(arguments)))
        except ToolError as exc:
            return result(id_, tool_result(str(exc), failed=True))
        except Exception as exc:  # a bad value: the model can read it and retry
            return result(id_, tool_result(describe(exc), failed=True))

    return error(id_, METHOD_NOT_FOUND, f"unknown method {method!r}")


def clip(value: str, limit: int = 220) -> str:
    """Shorten one validation message.

    The store's country error lists all 249 codes, which is fine in a terminal
    and wasteful in a model's context. The part that says what was wrong comes
    first, so cutting the tail loses nothing worth reading.
    """
    value = str(value)
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def describe(exc: Exception) -> str:
    """A tool failure in words a model can act on, not a traceback."""
    from .models import ValidationError

    if isinstance(exc, ValidationError):
        return "could not write: " + "; ".join(
            f"{k}: {clip(v)}" for k, v in exc.errors.items())
    return clip(f"{type(exc).__name__}: {exc}")


def keep_stdout_clean() -> None:
    """Detach any log handler pointing at stdout.

    A single stray line there desynchronises the client for the rest of the
    session, and the git push warning is exactly the kind of line that turns up
    at the worst moment. Python's own default already goes to stderr, so there
    is nothing to add -- only something to take away.
    """
    import logging

    for logger in (logging.getLogger(), logging.getLogger("crm")):
        for handler in list(logger.handlers):
            if getattr(handler, "stream", None) is sys.stdout:
                logger.removeHandler(handler)


def serve(root: Path, store, stdin=None, stdout=None) -> int:
    """Read messages until stdin closes. Returns an exit code."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    keep_stdout_clean()
    tools = {t.name: t for t in build_tools(Path(root), store)}

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            write(stdout, error(None, PARSE_ERROR, "invalid JSON"))
            continue
        try:
            response = handle(message, tools)
        except Exception as exc:  # never let one bad message kill the server
            response = error(message.get("id") if isinstance(message, dict) else None,
                             INTERNAL_ERROR, describe(exc))
        if response is not None:
            write(stdout, response)
    return 0


def write(stdout, payload: dict) -> None:
    stdout.write(json.dumps(payload) + "\n")
    stdout.flush()
