# Companies

`/companies` lists every company; `/companies/<slug>` is the account page with its fields, contacts, drafts, merge and timeline.

## The table

Columns: name, country, stage, source, my score, fit score, FTE, tags, last
touch, next step, due, plus website and LinkedIn links. The search box in the
nav matches company name, tags, contact names and contact emails. Each column
has a filter control (see the `?` next to Filter for the syntax) and sort
arrows. Temp-disqualified companies are hidden until you click "Show temp
disqualified (N)" or filter on that stage.

New companies come from `/companies/new` (name is required; website, LinkedIn,
country, source, stage, value, next step, tags, notes are optional), from
[Import](/help/import), or from the BCC and calendar imports on the Settings
page.

## The company page

- The header: one-liner, website and LinkedIn links, stage with days in stage,
  last touch, scores, FTE and AE count, country with an Add/Change control,
  **Enrich** (when an AI CLI is available) and **Fetch from URL**.
- **Disqualify** and **Temp disqualify** (with a reason and, for temp, an
  "until" date); **Requalify** brings a disqualified company back to prospect.
- The next step with its status tag, **Mark done** / **Reopen** and the Google
  Calendar link.
- **Log an interaction**: the quick-add form with the most recently touched
  contact preselected.
- **Company**: every field in an edit form. Setting the stage to lost needs a
  reason; leaving lost, disqualified or temp-disqualified clears it. Below the
  form: slug, created, updated, stage changed, and the stage history collapsed.
- **Contacts** with title, role, email and LinkedIn, and a New contact link.
- **Message drafts** for the preselected contact (see [Contacts](/help/contacts)).
- **Merge**: pick another company to compare and merge into this one.
- **Timeline**: every interaction across all contacts, newest first, bodies
  collapsed.

Edits made outside the app (by hand or by an agent) show up on the next page
view: the company's folder is re-read for every request.

## Stages

`prospect`, `reached-out`, `discovery`, `offer` are open; `won`, `lost` and
`disqualified` are closed; `temp-disqualified` is parked: off the board and
the table, back to prospect by itself on `requalify_on`. Every stage change
appends to `stage_history` and sets `stage_changed` to today.

## Country and language

`country` is an ISO 3166-1 alpha-2 code (`UK` and `USA` are accepted and
stored as `GB` and `US`). It also picks the draft language: German for DE, AT,
CH and LI, Dutch for NL, French for FR, LU and MC, English otherwise.

For **BE** the record decides between Dutch and French. Evidence, strongest
first: previous mails and messages (their replies weigh most, then yours), a
`/nl/` or `/fr/` website (or `nl.`/`fr.` subdomain), a postcode outside
Brussels (Flanders: Dutch; Wallonia: French; Brussels 1000-1299 counts for
neither), then the language of contact titles, notes and the product line.
One side needs at least twice the weight of the other; otherwise the drafts
are English. To force a language, add a `/nl/` or `/fr/` website or a note
with the address.

Related: [Pipeline](/help/pipeline), [Contacts](/help/contacts), [Interactions](/help/interactions), [Merge](/help/merge), [Enrich](/help/enrich), [Data format](/help/data-format)
