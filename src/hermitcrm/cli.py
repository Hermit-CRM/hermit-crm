#!/usr/bin/env python3
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

"""Hermit CRM: command-line entry point.

Thin wrapper around app/store.py (and, lazily, app/pipeline.py and
app/web.py) for scripting and for pasting output into an AI session. See
BRIEF.md section 6 for the exact output formats.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from hermitcrm import __version__, layout, migrations, task_types
from hermitcrm.datafolder import InitError, NotDataFolder, init_folder, resolve_data_dir
from hermitcrm.enrich import EnrichError, Enricher
from hermitcrm.gitops import GitOps
from hermitcrm.models import Channel, Direction
from hermitcrm.store import Store, load_config

COMPANY_FIELD_ORDER = [
    "name", "slug", "website", "linkedin", "country", "source", "stage",
    "stage_changed", "lost_reason", "requalify_on", "value_eur_month",
    "product_oneliner", "next_step", "next_step_due",
    "next_step_status", "next_step_type", "tags", "created", "updated",
]


def _writer(store: Store, root: Path, config: dict):
    """The same write path the web app uses: PIPELINE.md, commit, push."""
    from hermitcrm import pipeline

    gitops = GitOps(root, push_enabled=config["push_enabled"],
                    remote=config.get("remote", "origin"))

    def on_write(message: str) -> None:
        paths = store.take_touched()
        pipeline.write(store)
        gitops.commit(message, [*paths, "PIPELINE.md"])
        gitops.push_async()

    return on_write


def build_store(root: Path) -> Store:
    config = load_config(root)
    store = Store(root, silent_days=config["silent_days"], outcomes=config["outcomes"],
                  task_types=task_types.names(task_types.from_config(config.get("task_types"))))
    store.load()
    return store


LOOPBACK = ("127.0.0.1", "localhost", "::1")


def reachable_address(host: str) -> str:
    """The address to print for a bound host.

    Binding to 0.0.0.0 means "every interface", which is not something you can
    type into a phone. Printing this machine's LAN address instead is the whole
    point of the flag, so the URL on screen is one you can actually open.
    """
    if host not in ("0.0.0.0", "::"):
        return host
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: routed nowhere, sends nothing
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def cmd_serve(root: Path, port: int | None = None, host: str | None = None) -> None:
    from hermitcrm import accesslog
    from hermitcrm.web import create_app
    import uvicorn

    config = load_config(root)
    if port:
        config["port"] = port
    if host:
        config["host"] = host
    host = str(config.get("host") or "127.0.0.1")
    config["start_update_check"] = True  # background thread, never blocks
    app = create_app(root, config)
    shown = reachable_address(host)
    print(f"Hermit CRM {__version__}: {root} on http://{shown}:{config['port']}")
    if host not in LOOPBACK:
        print("  Reachable from the network. Hermit CRM has no password: anyone who "
              "can\n  reach this port can read and write your CRM. Use it on a "
              "network you trust,\n  or put it on a private one (Tailscale, "
              "WireGuard) rather than a public Wi-Fi.", file=sys.stderr)
    uvicorn.run(app, host=host, port=int(config["port"]), log_config=accesslog.log_config())


def cmd_init(target: Path, demo: bool = False) -> tuple[str, int]:
    try:
        path = init_folder(target, demo=demo)
    except InitError as exc:
        return (str(exc), 2)
    lines = [f"Created a Hermit CRM data folder in {path}" + (" with demo data." if demo else "."),
             f"Start the web app: hermitcrm --data {path} serve"]
    return ("\n".join(lines), 0)


def cmd_sample(store: Store, action: str) -> tuple[str, int]:
    from hermitcrm import sample

    if action == "add":
        try:
            company = sample.add(store)
        except sample.SampleError as exc:
            return (str(exc), 1)
        return (f"Added the sample account {company.name} (companies/{company.slug}). "
                "It is made up; `hermitcrm sample remove` deletes it again.", 0)
    removed = sample.remove(store)
    if not removed:
        return ("No sample account to remove.", 0)
    return ("Removed the sample account: " + ", ".join(c.name for c in removed)
            + ". It stays in the git history.", 0)


# -------------------------------------------------------------------- setup


def _yes(answer: str, default: bool) -> bool:
    answer = (answer or "").strip().lower()
    if not answer:
        return default
    return answer[0] in ("y", "j", "o")


def cmd_setup(root: Path, ask=input, ask_secret=None, say=print, runner=subprocess.run,
              platform: str | None = None, open_mailbox=None, push=None,
              fetch=None) -> int:
    """The three setup questions (You, BCC, Backup) plus the optional calendar."""
    import getpass

    from hermitcrm import secrets
    from hermitcrm import setup as st

    ask_secret = ask_secret or getpass.getpass
    platform = platform or sys.platform
    root = Path(root)
    # Each answer is committed as it is saved, as the web app's Settings do; a
    # later push takes them along.
    gitops = GitOps(root, push_enabled=False)

    def saved() -> None:
        st.commit_config(root, gitops.commit)

    def prompt(text: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        value = ask(f"{text}{suffix}: ").strip()
        return value or default

    try:
        config = load_config(root)
        say("\n1/3 You")
        for _ in range(3):
            name = prompt("Your name", str(config.get("owner_name") or ""))
            current = ", ".join(config.get("my_addresses") or []) or str(
                config.get("owner_email") or "")
            addresses = prompt("Addresses you send mail from (comma-separated)", current)
            result = st.save_you(root, name, addresses)
            saved()
            say(result.text())
            if result.ok:
                break
        config = load_config(root)

        say("\n2/3 BCC capture: mail you BCC or forward is logged automatically.")
        if _yes(ask("Set up BCC capture now? [y/N]: "), False):
            owner = str(config.get("owner_email") or "")
            address = prompt("BCC address", str(config.get("bcc_address") or "")
                             or st.suggest_bcc_address(owner))
            host = prompt("IMAP server", st.imap_host_for(address) or st.imap_host_for(owner))
            say("Create an app password (for Gmail: https://myaccount.google.com/apppasswords).")
            password = ask_secret("App password (input hidden, empty keeps the stored one): ")
            keychain = False
            store = secrets.os_store(platform, runner=runner) if password else None
            if store:
                keychain = _yes(ask(f"Store it in {secrets.STORE_LABELS[store]}? [Y/n]: "),
                                True)
            elif password and not platform.startswith("win"):
                say("No system keyring found (on Linux: install libsecret-tools and run "
                    "GNOME Keyring or KWallet); the password goes to .secrets.toml (mode 600).")
            result = st.save_bcc(root, address, host, password, use_keychain=keychain,
                                 runner=runner, platform=platform)
            saved()
            say(result.text())
            if result.ok and _yes(ask("Test the connection now (dry run)? [Y/n]: "), True):
                say(st.test_bcc(root, open_mailbox=open_mailbox).text())
        else:
            say("Skipped; rerun `hermitcrm setup` or open /setup in the web app.")

        say("\n3/3 Online copy (optional): push the data folder to a private git remote.\n"
            "Local backups start with `hermitcrm schedule install` or Settings > Backup.")
        url = ask("Git remote URL (empty to skip): ").strip()
        if url:
            warning = st.private_warning(url)
            if warning:
                say("WARNING: " + warning)
            result = st.save_backup(root, url, runner=runner, push=push)
            saved()
            say("; ".join(list(result.errors.values()) + result.messages))
        else:
            say("Skipped.")

        say("\nOptional: calendar import from a secret ICS address.")
        if _yes(ask("Add a calendar feed? [y/N]: "), False):
            ics = ask_secret("Secret ICS address (input hidden): ")
            say(st.save_calendar(root, ics, fetch=fetch).text())
    except (EOFError, KeyboardInterrupt):
        say("\nSetup stopped; rerun it any time with `hermitcrm setup`.")
        return 1

    state = st.setup_state(root, runner=runner, platform=platform)
    say("\nSetup: " + ", ".join(f"{k} {'done' if v else 'pending'}" for k, v in state.items()))
    return 0


def cmd_schedule(root: Path, action: str, at: str = "07:00", serve: bool = False,
                 home: Path | None = None, runner=subprocess.run,
                 platform: str | None = None, env: dict | None = None,
                 backup: bool = True, backup_every: int = 5) -> int:
    from hermitcrm import schedule

    ctx = schedule.Context(data_dir=root, home=home or Path.home(),
                           platform=platform or schedule.sys.platform, runner=runner, env=env)
    try:
        if action == "install":
            lines = schedule.install(ctx, at=at, serve=serve, backup=backup,
                                     backup_every=backup_every)
        elif action == "remove":
            lines = schedule.remove(ctx)
        else:
            lines = schedule.status(ctx)["lines"]
    except schedule.ScheduleError as exc:
        print(exc, file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0


def cmd_backup(root: Path, args, home: Path | None = None) -> int:
    """run / status / list / restore; see hermitcrm/backup.py."""
    from hermitcrm import backup

    config = load_config(root)
    action = args.action or "run"
    if action == "guard":
        from hermitcrm import guard

        try:
            added = guard.write(root)
        except guard.GuardError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(f"added {len(added)} deny rule(s) to {guard.SETTINGS}" if added
              else f"{guard.SETTINGS} already blocks all {len(guard.DENY)} commands")
        return 0
    if action == "status":
        state = backup.status(root, config, home=home)
        print("\n".join(state["lines"]))
        if state["summary"]:
            print(f"{state['level']}: {state['summary']}")
        return 0 if state["level"] == "ok" else 1
    if action == "list":
        try:
            text, code = backup.list_versions(root, config, path=args.path, limit=args.limit,
                                              home=home)
        except backup.BackupError as exc:
            text, code = str(exc), 2
        print(text, file=sys.stderr if code == 2 else sys.stdout)
        return code
    if action == "restore":
        outcome, commit = backup.restore(root, args.ref, args.paths, config=config,
                                         apply=args.apply, home=home)
        print("\n".join(outcome.lines),
              file=sys.stderr if outcome.code == 2 else sys.stdout)
        if commit:
            try:
                migrations.ensure_current(root)  # an older version may be an older format
                store = build_store(root)
                gitops = GitOps(root, push_enabled=config["push_enabled"],
                                remote=config.get("remote", "origin"))
                print(cmd_rebuild(store, gitops))
                _reload_server(config)
                after = backup.run(root, config, home=home, push_remote=False)
                if after.code != 2:  # so the restore itself is in the backup at once
                    print("backed up the restored state")
            except migrations.FormatTooNew as exc:
                print(exc, file=sys.stderr)
        return outcome.code
    outcome = backup.run(root, config, home=home)
    if outcome.changed or outcome.warnings or outcome.code or not args.quiet:
        stamp = f"{datetime.now():%Y-%m-%d %H:%M}"
        for line in outcome.lines:
            print(f"{stamp} {line}", file=sys.stderr if outcome.code == 2 else sys.stdout)
        for line in outcome.warnings:
            print(f"{stamp} WARNING: {line}", file=sys.stderr)
    return outcome.code


# ---------------------------------------------------------------------- mcp


def cmd_mcp(root: Path, store: Store, stdin=None, stdout=None) -> int:
    """Speak MCP on stdin/stdout until the client hangs up.

    Nothing may be printed to stdout but protocol messages, so this returns
    rather than prints, and anything worth saying goes to stderr.
    """
    from hermitcrm import mcp

    return mcp.serve(root, store, stdin=stdin, stdout=stdout)


# -------------------------------------------------------------------- brief


def cmd_brief(root: Path, store: Store, days: int = 7) -> str:
    """Briefs for the meetings the last calendar import found."""
    from hermitcrm import bcc, brief

    inbox = bcc.Inbox(root)
    return brief.render(brief.briefs(store, inbox, days=days), store.today(), days)


# ---------------------------------------------------------------- followups


def cmd_followups(store: Store, config: dict, reply_after: int | None = None,
                  nudge_after: int | None = None) -> str:
    """The follow-up radar as text; the same rows the home page shows."""
    from hermitcrm import followups

    rows = followups.radar(
        store,
        reply_after=(config["followup_reply_days"] if reply_after is None else reply_after),
        nudge_after=(config["followup_nudge_days"] if nudge_after is None else nudge_after),
    )
    return followups.render(rows)


# ------------------------------------------------------------------- digest


def cmd_digest(store: Store, days: int, now: datetime | None = None) -> str:
    now = now or store.now()
    cutoff = now - timedelta(days=days)

    pairs = []
    for company in store.companies.values():
        for it in company.interactions:
            if it.date and it.date >= cutoff:
                pairs.append((company, it))
    pairs.sort(key=lambda pair: pair[1].date)

    counts = {"email": {"out": 0, "in": 0},
              "linkedin": {"out": 0, "in": 0},
              "call": {"out": 0, "in": 0},
              "meeting": {"out": 0, "in": 0}}
    companies_touched: set[str] = set()
    blocks = []

    for company, it in pairs:
        header = (
            f"{it.date:%Y-%m-%d %H:%M} | {it.label} | "
            f"{company.slug} / {it.contact_label} | {it.subject or '-'} | "
            f"outcome: {it.outcome or '-'}"
        )
        preview = " ".join(it.body.split())[:150]
        blocks.append(f"{header}\n{preview}")
        if it.channel in counts and it.direction in ("out", "in"):
            counts[it.channel][it.direction] += 1
        if it.is_touch:  # a note is listed, but it is not contact made
            companies_touched.add(company.slug)

    notes = sum(1 for _, it in pairs if it.is_note)
    n = len(pairs) - notes
    if n == 0:
        summary = "Summary: 0 interactions | companies touched: 0"
    else:
        chan_parts = []
        for ch in ("email", "linkedin", "call", "meeting"):
            o, i = counts[ch]["out"], counts[ch]["in"]
            if o or i:
                chan_parts.append(f"{ch}: {o} out / {i} in")
        summary = f"Summary: {n} interactions"
        if chan_parts:
            summary += " | " + " | ".join(chan_parts)
        summary += f" | companies touched: {len(companies_touched)}"
    if notes:
        summary += f" | notes: {notes}"

    if blocks:
        return "\n\n".join(blocks) + "\n\n" + summary
    return summary


# ---------------------------------------------------------------------- show


def _company_field_text(company, key: str) -> str:
    if key == "tags":
        return ", ".join(company.tags)
    value = getattr(company, key)
    if value is None:
        return ""
    if key in ("stage_changed", "next_step_due", "requalify_on"):
        return f"{value:%Y-%m-%d}"
    if key in ("created", "updated"):
        return f"{value:%Y-%m-%dT%H:%M}"
    return str(value)


def _interaction_header(it, contact_label: str) -> str:
    return (
        f"{it.date:%Y-%m-%d %H:%M} | {it.label} | "
        f"{contact_label} | {it.subject or '-'} | {it.outcome or '-'}"
    )


def cmd_show(store: Store, slug: str, bodies: int = 3, all_bodies: bool = False) -> str:
    company = store.get(slug)
    if company is None:
        return f"unknown company: {slug}"

    lines: list[str] = []
    for key in COMPANY_FIELD_ORDER:
        text = _company_field_text(company, key)
        if key == "next_step_type" and not text:
            continue  # as in the file: only there once a type is set
        lines.append(f"{key}: {text}" if text else f"{key}:")

    lines.append("")
    if company.notes:
        lines.append(company.notes.rstrip("\n"))
    lines.append("")

    lines.append("Contacts:")
    for contact in sorted(company.contacts.values(), key=lambda c: c.name.lower()):
        lines.append(
            f"{contact.slug} | {contact.title or '-'} | {contact.email or '-'} | "
            f"{contact.role or '-'}"
        )

    lines.append("")
    lines.append("Interactions:")
    interactions = sorted(
        company.interactions, key=lambda i: (i.date or datetime.min), reverse=True
    )
    for it in interactions:
        lines.append(_interaction_header(it, it.contact_label))

    n_bodies = len(interactions) if all_bodies else min(bodies, len(interactions))
    if n_bodies > 0:
        for it in interactions[:n_bodies]:
            lines.append("")
            lines.append(f"--- {_interaction_header(it, it.contact_label)}")
            lines.append(it.body.rstrip("\n"))

    return "\n".join(lines)


# ------------------------------------------------------------------ rebuild


def cmd_rebuild(store: Store, gitops: GitOps) -> str:
    from hermitcrm import pipeline

    store.load()
    changed = pipeline.write(store)
    if changed:
        gitops.commit("pipeline: rebuild", ["PIPELINE.md"])
    n = len(store.companies)
    problems = len(store.problems)
    status = "rebuilt and committed" if changed else "already up to date"
    return f"PIPELINE.md {status} ({n} companies, {problems} problems)"


# -------------------------------------------------------------------- check


def cmd_check(store: Store) -> tuple[str, int]:
    store.load()
    # Since format 7 a contact has no notes body: what you know about a person
    # is a note interaction. A body written by hand is shown, not lost.
    stray = [f"companies/{c.slug}/contacts/{cs}.md: has a notes body; the app no longer "
             f"shows it (log it as a note on the contact instead)"
             for c in store.companies.values() for cs, ct in c.contacts.items()
             if ct.notes.strip()]
    # The files an agent may write to adjust Hermit: a problem in one fails
    # the check like a broken record does, with a line saying where.
    extension = layout.validate(store.root)
    if not store.problems and not extension:
        n_companies = len(store.companies)
        n_contacts = sum(len(c.contacts) for c in store.companies.values())
        n_interactions = sum(len(c.interactions) for c in store.companies.values())
        return (
            "\n".join(stray + [
                f"OK: {n_companies} companies, {n_contacts} contacts, "
                f"{n_interactions} interactions, no problems"]),
            0,
        )
    lines = [f"{p.path}: {p.message}" for p in store.problems] + extension
    return ("\n".join(lines), 1)


# ------------------------------------------------------------------- import


def parse_map_args(pairs: list[str] | None) -> dict[str, str]:
    """["Header=field", ...] -> {"Header": "field"}; the last "=" splits."""
    mapping = {}
    for pair in pairs or []:
        header, sep, target = pair.rpartition("=")
        if not sep or not header.strip():
            raise ValueError(f"--map expects \"Header=field\", got {pair!r}")
        mapping[header.strip()] = target.strip()
    return mapping


# ---------------------------------------------------------------------- add

# The optional `hermitcrm add` flags, as one set: each subcommand defines only
# its own, so filtering argparse's namespace by this leaves out what was not
# asked for (every one of them defaults to None).
NAMED_FIELDS = {
    "website", "linkedin", "country", "source", "stage", "lost_reason",
    "requalify_on", "value_eur_month", "product_oneliner", "next_step",
    "next_step_due", "next_step_type", "tags", "notes",
    "title", "email", "phone", "role",
    "contact", "subject", "date", "outcome",
}


def create_fields(method) -> set[str]:
    """The field names one of the store's create_* methods accepts.

    Read from the signature rather than listed here, so `--set` keeps working
    when the store gains a field and the CLI is not touched.
    """
    import inspect

    return {name for name in inspect.signature(method).parameters
            if name not in ("self", "company_slug")}


def _custom_defs(root: Path) -> list:
    """The folder's own field definitions; none when the file is unreadable."""
    from hermitcrm import fields as custom_fields
    try:
        return custom_fields.load(root)
    except custom_fields.FieldError:
        return []


