"""One-click capture: turn the page you are looking at into a company record.

`fetch <slug> --url` already reads a website or LinkedIn page and proposes
values, but it runs backwards for capture: you must create the company first and
then point it at a page. The wedge a solo CRM actually loses to is the record
that never gets made at all, so this inverts it -- hand it a URL, and it comes
back with a filled-in company form.

No browser extension: a bookmarklet opens the running app with the current URL
in the query string. Nothing to install, nothing to review, and it works in any
browser that has a bookmarks bar. On a LinkedIn profile it also sends pieces of
the page you are looking at (static/bookmarklet.js): logged in, your tab shows
everything, and a fetch from here, logged out, gets next to nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import scrape
from .models import Company, normalise_website, slugify
from .store import Store

# Words a site puts in <title> around the actual name: "Acme | Home", "Acme -
# Churn analytics for SaaS". Splitting on these beats using the whole title.
TITLE_SPLIT = re.compile(r"\s+[|–—·-]\s+")

# Bits of a <title> that are never a company name.
TITLE_NOISE = {"home", "homepage", "welcome", "index", "official site",
               "official website", "start", "startpagina", "accueil", "startseite"}


@dataclass
class Capture:
    """What a URL gave us, before anything is written."""

    url: str
    kind: str = "company"            # company | person
    name: str = ""
    fields: dict = field(default_factory=dict)
    notes: str = ""
    existing: Company | None = None  # already in the CRM, so do not make a second
    person: scrape.PersonFacts | None = None
    company: Company | None = None   # the employer, when we already have it
    fetch_error: str = ""            # why the page itself could not be read
    read_nothing: bool = False       # the bookmarklet ran, but the page gave nothing

    @property
    def contact_values(self) -> dict:
        """The new-contact form's values, prefilled from a profile page.

        The company is a name rather than a slug: that form already matches a
        typed name against the companies you have, falls back to the email
        domain and otherwise creates one, and it is the same journey whether
        you typed the name or a page suggested it.
        """
        p = self.person or scrape.PersonFacts()
        have = self.company is not None
        return {
            "name": p.name,
            "email": p.email,
            # "Head of Compliance" from Experience says more than a headline
            "title": p.position or p.headline,
            "linkedin": self.url,
            "company": self.company.name if have else p.employer,
            "website": self.company.website if have else "",
            "company_linkedin": "" if have else p.company_linkedin,
        }

    @property
    def values(self) -> dict:
        """The company form's values dict, prefilled."""
        blank = {
            "name": "", "website": "", "linkedin": "", "country": "", "source": "other",
            "stage": "prospect", "lost_reason": "", "requalify_on": "",
            "value_eur_month": "", "product_oneliner": "",
            "next_step": "", "next_step_due": "",
            "next_step_status": "open", "tags": "", "notes": "",
        }
        return {**blank, **self.fields, "name": self.name}


def host(url: str) -> str:
    """The registrable-ish host of a URL, lowercased and without www."""
    netloc = urlparse(normalise_website(url or "")).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def company_name(facts: scrape.PageFacts, url: str) -> str:
    """The best guess at the company's name from a page.

    og:site_name is what a site calls itself and is right when present. A title
    is usually "Name | tagline", so the first segment beats the whole string,
    and a segment that is only "Home" is worth stepping over. The host without
    its suffix is the last resort, and is what a person would have typed anyway.
    """
    if facts.site_name.strip():
        return facts.site_name.strip()
    parts = [p.strip() for p in TITLE_SPLIT.split(facts.title) if p.strip()]
    for part in parts:
        if part.lower() not in TITLE_NOISE:
            return part
    name = host(url).split(".")[0]
    return name.replace("-", " ").title() if name else ""


def find_existing(store: Store, url: str, fields: dict) -> Company | None:
    """A company already holding this website or LinkedIn page.

    Capture from a page you have already saved should take you to the record you
    have, not quietly open a second one next to it.
    """
    wanted = {h for h in (host(url), host(fields.get("website", "")),
                          host(fields.get("linkedin", ""))) if h}
    linkedin = (fields.get("linkedin") or "").rstrip("/").lower()
    for company in store.companies.values():
        if company.website and host(company.website) in wanted:
            return company
        if company.linkedin:
            if host(company.linkedin) in wanted and "linkedin.com" not in host(company.linkedin):
                return company
            if linkedin and company.linkedin.rstrip("/").lower() == linkedin:
                return company
    return None


def company_by_name(store: Store, name: str) -> Company | None:
    """An existing company with this name, case- and suffix-insensitively."""
    name = (name or "").strip()
    if not name:
        return None
    wanted = slugify(name, strip_legal=True)
    for company in store.companies.values():
        if company.slug == wanted or company.name.strip().lower() == name.lower():
            return company
    return None


