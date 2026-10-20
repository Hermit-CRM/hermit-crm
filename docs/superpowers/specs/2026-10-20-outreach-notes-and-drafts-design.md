# One outreach path, one list of notes, one-click copy

Status: proposal, not built. Written 20 Oct 2026. Decisions marked **yours** were
made by Gijs in conversation; decisions marked **call** were made by the author
and are listed again at the end for a veto.

## Why

Three things about the day-to-day flow of writing to someone keep costing time:

1. A contact page has two ways to get a first message: the **Message drafts** box
   (no AI, three fixed angles) and **Research & draft** (the AI bot, which lands
   on the Outreach page). The box is the poorer one and the two do not know about
   each other.
2. What you know about a person lives in two places that do not talk. **Notes**
   (timeline entries on the contact, channel `note`) never reach the AI that
   drafts the message, and **findings** (on each Outreach card) never reach the
   contact except as one summary note when you press Mark ready.
3. Email addresses on `/outreach` and on the contact page are `mailto:` links. To
   put one into another tool you select and copy it by hand.

## Goals

- One way to get an outreach message: from the contact page, one click opens
  Outreach ready to generate it for that person.
- A single list of what is known about a person, kept as notes. Add or read it on
  the Outreach card, the contact page or the company page and it is the same
  list. The AI drafts from it.
- One click copies an email address, on the Outreach card and on the contact page.

## Non-goals and anti-goals

- No AI call from a page load or a plain link. Generating stays a POST with a
  CSRF token, from a button.
- No new storage type, no new record file kind, no migration of records. A note is
  still an interaction with channel `note`.
- The web-research AI never receives notes. Its prompt stays limited to public
  identifiers (see `ai_web_prompt`: a page written by a stranger could try to
  make it leak whatever is in its context). Notes reach only the drafting and
  critic steps, which have no tools.
- Nothing is sent anywhere new, nothing is deleted without a click on a delete
  control that exists today.
- Not a rework of Outreach itself: tabs, states, scheduling, sending, learning,
  tracked edits and the critic stay as they are.

## Part A: copy email

Add a small **copy** button next to the address wherever it is shown as a link:

- `/outreach` card header (`outreach-email`).
- Contact page, Details row `email`. The existing "copy email" text in the
  action row stays.

The address itself stays a `mailto:` link; the button is separate, so both uses
survive. Button label becomes "copied" for about 1.5 seconds. It uses the same
`navigator.clipboard` code with the `execCommand` fallback that the Copy button
on a card already has, and it must work without the Clipboard API (127.0.0.1
counts as a secure context, so the fallback matters only on odd setups). Put the
script once in `static/` (or in base) and drive it with one data attribute, so the
two pages and any later page share it.

## Part B: Message drafts go, Outreach takes over (yours)

### The contact page and the company page

- Remove the **Message drafts** section from both pages.
- The `drafts` name in `layout.py` `SECTIONS` goes away. A `layout.toml` that
  still lists `drafts` must keep loading: an unknown or retired section name is
  ignored (and the Make-it-yours help text and `help/adjust-layout.md` stop
  naming it). The builder checks how `layout.py` validates names today and picks
  the least disruptive way.
- Replace the **Research & draft** form (select, select, button) with one button,
  **Generate outreach**, in the contact's action row. It is a link to
  `/outreach?contact=<company-slug>/<contact-slug>`. When the contact already has
  an open outreach item, the button reads **Open outreach draft** and links to
  the card, as the "Review it on Outreach" line does today.
- The company page gets the same link for its preselected contact.

### The Outreach page with `?contact=`

Above the tabs, when `contact` is given and the pair exists, show a panel
**Generate for \<first name\>** (nothing runs on load):