def parse_set_args(pairs: list[str], allowed: set[str], defs: list | None = None) -> dict:
    """`--set field=value` pairs, checked against the fields the store takes.

    A key the store does not have may still be one the folder defined itself;
    those are coerced by their own definition and handed over as `custom`.
    """
    allowed = set(allowed) - {"custom"}  # transport, not something to type
    by_key = {d.key: d for d in (defs or [])}
    values: dict[str, str] = {}
    custom: dict = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        key = key.strip().replace("-", "_")
        if not sep or not key:
            raise ValueError(f"--set wants field=value, got {pair!r}")
        if key in by_key:
            try:
                custom[key] = by_key[key].coerce(value)
            except ValueError as exc:
                raise ValueError(str(exc)) from None
        elif key in allowed:
            values[key] = value
        else:
            known = sorted(set(allowed) | set(by_key))
            raise ValueError(f"unknown field {key!r}; fields: " + ", ".join(known))
    if custom:
        values["custom"] = custom
    return values


def read_body(text: str, stdin=None) -> str:
    """`--body -` reads the body from stdin, for text with newlines in it."""
    if text == "-":
        return (stdin or sys.stdin).read()
    return text


def cmd_add(store: Store, args, stdin=None) -> tuple[str, int]:
    """Create one company, contact or interaction: the write the web app does.

    Every value arrives as a string and the store coerces and validates it,
    exactly as it does for a submitted form, so the CLI stays a thin binding
    and the two front doors cannot drift apart.
    """
    from hermitcrm.models import ValidationError, split_name

    def defs(scope: str) -> list:
        return [d for d in _custom_defs(store.root) if d.applies_to == scope]

    named = {k: v for k, v in vars(args).items() if k in NAMED_FIELDS and v is not None}
    try:
        if args.what == "company":
            fields = create_fields(store.create_company)
            values = {**named, **parse_set_args(args.set, fields, defs("company")),
                      "name": args.name}
            company = store.create_company(**values)
            return (f"company {company.slug} created: "
                    f"companies/{company.slug}/company.md", 0)

        if args.what == "contact":
            fields = create_fields(store.create_contact)
            first, last = split_name(args.name)
            values = {"first_name": first, "last_name": last, **named,
                      **parse_set_args(args.set, fields, defs("contact"))}
            contact = store.create_contact(args.company, **values)
            return (f"contact {contact.slug} created: "
                    f"companies/{args.company}/contacts/{contact.slug}.md", 0)

        fields = create_fields(store.create_interaction)
        values = {**named, **parse_set_args(args.set, fields, defs("interaction")),
                  "channel": args.channel, "direction": args.direction,
                  "body": read_body(args.body, stdin)}
        it = store.create_interaction(args.company, **values)
        return (f"interaction {it.id} created: "
                f"companies/{args.company}/interactions/{it.id}.md", 0)
    except ValidationError as exc:
        return ("could not create: " +
                "; ".join(f"{k}: {v}" for k, v in exc.errors.items()), 2)
    except ValueError as exc:  # a bad --set pair
        return (str(exc), 2)


