# Plan: Part 05 · follow-ups, `ai-web` research, the critic, the bookmarklet

**Status (17 Oct 2026): built and merged.** 05a PR #117; 05b PR #118, which also
carries 05c (PR #120 was merged into the 05b branch); 05d PR #121. Open
questions 2-6 went the way this plan reads; questions 7-10 took this plan's
defaults (8: the lowest of the four scores counts; 9: the second draft is
kept; 10: the bookmarklet sends About and the person's own posts and comments
only). The questions are left below as they were asked.

Spec: [05-ai-research-critic](05-ai-research-critic.md). Builds on the code as
it is: phase 1, 04a and **04b, replies to interest** on `main` (PRs #109,
#111, #112). 04b adds the pieces part 05 extends (`kind_for`, `reply_to` on
items, the thread-reply branches in `check_text` and `clean_answer`, the
Replies tab, `REPLY_CHANNEL_TEXT`, `reply_template`).

Four pull requests. 05a goes first; 05b, 05c and 05d do not depend on each
other and can go in any order after it (the order below is the suggested one):

- **05a, follow-ups**: the `follow-up` kind, picked by `followup_nudge_days`.
- **05b, `ai-web` research**: a web-only tool restriction for the AI CLI and
  `AiWebResearcher`.
- **05c, the critic**: a second AI call that scores a draft, one regeneration
  below the threshold.
- **05d, the bookmarklet**: "Add to research" from a LinkedIn profile you are
  logged in to.

**Done when** (spec): each works on the demo folder; a CLI that cannot be
restricted is refused.

## Fixed points (as in PLAN-04, unchanged)

- Plain FastAPI + Jinja, forms that POST and redirect with a flash. No HTMX, no
  SSE, no new frontend dependency, no background threads.
- Long AI work runs in `run_in_threadpool` inside the request, as Enrich,
  routines and the 04 build do. A batch builds one contact per request.
- Every write goes through `outreach.py` (one commit per step, through
  `store.lock` / `store.batch` and `store.notify`). The web layer only parses
  forms and renders.
- Commit messages in the data folder are the app's own (`outreach: …`), never
  `ai:`.
- Item bodies are kept byte for byte: a textarea's `\r\n` is turned into `\n`
  and nothing else is changed (`_edit`).
- CSRF on every POST (`check_csrf`); the request guard already refuses
  cross-site POSTs. A GET never writes.
- No new runtime dependency. No new front-matter key on companies or contacts.

## Contradictions between the spec and the code

Found while reading the code. Each has the choice this plan makes; the
maintainer may overrule it (see the open questions at the end).

1. **The cooldown excludes every follow-up.** `_excluded` refuses any
   non-reply candidate messaged within `outreach_cooldown_days` (default 30),
   and a follow-up is due after `followup_nudge_days` (default 5). Built as is,
   no follow-up is ever drafted. → Follow-ups skip the "messaged N days ago"
   cooldown, as replies to interest already do. The skip cooldown (a skipped
   follow-up comes back after `outreach_cooldown_days`) still applies.
2. **"Templates with the offer line as a slot", but the example has no offer
   line.** → `{offer_line}` is an optional line in the follow-up template (left
   out of the default wording, like `{first_step_offer}` in 04b) and a
   follow-up has no "must say the offer line" check.
3. **`[topic]` in the example would fail the gap check.** `check_text` refuses
   any `[ ]` when the draft is not a fallback. The example's `[topic]` is for
   the AI to fill, not a gap. → The template says `{topic}` and the prompt
   tells the AI to fill it from the first message. Careful: `reply_template`
   drops a line whose slots are all empty, so `topic` gets an explicit value
   ("the topic of your first message") rather than none, or the line vanishes.
4. **The link check skips follow-ups.** `check_text` refuses a plain link only
   for `first-touch` and `reply-to-interest`; the spec says part 03's hard
   checks apply. → A follow-up gets the link check too. Calendar links and
   time slots are already refused for every kind.
5. **Opt-out line.** `opt_out_line` adds the playbook's line only to a
   `first-touch` email. A follow-up email is just as unsolicited. → The plan
   adds it to follow-up emails as well (open question 2).
6. **Channel per batch vs the thread's channel.** A batch has one channel, but
   a follow-up belongs on the channel of the message it follows. → A follow-up
   batch takes only contacts whose unanswered message was on the batch's
   channel; the rest are excluded with that reason. A LinkedIn follow-up is a
   message in the conversation (pitch limits, like a LinkedIn reply), which only
   works if they accepted the connection: open question 3.
7. **No limit on follow-ups.** The radar puts a contact back under "waiting on
   them" `followup_nudge_days` after *every* unanswered message, so the
   follow-up itself would draw a second follow-up, and so on. The spec's
   shape ("then I'll close the loop") implies one. → At most one follow-up per
   silence: excluded when two or more outbound messages since their last
   inbound one (or ever, without one) are in the CRM. Open question 4.
8. **The tool check for `ai-web` does not exist.** `routines.ai_problem` and
   `Enricher.no_tools_problem` answer "can this CLI run with *no* tools", and
   Codex passes (read-only sandbox) although it can still read files on the
   machine and has no web search switched on. The Enrich default
   (`tools=None`) gives Claude `--allowedTools WebSearch,WebFetch` **without**
   `--tools`, which leaves Claude's read-only file tools on (the code comment
   at `ClaudeProvider.build_argv` says so). Neither is "only web search/fetch:
   no files, no shell". → A new web-only restriction per provider (05b); only
   Claude has one today (`--tools WebSearch,WebFetch`), so `ai-web` refuses
   Codex, Gemini, Grok and a custom command.
