# Playbook

`MESSAGING.md` in your data folder: what you sell, to whom, and how you write, per offer.

The playbook is the one place Hermit CRM learns about your business. The
outreach drafts, routines and your own AI agent read it. It works for any
B2B offer (a service, software, an agency); every part is optional except the
minimum the outreach bot needs (below, under "Ready for the outreach bot").

Fill it in under **Settings > Playbook** (`/settings/playbook`): one tab per
offer, one box per part with an example beside it, a meter that shows how
much is filled, and a Save button that stays in view. Or edit `MESSAGING.md`
yourself, or ask your AI agent to.

## Offers

An offer is one thing you sell to one audience. Most people have one. If you
sell different things to different companies (coaching to founders who still
sell themselves, building the team for companies that already have
salespeople), give each its own offer. Each offer is complete on its own:
offer line, ideal customer, personas, proof, voice, channels, don'ts,
disqualifiers and lessons.

- **New offer** starts empty or as a copy of another one; **Duplicate this
  offer** copies everything, so you only change what differs.
- The outreach bot picks the offer a company fits (see "Which offer a
  company gets"), and drafts with that offer's parts only.
- An offer that is not filled in yet is simply not used; the others are.

For a separate business with its own pipeline, use a second data folder
(`hermitcrm init`) instead: one folder keeps one pipeline and one set of
message statistics.

## Two halves

- **The front matter** (the YAML between the two `---` lines at the top) is
  for Hermit CRM itself: per offer its name, offer line, ideal customer, hard
  disqualifiers and personas. The app reads it to pick and sort prospects; an
  AI is never given it as instructions.
- **The body** (everything below) is for people and AI: the general notes on
  angles, slots and languages, then one `# Offer: <name>` block per offer
  with the rest.

## The front matter

```yaml
---
offers:
  - name: Booking software
    offer_line: "We build booking software for clinics."
    icp:
      industries: [healthcare, dental]
      fte: [5, 200]            # [min, max] people at the company
      salespeople: [0, 3]      # [min, max] salespeople (ae_count)
      countries: [NL, BE, DE]  # two-letter codes
      funding: [bootstrapped, seed]
      signals: [new-location, hiring-reception]   # positive signals
    disqualifiers:
      - title_present: ["IT Director"]
      - tag_present: [customer, do-not-contact]
    personas:
      owner: {titles: ["Owner", "Practice Manager", "Managing Director"]}
      ops: {titles: ["Operations Manager", "COO"]}
---
```

| Key | What it holds |
|---|---|
| `name` | The offer's name, unique in the file; its body block is `# Offer: <name>`. |
| `offer_line` | What you sell, in one sentence. One per offer: a list is refused. |
| `icp` | The ideal customer: `industries`, `countries`, `funding`, `signals` (lists of short words), `fte` and `salespeople` (`[min, max]`). Leave any of them empty. |
| `disqualifiers` | Hard reasons a company is not a prospect for this offer (below). |
| `personas` | Per buyer type, the job `titles` that belong to it. Optional `pains`, `cares` and `ignores` lists. |

### Not a prospect

Two hard checks the app can make for certain on your own data; a company
that matches one is left out of that offer:

| Key | Value | Leaves out a company when |
|---|---|---|
| `title_present` | a list of titles | a contact there has one of these titles |
| `tag_present` | a list of tags | it has one of these tags |

Every other reason ("they already work with an agency", "public sector") goes
in the offer's `## Disqualifiers` section as text, one per line. The AI weighs
those and says why; you decide. Company size and the number of salespeople
are the ideal customer's ranges.

### Which offer a company gets

The ideal customer decides, on the fields Hermit CRM knows: headcount
(`fte_estimate`), number of salespeople (`ae_count`), country, and industries
as tags. An offer whose range or countries the company falls outside, or
whose hard checks it fails, is left out. Of the rest, the one with the most
matches wins. An empty field cannot decide: when two offers stay equal, the
bot asks you, and says what was missing ("no number of salespeople").
Funding and positive signals are for research, not for this choice.

### Personas

A contact's title picks the persona: whole words, any case, and the longest
matching title wins, so `Head of Sales Operations` is not taken for
`Head of Sales`. A title no persona lists gets no persona.

## The body

Each offer block holds these `## ` headings. A comment under each heading says
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

An offer is ready when it has an offer line, something in the ideal customer
profile, one persona with titles and one proof line. The outreach bot runs
when at least one offer is ready, and uses the ready ones only.
`hermitcrm playbook` (or `hermitcrm playbook status`) says per offer what is
filled and what is missing; Settings > Playbook shows the same.

## Draft it from my website or a document

On Settings > Playbook, give your website address, upload a PDF, Word (.docx)
or text file (a sales deck, a one-pager), or paste text, and click
**Draft it**. Hermit CRM reads the website's home page and up to four pages
of the same site that describe the business (About, Services, Pricing and the
like). Your AI CLI (the one under Settings > AI, run without any tools) then
proposes every part of the offer from that text alone. The proposal fills the
form; nothing is saved until you click Save. It never invents proof: a result
your text does not state stays empty.

## Learn my voice from my sent emails

When the CRM has emails you sent (logged by hand, by BCC capture or the
extension), **Learn my voice from my sent emails** gives your most recent ones
(the quoted thread below each left out) to your AI CLI, which describes your
voice in the Voice box. Check it, then Save.

## A playbook from before

A data folder created before the playbook had offers keeps its `MESSAGING.md`
exactly as it is; nothing changes on its own. `hermitcrm check` says "not set
up for the outreach bot" (a hint, not an error). To set it up:

```
hermitcrm playbook upgrade --dry-run   # print the result, write nothing
hermitcrm playbook upgrade             # one commit
```

It adds the front matter with one offer at the top and that offer's block at
the end, and keeps every line you had, byte for byte (your "What worked"
notes included). Running it again changes nothing. Saving Settings > Playbook
does the same and fills it in at once.

Related: [Messages](/help/messages), [Adjust messages](/help/adjust-messages), [Settings](/help/settings), [Enrich](/help/enrich), [CLI](/help/cli)