def cmd_import(store: Store, path: Path, apply: bool = False, mode: str | None = None,
               mapping: dict | None = None) -> str:
    from hermitcrm.importer import apply_import, decode_upload, plan_import

    plan = plan_import(store, decode_upload(path.read_bytes()), mode=mode,
                       mapping=mapping, defs=_custom_defs(store.root))
    lines = [f"Mode: {plan.mode} | columns: " +
             ", ".join(f"{h} -> {t}" for h, t in plan.mapping.items()),
             plan.summary]
    for r in plan.rows:
        detail = r.reason if r.action != "create" else ", ".join(
            f"{k}={v}" for k, v in r.fields.items())
        contact = ""
        if r.contact:
            contact = f" | contact {r.contact['first_name']} {r.contact['last_name']}".rstrip() + \
                f" ({r.contact_action})"
            if r.contact_fields:
                contact += " fills " + ", ".join(sorted(r.contact_fields))
        lines.append(f"{r.row}: {r.name or '(empty)'} | {r.action} | {detail}{contact}")
        lines += [f"    warning: {w}" for w in r.warnings]
    if apply:
        counts = apply_import(store, plan)
        line = (f"Imported: {counts['created']} created, {counts['updated']} updated, "
                f"{counts['contacts']} contacts")
        if "contacts_updated" in counts:
            line += f", {counts['contacts_updated']} contacts updated"
        lines.append(f"{line}, {counts['skipped']} skipped, {counts['failed']} failed")
    else:
        lines.append("Dry run; add --apply to write.")
    return "\n".join(lines)