9. **A bookmarklet has no buttons.** The spec asks for a new "Add to research"
   button *in* the bookmarklet; a bookmarklet is one `javascript:` link. And
   today a profile that is already in the CRM goes straight to "already in the
   CRM" (`capture.already_saved`). → Same bookmarklet, no second one to
   install: when the profile belongs to a contact with a drafted outreach item,
   the page it opens offers **Add to research** for that card (05d).
10. **About and recent activity are not read today.** The bookmarklet sends
    `h1`, `top`, `exp`, `co`, `lab`, `mail` within a 16 KB request head. → Two
    new pieces, `about` and `act`, cut to a budget like the others; the old
    bookmarklet keeps working without them.
11. **"Regenerated once".** `AIDrafter.draft` already makes up to two calls
    (the second when the hard checks fail). → "Once" means one critic-driven
    regeneration (itself up to two draft calls), then the critic again: at
    most four draft calls and two critic calls per card. There is no cost cap
    (overview), but the card says how many calls it took (`attempts`).
12. **Tab names.** Part 04 lists "Replies to interest, Follow-ups, First
    touches, Ready, Skipped"; 04a/04b built "Replies to interest, Drafts,
    Ready, Sent, Skipped". → Follow-ups go between Replies to interest and
    Drafts; the other names stay as built.
13. **New keys in `outreach/` items and the migration rule.** CLAUDE.md asks for
    a numbered migration when front-matter keys change. 04b added `reply_to` to
    `ITEM_KEYS` without one: an item is not a company or contact record,
    `item_from_text` reads a missing key as empty, and a rewritten item gains
    the key in `ITEM_KEYS` order. → This plan does the same for its new keys
    (`follows`, `critic`, `critic_reason`, `critic_model`). Open question 6.
14. **"Active" differs.** The radar keeps only `company.is_active` (not closed,
    not parked); `select()` uses `store.stages.is_open(stage)`. For stages the
    two agree on the demo folder; a custom stage list could make them differ,
    and then the radar shows a nudge the bot refuses. → Follow-up selection
    asks `followups.for_contact` first and `_excluded` after, so the refusal
    reason is shown, never a silent gap. A test pins the demo folder.

## 05a · follow-ups

