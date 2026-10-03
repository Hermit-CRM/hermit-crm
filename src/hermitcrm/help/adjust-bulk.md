# Make it yours: bulk changes

Recipe for an AI agent: change many records at once with `hermitcrm set`, always as a dry run first, then one commit that can be undone.

Use this recipe when the user wants the same change on many companies, contacts or
messages: tag a group, score a list, move a batch to a stage, set an outcome on
old messages. The user does not need to know any syntax. You write the command.

## The rules

1. **Use `hermitcrm set`. Never edit many files by hand and never write a script.**
   The command validates every value the way the forms do, writes the files the
   standard way (keys Hermit does not know are kept), checks them, and makes one
   commit. A script or a hand edit can leave half the folder changed.
2. **Dry run first.** Without `--apply` nothing is written. It prints how many
   records match, how many would change and a few before and after lines.
3. **Show the dry run to the user and wait for a yes.** Quote the count and the
   sample lines in your reply. Run `--apply` only after the user has said yes to
   that exact change. A yes to an earlier, different command is not a yes.
4. **Then run the same command again with `--apply`.** It prints the commit, for
   example `23 companies changed in one commit a1b2c3d. Undo: hermitcrm undo a1b2c3d`.
   Tell the user that line.
5. **Do not make another commit for it.** `hermitcrm set --apply` has made the
   commit, with the subject `bulk: <summary>`. Pass `--message "..."` to word the
   summary yourself (Hermit adds the `bulk: ` in front).
6. **Run `hermitcrm check` afterwards** and tell the user if it reports anything.

## What it can change

```text
hermitcrm set <companies|contacts|interactions> [--where KEY=VALUE ...] [--all]
    [--set FIELD=VALUE ...] [--unset FIELD ...]
    [--add-tag TAG ...] [--remove-tag TAG ...] [--stage STAGE]
    [--apply] [--message TEXT]
```

| Scope | Records | Fields you can set or clear |
|---|---|---|
| `companies` | the Companies list | `website`, `linkedin`, `country`, `source`, `lost_reason`, `requalify_on`, `value_eur_month`, `product_oneliner`, `next_step`, `next_step_due`, `next_step_status`, `next_step_type`, `tags`, and your own fields |
| `contacts` | the Contacts list | `title`, `linkedin`, `email`, `phone`, `role`, `language`, and your own fields |
| `interactions` | the rows of the Messages page (messages you sent) | `outcome`, `subject`, and your own fields |

- `--set FIELD=VALUE` sets a field. An empty value (`--set next_step=`) clears it,
  and so does `--unset FIELD`. Values are read the way the forms read them: numbers,
  dates as `YYYY-MM-DD`, the choices of a `select` field, country codes such as `DE`.
- `--add-tag` and `--remove-tag` edit a company's tags (companies only). Tags are
  matched without regard to case, and a tag that is already there is not added again.
- `--stage` moves companies the way the stage buttons do: it goes into the stage
  history and the stage rules apply. `--stage lost` needs `--set lost_reason="..."` in
  the same command. Moving a company out of a parked or closed stage clears the
  reason and the requalify date, and the dry run shows that.
- Your own fields (from `fields.toml`) work like built-in ones. A field that does not
  exist is refused with a hint. Add it to `fields.toml` first, see
  `hermitcrm help adjust-fields`.

## Choosing the records: `--where`

`--where KEY=VALUE` means exactly what typing VALUE into the filter box of that
list page means. Repeat it; every `--where` has to hold. Quote the value, because
the shell reads `>` and `<`.

| Value | Matches |
|---|---|
| `foo` | the text contains foo (not case sensitive) |
| `=foo` | the text equals foo |
| `!foo` | the text does not contain foo |
| `>5`, `<5` | larger or smaller: numbers on number fields, dates (`YYYY-MM-DD`) on date fields, alphabetical order on text fields |
| `-` | is empty |
| `*` | is not empty |

On a column with fixed choices (stage, country, source, channel, status, a `select`
field) give the exact choice. Give several to mean "any of them":
`--where stage=prospect,engaged` or `--where stage=prospect --where stage=engaged`.
`-`, `*`, `!x` and `=x` work there too.

The keys, per scope. A column heading of the list also works as a key, with an
underscore for a space (`last touch` is `last_touch`, and the Messages heading
`outcome` is `status`):

| Scope | Keys |
|---|---|
| `companies` | `name`, `country`, `stage`, `source`, your own fields, `tags`, `last_touch`, `next_step`, `next_type` (when you have task types), `next_step_due` |
| `contacts` | `name`, `company_name`, `title`, `email`, `linkedin`, `last_touch`, `interaction_count`, your own contact fields |
| `interactions` | `date`, `company_name`, `contact`, `channel`, `country`, `stage`, `status` (the outcome, explicit or worked out), `uses`, your own interaction fields, `body` |

Things worth knowing:

- `tags=priority` matches a company whose tags contain the text "priority". `=priority`
  matches only a company whose whole tag list is "priority". Use `!priority` for "no
  such tag".
- `>` and `<` compare numbers only on a number field. A field that holds text such as
  `~45` compares alphabetically, which is wrong for sizes. If the user's size field is
  text, say so and offer to make it a number field first (`hermitcrm help adjust-fields`).
