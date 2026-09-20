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

from datetime import date, datetime, timedelta

from hermitcrm import pipeline
from hermitcrm.store import Store
from conftest import FIXED_NOW


def _populate(store):
    """A realistic, deterministic fixture set covering every PIPELINE.md rule."""
    acme = store.create_company(
        name="Acme Software", source="referral", stage="offer",
        value_eur_month=6000, next_step="Send proposal outline",
        next_step_due="2026-09-18",
    )
    jane = store.create_contact(acme.slug, first_name="Jane", last_name="Doe", title="CEO",
                                role="decision-maker")
    store.create_interaction(
        acme.slug, subject="Intro call follow-up", channel="email",
        direction="out", contact=jane.slug, date=datetime(2026, 9, 14, 9, 0),
    )
    # Backdate stage_changed to get a non-zero "in stage Nd" without waiting
    # for real time to pass -- create_company always stamps "today".
    store.companies[acme.slug].stage_changed = date(2026, 9, 10)

    store.create_company(name="Beta Robotics", stage="offer", value_eur_month=5000)

    store.create_company(
        name="Gamma Analytics", stage="discovery",
        next_step="Follow up on LinkedIn reply", next_step_due="2026-09-09",
    )
    store.companies["gamma-analytics"].stage_changed = date(2026, 9, 1)

    epsilon = store.create_company(name="Epsilon Systems", stage="prospect")
    bob = store.create_contact(epsilon.slug, first_name="Bob", last_name="King")
    store.create_interaction(
        epsilon.slug, subject="Follow-up call", channel="call", direction="in",
        contact=bob.slug, date=datetime(2026, 9, 11, 16, 0),
    )

    store.create_company(name="Zeta Devices", stage="prospect")
    # Backdate creation to simulate a prospect that has been silent for a
    # long time and never had a single interaction.
    store.companies["zeta-devices"].created = datetime(2026, 8, 1, 9, 0)

    store.create_company(name="Nova Robotics", stage="won")
    store.companies["nova-robotics"].stage_changed = date(2026, 8, 30)

    store.create_company(name="Orion Labs", stage="lost", lost_reason="no budget")
    store.companies["orion-labs"].stage_changed = date(2026, 8, 25)

    store.create_company(name="Vector Systems", stage="lost",
                         lost_reason="chose in-house hire")
    store.companies["vector-systems"].stage_changed = (
        date(2026, 9, 14) - timedelta(days=100)
    )

    return store


GOLDEN = """# Pipeline  (generated 2026-09-14 10:30, do not edit)

## offer (2, 11,000 EUR/month)
- acme-software | Acme Software | in stage 4d | last: email out 2026-09-14 (jane-doe) | next: Send proposal outline, due 2026-09-18
- beta-robotics | Beta Robotics | in stage 0d | last: none | next: none

## discovery (1, 0 EUR/month)
- gamma-analytics | Gamma Analytics | in stage 13d | last: none | next: Follow up on LinkedIn reply, due 2026-09-09

## engaged (1)
- epsilon-systems | Epsilon Systems | in stage 0d | last: call in 2026-09-11 (bob-king) | next: none

## prospect (1)
- zeta-devices | Zeta Devices | in stage 0d | last: none | next: none

## Overdue next steps (1)
- gamma-analytics | discovery | due 2026-09-09 | Follow up on LinkedIn reply

## Silent for 14+ days, not closed (1)
- zeta-devices | prospect | last touch none (44d)

## Temp disqualified (0)

## Closed last 90 days
- won: nova-robotics (2026-08-30)
- lost: orion-labs (2026-08-25, no budget)
"""


def test_render_golden_document(store):
    _populate(store)
    assert pipeline.render(store, now=FIXED_NOW) == GOLDEN


def test_render_defaults_now_to_store_now(store):
    _populate(store)
    # now omitted -> store.now() (the frozen clock) is used, same result.
    assert pipeline.render(store) == GOLDEN


EMPTY_GOLDEN = """# Pipeline  (generated 2026-09-14 10:30, do not edit)

## offer (0, 0 EUR/month)

## discovery (0, 0 EUR/month)

## engaged (0)

## prospect (0)

## Overdue next steps (0)

## Silent for 14+ days, not closed (0)

## Temp disqualified (0)

## Closed last 90 days
- none
"""


def test_render_empty_store(store):
    assert pipeline.render(store, now=FIXED_NOW) == EMPTY_GOLDEN


