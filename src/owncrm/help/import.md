# Import

`/import` (and `owncrm import FILE`): companies or contacts from a spreadsheet, previewed before anything is written.

## Input

Paste a tab-separated table (copied from a spreadsheet) or upload a `.tsv`,
`.csv` or `.xlsx` file (first worksheet; dates stay as serial numbers). The
first row is the header.

## Modes

- **companies**: needs a `name` column. Other recognised columns fill the
  company fields; contact columns prefixed `founder_` or `contact_` (name,
  title, email, LinkedIn) create a contact.
- **contacts**: needs a person name column; the company comes from a company
  column or from a non-freemail email domain. Companies are matched by slug or
  website domain, contacts by email, else by name.

The mode is detected from the header (contacts when there is a person-name
or email column plus a company column and no company-only column) and can be
forced. Header aliases from HubSpot, Apollo, LinkedIn, Pipedrive and Attio
exports are recognised; the full list is on the page. Unknown columns are kept
as `column: value` lines in the notes.

## Preview and apply

The preview lists every row with its planned action (**create**, **update**
of empty fields only, **keep**, **skip**) and warnings such as an unmapped
country or a non-numeric score. Every column can be remapped to a field, to
`notes` or to `ignore`. Applying writes everything in one commit:
`import: <n> companies created, <m> updated, <k> contacts created`.

In the CLI: `owncrm import FILE [--mode companies|contacts] [--map "Header=field" ...]`
prints the plan; `--apply` writes it.

Related: [Companies](/help/companies), [Contacts](/help/contacts), [CLI](/help/cli)
