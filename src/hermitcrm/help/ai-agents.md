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
   `messages.toml` (if present) before drafting anything.
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

## Backups and undo

The folder is backed up every few minutes to a repository outside it that
only grows (`hermitcrm backup status` says where; see
[Backups and undo](/help/backups)). For an agent that means:

- Never rewrite history in the folder: no `git reset --hard`, `commit --amend`,
  `rebase`, `filter-branch` or `push --force`. Undo with a new commit
  (`git revert`, or `hermitcrm backup restore`). A rewrite is not lost -- the
  backup keeps both lines and flags it -- but it is noisy and looks like damage.
- Never touch `~/.hermitcrm/backups/` or `.git/hermitcrm-backup.json`.
- To undo damage, find the version with `hermitcrm backup list <path>`, check
  with `hermitcrm backup restore <id> <path>` (a dry run), then add `--apply`.
  Say what you restored and from which version.

For Claude Code, a deny list in the data folder's `.claude/settings.json` stops
those commands before they run (deny rules apply in every permission mode):

```json
{
  "permissions": {
    "deny": [
      "Bash(git reset --hard:*)", "Bash(git push --force:*)", "Bash(git push -f:*)",
      "Bash(git push --force-with-lease:*)", "Bash(git commit --amend:*)",
      "Bash(git rebase:*)", "Bash(git filter-branch:*)", "Bash(git filter-repo:*)",
      "Bash(git update-ref -d:*)", "Bash(git reflog expire:*)", "Bash(git gc --prune:*)",
      "Bash(rm -rf .git:*)", "Bash(rm -rf companies:*)",
      "Edit(~/.hermitcrm/**)", "Write(~/.hermitcrm/**)"
    ]
  }
}
```

A deny list matches command prefixes, so it is a seat belt, not a lock: a
determined `bash -c "..."` gets past it. The backup is what makes that safe.

## What the web app does with hand edits

A company page re-reads that company's folder on every request, so an edit
shows up without a restart; the Reload button (or `hermitcrm rebuild`,
`POST /reload`) rebuilds the whole index. Validation problems (an unknown
stage, a missing name) never crash the app: `hermitcrm check` and `/health` list
them with file paths.

Related: [Data format](/help/data-format), [CLI](/help/cli), [Pipeline](/help/pipeline)

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
| `digest` | Interactions in the last N days. |
| `report` | Activity, funnel, time in stage, outcomes, hygiene. |
| `followups` | Threads you owe a reply, then ones you are waiting on. |
| `brief` | Each upcoming meeting with the record behind it. |
| `add_company` | Create a company; returns the slug. |
| `add_contact` | Create a contact under a company. |
| `add_interaction` | Log an email, message, call or meeting. |

The three `add_` tools are the same `store.create_*` calls the web form and
`hermitcrm add` make, so validation, slugging, the prospect-to-engaged move and
the git commit are shared rather than copied. Each one writes a file and makes a
commit, so call them only when a record has actually been asked for.

Every tool re-reads the folder before answering, so a long-lived MCP session
does not serve a snapshot from whenever the client connected.

A rejected value comes back as a tool error the model can read and retry
(`could not write: country: unknown country 'ZZZZ'`), not as a protocol error,
and nothing is written.
