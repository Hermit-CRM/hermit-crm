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

import subprocess

import pytest
import sys
from datetime import datetime
from pathlib import Path


# cmd_serve imports hermitcrm.accesslog, which reads LOGGING_CONFIG out of
# uvicorn.config. The serve tests below put a stub in sys.modules["uvicorn"],
# and a stub has no __path__ for the import machinery to find a submodule
# through, so the real uvicorn.config has to be in sys.modules before that --
# whatever else ran first in this process.
import uvicorn.config  # noqa: F401

from hermitcrm.gitops import GitOps
from hermitcrm.store import Store
from conftest import FIXED_NOW

from hermitcrm import cli as crm


def run(args, cwd):
    result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run(["init", "-b", "main"], cwd=path)
    run(["-c", "user.name=crm", "-c", "user.email=crm@localhost", "commit",
         "--allow-empty", "-m", "init"], cwd=path)
    return path


def fixed_store(tmp_path, messages=None) -> Store:
    s = Store(tmp_path, on_write=(messages.append if messages is not None else None),
              clock=lambda: FIXED_NOW)
    s.load()
    return s


# ------------------------------------------------------------------- digest


def test_digest_empty_window(tmp_path):
    store = fixed_store(tmp_path)
    text = crm.cmd_digest(store, days=7, now=FIXED_NOW)
    assert text == "Summary: 0 interactions | companies touched: 0"


def test_digest_ordering_and_format(tmp_path):
    store = fixed_store(tmp_path)
    store.create_company("Acme GmbH", source="referral", stage="prospect")
    store.create_contact("acme", "Jane", "Doe", title="CEO", email="Jane@Acme.de")

    # Oldest first once printed, so create them out of order.
    store.create_interaction(
        "acme", subject="Call notes", channel="call", direction="out",
        contact="", date="2026-09-13T09:00",
        body="This is a long body. " * 20,
    )
    store.create_interaction(
        "acme", subject="Intro email", channel="email", direction="out",
        contact="jane-doe", date="2026-09-10T10:30",
        outcome="successful", body="Hello   Jane,\n\nGreat  to connect.",
    )
    store.create_interaction(
        "acme", subject="LI reply", channel="linkedin", direction="in",
        contact="jane-doe", date="2026-09-14T08:00", body="",
    )

    text = crm.cmd_digest(store, days=7, now=FIXED_NOW)
    lines = text.split("\n")

    # oldest first
    assert lines[0] == (
        "2026-09-10 10:30 | email out | acme / jane-doe | Intro email | "
        "outcome: successful"
    )
    assert lines[1] == "Hello Jane, Great to connect."
    assert lines[2] == ""
    assert lines[3] == (
        "2026-09-13 09:00 | call out | acme / company | Call notes | outcome: -"
    )
    preview = lines[4]
    assert len(preview) == 150
    assert preview == " ".join(("This is a long body. " * 20).split())[:150]
    assert lines[5] == ""
    assert lines[6] == (
        "2026-09-14 08:00 | linkedin in | acme / jane-doe | LI reply | outcome: -"
    )
    assert lines[7] == ""  # empty body -> empty preview line

    summary = lines[-1]
    assert summary == (
        "Summary: 3 interactions | email: 1 out / 0 in | linkedin: 0 out / 1 in | "
        "call: 1 out / 0 in | companies touched: 1"
    )


def test_digest_window_excludes_older_interactions(tmp_path):
    store = fixed_store(tmp_path)
    store.create_company("Beta AG", source="other")
    store.create_interaction(
        "beta", subject="Old call", channel="call", direction="out",
        date="2026-08-01T09:00", body="old",
    )
    store.create_interaction(
        "beta", subject="Recent email", channel="email", direction="in",
        date="2026-09-13T09:00", body="recent",
    )
    text = crm.cmd_digest(store, days=7, now=FIXED_NOW)
    assert "Old call" not in text
    assert "Recent email" in text


# ---------------------------------------------------------------------- show


def test_show_unknown_slug(tmp_path):
    store = fixed_store(tmp_path)
    text = crm.cmd_show(store, "nope")
    assert text == "unknown company: nope"


