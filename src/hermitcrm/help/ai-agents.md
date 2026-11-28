# AI agents

How an AI session (Claude Code, Codex or any agent) should read and write a Hermit CRM data folder; the same rules are in the folder's `CLAUDE.md` and `AGENTS.md`.

The data folder is plain files in git, so an agent works in it like a person
would: read what is needed, edit front matter, commit. Run `hermitcrm` commands
from the folder, or add `--data <folder>`.

An agent with a shell in the folder should use the commands below. An AI client
with no shell -- Claude Desktop, ChatGPT, Cursor -- connects over MCP instead;
see **Connecting over MCP** at the end.

## Reading, cheapest first

1. Read `PIPELINE.md` first. For a pipeline review it is usually enough: one
   line per company, about 30 tokens each.
2. For one account, run `hermitcrm show <slug>` rather than opening its files.
3. For "what happened recently", run `hermitcrm digest --days 7`.
4. For numbers (activity, funnel, outcomes, messages), run
   `hermitcrm report --days 30 --md`.
5. Open interaction files directly only when the exact wording matters
   (drafting a reply, judging tone). Never read all interactions.
6. Never edit `PIPELINE.md` by hand; it is generated.
7. For outreach wording, read `MESSAGING.md` (the playbook) and
   `messages.toml` (if present) before drafting anything. Its front matter
   and headings are described in `hermitcrm help playbook`; cite only the
   proof written there.
8. For how a feature works, run `hermitcrm help <topic>` (`hermitcrm help` lists
   the topics).

## Creating a record

Three commands cover every kind of record, so an agent never has to write YAML
by hand:

```bash
hermitcrm add company "Acme BV" --country NL --website acme.example.com
hermitcrm add contact acme "Jane Roe" --title CTO --email jane@example.com
hermitcrm add interaction acme --channel email --direction out \
    --contact jane-roe --subject "Intro" --body -
```

- `add` writes the file, regenerates `PIPELINE.md` and commits, in that order.
  It has no `--apply` and no dry run: it always writes, exactly as clicking
  Save in the web app does.
- Each command prints the slug it assigned, on one line, with the path it
  wrote. Use that slug in the next command; never guess one.
- `--body -` reads the message from stdin, so a multi-line body survives
  intact.
- For any field the flags do not cover, `--set field=value` (repeatable). A
  wrong field name lists the ones that exist.
- Logging an interaction advances a prospect to engaged, in the same commit.
  That is intended.

A value the store rejects prints `could not create: field: why` and exits 2;
nothing is written and nothing is committed.

## Writing

- Prefer `hermitcrm add` over hand-written YAML, and the web app or a hand edit
  of front matter over ad-hoc scripts.
- Keep front-matter keys you do not recognise; Hermit CRM preserves them.
- After editing files by hand, run `hermitcrm check`, then `hermitcrm rebuild`.
- Commit messages for agent-made changes start with `ai:`.
- Never rewrite interaction bodies; they are the record.
- Never put secrets in `config.toml` and never commit `.secrets.toml`.

## Skills for Claude Code

Every data folder has six Claude Code skills in `.claude/skills/`. Type the name
in Claude Code, or just ask, and Claude picks the one that fits:

| Skill | What it does |
| --- | --- |
| `/hermit` | Change Hermit itself: fields, dashboards, layout, routines, the look (see below). |
| `/hermit-daily` | The morning review: overdue and today's tasks, replies you owe, today's meetings, drafts waiting. Reads only. |
| `/hermit-log` | Log a call or meeting from your notes, with its follow-up tasks; a stage move only after you agree. |
| `/hermit-research` | Research a prospect and keep the findings, with their sources, as a note on the company. |
| `/hermit-weekly` | The weekly review: the week in numbers, deals that went quiet, what matters next week. Reads only. |
| `/hermit-import` | Bring in a CSV, TSV or .xlsx list: a preview first, the import only after you say yes. |

Each skill names the commands to run in order (and the MCP tools, for an app
without a shell), and keeps the same rules: a dry run before a change to many
records, one commit per change, and never sending anything.