Needs 04b. No new setting: `followup_nudge_days` (default 5, in
`store.DEFAULT_CONFIG`) decides when a follow-up is due, the same value the
radar and routines read, so the bot and the radar cannot disagree.

### `outreach.py`

1. `FOLLOW_UP = "follow-up"` (already in `KINDS`); add it to `BUILT_KINDS`. A
   helper `in_thread(kind)` (REPLY or FOLLOW_UP) replaces the `kind == REPLY`
   tests that mean "answers a thread, no research, no angle" in `build`,
   `redraft`, `clean_answer` and `_apply_draft`. Tests that mean "reply to
   interest" (offer line, price, one proof line) stay on REPLY.
2. `Item.follows`: the id of the outbound interaction being followed up, after
   `reply_to` in `ITEM_KEYS`. Read and written like `reply_to`.
3. `due_followups(store, today, config) -> list[Nudge]`: per contact,
   `followups.for_contact(company, cslug, today, nudge_after=followup_nudge_days)`
   with `kind == NUDGE`; sample and inactive companies left out, as `replies()`
   does. Oldest first. Pure read, no AI.
4. `select(kind="follow-up")`: candidates are the due follow-ups (or the
   `contacts=` given); `_excluded` gains a follow-up branch:
   - the unanswered message is on another channel than the batch → excluded
   - two or more outbound messages since their last inbound one → "followed
     up already; close the loop" (contradiction 7)
   - no "messaged N days ago" cooldown (contradiction 1); do-not-contact,
     closed stage, open item, duplicate company and the skip cooldown apply
   - the approach: the one the conversation started with (`earlier`, as 04b
     does for replies), else `pick_approach`
5. `kind_for`: interested reply owed → REPLY; a follow-up due → FOLLOW_UP;
   else FIRST_TOUCH (select still says why when it is none of them).
