"""Capture: a URL in, a filled-in company form out. Nothing is written here."""

import pytest

from hermitcrm import capture
from hermitcrm.scrape import ScrapeError

PAGE = """<html><head>
<title>Northwind Robotics | Warehouse automation</title>
<meta property="og:site_name" content="Northwind Robotics">
<meta property="og:description" content="Robots that pick and pack for mid-size warehouses.">
</head><body>
<a href="https://www.linkedin.com/company/northwind-robotics">LinkedIn</a>
<p>We are 11-50 employees in Rotterdam, Netherlands.</p>
</body></html>"""


def page(text=PAGE):
    return lambda url, **kwargs: text


def test_a_page_becomes_a_company_ready_to_create(store):
    found = capture.from_url(store, "northwind.example.com", fetcher=page())

    assert found.name == "Northwind Robotics"
    assert found.fields["website"] == "https://northwind.example.com"
    assert found.fields["linkedin"] == "https://www.linkedin.com/company/northwind-robotics"
    assert found.fields["product_oneliner"].startswith("Robots that pick")
    assert found.existing is None
    assert capture.suggested_slug(found.name) == "northwind-robotics"
    # nothing was written
    assert store.companies == {}


def test_values_fill_the_company_form_and_leave_the_rest_blank(store):
    values = capture.from_url(store, "northwind.example.com", fetcher=page()).values

    assert values["name"] == "Northwind Robotics"
    assert values["stage"] == "prospect" and values["source"] == "other"
    assert values["next_step"] == "" and values["tags"] == ""


def test_capturing_a_page_you_already_have_finds_the_record(store):
    store.create_company(name="Northwind Robotics", website="https://northwind.example.com")

    found = capture.from_url(store, "https://northwind.example.com/pricing", fetcher=page())
    assert found.existing is not None and found.existing.slug == "northwind-robotics"


def test_the_linkedin_page_of_a_company_you_have_finds_it_too(store):
    store.create_company(name="Northwind Robotics",
                         linkedin="https://www.linkedin.com/company/northwind-robotics")

    found = capture.from_url(store, "northwind.example.com", fetcher=page())
    assert found.existing is not None and found.existing.slug == "northwind-robotics"


@pytest.mark.parametrize("title,expected", [
    ("Acme BV | Home", "Acme BV"),
    ("Home - Acme BV", "Acme BV"),
    ("Acme BV – Churn analytics", "Acme BV"),
    ("Acme BV", "Acme BV"),
])
def test_the_name_comes_out_of_a_messy_title(store, title, expected):
    html = f"<html><head><title>{title}</title></head><body></body></html>"
    assert capture.from_url(store, "acme.example.com", fetcher=page(html)).name == expected


def test_a_page_with_no_title_falls_back_to_the_host(store):
    html = "<html><head></head><body>nothing</body></html>"
    found = capture.from_url(store, "northwind-robotics.example.com", fetcher=page(html))
    assert found.name == "Northwind Robotics"


def test_no_url_is_an_error_not_a_fetch(store):
    with pytest.raises(ScrapeError):
        capture.from_url(store, "   ", fetcher=page())


def test_host_ignores_www_and_scheme():
    assert capture.host("https://www.acme.example.com/pricing") == "acme.example.com"
    assert capture.host("acme.example.com") == "acme.example.com"
    assert capture.host("") == ""


# ------------------------------------------------------------------- people

PROFILE = """<html><head>
<title>Ines Vega - Harbour Light Labs | LinkedIn</title>
<meta property="og:description" content="Most teams do not have a lead problem.
 They have an execution one\u2026 &middot; Experience: Harbour Light Labs
 &middot; Education: Someplace &middot; Location: Rotterdam &middot; 500+
 connections on LinkedIn. View Ines Vega&#39;s profile on LinkedIn.">
</head><body></body></html>"""


def person(store, url="https://www.linkedin.com/in/ines-vega/"):
    return capture.from_url(store, url, fetcher=lambda u: PROFILE)


def test_a_profile_makes_a_contact_not_a_company(store):
    """The reported bug: a LinkedIn profile opened a company form."""
    found = person(store)
    assert found.kind == "person" and found.name == "Ines Vega"
    values = found.contact_values
    assert values["name"] == "Ines Vega"
    assert values["company"] == "Harbour Light Labs"
    assert values["linkedin"] == "https://www.linkedin.com/in/ines-vega/"


def test_the_headline_is_the_title_and_never_the_product_oneliner(store):
    """The other half of the report: the one-liner it proposed was a profile blurb."""
    found = person(store)
    title = found.contact_values["title"]
    assert title.startswith("Most teams do not have a lead problem")
    assert "Experience:" not in title and "connections on LinkedIn" not in title
    assert "Education" not in title
    assert "product_oneliner" not in found.fields


def test_an_employer_already_in_the_crm_is_recognised(store):
    store.create_company("Harbour Light Labs")
    found = person(store)
    assert found.company is not None and found.company.slug == "harbour-light-labs"
    assert found.contact_values["company"] == "Harbour Light Labs"


def test_capturing_someone_you_already_have_finds_them(store):
    company = store.create_company("Harbour Light Labs")
    store.create_contact(company.slug, "Ines", "Vega",
                         linkedin="https://www.linkedin.com/in/ines-vega")
    found = person(store)
    assert found.existing is not None and found.existing.slug == "harbour-light-labs"
    assert capture.contact_slug_in(found.existing, found.url) == "ines-vega"


def test_a_company_page_is_still_a_company(store):
    found = capture.from_url(store, "acme.example.com",
                             fetcher=lambda u: "<html><head><title>Acme | Robots"
                                               "</title></head></html>")
    assert found.kind == "company" and found.name == "Acme"
