# Outreach bot: semi-automatic research and drafts

Status: proposal, not built. Written 16 Oct 2026.

## Goal

Make outreach quicker without making it worse. For each contact in a batch, the
bot puts on one card everything needed to write a good first message:

- the contact, with their LinkedIn link
- the company, with a link to its website
- research findings, each with the source it came from
- a proposed message for one channel (email or LinkedIn)

The person reviews the card, edits it if needed and marks it **ready**. In this
first version the bot never sends anything and never logs anything. The person
sends the message themselves and logs it the usual way: by hand, BCC import or
the extension.

Full auto (send and log by itself) will be a **setting that is off by default**.
It is not built now, but the design leaves a place for it.

## Decisions taken (16 Oct 2026)

| Question | Decision |
|---|---|
| How contacts enter the queue | Both: a batch built from a list filter, and a per-contact "Research & draft" button |
| Where research comes from | Chosen per run: free scrape or AI with web search (Clay later) |
| Channel | Fixed for the whole batch by the filter (email or LinkedIn); every draft in the batch uses that channel |
| What "approve" does | It only marks the draft ready. Sending and logging stay manual. Logging the message automatically is a later option |
| Clay | Not now. Research levels are `scrape` and `ai-web`; the `Researcher` interface leaves room to add Clay later |
| WhatsApp | Not a bot channel. The bot drafts for email and LinkedIn only |
| Findings | "Mark ready" appends the findings used to the contact's notes |
| Cost cap | None |
| What the bot knows about the seller | A playbook in the data folder, set up in a guided step; the bot refuses to run without its minimum (see "The playbook") |

## What already exists and gets reused

| Piece | Reused for |
|---|---|
| `scrape.py` | The free research level (website meta, JSON-LD, LinkedIn company page) |
| `enrich.py` `Enricher` | Running the AI command-line tool, model tiers, JSON schema answers, refusing tools when needed |
| `messaging.py` + `messages.toml` | Angles, tone and language rules the AI draft must follow |
| `routines.py` | How a draft is stored, the "a draft is a file, nothing is sent" rule, the prompt-safety rules |
| `filters.py` | The `--where` / column-filter syntax that picks the batch |
| Contact `linkedin`, `email`, `phone`; company `website`, `country` | The links on the card and the channel check. **No new front-matter keys on contacts or companies, so no migration is needed** |

## The playbook: what the bot knows about you

A message works when it connects **this person's** likely problem to **your**
offer, with proof, in a tone that fits their culture and the channel. Today
Hermit knows none of the seller's side. Setup asks only for your name, and the
templates in `default_messages.toml` contain gaps like `[your offer]` and
`[the problem you solve]`. Without that context, any AI draft is generic.

### The file

`playbook.md` in the data folder. A short TOML/YAML front matter holds what
Python needs; the Markdown body holds what the AI reads. Each section below is
one heading in the body.

| Section | What goes in it | Used by |
|---|---|---|
| **Offer** | What you sell, in one sentence; the outcome for the customer; price range or engagement model; what you do *not* do | Drafter |
| **ICP** (front matter) | Industries, company size (FTE range), countries, stages, signals that make a good moment (hiring, growth, funding) | Select (fit score, warns on poor fit) and Drafter |
| **Personas** (front matter + body) | Per buyer type: titles that map to it (`"Head of Sales", "VP Sales", "CRO"`), their top 2-3 pains, what they care about, what they ignore | Drafter picks the persona from the contact's title and `role` |
| **Proof** | Customer outcomes (fictional names in the demo), numbers, short case lines the AI may cite. The AI may cite **only** what is written here | Drafter, Critic |
| **Why you** | Differentiators against the usual alternative (hire, agency, do nothing) | Drafter |
| **Voice** | Tone (direct, warm, formal), words you use, words you never use, sign-off | Drafter, Critic |
| **Channels** | Per channel: purpose of the first touch, length, call to action (e.g. LinkedIn: connect, no pitch; email: one question, ask for 15 minutes) | Drafter, Critic |
| **Don'ts** | Hard rules: no fake familiarity, no "I hope this finds you well", no claims without proof, never mention competitors by name | Critic |

The default `messaging.py` angles stay in place. When the playbook is filled,
its offer and proof fill the template gaps, so even the non-AI drafts improve.

### Getting it filled: guided, not a blank page

- **Settings → Playbook**: a form with one box per section, examples beside
  each box, and a completeness meter.
- **"Draft it from my website"**: the user gives their own website, LinkedIn
  About text or a sales deck as pasted text. The AI CLI (no tools) proposes
  each section and the person edits and saves. Same pattern as Enrich: a
  proposal is never saved without confirmation.
