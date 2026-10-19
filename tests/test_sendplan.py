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

"""Outreach send: the planner and the daily caps (sendplan.py). Pure functions
with a fixed clock; Monday 19 October 2026 is the day the tests start on."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

import pytest

from hermitcrm import sendplan
from hermitcrm.sendplan import PlanConfig, Sent, Slot

MON = datetime(2026, 10, 19, 8, 0)      # a Monday
CFG = PlanConfig()


def slots(n, **kw):
    return [Slot(id=f"i{k:03d}", company=f"co{k}", queued=MON + timedelta(seconds=k), **kw)
            for k in range(n)]


def times(plan):
    return sorted(plan.values())


def per_day(plan):
    return Counter(t.date() for t in plan.values())


# ------------------------------------------------------------------ parsing


def test_the_window_and_the_days_parse():
    assert sendplan.parse_window("08:30-17:30") == (8 * 60 + 30, 17 * 60 + 30)
    assert sendplan.parse_days(["mon", "Wed", "FRI"]) == (0, 2, 4)
    for bad in ("", "9-17", "17:30-08:30", "08:30", "25:00-26:00", "08:30-08:30"):
        with pytest.raises(ValueError):
            sendplan.parse_window(bad)
    with pytest.raises(ValueError):
        sendplan.parse_days(["funday"])
    with pytest.raises(ValueError):
        sendplan.parse_days([])


# ------------------------------------------------------------------- jitter


def test_jitter_is_seeded_by_the_item_id_and_stays_between_0_6_and_1_4():
    values = [sendplan.jitter(f"item-{k}") for k in range(500)]
    assert all(0.6 <= v <= 1.4 for v in values)
    assert len({round(v, 3) for v in values}) > 100            # it does vary
    assert sendplan.jitter("item-7") == sendplan.jitter("item-7")
    assert sum(values) / len(values) == pytest.approx(1.0, abs=0.05)


# --------------------------------------------------------------------- caps


def test_the_ramp_counts_weeks_from_the_first_send_then_the_daily_cap():
    first = date(2026, 10, 5)
    cap = lambda d: sendplan.day_cap(d, first, {}, CFG)          # noqa: E731
    assert cap(date(2026, 10, 5)) == 10
    assert cap(date(2026, 10, 11)) == 10
    assert cap(date(2026, 10, 12)) == 20
    assert cap(date(2026, 10, 19)) == 30
    assert cap(date(2026, 10, 26)) == 40
    assert cap(date(2026, 11, 2)) == 50
    assert cap(date(2027, 3, 1)) == 50                                    # and it stays there
    assert sendplan.day_cap(date(2026, 10, 19), None, {}, CFG) == 10      # no send yet: week 1


def test_a_lower_daily_cap_wins_over_the_ramp():
    cfg = PlanConfig(daily_cap=15)
    assert sendplan.day_cap(date(2026, 10, 5), date(2026, 10, 5), {}, cfg) == 10      # the ramp is lower
    assert sendplan.day_cap(date(2026, 10, 12), date(2026, 10, 5), {}, cfg) == 15
    assert sendplan.day_cap(date(2026, 10, 26), date(2026, 10, 5), {}, cfg) == 15


def test_a_third_day_in_a_row_over_150_is_held_at_150():
    cfg = PlanConfig(daily_cap=200, ramp=())
    monday = date(2026, 10, 19)
    counts = {date(2026, 10, 15): 160, date(2026, 10, 16): 165}          # Thu, Fri
    assert sendplan.day_cap(monday, date(2026, 9, 1), counts, cfg) == 150    # weekend skipped
    assert sendplan.day_cap(monday, date(2026, 9, 1), {date(2026, 10, 16): 165}, cfg) == 200
    broken = {date(2026, 10, 14): 170, date(2026, 10, 15): 120, date(2026, 10, 16): 165}
    assert sendplan.day_cap(monday, date(2026, 9, 1), broken, cfg) == 200
    # Exactly 150 is not over 150.
    flat = {date(2026, 10, 15): 150, date(2026, 10, 16): 150}
    assert sendplan.day_cap(monday, date(2026, 9, 1), flat, cfg) == 200
    # A cap at or below 150 never needs the rule.
    assert sendplan.day_cap(monday, date(2026, 9, 1), counts,
                            PlanConfig(daily_cap=100, ramp=())) == 100


# ------------------------------------------------------------------ the plan


def test_a_plan_stays_inside_the_window_and_the_grace_and_keeps_the_gap():
    plan = sendplan.plan(slots(15), [], MON, CFG)
    assert len(plan) == 15
    ordered = times(plan)
    assert ordered[0] >= MON + timedelta(minutes=10)
    assert ordered[0] >= datetime(2026, 10, 19, 8, 30)
    for t in ordered:
        assert t.weekday() < 5 and t.second == 0
        assert datetime(2026, 10, 19, 8, 30).time() <= t.time() <= datetime(2026, 10, 19, 17, 30).time()
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(ordered, ordered[1:])]
    assert min(gaps) >= CFG.min_gap


def test_the_first_week_cap_spills_the_rest_to_the_next_working_day():
    plan = sendplan.plan(slots(15), [], MON, CFG)       # week 1: 10 a day
    days = per_day(plan)
    assert days[date(2026, 10, 19)] == 10 and days[date(2026, 10, 20)] == 5
    assert min(t for t in plan.values() if t.date() == date(2026, 10, 20)).time() \
        >= datetime(2026, 10, 20, 8, 30).time()


def test_the_example_from_the_spec_shape_a_full_day_ends_near_the_end_of_the_window():
    cfg = PlanConfig(ramp=(), daily_cap=35)
    plan = sendplan.plan(slots(50), [], MON, cfg)
    days = per_day(plan)
    assert days[date(2026, 10, 19)] >= 33 and days[date(2026, 10, 20)] >= 12
    last = max(t for t in plan.values() if t.date() == date(2026, 10, 19))
    assert last.time() > datetime(2026, 1, 1, 16, 0).time()


def test_at_100_a_day_the_mean_gap_is_about_five_minutes_and_never_under_the_floor():
    cfg = PlanConfig(ramp=(), daily_cap=100)
    plan = sendplan.plan(slots(100), [], MON, cfg)
    day = sorted(t for t in plan.values() if t.date() == date(2026, 10, 19))
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(day, day[1:])]
    assert 4.0 <= sum(gaps) / len(gaps) <= 6.5
    assert min(gaps) >= 3


def test_the_gap_floor_holds_when_the_cap_is_so_high_the_base_gap_is_tiny():
    cfg = PlanConfig(ramp=(), daily_cap=150)       # 540 / 150 = 3.6, times 0.6 is under 3
    plan = sendplan.plan(slots(60), [], MON, cfg)
    ordered = times(plan)
    assert min((b - a).total_seconds() / 60 for a, b in zip(ordered, ordered[1:])) >= 3


def test_sends_already_made_today_count_toward_the_cap():
    done = [Sent(when=datetime(2026, 10, 19, 7, 0) + timedelta(minutes=k), company=f"old{k}")
            for k in range(20)]
    plan = sendplan.plan(slots(3), done, datetime(2026, 10, 19, 9, 0), CFG)
    assert {t.date() for t in plan.values()} == {date(2026, 10, 20)}


def test_a_weekend_and_a_late_hour_roll_to_the_next_working_day():
    saturday = datetime(2026, 10, 17, 10, 0)
    assert min(sendplan.plan(slots(1), [], saturday, CFG).values()).date() == date(2026, 10, 19)
    late = datetime(2026, 10, 19, 17, 25)
    assert min(sendplan.plan(slots(1), [], late, CFG).values()).date() == date(2026, 10, 20)
    early = datetime(2026, 10, 19, 5, 0)
    assert min(sendplan.plan(slots(1), [], early, CFG).values()).date() == date(2026, 10, 19)


def test_two_contacts_at_one_company_or_domain_are_a_day_apart():
    queue = [Slot("a", "acme", "acme.example", queued=MON),
             Slot("b", "acme", "acme.example", queued=MON + timedelta(seconds=1)),
             Slot("c", "acme-gmbh", "acme.example", queued=MON + timedelta(seconds=2)),
             Slot("d", "other", "other.example", queued=MON + timedelta(seconds=3))]
    plan = sendplan.plan(queue, [], MON, CFG)
    acme = sorted([plan["a"], plan["b"], plan["c"]])
    assert acme[1] - acme[0] >= timedelta(hours=24) and acme[2] - acme[1] >= timedelta(hours=24)
    assert plan["d"].date() == date(2026, 10, 19)            # nobody waits for them
    sent_yesterday = [Sent(when=datetime(2026, 10, 19, 9, 0), company="acme",
                           domain="acme.example")]
    again = sendplan.plan([Slot("e", "acme", "acme.example", queued=MON)], sent_yesterday,
                          datetime(2026, 10, 19, 10, 0), CFG)
    assert again["e"] >= datetime(2026, 10, 20, 9, 0)


def test_follow_ups_that_are_due_go_first_then_first_touches_in_queue_order():
    queue = [Slot("first-1", "c1", queued=MON), Slot("first-2", "c2", queued=MON + timedelta(minutes=1)),
             Slot("follow", "c3", follow_up=True, queued=MON + timedelta(minutes=2))]
    plan = sendplan.plan(queue, [], MON, CFG)
    assert plan["follow"] < plan["first-1"] < plan["first-2"]


def test_the_same_input_gives_the_same_times():
    queue = slots(30)
    assert sendplan.plan(queue, [], MON, CFG) == sendplan.plan(list(reversed(queue)), [], MON,
                                                               CFG)


def test_items_already_planned_keep_their_time_and_new_ones_fit_around_them():
    first = sendplan.plan(slots(5), [], MON, CFG)
    queue = [Slot(i, f"co-{i}", queued=MON, send_at=t) for i, t in first.items()]
    queue.append(Slot("new", "newco", queued=MON + timedelta(minutes=30)))
    again = sendplan.plan(queue, [], MON + timedelta(minutes=5), CFG)
    assert {k: v for k, v in again.items() if k in first} == first
    ordered = times(again)
    assert len(again) == 6 and min((b - a) for a, b in zip(ordered, ordered[1:])) \
        >= timedelta(minutes=CFG.min_gap)


def test_overdue_items_move_to_free_slots_and_never_burst():
    noon = datetime(2026, 10, 19, 12, 0)
    queue = [Slot(f"o{k}", f"co{k}", queued=MON, send_at=datetime(2026, 10, 19, 9, 0)
                  + timedelta(minutes=5 * k)) for k in range(10)]
    plan = sendplan.plan(queue, [], noon, CFG)
    ordered = times(plan)
    assert ordered[0] >= noon + timedelta(minutes=10)
    assert min((b - a) for a, b in zip(ordered, ordered[1:])) >= timedelta(minutes=3)


def test_an_item_a_little_late_is_kept_for_the_worker_to_send():
    now = datetime(2026, 10, 19, 10, 0)
    queue = [Slot("late", "co", queued=MON, send_at=now - timedelta(minutes=5))]
    assert sendplan.plan(queue, [], now, CFG)["late"] == now - timedelta(minutes=5)
    way_late = [Slot("late", "co", queued=MON, send_at=now - timedelta(minutes=21))]
    assert sendplan.plan(way_late, [], now, CFG)["late"] > now


def test_an_item_planned_outside_the_window_after_a_config_change_is_replanned():
    now = datetime(2026, 10, 19, 8, 0)
    queue = [Slot("x", "co", queued=MON, send_at=datetime(2026, 10, 19, 20, 0))]
    new = sendplan.plan(queue, [], now, CFG)["x"]
    assert datetime(2026, 10, 19, 8, 30).time() <= new.time() <= datetime(2026, 10, 19, 17, 30).time()


def test_nothing_is_placed_beyond_the_horizon_and_an_empty_queue_is_empty():
    assert sendplan.plan([], [], MON, CFG) == {}
    cfg = PlanConfig(days=(0,), ramp=(), daily_cap=1)
    plan = sendplan.plan(slots(20), [], MON, cfg)         # one a week: 20 weeks is too far
    assert 0 < len(plan) < 20
    assert max(plan.values()) <= MON + timedelta(days=sendplan.HORIZON_DAYS)


def test_a_new_item_never_goes_out_before_one_queued_ahead_of_it():
    first = sendplan.plan(slots(1), [], MON, CFG)                    # one item, with a time
    (t,) = first.values()
    queue = [Slot("i000", "co0", queued=MON, send_at=t),
             Slot("new", "newco", queued=MON + timedelta(minutes=5))]
    again = sendplan.plan(queue, [], MON + timedelta(minutes=5), CFG)
    assert again["i000"] == t and again["new"] > t
    # An overdue item queued ahead of a later one that keeps its time may use the free slot before it.
    later = Slot("later", "co1", queued=MON + timedelta(hours=1), send_at=datetime(2026, 10, 19, 15, 0))
    early = Slot("early", "co2", queued=MON, send_at=datetime(2026, 10, 19, 8, 0))   # overdue by noon
    plan = sendplan.plan([later, early], [], datetime(2026, 10, 19, 12, 0), CFG)
    assert plan["later"] == datetime(2026, 10, 19, 15, 0)
    assert plan["early"] < plan["later"] and plan["early"] >= datetime(2026, 10, 19, 12, 10)
