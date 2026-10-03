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

import dataclasses
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__
from .help import TOPICS as HELP_TOPICS

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
    what most MCP clients will be pointed at. The three record writes are the
    same `store.create_*` calls the web form and `hermitcrm add` make, so
    validation, slugging, the stage move and the git commit are shared rather
    than copied. The Make it yours tools after them do for a client without a
    shell what `hermitcrm help adjust` asks of an agent with one: write the
    allowlisted files, check them, commit once, change records in bulk only
    after a dry run, and undo.
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

    # --- make it yours: the extension files, bulk changes and undo
    #
    # The same rules `hermitcrm help adjust` gives an agent with a shell, but
    # enforced here rather than only written down: a file outside the allowlist
    # is refused, content that `hermitcrm check` would fault never lands, a new
    # routine arrives paused, and a bulk change needs a fresh preview first.

    def gitops():
        from .gitops import GitOps

        config = load_config(root)
        return GitOps(root, push_enabled=bool(config.get("push_enabled", True)),
                      remote=str(config.get("remote", "origin")))

    def adjust_help_tool(args: dict) -> str:
        from . import help as helptext

        topic = str(args.get("topic") or "adjust").strip()
        if topic not in RECIPES:
            raise ToolError(f"unknown topic {topic!r}{near(topic, RECIPES)}. "
                            f"Topics: {', '.join(RECIPES)}.")
        return MCP_NOTE + "\n\n" + (helptext.read(topic) or "")

    def adjust_read_tool(args: dict) -> str:
        raw = str(args.get("path") or "").strip()
        if not raw:
            present = [rel for rel in (*WRITABLE, "config.toml") if (root / rel).is_file()]
            folder = root / "dashboards"
            if folder.is_dir():
                present += sorted(f"dashboards/{p.name}" for p in folder.glob("*.toml")
                                  if p.is_file())
            return ("Files you may change that exist now: " + ", ".join(present) + "."
                    if present else "None of the files you may change exist yet.")
        rel = extension_path(raw, config=True)
        if rel == "config.toml":
            return config_keys_text(load_config(root))
        target = no_link(rel)
        return target.read_text(encoding="utf-8") if target.is_file() else ""

    def adjust_write_tool(args: dict) -> str:
        from . import routines

        rel = extension_path(args.get("path"))
        content = args.get("content")
        if not isinstance(content, str):
            raise ToolError("content is required: the whole new text of the file")
        if len(content.encode("utf-8")) > MAX_FILE:
            raise ToolError(f"content is over {MAX_FILE // 1024} KB; a file you may "
                            "change is never that big")
        what = summary_of(args.get("summary"))
        target = no_link(rel)
        with store.lock:
            old = target.read_bytes() if target.is_file() else None
            if dirty(rel):
                raise ToolError(f"Not written: {rel} has changes that are not committed "
                                "yet (the user may be editing it). Ask the user to save or "
                                "discard them, then read it again with adjust_read.")
            notes = []
            if rel == routines.FILE:
                content, notes = arrive_paused(content, old)
            if old is not None and old == content.encode("utf-8"):
                return f"No change: {rel} already has this text. Nothing was committed."
            before, after = trial(rel, content)
            new = [p for p in after if p not in before or p.startswith(f"{rel}:")]
            if new:
                raise ToolError(f"Not written: {rel} would not pass `hermitcrm check`, so "
                                "the file is as it was and nothing was committed. Fix "
                                "these and write it again:\n- " + "\n- ".join(new))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            git = gitops()
            sha = git.commit(f"ai: adjust: {what}", [rel])
            if not sha:
                if old is None:
                    target.unlink()
                else:
                    target.write_bytes(old)
                raise ToolError(f"Not written: git could not commit {rel} (is it in "
                                ".gitignore, or is this not a git folder?). The file is "
                                "as it was.")
        git.push_async()
        sha7 = sha[:7]
        lines = [f"Wrote {rel} and committed it as {sha7}: ai: adjust: {what}.", *notes,
                 "The app shows it on the next page load. Undo: undo(" + sha7 + ")"]
        return "\n".join(lines)

    def adjust_config_tool(args: dict) -> str:
        from . import adjust
        from . import setup as setup_steps
        from . import task_types

        key = str(args.get("key") or "").strip()
        if key not in CONFIG_KEYS:
            raise ToolError(f"key must be one of {', '.join(CONFIG_KEYS)}"
                            f"{near(key, CONFIG_KEYS)}; every other setting is the user's "
                            "to change in Settings")
        if "value" not in args:
            raise ToolError("value is required")
        value = args["value"]
        config = load_config(root)
        path = root / "config.toml"
        if key == "task_types":
            # The Settings form's own reading of its rows; a name that is
            # there already is not a rename (Settings does renames).
            names, colours = task_type_rows(
                value, task_types.from_config(config.get("task_types")))
            types, _, errors = task_types.plan_rows(names, colours, names)
            if errors:
                raise ToolError("; ".join(errors.values()))
            new_values = {key: task_types.to_config(types)}
        else:
            outcomes = value if key == "outcomes" else config.get("outcomes") or []
            if key == "outcomes" and not isinstance(outcomes, list):
                raise ToolError("outcomes must be a list of names, e.g. "
                                '["replied", "no reply"]')
            silent = value if key == "silent_days" else config.get("silent_days", 14)
            planned = setup_steps.plan_outcomes(
                [str(o) for o in outcomes], str(config.get("message_window_days", 14)),
                str(silent))
            if not planned.ok:
                raise ToolError("; ".join(planned.errors.values()))
            new_values = {key: planned.values[key]}
        with store.lock:
            if dirty("config.toml"):
                raise ToolError("Not saved: config.toml has changes that are not committed "
                                "yet (the user may be editing it). Ask the user to save or "
                                "discard them, then try again.")
            if new_values[key] == load_config(root).get(key):
                return f"No change: {key} already is {json.dumps(new_values[key])}."
            # Tried on a scratch copy first, so a value check would fault never
            # reaches the folder.
            with tempfile.TemporaryDirectory(prefix="hermitcrm-adjust-") as tmp:
                scratch = Path(tmp)
                if path.is_file():
                    shutil.copyfile(path, scratch / "config.toml")
                before = adjust.validate_config(scratch)
                setup_steps.set_config_values(scratch / "config.toml", new_values)
                new = [p for p in adjust.validate_config(scratch) if p not in before]
            if new:
                raise ToolError("Not saved, config.toml is as it was: " + "; ".join(new))
            setup_steps.set_config_values(path, new_values)
            git, shas = gitops(), []

            def commit(message: str, paths: list[str]) -> None:
                what = message.removeprefix("settings: ")
                shas.append((git.commit(f"ai: adjust: {what}", paths), what))

            setup_steps.commit_config(root, commit)
        if not shas or not shas[0][0]:
            return (f"Saved {key} in config.toml, but it was not committed (see the "
                    "app's log); there is nothing to undo.")
        git.push_async()
        sha7, what = shas[0][0][:7], shas[0][1]
        return (f"Saved {key} and committed it as {sha7}: ai: adjust: {what}. "
                f"Undo: undo({sha7})")

    def bulk_args(args: dict):
        from . import bulk

        scope = str(args.get("scope") or "").strip()
        where = args.get("where") or []
        if isinstance(where, str):
            where = [where]
        if not isinstance(where, list) or not all(isinstance(w, str) for w in where):
            raise ToolError('where must be a list of "key=value" filters, e.g. '
                            '["stage=prospect", "country=DE"]')
        raw = args.get("ops") or {}
        if not isinstance(raw, dict):
            raise ToolError("ops must be an object: set, unset, add_tags, remove_tags, stage")
        unknown = [k for k in raw if k not in OPS]
        if unknown:
            raise ToolError(f"unknown op {unknown[0]!r}{near(unknown[0], OPS)}; "
                            f"ops are {', '.join(OPS)}")
        sets = raw.get("set") or {}
        if not isinstance(sets, dict):
            raise ToolError('ops.set must be an object, e.g. {"next_step": "Call"}')
        lists = {}
        for name in ("unset", "add_tags", "remove_tags"):
            value = raw.get(name) or []
            lists[name] = [value] if isinstance(value, str) else value
            if not isinstance(lists[name], list):
                raise ToolError(f"ops.{name} must be a list")

        def form(value) -> str:  # the text a form field would carry
            if value is None:
                return ""
            return ("true" if value else "false") if isinstance(value, bool) else str(value)

        ops = bulk.Ops(set={str(k): form(v) for k, v in sets.items()},
                       unset=[str(v) for v in lists["unset"]],
                       add_tags=[str(v) for v in lists["add_tags"]],
                       remove_tags=[str(v) for v in lists["remove_tags"]],
                       stage=str(raw["stage"]) if raw.get("stage") else None)
        everything = bool(args.get("all"))
        identity = json.dumps({"scope": scope, "where": where, "all": everything,
                               "ops": dataclasses.asdict(ops), "head": head()},
                              sort_keys=True)
        return scope, where, ops, everything, hashlib.sha256(identity.encode()).hexdigest()[:16]

    def plan_for(args: dict):
        from . import bulk

        scope, where, ops, everything, preview_id = bulk_args(args)
        try:
            plan = bulk.plan(fresh(), scope, where, ops, everything=everything)
        except bulk.BulkError as exc:
            raise ToolError(cli_words(str(exc))) from None
        if plan.matched == 0:
            return plan, preview_id, (f"No {plan.nouns} match {plan.describe_where()}. "
                                      "Nothing to change.")
        if plan.changed == 0:
            return plan, preview_id, (f"{plan.count(plan.matched).capitalize()} "
                                      f"{'matches' if plan.matched == 1 else 'match'}, and "
                                      "every one already looks like this. Nothing to change.")
        return plan, preview_id, ""

    def bulk_preview_tool(args: dict) -> str:
        plan, preview_id, nothing = plan_for(args)
        if nothing:
            return nothing
        shown = plan.render(arrow="->").rsplit("\n", 1)[0]
        return (f"{shown}\nNothing changed. Show this to the user. Only after they say "
                f"yes, call bulk_apply with preview_id {preview_id!r} and the same scope, "
                f"where, all and ops, to change {plan.count(plan.changed)} in one commit.")

    def bulk_apply_tool(args: dict) -> str:
        from . import bulk

        given_id = str(args.get("preview_id") or "").strip()
        if not given_id:
            raise ToolError("preview_id is required: call bulk_preview first and show "
                            "the user its dry run")
        _, _, _, _, expected = bulk_args(args)
        if given_id != expected:
            raise ToolError("Refused, nothing changed: this preview_id is not from a "
                            "preview of these same arguments on the folder as it is now "
                            "(the arguments differ, or something was committed since). "
                            "Call bulk_preview again, show the user the new dry run, and "
                            "apply with its preview_id.")
        plan, _, nothing = plan_for(args)
        if nothing:
            raise ToolError(nothing)
        message = " ".join(str(args.get("summary") or "").split()) or None
        try:
            sha = bulk.apply(writable(), plan, message=message)
        except bulk.BulkError as exc:
            raise ToolError(cli_words(str(exc))) from None
        sha7 = sha[:7]
        subject = subprocess.run(["git", "log", "-1", "--format=%s", sha], cwd=root,
                                 capture_output=True, text=True).stdout.strip()
        return (f"{plan.count(plan.changed).capitalize()} changed in one commit {sha7}: "
                f"{subject}. Undo: undo({sha7})")

    def undo_tool(args: dict) -> str:
        from . import history

        sha = str(args.get("sha") or "").strip()
        if not sha:
            raise ToolError("sha is required: the commit to undo")
        try:
            new, subject = history.undo(writable(), sha)
        except history.UndoError as exc:
            raise ToolError(str(exc)) from None
        gitops().push_async()
        return (f"Undone in a new commit {new}: {subject}. "
                f"To bring the change back: undo({new})")

    def no_link(rel: str) -> Path:
        """The file in the folder, refusing a link that leads out of it."""
        target = root / rel
        if target.is_symlink() or (target.parent != root and target.parent.is_symlink()):
            raise ToolError(f"Refused: {rel} is a link to a file elsewhere; only a file "
                            "in the data folder itself may be read or written here.")
        return target

    def head() -> str:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                              text=True).stdout.strip()

    def dirty(rel: str) -> bool:
        """Changes to this file that are not committed (or a file git never saw)."""
        status = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=root,
                                capture_output=True, text=True)
        return status.returncode == 0 and bool(status.stdout.strip())

    def trial(rel: str, content: str) -> tuple[list[str], list[str]]:
        """What `hermitcrm check` says about the extension files now, and with
        `rel` holding `content`, worked out on two scratch copies so the data
        folder is never written until the new text passes."""
        from . import adjust

        found = []
        for new in (None, content):
            with tempfile.TemporaryDirectory(prefix="hermitcrm-adjust-") as tmp:
                scratch = Path(tmp)
                for name in (*WRITABLE, "config.toml"):
                    if (root / name).is_file():
                        shutil.copyfile(root / name, scratch / name)
                if (root / "dashboards").is_dir():
                    (scratch / "dashboards").mkdir()
                    for path in (root / "dashboards").glob("*.toml"):
                        if path.is_file():
                            shutil.copyfile(path, scratch / "dashboards" / path.name)
                if new is not None:
                    (scratch / rel).parent.mkdir(exist_ok=True)
                    (scratch / rel).write_text(new, encoding="utf-8")
                found.append(adjust.all_problems(scratch))
        return found[0], found[1]

    days_field = text("integer", "How many days to cover.")
    list_of_text = {"type": "array", "items": {"type": "string"}}

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
        Tool("adjust_help",
             "Read this first when the user wants to change Hermit itself (Make it "
             "yours): a field, a dashboard, the page layout, many records at once, a "
             "routine, draft templates, the look. Returns a recipe: 'adjust' has the "
             "rules and says which recipe fits; the others are how to make each kind "
             "of change. Writes nothing.",
             schema({"topic": text(description="adjust (the rules, start here) or one "
                                               "of its recipes.",
                                   enum=list(RECIPES))}),
             adjust_help_tool),
        Tool("adjust_read",
             "The current text of a file you may change: fields.toml, layout.toml, "
             "dashboards/<name>.toml, routines.toml, theme.css, messages.toml, "
             "MESSAGING.md (empty text if it does not exist yet), or config.toml's "
             "task_types, outcomes and silent_days. Without a path, lists which of "
             "them exist. Read a file before you write it. Writes nothing.",
             schema({"path": text(description="Relative to the data folder, e.g. "
                                              "fields.toml or dashboards/monday.toml.")}),
             adjust_read_tool),
        Tool("adjust_write",
             "Replace one file you may change (fields.toml, layout.toml, "
             "dashboards/<name>.toml, routines.toml, theme.css, messages.toml, "
             "MESSAGING.md) with new text, following the recipe from adjust_help. The "
             "text is checked as `hermitcrm check` would first: if it has a problem, "
             "nothing is written and the problems come back to fix. A new routine "
             "always arrives paused, and so does one that was on but whose selector, "
             "filters, prompt or other settings you changed; the user turns it on. If "
             "it passes, it is ONE git commit, 'ai: adjust: <summary>', touching only "
             "that file, and the answer gives the commit id for undo. Never put a "
             "password or token in a file.",
             schema({"path": text(description="Relative to the data folder, e.g. "
                                              "fields.toml or dashboards/monday.toml."),
                     "content": text(description="The whole new text of the file."),
                     "summary": text(description='A few words for the commit message, '
                                                 'e.g. "contract renewal field".')},
                    ["path", "content", "summary"]), adjust_write_tool),
        Tool("adjust_config",
             "Change one of the three settings you may change: task_types, outcomes or "
             "silent_days, the way Settings saves them. ONE commit, 'ai: adjust: ...'; "
             "the answer gives the commit id for undo. Every other setting is the "
             "user's, in Settings. A rename of a task type that to-dos use belongs in "
             "Settings too (it renames the to-dos).",
             schema({"key": text(description="task_types, outcomes or silent_days.",
                                 enum=list(CONFIG_KEYS)),
                     "value": {"type": ["array", "integer", "string"],
                               "description": "task_types: a list of names or "
                                              '{"name", "colour"} objects (colours: '
                                              "green, blue, amber, red, violet, grey). "
                                              "outcomes: a list of names, the first is "
                                              "what a reply counts as, the last what "
                                              "silence counts as. silent_days: a whole "
                                              "number of days."}},
                    ["key", "value"]), adjust_config_tool),
        Tool("bulk_preview",
             "The dry run of a change to many records at once (`hermitcrm set`): how "
             "many match, how many would change, and a few before -> after lines. "
             "Writes nothing. ALWAYS show it to the user and wait for a yes before "
             "bulk_apply; the preview_id it returns is required there and only fits "
             "these same arguments while the folder is unchanged. Bodies of "
             "interactions are never changed.",
             schema({"scope": text(description="companies, contacts or interactions.",
                                   enum=["companies", "contacts", "interactions"]),
                     "where": {**list_of_text,
                               "description": 'Filters, all of which must hold, in the '
                                              'list pages\' syntax: "stage=prospect", '
                                              '"country=DE,NL", "fit_score=>70", '
                                              '"next_step=-" (empty).'},
                     "all": text("boolean", "true to change every record of the scope "
                                            "(instead of where)."),
                     "ops": {"type": "object", "description": "What to change: "
                             '{"set": {"field": "value"}, "unset": ["field"], '
                             '"add_tags": ["tag"], "remove_tags": ["tag"], '
                             '"stage": "discovery"} (tags and stage: companies only).'}},
                    ["scope", "ops"]), bulk_preview_tool),
        Tool("bulk_apply",
             "Apply a change to many records that bulk_preview showed and the user "
             "agreed to: pass its preview_id and exactly the same scope, where, all and "
             "ops. Refused if the preview is stale or the arguments differ. ONE commit "
             "('bulk: ...'); the answer gives the commit id for undo.",
             schema({"preview_id": text(description="From bulk_preview."),
                     "scope": text(enum=["companies", "contacts", "interactions"]),
                     "where": {**list_of_text}, "all": text("boolean"),
                     "ops": {"type": "object"},
                     "summary": text(description="Optional commit message; the default "
                                                 "names the change and the count.")},
                    ["preview_id", "scope", "ops"]), bulk_apply_tool),
        Tool("undo",
             "Undo one commit with a new commit that reverses it (git revert): what "
             "adjust_write, adjust_config, bulk_apply or an add_* tool did. Takes the "
             "commit id their answer gave. Refused for a merge, the folder's first "
             "commit or uncommitted changes; undoing the undo brings it back.",
             schema({"sha": text(description="The commit id, e.g. a1b2c3d.")}, ["sha"]),
             undo_tool),
    ]


