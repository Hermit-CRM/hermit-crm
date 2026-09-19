# Hermit CRM architecture

The specification Hermit CRM was built against: a single-user, local, file-based
CRM. The Markdown files under `companies/` are the only source of truth; the
web app and the CLI are thin layers that read and write them, and anything
they do can also be done by editing a file by hand and committing.

Invariants:

- Every file write is deterministic: fixed key order in front matter (unknown
  keys follow, sorted), `YYYY-MM-DD` for dates, `YYYY-MM-DDTHH:MM` (local time,
  no seconds) for datetimes, empty keys written as `key:`, bodies preserved
  byte for byte. Two writes of the same data produce identical files.
- The web app binds to `127.0.0.1` only and has no authentication.
- Code (the `hermitcrm` package) and data (a data folder) are separate; the data
  folder carries its format version in `.hermitcrm-format` and is migrated by
  `hermitcrm/migrations.py` in one commit.
- No database, no ORM, no JS framework, no build step, no CSS framework.

## 1. Layout

Code (this repository):

```text
src/hermitcrm/
├── cli.py                 # `hermitcrm` entry point (§6)
├── datafolder.py          # --data resolution, `hermitcrm init [--demo]`, config docs, agent rules
├── setup.py               # setup steps and settings sections shared by the CLI and /settings
├── schedule.py            # `hermitcrm schedule`: launchd / systemd units for the daily sync
├── doctor.py              # `hermitcrm doctor`: one ok/warn/fail line per check
├── models.py              # dataclasses, enums, validation, (de)serialisation
├── store.py               # file store and in-memory index (§3), DEFAULT_CONFIG
├── gitops.py              # commit and push (§4)
├── pipeline.py            # PIPELINE.md (§5)
├── migrations.py          # data format versions and migrations
├── secrets.py             # env, .secrets.toml, macOS Keychain
├── updates.py             # daily PyPI update check
├── messaging.py           # outreach drafts (§8.3) + default_messages.toml
├── bcc.py, calendar_sync.py, importer.py, enrich.py, scrape.py, filters.py, reports.py
├── help/                  # help pages (§7): __init__.py renders <topic>.md, topic_for(path)
├── web.py                 # FastAPI app factory and routes (§8)
├── templates/*.html
└── static/style.css
tests/
docs/ARCHITECTURE.md
```

Data (a folder created by `hermitcrm init`):

```text
<data>/
├── config.toml                   # every key optional, commented defaults
├── messages.toml                 # optional, deep-merged over default_messages.toml
├── .secrets.toml                 # optional, gitignored, mode 600
├── .hermitcrm-format                # data format version (integer)
├── PIPELINE.md                   # generated, never edited by hand
├── CLAUDE.md, AGENTS.md          # rules for AI agents
├── MESSAGING.md                  # your outreach playbook (§8.3)
├── inbox/                        # BCC and calendar items awaiting a decision
└── companies/<slug>/
    ├── company.md
    ├── contacts/<contact-slug>.md
    └── interactions/<id>.md
```

## 2. Data model

Three entities. A company owns contacts and interactions through its folder. An interaction belongs to a contact (by slug) or to the company alone.

### Company: `companies/<slug>/company.md`

Front matter keys, in this exact order:

| Key | Type | Rules |
|---|---|---|
| name | str | required |
| slug | str | equals folder name; immutable after creation |
| website | str | optional; normalise to include scheme |
| linkedin | str | optional |
| country | enum or empty | optional: `DE`, `CH`, `NL`, `SE`, `DK`, `NO`, `UK`, `USA`, `AT`, `FR`. Also picks the outreach language: DE/AT/CH German, NL Dutch, FR French, everything else English. |
| source | enum | `linkedin-search`, `referral`, `inbound`, `event`, `list`, `network`, `other`; default `other` |
| stage | enum | `prospect`, `engaged`, `discovery`, `offer`, `won`, `lost`, `disqualified`, `temp-disqualified`; default `prospect`. `won`, `lost` and `disqualified` are closed. `temp-disqualified` is parked: off the board, hidden in the Companies table (a toggle shows it) and out of the silent list, but an open next step (a revisit) still shows on the Calendar. |
| stage_changed | date | set to today whenever stage changes; set on creation |
| lost_reason | str | the reason for `lost` (required), `disqualified` or `temp-disqualified` (optional); cleared when the stage leaves those three |
| requalify_on | date or empty | only while `temp-disqualified`: the day the company goes back to `prospect` by itself (the web app sweeps on every page view and commits `company: <slug> requalified (parked until <date>)`); cleared whenever the stage is anything else |
| value_eur_month | int or empty | optional retainer estimate |
| my_score | int or empty | your own 0-10 interest score |
| fit_score | int or empty | 0-100 fit score from the source list |
| fte_estimate | str | headcount estimate as written, e.g. `~13` |
| ae_count | int or empty | account executives visible on LinkedIn |
| product_oneliner | str | one sentence on what the product does |
| next_step | str | one line, optional |
| next_step_due | date or empty | optional |
| next_step_status | enum | `open` or `done`; default `open`. A task is the pair next_step + next_step_due. Marking it done keeps the text but removes it from Today, Calendar and the overdue list. Rewriting next_step, or clearing the task, resets the status to `open`. |
| tags | list of str | may be empty `[]` |
| stage_history | list of maps | append-only, one `{date: YYYY-MM-DD, from: x, to: y, reason: z}` per stage change made through the store (update, disqualify, requalify, merge, creation in a stage other than prospect with `from: ''`); `reason` omitted when empty; the key is omitted while the list is empty. Merging combines both lists sorted by date. Derived: `closed_on`, `entered_stage_on(stage)`, `stage_durations(today)`. `hermitcrm backfill-history` fills it from git once. |
| created | datetime | set on creation |
| updated | datetime | set on every write of this file |

