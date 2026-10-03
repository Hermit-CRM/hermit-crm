# Make it yours: fields

A recipe for your AI agent: add or change fields of your own, where they show, and your task types, outcomes and quiet threshold.

Read `hermitcrm help adjust` first; its rules apply here too.

## What the user can ask for

- A new field on companies, contacts or interactions: text, number, date or a
  choice from a list ("Add a date field contract renewal to companies").
- A field shown in more places: the companies or contacts list, the pipeline
  cards, the Messages table (each a sortable, filterable column).
- A field offered to Enrich (`enrich = true`), or kept out of the draft
  templates (`messaging = false`).
- Task types and their colours, message outcomes, and after how many days an
  account counts as silent.
- "A new kind of record" (deals, partners, projects): Hermit has companies,
  contacts and interactions only. Answer honestly with a field plus a
  dashboard, for example partners as companies with a `type` field set to
  `partner` and a pinned "Partners" dashboard; say that this is the way.

## Files you may write

- `fields.toml` in the data folder (absent means no fields of your own).
- In `config.toml`: `task_types`, `outcomes`, `silent_days` only. Change the one
  line, keep the comments and every other line.

## fields.toml

One `[[field]]` table per field:

| Key | Required | Meaning |
|---|---|---|
| `key` | yes | the front-matter key, lower case with underscores (`contract_renewal`) |
| `label` | no | what the pages call it (default: the key with spaces) |
| `type` | no | `text` (default), `number`, `date` (YYYY-MM-DD) or `select` |
| `applies_to` | no | `company` (default), `contact` or `interaction` |
| `options` | for select | the allowed values, a list of strings |
| `show_in` | no | where it shows: `detail` (the record's page, the default) plus `board` and `companies` for a company field, `contacts` for a contact field, `messages` for an interaction field |
| `help` | no | one line under the input |
| `enrich`, `description` | no | offer it to Enrich, and what to tell the model to look for |
| `messaging` | no | `false` keeps it out of the draft templates (default `true`) |

A key a built-in field already uses (`stage`, `country`, `tags`, ...) is refused.

## Worked example

"Add a date field contract renewal to companies, shown on the company page and
in the companies list." Add to `fields.toml` (create it if it is not there):

```toml
[[field]]
key = "contract_renewal"
label = "contract renewal"
type = "date"
applies_to = "company"
help = "when their current contract ends"
show_in = ["detail", "companies"]
```

Then:

```bash
hermitcrm check
git add fields.toml && git commit -m "ai: adjust: contract renewal field on companies"
```

The field shows on every company page and as a column on `/companies` on the
next page load. Values are filled in on the company page, or in bulk with
`hermitcrm set` (`hermitcrm help adjust-bulk`).

## Task types, outcomes, silent days

In `config.toml`:

```toml
task_types = [{name = "call", colour = "green"}, {name = "demo", colour = "blue"}, {name = "proposal", colour = "amber"}]
outcomes = ["replied", "meeting booked", "no reply"]
silent_days = 21
```

- Task type colours: green, blue, amber, red, violet or grey.
- Outcomes are in order: the **first** is what a detected reply counts as, the
  **last** what silence after the message window counts as.
- Renaming a task type or an outcome here does not rename it on tasks and
  messages already logged. Settings > Your CRM renames task types everywhere;
  for outcomes, keep the old name in the list or ask the user before changing
  logged messages in bulk.

## Check

`hermitcrm check` reads `fields.toml` and these `config.toml` keys and names
each problem, for example:

```text
fields.toml: contract_renewal: type must be one of text, number, date, select (did you mean date?)
config.toml: task_types entry 2: colour 'bleu' is not one of green, blue, amber, red, violet, grey (did you mean blue?)
```

## Safety

- Removing a field from `fields.toml` hides it; every value stays in the
  record files and comes back when the field is described again.
- Changing a field's `key` does not move the values stored under the old key:
  ask the user first, and move them with `hermitcrm set` (dry run first).
- Never edit record files by hand to fill a field; use the page or `hermitcrm set`.
- Commit: `ai: adjust: <what>`, one commit per change. Undo:
  `hermitcrm undo <commit>`.

Related: [Make it yours](/help/adjust), [Settings](/help/settings), [Data format](/help/data-format)
