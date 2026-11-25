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

"""`call_outcome` and `call_type`: what happened on the line of an outbound
call, and what it was for. Both come from editable lists in config.toml
(`call_outcomes`, `call_types`). Fictional names only."""

from __future__ import annotations

import pytest

from conftest import FIXED_NOW
from hermitcrm import datafolder, fields, models
from hermitcrm.fields import FieldError
from hermitcrm.models import Interaction, ValidationError
from hermitcrm.store import DEFAULT_CONFIG, Store, split_file


@pytest.fixture
def seeded(store):
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe")
    return store


# ------------------------------------------------------------ Task 1: model

def test_the_defaults_are_the_agreed_lists_in_order():
    assert models.DEFAULT_CALL_OUTCOMES == (
        "connected", "conversation", "message to other human", "voicemail message",
        "no answer", "busy", "rejected by automated call screening", "wrong number")
    assert models.DEFAULT_CALL_TYPES == ("prospecting", "pipeline development")
    assert DEFAULT_CONFIG["call_outcomes"] == list(models.DEFAULT_CALL_OUTCOMES)
    assert DEFAULT_CONFIG["call_types"] == list(models.DEFAULT_CALL_TYPES)


@pytest.mark.parametrize("typed,stored", [
    ("No Answer", "no answer"), ("  voicemail   message ", "voicemail message"),
    ("", ""), (None, ""), ("left a message", "left a message")])
def test_match_choice_finds_the_configured_spelling(typed, stored):
    assert models.match_choice(typed, list(models.DEFAULT_CALL_OUTCOMES)) == stored


@pytest.mark.parametrize("channel,direction,expected", [
    ("call", "out", True), ("call", "in", False), ("email", "out", False),
    ("note", "", False)])
def test_is_outbound_call(channel, direction, expected):
    assert models.is_outbound_call(channel, direction) is expected


def test_an_outbound_call_round_trips_both_keys_in_order():
    i = Interaction(id="x", date=FIXED_NOW, channel="call", direction="out",
                    contact="jane-doe", outcome="successful",
                    call_outcome="no answer", call_type="prospecting")
    meta = models.interaction_to_frontmatter(i)
    keys = list(meta)
    assert keys.index("call_outcome") == keys.index("outcome") + 1
    assert keys.index("call_type") == keys.index("call_outcome") + 1
    assert keys.index("source") == keys.index("call_type") + 1
    back = models.interaction_from_dict(meta, "", "x")
    assert back.call_outcome == "no answer" and back.call_type == "prospecting"
    assert back.extra == {}


def test_reading_trims_a_hand_written_value():
    meta = {"date": FIXED_NOW, "channel": "call", "direction": "out",
            "call_outcome": "  busy ", "call_type": " prospecting"}
    back = models.interaction_from_dict(meta, "", "x")
    assert back.call_outcome == "busy" and back.call_type == "prospecting"


def test_an_interaction_without_call_fields_writes_no_such_keys():
    i = Interaction(id="x", date=FIXED_NOW, channel="email", direction="out")
    meta = models.interaction_to_frontmatter(i)
    assert "call_outcome" not in meta and "call_type" not in meta


def test_a_new_config_toml_documents_both_keys():
    text = datafolder.render_config()
    assert "# call_outcomes = [" in text and "# call_types = [" in text
    assert "what happened on the line" in text and "what the call was for" in text


def test_a_custom_field_named_call_outcome_is_reported_as_built_in():
    for key in ("call_outcome", "call_type"):
        with pytest.raises(FieldError) as exc:
            fields.parse({"field": [{"key": key, "applies_to": "interaction"}]})
        assert "already a built-in interaction field" in str(exc.value)


# ------------------------------------------------------------ Task 2: store

def _meta(store, it):
    return split_file((store.root / "companies/acme/interactions" / f"{it.id}.md").read_text())[0]


def _call(store, **kw):
    return store.create_interaction("acme", "call", "out", contact="jane-doe", **kw)


def test_an_outbound_call_keeps_its_outcome_and_type(seeded):
    it = _call(seeded, call_outcome="Voicemail message", call_type="prospecting")
    meta = _meta(seeded, it)
    assert meta["call_outcome"] == "voicemail message" and meta["call_type"] == "prospecting"


