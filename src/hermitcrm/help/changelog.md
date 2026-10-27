# Changelog

What changed in each version of Hermit CRM, newest first. Versions follow semantic versioning; a change to the data format always comes with an automatic migration.

To upgrade, press **Upgrade** in the notice (the sidebar, or Settings > About): it installs the new version, restarts the app and asks you to reload. Where it cannot do that the notice names the command instead (usually `uv tool install hermitcrm@latest`), or unpack the new download and run `uv tool install --reinstall .` in it, then restart the app. The notes for a version say whether your folder is migrated.

Related: [Settings](/help/settings), [Data format](/help/data-format), [Backups and undo](/help/backups)

## 1.0.0 (2026-10-27)

- **The Follow up list on the Pipeline explains itself.** It is now two groups, **You owe
  a reply** and **Waiting on them**, with a line saying the order (replies you owe
  first, oldest first). Each row shows the channel, direction and date of the message
  it is about, as a link to it, and quotes the first words, with **you:** in front of
  your own, so they no longer read as theirs. A mail header pasted into a message
  ("Name", "10:12 AM (1 minute ago)", "to Sam") is no longer taken for its first words.
  If a message was logged the wrong way round, **I sent this** / **They sent this** on
  the row flips its direction and keeps the text exactly as it was. A card on the board
  whose company is on the list has a small badge; the board's order does not change.
  See [Pipeline](/help/pipeline#follow-up-radar). No data migration.
- **Filter on the Pipeline stays on the Pipeline.** Pressing **Filter** on the board
  (for example after picking a column) took you to the Home page, and **clear filters
  and sorting** went there too. Both now stay on the Pipeline. The other list pages
  were fine. No data migration.
- **The tour and Home cover Outreach, Learning and Reports.** **Show me around** now
  stops at Outreach, Learning and Reports, in the order of the menu, and **What this
  thing does** on Home has a card each for Outreach and Learning. No data migration.
- **Save the questions you ask often.** Next to **Ask** there is now a **Save**
  button, and under an answer **Save this question**. Saved questions are suggested
  as you type in the Ask box on every page (Up/Down, then Enter or Tab), the newest
  four are buttons in the panel, and the Ask page lists them all with Use, Edit and
  Delete. A question saved with "search the whole CRM" ticked remembers that. They
  live in `ask-questions.toml` in your data folder, one commit per change, so they
  are in your backups. A new optional file, so no data migration. See
  [Ask the Hermit](/help/ask).
- **The questions you ask most come first.** Ask the Hermit now counts how often you
  ask each saved question: the four buttons in the panel, the suggestions as you type
  and the Ask page's list put the most asked first. The questions you asked but did
  not save are remembered too (the last 20, failed asks included) and offered under
  the saved ones in a **Recent** group, each with a **Save** button. This is kept in
  `.git/hermitcrm-ask.json`, which is never committed and is not shared between
  machines, so there is no data migration and `ask-questions.toml` is unchanged. See
  [Ask the Hermit](/help/ask).
- **Form fields line up.** In the Next step group of a company, in Log an interaction
  and in the Add task forms, every field's name now sits above its box. Before, a date
  field's name (such as **due** or **date**) sat to the left of the box, which put it
  higher than its neighbours, and a drop-down was a pixel or two shorter than a text
  box, so **outcome** sat lower than **subject**. Boxes and drop-downs in a row now
  share one height, and out/in sits level with them. No data migration.
- **One note box on the Generate panel.** The panel had an **Observation** field and
  an **Add note** box, and both saved a note on the person. Text typed in one was
  lost when you pressed the other's button. Now there is one note box: **Add note**
  or Enter saves it, and **Generate** saves what is in it first, then drafts. The
  list of notes the draft will use also says **company** (not **you**) for a company
  note. No data migration.
- **Company notes replace the company's notes box.** A company has no notes field
  any more. The Details form points to **Company notes** on the company page, and the
  New company form's one box, now **first note**, saves a dated company note. Your
  existing company text became company notes when you upgraded (data format 19,
  migrated for you): a line that starts with a date, such as `21-10-2026`,
  `21/10/2026`, `21.10.2026` or `2026-10-21`, opens a note on that day, with the lines
  under it; text above the first dated line is one note dated at the company's
  creation. The dates are kept, the time of day is not. An `Imported fields (...):`
  block from an import is its own note, so imported column dumps stay separate.
  Drafts may now cite company notes like any other note (the newest 20 notes and 4,000
  characters, the longest dropped first), and the Notes line in the brief shows the
  newest one. Imports write their company text as a company note once, and BCC no
  longer writes its "Created by the BCC import" note. Back up your folder first, as
  usual, then upgrade. `hermitcrm check` names any company body written by hand.
- **Follow up on another channel, or after many unanswered messages.** Pressing
  Generate or **Draft follow-up** for one person used to refuse with "your
  unanswered message was on linkedin, not email" or "followed up already ... close
  the loop". Now it drafts anyway and puts a warning on the draft (the channel
  changed; how many messages went unanswered). Batches still leave those people
  out, and the AI never sees the warning. No data migration.
