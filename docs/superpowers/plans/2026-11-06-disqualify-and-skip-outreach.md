# Company disqualification and skipping outreach (plan)

Status: Implemented 2026-11-06 (branch `claude/disqualify-skip-outreach-91538e`).
Deviations from this plan, all small:

- The migration is **22**, not 21: 21 was taken by `linkedin-import` before this
  shipped. It is a no-op like 13, 20 and 21: `stage_override` is written only when
  set (like `framework`), so no existing file changes.
- C9 (new): `outreach.replies()` now lists a reply from a company that is not open,
  but only when it shows interest (logged `interested`, confirmed, or waiting for
  confirmation). The plan guessed it already did; it did not (`followups._row`
  returned nothing for a closed company). Unchecked replies there stay unlisted and
  are not sent to the AI check, so old "no thanks" mails of lost deals cost nothing.
- `select` now excludes an address on the suppression list (it only checked
  do-not-contact before; send.py refused it). Test case 4 needs it.
- A stage-blocked contact is listed under "left out" only when nothing else is
  wrong (no email, an open item, a tag disqualifier...); otherwise the other
  reason is shown, since including it would not help.
- Bulk (`hermitcrm set --stage ... [--keep-drafts]`) copies the company's open items
  into its dry-run scratch folder, so the dry run says how many drafts it skips,
  and `apply` names those files in the one commit.

The
behaviour below was decided with Gijs in conversation; nothing here is a guess
unless it sits under "Calls I made" (those need a sanity check, not a debate).

## Why

Gijs's words: "if I disqualify a company, will the system still generate
outreach? From my perspective it shouldn't."

Today it mostly does not, but only by accident of the stage check. Two separate
mechanisms exist and they do not know about each other:

1. **Company disqualification** is a stage move (`disqualified`, role `closed`;
   `temp-disqualified`, role `parked` with a `requalify_on` date).
2. **Skipping outreach** is an outreach item state (`skipped`) with a
   `skip_reason` from `SKIP_REASONS`. `bad-fit` keeps the company out of new
   batches for good but never changes the company's stage.

The goal is to make them behave like one idea, with the person in control.

## What already works (verified in code, do not rebuild)

| Fact | Where |
|---|---|
| A batch or named draft skips any company whose stage role is not `open` (closed, parked, won, lost) | `outreach.py` `_excluded()`, `if not store.stages.is_open(company.stage)` (about line 2660) |
| Sending re-checks the stage and refuses ("the company is X now") | `send.py` about line 821 |
| Sending re-checks `do_not_contact`, the suppression list and the playbook's hard tag disqualifiers | `send.py` 810-830 |
| `playbook.disqualify()` is the hard tag disqualifier (`tag_present`), used by `select` (forced approach) and `send` | `playbook.py` `disqualify()` |
| Opting out already skips a contact's open items in the same commit; copy this pattern | `sendqueue.py` `opt_out()` |
| `outreach.skip()` skips one open item | `outreach.py` `skip()` (about line 3156) |
| Stage moves go through `Store.update_company(...)` (web, CLI, bulk, import, Ask all end there) | `store.py` `update_company()` (line 953) |

## Gaps this plan closes

1. Disqualifying leaves the company's existing open drafts
   (`researching`, `drafted`, `ready`, `queued`, `failed`) in the queue. Nothing
   calls `outreach.skip()` on a stage change. The only guard is send-time refusal.
2. "Generate" for one named contact at a closed company is refused with a plain
   "its company is disqualified" reason. Gijs wants it to be allowed.
3. A batch silently drops disqualified companies; there is no way to bring one
   back in on purpose.
4. Skipping an item as `bad-fit` never offers to disqualify the company.
5. Reply-to-interest drafts are blocked for closed or parked companies even
   when the prospect has just written back. Gijs wants replies allowed.

## Decisions (agreed with Gijs)

