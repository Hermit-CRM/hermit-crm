# Generate outreach: use logged interactions and company research

> **For agentic workers:** use superpowers:executing-plans. Checkbox steps. Read CLAUDE.md first (pytest must pass, commits start with `ai:`, fictional names in tests only, no new deps).

**Goal:** "Generate outreach" on a contact page drafts with the contact's real interaction history and, when the free scrape finds nothing, an automatic ai-web research pass.

**Spec:** the two decisions below (made by Gijs, 2026-10-25). No other doc.

## Why (verified in code, do not re-investigate)

1. `outreach.make_brief` (`src/hermitcrm/outreach.py` ~L747) builds `brief.relationship` from `mine[:3]`. `company.interactions` is sorted **oldest first** (`store.py` L516), so it takes the three *oldest*, not newest. Each line comes from `_interaction_line` (L708): date, label, subject or `followups.first_line(body)`, one line of 90 chars with the greeting skipped. A LinkedIn message gives a fragment or nothing. The draft never sees what was actually said.
2. `ScrapeResearcher.research` (L354) reads only website, company LinkedIn and person LinkedIn. Velatir has no website and LinkedIn refuses anonymous fetches, so `pages` is empty, it returns before the AI call, and there are no findings. `outreach_research` defaults to `scrape`; ai-web is opt-in via the panel select.

## Decisions (fixed)

- **Interactions:** all of this contact's interactions (notes included), newest kept, **~4,000 character total budget**, oldest dropped first, rendered oldest-to-newest with bodies. Plus the 2 latest touches with *other* contacts at the company as one-liners (as today).
- **Research:** keep `scrape` as default. If scrape yields **no usable finding** (`not any(f.usable and f.source != "crm" ...)`), automatically run one ai-web pass. Only when ai-web is possible (`enricher.web_only_problem() == ""`); otherwise keep the scrape result and add a note saying why it did not escalate.
- **Scope of escalation:** every scrape-level build: the Generate button, batch builds on the Outreach page and the CLI. An explicit `ai-web` level is unchanged.
- **Model:** the live server must run research (scrape, escalated ai-web) and the critic on **Haiku 5.5 (`claude-haiku-5-5`)**. The live `config.toml` sets `enrich_model = ""` and no `enrich_model_light`, so the fix is the code default (Task 3), not a config edit. Drafting stays on the medium model.
- **Ship:** open a PR, then deploy to the live server (Task 4).

## Do not collide with the "Ask-Adjust loading indicator" session

That session is editing Ask/Adjust: `ask.html`, `base.html`, `ask.py`, `adjust.py`, `help/ask.md`, the Ask routes and `ask_tier`/`ask_page_view` in `web.py`, and the ASK tier in `enrich.py`. Rules:
- Do **not** touch those files or those `web.py` regions. This plan edits only `outreach.py`, the `outreach_build` / `outreach_generate` region of `web.py` (~L4253-4450), `templates/outreach.html`, `help/changelog.md` (append one line, no reflow), and tests.
- Work in a fresh worktree off `main` (`git worktree add ../hermit-outreach-context -b ai/outreach-context main`). The main checkout has the other session's uncommitted changes; never stash, reset or commit them.
- If `git merge main` shows conflicts in `web.py` or `changelog.md`, keep both sides.

## Files

- Modify `src/hermitcrm/outreach.py`: `make_brief`, `_interaction_line`, new `EscalatingResearcher`, `researcher_for`.
- Modify `src/hermitcrm/web.py`: `outreach_build` (pass `escalate=True`), and the CLI call site of `researcher_for` in `cli.py` (~L1840).
- Modify `src/hermitcrm/enrich.py` (one line, `LIGHT_MODELS`; the Ask session has uncommitted edits nearby, so keep this a one-line change) and `datafolder.py` (the `enrich_model_light` help text).
- Modify `src/hermitcrm/templates/outreach.html`: one hint line in the Generate panel.
- Tests: `tests/test_outreach_select.py` (brief), new `tests/test_outreach_escalate.py` (use fixtures/fakes from `tests/outreach_fakes.py`, see `test_outreach_aiweb.py` for the pattern).
- Modify `src/hermitcrm/help/changelog.md`.

## Task 1: Brief carries the real thread

**Interfaces:** Produces `INTERACTION_BUDGET = 4000` and `BODY_LIMIT = 600` in `outreach.py`; `make_brief` signature unchanged.

