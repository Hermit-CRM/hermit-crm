# Overnight review, Saturday 17 October 2026

Written by the scheduled morning review (`hermit-w3-review`, started 09:00).
Not committed: this file is for you to read.

## The short version

- **Only one pull request is open: #89** (email validation, outside
  contributor). It looks good and safe, but **CI has not run on it**: GitHub
  holds workflows from a fork until you approve them. One click on the PR's
  Checks tab ("Approve and run workflows").
- **Already merged this morning (08:37–08:38):** #106 (dashboards,
  including the safety-check fix), #112 (outreach 04b), #113 (website 0.8.0)
  and #114 (scrape redirect guard). `main` is green at `1c05391`. Nothing to do.
- **Most overnight sessions stopped part-way and never committed.** Two ran
  out of usage at 21:32 (keep-in-touch, PLAN-05); export, leak scan and the QA
  pass also left work uncommitted in their worktrees. I committed, finished
  and rebased those onto `main` and **pushed six branches (these five plus `claude/ai-cli-isolation`) without opening
  PRs** (commands to open them are at the end).
- **Two tasks never ran at all: Linux CI and the website copy.** Their
  scheduled runs (23:46 and 23:48) show zero runs. Neither has a branch.
- **Another session is working right now** in
  `.claude/worktrees/outreach-phase0-playbook-00247a` (files changing at
  09:02–09:05). I didn't touch it.

| Work | Branch | State now | Verdict |
|---|---|---|---|
| Email validation | PR #89 (`codex/fix-issue-84`, fork) | open, CI waiting for your approval | needs a decision (approve CI), then ready |
| Safety-check fix + dashboards | #106 | merged | done |
| Outreach 04b, replies to interest | #112 | merged | done |
| `hermitcrm export` | `claude/export` | finished, pushed, no PR | ready |
| Keep-in-touch list | `claude/keep-in-touch` | finished, pushed, no PR | needs a decision (3 product questions) |
| Pre-launch QA pass | `claude/qa-launch-2026-10-16` | 2 commits, pushed, no PR | ready |
| Leak scan | `claude/leak-scan-2026-10-16` | partial, pushed, no PR | ready as far as it goes; rest after #89 |
| Outreach PLAN-05 | `claude/outreach-plan05` | finished, pushed, no PR | needs decisions (9 questions in the plan) |
| AI CLI isolation (from 19:22 yesterday) | `claude/ai-cli-isolation` | 1 commit, rebased, pushed, no PR | ready |
| Linux CI | none | never ran | not started |
| Website copy draft | none | never ran | not started |

**Tests** (full `pytest` on each branch after my changes, on this Mac):

| Branch | Result |
|---|---|
| `claude/export` | 2162 passed, 1 failed, then fixed (the help anchor below); the affected 107 tests re-run green |
| `claude/keep-in-touch` | 2135 passed, 2 failed, then fixed (two config tests that list every default); the affected 330 tests re-run green |
| `claude/qa-launch-2026-10-16` | 2129 passed, 2 skipped |
| `claude/leak-scan-2026-10-16` | 2124 passed; 3 PDF tests failed only because the venv I borrowed lacked `pypdf`, and they pass with the right one |
| `claude/ai-cli-isolation` | 2128 passed, 2 skipped |
| `claude/outreach-plan05` | docs only |
| **All seven merged together on `main`** | **2220 passed, 2 skipped**: they work together, not just merge |

(The 2 skipped are the Linux Secret Service tests.) None of the pushed
branches has run on GitHub CI yet: that happens when you open their PRs.

**Your main checkout's `.venv` is missing `pypdf`.** Run
`.venv/bin/pip install -e '.[dev]'` there before you trust a local test run.

---

## PR #89: validate contact emails before saving

**By** GSflaming (GitHub account since April 2024, 0 followers, 3 PRs ever:
this one and two small ones elsewhere). Commits signed off (DCO), "ai:"
prefix used. Last updated 08:55 this morning, when they merged `main` in
themselves.

**What it does.** A contact's email must now contain exactly one `@` with
text on both sides, or it's refused with a message next to the email field
(web forms), an error (CLI exit 2, MCP) or a skipped address (BCC, calendar
and spreadsheet imports skip it and carry on). An empty email is still
allowed. Old files with a bad email still load and aren't rewritten. Closes
issue #84.

