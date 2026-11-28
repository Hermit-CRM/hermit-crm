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

"""The MCP `search` tool: one word across companies, contacts, tasks and the
messages themselves.

`search_companies` turns a name into a slug; this finds where something was
said. It is a plain scan of the store, which already holds the whole folder in
memory, so there is no index to build or keep fresh.
"""

from __future__ import annotations

from .mcp import (READS, Folder, Tool, ToolError, more, page, paging_fields, schema,
                  text)

KINDS = ("company", "contact", "task", "interaction")
SNIPPET = 90   # characters of context around a hit in a message

RESULT = {"type": "object", "properties": {
    "kind": {"type": "string", "enum": list(KINDS)},
    "company": {"type": "string", "description": "The company's slug."},
    "contact": {"type": "string", "description": "The contact's slug, or empty."},
    "id": {"type": "string", "description": "The interaction or task id, or empty."},
    "title": {"type": "string"},
    "detail": {"type": "string"},
}, "required": ["kind", "company", "contact", "id", "title", "detail"]}

OUTPUT = {"type": "object", "properties": {
    "query": {"type": "string"},
    "total": {"type": "integer"},
    "results": {"type": "array", "items": RESULT},
    "next_cursor": {"type": "string"},
}, "required": ["query", "total", "results"]}


def snippet(body: str, needle: str) -> str:
    """The words around the first hit, on one line."""
    flat = " ".join(body.split())
    at = flat.lower().find(needle)
    if at < 0:
        return flat[:SNIPPET]
    start = max(0, at - SNIPPET // 3)
    piece = flat[start:start + SNIPPET]
    return ("…" if start else "") + piece + ("…" if start + SNIPPET < len(flat) else "")


def scan(store, needle: str, kinds: tuple[str, ...]) -> list[dict]:
    """Every hit, companies first, then people, tasks, and messages newest first."""
    from .mcp_records import task_id

    found = {kind: [] for kind in KINDS}

    def hit(kind, company, contact="", id_="", title="", detail=""):
        found[kind].append({"kind": kind, "company": company.slug, "contact": contact,
                            "id": id_, "title": title, "detail": detail})

    for c in sorted(store.companies.values(), key=lambda c: c.name.lower()):
        if "company" in kinds and needle in " ".join([
                c.name, c.slug, c.website, c.linkedin, c.country, c.product_oneliner,
                " ".join(c.tags)]).lower():
            hit("company", c, title=c.name, detail=c.stage)
        if "contact" in kinds:
            for p in c.contacts.values():
                if needle in " ".join([p.name, p.slug, p.title, p.email, p.phone,
                                       p.linkedin]).lower():
                    hit("contact", c, p.slug, title=p.name,
                        detail=", ".join(x for x in (p.title, c.name) if x))
        if "task" in kinds:
            for todo in c.todos():
                if needle in todo.text.lower():
                    who = todo.contact.slug if todo.contact else ""
                    when = f"due {todo.due}" if todo.due else "no date"
                    hit("task", c, who, task_id(c, todo), title=todo.text,
                        detail=("done, " if todo.done else "") + when)
    if "interaction" in kinds:
        messages = [(it, c) for c in store.companies.values() for it in c.interactions
                    if needle in f"{it.subject}\n{it.body}".lower()]
        messages.sort(key=lambda pair: (pair[0].date is not None, pair[0].date, pair[0].id),
                      reverse=True)
        for it, c in messages:
            when = it.date.strftime("%Y-%m-%d") if it.date else "undated"
            title = f"{when} {it.label}" + (f": {it.subject}" if it.subject else "")
            hit("interaction", c, it.contact, it.id, title=title,
                detail=snippet(it.body, needle) if needle in it.body.lower() else it.subject)
    return [row for kind in KINDS for row in found[kind]]


def line(row: dict) -> str:
    where = row["company"] + (f"/{row['contact']}" if row["contact"] else "")
    id_ = f" | {row['id']}" if row["id"] else ""
    return f"- {row['kind']} | {where}{id_} | {row['title']} | {row['detail']}"


def tools(folder: Folder) -> list[Tool]:
    def search_tool(args: dict):
        needle = " ".join(str(args.get("query") or "").split()).lower()
        if not needle:
            raise ToolError("query is required")
        kinds = args.get("kinds") or list(KINDS)
        if isinstance(kinds, str):
            kinds = [kinds]
        wrong = [k for k in kinds if k not in KINDS]
        if wrong:
            raise ToolError(f"kinds are {', '.join(KINDS)}; not {wrong[0]!r}")
        rows = scan(folder.fresh(), needle, tuple(kinds))
        shown, cursor = page(rows, args, "search")
        data = {"query": needle, "total": len(rows), "results": shown}
        if cursor:
            data["next_cursor"] = cursor
        if not rows:
            return f"Nothing matches {needle!r}.", data
        body = "\n".join(line(r) for r in shown) + more(cursor, len(shown), len(rows))
        return body, data

    return [
        Tool("search",
             "Find a word anywhere in the CRM: company names and fields, people "
             "(name, title, email, phone), task text, and the subject and body of "
             "every logged message. Companies come first, then people, tasks, and "
             "messages newest first; each row gives the slugs and id to pass to "
             "show_company, show_contact or complete_task.",
             schema({"query": text(description="Text to look for; case is ignored."),
                     "kinds": {"type": "array", "items": {"type": "string",
                                                          "enum": list(KINDS)},
                               "description": "Only these kinds of hit (default all)."},
                     **paging_fields()},
                    ["query"]),
             search_tool, title="Search everything", annotations=READS,
             output_schema=OUTPUT),
    ]
