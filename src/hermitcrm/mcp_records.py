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

"""MCP tools for one record at a time: a contact, and the to-do list.

A task is named by an id that `list_tasks` hands out:
`<company>/<contact or ->/<index or next>/<fingerprint>`. The fingerprint is a
few characters of the task's text, so an id kept from an earlier list is
refused once the task under it changed or moved, rather than ticking off the
task that took its place.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from .mcp import (READS, Folder, Tool, ToolError, more, page, paging_fields, schema,
                  text)

WHEN = ("overdue", "today", "week", "open", "done")

TASK = {"type": "object", "properties": {
    "id": {"type": "string", "description": "Pass to complete_task or reopen_task."},
    "company": {"type": "string"},
    "company_name": {"type": "string"},
    "contact": {"type": "string", "description": "The contact's slug, or empty."},
    "text": {"type": "string"},
    "due": {"type": "string", "description": "YYYY-MM-DD, or empty."},
    "type": {"type": "string"},
    "done": {"type": "boolean"},
    "done_on": {"type": "string"},
    "overdue": {"type": "boolean"},
}, "required": ["id", "company", "company_name", "contact", "text", "due", "type", "done",
                "done_on", "overdue"]}

TASKS_OUTPUT = {"type": "object", "properties": {
    "when": {"type": "string"},
    "total": {"type": "integer"},
    "tasks": {"type": "array", "items": TASK},
    "next_cursor": {"type": "string"},
}, "required": ["when", "total", "tasks"]}

CONTACT_OUTPUT = {"type": "object", "properties": {
    "company": {"type": "string"}, "contact": {"type": "string"},
    "name": {"type": "string"}, "title": {"type": "string"},
    "email": {"type": "string"}, "phone": {"type": "string"},
    "linkedin": {"type": "string"}, "role": {"type": "string"},
    "language": {"type": "string"},
    "custom": {"type": "object", "description": "Custom fields from fields.toml."},
    "tasks": {"type": "array", "items": TASK},
    "interactions": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "date": {"type": "string"},
        "channel": {"type": "string"}, "direction": {"type": "string"},
        "subject": {"type": "string"}, "outcome": {"type": "string"}},
        "required": ["id", "date", "channel", "direction", "subject", "outcome"]}},
}, "required": ["company", "contact", "name", "title", "email", "phone", "linkedin",
                "role", "language", "custom", "tasks", "interactions"]}


# ------------------------------------------------------------------ task ids


def fingerprint(task_text: str) -> str:
    return hashlib.sha256(" ".join(task_text.split()).encode()).hexdigest()[:6]


def task_id(company, todo) -> str:
    who = todo.contact.slug if todo.contact else "-"
    where = "next" if todo.index is None else str(todo.index)
    return f"{company.slug}/{who}/{where}/{fingerprint(todo.text)}"


def find_task(store, raw) -> tuple[object, object]:
    """(company, todo) for a task id, or a ToolError saying what to do."""
    parts = str(raw or "").strip().split("/")
    if len(parts) != 4:
        raise ToolError("task must be an id as list_tasks gives it, e.g. "
                        "acme/-/0/1a2b3c")
    slug, who, where, mark = parts
    company = store.get(slug)
    if company is None:
        raise ToolError(f"unknown company: {slug}")
    contact = "" if who == "-" else who
    index = None if where == "next" else where
    for todo in company.todos():
        if ((todo.contact.slug if todo.contact else "") == contact
                and (None if todo.index is None else str(todo.index)) == index):
            if fingerprint(todo.text) != mark:
                break
            return company, todo
    raise ToolError(f"task {raw} is not there any more (it was changed, done or deleted "
                    "since it was listed); call list_tasks again for its id")


def task_row(company, todo, today: date) -> dict:
    return {"id": task_id(company, todo), "company": company.slug,
            "company_name": company.name,
            "contact": todo.contact.slug if todo.contact else "",
            "text": todo.text, "due": todo.due.isoformat() if todo.due else "",
            "type": todo.type or "", "done": bool(todo.done),
            "done_on": todo.done_on.isoformat() if todo.done_on else "",
            "overdue": bool(todo.due and not todo.done and todo.due < today)}


def picks(when: str, today: date):
    """The test a task's (due, done) must pass for `when`."""
    week = today + timedelta(days=7)
    return {
        "overdue": lambda due, done: not done and due is not None and due < today,
        "today": lambda due, done: not done and due == today,
        "week": lambda due, done: not done and due is not None and today <= due <= week,
        "open": lambda due, done: not done,
        "done": lambda due, done: done,
    }[when]


def task_line(row: dict) -> str:
    who = f"/{row['contact']}" if row["contact"] else ""
    due = row["due"] or "no date"
    if row["done"]:
        due = f"done {row['done_on']}" if row["done_on"] else "done"
    elif row["overdue"]:
        due += " (overdue)"
    kind = f" [{row['type']}]" if row["type"] else ""
    return f"- {due} | {row['company_name']}{who} | {row['text']}{kind} | id {row['id']}"


