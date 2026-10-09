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

"""Deal stages as configuration: names, order and a role per stage."""

from __future__ import annotations

import pytest

from hermitcrm import stages as st
from hermitcrm.stages import DEFAULT_STAGES, Stage, StageSet


def five_open():
    """A custom set: five open stages, no parked stage."""
    return st.from_config([
        {"name": "lead", "role": "open"}, {"name": "contacted", "role": "open"},
        {"name": "qualified", "role": "open"},
        {"name": "proposal", "role": "open", "valued": True},
        {"name": "negotiation", "role": "open", "valued": True},
        {"name": "closed-won", "role": "won"}, {"name": "closed-lost", "role": "lost"},
    ])


# ------------------------------------------------------------------ defaults


def test_defaults_are_the_stages_hermit_always_had():
    assert DEFAULT_STAGES.names == ["prospect", "engaged", "discovery", "offer", "won",
                                    "lost", "disqualified", "temp-disqualified"]
    assert DEFAULT_STAGES.open == ["prospect", "engaged", "discovery", "offer"]
    assert DEFAULT_STAGES.board == DEFAULT_STAGES.open
    assert DEFAULT_STAGES.closed_lists == ["won", "lost", "disqualified", "temp-disqualified"]
    # PIPELINE.md lists the open stages the other way round.
    assert DEFAULT_STAGES.reverse_open == ["offer", "discovery", "engaged", "prospect"]
    assert DEFAULT_STAGES.funnel == ["prospect", "engaged", "discovery", "offer", "won"]
    assert DEFAULT_STAGES.entry == "prospect"
    assert DEFAULT_STAGES.advance_target == "engaged"
    assert DEFAULT_STAGES.valued_names == ["discovery", "offer"]


def test_default_roles():
    s = DEFAULT_STAGES
    assert [s.role_of(n) for n in s.names] == [
        "open", "open", "open", "open", "won", "lost", "closed", "parked"]
    assert s.is_closed("won") and s.is_closed("lost") and s.is_closed("disqualified")
    assert not s.is_closed("temp-disqualified") and not s.is_closed("offer")
    assert s.is_parked("temp-disqualified") and not s.is_parked("disqualified")
    assert s.is_open("engaged") and not s.is_open("won")
    # The old CLOSED_STAGES: closed for the win rate and the closed-last-90-days list.
    assert s.closed == ["won", "lost", "disqualified"]
    assert s.parked == ["temp-disqualified"]


def test_reason_rules_follow_the_role():
    s = DEFAULT_STAGES
    assert s.requires_reason("lost") and not s.requires_reason("disqualified")
    assert [n for n in s.names if s.keeps_reason(n)] == ["lost", "disqualified",
                                                         "temp-disqualified"]
    assert [n for n in s.names if s.keeps_requalify(n)] == ["temp-disqualified"]
    assert s.valued("offer") and not s.valued("prospect") and not s.valued("nope")


def test_unknown_stage_is_neither_closed_nor_parked_nor_open():
    s = DEFAULT_STAGES
    assert s.role_of("ghost") is None
    assert not s.is_closed("ghost") and not s.is_parked("ghost") and not s.is_open("ghost")
    assert not s.is_known("ghost") and s.is_known("won")
    assert not s.keeps_reason("ghost") and not s.requires_reason("ghost")


def test_the_old_reached_out_alias_only_applies_when_engaged_exists():
    assert DEFAULT_STAGES.resolve("reached-out") == "engaged"
    assert DEFAULT_STAGES.resolve("won") == "won"
    renamed = st.from_config([{"name": "contacted", "role": "open"}])
    assert renamed.resolve("reached-out") == "reached-out"


def test_absent_or_unusable_config_means_the_defaults():
    assert st.from_config(None) == DEFAULT_STAGES
    assert st.from_config([]) == DEFAULT_STAGES
    assert st.from_config("nope") == DEFAULT_STAGES
    assert st.from_config([{"name": "x", "role": "won"}]) == DEFAULT_STAGES  # no open stage


def test_to_config_round_trips_the_defaults():
    assert st.from_config(st.to_config(DEFAULT_STAGES)) == DEFAULT_STAGES
    assert st.to_config(DEFAULT_STAGES)[2] == {"name": "discovery", "role": "open",
                                               "valued": True}
    assert st.to_config(DEFAULT_STAGES)[0] == {"name": "prospect", "role": "open"}