- **Setup** (`hermitcrm init` and the welcome flow) gets an optional fourth
  step, "Your offer", which asks three questions: what you sell, to whom,
  and one customer result. That is the minimum; the rest can follow.
- **Readiness gate**: the Outreach page and `hermitcrm outreach build` refuse to
  run until Offer, ICP, one Persona and one Proof line are filled. The page
  explains what is missing and links to the form.
- `hermitcrm help playbook` documents the file for AI agents, and
  `hermitcrm check` validates the front matter.

### Understanding the contact

The drafter gets one compact brief per contact, built by Python, not by the AI
browsing freely:

| Input | Source |
|---|---|
| Persona | Title matched against playbook personas; `role` (champion, decision-maker...) |
| Seniority and tenure | Title; LinkedIn profile text if captured |
| What they said or posted | The **bookmarklet** (already in Hermit): on a LinkedIn profile you are logged in to, a new "Add to research" button sends the visible profile text, About and recent activity to the open outreach card. This is the reliable way to get person-level detail, because LinkedIn blocks anonymous fetches |
| Company situation | Findings from research, signals (`growing`, `hiring`...), `fte_estimate`, `product_oneliner`, stage |
| Relationship so far | The last interactions with the person and company (summaries, not whole threads), so a second touch is not written as a first |
| Culture and language | See below |
| ICP fit | Matched against the playbook front matter. A poor fit is shown on the card, not hidden |

### Culture

`default_messages.toml` gets a `[culture.<country>]` table with defaults the
person can override in `messages.toml`:

- language (exists today)
- formality: e.g. German first contact `Sie` vs `du`, Dutch directness,
  French politeness formulas. **Note:** today's German templates use `du`.
  The default should follow the playbook's Voice setting, with `du` for
  start-up audiences and `Sie` otherwise
- greeting and sign-off norms, use of first name vs title
- how direct the call to action can be

These are starting points; the card shows which norms were applied, so the
person can correct them.

### Making messages work

1. **A critic pass before you see the card.** A second AI call (no tools)
   scores the draft against a rubric: relevant to the persona's pain;
   personalisation based on a verified finding; one clear call to action;
   within the channel's length; uses only playbook proof; tone and culture
   right; none of the Don'ts. Below the threshold, the draft is regenerated
   once; the card shows the scores and the critic's one-line reason.
2. **Learning from your own results.** Each sent message gets an outcome
   (reply, meeting, no reply) through the existing message status. Reports
   show reply rate by angle × persona × channel × language. A message that got
   a reply can be saved as an example ("Use as example"); the drafter gets the
   2-3 closest examples (same persona, channel and language) as a pattern.
   Only your own sent messages become examples.
3. **Edits teach too.** When the text marked ready differs a lot from the
   draft, the card asks "What was wrong?" (wrong tone, wrong pain, too long, bad
   finding). The answers appear in the quality report and point to the
   playbook section to fix.
4. **One variable at a time.** An optional A/B setting drafts two angles for
   the same persona in a batch, so the report can compare them fairly.

### Also worth taking into account

- **Follow-ups.** Most replies come after the second or third touch. Later, the
  follow-up radar (`followups.py`) can queue a follow-up draft when a message
  marked ready and logged has had no reply after N days. The follow-up builds
  on the first message and adds something new.
- **Timing.** Triggers age fast. A finding older than about 90 days is marked
  stale and is not used as the opening line.
- **Email deliverability** (for later auto-send): plain text, no links or
  tracking pixels in the first mail, low daily volume, SPF/DKIM/DMARC on the
  sending domain.
- **LinkedIn.** A connection note has 300 characters and should not pitch. The
  pitch goes in the message after they accept, as a separate draft.
- **Consent and privacy.** Findings stored in notes are personal data. Keep
  only what is relevant to the business conversation; the opt-out line for
  cold email stays part of the email channel rules.
- **Honesty.** No invented familiarity ("loved your post" when no post was
  read), no fake urgency. The critic checks this.

## Pipeline

```
select ──> research ──> draft ──> review ──> [send] ──> [log]
 filter     Researcher   Drafter    person     Sender     Logger
 or button  (3 kinds)    (AI CLI)   marks      (manual    (manual
                                    ready       now)       now)
```

Every step is a small interface with one class behind it now. Full auto later
adds classes behind `Sender` and `Logger`. Nothing above them changes.

```python
class Researcher(Protocol):          # scrape | ai-web (Clay later)
    def research(self, company, contact) -> Research: ...

class Drafter(Protocol):             # AI CLI, no tools
    def draft(self, company, contact, research, channel) -> Draft: ...

class Sender(Protocol):              # ManualSender now: returns "not sent"
    def send(self, item) -> SendResult: ...

class Logger(Protocol):              # ManualLogger now: does nothing
    def log(self, item, result) -> None: ...
```

