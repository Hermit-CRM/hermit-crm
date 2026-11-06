# Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the verified findings of the 2026-10-31 audit in risk order: the one real security flaw first, then the cheap zero-behaviour cleanups, then the sender/AI/data-safety work, then docs and structure.

**Architecture:** No design change. Every task is a small, separately committed fix on its own test. Wave 1 (Tasks 1 to 7) is specified in full below; it needs no answers from the owner. Waves 2 to 6 are a gated roadmap: each names the decision it waits on and gets its own detailed plan when started.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, pytest. Mail via `smtplib` / `imaplib`.

**Spec:** `audit/06-action-plan.md` (task numbers below, in brackets, refer to it), findings in `audit/04-dependencies-security.md` (S1 to S17) and `audit/01-dead-code.md`, questions in `audit/07-open-questions.md`.

## Global Constraints

- Work from a **separate worktree cut from `main`**, never in `/Users/gijsbos/Code/HermitCRM`: that folder holds uncommitted Companies/Contacts table work (branch `ai/companies-table`, 20 table tests failing on purpose).
- `.venv/bin/pytest` must pass before any commit (CLAUDE.md). Commit messages start with `ai:`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- No new runtime dependencies. No real people, companies or addresses in code, tests or docs: `example.com` / `example.org` only.
- Front-matter keys or values are not touched, so no migration is needed in this wave.
- Every new `.py` file starts with the Apache-2.0 header used by its siblings (`tests/test_licensing.py` checks it).
- One task = one commit. Never `git add -A` (untracked tool folders exist); add files by name.

## Corrections to the audit (found while verifying; the tasks below already use them)

| Audit said | Verified fact | Effect on the plan |
|---|---|---|
| S1 fix: "pass `ssl_context=` to the connections" | Test fakes are `factory(self, host, port, timeout=None)` (`tests/send_fakes.py:56,128`). Passing a new kwarg at the call site breaks every fake. | The context goes **inside the default factory**, a new `mailtls.py`. Fakes and call sites stay unchanged. |
| Task 7 risk "med: a legitimate queued item might have an empty hash" | `sendqueue.py:237` always sets the hash when scheduling; `send.py:969` backfills it on retry. An app-made queued item never has an empty hash. | Task 7 is **low** risk. Open question 5 does not need an answer first. |
| Task 11 "compare the two `valid_email`, keep one" | They differ: `models.valid_email` = one `@` with text either side; `setup.valid_email` = the `_EMAIL` regex (`setup.py:276`). The local `def` shadows the import, so the regex is today's behaviour. | Zero-behaviour fix is to delete the unused import. Unifying the rules would change which addresses setup accepts: separate decision (Wave 6 note). |

## Review Focus

Inputs and conditions the audit implies that no task's tests cover by themselves:

- A mail host with a bad or self-signed certificate: setup and BCC import must fail with a readable "could not reach" message, not a stack trace (Task 1 pins this for IMAP).
- An approach name with `'`, `"`, `<`, `&` or `\`: the delete button must stay usable (Task 2 pins `'` and a script-like name).
- A queued item whose `send_hash` is empty and whose `send_at` is in the past: must be held, with the reason visible in `send_note`, and must not be sent on the next tick (Task 3).
- A hand-edited queued item that is **not** scheduled (`scheduled=False`, "Send now"): must still send. The new guard applies only to the unattended tick (Task 3).
- Removing dead constants must not remove `language_names()` / `signal_labels()` if those functions have other callers (Task 5 checks).

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `src/hermitcrm/mailtls.py` (new) | Default connection factories that verify the server certificate | 1 |
| `src/hermitcrm/send.py`, `src/hermitcrm/bcc.py` | Use `mailtls` as the default factory; `local_hold` guard | 1, 3 |
| `src/hermitcrm/templates/playbook.html` | Delete-approach confirm, JS-safe | 2 |
| `pyproject.toml`, `uv.lock` | pypdf floor | 4 |
| `.gitattributes` | Export-ignore for `tests/test_website_features.py` | 6 |
| `learning.py`, `messaging.py`, `calendar_sync.py`, `bcc.py`, `setup.py`, `adjust.py`, `exemplars.py`, `outreach.py`, `web.py` | Dead code only | 5 |

---

## Wave 0: Setup (once)

- [ ] **Step 1: Create the worktree from `main`**

