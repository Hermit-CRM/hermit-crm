# CLI

`hermitcrm [--data DIR] <command>`: the data folder is `--data`, then `$HERMITCRM_DATA`, then the current directory.

Commands that write take `--apply`; without it they print what they would
do. Every write is one git commit. Output is plain text meant to be read or
pasted into an AI session.

## Set up and run

```text
hermitcrm init DIR [--demo] [--no-setup]   new data folder (git repo, config, agent rules); asks the setup questions
hermitcrm sample add|remove                the made-up sample account in this folder: load it, or delete it again
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
hermitcrm check                            validate every file (records, fields.toml, layout.toml, dashboards/,
                                        routines.toml, theme.css, messages.toml, config.toml); exit 1 and
                                        one "file: where: what" line per problem
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
                                        create a contact under a company; the name is split into first and last;
                                        --notes is logged as a note interaction on them
hermitcrm add interaction SLUG --channel email|linkedin|call|meeting|note --direction in|out (not for a note)
                                        [--contact CSLUG] [--subject S] [--date D] [--body TEXT|-]
                                        log an interaction; --body - reads it from stdin, and a prospect becomes engaged
hermitcrm set companies|contacts|interactions --where KEY=VALUE ... [--all]
        [--set FIELD=VALUE ...] [--unset FIELD ...] [--add-tag T ...] [--remove-tag T ...]
        [--stage S] [--apply] [--message TEXT]
                                        change many records at once. A dry run unless --apply (count, five
                                        before -> after samples), then ONE commit `bulk: <summary>` and its
                                        undo command. --where is the list pages' filter syntax; no --where
                                        needs --all. Bodies and names are never touched. See Adjust: bulk changes
hermitcrm rebuild                          rebuild the index and PIPELINE.md, commit "pipeline: rebuild"
hermitcrm import FILE [--mode companies|contacts] [--map HEADER=FIELD ...] [--apply]
hermitcrm fetch SLUG [--url URL] [--apply] fields from the website or LinkedIn page (no AI)
hermitcrm enrich SLUG [--contact CSLUG] [--apply]
                                        fields from an AI CLI
hermitcrm bcc [--apply] [--eml FILE ...]   import BCC'd or forwarded mail (or .eml files)
hermitcrm calendar [--apply] [--ics FILE ...]
                                        import past meetings from the ICS feed (or .ics files)
hermitcrm sync [--apply]                   bcc, then calendar, then every routine that is on; what the daily job runs
hermitcrm backfill-history [--apply]       stage_history from git for companies without one
hermitcrm undo COMMIT                      reverse one commit with a new one (git revert); refuses a merge,
                                        an unknown commit or uncommitted changes, and stops on a conflict
```

`bcc`, `calendar`, `sync` and `set` with `--apply` tell a running web app to reload
its index afterwards.

`set` exits 0 for a dry run, a finished change and "nothing matches"; 2 when it
refused the request before writing anything; 1 when a write was tried and rolled
back (every file is as it was, nothing committed).

## Routines

```text
hermitcrm routines [list]                  every routine in routines.toml, on or paused, and its last run
hermitcrm routines preview NAME [--try]    who it would pick now, no AI and no writes; --try shows one AI draft, not saved
hermitcrm routines run [NAME] [--apply]    one routine (even a paused one) or all that are on; one commit per routine
hermitcrm routines on NAME                 turn it on: it runs after each daily sync (commit "routine: NAME: turned on")
hermitcrm routines off NAME                pause it
```

Drafts go to Home, never out. See [Routines](/help/adjust-routines).
`undo` is what the Undo buttons on the Make it yours page run; see
[Make it yours](/help/adjust).

Related: [Settings](/help/settings), [AI agents](/help/ai-agents), [Data format](/help/data-format), [Adjust: bulk changes](/help/adjust-bulk)
