# To do

Roadmap and open items. Personal items live in the private data folder.

## Before going public

- [ ] Use it daily for a while first; fix what annoys.
- [x] Rename OwnCRM (taken by two businesses) to Hermit CRM: package, CLI,
      env vars (`HERMITCRM_*`, old `OWNCRM_*` still read), launchd/systemd labels,
      format file. GitHub organisation `Hermit-CRM` reserved (2026-09-17);
      create the repo there, private until launch.
- [ ] Small website: a static landing page (GitHub Pages from the README, a
      demo GIF of BCC → import → Messages → `git log`, install command).
- [ ] GitHub organisation + first push (leak scan again right before).
- [ ] PyPI: trusted publishing from the release workflow; verify the update
      check against the real index.
- [ ] Run the GitHub Actions workflows once (never executed yet).
- [x] Belgian companies: draft language from correspondence, website path,
      postcode and the language of titles/notes (`belgian_language`).
- [ ] Belgian companies: read a contact's LinkedIn profile language (needs a
      fetch; LinkedIn blocks plain requests).

## Unverified

- [ ] Windows Task Scheduler and systemd paths of `schedule install`.
- [ ] `codex`, `gemini`, `grok` provider flags against the real CLIs.
- [ ] A real calendar feed end to end (parser and matching are tested on
      fixtures only).
- [ ] IMAP login from the Settings page against a non-Gmail host.
- [ ] Default model IDs for codex, gemini and grok (`DEFAULT_MODELS` in
      `enrich.py`); only the claude IDs were run.
- [ ] Ask Hermit's whole-CRM step on codex, gemini and grok: tool access in
      the data folder is only verified with Claude Code.
- [x] "Retry with Fable" end to end (Claude Code 2.1.274, 2026-09-17; needs
      >= 2.1.251).

## Later

- [ ] Ask Hermit without waiting on a blank page: stream progress or run in
      the background (needs a little JavaScript or a polling page).
- [ ] `GET /tasks.ics`: subscribe to next steps from Apple/Google Calendar.
- [ ] Deals entity, only if several parallel opportunities per account become
      common (see docs/LEARNINGS.md).
- [ ] Docker image, if asked for.
- [ ] Attio / Notion export headers for import.
- [ ] Show HN, r/selfhosted, Obsidian forum posts.
- [ ] Validate contact emails (must contain `@`) in the store; the forms accept any string today.
- [ ] The store commits with `git add -A`; restrict it to the data paths (companies/, inbox/, PIPELINE.md, config.toml, messages.toml) so stray folders in the data repo are never committed.
