# Part 08 · Send from the app: scheduled email, paced LinkedIn (MVP)

Context: [00-overview](00-overview.md), [03-draft-check-store](03-draft-check-store.md),
[07-auto-later](07-auto-later.md). Written 18 Oct 2026. **Status: approved on 18 Oct 2026 with the
decisions under "Decisions" below; built on branch `ai/outreach-send`** (plan:
`docs/superpowers/plans/2026-10-18-outreach-send.md`).

This part fills the `[send] ──> [log]` end of the pipeline for the
semi-automatic case: the person still approves every message, and the app then
sends approved email on a spaced schedule and paces LinkedIn. Part 07's full
auto (sending without a per-message approval) stays later and builds on this.

## Why

Today an approved item sits on the Ready tab; the person copies it into their
mail or LinkedIn and BCC import logs it afterwards. That works at five a day
and breaks at fifty: copy and paste is slow, and the sends come in bursts (a
batch of twenty in ten minutes), which is the pattern mailbox providers and
LinkedIn read as automation. The aim is **50-100 approved touches a day**,
spread over the working day, logged once, with no new risk to the sending
domain or the LinkedIn account.

## Goals

1. **Send an approved email** from the Outreach page: now, or on a schedule.
   Logged once, threaded with earlier mail, the text exactly as approved.
2. **Spacing:** a daily plan spreads queued email over a sending window with
   jitter, a daily cap, a warm-up ramp and per-company spacing. Every queued
   item shows when it goes out.
3. **LinkedIn:** a paced session that puts one approved touch in front of the
   person at a time, under daily and weekly caps, and logs it on "Sent".
4. **Safety:** a kill switch; auto-pause on an auth failure, a quota error or a
   bounce spike; no double sends; no burst when the Mac wakes up.

## Non-goals (MVP)

- Open or click tracking, HTML mail, links in a first touch. A tracking pixel
  sits badly with a tool whose pitch is that you own your data (TODO.md).
- Automatic multi-step sequences. A follow-up is still drafted and approved as
  its own item (part 05); it can then be scheduled like any other.
- More than one sending mailbox, or rotation between mailboxes.
- Non-Gmail SMTP verified end to end (it should work; only Gmail and Google
  Workspace get tested). Microsoft 365 / Outlook.com: not supported, as on the
  BCC page (Microsoft switched off password sign-in).
