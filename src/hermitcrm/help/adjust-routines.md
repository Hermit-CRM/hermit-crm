# Make it yours: routines

Small jobs in `routines.toml` that run every morning after the daily sync: a morning brief, or one AI draft per quiet thread. Drafts wait on Home; Hermit never sends anything.

This page is a recipe for an AI agent (Claude Code, Codex, Cursor, Gemini CLI)
asked to set up or change a routine, and the reference for the file. Read
`hermitcrm help adjust` first if you have not: it has the rules for every change.

## What the user can ask for

- "Every morning, show me a short brief: meetings today, tasks due, replies I owe."
- "Every morning, for people I messaged on LinkedIn 7 days ago without a reply,
  draft a short follow-up. Never send anything."
- "Draft replies to people who wrote to me and are still waiting."
- "Each morning, draft a first message for up to 3 prospects with a score above 7
  that I have never contacted."
- "Pause the follow-up routine", "make the nudges shorter and in my voice".

What routines cannot do: send anything, change records, run at other times than
after the daily sync, react to events, or start each other. If the user wants
that, say so plainly and offer the nearest thing (a routine that drafts, a
dashboard, or `hermitcrm set` with a dry run).

## How it works

1. **Python selects** the records, with no AI: the follow-up radar (the
   threads Home lists under replies you owe, and the ones waiting on them) or the
   same filters as the Companies and Contacts lists.
2. **The AI drafts** one message per selected record, at most `limit` per run,
   through the AI CLI set up for Enrich (Settings, AI), on the medium model, with
   no tools. It gets the record (as `hermitcrm show` prints it), the playbook
   `MESSAGING.md`, the folder's `messages.toml` wording in the contact's
   language, and the routine's `prompt`. It answers in JSON; an empty, overlong
   or garbled answer skips that record with a one-line reason.
3. **Drafts land on Home** under *Drafts from routines*, with a link to the
   person. The user edits one, sends it themselves, then clicks *I sent it*
   (logged as an outbound message) or *Discard*. A routine never writes a second
   draft for the same person while one is waiting, nor again for a thread that
   was already drafted, until something new is logged on it.
4. **Each run is one commit**, `routine: <name>: <n> drafts`, which the hub's
   Undo can revert. A run that drafted nothing makes no commit. The last run
   of each routine is kept in `inbox/.last-routines.json` (not in git).

A `brief` routine uses no AI and writes no records: its summary shows at the
top of Home for the rest of that day.

## The file

`routines.toml` in the data folder, one `[[routine]]` table per routine:

| key | for | value |
|---|---|---|
| `name` | all | required; lowercase letters, digits and dashes; unique |
| `title` | all | what Home and the hub show; default: the name |
| `paused` | all | `true` (default) or `false`. Leave it out or `true`: the user turns it on |
| `action` | all | `draft` (AI drafts one message per record) or `brief` (no AI) |
| `select` | draft | `quiet_threads`, `replies_owed` or `records` |
| `prompt` | draft | required: what to write, in the user's words; at most 2000 characters |
| `limit` | draft | most drafts per run, 1 to 50; default 10 |
| `channel` | draft | `email` or `linkedin`. For the radar selectors it also means "threads whose last message was on this channel" |
| `days` | quiet_threads, replies_owed | at least this many days since the last message; default: the follow-up days in Settings |
| `scope` | records | `companies` (default) or `contacts` |
| `filters` | draft | narrow the selection; the list filter syntax below |

The selectors:

- `quiet_threads`: you wrote last, on a message, at least `days` ago, nothing
  came back and no future next step is planned. Active companies only. One per
  company.
- `replies_owed`: they wrote last, at least `days` ago, and you have not
  answered. Active companies only. One per company.
- `records`: every company (or contact, with `scope = "contacts"`) that matches
  `filters`, by name. Without filters that is everyone, so always add some.

## Filters

`filters` is a table of column = value, with the syntax of the filter row on the
Companies and Contacts pages. Write values as text in quotes:

| value | means |
|---|---|
| `"acme"` | contains acme (any case) |
| `"!acme"` | does not contain acme |
| `"=acme"` | is exactly acme |
| `">70"`, `"<70"` | larger or smaller: numbers, dates as `YYYY-MM-DD` |
| `"-"` | empty (for `last_touch`: never contacted) |
| `"*"` | not empty |

