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

"""PIPELINE.md, reports, imports, bulk edits, `check` and the filters with
stages of the user's own."""

from __future__ import annotations

from datetime import datetime

import pytest

from conftest import FIXED_NOW
from hermitcrm import adjust, bulk, cli, pipeline, reports, routines
from hermitcrm import stages as st
from hermitcrm.bulk import BulkError, Ops
from hermitcrm.importer import plan_import
from hermitcrm.store import Store

FIVE = st.from_config([
    {"name": "lead", "role": "open"}, {"name": "contacted", "role": "open"},
    {"name": "qualified", "role": "open"},
    {"name": "proposal", "role": "open", "valued": True},
    {"name": "negotiation", "role": "open", "valued": True},
    {"name": "closed-won", "role": "won"}, {"name": "closed-lost", "role": "lost"},
    {"name": "dead", "role": "closed"}, {"name": "snoozed", "role": "parked"},
])
TODAY = FIXED_NOW.date()


@pytest.fixture
def five(tmp_path, messages):
    s = Store(tmp_path, on_write=messages.append, clock=lambda: FIXED_NOW, stages=FIVE)
    s.load()
    return s


def at(store, when: str):
    store.clock = lambda: datetime.fromisoformat(when)


# ----------------------------------------------------------------------- PIPELINE.md


def test_pipeline_lists_the_open_stages_furthest_first_with_value_where_valued(five):
    five.create_company("Acme", stage="proposal", value_eur_month=3000)
    five.create_company("Beta", stage="negotiation", value_eur_month=2000)
    five.create_company("Gamma")
    text = pipeline.render(five)
    headings = [l for l in text.splitlines() if l.startswith("## ")]
    assert headings[:5] == ["## negotiation (1, 2,000 EUR/month)",
                            "## proposal (1, 3,000 EUR/month)",
                            "## qualified (0)", "## contacted (0)", "## lead (1)"]


def test_pipeline_names_the_parked_stage_and_one_bullet_per_closed_stage(five):
    five.create_company("Acme", stage="closed-won")
    five.create_company("Beta", stage="closed-lost", lost_reason="price")
    five.create_company("Gamma", stage="dead", lost_reason="not a fit")
    five.create_company("Delta", stage="snoozed", lost_reason="after summer",
                        requalify_on="2026-11-01")
    text = pipeline.render(five)
    assert "## Snoozed (1)" in text
    assert "- delta | since 2026-09-14 until 2026-11-01 | after summer |" in text
    closed = text.split("## Closed last 90 days\n")[1]
    assert closed.splitlines()[:3] == [
        "- closed-won: acme (2026-09-14)",
        "- closed-lost: beta (2026-09-14, price)",
        "- dead: gamma (2026-09-14, not a fit)"]


def test_pipeline_has_no_parked_section_without_a_parked_stage(tmp_path):
    s = Store(tmp_path, clock=lambda: FIXED_NOW, stages=st.from_config(
        [{"name": "a", "role": "open"}, {"name": "b", "role": "won"}]))
    s.load()
    text = pipeline.render(s)
    assert "Temp disqualified" not in text and "## Closed last 90 days\n- none" in text


def test_pipeline_shows_companies_in_a_stage_settings_lack(five):
    five.create_company("Acme")
    five.companies["acme"].stage = "ghost"
    text = pipeline.render(five)
    assert "## Not in Settings (1)\n- acme | ghost |" in text


# --------------------------------------------------------------------------- reports


def seed_history(s):
    at(s, "2026-09-08T09:00")
    s.create_company("Acme", source="referral", value_eur_month=1000)
    s.create_company("Beta")
    s.create_company("Gamma")
    for when, stage in (("09", "contacted"), ("10", "qualified"), ("11", "proposal"),
                        ("12", "closed-won")):
        at(s, f"2026-09-{when}T09:00")
        s.update_company("acme", stage=stage)
    at(s, "2026-09-12T10:00")
    s.update_company("beta", stage="closed-lost", lost_reason="Price")
    at(s, "2026-09-14T09:00")


