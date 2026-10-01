# Changelog

All notable changes to Hermit CRM. Versions follow semantic versioning; a change to
the data format always comes with an automatic migration.

## Unreleased

- **Notes are interactions.** `note` is a new interaction channel: a memo
  about a person, with no direction, on their timeline. It never counts as
  contact made (last touch, a prospect's stage, follow-ups, outcomes and
  reports ignore it). The contact form has no notes field any more;
  `add contact --notes`, the agent tool and the importer log a note instead.
- **Data format 7.** The migration moves each contact's notes into note
  interactions (a line starting `DD/MM/YYYY:` dated that day, the rest dated
  the contact's creation) in one commit; contact front matter is unchanged.
- **Interactions are with a person.** The company page no longer has a log
  form; each contact has a **log** link in the company's contact list, and
  the standalone form asks for a contact. Message drafts moved below tasks on
  the company and contact pages.

## 0.4.1 (2026-09-23)

The first build offered for download on hermitcrm.io.

- **Support Hermit.** A Ko-fi link at the foot of the sidebar, in Settings
  and in Help. It opens in a new tab; the app loads nothing from Ko-fi.
- **Test data is made up.** A few importer test rows held names and websites
  of real people and companies. They are now invented ones; the tests check
  the same things.

## 0.4.0 (2026-09-22)

0.3.0 was never published as a release. Test builds went out under that
number, and each holds part of what is listed below.

**Hermit CRM is now Apache License 2.0, not MIT.** Apache 2.0 says the same
thing about warranty and liability in far more explicit words, and it adds a
patent grant and a trademark reservation that MIT has no wording for. The code
is as free as it was: use it, change it, sell it, keep your changes to
yourself. New beside it: `NOTICE`, `DISCLAIMER.md` (no warranty, your backups,
your integrations, in plain language), `SECURITY.md` (where to report, and that
a fix is not promised), and a DCO sign-off requirement in `CONTRIBUTING.md`
(`git commit -s`). Every source file carries the standard Apache header.

- **Local backups start from Settings.** Settings, Backup now leads with the
  backup on this computer: when it last ran and how big it is, in plain words,
  and a **Start local backups** button that makes the first one and schedules
  the rest every 5 minutes, with no terminal. Before, a new user was told to
  run two commands. Only the backup job is installed; the daily sync is left
  alone, and a backup job that already serves another folder is not moved.
  The path and `backup_dir` sit under "Where it is kept". Backup counts as
  done once a local backup has run; the git remote is now the optional
  "Online copy", and no longer what setup waits for.

- **A one-time disclaimer when the web app first opens a folder.** Three
  points -- no warranty, your backups are yours, your integrations are your
  responsibility -- a checkbox, and a link to the full text at
  `/help/disclaimer`. Ticking it writes the time to `disclaimer_accepted` in
  `config.toml` and it never appears again. Nothing is sent anywhere; there is
  nowhere to send it.

- A **sample account** for new users: **Look at a sample account** on the
  empty home page and on Getting started, or `hermitcrm sample add`, loads one
  made-up company (people, a message and its reply, a meeting, a deal at offer,
  a next step and tasks) marked `sample: true`. A bar on every page links to
  **Remove it**, which deletes only companies with that marker, in one commit
  (`hermitcrm sample remove`). The walkthrough does not count it, PIPELINE.md
  marks its line `sample (fictional)`, and new folders tell AI agents to leave
  it out.
- **The beginner help on the home page stays until you put it away.** It used
  to disappear the moment the first company existed -- two steps into ten --
  taking the ways in and the sample account with it, while *What this thing
  does* stayed for ever. Both are one block now, under your real lists once the
  folder has anything in it, and both go when Getting started is finished or
  when you press **Hide the tutorial** (the walkthrough's own switch).
- Fixed: **Open this at start again** on Getting started, and **Untick** on a
  step ticked by hand, did nothing. An empty form field never reaches the
  handler -- FastAPI puts the default in its place -- so the off button asked
  for "on".
- The `--demo` folder has eight companies now: every stage (disqualified and
  temp-disqualified too), tasks on companies and people, and a proposal that
  is still waiting for an answer.

Data format 6: the stage `reached-out` is renamed to **engaged** (in `stage`
and `stage_history`), the four built-in scoring fields become fields you
define, and every folder gets a `.claude/settings.json` that blocks
history-rewriting git commands. All migrate automatically in one commit.

- **On Linux the daily sync keeps running after you log out.** systemd user
  units stop at logout and do not start at boot unless lingering is on, so a
  server nobody was logged in to never ran its sync while `doctor` said
  `schedule: OK`. `schedule install` now runs `loginctl enable-linger` and says
  whether it worked (or prints the `sudo` line); `schedule status` shows
  `lingering: on/off`; `doctor` warns while it is off.

- **`schedule install` on Linux says so when systemd cannot be reached.** Over
  plain SSH, `su` or `sudo -u` there is no user D-Bus session, so every
  `systemctl --user` call fails. Install used to write the unit files, print
  `could not enable hermitcrm-sync.timer` among lines that read like success,
  and exit 0. It now stops with an `ERROR`, the `export
  XDG_RUNTIME_DIR=/run/user/<uid>` fix (and `loginctl enable-linger` first when
  the user manager is not running), and exit code 2.

- **BCC import creates the companies it does not know.** Mail you send or
  forward to someone at a domain no company has used to wait in the review
  queue; now the import creates the company (named after the domain, website
  `https://<domain>`), the contact and the interaction in one commit. Not for
  mail you did not send yourself, no-reply senders, personal addresses, or when
  a company of that name exists. `bcc_create_companies = false` restores the
  review queue. In the review queue, **Log at company** with a name that finds
  no company now creates it instead of refusing.

- **Backups that nothing can rewrite, and undo for any version.** Every change
  was already a commit, but the history itself was unprotected: a
  `git reset --hard`, an amend, a deleted `.git` or a force-push -- by you, a
  script or an AI agent -- lost it. `hermitcrm schedule install` now also runs
  `hermitcrm backup` every 5 minutes (`--backup-every`, `--no-backup`) into a
  bare repository outside the folder (`~/.hermitcrm/backups/`, or `backup_dir`)
  that refuses non-fast-forward pushes and deletions and never expires
  anything. Uncommitted edits are saved as snapshots without touching your
  branch or index; a rewritten history is kept beside the old one, with a
  warning in the log, `doctor` and Settings. `hermitcrm backup list [PATH]`
  finds a version and `hermitcrm backup restore ID [PATH ...] --apply` puts it
  back as a new commit, backing up the current state first. An idle run writes
  nothing, so the backup grows only with real edits (about 1 MB for a folder of
  350 companies). Help: Backups and undo; the agent rules in `CLAUDE.md` and
  `AGENTS.md` tell agents not to rewrite history and how to roll back.
- **Claude Code can no longer run the git commands that destroy history.**
  Every data folder gets a `.claude/settings.json` deny list (new folders from
  `init`, existing ones with format 6, merged into what is there): `git reset
  --hard`, `commit --amend`, `rebase`, `push --force`, `filter-branch`,
  `reflog expire`, `gc --prune`, `git clean -f`, the `git -C <dir>` forms,
  `rm -rf .git` / `companies` / `~/.hermitcrm`, and edits to the backup or the
  list itself. It holds in every permission mode. `doctor` warns when a rule
  is missing; `hermitcrm backup guard` puts them back. Pattern rules are a seat
  belt, not a lock, which the help says plainly; the backup covers the rest.
- **Fields of your own, and four fewer of somebody else's.** `my_score`,
  `fit_score`, `fte_estimate` and `ae_count` were built into every Hermit CRM.
  They were one person's way of working, and a new install met all four before
  it met a feature it asked for. They are gone, replaced by fields you define:
  a key, a label, a type (text, number, date or select) and where they show up,
  written in `fields.toml` beside your data and edited under Settings → Fields,
  one at a time or all at once. They work on companies, contacts and
  interactions; wherever one appears as a column it filters and sorts like any
  built-in field, the importer can map a spreadsheet column to it, and one that
  says `enrich = true` is offered to the AI. **A folder that used the old four
  keeps them**: the migration writes a `fields.toml` describing them and does
  not touch a single company file, because those keys were always ordinary
  front matter. A folder that never used them gets no file at all.
- **Your own look, in one file.** Put a `theme.css` in your data folder and the
  app uses it on top of its own styles: one `:root` block of colours and fonts,
  each colour written once for light and dark with `light-dark()`. Ask your AI
  tool to write it; Help > Settings has the template, Settings > Appearance says
  whether it is in use, and deleting it brings the default back. The defaults
  moved to `static/tokens.css`, which the website shares, so the default app and
  the site cannot drift apart. Every page now sends a Content-Security-Policy
  that allows only the app's own files, so a theme cannot load or send anything
  elsewhere; `hermitcrm doctor` names the line that tries.
- **The app takes the website's look.** Warm paper instead of cool grey, and
  the logo's green instead of blue for links, buttons and the keyboard focus
  ring, in light and dark. Page titles, the name in the menu and the numbers on
  Home are in the website's serif, and section labels are small caps. What you
  work in (the board, tables, forms) keeps the system sans at the same size.
  Fields you type in have borders you can see (3:1; they were 1.35:1). Your
  `theme.css` keeps working: `--title-font: var(--sans);` puts the titles back
  in sans, and Help > Settings has the earlier white, grey and blue look as a
  ready-made theme. Stylesheet URLs now carry a hash of the files, so an update
  shows its new look at once instead of the browser's cached copy.
- **A walkthrough, on first launch and under Help.** `/welcome` has ten steps
  -- who you are, a first company and contact, logging an interaction, moving a
  deal, next steps and tasks, BCC capture, the calendar, the extension, and
  finding things again -- each ticked by the data rather than by a click: "your
  first company" is done when a company exists. The two nothing can observe
  (installing a bookmarklet, learning the filters) are ticked by hand. A fresh
  start opens it once per server start until you dismiss it. **Show me around**
  runs a tour that points at each part of the screen, anchored to attributes on
  the elements themselves so a redesign cannot aim it at the wrong thing.
- **BCC capture explains itself, per mail provider.** Settings says how BCC
  capture works and offers Gmail, iCloud, Fastmail and Outlook presets that fill
  in the server and say where the app password lives -- and says plainly that
  Microsoft has switched off password sign-in for IMAP on most accounts, with
  the workaround.
- **The filter help says what it is.** `!text`, `=text`, `>5` and the rest were
  documented behind a bare `?` that nobody found; it now reads "what does !text
  mean?".
- **A home page, separate from the pipeline.** The logo and the Pipeline tab
  went to the same place, so the product had no front door, and on a fresh
  install that place was an empty board wearing three onboarding cards. `/` is
  now the home page -- what is due in the next seven days (next steps and tasks
  together), replies you owe, last month's numbers, and a grid saying in one
  line what each part of the app is for. The board moved to `/pipeline` with its
  own nav entry, and the ways to get started moved to the home page where a new
  folder will actually meet them.
- **Tasks: more than one per company, and one per person.** A company had
  exactly one thing you could write down -- its next step -- so a second thing
  you owed an account overwrote the first. Companies and contacts now each keep
  a `tasks` list in their front matter, with a due date and a done flag. The
  **next step is unchanged and still separate**: it is the one task that decides
  where the deal stands, and it is what the board, PIPELINE.md and the calendar
  read. Tasks are everything else. The calendar gained a **Create task** form
  and shows every open task on its due date; a contact's tasks show on their own
  page and, grouped under their name, on the company's. Deleting a contact takes
  their tasks with them and says how many are open first, and merging two
  records keeps both lists rather than choosing a side. Ticking off or deleting
  a task checks its text first, so a page left open in another tab cannot hit
  whatever moved into that position.
- **The extension reads the profile you are logged in to.** Capturing a person
  still fetched the profile again from your machine, logged out, and LinkedIn
  shows an ordinary member almost nothing that way: one in three real profiles
  answered HTTP 999 (an error page, no form), and the rest masked the job
  titles, which reached the title field as `['********** *** ***', ...]`. On a
  LinkedIn profile the bookmarklet now reads the page in your own tab -- name,
  headline, current company and its LinkedIn page, location, the current role
  from Experience as the title, and the email when Contact info is open -- and
  nothing is fetched at all. A company it creates keeps its LinkedIn page, so
  the next colleague you capture lands on the same record. It reads the order
  of lines and the labels screen readers get, never LinkedIn's scrambled class
  names; what it cannot place stays empty. Take the bookmarklet again from
  `/extension`; the old one keeps working the old way.
- **A profile address is one address.** `/in/x/overlay/contact-info/`,
  `nl.linkedin.com/in/x` and `/in/x?miniProfileUrn=...` are now stored as
  `https://www.linkedin.com/in/x`, and "already in the CRM" matches any of
  them, before anything is fetched. A profile LinkedIn will not show opens the
  contact form with its address and the name spelled in it, rather than an
  error. The serve log no longer keeps what a capture read: uvicorn wrote each
  captured address, query and all, to `~/Library/Logs/hermitcrm-serve.log`.
- **The extension captures a person.** A LinkedIn profile URL opened a form to
  create a *company* from it, because nothing in Hermit CRM recognised a profile
  page: the code only ever matched `linkedin.com/company/`. A profile now opens
  the new-contact form with the name, the headline as the title and the profile
  URL filled in, and the employer the page names typed into the company box --
  which matches an existing company, so capturing three people from one company
  gives you one record rather than three.
- **A person's headline is no longer read as a product one-liner.** Captured
  from a profile, `product_oneliner` came out as the headline with the
  experience, education and connection count stapled on. A profile yields none
  now, and the tail is stripped from company pages too.
- **The outreach playbook reads whichever fields you have.** Every field you
  define is a slot the templates can use by its key, so wording is data rather
  than code; an empty field renders as its label in square brackets, the mark
  the templates already use for the lines only you can write. Which field plays
  the two roles the shipped wording knows about -- a headcount, a count of sales
  people -- is set under Settings → Drafts, and defaults to the two keys a
  migrated folder already has, so nothing changes for a folder that had them. A
  new install has neither, and those sentences use their "unknown" wording
  instead of inventing a number.
- **Merging two records no longer drops what Hermit CRM does not recognise.**
  A merge rebuilt the kept record from the fields it knows by name, so every
  other front-matter key on both sides was silently lost. They are merged
  side by side now, choosable like any other field on the merge page. This
  affected merges before custom fields existed.
- **The AI CLI is asked how it is signed in.** A Codex CLI on a ChatGPT account
  refuses `gpt-5-mini`, the model Hermit CRM pinned for it, and both Enrich and
  Ask the Hermit died with the same 400 printed three times. Settings now has an
  **Account** choice -- subscription or API key -- for every provider; on a
  subscription Hermit CRM asks for no particular model where that is known to
  matter, so the CLI answers on whatever the plan gets. A provider that refuses a
  model now says so in one sentence naming the model and the setting, and a CLI
  that repeats itself no longer has its complaint printed three times.
- **"Ask Hermit" is now "Ask the Hermit"**, and the search box sits in the middle
  of the top bar with the Ask button in its corner, instead of both crowding the
  right-hand edge.
- **"Capture" is now "Extension"** (`/extension`; `/capture` still redirects, so a
  bookmarklet already in your bookmarks bar keeps working).
- **The company page header is two rows instead of six.** The country line is gone
  -- country is still on the record and in the edit form, where it goes on deciding
  which language a draft is written in -- and the two always-open disqualify panels
  became one menu.
- **Feedback form** (`/help/feedback`, in the Help sidebar). A tester writes what
  broke or confused them; Hermit CRM saves it as `feedback/<date>-<slug>.md`,
  commits it, and shows the text to copy or a prefilled mail link when
  `feedback_email` is set. Nothing is posted anywhere -- there is no server to post
  to, and adding one would undo the point. The report carries the version, Python,
  platform, record counts and which optional features are on; it deliberately
  carries no names, no company names and no file paths, since a data folder path
  is usually `/Users/<your name>/...`.
- **The update check no longer claims to be up to date when it failed.** Hermit
  CRM is not on PyPI, so the check 404s, and `doctor` answered `v0.3.0 is the
  latest` for a request that had never once succeeded. It now keeps "asked and we
  are current", "nothing published there yet" and "could not reach it" apart, and
  says which. New `update_url` key points the check at any URL answering
  `{"version": "0.4.0"}`, so a static file on a download page works with no
  package index; the upgrade hint follows the source.
- **`scripts/release.sh`**: builds `dist/hermitcrm-<version>.tar.gz` (unpacking to
  `hermitcrm-<version>/`) and its `.sha256`, from tracked files at a commit.
- **`hermitcrm init` explains a missing git** instead of ending in a
  `FileNotFoundError` traceback, and recognises Apple's command-line-tools stub
  rather than reporting it as a failed `git init`. INSTALL.md step 1 now also
  covers the Mac where nobody is logged in at the screen, so Apple's installer
  cannot open a window: `softwareupdate` with a password, or a conda-forge git in
  the home folder without one.

- Logging an interaction on a **prospect** moves it to **engaged** in the same
  commit (manual, BCC and calendar imports alike).
- **Follow-up radar on the home page** and `hermitcrm followups`: the threads
  where somebody wrote to you and you have not answered, and the ones where you
  wrote and nothing came back. Replies owed come first. A company with an open
  next step due in the future is left off the nudge list -- you have already
  decided what happens next, and the calendar owns that.
- **`hermitcrm mcp`: an MCP server for the data folder.** Ten tools over stdio
  (`list_pipeline`, `search_companies`, `show_company`, `digest`, `report`,
  `followups`, `brief`, and the three `add_*` writes), so Claude Desktop,
  ChatGPT, Cursor and anything else that speaks MCP can use the CRM without a
  terminal. No new dependency: MCP's stdio transport is newline-delimited
  JSON-RPC. The writes are the same `store.create_*` calls the web form and
  `hermitcrm add` make. See `hermitcrm help ai-agents` for a client config.
- **Capture from the page you are on**: a bookmarklet on the new **Capture**
  page reads the company website or LinkedIn page in front of you and opens a
  filled-in new-company form. `fetch` ran backwards for this -- it needed the
  record to exist first -- so capture inverts it. No extension to install. A
  page belonging to a company you already have takes you to that record instead
  of quietly making a second one.
- **Pre-meeting brief**: `hermitcrm brief`, and a folded "Brief" under every
  meeting on the Calendar page. Stage, open next step, contacts and the last
  three interactions for each company you are about to talk to. It reads the
  `upcoming.json` the calendar import already writes, so it is instant and works
  offline.
- **The pipeline board works on a phone**: the filter block folds behind a
  "Filters" toggle and the four stage columns stack, so the first screen is the
  follow-up radar and your companies rather than controls. Unchanged above
  760px.
- **The company page fits a phone**: at 390px it scrolled 110px sideways. Its
  tables (contacts, tasks, stage history) now scroll inside their own box, the
  Disqualify menu spans the header instead of running off the left edge, an
  open "Fetch from URL" field fills its row, and Compare in the merge form moves
  under the field when both do not fit. Unchanged above 760px.
- **Companies and Settings fit a phone too**, and the company page again: at
  390px Companies was ~1250px wide and Settings 413px. The companies table and
  the Settings fields table scroll inside their own box; a long data-folder path
  in Settings, About breaks instead of pushing the page. The new task row (task,
  for, due, Add task) had made every company page 508px wide; it wraps now, like
  every row of fields. A closed Disqualify menu no longer leaves its fields
  sitting past the right edge, and the filter help ("what does !text mean?")
  opens under the filter line within the screen. Unchanged above 760px.
- **`hermitcrm serve --host`** (config key `host`). `--host 0.0.0.0` puts the
  web app on your phone over the local network, and prints the address to type
  rather than `0.0.0.0`. Hermit CRM has no password, so it also prints a warning
  and the advice to prefer a private network (Tailscale, WireGuard) over open
  Wi-Fi.
- **`INSTALL.md`: install by asking an AI assistant.** Unpack the download,
  open the folder in Claude Code, Codex or Cursor and say "Read INSTALL.md and
  set up Hermit CRM for me". It checks Python, installs the command so it
  survives closing the terminal, creates the data folder, asks your name and
  sending addresses and writes them to `config.toml`, starts the app and
  verifies with `doctor`. It is told **not** to run `hermitcrm setup` (which
  reads a terminal an agent does not control) and **never** to ask for or
  handle the mail app password or calendar URL -- those you type into the
  Settings page yourself, so they never reach a model provider. `CLAUDE.md` and
  `AGENTS.md` now say up front that they are rules for changing the code, not
  for installing it, so an assistant does not read a contributor's checklist to
  somebody who just wants a CRM.
- **Settings has an Access section**, and Capture has a help page. Both new
  front doors are started from a terminal, so nothing on screen mentioned them:
  the page now shows the `serve --host` command with this machine's LAN address,
  the no-password warning, and the MCP JSON to paste into a client, filled in
  with the real paths. The help sidebar's CLI hint no longer looks like one more
  topic in the list.
- **`hermitcrm add company|contact|interaction`**: create a record from the
  command line. Same validation and same commit as the web form, so an agent
  no longer has to compose YAML by hand. `--set field=value` reaches any field
  without a flag, and `--body -` reads an interaction body from stdin. The
  README now walks through a first company, and `AGENTS.md`/`CLAUDE.md` in a new
  data folder carry the procedure.
- **`doctor` no longer calls a folder scheduled when the schedule belongs to a
  different one.** A machine has a single `io.hermitcrm.sync` job, and the check
  only tested that its file existed; it now compares the folder that job serves
  and names it when it is not this one.
- **Install docs** describe the clone-and-`pip install` route that works today;
  `pipx install hermitcrm` is marked as not yet published.
- `/favicon.ico` redirects to the app icon instead of answering 404.
- **A write commits its own files only.** Every commit used to stage the whole
  data folder, so an unrelated edit you had not committed yet (a half-written
  `MESSAGING.md`, a hand-added company) was swept into the next write's commit
  under that write's message. Each commit now holds exactly the files that write
  touched.
- **Settings saves are committed.** Saving anything that lands in `config.toml`
  (You, BCC, online copy, appearance, drafts, enrichment, outcomes, the
  walkthrough ticks, the disclaimer) or `fields.toml`, in the web app or in
  `hermitcrm setup`, left the file modified but never committed, so the data
  folder stayed dirty. Each save is now its own commit, named after what
  changed (`settings: theme light -> dark`). Only that file goes in: never
  `.secrets.toml`, and a `config.toml` holding a password is not committed.
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
