# Ask Hermit

The **Ask Hermit** button, top right on every page, sends a question to the AI CLI configured under [Settings](/help/settings) (the same one Enrich uses).

## How it answers

1. **This page first.** The page you were on is rendered to plain text
   (content, table cells, filled-in fields and the chosen value of each
   dropdown; no navigation) and the model answers from that text alone,
   without tools. This is fast and cheap.
2. **The whole CRM if the page is not enough.** The model says so, and a
   second run starts inside the data folder with read-only tools: reading
   files and `hermitcrm show`, `digest`, `report` and `check`. The folder's
   `CLAUDE.md` tells it to read `PIPELINE.md` first and never all interactions.
   Nothing is ever written.

The answer page says which of the two answered, which model ran and, for the
whole-CRM step, the sources it used.

## Buttons on the answer

- **Retry with Fable** (or the strong model of your provider): the same
  question on the strong tier. Shown when the answer came from the medium tier.
- **Search the whole CRM instead**: skip the page step, for when the page
  answer was too narrow.
- **Skip the page, search the whole CRM**: the same, for a new question.

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

## Notes

- The page waits for the answer (no JavaScript): usually 10 to 30 seconds for
  a page answer, up to `ask_timeout` (default 300 seconds) for the whole CRM.
- Only local pages are sent, and only as text; the CSRF token and hidden
  fields are left out.

Related: [Enrich](/help/enrich), [Settings](/help/settings), [AI agents](/help/ai-agents)
