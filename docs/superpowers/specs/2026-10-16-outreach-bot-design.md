# Outreach bot: semi-automatic research and drafts

Status: proposal, not built. Written 16 Oct 2026, revised the same day after a
review of a real pipeline in Hermit CRM (369 companies, about 24 real
conversations, 4 positive replies, 0 won).

## Goal

Make outreach quicker without making it worse. For each contact in a batch, the
bot puts on one card everything needed to write a good message:

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

**What the review showed.** The leak is less at the first touch than *after
the reply*. In 3 of 4 positive replies the prospect went quiet after receiving
a booking link or proposed times before being told what the offer was. Messages
also went to low-fit companies (fit 32-38) while 32 prospects at fit 65+ were
untouched. Companies with no salespeople replied 0 of 5. The design below
answers each of these.

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
| What the bot knows about the seller | `MESSAGING.md`, the playbook every data folder already has, extended with structured sections; the bot refuses to run without its minimum |
| Offers per data folder | **One.** Two businesses means two data folders, each with its own playbook (see "One offer per data folder") |
| German first contact | `du` |
| Critic | Starts **lenient**. Hard rules are deterministic checks in `clean_answer`, not part of the critic's score |
| Default call to action | One diagnostic question, **not** a meeting ask. A meeting comes only after they answer |

## What already exists and gets reused

| Piece | Reused for |
|---|---|
| `MESSAGING.md` (written by `datafolder.py`, called "the playbook" in the AI-agent instructions) | The home of the playbook; extended, not replaced |
| `scrape.py` | The free research level (website meta, JSON-LD, LinkedIn company page) |
| `enrich.py` `Enricher` | Running the AI command-line tool, model tiers, JSON schema answers, refusing tools when needed |
| `messaging.py` + `messages.toml` | Angles, tone and language rules the AI draft must follow |
| `routines.py` | How a draft is stored, the "a draft is a file, nothing is sent" rule, the prompt-safety rules |
| `followups.py` | "Replies owed" feeds the reply-to-interest drafts; "waiting on them" feeds follow-ups |
| `filters.py` | The `--where` / column-filter syntax that picks the batch |
| Contact `linkedin`, `email`, `phone`; company `website`, `country`, `fit_score`, `fte_estimate`, `ae_count` | The links on the card, the channel check, fit and disqualifiers |

The bot itself adds no front-matter keys to companies or contacts. The one
front-matter change is `angle` on interactions (see "Angle on interactions"),
with its own migration.

## The playbook: what the bot knows about you

A message works when it connects **this person's** likely problem to **your**
offer, with proof, in a tone that fits their culture and the channel. Today
Hermit knows little of the seller's side. Setup asks only for your name, and
the templates in `default_messages.toml` contain gaps like `[your offer]` and
`[the problem you solve]`. Without that context, any AI draft is generic.

### One home: `MESSAGING.md`

Every data folder already has `MESSAGING.md`, titled "Messaging playbook", and
the folder's agent instructions tell AI agents to read it for outreach
wording. It stays the one playbook; there is no second file.

- **Front matter** (new, YAML like every record): the parts Python needs,
  namely the ICP, disqualifiers, personas' title lists and the offer line.
- **Body**: the current text (angles, slots, languages, "What worked") stays,
  and gains the seller sections below as headings. The AI reads the body; it
  never sees the front matter as instructions.

**Existing folders.** `MESSAGING.md` is the user's file and `init` writes it
only when absent, so nothing changes by itself. Settings → Playbook and
`hermitcrm playbook upgrade` offer to add the front matter and the missing
headings, keeping every existing line byte for byte, in one commit. The
upgrade is idempotent. Because this is a file in the data folder and not a
record, it is not a `migrations.py` migration; `hermitcrm check` reports a
`MESSAGING.md` without front matter as "not set up for the outreach bot",
which is a hint and not an error.

### Sections

