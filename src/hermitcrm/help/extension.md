# Extension

`/extension`: turn the page you are looking at into a company record, in one
click, without typing the name twice.

The competition for a CRM is not another CRM, it is the record never getting
written. The extension is the short path: you are on a company's website or its
LinkedIn company page, you click one bookmark, and a new-company form opens
with the fields already filled in.

## A profile makes a contact

A LinkedIn or Xing profile is a person, not a company, so it opens the
new-contact form rather than the new-company one, with the employer typed into
the company box. That box matches what you have already, so capturing three
people from the same company puts all three on one record instead of making
three companies.

**On a LinkedIn profile you are logged in to, the bookmarklet reads the page
you are looking at.** Your tab already shows everything, so it sends pieces of
that page to Hermit CRM and nothing is fetched: no second request to LinkedIn,
no cookies copied, nothing an automation check could notice. It fills in:

- **name**, and **title**: the current role from Experience ("Head of
  Compliance"), or the headline when Experience is not on the page
- **company**: the one the page labels as the current company, and its
  **LinkedIn page**, which a new company keeps -- so the next colleague you
  capture lands on the same record, even if the names differ slightly
- **email**, only when you have opened *Contact info* (your 1st-degree
  connections) before clicking
- the **location**, shown above the form

It reads the order of the lines and the labels a screen reader gets, not
LinkedIn's class names, which change all the time. When LinkedIn moves things
around, a field it cannot place stays empty rather than wrong. If the form
comes up nearly empty, the profile had probably not finished loading: click
again once it has.

Logged out -- a pasted URL, or a bookmarklet taken before this version --
Hermit CRM fetches the profile itself, and LinkedIn shows an ordinary member
almost nothing that way: often HTTP 999, otherwise job titles masked as
`*****`. The form still opens, with the profile address and the name spelled
in it; take the bookmarklet again from this page to read the real thing. A
person's headline is never read as a company's one-liner -- that produced
sentences like "Most companies don't have a lead problem... - Experience: ...
- 500+ connections on LinkedIn", which is how the profile path was found.

## The bookmarklet

The `/extension` page has a link to drag to your bookmarks bar. It points at the
address this Hermit CRM is serving on, so take it again if you later run
`serve` on a different host or port. Some browsers refuse to run a bookmarklet
clicked from a page; dragging it to the bar first always works, and the code is
printed on the page to paste into a bookmark by hand.

There is also a plain box on the same page: paste a URL, press **Read the
page**. Same result, no bookmark.

## What it reads

On a LinkedIn profile, the page in your own tab (above). Anywhere else, the
page's own metadata, fetched by your machine directly: nothing is sent
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

A profile you have already saved opens that contact, whichever page of the
profile you clicked on: `/in/x/overlay/contact-info/`, `nl.linkedin.com/in/x`
and `/in/x?miniProfileUrn=...` are one person, stored as
`https://www.linkedin.com/in/x`. Nothing is fetched to find that out.

Related: [Enrich](/help/enrich), [Companies](/help/companies), [Import](/help/import)