Choice columns take one value or a list of exact values: `stage = ["prospect",
"engaged"]`. Stages: prospect, engaged, discovery, offer, won, lost,
disqualified, temp-disqualified.

Company columns (also used by `quiet_threads` and `replies_owed`): `name`,
`country` (a code such as DE), `stage`, `source`, `tags`, `last_touch`,
`next_step`, `next_step_due`, `next_type` (when task types are set up), plus every
company field in `fields.toml` shown in the companies list. Contact columns:
`name`, `company_name`, `title`, `email`, `linkedin`, `last_touch`,
`interaction_count`, plus every contact field shown in the contacts list. A
wrong column or value is reported by `hermitcrm check`, with a "did you mean".

## Three starters

Copy these as they are, then change what the user asked for. They start paused.

```toml
# Morning brief: meetings today, tasks due and replies owed, on Home. No AI.
[[routine]]
name = "morning-brief"
title = "Morning brief"
action = "brief"

# Nudge quiet threads: people I messaged on LinkedIn 7+ days ago, no reply.
[[routine]]
name = "nudge-quiet-threads"
title = "Nudge quiet threads"
action = "draft"
select = "quiet_threads"
channel = "linkedin"
days = 7
limit = 10
prompt = """
Write a short, friendly follow-up to my last message: two or three sentences,
one easy question, no pressure and no "just checking in". Refer to what we last
talked about. Sign with my first name.
"""

# Reply drafts: they wrote, I have not answered yet.
[[routine]]
name = "reply-drafts"
title = "Reply drafts"
action = "draft"
select = "replies_owed"
prompt = """
Draft a reply that answers their last message point by point. Put anything I
must check or decide myself in [square brackets]. Keep my usual tone.
"""
```

The sample account (`hermitcrm sample add`, and `init --demo`) writes a paused
`nudge-quiet-threads` routine like the second one, for any channel, under a
comment that starts "A sample routine". Change it in place when the user asks
for one like it; once changed (or turned on) it is the user's, and
`hermitcrm sample remove` leaves it.

A `records` routine, for "first messages to high-score prospects never
contacted":

```toml
[[routine]]
name = "first-touch"
title = "First touch for top prospects"
action = "draft"
select = "records"
scope = "companies"
filters = { stage = "prospect", my_score = ">7", last_touch = "-" }
limit = 3
prompt = "Draft a short first message using the playbook's hook angle."
```

## Steps for the agent

1. Read `routines.toml` if it exists and keep everything in it: other routines,
   comments, the user's `paused` values. Add or change only what was asked.
2. Write new routines without `paused` (or with `paused = true`). Never turn a
   routine on yourself: the user does that after looking at the preview.
3. Run `hermitcrm check` and fix every line it prints about `routines.toml`.
4. Run `hermitcrm routines preview <name>` and show the user who would be picked.
   If they want to see a draft: `hermitcrm routines preview <name> --try` (one AI
   run, nothing saved).
5. Commit only `routines.toml`, as `ai: adjust: routine <name>`.
6. Tell the user: it is paused; turn it on at `/yours/routines/<name>` or with
   `hermitcrm routines on <name>`; drafts will appear on Home after the next
   daily sync; nothing is ever sent.

## Rules

- Drafts only. No routine, prompt or command sends a message.
- New routines start paused; preview first; the user turns them on.
- Write only `routines.toml`. Never write into `drafts/`, never edit
  `inbox/.last-routines.json`, never run `hermitcrm routines run --apply` unless
  the user asks for a run now.
- The prompt is for wording, not for selection: who is picked is decided by
  `select`, `filters`, `days` and `channel`, never by the AI.
- A routine that fails is one line in the sync log; it never stops the sync or
  the other routines.

## Commands

```text
hermitcrm routines [list]                 every routine, on or paused, its last run; problems
hermitcrm routines preview NAME [--try]   who it would pick now (no AI, no writes); --try shows one AI draft, not saved
hermitcrm routines run [NAME] [--apply]   one routine (even a paused one), or all that are on; dry run without --apply
hermitcrm routines on NAME | off NAME     turn on or pause; one commit, only the paused line changes
```

The web app has the same: `/yours/routines` lists them, `/yours/routines/<name>`
is the preview with *Turn on*, *Pause* and *Try the AI on the first one*.

Related: [CLI](/help/cli), [Data format](/help/data-format), [AI agents](/help/ai-agents), [Enrich](/help/enrich)