Body: free Markdown notes.

### Contact: `companies/<slug>/contacts/<contact-slug>.md`

Keys in order: `first_name`, `last_name` (at least one required; a file that still carries a single `name` key is read by splitting on the first space and rewritten with both keys on its next save), `slug`, `title`, `linkedin`, `email`, `phone`, `role` (enum, optional: `champion`, `decision-maker`, `influencer`, `gatekeeper`), `created`, `updated`. Body: notes. Emails are stored lowercase.

### Interaction: `companies/<slug>/interactions/<id>.md`

Keys in order: `date` (datetime, required, defaults to now, editable), `channel` (enum: `email`, `linkedin`, `call`, `meeting`), `direction` (enum: `out`, `in`), `contact` (contact slug or empty for company-level), `subject` (str, optional, one line), `outcome` (one of the `outcomes` in config.toml, default `successful`, `unsuccessful`; empty means not yet known; the store refuses other values unless the file already holds one, and a legacy `result` key was folded in by migration 3), `source` (enum: `manual`, `bcc-import`, `calendar-import`), `message_id` (only on imports, the dedup key: the mail's Message-ID, or `ical:<UID>:<RECURRENCE-ID>:<attendee email>` for a meeting). A `meeting` is never a message on the Messages tab. Body: the pasted message or call notes verbatim; for BCC imports, the mail's new text with the quoted thread cut once at import.

An outbound interaction with a body is a *message*. Its status on the Messages tab is `outcome` when set; otherwise the first configured outcome when an inbound interaction from the same contact (or a company-level one) was logged later; otherwise the last configured outcome once it is `message_window_days` (default 14) old; otherwise `unknown`.

File id: `{date:%Y-%m-%dT%H%M}-{channel}-{direction}-{contact_slug or 'company'}`. On collision append `-2`, `-3`. The id is the interaction's identifier in URLs; renaming on date edit is allowed (write new file, delete old, one commit).

### Slugs

Lowercase ASCII, words joined by single hyphens, max 60 chars. Transliterate before stripping: `ä→ae ö→oe ü→ue ß→ss é→e` and so on (use a small explicit map plus `unicodedata` NFKD fallback). Strip legal suffixes only for the slug, not the name: `gmbh`, `ag`, `se`, `bv`, `b.v.`, `ltd`, `inc`, `sas`, `sarl`, `kg`, `ug`, `co`. Ensure uniqueness within scope (company slugs across `companies/`, contact slugs within one company) by suffixing `-2`, `-3`.

## 3. Store and index (`store.py`)

- On startup, walk `companies/`, parse every file with `python-frontmatter`, validate against the enums, and build an in-memory index: `companies: dict[slug, Company]`, each with `contacts: dict[slug, Contact]` and `interactions: list[Interaction]` sorted by date descending.
- Validation failures (unknown enum, missing required key, contact slug referenced by an interaction that does not exist) do not crash the app. Log them, load what is loadable, and surface them on `/health` and in `hermitcrm check`.
- Derived per company (computed, never written to the file): `last_touch` (max interaction date), `last_touch_summary` (`email out 2026-09-14 (jane-doe)`), `interaction_count`, `days_in_stage`, `next_step_overdue` (bool), `silent_days` (days since last touch, or since `created` if none), `requalify_due` (parked with a `requalify_on` that has arrived), `language` (outreach language from `country`), and `message_status(interaction)` (an outcome or unknown, see §2).
- `Store.requalify_due()` moves every temp-disqualified company whose `requalify_on` has arrived back to `prospect`, in one commit. It is idempotent; the web app calls it on every GET request, so no scheduler is needed.
- Company page requests re-parse that company's folder before rendering, so edits made outside the app (by hand or by Claude Code) show up without a restart. `POST /reload` and `hermitcrm rebuild` rebuild the whole index.
- Write path for every mutation, in this order: write file(s) to disk; update index; regenerate `PIPELINE.md`; `gitops.commit(message)`; `gitops.push_async()`. If the commit fails, the write still stands; log loudly.

## 4. Git operations (`gitops.py`)

- `commit(message, paths)`: `git add -A -- <paths> && git commit -m <message> -- <paths>`
  from the repo root. No-op when nothing changed. The store records every file a
  write touches (`Store.take_touched()`), so a commit holds that write's own files
  and nothing else: anything else in the folder stays the user's to commit. `paths`
  of None means the whole tree, which is only right when the whole folder is ours.
- `push_async()`: if `push_enabled` in config, run `git push origin main` in a background thread with a 20 s timeout. Failures (offline, placeholder remote, auth) are logged at WARNING once per minute at most and never raised. On the next successful push everything catches up, because git.
- Commit message conventions:
  - `company: <slug> created`
  - `company: <slug> updated`
  - `company: <slug> stage <old> -> <new>`
  - `company: <slug> next step done|reopened`
  - `contact: <company-slug>/<contact-slug> created|updated`
  - `interaction: <company-slug> <channel> <direction> <contact-slug|company> <date>`
  - `interaction: <company-slug> <id> updated`
  - `interaction: <company-slug> deleted <id>`
  - `company: <drop-slug> merged into <keep-slug>`, `contact: <company-slug>/<drop-slug> merged into <keep-slug>`
  - `company: <slug> requalified (parked until <date>)`, or `company: requalified <slug>, <slug> (parked until today)` when several come back at once
  - `interaction: <company-slug> <id> outcome <value>|unknown`
  - `company: <slug> fetched from <url>` (only from `hermitcrm fetch --apply`; the web Fetch button applies through the enrich page and commits `ai: company <slug> enriched`)
  - `import: <n> companies created, <m> updated, <k> contacts created` (companies mode) or `import: <n> contacts created, <m> updated, <k> companies created` (contacts mode); one commit per import
  - `bcc: imported <n> mails (<i> interactions, <c> contacts, <r> to review)` (one commit per BCC run, none when nothing new), `bcc: <item> assigned to <slug>/<contact>`, `bcc: <item> discarded`
  - `calendar: imported <n> events (<i> interactions, <c> contacts, <r> to review)` (one commit per calendar run, none when nothing new); meeting inbox items use `calendar: <item> assigned to …` / `calendar: <item> discarded`
  - `ai: company <slug> enriched`, `ai: contact <company-slug>/<contact-slug> enriched`
  - `pipeline: rebuild` (only from the CLI rebuild)
- The app never runs destructive git commands. Rollback is documented in README as manual `git checkout <sha> -- <path>` and `git revert`.

## 5. PIPELINE.md (`pipeline.py`)

Regenerated on every write and by `hermitcrm rebuild`. Exact format:

```markdown
# Pipeline  (generated 2026-09-14 10:31, do not edit)

## offer (2, 11,000 EUR/month)
- acme-gmbh | Acme GmbH | in stage 4d | last: email out 2026-09-14 (jane-doe) | next: Send proposal outline, due 2026-09-18
- ...

## discovery (5, 0 EUR/month)
...

## prospect (23)
...

## Overdue next steps (3)
- beta-ag | discovery | due 2026-09-09 | Follow up on LinkedIn reply

## Silent for 14+ days, not closed (7)
- gamma-gmbh | discovery | last touch 2026-08-27 (18d)

## Closed last 90 days
- won: delta-gmbh (2026-08-30)
- lost: epsilon-gmbh (2026-08-12, no budget); zeta-ag (2026-09-01, chose in-house hire)
```

Rules: after the silent section comes `## Temp disqualified (N)` with one line per parked company (`- slug | since date | reason | next: ...`, or `since date until date` when `requalify_on` is set), and the closed section adds `- disqualified: slug (date, reason)`. Open stages in the order offer, discovery, engaged, prospect; within a stage, sort by `next_step_due` ascending with empty dates last, then by `last_touch` descending. Monthly value in the stage header is the sum of `value_eur_month`, omitted for engaged and prospect. A done next step is shown as `next: <text>, due <date> (done)` and never counts as overdue. `last:` shows `none` when there are no interactions. `next:` shows `none` when empty. Silent threshold comes from `config.toml` (`silent_days = 14`). Every line is one company; never include interaction bodies or notes. Target: roughly 30 tokens per company.

## 6. CLI (`hermitcrm/cli.py`)

`hermitcrm serve` starts uvicorn on the configured port.

`hermitcrm digest --days N` prints, oldest first, one block per interaction in the window: `2026-09-14 10:30 | email out | acme-gmbh / jane-doe | Notes from our call | outcome: -` followed by the first 150 characters of the body on the next line, whitespace collapsed. Ends with one summary line: counts by channel and direction, number of companies touched.

`hermitcrm show <company-slug>` prints: the company front matter as `key: value` lines and the notes body; then each contact as one line (`jane-doe | Co-founder & CEO | jane@acme.de | decision-maker`); then every interaction as one line (`2026-09-14 10:30 | email out | jane-doe | subject | outcome`); then the full bodies of the three most recent interactions, each preceded by its one-line header. `--bodies N` overrides three; `--all` prints every body.

`hermitcrm rebuild` rebuilds the index and PIPELINE.md and commits `pipeline: rebuild` if it changed.

`hermitcrm check` validates every file and prints problems with file paths; exit code 1 if any.

`hermitcrm import <file> [--mode companies|contacts] [--map "Header=field" ...] [--apply]` plans a bulk import from a TSV, CSV or .xlsx file (stdlib zip + XML: first worksheet, dates stay serial numbers) and prints the mode, the column mapping and one line per row with the action: create, update (fills empty fields only), keep (contacts mode: company unchanged) or skip. Companies mode needs a `name` column; contacts mode needs a person name column and takes the company from a company column or a non-freemail email domain, matching companies by slug or website domain and contacts by email, else by name. `detect_mode` picks contacts when there is a person-name or email column plus a company column and no company-only column. Header aliases (including HubSpot, Apollo, LinkedIn, Pipedrive and Attio export names) live in `hermitcrm/importer.py` and are listed on the Import page; the preview can remap every column (a field, `notes` or `ignore`). Without `--apply` nothing is written.

`hermitcrm fetch <slug> [--url <website or LinkedIn company URL>] [--apply]` reads that one page with the standard library (no AI, no credits): title, meta description, links, JSON-LD and the domain's country TLD become proposals for the empty fields among website, linkedin, country, fte_estimate and product_oneliner. LinkedIn serves its public company page to some anonymous requests and refuses others (HTTP 999); the error says so. The web version is the "Fetch from URL" button next to Enrich.

`hermitcrm bcc [--apply] [--eml FILE ...]` imports mail BCC'd or forwarded to `bcc_address` (`hermitcrm/bcc.py`, standard library only). It logs in to Gmail over IMAP with an app password (see `hermitcrm/secrets.py`: `HERMITCRM_BCC_PASSWORD`, `.secrets.toml`, or the macOS Keychain), opens the folder flagged `\All`, searches `X-GM-RAW "deliveredto:<bcc_address> newer_than:<bcc_lookback_days>d"`, and with `--apply` marks every fetched mail `\Seen`. Per mail: from one of `my_addresses` means outbound to every To/Cc address; a forward (Gmail marker, or an Outlook header block under a Fwd/FW/WG/TR subject) is inbound from the original sender, or outbound when the original was yours. Addresses that are yours, the BCC address, or at `bcc_ignore_domains` are dropped. Per remaining address: an exact contact email match logs there; otherwise exactly one company whose website host (or a contact's email domain, freemail excluded) matches logs at the contact there with the same name and no email yet (filling in the email), or else creates the contact first; otherwise the mail goes to `inbox/`. Dedup by Message-ID against interactions (same contact), inbox items and `inbox/discarded.tsv`. The whole run is one commit, and every `--apply` run writes `inbox/.last-run.json` (ok, summary or error). Afterwards it POSTs `/reload` to a running web app.

