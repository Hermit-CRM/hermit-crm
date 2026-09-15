"""Where the data lives, and `owncrm init`: a fresh data folder (optionally with demo data)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, time, timedelta
from pathlib import Path

from . import migrations
from .store import DEFAULT_CONFIG, Store

ENV_DATA = "OWNCRM_DATA"
GIT_AUTHOR = ["-c", "user.name=owncrm", "-c", "user.email=owncrm@localhost"]
INIT_COMMIT = "init: OwnCRM data folder"


class NotDataFolder(Exception):
    pass


class InitError(Exception):
    pass


# ------------------------------------------------------------ resolution


def is_data_folder(path: Path) -> bool:
    return (path / "config.toml").is_file() or (path / "companies").is_dir()


def resolve_data_dir(option: str | Path | None = None, env: dict | None = None,
                     cwd: Path | None = None) -> Path:
    """--data, then $OWNCRM_DATA, then the current directory."""
    env = os.environ if env is None else env
    raw = option or env.get(ENV_DATA) or (cwd or Path.cwd())
    path = Path(raw).expanduser().resolve()
    if not is_data_folder(path):
        raise NotDataFolder(f"Not an OwnCRM data folder: {path}. Run `owncrm init {path}`.")
    return path


# --------------------------------------------------------------- config.toml

# One line of documentation per key; render_config fails if a key has none,
# so defaults (store.DEFAULT_CONFIG) and docs cannot drift apart.
CONFIG_DOCS = {
    "owner_name": "Your name; its first word signs outreach drafts ({owner_first_name}).",
    "owner_email": "Your main email address (informational).",
    "port": "Port of the web app on 127.0.0.1 (`owncrm serve --port` overrides it).",
    "silent_days": "A company with no interaction for this many days counts as silent.",
    "push_enabled": "Push to the git remote after each commit (when a remote exists).",
    "remote": "Name of the git remote to push to.",
    "enrich_provider": "AI CLI for Enrich: auto, claude, codex, gemini, grok or custom.",
    "enrich_command": "Custom enrich command; empty means the provider's own binary.",
    "enrich_model": "Model for the enrich CLI; empty means its default.",
    "enrich_timeout": "Seconds before an enrich call is abandoned.",
    "message_window_days": "A message without reply or result counts as unsuccessful after this many days.",
    "fetch_timeout": "Seconds to wait when Fetch from URL reads a page.",
    "outcomes": "Outcome choices for an interaction; first = what a reply counts as, last = what silence counts as.",
    "bcc_address": "Address you BCC or forward mail to, e.g. you+crm@gmail.com; empty disables BCC import.",
    "bcc_imap_host": "IMAP server of that mailbox.",
    "bcc_keychain_service": "macOS Keychain service holding the app password (account = IMAP user).",
    "bcc_lookback_days": "How far back the BCC import searches.",
    "my_addresses": "Mail from these addresses is yours (outbound).",
    "bcc_ignore_domains": "Recipients at these domains (colleagues) are never logged.",
    "calendar_keychain_service": "macOS Keychain service holding the secret ICS URL.",
    "calendar_keychain_account": "macOS Keychain account for the ICS URL.",
    "calendar_lookback_days": "How far back the calendar import looks.",
    "calendar_ignore_titles": "Events whose title contains one of these are skipped.",
    "calendar_min_attendees": "Events with fewer participants (you included) are skipped.",
    "update_check": "Check PyPI for a newer OwnCRM at most once a day (no identifiers sent).",
}


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


def render_config() -> str:
    lines = ["# OwnCRM configuration. Every key is optional and shown with its default.",
             "# Uncomment a line to change it. Secrets (app password, calendar URL) never",
             "# go here: use OWNCRM_* environment variables, .secrets.toml or the Keychain.",
             ""]
    for key, default in DEFAULT_CONFIG.items():
        lines.append(f"# {CONFIG_DOCS[key]}")
        lines.append(f"# {key} = {_toml_value(default)}")
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ files

GITIGNORE = """.secrets.toml
inbox/.last-run.json
inbox/.last-calendar-run.json
inbox/upcoming.json
.DS_Store
"""

AGENT_RULES = """# OwnCRM data folder: rules for AI agents

