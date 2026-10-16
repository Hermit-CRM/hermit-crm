# Outreach bot: semi-automatic research and drafts

Status: proposal, not built. Written 16 Oct 2026.

## Goal

Make outreach quicker without making it worse. For each contact in a batch, the
bot puts on one card everything needed to write a good first message:

- the contact, with their LinkedIn link
- the company, with a link to its website
- research findings, each with the source it came from
- a proposed message for one channel (email, LinkedIn or WhatsApp)

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
| Where research comes from | All three, chosen per run: free scrape, AI with web search, Clay |
| Channel | Fixed for the whole batch by the filter; every draft in the batch uses that channel |
| What "approve" does | It only marks the draft ready. Sending and logging stay manual. Logging the message automatically is a later option |

## What already exists and gets reused

| Piece | Reused for |
|---|---|
| `scrape.py` | The free research level (website meta, JSON-LD, LinkedIn company page) |
| `enrich.py` `Enricher` | Running the AI command-line tool, model tiers, JSON schema answers, refusing tools when needed |
| `messaging.py` + `messages.toml` | Angles, tone and language rules the AI draft must follow |
| `routines.py` | How a draft is stored, the "a draft is a file, nothing is sent" rule, the prompt-safety rules |
| `filters.py` | The `--where` / column-filter syntax that picks the batch |
| `secrets.py` | The Clay API key |
| Contact `linkedin`, `email`, `phone`; company `website`, `country` | The links on the card and the channel check. **No new front-matter keys on contacts or companies, so no migration is needed** |

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
class Researcher(Protocol):          # scrape | ai-web | clay
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
  needs `email`, LinkedIn needs `linkedin`, WhatsApp needs `phone`. The preview
  says how many were dropped and why.
- Always left out: contacts that already have an open outreach item, contacts
  messaged in the last `outreach_cooldown_days` (default 30), companies in a
  closed or parked stage, and anything tagged `do-not-contact`.
- There is a preview with no AI and no writes, like routines' `preview`.

### 2. Research

`outreach_research = "scrape" | "ai-web" | "clay"` in config.toml (default
`scrape`). The UI can override it per run.

| Level | What runs | Cost | Safety |
|---|---|---|---|
| `scrape` | `scrape.py` on the website and LinkedIn page, then the AI summarises with **no tools** | free + one small AI call | as today |
| `ai-web` | scrape first, then the AI CLI with **only web search/fetch** allowed: no files, no shell | AI tokens | new: pages are untrusted text, so the run gets read-only web tools and nothing else. A CLI that cannot restrict itself this way is refused with a one-line reason, like routines do |
| `clay` | Clay person + company enrichment, then the AI summary with no tools | Clay credits | API key in `secrets.py`; only the fields we ask for |

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
    level: str                 # scrape | ai-web | clay
```

**Quality rule:** a finding without a source is not shown as fact. The drafter
may use only findings with `high` or `medium` confidence. If research finds
nothing usable, the card says so and the draft falls back to the
`messaging.py` angles, with the gaps marked `[ ]`.

If research proposes a LinkedIn URL or website the record lacks, the card shows
it as an Enrich-style proposal. Nothing is written to the contact or company
until the person accepts it.

### 3. Draft

The AI CLI runs with **no tools**. It gets the record, the findings and the
channel's rules, and returns JSON (`subject`, `body`, `angle`, `findings_used`).

Channel rules live in `default_messages.toml` under a new `[outreach.<channel>]`
section, and a data folder can override them in `messages.toml`:

| Channel | Rules shipped by default |
|---|---|
| email | subject ≤ 60 chars, body ≤ 120 words, one question, no attachments or links in the first mail |
| linkedin | connection note ≤ 300 chars (LinkedIn's limit); a separate message variant ≤ 600 chars for existing connections |
| whatsapp | ≤ 2 short paragraphs, only for contacts already known (warm); the filter warns when the batch has no previous interaction |

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
- In this first version, **Mark ready** only changes the state. The
  interaction gets logged when the person logs it as usual.

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
| whatsapp | WhatsApp Business Cloud API | Needs opt-in and approved templates for the first message; suitable for warm contacts only |

Cold outreach to EU contacts also has GDPR / ePrivacy rules (legitimate
interest, an opt-out line in email). Auto mode should make the opt-out line
mandatory for email.

## Build order

| Phase | Scope | Done when |
|---|---|---|
| 1 | `outreach.py`: select, `ScrapeResearcher`, `Drafter`, `ManualSender`/`ManualLogger`, the `outreach/` files, CLI | `hermitcrm outreach build --where 'stage=prospect' --channel email --limit 3` writes 3 items on the demo folder |
| 2 | Outreach page, contact-page button, the Ready list | review a batch end to end in the browser |
| 3 | `AiWebResearcher` (tool-restricted) and `ClayResearcher` | each level works on the demo folder; a CLI that cannot be restricted is refused |
| 4 | Quality metrics in Reports | numbers show after a week of use |
| 5 | `outreach_auto_log` | marking ready logs the interaction and moves the stage |
| 6 | Senders + `outreach_mode = "auto"` behind the gates above | separate spec |

## Tests

- select: the filter, the channel-data check, cooldown, closed/parked stages,
  the `do-not-contact` tag, no duplicate open items
- each Researcher with a fake fetcher / fake CLI; findings without a source are dropped
- Drafter: `clean_answer` refuses over-length text, unknown findings, leftover gaps
- `outreach/` files: deterministic writes, body byte for byte, one commit per step
- the `ai-web` level refuses a provider without a tool restriction
- `ManualSender` never touches the network; "Mark ready" writes no interaction
- the `outreach_mode = "auto"` setting is refused without a Sender (guards the default)
- web: the page renders on the demo folder; a card's buttons change only the state

## Open questions

1. **Clay from inside the app.** The Clay connector is available in Claude
   sessions, not to a local Python app. Clay's own API may need a plan that
   includes it. If not, `clay` research may have to run through an agent
   (`hermitcrm` + MCP) rather than inside the web app.
2. **WhatsApp for cold contacts.** The proposal limits WhatsApp drafts to
   contacts with an earlier interaction. Is that right for you?
3. **Where research is kept.** The proposal keeps findings on the outreach item
   only. Should "Mark ready" also append them to the contact's notes body?
4. **Batch size and cost.** The default is 10 per run. With `ai-web`, a run costs
   real tokens. Should there be a monthly cap in Settings?
