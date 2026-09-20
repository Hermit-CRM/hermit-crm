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

"""User-defined fields: the schema, and what a folder without one looks like."""

import pytest

from hermitcrm import fields
from hermitcrm.fields import FieldDef, FieldError


def test_a_folder_without_the_file_has_no_fields(tmp_path):
    """The default install. Nothing to configure, nothing shown, no file."""
    assert fields.load(tmp_path) == []
    assert not (tmp_path / "fields.toml").exists()


def test_round_trip_through_the_file(tmp_path):
    defs = [
        FieldDef(key="fit_score", label="fit", type="number",
                 show_in=["detail", "companies"], help="0 to 100"),
        FieldDef(key="segment", type="select", options=["smb", "enterprise"],
                 show_in=["detail"]),
        FieldDef(key="seniority", applies_to="contact", show_in=["detail", "contacts"]),
    ]
    fields.write(tmp_path, defs)
    back = fields.load(tmp_path)
    assert [(d.key, d.label, d.type, d.applies_to, d.show_in, d.options) for d in back] == \
           [("fit_score", "fit", "number", "company", ["detail", "companies"], []),
            ("segment", "segment", "select", "company", ["detail"], ["smb", "enterprise"]),
            ("seniority", "seniority", "text", "contact", ["detail", "contacts"], [])]


def test_writing_no_fields_removes_the_file(tmp_path):
    fields.write(tmp_path, [FieldDef(key="x")])
    assert (tmp_path / "fields.toml").exists()
    fields.write(tmp_path, [])
    assert not (tmp_path / "fields.toml").exists()


def test_a_label_defaults_to_the_key_read_aloud():
    assert FieldDef(key="fte_estimate").label == "fte estimate"
    assert FieldDef(key="fte_estimate", label="FTE").label == "FTE"


@pytest.mark.parametrize("entry, expected", [
    ({}, "a field needs a key"),
    ({"key": "stage"}, "already a built-in company field"),
    ({"key": "email", "applies_to": "contact"}, "already a built-in contact field"),
    ({"key": "x", "type": "colour"}, "type must be one of"),
    ({"key": "x", "applies_to": "invoice"}, "applies_to must be one of"),
    ({"key": "x", "type": "select"}, "a select field needs options"),
    ({"key": "x", "show_in": ["messages"]}, "not a place a company field can appear"),
])
def test_a_definition_it_cannot_honour_is_refused(entry, expected):
    """Silently dropping a field would make its stored values uneditable."""
    with pytest.raises(FieldError) as exc:
        fields.parse({"field": [entry]})
    assert expected in str(exc.value)


def test_the_same_key_twice_is_refused():
    with pytest.raises(FieldError, match="defined twice"):
        fields.parse({"field": [{"key": "x"}, {"key": "x"}]})
    # ...but the same key on two different records is fine
    assert len(fields.parse({"field": [{"key": "x"},
                                       {"key": "x", "applies_to": "contact"}]})) == 2


def test_a_key_is_slugified_like_everything_else():
    assert fields.parse({"field": [{"key": " My Score "}]})[0].key == "my_score"


def test_coercing_a_form_string():
    number = FieldDef(key="n", type="number")
    assert number.coerce(" 42 ") == 42 and number.coerce("1.5") == 1.5
    assert number.coerce("") is None and number.coerce(None) is None
    with pytest.raises(ValueError, match="wants a number"):
        number.coerce("many")

    when = FieldDef(key="d", type="date")
    assert str(when.coerce("2026-09-18")) == "2026-09-18"
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        when.coerce("18/09/2026")

    pick = FieldDef(key="s", type="select", options=["a", "b"])
    assert pick.coerce("a") == "a"
    with pytest.raises(ValueError, match="must be one of a, b"):
        pick.coerce("c")

    assert FieldDef(key="t").coerce("  two  words ") == "two  words"


def test_coerce_all_only_touches_what_was_submitted():
    defs = [FieldDef(key="a", type="number"), FieldDef(key="b")]
    values, errors = fields.coerce_all(defs, {"a": "1"})
    assert values == {"a": 1} and errors == {}          # b was not in the form
    values, errors = fields.coerce_all(defs, {"a": "x", "b": "y"})
    assert values == {"b": "y"} and "a" in errors


def test_apply_removes_a_cleared_value():
    assert fields.apply({"a": 1, "b": 2}, {"a": None}) == {"b": 2}
    assert fields.apply({"a": 1}, {"a": 5, "c": "x"}) == {"a": 5, "c": "x"}
    assert fields.apply({"keep_me": "yes"}, {}) == {"keep_me": "yes"}


def test_display_is_what_the_ui_shows():
    assert FieldDef(key="x").display(None) == ""
    assert FieldDef(key="x").display(0) == "0"
    assert FieldDef(key="x").display(["a", "b"]) == "a, b"