def test_funnel_follows_the_five_open_stages_then_won(five):
    seed_history(five)
    f = reports.funnel(five, reports.period_for("7d", TODAY))
    assert [(r["from"], r["to"]) for r in f["conversion"]] == [
        ("lead", "contacted"), ("contacted", "qualified"), ("qualified", "proposal"),
        ("proposal", "negotiation"), ("negotiation", "closed-won")]
    conv = {(r["from"], r["to"]): (r["base"], r["reached"]) for r in f["conversion"]}
    assert conv[("lead", "contacted")] == (3, 1)
    # Acme skipped negotiation straight to won: reaching later counts.
    assert conv[("proposal", "negotiation")] == (1, 1)
    assert conv[("negotiation", "closed-won")] == (1, 1)
    assert [r["stage"] for r in f["pipeline"]] == FIVE.open
    assert {r["stage"]: r["count"] for r in f["pipeline"]}["lead"] == 1     # gamma
    entered = {r["stage"]: r["count"] for r in f["entered"]}
    assert list(entered) == FIVE.names and entered["closed-won"] == 1


def test_the_funnel_ends_at_the_last_open_stage_without_a_won_stage(tmp_path):
    s = Store(tmp_path, clock=lambda: FIXED_NOW, stages=st.from_config(
        [{"name": "a", "role": "open"}, {"name": "b", "role": "open"},
         {"name": "gone", "role": "closed"}]))
    s.load()
    s.create_company("Acme")
    f = reports.funnel(s, reports.period_for("7d", TODAY))
    assert [(r["from"], r["to"]) for r in f["conversion"]] == [("a", "b")]
    o = reports.outcomes(s, reports.period_for("7d", TODAY))
    assert o["win_rate"] is None and [r["stage"] for r in o["rows"]] == ["gone"]


def test_outcomes_win_rate_comes_from_the_won_and_lost_roles(five):
    seed_history(five)
    o = reports.outcomes(five, reports.period_for("7d", TODAY))
    assert [r["stage"] for r in o["rows"]] == ["closed-won", "closed-lost", "dead"]
    rows = {r["stage"]: r for r in o["rows"]}
    assert (rows["closed-won"]["count"], rows["closed-won"]["value"]) == (1, 1000)
    assert rows["closed-lost"]["count"] == 1
    assert o["win_rate"] == 0.5
    assert [(r["reason"], r["count"]) for r in o["lost_reasons"]] == [("price", 1)]


def test_sources_count_a_win_by_its_role(five):
    seed_history(five)
    s = reports.sources(five, reports.period_for("7d", TODAY))
    assert {r["source"]: r["won"] for r in s["rows"]}["referral"] == 1


def test_the_whole_report_builds_for_a_custom_set(five):
    seed_history(five)
    out = reports.build(five, reports.period_for("30d", TODAY))
    assert out["funnel"]["pipeline"] and out["outcomes"]["rows"]


# ------------------------------------------------------------------------- import / bulk


def test_import_takes_a_configured_stage_alias_and_keeps_the_rest_in_notes(five):
    text = ("name\tstage\nAcme\tqualified\nBeta\tprospect\nGamma\n")
    plan = plan_import(five, text, mode="companies")
    fields = {r.name: r.fields for r in plan.rows}
    assert fields["Acme"].get("stage") == "qualified"
    assert "stage" not in fields["Beta"]            # not a stage of this set: notes
    assert "stage" not in fields["Gamma"]


def test_import_applies_the_old_reached_out_alias_when_engaged_exists(store):
    plan = plan_import(store, "name\tstage\nAcme\treached-out\n", mode="companies")
    assert plan.rows[0].fields["stage"] == "engaged"


def test_bulk_stage_is_checked_against_the_configured_names(five):
    five.create_company("Acme")
    plan = bulk.plan(five, "companies", [], Ops(stage="qualified"), everything=True)
    assert plan.matched == 1
    with pytest.raises(BulkError) as e:
        bulk.plan(five, "companies", [], Ops(stage="prospect"), everything=True)
    assert "Allowed: lead, contacted, qualified" in str(e.value)


# ---------------------------------------------------------------------- check / config


def write_cfg(root, line):
    (root / "config.toml").write_text(line + "\n", encoding="utf-8")


def test_validate_config_accepts_a_good_stages_line(tmp_path):
    write_cfg(tmp_path, 'stages = [{name = "lead", role = "open"}, '
                        '{name = "won", role = "won"}]')
    assert adjust.validate_config(tmp_path) == []