```bash
cd /Users/gijsbos/Code/HermitCRM
git fetch origin && git worktree add ../HermitCRM-audit -b ai/audit-wave-1 origin/main
cd ../HermitCRM-audit && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

- [ ] **Step 2: Baseline** — `cd ../HermitCRM-audit && .venv/bin/pytest -q` (12 to 20 minutes under load; run it in the background and start Task 1 meanwhile). Expected: `3289 passed, 2 skipped` (the audit's clean-clone result; the count may differ by a few if `main` has moved).

**Suite cost:** CLAUDE.md demands a green full suite before every commit, and a run is slow. Per task: iterate on the targeted test file, then run the full suite once before that task's commit. Start the next task while it runs.

---

## Wave 1: Specified in full (no owner decisions needed)

### Task 1: Verify the mail server certificate [audit task 1, S1, HIGH]

**Files:**
- Create: `src/hermitcrm/mailtls.py`
- Modify: `src/hermitcrm/send.py:367` (default SMTP factory), `src/hermitcrm/send.py:496` (default IMAP factory), `src/hermitcrm/bcc.py:1031` (default IMAP factory)
- Test: `tests/test_mailtls.py` (new)

**Interfaces:**
- Produces: `mailtls.smtp_ssl(host: str, port: int, timeout: float | None = None) -> smtplib.SMTP_SSL` and `mailtls.imap_ssl(host: str, port: int = 993, timeout: float | None = None) -> imaplib.IMAP4_SSL`. Same call shape as the test fakes (`host, port, timeout=`), so nothing else changes.
- Consumes: nothing from earlier tasks. Port 587 already uses `ssl.create_default_context()` (`send.py:373`), left alone.

- [ ] **Step 1: Write the failing tests** in `tests/test_mailtls.py`. Monkeypatch `imaplib.IMAP4_SSL` and `smtplib.SMTP_SSL` with a recorder that captures kwargs, then call the helpers:
  - `test_imap_ssl_passes_a_verifying_context`: `ctx = recorded["ssl_context"]`; assert `ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True`; assert host `"imap.example.com"`, port `993`, timeout forwarded.
  - `test_smtp_ssl_passes_a_verifying_context`: same assertions on `recorded["context"]`.
  - `test_the_defaults_are_the_verifying_factories`: `send.Mailbox(settings, "pw").factory is mailtls.imap_ssl`; `bcc.GmailMailbox(settings, "pw").imap_factory is mailtls.imap_ssl` (reuse `SETTINGS` pattern from `tests/test_bcc.py:617`); for SMTP, assert via `inspect`-free route: monkeypatch `mailtls.smtp_ssl` with a sentinel raising `RuntimeError`, call `send.connect(settings_with_smtp_port_465, "pw")`, expect that sentinel hit (wrapped by `classify_smtp`; assert it was called).

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_mailtls.py -v`. Expected: collection/ImportError (`mailtls` does not exist).

- [ ] **Step 3: Implement** `mailtls.py` with the two functions above; each builds `ssl.create_default_context()` and passes it as `ssl_context=` (IMAP) / `context=` (SMTP). Then in `send.py` replace `smtplib.SMTP_SSL` with `mailtls.smtp_ssl` (line 367) and `imaplib.IMAP4_SSL` with `mailtls.imap_ssl` (line 496); in `bcc.py` replace `imaplib.IMAP4_SSL` with `mailtls.imap_ssl` (line 1031). Import it as `from . import mailtls`. Remove `imaplib` imports only if ruff then reports them unused.

- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_mailtls.py tests/test_send_email.py tests/test_send_worker.py tests/test_send_smtp_loopback.py tests/test_bcc.py -q`. Expected: all pass (fakes are untouched, so nothing else should move).

- [ ] **Step 5: Verify against the real world** — `.venv/bin/hermitcrm doctor --online` against the real mailbox still logs in (owner action, one command; if no mailbox is configured, state that this check was not run).

- [ ] **Step 6: Full suite, then commit**

```bash
git add src/hermitcrm/mailtls.py src/hermitcrm/send.py src/hermitcrm/bcc.py tests/test_mailtls.py
git commit -m "ai: verify the mail server certificate on IMAP and SMTP over 465"
```

**Release note to draft** (goes in the changelog, not code): users with a self-signed mail server will now get a "could not reach" error. That is the point of the change.

---

### Task 2: Make the "Delete approach" confirm safe [audit task 2, S6]

**Files:**
- Modify: `src/hermitcrm/templates/playbook.html:75`
- Test: `tests/test_web_playbook.py` (add; reuses the `client`, `folder`, `token` helpers at lines 43 to 57)

**Interfaces:** none.

- [ ] **Step 1: Write the failing test** `test_the_delete_confirm_is_valid_javascript_for_any_name(client, parametrize name in ["Owner's pitch", "x');alert(1);//", 'Say "hi"', "a\\b", "R&D <team>"])`:
  create the approach with `POST /settings/playbook/new` (`csrf_token`, `name`; it needs a second approach so the Delete form renders, which `new` provides), load `GET /settings/playbook?approach=<urlencoded name>`, find the `<form ... action="/settings/playbook/delete" ... onsubmit="...">` attribute with a regex, `html.unescape` it, strip the `return confirm(` prefix and the `)` suffix, then assert `json.loads(inner) == f"Delete the approach {name} and everything in it? It stays in the git history."`. This proves the browser sees one well-formed JS string equal to the intended text, for every name.

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_web_playbook.py -k delete_confirm -v`. Expected: FAIL on the apostrophe and script-like names (`json.loads` error).

