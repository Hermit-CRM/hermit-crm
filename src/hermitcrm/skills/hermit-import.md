---
name: hermit-import
description: "Import a list of companies or contacts into this CRM from a CSV, TSV or .xlsx file, with a dry run first. Use it when the user gives you a spreadsheet or an export from another tool to bring in."
---

Use it when the user hands you a file of companies or contacts.

1. Preview it. Without `--apply` nothing is written:

       hermitcrm import <file>

   Each row shows its action (create, update of empty fields only, keep or
   skip) and any warning. Show the user the counts and a few rows.
2. If a column landed in the wrong field, map it and preview again:

       hermitcrm import <file> --map "<Column header>=<field>"

   A field of the user's own maps as `custom_<key>` and must exist in
   fields.toml first (`hermitcrm help adjust-fields`).
3. Only after the user says yes, run the same command with `--apply`, then
   `hermitcrm check`. The import is one commit; do not commit again.

Over MCP there is no import tool: send the user to the Import page (`/import`)
in the web app, which shows the same preview.

Rules:
- A dry run before every import, and `--apply` only after a yes.
- Never edit the file's rows by hand to get round a warning; tell the user.
- Never send anything to the people imported.
- Undo the whole import with `hermitcrm undo <sha>`, the commit it printed.
- More on imports: `hermitcrm help adjust-connect`.
