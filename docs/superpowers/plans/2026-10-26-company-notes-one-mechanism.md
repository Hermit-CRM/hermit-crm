# Company notes: one mechanism (plan)

Status: Implemented in format 19; see changelog. Written 2026-10-26.

## Decision

A company has two places for free text: the `notes` body of `company.md` (one
blob, edited in the Details form) and company-level notes (note interactions
with no contact, added 2026-10-25 in `d500222`). They overlap. Contacts already
went through this: migration 7 turned the contact body into note interactions,
`Store.create_contact` / `update_contact` route `notes` into a note, and
`hermitcrm check` warns about a leftover body. Companies get the same treatment.
After this work a company's free text lives only as dated company notes.

Not in scope: a "pinned" or evergreen note (the one thing the blob did better).
Add it later as a flag on a note if it is missed.

## Template to copy (read these, do not re-derive)

| What | Where |
|---|---|
| Body to notes migration, hand-dated lines split into dated notes | `migrations.py`: `_split_notes`, `m7_contact_notes`, `Migration(7, ...)` (contacts; their lines are `dd/mm/yyyy:`); for companies `m19_company_notes`, `_split_company_notes`, `_opening_date` (`dd-mm-yyyy`, `dd/mm/yyyy`, `dd.mm.yyyy` or ISO lines, and `Imported fields (yyyy-mm-dd):`) |
| `notes` argument becomes a note, never rewrites a body | `store.py`: `create_contact` (comment "A contact has no notes body any more"), `update_contact` (`note = normalise_body(fields.get("notes"))`) |
| Leftover body warning | `cli.py` `check`: the `stray` list |
| Company-level note reading | `notes.py`: `company_notes`, `notes_for`, `elsewhere` |

The latest migration was 18; the new one is **19**.

## The contract (what every workstream can rely on)

1. `Store.create_company(..., notes=text)` writes the company with an empty body,
   then one company-level note interaction (`channel=note`, `contact=""`,
   `date=now`) in the same commit. Same for the new-company form.
2. `Store.update_company(..., notes=text)` adds a company-level note and never
   rewrites the body. `Company.notes` stays on the model as the **legacy** body
   (read-only in practice; empty after migration 19).
3. Migration 19 (`companies/*/company.md`) moves the body into note interactions
   (`source: migration`, `contact: ""`), dated by `_split_company_notes` (a line starting with a date opens a note on that
   day; the text before the first one takes the company's `created`, else `updated`;
   the time of day is not kept), and
   leaves the front matter byte for byte. Idempotent: a second run finds no body.
4. No call site writes `company.notes` any more. Writers call `create_company` /
   `update_company` with `notes=`, or `create_interaction(slug, "note", "", body=...)`.
5. Company notes are findings for drafts exactly like contact notes (they already
   are, through `notes.notes_for`). The separate "background only" path for the
   field goes away. (Decided: decision 2.)

## Workstreams

```
WS0 foundation (serial, first)
  └─ then in parallel, each in its own worktree:
       WS1 web UI          WS2 non-UI writers        WS3 readers         WS4 docs
  └─ then WS5 verification (serial, last)
```

Why this split: after WS0 the four parallel streams touch disjoint files
(except small, separate hunks of `web.py`), so they need no coordination and no
shared context. WS0 is the only one that needs deep context, so it is the only
one that gets the long brief.

### WS0 Foundation: migration + store (serial, first) (done)

Files: `migrations.py`, `store.py`, `models.py` (docstring only), `cli.py`
(`check` warning), tests.

1. `m19_company_notes`: generalise the m7 mechanics (split, unique interaction
   ids, front matter untouched). Register `Migration(19, "company notes become note
   interactions", "companies/*/company.md", ...)`. Dry run output like m7's.
2. `create_company` and `update_company` per contract 1 and 2. In
   `update_company`, `notes` in `fields` adds a note instead of
   `new.notes = ...` (line anchor: `if "notes" in fields:` in `store.py`).
3. `check`: warn `companies/<slug>/company.md: has a notes body; ...` next to the
   contact one. Warning, not an error.
4. Merge: `_merge_value`'s `notes`/`both` branch stays (a legacy body can still
   exist); interactions already move with the merge.

Tests (targeted): `tests/test_migrations.py` (dated lines, undated tail, empty
body, idempotent second run, collision of ids, front matter byte for byte),
`tests/test_store.py` (create with notes, update with notes, body untouched),
`tests/test_models.py` if it asserts on `Company.notes`.
Done when: `pytest tests/test_migrations.py tests/test_store.py -q` passes and a
demo folder (`hermitcrm init /tmp/x --demo`, then a hand-edited body, then
`hermitcrm migrate`) shows the notes as company notes. Full `pytest` once at the end.

### WS1 Web UI (parallel after WS0) (done)

Files: `templates/macros.html` (the `notes` textarea, line ~243),
`templates/company_new.html`, `templates/company.html` (Company notes section,
help copy), `web.py` (`company_new`, `company_create`, `company_update`,
`merge_rows` `"both"` for notes, `company_notes_context`), `layout.py`.

1. Details (edit) form: no notes textarea. The Company notes section below the
   contacts is the one place; link to it from where the textarea was.
2. New-company form: keep one box, relabelled **first note**; it creates a
   company note (contract 1). Remove `notes` from the edit POST handler.
3. Merge page: show the notes row only when either side still has a legacy body.
4. **`layout.py` `FIELDS["company"]` lists `"notes"`.** A user's config may hide it
   (record page layout). Keep the key accepted and ignored so an existing config does
   not start failing; add a test with `notes` in a hidden list.

Tests: `tests/test_company_form.py`, `tests/test_web.py`, `tests/test_settings_commit.py`
(already modified in the working tree by the date work; expect a merge there).