- Full auto (part 07, phase 6) and per-recipient time zones (the window is in
  the sender's time zone).
- Sending from the MCP server or by an agent on its own.

## Anti-goals (a failure even if it works)

- The sending domain lands in spam, or the LinkedIn account is restricted.
- A message goes out that differs from what the person approved, or goes out
  twice.
- The Mac wakes after a night and sends thirty overdue emails in a minute.
- An agent schedules or sends mail the person did not approve.

## Facts this rests on (checked 18 Oct 2026)

| Topic | Fact | Source |
|---|---|---|
| Gmail / Workspace SMTP | `smtp.gmail.com`, 587 STARTTLS or 465 SSL, the full address as user, a 16-character app password. App passwords need 2-Step Verification, a Workspace admin can switch them off, and changing the account password revokes them. Google calls them "not recommended" but still supports them. | Google Account Help 185833 |
| Gmail quota | Workspace: 2,000 messages per user per rolling 24 h (500 on a trial). Free Gmail: about 500. SMTP: at most 100 recipients per message. | Google Workspace Admin Help, "Gmail sending limits" |
| Deliverability | For cold email the ceiling is reputation, not quota. Common practice is about 30-50 cold emails per mailbox per day after a 2-4 week ramp, plain text, no links, SPF/DKIM/DMARC aligned. | practitioner consensus, not a Google figure |
| Sent copies | Gmail files mail sent over `smtp.gmail.com` in Sent by itself; most other providers need an IMAP `APPEND`. **Confirm in M1.** | |
| LinkedIn rules | User Agreement 8.2 forbids "unauthorized automated methods" to send messages; the help centre names bots, browser plug-ins and extensions. The consequence is restriction or closure of the account. | LinkedIn Help a1341387 |
| LinkedIn invites | No published cap. Estimates: about 100 invites per rolling 7 days, 15-25 a day, connection note ≤ 300 characters. Messages to first-degree connections have no published cap. | vendor sources; they disagree |
| EU law | Germany (UWG §7(2) no. 2) and Austria (TKG §174) require prior consent for advertising email, B2B included; an opt-out line does not cure it. UK and NL are looser for B2B. **Not legal advice.** | |

## What already exists and gets reused

| Piece | Reused for |
|---|---|
| `Sender` / `Logger` protocols and `SendResult` in `outreach.py` | `SmtpSender` and an `OutreachLogger` behind the same interfaces; `ManualSender` stays the default |
| `sent_by_interaction` | Flips the item to `sent` when its outbound interaction is logged; extended to `queued` items |
| `Store.create_interaction(..., source, message_id)` | Logging the sent mail; BCC import never imports the same Message-ID twice, so no double log |
| `secrets.py` (environment, `.secrets.toml`, Keychain / Secret Service) | New secret `send_password` |
| `bcc.py` IMAP code and its provider table | Reply guard, bounce scan and the Sent-folder check on the sending mailbox; the SMTP host presets |
| `/settings/bcc/test` | Pattern for `/settings/send/test` |
| `schedule.py` jobs (`StartInterval`, like the backup job) | New job `io.hermitcrm.send` |
| `clean_answer` and `[outreach.email]` / `[outreach.linkedin]` rules | The checks run again right before a send |
| `follows` / `reply_to` on items and the kept "Re:" subject | `In-Reply-To` / `References` headers |
| Outreach page tabs, cards, form tokens | Scheduled tab, LinkedIn session, status strip |

## The flow

```
                      ┌──────────── Send now (replies to interest, one-offs) ───────────┐
                      │                                                                  v
 ready ──> Schedule ──┴──> queued ──> worker tick ──> guards ──> SMTP ──> log ──> sent
            planner         send_at    launchd,        fail:      message_id   interaction,
            spreads         shown      every 3 min     hold/pause written first  source: outreach

 ready (LinkedIn) ──> session card ──> person sends on linkedin.com ──> "Sent" ──> log ──> sent
```

### States

```
ready ──> queued ──> sent
  ^         │  \
  └─────────┘   └──> failed ──(Retry)──> ready
  Unschedule, an edit, or a guard
  that holds it (they replied)
```

- `queued`: approved and scheduled. `send_at` says when; the planner may move
  it. An open state, like `ready`.
- `failed`: a permanent error (address unknown, refused). Retry puts it back
  to `ready`.
- A guard that holds an item (they wrote to you since it was approved, the
  deal moved to won or lost) puts it back to `ready` with a `send_note` that
  says why. The person decides; nothing is silently dropped.

New item keys, written in `ITEM_KEYS` order: `queued`, `send_at`,
`send_hash` (a hash of subject and body at Schedule time), `message_id`,
`send_tries`, `send_error`, `send_note`, and for LinkedIn `invite_sent`,
`accepted`, `pitch_sent`. A numbered migration adds them empty
to existing `outreach/` files, and the new interaction `source` value
`outreach` gets the no-op migration part 07 asks for, plus tests.

## Email

### SmtpSender

- Standard library only: `smtplib` and `email.message.EmailMessage`. No new
  runtime dependency.
- Plain text, UTF-8. From: `owner_name <send_from>`. No BCC, no HTML, no
  tracking, no `List-Unsubscribe` header (it is a bulk-sender requirement and
  makes a one-to-one mail look like a newsletter).
- `Message-ID` from `email.utils.make_msgid(domain=<sending domain>)`. It is
  written on the item and **committed before** the SMTP call, which is what
  makes a crash recoverable without a double send (see Errors).
- A follow-up or reply gets `In-Reply-To` and `References` from the earlier
  interaction's `message_id`, and keeps its "Re:" subject (already built).
- The opt-out line from the playbook goes under a cold first touch when the
  playbook has one. It is optional (decided 19 Oct): without it nothing is added
  and nothing is checked; with it, scheduling a first touch from which it was
  edited out is held, and Send now warns but allows it.
- Settings → Sending: provider preset (Gmail / Google Workspace by default;
  iCloud and Fastmail listed as untested), from address (one of
  `my_addresses`), SMTP user, app password (stored through `secrets.py`, the
  Keychain on macOS, never in `config.toml`), and **Send a test to myself**,
  which shows the server's exact reply on failure.

### Planner (the spacing)

A pure function, `plan(queue, recent_sends, now, config) -> {item_id: send_at}`.
It is deterministic (the jitter is seeded by the item id), so the tests, the
page and the worker all agree on the times.

1. **Window:** `send_days` and `send_window` (default Mon-Fri 08:30-17:30) in
   the sender's time zone.
2. **Daily cap:** `send_ramp` gives the cap for weeks 1, 2, 3... counted from
   the first send (default `[10, 20, 30, 40]`), then `send_daily_cap`
   (default **50**, a setting). More than 150 a day for more than 1-2 days in
   a row is strongly discouraged: a cap above 150 is held at 150 once the two
   previous send-days both went over it. The first send and today's count both
   come from the interactions with `source: outreach` (the local calendar day),
   so nothing extra is stored. Mail the person sends from Gmail directly does
   not count.
3. **Gap:** base = window length / today's cap; each gap = base × a seeded
   factor between 0.6 and 1.4, never below `send_min_gap_minutes` (3). At 50 a
   day over 9 hours that is about 11 ± 4 minutes; at 10 a day about 54 ± 20.
4. **Company spread:** two items for the same company (or the same email
   domain) at least `send_company_gap_hours` apart (default 24, so the next
   working day).
5. **Earliest slot:** now + `send_grace_minutes` (10), so a mistaken Schedule
   can still be undone.
6. **Order:** follow-ups that are due first, then first touches in the order
   they were queued.
7. **Re-plan** the whole queue when it changes (schedule, unschedule, pause,
   resume) and when the worker finds an item overdue by more than
   `send_overdue_minutes` (20). Overdue items move to the next free slots;
   they are never sent in a burst. A re-plan rewrites the changed `send_at`
   values in one commit.

**Send now** skips the queue: it ignores the window and the gap (a reply to
interest should not wait for a slot), but it counts toward today's cap and is
refused while sending is paused or the cap is reached. It runs the same guards
and the same send-and-log steps as the worker.

Example: 50 items queued on a Monday at 08:00 with a daily cap of 35: 35 go
out Monday between about 08:40 and 17:20, and 15 on Tuesday from about 08:35.

### Worker

`hermitcrm send due`, run every 3 minutes by a launchd job (systemd timer on
Linux). Settings → Sending → **Turn on scheduled sending** installs it
(`schedule install --send` from the CLI), and turning it off removes it. Each
tick:

1. Stop if sending is off or paused. Take a non-blocking lock
   (`<data>/.send.lock`); if another tick holds it, stop.
2. Re-plan if anything is overdue.
3. Take the first item with `send_at <= now`. At most one per tick
   (`send_max_per_tick = 1`).
4. Run the guards (below). If one fails, act on it and stop.
5. Write `message_id` and `send_tries + 1` on the item. Commit.
6. Send over SMTP.
7. Log the outbound interaction (channel email, `source: outreach`, the body
   byte for byte as sent, angle, approach, `message_id`); the item becomes
   `sent` in the same commit.
8. On an error, classify it (Errors).

Why a separate job and not a thread inside `serve`: sending keeps going when
the web app is closed or restarts, it is plain deterministic Python with no
AI anywhere on the path, it follows the existing sync and backup pattern, and
it can be run and tested from the CLI with `--dry-run`.

The Mac has to be awake during the window: launchd does not run jobs while the
Mac sleeps and fires once on wake, which is why step 2 re-plans and never
catches up in a burst. `doctor` reads `pmset -g` and warns when the Mac sleeps
on power (it never changes the setting).

### Guards (before every send)

- Sending on, not paused, inside the window, under today's cap, the last send
  at least the minimum gap ago.
- The item is still `queued` and its text hash equals the approved text. An
  edit on the page unschedules it; this also catches a hand edit to the file.
- The contact still has an email address, the address is not on the
  suppression list, and the company is not won, lost or disqualified.
- **Reply guard:** no inbound interaction from anyone at the company since the
  item was marked ready, and an IMAP search of the sending mailbox (`FROM`
  the contact, `SINCE` the ready date) finds nothing. Otherwise the item goes
  back to `ready` with "they wrote to you on <date>". The IMAP login happens
  only when an item is about to go out, not on every tick, and uses the same
  app password as SMTP (one app password covers both at Google).
- The channel's hard checks (`clean_answer`) still pass, and, when the playbook
  has an opt-out line, a cold first touch carries it.
- **Country guard:** a company whose country is in
  `send_email_block_countries` is never scheduled or sent by email; the card
  suggests LinkedIn. App default: empty. Each folder decides.

### Errors

| Kind | Example | What happens |
|---|---|---|
| Auth | `535 5.7.8` bad credentials, app password revoked | Pause all sending; a red banner on every page with the server's own text; `doctor` shows it. Nothing retries until a new Test passes. Fail fast and show the real error: never a silent retry loop. |
| Quota | `550 5.4.5` daily sending quota exceeded | Pause until the next window, then re-plan |
| Temporary | 421, 450, 451, a timeout, no network | `send_at` + 15 min, up to 3 tries, then `failed` |
| Recipient | `550 5.1.1` user unknown | `failed`; the address goes on the suppression list as bounced |
| Crash between SMTP and log | the process is killed | The next tick finds a `queued` item that already has a `message_id`. It searches Sent (the `\Sent` special-use folder) for that Message-ID: found, log it as sent; not found, send again with the same Message-ID |

### Bounces and opt-outs (M3)

- Every tick (at most every 30 minutes), search the sending mailbox for
  delivery reports since the last scan (`multipart/report`, from
  mailer-daemon or postmaster). Read `Final-Recipient` and the original
  Message-ID: the address goes on the suppression list (`bounced`), a note goes
  on the contact's timeline, and the item is flagged.
- More than 3 bounces in the last 50 sends, or over 5 %, pauses sending with
  a banner that says it is a list-quality problem.
- **Suppression list:** `outreach/suppressed.toml` holds the address, reason
  (`bounced`, `opted-out`, `manual`), date and item. It is a new file, not
  front matter, so it needs no migration, and it is committed like everything
  else. The planner never schedules a suppressed address and the worker never
  sends to one.
- An **Opted out** button on an inbound reply and on the contact page adds the
  address and unschedules everything open for that contact.

## LinkedIn

### The choice (decision needed)

The plan builds **A**. **C** can be added later behind the same `Sender`
protocol, but never in the public repo.

| | A. Paced session, the person clicks Send (recommended) | C. A browser bot sends (Playwright) |
|---|---|---|
| LinkedIn's rules | Within them: a person sends every message | Breaks 8.2; risk of a restricted or closed account |
| Spacing | Enforced by the session: a countdown between cards, caps | Scheduled like email |
| The person's time | About 30-40 s per touch: 50 touches ≈ 30 min a day in 3-4 sessions | About none |
| Fragility | None: it opens a URL and copies text | Breaks when LinkedIn changes its pages; a checkpoint or CAPTCHA has to stop it (it must stop, never solve one) |
| Where it lives | Hermit, public | A private plugin outside this repo |
| Volume ceiling | About 20 invites a day (about 100 a week): LinkedIn's limit, whatever the method | The same |

A middle way (an extension fills LinkedIn's message box, the person clicks
Send) saves only the paste, and the help centre names extensions explicitly.
It is not worth the grey zone.

### The session (A)

- Outreach page → LinkedIn → **Start session**. The queue is the ready
  LinkedIn items: connection notes first, then pitches to people who accepted.
- Counters at the top: invites today 0/20, the last 7 days 34/80, messages
  today 0/40, this session 0/10.
- One card at a time: name, title, company, the note (≤ 300 characters) or
  pitch (≤ 600) with its count. **Open profile & copy** copies the text (the
  clipboard API works on localhost, a secure context) and opens the contact's
  LinkedIn URL in a new tab. The person clicks Connect → Add a note → pastes →
  Send.
- Back on the card:
  - **Sent** logs an outbound LinkedIn interaction with the exact text;
    `invite_sent` or `pitch_sent` is set.
  - **Already connected** switches the card to the pitch.
  - **Couldn't send** asks for a reason (profile gone, other). LinkedIn's
    weekly-limit message pauses invites until the 7-day count drops.
- The next card unlocks after a seeded 45-120 s countdown. After the session
  size (10) the page says when the next session can start (at least 2 hours
  later).
- The item becomes `sent` with its first message out (the note, or the pitch
  to someone already connected), so cooldowns and the Messages statistics
  work as today. `accepted` and `pitch_sent` track the second step on the
  same item.
- Sent invites wait under **Waiting to accept**; **Accepted** puts the
  item's pitch in the session queue. An invite pending for more than 21 days
  gets a "withdraw it?" reminder: many pending invites count against the
  account.
- Realistic volume: about 20 invites and 30-40 messages to existing
  connections a day. 50-100 invites a day is not available by any method.

## Pages, CLI, MCP

- **Outreach page, top strip:** "Email: on · 23/35 today · next 10:42 ·
  Mon-Fri 08:30-17:30 · [Pause]" and "LinkedIn: invites 12/20 today ·
  61/80 this week". Pause is the kill switch: one click, effective from the
  next tick.
- **Ready tab:** Send now (email; meant for replies to interest and
  one-offs, which should not wait in a cold-email queue), Schedule, and
  Schedule all ready email, which shows the proposed times first, then asks
  to confirm.
- **Scheduled tab (new):** time, contact, subject; Unschedule, Send now, Move
  to front. A queued card says "goes out Tue 20 Oct, 09:47".
- Every new POST route takes the form token (unlike the 70 older routes in
  TODO.md).
- **Settings → Sending:** provider, from address, user, app password, Test,
  window, days, cap, ramp, country guard, scheduled sending on/off.
- **CLI:** `hermitcrm send test | status | due [--dry-run] | pause | resume`,
  `hermitcrm outreach schedule <id>... | --all-ready [--dry-run]`,
  `outreach unschedule <id>`, `outreach send-now <id>`,
  `schedule install --send`.
- **doctor:** the credentials log in (no mail sent), the job is installed,
  nothing overdue, Mac sleep on power.
- **MCP:** `outreach_list` may show queued items. No MCP tool schedules or
  sends. The data folder's `AGENTS.md` (written by `datafolder.py`) says an
  agent never schedules or sends unless the person asks in that conversation.
  The real limit on the damage is the cap and the window: an agent with a
  shell can do whatever the person can.
- **Help:** a new `hermitcrm help sending` page covering setup, the ramp,
  pausing, and why LinkedIn is not automated.

## Config keys (defaults)

| Key | Default | Meaning |
|---|---|---|
| `send_enabled` | `false` | Master switch; Send now and Schedule are hidden while off |
| `send_paused` | `false` | The kill switch (Pause button) |
| `send_from` | `owner_email` | Sending address |
| `send_smtp_host` / `send_smtp_port` / `send_smtp_user` | `smtp.gmail.com` / `587` / `send_from` | SMTP |
| `send_imap_host` | `imap.gmail.com` | Reply guard, bounce scan, the Sent check (same user and password) |
| secret `send_password` | | App password (Keychain) |
| `send_window` / `send_days` | `"08:30-17:30"` / Mon-Fri | Sending window, local time |
| `send_ramp` | `[10, 20, 30, 40]` | Cap per week from the first send |
| `send_daily_cap` | `50` | Cap after the ramp; a third day in a row over 150 is held at 150 |
| `send_min_gap_minutes` | `3` | Floor between two sends |
| `send_company_gap_hours` | `24` | Two contacts at one company |
| `send_grace_minutes` | `10` | Earliest slot after Schedule |
| `send_overdue_minutes` | `20` | Beyond this an item is re-planned, not sent |
| `send_email_block_countries` | `[]` | Country guard (ISO codes) |
| `linkedin_invites_per_day` / `_per_week` | `20` / `80` | Invite caps (rolling 7 days) |
| `linkedin_messages_per_day` | `40` | Messages to connections |
| `linkedin_session_size` | `10` | Cards per session |
| `linkedin_gap_seconds` | `[45, 120]` | Countdown between cards |
| `linkedin_session_break_minutes` | `120` | Between sessions |

## Milestones

M1 → M2 → M3 in order: they share `outreach.py`, the new `send.py` and the
Outreach page. M4 needs M1's logging only, but it touches the same page and
template, so it goes after M3 or in its own worktree with care at merge.
Sizes are rough, in days of AI-assisted work.

### M0 · Setup (the person, about 30 minutes, before M1 ships)

- 2-Step Verification on the sending account; in Google Workspace, the admin
  allows app passwords; create one named "Hermit CRM".
- SPF, DKIM and DMARC on the sending domain (a DMARC record with `p=none` is
  enough at this volume).
- Optionally, an opt-out line per language in the playbook (`MESSAGING.md`).
- A decision on the country guard (see Open questions).
- Energy settings: the Mac does not sleep on power during the window.

### M1 · Send one email (about 1 day)

**Done when:** the person sends a real email from the Ready tab; it appears in
Gmail's Sent, it is logged once (a later BCC import of the same mail adds
nothing), a follow-up threads under the first mail, and Test reports a wrong
password with Google's own error text.

