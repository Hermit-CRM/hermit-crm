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

"""Task types: the user's own labels for to-dos, kept in config.toml."""

from __future__ import annotations

import tomllib

from hermitcrm import task_types as tt
from hermitcrm.setup import save_task_types, set_config_values


def test_from_config_keeps_order_defaults_colour_and_drops_bad_entries():
    raw = [{"name": " pipeline   follow-up ", "colour": "green"},
           {"name": "prospecting", "colour": "pink"},
           {"name": "Prospecting", "colour": "blue"},   # duplicate, any case
           {"name": ""}, "lost deals", 7]
    assert tt.from_config(raw) == [tt.TaskType("pipeline follow-up", "green"),
                                   tt.TaskType("prospecting", "grey"),
                                   tt.TaskType("lost deals", "grey")]
    assert tt.from_config(None) == [] and tt.from_config("x") == []


def test_colour_of_is_none_for_a_type_not_in_settings():
    types = [tt.TaskType("prospecting", "blue")]
    assert tt.colour_of(types, "prospecting") == "blue"
    assert tt.colour_of(types, "gone") is None
    assert tt.names(types) == ["prospecting"]


def test_plan_rows_adds_renames_deletes_and_moves():
    names = ["pipeline follow-up", "lost deal revival", "prospecting", "new one"]
    colours = ["green", "amber", "blue", "violet"]
    olds = ["pipeline follow-up", "lost deals", "prospecting", ""]
    types, renames, errors = tt.plan_rows(names, colours, olds, delete="", move="2-up")
    assert errors == {}
    assert tt.names(types) == ["pipeline follow-up", "prospecting",
                               "lost deal revival", "new one"]
    assert renames == {"lost deals": "lost deal revival"}

    types, renames, _ = tt.plan_rows(names, colours, olds, delete="1", move="")
    assert "lost deal revival" not in tt.names(types) and renames == {}


def test_plan_rows_skips_the_blank_add_row_and_refuses_bad_names():
    types, _, errors = tt.plan_rows(["a", ""], ["green", "green"], ["a", ""], "", "")
    assert tt.names(types) == ["a"] and errors == {}
    _, _, errors = tt.plan_rows(["a", "A"], ["green", "blue"], ["", ""], "", "")
    assert "Duplicate" in errors["task_types"]
    _, _, errors = tt.plan_rows(["x" * 41], ["green"], [""], "", "")
    assert "40" in errors["task_types"]
    _, _, errors = tt.plan_rows([""], ["green"], ["lost deals"], "", "")
    assert "Delete" in errors["task_types"]


def test_save_task_types_writes_one_line_that_toml_reads_back(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('# mine\nport = 8765\n', encoding="utf-8")
    types = [tt.TaskType('say "hi"', "green"), tt.TaskType("lost deals", "amber")]
    save_task_types(tmp_path, types)
    text = cfg.read_text(encoding="utf-8")
    assert text.startswith("# mine\nport = 8765\n")
    assert sum(1 for line in text.splitlines() if line.startswith("task_types")) == 1
    assert tt.from_config(tomllib.loads(text)["task_types"]) == types
    set_config_values(cfg, {"port": 9000})          # other writes leave it alone
    assert tt.from_config(tomllib.loads(cfg.read_text())["task_types"]) == types