# ------------------------------------------------------------------- enrich


def cmd_enrich(store: Store, enricher: Enricher, slug: str, contact: str = "",
               apply: bool = False) -> tuple[str, int]:
    company = store.get(slug)
    if company is None:
        return (f"unknown company {slug!r}", 1)
    target = None
    if contact:
        target = company.contacts.get(contact)
        if target is None:
            return (f"unknown contact {contact!r} for {slug!r}", 1)
    try:
        defs = _custom_defs(store.root)
        proposal = (enricher.propose_contact(company, target,
                                             [d for d in defs if d.applies_to == "contact"])
                    if target else
                    enricher.propose_company(company,
                                             [d for d in defs if d.applies_to == "company"]))
    except EnrichError as exc:
        return (str(exc), 1)
    if not proposal.missing:
        return ("nothing to enrich: every field is set", 0)
    lines = [f"{k}: {v}" for k, v in proposal.fields.items()]
    unfound = [k for k in proposal.missing if k not in proposal.fields]
    if unfound:
        lines.append("not found: " + ", ".join(unfound))
    if proposal.notes:
        lines.append(f"notes: {proposal.notes}")
    for s in proposal.sources:
        lines.append(f"source: {s}")
    if apply and proposal.fields:
        if target:
            store.update_contact(slug, contact,
                                 message=f"ai: contact {slug}/{contact} enriched",
                                 **proposal.fields)
        else:
            store.update_company(slug, message=f"ai: company {slug} enriched",
                                 **proposal.fields)
        lines.append("applied: " + ", ".join(proposal.fields))
    elif proposal.fields:
        lines.append("Dry run; add --apply to write.")
    return ("\n".join(lines), 0)