class ToolError(Exception):
    """A tool was called wrongly. Reported to the model, not to the transport."""


# ------------------------------------------------------------ make it yours

# The files an agent may write without asking (contract 4 of Make it yours,
# history.EXTENSION_FILES), plus one file per dashboard. config.toml is not
# here: three of its keys change through adjust_config, the rest never.
WRITABLE = ("fields.toml", "layout.toml", "routines.toml", "theme.css", "messages.toml",
            "MESSAGING.md")
DASHBOARD_FILE = re.compile(r"^dashboards/[a-z0-9]+(?:-[a-z0-9]+)*\.toml$")
CONFIG_KEYS = ("task_types", "outcomes", "silent_days")   # = adjust.AGENT_CONFIG_KEYS
RECIPES = tuple(t for t in HELP_TOPICS if t == "adjust" or t.startswith("adjust-"))
OPS = ("set", "unset", "add_tags", "remove_tags", "stage")
MAX_FILE = 256 * 1024

# Put in front of a recipe: it is written for an agent with a shell.
MCP_NOTE = """(Over MCP: where this says to edit a file, run `hermitcrm check` and commit, call
adjust_write: it checks and commits for you, and refuses what check would fault.
`config.toml` keys go through adjust_config. `hermitcrm set` is bulk_preview, then
bulk_apply after the user says yes. `hermitcrm undo <sha>` is undo.)"""

