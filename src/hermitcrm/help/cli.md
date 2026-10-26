# CLI

`hermitcrm [--data DIR] <command>`: the data folder is `--data`, then `$HERMITCRM_DATA`, then the current directory.

Commands that write take `--apply`; without it they print what they would
do. Every write is one git commit. Output is plain text meant to be read or
pasted into an AI session.

## Set up and run

```text
hermitcrm init DIR [--demo] [--no-setup]   new data folder (git repo, config, agent rules, /hermit skill); asks the setup questions
hermitcrm sample add|remove                the made-up sample account in this folder, with a dashboard and a paused
                                        routine: load it, or delete it again (what you changed stays)
hermitcrm setup                            the setup questions again (you, BCC, backup, calendar)
hermitcrm serve [--port N]                 the web app on 127.0.0.1 (port from config.toml, default 8765)
hermitcrm doctor [--online]                one ok/warn/fail line per check; exit 1 on a failure
hermitcrm schedule install [--at HH:MM] [--serve] [--send] [--backup-every MIN | --no-backup]
                                        daily sync --apply and a backup every 5 minutes, via launchd
                                        or systemd (schtasks printed on Windows); --send also installs
                                        the worker that sends scheduled email every 3 minutes
hermitcrm schedule remove [--send]         remove the jobs (--send: only the sending worker)
hermitcrm schedule status
hermitcrm migrate [--dry-run]              upgrade the data format (every command does this automatically);
                                        also puts back a missing /hermit skill (.claude/skills/hermit/)
hermitcrm help [TOPIC]                     these pages; no topic prints the index and the topic list
```

## Read

```text
hermitcrm show SLUG [--bodies N | --all]   one company: fields, an old notes text while one is left, contacts, interactions, the last 3 bodies
hermitcrm digest [--days 7]                recent interactions oldest first, 150 characters of body each
hermitcrm followups [--reply-after N] [--nudge-after N]
                                        threads you owe a reply, then ones you are waiting on
hermitcrm keep-in-touch [--after N]        people outside an open deal you have not spoken to in N days
                                        (default keep_in_touch_days, 180), longest first
hermitcrm brief [--days 7]                 each upcoming meeting with its stage, next step, contacts and last 3 interactions
hermitcrm mcp                              serve this folder to AI clients over MCP (stdio); see the AI agents topic
hermitcrm report [--days N | --from D --to D] [--md]
                                        the Reports page as text tables (Markdown with --md)
hermitcrm check                            validate every file (records, fields.toml, layout.toml, dashboards/,
                                        routines.toml, theme.css, messages.toml, config.toml, the front
                                        matter of MESSAGING.md); exit 1 and one "file: where: what" line
                                        per problem
hermitcrm playbook [status]                per approach: what the playbook has and what the outreach bot
                                        still needs (exit 1 while no approach is ready); see
                                        `hermitcrm help playbook`
hermitcrm playbook upgrade [--dry-run]     add the front matter and missing headings to MESSAGING.md,
                                        keeping every line; one commit, and a second run changes nothing
hermitcrm outreach preview [--where K=V ...] [--contact CO/PERSON] [--channel email|linkedin]
                         [--limit N] [--approach NAME] [--kind first-touch|reply-to-interest|follow-up]
                                        who an outreach batch would go to, and why not the rest; no AI,
                                        nothing written
hermitcrm outreach build (same flags) [--research scrape] [--strong] [--framework ID]
                                        research, draft and check each contact: one item per contact in
                                        outreach/, one commit per step; refused until the playbook is ready;
                                        --framework writes the first touches with that framework (default:
                                        the approach's, else house); see `hermitcrm help outreach`
hermitcrm outreach list [--state S]        every item, newest first
hermitcrm outreach show ID                 one item in full: links, findings, flags, checks, the draft
hermitcrm outreach edits [--positive] [--noted]
                                        your tracked edits as Markdown: the AI's original, each change
                                        with your explainer, and how the message was answered
hermitcrm outreach ready ID [--tag T ...]  approve a draft (the checks run again on your text; a failing
                                        one is a warning); never sent; --tag says why you changed it
                                        (too-long, wrong-tone, wrong-pain, bad-finding, wrong-fact, cliche, other)
hermitcrm outreach sent ID                 you sent it (logging the message does this too); logs nothing
hermitcrm outreach skip ID --reason R [--note TEXT]
                                        drop an item: bad-fit, wrong-person, bad-timing, bad-draft,
                                        already-in-contact or other
hermitcrm outreach schedule ID... | --all-ready [--dry-run]
                                        queue approved email to go out over the working day, spaced
                                        and capped; --dry-run shows the times and writes nothing
hermitcrm outreach unschedule ID           take a queued item out of the queue (back to ready)
hermitcrm outreach front ID                make a queued item the next to go out
hermitcrm outreach retry ID                a failed item back to ready
hermitcrm outreach send-now ID             send one approved email now (same checks, counts toward the cap)
hermitcrm outreach opt-out COMPANY/CONTACT
                                        they asked not to be written to: suppress the address and skip
                                        their open items
hermitcrm send test [--to ADDRESS]         log in over SMTP and IMAP and mail a test to yourself
hermitcrm send status                      on/off, today's count against the cap, the queue, why paused
hermitcrm send due [--dry-run]             one tick of the worker (at most one email per run)
hermitcrm send pause | resume              the kill switch, and lifting any pause
```

