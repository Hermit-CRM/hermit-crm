# Calendar

`/calendar`: meetings this week, your tasks on their due date, and accounts going quiet. The list of all tasks, with filters, is on the [Tasks](/help/tasks) page.

## Sections, top to bottom

1. A line with the number of tasks due today or earlier, linking to them on
   the Tasks page.
2. **Meetings this week**: events in the next 7 days from the calendar import
   whose attendees match a company, linked to it. The **Import meetings now**
   button runs the same import as `hermitcrm calendar --apply`.
3. **The month grid**: Monday first; every open task sits on its due date,
   past dates in red, a company's next step in normal text and its other tasks
   in the lighter style. Arrows move a month; "this month" comes back.
4. **Silent for N+ days, not closed**: active companies with no interaction for
   `silent_days` (default 14, set on the Settings page), sorted by how long
   they have been quiet.

## Tasks

Marking a task done takes it off this page, the board's overdue colouring and
`PIPELINE.md`, and records the day it was done. Parked (temp-disqualified)
companies stay off the board but their tasks still show here, so a "revisit in
March" is not forgotten.

On the company page, a next step with a due date has an **Add to Google
Calendar** link: an all-day event on that date with a link back to the
company. No API, no account connection.

Related: [Tasks](/help/tasks), [Pipeline](/help/pipeline), [Companies](/help/companies), [Settings](/help/settings)