- channel, kind (first touch / reply to interest / follow-up, preselected from the
  contact's state exactly as the contact page does today), research level, the
  strong-model checkbox. These are the same fields the batch form and the
  contact-page form already post to `/outreach/build`, which stays the one
  endpoint.
- **Signal** (not checked / growing / stalled / declining / hiring), with the link
  to the company's LinkedIn insights that the box had.
- **Observation**: one sentence from their site or team, with the link to the
  website that the box had.
- **Language**: preselected from the contact's draft language, else the company's
  country (`messaging.draft_language`); changing it applies to this card,
  including its regenerates.
- The notes it will use, read-only, newest first (the list of Part C), with
  "add a note" above it.
- **Generate** posts to `/outreach/build` with `contact=` and `back=` as today.
  `data-busy` text says it is working (the busy helper from the last change).

How the inputs reach the draft:

- Observation, when filled, is saved as a note on the contact before the build,
  worded as the sentence you typed. It is then an ordinary note: visible on the
  timeline, usable by the draft. (In the old box it went "word for word into
  draft 3"; the AI is told it is a fact the seller checked, not a script.)
- Signal, when chosen, is saved as a note too: "Signal (LinkedIn insights,
  checked \<date\>): hiring." The playbook's angle choice keeps working as it
  does; the note is context, not a switch. **Call**: no code maps a signal to an
  angle.
- Language is passed through `build` and `redraft` for this item only, so the
  draft and its regenerates use it, and the record's draft language is not
  changed. How an item remembers it is the builder's call (an existing key if
  one fits; a new optional item key otherwise, which needs no record migration
  but does need a test that old item files still load).

### What is kept

`messaging.py` stays: `draft_language`, the reply and follow-up templates, the
language and signal labels, and `drafts()` (the Make-it-yours preview in
`adjust.py` uses it). Only the page code goes: `drafts_section` macro,
`draft_context` and its four call sites in `web.py`, the `signal` / `observation`
/ `lang` query handling on the two pages, and the tests that exercise them. The
no-AI drafts stop existing as something a user can reach. **Call**: no fallback
when no AI CLI is configured. Outreach already says so ("ai_problem") and links to
the setting; the contact button shows the same reason as its tooltip instead of
generating a message the user then has to rewrite by hand.

`docs/ARCHITECTURE.md` section 8.3 and the help pages `contacts.md`,
`companies.md` and `adjust-layout.md` are updated, and a line goes in
`help/changelog.md`.

## Part C: a finding is a note (yours)

### The rule

- The **Findings** panel on the Outreach card is replaced by a **Notes** panel.
  The "Save findings" button and the remove checkboxes are deleted.
- The panel shows the contact's notes live: every interaction of channel `note`
  for that contact (the same set `Company.contact_notes` already gathers),
  newest first. Each shows date, first line or full text, where it came from
  (**you**, or **research** with its source link) and a link to its place on the
  contact's timeline.
- **Add a note** on the card creates a note interaction on the contact at once
  (`store.create_interaction(company, "note", "", contact=...)`, one commit). The
  timeline of the contact and of the company show it because it is the same
  record. A note written on the contact or company page shows on the card the next
  time the page is rendered, because the card reads the store, not a copy.
- Editing or deleting a note happens where it does today (the timeline's own
  edit page). The card links there; it has no delete of its own. **Call.**
- The company's own free-text **notes** field (Details on the company page) is
  the company's side of the same idea. The card shows it read-only above the list,
  "Company notes", with a link to edit it, and the draft prompt gets it as
  background (not citable by number). A note on a colleague at the same company
  is not shown on this person's card or fed to their draft. **Call.**

### Research writes notes

- When the research step finishes (`build`), each finding with confidence
  medium or high and a source becomes a note on the contact, one per finding, in
  the same commit as the research step. Body is the finding's text and, on a line
  of its own, `Source: <url> (<kind>, <date>, <confidence>)`, so the origin, date and
  confidence survive as plain text on the timeline. The note's subject names the
  origin ("Research: example.com"). Findings already present as a note (same text)
  are not written twice. **Call**: low-confidence findings are not saved; the card
  says how many were dropped. They were never usable by the draft anyway.