`SmtpSender`, Settings → Sending, Send a test to myself, `send_password`
secret, Send now, `OutreachLogger` (`source: outreach`, migration), threading
headers, `send test` / `outreach send-now` CLI.

Tests: the message as built (headers, plain text, Message-ID on the sending
domain, opt-out line under a cold first touch only); `In-Reply-To` and
`References` from the earlier interaction; the SMTP class is a test double
and no test touches the network; a 535 shows the server's text; the logged
interaction has the Message-ID and BCC import skips it; the migration is
idempotent; `ManualSender` stays the default.

### M2 · Schedule and spacing (about 2 days)

**Done when:** 20 items scheduled in the morning go out across the day at the
times the page showed; Pause stops sending within one tick; a reply from the
contact holds their queued item; a Mac asleep for two hours resumes with
spacing, without a burst.

`queued` state and keys, planner, `send due` worker, guards, error handling,
the crash-recovery check in Sent, Scheduled tab, status strip, Pause, launchd
and systemd job, `doctor` checks, help page.

Tests: the planner with a fixed clock (window, days, cap, ramp, jitter range,
the gap floor, company spread, grace, order; the same input gives the same
times); overdue re-planning; one send per tick; every guard; every error
class; crash between SMTP and log (found in Sent, and not found); a lock held
by another tick; an edit unschedules; the job files written under
`HERMITCRM_DRY_SCHEDULE=1`.

