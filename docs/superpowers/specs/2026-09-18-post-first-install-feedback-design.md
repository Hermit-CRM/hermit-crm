# Design: the first outside install, and what it exposed

Date: 2026-09-18. Source: twelve observations from the first person other than
the author to install Hermit CRM and use it. The install itself worked; every
item below is about what they met afterwards.

This is one document covering seven shippable projects. Each has its own
section, its own PR and its own tests. They are ordered by dependency, not by
importance.

---

## 1. Custom fields replace the four bespoke ones

### The problem

`my_score`, `fit_score`, `fte_estimate` and `ae_count` are one person's sales
method wearing the clothes of a product. They are typed attributes on
`Company` (`models.py:361`) and they reach into: `store.py` (create, update,
copy fields), `importer.py` (three synonym tables, `INT_FIELDS`,
`COMPANY_ONLY`), `web.py` (board and companies columns, form fields, two POST
handlers), `macros.html`, `company.html`, `companies.html`, `enrich.py` (the
AI schema), `scrape.py` (proposals), `messaging.py` (draft sentence choice),
and `help/data-format.md`. A stranger meets all four before they meet a
feature they asked for.

### What already exists

Every model carries `extra: dict` (`models.py:292`, `319`, `376`), and
`_with_extra` / `_extra` round-trip any front-matter key the app does not
recognise. Unknown fields already survive a read/write cycle untouched. What
is missing is not storage. It is a schema: a name, a type, a label, and a
decision about which views show it.

That is the whole reason this is affordable. In a CRM with a database, adding
a user-defined field is a migration. Here it is a display concern.

### The design

A new file in the data folder, `fields.toml`, beside `messages.toml`:

```toml
[[field]]
key = "fit_score"          # the front-matter key, also the filter key
label = "fit"              # what the UI calls it
type = "number"            # number | text | date | select
applies_to = "company"     # company | contact
help = "0 to 100"          # optional, shown under the input
show_in = ["board", "companies", "detail"]   # where the column appears
min = 0                    # number only
max = 100

[[field]]
key = "segment"
label = "segment"
type = "select"
applies_to = "company"
options = ["enterprise", "mid-market", "smb"]
show_in = ["companies", "detail"]
```

`fields.toml` is a separate file rather than a section of `config.toml`
because `setup.set_config_values` (`setup.py:62`) is a line-based writer that
preserves comments and can only set scalar keys. Teaching it TOML array-of-
tables is more work than a second file, and `messages.toml` already sets the
precedent that a folder-level customisation lives in its own file.

**Loading.** `fields.load(root) -> list[FieldDef]`, cached on the store and
invalidated by `/reload` like everything else. Unknown `type` or a duplicate
`key` is a `check` problem with a file and a line, not an exception.

**Reading and writing values.** Custom values live in `Company.extra` /
`Contact.extra`, which is where they already go. `FieldDef.coerce(raw)` turns
a form string into the stored type and raises `ValidationError` with the
field's label in the message. `FieldDef.display(value)` goes the other way.

**Forms.** `macros.html` grows a `custom_fields(defs, values, errors)` macro
that renders one input per definition, typed: `number` gets `inputmode`, `date`
gets `type=date`, `select` gets a `<select>`. The four hard-coded inputs at
`macros.html:155-158` are deleted.

**Filters and columns.** `filters.Column` already carries a `getter`
(`filters.py:29`), so a custom field becomes
`Column(key, label, kind, getter=lambda c: c.extra.get(key))` with no change
to the filter engine. The operator syntax (`!foo`, `=foo`, `>5`, `-`, `*`)
works on them for free.

**Importer.** The synonym tables lose the four entries. `plan_import` gains
custom-field keys as valid targets, so a spreadsheet column can be mapped to
one, and `detect_mode` learns them.

