# Make it yours: bring data in

A recipe for your AI agent: get companies, contacts, mail and meetings into Hermit from files and the tools the user already has.

Read `hermitcrm help adjust` first; its rules apply here too.

## What the user can ask for, and how

| Wish | How | Who does it |
|---|---|---|
| "Import this list" (a CSV, TSV or .xlsx export from another tool) | `hermitcrm import FILE`: a preview, then `--apply` | you |
| "Log my mail with prospects" | BCC capture: a mailbox Hermit reads every morning | the user, in Settings > Email & calendar |
| "Log my meetings" | Calendar import from the calendar's secret address | the user, in Settings > Email & calendar |
| "Save LinkedIn profiles and websites as I browse" | the bookmarklet on the Extension page | the user, in the browser |
| "Let Claude Desktop or ChatGPT read my CRM" | the MCP server, `hermitcrm mcp` (see `hermitcrm help ai-agents`) | the user, in that app's settings |
| "Sync with my other tool every hour", webhooks, an API key | not supported yet | see below |

BCC and calendar need a password or a secret address. Never ask for one, never
write one into a file: send the user to Settings, which keeps secrets out of git.

## Worked example: an import

"Import ~/Downloads/leads.csv (an export from my outreach tool). Match existing
companies by website; show me what would be created first."

```bash
hermitcrm import ~/Downloads/leads.csv
```

Without `--apply` this only prints the plan: one line per row with its action
(**create**, **update** of empty fields only, **keep** or **skip**) and warnings.
Existing companies are matched by slug or website domain, contacts by email,
else by name, so a second import of the same file creates nothing twice. Show
the user the counts and a few rows. If a column landed in the wrong field,
map it and preview again:

```bash
hermitcrm import ~/Downloads/leads.csv --map "Company Website=website" --map "Score=custom_fit_score"
```

A field of the user's own is mapped as `custom_<key>`, and needs that field in
`fields.toml` first (`hermitcrm help adjust-fields`); a column named exactly like
the key maps to it by itself. Columns nobody maps are kept as lines in the
notes. When the user agrees:

```bash
hermitcrm import ~/Downloads/leads.csv --map "Company Website=website" --apply
hermitcrm check
```

`--apply` writes everything in one commit (`import: 12 companies created, ...`);
do not commit again. Undo: `hermitcrm undo <commit>`. The same import, with the
same preview, is on the Import page (`/import`) for a user who prefers clicking.

## Not supported yet: running code

Hermit runs no code from the data folder: no scheduled scripts, no webhooks, no
API keys for other services. A cloned or shared folder must never run anything
by itself. So for "keep it in sync with my other tool":

1. Say plainly that Hermit cannot do that yet.
2. Offer what works today: an export from that tool, imported as above (and
   again later; the matching keeps it from doubling), or BCC capture for mail.
3. If the user still wants it, write the feature request
   (`hermitcrm help adjust-feature`).

Never write a script that edits records behind Hermit's back, and never install
one in launchd, cron or the folder.

## Safety

- Preview before every import; apply only after the user has seen the counts.
- Imports update empty fields only; they never overwrite what the user typed.
- No secrets in any file, ever.

Related: [Make it yours](/help/adjust), [Import](/help/import), [Settings](/help/settings), [AI agents](/help/ai-agents)