- The Companies page hides parked companies (`temp-disqualified`) unless you ask.
  `hermitcrm set` does not hide them: `--where country=DE` finds them too. Add
  `--where stage=!temp-disqualified` to leave them out.
- Without any `--where` the command is refused. To change every record, say so with
  `--all` (it cannot be combined with `--where`).

## Worked example 1: tag a group

The user asks: "Tag every prospect in Germany with more than 50 FTE as priority."

```bash
hermitcrm set companies --where stage=prospect --where country=DE \
    --where 'fte_estimate=>50' --add-tag priority
```

Here `fte_estimate` is a number field. Output (nothing is written):

```text
Dry run: add tag priority on companies where stage=prospect, country=DE, fte_estimate=>50
25 companies match. 23 would change; 2 already look like this and are skipped.

  northwind-robotics: tags: robotics, demo → robotics, demo, priority
  ...
  and 18 more.

Nothing changed. Run again with --apply to change 23 companies in one commit.
```

Your reply to the user: "25 German prospects have more than 50 FTE. 2 already have the
tag, so 23 would change, for example northwind-robotics. Shall I apply it?" After a
yes:

```bash
hermitcrm set companies --where stage=prospect --where country=DE \
    --where 'fte_estimate=>50' --add-tag priority --apply
hermitcrm check
```

## Worked example 2: disqualify a batch

The user asks: "Disqualify every prospect I scored below 3. Reason: weak fit."

```bash
hermitcrm set companies --where stage=prospect --where 'my_score=<3' \
    --stage disqualified --set lost_reason="Weak fit"
```

The dry run shows `stage: prospect → disqualified` and `lost_reason: (empty) → Weak fit`
for each record. Show it, wait for the yes, run the same command with `--apply`. The
stage history of each company records the move, exactly as the stage buttons do. If
the user changes their mind, the undo command in the output reverses the whole batch.

## Worked example 3: outcomes on old messages

The user asks: "Every LinkedIn message I sent before 26 September that nobody has
answered counts as unsuccessful. I do not want to wait for the 14 days."

```bash
hermitcrm set interactions --where channel=linkedin --where status=unknown \
    --where 'date=<2026-09-26' --set outcome=unsuccessful
```

`interactions` here are the rows of the Messages page, so `status=unknown` is the
Messages filter: no explicit outcome, no reply, and still inside the message window
(Settings, `message_window_days`). The outcome must be one of the user's configured
outcomes; anything else is refused with the allowed list. The message bodies are never
touched.

More one-liners:

```bash
hermitcrm set contacts --where 'title=CEO' --set role=decision-maker
hermitcrm set companies --where 'last_touch=-' --where stage=prospect --set next_step="Research" \
    --set next_step_due=2026-10-15
hermitcrm set companies --where tags=old-list --remove-tag old-list --add-tag archive
hermitcrm set companies --where stage=lost --where 'tags=!lost' --add-tag lost
```

## What is refused, and why

Everything refused prints why and exits 2, and nothing is written.

| You tried | Why not |
|---|---|
| no `--where` and no `--all` | it would change every record |
| `--set body=...`, `notes`, `message` | bodies are the record of what was said and are never rewritten, on any scope |
| `name`, `slug`, `first_name`, `last_name` | they name the record or its file; change one record in the web app |
| interaction `date`, `channel`, `direction`, `contact` | they are part of the file name |
| `created`, `updated`, `stage_history`, `tasks`, an interaction's `source` or `message_id` | Hermit keeps these itself |
| `--set stage=...` | use `--stage`, so the move goes into the stage history |
| `--add-tag` on contacts or interactions | only companies have tags |
| a field that does not exist | add it to `fields.toml` first (`hermitcrm help adjust-fields`) |
| a value the form would refuse | a bad number, date, choice, country, outcome, or `--stage lost` without a reason |
| `--unset` on a field that cannot be empty | `source`, `next_step_status`: set a value instead |

The command is all or nothing. If one record cannot take the change, none are
written, and the message names the record. A change that would also alter a field
nobody asked about is refused too, as a bug in Hermit CRM to report.

## If something goes wrong

- Exit 2: refused before anything was written. Read the message, fix the command, run
  the dry run again.
- Exit 1: the write was tried and **rolled back**. Every file is back exactly as it
  was and nothing was committed. The message says why (the folder changed since the
  dry run, a written file failed the check, git could not commit). Run the dry run
  again. Do not work around it with a script.
- To undo a finished change: `hermitcrm undo <sha>` with the sha from the output.
  It makes a new commit that reverses the batch (`git revert --no-edit <sha>`); history
  is never rewritten. See [Backups and undo](/help/backups).

## Commit message

`hermitcrm set --apply` writes it: `bulk: <summary>`, for example
`bulk: add tag priority on 23 companies (stage=prospect, country=DE)`. The commit holds
only the changed record files and `PIPELINE.md`.

Related: [CLI](/help/cli), [Backups and undo](/help/backups), [AI agents](/help/ai-agents), [Companies](/help/companies), [Messages](/help/messages)