### M3 · Bounces, opt-outs, suppression (about 1 day)

**Done when:** a bounced address is suppressed and never mailed again, a bounce
spike pauses sending with a banner, and Opted out unschedules everything for
that contact.

Tests: delivery reports from Gmail and a generic MTA (fixtures); the bounce-
rate pause; the suppression list in the planner and in the worker;
`suppressed.toml` written deterministically and committed.

### M4 · LinkedIn session (about 1.5 days)

**Done when:** a 10-card session runs end to end in about 10 minutes, every
Sent is logged with its exact text, the caps and the countdown hold, and
Accepted brings the pitch into the queue.

Tests: the caps (day, rolling 7 days, messages, session); a seeded countdown;
Sent / Already connected / Couldn't send; Accepted → pitch; the 21-day
pending reminder; no network call anywhere on the path.

### M5 · Only if C is chosen: a private LinkedIn sender

Outside this repo, behind the `Sender` protocol, with lower caps than A (at
most 15 invites and 30 messages a day), working hours only, and a hard stop
on any checkpoint or CAPTCHA. Its own spec.

## Rollout for the first user

- Build on a branch off `main` with `send_enabled = false` as the default.
  When to merge is the maintainer's call; after the public launch week
  (19-27 Oct) is the low-risk option.
- Week 1: ramp cap 10. Send a test to an inbox on another provider and check
  it does not land in spam. Read replies and bounces daily.
