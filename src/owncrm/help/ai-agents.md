# AI agents

How an AI session (Claude Code, Codex or any agent) should read and write an OwnCRM data folder; the same rules are in the folder's `CLAUDE.md` and `AGENTS.md`.

The data folder is plain files in git, so an agent works in it like a person
would: read what is needed, edit front matter, commit. Run `owncrm` commands
from the folder, or add `--data <folder>`.

## Reading, cheapest first

1. Read `PIPELINE.md` first. For a pipeline review it is usually enough: one
   line per company, about 30 tokens each.
2. For one account, run `owncrm show <slug>` rather than opening its files.
3. For "what happened recently", run `owncrm digest --days 7`.
4. For numbers (activity, funnel, outcomes, messages), run
   `owncrm report --days 30 --md`.
5. Open interaction files directly only when the exact wording matters
   (drafting a reply, judging tone). Never read all interactions.
6. Never edit `PIPELINE.md` by hand; it is generated.
7. For outreach wording, read `MESSAGING.md` (the playbook) and
   `messages.toml` (if present) before drafting anything.
8. For how a feature works, run `owncrm help <topic>` (`owncrm help` lists
   the topics).

## Writing

- Prefer the web app or a hand edit of front matter over ad-hoc scripts.
- Keep front-matter keys you do not recognise; OwnCRM preserves them.
- After editing files by hand, run `owncrm check`, then `owncrm rebuild`.
- Commit messages for agent-made changes start with `ai:`.
- Never rewrite interaction bodies; they are the record.
- Never put secrets in `config.toml` and never commit `.secrets.toml`.

## What the web app does with hand edits

A company page re-reads that company's folder on every request, so an edit
shows up without a restart; the Reload button (or `owncrm rebuild`,
`POST /reload`) rebuilds the whole index. Validation problems (an unknown
stage, a missing name) never crash the app: `owncrm check` and `/health` list
them with file paths.

Related: [Data format](/help/data-format), [CLI](/help/cli), [Pipeline](/help/pipeline)
