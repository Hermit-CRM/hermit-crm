# Changelog

All notable changes to Hermit CRM. Versions follow semantic versioning; a change to
the data format always comes with an automatic migration.

## 0.3.0 (unreleased)

Data format 4: the stage `reached-out` is renamed to **engaged** (in `stage`
and `stage_history`), migrated automatically in one commit.

- Logging an interaction on a **prospect** moves it to **engaged** in the same
  commit (manual, BCC and calendar imports alike).
- **Install docs** describe the clone-and-`pip install` route that works today;
  `pipx install hermitcrm` is marked as not yet published.
- `/favicon.ico` redirects to the app icon instead of answering 404.
- **A write commits its own files only.** Every commit used to stage the whole
  data folder, so an unrelated edit you had not committed yet (a half-written
  `MESSAGING.md`, a hand-added company) was swept into the next write's commit
  under that write's message. Each commit now holds exactly the files that write
  touched.
- **Delete contact** on the contact page; its interactions stay on the company
  without a contact.
- The interaction form defaults to **LinkedIn**, out.
- Contact pages: Contact, Interactions, Drafts, Log an interaction, Merge, Delete; the sidebar marks Contacts.
- New draft signal **headcount decline** (`declining`): its own growth sentence, and
  a **decline** draft replaces scale as angle 1 (like bridge for hiring).
- **Tasks** section on company pages (before Merge) and contact pages (before
  Delete): the next step with due date, status, Mark done / Reopen and a form to
  write a new one.
- Logo in the sidebar and as the browser-tab icon (SVG that follows light/dark, PNG fallback).
- Contact Enrich opens the proposal page with notes and sources even when
  nothing could be verified, instead of a one-line message.

Renamed from OwnCRM to **Hermit CRM** (OwnCRM was taken). Package and command
`hermitcrm`, environment variables `HERMITCRM_*`, launchd labels
`io.hermitcrm.*`. Old names keep working: `OWNCRM_*` variables are still read,
`.owncrm-format` is renamed in a commit on first start, and `schedule install`
removes the old `io.owncrm.*` jobs.

- **Ask Hermit**: an always-visible button top right. Answers from the current
  page first (no tools), then from the whole data folder with read-only tools;
  "Retry with Fable" and "Search the whole CRM instead" on the answer.
- **Model tiers**: medium (default; Claude: Opus) and strong (Claude: Fable)
  per provider, a switch and overrides under Settings → AI (`ai_tier`,
  `enrich_model`, `enrich_model_strong`). Enrich proposals offer "Retry with".
- **Night mode** under Settings → Appearance (`theme`: light, dark, system).
  Every colour is a CSS token.
- Navigation moved to a light-grey left sidebar with icons; search and Ask
  Hermit sit in a sticky top bar.
- A failed AI CLI run shows the CLI's own message instead of its JSON envelope.
- Belgian companies get Dutch or French drafts when the record says which:
  previous mails (theirs weigh most), a `/nl/` or `/fr/` website, a postcode
  outside Brussels, or the language of titles and notes. English otherwise.

## 0.2.0 (unreleased)

Data format 3: `result` on interactions is folded into `outcome` by an
automatic migration.

- One `outcome` per interaction, chosen from a dropdown whose values come from
  `config.toml` (`outcomes`, default successful/unsuccessful; first = what a
  detected reply counts as, last = what silence counts as). The Messages tab
  and the interaction form write the same field, so a change on one shows on
  the other. Migration 3 merges the old `result` and normalises legacy
  spellings (front matter only).
- Messages: an expanded row shows the full text only, not preview and text.
- Interactions can be deleted (edit page and company timeline; confirm first).
- New contact from the Contacts page: type the company, an existing one is
  matched by name or email domain, otherwise it is created; possible
  duplicates (same email, same name at the company, similar company name)
  are shown first with "create anyway".
- Companies and Contacts pages carry their own New and Import buttons; the
  top nav is Pipeline · Calendar · Companies · Contacts · Messages · Reports ·
  Settings.
- Settings (`/settings`, replaces Setup): you, BCC capture, calendar, backup,
  enrichment provider, outcomes, the review queue (formerly Inbox), schedule
  status and version. `/setup` and `/inbox` redirect there.
- Reports: every number links to the rows behind it (`/reports/rows`).
- Help: `/help/<topic>` on every page (link in the nav) and `hermitcrm help
  <topic>` in the terminal, from Markdown shipped in the package; written to
  be read by people and AI agents alike.
- Merge: the picker offers the existing companies/contacts.
- Enrich works under launchd/systemd again: the CLI is looked up in
  /usr/local/bin, /opt/homebrew/bin and ~/.local/bin when PATH is bare, and
  `schedule install` sets PATH in the job.
- docs/LEARNINGS.md and TODO.md.

## 0.1.0 (2026-09-15)

First public release, by Gijs Bos.

- Guided setup: `hermitcrm init` asks three questions (you, BCC capture, backup;
  `--no-setup` skips them), `hermitcrm setup` reruns them, and the web app has a
  Setup page (`/setup`, CSRF-protected) that first-run redirects to once. An
  empty Board offers Import, Add a company and Set up BCC capture.
- `hermitcrm schedule install [--at HH:MM] [--serve]`, `remove` and `status`:
  a daily `sync --apply` via launchd (macOS) or systemd user units (Linux);
  Windows gets the `schtasks` command to run.
- `hermitcrm doctor [--online]`: one ok/warn/fail line per check (Python, git,
  data folder, migrations, config, secrets, IMAP login, calendar, schedule,
  git remote and last push, enrich CLI, updates); exits 1 on a failure.
- A CRM that is a folder of Markdown files with YAML front matter in git; every
  write is one commit.
- `hermitcrm init DIR [--demo]`: a data folder with a commented `config.toml`,
  agent rules (`CLAUDE.md` / `AGENTS.md`), a `MESSAGING.md` starter and optional
  demo data; `hermitcrm [--data DIR]` or `HERMITCRM_DATA` to point at it.
- Local web app (`hermitcrm serve`): pipeline board, companies and contacts tables
  with filters, calendar of next steps, company timelines, merge, Messages tab,
  Reports (activity, funnel, outcomes, messages, hygiene).
- Deterministic outreach drafts in English, German, Dutch and French, with the
  wording in `default_messages.toml` and an optional `messages.toml` override.
- BCC import over Gmail IMAP and calendar import from a secret ICS feed, with an
  Inbox for unmatched items.
- Import from CSV, TSV and `.xlsx`; enrichment from a URL or any AI CLI.
- Secrets from `HERMITCRM_*` environment variables, `.secrets.toml` or the macOS
  Keychain.
- Data format versions with automatic, one-commit migrations
  (`hermitcrm migrate --dry-run`); unknown front-matter keys are preserved.
- Any ISO 3166-1 alpha-2 country; `UK`/`USA` are stored as `GB`/`US`.
- `hermitcrm --version`, version in the footer, and a daily non-blocking update check.
