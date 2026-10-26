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

"""Export: the CSV zip and its profiles, JSON, formula escaping, the CLI, the
web download, and a round trip of the demo folder through export and import."""

from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import zipfile
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import cli, export, fields
from hermitcrm.datafolder import init_folder
from hermitcrm.importer import (
    apply_import, default_target, detect_mode, parse_table, plan_import, unescape_cell,
)
from hermitcrm.store import Store, load_config
from hermitcrm.web import create_app

FILES = ["companies.csv", "contacts.csv", "interactions.csv", "tasks.csv",
         "stage_history.csv"]


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "demo", demo=True)


def open_store(root: Path) -> Store:
    return cli.build_store(root)


def unzip(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {name: zf.read(name).decode("utf-8") for name in zf.namelist()}


def table(text: str) -> tuple[list[str], list[dict]]:
    reader = csv.reader(io.StringIO(text.lstrip("﻿"), newline=""))
    header = next(reader)
    return header, [dict(zip(header, row)) for row in reader]


def git_state(root: Path) -> tuple[str, str]:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                          text=True).stdout
    status = subprocess.run(["git", "status", "--porcelain", "--ignored"], cwd=root,
                            capture_output=True, text=True).stdout
    return head, status


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


# ------------------------------------------------------------------- cells


@pytest.mark.parametrize("value,escaped", [
    ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
    ("+49 30 1234567", "'+49 30 1234567"),
    ("-5", "'-5"),
    ("@cmd", "'@cmd"),
    ("\tx", "'\tx"),
    ("plain", "plain"),
    ("", ""),
    ("a=b", "a=b"),
    ("'quoted'", "'quoted'"),
])
def test_formula_cells_are_escaped_and_the_importer_undoes_it(value, escaped):
    assert export.escape_cell(value) == escaped
    assert unescape_cell(export.escape_cell(value)) == value


def test_the_importer_strips_the_apostrophe_from_csv_and_keeps_other_ones():
    text = "name,phone,note\n'=Evil Corp,'+49 30 1,'tis fine\n"
    _, rows = parse_table(text)
    assert rows == [{"name": "=Evil Corp", "phone": "+49 30 1", "note": "'tis fine"}]


def test_a_note_with_blank_lines_survives_parsing():
    text = 'name,notes\nAcme,"one\n\ntwo\n"\n\nBeta,x\n'
    _, rows = parse_table(text)
    assert [r["notes"] for r in rows] == ["one\n\ntwo", "x"]


def test_values_become_text_the_importer_reads():
    assert export.cell(None) == ""
    assert export.cell(True) == "true"
    assert export.cell(date(2026, 10, 5)) == "2026-10-05"
    assert export.cell(datetime(2026, 10, 5, 9, 30)) == "2026-10-05T09:30"
    assert export.cell(["saas", "demo"]) == "saas, demo"
    assert export.cell([{"b": 1, "a": date(2026, 1, 2)}]) == '[{"a": "2026-01-02", "b": 1}]'
    assert export.cell(7) == "7"


# ------------------------------------------------------------------- the zip


def test_the_zip_holds_five_csvs_in_a_fixed_order_and_is_byte_identical(demo):
    store = open_store(demo)
    first = export.zip_bytes(store)
    assert export.zip_bytes(open_store(demo)) == first
    with zipfile.ZipFile(io.BytesIO(first)) as zf:
        assert zf.namelist() == FILES
        assert zf.testzip() is None
    files = unzip(first)
    header, rows = table(files["companies.csv"])
    assert header[:3] == ["slug", "name", "website"]
    assert [r["slug"] for r in rows] == sorted(store.companies)
    assert files["companies.csv"].startswith("slug,")  # no byte-order mark by default


