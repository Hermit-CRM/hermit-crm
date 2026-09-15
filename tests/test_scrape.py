"""Free enrichment from a page's own HTML; nothing here touches the network."""

import pytest

from owncrm.models import Company
from owncrm.scrape import ScrapeError, fetch, parse_page, propose_from_url

SITE = """<html lang="de"><head><title>Acme – Procurement AI</title>
<meta name="description" content="Acme automates   tail spend for buyers.">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization",
 "sameAs":["https://twitter.com/acme","https://www.linkedin.com/company/acme-gmbh/"],
 "address":{"addressCountry":"Germany"},"numberOfEmployees":{"value":42}}</script>
</head><body><a href="/about">About</a><a href="https://www.linkedin.com/company/acme-gmbh/">LI</a></body></html>"""

LINKEDIN = """<html><head><title>Quill | LinkedIn</title>
<meta property="og:description" content="Quill | 1,234 followers on LinkedIn. AI product team as a service. | Long text">
<script type="application/ld+json">{"@graph":[{"@type":"Organization","numberOfEmployees":{"value":45},
 "sameAs":"https://quillhq.io","address":{"addressCountry":"SE"}}]}</script></head><body></body></html>"""

BARE = "<html><head><title>Foo Ltd - Home</title></head><body>We employ 11-50 employees.</body></html>"


def test_parse_page_collects_title_description_links_and_jsonld():
    facts = parse_page("https://acme.de", SITE)
    assert facts.title == "Acme – Procurement AI"
    assert facts.description == "Acme automates tail spend for buyers."
    assert facts.lang == "de" and "/about" in facts.links
    assert facts.jsonld[0]["numberOfEmployees"] == {"value": 42}


def test_propose_from_website_fills_only_empty_fields():
    company = Company(name="Acme", slug="acme", country="CH")
    proposal = propose_from_url(company, "acme.de", fetcher=lambda url: SITE)
    assert proposal.fields == {
        "website": "https://acme.de",
        "linkedin": "https://www.linkedin.com/company/acme-gmbh",
        "fte_estimate": "~42",
        "product_oneliner": "Acme automates tail spend for buyers.",
    }
    assert "country" not in proposal.missing
    assert proposal.sources == ["https://acme.de"]
    assert "page title: Acme" in proposal.notes


def test_propose_from_linkedin_page():
    company = Company(name="Quill", slug="quill")
    proposal = propose_from_url(company, "https://www.linkedin.com/company/quill/?trk=x",
                                fetcher=lambda url: LINKEDIN)
    assert proposal.fields == {
        "website": "https://quillhq.io",
        "linkedin": "https://www.linkedin.com/company/quill",
        "country": "SE",
        "fte_estimate": "~45",
        "product_oneliner": "AI product team as a service.",
    }


def test_bare_page_uses_title_tld_and_employee_hint():
    company = Company(name="Foo", slug="foo")
    proposal = propose_from_url(company, "https://foo.co.uk", fetcher=lambda url: BARE)
    assert proposal.fields["country"] == "GB"
    assert proposal.fields["product_oneliner"] == "Foo Ltd"
    assert proposal.fields["fte_estimate"] == "11-50"
    assert "linkedin" not in proposal.fields
    assert "only the title and links were usable" in proposal.notes


def test_fetch_rejects_non_web_urls():
    with pytest.raises(ScrapeError):
        fetch("file:///etc/passwd")
    with pytest.raises(ScrapeError):
        fetch("not a url")
