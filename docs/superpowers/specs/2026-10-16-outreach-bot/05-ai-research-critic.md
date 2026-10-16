# Part 05 · Phase 3: follow-ups, ai-web research, critic, bookmarklet

Context: [00-overview](00-overview.md). Needs phases 1-2.

**Done when:** each works on the demo folder; a CLI that cannot be restricted
is refused.

## Follow-up drafts

Trigger: an outbound message with no reply after `followup_nudge_days`
(default 5), the same setting that puts it under "waiting on them" in
`followups.py`. Decided: no separate `outreach_followup_days`; one setting for
"they have not answered", so the radar and the bot never disagree. Shape:
short, no calendar invite, an easy way out:

> quick follow-up, no calendar invite: is [topic] a priority at {company} right
> now, or not really? A short 'not now' is fine too, then I'll close the loop.

Templates ship in `default_messages.toml` (EN/DE/NL/FR) with the offer line as a
slot; overridable in `messages.toml`. The hard checks from part 03 apply.

## `AiWebResearcher` (the `ai-web` level)

| Level | What runs | Cost | Safety |
|---|---|---|---|
| `ai-web` | `scrape` first, then the AI CLI with **only** web search/fetch: no files, no shell | AI tokens | Pages are untrusted text, so the run gets read-only web tools and nothing else. A CLI that cannot restrict itself this way is refused with a one-line reason, as routines do |

Returns the same `Research` as `scrape` (part 02).

## Critic pass (lenient at first)

A second AI call (no tools) scores what the rules cannot: relevance to the
persona's pain, personalisation based on a verified finding, tone and culture,
honesty (no invented familiarity). The threshold starts low; below it the draft
is regenerated once. The card shows the scores and the critic's one-line
reason. Threshold is a setting, `outreach_critic_threshold`, to raise once there
is data. Hard rules stay in `clean_answer`, not in the critic's score.

## Bookmarklet: "Add to research"

On a LinkedIn profile you are logged in to, a new "Add to research" button in
the existing bookmarklet sends the visible profile text, About and recent
activity to the open outreach card. This is the reliable way to get
person-level detail, because LinkedIn blocks anonymous fetches.

## Tests

- `AiWebResearcher` with a fake fetcher / fake CLI; findings without a source
  are dropped
- the `ai-web` level refuses a provider without a tool restriction
- critic: a draft below the threshold is regenerated once, then shown with its
  scores