# The CLI's flags, as the bulk tools call them.
_CLI_WORDS = [("--where", "where"), ("--all", "all=true"), ("--set", "ops.set"),
              ("--unset", "ops.unset"), ("--add-tag", "ops.add_tags"),
              ("--remove-tag", "ops.remove_tags"), ("--stage", "ops.stage"),
              ("--message", "summary")]


def near(word: str, choices) -> str:
    match = difflib.get_close_matches(str(word), [str(c) for c in choices], n=1, cutoff=0.6)
    return f" (did you mean {match[0]}?)" if match else ""


def extension_path(raw, config: bool = False) -> str:
    """The relative path of a file an agent may write, or a ToolError saying why not."""
    rel = str(raw or "").strip()
    if not rel:
        raise ToolError("path is required, e.g. fields.toml or dashboards/monday.toml")
    parts = rel.replace("\\", "/").split("/")
    if (rel.startswith(("/", "~")) or "\\" in rel or "\x00" in rel or ".." in parts
            or re.match(r"^[A-Za-z]:", rel)):
        raise ToolError(f"Refused: {rel!r} is not a path inside the data folder. Give it "
                        "relative to the folder, e.g. fields.toml or dashboards/monday.toml.")
    if rel in WRITABLE or DASHBOARD_FILE.match(rel) or (config and rel == "config.toml"):
        return rel
    if rel == "config.toml":
        raise ToolError("Refused: config.toml changes only through adjust_config, and "
                        "only its task_types, outcomes and silent_days.")
    if rel.startswith("dashboards/"):
        raise ToolError(f"Refused: {rel}: a dashboard is dashboards/<name>.toml, the name "
                        "in lowercase letters, digits and dashes, e.g. "
                        "dashboards/monday-review.toml.")
    raise ToolError(f"Refused: {rel} is not a file you may write{near(rel, WRITABLE)}. "
                    f"You may write {', '.join(WRITABLE)} and dashboards/<name>.toml; "
                    "config.toml's task_types, outcomes and silent_days through "
                    "adjust_config; records through the add_* tools and bulk_apply.")


