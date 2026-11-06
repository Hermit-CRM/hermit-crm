# Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Files can be attached to notes and interactions (drag and drop, paste, file picker), arrive with BCC'd mail, and go out with approved outreach email, all as plain files in the data folder under git.

**Architecture:** One mechanism, as with company notes (see `2026-10-26-company-notes-one-mechanism.md`): the only owner of an attachment is an *interaction* (a note is an interaction) or an *outreach item* (before it is sent). A company or contact "Files" view is derived from its interactions; dropping a file on a company page creates a note. Files are stored content-addressed in `companies/<slug>/attachments/`, referenced from front matter by stored name, so renaming or re-dating an interaction never breaks a link.

**Tech Stack:** Python stdlib (`hashlib`, `mimetypes`, `email`), FastAPI/Starlette multipart (already a dependency), vanilla JS (`static/attach.js`). No new dependency.

**Spec:** none written; the Decisions section below is the design. The request was "make a plan"; the calls marked *(my call)* are assumptions to correct before building.

## Global Constraints

- `.venv/bin/pytest` passes before every commit; commit messages start with `ai:`.
- No new runtime dependencies. No JS framework, no build step.
- Every file write is deterministic: fixed front-matter key order, the same attachments give the same bytes; interaction bodies stay byte for byte.
- A new front-matter key needs a numbered migration in `migrations.py` (idempotent, front matter only) plus tests. Latest is 19, so this plan adds **20** (interactions, phase 1) and **21** (outreach items, phase 3).
- Tests and demo data use fictional names and `example.com` / `example.org` only. Fixture files are generated in code, never real documents.
- New files carry the Apache header the other modules have.
- The web app binds to 127.0.0.1; every POST goes through the existing host allowlist, cross-site check and `check_csrf`. Anything that serves uploaded bytes must survive `CSP` in `web.py`.
- Anything done in the app can also be done by editing a file and committing: a hand-placed file plus a front-matter line must work, and `hermitcrm check` must understand it.
- Work on a new branch from `main` (`ai/attachments`), not on `ai/companies-table`. One PR per phase.

## Review Focus

Most likely to bite, most likely first. Each has its test in the owning task.

1. A hostile filename (`../../.git/config`, `a\x00.pdf`, `CON`, 300 characters, only dots, composed vs decomposed accents) must stay inside the attachments folder (Task 1).
2. An uploaded `.svg` / `.html` with a script must never render inline in the app's origin; it downloads (Task 2).
3. An upload over the cap writes nothing: no partial file, no half note, no commit (Task 3).
4. A file shared by two notes, or by a sent interaction and a still-queued outreach item, is deleted only with its last reference (Task 1, Task 8).
5. An SMTP `552 message too large` must fail that one item, not pause all sending, which is what `_by_code` would do today (Task 8).

## Decisions *(my call unless said otherwise)*

| Topic | Decision | Why |
|---|---|---|
| Where files live | `companies/<slug>/attachments/<sha256[:12]>-<safe-name>` | Survives interaction renames (an id changes with date, channel, contact); same content is stored once; merging companies cannot collide; the hash prefix is a free integrity check. |
| Reference | Optional interaction key `attachments:`, a list of flow maps `{file, name, size, type}`, after `message_id`, omitted when empty | Same style as `stage_history` and outreach `edits`. `name` is what the person called it; `file` is the stored name; `type` comes from the extension, never from the upload. |
| Owners | Interactions and outreach items only | No new key on `company.md` / contacts, so no second mechanism and nothing to migrate for them. |
| Size | `attachment_max_mb = 25` (config, 1 to 90) | GitHub refuses files over 100 MB, and `guard.py` forbids history rewrites, so a mistaken 300 MB commit lives forever. |
| Removal | Removing a reference deletes the file from the tree when unreferenced; git history keeps it | Said plainly in the UI and help page. |
| Git LFS | Not used | Would add a dependency and setup step. |
| Serving | Allow-list inline (`png jpg jpeg gif webp pdf txt`); everything else `Content-Disposition: attachment`; always `nosniff` | A local app on one origin: an inline `.html` or `.svg` would run with the app's cookies and CSRF token reachable. |
| MCP | Read-only (list, read text). No tool that adds a file from a path | A prompt-injected agent could attach `~/.ssh/id_rsa` and the sync would push it. CLI `attach` is typed by the person. |
| Calendar ICS `ATTACH` | Not downloaded | It is a URL; fetching arbitrary URLs from an imported feed is an SSRF and privacy risk. |
| Extracted text | Not stored | "Nothing derived is stored." Read on demand with `textsource.read_file`. |

