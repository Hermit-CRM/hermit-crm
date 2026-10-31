# Sending

Sends the email you approved from the Outreach page, now or spaced over the working day, from a mailbox of its own; LinkedIn is a paced session where you click Send yourself. You approve every message.

Until now the outreach bot only wrote and checked: you copied each message into
your mail or LinkedIn, and logging it afterwards marked the item sent. That is
fine at five a day and breaks at fifty. Sending adds two things, both off until
you turn them on, and neither one writes anything you did not approve.

## Set it up (about 30 minutes, once)

1. **A separate mailbox.** Use a mailbox on its own domain (for example
   `sam@try-example.com`, not your main address). Cold email can hurt the
   reputation of the domain it is sent from; a separate one keeps your main
   domain safe. Give the new domain SPF, DKIM and DMARC (a DMARC record with
   `p=none` is enough at this volume).
2. **An app password.** With Gmail or Google Workspace: turn on 2-Step
   Verification, then make an app password named "Hermit CRM"
   (<https://myaccount.google.com/apppasswords>). A Workspace admin can switch
   app passwords off, and changing the account password revokes them. Only
   Gmail and Google Workspace are tested; iCloud and Fastmail should work;
   Microsoft has switched off password sign-in, so Outlook.com and Microsoft
   365 do not.
3. **Settings > Email & calendar > Sending.** Pick the provider, the sending
   address and the app password (kept in the Keychain or `.secrets.toml`, never
   in `config.toml`), tick **Sending is on**, press **Send a test to myself**
   (a wrong password shows the server's exact reply), then **Turn on scheduled
   sending**. One app password covers sending and the reply check. (An empty IMAP server switches the
   reply check, the Sent check and the bounce scan off: then a send that stopped halfway cannot be
   looked up in Sent, so use it only if your provider has no IMAP.)
4. **An opt-out line** (optional). If your playbook sets `opt_out:` in
   `MESSAGING.md`, one sentence or one per language, a cold first touch carries
   it and a scheduled one is held when it was edited out. Without it nothing is
   added and nothing is checked. The **Opted out** button and the suppression
   list work either way.
5. **Energy settings.** The Mac must not sleep on power during the window:
   launchd runs nothing while it sleeps. `hermitcrm doctor` reads the setting
   and warns; it never changes it.

## What it does

On the Ready tab each email card has **Send now** and **Schedule**, and **Schedule
all ready email** shows the proposed times first and asks you to confirm. A
queued card says when it goes out ("goes out Tue 20 Oct, 09:47"); the
**Scheduled** tab lists them with **Unschedule**, **Send now** and **Move to
front**. The strip at the top of the page shows today's count against the cap,
the next send and **Pause**, the kill switch: one click, effective from the
next tick.

A job (`hermitcrm send due`, every 3 minutes) sends **one** queued email per run.
Before each send it checks again:

- sending is on, not paused, inside the window, under today's cap, and the last
  send was at least the minimum gap ago;
- the text is still exactly what you approved (an edit on the page, or by hand
  in the file, puts it back to Ready). A file set to `queued` by hand or by an
  agent, without pressing **Schedule**, is held the same way and goes back to
  Ready ("it was never scheduled in the app"); **Send now** still sends it;
- the contact has an email address that is not on the suppression list, and the
  company is still open and not do-not-contact;
- **nobody there has written to you** since you approved it: in the CRM, and in
  the sending mailbox itself (one IMAP search, only when an item is about to go
  out). If they did, it goes back to Ready with "they wrote to you on 16 Oct";
- the checks still pass, and, when your playbook has an opt-out line, a cold
  first touch still carries it.

Nothing is dropped silently: whatever holds an item puts it back on the Ready
tab with the reason.

### The spacing

How many a day, and when:

| Setting | Default | Meaning |
|---|---|---|
| `send_window`, `send_days` | `08:30-17:30`, Mon-Fri | when mail may go out, in your time zone |
| `send_daily_cap` | 50 | the most per day, after the ramp |
| `send_ramp` | `[10, 20, 30, 40]` | the cap for weeks 1, 2, 3... counted from the first send |
| `send_min_gap_minutes` | 3 | the least time between two sends |
| `send_company_gap_hours` | 24 | two contacts at one company (or one email domain) go out a day apart |
| `send_grace_minutes` | 10 | the earliest slot after Schedule, so a mistake can be undone |
| `send_overdue_minutes` | 20 | later than this an item is planned again, never sent in a burst |
| `send_email_block_countries` | none | countries never emailed (see below) |

The gap between two sends is the window divided by the day's cap, times a factor
between 0.6 and 1.4 that depends only on the item (so the page and the worker
agree), never below the minimum gap: at 50 a day about 11 minutes, at 10 about
54. Follow-ups and replies to interest go first, then first touches in the order
they were queued. An item keeps the time the page showed unless it is overdue.
A Mac that slept for two hours plans what is overdue again and sends one at a
time; it never catches up in a burst.

**How much is too much.** 50 a day is the plan, reached from 10 a day in the
first week, 20 in the second, 30 and 40 after that. Raise `send_daily_cap` (and
the ramp) in steps, only while replies hold up and bounces stay low. More than 150 a day for more than one or two days in a row is
strongly discouraged (a mailbox that does it ends up in spam), so after two
send-days above 150 the third is held at 150 whatever the setting says.
Settings says the same next to the box. Reputation, not the provider's limit
(Gmail allows 2,000 a day), is the ceiling, and a brand new domain deserves a
slower start than the default ramp: lower `send_ramp` if you are unsure.

**Send now** ignores the window and the gap (a reply to interest should not wait
for a slot), but it counts toward today's cap, runs the same checks and is
refused while sending is paused. It is meant for replies and one-offs.

### When it goes wrong

| What happened | What it does |
|---|---|
| The login is refused (a revoked app password) | Pauses everything; a red banner on every page shows the server's own words; nothing retries until a new **Send a test** passes |
| The mail server's certificate cannot be verified (self-signed, expired or for another host name) | Pauses everything with the same banner, which says what is wrong; fix the host name or the server, then a passing **Send a test** lifts it |
| The daily quota is exceeded | Pauses until the next window, then plans again |
| A temporary error (421, 450, a timeout, no network) | Tries again in 15 minutes, up to 3 times, then the item is failed |
| The address does not exist | The item is failed and the address goes on the suppression list |
| The process stopped between sending and logging | The next run looks for the Message-ID in Sent: found, it logs it; not found, it sends again with the same Message-ID. Never twice |
| Too many bounced (more than 3 of the last 50, or over 5%) | Pauses with a banner: a list-quality problem, check where the addresses came from |

Each message gets a `Message-ID` on your sending domain, written on the item and
committed **before** it goes out; a follow-up or reply carries `In-Reply-To` and
`References`, so it threads under the mail it follows. The mail is plain text,
UTF-8, exactly as approved: no HTML, no links in a first touch, no tracking
pixel, no BCC and no List-Unsubscribe header (a one-to-one mail that looks like
a newsletter is what filters punish). It is logged once, as an outbound email
with `source: outreach`; a later BCC import of the same mail adds nothing.

## Bounces and opt-outs

Every half hour, while something is queued or went out in the last three days,
the sending mailbox is searched for delivery reports (from mailer-daemon or
postmaster). An address that bounced goes on the **suppression list**
(`outreach/suppressed.toml`: address, reason, date, item), a note goes on the
contact's timeline and the item is flagged. The planner never schedules a
suppressed address and the worker never sends to one.

**Opted out** (on a reply under Replies to interest, on the contact page, or
`hermitcrm outreach opt-out company/contact`) puts the address on the list and
skips every open item for that person. Delete a table from the file to mail an
address again.

## LinkedIn

LinkedIn's User Agreement (8.2) forbids automated sending, and a restricted account
is lost for good, so Hermit does not send on LinkedIn, ever. The **LinkedIn
session** on the Outreach page puts one approved touch in front of you at a time:

1. **Start session.** Counters at the top: invites today 0/20, the last 7 days
   0/80, messages today 0/40, this session 0/10.
2. A card shows the person and the text (a connection note up to 300 characters,
   a message up to 600). **Open profile & copy** copies the text and opens their
   profile in a new tab. You click Connect, Add a note, paste, Send.
3. Back on the card: **Sent** logs an outbound LinkedIn message with the exact
   text; **Already connected** turns the card into the message that would have
   followed the note; **Couldn't send** asks why (profile gone, LinkedIn's
   weekly-limit message, something else). The weekly-limit message pauses invites
   until the 7-day count drops.
4. The next card unlocks after a 45-120 second countdown that varies. After 10
   touches the session is done and the next can start two hours later.

The queue is answers and follow-ups to people you already talk to, then
connection notes, then messages to people who accepted. Sent invites wait under
**Waiting to accept**; **Accepted** brings the person's message into the queue.
An invite pending for 21 days gets a reminder to withdraw it: many pending
invites count against the account. Realistic volume is about 20 invites and
30-40 messages to connections a day. 50-100 invites a day is not available by
any method.

## Countries

German and Austrian law (UWG §7(2) no. 2, TKG §174) require prior consent for
advertising email, business to business included, and an opt-out line does not
cure that. The UK and the Netherlands are looser for B2B. This is not legal
advice. `send_email_block_countries` (Settings > Sending > Never email these
countries) keeps a country's companies out of the queue; the card then suggests
LinkedIn. It is empty by default: each folder decides.

## From the command line

```
hermitcrm send test               log in over SMTP and IMAP and mail a test to yourself
hermitcrm send status             on/off, today's count against the cap, the queue, why paused
hermitcrm send due [--dry-run]    one tick of the worker
hermitcrm send pause | resume     the kill switch
hermitcrm outreach schedule ID... | --all-ready [--dry-run]
hermitcrm outreach unschedule ID | front ID | retry ID | send-now ID
hermitcrm outreach opt-out COMPANY/CONTACT
hermitcrm schedule install --send
```

Agents never schedule or send unless you ask in that conversation: there is no
MCP tool for it, and the folder's `AGENTS.md` says so. The real limit on any
damage is the daily cap and the window.

Related: [Outreach bot](/help/outreach), [Playbook](/help/playbook), [Settings](/help/settings), [CLI](/help/cli)
