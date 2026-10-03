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

"""layout.toml: section order and visibility, hidden fields, list columns
(hermitcrm/layout.py, the templates that read it, and `hermitcrm check`)."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import cli, layout
from hermitcrm.store import Store
from hermitcrm.web import (LINKS, company_columns, company_values, contact_columns,
                           contact_values, create_app)
from conftest import FIXED_NOW

CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "owner_email": "me@example.com",
          "welcome_dismissed": True, "disclaimer_accepted": "2026-09-01T09:00:00"}

FIELDS = ('[[field]]\nkey = "fit_score"\nlabel = "fit"\ntype = "number"\n'
          'show_in = ["detail", "companies"]\n\n'
          '[[field]]\nkey = "segment"\nlabel = "segment"\ntype = "text"\n'
          'show_in = ["detail"]\n\n'
          '[[field]]\nkey = "seniority"\nlabel = "seniority"\ntype = "text"\n'
          'applies_to = "contact"\nshow_in = ["detail", "contacts"]\n')

COMPANY_MARKERS = {
    "enrich": 'class="small record-actions"', "next-step": 'class="small next-step-line',
    "details": 'id="details"', "contacts": 'id="contacts"', "tasks": 'id="tasks"',
    "drafts": 'id="drafts"', "merge": 'id="merge"', "timeline": 'id="timeline"',
}
CONTACT_MARKERS = {name: f'id="{name}"' for name in layout.SECTIONS["contact"]}
HOME_MARKERS = {name: f'id="{name}"' for name in layout.SECTIONS["home"]}


# ------------------------------------------------------------------- fixtures


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for args in (["init", "-b", "main"], ["config", "user.name", "CRM Test"],
                 ["config", "user.email", "crm@test.local"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    (tmp_path / "fields.toml").write_text(FIELDS, encoding="utf-8")
    return tmp_path


@pytest.fixture
def app(repo: Path):
    return create_app(repo, config=CONFIG, clock=lambda: FIXED_NOW)


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def acme(client, app):
    """One company with two contacts, a task, an inbound mail and custom values."""
    store = app.state.store
    store.create_company("Acme GmbH", website="https://acme.example", country="DE",
                         value_eur_month="900", custom={"fit_score": 80, "segment": "smb"})
    store.create_contact("acme", "Jane", "Doe", title="CTO", email="jane@acme.example",
                         custom={"seniority": "senior"})
    store.create_contact("acme", "Max", "Roe")
    store.create_interaction("acme", channel="email", direction="in", contact="jane-doe",
                             date=FIXED_NOW - timedelta(days=3), subject="Question",
                             body="Can you send the pricing?")
    store.add_task("acme", "send the pricing", due=FIXED_NOW.date())
    return store.get("acme")


def write_layout(repo: Path, text: str) -> None:
    path = repo / layout.FILENAME
    path.write_text(text, encoding="utf-8")
    # A second write within the same clock tick must still read as a change.
    stamp = path.stat().st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(stamp, stamp))


def order_of(page: str, markers: dict) -> list[str]:
    found = [(page.index(m), name) for name, m in markers.items() if m in page]
    return [name for _, name in sorted(found)]


def record_form(page: str) -> str:
    match = re.search(r'<form method="post" action="[^"]*" class="record-form">.*?</form>',
                      page, re.S)
    assert match, "no record form on the page"
    return match.group(0)


def form_names(page: str) -> set[str]:
    return set(re.findall(r'<(?:input|select|textarea)[^>]* name="([^"]+)"', record_form(page)))


def header_names(page: str) -> list[str]:
    head = page.split('<tr class="filters">')[0].split('<table class="filterable">')[1]
    return [re.sub(r"\s+", " ", h).strip()
            for h in re.findall(r"<th>([^<]*)", head)]


# ------------------------------------------------------------ reading the file


def test_no_file_is_the_default_layout(tmp_path):
    lay = layout.load(tmp_path)
    assert lay is layout.DEFAULT
    for page, names in layout.SECTIONS.items():
        assert lay.sections(page) == list(names)
    assert lay.hidden("company") == frozenset()
    assert layout.validate(tmp_path) == []
    assert layout.built_items(tmp_path) == []


def test_listed_sections_come_first_and_the_rest_keep_their_order():
    lay, problems = layout.parse({"company": {"sections": ["timeline", "contacts"],
                                              "hide_sections": ["merge"]}})
    assert problems == []
    assert lay.sections("company") == ["timeline", "contacts", "enrich", "next-step",
                                       "details", "tasks", "drafts"]
    assert lay.sections("contact") == list(layout.SECTIONS["contact"])


def test_problems_name_the_place_and_suggest_a_name():
    data = {
        "compnay": {"sections": ["timeline"]},
        "company": {"sections": ["timline", "details", "details", "merge"],
                    "hide_sections": ["merge"], "hide_fields": ["value_per_month", "name"],
                    "colums": ["name"]},
        "home": {"hide_sections": "owed"},
        "companies": {"columns": ["name", "fitscore", "country"]},
        "contacts": {"columns": []},
        "contact": 3,
    }
    lay, problems = layout.parse(data, defs=[])
    text = "\n".join(problems)
    assert "layout.toml: [compnay]: unknown table (did you mean company?)" in text
    assert ("layout.toml: [company] sections: unknown section timline "
            "(did you mean timeline?)") in text
    assert "layout.toml: [company] sections: details is listed twice" in text
    assert "layout.toml: [company]: section merge is in both sections and hide_sections" in text
    assert ("layout.toml: [company] hide_fields: unknown field value_per_month "
            "(did you mean value_eur_month?)") in text
    assert "layout.toml: [company] hide_fields: name is part of the page header" in text
    assert ("layout.toml: [company]: unknown key colums; known: sections, hide_sections, "
            "hide_fields") in text
    assert 'layout.toml: [home] hide_sections: must be a list of names in quotes' in text
    assert "layout.toml: [companies] columns: unknown column fitscore" in text
    assert "layout.toml: [contacts] columns: the list is empty" in text
    assert "layout.toml: contact: must be a table" in text
    # Whatever was wrong is left out; the rest still applies.
    assert lay.sections("company")[:2] == ["details", "enrich"]
    assert "merge" not in lay.sections("company")
    assert lay.hidden("company") == frozenset()
    assert lay.columns == {"companies": ("name", "country")}
    assert lay.sections("home") == list(layout.SECTIONS["home"])


def test_a_hidden_field_listed_as_a_column_is_named():
    _, problems = layout.parse({"company": {"hide_fields": ["country", "next_step_type"]},
                                "companies": {"columns": ["name", "country", "next_type"]}})
    assert problems == [
        "layout.toml: [companies] columns: country is hidden by hide_fields in [company], "
        "so it never shows",
        "layout.toml: [companies] columns: next_type is hidden by hide_fields in [company], "
        "so it never shows",
    ]


def test_custom_fields_are_known_through_fields_toml(repo):
    write_layout(repo, '[company]\nhide_fields = ["fit_score", "fit_scor"]\n'
                       '[contacts]\ncolumns = ["name", "seniority"]\n')
    assert layout.validate(repo) == [
        "layout.toml: [company] hide_fields: unknown field fit_scor (did you mean fit_score?)"]
    # The app does not judge custom names (it does not read fields.toml here):
    # an unknown one is kept and simply matches nothing.
    assert layout.load(repo).hidden("company") == {"fit_score", "fit_scor"}


def test_a_syntax_error_gives_the_line_and_the_default_layout(repo):
    write_layout(repo, '[company]\nsections = ["timeline"\nhide_fields = []\n')
    problems = layout.validate(repo)
    assert len(problems) == 1 and problems[0].startswith("layout.toml: line ")
    assert layout.load(repo) is layout.DEFAULT


def test_check_prints_layout_problems_and_fails(repo, capsys):
    Store(repo).load()
    write_layout(repo, '[company]\nsections = ["timline"]\n')
    assert cli.main(["check"], root=repo) == 1
    out = capsys.readouterr().out
    assert "layout.toml: [company] sections: unknown section timline (did you mean timeline?)" in out
    write_layout(repo, '[company]\nsections = ["timeline"]\n')
    assert cli.main(["check"], root=repo) == 0
    assert "no problems" in capsys.readouterr().out


def test_built_items_says_what_the_layout_changes(repo):
    write_layout(repo, '[company]\nsections = ["timeline"]\nhide_sections = ["merge"]\n'
                       'hide_fields = ["value_eur_month", "requalify_on"]\n'
                       '[companies]\ncolumns = ["name", "stage"]\n')
    [item] = layout.built_items(repo)
    assert item["kind"] == "layout" and item["title"] == "Page layout" and item["url"] == ""
    assert item["detail"] == ("company page: timeline first, merge hidden, 2 fields hidden; "
                              "Companies list: 2 columns chosen")
    assert "layout.toml" in item["adjust"]
    write_layout(repo, "")
    assert layout.built_items(repo)[0]["detail"] == "layout.toml changes nothing yet"


def test_the_column_lists_match_what_the_pages_build():
    built = [c.key for c in company_columns([], ["call"])] + [LINKS.key]
    assert tuple(built) == layout.COLUMNS["companies"]
    assert tuple(c.key for c in contact_columns([])) == layout.COLUMNS["contacts"]


# ------------------------------------------------------------------ the pages


PAGES = ["/", "/companies", "/contacts", "/companies/acme",
         "/companies/acme/contacts/jane-doe", "/companies/new",
         "/companies/acme/contacts/new", "/pipeline"]


def test_no_file_and_an_empty_file_render_the_same_pages(client, repo, acme):
    before = {url: client.get(url).text for url in PAGES}
    write_layout(repo, "# nothing changed yet\n[company]\n[contact]\n[home]\n")
    for url in PAGES:
        assert client.get(url).text == before[url], url


def test_every_built_in_form_field_is_hideable_or_part_of_the_header(client, app, acme):
    """layout.FIELDS must follow the forms: a new input is either hideable or
    named in HEADER_FIELDS, or the agent's recipe would be wrong."""
    app.state.task_types = []
    company = {n for n in form_names(client.get("/companies/acme").text)
               if not n.startswith("custom_")} - {"version"}
    assert company == set(layout.FIELDS["company"]) - {"next_step_type"} \
        | set(layout.HEADER_FIELDS["company"])
    contact = {n for n in form_names(client.get("/companies/acme/contacts/jane-doe").text)
               if not n.startswith("custom_")} - {"version"}
    assert contact == set(layout.FIELDS["contact"]) | set(layout.HEADER_FIELDS["contact"])