## File Structure

| File | Responsibility |
|---|---|
| `src/hermitcrm/attachments.py` (new) | `Attachment`, `Incoming`, name sanitising, media types, front-matter (de)serialisation, hash check. No store import. |
| `store.py` | Write, reference-count, move and delete files with the interaction that owns them. |
| `models.py` | `Interaction.attachments`, `INTERACTION_KEYS`, `interaction_to_dict` / `interaction_from_dict`. |
| `web.py`, `templates/macros.html`, `interaction_*.html`, `company.html`, `contact.html`, `static/attach.js`, `static/style.css` | Upload, serve, drop zone, chips, Files section. |
| `bcc.py` | Pull attachments out of mail; carry them through the inbox. |
| `outreach.py`, `send.py`, `sendqueue.py` | Attach to an item; build the multipart mail; guards. |
| `cli.py`, `mcp.py`, `export.py`, `doctor.py`, `datafolder.py`, `help/*.md`, `docs/ARCHITECTURE.md` | Command line, agent reads, export, checks, demo data, docs. |
| `tests/test_attachments.py`, `test_attachments_web.py`, `test_bcc_attachments.py`, `test_send_attachments.py` (new) | Per task below. |

---

## Phase 1: attach to notes and interactions

### Task 1: The attachment module and the store

**Files:**
- Create: `src/hermitcrm/attachments.py`, `tests/test_attachments.py`
- Modify: `src/hermitcrm/models.py` (`Interaction`, `INTERACTION_KEYS`, lines ~396, ~985, ~1001, ~1187), `src/hermitcrm/store.py` (`create_interaction`, `update_interaction`, `delete_interaction`, `merge_companies`, `load_config` defaults), `src/hermitcrm/migrations.py` (migration 20)

**Interfaces:**
- Produces, in `attachments.py`:
  - `@dataclass(frozen=True) class Attachment: file: str; name: str; size: int; type: str`
  - `@dataclass class Incoming: name: str; data: bytes`
  - `safe_name(name: str) -> str`: NFC-normalised, no path parts, no control characters, no leading dots, at most 100 characters keeping the extension, `"file"` when nothing is left
  - `media_type(name: str) -> str` (extension table with `mimetypes` fallback, `application/octet-stream` last)
  - `stored_name(data: bytes, name: str) -> str` (`<sha256 hex[:12]>-<safe_name>`)
  - `INLINE_TYPES: frozenset[str]`, `disposition(att: Attachment) -> str` (`"inline"` or `"attachment"`)
  - `from_meta(raw) -> list[Attachment]` (lenient; skips malformed entries), `to_meta(items) -> list[dict]` (key order `file, name, size, type`)
  - `intact(path: Path) -> bool` (hash prefix of the content equals the prefix in the file name)
- Produces, in `Store`:
  - `attachment_path(company_slug, file) -> Path` (through `contained`)
  - `add_files(company_slug, incoming: Sequence[Incoming]) -> list[Attachment]` (writes, records with `_touch`, raises `ValidationError({"files": ...}) ` over `attachment_max_mb`, writes nothing on any failure)
  - `referenced_files(company_slug) -> dict[str, int]` (counts from interactions and from outreach items of that company)
  - `create_interaction(..., attachments: Sequence[Incoming | Attachment] = ())`
  - `update_interaction(company_slug, id, ..., add_files: Sequence[Incoming] = (), remove_files: Sequence[str] = ())`