- [ ] **Step 3: Implement** — in `playbook.html:75` change the handler to `onsubmit="return confirm({{ ('Delete the approach ' ~ approach.name ~ ' and everything in it? It stays in the git history.') | tojson | forceescape }})"`. This is the same `tojson | forceescape` construction `contact.html:126` already uses.

- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_web_playbook.py -q` (new cases pass; the existing delete tests at lines 177, 189, 283 stay green).

- [ ] **Step 5: Full suite, then commit** `git add src/hermitcrm/templates/playbook.html tests/test_web_playbook.py` — `ai: playbook: the delete-approach confirm survives quotes in the name`.

---

### Task 3: Hold queued mail that has no approval hash [audit task 7, S3]

**Files:**
- Modify: `src/hermitcrm/send.py:786` (`local_hold`)
- Test: `tests/test_send_email.py` (add a case to the parametrized `test_every_guard_holds_the_item`, lines 369 to 417)

**Interfaces:** `local_hold(store, item, settings, *, scheduled: bool, config=None) -> str` keeps its signature. New reason string: `"it was never scheduled in the app (no approval fingerprint)"`.

- [ ] **Step 1: Write the failing test** — add `"unapproved"` to the parametrize list and the `why` map. Setup branch: `scheduled = True`; set `it.state, it.queued, it.send_at = "queued", NOW, NOW`, leave `it.send_hash = ""`, write the item. Expected `why`: `"never scheduled in the app"`. The shared assertions already check `out.kind == "held"`, nothing sent, and `message_id == ""`.
  Add `test_send_now_still_sends_an_item_with_no_hash(folder)`: `ready_item(...)`, `deliver(..., scheduled=False)`, assert `out.kind == "sent"`. This pins the Review Focus line that "Send now" is unaffected.

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_send_email.py -k "unapproved or no_hash" -v`. Expected: `unapproved` FAILS (the item is sent); the Send-now test passes already.

- [ ] **Step 3: Implement** — in `local_hold`, split the existing line `if scheduled and item.send_hash and item.send_hash != text_hash(...)` into two checks: first `if scheduled and not item.send_hash:` return the new reason; then the existing mismatch check without the `item.send_hash and` clause.

- [ ] **Step 4: Run the sender tests** — `.venv/bin/pytest tests/test_send_email.py tests/test_send_worker.py tests/test_send_web.py -q`. **Expected collateral:** some fixtures in `test_send_worker.py` may queue items without a hash. If one fails, fix the fixture to set `send_hash=send.text_hash(...)` (as line 356 does); do not weaken the guard.

- [ ] **Step 5: Full suite, then commit** `git add src/hermitcrm/send.py tests/test_send_email.py` (plus any fixed test file) — `ai: send: an unattended tick holds a queued item that has no approval hash`.

---

### Task 4: Raise the PDF library floor [audit task 3]

**Files:** Modify `pyproject.toml:35`, `uv.lock`. Test: existing PDF tests.

- [ ] **Step 1:** change `"pypdf",` to `"pypdf>=6.21.4",` in `pyproject.toml`.
- [ ] **Step 2:** `uv lock --upgrade-package pypdf` and confirm the diff touches only the pypdf entry (version 6.21.2 → 6.21.4 or later) and its hashes: `git diff --stat uv.lock`.
- [ ] **Step 3:** `uv export --frozen --no-hashes --no-emit-project > <scratchpad>/req.txt && uvx pip-audit -r <scratchpad>/req.txt --no-deps --disable-pip`; expected: no pypdf findings.
- [ ] **Step 4:** `.venv/bin/pip install -e '.[dev]' -U pypdf` then `.venv/bin/pytest tests -k "pdf or textsource" -q`. Expected: pass.
- [ ] **Step 5:** full suite, then `git add pyproject.toml uv.lock` — `ai: require pypdf 6.21.4 or newer (seven published advisories)`.

