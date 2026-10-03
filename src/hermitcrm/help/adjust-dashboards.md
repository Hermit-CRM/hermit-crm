# Make it yours: dashboards

Pages of your own at `/d/<name>`: lists, counts, bars and report sections, written as `dashboards/<name>.toml` by you or your AI agent, and pinned in the sidebar if you like.

This page is the recipe an AI agent follows when someone asks for a
dashboard. It is complete: you can write any dashboard from it without
reading Hermit's code.

## What people ask for

- "Make a dashboard called Monday review with the prospects I should contact,
  what is due this week and the deals by stage. Pin it."
- "Show me my partners: how many, the quietest first, and where they are."
- "A page with every message I sent on LinkedIn in the last month that got no
  answer."
- "Count the companies tagged priority per stage."

A dashboard only reads. It never changes a record, so it is safe to try.

## The file

One file per dashboard: `dashboards/<name>.toml` in the data folder. The
name is the page's address, so use lower-case letters, digits and hyphens:
`dashboards/monday-review.toml` is `/d/monday-review`. Hermit picks up a new
or changed file on the next page load; no restart.

Top-level keys:

| Key | Required | What |
|---|---|---|
| `title` | yes | the page's title and its name in the sidebar |
| `pin` | no | `true` shows it in the sidebar, just above Settings (default `false`) |
| `description` | no | one line under the title |
| `widget` | yes | one `[[widget]]` table per widget, in the order they appear |

## Widgets

Every widget has a `type` and an optional `title` (a sensible title is made
up when you leave it out). Each one is a saved view of a list page, so
everything it shows links to that page with the same filters, and you land
on exactly the records you counted.

| Type | Keys | Shows |
|---|---|---|
| `list` | `scope`, `filters`, `columns`, `sort`, `limit`, `when` | rows of a list page; the first column links to the record |
| `count` | `scope`, `filters`, `when` | one number, linking to those records |
| `group` | `scope`, `by`, `filters`, `limit`, `when` | how many rows per value of `by`, as bars; each bar links to its rows |
| `report` | `section`, `period` | one section of the Reports page; every number links to the rows behind it |

- `scope`: which list page: `companies`, `contacts`, `messages` or `tasks`.
- `filters`: a table of column key to filter, e.g.
  `filters = { stage = "prospect", fit_score = ">70" }`. All of them must
  match (AND).
- `columns` (list only): the column keys to show, in order. Leave it out for
  the defaults: companies `name, stage, country, next_step, next_step_due`;
  contacts `name, company_name, title, last_touch`; messages
  `date, company_name, contact, channel, status`; tasks
  `text, due, who, company_name`.
- `sort` (list only): a column key, A to Z (small to large, old to new);
  put `-` in front for Z to A: `sort = "-fit_score"`. Empty values go last.
  Without it, rows come in the list page's own order.
- `limit`: how many rows a list shows (default 20; the rest are one click
  away), or how many bars a group draws (default 20). At most 50.
- `by` (group only): the column to count per value. A list value such as
  `tags` counts once per tag.
- `when` (tasks only): the Tasks page's date buttons, one or a list of
  `overdue`, `today`, `week` (the next 7 days), `later` and `none` (no date).
  These follow the calendar, unlike a fixed date in a filter.

## Scopes: filter keys and columns

The keys are the columns of the list page, the same ones its filter boxes
use. Fields you defined yourself in `fields.toml` work too, under their
`key`, but only on a list whose page shows them: a field needs that list in
its `show_in` (`companies` for a company field, `contacts` for a contact
field, `messages` for an interaction field).

**`companies`** (the Companies page). Temp-disqualified companies are left
out unless the `stage` filter asks for `temp-disqualified`, as on the page.

| Key | Kind | What |
|---|---|---|
| `name` | text | the company's name |
| `country` | fixed values | ISO code, e.g. `DE`, `NL`, `GB` |
| `stage` | fixed values | `prospect`, `engaged`, `discovery`, `offer`, `won`, `lost`, `disqualified`, `temp-disqualified` |
| `source` | fixed values | `linkedin-search`, `referral`, `inbound`, `event`, `list`, `network`, `other` |
| `tags` | text | every tag, as `a, b` |
| `last_touch` | date | the last interaction; empty means never contacted |
| `next_step` | text | the open task due first |
| `next_type` | fixed values | that task's type; only once task types exist (`none` = no type) |
| `next_step_due` | date | that task's due date |

**`contacts`** (the Contacts page), A to Z by name.

| Key | Kind | What |
|---|---|---|
| `name` | text | the person's name |
| `company_name` | text | their company |
| `title` | text | job title |
| `email` | text | |
| `linkedin` | text | profile URL |
| `last_touch` | date | the last interaction with them |
| `interaction_count` | number | how many interactions name them |

**`messages`** (the Messages page): every outbound email, LinkedIn message
or call with a body, newest first.

| Key | Kind | What |
|---|---|---|
| `date` | date | when it was sent |
| `company_name` | text | |
| `contact` | text | the person's name |
| `channel` | fixed values | `email`, `linkedin`, `call` |
| `country` | fixed values | the company's country |
| `stage` | fixed values | the company's stage |
| `status` | fixed values | the outcome: your outcomes (Settings), or `unknown` while you wait |
| `uses` | number | how often this exact text was sent |
| `body` | text | the message itself |

