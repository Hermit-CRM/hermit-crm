# Make it yours: deal stages

Recipe for an AI agent: rename, add, reorder or remove the stages a deal goes through with `hermitcrm stages`, always as a dry run first.

Use this recipe when the user wants their own stages: "call engaged contacted", "add a qualified step before discovery", "drop the temp-disqualified stage". The stages are a setting (`stages` in `config.toml`), but **do not edit that line by hand and do not edit company files**. A stage name is stored on every company and in its `stage_history`, so a rename has to rewrite them all. `hermitcrm stages` does both, in commits you can undo.

## The rules

1. **Use `hermitcrm stages`.** It validates names and roles, saves `config.toml`, rewrites or moves the companies and makes **one commit** for all of it, with the subject `ai: adjust: ...`, so one undo takes the whole change back.
2. **Dry run first.** Without `--apply` nothing is written. It prints the new list, how many companies each change touches (with a few slugs) and anything that still names an old stage.
3. **Show the dry run to the user and wait for a yes.** A stage change rewrites record files, so it is not one of the keys you may write without asking. Run `--apply` only after the user has said yes to that exact change.
4. **Run `hermitcrm check` afterwards** and tell the user if it reports anything. `dashboards/*.toml` and `routines.toml` that name an old stage are *not* rewritten by the command; the dry run lists them, and `check` flags the old name (`unknown value 'engaged'`). Fix those files after the user agrees (`hermitcrm help adjust-dashboards`, `hermitcrm help adjust-routines`).
5. Tell the user what changed and how to undo it: the commit id (`git log -1`), and `hermitcrm undo <id>` reverses the whole change, the setting and the companies, with a new commit.

## What a stage is

A stage has a **name** and a **role**. The name is what you see; the role tells Hermit what the stage means, so no name is special.

| Role | Meaning |
|---|---|
| `open` | A column on the board and a step in the funnel. The **first** open stage is where a new company starts and where a requalified one returns. When a company in it gets its first outbound message, it moves to the next stage, if that is open too. |
| `won` | A deal closed won. Counts for the win rate and ends the funnel. |
| `lost` | A deal closed lost. A **reason is required**. Counts against the win rate. |
| `closed` | Any other end, such as disqualified. Keeps its reason, not in the win rate. |
| `parked` | Out of the pipeline for now, with a date to come back (`requalify_on`); it returns to the entry stage on that day. |

An `open` stage can also be **valued**: its heading in `PIPELINE.md` shows the monthly value. By default `discovery` and `offer` are valued.

The defaults, used when `config.toml` has no `stages` line:

```text
prospect (open)  engaged (open)  discovery (open, valued)  offer (open, valued)
won (won)  lost (lost)  disqualified (closed)  temp-disqualified (parked)
```

Names are lowercase `a-z`, `0-9` and single hyphens, at most 30 characters. `yes`, `no`, `on`, `off`, `true`, `false`, `null` and all-digit names are refused, because YAML would read them as something else. At least one stage must be `open`; the others can be absent (no `parked` stage means no "until" date; no `won` stage means the funnel ends at the last open stage).

## Commands

```text
hermitcrm stages                                   the stages, their roles and companies
hermitcrm stages rename OLD NEW [--apply]
hermitcrm stages add NAME [--role open] [--valued] [--after STAGE] [--apply]
hermitcrm stages move NAME (--after STAGE | --first) [--apply]
hermitcrm stages set NAME [--role ROLE] [--valued yes|no] [--apply]
hermitcrm stages remove NAME --move-to STAGE [--reason TEXT] [--apply]
```

- `rename` rewrites `stage` and every `stage_history` entry (`from` and `to`) on every company, in one commit. A rename does not change the `updated` date of a company.
- `add` puts a new open stage after the last open one unless you say `--after`; other roles go to the end.
- `remove` needs `--move-to` when companies are in the stage: they are moved with an ordinary stage change, so each history records it. Moving into a `lost` stage needs `--reason`.
- `set --role lost` is refused while companies in that stage have no reason.
- Putting a new stage first, or moving one first, changes the entry stage. The start of an old history is "created in the entry stage", so the command first writes that start into the files of companies that only imply it (in the same commit), and nothing is re-dated.

## Worked example: rename and insert

The user asks: "Call engaged contacted, and add a qualified step after it."

```bash
hermitcrm stages rename engaged contacted
```

```text
Stages after this change:
  prospect  open  341 companies
  contacted  open  21 companies (was engaged)
  discovery  open valued  1 company
  ...
Rename "engaged" to "contacted": 28 companies rewritten (21 in it now, the rest only in their stage_history), e.g. acme, beta, gamma
Dry run; add --apply to write (one commit, undoable).
```

Your reply: "Renaming engaged to contacted rewrites 28 company files (21 are in it now, the rest passed through it). Shall I apply it?" After a yes, run it with `--apply`, then:

```bash
hermitcrm stages add qualified --after contacted
hermitcrm stages add qualified --after contacted --apply
hermitcrm check
```

## What `hermitcrm check` says

- `config.toml: stages entry 2: ...` the setting is wrong (a bad name, an unknown role, a stage twice, no open stage). The app keeps the stages it had until the line is fixed.
- `companies/<slug>: stage 'x' is not in config.toml stages` a company is in a stage the setting does not list (the setting was edited by hand). The company still loads. It sits off the board, in grey in the Companies list, until it is moved to a stage that exists or the stage is added back.
- `dashboards/...: filter stage: unknown value 'engaged'` a dashboard or routine still names an old stage.

Related: [Make it yours](/help/adjust), [CLI](/help/cli), [Companies](/help/companies), [Pipeline](/help/pipeline), [Settings](/help/settings)