- Weeks 2-4: 20 → 30 → 40, then 50. The sending mailbox is a separate one on
  its own domain from the start (decision 3), which protects the main domain's
  reputation. 50 a day is at the top of the 30-50 that practitioners suggest for
  one cold mailbox: if replies fall or bounces rise, lower `send_ramp` and
  `send_daily_cap` before anything else. Past 50, raise the cap in steps; a second
  mailbox is the later multi-mailbox item.
- **The bottleneck moves upstream.** 50 sends a day needs about 50 approved
  items a day. On the first real batch (17 Oct) a draft took about 2 minutes
  of model time, so 50 is about 100 minutes in the background plus about a
  minute of review each. Build the queue the evening before.

## Risks

| Risk | Mitigation |
|---|---|
| Domain reputation | Ramp, cap, plain text, no links, company spread, bounce pause, a second mailbox past ~50 a day |
| LinkedIn account | Option A; caps under the estimated limits; a pending-invite reminder |
| DE/AT email law | Country guard; LinkedIn first for those countries; a legal check by the person |
| Mac asleep or off | Re-planning; the `doctor` warning; later, the worker on an always-on machine |
| App password revoked (password change) | The auth pause and banner; Test |
| Three writers on one git folder (`serve`, `sync`, the send worker) | The worker writes through `Store` as `sync` already does; check how a held `index.lock` is handled and retry |
| An agent sends | No MCP send tool, an `AGENTS.md` rule, the cap and window as the limit on damage |