**Enrich.** `enrich.py`'s `FIELDS` schema loses `fte_estimate` and `ae_count`.
A custom field can opt in with `enrich = true` plus a `description`, which is
exactly what the AI schema needs, so users can have the model fill their own
fields. That is a strictly better feature than the two it replaces.

**Settings.** A "Fields" section with two ways in:
- one at a time: a small form (key, label, type, applies to, options, where
  it shows), with a live preview of the input it will produce;
- in batch: a textarea that accepts TOML (the `fields.toml` format above) or
  a pasted two-column list `label<TAB>type`, previewed before it is written,
  in the same shape as the existing import preview.

Deleting a definition asks what to do with the data: keep the values in the
files (they stay in `extra`, invisible) or strip them. Never silently delete.

**Migration.** This one does not fit the existing framework, which is worth
stating plainly. `Migration` is `(version, title, glob, apply(meta) -> meta)`
(`migrations.py:115`) and `_run` walks files and rewrites front matter. It has
no way to create a folder-level file. So `Migration` gains an optional
`folder` step, `folder(data_dir) -> list[str]`, run after that version's file
pass and reporting the paths it wrote so `dry_run` can list them like any
other change.

`m5_custom_fields` then needs no per-file `apply` at all: the four keys stay
exactly where they are in the front matter, byte for byte, and are simply read
from `extra` instead of from typed attributes. Its `folder` step scans company
files for the four keys and, when any are present, writes a `fields.toml`
giving them their current labels ("my score", "fit", "FTE estimate", "AE
count"), types and `show_in` values matching where they appear today. The
author's own folder therefore looks and behaves unchanged after upgrading. A
folder created after this change has no `fields.toml` and shows no custom
fields anywhere.

This is the riskiest change in the document: it is the first migration that
writes something other than front matter, and it runs automatically before any
command. It ships with a test that asserts the company files are untouched at
the byte level.

### Scope

All three record types: companies, contacts and interactions. `extra` already
exists on each (`models.py:292`, `319`, `376`), so the storage question is
settled for all of them.

Interactions carry one extra rule, from the data folder's own instructions:
**never rewrite an interaction body; it is the record.** The custom-field
editor therefore writes front matter only, and the interaction edit form keeps
the body in a field of its own that custom fields cannot reach. A test asserts
that saving a custom field on an interaction leaves the body byte for byte.

There is already a precedent for a user-defined value on an interaction:
`outcome` is an enum whose options live in `config.toml` and are edited at
`/settings/outcomes` (`setup.py:437`). Custom fields are the general case of
that, and a `select` field is the same shape. `outcome` is *not* converted
here — it is load-bearing for reports and the messages view — but the new
editor should be built so that converting it later is a data change rather
than a rewrite.

Interaction fields are worth having for the things a channel does not capture:
which product was discussed, who else was in the room, the objection that came
up. `show_in` accepts `messages` for them, so they become filterable columns
on the Messages view (`web.py:183`), which is the one place interactions are
already listed with the filter engine attached.

---

## 2. The drafts engine stops hard-coding field names

### The problem

`messaging.py:230` reads `company.fte_estimate` and `company.ae_count` to pick
which sentence a draft uses, via `fte_number()` and `next_hurdle()`. Once
those fields are user-defined, that code refers to something a new install
does not have.

### The design

Two parts, per the decision to take both.

**Templates read any field by name.** `messages.toml` slots are extended so a
template can write `{fit_score}` or `{segment}` and get the value of any
field, built-in or custom. A slot whose field is empty or undefined falls back
to a sibling line declared in the template, which is what `team.known` /
`team.unknown` already does by hand at `messaging.py:248`. The FTE hurdle
logic (`fte_number`, `next_hurdle`) stays in code but is fed by whichever
field is configured, not by an attribute name.

**Settings chooses which fields feed drafts.** A "Fields used for messaging"
control lists every available field with a checkbox, plus a mapping for the
two special roles the playbook understands (team size, rep count). Unchecked
fields are simply not offered to templates. This keeps the author's drafts
identical after migration, and gives a new user an explicit place to say
"score my accounts on X and mention it".

`default_messages.toml` ships with no team-size sentence. The author's
`messages.toml` keeps his.

---

## 3. Extension: capture a contact, not only a company

### The problem

Reported verbatim: `https://www.linkedin.com/in/diegomangabeira/` produced a
*company* form. And the oneliner it proposed was the LinkedIn
`og:description`, which for a person is a headline followed by
`· Experience: … · Education: … · 500+ connections`.

Neither is a parser bug. `scrape.py:198` only ever matches
`linkedin.com/company/`; nothing in the codebase recognises `/in/`.
`capture.from_url()` returns a `Capture` whose `values` are a company form
(`capture.py:44`). The contact path was never written. `_oneliner_from()`
(`scrape.py:253`) was built for a company's description and is being handed a
person's.

### The design

**Detection.** `capture.kind(url) -> "person" | "company"`. A person is
`linkedin.com/in/…`, an `xing.com/profile/…`, or a page whose structured data
declares `@type: Person`. Everything else is a company.

**A capture form with two halves.** For a person URL:
- *Contact*: name, title (from the headline, with the `· Experience:` tail and
  the follower count stripped), email if the page offers one, LinkedIn URL.
- *Company*: a search box over existing companies, prefilled with the best
  guess from the headline's employer, with "create a new company" as the
  alternative and the scraped company fields shown when that is chosen.

Nothing is written until the form is submitted, and the company link is always
visible before it is made. Capturing a person whose company is already in the
CRM adds a contact to it rather than creating a second company, which is what
`find_existing()` already does for company URLs.

**The oneliner.** `_oneliner_from()` learns the person case and returns the
headline only, into the contact's title, never into `product_oneliner`. For
company pages it gains the same cleanup: drop trailing
`· Experience:`/`· Education:`/`· N connections` segments and anything after
the first sentence when the description is a LinkedIn boilerplate string.
A company captured from a person's page gets no oneliner rather than a bad
one; `enrich` is the way to fill it.

**The rename.** Nav item, page heading, route (`/capture` → `/extension`, with
the old path redirecting), help topic `capture.md` → `extension.md`, and the
bookmarklet described as the install step. No manifest, no store, no packaged
extension: that becomes its own project once this works.

---

## 4. Tasks: more than one per company

### The problem

A company holds exactly one task: `next_step` plus `next_step_due`
(`web.py:1217`). A "create task" form on the calendar would therefore
overwrite whatever was already there, silently. The request is for real tasks,
so the model changes.

### The design

`Company.tasks: list[Task]`, written to front matter as a YAML list:

```yaml
tasks:
  - text: send the DORA one-pager
    due: 2026-09-24
    done: false
  - text: check whether their audit landed
    due: 2026-10-08
    done: false
```

`next_step` and `next_step_due` stay exactly as they are and keep driving the
pipeline, PIPELINE.md, the board cards and `silent_days`. The relationship is
explicit: **the next step is the one task that decides the deal's state**;
tasks are everything else you owe that account. One is the pipeline, the other
is the to-do list. Promoting a task to next step is a button.

**Tasks on a contact.** A task about a person lives in that person's file:
`contacts/<slug>.md` gets the same `tasks:` list. Two reasons to put it there
rather than tagging a company task with a contact slug. Deleting or merging
the contact then carries its tasks with it automatically, instead of leaving
dangling references inside `company.md`. And it keeps the rule the whole data
folder runs on: the record about a thing lives in that thing's file.

Consequences that have to be handled rather than discovered:

- `merge_contacts` (`web.py:1323`) merges field by field, with the form
  choosing a winner per field. Task lists are not a field you choose between:
  the merge **concatenates** both lists, and the merge preview says so instead
  of offering a radio button.
- Deleting a contact (`web.py:1497`) deletes its tasks. When any are open, the
  confirmation names how many, rather than removing them quietly.
- Contacts do **not** get a `next_step`. The pipeline stays company-level;
  a contact task is something you owe a person, never a deal's state.
- A contact task displays with its account attached — "Ines Vega (Harbour
  Light Labs) — send the one-pager" — because on the calendar the account is
  what makes the row make sense.

