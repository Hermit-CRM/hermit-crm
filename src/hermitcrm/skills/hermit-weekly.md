---
name: hermit-weekly
description: "Weekly review of this CRM: the week in numbers, deals that went quiet, people to get back in touch with, and what matters next week. Use it when the user asks for a weekly review, a pipeline review or how the week went."
---

Use it at the end or the start of a week, or when the user asks how things
are going.

Run these from this folder, in order. They only read:

1. Read PIPELINE.md: every open deal by stage, with its last touch.
2. `hermitcrm report --days 7 --md`: activity, funnel, outcomes, messages.
3. `hermitcrm digest --days 7`: what happened, oldest first.
4. `hermitcrm followups` and `hermitcrm keep-in-touch`: who is waiting, and
   who went quiet.
5. `hermitcrm tasks list --when week`: what is due in the next 7 days.

Over MCP instead: the `weekly_review` prompt, or `list_pipeline`, `report`,
`digest`, `followups`, `keep_in_touch` and `list_tasks` (when `week`).

Answer in one page: the week in numbers, the deals that need a push (no next
step, or a next step overdue), and three things that matter most next week.
Leave out the sample account (`sample: true`).

Rules:
- This review only reads. Propose tasks or stage moves; make them only after a
  yes (`hermitcrm tasks add`, or `hermitcrm set ... --stage` with a dry run first).
- Never send, approve or schedule a message.
- One commit per change; say its id so `hermitcrm undo <sha>` can reverse it.
