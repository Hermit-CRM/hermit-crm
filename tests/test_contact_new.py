"""Global "New contact" (company resolved or created, duplicate checks), the
per-company form's duplicate check, list-page buttons and the merge pickers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from owncrm.store import COMPANY_MERGE_FIELDS, CONTACT_MERGE_FIELDS
from owncrm.web import (
    company_matches, contact_matches, create_app, merge_rows, resolve_contact_company,
    website_for_new_company,
)

CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "owner_email": "me@example.com"}

CONTACT = {"name": "", "email": "", "title": "", "linkedin": "", "company": "", "website": ""}
COMPANY_CONTACT = {"first_name": "", "last_name": "", "title": "", "linkedin": "",
                   "email": "", "phone": "", "role": "", "notes": ""}


# ------------------------------------------------------------------- fixtures


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "CRM Test"], cwd=tmp_path,
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "crm@test.local"], cwd=tmp_path,
                   check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    return tmp_path


@pytest.fixture
def app(repo: Path):
    return create_app(repo, config=CONFIG)


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def seeded(client, app):
    """Acme GmbH (acme.example.com) with Jane Doe, and Bolt Inc (no website)."""
    client.post("/companies", data={"name": "Acme GmbH", "website": "https://acme.example.com"})
    client.post("/companies/acme/contacts", data={**COMPANY_CONTACT, "first_name": "Jane",
                                                  "last_name": "Doe",
                                                  "email": "Jane@acme.example.com"})
    client.post("/companies", data={"name": "Bolt Inc"})
    return app.state.store


def post_contact(client, **fields):
    return client.post("/contacts", data={**CONTACT, **fields})


def last_commit(repo: Path) -> str:
    out = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo,
                         capture_output=True, text=True)
    return out.stdout.strip()


def commit_count(repo: Path) -> int:
    out = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=repo,
                         capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


# ------------------------------------------------------------------- helpers


def test_company_resolution_order(seeded):
    assert resolve_contact_company(seeded, "acme", "") == ("acme", "name")
    assert resolve_contact_company(seeded, "ACME gmbh", "x@other.example.org") == ("acme", "name")
    assert resolve_contact_company(seeded, "Acme", "x@acme.example.com") == ("acme", "domain")
    assert resolve_contact_company(seeded, "Acme", "x@sub.acme.example.com") == ("acme", "domain")
    assert resolve_contact_company(seeded, "Acme", "x@gmail.com") == ("", "new")
    assert resolve_contact_company(seeded, "Acme", "not-an-email") == ("", "new")
    assert resolve_contact_company(seeded, "Acme", "") == ("", "new")


def test_website_for_new_company():
    assert website_for_new_company("acme.example.org", "x@gmail.com") == "https://acme.example.org"
    assert website_for_new_company("", "X@Acme.Example.org") == "https://acme.example.org"
    assert website_for_new_company("", "x@gmail.com") == ""
    assert website_for_new_company("", "") == ""


def test_match_helpers_ignore_case_accents_and_legal_suffixes(seeded):
    assert [c.slug for c in company_matches(seeded, "ACME")] == ["acme"]
    assert [c.slug for c in company_matches(seeded, "acme b.v.")] == ["acme"]
    assert [c.slug for c in company_matches(seeded, "Bolt")] == ["bolt"]
    assert [c.slug for c in company_matches(seeded, "Bolts")] == []
    assert [c.slug for c in company_matches(seeded, "Other", "https://www.acme.example.com/x")] == ["acme"]
    assert [c.slug for c in company_matches(seeded, "Other", "https://other.example.com")] == []
    assert [(c.slug, ct.slug) for c, ct in contact_matches(seeded, "", "JANE@acme.example.com")] \
        == [("acme", "jane-doe")]
    assert [(c.slug, ct.slug) for c, ct in contact_matches(seeded, "jane  doe", "", "acme")] \
        == [("acme", "jane-doe")]
    assert contact_matches(seeded, "Jane Doe", "", "bolt") == []
    assert contact_matches(seeded, "Jane Doe", "", "") == []
    assert [(c.slug, ct.slug) for c, ct in contact_matches(seeded, "Jané Doe", "", "acme")] \
        == [("acme", "jane-doe")]


# ------------------------------------------------------------------ the form


def test_form_lists_companies_and_requires_name_and_company(client, seeded):
    page = client.get("/contacts/new").text
    assert '<form method="post" action="/contacts"' in page
    assert '<datalist id="company-names"><option value="Acme GmbH"><option value="Bolt Inc">' in page
    assert 'name="website"' in page and "New contact" in page
    r = post_contact(client, name="", company="Acme")
    assert r.status_code == 400 and "name is required" in r.text
    r = post_contact(client, name="Ann Roe", company="")
    assert r.status_code == 400 and "company is required" in r.text
    assert seeded.get("acme").contacts.keys() == {"jane-doe"}


def test_existing_company_by_name_or_slug(client, seeded, repo):
    before = commit_count(repo)
    r = post_contact(client, name="Ann Roe", company="acme gmbh", title="CTO",
                     email="ann@other.example.org", linkedin="https://l/ann")
    assert r.status_code == 303
    assert r.headers["location"] == "/companies/acme/contacts/ann-roe?flash=Contact%20created"
    c = seeded.get("acme").contacts["ann-roe"]
    assert (c.first_name, c.last_name, c.title, c.email, c.linkedin) == (
        "Ann", "Roe", "CTO", "ann@other.example.org", "https://l/ann")
    assert commit_count(repo) == before + 1
    assert last_commit(repo) == "contact: acme/ann-roe created"
    r = post_contact(client, name="Bo", company="bolt")
    assert r.headers["location"].startswith("/companies/bolt/contacts/bo?")
    assert len(seeded.companies) == 2


def test_existing_company_by_email_domain(client, seeded):
    r = post_contact(client, name="Max Mustermann", company="Acme Robotics",
                     email="max@acme.example.com")
    assert r.status_code == 303
    assert r.headers["location"] == ("/companies/acme/contacts/max-mustermann?flash="
                                     "Contact%20created%20%28company%20matched%20by%20email%20domain%29")
    assert "max-mustermann" in seeded.get("acme").contacts and len(seeded.companies) == 2


def test_new_company_created_with_website_from_email_domain(client, seeded, repo):
    before = commit_count(repo)
    r = post_contact(client, name="Eve Adams", company="Cygne SA", email="eve@cygne.example.org")
    assert r.status_code == 303
    assert r.headers["location"] == ("/companies/cygne-sa/contacts/eve-adams?flash="
                                     "Contact%20created%20with%20company%20Cygne%20SA")
    cygne = seeded.get("cygne-sa")
    assert cygne.name == "Cygne SA" and cygne.website == "https://cygne.example.org"
    assert cygne.stage == "prospect" and "eve-adams" in cygne.contacts
    assert commit_count(repo) == before + 1  # company and contact in one commit
    assert last_commit(repo) == "contact: cygne-sa/eve-adams created with company cygne-sa"
    assert (repo / "companies" / "cygne-sa" / "contacts" / "eve-adams.md").exists()

    # freemail: no website; an explicit website wins over the domain
    post_contact(client, name="Gil", company="Delta", email="gil@gmail.com")
    assert seeded.get("delta").website == ""
    post_contact(client, name="Hal", company="Echo", email="hal@echo.example.org",
                 website="echo-group.example.org")
    assert seeded.get("echo").website == "https://echo-group.example.org"


def test_duplicate_email_anywhere_warns_then_force_writes(client, seeded, repo):
    before = commit_count(repo)
    r = post_contact(client, name="J. Doe", company="Bolt Inc", email="JANE@acme.example.com")
    assert r.status_code == 200 and "Possible duplicate" in r.text
    assert '<a href="/companies/acme/contacts/jane-doe">Jane Doe at Acme GmbH (jane@acme.example.com)</a>' in r.text
    assert 'name="force" value="1"' in r.text and 'value="J. Doe"' in r.text
    assert commit_count(repo) == before and "j-doe" not in seeded.get("bolt").contacts
    r = post_contact(client, name="J. Doe", company="Bolt Inc", email="JANE@acme.example.com",
                     force="1")
    assert r.status_code == 303 and "j-doe" in seeded.get("bolt").contacts
    assert commit_count(repo) == before + 1


def test_duplicate_name_at_resolved_company(client, seeded):
    r = post_contact(client, name="jane DOE", company="Acme GmbH")
    assert r.status_code == 200 and "Jane Doe at Acme GmbH" in r.text
    assert list(seeded.get("acme").contacts) == ["jane-doe"]
    # the same name at another company is fine
    r = post_contact(client, name="Jane Doe", company="Bolt Inc")
    assert r.status_code == 303 and "jane-doe" in seeded.get("bolt").contacts


def test_close_company_when_a_new_one_would_be_created(client, seeded):
    # same name ignoring the legal suffix
    r = post_contact(client, name="Kim Lee", company="Acme B.V.", email="kim@gmail.com")
    assert r.status_code == 200
    assert '<a href="/companies/acme">company Acme GmbH (https://acme.example.com)</a>' in r.text
    assert len(seeded.companies) == 2
    # same website domain for the new company
    r = post_contact(client, name="Kim Lee", company="Totally Different",
                     website="https://www.acme.example.com/about")
    assert r.status_code == 200 and "company Acme GmbH" in r.text
    r = post_contact(client, name="Kim Lee", company="Acme B.V.", email="kim@gmail.com", force="1")
    assert r.status_code == 303
    assert seeded.get("acme-2").name == "Acme B.V."  # legal suffix dropped, slug suffixed


def test_per_company_form_checks_email_and_name(client, seeded, repo):
    before = commit_count(repo)
    r = client.post("/companies/bolt/contacts", data={**COMPANY_CONTACT, "first_name": "Jane",
                                                      "last_name": "X",
                                                      "email": "jane@acme.example.com"})
    assert r.status_code == 200 and "Jane Doe at Acme GmbH" in r.text
    assert 'name="force" value="1"' in r.text and 'value="jane@acme.example.com"' in r.text
    r = client.post("/companies/acme/contacts", data={**COMPANY_CONTACT, "first_name": "JANE",
                                                      "last_name": "doe"})
    assert r.status_code == 200 and "Possible duplicate" in r.text
    assert commit_count(repo) == before
    r = client.post("/companies/acme/contacts", data={**COMPANY_CONTACT, "first_name": "JANE",
                                                      "last_name": "doe", "force": "1"})
    assert r.status_code == 303 and "jane-doe-2" in seeded.get("acme").contacts
    r = client.post("/companies/bolt/contacts", data={**COMPANY_CONTACT, "first_name": "Jane",
                                                      "last_name": "Doe"})
    assert r.status_code == 303  # no clash at another company without an email
    page = client.get("/companies/bolt/contacts/new").text
    assert "Possible duplicate" not in page and 'action="/companies/bolt/contacts"' in page


# ------------------------------------------------- list buttons, merge picker


def test_list_pages_have_buttons_and_import_mode_is_preselected(client, seeded):
    companies = client.get("/companies").text
    assert '<a class="button" href="/companies/new">New company</a>' in companies
    assert '<a class="button" href="/import?mode=companies">Import</a>' in companies
    contacts = client.get("/contacts").text
    assert '<a class="button" href="/contacts/new">New contact</a>' in contacts
    assert '<a class="button" href="/import?mode=contacts">Import</a>' in contacts
    assert '<option value="contacts" selected>' in client.get("/import?mode=contacts").text
    assert '<option value="companies" selected>' in client.get("/import?mode=companies").text
    plain = client.get("/import").text
    assert '<option value="" selected>auto-detect</option>' in plain
    assert '<option value="" selected>auto-detect</option>' in client.get("/import?mode=x").text


def test_merge_pickers_offer_candidates_and_accept_names(client, seeded):
    page = client.get("/companies/acme").text
    assert '<input name="drop" list="merge-candidates"' in page
    assert '<datalist id="merge-candidates"><option value="bolt">Bolt Inc (prospect)</option></datalist>' in page
    assert 'value="acme"' not in page.split('id="merge-candidates"')[1].split("</datalist>")[0]
    form = client.get("/companies/acme/merge?drop=Bolt%20Inc").text
    assert "Merge Bolt Inc into Acme GmbH" in form and 'name="drop" value="bolt"' in form
    r = client.get("/companies/acme/merge?drop=Nobody")
    assert r.status_code == 303 and "cannot%20merge" in r.headers["location"]

    client.post("/companies/acme/contacts", data={**COMPANY_CONTACT, "first_name": "John",
                                                  "last_name": "Roe"})
    page = client.get("/companies/acme/contacts/jane-doe").text
    assert '<datalist id="merge-candidates"><option value="john-roe">John Roe</option></datalist>' in page
    form = client.get("/companies/acme/contacts/jane-doe/merge?drop=john%20roe").text
    assert "Merge John Roe into Jane Doe" in form and 'name="drop" value="john-roe"' in form
    r = client.get("/companies/acme/contacts/jane-doe/merge?drop=nobody")
    assert r.status_code == 303 and "Pick%20another" in r.headers["location"]


def test_merge_rows_default_to_the_filled_side(seeded):
    acme, bolt = seeded.get("acme"), seeded.get("bolt")
    seeded.update_company("bolt", linkedin="https://l/bolt", tags="a", notes="n")
    bolt = seeded.get("bolt")
    rows = {r["key"]: r for r in merge_rows(acme, bolt, COMPANY_MERGE_FIELDS)}
    assert rows["website"]["default"] == "keep"     # ours filled
    assert rows["linkedin"]["default"] == "drop"    # ours empty, theirs filled
    assert rows["tags"]["default"] == "drop" and rows["tags"]["both"]
    assert rows["notes"]["default"] == "drop" and rows["notes"]["both"]
    assert rows["stage"]["default"] == "keep"       # both filled: ours
    assert rows["my_score"]["default"] == "keep"    # both empty: ours
    assert rows["name"]["label"] == "name" and rows["value_eur_month"]["label"] == "value eur month"
    assert not rows["website"]["both"]
    jane = acme.contacts["jane-doe"]
    crow = {r["key"]: r for r in merge_rows(jane, jane, CONTACT_MERGE_FIELDS)}
    assert set(crow) == set(CONTACT_MERGE_FIELDS) and crow["email"]["default"] == "keep"