def test_default_section_order(client, acme):
    company = client.get("/companies/acme").text
    assert order_of(company, COMPANY_MARKERS) == list(layout.SECTIONS["company"])
    contact = client.get("/companies/acme/contacts/jane-doe").text
    assert order_of(contact, CONTACT_MARKERS) == list(layout.SECTIONS["contact"])
    home = client.get("/").text
    assert order_of(home, HOME_MARKERS) == ["doing", "owed", "going"]  # nothing to file


def test_sections_reorder_and_hide(client, repo, acme):
    write_layout(repo, '[company]\nsections = ["timeline", "tasks"]\nhide_sections = ["merge"]\n'
                       '[contact]\nsections = ["tasks"]\nhide_sections = ["delete", "drafts"]\n'
                       '[home]\nsections = ["going"]\nhide_sections = ["owed"]\n')
    company = client.get("/companies/acme").text
    assert order_of(company, COMPANY_MARKERS) == ["timeline", "tasks", "enrich", "next-step",
                                                  "details", "contacts", "drafts"]
    assert "/merge" not in company and "Can you send the pricing?" in company
    contact = client.get("/companies/acme/contacts/jane-doe").text
    assert order_of(contact, CONTACT_MARKERS) == ["tasks", "details", "timeline",
                                                  "quick-add", "merge"]
    assert "Delete contact" not in contact
    home = client.get("/").text
    assert order_of(home, HOME_MARKERS) == ["going", "doing"]
    assert "Replies you owe" not in home


