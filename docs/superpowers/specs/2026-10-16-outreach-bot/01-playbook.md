# Part 01 · Phase 0: the playbook (what the bot knows about you)

Context: [00-overview](00-overview.md).

**Done when:** the demo folder has a filled playbook; the readiness gate blocks
an empty one; an old `MESSAGING.md` upgrades byte for byte.

## Why

A message works when it connects this person's likely problem to your offer,
with proof, in a tone that fits their culture and channel. Today Hermit knows
little of the seller: setup asks only for a name, and `default_messages.toml`
has gaps like `[your offer]` and `[the problem you solve]`. Without that
context any AI draft is generic.

## One home: `MESSAGING.md`

Every data folder already has `MESSAGING.md` ("Messaging playbook"); the agent
instructions tell AI agents to read it. It stays the only playbook.

- **Front matter (new, YAML):** what Python needs: ICP, disqualifiers, persona
  title lists, offer line.
- **Body:** current text (angles, slots, languages, "What worked") stays and
  gains the seller sections below as headings. The AI reads the body; it never
  sees the front matter as instructions.
- **Existing folders:** `init` writes the file only when absent, so nothing
  changes by itself. Settings → Playbook and `hermitcrm playbook upgrade` offer
  to add the front matter and missing headings, keeping every existing line byte
  for byte, in one commit; idempotent. It is a data-folder file, not a record,
  so **not** a `migrations.py` migration. `hermitcrm check` reports a file
  without front matter as "not set up for the outreach bot" (a hint, not an
  error).

## Sections

| Section | Contents | Used by |
|---|---|---|
| Offer (front matter `offer_line` + body) | What you sell in one sentence (every reply to interest must contain it); customer outcome; engagement model; what you do not do | Drafter, `clean_answer` |
| ICP (front matter) | Industries, FTE range, number of salespeople, countries, funding stage, good-moment signals | Select (fit, sort), Drafter |
| Disqualifiers (front matter) | Hard reasons a company is not a prospect; Select **excludes**, not only warns | Select |
| Personas (front matter + body) | Per buyer type: matching titles, top 2-3 pains, what they care about / ignore | Drafter picks persona from title and role |
| Proof | Customer outcomes, numbers, case lines. The AI may cite **only** these | Drafter, `clean_answer` |
| Why you | Differentiators vs. the usual alternative (hire, agency, do nothing) | Drafter |
| Voice | Tone, words used / never used, sign-off, du/Sie | Drafter, Critic |
| Channels | Per channel: first-touch purpose, length, call to action | Drafter, Critic |
| Don'ts | No fake familiarity, no "I hope this finds you well", no claims without proof, never name competitors | Critic (mechanical ones also in `clean_answer`) |

Example front matter (fictional fractional sales leadership offer):

```yaml
offer_line: "I work as your fractional Head of Sales: part-time, no minimum term."
icp:
  industries: [b2b-saas, ai]
  fte: [10, 50]
  salespeople: [1, 5]
  countries: [DE, AT, CH, NL, SE, DK, NO]
  funding: [seed, series-a]
  signals: [founder-still-sells, no-sales-leader, hiring-sales]
disqualifiers:
  - fte_over: 100
  - title_present: ["Head of Sales", "VP Sales", "CRO", "Sales Director"]
  - no_salespeople: true          # ae_count == 0
personas:
  founder: {titles: ["CEO", "Founder", "Co-Founder", "Managing Director"]}
  sales-lead: {titles: ["Sales Lead", "Senior AE", "Account Executive"]}
```

Disqualifiers are a **small fixed vocabulary** evaluated in Python on known
fields (`fte_estimate`, `ae_count`, contact titles at the company, tags), so
`check` can validate them. An empty field cannot decide: the company stays in
and the card says "not checked: no headcount".

The default `messaging.py` angles stay. A filled playbook's offer line and proof
fill the template gaps, so non-AI drafts improve too.

## One offer per data folder

One folder = one offer, one playbook, one pipeline, one set of Messages
statistics. Mixing breaks the statistics (the review found a product pitch and
a referral ask counted inside a consulting pipeline). The bot does not detect a
second offer in prose; it enforces exactly one `offer_line` (`check` refuses a
list: "one offer per data folder; use a second folder for a second offer").
Several offers per folder is a possible later extension, not designed here.
`INSTALL.md` / the welcome page say when a second folder is useful; `init`
already creates any number of folders.

## Getting it filled

- **Settings → Playbook:** one box per section, examples beside each, a
  completeness meter. Reads and writes `MESSAGING.md`.
- **"Draft it from my website":** user pastes their website text, LinkedIn
  About or a sales deck; the AI CLI (no tools) proposes each section; the person
  edits and saves. As with Enrich, nothing is saved without confirmation.
- **Setup:** `hermitcrm init` and the welcome flow get an optional 4th step,
  "Your offer": what you sell (offer line), to whom, one customer result.
- **Readiness gate:** the Outreach page and `hermitcrm outreach build` refuse to
  run until offer line, ICP, one persona and one proof line are filled; the
  page says what is missing and links to the form.
- `hermitcrm help playbook` documents the format for AI agents; `hermitcrm
  check` validates the front matter.

## Tests

- front matter validation; one `offer_line` (a list refused); disqualifier
  vocabulary; the readiness gate; persona matching by title
- `playbook upgrade` keeps an existing `MESSAGING.md` byte for byte and is
  idempotent