## Decisions (18 Oct 2026)

1. **LinkedIn: A**, the paced session where the person clicks Send. M5 (a
   private browser bot) is not built.
2. **Country guard: no.** `send_email_block_countries` stays `[]`, so email to
   DE/AT first touches is not blocked. The guard code exists for a folder that
   wants it (Settings > Sending > Never email these countries).
3. **Sending mailbox: a separate one.** About 100 emails a day, and the maximum
   per day is a setting (`send_daily_cap`). Going above 150 a day for more than
   1-2 days in a row is strongly discouraged, so Settings warns above the plan and
   above 150, and the planner and the worker hold a third day in a row at 150.
   Throughput ceiling: one send per 3-minute tick, so at most 180 a day in the
   default window.
   **Changed 19 Oct:** the plan is **50 a day**, not 100 (default `send_daily_cap`
   50, ramp `[10, 20, 30, 40]`: start with 10 and step up by 10 a week). Settings
   warns above 50 and again above 150.
4. **The opt-out line is optional** (19 Oct). A playbook without `opt_out:` adds
   no line and blocks nothing; a playbook with one still has it added and checked.

## Built as (where the build decides what the spec left open)

- **Modules:** `sendplan.py` (the pure planner and caps), `send.py` (settings,
  message, SMTP, IMAP mailbox, guards, delivery, pause state, lock),
  `sendqueue.py` (schedule, unschedule, retry, move to front, the worker tick,
  bounce scan, opt-out), `suppress.py` (the list and delivery reports),
  `linkedin.py` (the session). `outreach.py` keeps the states.
