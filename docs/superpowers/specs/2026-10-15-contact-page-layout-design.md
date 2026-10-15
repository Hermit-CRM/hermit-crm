# Contact page layout: research and proposal

Status: proposal, not built. Written 15 Oct 2026.

## Question

How do established CRMs lay out the page for one person, and what should the
Hermit CRM contact page (`templates/contact.html`) take from them? Our user is
one person doing their own sales. Hermit CRM sends nothing: no mail, no
sequences, no LinkedIn automation. Messages are written elsewhere and logged
here (by hand, BCC import, calendar import, the extension).

## The page today

Measured on the demo folder (Lena Vogt at Northwind Robotics, 1280px wide), one
column, about 2,000px tall:

| Section | Starts at | Height |
|---|---|---|
| Header: name, company, title, role, email, "no phone", Enrich | 0 | ~110 |
| Contact: the edit form, always open | 167 | 203 |
| Interactions (3) | 393 | 269 |
| Log an interaction | 683 | 332 |
| Tasks for Lena Vogt | 1038 | 123 |
| Message drafts | 1182 | 590 |
| Merge | 1794 | 73 |
| Delete | 1889 | 62 |

What a returning visit needs (when did we last talk, who is waiting on whom,
what do I owe this person) is not on the page as an answer: you work it out
from the timeline dates and you scroll past the log form to reach the tasks.
The edit form is the first thing under the name, though fields change rarely.
Each timeline entry repeats the contact's own name and often says
"(no subject)", and the body hides behind "body". About 40% of the
page height is drafts, merge and delete, which are used occasionally.

## What ten CRMs do

| CRM | Top of the page | Main area | Side area | Notes |
|---|---|---|---|---|
| HubSpot | Name, title, action icons (note, email, call, task, meeting) | Tabs: Overview, Activities timeline | Associated company, deals, attachments | Three columns; left sidebar for properties |
| Salesforce | Highlights panel: up to 7 compact-layout fields, plus actions | Activity timeline (upcoming and overdue first, then past) | Related lists | One "compact layout" feeds the header and the timeline |
| Pipedrive | Summary panel: labels, email, phone, linked org, always these four | **Focus** (upcoming activities, drafts, pinned notes), then **History** (filterable, plus a changelog tab) | Details, linked deals and persons, Smart BCC address | Sections collapse; sidebar sections can be hidden and reordered |
| Attio | Name, action buttons; up to six **highlight** widgets (default: connection strength, last email, last interaction) | Tabs: Overview, Activity, Notes, Tasks, Emails, Files | Attributes, list memberships (stage) | Configurable per object |
| Copper | Name, title, company | Activity feed with **interaction stats** above it: count, date of the latest, days inactive | Details on the left; related records | Admin picks which activity types count as an interaction |
| Close | Lead status top right | Activity feed, filterable by type, up to 5 pinned notes on top | Open tasks, opportunities, contacts, custom fields | Tasks sit next to the feed, not under it |
| folk | Quick actions: email, enrich, call; social links, one-click WhatsApp | Details, interactions, notes, reminders | Opens as a right-hand panel over a list or full width | The company page lists its people with last interaction date |
| Twenty | Name | Tabs of widgets: Fields, Timeline, Tasks, Notes, Files, related records | (widgets) | Recommends key fields on Overview, the rest on a second tab |
| Dex (personal CRM) | Name, overdue marker when a keep-in-touch is due | One timeline of meetings, calls, mails, messages and notes | Keep-in-touch cadence, tags, groups | Next reminder = last interaction + cadence |
| Monica (personal CRM) | Name; "Log an activity", "Schedule a reminder", "Add a note" | Activities, notes | Reminders | Per-contact reminder intervals |

### The patterns that repeat

1. **Answer "where are we" before anything else.** Salesforce's highlights,
   Attio's highlight widgets, Copper's interaction stats and Pipedrive's summary
   are the same idea: a few computed facts at the top. The facts are almost
   always last interaction, how long ago, and what is next.
2. **Separate what is next from what happened.** Pipedrive splits Focus from
   History; Salesforce puts upcoming and overdue items above the past; Close
   puts open tasks next to the feed. Nobody puts tasks below a form.
