# Make it yours

Describe a change to Hermit CRM and your own AI agent builds it in your data folder; this page is the rules that agent follows, and the first thing it reads.

For people: open **Make it yours** in the sidebar (`/yours`), or the **Adjust**
tab of the **Ask · Adjust** button on any page. Pick an idea or describe a
change, then press **Open in Claude Code** (or your agent's button, or Copy
prompt). Your agent does the work in your data folder. Hermit picks the change
up on the next page you open, without a restart, and lists it under **Recent
changes** with an **Undo** button.

Hermit never builds the change itself, and never sends a message: routines and
templates only write drafts for you to send.

## For the agent: read this first

You were asked to change Hermit CRM itself: a field, the look, a dashboard, a
page layout, templates, a routine or many records at once. Work in the data
folder (the one with `config.toml` and `companies/`), and:

1. Find the request in the table under **Which recipe**, run that
   `hermitcrm help <topic>` and follow it. If none fits, read
   `hermitcrm help adjust-feature`.
2. Change only the files listed under **Files you may write**. Records change
   only through the CLI.
3. Run `hermitcrm check`. Fix every line it prints and run it again until it
   says `OK`.
4. Make one commit per change, with only the files you changed:
   `git add fields.toml && git commit -m "ai: adjust: contract renewal field"`.
   Never `git add -A`: the folder may hold the user's own unfinished edits.
5. Tell the user what changed, where to see it, and how to undo it (the commit
   id, `hermitcrm undo <commit>`, or Undo on the Make it yours page).

If the request is unclear or would change many records, ask before writing.

## Files you may write

Without asking, and only these:

- `fields.toml`: fields of the user's own (`hermitcrm help adjust-fields`)
- `layout.toml`: page layout (`hermitcrm help adjust-layout`)
- `dashboards/*.toml`: dashboards (`hermitcrm help adjust-dashboards`)
- `routines.toml`: routines (`hermitcrm help adjust-routines`)
- `theme.css`: the look (`hermitcrm help adjust-look`)
- `messages.toml` and `MESSAGING.md`: draft wording and the playbook
  (`hermitcrm help adjust-messages`)
- in `config.toml`, only the keys `task_types`, `outcomes` and `silent_days`;
  leave every other line as it is.

## Records only through the CLI

- `hermitcrm add company|contact|interaction ...` creates a record.
- `hermitcrm set ...` changes records in bulk. It shows a dry run first (how
  many, a few before and after); show it to the user, and only then run it again
  with `--apply`. See `hermitcrm help adjust-bulk`.
- Both commit by themselves; do not commit their files again.

## Never

- Rewrite an interaction body: it is the record of what was said.
- Touch `.hermitcrm-format`, `PIPELINE.md` (generated), `.secrets.toml`,
  `.claude/settings.json` or anything under `.git/`.
- Rewrite history: no `git reset --hard`, `commit --amend`, `rebase` or
  `push --force`. Undo with a new commit instead.
- Send anything: no mail, no LinkedIn message, no API call on the user's
  behalf. Messages are drafts; the user sends them.
- Edit the installed Hermit CRM package (its code, templates or `tokens.css`):
  an update overwrites it. A wish that needs code is `hermitcrm help adjust-feature`.
- Put a password, token or API key in any file in the folder.

## Which recipe

| The user asks for | Run |
|---|---|
| A new field, a field shown in a list or on the cards, task types, outcomes | `hermitcrm help adjust-fields` ([read it](/help/adjust-fields)) |
| Colours, fonts, a more compact look | `hermitcrm help adjust-look` ([read it](/help/adjust-look)) |
| Draft templates, a language, the playbook | `hermitcrm help adjust-messages` ([read it](/help/adjust-messages)) |
| Bringing data in, connecting another tool | `hermitcrm help adjust-connect` ([read it](/help/adjust-connect)) |
| Something none of these covers, a new kind of record | `hermitcrm help adjust-feature` ([read it](/help/adjust-feature)) |
| A dashboard, a saved view, a ranked list, a pin in the sidebar | `hermitcrm help adjust-dashboards` |
| Hiding a field or a section, reordering a page, list columns | `hermitcrm help adjust-layout` |
| Tagging, scoring or moving many records at once | `hermitcrm help adjust-bulk` |
| Something that should happen every day or week (drafts, briefs, reminders) | `hermitcrm help adjust-routines` |

