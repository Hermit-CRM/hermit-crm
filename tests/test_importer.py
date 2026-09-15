"""Bulk import: parsing, planning against existing data, applying in one commit."""

import io
import zipfile

from owncrm.importer import (
    apply_import, decode_upload, detect_mode, map_country, name_from_domain,
    normalise_linkedin, parse_table, plan_import, xlsx_to_text,
)
from owncrm.models import ValidationError
import pytest

SAMPLE = (
    "name\tLI invite\tComments\tmy score\topportunity_type\tfit_score\thq_country\t"
    "hq_city\twebsite\tfte_estimate\tsn_employees\tae_count\tfounder_name\t"
    "founder_title\tfounder_sales_nav_url\tfounder_linkedin\tproduct_oneliner\n"
    "Fjellmark\t\t\t\tcore\t82\tSweden\tStockholm\t\t21\t\t3\tAndreas Lindqvist\t"
    "Founder / CEO\thttps://www.linkedin.com/sales/lead/ACwAAABx\t"
    "linkedin.com/in/andreaskullberg\tAgentic AI platform for sales teams.\n"
    "Nimbus AI (YC S23)\tno personalization\t\t\tcore\t78\tGermany\t\t"
    "https://getnimbus.ai/\t~13\t\t2\tLucas Steinhof\tCo-Founder\t\t"
    "linkedin.com/in/lucas-steinhof\tAI SDR for European B2B teams.\n"
    "alvero\t\talready have VP sales\t5\tcore\t65\tFrance\tParis\t"
    "https://www.alvero.me/\t42\t42\t2\tIvica Horvatic\tCo Founder\t\t\t"
    "Digital assistant for hotels.\n"
    ", \t\topen HoS job\t6\tcore\t70\tGermany\tBerlin\thttps://hi.lumenhire.example.com/li\t32\t"
    "32\t2\tFinn zur Mühlen\tCEO\t\t\tAI phone calls that convert\n"
    "Quill\t\tInteresting!\t9\tcore\t72\tSweden\tStockholm\thttps://quillhq.io\t\t\t5\t"
    "Adam Jensen\tFounder & CEO\t\t\tAI product team as a service.\n"
)


def test_parse_table_tabs_and_blank_rows():
    headers, rows = parse_table("name\twebsite\n\nAcme\thttps://acme.de\n  \nBeta\n")
    assert headers == ["name", "website"]
    assert rows == [{"name": "Acme", "website": "https://acme.de"},
                    {"name": "Beta", "website": ""}]


def test_parse_table_csv_and_bom():
    headers, rows = parse_table('﻿name,country\r\n"Acme, Inc",Germany\r\n')
    assert headers == ["name", "country"]
    assert rows == [{"name": "Acme, Inc", "country": "Germany"}]


def test_country_and_linkedin_helpers():
    assert map_country("Sweden") == "SE" and map_country("de") == "DE"
    assert map_country("USA") == "US" and map_country("United Kingdom") == "GB"
    assert map_country("uk") == "GB" and map_country("PT") == "PT"
    assert map_country("Atlantis") is None and map_country("") == ""
    assert normalise_linkedin("linkedin.com/in/jane") == "https://www.linkedin.com/in/jane"
    assert normalise_linkedin("https://www.linkedin.com/in/jane/") == \
        "https://www.linkedin.com/in/jane"
    assert normalise_linkedin("http://www.linkedin.com/in/jane") == \
        "https://www.linkedin.com/in/jane"
    assert normalise_linkedin("") == ""


def test_plan_maps_columns_and_keeps_extras(store):
    plan = plan_import(store, SAMPLE)
    assert plan.count("create") == 4 and plan.count("skip") == 1
    fjellmark = plan.rows[0]
    assert fjellmark.action == "create" and fjellmark.slug == "fjellmark"
    assert fjellmark.fields == {
        "my_score": None, "fit_score": 82, "country": "SE", "fte_estimate": "21",
        "ae_count": 3, "product_oneliner": "Agentic AI platform for sales teams.",
        "source": "list",
    } or fjellmark.fields == {
        "fit_score": 82, "country": "SE", "fte_estimate": "21", "ae_count": 3,
        "product_oneliner": "Agentic AI platform for sales teams.", "source": "list",
    }
    assert fjellmark.tags == ["core"]
    assert "Imported fields (2026-09-14):" in fjellmark.notes
    assert "- hq_city: Stockholm" in fjellmark.notes
    assert fjellmark.contact == {
        "first_name": "Andreas", "last_name": "Lindqvist", "title": "Founder / CEO",
        "linkedin": "https://www.linkedin.com/in/andreaskullberg",
        "role": "decision-maker",
        "notes": "founder_sales_nav_url: https://www.linkedin.com/sales/lead/ACwAAABx\n",
        "slug": "andreas-lindqvist",
    }
    nimbus = plan.rows[1]
    assert nimbus.slug == "nimbus-ai-yc-s23" and nimbus.fields["fte_estimate"] == "~13"
    assert "- LI invite: no personalization" in nimbus.notes
    alvero = plan.rows[2]
    assert alvero.fields["country"] == "FR"  # any ISO country maps now
    assert not any("France" in w for w in alvero.warnings)
    assert alvero.notes.startswith("already have VP sales\n\nImported fields")
    assert "hq_country" not in alvero.notes
    assert plan.rows[3].action == "skip" and plan.rows[3].reason == "empty name"