def tools(folder: Folder) -> list[Tool]:
    def tasks_tool(args: dict):
        store = folder.fresh()
        when = str(args.get("when") or "open").strip()
        if when not in WHEN:
            raise ToolError(f"when is one of {', '.join(WHEN)}, not {when!r}")
        slug = str(args.get("company") or "").strip()
        companies = list(store.companies.values())
        if slug:
            company = store.get(slug)
            if company is None:
                raise ToolError(f"unknown company: {slug}")
            companies = [company]
        today = store.today()
        keep = picks(when, today)
        rows = [task_row(c, t, today) for c in companies for t in c.todos()
                if keep(t.due, t.done)]
        if when == "done":
            rows.sort(key=lambda r: (r["done_on"], r["company_name"].lower()), reverse=True)
        else:
            rows.sort(key=lambda r: (r["due"] == "", r["due"], r["company_name"].lower()))
        shown, cursor = page(rows, args, "list_tasks")
        data = {"when": when, "total": len(rows), "tasks": shown}
        if cursor:
            data["next_cursor"] = cursor
        if not rows:
            return f"No {when} tasks" + (f" for {slug}." if slug else "."), data
        return ("\n".join(task_line(r) for r in shown)
                + more(cursor, len(shown), len(rows))), data

    def contact_tool(args: dict):
        from .fields import for_scope, load as load_fields

        slug = str(args.get("company") or "").strip()
        cslug = str(args.get("contact") or "").strip()
        if not slug or not cslug:
            raise ToolError("company and contact are required (slugs, as show_company "
                            "lists them)")
        store = folder.fresh()
        company = store.get(slug)
        if company is None:
            raise ToolError(f"unknown company: {slug}")
        person = company.contacts.get(cslug)
        if person is None:
            known = ", ".join(sorted(company.contacts)) or "none"
            raise ToolError(f"unknown contact {cslug!r} at {slug} (contacts: {known})")
        today = store.today()
        custom = {d.key: person.extra[d.key]
                  for d in for_scope(load_fields(folder.root), "contact")
                  if person.extra.get(d.key) not in (None, "")}
        tasks = [task_row(company, t, today) for t in company.todos()
                 if t.contact is not None and t.contact.slug == cslug]
        history = sorted((it for it in company.interactions if it.contact == cslug),
                         key=lambda it: (it.date is not None, it.date, it.id), reverse=True)
        bodies = folder.as_int(args.get("bodies"), "bodies", 2)
        data = {"company": slug, "contact": cslug, "name": person.name,
                "title": person.title, "email": person.email, "phone": person.phone,
                "linkedin": person.linkedin, "role": person.role or "",
                "language": person.language or "", "custom": custom, "tasks": tasks,
                "interactions": [{"id": it.id,
                                  "date": it.date.isoformat() if it.date else "",
                                  "channel": it.channel, "direction": it.direction or "",
                                  "subject": it.subject, "outcome": it.outcome or ""}
                                 for it in history]}
        lines = [f"{person.name} at {company.name} ({slug}/{cslug})"]
        lines += [f"{k}: {data[k]}" for k in ("title", "email", "phone", "linkedin",
                                              "role", "language") if data[k]]
        lines += [f"{k}: {v}" for k, v in custom.items()]
        lines += ["", "Tasks:" if tasks else "Tasks: none"]
        lines += [task_line(r) for r in tasks]
        lines += ["", "Interactions:" if history else "Interactions: none"]
        for it in history:
            when = it.date.strftime("%Y-%m-%d") if it.date else "undated"
            lines.append(f"- {when} {it.label} | {it.id}"
                         + (f" | {it.subject}" if it.subject else "")
                         + (f" | {it.outcome}" if it.outcome else ""))
        for it in history[:max(bodies, 0)]:
            if it.body.strip():
                lines += ["", f"--- {it.id}", it.body.rstrip("\n")]
        return "\n".join(lines), data

    return [
        Tool("show_contact",
             "One person: their fields (custom ones too), their own tasks, every "
             "interaction with them newest first, and the latest message bodies.",
             schema({"company": text(description="The company's slug."),
                     "contact": text(description="The contact's slug, as show_company "
                                                 "lists it."),
                     "bodies": text("integer", "How many recent bodies to include "
                                               "(default 2).")},
                    ["company", "contact"]),
             contact_tool, title="Show a contact", annotations=READS,
             output_schema=CONTACT_OUTPUT),
        Tool("list_tasks",
             "Your to-do list, the Tasks page as rows: overdue, due today, due in the "
             "next 7 days (today onwards, as on the Tasks page), every open task, or "
             "the ones done. Soonest first; done ones latest first. Each row has the id "
             "that "
             "complete_task and reopen_task take.",
             schema({"when": text(description="overdue, today, week, open (default) "
                                              "or done.", enum=list(WHEN)),
                     "company": text(description="Only this company's tasks (its slug)."),
                     **paging_fields()}),
             tasks_tool, title="List tasks", annotations=READS,
             output_schema=TASKS_OUTPUT),
    ]
