"""Where the data lives, and `hermitcrm init`: a fresh data folder (optionally with demo data)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, time, timedelta
from pathlib import Path

from . import fields, guard, migrations
from .store import DEFAULT_CONFIG, Store

ENV_DATA = "HERMITCRM_DATA"
GIT_AUTHOR = ["-c", "user.name=hermitcrm", "-c", "user.email=hermitcrm@localhost"]
INIT_COMMIT = "init: Hermit CRM data folder"


class NotDataFolder(Exception):
    pass


class InitError(Exception):
    pass


# ------------------------------------------------------------ resolution


def is_data_folder(path: Path) -> bool:
    return (path / "config.toml").is_file() or (path / "companies").is_dir()


def resolve_data_dir(option: str | Path | None = None, env: dict | None = None,
                     cwd: Path | None = None) -> Path:
    """--data, then $HERMITCRM_DATA, then the current directory."""
    env = os.environ if env is None else env
    raw = option or env.get(ENV_DATA) or (cwd or Path.cwd())
    path = Path(raw).expanduser().resolve()
    if not is_data_folder(path):
        raise NotDataFolder(f"Not a Hermit CRM data folder: {path}. Run `hermitcrm init {path}`.")
    return path


# --------------------------------------------------------------- config.toml

# One line of documentation per key; render_config fails if a key has none,
# so defaults (store.DEFAULT_CONFIG) and docs cannot drift apart.
CONFIG_DOCS = {
    "owner_name": "Your name; its first word signs outreach drafts ({owner_first_name}).",
    "owner_email": "Your main email address (informational).",
    "port": "Port of the web app on 127.0.0.1 (`hermitcrm serve --port` overrides it).",
    "host": "Address the web app binds to (`hermitcrm serve --host` overrides it). 0.0.0.0 reaches your phone over the network; Hermit CRM has no password, so use a network you trust.",
    "allowed_hosts": "Host names the web app answers to besides localhost and IP addresses, e.g. [\"mymac.tail1234.ts.net\"]. Other names are refused, which stops DNS-rebinding attacks from web pages. Restart after changing it.",
    "silent_days": "A company with no interaction for this many days counts as silent.",
    "followup_reply_days": "Days before a message they sent and you have not answered shows on the follow-up radar.",
    "followup_nudge_days": "Days before a message you sent and nobody answered shows on the follow-up radar.",
    "push_enabled": "Push to the git remote after each commit (when a remote exists).",
    "remote": "Name of the git remote to push to.",
    "backup_dir": "Where `hermitcrm backup` keeps its repository that only grows; empty means ~/.hermitcrm/backups/<folder>-<hash>.git. Must be outside this folder.",
    "welcome_done": "Walkthrough steps you ticked yourself, the ones Hermit CRM cannot see happen.",
    "welcome_dismissed": "Stop opening the walkthrough when Hermit CRM starts; it stays under Help.",
    "messaging_size_field": "Which of your fields holds a headcount, for the drafts that mention team size; empty means the size line always uses its 'unknown' wording.",
    "messaging_team_field": "Which of your fields holds a count of sales people, for the drafts that mention the team; empty means the team line always uses its 'unknown' wording.",
    "enrich_provider": "AI CLI for Enrich: auto, claude, codex, gemini, grok or custom.",
    "enrich_account": "How the AI CLI is signed in: subscription (a ChatGPT, Claude or Gemini plan) or api (an API key). A subscription is not entitled to the same model ids, so Hermit CRM asks for no particular model where that is known to matter.",
    "enrich_command": "Custom enrich command; empty means the provider's own binary.",
    "enrich_model": "Medium-tier model for Enrich and Ask the Hermit; empty means the provider default (Claude: claude-opus-5).",
    "enrich_model_strong": "Strong-tier model for Retry; empty means the provider default (Claude: claude-fable-5-1).",
    "enrich_timeout": "Seconds before an enrich call is abandoned.",
    "ai_tier": "Which model tier Enrich and Ask the Hermit use by default: medium or strong.",
    "ask_timeout": "Seconds before one Ask the Hermit call is abandoned.",
    "theme": "Look of the web app: light, dark or system.",
    "message_window_days": "A message without reply or outcome counts as the last outcome after this many days.",
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
    "update_check": "Check for a newer Hermit CRM at most once a day (no identifiers sent).",
    "update_url": "Where that check asks; empty means PyPI. Any URL answering {\"version\": \"0.4.0\"} works.",
    "feedback_email": "Address the Feedback form offers to mail a report to; empty means copy it yourself.",
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
    lines = ["# Hermit CRM configuration. Every key is optional and shown with its default.",
             "# Uncomment a line to change it. Secrets (app password, calendar URL) never",
             "# go here: use HERMITCRM_* environment variables, .secrets.toml or the Keychain.",
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

AGENT_RULES = """# Hermit CRM data folder: rules for AI agents

