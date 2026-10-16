# Playbook

`MESSAGING.md` in your data folder: what you sell, to whom, and how you write.

The playbook is the one place Hermit CRM learns about your business. The
outreach drafts, routines and your own AI agent read it. It works for any
B2B offer (a service, software, an agency); every part is optional except the
minimum the outreach bot needs (below, under "Ready for the outreach bot").

Fill it in under **Settings > Playbook** (`/settings/playbook`): one box per
part, an example beside each, and a meter that shows how much is filled. Or
edit `MESSAGING.md` yourself, or ask your AI agent to.

## Two halves

- **The front matter** (the YAML between the two `---` lines at the top) is
  for Hermit CRM itself: the offer line, your ideal customer, the
  disqualifiers and the personas. The app reads it to pick and sort
  prospects; an AI is never given it as instructions.
- **The body** (everything below) is for people and AI: your offer in more
  words, proof, voice, channels and don'ts, next to the notes on angles, slots
  and languages that were already there, and your own "What worked".

## The front matter

```yaml
---
offer_line: "We build booking software for clinics."
icp:
  industries: [healthcare, dental]
  fte: [5, 200]            # [min, max] people at the company
  salespeople: [0, 3]      # [min, max] salespeople (ae_count)
  countries: [NL, BE, DE]  # two-letter codes
  funding: [bootstrapped, seed]
  signals: [new-location, hiring-reception]
disqualifiers:
  - fte_over: 500
  - title_present: ["IT Director"]
  - no_salespeople: true
personas:
  owner: {titles: ["Owner", "Practice Manager", "Managing Director"]}
  ops: {titles: ["Operations Manager", "COO"]}
---
```

| Key | What it holds |
|---|---|
| `offer_line` | What you sell, in one sentence. Exactly one: a list is refused. |
| `icp` | Your ideal customer: `industries`, `countries`, `funding`, `signals` (lists of short words), `fte` and `salespeople` (`[min, max]`). Leave any of them empty. |
| `disqualifiers` | Hard reasons a company is not a prospect. Such a company is left out, not just flagged. |
| `personas` | Per buyer type, the job `titles` that belong to it. Optional `pains`, `cares` and `ignores` lists. |

### One offer per data folder

One folder holds one offer, one pipeline and one set of message statistics.
Mixing two offers in one folder makes the statistics say nothing about either.
For a second business, create a second folder with `hermitcrm init`.

### Disqualifiers

A small, fixed list, so `hermitcrm check` can tell a typo from a rule:

| Key | Value | Leaves out a company when |
|---|---|---|
| `fte_over` | a whole number | its headcount (`fte_estimate`) is above it |
| `fte_under` | a whole number | its headcount is below it |
| `title_present` | a list of titles | a contact there has one of these titles |
| `no_salespeople` | `true` | its number of salespeople (`ae_count`) is 0 |
| `tag_present` | a list of tags | it has one of these tags |

An empty field cannot decide: a company without a headcount stays in, and the
outreach card says "not checked: no headcount".

### Personas

A contact's title picks the persona: whole words, any case, and the longest
matching title wins, so `Head of Sales Operations` is not taken for
`Head of Sales`. A title no persona lists gets no persona.

## The body

Each part is a `## ` heading. A comment under each heading says what goes
there; the text you write below it is what counts.

| Heading | What goes there |
|---|---|
| `## Offer` | The outcome a customer gets, how an engagement works, what you do not do. |
| `## Personas` | Per persona: the top 2-3 problems, what they care about and ignore. |
| `## Proof` | Customer results, one per line starting with `- `. Drafts may cite only these. |
| `## Why you` | Why you rather than doing it themselves, hiring, another provider or nothing. |
| `## Voice` | Tone, words you use and avoid, sign-off, formal or informal address. |
| `## Channels` | Per channel: what a first message is for, its length, what it asks. |
| `## Don'ts` | What a message must never do. |

Write them in any language; a draft is still written in the contact's language.

## Ready for the outreach bot

The outreach bot will not run until the playbook has an offer line, something
in the ideal customer profile, one persona with titles and one proof line.
`hermitcrm playbook` (or `hermitcrm playbook status`) says what is filled and
what is missing; Settings > Playbook shows the same.

## Draft it from my website

On Settings > Playbook, paste your website text, a profile summary or the
text of a sales deck and click **Draft it**. Your AI CLI (the one under
Settings > AI, run without any tools) proposes every part from that text
alone. The proposal fills the form; nothing is saved until you click Save.
It never invents proof: a result your text does not state stays empty.

## A playbook from before

A data folder created before the playbook had a front matter keeps its
`MESSAGING.md` exactly as it is; nothing changes on its own. `hermitcrm check`
says "not set up for the outreach bot" (a hint, not an error). To set it up:

```
hermitcrm playbook upgrade --dry-run   # print the result, write nothing
hermitcrm playbook upgrade             # one commit
```

It adds the front matter at the top and the missing headings at the end, and
keeps every line you had, byte for byte. Running it again changes nothing.
Saving Settings > Playbook does the same and fills it in at once.

Related: [Messages](/help/messages), [Adjust messages](/help/adjust-messages), [Settings](/help/settings), [Enrich](/help/enrich), [CLI](/help/cli)
