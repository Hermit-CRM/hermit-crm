#!/usr/bin/env python3
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

from hermitcrm import __version__, migrations
from hermitcrm.datafolder import InitError, NotDataFolder, init_folder, resolve_data_dir
from hermitcrm.enrich import EnrichError, Enricher
from hermitcrm.gitops import GitOps
from hermitcrm.store import Store, load_config

COMPANY_FIELD_ORDER = [
    "name", "slug", "website", "linkedin", "country", "source", "stage",
    "stage_changed", "lost_reason", "requalify_on", "value_eur_month", "my_score", "fit_score",
    "fte_estimate", "ae_count", "product_oneliner", "next_step", "next_step_due",
    "next_step_status", "tags", "created", "updated",
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
    store = Store(root, silent_days=config["silent_days"], outcomes=config["outcomes"])
    store.load()
    return store


def cmd_serve(root: Path, port: int | None = None) -> None:
    from hermitcrm.web import create_app
    import uvicorn

    config = load_config(root)
    if port:
        config["port"] = port
    config["start_update_check"] = True  # background thread, never blocks
    app = create_app(root, config)
    print(f"Hermit CRM {__version__}: {root} on http://127.0.0.1:{config['port']}")
    uvicorn.run(app, host="127.0.0.1", port=int(config["port"]))


def cmd_init(target: Path, demo: bool = False) -> tuple[str, int]:
    try:
        path = init_folder(target, demo=demo)
    except InitError as exc:
        return (str(exc), 2)
    lines = [f"Created a Hermit CRM data folder in {path}" + (" with demo data." if demo else "."),
             f"Start the web app: hermitcrm --data {path} serve"]
    return ("\n".join(lines), 0)


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

    from hermitcrm import setup as st

    ask_secret = ask_secret or getpass.getpass
    platform = platform or sys.platform
    root = Path(root)

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
            keychain = platform == "darwin" and _yes(
                ask("Store it in the macOS Keychain? [Y/n]: "), True)
            result = st.save_bcc(root, address, host, password, use_keychain=keychain,
                                 runner=runner, platform=platform)
            say(result.text())
            if result.ok and _yes(ask("Test the connection now (dry run)? [Y/n]: "), True):
                say(st.test_bcc(root, open_mailbox=open_mailbox).text())
        else:
            say("Skipped; rerun `hermitcrm setup` or open /setup in the web app.")

        say("\n3/3 Backup: push the data folder to a private git remote.")
        url = ask("Git remote URL (empty to skip): ").strip()
        if url:
            warning = st.private_warning(url)
            if warning:
                say("WARNING: " + warning)
            result = st.save_backup(root, url, runner=runner, push=push)
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
                 platform: str | None = None, env: dict | None = None) -> int:
    from hermitcrm import schedule

    ctx = schedule.Context(data_dir=root, home=home or Path.home(),
                           platform=platform or schedule.sys.platform, runner=runner, env=env)
    try:
        if action == "install":
            lines = schedule.install(ctx, at=at, serve=serve)
        elif action == "remove":
            lines = schedule.remove(ctx)
        else:
            lines = schedule.status(ctx)["lines"]
    except schedule.ScheduleError as exc:
        print(exc, file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0


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
            f"{it.date:%Y-%m-%d %H:%M} | {it.channel} {it.direction} | "
            f"{company.slug} / {it.contact_label} | {it.subject or '-'} | "
            f"outcome: {it.outcome or '-'}"
        )
        preview = " ".join(it.body.split())[:150]
        blocks.append(f"{header}\n{preview}")
        if it.channel in counts and it.direction in ("out", "in"):
            counts[it.channel][it.direction] += 1
        companies_touched.add(company.slug)

    n = len(pairs)
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
        f"{it.date:%Y-%m-%d %H:%M} | {it.channel} {it.direction} | "
        f"{contact_label} | {it.subject or '-'} | {it.outcome or '-'}"
    )


def cmd_show(store: Store, slug: str, bodies: int = 3, all_bodies: bool = False) -> str:
    company = store.get(slug)
    if company is None:
        return f"unknown company: {slug}"

    lines: list[str] = []
    for key in COMPANY_FIELD_ORDER:
        text = _company_field_text(company, key)
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
    if not store.problems:
        n_companies = len(store.companies)
        n_contacts = sum(len(c.contacts) for c in store.companies.values())
        n_interactions = sum(len(c.interactions) for c in store.companies.values())
        return (
            f"OK: {n_companies} companies, {n_contacts} contacts, "
            f"{n_interactions} interactions, no problems",
            0,
        )
    lines = [f"{p.path}: {p.message}" for p in store.problems]
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


def cmd_import(store: Store, path: Path, apply: bool = False, mode: str | None = None,
               mapping: dict | None = None) -> str:
    from hermitcrm.importer import apply_import, decode_upload, plan_import

    plan = plan_import(store, decode_upload(path.read_bytes()), mode=mode, mapping=mapping)
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
        proposal = (enricher.propose_contact(company, target) if target
                    else enricher.propose_company(company))
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

    p_init = sub.add_parser("init", help="create a new data folder (a git repo)")
    p_init.add_argument("dir", type=Path)
    p_init.add_argument("--demo", action="store_true", help="add six fictional companies")
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

    p_migrate = sub.add_parser("migrate", help="upgrade the data format (runs automatically)")
    p_migrate.add_argument("--dry-run", action="store_true",
                           help="list the files that would change")

    p_digest = sub.add_parser("digest", help="recent interactions, oldest first")
    p_digest.add_argument("--days", type=int, default=7)

    p_show = sub.add_parser("show", help="one company in full")
    p_show.add_argument("slug")
    p_show.add_argument("--bodies", type=int, default=3)
    p_show.add_argument("--all", action="store_true", dest="all_bodies")

    sub.add_parser("rebuild", help="rebuild the index and PIPELINE.md")
    sub.add_parser("check", help="validate every file")

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
        cmd_serve(root, port=args.port)
        return 0

    if args.command == "setup":
        return cmd_setup(root)

    if args.command == "schedule":
        return cmd_schedule(root, args.action, at=args.at, serve=args.serve)

    store = build_store(root)

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
