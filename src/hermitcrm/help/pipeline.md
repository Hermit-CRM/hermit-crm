# Pipeline

The board at `/`: one column per open stage, cards you can move with a dropdown, closed companies in lists below.

## Columns and cards

The four open stages are columns: **prospect**, **engaged**, **discovery**,
**offer**. A column with no companies is drawn narrow so all four fit on one
screen. A card shows the company name (a link), days in the current stage,
the country, the last touch (`email out 2026-09-14 (jane-doe)`), the next step
with its due date (red when overdue, struck through when done) and the monthly
value when set. The stage dropdown on a card saves on change; choosing
**lost** sends you to the company page to give a reason first.

Cards are ordered by next-step due date (earliest first, no date last), then
by last touch (most recent first).

## Closed and parked

Below the board, **won**, **lost**, **disqualified** and **temp-disqualified**
are collapsed lists with the reason and, for parked companies, the date they
come back to prospect (`requalify_on`). That return happens by itself: on any
page view, a parked company whose date has arrived goes back to prospect in
one commit.

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
