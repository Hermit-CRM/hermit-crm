# Outreach bot

Picks a batch of contacts, reads what their websites say, drafts a first message per person and checks it, answers replies that show interest and follows up on messages nobody answered; you review, send and log. Nothing is ever sent for you.

The outreach bot works from your [playbook](/help/playbook) (`MESSAGING.md`):
what you sell, to whom, and how you write. It will not build anything until at
least one approach in it is filled in (`hermitcrm playbook` says what is
missing). It runs on the **Outreach** page (in the menu, next to Messages)
and from the command line; both do the same steps and write the same files.

## On the Outreach page

- **Who**, **Draft type**, **Channel**, **Batch size**, **Approach**: the filter (conditions
  separated by `;`, for example `stage=prospect; country=DE`), a first touch or a
  follow-up, email or LinkedIn, how many, and which playbook approach to use. Left on "the best fit per
  company" it picks one per company, as the command line does without
  `--approach`.
  **Preview** shows who would get a draft and why not the others; no AI runs
  and nothing is written. **Build queue** researches and drafts them one at a
  time: each card appears when it is done and the page asks for the next one
  by itself. **Stop** ends the batch; what was built stays.
- **Tabs**: Replies to interest (first: that is where deals leak), Follow-ups,
  Drafts (first touches to review), Ready (to send), Sent, Skipped.
- **A card**: the person and company with their links, fit, flags, what
  research found (with source and a confidence dot), the draft and its checks.
  - **Save & check again** saves your edit and runs the checks on it. A check
    that fails never blocks you.
  - **Mark ready** approves the text as it is in the box (your edit and the
    approval are one change). A failing check stays on the card as a warning.
  - **Regenerate** writes a new draft from the same findings, optionally with
    the stronger model. Remove a finding or **add your own** first to steer it;
    one you add counts as a known fact.
  - **Skip** with a reason; **Copy** copies the message.
  - **Save to the record** shows when research found a website, LinkedIn URL or
    country for a field that is empty; it writes that one value and nothing else.
  - On a ready card: **Copy**, open your mail or LinkedIn, **Log it** (logging
    the message marks the item sent), or **Mark sent** without logging.
- **On a contact's page**: **Research & draft** builds one item for that
  person on the channel you pick (it says why when the person is left out),
  and while an item is open the page links to its card. The draft type comes
  from the history: someone who replied with interest gets **Draft a reply**
  (a reply to interest), everyone else a first touch; you can change it.

## Replies to interest

Someone answered and wants to know more. The tab lists every reply you owe an
answer (the follow-up radar's "you owe a reply", per person, from the day it
came in) and what is known about it:

- **Logged with the outcome `interested`**: listed as it is, no AI needed.
  Set the outcome when you log the reply (Settings > Outcomes offers the
  value to a folder that set its own list before it existed).
- **Otherwise, Check replies** asks your AI CLI, with no tools and no web,
  once per reply: interested, not interested or unclear. The answer is kept in
  `outreach/replies.json` (one commit) and never changes the interaction. An
  "interested" from the AI waits for you: **Confirm: interested** or **Not
  interested**. You can also mark any reply yourself.
- **Draft a reply** on an interested reply builds a reply-to-interest draft:
  no research, their reply is the context. It says the approach's offer line,
  one proof line, the playbook's **first step offer** (`first_step_offer`,
  left out when empty: not everyone offers a free first call) and asks one
  question. No time slot, booking link, link or price: a meeting comes after
  they answer. The wording template per language is
  `[outreach.reply_to_interest.<lang>]` in `messages.toml`.

The card shows their reply above the draft; Regenerate, Skip, Mark ready and
the rest work as on a first touch. Once you send and log your answer, the
reply leaves the list.

## Follow-ups

A message of yours that nobody answered. It is due on the follow-up radar's
rule: your latest message to that person has gone `followup_nudge_days` (5,
Settings) without an answer and nothing is planned for the company. The bot and
the radar read the same setting, so they never disagree.

