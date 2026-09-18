# Feedback

`/help/feedback`: tell whoever gave you Hermit CRM what worked and what did not,
without leaving the app.

Hermit CRM is early, and the things most worth hearing about are the small ones:
a label you read twice, a button you looked for and could not find, a number that
looked wrong. Those are the reports that never get written, because writing them
means leaving what you were doing and composing an email from nothing.

## What it does

Fill in the form and press **Save this report**. Hermit CRM writes a Markdown file
into your data folder under `feedback/` and commits it, the same way it commits a
company or an interaction, and then shows you the finished text.

**Nothing is sent anywhere.** There is no server behind Hermit CRM to post to, and
adding one would undo the point of a CRM that is a folder on your own disk. Sending
the report is your move: if `feedback_email` is set in `config.toml` the page offers
a **Send by email** link that opens your mail app with everything filled in;
otherwise, copy the text out of the box and send it however you like.

Because the file is in your folder, the report is also just a note to yourself. You
can write one and send it a week later, or never.

## What goes in it

What you typed, plus a short block of facts about this install that make a bug
reproducible:

- the Hermit CRM version, your Python version and your platform
- how many companies, contacts and interactions you have, and the data format
- which optional features are switched on: BCC import, calendar import, enrichment

Deliberately **not** included: any company name, contact name or email address from
your CRM, and the path to your data folder (which usually contains your own name).
The whole report is shown to you before you send it, so you can check.

The **From** box is yours to fill in or leave empty. It is the only way a reply can
reach you, and it is prefilled from `owner_name` and `owner_email` in your config.

## Sending it without the form

A report is an ordinary file. `feedback/2026-09-18-1432-sorting-looked-wrong.md` can
be attached, pasted or read out loud. Equally, an email written by hand is fine: the
form exists to lower the cost, not to be the only route.

Related: [Settings](/help/settings), [Data format](/help/data-format)
