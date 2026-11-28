---
name: hermit-daily
description: "Morning review of this CRM: overdue and today's tasks, replies owed, today's meetings, drafts waiting, and what to do first. Use it when the user asks what to do today, for a morning review or a daily briefing."
---

Use it at the start of the day, or when the user asks "what's on today?".

Run these from this folder, in order. They only read:

1. `hermitcrm tasks list --when overdue`, then `hermitcrm tasks list --when today`
2. `hermitcrm followups`: replies the user owes, then threads waiting on others
3. `hermitcrm brief --days 1`: today's meetings with the record behind each
4. `hermitcrm outreach list --state drafted`: drafts waiting for the user's approval

Over MCP instead: the `morning_review` prompt, or `list_tasks` (when `overdue`,
then `today`), `followups`, `brief` and `list_outreach`.

Answer in one short page: what to do first and why, then the rest grouped as
above. Name each company by its name and slug. Leave out the sample account
(`sample: true`).

Rules:
- This review only reads. Change something only when the user asks: tick a
  task off with `hermitcrm tasks done <id>` (the id from `tasks list`).
- Never send, approve or schedule a message. The user approves drafts in the
  web app.
- One commit per change, and say its commit id so `hermitcrm undo <sha>` can
  reverse it.