---

### Task 5: Remove the verified-dead Python [audit tasks 4 and 11]

High-confidence items only (`audit/01-dead-code.md` section A). Re-verified today: each name below has exactly one occurrence in `src`, `tests`, `docs`, `README.md`, `scripts`, `website`.

**Files:** `calendar_sync.py:68`, `learning.py:649`, `messaging.py:52,53,55,128,129`, imports in `calendar_sync.py`, `bcc.py`, `setup.py`, variables in `adjust.py`, `exemplars.py`, `outreach.py`, `web.py`.

- [ ] **Step 1: Baseline lint** — `uvx ruff check --select F401,F811,F841 --no-cache src`; note the count. Line numbers in the audit may have drifted; use ruff's output as the locator. (`ruff` is not in `.venv`; `uvx` runs it without adding a dependency.)
- [ ] **Step 2: Read `learning.smooth_weights`'s docstring** ("Rule 6"). If it describes a rule the owner may still want applied, **stop and ask** (open question 11) instead of deleting; otherwise delete it.
- [ ] **Step 3: Delete** `URL_ENV`, `DEFAULT_SIZE_FIELD`, `DEFAULT_TEAM_FIELD`, `GROWTH_SIGNALS`, the constants `LANGUAGE_NAMES` and `SIGNAL_LABELS`. Then `grep -rnw "language_names\|signal_labels" src tests`: if the functions now have no caller either, report that rather than deleting them.
- [ ] **Step 4: Remove** the unused imports and variables ruff lists for `calendar_sync.py` (`os`, `tomllib`, `date`), `bcc.py` (`os`), `setup.py` (`sys` **and the shadowed `from .models import valid_email` at line 41**), and the unused locals in `adjust.py`, `exemplars.py`, `web.py` (`cols`). For `outreach.py` (`company = store.get(item.company)`) first confirm `Store.get` has no side effects (`grep -n "def get" src/hermitcrm/store.py`), then delete the line. **Do not touch** the Medium items (`cli.layout`, `doctor.__version__`, `migrations.DEFAULT_OUTCOMES`): tests may use them as attributes.
- [ ] **Step 5: Rename the second `outreach_page`** at `web.py:4796` (the `POST /outreach/{id}/page` handler) to `outreach_item_page`. Verified: nothing else references the name (`grep` over templates, src and tests returned only the two `def` lines). Route paths and methods must not change.
- [ ] **Step 6: Prove no route moved** — before and after, dump `sorted((r.path, sorted(r.methods or []), r.name) for r in create_app(folder, config).routes)` for a demo folder and diff: the only difference must be the one renamed `name`.
- [ ] **Step 7:** `uvx ruff check --select F401,F811,F841 --no-cache src` shows only the deliberately skipped Medium items; full suite; `git add` the touched files by name — `ai: remove verified-dead constants, imports and variables; rename the second outreach_page`.

---

### Task 6: Keep `test_website_features.py` out of downloads [audit task 6]

**Files:** Modify `.gitattributes` (add after line 14).

- [ ] **Step 1: Reproduce** — `mkdir <scratchpad>/export && git archive HEAD | tar -x -C <scratchpad>/export && ls <scratchpad>/export/tests/test_website_features.py <scratchpad>/export/tests/test_website_stats.py`. Expected today: the first file exists (the bug), the second does not (its sibling is already ignored).
- [ ] **Step 2:** add the line `tests/test_website_features.py export-ignore` next to its five siblings, and commit (`git archive` reads the committed tree, so the attribute only takes effect after the commit).
- [ ] **Step 3: Verify** — in a fresh scratch folder, `git archive HEAD | tar -x`, confirm `tests/test_website_features.py` is gone, then run `<worktree>/.venv/bin/python -I -m pytest -q -x --ignore=tests/test_licensing.py` from inside the export (`test_licensing` needs `.git`, see audit `05`). Expected: no import error from a missing `website/build.py`.
- [ ] **Step 4:** commit message: `git add .gitattributes` — `ai: keep tests/test_website_features.py out of the download`.

---

### Task 7: Wave 1 wrap-up

- [ ] Push `ai/audit-wave-1` and open one PR with Tasks 1 to 6 as separate commits. The PR body lists the "Corrections to the audit" table and ends with the Claude Code attribution line. Then follow the repo's PR flow (bind the PR, read CI).
- [ ] Track progress by ticking the boxes in this plan file. `audit/` is untracked scratch in the main folder and is not a place for status.