See [Sending](/help/sending) for how it works.

## Learning

```text
hermitcrm learn report [--approach A]      phase, efficiency trend, patterns, outcome rates, style features; no AI
hermitcrm learn status [--approach A]      what a run would send and cost, pending proposals; no AI
hermitcrm learn run [--approach A]         distill your edits into proposals (one AI call), or write the
                                        evidence pack when learning_distill = "handoff"
hermitcrm learn import [--approach A]      read learning/proposals.json after a handoff run
hermitcrm learn accept ID [--text T]       apply a pending proposal to the Lessons (optionally reworded)
hermitcrm learn reject ID                  reject it for good
hermitcrm learn retire LESSON [--approach A]        remove a lesson
hermitcrm learn move LESSON worked|failed|open [--approach A]   move a lesson
hermitcrm learn exemplars [--approach A] [--item ID]   the examples a draft can be shown; --item previews one prompt block
hermitcrm learn pin|exclude|unmark ID      pin an example, never show it (the way to delete one), or clear that
hermitcrm learn suggest                    list the word-limit and never-write suggestions
hermitcrm learn apply SUGGESTION           apply one; see `hermitcrm help learning`
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
hermitcrm add interaction SLUG --channel email|linkedin|call|whatsapp|meeting|note --direction in|out (not for a note)
                                        [--contact CSLUG] [--subject S] [--date D] [--body TEXT|-]
                                        log an interaction; --body - reads it from stdin, and a prospect becomes engaged
                                        (the first open stage moves to the next)
hermitcrm set companies|contacts|interactions --where KEY=VALUE ... [--all]
        [--set FIELD=VALUE ...] [--unset FIELD ...] [--add-tag T ...] [--remove-tag T ...]
        [--stage S] [--apply] [--message TEXT]
                                        change many records at once. A dry run unless --apply (count, five
                                        before -> after samples), then ONE commit `bulk: <summary>` and its
                                        undo command. --where is the list pages' filter syntax; no --where
                                        needs --all. Bodies and names are never touched. See Make it yours: bulk changes
hermitcrm stages [rename OLD NEW | add NAME | move NAME | set NAME | remove NAME] [--apply]
                                        the deal stages and their roles; a dry run unless --apply (rewrites
                                        companies, one `ai: adjust:` commit per step). See Make it yours: deal stages
hermitcrm rebuild                          rebuild the index and PIPELINE.md, commit "pipeline: rebuild"
hermitcrm import FILE [--mode companies|contacts] [--map HEADER=FIELD ...] [--apply]
hermitcrm export [--format csv|json] [--profile generic|hubspot|pipedrive] [--excel] [-o PATH]
                                        everything as a zip of CSVs (or one JSON file); reads only. See Import and export
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

`bcc`, `calendar`, `sync`, `set` and `stages` with `--apply` tell a running web app to
reload its index afterwards.

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

Related: [Settings](/help/settings), [AI agents](/help/ai-agents), [Data format](/help/data-format), [Make it yours: bulk changes](/help/adjust-bulk), [Make it yours: deal stages](/help/adjust-stages)
