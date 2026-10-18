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

"""The spacing of scheduled email (spec part 08): which day and minute each
queued item goes out. Pure functions of their arguments, no clock, no files,
no randomness that is not seeded by the item id, so the page, the worker and
the tests agree on every time.

    plan(queue, sent, now, config) -> {item_id: send_at}

Rules, in the order they bite:

* **Window and days.** Only inside `window` on a `days` weekday, in the
  sender's local time (naive datetimes, like every date in the store).
* **Daily cap.** `day_cap` gives the most sends for a day: the ramp for the
  weeks since the first send, then `daily_cap`. A cap above SOFT_CEILING (150)
  is held at 150 once the previous MAX_DAYS_OVER send-days both went over it:
  more than 150 a day for more than 1-2 days in a row is how a mailbox gets
  burned.
* **Gap.** window length / that day's cap, times a factor between 0.6 and 1.4
  seeded by the item id, never below `min_gap`. The window's start counts as
  a send, so the first mail of a day is not at 08:30 sharp.
* **Company spread.** Two items for one company (or one email domain) at
  least `company_gap_hours` apart, sends already made included.
* **Grace.** Nothing before now + `grace`, so a mistaken Schedule can still be
  undone.
* **Order.** Follow-ups first, then first touches in the order they were
  queued.
* **Stability.** An item that already has a time inside the window, and is not
  overdue by more than `overdue` minutes, keeps it: what the page showed is
  when it goes out. New, overdue and moved items fill the first free slots,
  one by one, so an overdue backlog is never a burst.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SOFT_CEILING = 150     # emails a day that should not be exceeded for long
MAX_DAYS_OVER = 2      # send-days in a row that may go over it
HORIZON_DAYS = 60      # nothing is planned further out than this
JITTER_LOW, JITTER_HIGH = 0.6, 1.4
_WINDOW = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


def parse_window(text: str) -> tuple[int, int]:
    """'08:30-17:30' as minutes since midnight; ValueError says what is wrong."""
    m = _WINDOW.match(str(text or ""))
    if not m:
        raise ValueError(f"the sending window is HH:MM-HH:MM, e.g. 08:30-17:30 (got {text!r})")
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        raise ValueError(f"{text!r} is not a time of day")
    start, end = h1 * 60 + m1, h2 * 60 + m2
    if end <= start:
        raise ValueError(f"the window must end after it starts (got {text!r})")
    return start, end


def parse_days(names) -> tuple[int, ...]:
    """['mon', 'wed'] as weekday numbers (Monday is 0); ValueError names a bad day."""
    out = set()
    for name in names if isinstance(names, (list, tuple)) else [names]:
        key = str(name).strip().lower()[:3]
        if key not in WEEKDAYS:
            raise ValueError(f"{name!r} is not a day (use {', '.join(WEEKDAYS)})")
        out.add(WEEKDAYS.index(key))
    if not out:
        raise ValueError("choose at least one day to send on")
    return tuple(sorted(out))


@dataclass(frozen=True)
class PlanConfig:
    days: tuple[int, ...] = (0, 1, 2, 3, 4)
    window: tuple[int, int] = (8 * 60 + 30, 17 * 60 + 30)
    ramp: tuple[int, ...] = (20, 40, 60, 80)
    daily_cap: int = 100
    min_gap: int = 3
    company_gap_hours: int = 24
    grace: int = 10
    overdue: int = 20


@dataclass(frozen=True)
class Slot:
    """One queued item as the planner sees it."""
    id: str
    company: str
    domain: str = ""
    follow_up: bool = False
    queued: datetime = datetime.min
    send_at: datetime | None = None      # where it is now, if it has a time


@dataclass(frozen=True)
class Sent:
    """One email already sent (an interaction with source outreach)."""
    when: datetime
    company: str = ""
    domain: str = ""


def jitter(item_id: str) -> float:
    """A factor between 0.6 and 1.4 that depends only on the item id."""
    digest = hashlib.sha256(str(item_id).encode("utf-8")).digest()
    return JITTER_LOW + (JITTER_HIGH - JITTER_LOW) * int.from_bytes(digest[:8], "big") / 2 ** 64


# --------------------------------------------------------------------- caps


def ramp_cap(day: date, first_send: date | None, cfg: PlanConfig) -> int:
    """The cap for `day` before the 150 rule: the ramp week since the first send
    (week 1 when nothing was sent yet), then `daily_cap`; never above `daily_cap`."""
    week = max(0, (day - first_send).days // 7) if first_send is not None else 0
    base = cfg.ramp[week] if week < len(cfg.ramp) else cfg.daily_cap
    return max(0, min(int(base), int(cfg.daily_cap)))


def day_cap(day: date, first_send: date | None, counts: dict, cfg: PlanConfig) -> int:
    """The most emails for `day`. `counts` is sends per date (planned ones
    included). A cap above SOFT_CEILING is held at SOFT_CEILING when each of the
    MAX_DAYS_OVER send-days before `day` went over it; days off are skipped."""
    cap = ramp_cap(day, first_send, cfg)
    if cap <= SOFT_CEILING:
        return cap
    streak, back = 0, day
    for _ in range(14):
        back -= timedelta(days=1)
        if back.weekday() not in cfg.days:
            continue
        if counts.get(back, 0) <= SOFT_CEILING:
            break
        streak += 1
        if streak >= MAX_DAYS_OVER:
            return SOFT_CEILING
    return cap


def count_by_day(sent) -> dict:
    out: dict = {}
    for s in sent:
        out[s.when.date()] = out.get(s.when.date(), 0) + 1
    return out


def first_send_day(sent) -> date | None:
    return min((s.when.date() for s in sent), default=None)


# --------------------------------------------------------------------- time


def _at(day: date, minutes: int) -> datetime:
    return datetime(day.year, day.month, day.day) + timedelta(minutes=minutes)


def in_window(when: datetime, cfg: PlanConfig) -> bool:
    start, end = cfg.window
    minute = when.hour * 60 + when.minute
    return when.weekday() in cfg.days and start <= minute <= end


def _next_open(when: datetime, cfg: PlanConfig) -> datetime:
    """`when` itself if it is inside the window, else the next opening."""
    start, end = cfg.window
    when = when.replace(second=0, microsecond=0) + (
        timedelta(minutes=1) if when.second or when.microsecond else timedelta())
    minute = when.hour * 60 + when.minute
    day = when.date()
    if when.weekday() in cfg.days and start <= minute <= end:
        return when
    if when.weekday() in cfg.days and minute < start:
        return _at(day, start)
    for _ in range(8):
        day += timedelta(days=1)
        if day.weekday() in cfg.days:
            return _at(day, start)
    return _at(day, start)      # unreachable with at least one day; keeps the type honest


# --------------------------------------------------------------------- plan


def _same(a_company: str, a_domain: str, b_company: str, b_domain: str) -> bool:
    return bool(a_company and a_company == b_company) or bool(a_domain and a_domain == b_domain)


def plan(queue, sent, now: datetime, cfg: PlanConfig) -> dict[str, datetime]:
    """When each queued item goes out. Items it cannot place within HORIZON_DAYS
    are left out. The same arguments always give the same answer."""
    first = first_send_day(sent)
    counts = count_by_day(sent)
    window_start, window_end = cfg.window
    window_len = window_end - window_start
    horizon = now + timedelta(days=HORIZON_DAYS)
    gap_company = timedelta(hours=cfg.company_gap_hours)
    min_gap = timedelta(minutes=cfg.min_gap)

    # Everything already on the calendar: sent mail, then items that keep their time.
    taken: list[tuple[datetime, str, str]] = [(s.when, s.company, s.domain) for s in sent]
    by_day: dict[date, list[datetime]] = {}
    for s in sent:
        by_day.setdefault(s.when.date(), []).append(s.when)

    def put(when: datetime, company: str, domain: str) -> None:
        taken.append((when, company, domain))
        by_day.setdefault(when.date(), []).append(when)
        counts[when.date()] = counts.get(when.date(), 0) + 1

    result: dict[str, datetime] = {}
    todo = []
    for slot in queue:
        keeps = (slot.send_at is not None and in_window(slot.send_at, cfg)
                 and slot.send_at > now - timedelta(minutes=cfg.overdue))
        if keeps:
            result[slot.id] = slot.send_at
            put(slot.send_at, slot.company, slot.domain)
        else:
            todo.append(slot)
    todo.sort(key=lambda s: (not s.follow_up, s.queued, s.id))

    cursor = now + timedelta(minutes=cfg.grace)
    for slot in todo:
        found = _first_fit(slot, cursor, horizon, cfg, first, counts, by_day, taken,
                           window_start, window_len, gap_company, min_gap)
        if found is None:
            continue
        when, pushed = found
        result[slot.id] = when
        put(when, slot.company, slot.domain)
        if not pushed:           # one held back by company spacing does not hold up the rest
            cursor = when
    return result


def _first_fit(slot, start, horizon, cfg, first, counts, by_day, taken, window_start,
               window_len, gap_company, min_gap):
    """(when, pushed): the first time at or after `start` that fits every rule,
    and whether company spacing alone moved it. None when nothing fits."""
    t = start
    pushed = False
    for _ in range(20000):                 # every pass moves t forward; this is a guard
        t = _next_open(t, cfg)
        if t > horizon:
            return None
        day = t.date()
        cap = day_cap(day, first, counts, cfg)
        if counts.get(day, 0) >= cap:
            t = _at(day + timedelta(days=1), 0)
            continue
        times = sorted(by_day.get(day, []))
        # Whole minutes, to the nearest: rounding up would stretch every gap by half
        # a minute and a 100-a-day plan would not fit its window.
        gap = max(cfg.min_gap, round(window_len / max(cap, 1) * jitter(slot.id)))
        before = max((x for x in times if x <= t), default=_at(day, window_start))
        need = before + timedelta(minutes=gap)
        if t < need:
            t = need
            continue
        after = min((x for x in times if x > t), default=None)
        if after is not None and after - t < min_gap:
            t = after
            continue
        near = [x for (x, company, domain) in taken
                if _same(slot.company, slot.domain, company, domain)
                and abs(t - x) < gap_company]
        if near:
            t = max(near) + gap_company
            pushed = True
            continue
        return t, pushed
    return None
