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

from .mcp import (ADDS, CHANGES, READS, Folder, Tool, ToolError, hints, more, page,
                  paging_fields, schema, text)

WHEN = ("overdue", "today", "week", "open", "done")

# What update_company and update_contact may set: the fields of the edit forms.
# Not the stage (move_stage, with its rules) and not notes (add_interaction
# with channel note: a note is a dated record, not a field).
COMPANY_FIELDS = ("name", "website", "linkedin", "country", "source", "value_eur_month",
                  "product_oneliner", "next_step", "next_step_due", "next_step_type",
                  "tags")
CONTACT_FIELDS = ("name", "title", "email", "phone", "linkedin", "role", "language")

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


    # --- writes: the same store calls the web forms make, one commit each

    def changed(before: str, what: str) -> str:
        """`what` and the commit it made, with the undo line, or why there is none."""
        notices = "".join(f" {n}." for n in folder.store.take_notices())
        sha = folder.head()
        if not sha or sha == before:
            return f"{what}{notices} Nothing was committed (see the app's log)."
        return f"{what}{notices} Committed as {sha[:7]}. Undo: undo({sha[:7]})"

    def custom_values(args: dict, scope: str) -> dict:
        from .fields import coerce_all, for_scope, load as load_fields

        raw = args.get("custom")
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise ToolError('custom must be an object of field: value, e.g. '
                            '{"renewal": "2027-01-31"}')
        defs = for_scope(load_fields(folder.root), scope)
        known = [d.key for d in defs]
        for key in raw:
            if key not in known:
                raise ToolError(f"unknown custom field {key!r} for a {scope}; "
                                + (f"fields.toml has {', '.join(known)}" if known
                                   else "fields.toml has none"))
        values, errors = coerce_all(defs, {k: "" if v is None else str(v)
                                           for k, v in raw.items()})
        if errors:
            raise ToolError("could not write: " + "; ".join(
                f"{k}: {v}" for k, v in errors.items()))
        return values

    def given(args: dict, names: tuple[str, ...]) -> dict:
        return {n: str(args[n]) for n in names if n in args and args[n] is not None}

    def update_company_tool(args: dict) -> str:
        slug = str(args.get("company") or "").strip()
        if not slug:
            raise ToolError("company is required (its slug)")
        fields = given(args, COMPANY_FIELDS)
        custom = custom_values(args, "company")
        if not fields and not custom:
            raise ToolError("nothing to change: give one or more fields, or custom")
        store = folder.writable()
        if store.get(slug) is None:
            raise ToolError(f"unknown company: {slug}")
        before = folder.head()
        store.take_notices()
        if custom:
            fields["custom"] = custom
        store.update_company(slug, **fields)
        names = [*(k for k in fields if k != "custom"), *custom]
        return changed(before, f"Updated {slug}: {', '.join(names)}.")

    def update_contact_tool(args: dict) -> str:
        from .models import split_name

        slug = str(args.get("company") or "").strip()
        cslug = str(args.get("contact") or "").strip()
        if not slug or not cslug:
            raise ToolError("company and contact are required (slugs)")
        fields = given(args, CONTACT_FIELDS)
        if "name" in fields:
            fields["first_name"], fields["last_name"] = split_name(fields.pop("name"))
        custom = custom_values(args, "contact")
        if not fields and not custom:
            raise ToolError("nothing to change: give one or more fields, or custom")
        store = folder.writable()
        company = store.get(slug)
        if company is None:
            raise ToolError(f"unknown company: {slug}")
        if cslug not in company.contacts:
            raise ToolError(f"unknown contact {cslug!r} at {slug} (contacts: "
                            f"{', '.join(sorted(company.contacts)) or 'none'})")
        before = folder.head()
        if custom:
            fields["custom"] = custom
        store.update_contact(slug, cslug, **fields)
        names = [*(k for k in fields if k != "custom"), *custom]
        return changed(before, f"Updated {slug}/{cslug}: {', '.join(names)}.")

    def move_stage_tool(args: dict) -> str:
        slug = str(args.get("company") or "").strip()
        stage = str(args.get("stage") or "").strip()
        if not slug or not stage:
            raise ToolError("company and stage are required")
        store = folder.writable()
        company = store.get(slug)
        if company is None:
            raise ToolError(f"unknown company: {slug}")
        if stage not in store.stages:
            raise ToolError(f"unknown stage {stage!r}; the stages are "
                            f"{', '.join(store.stages.names)}")
        if company.stage == stage:
            return f"{slug} is already {stage}. Nothing changed."
        fields = {"stage": stage}
        if args.get("reason") is not None:
            fields["lost_reason"] = str(args["reason"])
        if args.get("requalify_on") is not None:
            fields["requalify_on"] = str(args["requalify_on"])
        before = folder.head()
        store.take_notices()
        store.update_company(slug, **fields)   # no force: the stage rules apply
        moved = store.get(slug)
        what = f"Moved {slug} {company.stage} -> {moved.stage}"
        if moved.requalify_on:
            what += f" until {moved.requalify_on}"
        return changed(before, what + ".")

    def add_task_tool(args: dict) -> str:
        slug = str(args.get("company") or "").strip()
        if not slug:
            raise ToolError("company is required (its slug)")
        store = folder.writable()
        company = store.get(slug)
        if company is None:
            raise ToolError(f"unknown company: {slug}")
        contact = str(args.get("contact") or "").strip()
        if contact and contact not in company.contacts:
            raise ToolError(f"unknown contact {contact!r} at {slug} (contacts: "
                            f"{', '.join(sorted(company.contacts)) or 'none'})")
        before = folder.head()
        task = store.add_task(slug, str(args.get("text") or ""), due=args.get("due") or None,
                              contact=contact, type=str(args.get("type") or ""))
        owner = store.get(slug)
        todo = next(t for t in reversed(owner.todos())
                    if t.index is not None and t.text == task.text
                    and (t.contact.slug if t.contact else "") == contact)
        due = f", due {task.due}" if task.due else ""
        return changed(before, f"Added the task {task.text!r} to {slug}"
                       + (f"/{contact}" if contact else "") + f"{due} as "
                       f"{task_id(owner, todo)}.")

    def set_done(args: dict, done: bool) -> str:
        store = folder.writable()
        company, todo = find_task(store, args.get("task"))
        word = "done" if done else "open"
        if bool(todo.done) == done:
            return f"That task is already {word}. Nothing changed."
        before = folder.head()
        if todo.index is None:
            store.update_company(company.slug, next_step_status="done" if done else "open")
        else:
            store.set_task_done(company.slug, todo.index, done,
                                contact=todo.contact.slug if todo.contact else "",
                                text=todo.text)
        verb = "Done" if done else "Reopened"
        return changed(before, f"{verb}: {todo.text!r} ({company.slug}).")

    custom_field = {"type": "object", "description": "Custom fields from fields.toml, "
                    'as {"key": "value"}; an empty value clears one.'}
    task_field = text(description="The task's id, from list_tasks (or add_task's answer).")

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
        Tool("update_company",
             "Change fields of one company, as its edit form does: only the fields you "
             "give change, an empty one clears it. Not the stage (move_stage) and not "
             "notes (add_interaction with channel note). ONE commit; the answer gives "
             "the commit id for undo.",
             schema({"company": text(description="The company's slug."),
                     "name": text(), "website": text(), "linkedin": text(),
                     "country": text(description="Two-letter code, e.g. NL."),
                     "source": text(),
                     "value_eur_month": text(description="Whole euros per month."),
                     "product_oneliner": text(), "next_step": text(),
                     "next_step_due": text(description="YYYY-MM-DD."),
                     "next_step_type": text(description="A task type from Settings, "
                                                        "or empty."),
                     "tags": text(description="Comma-separated; replaces the tags."),
                     "custom": custom_field},
                    ["company"]),
             update_company_tool, title="Update a company", annotations=CHANGES),
        Tool("update_contact",
             "Change fields of one contact, as its edit form does: only the fields you "
             "give change. ONE commit; the answer gives the commit id for undo.",
             schema({"company": text(description="The company's slug."),
                     "contact": text(description="The contact's slug."),
                     "name": text(description='Full name, e.g. "Jane van Doe".'),
                     "title": text(), "email": text(), "phone": text(),
                     "linkedin": text(), "role": text(),
                     "language": text(description="Two-letter code, e.g. de."),
                     "custom": custom_field},
                    ["company", "contact"]),
             update_contact_tool, title="Update a contact", annotations=CHANGES),
        Tool("move_stage",
             "Move a company to another stage, as the board and the company page do. "
             "The stage rules in Settings apply and there is no way round them here: a "
             "move they forbid is refused and names the moves allowed. A lost stage "
             "needs a reason; a parked one (temp-disqualified) keeps a requalify date. "
             "Leaving the open stages skips the company's open outreach drafts in the "
             "same commit. ONE commit; the answer gives the commit id for undo.",
             schema({"company": text(description="The company's slug."),
                     "stage": text(description="A stage from Settings, e.g. discovery."),
                     "reason": text(description="Why (required for a lost stage; kept "
                                                "for lost, closed and parked ones)."),
                     "requalify_on": text(description="YYYY-MM-DD: when a parked company "
                                                      "comes back to the first stage.")},
                    ["company", "stage"]),
             move_stage_tool, title="Move a deal's stage",
             annotations=hints(destructive=True, idempotent=True)),
        Tool("add_task",
             "Add a task to a company, or to one of its contacts. ONE commit; the "
             "answer gives the task's id and the commit id for undo.",
             schema({"company": text(description="The company's slug."),
                     "text": text(description="What to do, one line."),
                     "due": text(description="YYYY-MM-DD, or leave it out."),
                     "contact": text(description="The contact's slug, for a task with "
                                                 "one person."),
                     "type": text(description="A task type from Settings, or leave it "
                                              "out.")},
                    ["company", "text"]),
             add_task_tool, title="Add a task", annotations=ADDS),
        Tool("complete_task",
             "Tick a task off. ONE commit; the answer gives the commit id for undo.",
             schema({"task": task_field}, ["task"]),
             lambda args: set_done(args, True), title="Complete a task",
             annotations=hints(idempotent=True)),
        Tool("reopen_task",
             "Open a done task again. ONE commit; the answer gives the commit id for "
             "undo.",
             schema({"task": task_field}, ["task"]),
             lambda args: set_done(args, False), title="Reopen a task",
             annotations=hints(idempotent=True)),
    ]