- **One date format, your choice.** The app showed dates two ways: `2026-12-01`
  in lists and text, and whatever your browser's language says (often
  `01/12/2026`) in date fields. Settings > Appearance now has a **Date format**
  (`date_format` in `config.toml`): `YYYY-MM-DD` (the default), `DD-MM-YYYY`,
  `DD/MM/YYYY` or `MM/DD/YYYY`. Every page, form, report and filter uses it, date
  fields are text boxes in that format with a calendar button, and
  `YYYY-MM-DD` is always accepted when you type. Your files and exports stay
  `YYYY-MM-DD`. No data migration.
- **The light model is now Haiku 5.5.** The outreach bot's scrape research and
  critic (the cheaper "light" tier) run on `claude-haiku-5-5` for Claude instead of
  `claude-haiku-4-5`. A model you named yourself still wins: `enrich_model` is
  followed by light, and `enrich_model_light` overrides both, so pin
  `claude-haiku-4-5` there to keep the old one. No data migration.
- **Ask answers CRM-wide questions in one fast call, with links that work.**
  Hermit now builds a compact index of the CRM (a row per contact: link, stage
  and its role, last touch, last logged interaction, next open task, days since
  touch) and the model answers from it in a single call, about 5 to 10 seconds.
  The slow walk through the data folder runs only for questions the index cannot
  answer, and no longer carries your claude.ai connectors. Every link in an
  answer is checked: it opens the person or company, or it is shown as plain
  text. The answer shows how long it took. No data migration.
- **Ask runs on Sonnet and shows it is working.** Ask the Hermit now answers on
  Sonnet for Claude (the other providers' mid-size models already were the
  default), unless you set `enrich_model` or `ai_tier = "strong"`. The Ask button,
  and "Retry" and "Search the whole CRM instead", now show a spinner and the
  seconds waited while the answer is on its way. No data migration.
- **Generate outreach uses your logged interactions and researches when the scrape
  finds nothing.** The draft's brief now carries this contact's newest logged
  interactions with what was said (up to about 4,000 characters, oldest dropped
  first), not one short line each. When the free scrape finds nothing usable (a
  company with no website, LinkedIn refusing), Generate, batch builds and
  `hermitcrm outreach build` automatically run one ai-web research pass on the
  light model; the item shows the research level that actually ran. No data
  migration.
- **A cheaper outreach.** Generating an outreach is three AI calls (research, draft,
  critic). The research and the critic only read and score, so they now run on a
  light model (Claude: Haiku) instead of Opus; the draft stays on the medium
  model. Set `enrich_model_light` in `config.toml` to choose another. Every AI
  call that runs with no tools also keeps your claude.ai connectors (Gmail,
  Calendar, Drive) out: on a cold start their tool definitions were some 40,000
  tokens of the first call, which a lone outreach paid in full. No data migration.
- **Shorter page intros.** The line under the title on Calendar, Tasks, Messages,
  Outreach, Learning, Extension and Reports is now one short sentence. What a
  first-time reader needs once (what a next step is, how an outcome is set, how
  conversion is counted) sits behind a **?** you can hover, tab to or tap; the rest
  moved onto the button or column it describes, or stayed in Help. The send strip
  reads *Mon–Fri 08:30–17:30* instead of listing every day. Nothing was removed
  from Help.
