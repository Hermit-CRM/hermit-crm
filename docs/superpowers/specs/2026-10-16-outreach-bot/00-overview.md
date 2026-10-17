# Outreach bot: overview

Status (17 Oct 2026): parts 01-05 are built and merged; parts 06-07 are not
started. Written 16 Oct 2026, revised the
same day after a review of a real pipeline (369 companies, ~24 real
conversations, 4 positive replies, 0 won).

**How to read this spec.** Read this file, then only the part for the phase
being built. Each part holds its own scope, tests and open questions.

| Part | Phase | Scope | State |
|---|---|---|---|
| [01-playbook](01-playbook.md) | 0 | What the bot knows about the seller (`MESSAGING.md`) | Merged (PR #107) |
| [02-select-research](02-select-research.md) | 1 | `angle` field, picking the batch, research, the contact brief | Merged (PR #109) |
| [03-draft-check-store](03-draft-check-store.md) | 1 | First-touch drafts, `clean_answer`, `outreach/` files, CLI | Merged (PR #109) |
| [04-review-page](04-review-page.md) | 2 | Outreach page, Ready list, reply-to-interest | Merged (04a PR #111, 04b PR #112) |
| [05-ai-research-critic](05-ai-research-critic.md) | 3 | Follow-ups, `ai-web` research, critic, bookmarklet | Merged (05a PR #117, 05b and 05c PR #118, 05d PR #121); see `PLAN-05.md` |
| [06-quality](06-quality.md) | 4 | Data cleanup, quality report, learning from results | Not started |
| [07-auto-later](07-auto-later.md) | 5-6 | Auto-log, then full auto (not designed in detail) | Not started |

## Goal

Make outreach quicker without making it worse. Per contact in a batch, one card
holds: the contact (LinkedIn link), the company (website link), research
findings each with its source, and a proposed message for one channel (email or
LinkedIn). The person reviews, edits and marks it **ready**. In v1 the bot
never sends and never logs; the person sends and logs as usual (by hand, BCC
import or the extension). Full auto is a later setting, off by default; the
design leaves a place for it.

## What the review showed

- The leak is mostly **after the reply**: in 3 of 4 positive replies the
  prospect went quiet after getting a booking link or proposed times before
  hearing what the offer was. → reply-to-interest drafts (part 04).
- Messages went to low-fit companies (fit 32-38) while 32 prospects at fit 65+
  were untouched. → fit order and disqualifiers (part 02).
- Companies with no salespeople replied 0 of 5. → disqualifiers (part 01).

## Decisions (16 Oct 2026)

| Question | Decision |
|---|---|
| How contacts enter | Both: a batch from a list filter, and a per-contact "Research & draft" button |
| Research source | Chosen per run: `scrape` or `ai-web` (Clay later, via the `Researcher` interface) |
| Channel | Fixed per batch (email or LinkedIn). WhatsApp is not a bot channel |
| "Approve" | Only marks the draft ready. Sending and logging stay manual; auto-log is later |
| Findings | "Mark ready" appends the findings used to the contact's notes |
| Cost cap | None |
| Seller knowledge | `MESSAGING.md`, extended; the bot refuses to run without its minimum |
| Approaches per data folder | One or more (revised 16 Oct, part 01): each approach complete on its own, the bot picks the approach by ICP fit, a tie asks the person. A separate business = a second data folder |
| German first contact | `du` |
| Critic | Starts lenient. Hard rules are deterministic checks in `clean_answer`, not critic scores |
| Default call to action | One diagnostic question, not a meeting ask. A meeting only after they answer |
| Disqualifiers | Free text the AI weighs, plus one hard check (tag present); size, number of salespeople and the like are ICP ranges on the folder's own fields (revised 16 Oct, part 01) |
| Learning from sent messages | Compare the proposed draft with the message actually sent and feed the difference into the approach's Lessons: part 06, once drafts are stored (part 03) |

## Pipeline

```
select ──> research ──> draft ──> check ──> review ──> [send] ──> [log]
 filter     Researcher   Drafter   clean_    person     Sender     Logger
 button     (2 kinds)    (AI CLI)  answer +  marks      (manual    (manual
 radar                             critic    ready       now)       now)
```

Each step is a small interface with one class behind it now. Full auto later
adds classes behind Sender and Logger; nothing above them changes.

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

## What already exists and gets reused

| Piece | Reused for |
|---|---|
| `MESSAGING.md` (written by `datafolder.py`, "the playbook") | Home of the playbook; extended, not replaced |
| `scrape.py` | The free research level (website meta, JSON-LD, LinkedIn company page) |
| `enrich.py` Enricher | Running the AI CLI, model tiers, JSON schema answers, refusing tools |
| `messaging.py` + `messages.toml` | Angles, tone and language rules the draft must follow |
| `routines.py` | Draft storage, "a draft is a file, nothing is sent", prompt-safety rules |
| `followups.py` | "Replies owed" → reply-to-interest; "waiting on them" → follow-ups |
| `filters.py` | The `--where` / column-filter syntax that picks the batch |
| Contact `linkedin`, `email`, `phone`; company `website`, `country`, `fit_score`, `fte_estimate`, `ae_count` | Card links, channel check, fit, disqualifiers |

The bot adds **no** front-matter keys to companies or contacts. The
front-matter changes are `angle` and `approach` on interactions (part 02), with
their own migration: `approach` names the playbook approach a message was for, so the
Messages statistics can be read per approach.

## Rules that apply to every part

- **Honesty:** no invented familiarity ("loved your post" when none was read),
  no fake urgency.
- **Consent and privacy:** findings stored in notes are personal data; keep only
  what is relevant to the business conversation. The opt-out line for cold
  email stays part of the email channel rules.
- **Proposals, not writes:** anything research proposes for a record (LinkedIn
  URL, website, country) is shown Enrich-style and written only on acceptance.
