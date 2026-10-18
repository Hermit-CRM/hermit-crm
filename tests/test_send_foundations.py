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

"""Outreach send, task 1: the new states and item keys, their migrations, the
`outreach` interaction source, the send_password secret and the config keys.
Every name and address is made up."""

from __future__ import annotations

from datetime import datetime

import pytest

from hermitcrm import migrations, outreach, secrets
from hermitcrm.datafolder import CONFIG_DOCS
from hermitcrm.models import InteractionSource
from hermitcrm.store import DEFAULT_CONFIG, split_file
from outreach_fakes import NOW, demo

NEW_KEYS = ("queued", "send_at", "send_hash", "message_id", "send_tries", "send_error",
            "send_note", "invite_sent", "accepted", "pitch_sent")


def ready_item(**kw) -> outreach.Item:
    base = dict(id="2026-10-16T0900-email-acme-jo", state="ready", company="acme-robotics",
                contact="jo-lane", channel="email", subject="Your second office",
                body="Hi Jo,\n\nOne question: where does it hurt most?\n\nSam\n",
                ready=NOW, created=NOW)
    base.update(kw)
    return outreach.Item(**base)


# -------------------------------------------------------------- states, keys


def test_queued_and_failed_are_open_states():
    for state in ("queued", "failed"):
        assert state in outreach.STATES
        assert ready_item(state=state).is_open


def test_the_new_keys_follow_skipped_in_item_keys_order():
    keys = outreach.ITEM_KEYS
    at = keys.index("skipped")
    assert keys[at + 1:at + 1 + len(NEW_KEYS)] == NEW_KEYS


def test_an_item_with_send_keys_round_trips_byte_for_byte():
    item = ready_item(state="queued", queued=NOW, send_at=datetime(2026, 10, 19, 9, 47),
                      send_hash="abc123", message_id="<x.1@mail.example.com>", send_tries=1,
                      send_error="", send_note="", invite_sent=datetime(2026, 10, 20, 10, 0))
    text = outreach.item_text(item)
    again = outreach.item_from_text(item.id, text)
    assert again.send_at == datetime(2026, 10, 19, 9, 47)
    assert again.queued == NOW and again.send_tries == 1
    assert again.message_id == "<x.1@mail.example.com>"
    assert again.invite_sent == datetime(2026, 10, 20, 10, 0)
    assert outreach.item_text(again) == text


def test_an_unqueued_item_writes_the_keys_empty():
    text = outreach.item_text(ready_item())
    meta, _ = split_file(text)
    for key in NEW_KEYS:
        assert key in meta
    assert meta["send_tries"] == 0 and not meta["send_at"] and not meta["message_id"]


# --------------------------------------------------------------- migrations


def test_migration_12_adds_the_keys_exactly_as_the_app_writes_them():
    item = ready_item()
    current = outreach.item_text(item)
    meta, body = split_file(current)
    old = {k: v for k, v in meta.items() if k not in NEW_KEYS}
    migrated = migrations.m12_send_keys(old)
    from hermitcrm.store import build_file
    assert build_file(migrated, body) == current


def test_migration_12_is_idempotent_and_keeps_values():
    meta, _ = split_file(outreach.item_text(ready_item(state="queued", send_tries=2,
                                                       message_id="<a@b.example>")))
    assert migrations.m12_send_keys(meta) is meta or migrations.m12_send_keys(meta) == meta
    old = {k: v for k, v in meta.items() if k not in NEW_KEYS}
    once = migrations.m12_send_keys(old)
    assert migrations.m12_send_keys(once) == once


def test_migration_13_is_a_noop_for_the_new_interaction_source():
    m12, m13 = migrations.MIGRATIONS[-2], migrations.MIGRATIONS[-1]
    assert (m12.version, m12.glob, m12.apply) == (12, "outreach/*.md", migrations.m12_send_keys)
    assert (m13.version, m13.glob) == (13, "companies/*/interactions/*.md")
    meta = {"source": "outreach", "channel": "email"}
    assert m13.apply(meta) is meta
    assert migrations.LATEST == 13


def test_a_folder_at_format_11_gets_the_keys_in_one_run(tmp_path):
    root, store = demo(tmp_path)
    item = ready_item(company="lindenhof-data", contact="mara-keller")
    meta, body = split_file(outreach.item_text(item))
    from hermitcrm.store import build_file
    path = root / "outreach" / f"{item.id}.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(build_file({k: v for k, v in meta.items() if k not in NEW_KEYS}, body),
                    encoding="utf-8")
    migrations.write_format(root, 11)
    migrations.ensure_current(root)
    assert path.read_text(encoding="utf-8") == outreach.item_text(item)
    assert migrations.current_format(root) == migrations.LATEST


