# Hermit CRM help

Short pages on how each part of Hermit CRM works, for people and for AI agents.

Hermit CRM is a CRM that is a folder of Markdown files in git. The web app
(`hermitcrm serve`, http://127.0.0.1:8765) and the CLI read and write the same
files, and every change is one commit. The Help link in the nav opens the
page for the screen you are on; `hermitcrm help <topic>` prints the same text.

## Topics

- [Pipeline](/help/pipeline): the board, stages, filters and the closed lists.
- [Calendar](/help/calendar): next steps due, the month grid, silent accounts, meetings this week.
- [Companies](/help/companies): the table, the company page, stages, next steps, disqualify and requalify.
- [Contacts](/help/contacts): the table, the contact page, roles, message drafts.
- [Interactions](/help/interactions): logging email, LinkedIn, call and meeting touches; outcomes.
- [Messages](/help/messages): every sent message with its outcome.
- [Reports](/help/reports): activity, funnel, outcomes, messages, sources, hygiene.
- [Settings](/help/settings): you, BCC capture, calendar, backup, enrichment, outcomes, the review queue, schedule, phone and MCP access, about.
- [Import](/help/import): bulk import from CSV, TSV, .xlsx or a pasted table.
- [Capture](/help/capture): turn the page you are looking at into a company, from a bookmarklet.
- [Enrich](/help/enrich): "Fetch from URL" (no AI) and Enrich (an AI CLI).
- [Ask Hermit](/help/ask): ask a question about the page you are on or the whole CRM.
- [Merge](/help/merge): merging two companies or two contacts.
- [CLI](/help/cli): every `hermitcrm` command.
- [Data format](/help/data-format): the files, their front-matter keys, stage history, migrations.
- [AI agents](/help/ai-agents): how an AI session should read and write the folder, and the MCP server (`hermitcrm mcp`) that lets a client with no shell do it.
- [Feedback](/help/feedback): tell whoever gave you Hermit CRM what worked and what did not.

Related: [Settings](/help/settings), [CLI](/help/cli), [AI agents](/help/ai-agents)
