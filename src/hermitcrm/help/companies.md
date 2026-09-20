# Companies

`/companies` lists every company; `/companies/<slug>` is the account page with its fields, contacts, drafts, merge and timeline.

## The table

Columns: name, country, stage, source, any field of your own that asked for
this table, tags, last touch, next step, due, plus website and LinkedIn links. The search box in the
nav matches company name, tags, contact names and contact emails. Each column
has a filter control (see the `?` next to Filter for the syntax) and sort
arrows. Temp-disqualified companies are hidden until you click "Show temp
disqualified (N)" or filter on that stage.

New companies come from `/companies/new` (name is required; website, LinkedIn,
country, source, stage, value, next step, tags, notes are optional), from
[Import](/help/import), or from the BCC and calendar imports on the Settings
page.

## The sample account

A new folder can load one made-up company to look at: **Look at a sample
account** on the empty home page or on Getting started, or `hermitcrm sample
add`. It is Northwind Robotics, with two people, a message and its reply, a
meeting, a deal at offer with its stage history, a next step and tasks. Its
`company.md` carries `sample: true`, and a bar at the top of every page says
it is there. The Getting started steps do not count it.

**Remove it** in that bar (or `hermitcrm sample remove`) lists what goes and
deletes it in one commit. Only companies with `sample: true` can be removed
this way; delete that line by hand and the company is yours to keep. Hermit
CRM has no other way to delete a company: you disqualify it instead.

## The company page

- The header, two lines: one-liner, website and LinkedIn links, stage with days
  in stage, last touch, and any field of your own; then **Enrich** (when an AI
  CLI is available) and **Fetch from URL**. Country is in the edit form below,
  not the header.
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
- **Tasks**: the next step with its due date and status, **Mark done** /
  **Reopen**, the Google Calendar link, and a form to write a new next step.
  A rewritten next step starts open again.
- **Merge**: pick another company to compare and merge into this one.
- **Timeline**: every interaction across all contacts, newest first, bodies
  collapsed.

Edits made outside the app (by hand or by an agent) show up on the next page
view: the company's folder is re-read for every request.

## Tasks and the next step

Two different things, deliberately.

The **next step** is the one task that decides where the deal stands. There is
exactly one per company, it shows on the board card, in PIPELINE.md and on the
calendar, and rewriting it starts a new one.

**Tasks** are everything else you owe that account: a list, with a due date and
a done flag each. They live on the company, or on one of its contacts when the
thing you owe is owed to a person. A contact's tasks show on their own page and,
grouped under their name, on the company's. Add one from either page or from
the calendar, where every open task appears on its due date beside the next
steps.

Deleting a contact takes their tasks with them, and says how many are open
before it does. Merging two records keeps both lists: a task is work you still
owe, so there is no side to pick.

## Stages

`prospect`, `engaged`, `discovery`, `offer` are open; `won`, `lost` and
`disqualified` are closed; `temp-disqualified` is parked: off the board and
the table, back to prospect by itself on `requalify_on`. Every stage change
appends to `stage_history` and sets `stage_changed` to today. The first
interaction logged on a prospect moves it to engaged. Before format 4 the
engaged stage was called `reached-out`; migration 4 renamed it, and
`reached-out` is still accepted as input (imports, CLI).

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