**`tasks`** (the Tasks page). Only open tasks, unless you filter on `status`.

| Key | Kind | What |
|---|---|---|
| `text` | text | the task |
| `due` | date | |
| `type` | fixed values | the task type; only once task types exist (`none` = no type) |
| `who` | text | the person, or the company for a company task |
| `company_name` | text | |
| `stage` | fixed values | the company's stage |
| `status` | fixed values | `open` or `done` |
| `done_on` | date | when it was ticked off |

## Filters

The same little syntax as the filter boxes on the list pages. Always write
the filter in quotes.

| Filter | Means |
|---|---|
| `"foo"` | contains foo (any case) |
| `"!foo"` | does not contain foo |
| `"=foo"` | is exactly foo (any case) |
| `">5"`, `"<5"` | larger / smaller: numbers, dates as `2026-09-01`, otherwise A to Z order |
| `"-"` | empty |
| `"*"` | not empty |

There is no `>=` or `<=`: for "5 or more" write `">4"`. A column with
**fixed values** takes one value or a list of values and no operators:
`stage = "prospect"` or `stage = ["prospect", "engaged"]` (either one).
For `tags`, use contains (`tags = "partner"`), since `=` would have to match
all tags at once.

## Report sections and periods

A `report` widget shows one section of the Reports page, exactly as Reports
draws it: `activity`, `funnel` (with the pipeline and its monthly value),
`outcomes`, `messages`, `sources` or `hygiene` (overdue next steps, silent
accounts, contacts without email). `period` is `7d`, `30d` (the default),
`90d`, `quarter`, `ytd` or `all` (from the first day in your data).

## Example: Monday review

The request: "Make a dashboard called Monday review with: prospects with fit
above 70 that I have not contacted yet, the replies I owe, and the deals by
stage with their value. Pin it to the sidebar." Here `fit_score` is a field
of the user's own (a number in `fields.toml` with `companies` in its
`show_in`).

```toml
title = "Monday review"
pin = true
description = "What to work on this week."

[[widget]]
type = "list"
title = "High-fit prospects, never contacted"
scope = "companies"
filters = { stage = "prospect", fit_score = ">70", last_touch = "-" }
columns = ["name", "fit_score", "country", "next_step"]
sort = "-fit_score"
limit = 20

[[widget]]
type = "list"
title = "Due this week"
scope = "tasks"
when = ["overdue", "today", "week"]
columns = ["text", "due", "who", "company_name"]

[[widget]]
type = "group"
title = "Deals by stage"
scope = "companies"
by = "stage"
filters = { stage = ["prospect", "engaged", "discovery", "offer"] }

[[widget]]
type = "report"
title = "Pipeline and its value"
section = "funnel"
period = "30d"
```

The replies you owe are worked out from who wrote last (Home's follow-up
list, `hermitcrm followups`), not by a list page, so a dashboard cannot show
them yet. Say so, and point to Home.

The sample account (`hermitcrm sample add`, and `init --demo`) writes its own
`dashboards/monday-review.toml`, which starts with the comment "A sample
dashboard". When the user asks for a Monday review and that file is there,
change it in place rather than writing a second one. Once it is changed it is
the user's, and `hermitcrm sample remove` leaves it.

## Example: partners

"Show me my partners: how many, the quietest first, and where they are."
Hermit has no separate partner records; partners are companies with a tag
(or a field of your own), and a dashboard gives them a page of their own.

```toml
title = "Partners"
pin = true

[[widget]]
type = "count"
title = "Partners"
scope = "companies"
filters = { tags = "partner" }

[[widget]]
type = "list"
title = "Quietest first"
scope = "companies"
filters = { tags = "partner" }
columns = ["name", "country", "last_touch", "next_step"]
sort = "last_touch"

[[widget]]
type = "group"
title = "By country"
scope = "companies"
by = "country"
filters = { tags = "partner" }
```

## Check it, then commit

1. Run `hermitcrm check`. Every problem in a dashboard is one line, such as
   `dashboards/monday-review.toml: widget 2: unknown column fitscore (did you
   mean fit_score?)`. Fix them all; the page itself lists the same lines and
   shows only the widgets without a problem.
2. Open `/d/<name>` and look at it (the app is usually on
   http://127.0.0.1:8765).
3. Commit just that file, one commit per change:
   `git add dashboards/monday-review.toml` and
   `git commit -m "ai: adjust: dashboard Monday review"`.

## Rules

- Write only `dashboards/<name>.toml`. When a field of the user's own must
  become a filter or column, add the list to its `show_in` in `fields.toml`;
  that shows it on the list page too, so say so.
- A dashboard never changes records. Records change only through the
  `hermitcrm` commands, never by editing their files for a dashboard.
- Never touch interaction bodies, `PIPELINE.md`, `.hermitcrm-format`,
  `.secrets.toml`, `.claude/settings.json` or the git history.
- To undo a dashboard, revert its commit (`git revert <sha>`) or delete the
  file in a new commit.

Related: [Reports](/help/reports), [Data format](/help/data-format), [AI agents](/help/ai-agents)