- **Shorter Settings and Playbook.** The notes under the Settings headings are
  one short sentence each. What you need once (the roles of a deal stage, how
  each agent is started, why a subscription asks for no particular model, how
  to set up a system keyring) sits behind a **?**; the rest moved onto the
  control it describes, such as the Window box or the Delete button. What you
  must see before acting stays on the page, only shorter: the sending limits
  and deliverability note, where passwords are kept, the open-network warning,
  the private-repository warning. The Playbook page is trimmed the same way. A
  **?** near the right edge of a narrow window now opens inside the window, and
  a Settings form row no longer makes the page wider than a phone.
- **Angle retired (2026-10-25).** The angle label is gone from interactions,
  outreach items, the Learning page, settings (`learning_angle_sampling` and
  `outreach_angles`), the CLI (`hermitcrm learn angles` is removed) and the
  exports, with no replacement. A message is described by its framework, its
  approach and the findings it used. Data format 17 and 18 migrate your folder by
  themselves and drop the old `angle` key from outreach items and interactions.
- **Better first drafts, for every message.** A draft now says its proof in the
  language of the message: a German email states the proof in German, while the
  card's "Proof cited" keeps the playbook's own line, so the check still finds
  it. The critic is stricter on "personal": it finds the sentence that is about
  them and asks whether the message would still fit another company of the same
  kind; if it would, the score is 2 or less. The card also shows an **About you
  N, about them M** line, a count of the words that speak of you and of them,
  with a note when the message is more about you. It is a flag, not a check, so
  it never blocks a draft.
- **Message frameworks for first touches.** A framework is a recipe for a first
  message: its parts, how long it may be and what it asks. Eight come built in
  (`house`, the recipe first messages have always used, and seven more such as
  `trigger-tension-trust` and `problem-solution-question`). Write a batch with
  one using `hermitcrm outreach build --framework ID`, or give an approach its
  own with `frameworks:` and `default:` in MESSAGING.md; a draft with neither is
  written as before, with `house`. Add your own, or change a built-in one, in
  `frameworks.toml` in your data folder; `hermitcrm check` names an id the
  library does not have and anything in the file it cannot read. Each draft
  records the `framework` it was built with, and so does the message you log
  from it. The Messages tab shows it (and filters on it), and the export and the
  learning report show it too. `hermitcrm help playbook` has the details. Your
  data folder migrates by itself (data format 15 for outreach items, 16 for
  interactions); there is nothing to do.
- **One-click upgrade.** When a newer version is published, the notice in the
  sidebar and in Settings > About has an **Upgrade** button. One click downloads
  and installs it with the tool that installed Hermit CRM (uv, pipx or pip),
  checks that the new files start, restarts the app and asks you to **Reload**.
  Other open tabs ask you to reload too. While the files are replaced the app
  answers "upgrading" instead of serving pages. It is offered only when the app
  listens on this computer alone (no password, so not on a network), is not on
  Windows, and takes its updates from PyPI; otherwise the notice still names the
  command. Upgrading to this version is by hand, as before: the running app has
  no button yet.
- **A server that is older than its files says so.** If Hermit CRM is upgraded
  from a terminal or by an assistant while the app keeps running, the app used
  to read the new files with the old code and pages broke with an error that a
  reload could not fix. It now notices, shows **Restart needed** with a **Restart
  now** button, and if a page breaks in that state the error page explains it
  instead of saying "Internal Server Error".
- **A server that stays up still hears of new releases.** The update check ran
  once, when the app started; it now asks again as pages are opened (still at
  most once a day, the same request, no identifiers).
- **One path to outreach, and one list of notes.** The contact page's Message
  drafts box is gone. **Generate outreach** opens [Outreach](/help/outreach)
  with that person ready: channel, draft type, signal, an observation sentence,
  a language for the card, and the notes the draft will use. A finding is now a
  note: research saves what it finds as notes on the contact, the card's Notes
  panel is the same list as the contact's and the company's timeline, and a
  regenerate reads the notes as they are. Mark ready no longer writes a summary
  note. A `layout.toml` that still names `drafts` keeps working. Your data
  folder needs no migration.
- **Copy an email address with one click**, on Outreach cards and on the contact
  page.