- The **Follow-ups** tab lists who is due (oldest first) with **Draft follow-up**;
  a batch of them builds from the bar (**Draft type**: follow-up) or with
  `hermitcrm outreach build --kind follow-up`. On a contact's page the button
  says **Draft a follow-up** when one is due.
- No research: the thread is the context, and your earlier message goes to the
  AI as data. The draft is short, has no calendar invite, link, time slot or
  price, asks one question and gives an easy way out ("a short 'not now' is
  fine, then I'll close the loop"). The wording template is
  `[outreach.follow_up.<lang>]` in `messages.toml`; `{offer_line}` is an
  optional line it leaves out by default.
- The message's angle is the first message's, not the AI's, so Messages
  statistics count the follow-up under the angle that opened the thread.
- **Who is left out**: someone whose unanswered message was on another channel
  than the batch's (or on a call or in a meeting: write that one yourself);
  someone you already followed up with once (two messages of yours since they
  last wrote: close the loop); the usual do-not-contact, closed stage and open
  item. The 30-day cooldown does not apply to a follow-up: it is due after 5.
- A cold follow-up email gets the playbook's opt-out line, as a first touch does.
  A LinkedIn follow-up is a message in the conversation, so it only works if they
  accepted your connection; the bot cannot know that.

## The steps

1. **Preview**: who a batch would go to, and why not the others. No AI, nothing
   written.

   ```text
   hermitcrm outreach preview --where 'stage=prospect' --channel email --limit 10
   ```

2. **Build**: for each contact in the batch, research, then a draft, then the
   checks. Each item is a file in `outreach/`; each step is one commit, so
   `hermitcrm undo` takes any of it back.

   ```text
   hermitcrm outreach build --where 'stage=prospect' --channel email --limit 10
   ```

3. **Review**: `hermitcrm outreach list`, then `hermitcrm outreach show <id>`
   for the card: the contact and company links, what research found and where,
   the flags, the culture norms used, the checks, and the draft. Edit the draft
   in the file if you want: the text below the second `---` is the message.

4. **Ready or skip**: `hermitcrm outreach ready <id>` approves it. The checks
   run again on your edited text; one that still fails is a warning, kept on
   the item, and the choice is yours. Ready adds the findings the message used
   to the contact as a note. `hermitcrm outreach skip <id> --reason R [--note
   "..."]` drops it, R one of `bad-fit`, `wrong-person`, `bad-timing`,
   `bad-draft`, `already-in-contact`, `other`. A skipped person comes back in
   batches after the cooldown; `bad-fit` keeps their company out.

5. **Send and log** it yourself, as you always do (by hand, BCC or the
   extension). The bot does neither. Logging the message on the item's channel
   after you marked it ready marks the item **sent** (and gives the logged
   message the item's angle); `hermitcrm outreach sent <id>` does the same
   without logging anything.

## Who gets picked

- **The filter** is the Companies page's (`stage=prospect`, `country=DE,NL`,
  `fit_score=>60`, `tags=saas`). A contact key works too (`contact.title=CEO`).
  Or name people outright: `--contact acme/jane-doe`.
- **Order**: highest fit first, by the company field `outreach_fit_field`
  (default `fit_score`, 0 to 100). A company without one comes last, with "no
  fit score" on its card; the bot never makes one up. Within a company, someone
  the playbook has a persona for goes first.
- **Left out**, with the reason in the preview: a company in a closed or parked
  stage; anything tagged `do-not-contact`; a company an approach's disqualifier
  hits or that misses every approach's ideal customer; a contact the channel
  cannot reach (email needs an address, LinkedIn a profile URL); a contact with
  an open item (researching, drafted or ready); a contact you messaged or
  skipped in the last `outreach_cooldown_days` (30); a company skipped as
  `bad-fit`; for a first touch, anyone you messaged before. A reply to
  interest needs an interested reply owed, and skips the cooldown and the fit
  test: they asked (the approach is the one the conversation started with).
- **One item per company**, likely duplicates included: the same website
  domain, or names that are the same once `-ai`, `-hq`, `GmbH` and the like are
  dropped. The preview lists such pairs; merge them on the company page.
- **Flags, not exclusions**: no country (English and the default culture are
  used), no headcount, no number of salespeople. The card says what was not
  checked.
- **Which approach**: the one the company fits best (see the playbook). A tie
  takes the first one in the playbook and says so; `--approach NAME` picks.

## Research

Two levels, `outreach_research` in `config.toml` (default `scrape`), or the
**Research** select on the Outreach page and `--research` on the command line.

**`scrape`** (free): the company website, its LinkedIn page and the person's
LinkedIn page are read (LinkedIn usually refuses anonymous requests; the card
says so), then one small AI call with no tools lists the facts on them. Every
finding has its source; one without is dropped. A finding older than about 90
days is marked stale and never opens a message. Nothing found: the draft uses
the playbook's angles and marks gaps `[like this]`. A website, LinkedIn URL or
country found for an empty field is proposed on the card (a **Save to the
record** button), never written without it.

**`ai-web`** (AI tokens): the scrape first, then one more AI run that may search
the web and read pages, for what the company's own pages do not say: recent news,
a hire, a launch, something the person said. Only Claude Code can be held to
that (web search and fetch only, no files, no shell, no MCP servers, run in an
empty temporary folder); with any other AI CLI the level is refused with the
reason, and you use `scrape`. What the run is told is public only: the company
name, website, country, LinkedIn pages, the person's name and title, and what the
scrape found. Never your notes, messages, email addresses or phone numbers, since
a page written by a stranger could try to make the run repeat what it knows. A
finding stays only if it names a page the run listed as read, that page is an
http(s) address, and it can be read again (LinkedIn is taken as listed); the rest
are dropped, never shown as fact. If the run fails, the scrape findings stand and
the card says why.

## The draft and its checks

A first touch opens with something about them (never "I"), says the offer in
one line, and ends with exactly one question about their situation: no meeting
ask, no link, no time slot. It is written in the contact's draft language,
otherwise the company's country's, with the culture norms of `[culture.<lang>]`
in `messages.toml` (German first contact uses `du`); your playbook's Voice wins
over them.

The checks are rules, not AI: exactly one question (a LinkedIn connection note
may ask none); not opening with I, Ich, Ik or Je; no calendar link or proposed
time; the channel's length (email: subject 60 characters, 120 words; LinkedIn:
a 300-character connection note and a 600-character message for after they
accept); only findings and proof lines that exist; no `[ ]` gap. A draft that
breaks one is written again once; if it still breaks it, it is shown with the
problem marked. Only a fallback draft, written when research found nothing
usable, keeps its gaps: it says "needs hand edits".

