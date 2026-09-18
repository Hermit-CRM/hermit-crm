# Messages

`/messages`: every message you sent, newest first, with what came of it.

## Fields of your own in a draft

Every [field you defined](/help/settings) is a slot the templates can use by
its key: a field `segment` is `{segment}`. A field with no value yet renders as
its label in square brackets, like the other things only you can fill in, so a
draft never goes quietly blank. A field can be kept out of the templates
entirely with `messaging = false` in `fields.toml`, and a field whose key is
already a slot name (`company`, `site`, `first`, ...) is ignored rather than
shadowing it.

Two fields can also play the roles the shipped wording knows about: a
headcount, for the sentences about team size, and a count of sales people.
Pick them under Settings -> Drafts. With neither set, those sentences use their
"unknown" wording, which is a line you write yourself; nothing is invented.

## What counts as a message

An outbound interaction with a body, on any channel except `meeting`. Calls
with notes count too; a logged interaction without text does not.

## The table

Sent, company, contact, channel, country, stage, outcome, how many times that
exact text was used (whitespace and case ignored), and the message itself,
collapsed. Every column has a filter control and sort arrows; the search box
matches the message text, the company and the contact. The totals line at the
top counts each status.

## Outcome

A message's status is its outcome when one was set by hand; otherwise it is
derived: a later inbound interaction from the same contact (or a company-level
one) makes it the first configured outcome (default `successful`); no reply
within `message_window_days` (default 14) makes it the last one (default
`unsuccessful`); before that it is `unknown`. Derived values are marked
"(auto)". The buttons in the last column set or clear the outcome by hand
(commit `interaction: <company> <id> outcome <value>`; the same field the
interaction form edits, so both places always agree), and "edit" opens the
interaction.

The outcome list and the window are set on the Settings page. The Reports page
breaks message outcomes down by language, channel and the most reused texts.

Related: [Interactions](/help/interactions), [Reports](/help/reports), [Settings](/help/settings)
