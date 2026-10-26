# Pipeline

The board at `/pipeline`: one column per open stage, cards you can move with a dropdown, closed companies in lists below. The stages are yours to name and order (Settings > Deal stages); this page describes the defaults.

## Columns and cards

The open stages are columns. By default there are four: **prospect**,
**engaged**, **discovery**, **offer**. A column with no companies is drawn
narrow so they fit on one screen. A card shows the company name (a link), days in the current stage,
the country, the last touch (`email out 2026-09-14 (jane-doe)`), the next step
with its due date (red when overdue, struck through when done) and the monthly
value when set. The stage dropdown on a card saves on change; choosing
**lost** sends you to the company page to give a reason first.

Cards are ordered by next-step due date (earliest first, no date last), then
by last touch (most recent first).

## Follow-up radar

The **Follow up** list above the filter bar is not part of the board. It is
the companies where a conversation is waiting, in two groups:

- **You owe a reply**: the latest message in the company's history is one they
  sent, and it is at least `followup_reply_days` old (default 1).
- **Waiting on them**: the latest is a message you sent, nothing has been
  planned, and it is at least `followup_nudge_days` old (default 5).

Replies you owe come first, then your unanswered messages; inside each group the
oldest is on top. Both thresholds are in `config.toml` in your data folder.

Each row shows the evidence: the channel, direction and date of that interaction
(a link to it), and the first words of the message in quotes. What you wrote
starts with **you:**, so your own words do not read as theirs. A pasted mail
header ("Name", "10:12 AM (1 minute ago)", "to Sam") is skipped when picking the
words.

What counts, and what does not:

- A **note** is a memo and never counts as contact, so adding one does not clear a row.
- A **meeting** is not a message you sent, so it never makes a "waiting on them" row.
- A task for later silences "waiting on them" for that company until it is due.
  It does **not** silence "you owe a reply": a reply you owe is owed.
- Closed and parked companies are not on the list.

If a row is wrong because the message was logged the wrong way round, press
**I sent this** (or **They sent this**) on the row. It flips the direction of
that one interaction and nothing else; the text is kept exactly as it was, and
**Undo** in the history brings it back. A card on the board whose company is on
the radar carries a small badge (**reply owed 4d**, **no answer 25d**) that
jumps back to the list. The board's own order is unchanged.

## Closed and parked

Below the board, every other stage is a collapsed list: by default **won**,
**lost**, **disqualified** and **temp-disqualified**, with the reason and, for
parked companies, the date they come back to the first open stage
(`requalify_on`). That return happens by itself: on any page view, a parked
company whose date has arrived goes back to prospect in one commit.

## Filter bar

The bar above the board has one control per column: the **columns** list
picks which stages show; the other controls filter the cards. Text boxes take
a small syntax: `text` contains, `!text` does not contain, `=text` equals,
`>x` and `<x` larger or smaller (numbers, `YYYY-MM-DD` dates, otherwise text
order), `-` empty, `*` not empty. Filters combine with AND and stay in the
URL, so a view can be bookmarked. The `?` next to the Filter button shows
this syntax.

## Empty board

With no companies yet, the board offers three starts: import a spreadsheet,
add a company by hand, or set up BCC capture.

## The same data as text

`PIPELINE.md` in the data folder is the board as one Markdown page, regenerated
on every write: stages with counts and monthly value, overdue next steps,
silent accounts, parked companies, closed companies of the last 90 days.

Related: [Companies](/help/companies), [Calendar](/help/calendar), [Data format](/help/data-format)