A reply to interest is checked for the offer line (it must be there word for
word), one proof line, exactly one question, and no link, time, price or day
rate (`€900`, `2 days a week`); on LinkedIn it is a message of up to 600
characters, not a connection note.

The angle is one of the five template angles or `custom` (a reply has none).
Drafts use the
medium model; `build --strong` uses the strong one.

**Opt-out line** (optional): set `opt_out` in the playbook's front matter, one
sentence or one per language (`opt_out: {en: "...", de: "..."}`), and a cold
first email gets it added at the end, in the draft's language. It does not
count towards the 120 words. Without it, nothing is added.

## The files

`outreach/<id>.md`, one per item. The front matter holds `state`
(`researching`, `drafted`, `ready`, `sent`, `skipped`; `logged` is for later), the
channel, contact, company, the reply it answers (`reply_to`) or the message it
follows up (`follows`), approach, angle,
findings, check results, flags,
timestamps, the AI's original text and how much you changed it. The body is
the message, byte for byte. `hermitcrm check` reports a file it cannot read.

Settings in `config.toml`: `outreach_research` (`scrape` or `ai-web`), `outreach_cooldown_days`,
`outreach_fit_field`, `outreach_high_fit` (65: the preview counts high-fit
companies never contacted), `outreach_batch_size` (10), `outreach_angles`.
Channel rules and culture norms: `[outreach.<channel>]` and `[culture.<lang>]`
in `messages.toml`, over the shipped defaults.

Related: [Playbook](/help/playbook), [Messages](/help/messages), [CLI](/help/cli)
