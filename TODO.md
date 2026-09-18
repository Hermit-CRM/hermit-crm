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
- [x] The store commits with `git add -A`; restrict it to the data paths. Done
      2026-09-17 by recording the files each write touches (`Store.take_touched`)
      and scoping `commit(message, paths)` to them, so a write commits its own
      record and leaves the rest of the folder alone.
- [ ] WhatsApp: log WhatsApp conversations as interactions. Two routes worth
      comparing first: importing an exported chat `.txt` (no account, no
      approval, but manual and one-shot) and the WhatsApp Business Cloud API
      (live, but needs a Meta business account and number verification).
      Backed by the market scan: folk ships "CRM for WhatsApp" and scans
      WhatsApp chats for follow-ups, and for EU solopreneurs it is often the
      primary channel. It is the one channel Hermit is blind to.

## From the CRM market scan (2026-09-17)

Scanned Aurasell, Attio, Pipedrive, folk and Salesflare against an audience of
one person selling alone. Items 1-5 shipped in 0.3.0 (MCP server, follow-up
radar, `serve --host`, capture bookmarklet, pre-meeting brief). What is left:

- [ ] Win/loss: "the deals I lose share these three things". `stage_history`,
      `lost_reason`, message outcomes and sources are all already stored, and
      nobody else can do this well because nobody else has the full history.
      It is a report, not an agent.
- [ ] Keep-in-touch cadence for the network, separate from the deal pipeline.
      `silent_days` is deal-shaped; "people I have not spoken to in six months"
      is a different and useful list.
- [ ] Proposal or quote generated from the company record. Genuine value for a
      consultant; e-signature is somebody else's business.
- [ ] Send from the app. Weigh carefully: open tracking means a tracking pixel,
      which sits badly with a tool whose pitch is that you own your data.
      Sending without tracking is fine and much simpler.
- [ ] Positioning line sitting unused: Pipedrive's "you can't control results,
      but you can control the actions that close deals". Hermit's next step plus
      calendar *is* activity-based selling and the README never says so.

Deliberate non-goals from the same scan: workflow/agent builders (a folder of
files that you point your own agent at is the better answer), waterfall
enrichment and contact databases, and anything multi-user.