def test_plan_fills_only_empty_fields_of_existing_company(store):
    store.create_company("Quill", website="https://quillhq.io", my_score=7,
                         tags=["priority"], notes="Old notes.\n")
    store.create_contact("quill", "Adam", "Jensen")
    plan = plan_import(store, SAMPLE)
    quill = plan.rows[4]
    assert quill.action == "update" and quill.slug == "quill"
    assert quill.fields["fit_score"] == 72 and quill.fields["country"] == "SE"
    assert "my_score" not in quill.fields and "website" not in quill.fields
    assert quill.fields["tags"] == ["core", "priority"]
    assert quill.fields["notes"].startswith("Old notes.\n\nImported fields")
    assert "- Interesting!" in quill.fields["notes"]
    assert quill.contact_action == "exists"


def test_plan_rejects_tables_without_a_name_column(store):
    with pytest.raises(ValidationError):
        plan_import(store, "")
    with pytest.raises(ValidationError):
        plan_import(store, "website\tcountry\nhttps://x.de\tDE\n")


def test_apply_writes_everything_in_one_commit(store, messages):
    counts = apply_import(store, plan_import(store, SAMPLE))
    assert counts == {"created": 4, "updated": 0, "contacts": 4, "skipped": 1, "failed": 0}
    assert messages == ["import: 4 companies created, 0 updated, 4 contacts created"]
    fjellmark = store.get("fjellmark")
    assert fjellmark.country == "SE" and fjellmark.fit_score == 82 and fjellmark.tags == ["core"]
    contact = fjellmark.contacts["andreas-lindqvist"]
    assert contact.name == "Andreas Lindqvist" and contact.role == "decision-maker"
    text = (store.company_dir("fjellmark") / "contacts" / "andreas-lindqvist.md").read_text()
    assert "first_name: Andreas\nlast_name: Lindqvist\n" in text
    assert "founder_sales_nav_url:" in text

    # Importing the same sheet again changes nothing and commits nothing.
    plan = plan_import(store, SAMPLE)
    assert plan.count("skip") == 5
    assert apply_import(store, plan)["skipped"] == 5
    assert len(messages) == 1


# ------------------------------------------------------------ contacts mode

HUBSPOT = (
    "First Name,Last Name,Email,Job Title,Company Name,Website URL,Country/Region,"
    "Phone Number,LinkedIn URL,Lifecycle Stage\n"
    "Jane,Doe,jane@acme.de,CEO,Acme GmbH,acme.de,Germany,+49 30 1234,"
    "linkedin.com/in/janedoe,Lead\n"
    "Tom,Berg,tom@acme.de,Head of Sales,Acme GmbH,acme.de,Germany,,,Lead\n"
    "Ann,Lee,ann.lee@gmail.com,Founder,,,France,,,Subscriber\n"
    "Bob,Stone,bob@gmail.com,,,,,,,Lead\n"
)
APOLLO = (
    "First Name,Last Name,Title,Company,Company Name for Emails,Email,Email Status,"
    "Seniority,Departments,Person Linkedin Url,Website,Company Linkedin Url,"
    "# Employees,Country\n"
    'Lucas,Steinhof,Co-Founder,Nimbus AI,Nimbus,lucas@getnimbus.ai,Verified,Founder,'
    '"C-Suite, Sales",http://www.linkedin.com/in/lucas-steinhof,https://getnimbus.ai,'
    "http://www.linkedin.com/company/nimbus-ai,13,Germany\n"
    "Mia,Holm,VP Sales,Quill,Quill,mia@quillhq.io,Verified,VP,Sales,,http://www.quillhq.io,,5,Sweden\n"
)


def test_detect_mode():
    assert detect_mode(parse_table(HUBSPOT)[0]) == "contacts"
    assert detect_mode(parse_table(APOLLO)[0]) == "contacts"
    assert detect_mode(["First Name", "Last Name", "URL", "Email Address", "Company",
                        "Position", "Connected On"]) == "contacts"
    assert detect_mode(["Person - Name", "Organization - Name", "Person - Email"]) == "contacts"
    assert detect_mode(parse_table(SAMPLE)[0]) == "companies"
    assert detect_mode(["name", "website", "contact_email"]) == "companies"
    # Person columns without a company column, or with company-only columns.
    assert detect_mode(["First Name", "Email"]) == "companies"
    assert detect_mode(["Email", "Company", "fit_score"]) == "companies"


