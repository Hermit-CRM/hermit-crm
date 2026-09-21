# Tasks: many per company, one overview with filters

Proposal, 2026-09-21. **Decided the same day** (see "What Gijs decided" at the
end, which overrides the proposal where they differ). Built as one PR.

## What is there today

There are two kinds of to-do, stored separately:

| | Next step | Task |
|---|---|---|
| Stored in | `next_step`, `next_step_due`, `next_step_status` in `company.md` | `tasks:` list in `company.md` or a contact file |
| How many | **one per company** | unlimited, on the company and on each person |
| Used by | PIPELINE.md, board, companies list, follow-up radar (`followups.py`), meeting briefs, reports, importer, MCP, CLI | Home "What needs doing", Calendar, company and contact pages |

The data model already allows many tasks per company. It feels like a limit of
one because of how the company page works:

1. The Tasks section opens with the next step and its **"Save next step"** form.
   The form for more tasks sits below, under a small heading ("Everything else you
   owe them").
2. Saving a new next step **overwrites** the open one. The old text only survives
   in git history, so it is lost without warning.
3. You cannot turn a task into the next step, or the next step back into a task.

The overview problem: the Calendar page shows to-dos in three tables that are
split on two different axes. Next steps are split by date ("Top priority", "Future
tasks"); tasks are not split at all ("Your task list"). Next steps on closed
companies are hidden, but tasks on closed companies are not. There is no way to
filter.

## Part 1: many tasks per company, one of which is the next step

### Options

- **A. One list, one pinned (recommended).** On the page, the company has one task
  list. One task can be marked as the next step: it is pinned at the top with a
  "next step" label. Underneath, the next step stays in its own fields, so nothing
  else changes.
- B. Replace the next step with tasks: the pipeline's "next" becomes the open task
  with the earliest due date. Rejected. It is a data format 7 migration of your
  live folder, it touches 176 references in 21 files (PIPELINE.md, the
  follow-up radar, briefs, reports, importer, MCP, CLI), and "earliest due" is
  not the same as "what moves the deal". The `Task` docstring keeps the two apart
  on purpose, so the pipeline stays one line per company.
- C. Allow several next steps per company. Rejected. The pipeline line, the
  overdue check and the follow-up radar would each need a rule for which one
  counts.

### Design (option A)

Company page, Tasks section:

- **One table.** The next step comes first with a `next step` label, then the
  company's tasks, then each person's tasks under their name (as now).
- **One form: "Add task"** (text, due, optional person) with a checkbox **"make
  this the next step"**. The checkbox is ticked by default when the company has
  no open next step, so a new account still gets one.
- **Nothing is overwritten any more.** Making something the next step while
  another one is open moves the old next step into the task list, keeping its text
  and due date.
- Row actions:
  - task: `Done`, `Delete`, **`Make next step`** (it moves out of the list into
    the next-step fields, and the current open next step, if any, moves into the
    list; one commit, `task: <slug> made next step`)
  - next step: `Mark done`, **`Move to tasks`** (leaves the company with no next
    step, which the pipeline already shows as `next: none`), `Add to Google
    Calendar`
- Contact tasks can be made the next step too. It then moves to the company
  fields, because the next step belongs to the deal.

What stays the same: the data format, PIPELINE.md, board, companies list, the
follow-up radar, briefs, reports, importer, MCP and CLI. The Calendar and Home
already show both kinds, so they need no change for part 1.

New store methods: `promote_task(slug, index, contact="", text="")` and
`demote_next_step(slug)`. Both check `text` the way `_task_at` does, so a stale
page cannot move the wrong row. Each makes one commit.

## Part 2: one overview of all tasks, with filters

### Where it goes

- **Recommended:** a `/tasks` page that **replaces "Calendar" in the navigation**
  (label "Tasks"), so there are still 10 entries. The page opens with the filtered
  task table. A "Calendar view" link at the top goes to `/calendar`, which keeps
  the month grid, meetings this week and "Silent for N+ days" but loses its three
  task tables.
- Alternative: an 11th navigation entry "Tasks" next to Calendar. Simpler to
  build, but it adds a menu item, and the to-do lists would still be in two places.

### The table

One row per open item, whether next step or task:

| column | filter (reuses `filters.py`, the one board/companies/contacts use) |
|---|---|
| due | quick chips: **Overdue · Today · Next 7 days · Later · No date**; the date operators (`<2026-10-01`, `-` for none) also work |
| what | text contains / does not contain |
| kind | `next step` / `task` |
| for | company or person name |
| company stage | multi-select from your configured stages |
| status | `open` (default) / `done` |

- **Defaults:** open items only, closed companies hidden (a chip "include closed"
  shows them), sorted by due date with undated last. Every column is sortable,
  like the Companies page.
- **The URL holds the filters**, so a view can be bookmarked. Home's link
  becomes "All tasks" and points to `/tasks`. Marking done sends you back to the
  same filtered view.
- **Row actions:** `Done`, plus `Make next step` on tasks (from part 1).
- **Add task** form above the table (company, optional person, due, "make this
  the next step").
- A count per chip (for example "Overdue 4"), so the page doubles as a to-do
  summary.

### Not in this proposal

- **Done date.** Tasks only store `done: true`, not when, so "done this week" is
  not possible. Adding an optional `done_on` key would be backward compatible
  (unknown keys are kept), but it is a data format change, so it is left out
  unless you want it.
- Owner / assignee: single user, not needed.
- Recurring tasks.

## Tests (both parts)

- Promote and demote: the old next step moves into the list with its due date; a
  stale page (index or text changed) is refused; each action makes exactly one
  commit.
- Contact task → next step lands on the company.
- Overview: each filter and chip, the closed-company default, sort order with
  undated last, redirect back to the filtered URL after `Done`.
- Old links keep working: `/today` (now `/calendar#top-priority`) and the
  `#task-list` redirect after creating a task both go to `/tasks`.
- Dates frozen in tests, not moved forward (see LEARNINGS / date-coupled tests).

## Does this change what's live, your data, or anything public?

- Live app: yes, the company page Tasks section (part 1) and the navigation plus
  Calendar page (part 2). Testers see it after their next build.
- Your data: no format change and no migration. Existing next steps and tasks show
  up as they are.
- Public: no.

## What Gijs decided (2026-09-21)

1. Option A: one list per company. **But** (answer 3) the next step is not
   pinned or picked: *"the next step is the first thing due in the calendar for
   that specific company"*. So there is no "Make next step" / "Move to tasks"
   and no checkbox. `Company.next_todo()` returns the open to-do due first,
   across the `next_step` fields, the company's `tasks` and its contacts'
   `tasks`; undated after dated; ties keep stored order (field, company tasks,
   contacts). No data is moved between fields, so there is no migration.
   Everything that read `next_step`/`next_step_due` for display (PIPELINE.md,
   board, Companies table, follow-up radar, briefs, reports, Home, Calendar)
   reads the derived one.
2. "Tasks" is an **11th navigation entry** after Calendar. The Calendar keeps
   the month grid (now every open task), meetings and silent accounts; its
   three task tables are gone, replaced by one line linking to `/tasks`.
3. See 1.
4. **Completion dates**: `done_on` on tasks, `next_step_done_on` on the company,
   written only while done, so files without them stay byte-identical. No
   data format bump: both keys are optional and additive.
