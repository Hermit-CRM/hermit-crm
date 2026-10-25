# Button diet: Outreach, Contact and Learning pages

Status: PROPOSAL, waiting for Gijs's review. Nothing in this file has been implemented.
Written 2026-10-25 from the live app (127.0.0.1:8765) and the templates.

## For the Claude that implements this

Read this whole file, then work through "Work order". Rules from `CLAUDE.md` apply:
`.venv/bin/pytest` must pass before a commit, commit messages start with `ai:`,
no new runtime dependencies, fictional data only in tests and docs.

**Warning: the working tree is dirty.** When this was written,
`src/hermitcrm/templates/outreach.html`, `web.py`, `outreach.py`, `cli.py`,
`docs/ARCHITECTURE.md` and three outreach tests had uncommitted edits from other work.
Run `git status` first. Do not stash or revert them. Either wait for them to be
committed, or make your edits on top and commit only the files you changed
(use `git add -p` for `outreach.html`).

## Problem

The three pages show many buttons at once, most of them rarely used. The daily job
on Outreach is: review a draft, edit it, approve it, send or schedule it. Everything
else competes with that.

Measured by rendering the pages (buttons in the main content, per state):

| Page / state | Buttons visible |
|---|---|
| Outreach, Drafts tab, 1 card | 15 on first view (top strip, build form, one card) + 7 skip-reason buttons behind "Skip" |
| Outreach, Ready tab, per card | 9 actions (Send now, Schedule, Copy, Open in mail, Log it, Mark sent, Back to draft, Skip, plus "Open LinkedIn" on LinkedIn items) |
| Outreach, Scheduled tab, per card | 5 to 6 (Send now, Move to front, Unschedule, Mark sent, Skip) |
| Outreach, Follow-ups tab | 16 identical "Draft follow-up" buttons |
| Outreach, Sent tab | 10 tiny "copy" buttons, one per sent item, for a message that is already gone |
| Learning | 4 "Promote/Move to…" + 4 "Retire" on lessons, 8 "Pin" + 8 "Exclude" on examples (28 buttons at rest) |
| Contact (Aaron Hayos) | 8 in the header row, plus Edit, Add task, Log interaction, copy |

## Principle

Each card or page gets **one primary action** (what you do next), at most
**two secondary ones**, and everything that is a state fix, an escape hatch or a
rarely used tool goes into a **"More" overflow** (a closed `<details>`), which
already exists as a pattern: `details.more-box` on the contact page
(`style.css:892`). Destructive or unusual actions never sit next to the primary one.

Decision vocabulary used below:

- **KEEP**: stays as is.
- **DEMOTE**: stays, but moves into a closed "More" overflow (or loses primary styling).
- **HIDE**: only rendered when it is relevant (a condition on state or data).
- **REMOVE**: delete the button; a better way to do the same thing already exists.

## Shared building block (do this first)

Add one macro in `src/hermitcrm/templates/macros.html`:

```
{% macro more(label='More') %}<details class="row-more"><summary>{{ label }}</summary><div class="draft-actions">{{ caller() }}</div></details>{% endmacro %}
```

Used with `{% call m.more() %}…{% endcall %}`. Style it in `style.css` next to
`.outreach-card .draft-actions` (line ~936): inline `<summary>` that looks like a
quiet link ("More ▾", `color: var(--muted)`), buttons inside wrap normally. It must
work without JS (it is a `<details>`), keep keyboard access, and the forms inside keep
their CSRF fields. Nothing about the POST routes changes.

## Outreach page (`templates/outreach.html`)

### Top of page

| # | Button | Where | Decision | Why |
|---|---|---|---|---|
| O1 | Pause / Resume | l.65-68 | KEEP | The kill switch. Must stay one click away. |
| O2 | LinkedIn session (link) | l.77 | KEEP | Only shown when LinkedIn is on. Fine. |
| O3 | Preview + Build queue + the 8 fields of the build form | l.81-95 | DEMOTE the whole form into `<details class="outreach-build-box"><summary>Build a batch</summary>`, **closed by default**, open when `form.left` (a batch is running) or `preview` is set | It is a weekly "fill the pipeline" action, but today it sits above the review work every single day. Keep the id `outreach-build` so tests and JS still find it. |
| O4 | Schedule all ready email (N)… then Schedule N emails | l.216-227 | KEEP | Two-step on purpose (preview, then commit). Only appears with ready email. |

### Drafts tab, one draft card (state `drafted`, l.337-366)

