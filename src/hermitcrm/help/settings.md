# Settings

`/settings`: who you are, mail and calendar capture, backup, appearance, fields of your own, AI (Enrich and Ask the Hermit), outcomes, the review queue, the daily schedule, access from a phone or an AI client, and About.

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

## Appearance

Night mode: off (`theme = "light"`), on (`"dark"`) or follow the operating
system (`"system"`).

## Fields

Fields of your own, on top of the ones Hermit CRM has: a key, a label, a type
(text, number, date or select) and where they show up. Add them one at a time,
or edit `fields.toml` whole in the box below the form -- that box is the file
itself, so what you save is what you are reading. Their values live in the
front matter of the record they belong to, like every other field.

Removing a field stops Hermit CRM showing it and leaves every value where it
is; describing it again brings them back. See [the data format](/help/data-format).

## BCC capture, per mail provider

Pick your **mail provider** and the IMAP server fills itself in, with a note on
where that provider hides its app password. Every one of them wants an app
password rather than your normal one, and that is the step people get stuck on.

- **Gmail / Google Workspace**: `imap.gmail.com`. Turn on 2-step verification
  first; the app password page does not appear until you do.
- **iCloud Mail**: `imap.mail.me.com`, an app-specific password from your Apple
  account.
- **Fastmail**: `imap.fastmail.com`, an app password with IMAP access.
- **Outlook.com / Microsoft 365**: Microsoft has switched off password sign-in
  for IMAP on most accounts, so this usually fails however the password is
  made. What works is forwarding or BCC'ing to a Gmail or Fastmail address kept
  for the purpose, and pointing Hermit CRM at that one.

## AI: Enrich and Ask the Hermit

`enrich_provider` (`auto`, `claude`, `codex`, `gemini`, `grok` or `custom`),
`enrich_command` and `enrich_timeout`.

**Account** (`enrich_account`) says how that CLI is signed in: `subscription`
(a ChatGPT, Claude or Gemini plan, the default) or `api` (an API key). It
matters because a plan is not entitled to the same model ids as an API key,
and asking for one it does not have fails outright rather than quietly
choosing something else: a Codex CLI signed in with a ChatGPT account answers
`The 'gpt-5-mini' model is not supported`. On a subscription Hermit CRM asks
for no particular model where that is known to matter, and the CLI answers on
whatever the plan gets. A model you type into the fields below is always used,
whatever the account type.

**Model** switches between the medium
tier (default; Claude: Opus) and the strong tier (Claude: Fable) for Enrich
and [Ask the Hermit](/help/ask); `ai_tier` in `config.toml`. Answers and proposals
made on the medium tier offer "Retry with" the strong model. The two model
fields (`enrich_model`, `enrich_model_strong`) override the provider defaults. The section shows which
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

## Access

Read-only: the two other ways into the same folder, both started from a
terminal.

**From your phone.** The web app binds to `host` in `config.toml`, `127.0.0.1`
by default, which only this machine can reach. `hermitcrm serve --host 0.0.0.0`
binds every interface and prints the LAN address to open on the phone; setting
`host = "0.0.0.0"` in `config.toml` makes it permanent. Hermit CRM has no
password, so anyone who can reach the port can read and write the CRM: use a
network you trust, or a private one (Tailscale, WireGuard), not public Wi-Fi.

**From an AI client (MCP).** `hermitcrm mcp` speaks the Model Context Protocol
on stdin and stdout, so a desktop AI client -- Claude Desktop, ChatGPT desktop,
Cursor -- can read and write the CRM with no terminal. You do not run it
yourself; the page shows the JSON to paste into the client's MCP config, which
starts it. Because it is a local process talking over a pipe, the client has to
run on this machine: a phone app cannot reach it, and the phone route is the
web app above. Seven read tools and three writes, the writes committing exactly
as the web form does. [AI agents](/help/ai-agents) has the tool list.

## About

Version and the update check, the data folder, its format version, and
`hermitcrm doctor`, which checks the whole installation line by line.

The update check asks once a day, sends no identifiers, and says what it found:
a newer version, "the latest", "no release published yet" when nothing is
published where it asks, or "could not reach ..." when it could not ask at all.
Those last two are not the same as being up to date, and it will not say they
are. It asks PyPI unless `update_url` in `config.toml` points somewhere else;
any URL answering `{"version": "0.4.0"}` works, so a static file on a download
page is enough. Turn it off with `update_check = false`.

Related: [Interactions](/help/interactions), [Enrich](/help/enrich), [CLI](/help/cli), [Data format](/help/data-format)
