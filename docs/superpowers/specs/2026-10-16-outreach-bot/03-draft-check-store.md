# Part 03 · Phase 1b: first-touch draft, hard checks, storage, CLI

Context: [00-overview](00-overview.md). Follows
[02-select-research](02-select-research.md); same "done when".

## Draft

The AI CLI runs with **no tools**, on the **medium** model tier by default
(Regenerate can ask for a stronger one). Input: draft type, playbook body, contact
brief, findings, culture norms, up to 3 examples (from phase 4), channel rules.
Output JSON: `subject`, `body`, `angle`, `findings_used`, `proof_used`. `angle`
uses the interaction field's values (part 02). Language: the contact's draft
language, otherwise the company's country (existing rule).

### First-touch shape

A selected contact with no earlier outbound message. One finding-based opening
(not "I..."), the offer in one line, one diagnostic question as the call to
action, e.g. "Where does it hurt most right now: pipeline, conversion or deal
size?" No meeting ask, no link.

### Channel rules

In `default_messages.toml` under a new `[outreach.<channel>]`, overridable in
`messages.toml`:

| Channel | Default rules |
|---|---|
| email | subject ≤ 60 chars, body ≤ 120 words, exactly one question, no attachments or links in a first touch; opt-out line **optional** (wording set per folder in the playbook, not counted in the word limit; compulsory only in later auto mode) |
| linkedin | connection note ≤ 300 chars (LinkedIn's limit), no pitch; the pitch goes in a separate message variant ≤ 600 chars, sent after they accept / to existing connections |

**Angles:** the five template angles plus `custom` are allowed. A/B testing
(two angles per persona in a batch) moved to phase 4 (part 06).

## Hard checks in `clean_answer`

Deterministic, no AI. A draft is refused and retried **once**, then shown with
the problem marked, when it:

- asks more or fewer than exactly one question (count of `?` outside quotes,
  per language); a LinkedIn connection note may have zero or one
- opens with "I" (or Ich, Ik, Je)
- is a reply to interest without the approach's offer line (normalised
  whitespace; a translated offer line per language can be set in the playbook)
- contains a calendar link (Calendly and similar, Google/Microsoft booking
  URLs, a configurable list) or proposes a time slot (weekday + time, dates
  with times, "this week at") in a first touch, reply to interest or follow-up
- breaks the channel's length, cites a finding or proof line not in the input,
  or leaves any `[ ]` gap (exception: a fallback draft made without usable
  findings keeps its gaps and the card says it needs hand edits)

Each of these broke in real messages from late September; that is why they are
rules, not suggestions. All draft types share them.

## Storage: `outreach/<id>.md`

One file per item, next to `drafts/`. Front matter: state, draft type,
channel, contact and company slugs, angle, research level, findings (YAML),
check results, timestamps. Body: the draft text, byte for byte. Each step is
one commit (git history, can be undone).

```
state: researching -> drafted -> ready -> sent
                          \-> skipped (reason)
                 (later, auto-log)  ready -> logged
```

- **ready → sent** happens by itself when an outbound interaction to that
  contact is logged after the item was marked ready (by hand, BCC import or the
  extension: people also send from Gmail directly), or by `outreach sent` /
  a "Mark sent" button, which changes only the state and logs nothing. Only
  `sent` and `skipped` items stop counting as open.
- **Ready despite a failed check** is allowed: the card shows a warning and the
  failed check is stored for the quality report.
- **Skip reasons** are a fixed list (`bad-fit`, `wrong-person`, `bad-timing`,
  `bad-draft`, `already-in-contact`, `other`) plus optional free text. A
  skipped contact returns to future batches after the cooldown, except
  `bad-fit`, which excludes them until the item is changed.

Every item also records, for the quality report (part 06): ready or skipped
(and why), edit distance between AI draft and the text marked ready, research
level, model, time taken.

## Sender and Logger

`ManualSender` returns "not sent" and never touches the network.
`ManualLogger` does nothing.

## CLI

`hermitcrm outreach preview|build|list|show|ready|sent|skip`, same flags as the page.
The MCP server gets `outreach_list` and `outreach_show` later.

## Tests

- `clean_answer`: refuses zero or two questions, an opening "I"/"Ich"/"Ik"/"Je",
  a reply to interest without the offer line, a calendar link, a proposed time
  slot, over-length text, unknown findings or proof, leftover gaps; one retry,
  then the draft is shown with the problem marked
- `outreach/` files: deterministic writes, body byte for byte, one commit per
  step
- `ManualSender` never touches the network
