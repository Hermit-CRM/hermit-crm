# Interactions

An interaction is one touch with a company: an email, LinkedIn message, call or meeting, in or out, with the text kept verbatim.

## Logging one

The **Log an interaction** form sits on every company and contact page, and
on its own at `/companies/<slug>/interactions/new` (the "log interaction"
links on the Calendar open it). Fields: channel (`email`, `linkedin`, `call`,
`meeting`), direction (`out` or `in`, default out), contact (or "company
only"), date and time (default now, editable), subject, outcome and the body.
The body is the pasted message or the call notes; it is stored byte for byte
and never rewritten.

Saving redirects to the company page with the timeline scrolled to the new
entry. Each entry has an edit link (`/companies/<slug>/interactions/<id>/edit`)
where every field including the date can change; a date change renames the
file.

## Outcome

`outcome` is one line: what came of it. The choices are configured on the
Settings page (`outcomes` in `config.toml`, default `successful` and
`unsuccessful`). For a sent message the outcome decides its status on the
Messages tab: an explicit outcome wins; otherwise a later inbound interaction
from the same contact (or a company-level one) counts as the **first**
configured outcome; otherwise, once the message is older than
`message_window_days` (default 14), it counts as the **last** one; until then
it is unknown. Files from before format 3 carried a separate `result` key;
migration 3 folded it into `outcome`.

## Where interactions come from

- **manual**: the form.
- **bcc-import**: mail you BCC'd or forwarded to the tracking address, logged
  at the contact with that email; the quoted thread is cut once at import.
- **calendar-import**: past meetings from the calendar feed, one `meeting`
  interaction per external attendee, subject from the event title, body from
  its description.

Imports carry a `message_id` so a rerun never logs the same mail or meeting
twice. Mail and meetings that match no company wait in the review queue on the
Settings page.

## Files and ids

`companies/<slug>/interactions/<id>.md` with the id
`YYYY-MM-DDTHHMM-<channel>-<direction>-<contact-slug or company>` (a
collision gets `-2`, `-3`). The commit is
`interaction: <company> <channel> <direction> <contact> <date>`.

Related: [Messages](/help/messages), [Companies](/help/companies), [Contacts](/help/contacts), [Settings](/help/settings), [Data format](/help/data-format)
