# Contacts

`/contacts` lists every person across companies; a contact page holds the fields, this person's interactions and three message drafts.

## The table

Columns: name, company, title, email (a mailto link), LinkedIn, last touch and
interaction count, with a filter control per column and sort arrows. The search
box matches name, email, title and company.

## The contact page

`/companies/<slug>/contacts/<contact-slug>`:

- Header: company, title, role, email, phone, LinkedIn, and **Enrich** when an
  AI CLI is available.
- **Log an interaction** with this contact preselected.
- **Contact**: first name, last name (at least one required), title, role
  (`champion`, `decision-maker`, `influencer`, `gatekeeper` or none), email
  (stored lower case), phone, LinkedIn, notes.
- **Message drafts** (below).
- **Merge** another contact of the same company into this one (only shown when
  the company has more than one contact).
- **Interactions** of this contact, newest first.
- **Delete contact** (asks first). Their interactions stay on the company
  with the contact cleared, so the record survives; git keeps the file's
  history.

New contacts come from the company page's New contact link
(`/companies/<slug>/contacts/new`), from Import in contacts mode, and from the
BCC and calendar imports (a new person at a company whose domain is known).

## Tasks

The contact page shows the company's **Tasks** section (above Delete): the next
step, its due date and status, **Mark done** / **Reopen**, and a form to write a
new one. A next step belongs to the company, so it is the same task you see on
the company page and in the calendar.

## Message drafts

Three deliberately different drafts, written from CRM data alone, no AI, in
the language of the company's country:

1. **scale** (they are growing; offer help to keep the pace), or **bridge**
   when the signal is hiring (help while the role is open), or **decline** when
   the signal is headcount decline (a tough stretch, then an open question);
2. **unblock**: past the next headcount hurdle (10, 20, 50, 100, 250, 500,
   from `fte_estimate`);
3. **hook**: one observation, then an open question.

Two inputs are yours: the **signal** (growing, stalled, headcount decline, hiring, read off
LinkedIn company insights; the link is right there) and one **observation**
sentence from their website or team. Whatever the CRM cannot know is left in
square brackets. Edit in place, copy, or **log as sent**, which opens the
quick-add form with the draft as body and channel LinkedIn. The wording lives
in the package's `default_messages.toml`; a `messages.toml` in the data folder
overrides any part of it, and `MESSAGING.md` there is your playbook.

Related: [Companies](/help/companies), [Interactions](/help/interactions), [Messages](/help/messages), [Merge](/help/merge)