- [ ] **Step 1: Failing tests** in `tests/test_outreach_select.py`, next to `test_the_brief_has_persona_culture_relationship_and_fit`. Company with one contact and 6 dated interactions for them:
  - `test_brief_relationship_keeps_newest_interactions`: the last interaction's body text is in `brief.relationship`; the first (oldest) is dropped once the budget is exceeded.
  - `test_brief_relationship_includes_bodies_oldest_to_newest`: a LinkedIn message whose first line is only `Hi Ada,` has its second line present in the brief; entries are in date order.
  - `test_brief_relationship_budget`: `sum(len(l) for l in brief.relationship if contact-owned) <= 4000 + per-line overhead` (assert `<= 4300`).
  - `test_brief_relationship_includes_notes`: a `note` channel interaction for the contact appears, labelled `note`.
  - `test_brief_relationship_other_contacts_one_liners`: two latest touches with another contact appear as before, and a note by another contact does not.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_outreach_select.py -k relationship -q` → the new tests FAIL.
- [ ] **Step 3: Implement.** In `make_brief` replace the `mine[:3]` logic: walk `mine` newest-first, render each with a new `_interaction_detail(company, it) -> str` (`"{date:%Y-%m-%d} {label}"` + `": "` + subject, then body whitespace-collapsed and cut at `BODY_LIMIT`), stop adding when the running total would pass `INTERACTION_BUDGET` (always keep at least the newest, truncated), then reverse to oldest-first. Keep `_interaction_line` unchanged for `others[:2]` (also take the *newest* two: `others[-2:]`). Do not change `Brief.text()` output format.
- [ ] **Step 4:** run the new tests, then `.venv/bin/pytest tests/test_outreach_*.py -q` → all pass. If a prompt snapshot test breaks, update the expected relationship lines only.
- [ ] **Step 5:** commit `ai: outreach: the brief carries the newest interactions with their bodies`.

## Task 2: Escalate to ai-web when scrape finds nothing

**Interfaces:** Consumes `ScrapeResearcher`, `AiWebResearcher`, `Research` (fields `findings`, `notes`, `level`). Produces `class EscalatingResearcher` with `level = "scrape"`, `research(company, contact) -> Research`; `researcher_for(level, enricher, fetcher=None, today=None, timeout=10, escalate=False)`.

- [ ] **Step 1: Failing tests** in `tests/test_outreach_escalate.py` (fake fetcher and fake enricher runner as in `test_outreach_aiweb.py`):
  - `test_escalates_when_scrape_has_no_usable_findings`: company with no website → ai-web runner called once; result `level == "ai-web"`; findings from the AI kept.
  - `test_no_escalation_when_scrape_found_something`: website page yields a usable finding → ai-web runner not called, `level == "scrape"`.
  - `test_no_escalation_when_ai_web_unavailable`: enricher whose `web_only_problem()` is non-empty (e.g. a custom provider) → no ai-web call, scrape result returned, a note contains `ai-web`.
  - `test_explicit_ai_web_level_unchanged`: `researcher_for("ai-web", ..., escalate=True)` returns `AiWebResearcher`.
  - `test_escalate_false_keeps_scrape_only`: `researcher_for("scrape", ...)` returns `ScrapeResearcher`.
  - `test_generate_button_escalates` (in `tests/test_outreach_generate.py` style, via the web client): POST `/outreach/build` with `contact=` for a website-less company → the created item's `research_level == "ai-web"`.
  - `test_batch_build_escalates`: POST without `contact` (batch) for a website-less company → `research_level == "ai-web"`.
  - `test_cli_build_escalates`: the CLI outreach build path does the same.
  - `test_escalated_research_runs_on_the_light_model`: the ai-web call made by escalation uses the light-tier model (Task 3).
- [ ] **Step 2:** run them → FAIL.
- [ ] **Step 3: Implement** `EscalatingResearcher` in `outreach.py` next to `AiWebResearcher`: holds a `ScrapeResearcher` and an `AiWebResearcher` sharing fetcher/today/timeout; `research()` runs scrape; if `any(f.usable and f.source != "crm" for f in out.findings)` return it; if `enricher.web_only_problem()` return it with an appended note `"no usable findings and ai-web is not available: <problem>"`; else run `AiWebResearcher.research` (it re-runs the scrape internally, so avoid a double fetch by passing the first result: add an optional `base: Research | None = None` parameter to `AiWebResearcher.research` that skips its own scrape when given) and append a note `"scrape found nothing usable: ai-web research ran"`. `build()` stores `research_level` from `getattr(researcher, "level", "")` *before* research runs, so set `item.research_level = research.level` after research in `build()` (one line) so the item records what actually ran. Wire `escalate` into `researcher_for` (only for level `scrape`).
- [ ] **Step 4:** in `web.py` `outreach_build` and the CLI, call `researcher_for(level, enricher, ..., escalate=True)`. The escalated `AiWebResearcher` is built on `light(enricher)`, so the web pass also runs on the light tier. The existing `web_only_problem` early return applies only to an explicit `ai-web` level: leave as is.
- [ ] **Step 5:** in `templates/outreach.html` Generate panel, under the Research select add `<span class="small quiet">scrape, then ai-web automatically if it finds nothing</span>` (keep markup style of neighbours).
- [ ] **Step 6:** `.venv/bin/pytest -q` fully → pass. Fix only failures caused by this change.
- [ ] **Step 7:** append one line to `help/changelog.md` in the existing format; commit `ai: outreach: Generate escalates to ai-web when scrape finds nothing`.

## Task 3: Light tier is Haiku 5.5

- [ ] **Step 1: Failing tests.** In `tests/test_enrich.py` (~L208) the default light model for provider `claude` becomes `claude-haiku-5-5`; update that case and the `claude-haiku-4-5` expectations at ~L231, and in `tests/test_outreach_light.py` ~L86-87 (research and critic use `claude-haiku-5-5`, drafting unchanged). An explicit `enrich_model_light` or a named medium model still wins (existing cases stay).
- [ ] **Step 2:** run them → FAIL.
- [ ] **Step 3:** `enrich.py`: `LIGHT_MODELS = {"claude": "claude-haiku-5-5"}`; add `"claude-haiku-5-5": "Haiku"` to `MODEL_LABELS` (keep the old id). `datafolder.py` ~L93: `claude-haiku-4-5` → `claude-haiku-5-5` in the help text.
- [ ] **Step 4:** `.venv/bin/pytest -q` → pass. Commit `ai: light tier defaults to Haiku 5.5`.
- [ ] **Step 5 (after deploy, Task 4):** confirm the live default: `~/.local/share/uv/tools/hermitcrm/bin/python -c "from hermitcrm.enrich import LIGHT_MODELS; print(LIGHT_MODELS)"` prints `claude-haiku-5-5`.

## Task 4: PR and deploy

Follow the `hermitcrm-live-server-deploy` memory exactly.
- [ ] **Step 1:** `git diff main --stat` shows only this plan's files; `git diff main -- src/hermitcrm/migrations.py` is empty (live serve runs on the real data).
- [ ] **Step 2:** `.venv/bin/pytest -q` passes in the worktree. Push `ai/outreach-context`, open a PR to `main` with `gh pr create` (body: Why, the decisions, test result; end with the attribution line from the session reminder). Then ccd_pr `get_status` and `bind_pr` if unbound; do not poll CI yourself.
- [ ] **Step 3:** deploy from the worktree, not the shared checkout (it holds other sessions' WIP): `uv tool install --reinstall <worktree path>`; `diff -rq <worktree>/src/hermitcrm ~/.local/share/uv/tools/hermitcrm/lib/python3.12/site-packages/hermitcrm -x __pycache__ -x '*.pyc'` prints nothing; `launchctl kickstart -k gui/$(id -u)/io.hermitcrm.serve`; confirm a new PID and `curl` 200 on `/`.
- [ ] **Step 4:** report which branch went live, and run Task 3 step 5.

## Review Focus (one test each, add to the owning task)

- Contact with **no** interactions: brief shows `no earlier contact`, no crash (Task 1).
- Interaction with an empty body or only a greeting: line shows date and label, no empty `: ` (Task 1).
- A single interaction longer than the budget: truncated, not dropped (Task 1).
- ai-web raises `EnrichError`: scrape result kept, note added, item still drafted (Task 2).
- Batch of 3 contacts, one with a website: only the empty ones escalate (Task 2).
- Escalated item's card shows `ai-web` as its research level, not `scrape` (Task 2).

## Verify live (after merge only, never against /Users/gijsbos/Code/CRM for writes)

`hermitcrm init /tmp/x --demo`, add a website-less company with two logged interactions, run Generate from its contact page, open the item and confirm: relationship lines carry message bodies, research level reads ai-web. Putting it on the live :8765 server follows the `hermitcrm-live-server-deploy` memory and needs Gijs's go-ahead.
