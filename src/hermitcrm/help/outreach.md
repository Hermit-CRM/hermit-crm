# Outreach bot

Picks a batch of contacts, reads what their websites say, drafts a first message per person and checks it; drafts replies to people who answered with interest; you review, send and log. Nothing is ever sent for you.

The outreach bot works from your [playbook](/help/playbook) (`MESSAGING.md`):
what you sell, to whom, and how you write. It will not build anything until at
least one approach in it is filled in (`hermitcrm playbook` says what is
missing). Work with it on the **Outreach** page (in the menu, next to
Messages), on a contact's page (**Research & draft**), or from the command line.

## The Outreach page

- **The bar at the top**: a filter (the Companies page's, conditions separated
  by `;`), the draft type, the channel (required), the research level, the
  batch size and the approach. **Preview** shows who a batch would go to and
  why not the others; nothing is written. **Build queue** researches and
  drafts in the background; the cards appear as they are done.
- **Tabs**: Replies to interest (first: that is where deals are lost), Follow-ups,
  First touches, Ready, Skipped.
- **A card**: the contact (LinkedIn, email), the company (stage, fit,
  website), the flags, the findings with their sources and a confidence dot
  (remove one, or add what you know), the draft (edit it in place), the checks.
  **Check again** saves your edits and runs the checks on them; **Mark ready**
  saves them and approves the draft, also with a failing check (you see a
  warning); **Regenerate** writes a new draft on the same findings (tick
  "stronger model" for the strong one); **Skip** asks why; **Copy** copies the
  subject and the text. A website, LinkedIn URL or country research found for
  an empty field has a **Save to the record** button; nothing is written
  without it.
- **Mark ready** adds the findings the draft used to the contact's notes, under
  a heading such as `### Research 2026-10-16 (scrape)`, one line per finding
  with its source, in the same commit. It logs nothing: you send the message
  yourself and log it as usual.
- **Ready** is your list for sending by hand: Copy, open their mail or
  LinkedIn, send, then log it (that marks the item sent) or press **Mark
  sent** (the state only, nothing logged).

## Replies to interest

When someone answers and wants to know more, the reply should say what you
offer before anything else: people went quiet after getting a booking link
before hearing the offer. The Replies to interest tab lists everyone who
wrote last and has no answer yet.

- A reply logged with the outcome **interested** counts as interest, no AI
  needed. New data folders have that outcome; an older folder gets an **Add
  "interested" to my outcomes** button there (never added without asking).
- **Check replies** asks the AI (no tools) about each reply not checked yet,
  once per reply; the answer is kept in `outreach/replies.yaml`. You confirm
  (**Yes, interest** also sets the reply's outcome to interested) or say **Not
  interest**. **It is interest** works without any AI.
- **Draft a reply**: the approach's offer line, one of its proof lines, its
  first step offer if the playbook has one (`first_step`, for example "The
  first call is free"; left out when empty), and exactly one question. No
  time slot, booking link, price or days per week: you propose a meeting only
  after they answer. It needs no web research; the email subject is "Re:" and
  theirs. Without an AI CLI the reply is the wording template itself.
- The wording per language is `[outreach.reply.<lang>]` in `messages.toml`
  (English, German, Dutch and French ship; slots `{greeting}` `{offer_line}`
  `{proof}` `{first_step}` `{question}` `{signoff}` `{name}`).

## On a contact's page

**Research & draft**, with a channel, drafts one message for that person in the
background. The type is picked from the history (no message yet: a first
touch; they wrote last: a reply to interest; you wrote and nothing came back:
a follow-up, which comes in a later version); change it if it is wrong. While
an item is open for the person, the page links to its card instead.

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
  `bad-fit`; for a first touch, anyone you messaged before.
- **One item per company**, likely duplicates included: the same website
  domain, or names that are the same once `-ai`, `-hq`, `GmbH` and the like are
  dropped. The preview lists such pairs; merge them on the company page.
- **Flags, not exclusions**: no country (English and the default culture are
  used), no headcount, no number of salespeople. The card says what was not
  checked.
- **Which approach**: the one the company fits best (see the playbook). A tie
  takes the first one in the playbook and says so; `--approach NAME` picks.

## Research

`outreach_research = "scrape"` (the only level so far): the company website,
its LinkedIn page and the person's LinkedIn page are read (LinkedIn usually
refuses anonymous requests; the card says so), then one small AI call with no
tools lists the facts on them. Every finding has its source; one without is
dropped. A finding older than about 90 days is marked stale and never opens a
message. Nothing found: the draft uses the playbook's angles and marks gaps
`[like this]`. A website, LinkedIn URL or country found for an empty field is
proposed on the card, never written.

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

The angle is one of the five template angles or `custom`. Drafts use the
medium model; `build --strong` uses the strong one.

**Opt-out line** (optional): set `opt_out` in the playbook's front matter, one
sentence or one per language (`opt_out: {en: "...", de: "..."}`), and a cold
first email gets it added at the end, in the draft's language. It does not
count towards the 120 words. Without it, nothing is added.

## The files

`outreach/<id>.md`, one per item. The front matter holds `state`
(`researching`, `drafted`, `ready`, `sent`, `skipped`; `logged` is for later), the
channel, contact, company, approach, angle, findings, check results, flags,
timestamps, the AI's original text and how much you changed it. The body is
the message, byte for byte. `hermitcrm check` reports a file it cannot read.

Settings in `config.toml`: `outreach_research`, `outreach_cooldown_days`,
`outreach_fit_field`, `outreach_high_fit` (65: the preview counts high-fit
companies never contacted), `outreach_batch_size` (10), `outreach_angles`.
Channel rules and culture norms: `[outreach.<channel>]` and `[culture.<lang>]`
in `messages.toml`, over the shipped defaults.

Related: [Playbook](/help/playbook), [Messages](/help/messages), [CLI](/help/cli)