- The company's `product_oneliner` ("crm" finding) is not a note: it is a field of
  the record and is already in the brief ("What they do"). It stops being listed
  as a finding.
- **Add to research** from LinkedIn (`add_page`) writes its findings as notes the
  same way.
- **Mark ready** no longer writes the "Outreach research for..." summary note: the
  notes already exist.

### The draft reads notes

- `draft_prompt` lists the contact's notes in the block that today lists findings,
  numbered, capped (**call**: newest 20, 4,000 characters in all, longest dropped
  first) so a very long timeline cannot flood the prompt. The AI still cites by
  number in `findings_used`; the key keeps its name so critic, learning and the
  checks are untouched.
- `Item.findings` stays as a **snapshot** of the notes the draft was written from
  (text, source, kind, confidence, date, stale, used), exactly as today, so the
  card can show which notes the draft used, history shows what an old draft was
  based on, and every check that reads `findings` keeps working. Notes you wrote
  count as high confidence and never stale (you know when it is true); research
  notes carry the confidence and date from their source line. A finding's `kind`
  (company / person / trigger) is only a label in the prompt: your notes are
  `person`, research notes keep theirs as a word in the source line.
- Regenerate rebuilds the snapshot from the notes as they are now. That is how a
  note added after the draft reaches the next version.
- Whenever notes exist that are newer than the snapshot, the card says so: "2
  notes added since this draft was written. Regenerate to use them."
- A reply-to-interest or follow-up still takes no research; its prompt keeps
  using the thread. Notes are added to its context as background only, not as
  citable findings.

### Items made before this change

An open (drafted) card keeps working. Its stored findings that are not yet notes
are saved as notes the first time the card is regenerated or marked ready
(idempotent by text), so nothing on an open card is lost. Closed items (sent,
skipped) are not touched. Their findings stay as they are in the item file and are
shown read-only in the card's history. **Call**: no bulk conversion of old
summary notes.

## Constraints from the repo

- Commit messages for AI-made changes start with "ai:". `.venv/bin/pytest` passes
  before any commit. No new runtime dependency.
- Fictional names and example.com in code, tests and docs.
- Keep writes deterministic and interaction bodies byte for byte: the note format
  above is fixed text, not templated per run.
- A change to front-matter keys or values needs a numbered migration plus tests.
  This design adds none to records. If the language choice needs a new item key,
  items are not records, but old item files must still load and a test says so.
- One commit per research step stays: the research notes join that commit.

## Test and verify

- `tests/test_messaging.py` and `tests/test_draft_language.py`: keep what tests
  `messaging`; delete only what tested the page section.
- New: research writes notes (once each, no duplicates, low confidence dropped);
  the card lists live notes; a note added on the contact page appears on the card
  and in the next prompt; the web-research prompt contains no note text (a test on
  `ai_web_prompt` with a note present); the prompt's note cap; `add_page` writes
  notes; mark ready writes no summary note; an old item with findings and no notes
  adopts them once; `?contact=` renders the panel and generates nothing; a
  `layout.toml` naming `drafts` still loads.
- Copy button: check in the browser on `/outreach` and a contact page, click it,
  read the clipboard.
- Against a demo folder: `.venv/bin/hermitcrm init /tmp/x --demo`.

## Calls made by the author (veto any)

1. No no-AI fallback after Message drafts is removed.
2. Observation and signal become notes; no code maps a signal to an angle.
3. Language chosen on the panel applies to that card and its regenerates only.
4. One note per research finding, medium or high confidence; low confidence is
   dropped and counted.
5. No delete or edit of a note from the card; it links to the existing edit page.
6. Prompt cap of 20 notes / 4,000 characters; your own notes are never stale.
7. Open old cards adopt their findings as notes on regenerate or Mark ready;
   closed items are left alone.
8. `product_oneliner` stops appearing as a finding.
9. The copy button sits beside the address; the address stays a `mailto:` link.
10. The company's notes field shows on the card and goes to the draft as
    background; other contacts' notes at the same company do not.
