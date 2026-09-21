# Task types: your own labels for to-dos, set in Settings

Proposal, 2026-09-21, **approved by Gijs the same day**. Follows the Tasks
rework (#39, merged as 5c6840d). Built as one PR.

## What is there today

Since #39, `/tasks` has a **kind** column with two values Hermit works out
itself: `next step` (the company's open to-do due first) and `task` (everything
else). You never pick it, so it cannot say *why* a to-do exists: following up a
live deal, prospecting a new account, or reviving a lost one.

## What changes

A to-do can carry a **type** from a list you keep in Settings, for example
*pipeline follow-up*, *prospecting*, *lost deals*. Each type has a colour. The type:

- is **optional**: blank means "no type", and every existing to-do stays valid;
- is a **label and a filter**: it changes no dates, stages or ordering;
- shows wherever the to-do shows, and the next step's type also shows on the
  **Companies list** and the **board**.

"Next step" keeps the meaning #39 gave it (the open to-do due first). It stops
being a column value and becomes a **next** badge on the row plus a
**Next steps only** chip on `/tasks`.

## 1. Settings: "Task types"

A new section just before **Outcomes**, listed in the Settings contents line.
One row per type: **name** and **colour**, with **Up**, **Down** and **Delete**
buttons, plus an empty row to add one. Editing a name renames the type. The
order is the order of every dropdown and filter.

Colours come from a fixed palette: `green`, `blue`, `amber`, `red`, `violet`,
`grey`. Each is defined in `tokens.css` for the light and the dark theme (a
background and a text colour per chip). No free hex values, so no chip can
become unreadable in either theme.

Stored in `config.toml` as one line, written with the existing
`set_config_values` (it keeps comments and other lines):

```toml
task_types = [{name = "pipeline follow-up", colour = "green"}, {name = "prospecting", colour = "blue"}, {name = "lost deals", colour = "amber"}]
```

`toml_value` learns to write a list of inline tables. Reading accepts the same
shape; an entry without a known colour gets `grey`, and a duplicate or blank
name is dropped.

Validation on save: names are trimmed (inner whitespace collapsed), must be
unique (case-insensitive) and at most 40 characters. Any other character is
fine: tasks are written with YAML's own flow dumper, which quotes when needed.
Errors show on the form like Outcomes errors.

A new data folder starts with **no types**; the section says in one line what
types are for. Gijs's folder gets his three when he first saves the section (or
by hand; see "Rollout").

### Rename and delete

- **Rename** (same row, new name) also renames the type on every to-do that
  carries it, company tasks, contact tasks and next steps, in the same single
  commit: `settings: task type "X" renamed to "Y" (N to-dos)`. (Settings
  saves do not commit `config.toml` today; that is the separate
  `fix/settings-commit-config` work, so this commit holds the data files.)
  The row's old name travels as a hidden field, so a rename is told apart from
  delete-plus-add.
- **Delete** leaves the value on existing to-dos. They show it as a grey chip
  with the tooltip "not in Settings", and it stays filterable. Nothing is
  rewritten.

## 2. Storage

| Where | Key | Written |
|---|---|---|
| Task in `company.md` or a contact file | `type` inside the existing map: `- {text: send deck, due: 2026-09-24, type: pipeline follow-up}` | only when set |
| Company next step | `next_step_type` | only when set, next to `next_step_due` |

Absent keys stay absent, so untyped files are byte-identical after load and
save, and there is **no data-format bump and no migration**. `Task` gets
`type: str = ""`, `Company` gets `next_step_type: str = ""`, `Todo` gets
`type` (filled from either). `next_step_type` joins the known company keys in
`models.py` and `store.py`.

Validation reuses the Outcomes rule (`store.py`): a type must be empty, one of
the configured names, or **unchanged** (a legacy value from a deleted type
survives any save). Unknown types from a hand edit load fine and show as grey
chips. The running app picks up a Settings change at once (`refresh_config`
updates `store.task_types`).

## 3. Where you set and see it

| Place | Change |
|---|---|
| Add-task forms: company page, contact page (`task_list` macro), `/tasks` | **type** dropdown: blank + your types. Hidden when no types exist |
| Next-step form (`macros.html`) | **type** dropdown saving `next_step_type` |
| Open to-do rows on company and contact pages | small type dropdown that saves on change: `POST /companies/{slug}/todo-type` with `index` (empty for the next-step fields), `contact`, `text` (stale-index guard), `type` and `back`. One route for tasks and the next step; no need to delete and re-add |
| `/tasks` | `kind` column becomes **type**: coloured chip, enum filter with your types plus `(none)`. `next` badge in the *what* cell. **Next steps only** chip (`next=1`) beside the date chips, with a count |
| Companies list | new **next type** column (chip, enum filter) from `next_todo().type` |
| Board | the next step's chip on each card, after "next: ..." |
| Company page task list | chip after the task text |
| `PIPELINE.md` | `next: send deck [pipeline follow-up], due 2026-09-24`; nothing when untyped |
| MCP | `next_step_type` on company update, same validation (MCP has no task tools today) |
| CLI | `next_step_type` settable like `next_step_due` |

The chip is one macro (`type_chip(name)`), so every place renders it the same.
Colour is looked up by name from Settings at render time, so changing a type's
colour shows everywhere at once and touches no data file.

## 4. What does not change

- What counts as the next step, and every date, stage and ordering rule.
- Follow-up radar, meeting briefs, reports, importer: they ignore the type.
- Old `?f_kind=` links: the column is gone, so the filter is ignored and the
  page shows unfiltered. Single-user app; no redirect.

## 5. Tests

Frozen dates only (see the date-coupled-tests note); `-p no:randomly` is a no-op here.

- **Model:** `type` and `next_step_type` round-trip; an untyped company and
  contact file are byte-identical after load/save; a type with `:` or `#` in it
  round-trips.
- **Config:** `toml_value` writes a list of inline tables that `tomllib` reads
  back; other lines and comments survive; unknown colour → grey; duplicate and
  blank names dropped.
- **Store:** new to-do with unknown type rejected; unchanged legacy type kept;
  rename rewrites company tasks, contact tasks and `next_step_type` in **one**
  commit and counts them; delete rewrites nothing.
- **Web:** Settings add, rename, delete, reorder, and each validation error;
  dropdowns and the Companies column hidden with no types; set type on create and via the row dropdown;
  `/tasks` filter by type and `(none)`; `next=1` chip and count; chip on the
  Companies list and the board; grey "not in Settings" chip for a deleted type.
- **PIPELINE.md:** the bracketed type appears when set and not otherwise.
- Replace the `f_kind` tests from #39.

## Rollout

After merge and Gijs's test: deploy per the usual steps (install from the
merged sha on GitHub). `migrate --dry-run` must report nothing. Then add the three
types in Settings: pipeline follow-up (green), prospecting (blue), lost deals
(amber). That is a normal `settings:` commit in the data folder.

## Gijs's 2-minute test (goes in the PR)

1. Settings → Task types: add the three, save. Rename *lost deals* to *lost
   deal revival*, save.
2. A company page: add a task with type *prospecting*; change its type from the
   row dropdown.
3. `/tasks`: filter type = *prospecting*, then `(none)`; click **Next steps only**.
4. Companies list and board: the next step shows its coloured chip.
5. Switch theme to dark: chips stay readable.
