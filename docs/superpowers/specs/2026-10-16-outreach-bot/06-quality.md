# Part 06 · Phase 4: data cleanup, quality report, learning

Context: [00-overview](00-overview.md). Uses the per-item records from part 03.

**Done when:** numbers show after a week of use on a cleaned folder.

Full auto depends on knowing whether semi-auto works, and the baseline is only
as good as the data.

## Prerequisites: clean data

- **Country.** Companies without a country get English and default culture. The
  Companies list gets a "no country" filter (the card already flags it).
  Filling country is a listed step before trusting results per language.
- **Mislogged interactions** skew reply rates (notes logged as LinkedIn
  messages, a reply stored inside an outgoing record, duplicate replies,
  leftover demo-sample messages). `hermitcrm check` warns on the obvious
  cases:
  - an outbound body containing a quoted inbound header (`On ... wrote:`,
    `Am ... schrieb`)
  - two inbound interactions from the same contact with identical bodies
  - a message on a sample company in a non-demo folder
- **Duplicate companies.** Same rule as Select's (part 02), listed in `check`
  with a link to Merge.

## Quality report

A small "Outreach quality" section in Reports: ready rate, median edit size,
most common skip reasons, reply rate.

**Small numbers.** A grid of angle × persona × channel × language is mostly
empty. The report shows **one dimension at a time** (selector: angle, persona,
channel, language, draft type) and hides a cell until it has ≥ 10 results,
showing "n = 4, too few" instead.

## Learning from results

- **Examples.** A message that got a reply can be saved ("Use as example"). The
  drafter gets the 2-3 closest examples (same persona, channel, language). Only
  your own sent messages become examples.
- **"What was wrong?"** When the text marked ready differs a lot from the draft,
  the card asks (wrong tone, wrong pain, too long, bad finding). Answers appear
  in the quality report and point to the playbook section to fix.

## Tests

- report: a cell under 10 results is hidden; one dimension at a time
- `check`: the mislogged-interaction and duplicate-company warnings