6. `build` / `redraft` for a follow-up: no research (`Research(level="")`, like
   a reply), `follows` set, the earlier message passed to the drafter. The
   angle is copied from the first message (the interaction's `angle`, part 02),
   not asked of the AI, so the Messages statistics count the follow-up under
   the angle that opened the thread.
7. `AIDrafter`: `SHAPES["follow-up"]` (short; one question; no calendar
   invite, link, slot or price; an easy way out; never "just checking in"
   guilt), `FOLLOWUP_CHANNEL_TEXT` (email: their thread, `Re:` subject allowed;
   LinkedIn: a message in the conversation, `pitch_max_chars`). The prompt
   holds the earlier message (capped at `REPLY_LIMIT`) between data markers,
   as 04b does for their reply. `followup_template()` alongside
   `reply_template()` (or one function with the table name as argument).
8. Checks (`check_text`): the link check covers follow-ups (contradiction 4);
   the opt-out line is added to follow-up emails (contradiction 5; one line in
   `opt_out_line`); one question; the gap check as for a reply.

### Messages, CLI, page

- `default_messages.toml`: `[outreach.follow_up.<lang>]` for en/de/nl/fr with
  `template` (slots `{first}`, `{company}`, `{topic}`, optional `{offer_line}`)
  and `question`; overridable in `messages.toml` as the other tables are.
  English, from the spec, without the brackets: "quick follow-up, no calendar
  invite: is {topic} a priority at {company} right now, or not really? A short
  'not now' is fine too, then I'll close the loop." German in `du`.
- CLI: `--kind follow-up` on `preview` and `build` (the help text says when one
  is due).
- Web: the **Follow-ups** tab (contradiction 12): the due follow-ups with no
  open item, each with a **Draft follow-up** button (`POST /outreach/build`,
  `kind=follow-up`, `contact=…`), and the open follow-up items as cards. The
  build form gets a draft-type select (first touch / follow-up), so a batch of
  follow-ups builds one per request like any batch. `outreach_build` accepts
  `follow-up` without `contact` (today it forces anything but a first touch to
  a first touch unless `contact` is set).
- Contact page: the button picks follow-up from the history (`kind_for`).
- `help/outreach.md`: a Follow-ups section.

### Tests (`tests/test_outreach_followups.py`, fakes from `outreach_fakes.py`)

- a contact whose last touch is an outbound email 5 days old is due; 4 days is
  not; `followup_nudge_days = 3` moves it; the radar and `due_followups` list
  the same contacts on the demo folder
- an open next step with a future due date silences both (radar rule)
- a due follow-up is not excluded by `outreach_cooldown_days`
- a second follow-up is refused with "followed up already"
- a LinkedIn thread is excluded from an email batch, with the reason
- the item has `follows`, no research, the first message's angle, and the
  prompt holds the earlier message as data
- a follow-up with a link, a calendar link, a time slot or two questions
  fails its checks; a follow-up email gets the opt-out line
- templates exist in four languages and fill `{topic}` (the line is not dropped)
- web: the tab lists due follow-ups and their cards; Draft follow-up makes one
  item, one research-free commit plus one draft commit; CSRF refused
- `kind_for` on the contact page: interested reply > follow-up > first touch
- logging the follow-up marks the item sent (`sent_by_interaction`, unchanged)

## 05b · `ai-web` research

### Tool restriction (`enrich.py`)

1. `Provider.web_only`: how a run is held to web search and fetch only, in
   words; `""` = this CLI cannot be. A tools sentinel `WEB_ONLY = "web"` for
   `_run_cli(tools=…)`.
2. `ClaudeProvider.build_argv` with `tools == WEB_ONLY`: `--tools
   WebSearch,WebFetch` (only those exist; `--tools` takes the built-in set
   away, unlike `--allowedTools`), `--allowedTools WebSearch,WebFetch` (no
   approval prompt in `-p`), and `--strict-mcp-config` so no MCP server from the
   user's own config (mail, files, calendars) is loaded into a run that reads
   strangers' pages. Every other provider: `web_only = ""`.
3. `Enricher.web_only_problem()`, worded like `no_tools_problem()`: "codex
   can't be limited to web search only, so ai-web research needs Claude Code:
   set enrich_provider to claude (Settings, AI), or use scrape".
4. An `ai-web` run also gets `cwd=` a new empty temporary directory, so a
   tool that slipped through still sees no data folder.

### `outreach.py`

1. `AiWebResearcher(enricher, fetcher=None, today=None, timeout=10)`, `level =
   "ai-web"`: runs `ScrapeResearcher` first (same fetcher, same proposals),
   then one AI call with `tools=WEB_ONLY`.
2. The prompt holds **public identifiers only**: company name, website,
   company LinkedIn URL, country, the contact's name, title and LinkedIn URL,
   and the scrape findings (already public). Never notes, interaction bodies,
   email addresses or phone numbers: a hostile page could ask the AI to fetch
   an address with whatever is in its context in the URL, so the context holds
   nothing private.
3. `AI_WEB_SCHEMA`: `RESEARCH_SCHEMA` plus `sources` (the URLs read).
   `keep_findings(raw, scrape_sources + answer_sources, today)`: a finding
   whose source is not an `http(s)` URL in that list is dropped, never shown
   as fact (spec test). Open question 7: also fetch each new source once to
   drop invented URLs.
4. `BUILT_LEVELS = LEVELS`; `research_level()` accepts `ai-web`.
   `researcher_for(level, enricher, …)` picks the class, so the CLI and the
   page do not each repeat it.

### CLI, page, settings

- CLI `--research ai-web`; refused in one line with `web_only_problem()`
  before anything runs; the drafter's no-tools check still applies too.
- Build form: a **Research** select (scrape / ai-web), default
  `outreach_research`; `ai-web` disabled with the reason when the CLI cannot
  be restricted. `outreach_build` reads it (today it only calls
  `research_level(config)` as a refusal and always builds `ScrapeResearcher`).
- `datafolder.py`: the `outreach_research` description drops "ai-web comes
  later". `help/outreach.md`: what ai-web reads, what it costs, why only Claude.

### Tests (`tests/test_outreach_aiweb.py`)

- `ClaudeProvider` argv for `WEB_ONLY` has `--tools WebSearch,WebFetch` and
  `--strict-mcp-config`; for `""` it is unchanged (`--tools ""`)
- `web_only_problem()` refuses codex, gemini, grok and custom, passes claude;
  the CLI and the page refuse with that line and run no AI, write nothing
- `AiWebResearcher` with a fake fetcher and fake CLI: scrape runs first;
  the AI call has `tools=WEB_ONLY` and a temporary `cwd`; findings without a
  source, or with a source not in `sources`, are dropped
- the prompt contains no note, interaction body, email address or phone
  number of the demo contact
- an AI error leaves the scrape findings and a note (the batch goes on)
- web: the research select builds an `ai-web` item (`research_level: ai-web`)

## 05c · the critic

### `outreach.py`

1. `CRITIC_SCHEMA`: `relevance`, `personal`, `tone`, `honesty` (integers 1 to
   5) and `reason` (one sentence). `critic_prompt(item-or-draft, brief,
   findings, approach)`: the draft, the usable findings with sources, the
   persona's pains from the playbook, the culture norms; all marked data, not
   instructions. Honesty: a claim of familiarity with nothing in the findings
   behind it scores 1.
2. `Critic` protocol and `AICritic(enricher)`: one call, `tools=""`.
   `CriticResult(scores, reason, model, score)` where `score` is the lowest of
   the four (open question 8).
3. Setting `outreach_critic_threshold`: in `CONFIG_DEFAULTS`,
   `store.DEFAULT_CONFIG` and the `datafolder.py` descriptions; default **2**
   (lenient: only a draft that scores 1 somewhere is regenerated); `0` turns
   the critic off. Config, so no migration.
4. In `build` and `redraft`, after `drafter.draft` and before `_apply_draft`,
   inside the same draft step and commit: critique; below the threshold,
   draft once more with the critic's reason as the problems to fix (a new
   `critique=` argument on `AIDrafter.draft`, passed into `draft_prompt`'s
   `problems`), then critique that one. The second draft is kept (open
   question 9). Skipped for a failed draft and for a fallback with gaps.