def test_an_outbound_call_without_them_has_no_such_keys(seeded):
    meta = _meta(seeded, _call(seeded))
    assert "call_outcome" not in meta and "call_type" not in meta


def test_an_unknown_call_outcome_is_refused_with_the_allowed_list(seeded):
    with pytest.raises(ValidationError, match="allowed: connected, conversation"):
        _call(seeded, call_outcome="maybe")


def test_an_unknown_call_type_is_refused_with_the_allowed_list(seeded):
    with pytest.raises(ValidationError, match="unknown call type 'cold'.*prospecting"):
        _call(seeded, call_type="cold")


def test_the_store_checks_against_its_own_lists(tmp_path):
    s = Store(tmp_path, clock=lambda: FIXED_NOW, call_outcomes=["reached", "not reached"],
              call_types=["cold"])
    s.load()
    s.create_company("Acme GmbH", country="DE")
    s.create_contact("acme", "Jane", "Doe")
    assert _call(s, call_outcome="Reached", call_type="cold").call_outcome == "reached"
    with pytest.raises(ValidationError, match="allowed: reached, not reached"):
        _call(s, call_outcome="connected")


def test_an_empty_list_falls_back_to_the_defaults(tmp_path):
    s = Store(tmp_path, call_outcomes=[], call_types=None)
    assert s.call_outcomes == list(models.DEFAULT_CALL_OUTCOMES)
    assert s.call_types == list(models.DEFAULT_CALL_TYPES)


@pytest.mark.parametrize("channel,direction", [("email", "out"), ("call", "in")])
def test_call_fields_on_anything_but_an_outbound_call_are_refused(seeded, channel, direction):
    with pytest.raises(ValidationError, match="only for an outbound call"):
        seeded.create_interaction("acme", channel, direction, contact="jane-doe",
                                  call_outcome="busy")
    with pytest.raises(ValidationError, match="a call type is only for an outbound call"):
        seeded.create_interaction("acme", channel, direction, contact="jane-doe",
                                  call_type="prospecting")


def test_flipping_an_outbound_call_to_in_clears_the_call_fields(seeded):
    it = _call(seeded, call_outcome="busy", call_type="prospecting")
    new = seeded.update_interaction("acme", it.id, direction="in")
    meta = _meta(seeded, new)
    assert new.call_outcome == "" and new.call_type == ""
    assert "call_outcome" not in meta and "call_type" not in meta


def test_changing_the_channel_with_the_old_values_still_given_clears_them(seeded):
    it = _call(seeded, call_outcome="busy", call_type="prospecting")
    new = seeded.update_interaction("acme", it.id, channel="email", call_outcome="busy",
                                    call_type="prospecting")
    assert new.call_outcome == "" and new.call_type == ""


def test_editing_the_subject_keeps_the_call_fields(seeded):
    it = _call(seeded, call_outcome="busy", call_type="prospecting")
    new = seeded.update_interaction("acme", it.id, subject="Rang again")
    assert new.call_outcome == "busy" and new.call_type == "prospecting"


def test_an_edit_can_change_and_clear_them(seeded):
    it = _call(seeded, call_outcome="busy")
    new = seeded.update_interaction("acme", it.id, call_outcome="No answer",
                                    call_type="pipeline development")
    assert new.call_outcome == "no answer" and new.call_type == "pipeline development"
    new = seeded.update_interaction("acme", new.id, call_outcome="")
    assert new.call_outcome == "" and "call_outcome" not in _meta(seeded, new)


def test_a_value_no_longer_in_settings_survives_an_unrelated_edit(seeded):
    it = _call(seeded, call_outcome="busy")
    seeded.call_outcomes = ["reached"]
    new = seeded.update_interaction("acme", it.id, subject="x", call_outcome="busy")
    assert new.call_outcome == "busy"
    with pytest.raises(ValidationError, match="allowed: reached"):
        seeded.update_interaction("acme", it.id, call_outcome="wrong number")


def test_the_store_reads_them_back(seeded):
    it = _call(seeded, call_outcome="busy", call_type="prospecting")
    seeded.load()
    again = next(i for i in seeded.get("acme").interactions if i.id == it.id)
    assert again.call_outcome == "busy" and again.call_type == "prospecting"