A folder made by an older Hermit gets the skills from `hermitcrm migrate`, and
`hermitcrm doctor` says when one is missing. A skill you have edited is yours:
Hermit never overwrites it. Delete one you do not want; it stays deleted until
you run `hermitcrm migrate` again.

## Adjusting Hermit

When the user asks you to change Hermit CRM itself (a field, the look, a
dashboard, a page layout, templates, a routine, many records at once), run
`hermitcrm help adjust` first and follow it. It lists the files you may write
without asking, the recipe for each kind of change, and the rules: records only
through `hermitcrm add` and `hermitcrm set` (dry run first), `hermitcrm check`
after every change, one commit per change named `ai: adjust: <what>`, drafts
only and never sending anything. `hermitcrm undo <commit>` reverses a change with
a new commit. See [Make it yours](/help/adjust).

## Backups and undo

The folder is backed up every few minutes to a repository outside it that
only grows (`hermitcrm backup status` says where; see
[Backups and undo](/help/backups)). For an agent that means:

- Never rewrite history in the folder: no `git reset --hard`, `commit --amend`,
  `rebase`, `filter-branch` or `push --force`. Undo with a new commit
  (`git revert`, or `hermitcrm backup restore`). A rewrite is not lost -- the
  backup keeps both lines and flags it -- but it is noisy and looks like damage.
- Never touch `~/.hermitcrm/backups/`, `.git/hermitcrm-backup.json` or
  `.claude/settings.json`.
- To undo damage, find the version with `hermitcrm backup list <path>`, check
  with `hermitcrm backup restore <id> <path>` (a dry run), then add `--apply`.
  Say what you restored and from which version.

**For Claude Code, these commands are blocked, not just discouraged.** Every
data folder has a `.claude/settings.json` whose deny list refuses `git reset
--hard`, `commit --amend`, `rebase`, `push --force`, `filter-branch`,
`git clean -f`, `rm -rf .git` and the rest (also as `git -C <dir> ...`), in
every permission mode, bypass included. The full list and its limits are in
[Backups and undo](/help/backups), its first section. A
refusal there is the rule working: make a new commit instead, and do not
try another spelling, a script or `bash -c` to get round it.

Other agents (Codex, Gemini, ...) have no such file and get these rules as
text in `AGENTS.md`. A deny list matches command patterns, so it is a seat
belt, not a lock; the backup is what makes a command that gets past it
survivable.

## What the web app does with hand edits

A company page re-reads that company's folder on every request, so an edit
shows up without a restart; the Reload button (or `hermitcrm rebuild`,
`POST /reload`) rebuilds the whole index. Validation problems (an unknown
stage, a missing name) never crash the app: `hermitcrm check` and `/health` list
them with file paths.

Related: [Data format](/help/data-format), [CLI](/help/cli), [Pipeline](/help/pipeline)

## Connect your AI

**Settings > Advanced > Connect your AI** shows the exact line or block for
Claude Code, Claude Desktop and Cursor, already filled in with this folder's
path and the full path of the `hermitcrm` command, each with a copy button.
Hermit only shows the text: it changes nothing in the AI app's settings, and
nothing outside the data folder.

- **Claude Code** needs no setup in the folder: open it there (`cd <folder> &&
  claude`) and it has the rules and the skills above. To reach the CRM from
  Claude Code in any other folder, the section gives the one-time
  `claude mcp add --scope user hermitcrm -- ...` line.
- **Claude Desktop** and **Cursor** take the JSON block below, in
  `claude_desktop_config.json` or `~/.cursor/mcp.json`.

If Hermit cannot find where `hermitcrm` is installed, the section says so: run
`which hermitcrm` and use the path it prints, because a desktop app does not
search your terminal's PATH. The section also lists the skills, and says when
one is missing (`hermitcrm migrate` adds it).

## Connecting over MCP

`hermitcrm mcp` serves one data folder to any MCP client, over stdio. It adds no
dependency: MCP's stdio transport is newline-delimited JSON-RPC, which is all
this speaks.

For Claude Desktop, add this to `claude_desktop_config.json` (Settings →
Developer → Edit Config):

