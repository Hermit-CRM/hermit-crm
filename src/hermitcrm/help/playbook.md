# Playbook

`MESSAGING.md` in your data folder: what you sell, to whom, and how you write, per approach.

The playbook is the one place Hermit CRM learns about your business. The
outreach drafts, routines and your own AI agent read it. It works for any
B2B business (a service, software, an agency); every part is optional except the
minimum the outreach bot needs (below, under "Ready for the outreach bot").

Fill it in under **Settings > Playbook** (`/settings/playbook`): one tab per
approach, one box per part with an example beside it, a meter that shows how
much is filled, and a Save button that stays in view. Or edit `MESSAGING.md`
yourself, or ask your AI agent to.

## Approaches

An approach is one offer to one audience. Most people have one. If you
sell different things to different companies (coaching to founders who still
sell themselves, building the team for companies that already have
salespeople), give each its own approach. Each approach is complete on its own:
offer line, ideal customer, personas, proof, voice, channels, don'ts,
disqualifiers and lessons.

- **New approach** starts empty or as a copy of another one; **Duplicate this
  approach** copies everything, so you only change what differs.
- The outreach bot picks the approach a company fits (see "Which approach a
  company gets"), and drafts with that approach's parts only.
- An approach that is not filled in yet is simply not used; the others are.

For a separate business with its own pipeline, use a second data folder
(`hermitcrm init`) instead: one folder keeps one pipeline and one set of
message statistics.

## Two halves

- **The front matter** (the YAML between the two `---` lines at the top) is
  for Hermit CRM itself: per approach its name, offer line, ideal customer, hard
  disqualifiers and personas. The app reads it to pick and sort prospects; an
  AI is never given it as instructions.
- **The body** (everything below) is for people and AI: the general notes on
  angles, slots and languages, then one `# Approach: <name>` block per approach
  with the rest.

## The front matter

```yaml
---
approaches:
  - name: Booking software
    offer_line: "We build booking software for clinics."
    icp:
      industries: [healthcare, dental]
      countries: [NL, BE, DE]  # two-letter codes
      ranges:                  # your own company fields: [min, max]
        employees: [5, 200]
      funding: [bootstrapped, seed]
      signals: [new-location, hiring-reception]   # positive signals
    disqualifiers:
      - tag_present: [customer, do-not-contact]
    personas:
      owner: {titles: ["Owner", "Practice Manager", "Managing Director"]}
      ops: {titles: ["Operations Manager", "COO"]}
---
```

| Key | What it holds |
|---|---|
| `name` | The approach's name, unique in the file; its body block is `# Approach: <name>`. |
| `offer_line` | What you sell, in one sentence. One per approach: a list is refused. |
| `icp` | The ideal customer: `industries`, `countries`, `funding`, `signals` (lists of short words) and `ranges` (below). Leave any of them empty. |
| `disqualifiers` | Hard reasons a company is not a prospect for this approach (below). |
| `personas` | Per buyer type, the job `titles` that belong to it. Optional `pains`, `cares` and `ignores` lists. |

### Ranges on your own fields

Hermit CRM has no built-in headcount or team size: what a company "is" lives
in the fields you defined yourself ([Adjust fields](/help/adjust-fields),
`fields.toml`). `ranges` maps one of those company fields to `[min, max]`,
as many as you like: a headcount, a revenue band, the number of salespeople,
the number of locations. A number field is read as it is; a text field by
the first number in it, so `~13` counts as 13. `hermitcrm check` warns when a
range names a field the folder does not have.

### Not a prospect

Write every reason a company is not a prospect for this approach in its
`## Disqualifiers` section, one per line ("they already have a Head of Sales",
"they work with an agency", "public sector"). The AI weighs those against what
it finds and says why; you decide.

One check the app makes itself, without AI: `tag_present` leaves out every
company with one of these tags (`customer`, `do-not-contact`).

### Which approach a company gets

The ideal customer decides, on what Hermit CRM knows: your ranges, the
country, and industries as tags. An approach whose range or countries the
company falls outside, or whose tags rule it out, is left out. Of the rest,
the one with the most matches wins. An empty field cannot decide: when two
approaches stay equal, the bot asks you, and says what was missing ("no
employees"). Funding and positive signals are for research, not for this
choice.

### Personas

A contact's title picks the persona: whole words, any case, and the longest
matching title wins, so `Head of Sales Operations` is not taken for
`Head of Sales`. A title no persona lists gets no persona.

## The body

Each approach block holds these `## ` headings. A comment under each heading says
what goes there; the text you write below it is what counts.

| Heading | What goes there |
|---|---|
| `## Offer` | The outcome a customer gets, how an engagement works, what you do not do. |
| `## Personas` | Per persona: the top 2-3 problems, what they care about and ignore. |
| `## Proof` | Customer results, one per line starting with `- `. Drafts may cite only these. |
| `## Why you` | Why you rather than doing it themselves, hiring, another provider or nothing. |
| `## Voice` | Tone, words you use and avoid, sign-off, formal or informal address. |
| `## Channels` | Per channel: what a first message is for, its length, what it asks. |
| `## Don'ts` | What a message must never do. |
| `## Disqualifiers` | Other reasons a company is not a prospect, for the AI to weigh. |
| `## Lessons` | `### Worked`, `### Didn't work` and `### Still testing`: what you tried. Drafts follow what worked and avoid what did not. |

Write them in any language; a draft is still written in the contact's language.

## Ready for the outreach bot

An approach is ready when it has an offer line, something in the ideal customer
profile, one persona with titles and one proof line. The outreach bot runs
when at least one approach is ready, and uses the ready ones only.
`hermitcrm playbook` (or `hermitcrm playbook status`) says per approach what is
filled and what is missing; Settings > Playbook shows the same.

## Draft it from my website or a document

On Settings > Playbook, give your website address, upload a PDF, Word (.docx)
or text file (a sales deck, a one-pager), or paste text, and click
**Draft it**. Hermit CRM reads the website's home page and up to four pages
of the same site that describe the business (About, Services, Pricing and the
like). Your AI CLI (the one under Settings > AI, run without any tools) then
proposes every part of the approach from that text alone. The proposal fills the
form; nothing is saved until you click Save. It never invents proof: a result
your text does not state stays empty.

## Learn my voice from my sent emails

When the CRM has emails you sent (logged by hand, by BCC capture or the
extension), **Learn my voice from my sent emails** gives your most recent ones
(the quoted thread below each left out) to your AI CLI, which describes your
voice in the Voice box. Check it, then Save.

## A playbook from before

A data folder created before the playbook had approaches keeps its `MESSAGING.md`
exactly as it is; nothing changes on its own. `hermitcrm check` says "not set
up for the outreach bot" (a hint, not an error). To set it up:

```
hermitcrm playbook upgrade --dry-run   # print the result, write nothing
hermitcrm playbook upgrade             # one commit
```

It adds the front matter with one approach at the top and that approach's block at
the end, and keeps every line you had, byte for byte (your "What worked"
notes included). Running it again changes nothing. Saving Settings > Playbook
does the same and fills it in at once.

Related: [Messages](/help/messages), [Adjust messages](/help/adjust-messages), [Settings](/help/settings), [Enrich](/help/enrich), [CLI](/help/cli)
