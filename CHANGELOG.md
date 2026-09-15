# Changelog

All notable changes to OwnCRM. Versions follow semantic versioning; a change to
the data format always comes with an automatic migration.

## 0.1.0 (unreleased)

First public release, by Gijs Bos.

- A Settings page (`/settings`, always in the nav) with You, BCC capture,
  Calendar, Backup, Enrichment, Outcomes, the review queue (the former Inbox),
  the daily schedule's status and About; `/setup` and `/inbox` redirect there.
  Help pages for every screen (`/help/<topic>`, the Help link in the nav) and
  `owncrm help [topic]` for agents and terminals; the data folder's CLAUDE.md
  points at it.
- Guided setup: `owncrm init` asks three questions (you, BCC capture, backup;
  `--no-setup` skips them), `owncrm setup` reruns them, and the web app's
  Settings page (CSRF-protected) is where the first run lands once. An
  empty Board offers Import, Add a company and Set up BCC capture.
- `owncrm schedule install [--at HH:MM] [--serve]`, `remove` and `status`:
  a daily `sync --apply` via launchd (macOS) or systemd user units (Linux);
  Windows gets the `schtasks` command to run.
- `owncrm doctor [--online]`: one ok/warn/fail line per check (Python, git,
  data folder, migrations, config, secrets, IMAP login, calendar, schedule,
  git remote and last push, enrich CLI, updates); exits 1 on a failure.
- A CRM that is a folder of Markdown files with YAML front matter in git; every
  write is one commit.
- `owncrm init DIR [--demo]`: a data folder with a commented `config.toml`,
  agent rules (`CLAUDE.md` / `AGENTS.md`), a `MESSAGING.md` starter and optional
  demo data; `owncrm [--data DIR]` or `OWNCRM_DATA` to point at it.
- Local web app (`owncrm serve`): pipeline board, companies and contacts tables
  with filters, calendar of next steps, company timelines, merge, Messages tab,
  Reports (activity, funnel, outcomes, messages, hygiene).
- Deterministic outreach drafts in English, German, Dutch and French, with the
  wording in `default_messages.toml` and an optional `messages.toml` override.
- BCC import over Gmail IMAP and calendar import from a secret ICS feed, with an
  Inbox for unmatched items.
- Import from CSV, TSV and `.xlsx`; enrichment from a URL or any AI CLI.
- Secrets from `OWNCRM_*` environment variables, `.secrets.toml` or the macOS
  Keychain.
- Data format versions with automatic, one-commit migrations
  (`owncrm migrate --dry-run`); unknown front-matter keys are preserved.
- Any ISO 3166-1 alpha-2 country; `UK`/`USA` are stored as `GB`/`US`.
- `owncrm --version`, version in the footer, and a daily non-blocking update check.
