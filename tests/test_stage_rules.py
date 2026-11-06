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

"""Optional stage transition rules: a stage's `to` list and the `stage_rules` switch.

Off (the default) nothing is looked at. Warn lets the move through and says so.
Enforce refuses it, in every writer that goes through Store.update_company: the
web app, the CLI (`set`), MCP (bulk), bulk changes and the BCC import.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import bcc, bulk, mcp
from hermitcrm import cli as crm
from hermitcrm import stages as st
from hermitcrm.bulk import Ops
from hermitcrm.datafolder import init_folder
from hermitcrm.models import ValidationError
from hermitcrm.store import Store, load_config
from hermitcrm.web import create_app
from conftest import FIXED_NOW

RULES = [
    {"name": "prospect"},
    {"name": "engaged"},
    {"name": "discovery", "valued": True},
    {"name": "offer", "valued": True, "to": ["discovery", "won", "lost"]},
    {"name": "won", "role": "won"},
    {"name": "lost", "role": "lost"},
    {"name": "disqualified", "role": "closed"},
    {"name": "temp-disqualified", "role": "parked", "to": []},
]


def make(tmp_path, mode="enforce", raw=RULES, **kw) -> Store:
    store = Store(tmp_path, clock=lambda: FIXED_NOW, stages=st.from_config(raw),
                  stage_rules=mode, **kw)
    store.load()
    return store


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True).stdout


# ------------------------------------------------------------------ the model


def test_to_is_read_written_and_not_left_in_extra():
    s = st.from_config(RULES)
    assert s.allowed_moves("offer") == ["discovery", "won", "lost"]
    assert s.allowed_moves("prospect") is None            # absent: any stage
    assert s.allowed_moves("temp-disqualified") == []      # empty: nowhere
    assert s.allowed_moves("nowhere") is None
    assert "to" not in {k for stage in s for k in stage.extra}
    out = {e["name"]: e for e in st.to_config(s)}
    assert out["offer"]["to"] == ["discovery", "won", "lost"]
    assert out["temp-disqualified"]["to"] == []
    assert "to" not in out["prospect"]
    assert s.has_rules and not st.DEFAULT_STAGES.has_rules


def test_a_bad_to_is_named_and_dropped():
    raw = [{"name": "a"}, {"name": "b", "to": ["a", "ghost", "b"]},
           {"name": "c", "to": "a"}, {"name": "d", "to": [1]}]
    problems = st.problems(raw)
    assert any("'ghost', which is not a stage" in p for p in problems)
    assert any("lists the stage itself" in p for p in problems)
    assert sum("to must be a list of stage names" in p for p in problems) == 2
    s = st.from_config(raw)
    assert s.allowed_moves("b") == ["a"] and s.allowed_moves("c") is None


def test_move_problem_names_the_legal_moves():
    s = st.from_config(RULES)
    assert s.move_problem("offer", "won") is None
    assert s.move_problem("offer", "prospect") == (
        "offer -> prospect is not allowed (allowed: discovery, won, lost)")
    assert s.move_problem("prospect", "won") is None
    assert s.move_problem("offer", "offer") is None          # staying put
    assert s.move_problem("", "offer") is None               # a new company
    assert s.move_problem("offer", "retired") is None        # unknown: not a rules matter
    assert "no move is allowed out of temp-disqualified" in s.move_problem(
        "temp-disqualified", "offer")
    # A parked company returns to the entry stage whatever its list says.
    assert s.move_problem("temp-disqualified", "prospect") is None


def test_rules_mode_and_its_problem():
    assert st.rules_mode(None) == "off" and st.rules_mode("ENFORCE") == "enforce"
    assert st.rules_mode("sometimes") == "off"
    assert st.rules_problem("warn") is None and st.rules_problem(None) is None
    assert "not one of off, warn, enforce" in st.rules_problem("sometimes")


def test_settings_rows_keep_rename_and_drop_rules():
    before = st.from_config(RULES)
    names = before.names
    roles = [s.role for s in before]
    # Rename discovery; delete lost: offer's list follows the rename and loses lost.
    new_names = ["discovery-call" if n == "discovery" else n for n in names]
    new, renames, removed, errors = st.plan_rows(
        new_names, roles, ["2", "3"], names, before, delete=str(names.index("lost")))
    assert not errors and renames == {"discovery": "discovery-call"} and removed == ["lost"]
    assert new.allowed_moves("offer") == ["discovery-call", "won"]
    assert new.allowed_moves("temp-disqualified") == []


def test_settings_rows_set_a_rule_from_the_form():
    before = st.from_config(RULES)
    names, roles = before.names, [s.role for s in before]
    i = names.index("engaged")
    new, *_ = st.plan_rows(names, roles, [], names, before, restrict=[str(i)],
                           to_boxes=[f"{i}:won", f"{i}:discovery", f"{i}:engaged"])
    # Form order does not matter: the stage order does; itself is dropped.
    assert new.allowed_moves("engaged") == ["discovery", "won"]
    # A stage whose box is not ticked is back to any; the form speaks for all rows.
    assert new.allowed_moves("offer") is None


# ------------------------------------------------------------------ the store


def company(store, stage="offer", name="Acme BV"):
    return store.create_company(name, stage=stage)


def test_off_changes_nothing_even_with_rules_in_the_config(tmp_path, messages):
    store = make(tmp_path, mode="off")
    company(store)
    moved = store.update_company("acme", stage="prospect")
    assert moved.stage == "prospect" and store.take_notices() == []


def test_enforce_refuses_and_names_the_legal_moves(tmp_path):
    store = make(tmp_path)
    company(store)
    with pytest.raises(ValidationError) as err:
        store.update_company("acme", stage="prospect")
    assert err.value.errors == {
        "stage": "offer -> prospect is not allowed (allowed: discovery, won, lost)"}
    assert store.get("acme").stage == "offer"                # nothing was written
    assert store.update_company("acme", stage="won").stage == "won"


def test_warn_lets_it_through_and_says_so(tmp_path):
    store = make(tmp_path, mode="warn")
    company(store)
    assert store.update_company("acme", stage="prospect").stage == "prospect"
    assert store.take_notices() == [
        "offer -> prospect is not allowed (allowed: discovery, won, lost)"]
    assert store.take_notices() == []                        # said once


def test_force_moves_anyway_and_only_the_commit_message_says_so(tmp_path, messages):
    store = Store(tmp_path, clock=lambda: FIXED_NOW, on_write=messages.append,
                  stages=st.from_config(RULES), stage_rules="enforce")
    store.load()
    company(store)
    messages.clear()
    moved = store.update_company("acme", stage="prospect", force=True)
    assert moved.stage == "prospect"
    assert messages == ["company: acme stage offer -> prospect; stage rule overridden"]
    # The history is the ordinary one: no new key (that would need a migration).
    [entry] = [e for e in moved.stage_history if e.to_stage == "prospect"]
    assert (entry.from_stage, entry.to_stage) == ("offer", "prospect")
    # Forcing a legal move is not an override.
    messages.clear()
    store.update_company("acme", stage="discovery", force=True)
    assert messages == ["company: acme stage prospect -> discovery"]


def test_a_new_company_may_start_anywhere(tmp_path):
    store = make(tmp_path)
    assert company(store, stage="won").stage == "won"


def test_requalifying_a_parked_company_is_always_legal(tmp_path):
    store = make(tmp_path)
    store.create_company("Acme BV", stage="temp-disqualified", requalify_on="2026-09-01")
    assert store.requalify_due() == ["acme"]
    assert store.get("acme").stage == "prospect"


def test_the_first_touch_is_skipped_not_failed_when_the_rules_forbid_it(tmp_path):
    raw = [{"name": "prospect", "to": ["lost"]}, *RULES[1:]]
    store = make(tmp_path, raw=raw)
    store.create_company("Acme BV")
    store.create_contact("acme", "Jane", "Doe", email="jane@acme.example")
    it = store.create_interaction("acme", channel="email", direction="out", body="Hi")
    assert it.id and store.get("acme").stage == "prospect"
    (tmp_path / "w").mkdir()
    warn = make(tmp_path / "w", mode="warn", raw=raw)
    warn.create_company("Beta BV")
    warn.create_contact("beta", "Jo", "Roe", email="jo@beta.example")
    warn.create_interaction("beta", channel="email", direction="out", body="Hi")
    assert warn.get("beta").stage == "engaged"               # warn is not a block


def test_removing_a_stage_moves_its_companies_whatever_the_rules_say(tmp_path):
    store = make(tmp_path)
    company(store)
    assert store.remove_stage("offer", "prospect") == 1
    assert store.get("acme").stage == "prospect"


def test_check_says_about_history_the_rules_would_forbid(tmp_path):
    loose = make(tmp_path, mode="off")
    company(loose)
    loose.update_company("acme", stage="prospect")
    assert loose.stage_rule_warnings() == []                 # off: nothing to say
    strict = make(tmp_path, mode="warn")
    [line] = strict.stage_rule_warnings()
    assert line.startswith("companies/acme: stage_history 2026-09-14: offer -> prospect")
    assert strict.get("acme").stage == "prospect"            # never rewritten


# -------------------------------------------------------------------- writers


def folder_with_rules(tmp_path, mode="enforce") -> Path:
    root = init_folder(tmp_path / "crm", demo=False)
    from hermitcrm import setup as setup_steps
    setup_steps.save_stages(root, st.from_config(RULES))
    if mode != "off":
        setup_steps.set_config_values(root / "config.toml", {"stage_rules": mode})
    seed = Store(root, clock=lambda: FIXED_NOW, stages=st.from_config(RULES))
    seed.load()
    seed.create_company("Acme BV", stage="offer")
    seed.create_company("Beta BV", stage="offer")
    for args in (["add", "-A"], ["commit", "-q", "-m", "seed"]):
        git(root, *args)
    return root


@pytest.fixture
def web(tmp_path):
    root = folder_with_rules(tmp_path)
    config = load_config(root)
    config["push_enabled"] = False
    app = create_app(root, config)
    app.state.setup_platform = "linux"
    app.state.schedule_home = tmp_path / "home"
    app.state.calendar_url = lambda refresh=False: ""
    return root, app, TestClient(app, follow_redirects=False)


def test_web_the_board_move_is_refused_with_the_legal_moves(web):
    root, app, client = web
    r = client.post("/companies/acme/stage", data={"stage": "prospect"})
    assert r.status_code in (302, 303)
    page = client.get(r.headers["location"]).text
    assert "offer -&gt; prospect is not allowed" in page or "offer -> prospect is not allowed" in page
    assert app.state.store.get("acme").stage == "offer"
    client.post("/companies/acme/stage", data={"stage": "won"})
    assert app.state.store.get("acme").stage == "won"


def test_web_the_company_form_is_refused_too(web):
    root, app, client = web
    store = app.state.store
    form = {"name": "Acme BV", "stage": "prospect", "source": "other", "country": ""}
    r = client.post("/companies/acme", data=form)
    assert r.status_code == 400 and "is not allowed" in r.text
    assert "Move anyway" in r.text                          # the way out is on the page
    assert store.get("acme").stage == "offer"
    assert client.post("/companies/acme", data={**form, "force": "1"}).status_code == 303
    assert store.get("acme").stage == "prospect"


def test_web_move_anyway_overrides_and_the_commit_says_so(web):
    root, app, client = web
    r = client.post("/companies/acme/stage", data={"stage": "prospect", "force": "1"})
    assert r.status_code in (302, 303)
    assert app.state.store.get("acme").stage == "prospect"
    assert "stage rule overridden" in git(root, "log", "-1", "--format=%s")


def test_web_warn_shows_the_notice(tmp_path):
    root = folder_with_rules(tmp_path, mode="warn")
    config = load_config(root)
    config["push_enabled"] = False
    app = create_app(root, config)
    client = TestClient(app, follow_redirects=False)
    r = client.post("/companies/acme/stage", data={"stage": "prospect"})
    assert app.state.store.get("acme").stage == "prospect"
    page = client.get(r.headers["location"]).text
    assert "is not allowed" in page


def test_web_settings_saves_a_rule(web):
    root, app, client = web
    store = app.state.store
    page = client.get("/settings").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    names = store.stages.names
    i = names.index("engaged")
    data = {"csrf_token": token, "name": names, "old": names, "stage_rules": "warn",
            "role": [s.role for s in store.stages],
            "valued": [str(names.index("discovery")), str(names.index("offer"))],
            "restrict": [str(names.index("offer")), str(i)],
            "to": [f"{i}:discovery", f"{i}:won",
                   f"{names.index('offer')}:won", f"{names.index('offer')}:lost"]}
    r = client.post("/settings/stages", data=data)
    assert r.status_code in (302, 303), r.text[:300]
    assert store.stages.allowed_moves("engaged") == ["discovery", "won"]
    assert store.stages.allowed_moves("offer") == ["won", "lost"]
    assert store.stages.allowed_moves("prospect") is None
    assert store.stage_rules == "warn"
    assert 'stage_rules = "warn"' in (root / "config.toml").read_text()
    # A post that says nothing about rules (an older page) leaves them as they are.
    plain = {k: v for k, v in data.items() if k not in ("restrict", "to", "stage_rules")}
    assert client.post("/settings/stages", data=plain).status_code in (302, 303)
    assert store.stages.allowed_moves("engaged") == ["discovery", "won"]
    assert store.stage_rules == "warn"


def test_cli_set_is_refused_then_forced(tmp_path, monkeypatch, capsys):
    root = folder_with_rules(tmp_path)
    monkeypatch.setattr(crm, "_reload_server", lambda config: None)
    argv = ["set", "companies", "--where", "name=acme", "--stage", "prospect"]
    assert crm.main([*argv, "--apply"], root=root) == 2
    out = capsys.readouterr().err
    assert "offer -> prospect is not allowed (allowed: discovery, won, lost)" in out
    assert "--force" in out
    assert git(root, "status", "--porcelain") == ""
    assert crm.main([*argv, "--force"], root=root) == 0          # the dry run says so
    assert "break the stage rules" in capsys.readouterr().out
    assert crm.main([*argv, "--force", "--apply"], root=root) == 0
    capsys.readouterr()
    assert "stage rules overridden" in git(root, "log", "-1", "--format=%B")


def test_cli_stages_rules_and_set_to(tmp_path, monkeypatch, capsys):
    root = init_folder(tmp_path / "crm", demo=False)
    monkeypatch.setattr(crm, "_reload_server", lambda config: None)
    assert crm.main(["stages", "set", "offer", "--to", "won,lost", "--apply"], root=root) == 0
    capsys.readouterr()
    assert 'to = ["won", "lost"]' in (root / "config.toml").read_text()
    assert crm.main(["stages", "rules"], root=root) == 0
    out = capsys.readouterr().out
    assert "Stage rules: off" in out and "offer -> won, lost" in out
    assert crm.main(["stages", "rules", "enforce", "--apply"], root=root) == 0
    capsys.readouterr()
    assert 'stage_rules = "enforce"' in (root / "config.toml").read_text()
    assert crm.main(["stages", "set", "offer", "--to", "ghost"], root=root) == 2
    assert "no stage called 'ghost'" in capsys.readouterr().err
    assert crm.main(["stages", "set", "offer", "--any", "--apply"], root=root) == 0
    capsys.readouterr()
    assert 'to = ' not in (root / "config.toml").read_text()
    assert crm.main(["check"], root=root) == 0


def test_cli_check_says_about_old_moves(tmp_path, monkeypatch, capsys):
    root = folder_with_rules(tmp_path, mode="warn")
    store = Store(root, clock=lambda: FIXED_NOW, stages=st.from_config(RULES))
    store.load()
    store.update_company("acme", stage="prospect")
    assert crm.main(["check"], root=root) == 0                   # a warning, not an error
    assert "stage_history" in capsys.readouterr().out


def test_bulk_plan_refuses_and_force_overrides(tmp_path):
    root = folder_with_rules(tmp_path)
    store = Store(root, clock=lambda: FIXED_NOW, stages=st.from_config(RULES),
                  stage_rules="enforce")
    store.load()
    with pytest.raises(bulk.BulkError) as err:
        bulk.plan(store, "companies", ["stage=offer"], Ops(stage="prospect"))
    assert "offer -> prospect is not allowed" in str(err.value)
    plan = bulk.plan(store, "companies", ["stage=offer"], Ops(stage="prospect", force=True))
    assert plan.forced == 2
    bulk.apply(store, plan)
    assert {c.stage for c in store.companies.values()} == {"prospect"}
    assert "stage rules overridden (--force) for 2" in git(root, "log", "-1", "--format=%B")


def test_bulk_warn_lists_the_warnings_in_the_dry_run(tmp_path):
    root = folder_with_rules(tmp_path, mode="warn")
    store = Store(root, clock=lambda: FIXED_NOW, stages=st.from_config(RULES),
                  stage_rules="warn")
    store.load()
    plan = bulk.plan(store, "companies", ["stage=offer"], Ops(stage="prospect"))
    assert len(plan.warnings) == 2 and "Warning: acme: offer -> prospect" in plan.render()


def test_mcp_bulk_is_refused_and_cannot_be_forced(tmp_path):
    root = folder_with_rules(tmp_path)
    store = Store(root, clock=lambda: FIXED_NOW, stages=st.from_config(RULES),
                  stage_rules="enforce")
    store.load()
    tools = {t.name: t for t in mcp.build_tools(root, store)}
    args = {"scope": "companies", "where": ["stage=offer"],
            "ops": {"stage": "prospect", "force": True}}
    text, failed = _call(tools, "bulk_preview", **args)
    assert failed and "force" in text                         # not an op an agent has
    args["ops"] = {"stage": "prospect"}
    text, failed = _call(tools, "bulk_preview", **args)
    assert failed and "offer -> prospect is not allowed (allowed: discovery, won, lost)" in text
    assert "--force" not in text
    args["ops"] = {"stage": "won"}
    text, failed = _call(tools, "bulk_preview", **args)
    assert not failed


def _call(tools, tool, **arguments):
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": arguments}}
    payload = mcp.handle(message, tools)["result"]
    return payload["content"][0]["text"], bool(payload.get("isError"))


def test_bcc_import_logs_the_mail_and_leaves_a_forbidden_advance(tmp_path):
    from test_bcc import SETTINGS, inbox_for, raw_mail

    raw = [{"name": "prospect", "to": ["lost"]}, *RULES[1:]]
    store = make(tmp_path, raw=raw)
    store.create_company("Acme GmbH", website="acme.de")
    store.create_contact("acme", "Jane", "Doe", email="jane@acme.de")
    result = bcc.import_mails(store, inbox_for(store), [raw_mail()], SETTINGS, apply=True)
    assert result.duplicates == 0
    company = store.get("acme")
    assert [i.source for i in company.interactions] == ["bcc-import"]
    assert company.stage == "prospect"                       # the rule held, the mail is in


def test_a_csv_import_never_moves_a_stage_and_may_create_in_any(tmp_path):
    """The importer fills empty fields and creates companies; it never overwrites
    a stage, so it is not a way past the rules. A new company may start anywhere."""
    from hermitcrm.importer import apply_import, plan_import

    store = make(tmp_path)
    company(store)
    text = "name,stage\nAcme BV,prospect\nBeta BV,won\n"
    counts = apply_import(store, plan_import(store, text, mode="companies"))
    assert counts["created"] == 1 and counts["failed"] == 0
    assert store.get("acme").stage == "offer" and store.get("beta").stage == "won"
