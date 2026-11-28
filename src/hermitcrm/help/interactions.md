# Interactions

An interaction is one touch with a person: an email, LinkedIn message, call, WhatsApp message or meeting, in or out, with the text kept verbatim. A **note** is an interaction too: a memo about the person, with no direction, that shows on their timeline but never counts as contact made (it does not move last touch, a prospect's stage, follow-ups, outcomes or reports).

## Logging one

Notes may also be about the whole company: pick **whole company** in the
contact dropdown, or use **Add company note** (on the company page and on every
contact page). Only a note can be left without a contact. A company note shows
on the company page and, under **Notes elsewhere**, on every contact's page, as
do the notes on the company's other contacts (the newest five of each, with a
link to the rest), so nothing a colleague knows is hidden from you.

The company form has no notes box: company text is company notes, dated like any note, and outreach drafts cite them like any other note.

An interaction is always with a person, so the **Log an interaction** form
sits on every contact page (the "log" link in a company's contact list goes
there), and on its own at `/companies/<slug>/interactions/new` where you pick
the contact (the "log interaction" links on the Calendar open it). Fields:
channel (a dropdown: `email`, `linkedin`, `call`, `whatsapp`, `meeting`,
`note`, default linkedin),
direction (`out` or `in`, default out; hidden for a note), date and time
(default now, editable), subject, outcome, call outcome and call type (an
outbound call only, see [Calls](/help/interactions#calls)) and the body.
The body is the pasted message or the call notes; it is stored byte for byte
and never rewritten.

Logging an interaction (by hand or from the BCC and calendar imports) on a
company in **prospect** moves it to **engaged**, in the same commit; a note
does not. Other
stages are left alone.

Saving on a contact's page adds the entry to the timeline without a page
reload, empties the form for the next one, and says what happened in a short
message in the bottom right corner. Without JavaScript (and from
`/companies/<slug>/interactions/new`) saving redirects to the contact's page
with the timeline scrolled to the new entry. Each entry has an edit link (`/companies/<slug>/interactions/<id>/edit`)
where every field including the date can change; a date change renames the
file.

## Files

An interaction can carry files: a proposal you sent, a screenshot of their
pricing page, the PDF they attached.

- **On the form**: under the body, **files** opens the file picker. Drop files
  on the form, or paste a screenshot into it (a pasted picture is named
  `pasted-<date>.png`), and they are listed with a remove button before you save.
  Saving keeps the note and its files in one commit.
- **On an existing entry**: drop a file on it in the timeline, or use the picker
  on its edit page, which also lists the files with **Remove**.
- **On a page**: drop files anywhere on a company or contact page, or use the
  **Files** box at the bottom, and they become a new note (the subject is the file
  names; on a contact page the note is about that person). The **Files**
  section lists every file once, newest first, each linking back to its note.

A file is stored in `companies/<slug>/attachments/` under a name that starts with
twelve characters of its content hash, so the same file attached twice is kept
once and renaming or re-dating a note never loses it. The limit is
`attachment_max_mb` in `config.toml` (default 25, at most 90): git hosts refuse
larger files.

Pictures, PDFs and plain text open in the browser; every other type
(including `.svg` and `.html`) downloads. **Removing** a file, or deleting the
note that was the last to use it, deletes it from the folder, but git keeps the
old copy: Hermit CRM never rewrites history, so a large file you attached by
mistake stays in the repository's history. Keep very large files elsewhere and
link to them in a note.

From the command line, `hermitcrm attach COMPANY FILE... [--contact SLUG] [--to
INTERACTION_ID] [--note TEXT]` keeps files on a new note (or on an existing
interaction) and `hermitcrm attachments [COMPANY]` lists them. `hermitcrm check`
reports a note whose file is missing as an error, and a file no note uses, a
file whose content changed or one over the limit as a warning.

## Outcome

`outcome` is one line: what came of it. The choices are configured on the
Settings page (`outcomes` in `config.toml`, default `successful`,
`interested` and `unsuccessful`). Set `interested` on a reply that shows
interest: the Outreach page lists it under Replies to interest. For a sent message the outcome decides its status on the
Messages tab: an explicit outcome wins; otherwise a later inbound interaction
from the same contact (or a company-level one) counts as the **first**
configured outcome; otherwise, once the message is older than
`message_window_days` (default 14), it counts as the **last** one; until then
it is unknown. Files from before format 3 carried a separate `result` key;
migration 3 folded it into `outcome`.

## Calls

A call is logged like any interaction, with channel `call`. Its **direction**
says who rang: **out** (outbound) when you called them, **in** (inbound) when they
called you.

An **outbound** call has two more fields, which the form shows only when the
channel is `call` and the direction is `out`. Both are optional. You can change
both lists in [Settings](/settings#calls). These are the defaults:

**Call outcome**: what happened on the line.

- **connected**: you reached the person you called, but there was no real
  conversation: it was a bad time, they asked you to call back, or they hung up.
- **conversation**: you reached the person and talked with them about why you
  called.
- **message to other human**: someone else answered (a colleague, an assistant,
  reception) and you left a message with them.
- **voicemail message**: you left a message on their voicemail.
- **no answer**: it rang out and you left no message.
- **busy**: the line was busy, or the call dropped before it rang.
- **rejected by automated call screening**: an automated screen on their phone
  answered, asked who you were, and did not put you through.
- **wrong number**: the number does not belong to this person. Fix or remove it
  on the contact.

**Call type**: what the call was for.

- **prospecting**: opening a conversation with someone who is not yet a real
  opportunity in your pipeline.
- **pipeline development**: moving an existing opportunity forward: a follow-up,
  discovery, or agreeing next steps with an account already in your pipeline.

The call outcome is separate from **outcome** above. Outcome is what came of an
interaction and drives the Messages tab. Call outcome is only what happened on
the line. A voicemail can still lead to a reply.

In the file they are `call_outcome` and `call_type`, left out when empty, stored
as the name from your list. In `config.toml` the lists are `call_outcomes` and
`call_types`. Renaming or removing a name in Settings does not change calls
already logged: they keep the old name, and their edit form still offers it.
Changing a call's channel or direction so that it is no longer outbound clears
both. From the command line:
`hermitcrm add interaction COMPANY --channel call --direction out --call-outcome
"voicemail message" --call-type prospecting`.

## Where interactions come from

- **manual**: the form.
- **bcc-import**: mail you BCC'd or forwarded to the tracking address, logged
  at the contact with that email; the quoted thread is cut once at import.
- **calendar-import**: past meetings from the calendar feed, one `meeting`
  interaction per external attendee, subject from the event title, body from
  its description.

Imports carry a `message_id` so a rerun never logs the same mail or meeting
twice. Mail and meetings that match no company wait on Home under **To file**.

## To file (the review queue)

Home shows a **To file (N)** list under *What to do now* whenever the imports
left something they could not place (while the walkthrough is still your home
page, it shows there). Each item has the date, kind, direction, person and
subject, the reason (personal address, unknown domain, several matching
companies), the text collapsed, and a form to **Log at company** (a company slug
or name, legal suffixes like GmbH ignored, else the company that has the mail's
domain; a name that finds neither creates a new company, with the mail's domain
as its website unless it is a personal address; the contact is found by email,
else a same-named contact gets the email, else it is created) or **Discard**
(remembered in `inbox/discarded.tsv`). The count shows on Home in the nav. The
import status and the **Import now** buttons are under Settings, BCC capture and
Calendar; the red `!` on Settings means the last import failed or is two days
old, and jumps to the one that did.

## Files and ids

`companies/<slug>/interactions/<id>.md` with the id
`YYYY-MM-DDTHHMM-<channel>-<direction>-<contact-slug or company>` (a
collision gets `-2`, `-3`). The commit is
`interaction: <company> <channel> <direction> <contact> <date>`.

Related: [Messages](/help/messages), [Companies](/help/companies), [Contacts](/help/contacts), [Settings](/help/settings), [Data format](/help/data-format)
