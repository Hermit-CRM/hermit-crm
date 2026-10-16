# Part 07 · Phases 5-6: automatic logging, then full auto

Context: [00-overview](00-overview.md). Settings, off by default, introduced in
this order. Phase 6 gets its own spec.

## Phase 5: `outreach_auto_log = false`

**Done when:** marking ready logs the interaction with its angle and moves the
stage.

When on, Mark ready becomes **I sent it**: it logs an outbound interaction
(channel, contact, subject, body byte for byte, angle, `source: outreach`)
through the store, moves the stage from entry to advance target as a manual log
does, and sets the item to `logged`. The new `source` value is a front-matter
change, so it comes with a numbered migration (a no-op for existing files) and
tests.

## Phase 6: `outreach_mode = "semi" | "auto"` (default `semi`)

`auto` is refused unless all hold:

- a real Sender is configured for the channel
- a daily cap (`outreach_daily_cap`, default 10)
- per-channel opt-in (`outreach_auto_channels = ["email"]`)
- an unlock threshold the app checks: at least N items marked ready in semi
  mode, with ready rate and edit size within limits
- a visible kill switch on the Outreach page

In auto mode the app still drafts first, then sends after a grace period
(`outreach_send_delay_minutes`, default 60) during which the card can be
stopped. Replies to interest stay semi-automatic.

| Channel | Sender | Note |
|---|---|---|
| email | Gmail API or SMTP | Fits best. `message_id` from the send result becomes the dedup key, so a later BCC import does not double-log it |
| linkedin | none, ever | Automated sending breaks LinkedIn's user agreement and risks the account. Always copy + open, even in auto mode |

- **Deliverability:** plain text, no links or tracking pixels in the first mail,
  low daily volume, SPF/DKIM/DMARC on the sending domain.
- **GDPR / ePrivacy:** cold outreach to EU contacts needs legitimate interest
  and an opt-out line; auto mode makes the opt-out line mandatory for email.

## Tests

- the `outreach_mode = "auto"` setting is refused without a Sender (guards the
  default)
