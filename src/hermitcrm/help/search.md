# Search and the keyboard

The search box at the top of every page finds companies, people, the text of logged messages, tasks, help pages and the app's own pages, all at once; Cmd K (Ctrl K) does the same from anywhere, with shortcuts to start common work.

## What search finds

Type in the box at the top and press Enter: `/search` lists what matches, in
groups.

| Group | Matches on |
|---|---|
| Companies | name, slug, website, tags, one-liner |
| Contacts | name, email, title |
| Interactions | subject, the message text, the names of attached files |
| Tasks | the task's text, open and done (open ones first) |
| Pages | the pages in the sidebar, by name |
| Help | the titles of these help pages |

Every word you type has to appear somewhere in the same record, in any field,
in upper or lower case: `pricing berlin` finds a message that says both, not
every message that says one. Part of a word is enough: `north` finds
*Northwind*. An interaction shows the piece of text around the first match,
with the matches marked, and opens on its place in the timeline.

Within a group, a name that starts with what you typed comes first, then
whatever was touched most recently. Each group shows its first eight; **Show
all** lists the rest of that group. Search reads the folder as it is in memory,
so nothing is indexed and nothing is written; a new message is found as soon as
it is logged.

The **Messages** list keeps a search box of its own, for filtering that table.

## The command palette

Press **Cmd K** on a Mac (**Ctrl K** elsewhere) on any page, or **/** when you
are not typing in a field, to search without leaving the page. The same results
appear as you type, a moment after you stop, with the actions below them:

- **New company**, **New contact**, **Go to Pipeline**, **Tasks**, **Outreach**,
  **Settings**: shown before you type, and whenever what you type matches them.
- **Log a call with** the first person found: opens the log form with that
  person and *call* already chosen.
- **Add a task for** the first company found: opens the company on its task list.
- **Ask Hermit:** what you typed: puts it in the Ask box and opens it. The
  question is only asked when you press **Ask**.
- **All results**: the full results page.

Every entry opens a page or a form; nothing is saved until you press that
form's own button.

Use the arrow keys to choose and Enter to open. Cmd Enter (Ctrl Enter) opens
the full results page. Esc closes the palette and puts you back where you were.
If you press Enter before the results for what you typed have arrived, the full
results page opens. With a screen reader, the box reads as a list you move
through with the arrow keys, and the number of results is announced.

## Keyboard

These work on every page when you are not typing in a field. Press **?** to see
the list in the palette.

| Keys | What it does |
|---|---|
| Cmd K / Ctrl K | Search and commands (also inside a field) |
| / | Search and commands |
| g then h | Go to Home |
| g then p | Go to Pipeline |
| g then t | Go to Tasks |
| g then c | Go to Companies |
| g then o | Go to Outreach |
| n | New company |
| ? | This list of keys |

Press the two keys of a *g* pair one after the other, within a second and a
half. Keys held with Cmd, Ctrl or Alt are left to the browser.

Related: [Companies](/help/companies), [Interactions](/help/interactions), [Tasks](/help/tasks)