def from_url(store: Store, url: str, fetcher=scrape.fetch,
             custom_keys=()) -> Capture:
    """Read a page and come back with a record ready to create.

    A profile page makes a *contact*, with the company it names beside it; any
    other page makes a company. Raises ScrapeError when the page cannot be
    read; the caller shows the reason and lets the URL be typed by hand.
    Nothing is written here.
    """
    url = normalise_website((url or "").strip())
    if not url:
        raise scrape.ScrapeError("no URL given")
    if scrape.PERSON_URL.search(url):
        return profile(store, url, fetcher)
    facts = scrape.parse_page(url, fetcher(url))
    if scrape.is_person_page(facts):
        person = scrape.person_from(facts)
        return Capture(url=url, kind="person", name=person.name, person=person,
                       company=company_by_name(store, person.employer),
                       existing=contact_holding(store, url))
    # A blank company has every field empty, so nothing is skipped as "already set".
    proposal = scrape.propose_from_facts(Company(name="", slug=""), facts,
                                         custom_keys=custom_keys)
    fields = dict(proposal.fields)
    return Capture(url=url, name=company_name(facts, url), fields=fields,
                   notes=proposal.notes, existing=find_existing(store, url, fields))


def profile(store: Store, url: str, fetcher=scrape.fetch) -> Capture:
    """A profile page: someone you have, or a contact form, never a dead end.

    The CRM is asked before LinkedIn is: someone already saved needs no
    request at all. A page that will not show itself logged out (LinkedIn's
    HTTP 999) still leaves the address, and usually a name spelled in it, so
    the form opens with those rather than an error.
    """
    url = scrape.profile_url(url)
    saved = already_saved(store, url)
    if saved is not None:
        return saved
    try:
        facts = scrape.parse_page(url, fetcher(url))
    except scrape.ScrapeError as exc:
        person = scrape.PersonFacts(name=scrape.name_from_handle(url))
        # The fetch's advice ("use the company website instead") is for company
        # pages; for a person the form says what to do.
        return Capture(url=url, kind="person", name=person.name, person=person,
                       fetch_error=str(exc).split(";")[0])
    person = scrape.person_from(facts)
    return Capture(url=url, kind="person", name=person.name, person=person,
                   company=company_by_name(store, person.employer))


def from_page(store: Store, url: str, page: dict) -> Capture:
    """A profile read by the bookmarklet in your own, logged-in browser tab.

    Nothing is fetched: the page you are looking at is the best source there
    is, and asking LinkedIn again, logged out, only gets less. The employer is
    matched by its LinkedIn page first, since names drift ("Acme" and
    "Acme B.V."), and by name after that.
    """
    url = scrape.profile_url(normalise_website((url or "").strip()))
    saved = already_saved(store, url)
    if saved is not None:
        return saved
    person = scrape.person_from_page(page)
    empty = not person.name
    if empty:
        person.name = scrape.name_from_handle(url)
    company = (company_by_linkedin(store, person.company_linkedin)
               or company_by_name(store, person.employer))
    return Capture(url=url, kind="person", name=person.name, person=person,
                   company=company, read_nothing=empty)


def already_saved(store: Store, url: str) -> Capture | None:
    """Someone with this profile already in the CRM, as a capture that says so."""
    existing = contact_holding(store, url)
    if existing is None:
        return None
    contact = existing.contacts[contact_slug_in(existing, url)]
    return Capture(url=url, kind="person", name=contact.name, existing=existing)


def company_by_linkedin(store: Store, url: str) -> Company | None:
    """An existing company with this LinkedIn company page."""
    wanted = scrape.company_page_url(url).lower()
    if not wanted:
        return None
    for company in store.companies.values():
        if company.linkedin and scrape.company_page_url(company.linkedin).lower() == wanted:
            return company
    return None


def same_profile(a: str, b: str) -> bool:
    """Two addresses of one profile, whichever page of it each came from."""
    def key(url):
        return scrape.profile_url(url or "").rstrip("/").lower()
    return bool(a and b) and key(a) == key(b)


def contact_holding(store: Store, url: str) -> Company | None:
    """The company of a contact who already has this profile URL.

    Capturing someone you have already saved should take you to them, the same
    way capturing a company you have takes you to the company.
    """
    for company in store.companies.values():
        if contact_slug_in(company, url):
            return company
    return None


def contact_slug_in(company: Company, url: str) -> str:
    for contact in company.contacts.values():
        if same_profile(contact.linkedin, url):
            return contact.slug
    return ""


BOOKMARKLET_JS = Path(__file__).parent / "static" / "bookmarklet.js"


def bookmarklet(base: str) -> str:
    """The bookmarklet for an app answering at `base`, as one line.

    static/bookmarklet.js is written to survive this: its comments are whole
    lines, and every statement ends in ";", so lines join with a space.
    """
    lines = (line.strip() for line in BOOKMARKLET_JS.read_text(encoding="utf-8").splitlines())
    code = " ".join(line for line in lines if line and not line.startswith("//"))
    return "javascript:" + code.replace("__BASE__", base)


def suggested_slug(name: str) -> str:
    """What the company's folder will be called, shown before it is made."""
    return slugify(name, strip_legal=True) if name else ""