**Store.** `add_task`, `complete_task`, `delete_task`, each taking an optional
contact slug and each a commit in the existing style (`company: <slug> task
added`, `contact: <cslug> task added`).

**Calendar.** A "New task" form: company picker, an optional contact picker
narrowed to that company's contacts, text, due date. Tasks render on their due
date alongside events, with a checkbox that completes them in place. Overdue
tasks surface in the Today section that `/today` already redirects to.
Collecting them costs nothing extra: the store already holds every company
with its contacts nested, so gathering both lists is a walk over memory.

**Company page.** The existing Tasks section lists the account's own tasks
with the next step called out at the top, then its contacts' tasks grouped by
person. The contact page lists only that person's.

**Migration.** Nothing to migrate, for either file type: a file without
`tasks:` reads as an empty list, and `extra` would have preserved the key
anyway had it been there.

---

## 5. Home is not the pipeline

### The problem

Two things reported together: the Pipeline page is confusing on a fresh
install (it shows "import a spreadsheet, add a company, set up BCC capture" —
an empty board pretending to be an onboarding screen), and clicking the logo
goes to the same place as the Pipeline nav item, so the product has no home.

### The design

The board moves to `/pipeline` and gets its own nav entry. `/` becomes the
home page and the logo points at it. Home shows, in order:

1. **What needs doing** — overdue and due-today tasks, the follow-up radar
   (`followups.radar`, already built), next steps due this week.
2. **How it is going** — this month's activity, stage movements, and the
   funnel, from `reports.py`, as numbers with a link to the full report.
3. **What this thing does** — a grid of the product areas (Pipeline, Calendar,
   Companies, Contacts, Messages, Extension, Reports, Ask the Hermit), each
   with one sentence saying what it is for and a link. This is the part that
   answers "what am I looking at" for a new user, and it stays useful later as
   navigation.

On an empty folder the first two sections collapse into the walkthrough's
first steps rather than showing zeroes.

The empty-state advice currently on the board is deleted from there; it lives
in the walkthrough now.

---

## 6. The walkthrough

### The problem

There is none. A new user's first screen is an empty board. The feedback names
the two topics that most need explaining: BCC capture (how it works, and
sensible defaults per mail provider) and the filter syntax (`!text` is
undocumented anywhere a user will look).

### The design

Both forms, as decided: a page that tracks real state, and a tour that points
at the actual interface.

**`/welcome`** — ten steps, server-rendered, permanently linked from Help,
shown automatically on first launch until dismissed. Each step knows whether
it is done by asking the data, not by remembering a click:

| # | Step | Done when |
|---|------|-----------|
| 1 | Who you are | `owner_email` is set |
| 2 | Your first company | any company exists |
| 3 | Your first contact | any contact exists |
| 4 | Log what happened | any interaction exists |
| 5 | Move a deal | any company has stage history beyond its first |
| 6 | Set a next step and a task | any open next step exists |
| 7 | BCC capture | `bcc_address` set and the connection test passed |
| 8 | Calendar | a feed URL is configured |
| 9 | The extension | the bookmarklet page has been opened |
| 10 | Ask the Hermit | an AI provider is available |

Each step: one paragraph on why it matters, the action as a link into the
actual screen, and the progress line "4 of 10".

**The tour** — coach marks over the real UI on first launch, triggered from
`/welcome` and repeatable from Help. Anchored to `data-tour="…"` attributes
added to the elements it points at, so the markup and the tour move together,
in one small vanilla-JS file with no dependency. It skips any step whose
anchor is not on the page rather than breaking.

