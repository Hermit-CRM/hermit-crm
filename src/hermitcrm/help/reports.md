# Reports

`/reports`: numbers for a period, each with the change against the previous period of the same length.

## Period

`7d`, `30d` (default), `90d`, `quarter`, `ytd` or `custom` with from and to
dates. The CLI prints the same report: `hermitcrm report --days 30`, or
`--from D --to D`, `--md` for Markdown tables.

## Sections

- **Activity**: interactions per ISO week, by channel and direction; companies
  touched; new companies and contacts.
- **Funnel**: entries per stage from `stage_history`, conversion between
  prospect, reached-out, discovery, offer and won, median days in stage, and
  the current pipeline with its monthly value.
- **Outcomes**: won, lost and disqualified in the period (by the closing date
  from the stage history, else `stage_changed`), win rate, top 10 lost reasons.
- **Messages**: sent, and the results by language, by channel and for the five
  most reused texts.
- **Sources**: companies created and won per source.
- **Hygiene**: overdue next steps, silent accounts, contacts without email.

Tables with CSS bars, no charts library. Companies without a `stage_history`
(created before it existed) can get one from git with
`hermitcrm backfill-history --apply`.

Related: [Pipeline](/help/pipeline), [Messages](/help/messages), [CLI](/help/cli)
