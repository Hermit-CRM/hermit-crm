# OwnCRM

Your CRM is a folder of Markdown files in git. Every company, contact and
conversation is a small text file you can read, grep, edit and diff; every
change the app makes is a commit, so nothing is ever lost and any mistake is
one `git revert` away. A local web app gives you a pipeline board, a calendar
of next steps, message drafts and reports, and because the data is plain files
with a small CLI, AI agents (Claude Code, Codex and others) can read and
update your pipeline as easily as you can. OwnCRM is built for one person:
a founder, a freelancer, someone doing their own sales.

## How it compares

A modest, factual comparison (checked September 2026; corrections welcome):

| | OwnCRM | HubSpot Free | Twenty | Obsidian CRM plugin |
|---|---|---|---|---|
| Data as Markdown files | Yes | No | No (Postgres) | Yes |
| Git history of every change | Yes, one commit per write | No (activity log) | No | Only with a git plugin |
| Web app | Yes, local | Yes, hosted | Yes | No (inside Obsidian) |
| Email capture | BCC/forward via Gmail IMAP | Yes (BCC, inbox sync) | Yes (Gmail/Outlook sync) | Depends on the plugin |
| AI-agent friendly | Plain files, CLI, AGENTS.md | Via API | Via API | Plain files |
| Self-hosted without Docker | Yes (`pipx install`) | No (SaaS only) | No (Docker Compose) | n/a (desktop app) |
| Multi-user teams | No | Yes | Yes | No |

If you need a team CRM, use one of the others. If you want your pipeline in
files you own, OwnCRM is for you.

## Install

Quick start:

```bash
pipx install owncrm                              # or: uv tool install owncrm
owncrm init ~/crm                                # a new data folder; asks 3 questions
owncrm --data ~/crm serve                        # http://127.0.0.1:8765
owncrm --data ~/crm schedule install --serve     # daily sync, web app always on
```

`owncrm init` asks three questions: **you** (your name and sending addresses),
**BCC capture** (the tracking address and its app password) and **backup** (a
private git remote). Skip any of them; rerun with `owncrm setup` or open the
Settings page (`/settings`) in the web app. Add `--demo` for six fictional companies,
`--no-setup` to skip the questions. Python 3.11 or newer. Instead of `--data`
you can set `OWNCRM_DATA=~/crm` or run commands from inside the folder.

`owncrm doctor` checks the whole installation in one go. Every page of the
web app has a Help link; `owncrm help [topic]` prints the same pages.

## Features

- **Pipeline board** with stages prospect, reached out, discovery, offer, won,
  lost, disqualified and temporarily disqualified (with a requalify date).
- **Companies and contacts tables** with column filters and sorting.
- **Calendar** of next steps: overdue and due-today lists, a month grid and
  Google Calendar links.
- **Timeline per company**: email, LinkedIn, call and meeting interactions,
  in or out, with bodies kept byte for byte.
- **Message drafts without AI**: three angles per contact in English, German,
  Dutch or French (by country), with wording you control in `messages.toml`.
- **Messages tab**: every outbound message with its outcome (successful on a
  reply, unsuccessful after a window, or set by hand; the choices are
  `outcomes` in config.toml).
- **Reports**: activity per week, funnel and conversion, time in stage,
  outcomes, message results by language and channel, data hygiene.
- **BCC import**: BCC or forward mail to a Gmail address and it is logged on
  the right contact; unmatched mail waits in the review queue on the Settings
  page.
- **Calendar import**: past meetings from a secret ICS feed (no OAuth).
- **Import** companies or contacts from CSV, TSV or `.xlsx`.
- **Enrichment**: free "fetch from URL" (website or LinkedIn page), or any AI
  CLI you already use (claude, codex, gemini, grok or a custom command).
- **Stage history** per company, reconstructable from git.
- **PIPELINE.md**: a generated one-page summary for you and your agents.
- **Unknown front-matter keys are preserved**, so other tools can add fields.

## Configuration

`owncrm init` writes `config.toml` with every key commented out at its default.
Uncomment what you want to change.