| # | Button | Decision | Why |
|---|---|---|---|
| O5 | Mark ready | KEEP (primary) | The job. |
| O6 | Save & check again | KEEP (secondary) | An AI call that rescores after an edit. Rename the visible label to "Re-check" and keep the long `title`. |
| O7 | Regenerate (+ "stronger model" checkbox) | KEEP (secondary) | Needed. Keep the checkbox attached to it. |
| O8 | Copy (draft state) | REMOVE | In `drafted` you cannot send, you have to Mark ready first. The Ready card has its own Copy (O12). |
| O9 | Skip (+ 6 reason buttons + Cancel) | KEEP | The reason buttons are the point (they feed Learning) and are already hidden until Skip is pressed. |
| O10 | Add note (inside the Notes details) | KEEP | Collapsed per card is fine; notes drive regenerate. |
| O11 | "copy" next to the email in the card header (l.281) | REMOVE on **every** tab | The address is selectable text and a mailto link. On the Sent tab it is 10 useless buttons. The Ready card keeps "Copy" for the message body. |

Result: Drafts card goes from 5 buttons plus a copy chip to 3 visible buttons (Mark ready, Re-check, Regenerate) plus Skip.

### Ready tab, one card (l.367-401)

Current: Send now, Schedule, Copy, Open in mail / Open LinkedIn, Log it, Mark sent, Back to draft, Skip.

| # | Button | Decision | Why |
|---|---|---|---|
| O12 | Send now, Schedule (when `send_on` and email) | KEEP (primary, secondary) | The two real outcomes. |
| O13 | Copy, Open in mail, Open LinkedIn | KEEP **when the manual path is the main path** (LinkedIn, or email with sending off). When `send_on` and email: DEMOTE into More | With automated sending these are the "I'll do it myself" route. |
| O14 | Log it | DEMOTE (More) when `send_on` and email; KEEP visible for LinkedIn and sending-off | Log it is what records a manual send on the timeline. |
| O15 | Mark sent | DEMOTE (More), relabel "Mark sent (no log)" | Changes state with no timeline record; `title` already says so. Easy to hit by mistake next to Schedule. |
| O16 | Back to draft | DEMOTE (More) | A correction, not a step. |
| O17 | Skip | DEMOTE (More) on Ready/Scheduled; stays visible on Drafts (O9) | At Ready you have already approved it. |

Result: Ready card shows 2 buttons (email with sending on) or 3 (manual channels) plus "More".

### Scheduled / failed tab, one card (l.402-439)

| # | Button | Decision |
|---|---|---|
| O18 | Send now | KEEP (primary) |
| O19 | Unschedule (queued) / Retry (failed) | KEEP (secondary); it is the state fix you expect here |
| O20 | Move to front, Mark sent, Skip | DEMOTE (More) |

### Replies tab (l.123-176)

| # | Button | Decision | Why |
|---|---|---|---|
| O21 | Check replies (N) | KEEP | Already disabled when nothing to check. |
| O22 | Draft a reply (+ channel select) | KEEP (primary) | |
| O23 | Confirm: interested / Interested / Not interested | HIDE unless `r.to_confirm`. Otherwise DEMOTE one "Change verdict" pair into More | Once a verdict is set (by you or confirmed), the two buttons are noise. |
| O24 | Opted out | DEMOTE (More) | Suppression-list action, confirm dialog already guards it, but it should not sit beside Draft a reply. |

### Follow-ups tab (l.178-201)

| # | Button | Decision | Why |
|---|---|---|---|
| O25 | Draft follow-up (x16) | KEEP, restyle `class="secondary"` | It is the only way to pick one person. Do **not** add a bulk "draft all": it spends AI calls (use Build batch with kind follow-up for that). Optional later: collapse the list to the first 10 with a "Show all" link. |

### Sent and Skipped tabs

No buttons beyond O11 (removed). Nothing else to change.

## Contact page (`templates/contact.html`)

Header row today (l.26-47): Log interaction, Add note, Add task, Generate outreach / Open outreach draft, copy email, linkedin, Opted out, Enrich.

| # | Button | Decision | Why |
|---|---|---|---|
| C1 | Log interaction, Add note, Add task (jump links) | KEEP | The deliberate design of spec `2026-10-15-contact-page-layout-design.md`; `tests/test_contact_page.py:160` asserts them. |
| C2 | Generate outreach / Open outreach draft | KEEP | |
| C3 | Enrich | KEEP, only when `enricher.available` (already) | Costs credits, but it is a normal action and confirms before saving. Keep in the quiet group. |
| C4 | "copy email" link in the header (l.33) | REMOVE | Duplicate: the email row in Details (l.79) already has a "copy" button. Remove the `data-copy-email` script block (l.141-150) with it if nothing else uses it. |
| C5 | Opted out | DEMOTE: move into the "More" box at the bottom, next to Merge and Delete, as a fourth section `opt-out`. Keep the confirm dialog and the same POST route | A suppression-list action should not sit beside Enrich. The Outreach Replies tab keeps its own (O24) for the "they asked to stop" moment. |
| C6 | linkedin link | KEEP | A link, not a button. |
| C7 | Edit, Save contact, Add task form, Log interaction form | KEEP | Normal forms. |
| C8 | Compare (merge), Delete contact | KEEP in the More box | Already correctly hidden. |

