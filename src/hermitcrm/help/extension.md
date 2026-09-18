# Extension

`/extension`: turn the page you are looking at into a company record, in one
click, without typing the name twice.

The competition for a CRM is not another CRM, it is the record never getting
written. The extension is the short path: you are on a company's website or its
LinkedIn company page, you click one bookmark, and a new-company form opens
with the fields already filled in.

## A profile makes a contact

A LinkedIn or Xing profile is a person, not a company, so it opens the
new-contact form rather than the new-company one: name, title and the profile
URL filled in, with the employer the page names typed into the company box.
That box matches what you have already, so capturing three people from the
same company puts all three on one record instead of making three companies.
If the page names no employer, type the company yourself.

Logged out, a profile gives away very little: a name, a headline and usually
the current employer. Hermit CRM takes those and leaves the rest empty rather
than guessing, because a wrong employer creates a wrong company. A person's
headline becomes the contact's **title**, never the company's one-liner --
reading it as one produced sentences like "Most companies don't have a lead
problem... - Experience: ... - 500+ connections on LinkedIn", which is how this
was found.

## The bookmarklet

The `/extension` page has a link to drag to your bookmarks bar. It points at the
address this Hermit CRM is serving on, so take it again if you later run
`serve` on a different host or port. Some browsers refuse to run a bookmarklet
clicked from a page; dragging it to the bar first always works, and the code is
printed on the page to paste into a bookmark by hand.

There is also a plain box on the same page: paste a URL, press **Read the
page**. Same result, no bookmark.

## What it reads

The page's own metadata, fetched by your machine directly: nothing is sent
anywhere, and no AI is involved. It proposes the company name, the website,
the LinkedIn company page the site links to, the country, an employee-count
hint and a one-line description. The same parser as **Fetch from URL** on an
existing company ([Enrich](/help/enrich)); the extension only runs it the other way
round, page first and record after.

The guesses are guesses. Country in particular is inferred from the page and is
sometimes wrong, which is why the form says to check the fields. **Nothing is
written until you press Create company.**

## If you already have it

It looks for an existing company with that website or LinkedIn page before
offering the form. When it finds one it says so and links to it, so a second
click on the same bookmark opens the record rather than making a duplicate.

Related: [Enrich](/help/enrich), [Companies](/help/companies), [Import](/help/import)