| Key | Default | What it does |
|---|---|---|
| `owner_name` | `""` | Your name; its first word signs outreach drafts ({owner_first_name}). |
| `owner_email` | `""` | Your main email address (informational). |
| `port` | `8765` | Port of the web app on 127.0.0.1 (`owncrm serve --port` overrides it). |
| `silent_days` | `14` | A company with no interaction for this many days counts as silent. |
| `push_enabled` | `true` | Push to the git remote after each commit (when a remote exists). |
| `remote` | `"origin"` | Name of the git remote to push to. |
| `enrich_provider` | `"auto"` | AI CLI for Enrich: auto, claude, codex, gemini, grok or custom. |
| `enrich_command` | `""` | Custom enrich command; empty means the provider's own binary. |
| `enrich_model` | `""` | Model for the enrich CLI; empty means its default. |
| `enrich_timeout` | `180` | Seconds before an enrich call is abandoned. |
| `message_window_days` | `14` | A message without reply or outcome counts as the last outcome after this many days. |
| `fetch_timeout` | `10` | Seconds to wait when Fetch from URL reads a page. |
| `bcc_address` | `""` | Address you BCC or forward mail to, e.g. you+crm@gmail.com; empty disables BCC import. |
| `bcc_imap_host` | `"imap.gmail.com"` | IMAP server of that mailbox. |
| `bcc_keychain_service` | `"crm-bcc"` | macOS Keychain service holding the app password (account = IMAP user). |
| `bcc_lookback_days` | `30` | How far back the BCC import searches. |
| `my_addresses` | `[]` | Mail from these addresses is yours (outbound). |
| `bcc_ignore_domains` | `[]` | Recipients at these domains (colleagues) are never logged. |
| `calendar_keychain_service` | `"crm-calendar"` | macOS Keychain service holding the secret ICS URL. |
| `calendar_keychain_account` | `"ics"` | macOS Keychain account for the ICS URL. |
| `calendar_lookback_days` | `30` | How far back the calendar import looks. |
| `calendar_ignore_titles` | `[]` | Events whose title contains one of these are skipped. |
| `calendar_min_attendees` | `2` | Events with fewer participants (you included) are skipped. |
| `update_check` | `true` | Check PyPI for a newer OwnCRM at most once a day (no identifiers sent). |