def test_to_file_moves_on_home(client, repo, acme):
    (repo / "inbox").mkdir()
    (repo / "inbox" / "2026-09-13T0900-in-someone.md").write_text(
        "---\ndate: 2026-09-13T09:00\ndirection: in\naddress: someone@nowhere.example\n"
        "name: Some One\nsubject: Hello\nreason: no company matches\n---\nHi there.\n")
    assert order_of(client.get("/").text, HOME_MARKERS) == ["doing", "to-file", "owed", "going"]
    write_layout(repo, '[home]\nsections = ["to-file"]\n')
    assert order_of(client.get("/").text, HOME_MARKERS) == ["to-file", "doing", "owed", "going"]


def test_hidden_fields_leave_the_page_the_form_and_the_lists(client, repo, acme):
    company = client.get("/companies/acme").text
    assert 'noopener">acme.example</a>' in company and "fit 80" in company
    assert {"website", "value_eur_month", "custom_fit_score"} <= form_names(company)
    write_layout(repo, '[company]\nhide_fields = ["website", "value_eur_month", "fit_score", '
                       '"country"]\n[contact]\nhide_fields = ["email", "seniority"]\n')

    company = client.get("/companies/acme").text
    assert 'noopener">acme.example</a>' not in company and "fit 80" not in company
    assert "segment smb" in company                 # a field not hidden still shows
    names = form_names(company)
    assert not {"website", "value_eur_month", "custom_fit_score", "country"} & names
    assert {"name", "stage", "linkedin", "custom_segment", "notes"} <= names
    new = client.get("/companies/new").text
    assert 'name="value_eur_month"' not in new and 'name="custom_fit_score"' not in new

    assert {"fit", "country"}.isdisjoint(header_names(client.get("/companies").text))
    board = client.get("/pipeline").text
    assert 'name="f_country"' not in board and "900 EUR/month" not in board

    contact = client.get("/companies/acme/contacts/jane-doe").text
    assert "jane@acme.example" not in contact
    assert not {"email", "custom_seniority"} & form_names(contact)
    assert "CTO" in contact
    assert {"email", "seniority"}.isdisjoint(header_names(client.get("/contacts").text))


