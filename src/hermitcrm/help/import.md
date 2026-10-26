# Import and export

`/import` (and `hermitcrm import FILE`): companies or contacts from a spreadsheet, previewed before anything is written. Export, below, takes everything out again.

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
as `column: value` lines in one company note, under an `Imported fields (<date>):` line. For a company row, the notes text and that block become one company note, and a re-import adds only lines that no company note or old notes text has yet.

## Preview and apply

The preview lists every row with its planned action (**create**, **update**
of empty fields only, **keep**, **skip**) and warnings such as an unmapped
country or a non-numeric score. Every column can be remapped to a field, to
`notes` or to `ignore`. Applying writes everything in one commit:
`import: <n> companies created, <m> updated, <k> contacts created`.

In the CLI: `hermitcrm import FILE [--mode companies|contacts] [--map "Header=field" ...]`
prints the plan; `--apply` writes it.

## Export

Settings > Data > Export everything (or `hermitcrm export`) gives you a zip
of five CSV files: `companies.csv`, `contacts.csv`, `interactions.csv`,
`tasks.csv` and `stage_history.csv`. Exporting only reads: nothing in your
folder changes and nothing is committed.

- **Column names.** `generic` uses Hermit CRM's own names; `hubspot` and
  `pipedrive` rename the company and contact columns to what those CRMs
  call them. Your own fields and any key the app does not know come after
  the known columns, so nothing is left out.
- **For Excel** (`--excel`) starts each file with a UTF-8 byte-order mark, so
  Excel shows accents correctly.
- **Formulas.** A cell that starts with `=`, `+`, `-` or `@` gets an
  apostrophe in front, so a spreadsheet does not run it. Importing the file
  back removes the apostrophe again.
- **JSON.** `hermitcrm export --format json` writes one file with every
  company and its contacts, interactions, tasks and stage history.

The CLI writes `hermitcrm-export-DATE.zip` in the current folder, or where
`--output` says (`-` for stdout). It refuses a path inside the data folder,
where the export would end up in git.

Every column of the export is one the importer recognises: import
`companies.csv` first, then `contacts.csv`.

Related: [Companies](/help/companies), [Contacts](/help/contacts), [CLI](/help/cli)