**Safety (pr-review checklist).**
- Network: OK, no new URLs or requests.
- Execution: OK in the app. The new tests run `git show`, `git diff` and
  `git log` on their own temporary folders to check what was committed. That
  is what the safety check flags; it's read-only and harmless.
- Obfuscation, binaries: OK, none. Nothing hidden in the text.
- Dependencies, install files, agent instructions, `.github/`: OK, none
  touched.
- Data: OK, nothing collected or sent.
- Scope: OK. 14 files, all about email validation, plus a changelog entry.

**Quality.** I checked every place in the app that creates or edits a
contact (web, CLI, MCP, import, BCC, calendar, bulk edit, enrich). Each one
already catches this kind of error, so a bad address in an import can't stop
the whole batch. The rule is deliberately loose (`a@b` passes), which matches
the issue.

**What I changed.** Nothing. It's a contributor's fork, and the pr-review
rules say not to comment on a PR without your OK, so I posted nothing.

**Verdict: needs a decision (approve the CI run); then SAFE TO MERGE if CI is
green.** I didn't run its code locally (pr-review rule: never run a fork's
code).

**Clean-up.** `~/Code/HermitCRM-pr89` is an old local worktree that stopped
half-way through merging `main` into #89 (a conflict in `CHANGELOG.md` was
never resolved). It's out of date now that the contributor merged `main`
themselves. It also has an unstaged change to `TODO.md`. Look at that
before you discard it (`git -C ~/Code/HermitCRM-pr89 diff TODO.md`), then
`git -C ~/Code/HermitCRM-pr89 merge --abort` and
`git worktree remove ~/Code/HermitCRM-pr89`.

**Suggested reply** (post with `gh pr comment 89 --body "..."`, or tell me to
post it):

> Thanks a lot for this, and for keeping it up to date with main overnight.
> The change does what #84 asked and keeps old files loading, which is what
> I cared about most. I've approved the CI run; once it's green I'll merge
> it. Welcome aboard!

---

## `claude/export`: `hermitcrm export` and Settings > Data > Export everything

**What it does.** `hermitcrm export` writes a zip of five CSV files
(companies, contacts, interactions, tasks, stage history), or one JSON file
with `--format json`. Column names can follow Hermit CRM, HubSpot or
Pipedrive (`--profile`). `--excel` adds the marker Excel needs to show
accents. A cell starting with `=`, `+`, `-` or `@` gets an apostrophe so a
spreadsheet doesn't run it as a formula, and the importer removes it again,
so an export imports back. The same zip is under Settings > Data (a renamed
"Backup" tab) and at `GET /export.zip`. It only reads: no write, no commit.
It refuses to write the file inside the data folder, where it would end up
in git.

**What I changed.**
- The overnight session left everything uncommitted with **one failing
  test**. The test was wrong, not the code: it expected the company "Example
  Co" to get the slug `example-co`, but the importer drops legal forms like
  "Co", so it's `example`. Fixed the test.
- Added what was missing: an Export section in Help > Import (now "Import and
  export"; the Settings "How" link pointed at an anchor that didn't exist),
  the CLI help line, a changelog entry and the TODO tick.
- The full run then caught one more thing: the public docs page on the
  website can't follow an in-page `#export` link, so that sentence is plain
  text now (the Settings link into the app still works).
- Committed, merged `main` (no conflicts), pushed.
- Tried it on a demo folder: 13 companies and 15 contacts exported, five
  CSVs in the zip, the data folder untouched, and writing into the data
  folder is refused.

**Verdict: ready.**

**Open questions.**
1. `GET /export.zip` has no CSRF token, because it's a link that only reads.
   A web page you visit could make your browser *download* the zip into
   Downloads, but it can't *read* it (the app's Host check stops DNS
   rebinding). I think that's fine. Say if you'd rather make it a POST.
2. The HubSpot and Pipedrive column names are chosen so *our* importer reads
   them back. They're close to what those CRMs use, but nobody has imported
   such a file into real HubSpot or Pipedrive yet.

---

## `claude/keep-in-touch`: people you have not spoken to in months

**What it does.** A new Home section, "Keep in touch", lists people outside
an open deal you haven't spoken to in 180 days or more, longest first (8 on
Home, the rest via `hermitcrm keep-in-touch`). It's also an MCP tool
(`keep_in_touch`). It works per person: their latest interaction in either
direction, notes not counted. Left out: anyone at a company in an open stage,
anyone tagged do-not-contact (company or person), people you never contacted,
and the sample account. The setting is `keep_in_touch_days` in `config.toml`.
It has a default, so no migration is needed. The do-not-contact rule moved
into one shared place, used by outreach too.

