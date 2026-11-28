# Hermit CRM help

Short pages on how each part of Hermit CRM works, for people and for AI agents.

Hermit CRM is a CRM that is a folder of Markdown files in git. The web app
(`hermitcrm serve`, http://127.0.0.1:8765) and the CLI read and write the same
files, and every change is one commit. The Help link in the nav opens the
page for the screen you are on; `hermitcrm help <topic>` prints the same text.

## Topics

- **[Getting started](/welcome)**: thirteen steps, each ticked when it has actually happened, and a tour that points at each part of the screen.
- **[Make it yours](/help/adjust)**: describe a change and your own AI agent builds it in your data folder: fields, the look, dashboards, page layouts, routines, bulk changes. Every change can be undone in one click. The recipes your agent follows: [fields](/help/adjust-fields), [dashboards](/help/adjust-dashboards), [page layout](/help/adjust-layout), [bulk changes](/help/adjust-bulk), [deal stages](/help/adjust-stages), [routines](/help/adjust-routines), [messages](/help/adjust-messages), [the look](/help/adjust-look), [bringing data in](/help/adjust-connect), [something Hermit can't do yet](/help/adjust-feature).
- **The home page** (`/`, the logo): Getting started, until every step is ticked or you click *Don't open this at startup*. After that: [What to do now](#today), one list of what is waiting on you, then To file and last month's numbers.
- [Pipeline](/help/pipeline): the board, stages, filters and the closed lists.
- [Calendar](/help/calendar): the month grid, meetings this week, silent accounts.
- [Tasks](/help/tasks): every task in one list, with date buttons and filters.
- [Companies](/help/companies): the table, the company page, stages, next steps, disqualify and requalify.
- [Contacts](/help/contacts): the table, the contact page, roles, generating outreach.
- [Interactions](/help/interactions): logging email, LinkedIn, call, WhatsApp and meeting touches; outcomes; To file.
- [Messages](/help/messages): every sent message with its outcome.
- [Playbook](/help/playbook): what you sell and to whom (`MESSAGING.md`), for the drafts and the outreach bot.
- [Outreach bot](/help/outreach): a batch of researched, checked first messages for you to review, send and log (`hermitcrm outreach`).
- [Sending](/help/sending): send approved email from the app, now or spaced over the working day, from a mailbox of its own; a paced LinkedIn session where you click Send; bounces, opt-outs and the kill switch.
- [Learning](/help/learning): what your edits and outcomes teach the outreach bot, as lessons you accept (`hermitcrm learn`).
- [Reports](/help/reports): activity, funnel, outcomes, messages, sources, hygiene.
- [Settings](/help/settings): you, BCC capture, calendar, backup, enrichment, outcomes, schedule, phone and MCP access, support, about.
- [Import and export](/help/import): bulk import from CSV, TSV, .xlsx or a pasted table; export everything as CSV or JSON.
- [Extension](/help/extension): turn the page you are looking at into a company, from a bookmarklet.
- [Enrich](/help/enrich): "Fetch from URL" (no AI) and Enrich (an AI CLI).
- [Ask the Hermit](/help/ask): ask a question about the page you are on or the whole CRM.
- [Merge](/help/merge): merging two companies or two contacts.
- [Search and the keyboard](/help/search): the search box at the top, what it finds and how it ranks.
- [Backups and undo](/help/backups): a backup every few minutes that nothing can rewrite, and putting any version back.
- [CLI](/help/cli): every `hermitcrm` command.
- [Data format](/help/data-format): the files, their front-matter keys, stage history, migrations.
- [AI agents](/help/ai-agents): how an AI session should read and write the folder, and the MCP server (`hermitcrm mcp`) that lets a client with no shell do it.
- [Feedback](/help/feedback): tell whoever gave you Hermit CRM what worked and what did not.
- [Disclaimer](/help/disclaimer): no warranty, your backups, your integrations, and what the name is not licensed for.
- [Changelog](/help/changelog): what changed in each version, and how to upgrade.

Related: [Settings](/help/settings), [CLI](/help/cli), [AI agents](/help/ai-agents)

## Today

Once Getting started is done, Home opens on **What to do now**: one list of
what is waiting on you, most urgent first. `/today` shows the same list
without the rest of Home.

The groups, in this order:

1. **Replies you owe**: someone wrote and you have not answered (the
   [follow-up radar](/help/pipeline#follow-up-radar)).
2. **Overdue tasks**: open tasks whose date has passed.
3. **Today**: today's meetings from the calendar import, and today's brief
   from a [brief routine](/help/adjust-routines).
4. **Drafts waiting for you**: drafts your routines wrote. Nothing is sent:
   open the draft, send it yourself, then click *I sent it*.
5. **Due today**: open tasks due today.
6. **Waiting on them**: messages of yours nobody answered (the radar's nudges).
7. **Keep in touch**: people outside an open deal you have not spoken to in
   `keep_in_touch_days` days (default 180).

Inside a group the oldest comes first. A company shows once per group: three
overdue tasks at one company are one row with a ×3 mark, the oldest task on it
and the other two named; tick it off and the next one takes its place. The number next to each
heading counts every task or message, so it matches the Tasks page's
**Overdue** and **Today** buttons and `hermitcrm followups`.

Each row says who, what and why, and carries its buttons: **Done** for a task,
**Log a reply** or **Log a follow-up** for a message, **Open the draft** and
**Discard** for a draft. They do what the same buttons do elsewhere in the app.
Home shows the first 25 rows; **Show all** opens the full list on `/today`.

With nothing waiting, the list says so and names the next dated task.
