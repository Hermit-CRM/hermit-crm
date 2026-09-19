"""Capture: a URL in, a filled-in company form out. Nothing is written here."""

import pytest

from hermitcrm import capture, scrape
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
    assert values["linkedin"] == "https://www.linkedin.com/in/ines-vega"


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


# Logged out, LinkedIn's structured data masks an ordinary member's job titles
# and sends them as a list. Both reached the title field as "['*****', ...]".
MASKED = """<html><head>
<title>Ines Vega - Harbour Light Labs | LinkedIn</title>
<meta property="og:description" content="Execution, not leads &middot; Experience: Harbour Light Labs">
<script type="application/ld+json">{"@context":"http://schema.org","@graph":[{"@type":"Person",
 "name":"Ines Vega","jobTitle":["********** *** ***","******* ****"],
 "worksFor":[{"@type":"Organization","name":"Harbour Light Labs"}]}]}</script>
</head><body></body></html>"""


def test_masked_job_titles_are_dropped_not_written_as_a_list(store):
    found = capture.from_url(store, "https://www.linkedin.com/in/ines-vega/",
                             fetcher=lambda u: MASKED)
    assert found.contact_values["title"] == "Execution, not leads"


def test_a_list_of_job_titles_gives_the_first(store):
    page = MASKED.replace('"********** *** ***","******* ****"',
                          '"Head of Compliance","Board member"')
    found = capture.from_url(store, "https://www.linkedin.com/in/ines-vega/",
                             fetcher=lambda u: page)
    assert found.contact_values["title"] == "Head of Compliance"


def test_the_profile_address_is_stored_in_one_form(store):
    found = person(store, "https://nl.linkedin.com/in/ines-vega/overlay/contact-info/")
    assert found.contact_values["linkedin"] == "https://www.linkedin.com/in/ines-vega"


def test_someone_you_have_is_found_from_any_page_of_their_profile(store):
    company = store.create_company("Harbour Light Labs")
    store.create_contact(company.slug, "Ines", "Vega",
                         linkedin="https://nl.linkedin.com/in/ines-vega?trk=abc")
    found = person(store, "https://www.linkedin.com/in/ines-vega/details/experience/")
    assert found.existing is not None and found.existing.slug == "harbour-light-labs"
    assert capture.contact_slug_in(found.existing, found.url) == "ines-vega"


def test_someone_you_have_is_found_without_asking_linkedin(store):
    company = store.create_company("Harbour Light Labs")
    store.create_contact(company.slug, "Ines", "Vega",
                         linkedin="https://www.linkedin.com/in/ines-vega")

    def must_not_fetch(url):
        raise AssertionError(f"fetched {url}")

    found = capture.from_url(store, "https://www.linkedin.com/in/ines-vega/",
                             fetcher=must_not_fetch)
    assert found.existing is not None and found.existing.slug == "harbour-light-labs"


def test_a_profile_linkedin_will_not_show_still_makes_a_contact_form(store):
    """HTTP 999 used to end in an error page. The address still gives a person."""
    def refuse(url):
        raise ScrapeError("LinkedIn refused the anonymous request (HTTP 999)")

    found = capture.from_url(store, "https://www.linkedin.com/in/ines-vega-8a1b2c3d/",
                             fetcher=refuse)
    assert found.kind == "person"
    values = found.contact_values
    assert values["name"] == "Ines Vega"
    assert values["linkedin"] == "https://www.linkedin.com/in/ines-vega-8a1b2c3d"
    assert values["company"] == "" and values["title"] == ""
    assert "HTTP 999" in found.fetch_error
    assert store.companies == {}


def test_a_company_page_linkedin_will_not_show_is_still_an_error(store):
    def refuse(url):
        raise ScrapeError("LinkedIn refused the anonymous request (HTTP 999)")

    with pytest.raises(ScrapeError):
        capture.from_url(store, "https://www.linkedin.com/company/harbour-light-labs/",
                         fetcher=refuse)


# ------------------------------------------------ what the bookmarklet read
# Logged in, the page you are looking at has everything; the bookmarklet sends
# pieces of it (v=2) and nothing is fetched. These are the parts no layout
# change moves: the h1, a mailto link, links to company pages.

READ = {"v": "2", "h1": "Ines Vega",
        "co": "https://www.linkedin.com/company/1234567/|Harbour Light Labs logo",
        "mail": "ines@harbourlight.example"}


def test_a_page_read_in_the_browser_makes_a_contact_without_a_fetch(store):
    found = capture.from_page(store, "https://www.linkedin.com/in/ines-vega/", READ)
    assert found.kind == "person"
    values = found.contact_values
    assert values["name"] == "Ines Vega"
    assert values["email"] == "ines@harbourlight.example"
    assert values["linkedin"] == "https://www.linkedin.com/in/ines-vega"
    assert values["company"] == "Harbour Light Labs"
    assert values["company_linkedin"] == "https://www.linkedin.com/company/1234567"
    assert store.companies == {}


