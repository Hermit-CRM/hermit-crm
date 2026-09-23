# To do

Roadmap and open items. Personal items live in the private data folder.

## Launch (plan of 2026-09-19)

Target: public on Mon 19 Oct 2026, Show HN Wed 21 Oct, Product Hunt Tue 27 Oct
(live 08:01 CET: Europe leaves summer time on 25 Oct, the US on 1 Nov).
Fallback if the build week slips: everything one week later (PH Tue 3 Nov).

Now (19 Sep):
- [x] Register hermitcrm.io (main domain, at Cloudflare; site on Fly).
- [ ] Apply for GitHub Sponsors on the `Hermit-CRM` org (payout to
      CompoundGTM) and open a Ko-fi account for CompoundGTM; both take days.
- [ ] Send the testers a new build with the website's look (merged
      19 Sep). `rm -rf dist && ./scripts/release.sh`, then they unpack it and
      run `uv tool install --reinstall .` in it, then restart Hermit CRM.

Use (19 Sep - 3 Oct):
- [ ] Use it daily for two weeks for real sales work; fix what annoys.
- [ ] Start using the Product Hunt account (comment on other launches).

Build (5-9 Oct):
- [ ] `hermitcrm export`: zip of CSVs (companies, contacts, interactions,
      tasks, stage history) or one JSON file; profiles generic / hubspot /
      pipedrive; user fields and unknown keys as columns; `--excel` (UTF-8
      BOM); formula-cell escaping that the importer undoes; Settings → Data →
      Export everything (`GET /export.zip`); round-trip test export → import.
- [ ] Linux: CI on ubuntu-latest green; one real Ubuntu 24.04 VM (install
      with uv, init, serve, BCC import, `schedule install --serve`, reboot);
      `doctor` warns when systemd linger is off; INSTALL.md Linux section;
      extension in Chromium. Cut this first if the week runs over.
- [ ] Verify Codex, Cursor, Claude Desktop, ChatGPT and Gemini CLI end to end
      (install, read pipeline, log a call, draft); name only verified tools.
- [ ] Fix GitHub Actions billing; run the workflows once.
- [ ] PyPI: trusted publishing from the release workflow; verify the update
      check against the real index.
- [ ] Fresh public repo (new history, not the private repo flipped public:
      old PR refs keep pre-rewrite commits). Leak scan right before.
- [ ] Website: five benefits (Free and open source / Built for your AI / On
      your Mac / Yours to shape / Leave any time), audience subline, who it
      is / is not for, comparison table, support section, FAQ "Why is it
      free?" and "What happens if you stop?"; `build.py --release` passes.
- [ ] Website: multi-page build (`pages/*.md`, `compare.toml` with checked
      dates), sitemap, robots.txt allowing AI crawlers, llms.txt, JSON-LD,
      `/install.md`.
- [ ] Tier 1 pages: /free-crm, /vs/hubspot, /vs/spreadsheet,
      /crm-for-freelancers, /crm-for-consultants, /local-first-crm, /install,
      /ai-crm hub + /crm-for-claude-code, /crm-for-codex, /crm-for-cursor,
      /crm-for-claude-desktop, /crm-for-chatgpt, /crm-for-gemini-cli (each
      only once that tool is verified).
- [ ] Donations: `.github/FUNDING.yml`, README "Support", `Funding` URL in
      pyproject.toml, plain links on the site (no widget scripts).
- [ ] Real screenshot, 60-90 s video, 6 PH gallery images, maker comment.

Beta (12-16 Oct):
- [ ] 5-10 people install it on their own Macs (one never used for
      programming); fix install issues; three one-line quotes.
- [ ] Submit to AlternativeTo and OpenAlternative.

Public (19-27 Oct):
- [ ] Mon 19 Oct: repo public, PyPI release, hermitcrm.io already live and indexable since 23 Sep.
- [ ] Soft launch: LinkedIn post, r/selfhosted.
- [ ] Wed 21 Oct: Show HN, 14:00-16:00 CEST; stay in the thread all day.
- [ ] Tue 27 Oct: Product Hunt; answer every comment within the hour.

After:
- [ ] Smaller launch sites, MCP directories, european-alternatives.eu,
      awesome-selfhosted (check its minimum-age rule), Obsidian forum.
- [ ] Email authors of "best free CRM" / "CRM for freelancers" articles.
- [ ] Tier 2 pages: vs Attio, Close, Pipedrive, Salesforce, folk, Twenty,
      Notion, Obsidian, personal CRMs; /open-source-crm, /markdown-crm,
      /crm-for-solo-founders, /crm-for-solopreneurs, /eu-data-sovereignty.
- [ ] Tier 3: NL/DE/FR pages, guides, docs from the help pages.
- [ ] In-app support note (once, after 30 days and 50 interactions, never in
      demo folders, can be switched off); needs a yes first.
- [ ] Monthly check: is Hermit named by ChatGPT, Claude, Perplexity, Gemini
      for ~10 fixed prompts.
- [ ] vCard export of contacts.

## Before going public

- [x] Rename OwnCRM (taken by two businesses) to Hermit CRM: package, CLI,
      env vars (`HERMITCRM_*`, old `OWNCRM_*` still read), launchd/systemd labels,
      format file. GitHub organisation `Hermit-CRM` reserved (2026-09-17);
      create the repo there, private until launch.
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
