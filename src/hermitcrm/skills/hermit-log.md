---
name: hermit-log
description: "Log a call or meeting in this CRM from the user's notes, with the follow-up tasks it calls for. Use it when the user pastes or dictates notes of a call or meeting, or says they just spoke to someone."
---

Use it when the user gives you notes of a call or meeting to record.

1. Find the company: read PIPELINE.md, then `hermitcrm show <slug>` for its
   contacts. Over MCP: `search_companies`, then `show_company`. If two could
   match, ask which one.
2. Log it, with the notes as the body, word for word:

       hermitcrm add interaction <slug> --channel call --direction out \
           --contact <contact-slug> --subject "<one line>" --body -

   Use `--channel meeting` for a meeting and `--direction in` when they
   called. `--call-outcome` takes one of `call_outcomes` in config.toml.
   Over MCP: `add_interaction`.
3. Add each follow-up the notes call for, with a date when one was agreed:

       hermitcrm tasks add <slug> "<what to do>" --due YYYY-MM-DD \
           --contact <contact-slug>

   Over MCP: `add_task`.
4. If the deal moved on, propose the new stage and wait for a yes. Then
   `hermitcrm set companies --where "name=<Company name>" --stage <stage>` shows
   a dry run: check it names that one company, then add `--apply`. Over MCP:
   `move_stage`.

Rules:
- Never rewrite or tidy the notes: the body is the record.
- Never send anything. A follow-up email is a task or a draft, not a message.
- Each step is one commit. Say the commit ids so `hermitcrm undo <sha>` works.