def test_the_employer_is_found_by_its_linkedin_page_before_its_name(store):
    store.create_company("Harbour Light Labs B.V.",
                         linkedin="https://www.linkedin.com/company/1234567")
    found = capture.from_page(store, "https://www.linkedin.com/in/ines-vega/", READ)
    assert found.company is not None and found.company.slug == "harbour-light-labs"
    assert found.contact_values["company"] == "Harbour Light Labs B.V."


def test_someone_you_have_is_found_from_what_the_page_sent(store):
    company = store.create_company("Harbour Light Labs")
    store.create_contact(company.slug, "Ines", "Vega",
                         linkedin="https://www.linkedin.com/in/ines-vega")
    found = capture.from_page(store, "https://www.linkedin.com/in/ines-vega/overlay/contact-info/",
                              READ)
    assert found.existing is not None and found.existing.slug == "harbour-light-labs"


def test_a_page_that_sent_nothing_still_gives_the_name_in_its_address(store):
    """Clicked before the profile had loaded: the address is all there is."""
    found = capture.from_page(store, "https://www.linkedin.com/in/ines-vega-8a1b2c3d/",
                              {"v": "2"})
    assert found.contact_values["name"] == "Ines Vega"
    assert found.read_nothing
    assert found.contact_values["company"] == ""


@pytest.mark.parametrize("mail,want", [
    ("not an address", ""),
    ("javascript:alert(1)", ""),
    ("a@b.example?subject=hi", "a@b.example"),
    ("mailto:a@b.example", "a@b.example"),
    ("A@B.example ", "A@B.example"),
])
def test_only_a_plain_email_address_is_taken(store, mail, want):
    found = capture.from_page(store, "https://www.linkedin.com/in/ines-vega/",
                              {**READ, "mail": mail})
    assert found.contact_values["email"] == want


# The top card and Experience as a logged-in tab's innerText gives them:
# pronouns and the connection degree on lines of their own, and every
# Experience line twice (once for the eye, once for screen readers).
TOP = """Ines Vega

She/Her
· 2nd
Head of Compliance | DORA, ISO 27001 | ex-Big Four
Harbour Light Labs
TU Delft
Rotterdam, South Holland, Netherlands
·
Contact info
500+ connections
Message
Connect
More"""

EXP_SINGLE = """Experience
Experience
Head of Compliance
Head of Compliance
Harbour Light Labs · Full-time
Harbour Light Labs · Full-time
Jan 2023 - Present · 2 yrs 9 mos
Jan 2023 - Present · 2 yrs 9 mos
Rotterdam, Netherlands
Compliance Officer
Compliance Officer
Old Bank · Full-time"""

EXP_GROUPED = """Experience
Harbour Light Labs
Harbour Light Labs
Full-time · 5 yrs 2 mos
Full-time · 5 yrs 2 mos
Head of Compliance
Head of Compliance
Jan 2023 - Present · 2 yrs 9 mos
Compliance Lead
Compliance Lead"""

LABELS = ("Current company: Harbour Light Labs. Click to skip to experience card\n"
          "Education: TU Delft. Click to skip to education card")

PAGE = {"v": "2", "h1": "Ines Vega", "top": TOP, "exp": EXP_SINGLE, "lab": LABELS,
        "co": "https://www.linkedin.com/company/1234567/|Harbour Light Labs logo\n"
              "https://www.linkedin.com/company/7654321/|Old Bank logo"}


def read(**changes):
    return scrape.person_from_page({**PAGE, **changes})


def test_the_headline_is_the_line_under_the_name_not_pronouns_or_degree():
    assert read().headline == "Head of Compliance | DORA, ISO 27001 | ex-Big Four"


def test_the_employer_is_the_current_company_the_page_labels():
    person = read()
    assert person.employer == "Harbour Light Labs"
    assert person.company_linkedin == "https://www.linkedin.com/company/1234567"


def test_the_location_is_the_line_before_contact_info():
    assert read().location == "Rotterdam, South Holland, Netherlands"


def test_the_position_is_the_first_role_in_experience():
    assert read().position == "Head of Compliance"


def test_the_position_is_found_under_a_company_with_several_roles():
    assert read(exp=EXP_GROUPED).position == "Head of Compliance"


def test_the_title_is_the_position_rather_than_the_headline(store):
    found = capture.from_page(store, "https://www.linkedin.com/in/ines-vega/", PAGE)
    assert found.contact_values["title"] == "Head of Compliance"


def test_without_labels_the_first_company_in_experience_is_the_employer():
    person = read(lab="")
    assert person.employer == "Harbour Light Labs"
    assert person.company_linkedin == "https://www.linkedin.com/company/1234567"


def test_a_dutch_interface_reads_the_same():
    person = read(lab="Huidig bedrijf: Harbour Light Labs. Klik om naar de ervaringskaart "
                      "te gaan", top=TOP.replace("Contact info", "Contactgegevens"))
    assert person.employer == "Harbour Light Labs"
    assert person.location == "Rotterdam, South Holland, Netherlands"