def summary_of(raw) -> str:
    """The <what> of `ai: adjust: <what>`: one line, at most 72 characters."""
    what = " ".join(str(raw or "").split())
    if what.lower().startswith("ai: adjust:"):
        what = what[len("ai: adjust:"):].strip()
    if not what:
        raise ToolError("summary is required: a few words on what changed, for the "
                        "commit message (e.g. \"contract renewal field\")")
    return what if len(what) <= 72 else what[:71].rstrip() + "…"


def config_keys_text(config: dict) -> str:
    """The config.toml keys an agent may change, as TOML, with their values now."""
    from .setup import toml_value

    lines = ["# config.toml: only these keys change, through adjust_config."]
    for key in CONFIG_KEYS:
        value = config.get(key)
        lines.append(f"{key} = {toml_value(value if value is not None else [])}")
    return "\n".join(lines) + "\n"


def task_type_rows(value, current: list) -> tuple[list[str], list[str]]:
    """(names, colours) from a list of names or {name, colour} objects. A type
    given without a colour keeps the one it has now (grey for a new one)."""
    from .task_types import PALETTE

    if not isinstance(value, list):
        raise ToolError('task_types must be a list of names or {"name": ..., '
                        '"colour": ...} objects')
    had = {t.name.lower(): t.colour for t in current}
    names, colours = [], []
    for i, entry in enumerate(value, 1):
        entry = {"name": entry} if isinstance(entry, str) else entry
        if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
            raise ToolError(f"task_types entry {i} needs a name")
        name = str(entry["name"])
        colour = str(entry.get("colour") or entry.get("color")
                     or had.get(" ".join(name.split()).lower(), "grey")).strip().lower()
        if colour not in PALETTE:
            raise ToolError(f"task_types entry {i}: colour {colour!r} is not one of "
                            f"{', '.join(PALETTE)}{near(colour, PALETTE)}")
        names.append(name)
        colours.append(colour)
    return names, colours