| # | Situation | Behaviour |
|---|---|---|
| D1 | One named contact (per-contact Generate button; CLI with exactly one `--contact`) at a company in a non-open stage | **Generate it**, with a visible warning on the card that the company is disqualified (or parked, closed...). No prompt. |
| D2 | A batch or filter run, or several named contacts, that would include non-open companies | Those companies are **left out by default** and **listed separately** with a way to **include them on purpose** (ask). Default is never to include. |
| D3 | A company is moved to a non-open stage and has open drafts | The disqualify form **asks**: "N open outreach drafts for this company" with a checkbox **ticked by default** to skip them. Non-interactive paths (CLI, bulk, import, Ask, sweeps) **skip them by default**; a flag keeps them. |
| D4 | Temp disqualify (parked, `requalify_on`) | Same as D3 now: open drafts are **skipped, not held**. When the company requalifies it is eligible for new drafts again. Old drafts are not revived. |
| D5 | Skipping an item as `bad-fit` | **Offer** "Also disqualify this company?" Default off. Never forced. Nothing is offered if the company is already non-open. |
| D6 | Reply-to-interest | **Allowed** for non-open companies (the prospect wrote to you). **First touches and follow-ups stay blocked.** |
| D7 | Hard stops | The "generate anyway" override lifts **the stage check only**. `do-not-contact` tag, the suppression list and the playbook's hard tag disqualifiers stay absolute for single drafts and batches, and send re-checks them. |

## Calls I made (check these, tell Gijs in the final report which you changed)

- **C1 New skip reason `company-closed`**, set by the cascade (D3/D4). It must not
  appear as a manual button in the skip form (`outreach.html` line 314 renders
  every entry of `skip_reasons`; pass a manual-only tuple there). Keep `SKIP_REASONS`
  as the full set that `skip()` and `learning.py` accept, or add a separate
  `SYSTEM_SKIP_REASONS`; pick whichever touches fewer call sites.
- **C2 `company-closed` skips are not a quality signal and set no cooldown.**
  They must not count as a bad draft in `learning.py` (lines ~390, 545, 1035,
  1123) and must not trigger the per-contact cooldown in `select()`
  (`skipped_by_contact`, about line 2598). Otherwise a temp-disqualified company
  that requalifies after a week would still be blocked by "skipped N days ago".
  They also must not behave like `bad-fit` (`bad_fit` dict, line 2596).
- **C3 The cascade lives in the store layer**, as a `keep_drafts=False` keyword on
  `Store.update_company(...)`, so web, CLI, bulk, import and Ask all get it
  without each remembering. It skips open items in the same `store.batch(...)`
  commit as the stage move, following `sendqueue.opt_out()` (clear `queued` and
  `send_at` too). It fires when the new stage's role is not `open` and the old
  stage's role was `open`. Moving between two non-open stages does nothing.
  `store.py` already imports `outreach` lazily (lines 488, 1771); do the same.
- **C4 "Any non-open role" counts**, not only `closed`. Moving to `won` or `lost`
  also skips open drafts. `select()` already excludes them, so this just keeps
  the queue honest. If this feels wrong for `won`, say so; it is one condition.
- **C5 The override must reach the send step.** If D1 generates a draft for a
  disqualified company and send then refuses it ("the company is X now"), the
  override only produces a dead card. So the item records that the stage check
  was overridden on purpose, and `send.py` honours that marker for the stage
  check only. Recommended: a new item key `stage_override` (empty or the stage
  name at draft time) in `ITEM_KEYS`, which per CLAUDE.md means **migration 21**
  (idempotent, front matter only, `outreach/*.md`, copy `m15_framework` /
  `m17_drop_angle` in `migrations.py`) plus tests. Cheaper alternative if you
  find one that is still deterministic: reuse `flags`. Do not skip the migration
  question; decide and write down why.
- **C6 CLI "ask" is a flag, not a prompt.** `hermitcrm outreach build/preview`
  prints the left-out disqualified contacts and the flag
  `--include-closed company/contact` (repeatable) to bring them in. Unattended
  runs therefore can never include them by accident.
- **C7 The reply exception covers `closed`, `parked`, `won`, `lost`** the same
  way (it is the stage check that is skipped, for `kind == REPLY` only).
- **C8 One stage for "Also disqualify" (D5):** the first stage whose role is
  `closed`, preferring one named `disqualified`. If the folder has no `closed`
  stage, hide the checkbox.

## Workstreams

Do A first; B to F are independent after it. Each ends with its tests passing.

### A. Core rules in `outreach.py` (select, candidates, skip reason)

1. `Candidate` (dataclass near line 2421): add a field marking that the only
   thing excluding it is a non-open stage (for example `stage_blocked: str`,
   the stage name). `Selection` (line 2441): add a list for these, separate from
   `excluded`, and render it in `Selection.render()` (line ~2471) as its own
   section with the include hint (C6).
