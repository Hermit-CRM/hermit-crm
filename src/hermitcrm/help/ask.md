# Ask the Hermit

The **Ask the Hermit** button, top right on every page, sends a question to the AI CLI configured under [Settings](/help/settings) (the same one Enrich uses).

## How it answers

1. **One quick call over a CRM index.** Hermit builds a compact table of your
   CRM itself: one row per contact with a ready-made link, the company stage and
   its role (open, won, lost, closed, parked), the last touch, the last thing
   logged (notes included), the company-level touch, the next open task (marked
   `overdue` when it is) and the days since the last touch. The model gets that
   table plus the text of the page you were on (with its links) and answers
   without tools, usually in 5 to 10 seconds. Questions such as "who did I
   write to recently and have no follow-up planned?" are answered here.
2. **The data folder if the index is not enough.** For what only the text
   holds (what a note or an email says), the model says so and a second run
   starts inside the data folder with read-only tools: reading files and
   `hermitcrm show`, `digest`, `report` and `check`. The folder's `CLAUDE.md`
   tells it to read `PIPELINE.md` first and never all interactions. Nothing is
   ever written.

Links in an answer are checked before you see them: a link to a person or
company opens their page, a link that names a file or a slug is repaired, and
a link that points nowhere is shown as plain text.

The answer page says which of the two answered, which model ran, how many
seconds it took and, for the data-folder step, the sources it used.

## Buttons on the answer

- **Retry with Fable** (or the strong model of your provider): the same
  question on the strong tier. Shown when the answer came from the medium tier.
- **Search every file instead**: skip the index and read the data folder, for
  when the quick answer missed something.
- **Skip the page, search the whole CRM**: for a new question, leave the page
  out and answer from the CRM index alone.

## Saved questions

For the questions you ask again and again. Type one and press **Save** next to
**Ask** (in the panel or on the Ask page), or press **Save this question** under an
answer; the answer stays where it is.

- **While you type**, the saved questions that contain every word you typed are
  listed under the box. Up and Down choose, Enter or Tab fills the box, Esc closes
  the list. In an empty box, Down lists them all.
- **The newest four** are buttons in the panel; one click puts the question in the
  box. **All saved** opens the full list on the Ask page, where you can **Use**,
  **Edit** or **Delete** each one.
- **Whole CRM.** A question saved with *Skip the page, search the whole CRM* ticked
  keeps that: choosing it ticks the box again, and the panel says so ("Skips this
  page...") with a link to go back to the page.
- **[Placeholders].** A part in square brackets, such as `What did I promise
  [company] in my last email?`, is selected when you choose the question, so typing
  replaces it.

They are kept in `ask-questions.toml` in your data folder, newest first, one commit
per change (`ask: saved question "..."`), so they are in your backups and on every
machine you sync. You can edit the file by hand. If it has a mistake Hermit does not
touch it: the Ask page shows what is wrong and a save is refused until it is fixed.
Saving the same question again (case and spacing ignored) changes nothing. At most
100 are kept.

## Models

Two tiers per provider. Medium is the default; switch it under Settings → AI.

| provider | medium | strong |
|---|---|---|
| claude | `claude-opus-5` (Opus) | `claude-fable-5-1` (Fable) |
| codex | `gpt-5-mini` | `gpt-5` |
| gemini | `gemini-2.5-flash` | `gemini-2.5-pro` |
| grok | `grok-4-fast` | `grok-4` |

Override either with `enrich_model` / `enrich_model_strong` in `config.toml`
(or the Settings fields) when your CLI names a model differently. Only the
claude IDs are verified. Fable needs Claude Code 2.1.251 or newer.

Ask the Hermit has its own default: for claude it answers on Sonnet
(`claude-sonnet-5-5`), which is plenty for reading a page or the CRM and cheaper
than Opus. The other providers' medium models are already their mid-size ones, so
Ask uses those. If you set `enrich_model` yourself, Ask follows it; "Retry" still
uses the strong model.

A third, **light** tier is used only by the outreach bot's scrape research and
critic, which read and score rather than write. For claude it is
`claude-haiku-5-5` (Haiku). If you set `enrich_model` yourself, light follows it, so
Hermit never swaps a model you named; set `enrich_model_light` in `config.toml` to
choose one. For the other providers it is the medium model.

## Notes

- The page waits for the answer (no JavaScript): usually 5 to 10 seconds for
  an index answer, up to `ask_timeout` (default 300 seconds) for the data folder.
- Only local pages are sent, and only as text; the CSRF token and hidden
  fields are left out.

Related: [Enrich](/help/enrich), [Settings](/help/settings), [AI agents](/help/ai-agents)
