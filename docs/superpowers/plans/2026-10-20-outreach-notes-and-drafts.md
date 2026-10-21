# One outreach path, one list of notes, one-click copy: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Message drafts box with a Generate outreach deep link into Outreach, make findings and notes one list, and add one-click copy for email addresses.

**Architecture:** A new `notes.py` owns the note format and the card's rows. `outreach.py` writes research findings as notes, rebuilds `Item.findings` as a snapshot of the live notes at each draft, and passes an optional language pick. `web.py` and the templates swap the Findings panel for a Notes panel, add the `/outreach?contact=` panel, and drop the drafts section. A small `static/copy.js` does the copy buttons.

**Tech Stack:** Python 3.13, FastAPI, Jinja2, pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-20-outreach-notes-and-drafts-design.md`

## Global Constraints

- Commit messages for AI-made changes start with `ai:`; each ends with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- `.venv/bin/pytest` passes before the final commit (full run takes about 9 minutes; run targeted files while working).
- No new runtime dependency.
- Fictional names, `example.com` / `example.org` only in code, tests and docs.
- No record migration: a note stays an interaction with channel `note`. `Item` may gain one optional key (`language_pick`); old item files must still load.
- The web-research prompt (`ai_web_prompt`) never contains note text.
- Keep writes deterministic and interaction bodies byte for byte: the research note format is fixed text.
- Generating stays a POST with a CSRF token; a GET never calls the AI or writes.
- Prompt line format for findings stays `N. [kind, confidence, note; source S] text` (the test fakes parse it).

## Review Focus

- A user note whose text contains the word "Source:" mid-body must stay a plain user note (only an exact last line in the research format is parsed).
- Running research twice for one contact writes each finding once (duplicate text is skipped).
- A contact with no notes, and one with 100 notes (cap: newest 20, 4,000 characters, longest dropped first).
- An item file written before this change (findings including a `crm` one, no `language_pick`) loads, regenerates and marks ready without losing a finding.
- `/outreach?contact=` with a malformed or unknown value renders the normal page without a panel, and never writes.

---

### Task 1: Copy-email button

**Files:**
- Create: `src/hermitcrm/static/copy.js`
- Modify: `src/hermitcrm/templates/base.html:17` (script tag after busy.js), `templates/outreach.html:243`, `templates/contact.html:89`, `static/style.css`
- Test: `tests/test_copy_email.py`

**Interfaces:**
- Produces: any `<button type="button" class="copy-btn" data-copy-text="…">copy</button>` copies its `data-copy-text` and shows "copied" for 1.5 s. Later tasks may reuse it.

- [ ] **Step 1: Write failing tests** in `tests/test_copy_email.py`: `test_outreach_card_has_a_copy_button_next_to_the_email` (build a drafted item as `tests/test_outreach_page.py` does, GET `/outreach`, assert `data-copy-text="jane@acme.example"` and the `mailto:` link both present); `test_contact_details_row_has_a_copy_button` (GET contact page, the `<dt>email</dt>` row holds a `copy-btn` with the address and still a `mailto:` link); `test_copy_script_is_served_and_loaded` (GET `/static/copy.js` is 200; base page contains `/static/copy.js`).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_copy_email.py -q`. Expected: 3 FAIL.
- [ ] **Step 3: Implement** `copy.js`: one delegated click listener on `document` for `.copy-btn[data-copy-text]`; `navigator.clipboard.writeText` when `window.isSecureContext`, else the hidden-textarea `execCommand("copy")` fallback copied from `outreach.html`'s Copy handler; label "copied" or "copy failed", restored after 1.5 s. Add the buttons beside the address in both templates; style `.copy-btn` as a small quiet button in `style.css`.
- [ ] **Step 4: Run** the tests again. Expected: PASS.
- [ ] **Step 5: Commit** `ai: copy: one-click copy next to an email address on Outreach and the contact page`.

### Task 2: `notes.py`, the note format and the snapshot

**Files:**
- Create: `src/hermitcrm/notes.py`
- Test: `tests/test_notes.py`

