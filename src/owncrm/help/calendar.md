# Calendar

`/calendar`: what is due, this month's next steps, future tasks, accounts going quiet, and meetings this week.

## Sections, top to bottom

1. **Top priority tasks**: every open next step due today or earlier, sorted by
   due date, each with a "log interaction" link and a **Mark done** button.
   (`/today` redirects here.)
2. **Meetings this week**: events in the next 7 days from the calendar import
   whose attendees match a company, linked to it. The **Import meetings now**
   button runs the same import as `owncrm calendar --apply`.
3. **The month grid**: Monday first; every open next step sits on its due date,
   past dates in red. Arrows move a month; "this month" comes back.
4. **Future tasks**: every other open next step, dated ones first by due date,
   then undated ones.
5. **Silent for N+ days, not closed**: active companies with no interaction for
   `silent_days` (default 14, set on the Settings page), sorted by how long
   they have been quiet.

## Tasks

A task is a company's next step plus its due date. Marking it done keeps the
text but takes it off this page, the board's overdue colouring and
`PIPELINE.md`; rewriting the next step or clearing it reopens it. Parked
(temp-disqualified) companies stay off the board but their next step still
shows here, so a "revisit in March" is not forgotten.

On the company page, a next step with a due date has an **Add to Google
Calendar** link: an all-day event on that date with a link back to the
company. No API, no account connection.

Related: [Pipeline](/help/pipeline), [Companies](/help/companies), [Settings](/help/settings)