3. **One merged timeline, with notes in it.** Every one of them treats notes,
   calls, meetings and messages as one stream, newest first, with a type
   filter. Close and Pipedrive pin a few notes on top.
4. **Fields are read, not edited.** No CRM opens a person as an edit form.
   Fields are a read-only list; you click to edit one, or press Edit.
5. **Two zones on a wide screen.** Activity in the wide column, facts and
   related records in a narrow one. Twenty and HubSpot use tabs on top of this;
   for a small record tabs only hide things.
6. **Actions next to the name.** Log a call, add a note, add a task, open
   LinkedIn: one click from the top of the page.
7. **Show the colleagues.** The person's company and the other people there
   (folk lists them with last interaction date; HubSpot and Pipedrive with
   association cards).
8. **Rare and destructive things go out of the way.** Merge and delete live in
   a "..." menu everywhere.

### What we leave out on purpose

- Compose or send email, sequences, "enroll in sequence": we do not send.
  The honest equivalents are copy the email address, open it in your own mail
  app (`mailto:`), and the BCC address the user already has.
- Connection strength, marketing status, followers, owners, team activity:
  one-person CRM, no tracking.
- A changelog tab: git is the changelog. A "history" link could come later.
- Tabs: the record is small; tabs would hide the timeline behind a click.
- An empty-field hunt ("no phone"): show "+ phone" as a link to the edit form
  instead of telling the user what is missing.

## Proposal

### Wireframe (1000px and wider)

```
+-------------------------------------------------------------------------+
| Lena Vogt                                                               |
| COO at Northwind Robotics  [discovery]  [decision-maker]                |
| [Log interaction] [Add note] [Add task]   copy email | linkedin | Enrich |
+-------------------------------------------------------------------------+
| LAST TOUCH          | WAITING ON          | NEXT FOR LENA    | HISTORY  |
| 17 Sep, meeting out | you: reply owed     | send proposal    | 3 in 2/1 |
| 28 days ago         | since 12 Sep        | due 20 Oct       | since Sep|
+------------------------------------------+------------------------------+
| LOG AN INTERACTION (one row, opens on    | TASKS FOR LENA               |
| focus: channel, in/out, date, body)      |  [ ] send proposal  20 Oct   |
|                                          |  + add task                  |
| TIMELINE   all | messages | meetings |   |                              |
|            notes                         | DETAILS              [Edit]  |
| 17 Sep  meeting  ->  Intro call: wants   |  email  lena@...  (copy)     |
|         a proposal for two sites         |  phone  + add                |
|         "First line of the notes..."     |  linkedin  open              |
| 12 Sep  linkedin <-  "Thanks Gijs, ..."  |  draft language  German      |
| 10 Sep  linkedin ->  "Hallo Lena, ..."   |  custom fields ...           |
|                                          |                              |
|                                          | NORTHWIND ROBOTICS           |
|                                          |  discovery, 12d in stage     |
|                                          |  next: demo, due 22 Oct      |
|                                          |  also here: Jonas Brandt,    |
|                                          |    CTO, last touch 2 Sep     |
+------------------------------------------+------------------------------+
| > Message drafts for Lena (German)        (closed unless never written) |
| > More: merge, delete, slug and dates                                   |
+-------------------------------------------------------------------------+
```

Under 1000px the side column drops below the main column in the order above,
the same way the rest of the app already wraps.

### Changes, by priority

**P1: the answers on top (small, no data change)**

1. **Header subtitle as a sentence**: "COO at Northwind Robotics", then chips
   for the company stage and the contact's role. Missing title or role shows
   nothing, not "no title" / "no role".
2. **Action row under the name**: Log interaction (scrolls to and focuses the
   log form), Add note (same form with channel `note`), Add task (focuses the
   task input), then quiet links: copy email (clipboard; one line of vanilla
   JS, falls back to the `mailto:` link), LinkedIn, Enrich. No "Email" button
   that suggests we send.