```json
{
  "mcpServers": {
    "hermitcrm": {
      "command": "hermitcrm",
      "args": ["--data", "/Users/you/crm", "mcp"]
    }
  }
}
```

Use the full path to the `hermitcrm` binary if it is not on the launcher's PATH
(`which hermitcrm` prints it). Other clients take the same command and arguments.
The client starts the process and talks to it over a pipe, so it has to run on
the machine holding the folder. A phone reaches the CRM through the web app
(`hermitcrm serve --host 0.0.0.0`), not through this.

If you already have a shell in the folder, you do not need any of this: the CLI
is strictly more capable, because it can also grep, read a single interaction
and use git. MCP is for the client that has no shell.

The tools, reads first:

| Tool | What it gives |
| --- | --- |
| `list_pipeline` | The whole pipeline as one page. Start here. |
| `search_companies` | Turn a name into a slug. |
| `show_company` | One account: fields, contacts, timeline, recent bodies. |
| `company_folder` | The company's client folder on this computer: its path and the files in it, newest first (read-only; see [Client folders](/help/companies#client-folders)). |
| `digest` | Interactions in the last N days. |
| `report` | Activity, funnel, time in stage, outcomes, hygiene. |
| `followups` | Threads you owe a reply, then ones you are waiting on. |
| `keep_in_touch` | People outside an open deal you have not spoken to in a while. |
| `brief` | Each upcoming meeting with the record behind it. |
| `search` | A word anywhere: companies, people, task text, and the subject and body of every message. |
| `show_contact` | One person: fields (custom ones too), their tasks, every interaction with them. |
| `list_tasks` | The to-do list: overdue, today, the next 7 days, every open task, or done; for one company or all. |
| `list_outreach` | The Outreach drafts by status (drafted, ready, skipped, sent, ...). |
| `show_outreach` | One draft in full: who it is for, research, checks, subject and text. |
| `list_routines` | The routines, on or paused, what each does and how its last run went. |
| `add_company` | Create a company; returns the slug. `notes` is saved as a company note, not a body. |
| `add_contact` | Create a contact under a company. |
| `add_interaction` | Log an email, message, call or meeting. |
| `update_company` | Change fields of a company (custom ones too), as its edit form does. |
| `update_contact` | Change fields of a contact (custom ones too). |
| `move_stage` | Move a deal to another stage, with a reason and a requalify date; the stage rules apply. |
| `add_task` | Add a task to a company or one of its people. |
| `complete_task` | Tick a task off (its id comes from `list_tasks`). |
| `reopen_task` | Open a done task again. |
| `edit_outreach_draft` | Change a draft's text; it is kept as a tracked edit and stays a draft. |
| `skip_outreach` | Take a draft out of the queue, with a reason. |
| `adjust_help` | A Make it yours recipe: `adjust` (the rules) or `adjust-<topic>`. |
| `adjust_read` | The text of a file you may change, or which of them exist. |
| `adjust_write` | Replace one of those files: checked first, then one commit. |
| `adjust_config` | Change `task_types`, `outcomes` or `silent_days`; one commit. |
| `bulk_preview` | The dry run of a change to many records, with a `preview_id`. |
| `bulk_apply` | Apply that change after the user said yes; one commit. |
| `undo` | Reverse one commit with a new one (`git revert`). |

Thirty-three tools: eighteen that only read (`adjust_help`, `adjust_read` and
`bulk_preview` included) and fifteen that write. The record tools (`add_*`,
`update_*`, `move_stage`, the task tools) are the same `store` calls the web forms
and `hermitcrm add` make, and the two outreach tools the same calls as the
Outreach page, so validation, slugging, the stage rules, the prospect-to-engaged
move and the git commit are shared rather than copied. Each one writes a file and
makes one commit, so call them only when the user has asked for the change. The
answer of every write after the first three gives its commit id: `undo(<id>)`
reverses it.

### Resources and prompts

Besides tools, the server offers three things to read without a tool call
(resources) and four ready-made jobs (prompts). How a client shows them is up to
the client: Claude Desktop puts both under the **+** button.