5. Item keys `critic` (the four scores), `critic_reason`, `critic_model`,
   after `checks` in `ITEM_KEYS`. A flag "critic: regenerated once (score 1,
   threshold 2)". A critic that fails (an `EnrichError`, no JSON) leaves the
   draft as it is with the flag "critic did not run: …": it never blocks.
6. **Check again** (`save_text`) runs the critic on the edited text when one is
   given (part 04: "from phase 3 also the critic"). Mark ready does not run it.
   Hard rules stay in `check_text` / `clean_answer`; the critic score never
   becomes a check.

### Page and CLI

- The card shows the four scores and the reason next to the checks; the
  Check again button says it also asks the critic (it is an AI call).
- `hermitcrm outreach show` prints the scores; `build` lines add the score.
- `help/outreach.md`: what the critic scores, the setting, why it starts low.

### Tests (`tests/test_outreach_critic.py`, `FakeAI` learns `CRITIC_SCHEMA`)

- a draft below the threshold is regenerated once, with the critic's reason in
  the second prompt, then shown with its scores (spec test); never a third time
- at or above the threshold: one draft call, one critic call
- threshold 0: no critic call
- the critic runs with `tools=""`; a failing critic leaves the draft and the flag
- build is still two commits per item (research, draft); the critic adds none
- Check again with an AI available stores new scores; without one, the hard
  checks run and the card says the critic did not run
- a failing hard check is not hidden by a high critic score

## 05d · the bookmarklet: "Add to research"

### Bookmarklet and capture

1. `static/bookmarklet.js` on a LinkedIn profile adds two pieces: `about` (the
   About section) and `act` (the visible text of the Activity section), each
   cut to a budget so the request head stays under 16 KB with the old pieces;
   `v=3`. Cuts shrink `act` first, then `about`, then `exp`. The file's rules
   (whole-line comments, every statement ends in `;`, no percent sign) hold.