def test_every_record_is_in_the_export(demo):
    store = open_store(demo)
    files = unzip(export.zip_bytes(store))
    companies = table(files["companies.csv"])[1]
    contacts = table(files["contacts.csv"])[1]
    interactions = table(files["interactions.csv"])[1]
    tasks = table(files["tasks.csv"])[1]
    stages = table(files["stage_history.csv"])[1]
    assert len(companies) == len(store.companies)
    assert len(contacts) == sum(len(c.contacts) for c in store.companies.values())
    assert {(r["company_slug"], r["id"]) for r in interactions} == {
        (c.slug, i.id) for c in store.companies.values() for i in c.interactions}
    assert len(tasks) == sum(len(c.todos()) for c in store.companies.values())
    assert len(stages) == sum(len(c.stage_history) for c in store.companies.values())
    # Bodies come through whole, newlines and all.
    some = next(i for c in store.companies.values() for i in c.interactions if "\n" in i.body)
    row = next(r for r in interactions if r["id"] == some.id)
    assert row["body"] == some.body


def test_the_interactions_csv_has_the_framework_right_after_the_subject(demo):
    store = open_store(demo)
    company = next(c for c in store.all() if any(i.is_message for i in c.interactions))
    it = next(i for i in company.interactions if i.is_message)
    store.update_interaction(company.slug, it.id, framework="trigger-tension-trust")
    header, rows = table(unzip(export.zip_bytes(open_store(demo)))["interactions.csv"])
    assert header[header.index("subject") + 1] == "framework"
    assert header.count("framework") == 1
    by_id = {(r["company_slug"], r["id"]): r for r in rows}
    row = by_id[(company.slug, it.id)]
    assert row["framework"] == "trigger-tension-trust"
    assert {r["framework"] for k, r in by_id.items() if k != (company.slug, it.id)} == {""}


def test_user_fields_then_unknown_keys_come_after_the_known_columns_sorted(demo):
    company = next(p for p in sorted((demo / "companies").iterdir()) if p.is_dir())
    path = company / "company.md"
    text = path.read_text()
    path.write_text(text.replace("\n---\n", "\nzz_legacy: kept\naa_custom: [a, b]\n---\n", 1))
    store = open_store(demo)
    defs = fields.load(demo)
    header, rows = table(export.csv_files(store, defs)[0][1])
    known = list(export.COMPANY_FIELDS)
    own = sorted(d.key for d in defs if d.applies_to == "company")
    assert header[:len(known)] == known
    assert header[len(known):] == own + ["aa_custom", "zz_legacy"]
    row = next(r for r in rows if r["slug"] == company.name)
    assert row["zz_legacy"] == "kept"
    assert row["aa_custom"] == "a, b"


def test_contact_user_fields_are_columns(demo):
    fields.write(demo, fields.load(demo) + [fields.FieldDef(key="pet", applies_to="contact")])
    store = open_store(demo)
    company = store.companies[sorted(store.companies)[0]]
    cslug = sorted(company.contacts)[0]
    store.update_contact(company.slug, cslug, custom={"pet": "=cat"})
    header, rows = table(export.csv_files(open_store(demo), fields.load(demo))[1][1])
    assert header[-1] == "pet"
    assert next(r for r in rows if r["slug"] == cslug)["pet"] == "'=cat"


def test_formula_cells_in_the_data_are_escaped_in_the_zip(demo):
    store = open_store(demo)
    slug = sorted(store.companies)[0]
    store.update_company(slug, product_oneliner="=HYPERLINK(\"http://example.com\")")
    files = unzip(export.zip_bytes(open_store(demo)))
    row = next(r for r in table(files["companies.csv"])[1] if r["slug"] == slug)
    assert row["product_oneliner"] == "'=HYPERLINK(\"http://example.com\")"


def test_excel_adds_a_byte_order_mark_to_every_file(demo):
    files = unzip(export.zip_bytes(open_store(demo), excel=True))
    assert all(text.startswith("﻿") for text in files.values())
    plain = unzip(export.zip_bytes(open_store(demo)))
    assert all(files[n] == "﻿" + plain[n] for n in FILES)


