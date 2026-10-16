# Part 04 · Phase 2: Outreach page, Ready list, reply-to-interest

Context: [00-overview](00-overview.md). Needs phase 1 (parts 02-03).

**Done when:** review a batch and a reply to interest end to end in the browser.

## Outreach page (new, in the nav next to Messages)

- **Top:** filter bar, draft type, channel (required), research level, batch
  size, "Preview" and "Build queue". The queue builds in the background; cards
  appear as they finish.
- **Tabs:** Replies to interest (first: that is where deals leak), Follow-ups,
  First touches, Ready, Skipped.
- **One card per contact:**
  - name, title, LinkedIn ↗; company, stage, fit, website ↗
  - flags (no country, unchecked disqualifier, possible duplicate)
  - findings with source links and a confidence dot; remove one or add your own
  - the draft (editable), its type and angle, which findings and proof it
    uses, the check results
  - buttons: **Mark ready**, **Regenerate** (optionally "stronger model"),
    **Skip** (with a reason), **Copy**
- **Ready** is the working list for sending by hand: copy button and the
  contact's links.

**Mark ready** changes the state and appends the findings used to the contact's
notes under a dated heading (`### Research 2026-10-16 (scrape)`, one line per
finding with its source), in the same commit. It does **not** log an
interaction; the person logs it as usual.

**Contact page:** a "Research & draft" button (with channel picker), and an
outreach card while an item is open for that contact.

## Reply-to-interest drafts

Source: an inbound reply that shows interest, from `followups.py` "replies
owed". The AI classifies the reply (no tools) and the person confirms.

Shape: the offer line, one proof line, "the first call is free, no pitch", and
one question. **No** time slot, booking link, price, or days per week. A meeting
is proposed only after they answer the question. Replies to interest stay
semi-automatic even in a later auto mode.

Example (English, approved shape; each folder keeps its own wording per
language in `MESSAGING.md`):

> Fair question. I work as your fractional Head of Sales: part-time, no minimum
> term. I build the sales playbook, coach your AEs and close the bigger deals
> with you, until your team can carry it. I've run sales teams in 5
> organisations. The first call is free and all about you, without a sales
> pitch. Where does it hurt most right now: pipeline, conversion or deal size?

Wording templates ship in `default_messages.toml` (EN/DE/NL/FR), neutral, with
the offer line as a slot; overridable in `messages.toml`.

## Tests

- web: the page renders on the demo folder; a card's buttons change only the
  state
- Mark ready appends findings to the contact notes deterministically, in the
  same commit
- "Mark ready" writes no interaction

## Open question

**Interest detection.** The AI classifies an inbound reply as interest and the
person confirms. Should an outcome value (e.g. `interested`) also be added to
`outcomes` in `config.toml`, so the radar can use it without AI?
