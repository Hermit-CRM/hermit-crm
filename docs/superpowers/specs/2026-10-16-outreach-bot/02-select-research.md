# Part 02 · Phase 1a: angle field, select, research, contact brief

Context: [00-overview](00-overview.md). Needs part 01 (playbook). Phase 1
continues in [03-draft-check-store](03-draft-check-store.md).

**Phase 1 done when:** `hermitcrm outreach build --where 'stage=prospect'
--channel email --limit 3` writes 3 checked items on the demo folder.

## Angle on interactions (ships first)

Manual messages and bot items must be comparable from day one, so interactions
get an optional `angle` key:

- values: `scale`, `unblock`, `hook`, `bridge`, `decline`, `custom`, or empty
  (unknown); same values as the Drafter's `angle` output
- placed after `subject` in key order; omitted when empty, so existing files are
  unchanged when rewritten
- shown and filterable on the Messages tab; settable in the log form and in bulk
  with `hermitcrm set`
- a new numbered migration in `migrations.py` (idempotent, front matter only: it
  normalises a hand-written `angle` value, touches nothing else) plus tests

## Select

- **Batch:** a list filter (same syntax as the Contacts page and `hermitcrm set
  --where`), one channel, a draft type, a batch size (default 10).
- **Button:** "Research & draft" on the contact page, with a channel picker
  (UI in phase 2).
- **Radar:** replies to interest and follow-ups come from `followups.py`
  (phases 2-3).
- **Order:** fit score, highest first. The preview shows how many high-fit
  prospects (fit ≥ 65 by default) are untouched.
- **Excluded:** companies hit by a playbook disqualifier (preview lists them
  with the rule that hit); contacts the channel cannot reach (email needs
  `email`, LinkedIn needs `linkedin`); contacts with an open outreach item;
  contacts messaged in the last `outreach_cooldown_days` (default 30);
  companies in a closed or parked stage; anything tagged `do-not-contact`.
- **Company duplicates:** "one open item" applies per company too, including
  likely duplicates: same website domain, or names equal after slug
  normalisation and dropping suffixes like `-ai`, `-gmbh`, `-hq`
  (`acme-robotics` / `acme-robotics-ai`). The preview flags the pair and links
  to Merge.
- **Flags, not exclusions:** no country, no headcount, no `ae_count`. The card
  says what is missing and which rule could not be checked.
- **Preview:** no AI, no writes, like routines' preview.

## Research: the `scrape` level

`outreach_research = "scrape" | "ai-web"` in `config.toml` (default `scrape`);
the UI can override per run. `ai-web` is part 05; Clay would be a third
Researcher later.

| Level | What runs | Cost | Safety |
|---|---|---|---|
| `scrape` | `scrape.py` on the website and LinkedIn page, then the AI summarises with no tools | free + one small AI call | as today |

Every level returns the same `Research`:

```python
@dataclass
class Finding:
    text: str          # "Opened a Munich office in Sept 2026"
    source: str        # URL, or "crm" for something we already knew
    kind: str          # company | person | trigger (hiring, funding, launch...)
    confidence: str    # high | medium | low

@dataclass
class Research:
    findings: list[Finding]
    linkedin_url: str          # proposed if the contact has none (person confirms)
    website_url: str           # proposed if the company has none
    level: str                 # scrape | ai-web
```

- A finding without a source is not shown as fact (dropped).
- The drafter uses only `high` / `medium` findings.
- A finding older than ~90 days is marked **stale** and is not used as the
  opening line (triggers age fast).
- Nothing usable found → the card says so and the draft falls back to the
  `messaging.py` angles, gaps marked `[ ]`.
- Proposed LinkedIn URL, website or country: shown Enrich-style, written only
  when the person accepts.

## The contact brief

Python (not the AI browsing freely) builds one compact brief per contact:

| Input | Source |
|---|---|
| Persona | Title matched against playbook personas; role (champion, decision-maker...) |
| Seniority and tenure | Title; LinkedIn profile text if captured |
| What they said or posted | The bookmarklet's "Add to research" (part 05); the reliable route, since LinkedIn blocks anonymous fetches |
| Company situation | Research findings, signals (growing, hiring...), `fte_estimate`, `ae_count`, `product_oneliner`, stage |
| Relationship so far | Last interactions with person and company (summaries, not threads), so a second touch is not written as a first |
| Culture and language | See below. No country → flagged on the card ("no country: English and default culture used"), never guessed |
| ICP fit | Fit score and which ICP points matched |

### Culture

`default_messages.toml` gets a `[culture.<country>]` table, overridable in
`messages.toml`:

- language (exists today)
- formality: German first contact uses `du` (as today's templates do); Dutch
  directness; French politeness formulas. The playbook's Voice can override
  per folder
- greeting and sign-off norms; first name vs title
- how direct the call to action can be

These are starting points; the card shows which norms were applied so the
person can correct them.

## Tests

- select: the filter; fit-score order; each disqualifier excludes, and an empty
  field leaves the company in with a flag; channel-data check; cooldown;
  closed/parked stages; `do-not-contact`; one open item per contact and per
  company, including likely duplicates
- `ScrapeResearcher` with a fake fetcher / fake CLI; findings without a source
  are dropped
- `angle` migration: idempotent, front matter only, interaction bodies byte for
  byte; files without `angle` are unchanged

## Open question

**Fit score source.** `fit_score` comes from the source list today. Should the
bot compute its own fit from the playbook ICP when the field is empty, or only
show "no fit score"?