# ------------------------------------------------------------------ parsing


def test_from_config_drops_bad_and_repeated_entries():
    s = st.from_config([
        {"name": "lead", "role": "open"},
        {"name": "lead", "role": "open"},             # repeated
        {"name": "Not Valid", "role": "open"},        # name rules
        {"name": "meh", "role": "sideways"},          # unknown role
        7, {"role": "open"},                          # no table / no name
        "qualified",                                  # a bare string is an open stage
        {"name": "won-deal", "role": "won"},
    ])
    assert s.names == ["lead", "qualified", "won-deal"]
    assert s.role_of("qualified") == "open"


def test_unknown_keys_in_a_stage_table_survive():
    s = st.from_config([{"name": "lead", "role": "open", "colour": "green"}])
    assert st.to_config(s) == [{"name": "lead", "role": "open", "colour": "green"}]


def test_valued_only_counts_on_open_stages():
    s = st.from_config([{"name": "a", "role": "open", "valued": True},
                        {"name": "b", "role": "won", "valued": True}])
    assert s.valued("a") and not s.valued("b")


@pytest.mark.parametrize("name", ["yes", "no", "on", "off", "true", "false", "null",
                                  "123", "2026-10-09", "0x1f", "Upper", "has space",
                                  "under_score", "-lead", "lead-", "a--b", "", "x" * 31])
def test_bad_names(name):
    assert st.name_problem(name)


@pytest.mark.parametrize("name", ["prospect", "temp-disqualified", "q4", "a", "x" * 30,
                                  "stage-2"])
def test_good_names(name):
    assert st.name_problem(name) is None


def test_problems_say_what_is_wrong():
    assert st.problems(None) == []
    assert st.problems(st.to_config(DEFAULT_STAGES)) == []
    msgs = st.problems([{"name": "yes", "role": "open"}, {"name": "a", "role": "open"},
                        {"name": "a", "role": "won"}, {"name": "b", "role": "sideways"}])
    text = " | ".join(msgs)
    assert "entry 1" in text and "yes" in text
    assert "a is there twice" in text
    assert "sideways" in text
    assert any("at least one" in m for m in st.problems([{"name": "w", "role": "won"}]))
    assert st.problems("nope")


# --------------------------------------------------------- derived behaviour


def test_entry_and_advance_target_with_a_custom_set():
    s = five_open()
    assert s.entry == "lead" and s.advance_target == "contacted"
    assert s.funnel == ["lead", "contacted", "qualified", "proposal", "negotiation",
                        "closed-won"]
    assert s.reverse_open[0] == "negotiation"
    assert s.valued_names == ["proposal", "negotiation"]
    assert s.parked == [] and s.closed == ["closed-won", "closed-lost"]


def test_a_single_open_stage_has_nothing_to_advance_to():
    s = st.from_config([{"name": "deal", "role": "open"}, {"name": "done", "role": "won"}])
    assert s.entry == "deal" and s.advance_target is None


def test_advance_target_must_be_open():
    s = st.from_config([{"name": "new", "role": "open"}, {"name": "done", "role": "won"}])
    assert s.advance_target is None


def test_no_won_stage_ends_the_funnel_at_the_last_open_stage():
    s = st.from_config([{"name": "a", "role": "open"}, {"name": "b", "role": "open"},
                        {"name": "gone", "role": "closed"}])
    assert s.funnel == ["a", "b"]
    assert s.with_role("won") == []


def test_inserting_a_stage_first_changes_the_entry():
    s = st.from_config([{"name": "inbox", "role": "open"}] + st.to_config(DEFAULT_STAGES))
    assert s.entry == "inbox" and s.advance_target == "prospect"


def test_stageset_is_comparable_and_iterable():
    assert StageSet([Stage("a"), Stage("b", "won")]) == StageSet([Stage("a"), Stage("b", "won")])
    assert [x.name for x in DEFAULT_STAGES] == DEFAULT_STAGES.names
    assert "won" in DEFAULT_STAGES and "ghost" not in DEFAULT_STAGES
    with pytest.raises(ValueError):
        StageSet([Stage("only-won", "won")])


# ---------------------------------------------------------------- plan_rows


def rows(names, roles=None, valued=(), olds=None, **kw):
    roles = roles or ["open"] * len(names)
    olds = names if olds is None else olds
    return st.plan_rows(names, roles, [str(i) for i in valued], olds,
                        existing=kw.pop("existing", DEFAULT_STAGES), **kw)