@pytest.mark.parametrize("line,needle", [
    ('stages = "lead"', "must be a list"),
    ('stages = [{name = "lead", role = "sideways"}]', "sideways"),
    ('stages = [{name = "Lead", role = "open"}]', "a-z"),
    ('stages = [{name = "yes", role = "open"}]', "reserved"),
    ('stages = [{name = "a", role = "open"}, {name = "a", role = "won"}]', "twice"),
    ('stages = [{name = "w", role = "won"}]', "at least one stage with role open"),
    ('stages = [{name = "a", role = "open", valued = "yes"}]', "valued"),
])
def test_validate_config_names_what_is_wrong_with_stages(tmp_path, line, needle):
    write_cfg(tmp_path, line)
    found = adjust.validate_config(tmp_path)
    assert found and any(needle in p for p in found), found


def test_a_misspelt_stages_key_gets_a_hint(tmp_path):
    write_cfg(tmp_path, 'stagez = []')
    assert any("stages" in p for p in adjust.validate_config(tmp_path))


def test_stages_is_not_a_key_an_agent_may_write():
    assert "stages" not in adjust.AGENT_CONFIG_KEYS


def test_check_says_ok_for_a_valid_custom_set(tmp_path):
    from hermitcrm.datafolder import init_folder
    root = init_folder(tmp_path / "f")
    cli_store = cli.build_store(root)
    assert cli.cmd_check(cli_store)[1] == 0
    write_cfg(root, 'stages = [{name = "lead", role = "open"}, {name = "won", role = "won"}]')
    store = cli.build_store(root)
    assert store.stages.names == ["lead", "won"]
    store.create_company("Acme")
    text, code = cli.cmd_check(store)
    assert code == 0 and text.startswith("OK:")


# ---------------------------------------------------------------------- the filters


def test_filters_on_a_custom_stage_name_work_in_routines_and_lists(tmp_path):
    (tmp_path / "config.toml").write_text(
        'stages = [{name = "lead", role = "open"}, {name = "qualified", role = "open"}]\n')
    cols = routines.columns(tmp_path, "companies")
    stage_col = next(c for c in cols if c.key == "stage")
    assert stage_col.options == ["lead", "qualified"]


def test_add_and_set_take_custom_stage_names_on_the_command_line(tmp_path, capsys):
    from hermitcrm.datafolder import init_folder
    root = init_folder(tmp_path / "f")
    write_cfg(root, 'stages = [{name = "lead", role = "open"}, '
                    '{name = "qualified", role = "open"}, {name = "won", role = "won"}]')
    assert cli.main(["add", "company", "Acme", "--stage", "qualified"], root=root) == 0
    assert "stage: qualified" in (root / "companies" / "acme" / "company.md").read_text()
    assert cli.main(["add", "company", "Beta"], root=root) == 0
    assert "stage: lead" in (root / "companies" / "beta" / "company.md").read_text()
    capsys.readouterr()
    assert cli.main(["add", "company", "Gamma", "--stage", "prospect"], root=root) == 2
    assert "unknown stage 'prospect' (allowed: lead, qualified, won)" in capsys.readouterr().err


# ------------------------------------------------------------------ the sample account


def test_the_sample_account_fits_a_folder_with_stages_of_its_own(tmp_path):
    """The sample's story runs through the user's stages, and its dashboard filters
    on their names, so adding it leaves `check` clean and removing it takes it all."""
    from hermitcrm import sample
    from hermitcrm.datafolder import init_folder

    root = init_folder(tmp_path / "f")
    with open(root / "config.toml", "a", encoding="utf-8") as fh:
        fh.write('\nstages = [{name = "lead", role = "open"}, {name = "contacted", role = '
                 '"open"}, {name = "proposal", role = "open", valued = true}, '
                 '{name = "closed-won", role = "won"}]\n')
    store = cli.build_store(root)
    outcome = sample.add(store)
    company = outcome.companies[0]
    assert company.stage == "proposal"                       # the offer, in the last open stage
    assert [e.to_stage for e in company.stage_entries()] == ["lead", "contacted", "proposal"]
    dashboard = (root / sample.DASHBOARD).read_text()
    assert 'stage = ["contacted", "proposal"]' in dashboard
    assert 'stage = ["lead", "contacted", "proposal"]' in dashboard
    text, code = cli.cmd_check(store)
    assert code == 0 and text.startswith("OK:"), text
    removed = sample.remove(store)
    assert removed.companies and not (root / sample.DASHBOARD).exists()


def test_the_sample_is_unchanged_for_the_default_stages(tmp_path):
    from hermitcrm import sample
    from hermitcrm.datafolder import init_folder

    root = init_folder(tmp_path / "f")
    assert sample.dashboard_text(root) == sample.DASHBOARD_TEXT