- Commit subjects: unchanged for create (append `; 2 files`), `interaction: <slug> <id> files added|removed` for update-only changes.

- [ ] **Step 1: Write the failing tests** in `tests/test_attachments.py`:
  - `test_safe_name_stays_inside`: parametrised over `"../../.git/config"`, `"a\x00.pdf"`, `"CON"`, `"." * 5`, `"x" * 300 + ".pdf"`, `"/etc/passwd"`; asserts `"/" not in n`, `"\\" not in n`, `"\x00" not in n`, `len(n) <= 100`, not starting with `.`, and that the long one still ends in `.pdf`.
  - `test_safe_name_composed_and_decomposed_agree`: `"é.pdf"` in NFC and NFD give the same result.
  - `test_stored_name_is_content_addressed`: same bytes and name give the same stored name; different bytes give a different one; `intact()` is true for a written file and false after one byte is changed.
  - `test_media_type_ignores_the_client`: `media_type("x.svg") == "image/svg+xml"`, `disposition` of it is `"attachment"`; `.png` is `"inline"`.
  - `test_create_interaction_with_files_round_trips`: file exists at `companies/<slug>/attachments/<stored>`, the interaction file has `attachments:` after `message_id`, reloading the store gives equal `Attachment`s, writing twice gives identical bytes.
  - `test_no_attachments_key_when_empty`: an interaction without files has no `attachments` line (existing files stay byte-identical).
  - `test_too_big_writes_nothing`: with `attachment_max_mb = 1` and a 2 MB `Incoming`, `ValidationError` is raised, no `attachments/` entry, no interaction file, `store.take_touched()` is empty.
  - `test_shared_file_removed_with_last_reference`: two notes carry the same bytes; deleting one keeps the file; deleting the second removes it.
  - `test_same_name_different_bytes_are_two_files`.
  - `test_rekeying_the_interaction_keeps_files`: `update_interaction(date=...)` changes the id, `attachments` and the file are untouched.
  - `test_merge_companies_moves_files`: after `merge_companies(keep, drop)` the files are in `keep`'s folder, references still resolve, `drop`'s folder is gone.
  - `test_migration_20_is_a_noop_and_idempotent`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_attachments.py -q`. Expected: FAIL, `ModuleNotFoundError: hermitcrm.attachments`.
- [ ] **Step 3: Implement** `attachments.py` per the interfaces above. `safe_name` also drops Windows-reserved device names by prefixing `_`.
- [ ] **Step 4: Implement** the model key (`Interaction.attachments: list[Attachment] = field(default_factory=list)`, copied in `INTERACTION_COPY_FIELDS`) and the store methods. `add_files` hashes once, skips the write when the stored name already exists and `intact()`, and writes via temp file plus `os.replace` like `ask_state`. `delete_interaction` and `update_interaction(remove_files=...)` delete a file only when `referenced_files` drops to zero. `merge_companies` moves `attachments/*` before it removes the drop folder (identical stored names are the same content, so skip). `attachment_max_mb` default 25 goes next to the other defaults in `DEFAULT_CONFIG`.
- [ ] **Step 5: Add** `Migration(20, "interactions may have attachments (nothing to change in a file)", "companies/*/interactions/*.md", _noop)`, the way migration 13 was done, and extend `tests/test_migrations.py` for the latest-version assertion.
- [ ] **Step 6: Run** `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 7: Commit** `ai: attachments: content-addressed files owned by interactions`.

### Task 2: Serving files safely

**Files:**
- Modify: `src/hermitcrm/web.py` (new route near the interaction routes ~line 3118)
- Test: `tests/test_attachments_web.py` (copy the client setup from `tests/test_contact_page.py`)

**Interfaces:**
- Consumes: `Store.attachment_path`, `attachments.disposition`, `attachments.media_type`.
- Produces: `GET /companies/{slug}/attachments/{file}` (`?download=1` forces `attachment`).

- [ ] **Step 1: Write the failing tests:**
  - `test_png_is_inline_with_nosniff`: `Content-Disposition` starts with `inline`, `X-Content-Type-Options: nosniff`, `Content-Type: image/png`.
  - `test_script_in_svg_and_html_downloads`: an attached `evil.svg` and `evil.html` containing `<script>` come back with `Content-Disposition: attachment; filename="evil.svg"` and never `inline`; response header `Content-Security-Policy` includes `sandbox`.
  - `test_filename_header_is_escaped`: a name with `"` and newline characters cannot inject a header (the response still has exactly one `Content-Disposition`); the `filename*=UTF-8''...` form carries non-ASCII.
  - `test_traversal_is_404`: `/companies/acme/attachments/..%2f..%2fcompany.md` is 404; so is a reference to a missing file; so is a file that exists on disk but no interaction references (serve only what is referenced).
  - `test_unknown_company_404`.
- [ ] **Step 2: Run** the file. Expected: FAIL (404 for everything, route missing).
- [ ] **Step 3: Implement** the route with `FileResponse`. Content type from `media_type`, never from a stored header. Add `sandbox` to the response CSP for every attachment response (the global middleware uses `setdefault`, so set the header explicitly).
- [ ] **Step 4: Run** the file, then the full suite. Expected: pass.
- [ ] **Step 5: Commit** `ai: attachments: serve files inline only when harmless`.

### Task 3: Attach from the forms (picker, drag and drop, paste)

**Files:**
- Create: `src/hermitcrm/static/attach.js`
- Modify: `src/hermitcrm/web.py` (`interaction_create` ~3118, the edit route, new add/remove routes, an upload helper), `templates/macros.html` (`interaction_form` line 104, `timeline`), `templates/interaction_new.html`, `templates/interaction_edit.html`, `templates/base.html` (script tag), `static/style.css`
- Test: `tests/test_attachments_web.py`

**Interfaces:**
- Consumes: Task 1 store methods, Task 2 route.
- Produces:
  - `async def read_uploads(files: list[UploadFile], limit: int) -> list[Incoming]` in `web.py`: reads in 1 MB chunks, stops at `limit` bytes with a `ValidationError`, ignores empty file inputs (a browser sends an empty part when nothing is chosen).
  - Form field `files` (multiple) on `POST /companies/{slug}/interactions` and `POST /companies/{slug}/interactions/{id}/edit`.
  - `POST /companies/{slug}/interactions/{id}/attachments` (field `files`, `csrf_token`; answers JSON `{ok, attachments}` for `fetch`, else redirects back).
  - `POST /companies/{slug}/interactions/{id}/attachments/{file}/delete`.
  - `static/attach.js`: for a `form[data-attach]`, makes the textarea and a labelled drop area accept dropped files and pasted images, merges them into the form's file input through `DataTransfer`, lists them as chips with a remove button, and shows the size cap. With JavaScript off the plain file input still works.
  - A timeline entry that has files renders chips (name, size, paperclip icon, thumbnail for images) linking to the Task 2 route.
  - An existing timeline entry accepts a drop: `attach.js` posts to the add route and reloads.

- [ ] **Step 1: Write the failing tests:**
  - `test_note_with_a_file_is_one_commit`: multipart POST with a body and one file creates the note, the file and one git commit containing both paths.
  - `test_note_form_still_works_without_files`: the existing url-encoded and empty-file-part posts create a plain note with no `attachments` key.
  - `test_over_cap_upload_writes_nothing`: file larger than `attachment_max_mb` returns 400 with the message above the form, the typed body kept, no file, no interaction, no commit. A 413 is returned before parsing when `Content-Length` exceeds cap plus 1 MB of overhead.
  - `test_upload_needs_the_csrf_token`: a multipart POST without it is 403 and writes nothing; a cross-site `Origin` is refused by the existing middleware.
  - `test_add_and_remove_on_an_existing_note`.
  - `test_edit_page_lists_files_with_remove`.
  - `test_timeline_shows_chip_and_thumbnail_for_png`.
  - `test_attach_js_is_served_and_referenced` (the base template links it; the file exists in package data, `static/*` is already included in `pyproject.toml`).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the routes and `read_uploads`. In `interaction_create` add `files: list[UploadFile] = File(default=[])` next to the `Form` parameters; on `ValidationError` re-render with the same status 400 path that exists. The `<form>` in `interaction_form` gets `enctype="multipart/form-data"` and `data-attach`.
- [ ] **Step 4: Implement** `attach.js` (no dependencies, the header style of `copy.js`). It must not change what the form posts other than the file list, and must work when the clipboard has no files.
- [ ] **Step 5: Verify in a browser** against `.venv/bin/hermitcrm init /tmp/x --demo`: drag a file onto the note box, paste a screenshot, submit, see the chip, open it. Use `preview_start`, check the console for errors, screenshot light and dark.
- [ ] **Step 6: Run** the full suite. Expected: pass.
- [ ] **Step 7: Commit** `ai: attachments: add files to a note by picking, dropping or pasting`.

### Task 4: Files on the company and contact pages

**Files:**
- Modify: `src/hermitcrm/layout.py` (`SECTIONS`), `web.py` (company and contact page context, `POST /companies/{slug}/attachments`, `q` matching in `/companies`), `templates/company.html`, `templates/contact.html`, `templates/macros.html`, `static/attach.js`, `static/style.css`
- Test: `tests/test_attachments_web.py`, `tests/test_layout.py`

**Interfaces:**
- Produces:
  - `attachments.files_of(interactions) -> list[tuple[Attachment, Interaction]]` newest first (a file used by two interactions appears once, with its newest).
  - A **Files (n)** section on company and contact pages (section name `files`, listed by `layout.sections`, hideable in `layout.toml`). The contact page lists the files of that person's interactions.
  - `POST /companies/{slug}/attachments` (fields `files`, `contact` optional, `back`): creates one note, subject = the file names, empty body, with the files. This is what a drop on the page outside any form does.
  - Search: `/companies?q=` also matches attachment names.

- [ ] **Step 1: Write the failing tests:** `test_files_section_lists_each_file_once`; `test_page_drop_creates_a_note_with_the_files` (note channel, contact kept, one commit); `test_search_finds_a_company_by_attachment_name`; in `test_layout.py`, `test_old_layout_toml_still_renders_and_files_is_appended` (a `layout.toml` written before this section existed lists no `files`, and `Layout.sections('company')` still includes it last).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the section, the route and the search clause. `attach.js` gets a page-level `dragenter` overlay on `body[data-drop-company]` that posts to the new route; drops onto a form or a timeline entry keep their own behaviour.
- [ ] **Step 4: Verify in the browser** as in Task 3 (company and contact page, drop on empty space).
- [ ] **Step 5: Run** the full suite. **Step 6: Commit** `ai: attachments: Files section and page-wide drop`.

### Task 5: Checks, config, command line, agent rules

**Files:**
- Modify: `src/hermitcrm/cli.py` (`check`, new `attach` and `attachments` commands), `doctor.py`, `datafolder.py` (`AGENT_RULES`, `render_config`), `migrations.py` (agent-rules migration only if `AGENT_RULES` text changes need one; follow migration 14's pattern)
- Test: `tests/test_cli.py`, `tests/test_doctor.py`, `tests/test_datafolder.py`

**Interfaces:**
- `hermitcrm attach <company> <file>... [--contact SLUG] [--to INTERACTION_ID] [--note TEXT]`: with `--to`, adds to that interaction; otherwise creates a note (text from `--note`, else the file names). Prints the stored names. Refuses a path that is a directory or over the cap.
- `hermitcrm attachments [<company>]`: one line per file (`company | stored name | size | interaction id`).
- `hermitcrm check`: error for a reference whose file is missing; warning for an unreferenced file, a hash mismatch, a file over the cap. Exit code rules as today (warnings do not change it).
- `hermitcrm doctor`: one line, total attachment size, `warn` above 500 MB with the sentence about history that cannot shrink.
- `AGENT_RULES`: "files in `attachments/` are referenced from interactions; never edit or delete them; add one with `hermitcrm attach`."

- [ ] **Step 1: Write the failing tests:** `test_check_reports_missing_attachment_as_error`, `test_check_warns_on_orphan_and_tampered_file`, `test_attach_command_creates_note_and_commit`, `test_attach_refuses_directory_and_oversize`, `test_doctor_warns_over_500mb` (monkeypatch the threshold), `test_agent_rules_mention_attachments`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** **Step 4: Run** the full suite. **Step 5: Commit** `ai: attachments: check, doctor and the attach command`.

### Task 6: Phase 1 docs

**Files:** `docs/ARCHITECTURE.md` (§1 layout, §2 Interaction keys, §3, §4 commit subjects, §8 routes), `src/hermitcrm/help/interactions.md`, `help/data-format.md`, `CHANGELOG.md`.

- [ ] Write each statement from the shipped code (the help pages' rule). Say plainly that removing a file does not shrink git history.
- [ ] `.venv/bin/pytest tests/test_help.py -q` passes. Commit `ai: attachments: docs for phase 1`. Open the PR for phase 1.

---

## Phase 2: inbound mail

### Task 7: Attachments from BCC mail, through the inbox

**Files:**
- Modify: `src/hermitcrm/bcc.py` (`Mail` ~181, `parse_mail` ~256, `Entry` ~414, `entries_for_mail` ~437, `Inbox` ~644, `InboxItem` ~615, `assign`, `discard`, `handle_entry`), `datafolder.py` (`render_config`)
- Test: `tests/test_bcc_attachments.py`

**Interfaces:**
- Produces: `Mail.attachments: list[Incoming]`, `Entry.attachments: list[Incoming]`; config `bcc_attachments = "documents"` (`off` | `documents` | `all`).
  - `documents`: real attachments (disposition `attachment`, or a named part that is not an inline image with a `Content-ID`). Drops signature logos, tracking pixels, `text/calendar`, `message/rfc822`.
  - `all`: also inline images over 20 KB.
  - Per file cap `attachment_max_mb`; files over it are skipped and counted in the run summary (`2 attachments skipped (too large)`), never the whole mail.
  - A part with no filename gets one from its type (`image.png`); two parts with the same name are both kept (stored names differ by hash, or the second is a duplicate and is dropped).
- Inbox item: `attachments:` front matter; bytes at `inbox/attachments/<stored>` (committed with the item; the folder is added to nothing in `.gitignore`). `assign` moves them into the company's folder in the same commit; `discard` deletes those not referenced by another item.

- [ ] **Step 1: Write the failing tests** with mails built by `email.message.EmailMessage` in the test:
  - `test_pdf_attachment_lands_on_the_logged_interaction`
  - `test_signature_logo_and_calendar_part_are_ignored` (inline PNG with Content-ID, `invite.ics`)
  - `test_unnamed_part_gets_a_name_from_its_type`
  - `test_oversize_attachment_skipped_mail_still_logged_and_summary_says_so`
  - `test_zero_byte_attachment_is_ignored`
  - `test_one_mail_to_two_contacts_stores_the_file_once`
  - `test_unmatched_mail_keeps_its_files_in_the_inbox_and_assign_moves_them` (files end up under the company, none left in `inbox/attachments/`, one commit)
  - `test_discard_removes_inbox_files`
  - `test_setting_off_ignores_all_attachments`
  - `test_dedup_by_message_id_does_not_duplicate_files` (second run adds nothing)
  - `test_rfc2231_and_encoded_word_filenames_decode` (`=?utf-8?q?...?=`, `filename*=UTF-8''...`)
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** with `msg.iter_attachments()` for named parts, falling back to walking parts that carry a filename. Never decode HTML or run anything from the payload. Pass `attachments` through `Entry` to `store.create_interaction` and the `Inbox`.
- [ ] **Step 4: Verify** with `hermitcrm bcc --eml <generated .eml> --apply` into `/tmp/x` (demo folder), then open the page.
- [ ] **Step 5: Run** the full suite, update ARCHITECTURE §6 (`bcc`) and `help/settings.md`. **Step 6: Commit** `ai: attachments: keep attachments of BCC'd mail`. Open the PR for phase 2.

---

## Phase 3: outbound

### Task 8: Attach to an outreach draft and send it

**Files:**
- Modify: `src/hermitcrm/outreach.py` (`ITEM_KEYS` ~121, `Item` ~1810, reader/writer ~1948, a new `set_attachments`), `migrations.py` (migration 21), `send.py` (`build_message` 337, `text_hash` 315, `deliver` 874, `_by_code` 299, guards ~789), `sendqueue.py` (hash at Schedule, ~237), `templates/outreach.html`, `web.py` (Outreach routes), `static/attach.js`
- Test: `tests/test_send_attachments.py`, `tests/test_migrations.py`, existing `tests/send_fakes.py` for the fake SMTP

**Interfaces:**
- Produces:
  - `Item.attachments: list[Attachment]`; key `attachments` in `ITEM_KEYS`, written as `[]` when empty (items always write every key).
  - Migration 21 adds `attachments: []` to `outreach/*.md`, anchored the way `m12_send_keys` places its keys; idempotent.
  - `outreach.set_attachments(store, item_id, add: Sequence[Incoming] = (), remove: Sequence[str] = (), reuse: Sequence[str] = ()) -> Item`: email channel only (LinkedIn is refused with an `OutreachError`), only in `drafted` or `ready` (a queued item is unscheduled first, as for text edits), total raw size at most `send_attachment_max_mb` (default 10; base64 makes a mail about 1.37 times larger). `reuse` takes stored names already attached to this company's interactions ("Attach again").
  - Commit `outreach: attachments <company>/<contact> added|removed`.
  - `send.text_hash(subject, body, attachments=())`: with no attachments the result equals today's value, so queued items scheduled before this change are not flagged as edited.
  - `build_message`: when `item.attachments`, `msg.add_attachment(data, maintype, subtype, filename=name)` per file, after `set_content`; no attachments gives byte-identical output to today.
  - `deliver`: before SMTP, every file must exist and be `intact` or the item goes back to `ready` with a `send_note` (the existing guard pattern); the logged interaction gets the same `Attachment` refs (the files are not copied).
  - `send.TOO_LARGE` error kind: `_by_code` maps `552`, and 5xx text matching `size|too large|exceeds`, to it. It fails **that item** with the server's text in `send_error`; it does not pause sending.
  - A soft flag in the item's `flags` (not a hard check): the body says it attaches something (words `attached`, `attachment`, `anbei`, `im Anhang`, `bijgevoegd`, `in bijlage`, `ci-joint`, `pièce jointe`) and the item has no attachment. The card shows it next to Mark ready. A second soft flag when a cold first touch carries an attachment (it hurts deliverability); neither blocks sending.
  - The draft prompt gets attachment *names* only, never their contents.
  - Regenerate keeps the attachments; Unready keeps them; Skip leaves the files for the usual unreferenced rule.

- [ ] **Step 1: Write the failing tests** (`tests/test_send_attachments.py` unless noted):
  - `test_text_hash_unchanged_without_attachments`: equals the literal value from before the change for a fixed subject and body.
  - `test_build_message_has_the_attachment`: `msg.is_multipart()`, one attachment, filename and bytes equal, text part still the approved body byte for byte.
  - `test_build_message_without_attachments_is_byte_identical`.
  - `test_deliver_sends_and_logs_interaction_with_the_same_refs` (fake SMTP records the message).
  - `test_file_removed_after_schedule_puts_item_back_to_ready_with_note`.
  - `test_editing_attachments_after_schedule_changes_the_hash_and_triggers_the_edited_guard`.
  - `test_552_too_large_fails_only_that_item` (the next queued item still sends; `SendState` is not paused).
  - `test_total_over_10mb_refused_when_attaching`.
  - `test_linkedin_item_refuses_attachments`.
  - `test_shared_file_survives_deleting_the_sent_interaction_while_a_queued_item_references_it` (Task 1's `referenced_files` counts items).
  - `test_forgot_attachment_flag_in_four_languages` and `test_no_flag_when_attached`.
  - `test_migration_21_adds_the_empty_key_and_is_idempotent`; `test_item_with_attachments_round_trips_with_stable_bytes`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** in the order: migration and item key, `set_attachments`, `text_hash` and `build_message`, `deliver` guards and logging, `TOO_LARGE`, flags, Outreach card UI (attach box on an email card using the same `attach.js` drop area, an "Attach again" picker listing the company's existing files, chips with remove).
- [ ] **Step 4: Verify** with the fake sender or a local `python -m smtpd`-style debug server on localhost (never a real mailbox): attach a generated PDF to a demo draft, Mark ready, Schedule, run `hermitcrm send due`, read the captured mail's MIME structure.
- [ ] **Step 5: Run** the full suite; update ARCHITECTURE §2 (Outreach item keys) and "Sending", and `help/messages.md`. **Step 6: Commit** `ai: attachments: send approved files with outreach email`. Open the PR for phase 3.

---

## Phase 4: surfaces

### Task 9: Export, agents, demo data, website

**Files:**
- Modify: `src/hermitcrm/export.py` (`interaction_rows` ~219, zip builder ~266), `mcp.py` (new read-only tools), `datafolder.py` (demo, ~688 and ~741), `cli.py` (`export --files`), `help/*.md`, `website/` screenshots
- Test: `tests/test_export.py`, `tests/test_mcp.py`, `tests/test_datafolder.py`

**Interfaces:**
- `interactions.csv` gets an `attachments` column (names joined by `; `). `hermitcrm export --files` (and the web export's checkbox) adds `attachments/<company>/<stored name>` entries to the zip, fixed timestamps like the CSVs.
- MCP tools `list_attachments(company, contact?)` and `read_attachment_text(company, file)` (through `textsource.read_file`, 15 MB cap, errors as `ToolError`). There is **no** tool that creates one (see Decisions).
- Demo data: the two demo emails that already say "attached the proposal" and "Signed contract attached" get a small generated PDF and text file each, so the demo and the website screenshots show the feature. Fictional content only.

- [ ] **Step 1: Write the failing tests:** `test_export_csv_has_attachment_names`, `test_export_files_flag_adds_entries_with_stable_zip_bytes`, `test_mcp_lists_and_reads_text_of_a_pdf_and_a_txt`, `test_mcp_has_no_tool_that_adds_a_file` (asserts the tool names), `test_mcp_refuses_traversal_and_oversize`, `test_demo_folder_has_attachments_and_check_passes`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.**
- [ ] **Step 4: Verify** `hermitcrm init /tmp/x --demo && hermitcrm check --data /tmp/x` exits 0; retake the website screenshots per the *Website deploy* memory (watch the gitignored-downloads trap).
- [ ] **Step 5: Run** the full suite. **Step 6: Commit** `ai: attachments: export, agent reads and demo files`. Open the PR for phase 4.

---

## Self-review (run against the request)

- **Attachments on notes with drag and drop:** Tasks 1 and 3 (picker, drop onto the note box, paste a screenshot, drop onto an existing note), Task 4 (drop anywhere on a company or contact page).
- **Inbound:** Task 7 (BCC'd and forwarded mail, the review queue). Calendar attachments are a recorded non-goal.
- **Outbound:** Task 8 (outreach email with files, hash and guard integrity, logging what was sent). LinkedIn is refused on purpose.
- **Other places:** company and contact Files view, search, paperclip chips in the timeline, `check` and `doctor`, CLI, export, read-only MCP, demo data, merge and delete behaviour.
- **Type consistency:** `Attachment(file, name, size, type)`, `Incoming(name, data)`, `Store.add_files`, `Store.referenced_files`, `attachments.disposition` and `attachments.files_of` are used under the same names in Tasks 1 to 9.
- **Not covered, on purpose:** Git LFS, downloading ICS `ATTACH` URLs, attachments on tasks, stored text extraction, an MCP tool that attaches from a path, a shared file library across companies.