def arrive_paused(content: str, old: bytes | None) -> tuple[str, list[str]]:
    """routines.toml as it may be written: a routine that was not on before, or
    that was on but now does something else, is set to `paused = true`, with a
    line saying so. Turning one on is the user's, after a preview.

    "Does something else" is any key but `paused` and `title` (the selector,
    filters, prompt, action, channel, days, limit ...) with a different value:
    what the user turned on was that definition, not the name."""
    from . import routines

    try:
        entries = tomllib.loads(content).get("routine", [])
    except tomllib.TOMLDecodeError:
        return content, []  # check reports it, so it is refused anyway

    def definition(entry: dict) -> dict:
        return {k: v for k, v in entry.items() if k not in ("paused", "title")}

    was_on = {}  # name -> the definition the user had turned on
    try:
        for entry in tomllib.loads((old or b"").decode("utf-8")).get("routine", []):
            if isinstance(entry, dict) and entry.get("paused", True) is False:
                was_on[entry.get("name")] = definition(entry)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, AttributeError):
        pass
    notes = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("paused", True) is not False:
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue  # no name (check refuses that)
        now, before = definition(entry), was_on.get(name)
        if before == now:
            continue  # on already, and doing what the user turned on
        changed = sorted(k for k in {*before, *now} if before.get(k) != now.get(k)) \
            if before is not None else []
        try:
            content = routines.with_paused(content, name, True)
        except routines.RoutineError:
            raise ToolError(f"Not written: routine {name} would start on. A new routine "
                            "starts paused: write paused = true for it.") from None
        if changed:
            notes.append(f"Routine {name} was on, but you changed what it does "
                         f"({', '.join(changed)}), so it was paused again "
                         "(paused = true): the user turned on the old version. The "
                         "user previews it and turns it on again under Make it yours, "
                         f"or with `hermitcrm routines on {name}`.")
        else:
            notes.append(f"Routine {name} arrived paused (paused = true): a new routine "
                         "starts paused. The user previews it and turns it on under Make it "
                         f"yours, or with `hermitcrm routines on {name}`.")
    return content, notes


def cli_words(message: str) -> str:
    """A bulk error as the MCP tools would say it: `where`, not `--where`."""
    for flag, word in _CLI_WORDS:
        message = re.sub(re.escape(flag) + r"\b", word, message)
    return message


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
                "for a record to be created or logged. To change Hermit itself "
                "(fields, dashboards, layout, routines, templates, the look, many "
                "records at once), call adjust_help first and follow it: every write "
                "is one commit that undo reverses, a bulk change needs bulk_preview "
                "and the user's yes first, and nothing is ever sent: messages are "
                "drafts."),
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