def test_show_format_default_three_bodies(tmp_path):
    store = fixed_store(tmp_path)
    store.create_company(
        "Acme GmbH", source="referral", stage="discovery",
        value_eur_month=1500, next_step="Send proposal",
        next_step_due="2026-09-20", tags=["priority", "eu"],
        notes="Some notes about Acme.",
    )
    store.create_contact("acme", "Jane", "Doe", title="CEO",
                         email="Jane@Acme.de", role="decision-maker")
    store.create_contact("acme", "Jonas", "Berg", title="CTO")

    for i in range(4):
        store.create_interaction(
            "acme", subject=f"Touch {i}", channel="email", direction="out",
            contact="jane-doe", date=f"2026-09-{10 + i:02d}T09:00",
            body=f"Body number {i}",
        )

    text = crm.cmd_show(store, "acme")
    lines = text.split("\n")

    assert lines[:21] == [
        "name: Acme GmbH", "slug: acme", "website:", "linkedin:", "country:",
        "source: referral", "stage: discovery", "stage_changed: 2026-09-14",
        "lost_reason:", "requalify_on:", "value_eur_month: 1500",
        "product_oneliner:", "next_step: Send proposal",
        "next_step_due: 2026-09-20", "next_step_status: open", "tags: priority, eu",
        "created: 2026-09-14T10:30", "updated: 2026-09-14T10:30", "",
        "Some notes about Acme.", "",
    ]
    assert lines[21] == "Contacts:"
    assert lines[22] == "jane-doe | CEO | jane@acme.de | decision-maker"
    assert lines[23] == "jonas-berg | CTO | - | -"
    assert lines[24] == ""
    assert lines[25] == "Interactions:"
    assert lines[26] == "2026-09-13 09:00 | email out | jane-doe | Touch 3 | -"
    assert lines[27] == "2026-09-12 09:00 | email out | jane-doe | Touch 2 | -"
    assert lines[28] == "2026-09-11 09:00 | email out | jane-doe | Touch 1 | -"
    assert lines[29] == "2026-09-10 09:00 | email out | jane-doe | Touch 0 | -"

    # default: three most recent bodies
    assert lines[30] == ""
    assert lines[31] == "--- 2026-09-13 09:00 | email out | jane-doe | Touch 3 | -"
    assert lines[32] == "Body number 3"
    assert lines[33] == ""
    assert lines[34] == "--- 2026-09-12 09:00 | email out | jane-doe | Touch 2 | -"
    assert lines[35] == "Body number 2"
    assert lines[36] == ""
    assert lines[37] == "--- 2026-09-11 09:00 | email out | jane-doe | Touch 1 | -"
    assert lines[38] == "Body number 1"
    assert len(lines) == 39
    # Touch 0's body is not printed by default.
    assert "Body number 0" not in text


def test_show_bodies_n(tmp_path):
    store = fixed_store(tmp_path)
    store.create_company("Beta AG", source="other")
    for i in range(4):
        store.create_interaction(
            "beta", subject=f"Touch {i}", channel="call", direction="out",
            date=f"2026-09-{10 + i:02d}T09:00", body=f"Body {i}",
        )

    text = crm.cmd_show(store, "beta", bodies=1)
    assert text.count("---") == 1
    assert "Body 3" in text
    assert "Body 2" not in text


def test_show_all_bodies(tmp_path):
    store = fixed_store(tmp_path)
    store.create_company("Beta AG", source="other")
    for i in range(4):
        store.create_interaction(
            "beta", subject=f"Touch {i}", channel="call", direction="out",
            date=f"2026-09-{10 + i:02d}T09:00", body=f"Body {i}",
        )

    text = crm.cmd_show(store, "beta", all_bodies=True)
    assert text.count("---") == 4
    for i in range(4):
        assert f"Body {i}" in text


def test_show_company_with_no_interactions_or_contacts(tmp_path):
    store = fixed_store(tmp_path)
    store.create_company("Gamma SE", source="other")
    text = crm.cmd_show(store, "gamma")
    assert "Contacts:" in text
    assert "Interactions:" in text
    assert not text.rstrip("\n").endswith("---")


# --------------------------------------------------------------------- check


def test_check_clean_store_returns_zero(tmp_path):
    store = fixed_store(tmp_path)
    store.create_company("Acme GmbH", source="referral")
    store.create_contact("acme", "Jane", "Doe")
    store.create_interaction("acme", subject="Hi", channel="email",
                             direction="out", contact="jane-doe", body="hi")

    text, code = crm.cmd_check(store)
    assert code == 0
    assert text == "OK: 1 companies, 1 contacts, 1 interactions, no problems"