2. `select(...)`: add `include_closed: set[str] | None = None` (records
   `company/contact`). Compute `single = bool(contacts) and len(contacts) == 1`.
3. `_excluded(...)`: change the stage check (about line 2660):
   - `kind == REPLY`: skip the stage check entirely (D6, C7).
   - else if the contact is `single` or in `include_closed`: do not exclude;
     append a warning to `cand.warnings` naming the stage and role (it already
     flows into `item.flags` at line ~2926) and mark the candidate as overridden
     so `build()` can set `stage_override` (C5).
   - else: exclude with the existing reason text and set the stage-blocked
     marker so the UI can offer it back (D2).
   Everything after this check (`do_not_contact`, approach disqualifiers,
   `fit`, open items, cooldown) is unchanged and still applies (D7).
4. `playbook.disqualify()` for a forced approach and `pick_approach` must still
   exclude hard tag disqualifiers even for overridden candidates. Add a test.
5. Add the `company-closed` skip reason (C1) and its no-cooldown, not-bad-fit,
   not-a-quality-signal handling (C2).
6. New function, for example `skip_open_for_company(store, slug, reason="company-closed", note="")`:
   skips every open item of the company in one pass, clears `queued`/`send_at`,
   returns the skipped ids. Reuse inside `Store.update_company` (C3) and
   `sendqueue.opt_out` can stay as it is.
7. Add the marker (C5) to `ITEM_KEYS`, `Item`, the loader (about line 1944) and
   `build()`.

### B. Store cascade (D3, D4, C3, C4)

- `Store.update_company(..., keep_drafts=False)`. When `stage_changed` and the
  old role is `open` and the new role is not, skip the company's open items in
  the same `with self.batch(message):` block and add the count to
  `take_notices()` text ("3 open outreach drafts skipped").
- The commit message stays `company: <slug> stage a -> b`.
- Check these callers and decide per caller whether the default is right:
  `bulk.py` (stage moves, simulation at ~804 must show the side effect in its
  before -> after lines), `importer.py`, `cli.py` company set paths (~1209-1217),
  `adjust.py` routines that move stages (~314 "Move every prospect I have not
  touched in 90 days to lost"), `ask.py`, `store.requalify_due()` (moves parked
  to open: must not cascade, and it does not because the new role is open).
- CLI: a `--keep-drafts` flag on whichever command sets `stage`.

### C. Disqualify form (web, D3)

- `company.html` lines 28-45: each exit form gets, only when the company has
  open outreach items, a line "N open outreach drafts" and a checkbox
  `skip_drafts`, ticked by default.
- `web.py` `company_disqualify` (line 2794): read `skip_drafts`; pass
  `keep_drafts=not skip_drafts`. Flash message includes the skipped count.
- The count comes from `outreach.items(root)` filtered by company and `is_open`.

### D. Batch ask in the web UI (D2) and the single-draft path (D1)

- `/outreach?preview=1` (`web.py` `outreach_page`, line ~4651): show the left-out
  disqualified contacts in their own list with an "include anyway" checkbox per
  row, default off, and the stage next to each name.
- `/outreach/build` (line 4700) selects one contact per request in a loop with
  `left` carrying the remainder. Carry the confirmed records through that loop in
  a form field and pass them as `include_closed` to every `select()` call, so
  confirmed contacts survive the one-per-request design.
- The Generate panel (`outreach_generate`, line 4599) is the D1 case: no
  prompt. Show the warning text on the panel before the click if the company is
  non-open, and on the resulting card (flags).

### E. Skip form offers disqualify (D5, C8)

- `outreach.html` line ~314: when the item's company is open and has a `closed`
  stage, show a checkbox "Also disqualify <company>" next to the skip buttons,
  default off. Only the `bad-fit` button acts on it.
- Web route `/outreach/{item_id}/{what}` (line 5030): on `skip` with
  `bad-fit` and the box ticked, skip first, then `update_company(stage=...)`
  with the skip note as the reason. The cascade skips the company's other open
  items.
- CLI: `hermitcrm outreach skip ID --reason bad-fit --disqualify`.

### F. Reply exception end to end (D6, C7)