def test_saving_a_form_without_its_hidden_fields_keeps_their_values(client, app, repo, acme):
    write_layout(repo, '[company]\nhide_fields = ["website", "value_eur_month", "fit_score", '
                       '"tags", "notes"]\n[contact]\nhide_fields = ["email", "seniority"]\n')
    app.state.store.update_company("acme", tags="vip", notes="Met at the fair.")

    # Post exactly what the rendered form carries, with one visible change.
    page = client.get("/companies/acme").text
    values = {**company_values(app.state.store.get("acme")),
              "custom_segment": "enterprise", "version": ""}
    data = {k: v for k, v in values.items() if k in form_names(page)}
    data["product_oneliner"] = "Robots for warehouses"
    assert client.post("/companies/acme", data=data).status_code == 303
    company = app.state.store.get("acme", refresh=True)
    assert company.product_oneliner == "Robots for warehouses"
    assert company.website == "https://acme.example" and company.value_eur_month == 900
    assert company.tags == ["vip"] and "Met at the fair." in company.notes
    assert company.extra == {"fit_score": 80, "segment": "enterprise"}

    page = client.get("/companies/acme/contacts/jane-doe").text
    contact = app.state.store.get("acme").contacts["jane-doe"]
    data = {k: v for k, v in contact_values(contact).items() if k in form_names(page)}
    data["title"] = "CEO"
    assert client.post("/companies/acme/contacts/jane-doe", data=data).status_code == 303
    contact = app.state.store.get("acme", refresh=True).contacts["jane-doe"]
    assert (contact.title, contact.email) == ("CEO", "jane@acme.example")
    assert contact.extra == {"seniority": "senior"}


def test_the_contact_form_shows_and_keeps_its_own_custom_fields(client, app, acme):
    """Without a layout too: the contact page used to show its custom fields
    empty, so a save cleared them."""
    page = client.get("/companies/acme/contacts/jane-doe").text
    assert 'name="custom_seniority" value="senior"' in page
    contact = app.state.store.get("acme").contacts["jane-doe"]
    data = {**contact_values(contact), "custom_seniority": "senior", "phone": "+49 1"}
    assert client.post("/companies/acme/contacts/jane-doe", data=data).status_code == 303
    contact = app.state.store.get("acme", refresh=True).contacts["jane-doe"]
    assert contact.phone == "+49 1" and contact.extra == {"seniority": "senior"}


