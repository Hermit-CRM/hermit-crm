# To do

Roadmap and open items. Personal items live in the private data folder.

## Before going public

- [ ] Use it daily for a while first; fix what annoys.
- [ ] Pick a unique name (OwnCRM is taken by two businesses) and rename the
      package, CLI, env vars (`OWNCRM_*`), launchd/systemd labels, Keychain
      services and this repo.
- [ ] Small website: a static landing page (GitHub Pages from the README, a
      demo GIF of BCC → import → Messages → `git log`, install command).
- [ ] GitHub organisation + first push (leak scan again right before).
- [ ] PyPI: trusted publishing from the release workflow; verify the update
      check against the real index.
- [ ] Run the GitHub Actions workflows once (never executed yet).
- [ ] Belgian companies: implement `belgian_language` in `messaging.py`
      (Flemish vs Walloon from website path, notes language, names).

## Unverified

- [ ] Windows Task Scheduler and systemd paths of `schedule install`.
- [ ] `codex`, `gemini`, `grok` provider flags against the real CLIs.
- [ ] A real calendar feed end to end (parser and matching are tested on
      fixtures only).
- [ ] IMAP login from the Settings page against a non-Gmail host.

## Later

- [ ] `GET /tasks.ics`: subscribe to next steps from Apple/Google Calendar.
- [ ] Deals entity, only if several parallel opportunities per account become
      common (see docs/LEARNINGS.md).
- [ ] Docker image, if asked for.
- [ ] Attio / Notion export headers for import.
- [ ] Show HN, r/selfhosted, Obsidian forum posts.
- [ ] Validate contact emails (must contain `@`) in the store; the forms accept any string today.
- [ ] The store commits with `git add -A`; restrict it to the data paths (companies/, inbox/, PIPELINE.md, config.toml, messages.toml) so stray folders in the data repo are never committed.