3. **Status strip** with four facts, each computed from data we already have:
   - Last touch: date, channel, direction, "N days ago"
     (`company.contact_last_touch`, the same value as the Contacts tab).
   - Waiting on: "you owe a reply since …" or "no answer since …" or nothing,
     using the rules in `followups.py` applied to this contact's interactions
     only (needs a small `followups.for_contact()` that shares `radar()`'s
     rules: `is_touch`, `reply_after`, the nudge threshold, `_waiting`, so
     Home and this page cannot disagree).
   - Next for this person: the contact's open task due first, overdue in
     `--danger`.
   - History: interaction count, in vs out, first contact date.
4. **Tasks move above the timeline** (or into the side column with P2).
5. **Timeline cleanup on the contact page** (a flag on the `timeline` macro, so
   the company page is untouched): drop the "who" label (it is always this
   person), drop "(no subject)", show direction as an arrow with a text label
   for screen readers, and show the first line of the body (the
   `followups.first_line` helper already strips greetings) with the full body
   behind "more". Notes stay open as today.
6. **Details read-only by default** with an Edit toggle, using the
   `<details class="inline-edit">` pattern the company page already has. No
   JavaScript needed. Validation errors open it again.
7. **Drafts collapsed** into a `<details>`, open by default only when this
   contact has no outbound interaction yet (that is when you need a first
   message).
8. **Merge, Delete and the slug/created/updated line** into one closed
   "More" `<details>` at the bottom.

**P2: two columns and the colleagues (template + CSS)**

9. **Two columns at 1000px and up**: main (log form, timeline) about 2/3, side
   (tasks, details, company card) about 1/3. One CSS grid, collapsing to one
   column below 1000px. All colours and fonts stay tokens.
10. **Company card in the side column**: stage, days in stage, the company's
    next step, and "also here": the other contacts with title and last touch,
    each a link. This is the one thing the page cannot show today without a
    click to the company.
11. **`layout.toml` keeps working**: the existing section names stay
    (`details`, `timeline`, `quick-add`, `tasks`, `drafts`, `merge`, `delete`),
    two are added (`summary` for the status strip, `company` for the card), and
    each section has a fixed column. The user's order applies within a column;
    hiding still hides. `layout.py` `SECTIONS["contact"]` gets the two new
    names, `help/adjust-layout` gets a line, and tests cover an old
    `layout.toml` that lacks them (they default to shown, in the default place).

**P3: later, each needs its own decision**

12. Timeline filter chips (all / messages / meetings / notes) as GET links
    (`?show=notes`), no JavaScript.
13. Pinned notes on top of the timeline (Close, Pipedrive). Needs a
    `pinned: true` key on note interactions, so a migration plus tests.
14. Keep-in-touch cadence per contact (Dex, Monica): `keep_in_touch_days` on the
    contact, next reminder = last touch + cadence, shown in the status strip and
    on Home. New front-matter key, so a migration plus tests; worth it only if
    users manage relationships after the deal, which is outside the current
    pipeline focus.

### What does not change

- No front-matter keys or values in P1 and P2, so no migration.
- No new runtime dependencies; the only JavaScript is the copy button and the
  focus jumps, both optional.
- The company page, the timeline on the company page, the MCP server and the
  CLI.
- The template's "default page byte for byte as before layouts" promise ends
  with this change: the default page is new on purpose. Tests that pin the
  default contact page HTML need updating with it.

### Testing

- `tests/` for the status strip values: no interactions; only a note (notes
  are not a touch, as in `followups.latest`); inbound last (reply owed);
  outbound last (waiting); an overdue task.
- Layout: an old `layout.toml` without `summary`/`company`; a hidden section;
  a reordered section stays in its column.
- Edit toggle: a form with errors renders open.
- Check in the demo folder at 1280px and 760px, light and dark.

## Sources

Each vendor's own help pages, read 15 Oct 2026 (titles only; search the vendor's help centre for them):

- HubSpot, Understand the default record layout and Work with records
- Salesforce, Customize the user interface (Trailhead) and Tailor the activity timeline
- Pipedrive, Contact detail view, Detail view sidebar, Introducing the new contact detail view
- Attio, Configure record pages and Create and view records
- Copper, Understand contact records in Copper
- Close, Leads
- folk, Contact profile and Set reminders on your contacts
- Twenty, Record pages
- Dex, Keep in touch
- Monica, Dex's Monica review and Monica docs mirror