**What I changed.** The session ran out of usage at 21:32 with everything
uncommitted. I committed it and rebased it onto `main`. That had two small
conflicts with 04b: an import line in `outreach.py`, and a paragraph in
Settings help where both changes were kept. I added the changelog entry,
placed so it doesn't collide with export's, and ticked TODO. On the demo
folder: the list is empty at 180 days (the demo data is recent), and with
`--after 20` it shows the two people expected (Emberoak Foods, lost;
Glasshouse Health, temporarily disqualified). I tested it through the test
suite and the CLI, not in a browser.

**Verdict: needs a decision.**

**Open questions (product).**
1. **Open stages are left out entirely**, including every lead or prospect
   company. So someone at a company still marked "lead" whom you last spoke
   to a year ago never shows here. Is that right, or should only companies
   with a real open deal be left out?
2. **Only interactions logged against a person count.** A company-level
   email with no contact set doesn't refresh anyone. OK?
3. **No setting in the Settings page**: `config.toml` only, like
   `silent_days`. And no full-list page in the browser beyond the 8 rows on
   Home. Fine for launch?

(Also: this list uses "not closed and not parked", while outreach uses "open
stage". On a custom stage list the two could differ. PLAN-05 point 14 notes
the same gap.)

---

## `claude/qa-launch-2026-10-16`: pre-launch QA pass

**What it does.** Two small fixes:
- Changing a deal's stage on the Pipeline board used to send you to Home. It
  now returns to the board, with your filters kept. This was already
  committed overnight.
- I committed the session's uncommitted rest. In the import preview, a
  skipped contact row without a name now shows its company, so you can tell
  which row it was. The page-footer style now applies only to the small page
  footer (I checked: it's the only footer). The "search the whole CRM"
  checkbox on Ask uses the normal checkbox style.

**What I changed.** Committed the leftovers, rebased onto `main`, pushed.

**Verdict: ready.** The QA session left no notes on what else it checked,
so don't read this as a full QA pass.

---

## `claude/leak-scan-2026-10-16`: real names and domains out of the repo

**What it does.** Replaces a real person's LinkedIn handle in the
first-install feedback spec, plus real-looking company names and domains in
two test files (`getcirrusly.ai`, `lindqvist-labs.se`, `quillhq`, a "YC S23"
batch), with fictional ones on `.example`.

**What I changed.** Committed, rebased, pushed.

**Verdict: ready as far as it goes, but it's partial.** It found the worst
items but stopped before a full sweep, and left no report. Still left, all
fixture addresses in tests and one doc:
- `@acme.de`: 79 places in 7 files (`docs/ARCHITECTURE.md`, `tests/test_bcc.py`,
  `test_calendar_sync.py`, `test_cli.py`, `test_importer.py`, `test_store.py`,
  `test_web.py`)
- `@nowhere.org` (9), `@lee.com` (6), `@acme.com` (1), `@test.local` (12, in 12
  files)
- The many `@gmail.com` addresses are on purpose: the tests check how
  free-mail addresses are handled. Keep them.
- Your own LinkedIn (`/in/gijsbos`) on the website is intentional.

I didn't do the `acme.de` sweep: it touches five of the same test files as
PR #89, and would hand an outside contributor a conflict. Do it right after
#89 merges (it's mechanical: `acme.de` becomes `acme.example`).

---

## `claude/outreach-plan05`: the plan for outreach part 05

**What it does.** `PLAN-05.md` splits part 05 into four small PRs, each with
its tests: 05a follow-ups (using `followup_nudge_days`), 05b `ai-web`
research, 05c the critic, 05d the bookmarklet's "Add to research". It keeps
PLAN-04's fixed points (no HTMX, no SSE, no background threads, one commit
per step, bodies byte for byte, CSRF). It also lists 14 places where the spec
and the code disagree, each with the choice it makes. The most important:
the 30-day outreach cooldown would block *every* follow-up (point 1), and
only Claude can be restricted to web-only tools, so `ai-web` refuses Codex,
Gemini, Grok and custom commands (point 8).

**What I changed.** The file was written but never committed. It said 04b
had no PR yet, which was wrong: #112 merged at 19:37. I fixed that and marked
its first open question settled. Committed, rebased, pushed. Docs only.

