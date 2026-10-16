# Plan: Part 04 · the Outreach page and replies to interest

Replaces `PLAN-03-04-05.md`, which re-planned part 03 (already built in
`src/hermitcrm/outreach.py`, PR #109) and assumed HTMX, SSE and a single offer
line. This plan builds on the phase 1 code as it is. Spec:
[04-review-page](04-review-page.md); decisions in PR #110.

Two pull requests, in order:

- **04a, the review page**: the Outreach page, the card actions, the contact
  page button and card. First touches only (the only kind phase 1 drafts).
- **04b, replies to interest**: the `reply-to-interest` kind, the
  `interested` outcome, classification, the first step offer.

Part 05 (follow-ups, `ai-web`, critic, bookmarklet) gets its own plan after 04
lands. Follow-ups use `followup_nudge_days` (decided in PR #110).

## Fixed points (from the codebase, not up for change here)

- Plain FastAPI + Jinja, forms that POST and redirect with a flash. No HTMX, no
  SSE, no new frontend dependency, no background threads.
- Long AI work runs in `run_in_threadpool` inside the request, as Enrich and
  routines do.
- Every write goes through `outreach.py` (one commit per step, through
  `store.lock` / `store.batch` and `store.notify`). The web layer only parses
  forms and renders.
- Commit messages in the data folder are the app's own (`outreach: …`), never
  `ai:`.
- Item bodies are kept byte for byte: a textarea's `\r\n` is turned into `\n`
  and nothing else is changed.
- CSRF on every POST (`check_csrf`); the request guard already refuses
  cross-site POSTs.

## 04a · the review page

### Building a batch without a background thread

"Cards appear as they finish" without threads or SSE: **one contact per
request**.

1. `GET /outreach` shows the build form (filter, channel, batch size, research
   level, `--strong`) and, with `?preview=1`, the `select()` result (no AI, no
   writes): who would get a draft, who not and why, the playbook gate.
2. `POST /outreach/build` re-runs `select()` with the same form, builds the
   **first** pick only (`outreach.build` with that one candidate, in the
   threadpool), then redirects to `/outreach?…&left=N-1&batch=<id>`.
3. While `left > 0`, the page shows "Building: n of N done" and a small inline
   script submits the build form again on load (a **Stop** link drops
   `left`). Without JavaScript the button reads "Build the next one".

Re-running `select()` each time is safe: a contact with an open item is
excluded, so the next request takes the next contact. All items of one run
share a batch id: `build()` gets an optional `batch=` argument.

### Card actions (each one POST, one commit, back to the card's anchor)

| Action | Route | `outreach.py` |
|---|---|---|
| Save and check again | `/outreach/{id}/check` | `save_text()` (new): writes the edited subject/body/pitch and the checks re-run on it |
| Mark ready | `/outreach/{id}/ready` | `mark_ready(..., subject=, body=, pitch=)`: the edit and the state change in **one** commit |
| Regenerate (optionally stronger) | `/outreach/{id}/regenerate` | `redraft()` (new): same findings, new draft, the old AI text replaced |
| Skip | `/outreach/{id}/skip` | `skip(reason, note)` |
| Mark sent | `/outreach/{id}/sent` | `mark_sent()` |
| Remove a finding / add your own | `/outreach/{id}/findings` | `set_findings()` (new): a finding of your own has source `you`, confidence high |
| Copy | (no route) | clipboard, inline script |

A finding of your own counts as a known finding for the "cites unknown
findings" check, so a regenerate can use it.

### The page

- Nav: **Outreach** next to Messages.
- Tabs as query links (`?tab=`): **Drafts** (drafted and researching), **Ready**,
  **Sent**, **Skipped**, with counts. Replies to interest and Follow-ups tabs
  arrive with 04b and part 05; until then they are not shown.
- A card: name, title, LinkedIn ↗; company, stage, fit, website ↗; flags;
  findings with source link and a confidence dot; the editable draft; angle,
  approach, language, norms; check results (a failing check is a warning);
  the buttons.
- Playbook not ready: the page says so and links Settings > Playbook; no build
  button.
- AI CLI missing or not restrictable (`routines.ai_problem`): build and
  regenerate say why and are disabled.

### Contact page

- An **outreach card** while an open item exists for that contact (state,
  channel, link to the card on /outreach).
- A **Research & draft** button with a channel picker: `POST /outreach/build`
  with `contact=company/contact` (`select(contacts=[…])` already exists). It
  refuses with the reason `select()` gives (cooldown, open item, do not
  contact…).

### Tests (`tests/test_outreach_web.py`, fake AI from `outreach_fakes.py`)

- the page renders on the demo folder, empty and with items; tabs count right
- preview writes nothing and runs no AI
- build makes one item per request, `left` counts down, items share a batch id
- each action is one commit and changes only what it says; Mark ready with an
  edit is one commit; bodies byte for byte (`\r\n` → `\n` only)
- Mark ready with a failing check: allowed, warning shown, kept in `checks`
- Mark ready writes no outbound interaction (only the findings note)
- regenerate keeps findings, replaces the AI text, refuses on a non-drafted item
- a finding of your own survives a regenerate and passes the known-findings check
- CSRF refused on every POST; unknown id 404
- the contact page shows the card and the button; the button refuses with the
  reason when `select()` excludes the contact

## 04b · replies to interest (next PR)

1. `interested` outcome: in `DEFAULT_OUTCOMES` **between** `successful` and
   `unsuccessful` (first = a reply, last = silence). New folders get it;
   existing ones get an offer in Settings > Outcomes, never a silent change.
   `outcomes` is config: no migration.
2. Sources: inbound replies from `followups.py` "replies owed". Logged with
   outcome `interested` → listed with no AI. Otherwise "Check replies" asks the
   AI (no tools) once per reply; the result is stored on the item, the person
   confirms.
3. Playbook: optional `first_step_offer` per approach (left out when empty).
   A front-matter key in `MESSAGING.md`, so a numbered migration only if an
   existing value changes; adding an optional key needs only the validator and
   its tests.
4. `AIDrafter` learns `reply-to-interest`: the approach's offer line, one proof
   line, the first step offer, one question; no time slot, link or price.
   Templates in `default_messages.toml` (EN/DE/NL/FR). The offer-line check
   already exists in `check_text`.
5. Page: the **Replies to interest** tab, first. Contact page: the button picks
   the kind from the history (no outbound → first touch; interested reply →
   reply to interest).

Tests: an inbound interaction with outcome `interested` appears in the tab
with no AI call; the outcome order in reports (reply rate unchanged on the
demo folder); a reply-to-interest draft without the offer line is refused.
