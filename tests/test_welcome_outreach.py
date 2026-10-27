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

"""The walkthrough step that leads to the outreach bot ("Draft your first message")."""

from __future__ import annotations

from datetime import datetime

import pytest

from hermitcrm import cli, outreach, welcome
from hermitcrm.datafolder import init_folder
from hermitcrm.store import Store

WHEN = datetime(2026, 10, 19, 8, 0)


@pytest.fixture
def folder(tmp_path):
    return init_folder(tmp_path / "crm")


def step(folder, ai_available=False):
    store = Store(folder)
    store.load()
    return next(s for s in welcome.steps(store, {}, {}, ai_available) if s.key == "outreach")


def write(folder, company, contact="jane-roe", **extra):
    outreach.write_item(folder, outreach.Item(
        id=f"2026-10-19T0800-email-{company}-{contact}", state="drafted", company=company,
        contact=contact, subject="Hello", body="Hi Jane,\n\nA question.\n", created=WHEN,
        drafted=WHEN, **extra))


def test_the_outreach_step_leads_to_the_outreach_page(folder):
    s = step(folder)
    assert (s.title, s.href, s.manual) == ("Draft your first message", "/outreach", False)
    assert "playbook" in s.why and "contact" in s.why


def test_the_text_asks_for_an_ai_cli_only_while_there_is_none(folder):
    assert "AI CLI" in step(folder, ai_available=False).why
    assert "AI CLI" not in step(folder, ai_available=True).why


def test_it_comes_after_the_plan_step_and_before_bcc(folder):
    store = Store(folder)
    store.load()
    keys = [s.key for s in welcome.steps(store, {}, {}, False)]
    assert len(keys) == 13 and keys.index("plan") < keys.index("outreach") < keys.index("bcc")


def test_it_is_not_done_on_a_fresh_folder(folder):
    assert not step(folder).done


def test_it_is_done_once_a_draft_of_your_own_exists(folder):
    store = Store(folder)
    store.create_company("Acme")
    write(folder, "acme")
    assert step(folder).done


def test_an_item_that_never_got_a_draft_does_not_tick_it(folder):
    store = Store(folder)
    store.create_company("Acme")
    outreach.write_item(folder, outreach.Item(
        id="2026-10-19T0800-email-acme-jane-roe", state="researching", company="acme",
        contact="jane-roe", created=WHEN))
    assert not step(folder).done


def test_a_draft_for_the_sample_does_not_tick_it(folder):
    assert cli.main(["--data", str(folder), "sample", "add"]) == 0
    write(folder, "northwind-robotics")
    assert not step(folder).done