def test_a_company_page_that_is_not_the_employer_is_never_attached():
    person = read(co="https://www.linkedin.com/company/7654321/|Old Bank logo")
    assert person.employer == "Harbour Light Labs"
    assert person.company_linkedin == ""


def test_a_page_that_is_not_laid_out_as_expected_leaves_fields_empty():
    """LinkedIn will change its layout. Then fields stay empty, never wrong."""
    person = read(top="Ines Vega", exp="", lab="", co="")
    assert (person.name, person.headline, person.employer, person.location,
            person.position) == ("Ines Vega", "", "", "", "")


def test_the_company_and_school_lines_are_never_the_headline():
    """Some layouts print the company and school block above the headline."""
    top = ("Ines Vega\nHarbour Light Labs\nTU Delft\nHead of Compliance | DORA\n"
           "Rotterdam, South Holland, Netherlands\nContact info")
    assert read(top=top).headline == "Head of Compliance | DORA"


def test_a_school_right_before_contact_info_is_not_a_location():
    top = "Ines Vega\nHead of Compliance | DORA\nTU Delft\nContact info"
    person = read(top=top)
    assert person.location == "" and person.headline == "Head of Compliance | DORA"


def test_a_name_sharing_its_line_with_pronouns_still_anchors_the_headline():
    """LinkedIn's h1 has been display:inline: the name, pronouns and degree
    then come out as one line of innerText."""
    top = ("Ines Vega She/Her · 2nd\nHead of Compliance | DORA\n"
           "Rotterdam, South Holland, Netherlands\nContact info")
    assert read(top=top).headline == "Head of Compliance | DORA"


def test_without_the_name_in_the_top_card_there_is_no_headline_guess():
    top = "Open to work\nHead of Compliance | DORA\nRotterdam\nContact info"
    assert read(top=top).headline == ""


def test_a_label_without_its_click_sentence_still_names_the_company():
    person = read(lab="Current company: Harbour Light Labs",
                  co="https://www.linkedin.com/company/7654321/|Old Bank logo")
    assert person.employer == "Harbour Light Labs"


def test_a_location_on_one_line_with_contact_info_is_read():
    """The location, a separator and the Contact info link are inline elements
    in one block, so innerText can give them as a single line."""
    top = ("Ines Vega\nHead of Compliance | DORA\n"
           "Rotterdam, South Holland, Netherlands · Contact info\n500+ connections")
    person = read(top=top)
    assert person.location == "Rotterdam, South Holland, Netherlands"
    assert person.headline == "Head of Compliance | DORA"


def test_an_entity_linkedin_encoded_twice_is_read_as_the_character(store):
    """Seen on a real profile: the description said "I&amp;#39;ve spent..."."""
    page = PROFILE.replace("Most teams do not have", "I&amp;#39;ve seen most teams not have")
    found = capture.from_url(store, "https://www.linkedin.com/in/ines-vega/",
                             fetcher=lambda u: page)
    assert found.contact_values["title"].startswith("I've seen most teams")


# LinkedIn's newer profile layout has no <h1> and no #experience: the
# bookmarklet then sends the page's whole text, and the name comes from the
# tab's title, which still reads "Name | LinkedIn".
@pytest.mark.parametrize("title,want", [
    ("Ines Vega | LinkedIn", "Ines Vega"),
    ("(3) Ines Vega | LinkedIn", "Ines Vega"),
    ("(99+) Ines Vega | LinkedIn", "Ines Vega"),
    ("LinkedIn", ""),
    ("", ""),
])
def test_without_a_heading_the_name_comes_from_the_tab_title(title, want):
    assert read(h1="", title=title).name == want


WHOLE = ("Skip to main content\nHome\nMy Network\nJobs\nMessaging\n"
         + TOP + "\nAbout\nI help banks stay compliant.\nActivity\n1,204 followers\n"
         + EXP_SINGLE)


def test_the_whole_page_text_reads_like_the_top_card():
    person = read(h1="", title="Ines Vega | LinkedIn", top=WHOLE)
    assert person.name == "Ines Vega"
    assert person.headline == "Head of Compliance | DORA, ISO 27001 | ex-Big Four"
    assert person.location == "Rotterdam, South Holland, Netherlands"
    assert person.position == "Head of Compliance"


def test_a_title_alone_gives_the_name_but_says_nothing_was_read(store):
    found = capture.from_page(store, "https://www.linkedin.com/in/ines-vega-8a1b2c3d/",
                              {"v": "2", "title": "Ines Vega | LinkedIn"})
    assert found.contact_values["name"] == "Ines Vega"
    assert found.read_nothing


def test_a_page_that_sent_its_text_is_not_reported_empty(store):
    found = capture.from_page(store, "https://www.linkedin.com/in/ines-vega/",
                              {"v": "2", "title": "Ines Vega | LinkedIn", "top": WHOLE,
                               "co": PAGE["co"]})
    assert not found.read_nothing
    assert found.contact_values["title"] == "Head of Compliance"