def cmd_fetch(store: Store, slug: str, url: str = "", apply: bool = False,
              fetcher=None) -> tuple[str, int]:
    """Free enrichment from the website or LinkedIn page (no AI)."""
    from hermitcrm import scrape

    company = store.get(slug)
    if company is None:
        return (f"unknown company {slug!r}", 1)
    url = url or company.website or company.linkedin
    if not url:
        return ("no URL: pass --url or set website/linkedin first", 1)
    try:
        proposal = scrape.propose_from_url(company, url, fetcher=fetcher or scrape.fetch)
    except scrape.ScrapeError as exc:
        return (str(exc), 1)
    if not proposal.missing:
        return ("nothing to enrich: every field is set", 0)
    lines = [f"{k}: {v}" for k, v in proposal.fields.items()]
    unfound = [k for k in proposal.missing if k not in proposal.fields]
    if unfound:
        lines.append("not found: " + ", ".join(unfound))
    if proposal.notes:
        lines.append(f"notes: {proposal.notes}")
    if apply and proposal.fields:
        store.update_company(slug, message=f"company: {slug} fetched from {url}",
                             **proposal.fields)
        lines.append("applied: " + ", ".join(proposal.fields))
    elif proposal.fields:
        lines.append("Dry run; add --apply to write.")
    return ("\n".join(lines), 0)


def cmd_bcc(store: Store, root: Path, config: dict, apply: bool = False,
            eml: list[Path] | tuple = (), open_mailbox=None) -> tuple[str, int]:
    """Import mails BCC'd or forwarded to the tracking address (no AI)."""
    from hermitcrm import bcc

    settings = bcc.settings_from_config(config)
    inbox = bcc.Inbox(root)
    try:
        if eml:
            result = bcc.import_mails(store, inbox, [Path(p).read_bytes() for p in eml],
                                      settings, apply=apply)
        else:
            result = bcc.run_bcc(store, inbox, settings, apply,
                                 open_mailbox or (lambda: bcc.open_gmail(settings, root)))
    except bcc.BccError as exc:
        return (f"BCC import failed: {exc}", 1)
    lines = result.lines + [result.summary()]
    if not apply:
        lines.append("Dry run; add --apply to write and mark the mails read.")
    return ("\n".join(lines), 0)


# ------------------------------------------------------------ backfill-history


_LOG_HEADER = re.compile(r"^([0-9a-f]{40}) (\d{4}-\d{2}-\d{2})$")


