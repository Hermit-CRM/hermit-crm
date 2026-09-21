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

"""PIPELINE.md generation: a rolled-up, token-cheap view derived from Store.

Regenerated on every write; see BRIEF.md section 5 for the exact format.
Never reads or writes interaction bodies/notes -- one line per company.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .models import OPEN_STAGES, UNVALUED_STAGES
from .store import Store

CLOSED_WINDOW_DAYS = 90


def _fmt_money(n: int) -> str:
    return f"{n:,}"


def _next_field(c) -> str:
    """The company's next step: its open to-do due first (see Company.next_todo)."""
    todo = c.next_todo()
    if todo is None:
        return "next: none"
    next_step, next_step_due = todo.text, todo.due
    if todo.contact is not None and next_step:
        next_step = f"{next_step} ({todo.contact.name})"
    if todo.type and next_step:
        next_step = f"{next_step} [{todo.type}]"
    suffix = " (done)" if todo.done else ""
    if next_step and next_step_due:
        return f"next: {next_step}, due {next_step_due:%Y-%m-%d}{suffix}"
    if next_step:
        return f"next: {next_step}{suffix}"
    if next_step_due:
        # Edge case not covered by a real form (due date without text).
        return f"next: (no text), due {next_step_due:%Y-%m-%d}{suffix}"
    return "next: none"


def _company_line(c, today: date) -> str:
    return (
        f"- {c.slug} | {c.name} | in stage {c.days_in_stage(today)}d | "
        f"last: {c.last_touch_summary} | {_next_field(c)}"
        + (" | sample (fictional)" if c.is_sample else "")
    )


def _stage_sort_key(c):
    due = c.next_due
    due_key = (0, due) if due is not None else (1, date.max)
    lt = c.last_touch
    lt_key = (0, -lt.timestamp()) if lt is not None else (1, 0.0)
    return (due_key, lt_key, c.slug)


def render(store: Store, now: datetime | None = None) -> str:
    """Return the full PIPELINE.md text. now defaults to store.now(); today = now.date()."""
    now = now or store.now()
    today = now.date()
    companies = store.all()

    blocks = [f"# Pipeline  (generated {now:%Y-%m-%d %H:%M}, do not edit)"]

    for stage in OPEN_STAGES:
        stage_companies = sorted(
            (c for c in companies if c.stage == stage), key=_stage_sort_key
        )
        if stage in UNVALUED_STAGES:
            heading = f"## {stage} ({len(stage_companies)})"
        else:
            total = sum(c.value_eur_month or 0 for c in stage_companies)
            heading = f"## {stage} ({len(stage_companies)}, {_fmt_money(total)} EUR/month)"
        lines = [heading] + [_company_line(c, today) for c in stage_companies]
        blocks.append("\n".join(lines))

    overdue = sorted(
        (c for c in companies if not c.is_closed and c.next_overdue(today)),
        key=lambda c: (c.next_due, c.slug),
    )
    lines = [f"## Overdue next steps ({len(overdue)})"] + [
        f"- {c.slug} | {c.stage} | due {c.next_due:%Y-%m-%d} | {c.next_text}"
        for c in overdue
    ]
    blocks.append("\n".join(lines))

    silent = sorted(
        (
            c for c in companies
            if c.is_active and c.silent_days(today) >= store.silent_days
        ),
        key=lambda c: (-c.silent_days(today), c.slug),
    )
    lines = [f"## Silent for {store.silent_days}+ days, not closed ({len(silent)})"]
    for c in silent:
        touch = f"{c.last_touch:%Y-%m-%d}" if c.last_touch else "none"
        lines.append(f"- {c.slug} | {c.stage} | last touch {touch} ({c.silent_days(today)}d)")
    blocks.append("\n".join(lines))

    cutoff = today - timedelta(days=CLOSED_WINDOW_DAYS)
    closed = [
        c for c in companies
        if c.is_closed and c.stage_changed is not None and c.stage_changed >= cutoff
    ]
    won = sorted((c for c in closed if c.stage == "won"),
                 key=lambda c: (c.stage_changed, c.slug))
    lost = sorted((c for c in closed if c.stage == "lost"),
                  key=lambda c: (c.stage_changed, c.slug))
    disqualified = sorted((c for c in closed if c.stage == "disqualified"),
                          key=lambda c: (c.stage_changed, c.slug))
    parked = sorted((c for c in companies if c.is_parked),
                    key=lambda c: (c.stage_changed or date.min, c.slug))
    lines = [f"## Temp disqualified ({len(parked)})"]
    for c in parked:
        since = f"{c.stage_changed:%Y-%m-%d}" if c.stage_changed else "unknown"
        if c.requalify_on:
            since += f" until {c.requalify_on:%Y-%m-%d}"
        reason = c.lost_reason or "no reason"
        lines.append(f"- {c.slug} | since {since} | {reason} | "
                     f"{_next_field(c)}")
    blocks.append("\n".join(lines))

    lines = ["## Closed last 90 days"]
    if won:
        lines.append(
            "- won: " + "; ".join(f"{c.slug} ({c.stage_changed:%Y-%m-%d})" for c in won)
        )
    if lost:
        lines.append(
            "- lost: " + "; ".join(
                f"{c.slug} ({c.stage_changed:%Y-%m-%d}, {c.lost_reason})" for c in lost
            )
        )
    if disqualified:
        lines.append(
            "- disqualified: " + "; ".join(
                f"{c.slug} ({c.stage_changed:%Y-%m-%d}, {c.lost_reason or 'no reason'})"
                for c in disqualified
            )
        )
    if not won and not lost and not disqualified:
        lines.append("- none")
    blocks.append("\n".join(lines))

    return "\n\n".join(blocks) + "\n"


def write(store: Store, now: datetime | None = None) -> bool:
    """Render and write store.root / 'PIPELINE.md' (utf-8). Only write when the
    content differs from the existing file (compare bytes) -- return True if
    written/changed, False if unchanged."""
    content = render(store, now)
    path = store.root / "PIPELINE.md"
    new_bytes = content.encode("utf-8")
    if path.exists() and path.read_bytes() == new_bytes:
        return False
    path.write_text(content, encoding="utf-8")
    return True
