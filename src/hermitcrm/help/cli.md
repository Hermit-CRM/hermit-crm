# CLI

`hermitcrm [--data DIR] <command>`: the data folder is `--data`, then `$HERMITCRM_DATA`, then the current directory.

Commands that write take `--apply`; without it they print what they would
do. Every write is one git commit. Output is plain text meant to be read or
pasted into an AI session.

## Set up and run

```text
hermitcrm init DIR [--demo] [--no-setup]   new data folder (git repo, config, agent rules); asks the setup questions
hermitcrm setup                            the setup questions again (you, BCC, backup, calendar)
hermitcrm serve [--port N]                 the web app on 127.0.0.1 (port from config.toml, default 8765)
hermitcrm doctor [--online]                one ok/warn/fail line per check; exit 1 on a failure
hermitcrm schedule install [--at HH:MM] [--serve] [--backup-every MIN | --no-backup]
                                        daily sync --apply and a backup every 5 minutes, via launchd
                                        or systemd (schtasks printed on Windows)
hermitcrm schedule remove|status
hermitcrm migrate [--dry-run]              upgrade the data format (every command does this automatically)
hermitcrm help [TOPIC]                     these pages; no topic prints the index and the topic list
```

## Read

```text
hermitcrm show SLUG [--bodies N | --all]   one company: fields, notes, contacts, interactions, the last 3 bodies
hermitcrm digest [--days 7]                recent interactions oldest first, 150 characters of body each
hermitcrm followups [--reply-after N] [--nudge-after N]
                                        threads you owe a reply, then ones you are waiting on
hermitcrm brief [--days 7]                 each upcoming meeting with its stage, next step, contacts and last 3 interactions
hermitcrm mcp                              serve this folder to AI clients over MCP (stdio); see the AI agents topic
hermitcrm report [--days N | --from D --to D] [--md]
                                        the Reports page as text tables (Markdown with --md)
hermitcrm check                            validate every file; exit 1 and the file paths on problems
```

## Backups

```text
hermitcrm backup [run] [--quiet]           back up now: new commits, uncommitted edits, a rewrite kept aside
hermitcrm backup status                    where the backup is, its size, the last run; exit 1 on a warning
hermitcrm backup list [PATH] [-n 20]       versions in the backup, newest first, optionally only those touching PATH
hermitcrm backup restore ID [PATH ...] [--apply]
                                        put files back as they were in version ID, as a new commit
hermitcrm backup guard                     block history-rewriting git commands for Claude Code (.claude/settings.json)
```

See [Backups and undo](/help/backups).

## Write

```text
hermitcrm add company NAME [--country NL] [--website URL] [--stage S] [--set FIELD=VALUE ...]
                                        create a company; prints its slug. Writes and commits at once (no --apply)
hermitcrm add contact SLUG NAME [--title T] [--email E] [--phone P] [--role R] [--notes N]
                                        create a contact under a company; the name is split into first and last
hermitcrm add interaction SLUG --channel email|linkedin|call|meeting --direction in|out
                                        [--contact CSLUG] [--subject S] [--date D] [--body TEXT|-]
                                        log an interaction; --body - reads it from stdin, and a prospect becomes engaged
hermitcrm rebuild                          rebuild the index and PIPELINE.md, commit "pipeline: rebuild"
hermitcrm import FILE [--mode companies|contacts] [--map HEADER=FIELD ...] [--apply]
hermitcrm fetch SLUG [--url URL] [--apply] fields from the website or LinkedIn page (no AI)
hermitcrm enrich SLUG [--contact CSLUG] [--apply]
                                        fields from an AI CLI
hermitcrm bcc [--apply] [--eml FILE ...]   import BCC'd or forwarded mail (or .eml files)
hermitcrm calendar [--apply] [--ics FILE ...]
                                        import past meetings from the ICS feed (or .ics files)
hermitcrm sync [--apply]                   bcc, then calendar; what the daily job runs
hermitcrm backfill-history [--apply]       stage_history from git for companies without one
```

`bcc`, `calendar` and `sync` with `--apply` tell a running web app to reload
its index afterwards.

Related: [Settings](/help/settings), [AI agents](/help/ai-agents), [Data format](/help/data-format)