`hermitcrm report [--days N | --from D --to D] [--md]` prints the Reports page as aligned text tables, or Markdown with `--md`; default the last 30 days.

`hermitcrm backfill-history [--apply]` rebuilds `stage_history` for companies without one from `git log --follow` of their `company.md` and `git show <sha>:<path>` of each version (stage per commit, first entry from `''` dated `created`). Prints the plan; `--apply` writes one commit `ai: backfill stage history for N companies`.

`hermitcrm calendar [--apply] [--ics FILE ...]` imports past meetings from a secret ICS feed (`hermitcrm/calendar_sync.py`, standard library only, no OAuth). URL order: `$CRM_CALENDAR_URL`, Keychain (`security find-generic-password -s crm-calendar -a ics -w`), `.secrets.toml` key `calendar_ics_url`; `webcal://` becomes https; 10 MB cap. The parser unfolds lines, unescapes text, and reads DTSTART/DTEND as UTC, TZID (zoneinfo, converted to naive local time), floating or all-day. Skipped: cancelled events, RRULE masters (a RECURRENCE-ID override is a single event), titles containing a `calendar_ignore_titles` entry, fewer than `calendar_min_attendees` participants (rooms excluded). Past events (end <= now, within `calendar_lookback_days`): each external attendee (attendees plus organizer, minus `my_addresses`, `bcc_ignore_domains`, declined attendees and Google resource/group calendars) goes through the BCC matching (`bcc.handle_entry`) as a `meeting` interaction, `out` when you organised it, subject = SUMMARY, body = DESCRIPTION (500 chars), date = DTSTART; unmatched ones become `kind: meeting` inbox items. Events in the next 7 days with a matched company go to `inbox/upcoming.json`. `--apply` runs write `inbox/.last-calendar-run.json`; its failure or staleness flags the nav only while a URL is configured. `hermitcrm sync [--apply]` runs bcc then calendar (calendar skipped quietly without a URL).

