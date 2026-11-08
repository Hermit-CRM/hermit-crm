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

"""`lead_rule`: the research rule whose gap led a message. It is set on the
outreach item when the draft is written, and copied onto the interaction when
the message is logged, so results can be read per rule. Fictional names only."""

from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import FIXED_NOW
from hermitcrm import migrations, outreach
from hermitcrm.outreach import Finding
from hermitcrm.store import split_file

URL = "https://acme.example.com/contact"


def finding(kind="gap", rule="r08", text="No way to book a call", **kw):
    return Finding(text=text, source=URL, kind=kind, confidence="high", date="2026-11-01",
                   rule=rule, **kw)


def item(**kw):
    base = dict(id="acme-jane-doe", state="researching", kind="first-touch",
                channel="email", company="acme", contact="jane-doe", created=FIXED_NOW)
    base.update(kw)
    return outreach.Item(**base)


def drafted(findings, used):
    it = item(findings=list(findings))
    draft = outreach.Draft(subject="Hi", body="Hello\n", findings_used=list(used))
    outreach._apply_draft(it, draft, False, FIXED_NOW)
    return it


# ------------------------------------------------------------- on the item


def test_an_item_keeps_its_lead_rule_in_the_front_matter():
    assert item(lead_rule="r08").to_frontmatter()["lead_rule"] == "r08"


def test_an_item_without_a_lead_rule_has_no_such_key():
    assert "lead_rule" not in item().to_frontmatter()


def test_a_lead_rule_is_read_back_clean():
    text = "---\nstate: drafted\nkind: first-touch\nlead_rule: ' R08 '\n---\nbody\n"
    assert outreach.item_from_text("x", text).lead_rule == "r08"
    bad = "---\nstate: drafted\nkind: first-touch\nlead_rule: not a rule!\n---\nbody\n"
    assert outreach.item_from_text("x", bad).lead_rule == ""


def test_the_draft_takes_the_rule_of_the_gap_it_cites():
    it = drafted([finding(kind="trigger", rule=""), finding(rule="r08")], used=[2])
    assert it.lead_rule == "r08"


def test_the_first_cited_gap_with_a_rule_leads():
    it = drafted([finding(rule="r04"), finding(rule="r08")], used=[2, 1])
    assert it.lead_rule == "r04"        # by position in the findings, not in the citation


def test_citing_no_gap_leaves_no_lead_rule():
    it = drafted([finding(kind="trigger", rule=""), finding(rule="r08")], used=[1])
    assert it.lead_rule == ""


def test_a_new_draft_replaces_the_lead_rule():
    it = drafted([finding(rule="r04"), finding(rule="r08")], used=[1])
    assert it.lead_rule == "r04"
    outreach._apply_draft(it, outreach.Draft(subject="Hi", body="Hello\n", findings_used=[2]),
                          False, FIXED_NOW)
    assert it.lead_rule == "r08"


# ------------------------------------------------------ on the logged message


@pytest.fixture
def seeded(store):
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe")
    return store


def ready_item(store, **kw):
    it = item(state="ready", subject="Hi", body="Hello\n", ready=FIXED_NOW,
              drafted=FIXED_NOW, **kw)
    outreach.write_item(store.root, it)
    return it


def test_the_logged_message_gets_the_lead_rule_of_the_item(seeded):
    ready_item(seeded, lead_rule="r08")
    logged = seeded.create_interaction("acme", "email", "out", subject="Hi",
                                       contact="jane-doe", date=FIXED_NOW + timedelta(hours=1),
                                       body="Hello", source="outreach")
    assert logged.lead_rule == "r08"
    again = [i for i in seeded.get("acme").interactions if i.id == logged.id][0]
    assert again.lead_rule == "r08"
    path = seeded.root / "companies/acme/interactions" / f"{logged.id}.md"
    meta, _ = split_file(path.read_text())
    assert meta["lead_rule"] == "r08"


def test_a_message_of_your_own_keeps_the_rule_you_gave_it(seeded):
    ready_item(seeded, lead_rule="r08")
    logged = seeded.create_interaction("acme", "email", "out", contact="jane-doe",
                                       date=FIXED_NOW + timedelta(hours=1), lead_rule="r04",
                                       body="Hello", source="outreach")
    assert logged.lead_rule == "r04"


def test_a_message_without_a_lead_rule_has_no_such_key(seeded):
    ready_item(seeded)
    logged = seeded.create_interaction("acme", "email", "out", contact="jane-doe",
                                       date=FIXED_NOW + timedelta(hours=1), body="Hello",
                                       source="outreach")
    assert logged.lead_rule == ""
    path = seeded.root / "companies/acme/interactions" / f"{logged.id}.md"
    assert "lead_rule" not in path.read_text()


def test_a_bad_rule_on_a_message_is_refused(seeded):
    from hermitcrm.models import ValidationError
    with pytest.raises(ValidationError, match="lead_rule"):
        seeded.create_interaction("acme", "email", "out", contact="jane-doe",
                                  body="Hello", lead_rule="Not A Rule!")


# --------------------------------------------------------------- migrations


@pytest.mark.parametrize("meta,expected", [
    ({"state": "drafted", "lead_rule": ""}, {"state": "drafted"}),
    ({"state": "drafted", "lead_rule": None}, {"state": "drafted"}),
    ({"state": "drafted", "lead_rule": " R08 "}, {"state": "drafted", "lead_rule": "r08"}),
    ({"state": "drafted", "lead_rule": "Not a rule!"}, {"state": "drafted"}),
    ({"state": "drafted", "lead_rule": "r08"}, {"state": "drafted", "lead_rule": "r08"}),
    ({"state": "drafted"}, {"state": "drafted"}),
])
def test_the_lead_rule_migration_normalises_and_is_idempotent(meta, expected):
    once = migrations.m24_lead_rule(meta)
    assert once == expected and migrations.m24_lead_rule(once) == once


def test_the_lead_rule_migration_returns_an_unchanged_value_as_it_is():
    meta = {"state": "drafted", "lead_rule": "r08"}
    assert migrations.m24_lead_rule(meta) is meta


def test_items_and_interactions_have_a_migration_each():
    steps = {m.version: m for m in migrations.MIGRATIONS}
    assert steps[24].glob == "outreach/*.md" and steps[25].glob == "companies/*/interactions/*.md"
    assert migrations.LATEST == 25