def default_rows():
    cfg = st.to_config(DEFAULT_STAGES)
    names = [c["name"] for c in cfg]
    roles = [c["role"] for c in cfg]
    valued = [i for i, c in enumerate(cfg) if c.get("valued")]
    return names, roles, valued


def test_plan_rows_unchanged_form_gives_back_the_same_set():
    names, roles, valued = default_rows()
    new, renames, removed, errors = rows(names, roles, valued)
    assert errors == {} and renames == {} and removed == []
    assert new == DEFAULT_STAGES


def test_plan_rows_rename_and_insert_and_drop():
    names, roles, valued = default_rows()
    olds = list(names)
    names[1] = "contacted"                         # rename engaged
    names.insert(2, "qualified"); roles.insert(2, "open"); olds.insert(2, "")
    valued = [v + 1 if v >= 2 else v for v in valued]
    i = names.index("temp-disqualified")           # drop the parked stage
    new, renames, removed, errors = rows(names, roles, valued, olds, delete=str(i))
    assert errors == {}
    assert renames == {"engaged": "contacted"}
    assert removed == ["temp-disqualified"]
    assert new.names == ["prospect", "contacted", "qualified", "discovery", "offer", "won",
                         "lost", "disqualified"]
    assert new.valued_names == ["discovery", "offer"]


def test_plan_rows_normalises_names_but_rejects_bad_ones():
    new, _, _, errors = rows(["Lead Gen", "done"], ["open", "won"], olds=["", ""],
                             existing=None)
    assert errors == {} and new.names == ["lead-gen", "done"]
    _, _, _, errors = rows(["yes", "done"], ["open", "won"], olds=["", ""], existing=None)
    assert "stages" in errors and "yes" in errors["stages"]


def test_plan_rows_errors():
    _, _, _, e = rows(["a", "a"], ["open", "won"], olds=["", ""], existing=None)
    assert "Duplicate" in e["stages"]
    _, _, _, e = rows(["a"], ["won"], olds=[""], existing=None)
    assert "open" in e["stages"]
    _, _, _, e = rows(["", "b"], ["open", "open"], olds=["a", "b"], existing=None)
    assert "Give" in e["stages"]
    _, _, _, e = rows(["a"], ["sideways"], olds=[""], existing=None)
    assert "role" in e["stages"]
    _, _, _, e = rows(["x" * 31], ["open"], olds=[""], existing=None)
    assert "30" in e["stages"]


def test_plan_rows_blank_add_row_is_ignored():
    names, roles, valued = default_rows()
    new, renames, removed, errors = rows(names + [""], roles + ["open"], valued,
                                         names + [""])
    assert errors == {} and new == DEFAULT_STAGES


def test_plan_rows_moves_a_row():
    new, *_ = rows(["a", "b", "c"], ["open", "open", "won"], move="1-up")
    assert new.names == ["b", "a", "c"]
    new, *_ = rows(["a", "b", "c"], ["open", "open", "won"], move="0-down")
    assert new.names == ["b", "a", "c"]
    new, *_ = rows(["a", "b", "c"], ["open", "open", "won"], move="0-up")  # at the top
    assert new.names == ["a", "b", "c"]


def test_plan_rows_swapping_two_names_is_two_renames():
    new, renames, removed, errors = rows(["b", "a", "z"], ["open", "open", "won"],
                                         olds=["a", "b", "z"],
                                         existing=st.from_config(
                                             [{"name": "a"}, {"name": "b"},
                                              {"name": "z", "role": "won"}]))
    assert errors == {} and renames == {"a": "b", "b": "a"} and removed == []


def test_plan_rows_keeps_unknown_keys_of_a_renamed_stage():
    existing = st.from_config([{"name": "a", "role": "open", "colour": "green"}])
    new, renames, _, errors = rows(["b"], ["open"], olds=["a"], existing=existing)
    assert errors == {} and renames == {"a": "b"}
    assert st.to_config(new) == [{"name": "b", "role": "open", "colour": "green"}]


def test_plan_rows_valued_is_dropped_off_open_stages():
    new, *_ = rows(["a", "w"], ["open", "won"], valued=[0, 1], olds=["", ""], existing=None)
    assert new.valued("a") and not new.valued("w")
    assert st.to_config(new)[1] == {"name": "w", "role": "won"}
