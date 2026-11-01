# LinkedIn Conversation Import Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On a LinkedIn conversation you are looking at (the full Messaging page, or the chat bubble that opens from a profile's **Message** button or a `messaging/compose/?profileUrn=...` link), one click on a bookmark opens Hermit with the conversation read, matched to a contact, de-duplicated against what is already logged, and shown for review. **Import** logs each new message as a `linkedin` interaction (in/out, real timestamp, text byte for byte) in one commit.

**Architecture:** Same shape as the profile bookmarklet (`static/bookmarklet.js` -> `/extension/new`): the person clicks a bookmark in their own logged-in tab, the page is read there, **nothing is fetched from LinkedIn**, and Hermit shows a review page before anything is written. Two differences: a conversation is bigger than the 12.5 KB the profile bookmarklet fits in a GET query string, so it needs a different transport (Task 0.1); and it is a write of many interactions, so it uses `Store.batch` for one commit. **Dumb client, smart server:** the bookmarklet sends raw pieces (sender text, time text, day heading, message text, the header's profile link); all interpretation (language, dates, direction, matching, de-duplication) is server-side Python that pytest can reach.

**Tech Stack:** Python stdlib, FastAPI (already), vanilla JS (`static/conversation.js` receiver, `static/conversation-bookmarklet.js`). No new dependency, no browser-extension build, no store listing.

**Spec:** none written; the Decisions section is the design. The request was "how difficult, and make a plan"; calls marked *(my call)* are assumptions to correct before building.

## Difficulty, honestly

| Part | Effort | Risk |
|---|---|---|
| Hermit side: model, matching, de-duplication, review page, one-commit write, migration, docs, tests | about 1.5 to 2 days of agent work | Low. Every piece has a precedent (`bcc.py` message ids, `capture.same_profile`, `Store.batch`, `bulk.py` plan/apply). |
| Reading LinkedIn's page | about 0.5 to 1 day to get working | **Medium, and it never ends.** LinkedIn's class names are generated and change every few months; the page has two layouts (full page, chat bubble). Expect an occasional repair. The server-side fallback (Task 4.1) makes a break cost a paste instead of a dead feature. |
| Getting the data from LinkedIn's tab to Hermit | a half-day spike | **Unknown until tried.** The GET-query-string route is too small; the alternatives depend on LinkedIn's headers (COOP) and the browser. |
| LinkedIn's User Agreement | not engineering | See "Terms of Service" below. |

Total: a working version in about 3 days, plus a small recurring repair cost.

## Terms of Service (read before building)

`linkedin.py` already says why Hermit does not automate LinkedIn: User Agreement 8.2 forbids automated access and software that scrapes or copies the Services, and it names "browser plugins and add-ons" in that list. A bookmarklet that copies your own messages on your own click is the same category as the profile bookmarklet Hermit already ships, and is the mildest form (no background activity, no automation, nothing sent to LinkedIn, your own data). It is still not blessed by LinkedIn. Design rules that keep it at the mild end, each tested or enforced:

1. **Only what is already on screen.** The bookmarklet never scrolls, clicks "load earlier messages", opens other threads or loops over conversations. Long history comes from the official data export instead (Task 3.1).
2. **One thread per click, started by the person.** No timers, no listeners, no code that runs without a click.
3. **No request to LinkedIn.** The bookmarklet reads the DOM and opens a Hermit tab. The existing sentence on the Extension page ("nothing is fetched and nothing goes to LinkedIn") stays true and is repeated for this feature.
4. **Say it once in the help page**, in the same plain words `linkedin.py` uses, so the person decides with the facts.

## Global Constraints

- `.venv/bin/pytest` passes before every commit; commit messages start with `ai:`.
- No new runtime dependencies. No JS framework, no build step.
- Interaction bodies are the message text byte for byte after `normalise_body`; writes are deterministic.
- A new front-matter **value** (`source: linkedin-import`) needs a numbered migration plus tests. Latest is 20 (attachments, a `_noop`), so this plan adds **21**, also a `_noop` that reserves the value, as 13 and 20 did.
- Tests and fixtures use fictional people and `example.com` / `example.org` only. **Never commit a real LinkedIn page or real messages.** DOM fixtures are hand-built from the structure notes in Task 0.2, with invented names and text.
- Every POST goes through the existing host allowlist, cross-site check and `check_csrf`. The receiver route reads a payload that arrives by a cross-origin channel, so it treats the payload as hostile text: escaped on render, size-capped, never executed.
- Anything done in the app can also be done by editing a file: an imported message is an ordinary interaction file, and `hermitcrm check` understands `source: linkedin-import`.
- Work on a new branch from `main` (`ai/linkedin-conversation`), not on `ai/attachments-inbound`. One PR per phase.

## Review Focus

Most likely to bite, most likely first.

1. **Double logging.** The same message already exists as an interaction because the LinkedIn session (`linkedin.py` Sent) or the person logged it by hand. Import must recognise it (same contact, same direction, same normalised text, within a day) and leave it unticked. Importing the same thread twice adds nothing (Task 1.3).
2. **Wrong direction.** Every message is attributed to "them" or "you". A wrong guess silently inverts the follow-up radar ("who is waiting on whom"). The review page shows direction per message with a one-click flip, and the sender rule is conservative: unknown means "ask" (Task 1.2).
3. **Wrong date.** LinkedIn shows `10:32` under a day heading (`Today`, `Wed`, `Oct 28`, `Vandaag`, `Gestern`, ...). A year-less heading near New Year, a locale the parser does not know, or a timezone slip files a message in the wrong month (Task 1.1).
4. **Wrong contact.** The compose URL carries an opaque member id (`ACoAAA...`), not `/in/<name>`. Matching must use the profile link in the thread header, fall back to the name, and never guess between two people with one name (Task 1.2).
5. **The payload is attacker-shaped text** (a message can contain anything, including `</script>` or HTML). Escaped everywhere, capped, and never used as a path, slug or URL without validation (Task 2.1).
6. **Browser history leak**, if the transport puts the conversation in a URL (Task 0.1).
7. **Group threads** must be refused, not flattened into a 1:1 (Task 1.1).

## Decisions *(my call unless said otherwise)*

| Topic | Decision | Why |
|---|---|---|
| Form of the feature | A second **bookmarklet**, "Hermit: conversation", on the existing Extension page (`/extension`). Not a Chrome extension. | You already call the bookmarklet "the extension"; no store review, no unpacked-extension friction, works in any browser with a bookmarks bar, and matches `capture.py`'s stated reasoning. A real extension would be the clearer ToS target ("browser plugins") and adds a cross-site request that Hermit's guard refuses by design. |
| One bookmark or two | Two. | On a profile page with a chat bubble open, one bookmark cannot know which you mean. Cost of a second bookmark: nothing. |
| Granularity | One `linkedin` interaction **per message**, `direction` in/out, `date` = the message's time. | It is what email BCC and the radar already model, keeps "last touch" and "waiting on whom" correct, and makes re-import idempotent. One note per import would break all three. |
| Dedup key | `message_id` = `linkedin:<urn>` when the DOM exposes a message id, else `linkedin:<contact>:<sha1(direction + minute + normalised text)[:16]>`. Plus a fuzzy check against interactions not made by this feature (Review Focus 1). | Same mechanism as BCC's `message_id`; the hash fallback does not depend on LinkedIn's markup. |
| Review before write | Always. Ticked = new, unticked = already logged or likely duplicate. | Same trust model as `/extension/new`: a GET/receiver reads and renders, only a same-origin POST writes. |
| Transport | **`postMessage` handshake, decided 2026-11-01 (spike 0.1).** On real linkedin.com in Chrome 156: A passed (100,021 bytes intact, 165 ms, opener present, so no COOP block), B passed (172,812-character URL), C passed (clipboard + paste). Use A. Keep C as the fallback when `window.opener` is null. Drop B. | Nothing in a URL means nothing in browser history or Chrome sync. Safari and Firefox untested: Chrome only for now. |
| Group chats | Refused with a clear message in v1. | Direction and contact are ambiguous; flattening is worse than saying no. |
| Attachments, reactions, link previews | Message text only, plus a marker line `[attachment: <file name>]` when the DOM names one. No download. | Attachments from LinkedIn need an authenticated fetch, which breaks the "nothing is fetched" promise. |
| Unknown contact | Review page offers a contact picker over every contact, and **Create contact** that opens `/contacts/new` prefilled via the existing `Capture.contact_values` path. | Reuses the one journey for new people. |
| Member id on the contact | Not stored in v1. | New front-matter key means a migration and a second mechanism. Revisit only if matching by profile link and name proves flaky. |
| Language | Date headings and weekday names in en, nl, de, fr, es (the lists the bookmarklet already carries for section headings). Unknown heading: the review page asks for the date of that block. | You use LinkedIn in several languages; a silent wrong date is worse than one question. |
| Stage and outreach side effects | Left as `create_interaction` does today (a first touch advances a prospect to engaged; an outbound message at or after an outreach item's `ready` marks it sent). Shown on the review page before Import. | Backdated history before `ready` matches nothing, and a message you sent today by hand should close the card. Test both. |

## File Structure

| File | Responsibility |
|---|---|
| `src/hermitcrm/conversation.py` (new) | `Message`, `Thread`, payload parsing and caps, day-heading and time parsing, direction, `message_id`. No store import for parsing; `plan` and `apply` take a `Store`. |
| `src/hermitcrm/models.py` | `InteractionSource.LINKEDIN_IMPORT = "linkedin-import"`. |
| `src/hermitcrm/migrations.py` | Migration 21 (`_noop`). |
| `src/hermitcrm/web.py` | `GET /extension/conversation` (receiver), `POST /extension/conversation/preview`, `POST /extension/conversation`. |
| `src/hermitcrm/templates/conversation_import.html`, `extension.html` | Review page; second bookmark and its help on the Extension page. |
| `src/hermitcrm/static/conversation.js` (new) | Receives the payload, posts it to the preview route, wires flip/untick. |
| `src/hermitcrm/static/conversation-bookmarklet.js` (new) | Reads the DOM on LinkedIn. Same one-line constraints as `bookmarklet.js`. |
| `src/hermitcrm/capture.py` | `conversation_bookmarklet(base)` next to `bookmarklet(base)`. |
| `src/hermitcrm/importer.py` | (Phase 3) `messages.csv` from LinkedIn's data export. |
| `src/hermitcrm/help/`, `docs/ARCHITECTURE.md`, `README.md`, `CHANGELOG.md` | Docs, including the Terms of Service paragraph. |
| `tests/test_conversation.py`, `tests/test_conversation_web.py` (new) | Everything below. |

---

## Phase 0: Spikes (throwaway, nothing committed)

Both spikes need **your** logged-in LinkedIn and, for 0.2, your own messages, so you run them; I supply the snippets. They are labelled throwaway: keeping anything they produce is a new request.

### Task 0.1: Transport

**Question:** how does a bookmarklet on `https://www.linkedin.com` hand 100 KB of text to `http://127.0.0.1:8765` without a server round trip carrying it in the query string?

- [ ] **Step 1: In the LinkedIn tab's DevTools, read the response headers of a messaging page.** Is `Cross-Origin-Opener-Policy` set to `same-origin`? If so, `window.open` severs `window.opener` and the handshake below cannot work.
- [ ] **Step 2: Try A, `postMessage` handshake.** The bookmarklet opens `B/extension/conversation` and keeps a `message` listener; the receiver page does `window.opener.postMessage('ready', 'https://www.linkedin.com')`; the listener answers `event.source.postMessage(payload, B)`; the receiver accepts only `event.origin === 'https://www.linkedin.com'`. Test 100 KB.
- [ ] **Step 3: Try B, URL fragment.** `window.open(B + '/extension/conversation#' + encodeURIComponent(json))`. The fragment is not sent to the server and is not limited by the 16 KB request head. Check: Chrome accepts a 100 KB URL; the receiver can `history.replaceState` it away; whether the first history entry keeps the full URL (it may, and Chrome sync may upload history).
- [ ] **Step 4: Try C, clipboard.** Bookmarklet copies the JSON (needs a user gesture; a bookmarklet click may or may not count), the receiver page has a "Paste here" box.
- [ ] **Step 5: Pick one and record the result in this plan's Decisions table**, including the browsers tested (Chrome, and Safari if you use it).

Exit criterion: one transport works on your browser for a 100 KB payload, with the history-leak answer written down.

### Task 0.2: What the page looks like

**Question:** what does the DOM of a conversation look like, in the three situations you named?

- [ ] **Step 1: I give you a snippet that dumps the page's *structure only*** (tag, role, aria-label, class names, `datetime` attributes, `href` of profile links; every text node replaced by its length). Nothing you wrote or received leaves the tab, and nothing real can reach the repo.
- [ ] **Step 2: Run it on (a)** `linkedin.com/messaging/thread/...` full page, **(b)** the chat bubble after clicking **Message** on a profile such as `linkedin.com/in/<name>/`, **(c)** the chat bubble opened cold from a `messaging/compose/?profileUrn=...&recipient=...` link for someone you have already written to, and **(d)** the same for someone you have never written to (empty thread).
- [ ] **Step 3: Write `docs/superpowers/specs/linkedin-conversation-dom.md`**: for each of the four, where is (1) the other person's profile link, (2) the list of messages, (3) the sender of each message and how consecutive messages by one sender are grouped, (4) the time and the day heading, (5) any stable message id (`data-*-urn`), (6) the UI language used. Then hand-build **synthetic** fixture HTML for each, with invented names, in `tests/fixtures/linkedin/`.

Exit criterion: a note and four synthetic fixtures that a developer who has never seen LinkedIn could code against.

**Result (2026-11-01):** done for (a) and (b); (c) and (d) not run, expected to match (b) and an empty list. Note: `docs/superpowers/specs/linkedin-conversation-dom.md`. Fixtures: `tests/fixtures/linkedin/full-page-thread.html` and `profile-bubble.html` (the bubble in a declarative shadow root, as on LinkedIn). Findings that change the plan: (1) the bubble is in an **open shadow root**, so the extractor must walk shadow roots; (2) both places use the same `msg-s-*` markup, so one extractor, not two; (3) direction is a class (`msg-s-event-listitem--other`), not only a name comparison; (4) day headings and times are text with **no `datetime`**; (5) only the first message of a run carries name and time, so follow-ups inherit them (shown as approximate); (6) `data-event-urn` is a real per-message id, so the dedup key does not need the hash fallback; (7) own messages also carry an absolute `Sent at ...` title that verifies the date.

---

## Phase 1: Hermit side (testable without LinkedIn)

### Task 1.1: Parse a payload into a `Thread`

**Files:** `src/hermitcrm/conversation.py`, `tests/test_conversation.py`

The payload (shape fixed by Task 0.2, see section 4 of the DOM note): `{v, url, layout, other: {name, href}, lang, now_local, tz_min, items: [{urn, is_other, who, who_href, day, time, inherited, sent_title, text}]}`.

- [ ] **Step 1: Failing tests** for: a normal 1:1 thread; a thread with a day heading in each of en/nl/de/fr/es; `Today` and `Yesterday` resolved against an injected `now`; a weekday heading resolves to the most recent such day; a year-less `Oct 28` heading read in January means last year; 24-hour and AM/PM times; a block with an unknown heading surfaces as `needs_date`; group thread raises `ConversationError("group conversations are not supported")`; caps (500 messages, 20,000 characters each, 1 MB total) cut, never crash; control characters and a NUL are stripped; the payload is never `eval`ed or used as a path.
- [ ] **Step 2: Implement** `Message(direction, when, text, urn)`, `Thread(profile_url, name, messages, needs_date)`, `parse(payload, now)`. Dates are naive local time, as `Store._coerce_datetime` expects. Normalise text with `models.normalise_body`.
- [ ] **Step 3: Run, commit** (`ai: conversation: parse a LinkedIn thread payload`).

### Task 1.2: Direction and contact matching

- [ ] **Step 1: Failing tests.** Direction: the page's own marker (`is_other`) is the primary signal; it is cross-checked against the sender name (the header's other person is "in", config `owner_name`, saved by Settings > You, is "out"). They agree: use it. They disagree, or the sender is a third name: "ask", never imported until the person picks. Matching, in order: `capture.same_profile` against every contact's `linkedin` (a vanity URL and a `/in/ACoAAA...` URL are both tried); else normalised full name across all contacts; **two contacts with one name returns candidates, never one**; no match returns none.
- [ ] **Step 2: Implement** `match(store, thread) -> Match(kind, company, contact, candidates)` and `direction_for(...)`.
- [ ] **Step 3: Run, commit.**

### Task 1.3: Plan, de-duplicate, apply

- [ ] **Step 1: Failing tests.**
  - `plan()` marks each message `new`, `logged` (same `message_id` for this contact) or `maybe` (same contact, same direction, same normalised text, within 24 hours of a `linkedin` interaction with another source: hand-logged or `outreach`).
  - Importing the same thread twice: the second `plan()` is all `logged`; `apply()` writes nothing and makes no commit.
  - A thread that grew by two messages: `apply()` adds exactly those two.
  - A hand-logged, byte-different copy (trailing space, `\r\n`) is `maybe`, not `new`.
  - `apply()` makes **one** commit, `interaction: <company> linkedin import <contact> (<n> messages)`, via `store.batch`; ids are unique when two messages share a minute.
  - Stage: a `prospect` becomes `engaged` once, in that commit. An outbound message dated after an outreach item's `ready` marks it sent; a message dated before does not.
  - A message with a `needs_date` block and no date given is refused, not guessed.
- [ ] **Step 2: Implement** `plan(store, company_slug, contact_slug, thread, now)` and `apply(store, plan, selected)`; add `InteractionSource.LINKEDIN_IMPORT`; **migration 21** (`_noop`, "interactions may have the source linkedin-import"); `hermitcrm check` accepts it; update the `source` enum line in `docs/ARCHITECTURE.md`.
- [ ] **Step 3: Run the whole suite, commit.**

---

## Phase 2: Web and bookmarklet

### Task 2.1: Receiver, preview, import

**Files:** `web.py`, `templates/conversation_import.html`, `static/conversation.js`, `tests/test_conversation_web.py`

- [ ] **Step 1: Failing tests.** `GET /extension/conversation` renders only a shell (it reads and writes nothing; it carries no conversation text). `POST /extension/conversation/preview` takes the JSON, returns the review fragment with every value HTML-escaped (test with `</script><img src=x onerror=alert(1)>` as a message and as a name); is refused over the size cap (413); is refused cross-site; and writes nothing (assert the data folder is byte-identical afterwards). `POST /extension/conversation` needs `check_csrf`, imports only the ticked indices, applies a flipped direction, and redirects to the contact with a flash ("12 messages imported, 3 already logged").
- [ ] **Step 2: Implement.** The review page shows: who it matched (or a picker and **Create contact**), the first and last date, and one row per message with a checkbox (new ticked, logged/maybe unticked and labelled), a direction arrow with flip, the time, and the text (first lines, rest behind "more", as the contact page does). The receiver JS never inserts payload text with `innerHTML`.
- [ ] **Step 3: Run, commit.**

### Task 2.2: The bookmarklet

**Files:** `static/conversation-bookmarklet.js`, `capture.py`, `templates/extension.html`, tests in `test_capture.py`

- [ ] **Step 1: Failing tests** for `capture.conversation_bookmarklet(base)`: one line, no percent sign, no line breaks, every statement ends in `;`, base URL substituted, same constraints `test_capture.py` already enforces for `bookmarklet()`. pytest cannot run the bookmarklet's JS and the repo has no JS test runner, so keep the extraction tiny and put the interpretation in Python (Task 1.1). Decide in this task whether a one-file Node check over the synthetic fixtures is worth it (Node exists on this Mac, but CI and `jsdom` would be a new dependency, which is not allowed without discussion); the default is no, and the manual check in Step 4 covers the DOM.
- [ ] **Step 2: Implement** the transport chosen in Task 0.1 and the extraction from Task 0.2. Read only what is rendered. No scrolling, no clicks, no `fetch`, no timers beyond the handshake wait.
- [ ] **Step 3: Extension page.** Second draggable bookmark, "Hermit: conversation", one paragraph on how to use it (open the thread or the chat bubble, click the bookmark, review in Hermit), the Terms of Service paragraph, and the same sentence as the profile bookmarklet: nothing is fetched and nothing goes to LinkedIn.
- [ ] **Step 4: Manual check on a real thread (you), then commit.**

---

## Phase 3: Backfill and docs

### Task 3.1: LinkedIn data export, `messages.csv` *(recommended companion, ToS-clean)*

The official export (Settings > Data privacy > Get a copy of your data > Messages) delivers `messages.csv` with the full history, sender and recipient profile URLs, ISO timestamps and message text, with no scraping at all. This is the right tool for years of history; the bookmarklet is for the daily trickle.

- [ ] **Step 1: You send one export** (or the first 20 rows with names changed), so the column names are verified against a real file. I believe they include `CONVERSATION ID, CONVERSATION TITLE, FROM, SENDER PROFILE URL, TO, RECIPIENT PROFILE URLS, DATE, SUBJECT, CONTENT, FOLDER`; **unverified**.
- [ ] **Step 2: Tests, then** an importer mode (`hermitcrm import messages.csv --mode linkedin-messages`, plus the Import page), grouping by conversation id, matching by profile URL, going through the same `plan`/`apply` as the bookmarklet so de-duplication is shared. Group conversations skipped with a count.
- [ ] **Step 3: Commit.**

### Task 3.2: Docs

- [ ] Help page, `docs/ARCHITECTURE.md` (routes table, `source` enum, the conversation module), `README.md` feature line, `CHANGELOG.md`, `TODO.md` entry for "member id on the contact" as a deferred idea.

## Phase 4: Resilience

### Task 4.1: "Paste instead" fallback

- [ ] LinkedIn changes its markup; the bookmarklet then reads nothing. The receiver shows "Hermit could not read this page" (the `read_nothing` pattern `Capture` already has) with a box: select the thread, copy, paste. `conversation.parse_text(text, now)` reads LinkedIn's copied layout (name line, time, message) into the same `Thread`, and the review page continues unchanged. Also the answer for a browser where the transport fails. Tests with synthetic pasted text in two languages.

---

## Open questions (assumptions stand if you do not answer)

1. **Granularity:** one interaction per message, as above.
2. **Browser(s):** assumed Chrome-family on macOS. If you use Safari or Firefox for LinkedIn, Task 0.1 must be run there too.
3. **LinkedIn UI language:** assumed English with occasional Dutch/German/French contacts' pages; the day-heading parser covers en/nl/de/fr/es.
4. **Group chats:** refused in v1.
5. **Start with Phase 3.1?** If most of your pain is old history rather than today's copy-paste, the export import is the cheaper, safer first deliverable and could ship before any DOM work.