| Section | What goes in it | Used by |
|---|---|---|
| **Offer** (front matter `offer_line` + body) | What you sell, in one sentence (the *offer line*, which every reply to interest must contain); the outcome for the customer; engagement model; what you do *not* do | Drafter, `clean_answer` |
| **ICP** (front matter) | Industries, company size (FTE range), number of salespeople, countries, funding stage, signals that make a good moment | Select (fit and sort), Drafter |
| **Disqualifiers** (front matter) | Hard reasons a company is not a prospect. Select **excludes** them (not only warns) | Select |
| **Personas** (front matter + body) | Per buyer type: titles that map to it, their top 2-3 pains, what they care about, what they ignore | Drafter picks the persona from the contact's title and `role` |
| **Proof** | Customer outcomes, numbers, short case lines the AI may cite. The AI may cite **only** what is written here | Drafter, `clean_answer` |
| **Why you** | Differentiators against the usual alternative (hire, agency, do nothing) | Drafter |
| **Voice** | Tone, words you use, words you never use, sign-off, `du`/`Sie` | Drafter, Critic |
| **Channels** | Per channel: purpose of the first touch, length, call to action | Drafter, Critic |
| **Don'ts** | Rules: no fake familiarity, no "I hope this finds you well", no claims without proof, never name competitors | Critic (the mechanical ones also in `clean_answer`) |

Example front matter for a fractional sales leadership offer (fictional, but
shaped like the real case that drove this revision):

```yaml
offer_line: "I work as your fractional Head of Sales: part-time, no minimum term."
icp:
  industries: [b2b-saas, ai]
  fte: [10, 50]
  salespeople: [1, 5]
  countries: [DE, AT, CH, NL, SE, DK, NO]
  funding: [seed, series-a]
  signals: [founder-still-sells, no-sales-leader, hiring-sales]
disqualifiers:
  - fte_over: 100
  - title_present: ["Head of Sales", "VP Sales", "CRO", "Sales Director"]
  - no_salespeople: true          # ae_count == 0
personas:
  founder: {titles: ["CEO", "Founder", "Co-Founder", "Managing Director"]}
  sales-lead: {titles: ["Sales Lead", "Senior AE", "Account Executive"]}
```

Disqualifiers are a small fixed vocabulary that Python evaluates on known
fields (`fte_estimate`, `ae_count`, contact titles at the company, tags), so
`check` can validate them. When a field is empty the rule cannot decide, so
the company stays in, and the card says "not checked: no headcount".

The default `messaging.py` angles stay in place. When the playbook is filled,
its offer line and proof fill the template gaps, so even the non-AI drafts
improve.

### One offer per data folder

A data folder holds **one** offer and one playbook. Someone selling two things
(say a consulting service and a software product) uses two data folders, each
with its own pipeline, playbook and Messages statistics. Mixing them makes the
statistics meaningless: the review found a product pitch and a referral ask
inside a consulting pipeline, counted in the same reply rates.