def test_contacts_mode_hubspot_creates_company_once_and_skips_freemail(store, messages):
    plan = plan_import(store, HUBSPOT)
    assert plan.mode == "contacts"
    assert plan.mapping["Lifecycle Stage"] == "notes" and plan.mapping["Email"] == "email"
    assert plan.samples["Company Name"] == "Acme GmbH"
    jane, tom, ann, bob = plan.rows
    assert jane.action == "create" and jane.slug == "acme"
    assert jane.fields == {"website": "https://acme.de", "country": "DE", "source": "list"}
    assert jane.contact["email"] == "jane@acme.de" and jane.contact["role"] == "decision-maker"
    assert jane.contact["linkedin"] == "https://www.linkedin.com/in/janedoe"
    assert "- Lifecycle Stage: Lead" in jane.contact["notes"]
    assert tom.action == "keep" and tom.contact_action == "create"
    # Freemail and no company: Ann is skipped, but her France warning is not needed.
    assert ann.action == "skip" and ann.reason == "no company"
    assert bob.action == "skip" and "no company email domain" in bob.warnings[0]
    assert plan.summary == ("2 contacts to create, 0 to update, 1 companies to create, "
                            "0 to update, 2 rows skipped")

    counts = apply_import(store, plan)
    assert counts == {"created": 1, "updated": 0, "contacts": 2, "skipped": 2, "failed": 0,
                      "contacts_updated": 0}
    assert messages == ["import: 2 contacts created, 0 updated, 1 companies created"]
    acme = store.get("acme")
    assert set(acme.contacts) == {"jane-doe", "tom-berg"} and acme.country == "DE"
    # Re-importing matches everything and writes nothing.
    again = plan_import(store, HUBSPOT)
    assert [r.action for r in again.rows] == ["skip"] * 4
    assert not again.has_changes


def test_contacts_mode_matches_by_email_by_name_and_by_domain(store):
    store.create_company("Northwind", website="https://www.northwind.io")
    store.create_contact("northwind", "Jane", "Doe", email="jd@northwind.io")
    store.create_contact("northwind", "Sam", "Rivera")
    text = (
        "Name,Email,Title,Company,Phone\n"
        # by email, even with a different company spelling: fills the empty title
        "Jane Doe,JD@northwind.io,CTO,Northwind Traders,\n"
        # by name within the company matched by domain (no company column value)
        "Sam Rivera,sam@northwind.io,,,+1 555\n"
        # new person, company matched by the website domain of the email
        "Kim Park,kim@northwind.io,COO,,\n"
    )
    plan = plan_import(store, text, mode="contacts")
    jane, sam, kim = plan.rows
    assert jane.slug == "northwind" and jane.contact_action == "update"
    assert jane.contact_slug == "jane-doe" and jane.contact_fields == {"title": "CTO", "role": "decision-maker"}
    assert sam.slug == "northwind" and sam.contact_slug == "sam-rivera"
    assert sam.contact_fields == {"email": "sam@northwind.io", "phone": "+1 555"}
    assert kim.slug == "northwind" and kim.contact_action == "create"
    assert all(r.action == "keep" for r in plan.rows)
    counts = apply_import(store, plan)
    assert counts["contacts"] == 1 and counts["contacts_updated"] == 2
    company = store.get("northwind")
    assert company.contacts["jane-doe"].title == "CTO"
    assert company.contacts["jane-doe"].email == "jd@northwind.io"
    assert company.contacts["sam-rivera"].phone == "+1 555"
    assert company.website == "https://www.northwind.io"  # never overwritten


def test_contacts_mode_derives_company_from_email_domain(store):
    plan = plan_import(store, "First Name,Last Name,Email,Company\n"
                              "Eva,Lind,eva@lindqvist-labs.se,\n", mode="contacts")
    row = plan.rows[0]
    assert row.action == "create" and row.name == "Lindqvist-labs"
    assert row.fields["website"] == "https://lindqvist-labs.se"
    assert any("derived from lindqvist-labs.se" in w for w in row.warnings)
    assert name_from_domain("mail.acme.co.uk") == "Acme"
    assert name_from_domain("getnimbus.ai") == "Getnimbus"


