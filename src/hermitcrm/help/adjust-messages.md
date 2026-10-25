# Make it yours: messages

A recipe for your AI agent: rewrite the outreach drafts in the user's own voice, add a language, and keep the playbook.

Read `hermitcrm help adjust` first; its rules apply here too. Messages are
always drafts: nothing in Hermit sends them, and neither do you.

## What the user can ask for

- The wording of the outreach drafts (the Outreach page), in their own words
  ("shorter", "less salesy", "sign off with Best, Alex").
- Another language for the drafts.
- A template the built-in wording does not cover (a connection note, a follow-up, a
  reply to a no): that goes in the playbook, `MESSAGING.md`, where they and you
  find it when drafting.

## Files you may write

- `messages.toml`: the draft wording. It is merged key by key over the defaults
  that ship with Hermit, so write only the keys that change.
- `MESSAGING.md`: the playbook, the user's own notes. Add to it and edit the
  part you were asked about; never wipe what the user wrote.

Read both before you write anything. The shipped wording is
`default_messages.toml` inside the installed Hermit CRM package: read it there
when you need a key's current text, never change it.

## How the drafts are built

The Messages page lists the messages you sent and drafted, with their outcomes;
it has no drafts box of its own. Outreach drafts are written on the Outreach page
from the playbook (`MESSAGING.md`), and their wording is in `messages.toml`, per
language under `[languages.<code>]` (for example `greeting` and `signoff`), with
the reply and follow-up templates under `[outreach.reply_to_interest.<lang>]` and
`[outreach.follow_up.<lang>]`. Check the key names in `default_messages.toml`
before you change one.

Slots in `{braces}`: `{first}` `{company}` `{growth}` `{size}` `{hurdle}`
`{team}` `{observation}` `{fte}` `{ae}` `{site}` `{owner_first_name}`, plus one
per field of the user's own, by its key (`{segment}`). Text in `[square
brackets]` is for the user to fill in before sending. A literal brace is `{{`
or `}}`.

## Worked example

"Make the drafts shorter and sign them Best, Alex." Write `messages.toml`:

```toml
[languages.en]
signoff = "Best,\n{owner_first_name}"
```

Then:

```bash
hermitcrm check
git add messages.toml && git commit -m "ai: adjust: shorter English drafts"
```

"Write a LinkedIn connection note template for operations leads, in English
and German." That is not part of the built-in wording, so add it to `MESSAGING.md`
under its own heading, one block per language, with `[square brackets]` for what
the user fills in, and commit `ai: adjust: connection note in the playbook`.

## A new language

Add a full `[languages.<code>]` table (every key above, with `name = "Swedish"`)
plus its `growth`, `size` and `team` tables. Drafts use it for a contact whose
language is set to that code on their page, or when it is picked above the
drafts; countries map to English, German, Dutch and French only.

## Check

`hermitcrm check` reads `messages.toml` and writes a draft in every language
with it, so a typo shows before a page breaks:

```text
messages.toml: languages.en: {segmnt} is not a slot or a missing key (did you mean segment?)
messages.toml: line 7: Expected '=' after a key in a key/value pair
```

## Safety

- Drafts only. Never send anything, never log a message as sent for the user.
- Keep the user's voice: read `MESSAGING.md` (what worked) before rewriting.
- Commit: `ai: adjust: <what>`. Undo: `hermitcrm undo <commit>`; deleting
  `messages.toml` brings the shipped wording back.

Related: [Make it yours](/help/adjust), [Messages](/help/messages), [Contacts](/help/contacts)
