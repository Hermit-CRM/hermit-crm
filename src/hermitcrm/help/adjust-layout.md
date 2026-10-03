# Make it yours: page layout

A recipe for your AI agent: put the sections of the company, contact and home pages in another order or hide them, hide fields, and choose the columns of the Companies and Contacts lists, all in one file, `layout.toml`.

## What you can ask for

- "On company pages, show the timeline first and hide the Merge section."
- "Hide the value per month field everywhere."
- "On Home, put Replies you owe at the top."
- "In the companies list, show only name, stage, fit, country and the next step."
- "Add my seniority field as a column in the contacts list."

What a layout cannot do: rename a label, add a new kind of section, or change
the HTML. For a new field, see `fields.toml` in [Data format](/help/data-format);
for anything else, `hermitcrm help adjust` says which recipe fits.

## The one file you write

`layout.toml` in the data folder. Nothing else: no templates, no CSS, no
record files. The file is optional, and so is every table and key in it. When
it is absent, every page is exactly as it ships. The app reads it again on the
next page load; there is nothing to restart.

If the file exists, read it first and change it; keep the tables you were not
asked about.

```toml
[company]                     # the company page
sections = ["timeline", "details", "contacts"]   # these first, in this order
hide_sections = ["merge"]     # never shown
hide_fields = ["value_eur_month", "requalify_on"]

[contact]                     # the contact page: the same three keys
hide_fields = ["phone"]

[home]                        # Home: sections and hide_sections only
sections = ["owed"]

[companies]                   # the Companies list
columns = ["name", "stage", "fit_score", "country", "next_step"]

[contacts]                    # the Contacts list
columns = ["name", "company_name", "title", "email", "last_touch"]
```

Every value is a list of names in quotes.

## Sections

`sections` puts the sections you list first, in that order. **Sections you do
not list are not hidden**: they follow in their default order. Only
`hide_sections` hides a section. So a section that a later Hermit CRM adds
always shows up. The page header (the name, the line under it, the stage and
Disqualify) always stays on top and is not a section.

| Page | Section names, in their default order |
|---|---|
| `[company]` | `enrich` (the Enrich and Fetch from URL buttons), `next-step` (the next step line), `details` (the edit form), `contacts`, `tasks`, `drafts` (message drafts), `merge`, `timeline` |
| `[contact]` | `details` (the edit form), `timeline` (interactions), `quick-add` (Log an interaction), `tasks`, `drafts`, `merge` (only shown when the company has two or more people), `delete` |
| `[home]` | `doing` (What needs doing), `to-file` (To file, only while there is something to file), `owed` (Replies you owe, only when you owe some), `going` (How it is going) |

On Home the layout applies once the folder has companies. The empty-folder
start cards and the Getting started block do not move.

## Fields

`hide_fields` hides a field on that record's page: the header line, the edit
form and the New form. It also leaves the list: hidden company fields leave
the Companies list and the Pipeline filters, hidden contact fields the
Contacts list. A hidden country or value per month leaves the Pipeline cards,
and a hidden value or one-liner the meeting brief on the Calendar. Reports,
`PIPELINE.md`, the CLI and Ask still see every field.

| Table | Built-in fields you can hide |
|---|---|
| `[company]` | `website`, `linkedin`, `country`, `source`, `lost_reason`, `requalify_on`, `value_eur_month`, `product_oneliner`, `next_step`, `next_step_due`, `next_step_status`, `next_step_type`, `tags`, `notes` |
| `[contact]` | `title`, `role`, `language` (draft language), `email`, `phone`, `linkedin` |

Your own fields from `fields.toml` work too: use their `key`, in the table for
what they apply to (`company` or `contact`). The name and the stage of a
company, and the first and last name of a contact, cannot be hidden.

**Hiding never loses data.** The value stays in the file. A form leaves a
hidden field out entirely, and saving a form keeps every value it did not
carry. A hidden field that has an error (for example the reason, when the
stage is set to lost) shows again so it can be filled in.

## Columns

`columns` chooses which columns a list shows and in what order. Leave it out
for the default columns.

| Table | Built-in column keys, in their default order |
|---|---|
| `[companies]` | `name`, `country`, `stage`, `source`, `tags`, `last_touch`, `next_step`, `next_type` (only when task types are set up), `next_step_due` (due), `links` (website and LinkedIn) |
| `[contacts]` | `name`, `company_name` (company), `title`, `email`, `linkedin`, `last_touch`, `interaction_count` |

Any of your own fields of that record type can be a column, by its `key`. When
`columns` is set it wins over the field's `show_in` for that list: a field you
list shows even without `companies` (or `contacts`) in its `show_in`, and a
field you leave out does not show. Without `columns`, `show_in` decides, as
before. Every column shown can be filtered and sorted, and a filter on a
column that is not shown still works in a saved link.

## Example: the company page

The user asks: "On company pages, show the timeline first and hide the Merge
section. Hide the value per month field everywhere."

```toml
[company]
sections = ["timeline"]
hide_sections = ["merge"]
hide_fields = ["value_eur_month"]
```

The company page now shows the header, then the timeline, then the other
sections in their default order: enrich, next-step, details, contacts, tasks,
drafts. The value per month is gone from the form, the Pipeline cards and the
meeting brief, and it stays in every company file.

## Example: the lists

The user asks: "Make the companies list just name, stage, fit, country and
next step. In the contacts list, add my seniority field after the title."

`fields.toml` has a company field `fit_score` and a contact field
`seniority`, so:

```toml
[companies]
columns = ["name", "stage", "fit_score", "country", "next_step"]

[contacts]
columns = ["name", "company_name", "title", "seniority", "email", "last_touch"]
```

## Check, then commit

1. Run `hermitcrm check`. It reads `layout.toml` with `fields.toml` and names
   every problem with its place and, for a near miss, the name you meant:
   `layout.toml: [company] sections: unknown section timline (did you mean timeline?)`.
   Fix what it says until it prints OK.
2. Open the page (or ask the user to) to see the result.
3. Commit only that file, one commit per change:
   `git add layout.toml && git commit -m "ai: adjust: layout timeline first on company pages"`.

A mistake never breaks a page: a syntax error means the default layout, and a
wrong name is skipped while the rest applies. Still fix it: `check` fails
until you do. To go back, revert the commit or delete the file.

## Rules

- Write `layout.toml` and nothing else for a layout request.
- Never edit the templates or the package: an update would undo it.
- Never rewrite history; undo with a new commit (`git revert`).

Related: [Data format](/help/data-format), [Companies](/help/companies), [Contacts](/help/contacts), [AI agents](/help/ai-agents)