| Resource | What it is |
| --- | --- |
| `hermitcrm://pipeline` | `PIPELINE.md` as it is now. |
| `hermitcrm://playbook` | Your messaging playbook, `MESSAGING.md`. |
| `hermitcrm://companies/{slug}` | One company, as `show_company` gives it. |

| Prompt | What it asks the agent to do |
| --- | --- |
| `morning_review` | Overdue and today's tasks, replies you owe, today's meetings, drafts waiting, and what to do first. Reads only. |
| `prep_meeting` | A one-page brief on one company (give its name or slug). Reads only. |
| `log_call` | Log a call from your notes, add the follow-up task, and propose a stage move, which it makes only after you agree. |
| `weekly_review` | The week in numbers, deals that went quiet, and what matters next week. Reads only. |

A prompt is a short instruction that names the tools to call; the agent still
asks you before anything it was not told to write.

### What an agent cannot do over MCP

These are left out on purpose, not forgotten. Each is a person's decision, made
in the web app:

- **Mark a draft ready, schedule it or send it.** An agent may read a draft,
  edit its text and skip it. Approving and sending a message is yours; no tool
  name contains `send`, `ready` or `schedule`, and a test keeps it that way.
- **Run a routine or turn one on.** A run asks your AI tool and writes drafts.
  `list_routines` shows them; `adjust_write` can only add one paused.
- **Delete anything.** No tool deletes a company, contact, interaction, task or
  draft. `undo` reverses a commit with a new one, so nothing is lost.
- **Change settings** beyond `task_types`, `outcomes` and `silent_days`
  (`adjust_config`). The stage rules, sending, AI and every other setting stay
  in Settings.
- **Move a stage the rules forbid.** The web app offers "Move anyway"; over MCP
  there is no such override: `move_stage` names the moves that are allowed.

### Make it yours over MCP

A client with no shell (Claude Desktop, ChatGPT) can change Hermit itself the
way an agent with a shell does with `hermitcrm help adjust`, and the rules that
page asks an agent to keep are enforced rather than only written down:

- `adjust_help` first: the rules, then the recipe for the kind of change.
- `adjust_write` takes only `fields.toml`, `layout.toml`,
  `dashboards/<name>.toml`, `routines.toml`, `theme.css`, `messages.toml` and
  `MESSAGING.md`, and no path outside the folder. It runs the checks of
  `hermitcrm check` on the new text first: a problem leaves the file as it was,
  makes no commit and comes back as `<file>: <where>: <what>` lines to fix. A
  file with changes that are not committed yet is not overwritten.
- A routine written this way arrives paused (`paused = true`, and the answer
  says so), unless it was already on and you left what it does alone: change
  its selector, filters, prompt, action, channel, days or limit and it is paused
  again (only `title` and `paused` may differ). The user previews it and turns
  it on.
- `adjust_config` changes only `task_types`, `outcomes` and `silent_days`,
  through the same code Settings saves them with.
- `bulk_apply` refuses unless its `preview_id` comes from a `bulk_preview` of
  the same scope, filters and changes on the folder as it is now, so the dry
  run always comes first. Interaction bodies are never changed.
- Every write is one commit (`ai: adjust: <summary>` or `bulk: ...`), and the
  answer gives its id for `undo`. Nothing is ever sent: messages are drafts.

Every tool carries a title and the protocol's four hints, so a client can show
which tools only read and ask before the ones that write: read-only or not,
destructive (overwrites something) or only adding, idempotent (calling it twice
changes nothing more) or not, and closed-world for all of them, because a tool
only ever works on this data folder.

The six newer read tools (`search` to `list_routines`) also answer with
structured data, described by each tool's output schema, beside the text. The
ones that list take `limit` (default 20, at most 100) and, for the rows after
those, the `cursor` the previous answer gave as `next_cursor`.

Every tool re-reads the folder before answering, so a long-lived MCP session
does not serve a snapshot from whenever the client connected.

A rejected value comes back as a tool error the model can read and retry
(`could not write: country: unknown country 'ZZZZ'`), not as a protocol error,
and nothing is written.