**Verdict: needs decisions** before 05a starts: open questions 2–10 at the
end of the plan (opt-out line on follow-ups, LinkedIn follow-ups, how many
follow-ups, research for follow-ups, the migration rule for outreach item
keys, checking `ai-web` sources, critic score, which draft to keep,
bookmarklet scope).

---

## `claude/ai-cli-isolation`: AI runs ignore your own Claude settings

Not on tonight's list. It's one unpushed commit from 19:22 yesterday that I
found while looking.

**What it does.** When Hermit CRM calls `claude -p` (enrich, Ask, outreach
drafts), Claude loaded *your* `~/.claude/CLAUDE.md` and memory, so drafts for
a demo folder came out signed with your name. Now it passes
`--setting-sources ""` and turns auto-memory off. Login still works. Codex
still reads `~/.codex/AGENTS.md` (no flag exists; noted as a TODO).

**What I changed.** Rebased onto `main` (no conflicts), ran the full suite
(green) and pushed it as `claude/ai-cli-isolation`.

**Verdict: ready.** Before launch this matters more than it looks: every
user's own Claude instructions would leak into their drafts.

---

## Not started

- **Linux CI** (`hermit-w2-linux-ci`): zero runs. It's not small (CI on
  ubuntu-latest, fixing whatever breaks over several CI rounds, the `doctor`
  linger warning, the INSTALL.md Linux section), so I didn't start it.
  Re-run the task ("Run now") when you have usage to spare. It's about one
  session.
- **Website copy draft** (`hermit-w2-website-copy`): zero runs. It's
  customer-facing copy, so I didn't write it unattended. Re-run the task.
  Note it should say "Leave any time" only once export is merged: export is
  ready now (above).

---

## Merge order

`git merge-tree` finds no conflicts between any two of these branches (21
pairs), and all seven merge one after another onto `main` without a
conflict. All the branches are rebased onto (or merged with) today's
`main`. The suggested order puts the riskiest-to-rebase first and the
outside contributor ahead of our own work:

1. **#89** (email validation), once CI is green. It goes first so the
   contributor never has to rebase again.
2. **`claude/ai-cli-isolation`**: tiny and important for launch.
3. **`claude/qa-launch-2026-10-16`**: small fixes.
4. **`claude/export`**: needed before the website can say "Leave any time".
5. **`claude/keep-in-touch`**, after your answers to its three questions.
6. **`claude/leak-scan-2026-10-16`**, then the `acme.de` sweep on top.
7. **`claude/outreach-plan05`**: docs only, any time.

Where they meet: `importer.py` and `tests/test_importer.py` (#89, export, QA,
leak scan), `web.py` (export, keep-in-touch, QA), `cli.py` and
`help/cli.md` (export, keep-in-touch), and the changelog's Unreleased list
(#89, export, keep-in-touch). Each pair edits different lines. If a
GitHub merge does show a conflict after an earlier merge, it'll be one of
those, and it'll be "keep both".

To open the PRs (I pushed the branches but didn't open PRs, since the task
didn't ask for that):

```bash
gh pr create --head claude/ai-cli-isolation --fill
```
```bash
gh pr create --head claude/qa-launch-2026-10-16 --fill
```
```bash
gh pr create --head claude/export --fill
```
```bash
gh pr create --head claude/keep-in-touch --fill
```
```bash
gh pr create --head claude/leak-scan-2026-10-16 --fill
```
```bash
gh pr create --head claude/outreach-plan05 --title "ai: spec: outreach bot, plan for part 05" --fill
```

## Decisions for you before Monday

1. **#89: approve the CI run** on the PR (Checks tab), then merge if green.
   Post the reply above, or ask me to.
2. **Keep-in-touch: three questions** above (leave out every open-stage
   company? only contact-linked interactions? config.toml only?).
3. **Export: `GET /export.zip` without CSRF**, fine (my recommendation), or
   make it a POST?
4. **Linux CI and the website copy didn't run.** Re-run both tasks today?
   Launch copy without "Leave any time" stays honest only if export is
   merged first.
5. **PLAN-05: nine open questions** before anyone builds 05a. Not needed for
   Monday.
6. **Leak scan:** OK to do the `acme.de` sweep right after #89 merges?
7. **Clean-up:** the stale `~/Code/HermitCRM-pr89` worktree (see #89), and
   `docs/superpowers/specs/2026-10-16-dashboard-followups.md`, which is
   untracked in the main checkout (a brief for a future session; commit it or
   delete it).