`hermitcrm enrich <slug> [--contact <cslug>] [--apply]` asks an AI CLI (`enrich_provider` = auto | claude | codex | gemini | grok | custom, plus `enrich_command`, `enrich_model`, `enrich_timeout` in config.toml; auto takes the first CLI on PATH; each provider in `hermitcrm/enrich.py` builds its argv, environment and output parser, and all output goes through `extract_json`) for the empty fields of a company (website, linkedin, country, fte_estimate, ae_count, product_oneliner) or a contact (title, linkedin) and prints the proposal with sources. Only `--apply` writes, with an `ai:` commit. Nothing is ever guessed silently: unverifiable fields come back as "not found".

`hermitcrm help [topic]` prints a help page as Markdown (§7); without a topic, the index and the topic list. It needs no data folder.

Output of `digest` and `show` is plain text meant to be pasted or piped into an AI session, so no ANSI colour, no tables wider than 120 characters.

## 7. Agent rules and help

`hermitcrm init` writes `CLAUDE.md` and `AGENTS.md` into the data folder; the text is
`AGENT_RULES` in `hermitcrm/datafolder.py`. Its last reading rule points at `hermitcrm help`.

Help lives in `hermitcrm/help/<topic>.md` (package data): one short page per topic
(`index`, `pipeline`, `calendar`, `companies`, `contacts`, `interactions`, `messages`,
`reports`, `settings`, `import`, `enrich`, `merge`, `cli`, `data-format`, `ai-agents`),
each with a one-line summary under the title and a `Related:` line at the end, written
from the code so every statement is true. `hermitcrm/help/__init__.py` lists the topics
(`TOPICS`, in that order), reads them, renders Markdown to HTML with a small
dependency-free converter (headings, paragraphs, unordered and ordered lists, fenced
code, tables, inline code, bold, links; everything escaped, only http(s), site-relative
and fragment hrefs) and maps a request path to a topic (`topic_for`: `/` → pipeline,
`/companies/<slug>/contacts/…` → contacts, `…/interactions…` → interactions,
`…/merge` → merge, `…/enrich` and `…/fetch` → enrich, `/settings`, `/setup`, `/inbox` →
settings, `/help…` → index, and so on). The same pages are served at `/help` and
`/help/<topic>` and printed by `hermitcrm help`.