### WS2 Non-UI writers (parallel after WS0) (done)

Files: `importer.py`, `bcc.py`, `mcp.py`, `capture.py`, `datafolder.py`
(`SAMPLE_NOTES`), `bulk.py` (`_BODY_NAMES`).

1. Importer: company `notes_text` and the `Imported fields (<stamp>):` block
   become a company note via the store (`update_company(notes=...)` after WS0).
   The "line already present" check (`existing.notes`, line ~652) compares against
   existing company notes' text instead of the body; keep the contact path as is.
2. BCC: stop writing "Created by the BCC import from a mail ..." as a note. The
   logged interaction is the record, and as a note it would reach drafts as a
   finding. Update `tests/test_bcc.py`.
3. MCP: `add_company` / `update_company` `notes` description says "Logged as a
   note on the company" (as `add_contact` already does).
4. Sample data: `SAMPLE_NOTES` becomes a company note (the demo folder must still
   read well).
5. `capture.py` passes `proposal.notes` (what the scraper saw) to a form, not to
   the record: check, change nothing unless it reaches `create_company`.

Tests: `tests/test_importer.py`, `tests/test_bcc.py`, `tests/test_sample.py`,
`tests/test_bulk.py`, the MCP test file.

### WS3 Readers (parallel after WS0) (done)

Files: `brief.py`, `outreach.py` (~line 799), `notes.py` (`card`), 
`templates/outreach.html` (~line 336), `web.py` (the `"company_notes": ""`
default near the card), `messaging.py`, `export.py`, `cli.py` (`show`).

1. `brief.py`: the "Notes:" line shows the newest company note's first line (and a
   count when more) instead of the body's first line. Today a body that starts with
   a hand-typed date shows only the date.
2. `outreach.py`: remove the `"Company notes: ..."` situation line. Company notes
   already reach the draft as findings via `notes.notes_for`; keeping both would
   cite them twice.
3. `notes.card` / `outreach.html`: drop the separate `company_notes` paragraph;
   company notes already appear in the Notes list with origin "company".
4. `messaging.py` language evidence: read the text of company notes, not
   `company.notes`.
5. `export.py`: keep the `notes` column in the company CSV/JSON (the importer reads
   that header back), now filled with the company notes' text, oldest first. Check
   `tests/test_export*`.
6. `cli show`: nothing to add (the timeline lists notes); remove the body print only
   if it becomes dead.

Tests: `tests/test_outreach_notes.py`, `tests/test_outreach_page.py`,
`tests/test_messaging.py`, `tests/test_outreach_draft.py`, export tests.

### WS4 Docs (parallel after WS0; cheapest model) (done)

Files: `docs/ARCHITECTURE.md` (find with `grep -n` on "Body: free Markdown notes",
"notes body", `hermitcrm show`, `hermitcrm check`, the `/companies/new` row, the
bcc and import paragraphs; the file has very long lines, never read it whole),
`src/hermitcrm/help/companies.md`, `help/interactions.md`, `help/import.md` (if it
mentions notes), `help/changelog.md` (user-facing: the field is gone, existing
text became dated company notes, drafts may now cite company notes), and a
one-line "superseded" note on lines ~151 and ~247 of
`docs/superpowers/specs/2026-10-20-outreach-notes-and-drafts-design.md`.
Describe the **contract**, not the code, so this does not wait for WS1 to WS3.

### WS5 Verification (serial, last)

1. Full `.venv/bin/pytest` on the integration branch.
2. Demo folder: `init /tmp/x --demo`, put a body with hand-dated lines into one
   company, migrate, then in the browser (preview): company page, a contact page
   ("Notes elsewhere"), new-company form, Outreach card, the brief, `hermitcrm check`.
3. Idempotence: run the migration twice, `git status` clean after the second.
4. Deploy is a separate, user-gated step: back up the data folder, reinstall the
   uv-tool copy, kickstart launchd (see the live-server memory). The migration
   runs on the real folder at that point.

## Token efficiency rules for the sessions

- Fresh sessions with a short brief (this file's section for that workstream plus
  the contract), never forks of this conversation.
- The anchors above come from a `grep` on 2026-10-26; sessions verify with one
  `grep -n` and do not re-explore the repo.
- Cheaper models for WS2 and WS4 (mechanical), default for WS0, WS1, WS3.
- Targeted `pytest <file> -q` while working; the full suite once per branch before
  the commit (required by CLAUDE.md), and once more in WS5.
- Never read `docs/ARCHITECTURE.md` or `web.py` whole; `grep -n` and read ranges.

## Risks

- **Date-format work is uncommitted** in the main checkout (branch
  `ai/date-format-setting`) and edits the same files (`store.py`, `models.py`,
  `web.py`, `company.html`, `macros.html`, `help/changelog.md`). New worktrees do
  not see it; merging later conflicts in those files. (Decision 1: landed first; the date-format work is on main.)
- **Behaviour change for drafts**: what used to be uncited background becomes a
  citable finding. The snapshot keeps 20 notes and 4,000 characters, longest
  dropped first, so a long migrated blob may be dropped silently. (Decided: decision 2, citable.)
- **`updated` timestamp**: the migration rewrites `company.md`; it should not touch
  `updated` (front matter byte for byte), or reports sorted by it move.
- **Layout config** may hide `notes` (WS1 item 4).
- **Export round trip** of the `notes` column (WS3 item 5).

## Decisions (answered 2026-10-26)

1. Sequencing: land the date-format work first (commit and merge it), then branch
   from main. WS0 does not start before that.
2. Company notes are citable in drafts, like every other note.
3. PR shape: the work is on `claude/company-notes-335027` (WS0 to WS4); one final PR
   to main comes later, when the user says so.
