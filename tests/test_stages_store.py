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

"""What configurable stages do to the Store: the rules follow the role, not the name."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from conftest import FIXED_NOW, read
from hermitcrm import cli
from hermitcrm import stages as st
from hermitcrm.models import StageChange, ValidationError
from hermitcrm.store import Store

CUSTOM = st.from_config([
    {"name": "lead", "role": "open"}, {"name": "contacted", "role": "open"},
    {"name": "qualified", "role": "open"},
    {"name": "proposal", "role": "open", "valued": True},
    {"name": "closed-won", "role": "won"}, {"name": "closed-lost", "role": "lost"},
    {"name": "dead", "role": "closed"}, {"name": "snoozed", "role": "parked"},
])


@pytest.fixture
def cs(tmp_path, messages):
    """A store with the custom stage set."""
    s = Store(tmp_path, on_write=messages.append, clock=lambda: FIXED_NOW, stages=CUSTOM)
    s.load()
    return s


def front(store, slug):
    return read(store.root / "companies" / slug / "company.md")


# ------------------------------------------------------------ create / strict writes


def test_a_new_company_starts_in_the_entry_stage_and_that_start_is_implicit(cs):
    c = cs.create_company("Acme")
    assert c.stage == "lead" and c.stage_history == []
    assert "stage: lead" in front(cs, "acme")
    assert [(e.from_stage, e.to_stage) for e in c.stage_entries()] == [("", "lead")]


def test_another_start_stage_is_recorded_in_the_history(cs):
    c = cs.create_company("Acme", stage="qualified")
    assert [(e.from_stage, e.to_stage) for e in c.stage_history] == [("", "qualified")]


def test_writes_accept_only_configured_stages(cs):
    with pytest.raises(ValidationError) as e:
        cs.create_company("Acme", stage="prospect")      # a default name, not in this set
    assert "unknown stage 'prospect'" in e.value.errors["stage"]
    assert "lead, contacted" in e.value.errors["stage"]
    cs.create_company("Beta")
    with pytest.raises(ValidationError):
        cs.update_company("beta", stage="engaged")


def test_the_stage_a_company_already_has_may_stay_when_the_rest_is_saved(cs, tmp_path):
    cs.create_company("Acme")
    path = cs.root / "companies" / "acme" / "company.md"
    path.write_text(read(path).replace("stage: lead", "stage: old-stage"), encoding="utf-8")
    cs.load()
    # Unchanged value passes; anything else still has to be configured.
    cs.update_company("acme", stage="old-stage", product_oneliner="Makes anvils")
    assert cs.companies["acme"].stage == "old-stage"
    assert cs.companies["acme"].product_oneliner == "Makes anvils"
    with pytest.raises(ValidationError):
        cs.update_company("acme", stage="also-old")


def test_old_alias_is_applied_only_when_the_target_exists(cs, store):
    store.create_company("Acme")
    assert store.update_company("acme", stage="reached-out").stage == "engaged"
    cs.create_company("Acme")
    with pytest.raises(ValidationError):
        cs.update_company("acme", stage="reached-out")     # no stage called engaged here


# ------------------------------------------------------------------ reasons by role


def test_a_lost_stage_needs_a_reason_whatever_it_is_called(cs):
    with pytest.raises(ValidationError) as e:
        cs.create_company("Acme", stage="closed-lost")
    assert e.value.errors["lost_reason"] == "lost_reason is required when stage is closed-lost"
    cs.create_company("Beta")
    cs.update_company("beta", stage="closed-lost", lost_reason="went with a rival")
    assert cs.companies["beta"].lost_reason == "went with a rival"
    # "lost" is just a name here: no reason needed for a stage that is not lost-role.
    cs.update_company("beta", stage="dead")
    assert cs.companies["beta"].lost_reason == "went with a rival"   # closed keeps the reason


def test_only_lost_closed_and_parked_stages_keep_a_reason(cs):
    cs.create_company("Acme")
    cs.update_company("acme", stage="dead", lost_reason="no budget")
    assert cs.companies["acme"].lost_reason == "no budget"
    cs.update_company("acme", stage="contacted")
    assert cs.companies["acme"].lost_reason == ""
    cs.update_company("acme", stage="closed-won", lost_reason="ignored")
    assert cs.companies["acme"].lost_reason == ""


def test_only_a_parked_stage_keeps_a_requalify_date(cs):
    cs.create_company("Acme")
    cs.update_company("acme", stage="snoozed", requalify_on="2026-12-01", lost_reason="later")
    c = cs.companies["acme"]
    assert c.requalify_on == date(2026, 12, 1) and c.lost_reason == "later"
    assert c.is_parked and not c.is_closed and not c.is_active
    cs.update_company("acme", stage="dead", requalify_on="2026-12-01", lost_reason="no")
    assert cs.companies["acme"].requalify_on is None
    assert cs.companies["acme"].is_closed


def test_a_removed_stage_keeps_its_reason_and_date_when_other_fields_change(cs):
    cs.create_company("Acme", stage="dead", lost_reason="no budget")
    path = cs.root / "companies" / "acme" / "company.md"
    path.write_text(read(path).replace("stage: dead", "stage: gone"), encoding="utf-8")
    cs.load()
    cs.update_company("acme", product_oneliner="x")
    assert cs.companies["acme"].lost_reason == "no budget"


# ----------------------------------------------------------------- auto-advance, requalify


def test_first_outbound_touch_moves_entry_to_the_next_open_stage(cs, messages):
    cs.create_company("Acme")
    cs.create_contact("acme", first_name="Jane", last_name="Doe")
    cs.create_interaction("acme", channel="email", direction="out", contact="jane-doe",
                          subject="Hello", date=datetime(2026, 9, 14, 9, 0))
    assert cs.companies["acme"].stage == "contacted"
    assert "stage lead -> contacted" in messages[-1]
    # Already past the entry stage: a second touch moves nothing.
    cs.create_interaction("acme", channel="email", direction="out", contact="jane-doe",
                          subject="Again", date=datetime(2026, 9, 15, 9, 0))
    assert cs.companies["acme"].stage == "contacted"


def test_a_note_is_not_contact(cs):
    cs.create_company("Acme")
    cs.create_interaction("acme", channel="note", direction="", subject="memo",
                          date=datetime(2026, 9, 14, 9, 0))
    assert cs.companies["acme"].stage == "lead"


def test_nothing_advances_when_the_entry_stage_is_the_only_open_one(tmp_path, messages):
    one = st.from_config([{"name": "deal", "role": "open"}, {"name": "done", "role": "won"}])
    s = Store(tmp_path, on_write=messages.append, clock=lambda: FIXED_NOW, stages=one)
    s.load()
    s.create_company("Acme")
    s.create_interaction("acme", channel="email", direction="out", subject="Hi",
                         date=datetime(2026, 9, 14, 9, 0))
    assert s.companies["acme"].stage == "deal"


def test_requalify_returns_a_parked_company_to_the_entry_stage(cs):
    cs.create_company("Acme")
    cs.update_company("acme", stage="snoozed", requalify_on="2026-09-01")
    assert cs.requalify_due(date(2026, 9, 14)) == ["acme"]
    assert cs.companies["acme"].stage == "lead"


def test_requalify_ignores_closed_stages(cs):
    cs.create_company("Acme")
    cs.update_company("acme", stage="dead", requalify_on="2026-09-01")
    assert cs.requalify_due(date(2026, 9, 14)) == []


# ------------------------------------------------------------------ lenient load


def test_a_stage_not_in_settings_loads_and_is_warned_about(cs):
    cs.create_company("Acme")
    cs.create_company("Beta")
    path = cs.root / "companies" / "acme" / "company.md"
    path.write_text(read(path).replace("stage: lead", "stage: negotiating"), encoding="utf-8")
    problems = cs.load()
    assert problems == [] and cs.companies["acme"].stage == "negotiating"
    c = cs.companies["acme"]
    assert not c.is_closed and not c.is_parked and c.is_active
    assert [x.slug for x in cs.off_board()] == ["acme"]
    assert cs.stage_warnings() == [
        "companies/acme: stage 'negotiating' is not in config.toml stages"]
    text, code = cli.cmd_check(cs)
    assert code == 0 and "stage 'negotiating' is not in config.toml stages" in text
    assert text.splitlines()[-1].startswith("OK:")


def test_an_unknown_stage_in_the_history_loads(cs):
    cs.create_company("Acme")
    path = cs.root / "companies" / "acme" / "company.md"
    path.write_text(read(path).replace(
        "stage: lead\n", "stage: lead\nstage_history:\n- date: 2026-09-01\n  from: ''\n"
        "  to: ghost-stage\n- date: 2026-09-02\n  from: ghost-stage\n  to: lead\n"),
        encoding="utf-8")
    assert cs.load() == []
    assert [e.to_stage for e in cs.companies["acme"].stage_history] == ["ghost-stage", "lead"]


def test_a_lost_stage_without_a_reason_is_still_a_load_error(cs):
    cs.create_company("Acme", stage="closed-lost", lost_reason="x")
    path = cs.root / "companies" / "acme" / "company.md"
    path.write_text(read(path).replace("lost_reason: x\n", ""), encoding="utf-8")
    problems = cs.load()
    assert len(problems) == 1 and "lost_reason is required when stage is closed-lost" in \
        problems[0].message


# ----------------------------------------------------------------------- rename sweep


def test_rename_sweep_rewrites_stage_and_every_history_entry_in_one_commit(cs, messages):
    cs.create_company("Acme")
    cs.update_company("acme", stage="contacted")
    cs.update_company("acme", stage="qualified")
    cs.create_company("Beta", stage="contacted")
    cs.create_company("Gamma")
    cs.update_company("gamma", stage="proposal")
    updated = cs.companies["acme"].updated
    messages.clear()

    assert cs.rename_stages({"contacted": "reached"}) == 2
    assert messages == ['settings: stage "contacted" renamed to "reached" (2 companies)']
    acme, beta = cs.companies["acme"], cs.companies["beta"]
    assert acme.stage == "qualified" and beta.stage == "reached"
    assert [(e.from_stage, e.to_stage) for e in acme.stage_history] == [
        ("lead", "reached"), ("reached", "qualified")]
    assert [(e.from_stage, e.to_stage) for e in beta.stage_history] == [("", "reached")]
    assert acme.updated == updated                  # a housekeeping sweep, not an edit
    assert "from: reached" in front(cs, "acme")
    assert cs.companies["gamma"].stage_history[0].from_stage == "lead"   # untouched
    assert cs.rename_stages({"contacted": "again"}) == 0      # nothing left to rename


def test_two_stages_can_swap_names(cs, messages):
    cs.create_company("Acme", stage="lead")
    cs.create_company("Beta", stage="qualified")
    messages.clear()
    assert cs.rename_stages({"lead": "qualified", "qualified": "lead"}) == 2
    assert cs.companies["acme"].stage == "qualified" and cs.companies["beta"].stage == "lead"
    assert messages[0].startswith('settings: stages renamed: "lead" to "qualified", ')


def test_rename_leaves_the_rest_of_the_file_byte_for_byte(cs):
    cs.create_company("Acme", notes="Keep   this\n\n  exactly.\n")
    before = front(cs, "acme")
    cs.rename_stages({"lead": "inbox"})
    assert front(cs, "acme") == before.replace("stage: lead", "stage: inbox")


# ------------------------------------------------------------------ remove with move-to


def test_removing_a_stage_moves_its_companies_and_records_the_move(cs, messages):
    cs.create_company("Acme", stage="qualified")
    cs.create_company("Beta", stage="qualified")
    cs.create_company("Gamma")
    messages.clear()
    assert cs.remove_stage("qualified", "contacted") == 2
    assert messages == ['settings: stage "qualified" removed, 2 companies moved to "contacted"']
    for slug in ("acme", "beta"):
        c = cs.companies[slug]
        assert c.stage == "contacted"
        assert (c.stage_history[-1].from_stage, c.stage_history[-1].to_stage) == (
            "qualified", "contacted")
    assert cs.companies["gamma"].stage == "lead"


def test_moving_into_a_lost_stage_needs_a_reason_for_companies_without_one(cs):
    cs.create_company("Acme", stage="qualified")
    with pytest.raises(ValidationError) as e:
        cs.remove_stage("qualified", "closed-lost")
    assert "reason" in e.value.errors["lost_reason"]
    assert cs.companies["acme"].stage == "qualified"
    assert cs.remove_stage("qualified", "closed-lost", "stage removed") == 1
    assert cs.companies["acme"].lost_reason == "stage removed"


def test_remove_needs_a_configured_target(cs):
    cs.create_company("Acme", stage="qualified")
    with pytest.raises(ValidationError) as e:
        cs.remove_stage("qualified", "nowhere")
    assert "move_to" in e.value.errors
    assert cs.remove_stage("proposal", "lead") == 0       # nobody in it


# --------------------------------------------------------------- materialise history


def test_materialise_writes_the_implied_start_of_a_history_less_company(cs, messages):
    cs.create_company("Acme")                              # lead, no history written
    cs.create_company("Beta", stage="qualified")           # has its start already
    messages.clear()
    assert cs.materialise_stage_history() == 1
    assert [(e.from_stage, e.to_stage) for e in cs.companies["acme"].stage_history] == [
        ("", "lead")]
    assert "stage_history" in front(cs, "acme")
    assert messages == ["settings: stage history written out for 1 company"]
    assert cs.materialise_stage_history() == 0             # idempotent, no second commit
    assert len(messages) == 1


def test_changing_the_entry_stage_does_not_re_date_old_companies(cs):
    """The implied start follows the entry stage, so it is written first."""
    cs.create_company("Acme")
    new = st.from_config([{"name": "inbox", "role": "open"}, *st.to_config(CUSTOM)])
    assert st.entry_moves(CUSTOM, new)
    cs.materialise_stage_history()
    cs.set_stages(new)
    c = cs.companies["acme"]
    assert [(e.from_stage, e.to_stage) for e in c.stage_entries()] == [("", "lead")]
    # Without it the history would now start in the new entry stage.
    bare = type(c)(name="Bare", slug="bare", stage="lead", stages=new,
                   created=datetime(2026, 9, 1, 9, 0))
    assert bare.stage_entries()[0].to_stage == "inbox"


def test_entry_moves_sees_through_a_rename(cs):
    renamed = st.from_config([{"name": "first", "role": "open"}, *st.to_config(CUSTOM)[1:]])
    assert not st.entry_moves(CUSTOM, renamed, {"lead": "first"})
    assert st.entry_moves(CUSTOM, renamed, {})


# --------------------------------------------------------------------------- merging


def test_merge_follows_the_roles_of_the_configured_stages(cs):
    cs.create_company("Acme")
    cs.create_company("Zorro Holdings", stage="dead", lost_reason="duplicate")
    merged = cs.merge_companies("acme", "zorro-holdings", {"stage": "drop"})
    assert merged.stage == "dead" and merged.lost_reason == "duplicate"
    assert merged.stage_history[-1].to_stage == "dead"


# ----------------------------------------------------------------------- misc


def test_stage_counts_include_stages_the_settings_do_not_have(cs):
    cs.create_company("Acme")
    cs.create_company("Beta", stage="dead", lost_reason="x")
    cs.companies["beta"].stage = "ghost"
    assert cs.stage_counts() == {"lead": 1, "ghost": 1}


def test_stagechange_equality_is_by_value():
    assert StageChange(date(2026, 1, 1), "a", "b") == StageChange(date(2026, 1, 1), "a", "b")


# ------------------------------------------------------------ a change that fails half-way


def test_a_stage_change_that_fails_part_way_puts_every_file_back(cs, messages, monkeypatch):
    from hermitcrm import setup as setup_steps
    from hermitcrm import stage_ops
    setup_steps.save_stages(cs.root, CUSTOM)
    cs.create_company("Acme")
    cs.update_company("acme", stage="contacted")
    cs.create_company("Beta", stage="qualified")
    config = (cs.root / "config.toml").read_bytes()
    files = {slug: (cs.root / "companies" / slug / "company.md").read_bytes()
             for slug in ("acme", "beta")}
    kept = [s for s in st.to_config(CUSTOM) if s["name"] != "qualified"]
    new = st.from_config([{**s, "name": "reached"} if s["name"] == "contacted" else s
                          for s in kept])
    change = stage_ops.Change(CUSTOM, new, {"contacted": "reached"}, ["qualified"], "lead")

    def disk_full(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(cs, "remove_stage", disk_full)
    messages.clear()

    with pytest.raises(OSError):
        stage_ops.apply(cs, cs.root, change, lambda: cs.set_stages(new),
                        deactivate=lambda: cs.set_stages(CUSTOM))

    assert (cs.root / "config.toml").read_bytes() == config
    for slug, data in files.items():
        assert (cs.root / "companies" / slug / "company.md").read_bytes() == data
    assert cs.stages == CUSTOM
    assert cs.companies["acme"].stage == "contacted" and cs.companies["beta"].stage == "qualified"
    assert messages == []                     # nothing was committed