- **Send approved email from the app.** Turn it on in Settings > Email &
  calendar > Sending, with a mailbox of its own and an app password. On the
  Outreach page an approved email card has **Send now** and **Schedule**;
  **Schedule all ready email** shows the proposed times and asks you to confirm.
  A job (`hermitcrm schedule install --send`, or **Turn on scheduled sending**)
  sends one queued email every 3 minutes, spaced over your working window with
  jitter, a daily cap (50, starting at 10 a day; after two days in a row above 150 the third is
  held at 150), a ramp for a new mailbox, a minimum gap and a day between two
  mails to one company. Before every send it checks again: the text is still what
  you approved, nobody has written to you (in the CRM and in the sending
  mailbox), the address is not suppressed. A refused login, a quota error or a
  bounce spike pauses everything with a red banner; **Pause** is the kill switch.
  The mail is plain text with its Message-ID written first, logged once with
  `source: outreach`, and a crash between sending and logging never sends twice.
  `hermitcrm send` and `hermitcrm outreach schedule|unschedule|send-now|retry|front`
  do the same from the terminal; `hermitcrm help sending` has the details. Off by
  default. Data format 14: new keys on outreach items, a new interaction source and
  the agent rule that an agent never schedules or sends unasked; the migration is
  automatic.
- **Bounces and opt-outs.** Delivery reports in the sending mailbox put the address
  on a suppression list (`outreach/suppressed.toml`), note it on the contact and
  flag the item; **Opted out** (on a reply, on the contact page, or `hermitcrm
  outreach opt-out`) does the same and skips their open items.
- **A paced LinkedIn session.** Outreach > LinkedIn session puts one approved note
  or message in front of you at a time with a countdown, a session of ten and a
  break, under daily and weekly caps. You send each one on linkedin.com yourself:
  Hermit copies the text and opens the profile, then logs what you sent. Nothing
  is automated, because LinkedIn's rules forbid it.
- **A reply keeps their subject.** A reply to interest or a follow-up no longer
  gets a "subject is N characters" warning when the thread's `Re:` subject is
  long: the 60 character limit is for a first touch, where you write the
  subject. `hermitcrm help cli` now lists `--kind` on `outreach preview` and
  `build`.
- **Filter problems explain themselves.** A filter typed like a sentence
  (`fte_estimate >24`, `fit_score>=70`, `country: DE`) now says what to type
  (`fte_estimate=>24`) instead of "unknown filter key". An unknown key suggests
  the closest one and lists the keys with their type (`fte_estimate (text)`).
  Comparing a text field with a number (`>24`), which compares letter by letter
  and drops 100 or more, gets a note on the Outreach preview and in `hermitcrm
  set` dry runs. On Outreach each problem has an **Explain and fix with AI** link
  that opens Ask · Adjust with it filled in. The page's csrf token and empty
  parameters no longer travel into the Ask · Adjust prompt.
- **Export everything.** Settings > Data > Export everything (or
  `hermitcrm export`) gives a zip of CSV files: companies, contacts,
  interactions, tasks and stage history, with column names for Hermit CRM,
  HubSpot or Pipedrive. `--format json` writes one JSON file instead. It only
  reads: nothing in your folder changes. An export imports back.
- **Trends on dashboards.** A new `trend` widget counts the rows of a list
  page per week or month of one date column (messages sent, last touches,
  tasks done) over a report period, and draws one bar per week or month,
  empty ones as zero. Every number links to its rows. `hermitcrm help
  adjust-dashboards` has the keys and an example.
- **Adjust on a dashboard.** The Ask · Adjust button on `/d/<name>` now
  offers changes to that dashboard (add a widget, change what it shows, pin
  or rename it, make a copy), naming its file for your agent.
- **Keep in touch.** Home lists the people outside an open deal you have
  not spoken to in 180 days or more (`keep_in_touch_days` in `config.toml`),
  longest first. Do-not-contact and people you never contacted are left
  out. Also `hermitcrm keep-in-touch` and the MCP tool `keep_in_touch`.
- **Where a dashboard came from.** A dashboard page says when its file last
  changed and in which commit, with Undo (back on the same page afterwards)
  and a link to all changes. Nothing shows for a file that is not committed.

- Reject non-empty contact emails unless they contain exactly one `@` with text
  on both sides, across the web app, CLI, MCP and imports. Contact forms show the
  error beside the email field. Empty emails remain allowed and existing files
  with invalid emails still load without being rewritten.
- Skip addresses that fail that rule when reading BCC mail, calendar attendees
  and contact-import email lists, so a bad address does not interrupt importing
  and committing valid contacts.
