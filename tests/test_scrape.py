# Copyright 2026 Gijs Bos
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Free enrichment from a page's own HTML; nothing here touches the network."""

import pytest

from hermitcrm.models import Company
from hermitcrm.scrape import (ScrapeError, company_page_url, fetch, name_from_handle,
                             parse_page, profile_url, propose_from_url)

SITE = """<html lang="de"><head><title>Acme – Procurement AI</title>
<meta name="description" content="Acme automates   tail spend for buyers.">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization",
 "sameAs":["https://twitter.com/acme","https://www.linkedin.com/company/acme-gmbh/"],
 "address":{"addressCountry":"Germany"},"numberOfEmployees":{"value":42}}</script>
</head><body><a href="/about">About</a><a href="https://www.linkedin.com/company/acme-gmbh/">LI</a></body></html>"""

LINKEDIN = """<html><head><title>Quill | LinkedIn</title>
<meta property="og:description" content="Quill | 1,234 followers on LinkedIn. Bookkeeping for small breweries. | Long text">
<script type="application/ld+json">{"@graph":[{"@type":"Organization","numberOfEmployees":{"value":45},
 "sameAs":"https://quillhq.example","address":{"addressCountry":"SE"}}]}</script></head><body></body></html>"""

BARE = "<html><head><title>Foo Ltd - Home</title></head><body>We employ 11-50 employees.</body></html>"


def test_parse_page_collects_title_description_links_and_jsonld():
    facts = parse_page("https://acme.de", SITE)
    assert facts.title == "Acme – Procurement AI"
    assert facts.description == "Acme automates tail spend for buyers."
    assert facts.lang == "de" and "/about" in facts.links
    assert facts.jsonld[0]["numberOfEmployees"] == {"value": 42}


def test_propose_from_website_fills_only_empty_fields():
    company = Company(name="Acme", slug="acme", country="CH")
    proposal = propose_from_url(company, "acme.de", fetcher=lambda url: SITE,
                                custom_keys={"fte_estimate"})
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
                                custom_keys={"fte_estimate"},
                                fetcher=lambda url: LINKEDIN)
    assert proposal.fields == {
        "website": "https://quillhq.example",
        "linkedin": "https://www.linkedin.com/company/quill",
        "country": "SE",
        "fte_estimate": "~45",
        "product_oneliner": "Bookkeeping for small breweries.",
    }


def test_bare_page_uses_title_tld_and_employee_hint():
    company = Company(name="Foo", slug="foo")
    proposal = propose_from_url(company, "https://foo.co.uk", fetcher=lambda url: BARE,
                                custom_keys={"fte_estimate"})
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


# ------------------------------------------------------ LinkedIn addresses
# One person, many addresses: the bookmarklet sends whatever the tab shows,
# and "already in the CRM" only works if all of them come out the same.

@pytest.mark.parametrize("given,want", [
    ("https://www.linkedin.com/in/ines-vega/", "https://www.linkedin.com/in/ines-vega"),
    ("https://www.linkedin.com/in/ines-vega", "https://www.linkedin.com/in/ines-vega"),
    ("https://nl.linkedin.com/in/ines-vega/", "https://www.linkedin.com/in/ines-vega"),
    ("http://linkedin.com/in/ines-vega?originalSubdomain=nl",
     "https://www.linkedin.com/in/ines-vega"),
    ("https://www.linkedin.com/in/ines-vega/overlay/contact-info/",
     "https://www.linkedin.com/in/ines-vega"),
    ("https://www.linkedin.com/in/ines-vega/details/experience/",
     "https://www.linkedin.com/in/ines-vega"),
    ("https://www.linkedin.com/in/ines-vega/?miniProfileUrn=urn%3Ali%3Afs_miniProfile%3AACoAAB",
     "https://www.linkedin.com/in/ines-vega"),
    ("www.linkedin.com/in/ines-vega/#experience", "https://www.linkedin.com/in/ines-vega"),
    ("https://www.linkedin.com/in/j%C3%B6rg-m%C3%BCller-4b2a/",
     "https://www.linkedin.com/in/j%C3%B6rg-m%C3%BCller-4b2a"),
])
def test_a_profile_has_one_address_whichever_page_it_came_from(given, want):
    assert profile_url(given) == want


@pytest.mark.parametrize("given", [
    "https://acme.example.com/about",
    "https://www.linkedin.com/company/acme/",
    "https://www.linkedin.com/feed/",
    "",
])
def test_anything_that_is_not_a_profile_is_left_alone(given):
    assert profile_url(given) == given


@pytest.mark.parametrize("given,want", [
    ("https://www.linkedin.com/company/1234567/", "https://www.linkedin.com/company/1234567"),
    ("https://www.linkedin.com/company/harbour-light-labs/life/?trk=x",
     "https://www.linkedin.com/company/harbour-light-labs"),
    ("https://nl.linkedin.com/company/harbour-light-labs",
     "https://www.linkedin.com/company/harbour-light-labs"),
    ("/company/1234567/", "https://www.linkedin.com/company/1234567"),
    ("https://www.linkedin.com/in/ines-vega/", ""),
    ("https://www.linkedin.com/school/tu-delft/", ""),
    ("javascript:alert(1)", ""),
    ("https://evil.example.com/company/acme", ""),
])
def test_a_company_page_address_is_cleaned_or_refused(given, want):
    assert company_page_url(given) == want


@pytest.mark.parametrize("url,want", [
    ("https://www.linkedin.com/in/ines-vega-8a1b2c3d/", "Ines Vega"),
    ("https://www.linkedin.com/in/ines-vega-654588385", "Ines Vega"),
    ("https://www.linkedin.com/in/ines-vega/", "Ines Vega"),
    ("https://www.linkedin.com/in/ines-van-der-berg-2/", "Ines van der Berg"),
    ("https://www.linkedin.com/in/j%C3%B6rg-m%C3%BCller/", "Jörg Müller"),
    ("https://www.linkedin.com/in/inesvega/", ""),       # one word: no guess
    ("https://www.linkedin.com/in/ACoAABx1y2z3/", ""),   # an internal id, not a name
    ("https://acme.example.com/", ""),
])
def test_a_name_is_guessed_from_the_address_only_when_it_spells_one(url, want):
    assert name_from_handle(url) == want


def test_an_address_built_from_a_link_keeps_only_url_characters():
    """The parts come from pages and queries that are not ours."""
    assert profile_url('https://www.linkedin.com/in/ines"><script>/') == \
        "https://www.linkedin.com/in/ines"
    assert company_page_url("https://www.linkedin.com/company/acme'onmouseover=x/") == \
        "https://www.linkedin.com/company/acme"