def test_a_hidden_field_with_an_error_shows_so_it_can_be_fixed(client, app, repo, acme):
    write_layout(repo, '[company]\nhide_fields = ["lost_reason"]\n')
    page = client.get("/companies/acme").text
    assert 'name="lost_reason"' not in record_form(page)
    data = {k: v for k, v in company_values(app.state.store.get("acme")).items()
            if k in form_names(page)}
    r = client.post("/companies/acme", data={**data, "stage": "lost"})
    assert r.status_code == 400 and "lost_reason is required" in r.text
    assert 'name="lost_reason"' in record_form(r.text)


def test_columns_choose_and_order_the_list(client, app, repo, acme):
    app.state.store.create_company("Beta BV", country="NL", custom={"fit_score": 40,
                                                                     "segment": "enterprise"})
    default = header_names(client.get("/companies").text)
    assert default == ["name", "country", "stage", "source", "fit", "tags", "last touch",
                       "next step", "due", "links"]
    # `segment` is not in show_in companies: columns wins over show_in.
    write_layout(repo, '[companies]\ncolumns = ["segment", "name", "fit_score", "links"]\n'
                       '[contacts]\ncolumns = ["seniority", "name", "company_name"]\n')
    page = client.get("/companies").text
    assert header_names(page) == ["segment", "name", "fit", "links"]
    row = page.split("<td><a href=\"/companies/acme\">")[0].rsplit("<tr>", 1)[1]
    assert "<td>smb</td>" in row
    assert page.count('<td class="links">') == 2

    contacts = client.get("/contacts").text
    assert header_names(contacts) == ["seniority", "name", "company"]
    assert "<td>senior</td>" in contacts and "jane@acme.example" not in contacts


def test_filters_and_sorting_work_on_every_shown_column(client, app, repo, acme):
    app.state.store.create_company("Beta BV", country="NL", custom={"fit_score": 40,
                                                                     "segment": "enterprise"})
    app.state.store.create_company("Gamma AG", country="DE", custom={"fit_score": 60,
                                                                      "segment": "smb"})
    write_layout(repo, '[companies]\ncolumns = ["name", "segment", "fit_score"]\n')

    def names(url):
        page = client.get(url).text
        return re.findall(r'<td><a href="/companies/[a-z-]+">([^<]+)</a></td>', page)

    assert names("/companies?sort=fit_score&dir=desc") == ["Acme GmbH", "Gamma AG", "Beta BV"]
    assert names("/companies?sort=segment&dir=asc")[0] == "Beta BV"
    assert names("/companies?f_segment=smb") == ["Acme GmbH", "Gamma AG"]
    assert names("/companies?f_fit_score=>50&sort=name&dir=desc") == ["Gamma AG", "Acme GmbH"]
    page = client.get("/companies?f_segment=smb").text
    assert 'name="f_segment" form="company-filters" value="smb"' in page
    # A filter on a column the layout leaves out still applies (bookmarks).
    assert names("/companies?f_country=NL") == ["Beta BV"]


def test_an_invalid_file_never_breaks_a_page(client, repo, acme):
    write_layout(repo, '[company\nsections = ["timeline"]\n')
    for url in PAGES:
        assert client.get(url).status_code == 200, url
    write_layout(repo, '[company]\nsections = "timeline"\nhide_sections = ["nope", "merge"]\n'
                       'hide_fields = [1, 2]\n[companies]\ncolumns = ["nope"]\n')
    for url in PAGES:
        assert client.get(url).status_code == 200, url
    company = client.get("/companies/acme").text
    assert order_of(company, COMPANY_MARKERS) == [s for s in layout.SECTIONS["company"]
                                                  if s != "merge"]
    assert header_names(client.get("/companies").text)[0] == "name"


def test_an_edit_shows_on_the_next_request_without_a_restart(client, repo, acme):
    assert order_of(client.get("/companies/acme").text, COMPANY_MARKERS)[0] == "enrich"
    write_layout(repo, '[company]\nsections = ["timeline"]\n')
    assert order_of(client.get("/companies/acme").text, COMPANY_MARKERS)[0] == "timeline"
    write_layout(repo, '[company]\nsections = ["contacts"]\n')
    assert order_of(client.get("/companies/acme").text, COMPANY_MARKERS)[0] == "contacts"
    (repo / layout.FILENAME).unlink()
    assert order_of(client.get("/companies/acme").text, COMPANY_MARKERS)[0] == "enrich"