def test_thousands_separator_for_large_value(tmp_path):
    s = Store(tmp_path, clock=lambda: FIXED_NOW)
    s.load()
    s.create_company(name="Big Client Holding", stage="offer",
                     value_eur_month=1234000)
    text = pipeline.render(s, now=FIXED_NOW)
    assert "## offer (1, 1,234,000 EUR/month)" in text


def test_next_step_due_without_text_is_edge_cased(tmp_path):
    s = Store(tmp_path, clock=lambda: FIXED_NOW)
    s.load()
    s.create_company(name="Edge Case Co", stage="prospect",
                     next_step_due="2026-09-20")
    text = pipeline.render(s, now=FIXED_NOW)
    assert "next: (no text), due 2026-09-20" in text


def test_stage_ordering_due_tie_then_last_touch_desc_then_empty_due_last(tmp_path):
    s = Store(tmp_path, clock=lambda: FIXED_NOW)
    s.load()
    a = s.create_company(name="Alpha One", stage="engaged",
                         next_step="Follow up", next_step_due="2026-09-20")
    b = s.create_company(name="Beta Two", stage="engaged",
                         next_step="Follow up", next_step_due="2026-09-20")
    c = s.create_company(name="Gamma Three", stage="engaged")

    ca = s.create_contact(a.slug, first_name="Contact", last_name="A")
    s.create_interaction(a.slug, subject="Touch A", channel="email",
                         direction="out", contact=ca.slug,
                         date=datetime(2026, 9, 10, 9, 0))
    cb = s.create_contact(b.slug, first_name="Contact", last_name="B")
    s.create_interaction(b.slug, subject="Touch B", channel="email",
                         direction="out", contact=cb.slug,
                         date=datetime(2026, 9, 12, 9, 0))

    text = pipeline.render(s, now=FIXED_NOW)
    section = text.split("## engaged")[1].split("\n\n")[0]
    slugs = [line.split(" | ")[0][2:] for line in section.splitlines()
             if line.startswith("- ")]
    # b's last touch (09-12) is more recent than a's (09-10) -> b before a
    # despite an identical next_step_due; c has no due date so sorts last.
    assert slugs == [b.slug, a.slug, c.slug]


def test_write_creates_file_matching_render(store):
    _populate(store)
    changed = pipeline.write(store, now=FIXED_NOW)
    assert changed is True
    path = store.root / "PIPELINE.md"
    assert path.exists()
    assert path.read_text(encoding="utf-8") == pipeline.render(store, now=FIXED_NOW)
    assert path.read_text(encoding="utf-8") == GOLDEN


def test_write_returns_false_when_unchanged(store):
    _populate(store)
    assert pipeline.write(store, now=FIXED_NOW) is True
    assert pipeline.write(store, now=FIXED_NOW) is False


def test_write_returns_true_again_after_a_real_change(store):
    _populate(store)
    assert pipeline.write(store, now=FIXED_NOW) is True
    assert pipeline.write(store, now=FIXED_NOW) is False
    store.update_company("beta-robotics", value_eur_month=9000)
    later = FIXED_NOW + timedelta(minutes=1)
    assert pipeline.write(store, now=later) is True


def test_done_next_step_is_marked_and_not_overdue(store):
    store.create_company(name="Acme", stage="offer", next_step="Send deck",
                         next_step_due="2026-09-01", next_step_status="done")
    out = pipeline.render(store)
    assert "next: Send deck, due 2026-09-01 (done)" in out
    assert "## Overdue next steps (0)" in out


def test_disqualified_and_parked_sections(store):
    store.create_company(name="Gone", stage="disqualified", lost_reason="no fit")
    store.create_company(name="Later", stage="temp-disqualified", lost_reason="hiring freeze",
                         next_step="Revisit", next_step_due="2026-12-01")
    store.create_company(name="Quiet", stage="temp-disqualified")
    out = pipeline.render(store)
    assert "## Temp disqualified (2)" in out
    assert "- later | since 2026-09-14 | hiring freeze | next: Revisit, due 2026-12-01" in out
    assert "- quiet | since 2026-09-14 | no reason | next: none" in out
    assert "- disqualified: gone (2026-09-14, no fit)" in out
    assert "## Silent for 14+ days, not closed (0)" in out


def test_parked_line_shows_requalify_date(store):
    store.create_company(name="Later", stage="temp-disqualified", lost_reason="freeze",
                        requalify_on="2026-12-01")
    out = pipeline.render(store)
    assert "- later | since 2026-09-14 until 2026-12-01 | freeze | next: none" in out