def test_contacts_mode_existing_company_by_slug_fills_empty_fields_only(store):
    store.create_company("Quill", country="SE")
    plan = plan_import(store, APOLLO)
    lucas, mia = plan.rows
    assert lucas.action == "create" and lucas.slug == "nimbus-ai"
    assert lucas.fields["linkedin"] == "https://www.linkedin.com/company/nimbus-ai"
    assert lucas.fields["fte_estimate"] == "13"
    assert lucas.contact["title"] == "Co-Founder" and lucas.contact["role"] == "decision-maker"
    assert mia.action == "update" and mia.slug == "quill"
    assert mia.fields == {"website": "http://www.quillhq.io", "fte_estimate": "5"}
    assert "- Seniority: VP" in mia.contact["notes"]
    assert plan.mapping["Company Name for Emails"] == "notes"


def test_mapping_override_with_ignore_and_notes(store):
    text = "Full Name,Company,Email,Lifecycle Stage,Country\nJane Doe,Acme,jane@acme.de,Lead,Germany\n"
    plan = plan_import(store, text, mapping={"Lifecycle Stage": "ignore",
                                             "Country": "notes", "Email": "email"})
    row = plan.rows[0]
    assert plan.mapping["Lifecycle Stage"] == "ignore" and plan.mapping["Country"] == "notes"
    assert "country" not in row.fields
    assert row.contact["notes"] == "Imported fields (2026-09-14):\n- Country: Germany\n"
    with pytest.raises(ValidationError) as exc:
        plan_import(store, text, mapping={"Email": "fit_score"})
    assert "unknown field" in exc.value.errors["mapping"]

    # Companies mode: remap an unknown column to a field and drop another.
    plan = plan_import(store, "name\tHomepage\tsecret\nAcme\tacme.de\tx\n",
                       mapping={"Homepage": "website", "secret": "ignore"})
    assert plan.rows[0].fields["website"] == "https://acme.de"
    assert plan.rows[0].notes == ""


def test_contacts_mode_needs_a_name_column(store):
    with pytest.raises(ValidationError):
        plan_import(store, "Email,Company\na@b.de,B\n", mode="contacts")
    with pytest.raises(ValidationError):
        plan_import(store, "name\nAcme\n", mode="people")


def _xlsx(rows_xml: str, shared: list[str]) -> bytes:
    buf = io.BytesIO()
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/workbook.xml",
                    f'<workbook {ns} {rel}><sheets><sheet name="People" sheetId="1" '
                    f'r:id="rId7"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                    'relationships"><Relationship Id="rId7" Type="worksheet" '
                    'Target="worksheets/sheet3.xml"/></Relationships>')
        zf.writestr("xl/sharedStrings.xml",
                    f"<sst {ns}>" + "".join(f"<si><t>{t}</t></si>" for t in shared) +
                    f"<si><r><t>Rich </t></r><r><t>Co</t></r></si></sst>")
        zf.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData/></worksheet>")
        zf.writestr("xl/worksheets/sheet3.xml",
                    f"<worksheet {ns}><sheetData>{rows_xml}</sheetData></worksheet>")
    return buf.getvalue()


def test_xlsx_upload_reads_first_sheet(store):
    shared = ["First Name", "Last Name", "Company", "Email", "Employees", "Jane", "Doe"]
    rows = (
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
        '<c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c><c r="E1" t="s"><v>4</v></c>'
        '<c r="F1" t="inlineStr"><is><t>Added</t></is></c></row>'
        '<row r="2"><c r="A2" t="s"><v>5</v></c><c r="B2" t="s"><v>6</v></c>'
        '<c r="C2" t="s"><v>7</v></c><c r="D2" t="inlineStr"><is><t>jane@rich.co</t></is></c>'
        '<c r="E2"><v>25.0</v></c><c r="F2"><v>46280</v></c></row>'
        '<row r="4"><c r="A4" t="inlineStr"><is><t>Tab\tand "quote"</t></is></c>'
        '<c r="C4" t="s"><v>7</v></c><c r="E4"><v>2.5</v></c></row>'
    )
    data = _xlsx(rows, shared)
    text = xlsx_to_text(data)
    assert decode_upload(data) == text
    headers, parsed = parse_table(text)
    assert headers == ["First Name", "Last Name", "Company", "Email", "Employees", "Added"]
    assert parsed[0] == {"First Name": "Jane", "Last Name": "Doe", "Company": "Rich Co",
                         "Email": "jane@rich.co", "Employees": "25", "Added": "46280"}
    assert parsed[1]["First Name"] == 'Tab and "quote"' and parsed[1]["Employees"] == "2.5"
    plan = plan_import(store, text)
    assert plan.mode == "contacts" and plan.rows[0].slug == "rich"  # "Co" is a legal suffix
    with pytest.raises(ValidationError):
        decode_upload(b"PK\x03\x04 not really a zip")
    assert decode_upload("name\nCafé\n".encode("cp1252")) == "name\nCafé\n"
    assert decode_upload("name\nCafé\n".encode("utf-16")) == "name\nCafé\n"