This folder is a CRM. Data lives in `companies/<slug>/` as Markdown with YAML
front matter: `company.md`, `contacts/<slug>.md` and `interactions/<id>.md`.
The web app (`owncrm serve`, http://127.0.0.1:8765) and these files are two
views of the same data, and every change is a git commit. Run the commands
below from this folder, or add `--data <this folder>`.

Reading rules, in order of cost:
1. Read PIPELINE.md first. For pipeline reviews it is usually enough.
2. For one account, run `owncrm show <slug>` rather than opening files.
3. For "what happened recently", run `owncrm digest --days 7`.
4. For numbers (activity, funnel, outcomes, messages), run `owncrm report --days 30 --md`.
5. Open interaction files directly only when the exact wording matters
   (drafting a reply, judging tone). Never read all interactions.
6. Never edit PIPELINE.md by hand; it is generated.
7. For outreach wording, read MESSAGING.md (the playbook) and messages.toml
   (if present) before drafting anything.
8. For how a feature works: `owncrm help <topic>` (topics: `owncrm help`).

Writing rules:
- Prefer the web app or a hand edit of front matter over ad-hoc scripts.
- Keep front-matter keys you do not recognise; OwnCRM preserves them.
- After editing files by hand, run `owncrm check`, then `owncrm rebuild`.
- Commit messages for AI-made changes start with "ai:".
- Never rewrite interaction bodies; they are the record.
- Never put secrets in config.toml and never commit .secrets.toml.
"""

MESSAGING = """# Messaging playbook

OwnCRM writes three outreach drafts per contact without AI (the Messages part
of a company or contact page). The wording is not in code but in TOML:

- the package ships neutral defaults (`owncrm/default_messages.toml`);
- a `messages.toml` in this folder is deep-merged over them, so you only
  write the keys you want to change.

## The three angles

1. **scale**: they are growing (or growth is levelling off); offer help to keep
   the pace. A `hiring` signal swaps this for **bridge**: help while the role is open.
2. **unblock**: "you are at N people"; get past the next headcount hurdle.
3. **hook**: one concrete observation about their product, then an open question.

The signal (growing / stalled / hiring) and the observation are the two things
you check by hand on LinkedIn and the website. Square brackets mark what only
you can fill in.

## Slots

`{first} {company} {growth} {size} {hurdle} {team} {observation} {fte} {ae}
{site} {owner_first_name}`. `size` and `team` have `known` / `unknown`
variants; `growth` has `growing`, `stalled` and `""` (not checked).

## Languages

The draft language follows the company's country: German for DE/AT/CH/LI,
Dutch for NL, French for FR/LU/MC, English for everything else (Belgium
included, since it depends on the region).

## Example messages.toml

```toml
[labels]
hook = "3. hook: what I noticed, then a question"

[languages.en]
signoff = "Best,\\n{owner_first_name}"
scale = "{growth}\\nWe help teams like yours [outcome].\\nWorth 15 minutes to see if it fits {company}?"

[languages.en.team]
unknown = "[Something specific about the team.]"
```

## What worked (write your own notes here)

- 
"""


# ------------------------------------------------------------------- init


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise InitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def init_folder(target: str | Path, demo: bool = False, now: datetime | None = None) -> Path:
    path = Path(target).expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise InitError(f"{path} exists and is not a folder.")
    if path.exists() and any(path.iterdir()):
        existing_repo = (path / ".git").exists() and not (path / "config.toml").exists()
        if not existing_repo:
            raise InitError(f"Refusing to init {path}: the folder is not empty "
                            "(an existing git repo without config.toml is allowed).")
    path.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        _git(["init", "-q", "-b", "main"], path)

    (path / "config.toml").write_text(render_config(), encoding="utf-8")
    for folder in ("companies", "inbox"):
        (path / folder).mkdir(exist_ok=True)
        (path / folder / ".gitkeep").touch()
    gitignore = path / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    missing = [line for line in GITIGNORE.splitlines() if line not in existing.splitlines()]
    if missing:
        sep = "" if not existing or existing.endswith("\n") else "\n"
        gitignore.write_text(existing + sep + "\n".join(missing) + "\n", encoding="utf-8")
    for name in ("CLAUDE.md", "AGENTS.md"):
        (path / name).write_text(AGENT_RULES, encoding="utf-8")
    if not (path / "MESSAGING.md").exists():
        (path / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    migrations.write_format(path, migrations.LATEST)

    from . import pipeline

    store = Store(path)
    store.load()
    if demo:
        store = load_demo(path, now or datetime.now())
    pipeline.write(store)
    _git(["add", "-A"], path)
    _git([*GIT_AUTHOR, "commit", "-q", "-m", INIT_COMMIT], path)
    return path


# ------------------------------------------------------------------- demo

DEMO_COMPANIES = [
    # (name, website, country, source, fte, ae, oneliner, tags, score)
    ("Northwind Robotics", "https://northwind-robotics.example.com", "DE", "referral",
     "~45", 3, "Warehouse picking robots for mid-size retailers", ["robotics", "demo"], 8),
    ("Bluefin Analytics", "https://bluefin-analytics.example.com", "NL", "linkedin-search",
     "~18", 1, "Churn dashboards for subscription apps", ["saas", "demo"], 7),
    ("Copperleaf Studio", "https://copperleaf-studio.example.org", "FR", "event",
     "~9", None, "Brand design studio for food start-ups", ["agency", "demo"], 5),
    ("Tallpine Software", "https://tallpine-software.example.com", "GB", "list",
     "", None, "Scheduling software for clinics", ["saas", "demo"], None),
    ("Quartzline Logistics", "https://quartzline-logistics.example.com", "US", "inbound",
     "~120", 6, "Freight tracking for small shippers", ["logistics", "demo"], 9),
    ("Emberoak Foods", "https://emberoak-foods.example.org", "SE", "network",
     "~30", 2, "Plant-based ready meals", ["food", "demo"], 4),
]


def load_demo(path: Path, now: datetime) -> Store:
    """Six fictional companies spread over the last six weeks, every stage type."""
    today = now.date()
    clock = {"now": datetime.combine(today - timedelta(days=42), time(9, 0))}
    store = Store(path, clock=lambda: clock["now"])
    store.load()

    def at(days_ago: int, hour: int = 9, minute: int = 0) -> str:
        when = datetime.combine(today - timedelta(days=days_ago), time(hour, minute))
        clock["now"] = when
        return when.strftime("%Y-%m-%dT%H:%M")

    slugs = []
    for i, (name, site, country, source, fte, ae, oneliner, tags, score) in enumerate(DEMO_COMPANIES):
        at(42 - i)
        c = store.create_company(name, website=site, country=country, source=source,
                                 fte_estimate=fte, ae_count=ae, product_oneliner=oneliner,
                                 tags=tags, my_score=score,
                                 notes=f"Demo company. {oneliner}.\n")
        slugs.append(c.slug)
    northwind, bluefin, copperleaf, tallpine, quartzline, emberoak = slugs
    domain = lambda slug: next(s for n, s, *_ in DEMO_COMPANIES if store.get(slug).name == n) \
        .split("//")[1]

    def person(slug, first, last, title, role=""):
        at(40)
        return store.create_contact(slug, first, last, title=title, role=role,
                                    email=f"{first.lower()}@{domain(slug)}").slug

    lena = person(northwind, "Lena", "Vogt", "COO", "decision-maker")
    jonas = person(northwind, "Jonas", "Brandt", "Head of Operations", "champion")
    joris = person(bluefin, "Joris", "Veldkamp", "Founder & CEO", "decision-maker")
    camille = person(copperleaf, "Camille", "Martin", "Managing Partner")
    oliver = person(tallpine, "Oliver", "Hart", "CTO")
    maya = person(quartzline, "Maya", "Chen", "VP Operations", "decision-maker")
    erik = person(emberoak, "Erik", "Lund", "CEO", "decision-maker")

    def log(slug, days_ago, channel, direction, contact, body, subject="", outcome="",
            result="", hour=10):
        return store.create_interaction(slug, channel=channel, direction=direction,
                                        contact=contact, date=at(days_ago, hour),
                                        subject=subject, outcome=outcome, body=body,
                                        result=result)

    # Northwind: reached out, got a reply, meetings, now an offer.
    log(northwind, 35, "linkedin", "out", lena,
        "Hi Lena,\nNorthwind Robotics is growing fast.\nWorth a short call?\n\nAlex\n")
    log(northwind, 33, "linkedin", "in", lena, "Hi Alex, sure. Thursday works.\n")
    at(33, 11)
    store.update_company(northwind, stage="reached-out")
    log(northwind, 28, "meeting", "out", lena, "Intro call. Pain: slow onboarding of pickers.",
        subject="Intro call", outcome="Wants a proposal for two sites")
    at(28, 12)
    store.update_company(northwind, stage="discovery", value_eur_month=4000)
    log(northwind, 14, "email", "out", jonas, "Hi Jonas,\nattached the proposal for both sites.\n\nAlex\n",
        subject="Proposal", outcome="Sent")
    at(14, 11)
    store.update_company(northwind, stage="offer", next_step="Follow up on the proposal",
                         next_step_due=(today + timedelta(days=3)).isoformat())

    # Bluefin: a message, a call, discovery with an overdue next step.
    log(bluefin, 30, "email", "out", joris,
        "Hi Joris,\nyou're at ~18 people now.\nInterested in how similar teams got past 20?\n\nAlex\n",
        subject="Getting past 20", result="success")
    at(30, 11)
    store.update_company(bluefin, stage="reached-out")
    log(bluefin, 20, "call", "out", joris, "Good call; budget decision next quarter.",
        outcome="Discovery booked")
    at(20, 12)
    store.update_company(bluefin, stage="discovery", value_eur_month=1500,
                         next_step="Send case study",
                         next_step_due=(today - timedelta(days=2)).isoformat())

    # Copperleaf: one outbound message, no answer yet.
    log(copperleaf, 5, "linkedin", "out", camille,
        "Bonjour Camille,\nCopperleaf Studio se développe vite.\nUn court échange ?\n\nAlex\n")
    at(5, 11)
    store.update_company(copperleaf, stage="reached-out", next_step="Follow up if no reply",
                         next_step_due=(today + timedelta(days=5)).isoformat())

    # Tallpine: still a prospect, research first.
    at(10)
    store.update_company(tallpine, next_step="Check LinkedIn insights for growth",
                         next_step_due=today.isoformat())
    _ = oliver

    # Quartzline: inbound, quick win.
    log(quartzline, 25, "email", "in", maya, "Hi, we saw your talk. Can we talk next week?\n",
        subject="Inbound request")
    at(25, 11)
    store.update_company(quartzline, stage="discovery", value_eur_month=6000)
    log(quartzline, 18, "meeting", "out", maya, "Scoping session with the ops team.",
        subject="Scoping", outcome="Agreed on scope")
    at(18, 12)
    store.update_company(quartzline, stage="offer")
    log(quartzline, 8, "email", "in", maya, "Signed contract attached. Looking forward!\n",
        subject="Contract")
    at(8, 11)
    store.update_company(quartzline, stage="won")

    # Emberoak: reached out, then lost.
    log(emberoak, 32, "email", "out", erik,
        "Hi Erik,\nEmberoak Foods has come a long way.\nWorth a short call?\n\nAlex\n",
        subject="Quick question", result="unsuccessful")
    at(32, 11)
    store.update_company(emberoak, stage="reached-out")
    at(12)
    store.update_company(emberoak, stage="lost", lost_reason="No budget this year")

    store.load()
    return store
