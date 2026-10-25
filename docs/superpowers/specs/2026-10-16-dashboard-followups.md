# Brief: three dashboard follow-ups

**For:** a fresh Claude Code session working on the Hermit CRM repo (the code,
not a data folder).
**Written:** 2026-10-16, after a review of an external "lessons from Claude
Dashboards" brief. That brief proposed rebuilding dashboards; they already
exist. These three items are what was worth keeping.

Read first: `CLAUDE.md` (repo rules), `src/hermitcrm/help/adjust.md` (what
Make it yours is), `src/hermitcrm/help/adjust-dashboards.md` (the dashboard
format), and the module docstrings of `src/hermitcrm/dashboards.py`,
`src/hermitcrm/adjust.py` and `src/hermitcrm/history.py`.

## Ground rules (do not break these)

- **Hermit never builds a change itself.** Make it yours shows ideas, hands a
  request to the user's own AI agent (deep link, command or copied prompt),
  and shows the result afterwards. Do not add an LLM call, a query language
  or a "generate dashboard" button inside Hermit.
- **Dashboards only read.** A `dashboards/<slug>.toml` file is written by the
  user or their agent; Hermit never rewrites it.
- **A broken file never breaks a page.** Problems go to `hermitcrm check` and
  the page's problem list; the widgets that are fine still show.
- **The help page is the agent's whole contract.** Anything new an agent may
  write must be documented in `help/adjust-dashboards.md`, completely enough
  that an agent can write it without reading code. `tests/test_dashboards.py`
  (around line 815) checks that the help mentions every widget type, section
  and period.
- No new runtime dependencies (no chart library); bars are drawn the way the
  `group` widget draws them now (`rs.bar(...)` in `templates/dashboard.html`).
- `.venv/bin/pytest` passes before every commit; commit messages start with
  `ai:`; fictional names and example.com only.
- Try every change in a demo folder: `.venv/bin/hermitcrm init /tmp/x --demo`,
  then `hermitcrm serve` there. The demo comes with a pinned "Monday review"
  dashboard at `/d/monday-review`.

Do the three items as three separate commits (or three PRs) in the order
below; they touch mostly different files and each one stands on its own.

---

## 1. The Adjust tab on a dashboard offers changes to that dashboard

**Already listed in `TODO.md` (around line 190).**

### Problem

On `/d/<slug>` the **Ask · Adjust** button's Adjust tab suggests "A Monday
dashboard" (make a new one), not changes to the dashboard you are looking at.
This is the conversational refinement loop ("add a filter for region", "sort
by fit score"), and it is the most useful of the three items.

### Cause

`adjust.page_kind()` (`src/hermitcrm/adjust.py`, around line 175) has no case
for `/d/...`, so it returns `"other"`. `adjust.starters_for("other", ...)`
then shows the starters whose `kinds` include `"other"`, and
`dashboard-monday` is first among them. `web.adjust_context()`
(`src/hermitcrm/web.py`, around line 1316) calls both.

### What to build

1. Add a page kind `"dashboard"` to `PAGE_KINDS` and to `page_kind()` for
   paths `/d/<slug>`. Leave a bare `/d` or `/d/` as `"other"`.
2. Add three or four starters with `kinds=("dashboard",)`, in the
   `"Dashboards"` family, that change *this* dashboard. Suggested set:
   - **Add a widget**: "Add to this dashboard: [the deals by stage with their
     value]."
   - **Change what it shows**: "On this dashboard, [only show companies in
     Germany] and [sort the prospects by fit score, highest first]."
   - **Pin or rename it**: "[Pin this dashboard to the sidebar] and rename it
     to [Weekly review]."
   - Optionally, **A copy for a variation**: "Make a copy of this dashboard
     for [partners instead of prospects]."
   Keep the house style: `[brackets]` for what the user edits, `{slots}` only
   for values `prefill()` provides. Each starter's `changes` should name the
   file, so the agent and the card both say which file changes.
3. The starter has to say *which* file. The agent already receives the page
   path (`adjust.prompt_for(..., path=...)` puts `/d/<slug>` in the prompt),
   but naming the file in the text is clearer and costs a few bytes. Either:
   - pass the slug into the starter values for this page (in
     `web.adjust_context()`, add `{"dashboard": slug, "dashboard_file":
     f"dashboards/{slug}.toml"}` to the values when `kind == "dashboard"`)
     and use `{dashboard_file}` in the starter text and `changes`; add a
     fallback to `DEFAULTS` so `render_starter()` never fails on other pages;
   - or keep the text generic ("this dashboard") and rely on the path in the
     prompt.
   Prefer the first. Mind `LINK_LIMIT` (500 bytes): starters plus page path
   must stay short enough to go out as a deep link, or they fall back to copy.