@pytest.mark.parametrize("profile", ["hubspot", "pipedrive"])
def test_profile_headers_map_back_to_the_same_fields(profile):
    names = export.PROFILE_HEADERS[profile]
    for key, header in names["companies"].items():
        expected = {"notes": "notes_text"}.get(key, key)
        assert default_target(header, "companies") == expected, header
    for key, header in names["contacts"].items():
        assert default_target(header, "contacts") == key, header


@pytest.mark.parametrize("profile,name,first", [
    ("generic", "name", "first_name"),
    ("hubspot", "Company name", "First Name"),
    ("pipedrive", "Organization - Name", "Person - First name"),
])
def test_profiles_rename_company_and_contact_columns(demo, profile, name, first):
    store = open_store(demo)
    files = unzip(export.zip_bytes(store, profile=profile))
    company_header, companies = table(files["companies.csv"])
    contact_header, contacts = table(files["contacts.csv"])
    assert name in company_header and first in contact_header
    assert sorted(r[name] for r in companies) == sorted(c.name for c in store.companies.values())
    # Each file is read back in the mode it is for.
    assert detect_mode(company_header) == "companies"
    assert detect_mode(contact_header) == "contacts"
    # Interactions, tasks and stage history keep one shape for every profile.
    generic = unzip(export.zip_bytes(store))
    for other in FILES[2:]:
        assert files[other] == generic[other]


def test_an_unknown_profile_is_refused(demo):
    with pytest.raises(ValueError):
        export.csv_files(open_store(demo), profile="salesforce")


# ------------------------------------------------------------------- json


def test_json_nests_everything_and_is_deterministic(demo):
    store = open_store(demo)
    text = export.json_text(store, fields.load(demo))
    assert export.json_text(open_store(demo), fields.load(demo)) == text
    data = json.loads(text)
    assert data["format"] == "hermitcrm-export" and data["version"] == 1
    assert [c["slug"] for c in data["companies"]] == sorted(store.companies)
    first = store.companies[data["companies"][0]["slug"]]
    got = data["companies"][0]
    assert [p["slug"] for p in got["contacts"]] == sorted(first.contacts)
    assert len(got["interactions"]) == len(first.interactions)
    assert got["notes"] == f"Demo company. {first.product_oneliner}."   # the one company note
    assert {f["key"] for f in data["fields"]} == {d.key for d in fields.load(demo)}


# ------------------------------------------------------------------- the CLI


def test_the_notes_column_holds_the_company_notes_oldest_first(tmp_path):
    store = open_store(init_folder(tmp_path / "crm"))
    store.create_company(name="Example Robotics", notes="Second look: pricing came up.")
    store.create_interaction("example-robotics", channel="note", direction="", contact="",
                             date=datetime(2020, 1, 5, 9, 0), body="2020-01-05 First call, warm.\n")
    store.create_interaction("example-robotics", channel="note", direction="", contact="",
                             date=datetime(2099, 1, 1, 9, 0), body="Newest note.\n\nWith a blank line.")
    store.create_company(name="Example Quiet")
    person = store.create_contact("example-robotics", "Ada", "Example").slug
    store.create_interaction("example-robotics", channel="note", direction="", contact=person,
                             date=datetime(2020, 2, 1, 9, 0), body="About Ada, not the company.")

    expected = ("2020-01-05 First call, warm.\n\nSecond look: pricing came up."
                "\n\nNewest note.\n\nWith a blank line.")
    _, rows = export.company_rows(store)
    by_name = {r["name"]: r for r in rows}
    assert by_name["Example Robotics"]["notes"] == expected   # dated lines as written
    assert by_name["Example Quiet"]["notes"] == ""
    nested = {c["name"]: c for c in json.loads(export.json_text(store, []))["companies"]}
    assert nested["Example Robotics"]["notes"] == expected

    # a legacy body, when a hand edit left one, comes first
    store.get("example-robotics").notes = "Hand-typed body."
    _, rows = export.company_rows(store)
    assert {r["name"]: r for r in rows}["Example Robotics"]["notes"] == "Hand-typed body.\n\n" + expected


