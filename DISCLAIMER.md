# Disclaimer

Plain language, because this matters more than legal wording. The binding text
is the Apache License 2.0 in [LICENSE](LICENSE), sections 7 and 8.

## What this is

Hermit CRM is free. You pay nothing and you owe nothing.

It is alpha software. It is incomplete, it changes without notice, and it has
bugs that nobody has found yet. Parts of it will break.

It comes with **no warranty of any kind**. Not that it works. Not that it keeps
working. Not that it fits what you want to do with it. It is provided "as is".

## Liability

The author is not liable for any damage that comes from using this software.
That includes, and is not limited to:

- Lost, deleted, corrupted or unreadable data.
- Backups that did not run, ran wrong, or could not be restored.
- Lost deals, lost customers, lost revenue, lost time.
- Any indirect or consequential loss of any kind.

This holds even if you told the author the problem was likely, and even if the
author should have seen it coming.

## Backups are yours

Hermit CRM writes a git commit for every change and copies your folder to a
second repository every few minutes. That is a convenience, not a guarantee.

**You are responsible for your own backups.** You are also responsible for
testing that a restore actually works. A backup you have never restored is not
a backup — it is a hope. Restore one to a scratch folder now and then and check
the result with your own eyes.

If the backup does not run, does not include what you expected, or cannot be
restored when you need it, that is your risk to carry.

## Your data

Hermit CRM runs on your machine. Your data is a folder of files that you own,
on disk that you control.

- It sends **no telemetry**. No usage statistics, no crash reports, no pings.
- The author **never receives, stores or processes your data**. There is no
  server to receive it. There is no account. There is nothing to opt out of.
- Under the GDPR, **you are the data controller** for everything you put in.
  Your contacts, your records, your obligations. The author is not a processor
  and not a joint controller, because nothing of yours ever reaches him.

The one thing the app fetches on its own is a version number, at most once a
day, to tell you an update exists. No identifiers are sent. Switch it off with
`update_check = false` in `config.toml` or `HERMITCRM_NO_UPDATE_CHECK=1`.

## Third-party integrations

Some features talk to services that are not the author's: your mail provider
over IMAP, your calendar's secret address, websites and LinkedIn pages you ask
it to read, and AI command-line tools such as Claude Code or Codex.

- **You supply your own keys, passwords and addresses.** They stay on your
  machine. The author never sees them.
- **You are responsible for following those providers' terms**, including the
  [LinkedIn User Agreement](https://www.linkedin.com/legal/user-agreement).
  Whether fetching a given page is allowed is between you and them.
- **You are responsible for your own GDPR obligations** whenever data leaves
  your machine — for example when an AI tool is given a contact's details to
  enrich or draft with. That is a transfer you have chosen to make, on your
  legal basis, under that provider's terms.
- Costs are yours too. AI tools bill you, not the author.

## Support

There is none.

No support, no service level, no response time, no obligation to fix anything
or to answer at all. Bug reports and patches are welcome and may well be
ignored. See [SECURITY.md](SECURITY.md) for security reports, which are read
with more care but carry no promise either.

## Trademark

The Apache License covers the code. It does **not** grant rights to the name
"Hermit CRM" or to the hermit logo (Apache 2.0, section 6).

Fork the code, change it, ship it — that is what the licence is for. Give your
fork a different name, and do not use the name or logo in a way that suggests
the original project endorses it.