4. **The JS twin.** `static/adjust.js` rebuilds the prompt, link and command
   in the browser from data attributes the server renders (see the
   `adjust.py` docstring). Starters are rendered server-side, so this probably
   needs no JS change, but confirm that the prompt the browser builds for a
   dashboard starter matches `adjust.handoff()`. `tests/test_adjust.py` runs
   both on the same inputs when node is installed.
5. Remove the item from `TODO.md`.

### Tests (`tests/test_adjust.py`)

- Add `("/d/monday-review", "dashboard")`, `("/d", "other")` and a query
  string case to the `test_page_kinds` parametrisation (around line 217).
- `test_every_page_kind_gets_three_or_four_starters_that_fit_it` (around
  line 221) iterates `PAGE_KINDS`, so the new kind needs at least three
  starters or it fails. That is intended.
- A web test: GET `/d/monday-review` in a demo-like folder and assert the
  Adjust tab contains the new starter titles and the file name, and does not
  contain "A Monday dashboard".
- If you use `{dashboard_file}`: `render_starter()` on a non-dashboard page
  still renders (falls back to `DEFAULTS`).

### Done when

On `/d/monday-review` the Adjust tab shows the dashboard starters with
`dashboards/monday-review.toml` named. Clicking one hands a prompt that,
given to Claude Code in the demo folder, edits that file. Check that run by
hand once and say whether you did.

---

## 2. A `trend` widget: counts over time

### Problem

The four widget types (`list`, `count`, `group`, `report`) all answer "how
many now". None shows a change over time: touches per week, messages sent per
week, tasks falling due per week. That is the most common dashboard chart
people ask for, and the one thing Claude Dashboards does that Hermit cannot
express.

### Design (v1: keep it small)

A widget that counts the rows of a list page per week or month, by one date
column, over a period, and draws one bar per bucket, oldest first.

```toml
[[widget]]
type   = "trend"
title  = "Messages sent per week"
scope  = "messages"
by     = "date"          # a date column of that scope
every  = "week"          # "week" (Monday start) or "month"; default "week"
period = "90d"           # same values as report widgets: 7d 30d 90d quarter ytd all
filters = { channel = "linkedin" }   # optional, same as other widgets
```

- `by` must be a **date** column of the scope (`companies.last_touch`,
  `companies.next_step_due`, `contacts.last_touch`, `messages.date`,
  `tasks.due`, plus date fields from `fields.toml` that show on that list).
  `dashboards.columns_for()` knows each column's kind; `check` names the date
  columns when `by` is wrong, the same way `group` hints at a near column
  (`dashboards._hint()`).
- Reuse `PERIODS` and the period logic report widgets use
  (`reports.period_for()`, and `first_day()` for `all`) so periods mean the
  same everywhere.
- Rows with an empty date are left out (say so in the help). A list value is
  not possible here, since `by` is a date.
- Empty buckets are drawn as zero, so gaps show as gaps.
- **Every bar links**, like everything else on a dashboard: to the list page
  with the widget's filters plus that bucket's date range as a filter on
  `by`. **Known limit:** a list page carries one `f_<key>` value per column,
  and the filter syntax (`filters.py` docstring) has `>` and `<` but no way
  to say both at once, so a closed range ("this week only") cannot be
  expressed today. For v1, link each bar to its rows from the bucket start
  onwards (`>YYYY-MM-DD` the day before), or to the whole period, and add a
  TODO for a range syntax. Do not change the filter syntax in this item.
- Limit: at most `MAX_LIMIT` (50) buckets. `all` with `every = "week"` can
  exceed that; either clamp to the newest 50 buckets and say so under the
  chart, or make `check` warn. Pick one, document it.

### Where it goes

- `dashboards.py`: add `"trend"` to `TYPES`, its keys to `WIDGET_KEYS`
  (`type, title, scope, filters, by, every, period, when`), validation in
  `widget_problems()`, a `_trend_view()` next to `_group_view()`, a branch in
  `view()`, and a default title such as "Messages per week (90d)". Evaluate
  rows through the same `listing(scope, params)` callback the other widgets
  use, so filters behave exactly as on the list page.
- `templates/dashboard.html`: a block for `w.type == "trend"`, using the same
  `rs.bar()` macro horizontally (one row per bucket, label = week start or
  month) or a simple vertical row of bars in CSS. Match the existing look;
  `DESIGN.md` has the rules. It must read well in light and dark themes and
  on a phone.
- `help/adjust-dashboards.md`: a row in the widget table, the `by`, `every`
  and `period` keys, the date columns per scope, and one example under "What
  people ask for" ("Messages I sent per week this quarter").