def test_check_broken_enum_returns_one_and_names_file(tmp_path):
    store = fixed_store(tmp_path)
    store.create_company("Acme GmbH", source="referral")

    company_file = tmp_path / "companies" / "acme" / "company.md"
    broken = company_file.read_text().replace("stage: prospect", "stage: bogus")
    company_file.write_text(broken)

    text, code = crm.cmd_check(store)
    assert code == 1
    assert "companies/acme/company.md" in text
    assert "stage" in text


# ------------------------------------------------------------------- rebuild


def test_rebuild_writes_pipeline_and_commits(tmp_path):
    init_repo(tmp_path)
    store = fixed_store(tmp_path)
    store.create_company("Acme GmbH", source="referral", stage="prospect")
    gitops = GitOps(root=tmp_path, push_enabled=False)

    summary = crm.cmd_rebuild(store, gitops)

    assert (tmp_path / "PIPELINE.md").exists()
    assert "rebuilt" in summary
    log = run(["log", "-1", "--format=%s"], cwd=tmp_path)
    assert log.strip() == "pipeline: rebuild"


def test_rebuild_no_change_makes_no_new_commit(tmp_path):
    init_repo(tmp_path)
    store = fixed_store(tmp_path)
    store.create_company("Acme GmbH", source="referral", stage="prospect")
    gitops = GitOps(root=tmp_path, push_enabled=False)

    crm.cmd_rebuild(store, gitops)
    count_after_first = run(["rev-list", "--count", "HEAD"], cwd=tmp_path).strip()

    second_summary = crm.cmd_rebuild(store, gitops)
    count_after_second = run(["rev-list", "--count", "HEAD"], cwd=tmp_path).strip()

    assert count_after_first == count_after_second
    assert "up to date" in second_summary


# ---------------------------------------------------------------------- main


def test_main_check_end_to_end(tmp_path, capsys):
    store = fixed_store(tmp_path)
    store.create_company("Acme GmbH", source="referral")

    code = crm.main(["check"], root=tmp_path)
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out.strip() == "OK: 1 companies, 0 contacts, 0 interactions, no problems"


def test_main_check_end_to_end_with_problem(tmp_path, capsys):
    store = fixed_store(tmp_path)
    store.create_company("Acme GmbH", source="referral")
    company_file = tmp_path / "companies" / "acme" / "company.md"
    company_file.write_text(
        company_file.read_text().replace("stage: prospect", "stage: bogus")
    )

    code = crm.main(["check"], root=tmp_path)
    captured = capsys.readouterr()

    assert code == 1
    assert "companies/acme/company.md" in captured.out


def test_main_show_unknown_slug_returns_one(tmp_path, capsys):
    fixed_store(tmp_path)
    code = crm.main(["show", "nope"], root=tmp_path)
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out.strip() == "unknown company: nope"


def test_main_digest_default_days(tmp_path, capsys):
    fixed_store(tmp_path)
    code = crm.main(["digest"], root=tmp_path)
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "Summary: 0 interactions | companies touched: 0"


def test_cli_add_company_contact_and_interaction(tmp_path, capsys):
    fixed_store(tmp_path)

    assert crm.main(["add", "company", "Acme BV", "--country", "NL",
                     "--website", "acme.example.com"], root=tmp_path) == 0
    assert "company acme created" in capsys.readouterr().out
    text = (tmp_path / "companies" / "acme" / "company.md").read_text()
    assert "country: NL" in text and "website: https://acme.example.com" in text

    assert crm.main(["add", "contact", "acme", "Jane van Roe",
                     "--title", "CTO", "--email", "Jane@Example.com"], root=tmp_path) == 0
    assert "contact jane-van-roe created" in capsys.readouterr().out
    text = (tmp_path / "companies" / "acme" / "contacts" / "jane-van-roe.md").read_text()
    # the single name argument is split, and the store normalises the address
    assert "first_name: Jane" in text and "last_name: van Roe" in text
    assert "email: jane@example.com" in text

    assert crm.main(["add", "interaction", "acme", "--channel", "email",
                     "--direction", "out", "--contact", "jane-van-roe",
                     "--subject", "Intro", "--body", "Hi Jane"], root=tmp_path) == 0
    assert "interaction" in capsys.readouterr().out
    # logging an interaction advances the company out of prospect
    assert "stage: engaged" in (tmp_path / "companies" / "acme" / "company.md").read_text()


