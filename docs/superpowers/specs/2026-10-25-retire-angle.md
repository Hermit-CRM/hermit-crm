# Retire "Angle" (2026-10-25)

## Decision

The Angle label (`scale|unblock|hook|bridge|decline|custom`) is retired
completely, with no replacement. It was introduced on 2026-10-16 as the key of
the five no-AI template drafts; that drafts box went on 2026-10-20, so the name
outlived its feature. Left over, it was only an AI self-label on first touches,
copied onto the sent interaction. People rewrite most drafts, so the label does
not describe the sent text; it was never typed by hand; per-angle learning
needs about 200 sends per angle; and the angle bandit (off by default, acting
from 30 sends) ignored findings and could force an unfit angle. `framework` and
the findings used (with their kind) describe a message better.

## What was removed

- Data: the `angle` key on interactions and outreach items; `Angle`, `ANGLES`,
  `normalise_angle`; the `outreach_angles` default.
- AI contract: `angle` in the drafter's JSON schema, its check, the `Angle:`
  prompt lines and the "angle policy" flag. A model reply that still carries
  `angle` is ignored.
- Learning: the angle bandit in `exemplars.py` (table, Thompson sampling,
  `learning_angle_sampling`), `angle` as a learning dimension and on cards,
  `hermitcrm learn angles`. Exemplar relevance is now persona 0.4 + findings 0.6.
- UI and tools: the Messages column, the Log-interaction select, the Learning
  page's Angles block, the settings sampling select, the CSV export column, bulk
  and filter choices.
- Docs, help pages, README and website sources. Old changelog entries stay.

## Migration

Format 17 (`outreach/*.md`) and 18 (`companies/*/interactions/*.md`) share one
function that drops the `angle` key from front matter and changes nothing else.
Idempotent; a file without `angle` is returned as it is; bodies stay byte for
byte. `LATEST` is 18. Migration 9 stays, with its trim inlined.

## Deliberately kept

- A user's `messages.toml` (keys `scale`, `unblock`, `hook`, `bridge`,
  `decline`), `MESSAGING.md` prose and `config.toml` keys `outreach_angles` and
  `learning_angle_sampling` still load, with no errors or warnings.
- A saved dashboard, layout or bulk command naming `angle` fails like any other
  unknown column.
- Specs and plans under `docs/superpowers/` and past changelog entries.
- Old outreach flags such as `angle policy: ...` in existing items are plain text.