- `docs/ARCHITECTURE.md`: if it lists the widget types, add `trend`.
- `CHANGELOG.md`: there is no unreleased section yet (the top is 0.7.5);
  start one above it, as earlier releases did.
- Optionally add a trend widget to the sample account's Monday review
  dashboard (`sample.py`) so new users see one; keep the sample deterministic.
- No migration: dashboards are not front matter.

### Tests (`tests/test_dashboards.py`)

- A trend widget over a fixed set of interactions gives the expected bucket
  counts for `week` and `month`, including empty buckets in between and a
  week that crosses a month boundary.
- Filters apply (only `linkedin` messages counted).
- `check` problems: `by` not a date column (with a hint naming the date
  columns), unknown `every`, unknown `period`, unknown key.
- A broken trend widget does not break the page; the other widgets show.
- Bar links carry the widget filters (and the date range, if supported).
- The help test around line 815 passes with the new type mentioned.

### Done when

A demo folder with a `trend` widget added to `dashboards/monday-review.toml`
shows weekly bars at `/d/monday-review`, `hermitcrm check` says `OK`, a typo
in `by` gives a helpful `check` line, and a screenshot in light and dark mode
looks right.

---

## 3. Show where a dashboard came from, with Undo

### Problem

Claude Dashboards shows each chart's query and when it was refreshed. In
Hermit the query is already visible (every number links to its rows), but a
dashboard page does not say who made it, when, or how to take it back. That
information exists: `history.recent_changes()` already lists commits that
touch `dashboards/*.toml` (see `history.is_extension_file()`), and the Make
it yours page has Undo for them.

### What to build

A short line on `/d/<slug>`, under the title or at the bottom:

> Last changed 2 days ago: "ai: adjust: monday review dashboard" · Undo ·
> All changes

- **Last changed**: the newest commit that touched `dashboards/<slug>.toml`,
  with `history.when_text()` for the time and the commit subject.
- **Undo**: the same POST the Make it yours page uses (`/yours/undo`, with
  the CSRF token and `sha`), shown only when `Change.can_undo` is true. After
  undo, redirect back to the dashboard, or to `/yours` if the undo removed
  the file (an undone "create" makes the page a 404). Today
  `web.yours_undo()` always redirects to `/yours?undo=1` with a flash, and on
  a conflict to `/yours?request=...` with a prefilled agent prompt. Keep the
  conflict path as it is; for success, add an optional `back` form field that
  is used only when it is a local path starting with `/d/` and the dashboard
  file still exists.
- **All changes**: link to `/yours` (Recent changes).
- Nothing at all when the folder is not a git repository, git fails, or the
  file has no commit yet (a hand-written dashboard not committed): the page
  must never fail because of this line.

### Where it goes

- `history.py`: a small function, e.g. `last_change(root, path) -> Change |
  None`, using `git log -1 --format=... -- <path>`. Do not scan 500 commits
  for one page; it runs on every dashboard page load. Reuse the `Change`
  dataclass and the revert detection (`_REVERTS`) so `can_undo` stays
  correct; if detecting "undone" needs a wider scan, it is fine to show the
  line without Undo rather than slow the page.
- `web.dashboard_page()`: pass the change to the template.
- `templates/dashboard.html`: the line, in the page's muted style.

### Tests

- There is no `tests/test_history.py`; undo and Recent changes are tested in
  `tests/test_adjust.py` and `tests/test_cli.py`. Add `tests/test_history.py`
  for the new function, reusing their git-folder fixtures: `last_change()`
  returns the newest commit for a path, `None` for an untracked file and for
  a folder without git, and marks a reverted change as not undoable.
- A web test: after committing a dashboard in a temporary git folder, the
  page shows the subject and an Undo form with the right `sha`; without git
  the page still renders.
- Undo from the dashboard page reverts the commit and lands somewhere that
  exists (dashboard or `/yours`).

### Done when

In a demo folder, ask Claude Code (via the Adjust tab from item 1) to change
`monday-review`, reload `/d/monday-review`, see the new line with the agent's
commit, press Undo, and see the dashboard back as it was.

---

## Out of scope

Do not build these, even if they look related:

- An LLM, SQL or natural-language query engine inside Hermit.
- A `hermitcrm dashboard` CLI subcommand (the agent writes the file).
- `dashboards.enabled` or per-template switches in `config.toml`.
- Sharing dashboards by link or exposing them beyond `127.0.0.1`.
- New filter syntax (item 2 may note a TODO if date ranges are missing).

## When you finish

Report per item: what changed (files), test results, what you checked in the
demo folder by hand, and anything you could not check (for example a real
deep link on macOS, or a real agent run). Leave the work on a branch; do not
push or open a PR unless asked.