---

## Waves 2 to 6: Gated roadmap (each gets its own detailed plan when started)

| Wave | Audit tasks | Waits for | Notes from verification |
|---|---|---|---|
| **2. Sender and AI** | 8 (duplicate-send), 9 (spend caps, enrichment lockdown), 10 (deny `.secrets.toml` in Ask) | Q4 (IMAP always set?), Q9 (cap number, subscription or API key), Q10 (enrichment web-only?), Q8 (confirm) | Task 10 starts with a throw-away probe of whether `Grep`/`Glob` honour a Read deny in the installed `claude`; the plan branches on that result. Task 8 touches `send.py`, so do it after Task 1 merges. |
| **3. Data safety** | 12 (atomic writes, migration lock), 13 (xlsx caps), 14 (https-only calendar), 29 (surface commit failures), 15 (Keychain via stdin) | Q13, Q7, Q6, Q15, Q17 | Task 12 is the riskiest: one helper used by every writer, byte-for-byte output required (CLAUDE.md). Write the interrupted-write test first. Task 15 needs a real Mac Keychain check and rewrites the two tests that currently lock the weakness (`tests/test_setup.py:139-140`, `tests/test_cli_setup.py:120-121`). |
| **4. Docs and hygiene** | 17 (README, plus a test comparing README tables to `cli.py` / `DEFAULT_CONFIG`), 18 (ARCHITECTURE, TODO, DIRECTORIES, specs, AGENTS.md credits paragraph), 19 (CI: ruff F-rules, pip-audit, site-build check, DCO), 16 (real-domain fixtures), 20 (worktree and branch clean-up) | Q25, Q26, Q23/Q24 for task 20 | Task 20 deletes things: never touch `HermitCRM-pr89` (119 uncommitted files) or `claude/demo-plan-b3cbad` without the owner's explicit yes. The `.gitignore` additions from audit task 5 (`.impeccable/`, `.superpowers/`, `AUDIT-*.md`) can go here too: `.gitignore` is not touched by the table work, only audit task 5's CSS half is blocked. |
| **5. Table work** | 31 (finish Companies/Contacts tables, 20 failing tests), then 5-CSS (dead CSS and attributes), 21, 25 | Whoever owns `ai/companies-table` | Not an audit defect. Do not mix with Waves 1 to 4; all of them avoid `style.css`, `macros.html`, `layout.py` and `tests/test_dashboards.py`. |
| **6. Structure** | 22 (move borrowed functions + no-upward-imports test), 23 (split `web.py`), 24 (inline scripts out, drop `'unsafe-inline'`, headers), 27, 28, 30 | Only when those areas are next touched; 23 needs 22 and Wave 5 | Before 23, snapshot the route table (the Task 5 Step 6 script) and require it identical after. `setup.valid_email` vs `models.valid_email` unification belongs here as an explicit behaviour decision. |
| **Decision track** | 26 (history/prospect data) | Q1 (were the people real?) | Fact gathering only; **no history rewrite without the owner's explicit yes**. Can run any time, in parallel to everything, since it changes no code. |

### Questions to ask the owner in one batch (they unblock Waves 2 to 4)

Q1 (real prospects in history?), Q4 and Q5 (IMAP set? who else edits outreach files?), Q8 to Q10 (Ask deny, AI cap number, enrichment scope), Q13 to Q15 and Q17 (crash-safe saving, backups, commit warning, Keychain), Q23 and Q24 (worktrees, `.impeccable/`). The rest of `audit/07-open-questions.md` can wait.

---

## Self-Review

- **Spec coverage:** every task in `audit/06-action-plan.md` appears either in Wave 1 (1, 2, 3, 4, 5, 6, 7, 11) or in the roadmap (8, 9, 10, 12 to 31, 5-CSS). The audit's top-10 items 1 to 7, 9 and 10 map to Waves 1 to 4; item 8 (hard to change) maps to Wave 6.
- **Type consistency:** `mailtls.smtp_ssl` / `mailtls.imap_ssl` are named identically in Task 1's tests, interface and implementation step. `local_hold`'s signature is unchanged in Task 3.
- **Review Focus:** each of the five lines has an owning test (Tasks 1, 2, 3, 3, 5).
- **Proportion:** Wave 1 is six small fixes with signatures and assertions, no function bodies; later waves stay a table because their shape depends on the owner's answers.
