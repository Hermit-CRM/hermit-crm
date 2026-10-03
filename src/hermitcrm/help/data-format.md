# Data format

Every record is a Markdown file with YAML front matter in a fixed key order; the files are the only source of truth.

```text
<data>/
  config.toml                 settings, every key optional and commented with its default
  messages.toml               optional draft wording, merged over the package defaults
  layout.toml                 optional page layout: section order, hidden fields, list columns
  .secrets.toml               optional secrets (gitignored, mode 600)
  .hermitcrm-format              data format version, one integer, committed
  PIPELINE.md                 generated, never edit by hand
  CLAUDE.md, AGENTS.md        rules for AI agents
  .claude/settings.json       git commands Claude Code may not run (see Backups and undo)
  MESSAGING.md                your outreach playbook
  inbox/                      BCC and calendar items waiting for a decision
  companies/<slug>/company.md
  companies/<slug>/contacts/<contact-slug>.md
  companies/<slug>/interactions/<id>.md
```

Writes are deterministic: known keys in the order below, unknown keys after
them sorted by name and preserved as they were, dates as `YYYY-MM-DD`,
datetimes as `YYYY-MM-DDTHH:MM` (local time), empty values as `key:`, bodies
byte for byte. Two writes of the same data give identical files, so diffs
show only real changes.

## Company (`company.md`)

| Key | Type | Notes |
|---|---|---|
| name | text | required |
| slug | text | equals the folder name; never changes |
| website | text | normalised to include the scheme |
| linkedin | text | |
| country | code or empty | ISO 3166-1 alpha-2; also picks the draft language |
| source | enum | linkedin-search, referral, inbound, event, list, network, other |
| stage | enum | prospect, engaged, discovery, offer, won, lost, disqualified, temp-disqualified |
| stage_changed | date | set whenever the stage changes |
| lost_reason | text | required for lost; optional for disqualified and temp-disqualified; cleared otherwise |
| requalify_on | date or empty | only while temp-disqualified: the day it goes back to prospect |
| value_eur_month | int or empty | |
| product_oneliner | text | |
| next_step | text | one line |
| next_step_due | date or empty | |
| next_step_status | enum | open or done |
| next_step_done_on | date | the day it was marked done; omitted otherwise |
| tags | list | may be `[]` |
| stage_history | list of maps | see below; omitted while empty |
| created, updated | datetime | |

`tasks` is a list of maps, absent until there is one, on a company **and** on
a contact:

```yaml
tasks:
  - {text: send the pricing page, due: 2026-09-24}
  - {text: check whether the audit landed, done: true, done_on: 2026-09-21}
```

`text` is required; `due`, `done` and `done_on` (the day it was ticked off,
written by the app) are optional. A company's next step is derived, not
stored: it is the open task due first across the company's `tasks`, its
contacts' `tasks` and the `next_step` fields, which older files use and which
are read as one more task.

Plus any field you defined yourself (see below), and any key Hermit CRM does
not recognise, which is kept and written back untouched.

## Fields of your own

`fields.toml`, beside your data, describes fields Hermit CRM does not have:

```toml
[[field]]
key = "fit_score"          # the front-matter key, and the filter key
label = "fit"              # what the interface calls it
type = "number"            # text, number, date or select
applies_to = "company"     # company, contact or interaction
help = "0 to 100"          # optional, shown under the input
show_in = ["detail", "companies"]   # where it appears
```

