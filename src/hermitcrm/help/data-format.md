# Data format

Every record is a Markdown file with YAML front matter in a fixed key order; the files are the only source of truth.

```text
<data>/
  config.toml                 settings, every key optional and commented with its default
  messages.toml               optional draft wording, merged over the package defaults
  .secrets.toml               optional secrets (gitignored, mode 600)
  .hermitcrm-format              data format version, one integer, committed
  PIPELINE.md                 generated, never edit by hand
  CLAUDE.md, AGENTS.md        rules for AI agents
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
| stage | enum | prospect, reached-out, discovery, offer, won, lost, disqualified, temp-disqualified |
| stage_changed | date | set whenever the stage changes |
| lost_reason | text | required for lost; optional for disqualified and temp-disqualified; cleared otherwise |
| requalify_on | date or empty | only while temp-disqualified: the day it goes back to prospect |
| value_eur_month | int or empty | |
| my_score | int or empty | your 0 to 10 |
| fit_score | int or empty | 0 to 100 |
| fte_estimate | text | as written, e.g. `~13` |
| ae_count | int or empty | |
| product_oneliner | text | |
| next_step | text | one line |
| next_step_due | date or empty | |
| next_step_status | enum | open or done |
| tags | list | may be `[]` |
| stage_history | list of maps | see below; omitted while empty |
| created, updated | datetime | |

The body is free Markdown notes.

## Contact (`contacts/<slug>.md`)

`first_name`, `last_name` (at least one), `slug`, `title`, `linkedin`, `email`
(lower case), `phone`, `role` (champion, decision-maker, influencer,
gatekeeper or empty), `created`, `updated`. Body: notes. A file that still has
a single `name` key is read by splitting on the first space and rewritten with
both keys on its next save.

## Interaction (`interactions/<id>.md`)

`date` (datetime), `channel` (email, linkedin, call, meeting), `direction`
(out, in), `contact` (contact slug, or empty for company-level), `subject`,
`outcome` (one line; see the configured outcomes), `result` (legacy: success,
unsuccessful or empty), `source` (manual, bcc-import, calendar-import),
`message_id` (imports only: the mail's Message-ID, or
`ical:<UID>:<RECURRENCE-ID>:<attendee>` for a meeting). Body: the message or
notes verbatim. Id: `YYYY-MM-DDTHHMM-<channel>-<direction>-<contact or company>`,
`-2`, `-3` on collision.

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
`migrate: data format N → M (...)`, front matter only, never bodies;
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