def test_cli_add_body_from_stdin_keeps_newlines(tmp_path, capsys):
    import io

    fixed_store(tmp_path)
    crm.main(["add", "company", "Acme BV"], root=tmp_path)
    capsys.readouterr()

    code = crm.main(["add", "interaction", "acme", "--channel", "email",
                     "--direction", "out", "--body", "-"], root=tmp_path,
                    stdin=io.StringIO("Line one\n\nLine two\n"))

    assert code == 0
    written = next((tmp_path / "companies" / "acme" / "interactions").glob("*.md"))
    assert written.read_text().endswith("Line one\n\nLine two\n")


def test_cli_add_set_reaches_a_field_without_a_flag(tmp_path, capsys):
    fixed_store(tmp_path)

    (tmp_path / "fields.toml").write_text(
        '[[field]]\nkey = "my_score"\ntype = "number"\n\n'
        '[[field]]\nkey = "fte_estimate"\ntype = "text"\n', encoding="utf-8")

    code = crm.main(["add", "company", "Acme BV", "--set", "my_score=4",
                     "--set", "fte-estimate=10-50"], root=tmp_path)

    assert code == 0
    text = (tmp_path / "companies" / "acme" / "company.md").read_text()
    assert "my_score: 4" in text and "fte_estimate: 10-50" in text


def test_cli_add_set_refuses_a_field_nobody_defined(tmp_path, capsys):
    """An undefined key is a typo, not a new field: --set will not invent one."""
    fixed_store(tmp_path)
    code = crm.main(["add", "company", "Acme BV", "--set", "mystery=4"], root=tmp_path)
    assert code == 2
    err = capsys.readouterr().err
    assert "unknown field 'mystery'" in err
    assert not (tmp_path / "companies" / "acme").exists()


def test_cli_add_rejects_bad_input_without_writing(tmp_path, capsys):
    fixed_store(tmp_path)

    assert crm.main(["add", "company", "Nowhere Ltd", "--stage", "lost"],
                    root=tmp_path) == 2
    assert "lost_reason" in capsys.readouterr().err

    assert crm.main(["add", "company", "Typo Ltd", "--set", "nope=1"],
                    root=tmp_path) == 2
    err = capsys.readouterr().err
    assert "unknown field 'nope'" in err and "product_oneliner" in err

    assert crm.main(["add", "contact", "ghost", "Jane Roe"], root=tmp_path) == 2
    assert "unknown company" in capsys.readouterr().err
    assert not list((tmp_path / "companies").glob("*/company.md"))


def test_cli_import_dry_run_and_apply(tmp_path, capsys):
    root = git_root(tmp_path) if "git_root" in globals() else tmp_path
    sheet = tmp_path / "sheet.tsv"
    sheet.write_text("name\thq_country\tfounder_name\nFjellmark\tSweden\tAndreas Lindqvist\n")
    assert crm.main(["import", str(sheet)], root=root) == 0
    out = capsys.readouterr().out
    assert "1 companies to create" in out and "Dry run" in out
    assert not (root / "companies" / "fjellmark").exists()
    assert crm.main(["import", str(sheet), "--apply"], root=root) == 0
    out = capsys.readouterr().out
    assert "Imported: 1 created, 0 updated, 1 contacts" in out
    assert (root / "companies" / "fjellmark" / "contacts" / "andreas-lindqvist.md").exists()


def test_cli_import_mode_and_map_flags(tmp_path, capsys):
    root = tmp_path
    sheet = tmp_path / "people.csv"
    sheet.write_text("Name,Organisation,E-mail,Source list\n"
                     "Jane Doe,Acme,jane@acme.de,webinar\n")
    assert crm.main(["import", str(sheet), "--mode", "contacts",
                     "--map", "Source list=ignore", "--map", "E-mail=email"], root=root) == 0
    out = capsys.readouterr().out
    assert "Mode: contacts" in out and "Source list -> ignore" in out
    assert "1 contacts to create" in out and "contact Jane Doe (create)" in out
    assert crm.main(["import", str(sheet), "--map", "E-mail=bogus"], root=root) == 1
    assert "unknown field 'bogus'" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        crm.main(["import", str(sheet), "--map", "no-equals-sign"], root=root)
    capsys.readouterr()
    assert crm.main(["import", str(sheet), "--mode", "contacts", "--apply"], root=root) == 0
    out = capsys.readouterr().out
    assert "Imported: 1 created, 0 updated, 1 contacts, 0 contacts updated" in out
    assert (root / "companies" / "acme" / "contacts" / "jane-doe.md").exists()


