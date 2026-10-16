# Part 01 · Phase 0: the playbook (what the bot knows about you)

Context: [00-overview](00-overview.md).

**Done when:** the demo folder has a filled playbook; the readiness gate blocks
an empty one; an old `MESSAGING.md` upgrades byte for byte.

Revised 16 Oct 2026 after the maintainer's review of the first build: several
offers per folder, disqualifiers as two hard checks plus free text, Lessons,
drafting from a website or a document, voice from sent emails, a save bar that
stays in view.

## Why

A message works when it connects this person's likely problem to your offer,
with proof, in a tone that fits their culture and channel. Today Hermit knows
little of the seller: setup asks only for a name, and `default_messages.toml`
has gaps like `[your offer]` and `[the problem you solve]`. Without that
context any AI draft is generic.

## One home: `MESSAGING.md`

Every data folder already has `MESSAGING.md` ("Messaging playbook"); the agent
instructions tell AI agents to read it. It stays the only playbook.

- **Front matter (new, YAML):** what Python needs, per offer: name, offer
  line, ICP, hard disqualifiers, persona title lists.
- **Body:** the current general text (angles, slots, languages) stays; each
  offer gets a `# Offer: <name>` block with the seller sections below as `## `
  headings. The AI reads the body (for a draft: the general text plus that
  offer's block only); it never sees the front matter as instructions.
- **Existing folders:** `init` writes the file only when absent, so nothing
  changes by itself. Settings → Playbook and `hermitcrm playbook upgrade` offer
  to add the front matter (one offer, "My offer") and its block, keeping every
  existing line byte for byte, in one commit; idempotent. It is a data-folder
  file, not a record, so **not** a `migrations.py` migration. `hermitcrm check`
  reports a file without front matter as "not set up for the outreach bot" (a
  hint, not an error). A front matter of someone else's (no `offers:`) is left
  alone.
- **New folders** get the general text without the old "What worked" list
  (each offer has Lessons instead) and one empty offer. Old files keep theirs.

## Offers

An offer is one thing sold to one audience (founder coaching for companies
whose founder still sells; a team build-out for companies that already have
salespeople). Each offer is **complete on its own**: every section below is per
offer, and "Duplicate this offer" copies all of it. Chosen over a shared base
plus per-offer parts because it is the simplest model to read and edit; the
cost is that a change to, say, the voice is made per offer.

- **Picking the offer:** by ICP fit, in Python, on known fields (headcount,
  number of salespeople, country, industries as tags). An offer the company is
  outside of, or fails a hard disqualifier for, is left out; of the rest the
  most matches win; a tie (an empty field could not decide) asks the person.
  `playbook.pick_offer` returns the offer, why, the tie, and per left-out offer
  the reasons. The per-company override lives on the outreach card (part 04),
  not on the company.
- **Statistics:** every message the bot proposes records its offer (`offer` on
  the interaction, with `angle`, part 02), so the Messages statistics can be
  read per offer.
- **One pipeline per folder:** a separate business still gets a second data
  folder.

## Sections

| Section | Contents | Used by |
|---|---|---|
| Offer (front matter `offer_line` + body) | What you sell in one sentence (every reply to interest must contain it); customer outcome; engagement model; what you do not do | Drafter, `clean_answer` |
| ICP (front matter) | Industries, FTE range, number of salespeople, countries, funding stage, positive signals | Picking the offer, Select (fit, sort), Drafter |
| Disqualifiers (front matter + body) | Hard: `title_present`, `tag_present` (Select **excludes**). Everything else as free text in the body, which the AI weighs and the person confirms | Select, Critic |
| Personas (front matter + body) | Per buyer type: matching titles, top 2-3 pains, what they care about / ignore | Drafter picks persona from title and role |
| Proof | Customer outcomes, numbers, case lines. The AI may cite **only** these | Drafter, `clean_answer` |
| Why you | Differentiators vs. the usual alternative (hire, agency, do nothing) | Drafter |
| Voice | Tone, words used / never used, sign-off, du/Sie | Drafter, Critic |
| Channels | Per channel: first-touch purpose, length, call to action | Drafter, Critic |
| Don'ts | No fake familiarity, no "I hope this finds you well", no claims without proof, never name competitors | Critic (mechanical ones also in `clean_answer`) |
| Lessons | `### Worked`, `### Didn't work`, `### Still testing` | Drafter, Critic; filled by hand now, from sent-vs-proposed comparisons in part 06 |

Example front matter (fictional fractional sales leadership business):

```yaml
offers:
  - name: Founder coaching
    offer_line: "I coach founders who still do all the selling."
    icp:
      industries: [b2b-saas, ai]
      fte: [5, 40]
      salespeople: [0, 0]
      countries: [DE, AT, CH, NL]
      funding: [bootstrapped, seed]
      signals: [founder-still-sells]
    disqualifiers:
      - tag_present: [customer, do-not-contact]
    personas:
      founder: {titles: ["CEO", "Founder", "Co-Founder", "Managing Director"]}
  - name: Scaling the sales team
    offer_line: "I work as your fractional Head of Sales: part-time, no minimum term."
    icp: {fte: [10, 150], salespeople: [1, 8], countries: [DE, AT, CH, NL]}
    disqualifiers:
      - title_present: ["Head of Sales", "VP Sales", "CRO", "Sales Director"]
    personas:
      founder: {titles: ["CEO", "Founder"]}
      sales-lead: {titles: ["Sales Lead", "Senior AE", "Account Executive"]}
```

Hard disqualifiers are a **small fixed vocabulary** evaluated in Python on known
fields, so `check` can validate them. An empty field cannot decide: the company
stays in and the card says "not checked: no contact titles". Size and number of
salespeople are ICP ranges, not disqualifiers.

The default `messaging.py` angles stay. Filling the non-AI templates' gaps
(`[your offer]`) from the playbook needs a short noun phrase per offer, not the
offer line (a sentence); left for later.

## Getting it filled

- **Settings → Playbook:** one tab per offer ("+ New offer": empty or a copy;
  "Duplicate this offer"; "Delete this offer", never the last one), one box per
  section with examples beside each, a completeness meter per offer, and a save
  bar that stays at the bottom of the screen with "Unsaved changes", a warning
  before leaving with unsaved edits, and Cmd/Ctrl+S.
- **"Draft it from my website or a document":** a website address (home page
  plus up to four same-site pages whose path looks like About, Services,
  Pricing, Customers, in the app's languages), an uploaded PDF (pypdf, a new
  dependency agreed 16 Oct), Word .docx (standard library) or text file, or
  pasted text. The AI CLI (no tools) proposes each section of the current
  offer; the person edits and saves. As with Enrich, nothing is saved without
  confirmation.
- **"Learn my voice from my sent emails":** the most recent outbound emails
  with a body (quoted thread cut off) go to the AI CLI (no tools), which
  proposes the Voice section. Nothing is saved without confirmation.
- **Setup:** `hermitcrm init` and the welcome flow get an optional 4th step,
  "Your offer": what you sell (offer line), to whom, one customer result; it
  fills the first offer.
- **Readiness gate:** an offer is ready with offer line, ICP, one persona and
  one proof line. The Outreach page and `hermitcrm outreach build` refuse to
  run until at least one offer is ready (`playbook.require_ready`), then use
  the ready offers only; the page says per offer what is missing and links to
  the form.
- `hermitcrm help playbook` documents the format for AI agents; `hermitcrm
  check` validates the front matter; `hermitcrm playbook` reports per offer.

## Later (not phase 0)

- Compare the draft the bot proposed with the message actually sent, and turn
  the difference into Lessons (part 06; needs stored drafts from part 03).

## Tests

- front matter validation; one `offer_line` per offer (a list refused); unique
  offer names; disqualifier vocabulary; the readiness gate (none ready, one of
  two ready, a named offer); persona matching by title; picking the offer (fit,
  left out, tie)
- offers added, copied and deleted (not the last); the form round trip writes
  the same bytes twice
- `playbook upgrade` keeps an existing `MESSAGING.md` byte for byte and is
  idempotent
- website, PDF, Word and text sources; voice from sent emails; the web page
  writes one commit per save and nothing on a proposal
