---
name: hermit-research
description: "Research a prospect or account in this CRM and file what you find as a note on the company. Use it when the user asks to research, look into or find out about a company or person before outreach or a meeting."
---

Use it when the user asks what a company does, who to talk to there, or what
changed there lately.

1. Read what Hermit already has: `hermitcrm show <slug>` (over MCP:
   `show_company`). Do not research what is already there.
2. `hermitcrm fetch <slug>` proposes fields from the company's own website, with
   no AI. It is a dry run: show it, and add `--apply` only after a yes.
3. Research with your own tools (the web, the user's files). Keep the source of
   every finding.
4. File the findings as one note, with the sources as links at the end:

       hermitcrm add interaction <slug> --channel note \
           --subject "Research: <topic>" --body -

   Over MCP: `add_interaction` with channel `note`.
5. A finding that belongs in a field (one-liner, website, country) is a change
   to propose. Over MCP: `update_company`. On the command line this is a dry
   run; check it names that one company, and add `--apply` after a yes:

       hermitcrm set companies --where "name=<Company name>" --set <field>=<value>

Rules:
- Write only what a source says, and say which source. Mark a guess as one.
- Never send anything and never contact anyone. Draft outreach only when asked.
- Skip the sample account (`sample: true`).
- One commit per change; say its id so `hermitcrm undo <sha>` can reverse it.