Note `layout_sections('contact')` drives section order from `layout.toml`; the new
`opt-out` section must be added to the allowed section names in `layout.py` (look at
how `merge` and `delete` are listed) and to the `more` filter in `contact.html` l.19,
and documented in help `adjust-layout`. If that is too invasive, fallback: render
Opted out as a plain extra block inside the More box, outside the layout system.

## Learning page (`templates/learning.html`)

| # | Button | Decision | Why |
|---|---|---|---|
| L1 | Accept / Reject on proposals | KEEP | The point of the page. |
| L2 | Run now / Write evidence pack, Import | KEEP | Already disabled when there is nothing to do. Import only shows in handoff mode. |
| L3 | Apply on suggestions | KEEP | |
| L4 | Retire on each lesson | KEEP (secondary) | |
| L5 | Promote to Worked / Demote to Didn't work / Move to Still testing (2-3 per lesson) | HIDE the buttons by default. Show a single **Promote** button only when `sc.promotion` is set (the page already prints a promotion hint, l.103). All other moves go into More | 12 lessons x 3 buttons with identical styling, used rarely. The data already says when a move makes sense. |
| L6 | Pin / Exclude / Clear on every example (8 x 2) | DEMOTE into the existing "What the drafter would see" `<details>` (l.139), so they appear when you open an example. The "pinned" / "excluded" tag stays visible on the row | Marking an example is a deliberate, informed act: you should be looking at what the drafter sees when you do it. |
| L7 | noscript "Show" | KEEP | Invisible with JS. |

## Out of scope (decided, do not redo)

- No change to routes, form field names, CSRF handling, or stored data. This is
  template and CSS only, so **no migration** is needed.
- No bulk "draft all follow-ups".
- No new settings toggle for "show advanced buttons" (a single More overflow is enough).

## Tests that will need updating

Run `.venv/bin/pytest -q` and expect these to fail until updated; the assertions are
about visible label text, so update them to match, do not delete the coverage:

- `tests/test_send_web.py:118, 178-180, 198` : Mark sent, Open in mail, Move to front, Unschedule, Back to draft. Assert they are still **present in the HTML** (inside the More overflow), and that Back to draft is still absent on queued cards.
- `tests/test_outreach_web.py:228, 245, 249` : Log it, Mark sent, Back to draft on the Ready tab.
- `tests/test_learning_web.py:94` : "Retire" and the part titles.
- `tests/test_contact_page.py:160` : stays valid (C1 kept). Add an assertion that "copy email" is gone from the header and that the opt-out form is inside `details.more-box`.
- Add: a test that the Sent tab renders no `copy-btn`; one that a Replies row with a settled verdict has no Interested/Not interested buttons; one that the Learning example Pin/Exclude forms sit inside the details element.

## Work order (suggested commits, each green on its own)

1. `ai: ui: add the row-more overflow macro and style` (macro + CSS, no page uses it yet).
2. `ai: outreach: quiet the Ready and Scheduled cards` (O12-O20 and O11).
3. `ai: outreach: tidy Drafts, Replies and build form` (O3, O6, O8, O21-O25).
4. `ai: contact: drop duplicate copy, move Opted out to More` (C4, C5).
5. `ai: learning: fewer lesson and example buttons` (L5, L6).
6. Verify each with the demo folder (`.venv/bin/hermitcrm init /tmp/x --demo`) and by
   loading `/outreach` (all tabs), `/learning`, and a contact page in the browser;
   re-run the button count script below and record before/after in the commit message.

Button-count probe (paste in the browser console):

```
[...document.querySelectorAll('main button, main a.button, main summary.button')]
  .filter(b => b.getBoundingClientRect().width > 0).length
```

## Open questions for Gijs (defaults chosen so work can start)

1. **O13/O14/O15 with email sending on:** hide Copy, Open in mail, Log it and Mark sent behind More. Default: yes. Say so if you still send some email by hand.
2. **C5:** move Opted out off the contact header? Default: yes.
3. **O3:** collapse the build form by default? Default: yes, open automatically while a batch runs.
4. **L6:** are Pin/Exclude something you use? If never, they could go entirely. Default: keep behind the expander.
