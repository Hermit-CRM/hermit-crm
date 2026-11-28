# Search and the keyboard

The search box at the top of every page finds companies, people, the text of logged messages, tasks, help pages and the app's own pages, all at once.

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

Related: [Companies](/help/companies), [Interactions](/help/interactions), [Tasks](/help/tasks)