- **Migrations:** 12 adds the item keys (empty, after `skipped`), 13 allows
  `source: outreach` (a no-op), 14 adds the "Sending mail" rule to `CLAUDE.md` and
  `AGENTS.md` of existing folders.
- **A re-plan keeps the times the page already showed.** Only new, overdue, moved
  or outside-the-window items get new slots (first fit, never ahead of an item that
  was queued before them), so "goes out at the time the page showed" holds. Each
  day fills its cap whenever the window has the minutes for it: a gap never takes
  more than its share of the room left.
- **`failed` is an open state**, so the contact gets no second draft and the card
  can be skipped; Retry keeps the Message-ID so a later send still asks Sent first.
- **Replies to interest go first**, with follow-ups, ahead of first touches.
- **A check that already failed when the item was approved does not hold it**
  (the person approved it with that warning); one that fails now and did not then does.
- **Runtime state lives in `.git/`** (`hermitcrm-send.json`, the lock,
  `hermitcrm-linkedin.json`): never committed, no `.gitignore` migration. The Pause
  button is `send_paused` in `config.toml`; automatic pauses (login, quota, bounces)
  are in the state file. A damaged state file reads as paused.
- **Bounce rate:** more than 3 bounces among the last 50 sends, or over 5% once
  there are at least 20 sends (one bounce in the first five is not a rate).
- **Opted out skips** the person's open items (reason `other`, note "opted out")
  rather than leaving them queued.
- **LinkedIn queue order:** answers and follow-ups, then connection notes, then
  pitches. A weekly-limit message from LinkedIn pauses invites until the 7-day count
  drops below what it was then (seven days when there was nothing of ours to drop).
- **Not verified live:** that Gmail files mail sent over `smtp.gmail.com` in Sent by
  itself (M1 asked to confirm; no real mailbox was used in the tests). Run **Send a
  test to myself** and look in Sent before the first batch. The real `smtplib` path
  is covered by an in-memory SMTP server, not Google.

## Left to the builder

The exact `ITEM_KEYS` order and the migration numbers; the module split (a new
`send.py` for the sender, planner and worker, with `outreach.py` keeping the
states); how the worker opens the store; the lock mechanism (`fcntl`);
finding Sent and Inbox by their special-use flags rather than by localised
names; DSN parsing details; button wording and the page layout, following
`DESIGN.md`.