Secrets never go in `config.toml`; see [Secrets](#secrets).

### Message templates

Drafts come from the package's neutral `default_messages.toml`. Put a
`messages.toml` in your data folder to override any part of it; it is
deep-merged, so a two-line file is enough:

```toml
[languages.en]
signoff = "Best,\n{owner_first_name}"
```

`MESSAGING.md` in your data folder explains the angles, slots and languages.

## CLI

```text
owncrm [--data DIR] <command>      --data, then $OWNCRM_DATA, then the current directory
owncrm --version

owncrm init DIR [--demo] [--no-setup]
                                   create a data folder (git repo, config, agent rules)
owncrm setup                       the setup questions again (you, BCC, backup, calendar)
owncrm help [TOPIC]                how a feature works (the web app's /help pages)
owncrm doctor [--online]           check Python, git, config, secrets, schedule, backup, updates
owncrm schedule install [--at HH:MM] [--serve]
                                   daily sync --apply (launchd, systemd; schtasks is printed)
owncrm schedule remove|status
owncrm serve [--port N]            the web app on 127.0.0.1
owncrm show <slug> [--bodies N | --all]
owncrm digest [--days 7]           recent interactions, oldest first
owncrm report [--days N | --from D --to D] [--md]
owncrm check                       validate every file (exit 1 on problems)
owncrm rebuild                     regenerate PIPELINE.md and commit
owncrm import FILE [--mode companies|contacts] [--map HEADER=FIELD] [--apply]
owncrm fetch <slug> [--url URL] [--apply]
owncrm enrich <slug> [--contact SLUG] [--apply]
owncrm bcc [--apply] [--eml FILE ...]
owncrm calendar [--apply] [--ics FILE ...]
owncrm sync [--apply]              bcc, then calendar
owncrm backfill-history [--apply]  stage_history from git
owncrm migrate [--dry-run]         upgrade the data format (runs automatically)
```

Commands that write take `--apply`; without it they show what they would do.
Every write is one git commit.

## Secrets

Two secrets exist: `bcc_password` (a Gmail app password) and
`calendar_ics_url`. OwnCRM looks for each in this order:

1. the environment: `OWNCRM_BCC_PASSWORD`, `OWNCRM_CALENDAR_ICS_URL`;
2. `.secrets.toml` in the data folder (gitignored; keep it `chmod 600`,
   OwnCRM warns otherwise):
   ```toml
   bcc_password = "abcd efgh ijkl mnop"
   calendar_ics_url = "https://calendar.google.com/calendar/ical/.../basic.ics"
   ```
3. on macOS, the Keychain (service from `bcc_keychain_service` /
   `calendar_keychain_service` in `config.toml`).

## BCC import setup

The easy way: **Settings → BCC capture** in the web app (`/settings#bcc`) or
`owncrm setup`. It suggests `you+crm@gmail.com` for Gmail, picks the IMAP server
for Gmail, Outlook/Hotmail/Live and iCloud, stores the app password in
`.secrets.toml` or the macOS Keychain, tests the connection with a dry run and
shows the Gmail filter to add:

```text
Matches: to:(you+crm@gmail.com) → Skip the Inbox, Mark as read, Apply label OwnCRM
```

For Gmail, turn on 2-step verification and create an app password at
https://myaccount.google.com/apppasswords; your normal password is rejected.

By hand: set `bcc_address`, `my_addresses` and optionally `bcc_ignore_domains`
in `config.toml` and store `bcc_password` as a secret (see [Secrets](#secrets)).
Then BCC that address on mail you send, or forward a thread to it, and run
`owncrm bcc` (dry run) and `owncrm bcc --apply`. Mail that matches no contact or
company waits in the review queue on the Settings page (`/settings#inbox`).
`owncrm schedule install` runs it daily.

## Calendar import setup

1. Copy the secret ICS address of your calendar (treat it like a password):
   - **Google Calendar**: Settings → your calendar → Integrate calendar →
     *Secret address in iCal format*.
   - **Outlook / Microsoft 365**: Settings → Calendar → Shared calendars →
     Publish a calendar → copy the ICS link.
   - **iCloud**: share the calendar as a public calendar (`webcal://` works).
2. Paste it in **Settings → Calendar** (`/settings#calendar`) or answer yes to the
   calendar question of `owncrm setup`; it is stored as `calendar_ics_url` in
   `.secrets.toml` and tested with a dry run. By hand, see [Secrets](#secrets).
3. `owncrm calendar`, then `owncrm calendar --apply` (or let `owncrm schedule
   install` run `sync` daily). Meetings with a known contact are logged as
   `meeting` interactions; the rest wait in the review queue on the Settings page.

## Updating

```bash
pipx upgrade owncrm   # or: uv tool upgrade owncrm
```

The web app checks PyPI at most once a day (no identifiers sent; turn it off
with `update_check = false` or `OWNCRM_NO_UPDATE_CHECK=1`) and shows a notice
in the nav when a newer version exists. When a release changes the data
format, the next command migrates your folder automatically, in **one git
commit** named `migrate: data format N → M (...)`, so `git revert <sha>`
undoes it. See what would change first with `owncrm migrate --dry-run`. A
folder written by a newer OwnCRM is refused until you upgrade.

## Data layout

```text
~/crm/
├── config.toml                 settings (all optional)
├── messages.toml               optional draft wording, merged over the defaults
├── .secrets.toml               optional secrets (gitignored, chmod 600)
├── .owncrm-format              data format version (committed)
├── PIPELINE.md                 generated summary, never edit by hand
├── CLAUDE.md / AGENTS.md       rules for AI agents working in this folder
├── MESSAGING.md                your outreach playbook
├── inbox/                      BCC and calendar items waiting for a decision
└── companies/<slug>/
    ├── company.md              front matter: stage, next step, scores, history...
    ├── contacts/<slug>.md
    └── interactions/<date>-<channel>-<direction>-<contact>.md
```

Every file is Markdown with YAML front matter in a fixed key order, so two
writes of the same data are identical and diffs show only real changes. Keys
OwnCRM does not know are kept, after the known ones.

## Rollback recipes

Every write is a commit, so rolling back is plain git, run in the data folder:

```bash
git log -- companies/<slug>          # the history of one company
git checkout <sha> -- <path>         # restore one file to an older version
git revert <sha>                     # undo one commit, keeping history
owncrm rebuild                       # then regenerate PIPELINE.md
```

Pushing to a remote after each write is on by default (`push_enabled`) and
simply does nothing until you add one with `git remote add origin <url>`.

## Working with AI agents

`owncrm init` writes `CLAUDE.md` and `AGENTS.md` (the same text) into the data
folder: read `PIPELINE.md` first, use `owncrm show` / `digest` / `report`
instead of opening many files, run `owncrm check` and `owncrm rebuild` after
hand edits, never rewrite interaction bodies, and `owncrm help <topic>` for
how a feature works. Open the folder in Claude Code, Codex or any agent and
ask for a pipeline review or a follow-up draft.

## Roadmap

- TODO: scheduling. Run `owncrm sync --apply` daily without setting up
  launchd, systemd or cron by hand.
- Per-record history and restore in the web app.
- More draft languages out of the box.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
MIT licensed.

---

Built by Gijs Bos at CompoundGTM