This folder is a CRM. Data lives in `companies/<slug>/` as Markdown with YAML
front matter: `company.md`, `contacts/<slug>.md` and `interactions/<id>.md`.
The web app (`hermitcrm serve`, http://127.0.0.1:8765) and these files are two
views of the same data, and every change is a git commit. Run the commands
below from this folder, or add `--data <this folder>`.

Reading rules, in order of cost:
1. Read PIPELINE.md first. For pipeline reviews it is usually enough.
2. For one account, run `hermitcrm show <slug>` rather than opening files.
3. For "what happened recently", run `hermitcrm digest --days 7`.
4. For numbers (activity, funnel, outcomes, messages), run `hermitcrm report --days 30 --md`.
5. Open interaction files directly only when the exact wording matters
   (drafting a reply, judging tone). Never read all interactions.
6. Never edit PIPELINE.md by hand; it is generated.
7. For outreach wording, read MESSAGING.md (the playbook) and messages.toml
   (if present) before drafting anything.
8. For how a feature works: `hermitcrm help <topic>` (topics: `hermitcrm help`).

Creating a record (company, contact, interaction):

    hermitcrm add company "Acme BV" --country NL --website acme.example.com
    hermitcrm add contact acme "Jane Roe" --title CTO --email jane@example.com
    hermitcrm add interaction acme --channel email --direction out \
        --contact jane-roe --subject "Intro" --body -

- `add` writes the file, regenerates PIPELINE.md and commits, in that order.
  It has no --apply and no dry run: it always writes.
- Each command prints the slug it assigned. Use that slug in the next command;
  never guess one, and never invent a file path of your own.
- `--body -` reads the message from stdin, so newlines survive intact.
- Any field the flags do not cover: `--set field=value`, repeatable. The known
  fields are listed in the error when a name is wrong.
- Logging an interaction moves a company from prospect to engaged in the same
  commit. That is intended; do not undo it.

Writing rules:
- Prefer `hermitcrm add` over hand-written YAML, and the web app or a hand edit
  of front matter over ad-hoc scripts.
- Keep front-matter keys you do not recognise; Hermit CRM preserves them.
- After editing files by hand, run `hermitcrm check`, then `hermitcrm rebuild`.
- Commit messages for AI-made changes start with "ai:".
- Never rewrite interaction bodies; they are the record.
- Never put secrets in config.toml and never commit .secrets.toml.
- To change how the app looks, write overrides to `theme.css` in this folder
  (`hermitcrm help settings`, "Your own look"). Never edit the Hermit CRM package.

"""

AGENT_BACKUP_RULES = """Backups and undo (`hermitcrm help backups`):
- This folder is backed up every few minutes to a repository outside it that
  only grows (`hermitcrm backup status` says where, under ~/.hermitcrm/backups/).
- Never rewrite history here: no `git reset --hard`, `commit --amend`, `rebase`,
  `filter-branch`, `git clean -f` or `push --force`. Undo with a new commit instead.
- For Claude Code these commands are blocked: `.claude/settings.json` denies
  them in every permission mode. A refusal is intended; do not work around it
  (another form of the command, a script, `bash -c`). Ask the user instead.
- Never touch ~/.hermitcrm/backups/, .git/hermitcrm-backup.json or
  .claude/settings.json.
- To undo damage: `hermitcrm backup list <path>` finds the version,
  `hermitcrm backup restore <id> <path>` shows what would change, `--apply`
  does it (as a new commit). Say what you restored and from which version.
"""

# Its own constant so migration 6 can add it to CLAUDE.md files written before it.
AGENT_RULES += AGENT_BACKUP_RULES

MESSAGING = """# Messaging playbook

Hermit CRM writes three outreach drafts per contact without AI (the Messages part
of a company or contact page). The wording is not in code but in TOML:

- the package ships neutral defaults (`hermitcrm/default_messages.toml`);
- a `messages.toml` in this folder is deep-merged over them, so you only
  write the keys you want to change.

## The three angles

1. **scale**: they are growing (or growth is levelling off); offer help to keep
   the pace. A `hiring` signal swaps this for **bridge**: help while the role is open;
   a `declining` signal for **decline**: a tough stretch, then an open question.
2. **unblock**: "you are at N people"; get past the next headcount hurdle.
3. **hook**: one concrete observation about their product, then an open question.

The signal (growing / stalled / headcount decline / hiring) and the observation are the two things
you check by hand on LinkedIn and the website. Square brackets mark what only
you can fill in.

## Slots

`{first} {company} {growth} {size} {hurdle} {team} {observation} {fte} {ae}
{site} {owner_first_name}`. `size` and `team` have `known` / `unknown`
variants; `growth` has `growing`, `stalled`, `declining` and `""` (not checked).

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


GIT_MISSING = (
    "git is not on PATH. A Hermit CRM data folder is a git repository, so there "
    "is nothing sensible to create without it. See step 1 of INSTALL.md: on a Mac "
    "that is Apple's Command Line Tools, or, on a Mac with no screen for their "
    "installer, a git of your own from conda-forge."
)

GIT_STUB = (
    "git on this Mac is Apple's placeholder for git, not git: it only asks for the "
    "Command Line Tools to be installed. Run xcode-select --install and click "
    "Install in the window it opens, or put a real git on PATH. Step 1 of "
    "INSTALL.md covers both, including the case where no one is at the screen."
)


def _git(args: list[str], cwd: Path) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        raise InitError(GIT_MISSING) from None
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        # The stub always exists and always "runs", so a plain "git init failed"
        # sends people looking for a broken repo instead of a missing toolchain.
        if "No developer tools were found" in stderr or "xcode-select" in stderr:
            raise InitError(GIT_STUB)
        raise InitError(f"git {' '.join(args)} failed: {stderr}")
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
    guard.write(path)
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


# The demo folder defines three fields of its own. A plain `hermitcrm init`
# writes no fields.toml at all -- these exist to show what user-defined fields
# look like once they hold something, which an empty Settings form cannot.
DEMO_FIELDS = [
    fields.FieldDef(key="my_score", label="my score", type="number",
                    help="your own 0 to 10", show_in=["detail", "board", "companies"]),
    fields.FieldDef(key="fte_estimate", label="FTE estimate", type="text",
                    help="as written, e.g. ~13", show_in=["detail", "companies"]),
    fields.FieldDef(key="ae_count", label="AE count", type="number",
                    show_in=["detail"]),
]


def load_demo(path: Path, now: datetime) -> Store:
    """Six fictional companies spread over the last six weeks, every stage type."""
    fields.write(path, DEMO_FIELDS)
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
                                 product_oneliner=oneliner, tags=tags,
                                 custom={"fte_estimate": fte, "ae_count": ae,
                                         "my_score": score},
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
            hour=10):
        return store.create_interaction(slug, channel=channel, direction=direction,
                                        contact=contact, date=at(days_ago, hour),
                                        subject=subject, outcome=outcome, body=body)

    # Northwind: reached out (logging it makes the company engaged), got a
    # reply, meetings, now an offer.
    log(northwind, 35, "linkedin", "out", lena,
        "Hi Lena,\nNorthwind Robotics is growing fast.\nWorth a short call?\n\nAlex\n")
    log(northwind, 33, "linkedin", "in", lena, "Hi Alex, sure. Thursday works.\n")
    log(northwind, 28, "meeting", "out", lena, "Intro call. Pain: slow onboarding of pickers.",
        subject="Intro call: wants a proposal for two sites")
    at(28, 12)
    store.update_company(northwind, stage="discovery", value_eur_month=4000)
    log(northwind, 14, "email", "out", jonas, "Hi Jonas,\nattached the proposal for both sites.\n\nAlex\n",
        subject="Proposal sent")
    at(14, 11)
    store.update_company(northwind, stage="offer", next_step="Follow up on the proposal",
                         next_step_due=(today + timedelta(days=3)).isoformat())

    # Bluefin: a message, a call, discovery with an overdue next step.
    log(bluefin, 30, "email", "out", joris,
        "Hi Joris,\nyou're at ~18 people now.\nInterested in how similar teams got past 20?\n\nAlex\n",
        subject="Getting past 20", outcome="successful")
    log(bluefin, 20, "call", "out", joris, "Good call; budget decision next quarter.",
        subject="Discovery booked")
    at(20, 12)
    store.update_company(bluefin, stage="discovery", value_eur_month=1500,
                         next_step="Send case study",
                         next_step_due=(today - timedelta(days=2)).isoformat())

    # Copperleaf: one outbound message, no answer yet.
    log(copperleaf, 5, "linkedin", "out", camille,
        "Bonjour Camille,\nCopperleaf Studio se développe vite.\nUn court échange ?\n\nAlex\n")
    at(5, 11)
    store.update_company(copperleaf, next_step="Follow up if no reply",
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
        subject="Scoping: agreed on scope")
    at(18, 12)
    store.update_company(quartzline, stage="offer")
    log(quartzline, 8, "email", "in", maya, "Signed contract attached. Looking forward!\n",
        subject="Contract")
    at(8, 11)
    store.update_company(quartzline, stage="won")

    # Emberoak: reached out, then lost.
    log(emberoak, 32, "email", "out", erik,
        "Hi Erik,\nEmberoak Foods has come a long way.\nWorth a short call?\n\nAlex\n",
        subject="Quick question", outcome="unsuccessful")
    at(12)
    store.update_company(emberoak, stage="lost", lost_reason="No budget this year")

    store.load()
    return store
