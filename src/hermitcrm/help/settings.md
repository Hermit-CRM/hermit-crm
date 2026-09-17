# Settings

`/settings`: who you are, mail and calendar capture, backup, enrichment, outcomes, the review queue, the daily schedule and About.

Every section writes `config.toml` in the data folder, keeping its comments;
secrets (the mail app password, the calendar URL) go to `.secrets.toml`
(mode 600) or the macOS Keychain, never to `config.toml`. The first time the
web app starts without an owner email it opens this page once; "Skip for now"
goes to the board. The same questions run in the terminal as `hermitcrm setup`.

## You

Your name (its first word signs the drafts) and the addresses you send mail
from, comma-separated. Mail from these addresses counts as outbound; their
non-freemail domains become `bcc_ignore_domains`, so colleagues are never
logged as contacts.

## BCC capture

BCC or forward mail to a tracking address (for Gmail, `you+crm@gmail.com` is
suggested) and Hermit CRM reads it over IMAP with an app password. Gmail needs
2-step verification and an app password; the page shows the Gmail filter to
add so the copies skip your inbox. **Test connection** runs a dry-run import.
Per mail: an exact contact email match logs there; a new person at a company
whose website or contact domain matches becomes a contact; everything else
goes to the review queue. Dedup is by Message-ID.

## Calendar

The secret ICS address of your calendar (Google: Settings, your calendar,
Integrate calendar, secret address in iCal format; `webcal://` is fine).
It is tested with a dry run and never shown again. Past meetings with an
external attendee become `meeting` interactions; unmatched ones wait in the
review queue; events in the next 7 days show on the Calendar page.

## Backup

A git remote (must be **private**: the folder holds your contacts and mail).
Saving sets or updates the remote, tries a push, and turns `push_enabled` on
when it worked. Pushes then run in the background after every commit and
never block.

## Enrichment

`enrich_provider` (`auto`, `claude`, `codex`, `gemini`, `grok` or `custom`),
`enrich_command`, `enrich_model` and `enrich_timeout`. The section shows which
CLI is in use, or why none is. Under launchd or systemd the process starts
with a bare PATH, so the CLI must be in `/usr/local/bin`, `/opt/homebrew/bin`
or `~/.local/bin`, or the command must be a full path. See [Enrich](/help/enrich).

## Outcomes

The outcome choices for interactions, one per line, in order: the first is
what a detected reply counts as, the last what silence past the message
window counts as. Also here: `message_window_days` (default 14) and
`silent_days` (default 14, the Calendar's silent list and `PIPELINE.md`).
Duplicates and an empty list are refused.

## Review queue

Mail and meetings the imports could not place: the date, kind, direction,
person and subject, the reason (personal address, unknown domain, several
matching companies), the text collapsed, and a form to **Log at company**
(company slug or exact name; the contact is found by email, else a same-named
contact gets the email, else it is created) or **Discard** (remembered in
`inbox/discarded.tsv`). **Import now** and **Import meetings now** run the
imports on the spot. The nav shows the count on the Settings link and a red
`!` when the last import failed or is two days old.

## Schedule

Read-only status of the daily job (`hermitcrm sync --apply`: BCC, then calendar)
installed by `hermitcrm schedule install [--at HH:MM] [--serve]` through launchd
(macOS) or systemd user units (Linux); on Windows the `schtasks` commands are
printed for you to run. The install command to copy is on the page.

## About

Version and the update check (PyPI, at most once a day, no identifiers sent),
the data folder, its format version, and `hermitcrm doctor`, which checks the
whole installation line by line.

Related: [Interactions](/help/interactions), [Enrich](/help/enrich), [CLI](/help/cli), [Data format](/help/data-format)