def test_the_company_notes_survive_an_export_and_import_as_one_note(tmp_path):
    source = open_store(init_folder(tmp_path / "source"))
    source.create_company(name="Example Robotics")
    for day, body in ((5, "2020-01-05 First call."), (9, "Pricing came up.")):
        source.create_interaction("example-robotics", channel="note", direction="",
                                  date=datetime(2020, 1, day, 9, 0), body=body)
    files = unzip(export.zip_bytes(open_store(tmp_path / "source"), fields.load(tmp_path / "source")))
    assert table(files["companies.csv"])[1][0]["notes"] == "2020-01-05 First call.\n\nPricing came up."

    target = init_folder(tmp_path / "target")
    store = open_store(target)
    import_file(store, files["companies.csv"], "companies", fields.load(target))
    company = open_store(target).get("example-robotics")
    [note] = [i for i in company.interactions if i.is_note and not i.contact]
    assert note.body.strip() == "2020-01-05 First call.\n\nPricing came up."
    assert company.notes.strip() == ""


def test_cli_writes_the_zip_and_leaves_the_folder_alone(demo, tmp_path, capsys):
    before, files_before = git_state(demo), snapshot(demo)
    out = tmp_path / "out"
    out.mkdir()
    assert cli.main(["--data", str(demo), "export", "-o", str(out)]) == 0
    written = list(out.iterdir())
    assert len(written) == 1 and written[0].name.startswith("hermitcrm-export-")
    assert written[0].read_bytes() == export.zip_bytes(open_store(demo))
    assert "Exported 13 companies" in capsys.readouterr().out
    assert git_state(demo) == before and snapshot(demo) == files_before


def test_cli_json_profile_and_excel(demo, tmp_path):
    target = tmp_path / "all.json"
    assert cli.main(["--data", str(demo), "export", "--format", "json", "-o",
                     str(target)]) == 0
    assert json.loads(target.read_text())["format"] == "hermitcrm-export"
    target = tmp_path / "hs.zip"
    assert cli.main(["--data", str(demo), "export", "--profile", "hubspot", "--excel",
                     "-o", str(target)]) == 0
    assert target.read_bytes() == export.zip_bytes(open_store(demo), fields.load(demo),
                                                   "hubspot", excel=True)
    assert cli.main(["--data", str(demo), "export", "--format", "json", "--excel",
                     "-o", str(tmp_path / "x.json")]) == 2


def test_cli_refuses_to_write_inside_the_data_folder(demo, capsys):
    assert cli.main(["--data", str(demo), "export", "-o", str(demo / "x.zip")]) == 2
    assert not (demo / "x.zip").exists()
    assert "inside the data folder" in capsys.readouterr().err


# ------------------------------------------------------------------- the web


def make_client(folder: Path, tmp_path: Path):
    config = load_config(folder)
    config["push_enabled"] = False
    config["owner_email"] = config.get("owner_email") or "me@example.com"
    app = create_app(folder, config)
    app.state.setup_platform = "linux"
    app.state.schedule_home = tmp_path / "home"
    app.state.calendar_url = lambda refresh=False: ""
    return app, TestClient(app, follow_redirects=False)


