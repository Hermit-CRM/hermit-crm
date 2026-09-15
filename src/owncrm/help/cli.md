# CLI

`owncrm [--data DIR] <command>`: the data folder is `--data`, then `$OWNCRM_DATA`, then the current directory.

Commands that write take `--apply`; without it they print what they would
do. Every write is one git commit. Output is plain text meant to be read or
pasted into an AI session.

## Set up and run

```text
owncrm init DIR [--demo] [--no-setup]   new data folder (git repo, config, agent rules); asks the setup questions
owncrm setup                            the setup questions again (you, BCC, backup, calendar)
owncrm serve [--port N]                 the web app on 127.0.0.1 (port from config.toml, default 8765)
owncrm doctor [--online]                one ok/warn/fail line per check; exit 1 on a failure
owncrm schedule install [--at HH:MM] [--serve]
                                        daily sync --apply via launchd or systemd (schtasks printed on Windows)
owncrm schedule remove|status
owncrm migrate [--dry-run]              upgrade the data format (every command does this automatically)
owncrm help [TOPIC]                     these pages; no topic prints the index and the topic list
```

## Read

```text
owncrm show SLUG [--bodies N | --all]   one company: fields, notes, contacts, interactions, the last 3 bodies
owncrm digest [--days 7]                recent interactions oldest first, 150 characters of body each
owncrm report [--days N | --from D --to D] [--md]
                                        the Reports page as text tables (Markdown with --md)
owncrm check                            validate every file; exit 1 and the file paths on problems
```

## Write

```text
owncrm rebuild                          rebuild the index and PIPELINE.md, commit "pipeline: rebuild"
owncrm import FILE [--mode companies|contacts] [--map HEADER=FIELD ...] [--apply]
owncrm fetch SLUG [--url URL] [--apply] fields from the website or LinkedIn page (no AI)
owncrm enrich SLUG [--contact CSLUG] [--apply]
                                        fields from an AI CLI
owncrm bcc [--apply] [--eml FILE ...]   import BCC'd or forwarded mail (or .eml files)
owncrm calendar [--apply] [--ics FILE ...]
                                        import past meetings from the ICS feed (or .ics files)
owncrm sync [--apply]                   bcc, then calendar; what the daily job runs
owncrm backfill-history [--apply]       stage_history from git for companies without one
```

`bcc`, `calendar` and `sync` with `--apply` tell a running web app to reload
its index afterwards.

Related: [Settings](/help/settings), [AI agents](/help/ai-agents), [Data format](/help/data-format)