### 1. Select

- **Batch:** a list filter (the same syntax as the Contacts page and
  `hermitcrm set --where`), one channel, and a batch size (default 10).
- **Button:** "Research & draft" on the contact page, with a channel picker.
- The channel filter also removes contacts the channel cannot reach: email
  needs `email`, LinkedIn needs `linkedin`. The preview says how many were
  dropped and why. WhatsApp is not a bot channel.
- Always left out: contacts that already have an open outreach item, contacts
  messaged in the last `outreach_cooldown_days` (default 30), companies in a
  closed or parked stage, and anything tagged `do-not-contact`.
- There is a preview with no AI and no writes, like routines' `preview`.

### 2. Research

`outreach_research = "scrape" | "ai-web"` in config.toml (default `scrape`).
The UI can override it per run. Clay is left out for now; it would be a third
`Researcher` later.

| Level | What runs | Cost | Safety |
|---|---|---|---|
| `scrape` | `scrape.py` on the website and LinkedIn page, then the AI summarises with **no tools** | free + one small AI call | as today |
| `ai-web` | scrape first, then the AI CLI with **only web search/fetch** allowed: no files, no shell | AI tokens | new: pages are untrusted text, so the run gets read-only web tools and nothing else. A CLI that cannot restrict itself this way is refused with a one-line reason, like routines do |

Every level returns the same `Research`:

```python
@dataclass
class Finding:
    text: str          # "Opened a Munich office in Sept 2026"
    source: str        # URL, or "crm" for something we already knew
    kind: str          # company | person | trigger (hiring, funding, launch...)
    confidence: str    # high | medium | low

@dataclass
class Research:
    findings: list[Finding]
    linkedin_url: str          # proposed if the contact has none (person confirms)
    website_url: str           # proposed if the company has none
    level: str                 # scrape | ai-web
```

**Quality rule:** a finding without a source is not shown as fact. The drafter
may use only findings with `high` or `medium` confidence. If research finds
nothing usable, the card says so and the draft falls back to the
`messaging.py` angles, with the gaps marked `[ ]`.

If research proposes a LinkedIn URL or website the record lacks, the card shows
it as an Enrich-style proposal. Nothing is written to the contact or company
until the person accepts it.

### 3. Draft

The AI CLI runs with **no tools**. It gets the playbook, the contact brief, the
findings, the culture norms, up to 3 examples and the channel's rules, and returns JSON (`subject`, `body`, `angle`, `findings_used`).

Channel rules live in `default_messages.toml` under a new `[outreach.<channel>]`
section, and a data folder can override them in `messages.toml`:

| Channel | Rules shipped by default |
|---|---|
| email | subject ≤ 60 chars, body ≤ 120 words, one question, no attachments or links in the first mail |
| linkedin | connection note ≤ 300 chars (LinkedIn's limit); a separate message variant ≤ 600 chars for existing connections |

Language comes from the existing rule: the contact's draft language, otherwise
the company's country.

`clean_answer` refuses a draft that breaks a length limit, cites a finding that
is not in the list, or still contains a `[ ]` gap when the research had an
answer. Each refusal gets one retry; after that the card shows the draft with
the problem marked.

### 4. Review

**Storage.** One file per item in `outreach/<id>.md`, next to `drafts/`. The
front matter holds the state, the channel, the contact and company slugs, the
research level, the findings (as YAML) and timestamps. The body is the draft
text, kept byte for byte. Each step is one commit, so it is git history and
can be undone.

```
state: researching -> drafted -> ready
                          \-> skipped (reason)
                 (later)        ready -> sent -> logged
```

**Outreach page** (new, in the nav next to Messages):

- Top: filter bar, channel (required), research level, batch size,
  "Preview" and "Build queue". The queue builds in the background; cards
  appear as they finish.
- One card per contact:
  - name, title, **LinkedIn ↗**; company, stage, **website ↗**
  - findings with source links and a confidence dot; you can remove one or add your own
  - the draft (editable), its angle, and which findings it uses
  - buttons: **Mark ready**, **Regenerate** (optionally "stronger model"),
    **Skip** (with a reason), **Copy**
- Tabs: *To review*, *Ready*, *Skipped*. *Ready* is the working list for
  sending by hand, with a copy button and the contact's links.
- In this first version, **Mark ready** changes the state and appends the
  findings used to the contact's notes, under a dated heading
  (`### Research 2026-10-16 (scrape)`, one line per finding with its source),
  in the same commit. It does not log an interaction; the person logs it as
  usual.

**Contact page:** a "Research & draft" button, and an outreach card while an
item is open for that contact.

**CLI:** `hermitcrm outreach preview|build|list|show|ready|skip`, with the same
flags as the page. The MCP server gets `outreach_list` and `outreach_show`
later.

### 5. Measure quality

The plan for full auto depends on knowing whether semi-auto works. Every item
records:

- whether it was marked ready or skipped, and why it was skipped
- the edit distance between the AI draft and the text marked ready
- research level, model, time taken

A small "Outreach quality" section in Reports shows: ready rate, median edit
size, the most common skip reasons, and the reply rate once a matching message
is logged (matched on contact + channel + date ≥ ready date). Its data comes
from the `outreach/` files and the existing message status.

## Later: automatic logging, then full auto

These are settings, off by default, introduced in this order:

1. **`outreach_auto_log = false`**. When on, *Mark ready* becomes
   *I sent it*: it logs an outbound interaction (channel, contact,
   subject, the body byte for byte, `source: outreach`) through the store,
   moves the stage from entry to advance target as a manual log does, and
   sets the item to `logged`. The new `source` value counts as a
   front-matter change, so it comes with a numbered migration (a no-op for
   existing files) and tests, as CLAUDE.md requires.
2. **`outreach_mode = "semi" | "auto"`** (default `semi`). `auto` is refused
   unless all of the following hold:
   - a real `Sender` is configured for the channel
   - a daily cap (`outreach_daily_cap`, default 10)
   - per-channel opt-in (`outreach_auto_channels = ["email"]`)
   - an unlock threshold the app checks: at least N items marked ready in
     semi mode with a ready rate and edit size within limits
   - a visible kill switch on the Outreach page

   In auto mode the app still drafts first, then sends after a grace period
   (`outreach_send_delay_minutes`, default 60) during which the card can be
   stopped.

Candidate senders:

| Channel | Sender | Note |
|---|---|---|
| email | Gmail API or SMTP | Fits best. `message_id` from the send result becomes the dedup key, so a later BCC import does not double-log it |
| linkedin | — | Automated sending breaks LinkedIn's user agreement and risks the account. Recommended: LinkedIn always stays copy + open, even in auto mode |

Cold outreach to EU contacts also has GDPR / ePrivacy rules (legitimate
interest, an opt-out line in email). Auto mode should make the opt-out line
mandatory for email.

## Build order

| Phase | Scope | Done when |
|---|---|---|
| 0 | `playbook.md`: the file, Settings form, "draft it from my website", the setup step, the readiness gate, `check` | the demo folder has a filled playbook; the gate blocks an empty one |
| 1 | `outreach.py`: select, `ScrapeResearcher`, `Drafter`, `ManualSender`/`ManualLogger`, the `outreach/` files, CLI | `hermitcrm outreach build --where 'stage=prospect' --channel email --limit 3` writes 3 items on the demo folder |
| 2 | Outreach page, contact-page button, the Ready list | review a batch end to end in the browser |
| 3 | `AiWebResearcher` (tool-restricted), the critic pass, the bookmarklet's "Add to research" | each works on the demo folder; a CLI that cannot be restricted is refused |
| 4 | Quality metrics in Reports, "What was wrong?", examples from replies | numbers show after a week of use |
| 5 | `outreach_auto_log` | marking ready logs the interaction and moves the stage |
| 6 | Senders + `outreach_mode = "auto"` behind the gates above | separate spec |

## Tests

- select: the filter, the channel-data check, cooldown, closed/parked stages,
  the `do-not-contact` tag, no duplicate open items
- each Researcher with a fake fetcher / fake CLI; findings without a source are dropped
- Drafter: `clean_answer` refuses over-length text, unknown findings, leftover gaps
- `outreach/` files: deterministic writes, body byte for byte, one commit per step
- the `ai-web` level refuses a provider without a tool restriction
- playbook: front matter validation, the readiness gate, persona matching by title
- critic: a draft below the threshold is regenerated once, then shown with its scores
- Mark ready appends findings to the contact notes deterministically, in the same commit
- `ManualSender` never touches the network; "Mark ready" writes no interaction
- the `outreach_mode = "auto"` setting is refused without a Sender (guards the default)
- web: the page renders on the demo folder; a card's buttons change only the state

## Open questions

1. **One offer or several?** If you sell more than one thing, the playbook needs
   one Offer + Proof block per offer and the batch picks which one.
2. **German formality.** Should first contact default to `Sie`, or to `du` as
   today's templates do?
3. **The critic's threshold.** Strict (more regenerations, slower) or lenient
   (more drafts to fix by hand) to begin with?