`show_in` takes `detail` (the record's own page) plus the tables the record
appears in: `board` and `companies` for a company field, `contacts` for a
contact, `messages` for an interaction. Wherever a field is a column it can be
filtered and sorted like any built-in one. A `select` field needs `options`,
and a field with `enrich = true` and a `description` is offered to the AI when
you press Enrich.

The values are ordinary front matter, so a field you stop describing does not
lose anything: the key stays in the file and comes back the moment you
describe it again. A key that a built-in field already uses is refused, since
a custom field with that name would shadow it.

Hermit CRM had four such fields built in until 0.3.0 -- `my_score`,
`fit_score`, `fte_estimate` and `ae_count` -- which were one person's way of
working rather than a CRM's. An existing folder that used them gets a
`fields.toml` describing them, written automatically, without a single
company file being touched.

The body is free Markdown notes.

## Page layout

`layout.toml`, beside your data, changes how the pages are laid out and
nothing else: the order of the sections on the company, contact and home
pages and which are hidden, the fields a record page hides, and the columns of
the Companies and Contacts lists.

```toml
[company]
sections = ["timeline"]              # first; the other sections follow in their usual order
hide_sections = ["merge"]
hide_fields = ["value_eur_month"]    # built-in or your own; the value stays in the file

[companies]
columns = ["name", "stage", "fit_score", "country", "next_step"]
```

The file is optional and so is every key; without it the pages are as they
ship. A hidden field keeps its value, also when you save a form that does not
show it. `hermitcrm check` reports unknown names and syntax errors; the app
skips them meanwhile. Every section name, field and column key is in
[Page layout](/help/adjust-layout).

## Contact (`contacts/<slug>.md`)

`first_name`, `last_name` (at least one), `slug`, `title`, `linkedin`, `email`
(lower case), `phone`, `role` (champion, decision-maker, influencer,
gatekeeper or empty), `created`, `updated`. No body since format 7: notes on a
person are note interactions (`hermitcrm check` lists a body written by hand). A file that still has
a single `name` key is read by splitting on the first space and rewritten with
both keys on its next save.

## Interaction (`interactions/<id>.md`)

`date` (datetime), `channel` (email, linkedin, call, meeting, note), `direction`
(out, in; empty for a note), `contact` (contact slug; empty only in older or
imported files), `subject`,
`outcome` (one line; see the configured outcomes), `result` (legacy: success,
unsuccessful or empty), `source` (manual, bcc-import, calendar-import, migration),
`message_id` (imports only: the mail's Message-ID, or
`ical:<UID>:<RECURRENCE-ID>:<attendee>` for a meeting). Body: the message or
notes verbatim. Id: `YYYY-MM-DDTHHMM-<channel>-<direction>-<contact or company>`
(a note: `YYYY-MM-DDTHHMM-note-<contact>`), `-2`, `-3` on collision. A note is a
memo, not a touch: it never moves last touch, outcomes, follow-ups or reports.

## Stage history

`stage_history` is append-only, one map per stage change made through Hermit CRM:
`{date: YYYY-MM-DD, from: <stage>, to: <stage>, reason: <text>}` (`reason`
omitted when empty; `from` is `''` for the stage a company was created in when
that was not prospect). Merging combines both lists by date. It feeds the
funnel, time in stage and closing dates on the Reports page.
`hermitcrm backfill-history` reconstructs it from git for older companies.

## Slugs

Lower-case ASCII, words joined by single hyphens, at most 60 characters;
umlauts and accents transliterated (`ä` to `ae`, `é` to `e`); legal suffixes
(gmbh, ag, bv, ltd, inc, sas, ...) dropped from the slug only; `-2`, `-3` on
collision.

## Format version and migrations

`.hermitcrm-format` holds one integer. When a release changes the format, the
next command migrates the folder in one commit named
`migrate: data format N → M (...)`, never touching an interaction body (format 6 adds
`.claude/settings.json` and the backup rules in `CLAUDE.md` / `AGENTS.md`; format 7
moves each contact's notes body into note interactions, a line starting
`DD/MM/YYYY:` dated that day, the rest dated the contact's `created`);
`hermitcrm migrate --dry-run` lists the files first and `git revert` undoes it. A
folder written by a newer Hermit CRM is refused until you upgrade.

## Commits

One commit per write, with a fixed message shape: `company: <slug> created`,
`company: <slug> stage <old> -> <new>`, `contact: <company>/<slug> updated`,
`interaction: <company> <channel> <direction> <contact> <date>`,
`import: ...`, `bcc: ...`, `calendar: ...`, `ai: ...` for enrichment and
agent-made changes, `pipeline: rebuild`. Rolling back is plain git:
`git checkout <sha> -- <path>` or `git revert <sha>`, then `hermitcrm rebuild`.

Related: [Companies](/help/companies), [Interactions](/help/interactions), [AI agents](/help/ai-agents), [CLI](/help/cli)