2. `GET /extension/new` (already quiet in `accesslog.QUIET_PATHS`, so the query
   with the profile text does not reach the serve log): when the profile is
   already saved **and** its contact has a `drafted` outreach item, render a
   new `outreach_add.html` instead of the "already in the CRM" redirect: the
   card's name, the pieces read (About, Activity, the top card), each in a
   textarea the person can trim, and an **Add to research** button. Nothing
   is written by the GET. Any other open state (researching, ready) says the
   card cannot take research now; no open item: today's behaviour.
3. `POST /outreach/{id}/page`: CSRF, same-origin (the request guard refuses a
   POST from linkedin.com, which is why the bookmarklet cannot post itself).
   `outreach.add_page(store, item_id, url, text, enricher)`: one AI call with
   no tools, `research_prompt` with that one page, `keep_findings` with the
   profile URL as the only source, kind `person`; the findings are added to the
   item (duplicates by text skipped). One commit, "outreach: findings
   {record}: added N from LinkedIn". The raw page text is never stored: only
   the findings, which the person can remove as any other. Without an AI CLI:
   refused with the reason, nothing written.
4. A finding from the page counts as known for the "cites unknown findings"
   check, so Regenerate uses it (as findings of your own do in 04a).

### Tests (`tests/test_outreach_page.py`, `tests/test_capture.py`, `tests/test_accesslog.py`)

- GET with a saved profile and a drafted item renders the Add page and writes
  nothing (no commit); without an open item it redirects as before; with a
  ready item it says why
- POST without CSRF and a cross-site POST are refused
- POST adds findings sourced to the profile URL, one commit, the item body
  byte for byte unchanged; the raw text is in no file of the data folder
- the AI runs with `tools=""`; a finding not about that page is dropped
- an old v=2 query (no `about`, no `act`) still works
- the bookmarklet: `capture.bookmarklet()` stays one line, has no `%`, and the
  pieces fit the 16 KB budget on a long fixture profile
- `accesslog`: the query of the Add page request is not logged

## Open questions for the maintainer

1. ~~**04b first.**~~ Settled: 04b was merged as PR #112 on 16 October.
2. **Opt-out on follow-ups.** Add the playbook's opt-out line to follow-up
   emails (this plan), or only to first touches as now?
3. **LinkedIn follow-ups.** A follow-up on LinkedIn needs an accepted
   connection, which the CRM does not know. Draft them as conversation
   messages and let the person judge (this plan), or leave LinkedIn out of
   follow-ups in v1?
4. **How many follow-ups.** One per silence (this plan), or a setting
   (`outreach_followups_max`)? Counting is from the CRM's history, so a
   follow-up sent by hand counts too.
5. **Research on follow-ups.** None (this plan: the thread is the context, and
   it keeps the follow-up short and cheap), or a fresh scrape for a new
   trigger?
6. **Item keys and migrations.** Is adding keys to `outreach/` items (as 04b did
   with `reply_to`) exempt from the "new numbered migration" rule, since items
   are not company or contact front matter? If not, one migration per PR that
   adds keys.
7. **Checking `ai-web` sources.** Drop findings whose URL the AI lists but
   does not resolve (one fetch per new source with the existing fetcher;
   LinkedIn URLs skipped, they refuse anonymous requests), or trust the
   `sources` list?
8. **Critic score.** The lowest of the four scores (this plan: a draft that
   invents familiarity is caught even when the rest is fine), or the mean?
   And should a reply to interest be scored on `personal`, when it answers
   what they asked rather than a finding?
9. **After the critic's regeneration.** Keep the second draft always (this
   plan, as the spec reads), or keep whichever has fewer failed hard checks
   and the higher score?
10. **Bookmarklet scope.** Activity is the noisiest part of a profile (other
    people's posts, reactions). Send only posts and comments by the person, or
    leave Activity out and send About only?