- `_excluded` (workstream A.3) and `send.py` line ~821: for `item.kind == REPLY`
  do not refuse on stage. Keep every other check.
- Verify the Replies tab and `outreach.replies()` do list replies from closed
  or parked companies. `replies()` calls `followups.for_contact`, which does not
  filter on `is_active`, so it probably does already; its docstring says
  "closed companies are left out", which is then wrong. Fix whichever is wrong.
- Follow-ups stay blocked: `due_followups` and `radar()` already use
  `company.is_active`. Add a test that proves it.

## Tests (write them first; the repo uses pytest and the demo folder)

Style and fixtures: `tests/test_outreach_select.py`, `tests/outreach_fakes.py`
(`demo`, `FakeAI`), `tests/test_stages_store.py`, `tests/test_stages_web.py`,
`tests/test_send_worker.py`, `tests/test_outreach_web.py`.

Minimum cases:

1. Batch select with a disqualified company: left out, listed under the new
   section, not in `excluded`, with the stage name; `include_closed` brings it in
   with a warning.
2. One named contact at a disqualified company: picked, warning present.
   Two named contacts: both left out and listed.
3. Parked (`temp-disqualified`) behaves like closed for 1 and 2.
4. `do-not-contact` tag and suppression-list address: never picked, even
   single or included. Playbook tag disqualifier: never picked, even single.
5. Reply-to-interest for a closed company: picked. First touch and follow-up for
   the same company: not.
6. `update_company(stage="disqualified")` with open items in each of the five open
   states: all skipped with `company-closed`, one commit, queued items lose
   `queued`/`send_at`. With `keep_drafts=True`: untouched. Moving back to
   `prospect` revives nothing.
7. After `company-closed`, a requalified company is eligible again without
   waiting for the cooldown and is not treated as `bad-fit`.
8. Quality/learning reports ignore `company-closed` (C2).
9. Send: an item generated under the single-draft override is not refused on
   stage (C5) but is still refused for suppression, do-not-contact and tag
   disqualifier. An ordinary item whose company is disqualified after drafting
   is still refused.
10. Disqualify form: checkbox present only with open items, ticked by default;
    posting without it keeps the drafts.
11. Skip form: `bad-fit` plus the checkbox moves the company and skips its other
    items; checkbox off leaves the stage alone; not shown for a non-open company.
12. Migration 21 (if C5 uses a new key): idempotent, front matter only, body
    byte for byte unchanged.
13. Demo folder run: `.venv/bin/hermitcrm init /tmp/x --demo`, then disqualify a
    prospect that has a draft and check the queue by hand and in the browser.

## Documentation

Update where these behaviours are described: `docs/ARCHITECTURE.md` (outreach
state diagram: add the cascade), the module docstring of `outreach.py`
(it lists skip reasons and "A skipped contact comes back after the cooldown,
except `bad-fit`"), the help pages under `src/hermitcrm/help/` including the
changelog (`src/hermitcrm/help/changelog.md`), and the outreach spec if it
names the skip reasons. Use only fictional names and example.com addresses.

## Project rules to follow (from CLAUDE.md)

- Set up with `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`.
- `.venv/bin/pytest` must pass before any commit.
- Commit messages for AI-made changes start with `ai:`.
- No new runtime dependencies.
- No real people, companies or addresses in code, tests or docs.
- A new front-matter key or value means a numbered migration plus tests.
- Keep writes deterministic and interaction bodies byte for byte.
- Check the live server notes in memory before claiming anything is deployed.

## Out of scope

- Changing what "disqualified" means as a stage, or the stage rules feature.
- A "hold and restore" mode for drafts of parked companies (decided against).
- Contact-level disqualification (`wrong-person` stays an outreach-only skip).
- Letting the AI weigh the free-text Disqualifiers section differently.
- Auto-skipping stale drafts of companies that were closed before this ships.
  Optional follow-up: a banner on the Drafts tab ("N open drafts belong to
  closed companies") with a button that calls `skip_open_for_company`.

## Done means

Disqualify a company with drafts in the demo folder and see the drafts skipped
with the reason; run a batch and see the company listed as left out with a way
back in; generate one draft for it and see the warning; reply to one of its
people and get a reply draft; confirm that nothing reaches send for it except
that single, deliberate draft. Report which of the calls C1 to C8 you changed.