# ------------------------------------------------- source, secret and config


def test_outreach_is_an_interaction_source(tmp_path):
    assert InteractionSource("outreach") is InteractionSource.OUTREACH
    root, store = demo(tmp_path)
    it = store.create_interaction("lindenhof-data", "email", "out", subject="Hello",
                                  contact="mara-keller", body="Hi\n", source="outreach",
                                  message_id="<m1@mail.example.com>")
    assert it.source == "outreach" and it.message_id == "<m1@mail.example.com>"
    store.load()
    found = [i for i in store.get("lindenhof-data").interactions if i.id == it.id][0]
    assert found.source == "outreach"


def test_send_password_is_a_known_secret(monkeypatch, tmp_path):
    assert "send_password" in secrets.NAMES
    monkeypatch.setenv("HERMITCRM_SEND_PASSWORD", "abcd efgh")
    assert secrets.get("send_password", tmp_path) == "abcd efgh"
    monkeypatch.delenv("HERMITCRM_SEND_PASSWORD")
    secrets.set("send_password", "from-file", tmp_path)
    assert secrets.get("send_password", tmp_path) == "from-file"


def test_the_send_config_keys_have_the_decided_defaults():
    c = DEFAULT_CONFIG
    assert c["send_enabled"] is False and c["send_paused"] is False
    assert c["send_daily_cap"] == 100 and c["send_ramp"] == [20, 40, 60, 80]
    assert c["send_window"] == "08:30-17:30"
    assert c["send_days"] == ["mon", "tue", "wed", "thu", "fri"]
    assert c["send_min_gap_minutes"] == 3 and c["send_company_gap_hours"] == 24
    assert c["send_grace_minutes"] == 10 and c["send_overdue_minutes"] == 20
    assert c["send_email_block_countries"] == []
    assert c["linkedin_invites_per_day"] == 20 and c["linkedin_invites_per_week"] == 80
    assert c["linkedin_messages_per_day"] == 40 and c["linkedin_session_size"] == 10
    assert c["linkedin_gap_seconds"] == [45, 120]
    assert c["linkedin_session_break_minutes"] == 120
    assert c["send_smtp_host"] == "smtp.gmail.com" and c["send_smtp_port"] == 587
    assert c["send_imap_host"] == "imap.gmail.com"
    missing = [k for k in c if k not in CONFIG_DOCS]
    assert not missing


# ------------------------------------------------- an outbound mail flips it


@pytest.mark.parametrize("state", ["ready", "queued", "failed"])
def test_logging_the_mail_marks_the_item_sent_and_keeps_its_message_id(tmp_path, state):
    root, store = demo(tmp_path)
    item = ready_item(company="lindenhof-data", contact="mara-keller", state=state,
                      ready=datetime(2026, 10, 16, 8, 0), message_id="<m9@mail.example.com>",
                      angle="hook")
    outreach.write_item(root, item)
    it = store.create_interaction("lindenhof-data", "email", "out", subject="Hello",
                                  contact="mara-keller", date=datetime(2026, 10, 16, 9, 30),
                                  body="Hi\n", source="outreach",
                                  message_id="<m9@mail.example.com>")
    after = outreach.get_item(root, item.id)
    assert after.state == "sent" and after.sent_with == it.id
    assert after.message_id == "<m9@mail.example.com>"
    assert it.angle == "hook"


def test_an_inbound_mail_does_not_flip_a_queued_item(tmp_path):
    root, store = demo(tmp_path)
    item = ready_item(company="lindenhof-data", contact="mara-keller", state="queued",
                      ready=datetime(2026, 10, 16, 8, 0))
    outreach.write_item(root, item)
    store.create_interaction("lindenhof-data", "email", "in", subject="Re: Hello",
                             contact="mara-keller", date=datetime(2026, 10, 16, 9, 30),
                             body="Thanks\n")
    assert outreach.get_item(root, item.id).state == "queued"


def test_queued_and_failed_items_count_as_reviewed_for_learning():
    from hermitcrm import learning
    assert "queued" in learning.REVIEWED_STATES and "failed" in learning.REVIEWED_STATES
