# Quick capture

Type what happened in a sentence; Hermit shows what it would file (the interaction, the tasks, a stage move) and saves it when you confirm.

Related: [Interactions](/help/interactions), [Tasks](/help/tasks), [Search and the keyboard](/help/search), [Ask the Hermit](/help/ask)

## How to use it

1. Open **Quick capture** (`/quick-capture`), or type the sentence in the
   search box (⌘ K or `/`) and pick **Capture: ...**. That opens the box with
   your text in it; nothing runs until you press **Read it**.
2. Write what happened, for example: *Called Jane at Acme: she wants a
   proposal by Friday and a demo next week.*
3. Hermit reads it in the background (the badge at the top shows it working;
   you can leave the page). One quick call goes to the AI tool set up under
   [Settings](/help/settings), on its light model and without any tools. It
   gets your text and the list of your companies and contacts, nothing else.
4. The **preview** shows what it found: the company and person, the channel,
   direction, date, subject and outcome of the interaction, each task with its
   due date, and a stage move if the text says the deal moved. Every part has a
   tick box and every value can be changed.
5. **File it** saves everything ticked as **one change** (one commit), which
   [Undo](/help/backups) takes back in one click.

Nothing is written before you press **File it**. Filing the same preview twice
saves it once.

## What it keeps exactly

The interaction's text is **what you typed**, byte for byte (only line endings
are made the same as every other form makes them). The AI's reading fills the
fields around it (subject, channel, date); it never rewrites your words.

## Names

- A company or person already in your CRM is picked for you. Wrong one? Pick
  another from the list under it (*not this one*). If you pick another company,
  the list of people follows it when you file: Hermit asks again if the person
  is not at that company.
- A name that is not in your CRM is offered as **create a new company** or
  **create a new contact**. It is created only if you leave that picked and
  file; never on its own.

## Dates

The AI copies dates as you wrote them ("Friday", "next week", "3 October"), and
Hermit works out the actual date itself, from today, so the same sentence gives
the same dates. The preview shows both: the date it worked out, and what you
wrote.

- For a task: "Friday" is the next Friday (never today), "this Friday" is the
  Friday of this week, "next Friday" the Friday of next week, "next week" its
  Monday, "end of the week" this Friday, "in 3 days", "next month" (the 1st),
  "3 October" (next year once that date has passed).
- For when it happened: "yesterday", "on Monday" (the last Monday), "2 days
  ago", "last week". No date in the text means now.

A date Hermit cannot read is left empty, and the preview says so.

## No AI tool

Quick capture needs an AI tool (Claude Code, Codex, Gemini or another, under
[Settings](/help/settings)). Without one, the page says so and points at the
normal forms: log an interaction or add a task from the company's page.