## 8. Web app (`web.py` + templates)

Server-rendered HTML. One base template with a top nav: Pipeline, Calendar, Companies, Contacts, Messages, Reports, Settings (with the review-queue count and a red `!` when the last import failed or is two days old), Reload, the search box, and a right-aligned Help link to `/help/<topic>` for the current page (§7). Vanilla JS only for: submitting the stage dropdown on change, and prefilling the quick-add interaction form. Plain, fast, readable on a 13-inch laptop, in light, dark or following the system (Settings > Appearance); the look and its tokens are in `DESIGN.md`.

| Method and route | Behaviour |
|---|---|
| GET `/` | Kanban board. Columns: prospect, engaged, discovery, offer; columns without companies are narrow so all four fit on screen. Won, lost, disqualified and temp-disqualified shown as collapsed lists below with counts and reasons. A filter bar above the board (§8.2) picks which columns show and filters the cards. Card: company name (link), days in stage, last touch summary, next step with due date (red if overdue), value if set, stage dropdown. |
| GET `/today` | Redirects to `/calendar#top-priority`; the Today lists live on the Calendar page. |
| GET `/calendar?month=YYYY-MM` | Top to bottom: **Top priority tasks** (open next steps due today or earlier, sorted by due date, each with a log-interaction link and a Mark done button), the month grid (Monday first, every open next step on its due date, past dates in red), **Future tasks** (every other open task, dated ones first by due date, then undated), and the silent list (accounts silent for `silent_days`+ and not closed, sorted by silent days descending). Defaults to the current month. |
| GET `/companies?q=&parked=1` | "New company" and "Import" buttons above the table (the Contacts tab has "New contact" and "Import" likewise; `/import?mode=` preselects the mode). Table with a filter row under the header (§8.2) and a links column (website, LinkedIn): name, country, stage, source, my score, fit score, FTE, tags, last touch, next step, due. Temp-disqualified companies are hidden unless `parked=1` (a "Show / Hide temp disqualified (N)" link above the table) or the stage filter names them. `q` matches company name, tags, contact names and contact emails, case-insensitive substring. |
| GET `/companies/new`, POST `/companies` | Create form: name (required), website, linkedin, source, stage, value, next_step, next_step_due, tags (comma separated), notes. Redirect to the company page. |
| GET `/companies/{slug}` | Company overview: all fields with an inline edit form (or an Edit toggle), contacts list with role and email, an Add country button, a Mark done / Reopen button next to the next step, a **Tasks** section (next step, due, status, Mark done / Reopen, Google Calendar link and a form to write a new next step) between the drafts and Merge, mirrored on the contact page between Merge and Delete, the rolled-up timeline of every interaction across all contacts newest first (date, channel, direction, contact, subject, outcome, body collapsed behind a toggle), and the quick-add interaction form at the top with company fixed and the most recently touched contact preselected. Next to the next step: an "Add to Google Calendar" link (§8.1). |
| POST `/companies/{slug}` | Update fields. Changing stage sets `stage_changed`; setting stage to lost requires `lost_reason` (validation error otherwise); leaving lost clears it. |
| POST `/companies/{slug}/next-step` | Sets `next_step_status` from the Mark done / Reopen buttons; redirects back to the referring page (anchored at `#tasks` on a company or contact page). |
| POST `/companies/{slug}/task` | Sets `next_step` and `next_step_due` from the Tasks section on the company or contact page; the task starts open. Commit message `company: <slug> next step set`; redirects back to the referring page at `#tasks`. |
| POST `/companies/{slug}/country` | Sets the country from the Add country button on the company page. |
| POST `/companies/{slug}/stage` | Stage change from the board dropdown. If new stage is lost, redirect to the company page with the lost_reason field focused instead of saving. |
| GET `/companies/{slug}/contacts/new`, POST `/companies/{slug}/contacts` | Create contact (first name, last name, title, role, email, phone, linkedin, notes). A contact anywhere with the same email, or one at this company with the same normalised name, re-renders the form with the matches linked and a "Create anyway" checkbox (`force=1`). |
| GET `/contacts/new`, POST `/contacts` | New contact without picking a company first: name (required), email, title, linkedin, company (required; a datalist of every company name) and website (used only for a new company). The company is resolved by slug or name (case-insensitive), else by the email's domain (`bcc.match_address`), else created in the default stage with the given website or `https://<email domain>` (not for freemail). Same duplicate check as above, plus: when a company would be created, an existing one with the same name ignoring legal suffixes or the same website domain. One commit: `contact: <slug>/<contact-slug> created [with company <slug>]`. |
| GET `/contacts?q=` | Contacts tab: every contact across companies (name, company, title, email as mailto, LinkedIn link, last touch, interaction count) with search and a filter row (§8.2). Role stays on the contact page only. |
| GET `/reports?period=7d\|30d\|90d\|quarter\|ytd\|custom&from=&to=` | Reports (`hermitcrm/reports.py`, default 30d) with deltas against the previous period of equal length: activity (interactions per ISO week, channel and direction; companies touched; new companies and contacts), funnel (entries per stage from `stage_history`, conversion between prospect, engaged, discovery, offer and won, median days in stage, current pipeline with value), outcomes (won, lost, disqualified by `closed_on` else `stage_changed`, win rate, top 10 lost reasons), messages (sent, success / unsuccessful / unknown by language, channel and top 5 reused texts), sources (created and won), hygiene (overdue, silent, contacts without email). Tables and CSS bars. The company page shows the stage history collapsed. |
| GET `/messages?q=` | Messages tab: every outbound interaction with a body, newest first: sent, company, contact, channel, country, stage, outcome (see §2), how many times that exact text was used, the message (collapsed), and one button per configured outcome plus Unknown. Filters, sorting and search (§8.2). |
| POST `/companies/{slug}/interactions/{id}/outcome` | Sets `outcome` on a sent message from those buttons (form field `outcome`); redirects back to the referring page. Commit `interaction: <slug> <id> outcome <value>`. The interaction edit form writes the same key, so both views always agree. |
| POST `/companies/{slug}/disqualify` | Disqualify / Temp disqualify buttons (with an optional reason; Temp disqualify also takes an "until" date that becomes `requalify_on`) and Requalify (back to prospect) on the company page. |
| POST `/companies/{slug}/fetch` | "Fetch from URL" on the company page: reads the given website or LinkedIn company URL (defaults to the company's own) with `scrape.py` and shows the same proposal page as Enrich, applied through `/enrich/apply`. No AI, no credits. |
| GET `/companies/{slug}/merge?drop=`, POST `/companies/{slug}/merge` | Merge another company into this one; the picker on the company page is a text input with a datalist of slugs and names (a name is accepted too). The page shows every field side by side with a radio per side; the default is this company's value, or the other's when this one is empty; tags and notes can be combined. Contacts and interactions move over (slug collisions get -2), the dropped folder is deleted, one commit. Same pair for contacts within a company under `/companies/{slug}/contacts/{cslug}/merge`; their interactions are re-pointed and renamed. |
| GET `/companies/{slug}/contacts/{cslug}?signal=&observation=` | Contact overview: fields, edit form, this contact's interactions newest first, quick-add form with this contact preselected, and a Message drafts section (§8.3). The company page shows the same section for its preselected contact. |
| POST `/companies/{slug}/contacts/{cslug}` | Update contact. |
| POST `/companies/{slug}/contacts/{cslug}/delete` | Delete contact (browser confirm). Its interactions stay with `contact` cleared (renamed to `…-company`), one commit `contact: <slug>/<cslug> deleted`. |
| GET `/companies/{slug}/interactions/new?contact=&channel=&body=` | Quick-add form: channel (radio, default linkedin), direction (radio, default out), contact (select, includes "company only"), date (datetime-local, default now), subject, outcome, body (large textarea). `channel` and `body` prefill the form (used by "log as sent" under a draft). |
| POST `/companies/{slug}/interactions` | Create. A company in `prospect` moves to `engaged` in the same commit (`…; stage prospect -> engaged`); this lives in `Store.create_interaction`, so imports do it too. Redirect back to the company page with the timeline scrolled to the new entry. |
| GET/POST `/companies/{slug}/interactions/{id}/edit` | Edit an interaction, including date. The page also carries a Delete button (browser confirm). |
| POST `/companies/{slug}/interactions/{id}/delete` | Delete an interaction (also from the small "delete" control next to each timeline entry). The file is removed and committed as `interaction: <slug> deleted <id>`; 404 for an unknown id. |
| GET `/import`, POST `/import/preview`, POST `/import` | Bulk import. Paste a tab-separated table or upload a .tsv/.csv. Preview lists every row with its planned action (create, update of empty fields only, skip) and warnings (unmapped country, non-numeric score) before anything is written; the import itself is one commit. Contact columns are prefixed `founder_` or `contact_`; unknown columns are kept as `column: value` lines in the notes. |
| POST `/companies/{slug}/enrich`, POST `/companies/{slug}/enrich/apply` | Enrich button on the company page: runs the lookup (can take a minute), shows proposed values for empty fields with a checkbox and an editable input each, plus sources. Apply writes only the ticked fields. Same pair for contacts under `/companies/{slug}/contacts/{cslug}/enrich`. |
| GET `/settings` | The Settings page, always in the nav; the first request to `/` without an `owner_email` redirects here once per server start ("Skip for now" goes back). Sections, each an `id` anchor: **You**, **BCC capture**, **Calendar**, **Backup** (the setup steps of `hermitcrm/setup.py`, with done/pending badges), **Enrichment** (`enrich_provider`, `enrich_command`, `enrich_model`, `enrich_timeout`; shows the resolved provider or `unavailable_reason()` with the bare-PATH hint), **Outcomes** (`outcomes` as a one-per-line textarea, `message_window_days`, `silent_days`), the **Review queue** (below), **Schedule** (read-only `schedule.status()` plus the install command) and **About** (version, update check, data folder, data format, `hermitcrm doctor`). Plain settings are written to `config.toml` through `setup.set_config_values` (comments kept); every save re-reads the config and refreshes the store's silent threshold, the message window, the enricher, BCC and calendar settings without a restart. GET `/setup` and `/inbox` redirect here with 301 (`/settings`, `/settings#inbox`). |
| POST `/settings/you`, `/settings/bcc`, `/settings/bcc/test`, `/settings/backup`, `/settings/calendar` | The setup steps; the same handlers also answer under `/setup/...`. CSRF: a per-process token in every form, checked with `hmac.compare_digest` (403 otherwise). Success redirects to `/settings?flash=...#<section>`; a validation error re-renders the whole page with status 400 and the values kept. |
| POST `/settings/enrichment`, POST `/settings/outcomes` | Same pattern. Enrichment refuses an unknown provider, `custom` without a command, and a timeout below 1. Outcomes refuses an empty list, a duplicate (case-insensitive) and day counts below 1. |
| Review queue (`/settings#inbox`) | The former BCC inbox: the tracking address, the last import (time and summary, or the error), an Import now button, the last meeting import with its button, and every mail or meeting waiting for a company with its reason (personal address, unknown domain, several matches), the body collapsed, a company field (datalist of slugs), first and last name prefilled, and Log at company / Discard buttons. The nav shows `Settings (N)` and a red `!` when the last run failed or is two days old. |
| POST `/bcc/import` | Import now: the same run as `hermitcrm bcc --apply`; flashes the summary or the error at `/settings#inbox`. |
| POST `/calendar/import` | "Import meetings now" (on `/settings` and `/calendar`, form field `back`; `/inbox` is still accepted as the old name and lands on `/settings#inbox`): the same run as `hermitcrm calendar --apply`; flashes the summary or the error. `/calendar` shows **Meetings this week** from `inbox/upcoming.json`, each row linked to its companies. |
| POST `/inbox/{id}/assign`, POST `/inbox/{id}/discard` | Log a queued item at a company (uses the contact with that email, else fills the email of a same-named contact without one, else creates the contact) in one commit; or discard it (remembered in `inbox/discarded.tsv`). Both redirect to `/settings#inbox`; an unknown company re-renders the Settings page with status 400. |
| GET `/help`, GET `/help/{topic}` | The help pages (§7) rendered inside the base template with a topic list on the left; unknown topic → 404. |
| POST `/reload` | Rebuild index, redirect back. |
| GET `/health` | JSON: counts, last commit sha, last push status and time, validation problems. |

Global: a search box in the nav that submits to `/companies?q=`. Flash messages after writes. Form validation errors re-render the form with the values kept.

### 8.2 Column filters and sorting

Board, Companies, Contacts and Messages carry one control per column, submitted as `f_<column>` query params (GET, bookmarkable). Enum columns (stage, country, source, channel, outcome) are multi-selects. Every other column is a text box with a tiny syntax: `text` contains, `!text` does not contain, `=text` equals, `>x` larger, `<x` smaller (numbers, `YYYY-MM-DD` dates, otherwise text order), `-` empty, `*` not empty. Filters combine with AND and with the `q` search. Every heading has ▲ (A to Z, small to large, old to new) and ▼ (Z to A) links that set `sort=<column>&dir=asc|desc`; empty values sort last; the sort survives filter submits. The syntax explainer sits above each table behind a "?" that opens on hover or keyboard focus (pure CSS, no JavaScript). Implemented in `hermitcrm/filters.py`.

### 8.3 Message drafts (no AI)

`hermitcrm/messaging.py` renders three deliberately different drafts per contact from CRM data alone, in the language of the company's country (German for DE/AT/CH/LI, Dutch for NL, French for FR/LU/MC, otherwise English): (1) *scale* (they are growing; offer help to keep the pace) or, when the signal is "hiring", *bridge* (help while the role is open), or, when it is "declining", *decline* (a tough stretch, then an open question; falls back to *scale* when a `messages.toml` lacks the key); (2) *unblock* (past the next headcount hurdle: 10, 20, 50, 100, 250, 500 derived from `fte_estimate`); (3) *hook* (one observation, then an open question). Two inputs are yours: a `signal` (growing / stalled / declining / hiring, read off LinkedIn company insights, linked from the section) and one `observation` sentence from their website or team. Anything the CRM cannot know is left in square brackets. The wording lives in `hermitcrm/default_messages.toml`; `<data>/messages.toml` is deep-merged over it, and the sign-off uses `owner_name`. "Log as sent" opens the quick-add form with the draft as body and channel linkedin. `MESSAGING.md` in the data folder is the playbook.

### 8.1 Google Calendar link

Build `https://calendar.google.com/calendar/render?action=TEMPLATE&text=<company name>: <next_step>&dates=<YYYYMMDD>/<YYYYMMDD+1>&details=<next step text>%0A%0Ahttp://127.0.0.1:8765/companies/<slug>` with an all-day event on `next_step_due`. Hide the link when there is no due date. Open in a new tab. No API, no OAuth.

## 9. Acceptance scenario (covered by the test suite)

1. Create company "Müller & Söhne GmbH", source referral, stage prospect. Expect folder `companies/mueller-soehne/`, `stage_changed` today, one commit `company: mueller-soehne created`.
2. Create contact "Anna Müller", title CEO, email `Anna@Mueller.de`. Expect `contacts/anna-mueller.md`, email stored lowercase.
3. Create a second contact "Jonas Berg".
4. Log an interaction: linkedin out to anna-mueller, dated 2026-09-08 09:12. Then an email in from anna-mueller dated 2026-09-11 16:40. Then a call, company-level, dated 2026-09-14 10:30 with notes. Expect three files with the specified ids, and the company page timeline showing all three newest first with the correct contact labels.
5. Change stage to discovery from the board dropdown. Expect `stage_changed` today and commit `company: mueller-soehne stage prospect -> discovery`.
6. Set next step "Send proposal outline" due yesterday. Expect the company under "Top priority tasks" on `/calendar` and under "Overdue next steps" in `PIPELINE.md`, and the calendar link present with the correct dates parameter.
7. Set stage to lost without a reason: expect a validation error and no file change. Set it with reason "no budget": expect the company listed under closed with the reason.
8. Run `hermitcrm show mueller-soehne` and `hermitcrm digest --days 30`; expect the formats of §6.
9. Roll back: `git checkout HEAD~1 -- companies/mueller-soehne/company.md`, `hermitcrm rebuild`; expect the company back in discovery on the board.
10. `hermitcrm check` exits 0. Break a file's enum by hand; `check` exits 1 and names the file; the app still serves.