## Check and pickup

`hermitcrm check` validates the records and every file above. Each problem is
one line, `<file>: <where>: <what>`, often with a hint:

```text
fields.toml: renewal: type must be one of text, number, date, select (did you mean date?)
theme.css: line 3: --acent is not a token the app uses (did you mean --accent?)
```

The running app re-reads `config.toml`, `fields.toml` and `messages.toml` when
they change, and its index after any commit, so a change shows on the next page
load. `theme.css` is read on every page. The Make it yours page shows the same
problems as `check`, so the user can paste them back to you.

## Undo

```bash
hermitcrm undo a1b2c3d     # a new commit that reverses a1b2c3d (git revert)
```

It refuses an unknown commit, a merge, the folder's first commit, and a folder
with uncommitted changes to tracked files. When later changes touched the same
lines it stops, leaves the folder as it was, and says so; then undo by hand
with a new commit. The Undo buttons under Recent changes do the same. An undo
is itself a commit, so undoing it brings the change back.

## The safety badges

Each idea on the Make it yours page says how safe it is:

- **undo in one click**: one commit to one file; Undo takes it back.
- **dry run first**: changes records; your agent shows how many and a few
  examples before anything is written.
- **preview first**: an import; you see every row and what will happen to it.
- **starts paused**: a routine; it does nothing until you preview it and turn
  it on, and it only ever writes drafts.

## How the request reaches your agent

Hermit hands the request to the agent named by `adjust_agent` in `config.toml`
(Settings > AI): `claude`, `cursor`, `codex`, `gemini` or `copy`. Without it,
it follows the tool Enrich uses (`enrich_provider`, or the name `enrich_command`
starts with) when that is Claude Code, Codex or Gemini CLI, and otherwise gives
you a prompt to copy.

- **Claude Code**: a `claude-cli://` link opens a terminal in your data folder
  with `/hermit Asked on <page> (<path>): <request>` typed in. `/hermit` is a
  skill in the folder that runs `hermitcrm help adjust`. Nothing runs until you
  press Enter. If nothing opens, run `claude` once in a terminal and try again.
- **Cursor**: a link puts the request in the Cursor window in front; open the
  data folder there first.
- **Codex, Gemini CLI**: a command to paste in a terminal (`cd <folder> && codex '...'`).
- Every other agent: **Copy prompt**, which starts with
  `Run "hermitcrm help adjust" first and follow it.`

A link longer than 500 bytes fails without a word on macOS, so a longer request
gets Copy prompt instead of Open, with a line saying why.

## Without a shell (Claude Desktop, ChatGPT)

An AI app connected over MCP (`hermitcrm mcp`, see [AI agents](/help/ai-agents))
cannot run commands, so it has tools for the same steps, and they keep the
rules above for it:

| With a shell | Over MCP |
|---|---|
| `hermitcrm help adjust`, `hermitcrm help adjust-<topic>` | `adjust_help` |
| read a file you may change | `adjust_read` |
| edit it, `hermitcrm check`, commit | `adjust_write`: refused, with the problems, until check passes; then one commit |
| the `config.toml` keys | `adjust_config` |
| `hermitcrm set` (dry run), then `--apply` | `bulk_preview`, then `bulk_apply` with its `preview_id` |
| `hermitcrm undo <commit>` | `undo` |

A routine written over MCP arrives paused. A prompt copied from Make it yours
says to run `hermitcrm help adjust`; over MCP, call `adjust_help` instead.

Related: [AI agents](/help/ai-agents), [CLI](/help/cli), [Settings](/help/settings), [Backups and undo](/help/backups)
