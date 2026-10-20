# Contacts

`/contacts` lists every person across companies; a contact page holds the fields, this person's interactions, notes and a button that opens Outreach for them.

## The table

Columns: name, company, title, email (a mailto link), LinkedIn, last touch and
interaction count, with a filter control per column and sort arrows. The search
box matches name, email, title and company.

## The contact page

`/companies/<slug>/contacts/<contact-slug>`:

- Header: company, title, role, email, phone, LinkedIn, and **Enrich** when an
  AI CLI is available.
- **Contact**: first name, last name (at least one required), title, role
  (`champion`, `decision-maker`, `influencer`, `gatekeeper` or none), email
  (stored lower case), phone, LinkedIn. There is no notes field: what you
  know about a person is a **note** on their timeline.
- **Interactions** of this contact, newest first, notes included.
- **Log an interaction** for this contact: an email, LinkedIn message, call,
  meeting or note.
- **Tasks** you owe this person.
- **Generate outreach** (below).
- **Merge** another contact of the same company into this one (only shown when
  the company has more than one contact).
- **Delete contact** (asks first). Their interactions stay on the company
  with the contact cleared, so the record survives; git keeps the file's
  history.

New contacts come from the company page's New contact link
(`/companies/<slug>/contacts/new`), from Import in contacts mode, and from the
BCC and calendar imports (a new person at a company whose domain is known).

## Keep in touch

The follow-up radar and the silent list are about deals. **Keep in touch** on
Home is about everyone else: people you have not spoken to in
`keep_in_touch_days` days (default 180, about six months) who are not in an
open deal. It is a read-only list, longest quiet first, eight on Home;
`hermitcrm keep-in-touch` (and the `keep_in_touch` tool for an AI client)
prints all of them.

- **Last touch** is the latest interaction logged against that person, in
  either direction: an email, a message, a call or a meeting. Notes do not
  count, and neither does an interaction logged against the company with no
  person on it.
- **Left out**: people at a company in an open stage (prospect, engaged,
  discovery, offer, or whatever your open stages are), so the list holds
  customers, lost and disqualified deals and parked companies; anyone tagged
  `do-not-contact`, on the company or on the person; people you never had any
  interaction with; and the sample account.
- Logging anything with a person takes them off the list.
- Change the threshold in `config.toml` (`keep_in_touch_days = 90`), move
  or hide the section with `layout.toml` (`keep-in-touch`, see
  [Make it yours: layout](/help/adjust-layout)).

## Tasks

The contact page lists the tasks you owe this person, with **Done**, **Delete**
and a form to add one. They also show in the company's task list, and when one
of them is the company's task due first, it is the company's next step.

## Generate outreach

The **Generate outreach** button in the action row opens [Outreach](/help/outreach)
with this person ready to draft: channel, draft type, signal, one observation
sentence, a language, and the notes the draft will be written from. Nothing runs
until you press **Generate**. When the person already has an open draft, the
button says **Open outreach draft** and goes to its card.

The no-AI **Message drafts** box that used to sit here is gone; its signal,
observation and language picker moved to that panel, and what you write there is
kept as notes. The contact's **draft language** (set on the contact, say for a
German speaker at a Dutch company) is where the panel starts, else the language
of the company's country. The wording of reply and follow-up templates lives in
the package's `default_messages.toml`; a `messages.toml` in the data folder
overrides any part of it, and `MESSAGING.md` there is your playbook.

Related: [Companies](/help/companies), [Interactions](/help/interactions), [Messages](/help/messages), [Merge](/help/merge)