def _git_runner(root: Path):
    def run(args: list[str]) -> str:
        result = subprocess.run(["git"] + args, cwd=root, capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else ""
    return run


def _front_matter_value(text: str, key: str) -> str:
    """`key: value` from a file's front matter only (never the notes body)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith(f"{key}:"):
            return line[len(key) + 1:].strip().strip("'\"")
    return ""


def history_from_git(company, git_log, git_show):
    """Reconstruct a company's stage history from the commits of its company.md.

    `git_log(args)` and `git_show(args)` run git and return stdout (the seams
    tests replace). Commits come from `git log --follow --name-only`, so a
    renamed file is read under its old path. Each version's `stage:` line
    becomes a transition dated by its commit; the first version's stage is the
    entry from "" dated `created` (or the first commit, when that is earlier). A working copy whose
    stage differs from the last commit adds one entry dated `stage_changed`.
    """
    from hermitcrm.models import REASON_STAGES, Stage, StageChange

    path = f"companies/{company.slug}/company.md"
    out = git_log(["log", "--follow", "--name-only", "--format=%H %cs", "--", path])
    commits, current = [], None
    for line in out.splitlines():
        match = _LOG_HEADER.match(line.strip())
        if match:
            current = [match.group(1), date.fromisoformat(match.group(2)), path]
            commits.append(current)
        elif line.strip() and current is not None:
            current[2] = line.strip()
    if not commits:  # never committed: nothing to reconstruct
        return []
    commits.reverse()  # oldest first

    allowed = {s.value for s in Stage}
    history: list = []
    stage = ""
    for sha, when, file_path in commits:
        text = git_show(["show", f"{sha}:{file_path}"])
        new_stage = _front_matter_value(text, "stage")
        if new_stage not in allowed or new_stage == stage:
            continue
        reason = _front_matter_value(text, "lost_reason") if new_stage in REASON_STAGES else ""
        if not history and company.created:
            when = min(company.created.date(), when)
        history.append(StageChange(when, stage, new_stage, reason))
        stage = new_stage
    if company.stage != stage:
        when = company.stage_changed or (company.created.date() if company.created else None)
        if when is not None:
            reason = company.lost_reason if company.stage in REASON_STAGES else ""
            history.append(StageChange(when, stage, company.stage, reason))
    return history


def cmd_backfill_history(store: Store, apply: bool = False, git_log=None,
                         git_show=None) -> str:
    """Fill stage_history from git for every company that has none; one commit."""
    git_log = git_log or _git_runner(store.root)
    git_show = git_show or git_log
    plans = []
    for company in sorted(store.companies.values(), key=lambda c: c.slug):
        if company.stage_history:
            continue
        history = history_from_git(company, git_log, git_show)
        if history:
            plans.append((company.slug, history))

    lines = []
    for slug, history in plans:
        steps = " -> ".join([history[0].from_stage or "start"] + [e.to_stage for e in history])
        lines.append(f"{slug} | {len(history)} entries | {steps} | "
                     f"{history[0].date:%Y-%m-%d} to {history[-1].date:%Y-%m-%d}")
    skipped = sum(1 for c in store.companies.values() if c.stage_history)
    summary = (f"{len(plans)} companies to backfill, {skipped} already have a history, "
               f"{len(store.companies) - len(plans) - skipped} without git history")
    if apply and plans:
        with store.batch(f"ai: backfill stage history for {len(plans)} companies"):
            for slug, history in plans:
                store.backfill_stage_history(slug, history)
        summary += " | applied in one commit"
    elif plans:
        summary += " | dry run, add --apply to write"
    return "\n".join(lines + [summary])


# --------------------------------------------------------------------- report


def cmd_report(store: Store, days: int | None = None, start: date | None = None,
               end: date | None = None, md: bool = False, window_days: int = 14,
               today: date | None = None) -> str:
    """The Reports page as text: `--days N` ends today, `--from/--to` is custom,
    neither means the last 30 days."""
    from hermitcrm import reports

    today = today or store.today()
    if start or end:
        period = reports.period_for("custom", today, start, end)
    else:
        period = reports.period_for("custom", today, today - timedelta(days=(days or 30) - 1),
                                    today)
    return reports.render_text(reports.build(store, period, today, window_days), md=md)


# ------------------------------------------------------------ calendar


def cmd_calendar(store: Store, root: Path, config: dict, apply: bool = False,
                 ics: list[Path] | tuple = (), fetch=None, resolve=None,
                 quiet_if_unconfigured: bool = False) -> tuple[str, int]:
    """Import past meetings from the secret ICS feed, or from .ics files (no AI)."""
    from hermitcrm import bcc, calendar_sync

    settings = calendar_sync.settings_from_config(config)
    inbox = bcc.Inbox(root)
    try:
        if ics:
            events = []
            for path in ics:
                events += calendar_sync.parse_ics(
                    Path(path).read_text(encoding="utf-8", errors="replace"))
            result = calendar_sync.import_events(store, inbox, events, settings,
                                                 store.now(), apply)
        else:
            if fetch is None:
                url = (resolve or (lambda: calendar_sync.resolve_url(settings, root)))()
                if not url:
                    if quiet_if_unconfigured:
                        return ("Calendar import skipped: no calendar URL configured", 0)
                    return (f"Calendar import failed: {calendar_sync.setup_hint(settings)}", 1)
                fetch = lambda: calendar_sync.fetch_ics(url)  # noqa: E731
            result = calendar_sync.run_calendar(store, inbox, settings, apply, fetch)
    except (calendar_sync.CalendarError, OSError) as exc:
        return (f"Calendar import failed: {exc}", 1)
    lines = result.lines + [result.summary()]
    if not apply:
        lines.append("Dry run; add --apply to write.")
    return ("\n".join(lines), 0)


def cmd_sync(store: Store, root: Path, config: dict, apply: bool = False,
             open_mailbox=None, fetch=None, resolve=None) -> tuple[str, int]:
    """BCC import, then calendar import (skipped quietly when not set up)."""
    bcc_text, bcc_code = cmd_bcc(store, root, config, apply=apply, open_mailbox=open_mailbox)
    cal_text, cal_code = cmd_calendar(store, root, config, apply=apply, fetch=fetch,
                                      resolve=resolve, quiet_if_unconfigured=True)
    return (f"== BCC ==\n{bcc_text}\n\n== Calendar ==\n{cal_text}", max(bcc_code, cal_code))


def _reload_server(config: dict) -> None:
    """Best effort: tell a running web app to re-read the files."""
    import urllib.request

    url = f"http://127.0.0.1:{config.get('port', 8765)}/reload"
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST"),
                               timeout=3)
    except Exception:
        pass


# ---------------------------------------------------------------------- cli


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermitcrm", description="Hermit CRM: a CRM that is a folder of Markdown files in git")
    parser.add_argument("--version", action="version", version=f"hermitcrm {__version__}")
    parser.add_argument("--data", metavar="DIR", default=None,
                        help="the data folder (default: $HERMITCRM_DATA, then the current "
                             "directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="start the web app on 127.0.0.1")
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--host", default=None,
                         help="address to bind (default 127.0.0.1); 0.0.0.0 reaches "
                              "your phone over the network, with no password on it")

    p_init = sub.add_parser("init", help="create a new data folder (a git repo)")
    p_init.add_argument("dir", type=Path)
    p_init.add_argument("--demo", action="store_true", help="add eight fictional companies")
    p_init.add_argument("--no-setup", action="store_true",
                        help="skip the setup questions (also skipped without a terminal)")

    sub.add_parser("setup", help="ask the setup questions again (you, BCC, backup)")

    p_doctor = sub.add_parser("doctor", help="check the installation (ok/warn/fail per line)")
    p_doctor.add_argument("--online", action="store_true", help="also try the IMAP login")

    p_sched = sub.add_parser("schedule", help="run sync daily (launchd, systemd or schtasks)")
    p_sched.add_argument("action", choices=["install", "remove", "status"])
    p_sched.add_argument("--at", default="07:00", metavar="HH:MM",
                         help="time of the daily sync --apply (default 07:00)")
    p_sched.add_argument("--serve", action="store_true",
                         help="also keep the web app running (install only)")
    p_sched.add_argument("--backup-every", type=int, default=5, metavar="MIN",
                         help="minutes between backups (default 5; install only)")
    p_sched.add_argument("--no-backup", action="store_true",
                         help="do not schedule the backup job (install only)")

    p_backup = sub.add_parser("backup", help="back up to a repository that only grows; "
                              "list and restore versions")
    b_sub = p_backup.add_subparsers(dest="action")
    b_run = b_sub.add_parser("run", help="one backup now (the default; what the job runs)")
    b_run.add_argument("--quiet", action="store_true",
                       help="print nothing when there was nothing new (for the job's log)")
    b_sub.add_parser("status", help="where the backup is, its size and the last run")
    b_list = b_sub.add_parser("list", help="versions in the backup, newest first")
    b_list.add_argument("path", nargs="?", default="",
                        help="only versions that touch this file or folder")
    b_list.add_argument("-n", type=int, default=20, dest="limit", help="how many (default 20)")
    b_restore = b_sub.add_parser("restore", help="put files back as they were in a version")
    b_restore.add_argument("ref", help="a version id from hermitcrm backup list")
    b_restore.add_argument("paths", nargs="*",
                           help="files or folders to restore (default: everything)")
    b_restore.add_argument("--apply", action="store_true")
    b_sub.add_parser("guard", help="block history-rewriting git commands for Claude Code "
                     "(.claude/settings.json; new folders have it)")
    p_backup.set_defaults(action="run", quiet=False)

    p_migrate = sub.add_parser("migrate", help="upgrade the data format (runs automatically)")
    p_migrate.add_argument("--dry-run", action="store_true",
                           help="list the files that would change")

    sub.add_parser("mcp", help="serve this folder to AI clients over MCP (stdio)")

    p_brief = sub.add_parser("brief", help="what you need before each upcoming meeting")
    p_brief.add_argument("--days", type=int, default=7,
                         help="how far ahead to look (default 7)")

    p_followups = sub.add_parser("followups",
                                 help="threads you owe a reply, and ones you are waiting on")
    p_followups.add_argument("--reply-after", type=int, default=None,
                             help="days before an unanswered inbound message counts")
    p_followups.add_argument("--nudge-after", type=int, default=None,
                             help="days before an unanswered outbound message counts")

    p_digest = sub.add_parser("digest", help="recent interactions, oldest first")
    p_digest.add_argument("--days", type=int, default=7)

    p_show = sub.add_parser("show", help="one company in full")
    p_show.add_argument("slug")
    p_show.add_argument("--bodies", type=int, default=3)
    p_show.add_argument("--all", action="store_true", dest="all_bodies")

    sub.add_parser("rebuild", help="rebuild the index and PIPELINE.md")
    sub.add_parser("check", help="validate every file")

    p_sample = sub.add_parser("sample", help="add or remove the made-up sample account")
    p_sample.add_argument("action", choices=["add", "remove"])

    p_add = sub.add_parser("add", help="create one company, contact or interaction")
    add_sub = p_add.add_subparsers(dest="what", required=True)

    p_add_co = add_sub.add_parser("company", help="create a company (prints its slug)")
    p_add_co.add_argument("name", help='the company name, e.g. "Acme BV"')
    for flag in ("--website", "--linkedin", "--country", "--source", "--stage",
                 "--lost-reason", "--requalify-on", "--value-eur-month",
                 "--product-oneliner", "--next-step", "--next-step-due",
                 "--next-step-type", "--tags", "--notes"):
        p_add_co.add_argument(flag, default=None)

    p_add_ct = add_sub.add_parser("contact", help="create a contact under a company")
    p_add_ct.add_argument("company", help="the company slug")
    p_add_ct.add_argument("name", help='the full name, e.g. "Jane van Doe"')
    for flag in ("--title", "--email", "--phone", "--linkedin", "--role"):
        p_add_ct.add_argument(flag, default=None)
    p_add_ct.add_argument("--notes", default=None,
                          help="logged as a note interaction on the new contact")

    p_add_in = add_sub.add_parser("interaction", help="log an interaction (advances a "
                                                     "prospect to engaged)")
    p_add_in.add_argument("company", help="the company slug")
    p_add_in.add_argument("--channel", required=True,
                          choices=[c.value for c in Channel])
    p_add_in.add_argument("--direction", default="",
                          choices=["", *[d.value for d in Direction]],
                          help="required, except for --channel note")
    p_add_in.add_argument("--body", default="",
                          help="the message itself; - reads it from stdin")
    for flag in ("--contact", "--subject", "--date", "--outcome"):
        p_add_in.add_argument(flag, default=None)

    for parser_ in (p_add_co, p_add_ct, p_add_in):
        parser_.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE",
                             help="any other front-matter field (repeatable)")

    p_import = sub.add_parser("import", help="import companies/contacts from a TSV, CSV "
                                             "or .xlsx file")
    p_import.add_argument("file", type=Path)
    p_import.add_argument("--mode", choices=["companies", "contacts"], default=None,
                          help="default: detected from the header row")
    p_import.add_argument("--map", action="append", default=[], metavar="HEADER=FIELD",
                          help="map a column to a field, 'notes' or 'ignore' (repeatable)")
    p_import.add_argument("--apply", action="store_true")

    p_enrich = sub.add_parser("enrich", help="look up missing fields with an AI CLI "
                                          "(claude, codex, gemini, grok or custom)")
    p_enrich.add_argument("slug")
    p_enrich.add_argument("--contact", default="")
    p_enrich.add_argument("--apply", action="store_true")

    p_fetch = sub.add_parser("fetch", help="propose fields from the website or LinkedIn "
                                           "page itself (no AI, no credits)")
    p_fetch.add_argument("slug")
    p_fetch.add_argument("--url", default="")
    p_fetch.add_argument("--apply", action="store_true")

    p_bcc = sub.add_parser("bcc", help="import mails BCC'd or forwarded to the "
                                       "tracking address (Gmail over IMAP)")
    p_bcc.add_argument("--apply", action="store_true")
    p_bcc.add_argument("--eml", nargs="+", type=Path, default=[],
                       help="read these .eml files instead of Gmail")

    p_backfill = sub.add_parser("backfill-history",
                                help="rebuild stage_history from git for companies without one")
    p_backfill.add_argument("--apply", action="store_true")

    p_report = sub.add_parser("report", help="activity, funnel, outcomes, messages, "
                                             "sources and hygiene for a period")
    p_report.add_argument("--days", type=int, default=None)
    p_report.add_argument("--from", dest="start", type=date.fromisoformat, default=None)
    p_report.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    p_report.add_argument("--md", action="store_true", help="Markdown tables")
    p_cal = sub.add_parser("calendar", help="log past meetings from the secret ICS "
                                            "calendar feed (no OAuth)")
    p_cal.add_argument("--apply", action="store_true")
    p_cal.add_argument("--ics", nargs="+", type=Path, default=[],
                       help="read these .ics files instead of the feed")

    p_sync = sub.add_parser("sync", help="bcc, then calendar (the daily launchd run)")
    p_sync.add_argument("--apply", action="store_true")

    p_help = sub.add_parser("help", help="how a feature works (the web app's /help pages)")
    p_help.add_argument("topic", nargs="?", default="",
                        help="a topic; none prints the index and lists the topics")

    return parser


def cmd_help(topic: str = "") -> tuple[str, int]:
    """The help page as Markdown; the index plus the topic list without a topic."""
    from hermitcrm import help as helpdocs

    names = ", ".join(helpdocs.topics())
    if not topic:
        text = helpdocs.read("index") or ""
        return (text.rstrip("\n") + f"\n\nTopics: {names}\nUse: hermitcrm help <topic>\n", 0)
    text = helpdocs.read(topic)
    if text is None:
        return (f"unknown help topic {topic!r}. Topics: {names}\n", 2)
    return (text, 0)


def main(argv: list[str] | None = None, root: Path | None = None, stdin=None) -> int:
    for key, value in list(os.environ.items()):  # OWNCRM_* from before the rename
        if key.startswith("OWNCRM_"):
            os.environ.setdefault("HERMITCRM_" + key[len("OWNCRM_"):], value)
    parser = _build_parser()
    args = parser.parse_args(argv)
    stdin = stdin or sys.stdin

    if args.command == "init":
        text, code = cmd_init(args.dir, demo=args.demo)
        print(text, file=sys.stderr if code else sys.stdout)
        if code == 0 and not args.no_setup and stdin.isatty():
            cmd_setup(Path(args.dir).expanduser().resolve())
        return code

    if args.command == "help":  # needs no data folder
        text, code = cmd_help(args.topic)
        print(text, end="", file=sys.stderr if code else sys.stdout)
        return code

    if root is None:
        try:
            root = resolve_data_dir(args.data)
        except NotDataFolder as exc:
            if args.command != "doctor":
                print(exc, file=sys.stderr)
                return 2
            root = Path(args.data or os.environ.get("HERMITCRM_DATA") or Path.cwd())
    root = Path(root)

    if args.command == "backup":  # before migrations: a backup never changes the data
        return cmd_backup(root, args)

    if args.command == "doctor":  # before migrations: report, never change the folder
        from hermitcrm import doctor
        text, code = doctor.report(doctor.run_checks(root, online=args.online))
        print(text)
        return code

    try:
        if args.command == "migrate" and args.dry_run:
            print(migrations.dry_run(root))
            return 0
        note = migrations.ensure_current(root)
    except migrations.FormatTooNew as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.command == "migrate":
        print(note or f"Data format {migrations.current_format(root)} is current.")
        return 0
    if note:
        print(note, file=sys.stderr)

    if args.command == "serve":
        cmd_serve(root, port=args.port, host=args.host)
        return 0

    if args.command == "setup":
        return cmd_setup(root)

    if args.command == "schedule":
        return cmd_schedule(root, args.action, at=args.at, serve=args.serve,
                            backup=not args.no_backup, backup_every=args.backup_every)

    store = build_store(root)

    if args.command == "mcp":
        return cmd_mcp(root, store, stdin=stdin)

    if args.command == "brief":
        print(cmd_brief(root, store, args.days))
        return 0

    if args.command == "followups":
        print(cmd_followups(store, load_config(root), args.reply_after, args.nudge_after))
        return 0

    if args.command == "digest":
        text = cmd_digest(store, args.days)
        print(text)
        return 0

    if args.command == "show":
        text = cmd_show(store, args.slug, bodies=args.bodies, all_bodies=args.all_bodies)
        print(text)
        return 1 if store.get(args.slug) is None else 0

    if args.command == "rebuild":
        config = load_config(root)
        gitops = GitOps(root, push_enabled=config["push_enabled"],
                        remote=config.get("remote", "origin"))
        text = cmd_rebuild(store, gitops)
        print(text)
        return 0

    if args.command == "check":
        text, code = cmd_check(store)
        print(text)
        return code

    if args.command == "report":
        config = load_config(root)
        try:
            text = cmd_report(store, days=args.days, start=args.start, end=args.end,
                              md=args.md, window_days=int(config["message_window_days"]))
        except ValueError as exc:
            print(exc)
            return 2
        print(text, end="")
        return 0

    if args.command == "backfill-history":
        if args.apply:
            store.on_write = _writer(store, root, load_config(root))
        print(cmd_backfill_history(store, apply=args.apply))
        return 0

    if args.command == "bcc":
        config = load_config(root)
        if args.apply:
            store.on_write = _writer(store, root, config)
        print(f"{datetime.now():%Y-%m-%d %H:%M} hermitcrm bcc{' --apply' if args.apply else ''}")
        text, code = cmd_bcc(store, root, config, apply=args.apply, eml=args.eml)
        print(text)
        if code == 0 and args.apply:
            _reload_server(config)
        return code

    if args.command in ("calendar", "sync"):
        config = load_config(root)
        if args.apply:
            store.on_write = _writer(store, root, config)
        print(f"{datetime.now():%Y-%m-%d %H:%M} hermitcrm {args.command}"
              f"{' --apply' if args.apply else ''}")
        if args.command == "calendar":
            text, code = cmd_calendar(store, root, config, apply=args.apply, ics=args.ics)
        else:
            text, code = cmd_sync(store, root, config, apply=args.apply)
        print(text)
        if code == 0 and args.apply:
            _reload_server(config)
        return code

    if args.command == "sample":
        store.on_write = _writer(store, root, load_config(root))
        text, code = cmd_sample(store, args.action)
        print(text, file=sys.stderr if code else sys.stdout)
        return code

    if args.command == "add":
        store.on_write = _writer(store, root, load_config(root))
        text, code = cmd_add(store, args, stdin=stdin)
        print(text, file=sys.stderr if code else sys.stdout)
        return code

    if args.command in ("import", "enrich", "fetch"):
        config = load_config(root)
        if args.apply:
            store.on_write = _writer(store, root, config)
        if args.command == "import":
            from hermitcrm.models import ValidationError
            try:
                mapping = parse_map_args(args.map)
            except ValueError as exc:
                parser.error(str(exc))
            try:
                print(cmd_import(store, args.file, apply=args.apply, mode=args.mode,
                                 mapping=mapping))
            except ValidationError as exc:
                print("import failed: " + "; ".join(f"{k}: {v}" for k, v in exc.errors.items()))
                return 1
            return 0
        if args.command == "fetch":
            text, code = cmd_fetch(store, args.slug, url=args.url, apply=args.apply)
            print(text)
            return code
        enricher = Enricher(provider=config.get("enrich_provider", "auto"),
                            command=config.get("enrich_command", ""),
                            model=config.get("enrich_model", ""),
                            timeout=config.get("enrich_timeout", 180))
        if not enricher.available:
            print(f"enrichment unavailable: {enricher.unavailable_reason()}")
            return 1
        text, code = cmd_enrich(store, enricher, args.slug, contact=args.contact,
                                apply=args.apply)
        print(text)
        return code

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
