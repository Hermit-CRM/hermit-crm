"""One-click capture: turn the page you are looking at into a company record.

`fetch <slug> --url` already reads a website or LinkedIn page and proposes
values, but it runs backwards for capture: you must create the company first and
then point it at a page. The wedge a solo CRM actually loses to is the record
that never gets made at all, so this inverts it -- hand it a URL, and it comes
back with a filled-in company form.

No browser extension: a bookmarklet opens the running app with the current URL
in the query string. Nothing to install, nothing to review, and it works in any
browser that has a bookmarks bar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
    name: str = ""
    fields: dict = field(default_factory=dict)
    notes: str = ""
    existing: Company | None = None  # already in the CRM, so do not make a second

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


def from_url(store: Store, url: str, fetcher=scrape.fetch,
             custom_keys=()) -> Capture:
    """Read a page and come back with a company ready to create.

    Raises ScrapeError when the page cannot be read; the caller shows the reason
    and lets the URL be typed by hand. Nothing is written here.
    """
    url = normalise_website((url or "").strip())
    if not url:
        raise scrape.ScrapeError("no URL given")
    facts = scrape.parse_page(url, fetcher(url))
    # A blank company has every field empty, so nothing is skipped as "already set".
    proposal = scrape.propose_from_facts(Company(name="", slug=""), facts,
                                         custom_keys=custom_keys)
    fields = dict(proposal.fields)
    return Capture(url=url, name=company_name(facts, url), fields=fields,
                   notes=proposal.notes, existing=find_existing(store, url, fields))


def suggested_slug(name: str) -> str:
    """What the company's folder will be called, shown before it is made."""
    return slugify(name, strip_legal=True) if name else ""