def test_cli_enrich_dry_run_and_apply(tmp_path, capsys, monkeypatch):
    from hermitcrm.enrich import Enricher, Proposal
    store = fixed_store(tmp_path)
    store.create_company("Acme")

    class Stub:
        def propose_company(self, company, defs=None):
            return Proposal(fields={"website": "https://acme.de"},
                            missing=["website", "linkedin"], sources=["https://acme.de"])

        def propose_contact(self, company, contact, defs=None):
            return Proposal(fields={}, missing=["title"], notes="nothing public")

    text, code = crm.cmd_enrich(store, Stub(), "acme")
    assert code == 0 and "website: https://acme.de" in text
    assert "not found: linkedin" in text and "Dry run" in text
    assert store.get("acme").website == ""

    text, code = crm.cmd_enrich(store, Stub(), "acme", apply=True)
    assert code == 0 and "applied: website" in text
    assert store.get("acme").website == "https://acme.de"
    assert crm.cmd_enrich(store, Stub(), "nope")[1] == 1
    store.create_contact("acme", "Jane", "Doe")
    text, code = crm.cmd_enrich(store, Stub(), "acme", contact="jane-doe")
    assert code == 0 and "not found: title" in text and "nothing public" in text
    assert crm.cmd_enrich(store, Stub(), "acme", contact="ghost")[1] == 1


# --------------------------------------------------------------- serve --host


def test_reachable_address_prints_a_typeable_one_for_a_wildcard_bind():
    """0.0.0.0 is not something you can open on a phone; a LAN address is."""
    assert crm.reachable_address("127.0.0.1") == "127.0.0.1"
    assert crm.reachable_address("crm.local") == "crm.local"
    for wildcard in ("0.0.0.0", "::"):
        shown = crm.reachable_address(wildcard)
        assert shown not in ("0.0.0.0", "::") and shown.count(".") == 3


def test_serve_binds_the_host_it_is_given_and_warns_off_loopback(tmp_path, capsys,
                                                                 monkeypatch):
    calls = {}
    monkeypatch.setattr(crm, "load_config", lambda root: {"port": 8765,
                                                          "host": "127.0.0.1"})
    monkeypatch.setitem(sys.modules, "uvicorn",
                        type("M", (), {"run": staticmethod(
                            lambda app, host, port, **kw: calls.update(host=host, port=port))}))
    monkeypatch.setattr("hermitcrm.web.create_app", lambda root, config: "app")

    crm.cmd_serve(tmp_path)
    assert calls["host"] == "127.0.0.1"
    assert "Hermit CRM has no password" not in capsys.readouterr().err

    crm.cmd_serve(tmp_path, host="0.0.0.0", port=9001)
    assert calls == {"host": "0.0.0.0", "port": 9001}
    err = capsys.readouterr().err
    assert "Hermit CRM has no password" in err and "network you trust" in err


def test_serve_keeps_what_a_capture_read_out_of_its_log(tmp_path, capsys, monkeypatch):
    """The bookmarklet puts a profile's name and headline in a local address,
    and uvicorn writes every address it answers to the serve log."""
    import logging
    import logging.config
    calls = {}
    monkeypatch.setattr(crm, "load_config", lambda root: {"port": 8765,
                                                          "host": "127.0.0.1"})
    monkeypatch.setitem(sys.modules, "uvicorn",
                        type("M", (), {"run": staticmethod(
                            lambda app, **kw: calls.update(kw))}))
    monkeypatch.setattr("hermitcrm.web.create_app", lambda root, config: "app")
    crm.cmd_serve(tmp_path)
    monkeypatch.undo()                      # the real uvicorn, for its formatters

    access = logging.getLogger("uvicorn.access")
    saved = (access.handlers[:], access.filters[:], access.propagate)
    try:
        logging.config.dictConfig(calls["log_config"])
        access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET",
                    "/extension/new?url=x&name=Ines+Vega", "1.1", 200)
        out = capsys.readouterr().out
    finally:
        access.handlers[:], access.filters[:], access.propagate = saved
    assert "GET /extension/new" in out and "Ines" not in out