- **Getting started leads to the outreach bot.** A new step, "Draft your first
  message", sits after "Write down what comes next" and opens the Outreach page. It
  says what the bot needs (an approach in your playbook, a contact, an AI CLI) and
  ticks itself once a draft exists for one of your own companies. The walkthrough
  now has thirteen steps. See [Outreach bot](/help/outreach).

## 0.8.0 (2026-10-16)

**A playbook for your outreach.** Settings > Playbook writes down what you
sell, to whom and how you sound, in `MESSAGING.md`. It is the first part of
the outreach bot: the parts that follow will pick companies and draft first
messages from it, and they will not start while no approach is ready.
Help > Playbook explains every part.

**Upgrading from 0.7.5.** Run the command the update notice names (usually
`uv tool install hermitcrm@latest`), or unpack the new download and run
`uv tool install --reinstall .` in it, then restart the app. The data format
stays at 8: nothing in your folder is migrated or rewritten by the upgrade.
An existing `MESSAGING.md` stays exactly as it is until you press "Set up
MESSAGING.md" on the Playbook page (or run `hermitcrm playbook upgrade`),
which adds the playbook in one commit and keeps every line you wrote.

- **Approaches.** One approach is one offer to one audience: an offer line,
  the ideal customer (industries, countries, positive signals, funding, and
  a from-to range on any of your own company fields, such as headcount),
  personas with the job titles to look for, proof, why you, voice, channels,
  don'ts and lessons (worked, didn't work, still testing). Each approach is a
  tab, with New, Duplicate (the copy's name is selected, ready to type over)
  and Delete. A meter says how many of the 10 parts are filled and what the
  bot still misses.
- **Not a prospect.** One box of reasons a company is not a prospect, which
  the AI weighs and explains, plus tags that always leave a company out (such
  as customer or do-not-contact), checked by the app itself without AI.
- **Draft it from my website or a document.** Give a web address or upload a
  PDF, Word (.docx) or text file, and your AI CLI proposes the playbook in
  the form. Nothing is saved until you press Save.
- **Learn my voice.** Reads the emails you sent and proposes a Voice section,
  again only in the form until you save.
- **CLI and checks.** `hermitcrm playbook` says per approach what is filled
  in and what is missing (exit 1 while none is ready), `hermitcrm playbook
  upgrade` sets up an existing `MESSAGING.md`, and `hermitcrm check` checks
  the playbook's front matter. Getting started has a "Say what you sell" step.
- **Release notes in the app.** This page: Help > Changelog, linked from the
  update notice and from Settings. The website has the same page at
  /changelog/.
- Behind the scenes: one new dependency, `pypdf`, to read the text of a PDF.
  A new demo folder (`hermitcrm init --demo`) comes with two made-up
  approaches.

## 0.7.5 (2026-10-16)

**A clearer contact page, editable tasks and a WhatsApp channel.** The contact
page now says where things stand before anything else, a task's text and due
date can be changed after it is made, and WhatsApp joins the channels an
interaction can have.

**Upgrading from 0.7.0.** Run the command the update notice names (usually
`uv tool install hermitcrm@latest`), or unpack the new download and run
`uv tool install --reinstall .` in it, then restart the app. The data format
stays at 8: nothing in your folder is migrated or rewritten by the upgrade.

- **Contact page.** A status strip on top shows the last touch, who is waiting
  on whom (the same rule as the follow-up radar on Home), the person's next
  task and the history in numbers. Under the name: "title at Company" with
  stage and role badges. An action row offers Log interaction, Add note, Add
  task, copy email, LinkedIn and Enrich. Fields are read-only with an Edit
  box. The timeline shows a direction arrow and the first line of each body,
  with the rest behind "more"; drafts, merge and delete are folded away.
- **Editing a task.** An Edit button on the company, contact and Tasks pages
  changes the text and due date of an open to-do.
- **WhatsApp channel.** The interaction form's channel choice is a dropdown:
  email, LinkedIn, call, WhatsApp and note. Reports, the CLI log summary and
  the MCP `add_interaction` tool know the new channel. Meeting stays valid
  (calendar imports) and is offered when editing a meeting.
- **Company form.** Fields sit in labelled groups on a grid, each as wide as
  it needs. The reason and requalify date show only for a stage that uses
  them, or when they already hold something.
- **Bcc and calendar import.** A mail from a new address of someone who looks
  like a person already on file (same name, or the same first name where one
  side has no last name) goes to the review inbox instead of creating a
  duplicate contact. Assigning it logs on that contact.
- Behind the scenes: a test guards the no-telemetry promise against FastAPI's
  OpenTelemetry support, and no release ships until `scripts/install-check.sh`
  has installed the wheel and the download in a clean virtualenv and run them
  as a new user would. Pull requests get an automatic safety check.

## 0.7.0 (2026-10-09)

**Stages are configurable.** The steps a deal goes through are yours to name
and order. Settings > Your CRM > Deal stages renames, reorders, adds and
removes them, and each stage has a role that tells Hermit what it means: `open`
(a board column; the first one is where new companies start), `won`, `lost`
(needs a reason), `closed` (any other end, such as disqualified) or `parked`
(out of the pipeline until a date). Without a setting the stages are the ones
Hermit always had, so nothing changes until you change it: no data-format
change, no migration, and `PIPELINE.md`, the reports and `hermitcrm check`
print exactly what they did before.

**Upgrading from 0.6.0.** Run the command the update notice names (usually
`uv tool install hermitcrm@latest`), or unpack the new download and run
`uv tool install --reinstall .` in it, then restart the app. The data format
stays at 8: nothing in your folder is migrated or rewritten by the upgrade.

- **Renaming is a sweep.** The new name goes on every company and into every
  `stage_history` entry. Two stages can swap names. A stage change is one
  commit, the setting and the records together, so one undo takes it all back.
  If a change fails part-way (a full disk, say), the files are put back as they
  were and nothing is committed.
- **Deleting a stage that has companies asks where they go**, and for a reason
  when that stage is a lost one. The move is an ordinary stage change, so the
  history records it.
- **A stage that is not in the settings never makes a file unreadable.** The
  company loads, sits off the board in grey, a banner says so, and
  `hermitcrm check` prints a warning (exit code unchanged). Saving it keeps
  its stage, reason and date until you pick one that exists.
- **`hermitcrm stages`** lists the stages and changes them (`rename`, `add`,
  `move`, `set`, `remove`): a dry run first, `--apply` writes it, commits start
  with `ai: adjust:`. A new recipe, `hermitcrm help adjust-stages`, tells an
  agent how.
- The company page's Disqualify menu offers every closed or parked stage, and
  Requalify returns a company to the first open stage. With the default names
  the buttons read as before.
- Dashboards and routines that name an old stage are not rewritten. The
  Settings message and `hermitcrm check` name them.
- A setting saved over a value you wrote on several lines (a `stages` or
  `task_types` list) is replaced whole. Before, only its first line was
  replaced and the rest was left behind, which broke `config.toml`. A value
  written as a multi-line `"""` string is replaced whole too.
- The sample account follows your stages: its story runs through them and its
  dashboard filters on their names.
- Behind the scenes there are no stage constants any more: every rule asks the
  configured stages by role.

## 0.6.0 (2026-10-04)

**Make it yours, with your own AI.** Hermit now has one place for changing it
to fit how you work, and your own AI agent does the building. Nothing is sent
anywhere new: the agent is the one you already use (Claude Code, Cursor, Codex,
Gemini), working on the files in your folder, and every change is a git commit
you can undo.

**Upgrading from 0.5.0.** Run the command the update notice names (usually
`uv tool install hermitcrm@latest`), or unpack the new download and run
`uv tool install --reinstall .` in it, then restart the app. The data format
goes from 7 to 8: the first command after the upgrade (restarting the app
counts) adds an agent skill and a short "Adjusting Hermit" section to the
folder's agent files, and one line to `.gitignore`, in one commit. It touches
no company, contact or interaction. `hermitcrm migrate --dry-run` shows it
first; to go back, `git revert` that commit and reinstall 0.5.0, which
refuses a format-8 folder.

- **Ask · Adjust.** One button on every page opens a panel: Ask a question
  about the page, or Adjust it by describing the change. The request goes to
  your own agent with the page it was asked on (Claude Code opens in the data
  folder through a deep link; Cursor too; Codex and Gemini get a copy-ready
  command). Settings > AI picks the agent.
- **Make it yours** (`/yours`). Everything you changed, in one list with Undo,
  plus starters to begin from, filled in from your own data.
- **Dashboards.** One TOML file per dashboard in `dashboards/`, built from the
  same filters the list pages use: counts, tables and groups. Pin one and it
  shows in the sidebar.
- **Page layout** (`layout.toml`). Order or hide the sections of the company,
  contact and Home pages, hide fields, choose the columns of the company and
  contact lists. Hidden fields keep their values. Sections you do not list
  keep their place after the ones you do, so a section added by a later
  release never disappears.
- **Bulk changes.** `hermitcrm set` changes a field on many records at once:
  a dry run first, `--apply` to do it, one commit.
- **Routines** (`routines.toml`). Python picks the records (quiet threads,
  replies owed, or any filter), your AI drafts one message for each, and the
  drafts wait on Home as "Drafts from routines". Routines start paused, run
  after the daily sync when on, and never send anything. The AI step runs
  without tools, which today means Claude or Codex; a routine on another AI
  command is refused with a reason. `hermitcrm routines` lists, previews, runs,
  turns on and off.
- **`hermitcrm undo <commit>`.** Reverts one change as a new commit.
- **Recipes your agent reads.** `hermitcrm help adjust` and nine topics
  (fields, look, messages, connect, feature, dashboards, bulk, layout,
  routines) hold the rules, so the agent's instructions never go stale. New
  folders get a `/hermit` skill for Claude Code and an "Adjusting Hermit"
  section in `CLAUDE.md` and `AGENTS.md`.
- **MCP write tools.** Seven new tools for clients without a shell (Claude
  Desktop, ChatGPT): read the recipes, read and write the allowed extension
  files (validated before they are kept), change three settings, preview and
  apply a bulk change (apply refuses without a fresh preview), and undo. 17
  tools in all.
- **The sample account** also brings a pinned Monday review dashboard and a
  paused routine, so you can see both before you ask for your own.
- **`hermitcrm check`** also checks the new files and says what is wrong in
  each, with the line.
- **Settings in five tabs**: General, Email & calendar, Your CRM, Backup and
  Advanced, at about half the words. Each section leads with its status
  and opens its form on request; a tab shows a dot when something in it
  needs you. Links to a section (`/settings#bcc`) still land on it, and
  "How it works" opens the matching part of Help.
- Fixed: saving a contact removed its tasks. Saving a contact form cleared its
  custom fields.
- Fixed: unticking "Outreach templates may use it" on a field did nothing.
  "Shown in" offers only the places the field's record type can appear. A
  stored calendar address says it is stored, as the BCC password does.

## 0.5.0 (2026-10-02)

The first release on PyPI: `uv tool install hermitcrm`. The download on
hermitcrm.io is the same code.

**Upgrading from 0.4.1.** Run `uv tool install hermitcrm@latest`, or unpack the
new download and run `uv tool install --reinstall .` in it, then restart the
app. 0.4.1's update notice says `pipx upgrade hermitcrm`, which does nothing
for an install made from a download. The data format goes from 6 to 7: the
first command after the upgrade (restarting the app counts) moves each
contact's notes into note interactions, in one commit. `hermitcrm migrate
--dry-run` shows it first; to go back, `git revert` that commit and reinstall
0.4.1, which refuses a format-7 folder.

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
- **A contact's own draft language.** A contact can have a draft language
  (`language` in front matter, absent until set) and the drafts have a
  language picker that holds for that page only. Drafts follow the picker,
  then the contact's language, then the company's country (Belgium by its
  evidence), then English. Before, a German speaker at a Dutch company got
  Dutch drafts and there was nowhere to say otherwise.
- **LinkedIn capture names the right employer on the newer profile layout.**
  Without an `<h1>` on the page, the employer is the company Experience
  starts with, not the first company linked anywhere (Activity, Featured and
  Interests come earlier on the page). With no match it stays empty rather
  than wrong. Drag the bookmarklet from Extension again for the new one; an
  old one already in the bookmarks bar benefits too.
- **The update notice names a command that works.** It said `pipx upgrade
  hermitcrm` to everyone. It now says `uv tool install hermitcrm@latest` for
  an install made with uv, `pipx install --force hermitcrm` for pipx and
  `pip install --upgrade hermitcrm` otherwise, and the error for a folder
  written by a newer version says the same. The first two also move an
  install from a download over to PyPI.

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