**Interfaces:**
- Consumes: `outreach.Finding`, `outreach.YOURS`, `outreach.is_stale`, `outreach.USABLE`, `outreach.OutreachError`, `Store.create_interaction`, `Store.batch`.
- Produces:
  - `NOTE_COUNT = 20`, `NOTE_CHARS = 4000`
  - `contact_notes(company, contact_slug) -> list[Interaction]` newest first, channel `note` only
  - `research_note(f: Finding) -> tuple[str, str]` (subject `"Research: <host>"`, body `"<text>\nSource: <url> (<kind>, <date>, <confidence>)"`)
  - `finding_of(note: Interaction, today: date) -> Finding`
  - `snapshot(company, contact_slug, today: date) -> list[Finding]` capped as the spec says
  - `save_findings(store, company_slug, contact_slug, findings: list[Finding]) -> tuple[int, int]` (written, dropped_low): skips `crm`/`you` sources and text already a note, writes medium/high as notes, counts low
  - `add_note(store, company_slug, contact_slug, text: str) -> Interaction` (raises `OutreachError` on empty text)
  - `adopt(store, item) -> int`: saves an open item's findings that are not notes yet (a `you` finding as a plain note); returns how many
  - `card(company, contact_slug, item, today) -> dict` with keys `rows` (list of `{note, used, source_url, origin}`), `newer` (notes dated after `item.drafted`), `legacy` (item findings not yet notes, no `crm`), `company_notes` (the company's `notes` text)

- [ ] **Step 1: Write failing tests** in `tests/test_notes.py` (a store fixture with one company and contact, as `tests/test_contact_page.py` builds): `test_research_note_round_trips` (`finding_of(research_note(f))` equals `f` in text, source, kind, confidence, date); `test_a_note_you_wrote_is_high_confidence_person_and_never_stale`; `test_source_in_the_middle_of_a_note_is_a_plain_note` (Review Focus 1); `test_save_findings_skips_low_crm_and_duplicates` (written/dropped counts, second call writes 0; Review Focus 2); `test_snapshot_caps_at_twenty_notes_and_4000_characters_dropping_the_longest` (Review Focus 3); `test_snapshot_with_no_notes_is_empty`; `test_add_note_creates_a_note_interaction_on_the_contact_and_company_timeline`; `test_adopt_saves_legacy_findings_once`; `test_card_marks_used_notes_and_counts_newer_ones`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_notes.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `notes.py` to the interfaces. Parse with `SOURCE_LINE = re.compile(r"^Source: (\S+) \((company|person|trigger), ([0-9-]*), (high|medium)\)\s*$")` on the last line only. Match snapshot to notes by `" ".join(text.split()).lower()`. Import `outreach` at module top; `outreach.py` imports `notes` lazily inside functions (as `store.py` does with `outreach`).
- [ ] **Step 4: Run** the tests again. Expected: PASS.
- [ ] **Step 5: Commit** `ai: notes: the note format, the snapshot and the card rows for outreach`.

### Task 3: The pipeline reads and writes notes

**Files:**
- Modify: `src/hermitcrm/outreach.py` (`build` ~2512, `redraft` ~2953, `mark_ready` ~2707, `add_page` ~3060, `set_findings` ~3022 removed, `make_brief` ~606)
- Test: `tests/test_outreach_draft.py:277`, `tests/test_outreach_page.py:170-305`, `tests/test_outreach_web.py:290-325`, `tests/test_outreach_aiweb.py`, new `tests/test_outreach_notes.py`

**Interfaces:**
- Consumes: everything from Task 2.
- Produces: `outreach.add_note(store, item_id, text) -> Item`-free helper is not needed; the web layer calls `notes.add_note` directly. `make_brief(..., notes_background: bool = False)`.

- [ ] **Step 1: Write failing tests** in `tests/test_outreach_notes.py` using `outreach_fakes`: `test_build_saves_research_findings_as_notes_in_the_research_commit` (medium/high findings become notes, the research commit message is unchanged, `item.findings` equals the snapshot, no `crm` finding in it); `test_low_confidence_findings_are_dropped_and_counted_in_a_flag`; `test_a_note_on_the_contact_reaches_the_draft_prompt_numbered_and_citable`; `test_company_notes_field_goes_to_the_prompt_as_background_only`; `test_reply_and_follow_up_get_notes_as_background_not_findings` (`item.findings == []`, notes text in the prompt); `test_redraft_rebuilds_the_snapshot_from_current_notes` (add a note after the draft, regenerate, it is in the new prompt and `item.findings`); `test_mark_ready_writes_no_summary_note`; `test_old_item_with_findings_adopts_them_on_regenerate_and_mark_ready` (hand-write an item file with a `crm` finding and no `language_pick`; Review Focus 4); `test_ai_web_prompt_never_contains_note_text` (a note with distinctive text exists, `FakeAI` research prompt for level `ai-web` lacks it); `test_add_page_saves_findings_as_notes`.
- [ ] **Step 2: Update** the existing tests that assert the old behavior to the new one: `test_outreach_draft.py:277` expects `[True]` (no `crm` line); the `/findings` route tests in `test_outreach_page.py` and `test_outreach_web.py` move to Task 4. Run `.venv/bin/pytest tests/test_outreach_notes.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** In `build`: replace the research step's `item.findings = research.findings` with, inside `with store.batch(message)` (instead of `store.lock`): `notes.save_findings(...)`, flag the dropped count in `item.flags`, then `item.findings = notes.snapshot(store.get(slug), contact.slug, store.today())` and `research.findings = item.findings`; threaded kinds keep `[]`. In `redraft`: call `notes.adopt`, rebuild the snapshot the same way before `_item_brief` (threaded kinds keep `[]`). In `mark_ready`: call `notes.adopt` inside the batch and delete the "Outreach research for…" note block. `add_page`: pass the kept findings to `notes.save_findings`; return `(item, written)`; no item write. `make_brief`: add `notes_background` (true for reply and follow-up from `build` and `_item_brief`); it always adds a `Company notes: …` situation line (first 600 characters of `company.notes`) and, when `notes_background`, the 5 newest note first lines. Delete `set_findings` and its helpers.
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_outreach_notes.py tests/test_outreach_draft.py tests/test_outreach_aiweb.py tests/test_outreach_followups.py tests/test_outreach_select.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `ai: outreach: research writes notes and the draft reads them`.

### Task 4: The Notes panel on the card

**Files:**
- Modify: `src/hermitcrm/web.py` (`outreach_card` ~4070, `OUTREACH_ACTIONS` ~4545, `outreach_action` ~4547 and its `findings` branch ~4640, `outreach_page` context ~4240), `templates/outreach.html:237-294`, `static/style.css`
- Test: `tests/test_outreach_page.py`, `tests/test_outreach_web.py`

**Interfaces:**
- Consumes: `notes.card`, `notes.add_note`.
- Produces: POST `/outreach/{item_id}/note` with form field `add`; the card dict gains `notes` (the `notes.card` result).

- [ ] **Step 1: Write failing tests**: `test_card_lists_the_contacts_notes_and_no_findings_panel` (no "Save findings", no `name="remove"`, the notes text and a link to `/companies/<c>/contacts/<k>#i-<id>`); `test_adding_a_note_on_the_card_shows_on_the_contact_and_company_pages` (POST `/outreach/<id>/note` with `add`, then both pages contain it); `test_a_note_written_on_the_contact_page_shows_on_the_card_with_a_regenerate_hint` ("1 note added since this draft was written"); `test_the_card_shows_company_notes_read_only`; `test_an_old_card_lists_unsaved_findings_read_only`; replace the old `/findings` route tests with the above and delete them.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_outreach_page.py tests/test_outreach_web.py -q`. Expected: new tests FAIL.
- [ ] **Step 3: Implement** the panel in `outreach.html` (summary "Notes (N)", used marker, origin as "you" or the source link, add box only when `i.state == 'drafted'`, the Norms-applied block stays inside it, `has_notes` keeps the old `has_findings` condition); the `note` action in `outreach_action` (text "Note saved. Regenerate to use it."); remove the `findings` action, `finding_kinds` from the context and the `kind` form field.
- [ ] **Step 4: Run** the two files. Expected: PASS.
- [ ] **Step 5: Commit** `ai: outreach: the Findings panel is a Notes panel`.

### Task 5: Language pick, signal and observation, and the `?contact=` panel

**Files:**
- Modify: `src/hermitcrm/outreach.py` (`Item` + `ITEM_KEYS` gain `language_pick`; `build(..., language: str = "")`; `AIDrafter.draft/context/_learned` take the override; `make_brief(..., language="")`; `redraft` and `_item_brief` pass `item.language_pick`), `src/hermitcrm/web.py` (`outreach_page`, `outreach_build`, new `POST /outreach/note`), `templates/outreach.html` (panel above the tabs), `static/style.css`
- Test: `tests/test_outreach_generate.py`

**Interfaces:**
- Consumes: `notes.add_note`, `messaging.SIGNALS`, `messaging.language_names`, `messaging.draft_language(company, contact, override, messages)`, `outreach.kind_for`.
- Produces: GET `/outreach?contact=<company>/<contact>` renders `<section id="generate">`; POST `/outreach/build` accepts `signal`, `observation`, `language`; POST `/outreach/note` takes `contact`, `text`, `back`.

- [ ] **Step 1: Write failing tests**: `test_contact_param_renders_the_panel_and_writes_nothing` (no new commits, no AI calls); `test_malformed_or_unknown_contact_param_renders_no_panel` (Review Focus 5); `test_panel_preselects_kind_channel_language_and_lists_notes`; `test_build_with_observation_and_signal_saves_notes_first`; `test_language_pick_applies_to_the_draft_and_its_regenerate` (Dutch contact, German picked: prompt says German twice, record language unchanged); `test_old_item_file_without_language_pick_loads`; `test_panel_add_note_posts_and_returns_to_the_panel`; `test_generate_is_disabled_with_the_ai_problem_shown`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_outreach_generate.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** `language_pick` as an optional `Item` key stored only when non-empty. Valid language codes come from `messaging.language_names(app.state.messages)`; an invalid `language` or `signal` is ignored. The build route writes the observation note and the signal note (`Signal (LinkedIn insights, checked <YYYY-MM-DD>): <signal>.`) only after the selection and AI checks pass, then calls `outreach.build(..., language=...)`. The panel posts to `/outreach/build` with `contact` and `back=/outreach?contact=...`; its Generate button uses `data-busy`; links to the company's LinkedIn insights and website as the old box had.
- [ ] **Step 4: Run** the file plus `tests/test_outreach_notes.py`. Expected: PASS.
- [ ] **Step 5: Commit** `ai: outreach: a Generate panel per contact, with signal, observation and language`.

### Task 6: Drafts box out, Generate button in

**Files:**
- Modify: `templates/contact.html:46-57,122-127`, `templates/company.html:113`, `templates/macros.html:60-94` (macro removed), `src/hermitcrm/web.py` (`draft_context` and its four call sites; `contact_context` keeps `outreach_open`, drops `outreach_channels`/`outreach_kind`), `src/hermitcrm/layout.py` (`SECTIONS` loses `drafts`; a retired-name set is accepted silently), `static/style.css` (drafts-form rules), the "message drafts" starter text wherever it lives
- Test: `tests/test_contact_page.py:201`, `tests/test_draft_language.py`, `tests/test_web.py:1725,1814,2471`, `tests/test_layout.py:49,142,278`

**Interfaces:**
- Consumes: Task 5's `/outreach?contact=`.

- [ ] **Step 1: Write failing tests**: `test_contact_page_has_generate_outreach_link_and_no_drafts_box` (link `href="/outreach?contact=acme/jane-doe#generate"`, no `id="drafts"`); `test_open_item_turns_the_button_into_open_outreach_draft`; `test_company_page_links_generate_for_its_contact`; `test_layout_toml_naming_drafts_still_loads_without_a_problem` (Review Focus: a retired section; `layout.parse` returns no problem); `test_drafts_is_not_a_section_any_more`.
- [ ] **Step 2: Update the old tests** that assert the box: `test_contact_page.py:201` becomes the open-item/Generate test; `test_draft_language.py` keeps its language cases but asserts them on the Outreach panel's preselected language (`/outreach?contact=…`); `test_web.py` section lists lose `drafts`; `test_layout.py` expectations drop `drafts` (keep one case that lists it and expects it ignored). Run `.venv/bin/pytest tests/test_contact_page.py tests/test_draft_language.py tests/test_layout.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the removals and the button. The contact action row gets `<a class="button" href="/outreach?contact=<co>/<ct>#generate">Generate outreach</a>`, or `Open outreach draft` linking to the card when `outreach_open`; the old "Outreach: … Review it on Outreach" line and the Research & draft form go. `messaging.py` is untouched (`adjust.py` still uses `drafts()`).
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_contact_page.py tests/test_draft_language.py tests/test_layout.py tests/test_web.py tests/test_messaging.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `ai: contact: Generate outreach replaces the Message drafts box`.

### Task 7: Docs, full suite, browser check

**Files:**
- Modify: `docs/ARCHITECTURE.md` (§8 contact route row, §8.3 rewritten as "Message drafts removed; see Outreach"), `src/hermitcrm/help/contacts.md`, `help/companies.md`, `help/adjust-layout.md`, `help/outreach.md` (notes, Generate panel), `help/changelog.md`, `README.md:186`, `tests/test_help.py` only if a help link breaks

- [ ] **Step 1: Edit the docs** to match the spec (Notes replace Findings, `?contact=` panel, copy buttons, `drafts` retired from layout).
- [ ] **Step 2: Run the full suite** in the background: `.venv/bin/pytest -q`. Expected: all pass (baseline was 2826 passed, 2 skipped; new tests add to it).
- [ ] **Step 3: Browser check** on a demo folder (`.venv/bin/hermitcrm init /tmp/x --demo`, run the app): click both copy buttons and read the clipboard, open the contact page, click Generate outreach, see the panel, add a note, check it on the contact page and company page, no console errors.
- [ ] **Step 4: Commit** `ai: docs: Outreach notes, the Generate panel and copy buttons`.