The bot does not try to detect a second offer in prose. It enforces what it
can: the front matter has exactly one `offer_line` (a list is refused by
`check` with "one offer per data folder; use a second folder for a second
offer"). Several offers per folder is left as a possible later extension
(one offer block per offer, chosen per batch, statistics split by offer). It
is not designed here.

`INSTALL.md` / the welcome page say this plainly when a second folder is
useful, and `hermitcrm init` already creates any number of folders.

### Getting it filled: guided, not a blank page

- **Settings → Playbook**: a form with one box per section, examples beside
  each box, and a completeness meter. It reads and writes `MESSAGING.md`.
- **"Draft it from my website"**: the user gives their own website, LinkedIn
  About text or a sales deck as pasted text. The AI CLI (no tools) proposes
  each section and the person edits and saves. Same pattern as Enrich: a
  proposal is never saved without confirmation.
- **Setup** (`hermitcrm init` and the welcome flow) gets an optional fourth
  step, "Your offer", which asks three questions: what you sell (the offer
  line), to whom, and one customer result.
- **Readiness gate**: the Outreach page and `hermitcrm outreach build` refuse to
  run until the offer line, ICP, one persona and one proof line are filled. The
  page explains what is missing and links to the form.
- `hermitcrm help playbook` documents the format for AI agents, and
  `hermitcrm check` validates the front matter.

### Understanding the contact

The drafter gets one compact brief per contact, built by Python, not by the AI
browsing freely:

| Input | Source |
|---|---|
| Persona | Title matched against playbook personas; `role` (champion, decision-maker...) |
| Seniority and tenure | Title; LinkedIn profile text if captured |
| What they said or posted | The **bookmarklet** (already in Hermit): on a LinkedIn profile you are logged in to, a new "Add to research" button sends the visible profile text, About and recent activity to the open outreach card. This is the reliable way to get person-level detail, because LinkedIn blocks anonymous fetches |
| Company situation | Findings from research, signals (`growing`, `hiring`...), `fte_estimate`, `ae_count`, `product_oneliner`, stage |
| Relationship so far | The last interactions with the person and company (summaries, not whole threads), so a second touch is not written as a first |
| Culture and language | See below. A company with **no country** is flagged on the card ("no country: English and default culture used"), never silently guessed |
| ICP fit | Fit score and which ICP points matched |

### Culture

`default_messages.toml` gets a `[culture.<country>]` table with defaults the
person can override in `messages.toml`:

- language (exists today)
- formality: German first contact uses **`du`** (as today's templates do);
  Dutch directness; French politeness formulas. The playbook's Voice can
  override this per folder
- greeting and sign-off norms, use of first name vs title
- how direct the call to action can be

These are starting points; the card shows which norms were applied, so the
person can correct them.

### Making messages work

1. **Hard checks in `clean_answer`** (deterministic, no AI). A draft is refused
   and retried once, then shown with the problem marked, when it:
   - asks more or fewer than **exactly one question** (count of `?` outside
     quotes, per language)
   - **opens with "I"** (or the language's equivalent: `Ich`, `Ik`, `Je`)
   - is a reply to interest and does **not contain the offer line** from the
     playbook (normalised whitespace; a translated offer line per language can
     be set in the playbook)
   - contains a **calendar link** (Calendly and similar scheduling services, Google/Microsoft booking
     URLs, a configurable list) or **proposes a time slot** (weekday + time,
     dates with times, "this week at") in a first touch, a reply to interest
     or a follow-up
   - breaks the channel's length, cites a finding or proof line that is not in
     the input, or leaves a `[ ]` gap the research could fill

   Each of these broke in real messages from late September, which is why they
   are rules and not suggestions.
2. **A critic pass, lenient at first.** A second AI call (no tools) scores what
   the rules cannot: relevance to the persona's pain, personalisation based on
   a verified finding, tone and culture, honesty (no invented familiarity).
   The threshold starts low; below it the draft is regenerated once. The card
   shows the scores and the critic's one-line reason. The threshold is a
   setting (`outreach_critic_threshold`) to raise once there is data.
3. **Learning from your own results.** Reply rate by angle, persona, channel
   and language, **one dimension at a time** (see "Measure quality"). A message
   that got a reply can be saved as an example ("Use as example"); the drafter
   gets the 2-3 closest examples (same persona, channel and language). Only
   your own sent messages become examples.
4. **Edits teach too.** When the text marked ready differs a lot from the
   draft, the card asks "What was wrong?" (wrong tone, wrong pain, too long, bad
   finding). The answers appear in the quality report and point to the
   playbook section to fix.
5. **One variable at a time.** For the first weeks, use only the template
   angles, so results can be compared. An optional A/B setting drafts two
   angles for the same persona in a batch.

### Also worth taking into account

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
  read), no fake urgency.

## Draft types

The bot drafts three kinds of message. Each has its own rules; all share the
hard checks.

| Type | When | Shape |
|---|---|---|
| `first-touch` | A selected contact with no earlier outbound message | One finding-based opening (not "I..."), the offer in one line, **one diagnostic question** as the call to action, e.g. "Where does it hurt most right now: pipeline, conversion or deal size?" No meeting ask, no link |
| `reply-to-interest` | An inbound reply that shows interest (from `followups.py` "replies owed"; the AI classifies the reply with no tools and the person confirms) | The offer line, one proof line, "the first call is free, no pitch", and one question. **No time slot, no booking link, no price, no days per week.** A meeting is proposed only after they answer the question |
| `follow-up` | An outbound message with no reply after `outreach_followup_days` (default 7) | Short, no calendar invite, an easy way out: "quick follow-up, no calendar invite: is [topic] a priority at {company} right now, or not really? A short 'not now' is fine too, then I'll close the loop." |

Example `reply-to-interest` in English, in the approved shape (each folder
keeps its own wording, per language, in `MESSAGING.md`):

> Fair question. I work as your fractional Head of Sales: part-time, no
> minimum term. I build the sales playbook, coach your AEs and close the bigger
> deals with you, until your team can carry it. I've run sales teams in 5
> organisations. The first call is free and all about you, without a sales
> pitch. Where does it hurt most right now: pipeline, conversion or deal size?

The wording templates for `reply-to-interest` and `follow-up` ship in
`default_messages.toml` (EN/DE/NL/FR), neutral, with the offer line as a slot,
and can be overridden in `messages.toml`.

## Pipeline

```
select ──> research ──> draft ──> check ──> review ──> [send] ──> [log]
 filter     Researcher   Drafter   clean_    person     Sender     Logger
 button     (2 kinds)    (AI CLI)  answer +  marks      (manual    (manual
 radar                             critic    ready       now)       now)
```

Every step is a small interface with one class behind it now. Full auto later
adds classes behind `Sender` and `Logger`. Nothing above them changes.

```python
class Researcher(Protocol):          # scrape | ai-web (Clay later)
    def research(self, company, contact) -> Research: ...

class Drafter(Protocol):             # AI CLI, no tools
    def draft(self, kind, company, contact, research, channel) -> Draft: ...

class Sender(Protocol):              # ManualSender now: returns "not sent"
    def send(self, item) -> SendResult: ...

class Logger(Protocol):              # ManualLogger now: does nothing
    def log(self, item, result) -> None: ...
```

### 1. Select

- **Batch:** a list filter (the same syntax as the Contacts page and
  `hermitcrm set --where`), one channel, a draft type and a batch size
  (default 10).
- **Button:** "Research & draft" on the contact page, with a channel picker.
- **Radar:** replies to interest and follow-ups come from `followups.py`.
- **Order:** by fit score, highest first, by default. The preview shows how
  many high-fit prospects (fit ≥ 65 by default) are untouched.
- **Excluded:** companies hit by a playbook disqualifier (the preview lists
  them with the rule that hit); contacts the channel cannot reach (email needs
  `email`, LinkedIn needs `linkedin`); contacts with an open outreach item;
  contacts messaged in the last `outreach_cooldown_days` (default 30);
  companies in a closed or parked stage; anything tagged `do-not-contact`.
- **Duplicates at company level.** "One open item" applies per company too,
  and to likely duplicate companies: the same website domain, or names equal
  after slug normalisation and dropping suffixes like `-ai`, `-gmbh`, `-hq`
  (e.g. `acme-robotics` and `acme-robotics-ai`). The preview flags the pair
  and links to Merge.
- **Flags, not exclusions:** no country, no headcount, no `ae_count`. The card
  says what is missing and which rule could not be checked.
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

If research proposes a LinkedIn URL, website or country the record lacks, the
card shows it as an Enrich-style proposal. Nothing is written to the contact or
company until the person accepts it.

### 3. Draft

The AI CLI runs with **no tools**. It gets the draft type, the playbook body,
the contact brief, the findings, the culture norms, up to 3 examples and the
channel's rules, and returns JSON (`subject`, `body`, `angle`,
`findings_used`, `proof_used`). `angle` uses the same values as the
interaction field below.

Channel rules live in `default_messages.toml` under a new `[outreach.<channel>]`
section, and a data folder can override them in `messages.toml`:

| Channel | Rules shipped by default |
|---|---|
| email | subject ≤ 60 chars, body ≤ 120 words, exactly one question, no attachments or links in a first touch |
| linkedin | connection note ≤ 300 chars (LinkedIn's limit), no pitch; a separate message variant ≤ 600 chars for existing connections |

Language comes from the existing rule: the contact's draft language, otherwise
the company's country.

### 4. Review

**Storage.** One file per item in `outreach/<id>.md`, next to `drafts/`. The
front matter holds the state, the draft type, the channel, the contact and
company slugs, the angle, the research level, the findings (as YAML), the
check results and timestamps. The body is the draft text, kept byte for byte.
Each step is one commit, so it is git history and can be undone.

```
state: researching -> drafted -> ready
                          \-> skipped (reason)
                 (later)        ready -> sent -> logged
```

**Outreach page** (new, in the nav next to Messages):

- Top: filter bar, draft type, channel (required), research level, batch size,
  "Preview" and "Build queue". The queue builds in the background; cards
  appear as they finish.
- Tabs: *Replies to interest* (first, because that is where deals leak),
  *Follow-ups*, *First touches*, *Ready*, *Skipped*.
- One card per contact:
  - name, title, **LinkedIn ↗**; company, stage, fit, **website ↗**
  - flags (no country, unchecked disqualifier, possible duplicate)
  - findings with source links and a confidence dot; you can remove one or add your own
  - the draft (editable), its type and angle, which findings and proof it
    uses, and the check results
  - buttons: **Mark ready**, **Regenerate** (optionally "stronger model"),
    **Skip** (with a reason), **Copy**
- *Ready* is the working list for sending by hand, with a copy button and the
  contact's links.
- **Mark ready** changes the state and appends the findings used to the
  contact's notes, under a dated heading (`### Research 2026-10-16 (scrape)`,
  one line per finding with its source), in the same commit. It does not log
  an interaction; the person logs it as usual.

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

A small "Outreach quality" section in Reports shows ready rate, median edit
size, the most common skip reasons, and reply rate.

**Small numbers.** With a few dozen conversations, a grid of angle × persona ×
channel × language is mostly empty cells. The report shows **one dimension at
a time** (a selector: angle, persona, channel, language, draft type) and hides
a cell until it has **at least 10 results**, showing "n = 4, too few" instead.

**Prerequisites before phase 4.** The baseline is only as good as the data:

- **Country.** Companies without a country get English and default culture.
  The Companies list gets a "no country" filter and the bot's card a flag;
  filling country is a listed step before trusting results per language.
- **Mislogged interactions.** Notes logged as LinkedIn messages, a reply stored
  inside an outgoing record, duplicate replies and leftover demo-sample
  messages skew reply rates. `hermitcrm check` gets warnings for the obvious
  cases: an outbound message whose body contains a quoted inbound header
  (`On ... wrote:`, `Am ... schrieb`), two inbound interactions from the same
  contact with identical bodies, a message on a sample company in a non-demo
  folder. Cleaning them is a phase 4 prerequisite.
- **Duplicate companies.** The same check as Select's duplicate rule, listed
  in `check` with a link to Merge.

## Angle on interactions (now, not at phase 5)

Manually logged messages and bot items must be comparable from day one, so
interactions get an optional `angle` key:

- values: `scale`, `unblock`, `hook`, `bridge`, `decline`, `custom`, or empty
  (unknown); the same values as the Drafter's `angle` output
- placed after `subject` in the key order; omitted when empty so existing
  files are unchanged when rewritten
- shown and filterable on the Messages tab; settable in the log form and in
  bulk with `hermitcrm set`
- a new numbered migration in `migrations.py` (idempotent, front matter only:
  it normalises an `angle` value already written by hand and touches nothing
  else) plus tests, as CLAUDE.md requires

This ships with phase 1, before the bot is used, so its first weeks are
measured against manual messages with the same field.

## Later: automatic logging, then full auto

These are settings, off by default, introduced in this order:

1. **`outreach_auto_log = false`**. When on, *Mark ready* becomes
   *I sent it*: it logs an outbound interaction (channel, contact,
   subject, the body byte for byte, `angle`, `source: outreach`) through the
   store, moves the stage from entry to advance target as a manual log does,
   and sets the item to `logged`. The new `source` value counts as a
   front-matter change, so it comes with a numbered migration (a no-op for
   existing files) and tests.
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
   stopped. Replies to interest stay semi-automatic even in auto mode.

Candidate senders:

| Channel | Sender | Note |
|---|---|---|
| email | Gmail API or SMTP | Fits best. `message_id` from the send result becomes the dedup key, so a later BCC import does not double-log it |
| linkedin | none, ever | Automated sending breaks LinkedIn's user agreement and risks the account. LinkedIn always stays copy + open, even in auto mode |

Cold outreach to EU contacts also has GDPR / ePrivacy rules (legitimate
interest, an opt-out line in email). Auto mode should make the opt-out line
mandatory for email.

## Build order

| Phase | Scope | Done when |
|---|---|---|
| 0 | Playbook in `MESSAGING.md`: front matter, `playbook upgrade`, Settings form, "draft it from my website", setup step, readiness gate, `check` (incl. one offer line) | the demo folder has a filled playbook; the gate blocks an empty one; an old `MESSAGING.md` upgrades byte for byte |
| 1 | `angle` on interactions + migration; `outreach.py`: select (disqualifiers, fit order, company duplicates, flags), `ScrapeResearcher`, `Drafter` for `first-touch`, `clean_answer` hard checks, `ManualSender`/`ManualLogger`, the `outreach/` files, CLI | `hermitcrm outreach build --where 'stage=prospect' --channel email --limit 3` writes 3 checked items on the demo folder |
| 2 | Outreach page, contact-page button, Ready list; **`reply-to-interest`** drafts from the radar | review a batch and a reply to interest end to end in the browser |
| 3 | `follow-up` drafts, `AiWebResearcher` (tool-restricted), the critic pass (lenient), the bookmarklet's "Add to research" | each works on the demo folder; a CLI that cannot be restricted is refused |
| 4 | Data-quality warnings in `check`; quality report (one dimension at a time, n ≥ 10); "What was wrong?"; examples from replies | numbers show after a week of use on a cleaned folder |
| 5 | `outreach_auto_log` | marking ready logs the interaction with its angle and moves the stage |
| 6 | Senders + `outreach_mode = "auto"` behind the gates above | separate spec |

## Tests

- playbook: front matter validation; one `offer_line` (a list refused);
  disqualifier vocabulary; the readiness gate; persona matching by title;
  `playbook upgrade` keeps an existing `MESSAGING.md` byte for byte and is
  idempotent
- select: the filter; fit-score order; each disqualifier excludes, and an
  empty field leaves the company in with a flag; channel-data check; cooldown;
  closed/parked stages; `do-not-contact`; one open item per contact and per
  company, including likely duplicates
- `clean_answer`: refuses zero or two questions, an opening "I"/"Ich"/"Ik"/"Je",
  a reply to interest without the offer line, a calendar link, a proposed time
  slot, over-length text, unknown findings or proof, leftover gaps; one retry,
  then the draft is shown with the problem marked
- each Researcher with a fake fetcher / fake CLI; findings without a source
  are dropped
- `angle` migration: idempotent, front matter only, interaction bodies byte
  for byte; files without `angle` are unchanged
- `outreach/` files: deterministic writes, body byte for byte, one commit per step
- the `ai-web` level refuses a provider without a tool restriction
- critic: a draft below the threshold is regenerated once, then shown with its
  scores
- Mark ready appends findings to the contact notes deterministically, in the
  same commit
- report: a cell under 10 results is hidden; one dimension at a time
- `check`: the mislogged-interaction and duplicate-company warnings
- `ManualSender` never touches the network; "Mark ready" writes no interaction
- the `outreach_mode = "auto"` setting is refused without a Sender (guards the
  default)
- web: the page renders on the demo folder; a card's buttons change only the
  state

## Open questions

1. **Interest detection.** The AI classifies an inbound reply as interest and
   the person confirms. Should an outcome value (e.g. `interested`) be added
   to `outcomes` in config.toml as well, so the radar can use it without AI?
2. **Fit score source.** `fit_score` comes from the source list today. Should
   the bot compute its own fit from the playbook ICP when the field is empty,
   or only show "no fit score"?