**BCC presets.** `bcc.py` already defaults `imap_host` to `imap.gmail.com`
(`bcc.py:72`). Settings gains a provider picker — Gmail, Outlook/Microsoft 365,
Fastmail, iCloud, other — that fills the IMAP host and links to that
provider's app-password page, because every one of them needs an app password
rather than the account password, and that is the step people fail. "Other"
keeps the manual host box.

**Filter syntax.** The operators are documented in `filters.py:5-13` and
nowhere a user can see them. Every filter row gets a small help control
showing the seven operators with an example each, and the same table goes into
the help page.

---

## 7. Small corrections

Independent of everything above, shipped first.

**Provider account type.** `enrich.py:156` pins `gpt-5-mini` as the medium
tier for codex. A ChatGPT account rejects it with a 400, which surfaced raw
three times over in one error string, on both Enrich and Ask. Settings gains
an account-type choice per provider — subscription sign-in vs API key — which
picks the tier defaults, and a subscription account passes no model flag at
all so the account's own default is used. Applied to every provider, not only
codex: `claude`, `gemini` and `grok` have the same split. Any provider error
naming an unsupported model is caught and shown as one sentence: provider,
model, and which setting to change.

**"Ask Hermit" → "Ask the Hermit"** everywhere: topbar button
(`base.html:39`), page title and heading (`ask.html`), help text.

**Topbar layout.** `base.html:35` puts search first and Ask second in a flex
row. It becomes three zones: search centred in the page, Ask the Hermit
pinned right.

**Company page header.** The `country-line` block (`company.html:44-51`) is
removed; country stays on the record and in the edit form, because
`messaging.py` uses it to pick the draft's language. The header's four stacked
paragraphs — oneliner, links, stage line, last touch — collapse into two
rows, and the disqualify controls move behind a single menu instead of two
always-open `<details>` blocks.

---

## Sequencing

| PR | Contents | Depends on |
|----|----------|-----------|
| 1 | Section 7: provider account type, renames, topbar, company header | — |
| 2 | Section 1: custom fields, migration, Settings editor | — |
| 3 | Section 2: messaging reads configured fields | 2 |
| 4 | Section 3: extension, person capture, oneliner | — |
| 5 | Section 4: tasks | — |
| 6 | Section 5: home page, board moves to /pipeline | — |
| 7 | Section 6: walkthrough, BCC presets, filter help | 5, 6 |

PRs 1, 2, 4 and 5 are independent of each other and can land in any order.

Two of these grew after the first draft. PR 2 now covers interaction fields as
well, which adds the two interaction forms and a Messages-view column but no
new mechanism. PR 5 now covers contact tasks, which adds the contact file, the
merge rule and the delete warning; that one is genuinely bigger, and it is the
PR where the tests matter most, because a merge that drops a task loses work
silently.

## Testing

Every section adds tests in the existing style (`tests/test_*.py`, currently
653 passing). The ones that matter most:

- a folder with no `fields.toml` shows no custom fields anywhere, and a
  round-trip of a file containing unknown keys still preserves them;
- the migration turns the four keys into definitions without touching a single
  front-matter value, asserted byte for byte;
- `capture.kind()` on a `/in/` URL produces a contact form, and a captured
  person whose employer is already in the CRM adds to it rather than
  duplicating;
- a LinkedIn person description never becomes a `product_oneliner`;
- adding a task does not change `next_step`, on a company or on a contact;
- merging two contacts keeps every task from both, and deleting a contact with
  open tasks says how many before it goes;
- saving a custom field on an interaction leaves its body byte for byte;
- a subscription-account provider is invoked with no model flag.

## Explicitly not in scope

- A packaged browser extension (manifest, store listing, update channel).
- Converting the existing `outcome` enum into a custom select field.
- Multi-user anything.
- Tasks attached to nothing at all: every task hangs off a company or off a
  contact within one.
