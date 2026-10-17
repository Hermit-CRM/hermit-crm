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


# ------------------------------------------------- redirects, no network
# A site the user typed may redirect anywhere; only a public host is followed.

import email.message
import io
import urllib.request
import urllib.response

from hermitcrm import scrape

FAKE_DNS = {"www.example.com": "93.184.215.14", "example.org": "93.184.215.15",
            "intranet.example.com": "10.0.0.7", "meta.example.com": "169.254.169.254",
            "sneaky.example.com": "::ffff:127.0.0.1"}


def fake_resolve(host, port):
    if host not in FAKE_DNS:
        raise OSError("no such host")
    return [(None, None, None, "", (FAKE_DNS[host], 0))]


class FakeWeb(urllib.request.BaseHandler):
    """Answers every request from a table; nothing touches a socket."""

    handler_order = 100  # before urllib's own HTTP(S)Handler

    def __init__(self, pages):
        self.pages = pages  # url -> (status, {header: value}, body)
        self.asked = []

    def _answer(self, req):
        self.asked.append(req.full_url)
        status, headers, body = self.pages[req.full_url]
        msg = email.message.Message()
        for key, value in headers.items():
            msg[key] = value
        resp = urllib.response.addinfourl(io.BytesIO(body), msg, req.full_url, status)
        resp.msg = "OK" if status == 200 else "Found"
        return resp

    http_open = https_open = _answer


def use_fake_web(monkeypatch, pages):
    web = FakeWeb(pages)
    monkeypatch.setattr(scrape, "_opener", lambda: urllib.request.build_opener(
        scrape._RedirectGuard(resolve=fake_resolve), web))
    return web


HTML = {"Content-Type": "text/html; charset=utf-8"}


@pytest.mark.parametrize("target", [
    "http://127.0.0.1:8765/settings",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://intranet.example.com/wiki",
    "http://meta.example.com/",
    "http://sneaky.example.com/",
])
def test_fetch_refuses_a_redirect_to_a_non_public_host(monkeypatch, target):
    web = use_fake_web(monkeypatch, {
        "https://www.example.com/": (302, {"Location": target}, b""),
        target: (200, HTML, b"<title>secret</title>"),
    })
    with pytest.raises(ScrapeError, match="only follows a redirect to a public website"):
        fetch("https://www.example.com/")
    assert web.asked == ["https://www.example.com/"]


def test_fetch_follows_a_redirect_to_a_public_host(monkeypatch):
    web = use_fake_web(monkeypatch, {
        "http://www.example.com/": (301, {"Location": "https://example.org/home"}, b""),
        "https://example.org/home": (200, HTML, b"<title>Acme</title>"),
    })
    assert "Acme" in fetch("http://www.example.com/")
    assert web.asked == ["http://www.example.com/", "https://example.org/home"]


def test_fetch_still_reads_an_intranet_address_the_user_typed(monkeypatch):
    use_fake_web(monkeypatch, {
        "http://intranet.example.com/": (200, HTML, b"<title>Our wiki</title>"),
        "http://10.0.0.7/": (200, HTML, b"<title>By number</title>"),
    })
    assert "Our wiki" in fetch("http://intranet.example.com/")
    assert "By number" in fetch("http://10.0.0.7/")


def test_a_refused_redirect_reaches_read_website_as_a_plain_error(monkeypatch):
    from hermitcrm import textsource
    use_fake_web(monkeypatch, {
        "https://www.example.com/": (302, {"Location": "http://127.0.0.1:8765/"}, b""),
    })
    with pytest.raises(textsource.SourceError) as info:
        textsource.read_website("https://www.example.com/")
    assert "public website" in str(info.value)


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