def test_export_zip_downloads_and_writes_nothing(demo, tmp_path):
    _, client = make_client(demo, tmp_path)
    before, files_before = git_state(demo), snapshot(demo)
    response = client.get("/export.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert 'attachment; filename="hermitcrm-export-' in response.headers["content-disposition"]
    assert response.content == export.zip_bytes(open_store(demo), fields.load(demo))
    hubspot = client.get("/export.zip?profile=hubspot&excel=true")
    assert unzip(hubspot.content)["contacts.csv"].startswith("﻿company_slug,Company Name")
    assert client.get("/export.zip?profile=nope").status_code == 400
    assert git_state(demo) == before and snapshot(demo) == files_before


def test_settings_data_tab_offers_the_export(demo, tmp_path):
    _, client = make_client(demo, tmp_path)
    page = client.get("/settings").text
    assert 'data-group="tab-backup">Data' in page
    section = page[page.index('id="export"'):]
    assert 'action="/export.zip"' in section and "Export everything" in section


# ------------------------------------------------------------------- round trip


COMPANY_KEYS = ("website", "linkedin", "country", "source", "stage", "lost_reason",
                "requalify_on", "value_eur_month", "product_oneliner", "next_step",
                "next_step_due", "next_step_status", "tags", "extra")
CONTACT_KEYS = ("title", "email", "phone", "linkedin", "role", "extra")


def company_record(c) -> dict:
    record = {k: getattr(c, k) for k in COMPANY_KEYS}
    record["tags"] = sorted(record["tags"])
    record["notes"] = c.notes.strip()
    record["contacts"] = {p.name: {k: getattr(p, k) for k in CONTACT_KEYS}
                          for p in c.contacts.values()}
    return record


def import_file(store: Store, text: str, mode: str, defs) -> dict:
    plan = plan_import(store, text, mode=mode, defs=defs)
    assert not [w for r in plan.rows for w in r.warnings], plan.rows
    counts = apply_import(store, plan)
    assert counts["failed"] == 0
    return counts


@pytest.mark.parametrize("profile", ["generic", "hubspot", "pipedrive"])
def test_round_trip_demo_through_export_and_import(demo, tmp_path, profile):
    source = open_store(demo)
    files = unzip(export.zip_bytes(source, fields.load(demo), profile, excel=True))

    # A new, empty folder with the same settings (fields, stages): the records
    # are what moves.
    target = init_folder(tmp_path / "empty")
    shutil.copy(demo / "fields.toml", target / "fields.toml")
    shutil.copy(demo / "config.toml", target / "config.toml")
    store = open_store(target)
    defs = fields.load(target)
    assert not store.companies

    import_file(store, files["companies.csv"], "companies", defs)
    import_file(store, files["contacts.csv"], "contacts", defs)
    store = open_store(target)

    expected = {c.name: company_record(c) for c in source.companies.values()}
    got = {c.name: company_record(c) for c in store.companies.values()}
    assert got == expected


def test_round_trip_keeps_awkward_values(tmp_path):
    """Formula-looking cells, a phone with +, notes with blank lines, a lost
    deal with its reason, a done next step and a contact field of your own."""
    source_root = init_folder(tmp_path / "source")
    fields.write(source_root, [fields.FieldDef(key="score", type="number"),
                               fields.FieldDef(key="pet", applies_to="contact")])
    source = open_store(source_root)
    source.create_company(
        name="Example Robotics", website="https://robotics.example.com", country="DE",
        source="event", product_oneliner="=1+2, then @mentions", value_eur_month=-5,
        next_step="Call back", next_step_due="2026-10-20", next_step_status="done",
        tags=["b-tag", "a-tag"], notes="First line.\n\nSecond paragraph, \"quoted\".\n",
        custom={"score": 7})
    source.update_company("example-robotics", stage="lost", lost_reason="-budget cut")
    source.create_contact("example-robotics", "Ada", "Example", title="Founder",
                          email="ada@robotics.example.com", phone="+49 30 1234567",
                          custom={"pet": "@cat"})
    source.create_contact("example-robotics", "Bo", "Example", title="Engineer",
                          role="champion")
    source = open_store(source_root)
    files = unzip(export.zip_bytes(source, fields.load(source_root)))
    assert "'+49 30 1234567" in files["contacts.csv"]

    target = init_folder(tmp_path / "target")
    shutil.copy(source_root / "fields.toml", target / "fields.toml")
    store = open_store(target)
    defs = fields.load(target)
    import_file(store, files["companies.csv"], "companies", defs)
    import_file(store, files["contacts.csv"], "contacts", defs)
    store = open_store(target)
    expected = {c.name: company_record(c) for c in source.companies.values()}
    got = {c.name: company_record(c) for c in store.companies.values()}
    assert got == expected
    assert got["Example Robotics"]["contacts"]["Ada Example"]["extra"] == {"pet": "@cat"}
    assert got["Example Robotics"]["contacts"]["Ada Example"]["role"] == ""
