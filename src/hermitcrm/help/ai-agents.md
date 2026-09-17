# AI agents

How an AI session (Claude Code, Codex or any agent) should read and write a Hermit CRM data folder; the same rules are in the folder's `CLAUDE.md` and `AGENTS.md`.

The data folder is plain files in git, so an agent works in it like a person
would: read what is needed, edit front matter, commit. Run `hermitcrm` commands
from the folder, or add `--data <folder>`.

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

## What the web app does with hand edits

A company page re-reads that company's folder on every request, so an edit
shows up without a restart; the Reload button (or `hermitcrm rebuild`,
`POST /reload`) rebuilds the whole index. Validation problems (an unknown
stage, a missing name) never crash the app: `hermitcrm check` and `/health` list
them with file paths.

Related: [Data format](/help/data-format), [CLI](/help/cli), [Pipeline](/help/pipeline)
