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

"""Autopilot: the morning's routine work, done before the user opens the app.

Autopilot is built-in routines the user switches on once in Settings, not a
new engine. One `config.toml` key, a table of switches, every one off unless
the user turned it on (the key is not in DEFAULT_CONFIG):

    autopilot = { reply_drafts = true, follow_up_drafts = false,
                  meeting_briefs = true, next_steps = false }
    autopilot_daily_cap = 15     # prepared items a day, at most (default 15)

- `reply_drafts`: the `replies_owed` selector with the `draft` action.
- `follow_up_drafts`: the `quiet_threads` selector with the `draft` action.
- `meeting_briefs`: the morning brief (`routines.make_brief`); no AI.
- `next_steps`: a proposed next step for a company that has none (step 2).

It runs where routines run, after the daily sync (`routines.run_all`, which
`hermitcrm sync --apply` calls), after the user's own routines. Drafts are the
routines' draft files (`drafts/`), so Home, Today, "I sent it" and Discard work
on them unchanged. Nothing here sends, schedules or marks anything ready.

Privacy: with every switch off, `run` returns before it builds an enricher, so
a sync makes no AI call at all (tests/test_autopilot.py proves it).

A run that cannot work (no AI tool, one that cannot run without tools, an
exception, or every AI call failing) is recorded in `.git/hermitcrm-autopilot.json`
and Today shows "Autopilot could not run: <reason>" until a run works. The
file also keeps the daily count for the cap and today's brief. It is runtime
state, never committed; a missing or damaged one reads as empty.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import routines
from .enrich import EnrichError
from .models import fmt_datetime
from .send import runtime_dir

logger = logging.getLogger("hermitcrm.autopilot")

KEY = "autopilot"
CAP_KEY = "autopilot_daily_cap"
DEFAULT_CAP = 15
MAX_CAP = 100
STATE_FILE = "hermitcrm-autopilot.json"

REPLY_DRAFTS = "reply_drafts"
FOLLOW_UP_DRAFTS = "follow_up_drafts"
MEETING_BRIEFS = "meeting_briefs"
NEXT_STEPS = "next_steps"
SWITCHES = (REPLY_DRAFTS, FOLLOW_UP_DRAFTS, MEETING_BRIEFS, NEXT_STEPS)

# What Settings says next to each switch: what goes to the AI tool, and when.
LABELS = {
    REPLY_DRAFTS: (
        "Reply drafts",
        "After the daily sync, for each person who wrote to you and is still waiting, "
        "the company's record (as hermitcrm show prints it) and your playbook go to "
        "your AI tool, with its tools off. The draft waits on Today; nothing is sent."),
    FOLLOW_UP_DRAFTS: (
        "Follow-up drafts",
        "After the daily sync, for each thread where you wrote last and nothing came "
        "back within the follow-up days, the same record and playbook go to your AI "
        "tool. The draft waits on Today; nothing is sent."),
    MEETING_BRIEFS: (
        "Morning brief",
        "After the daily sync, a short brief of today's meetings, tasks due and "
        "replies owed. Made on this computer: nothing goes to your AI tool."),
    NEXT_STEPS: (
        "Next-step proposals",
        "After the daily sync, for each open company with no next step and a "
        "conversation in the last 14 days, its record goes to your AI tool on the "
        "light model, tools off. It proposes a next step and a date for you to "
        "approve; nothing is written to the record until you do."),
}

# The built-in routines. Their names are what the draft files carry.
REPLY_ROUTINE = "autopilot-replies"
FOLLOW_UP_ROUTINE = "autopilot-follow-ups"
BRIEF_ROUTINE = "autopilot-brief"
TITLES = {REPLY_ROUTINE: "Autopilot: reply drafts",
          FOLLOW_UP_ROUTINE: "Autopilot: follow-up drafts",
          BRIEF_ROUTINE: "Autopilot: morning brief"}
REPLY_PROMPT = (
    "Draft a reply that answers their last message point by point. Put anything I "
    "must check or decide myself in [square brackets]. Keep my usual tone.")
FOLLOW_UP_PROMPT = (
    "Write a short, friendly follow-up to my last message: two or three sentences, "
    "one easy question, no pressure and no \"just checking in\". Refer to what we "
    "last talked about. Sign with my first name.")


# ------------------------------------------------------------------ settings


def _on(value) -> bool:
    """Only a real `true` turns a switch on: a typo or a string stays off."""
    return value is True


def switches(config: dict | None) -> dict[str, bool]:
    """Every switch, on or off. A missing or malformed table is all off."""
    table = (config or {}).get(KEY)
    table = table if isinstance(table, dict) else {}
    return {name: _on(table.get(name)) for name in SWITCHES}


def enabled(config: dict | None) -> bool:
    return any(switches(config).values())


def daily_cap(config: dict | None) -> int:
    raw = (config or {}).get(CAP_KEY, DEFAULT_CAP)
    if isinstance(raw, bool):
        return DEFAULT_CAP
    try:
        cap = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_CAP
    return max(0, min(MAX_CAP, cap))


def plan_settings(on: list[str], cap: str) -> tuple[dict, dict[str, str]]:
    """The Settings form as config values, and the errors by field."""
    errors: dict[str, str] = {}
    chosen = set(on or [])
    unknown = chosen - set(SWITCHES)
    if unknown:
        errors["autopilot"] = f"Unknown switch: {', '.join(sorted(unknown))}."
    text = str(cap or "").strip()
    value = DEFAULT_CAP
    if text:
        if not text.isdigit() or not 1 <= int(text) <= MAX_CAP:
            errors[CAP_KEY] = f"The daily limit must be a whole number from 1 to {MAX_CAP}."
        else:
            value = int(text)
    return ({KEY: {name: name in chosen for name in SWITCHES}, CAP_KEY: value}, errors)


def save_settings(root: Path | str, on: list[str], cap: str) -> dict[str, str]:
    """Write the switches and the cap to config.toml; the errors, {} when saved.
    The caller commits it (setup.commit_config), as every Settings save does."""
    from .setup import set_config_values

    values, errors = plan_settings(on, cap)
    if not errors:
        set_config_values(Path(root) / "config.toml", values)
    return errors


# --------------------------------------------------------------------- state


def path(root: Path | str) -> Path:
    return runtime_dir(root) / STATE_FILE


def read_state(root: Path | str) -> dict:
    try:
        data = json.loads(path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(root: Path | str, state: dict) -> None:
    """Write the whole file. Never raises: a run must not fail on its log."""
    target = path(root)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        logger.exception("could not write %s", target)


def made_today(state: dict, today: date) -> int:
    """Items prepared today so far, for the daily cap."""
    count = state.get("made") if state.get("day") == today.isoformat() else 0
    return count if isinstance(count, int) and count > 0 else 0


def failure(root: Path | str) -> str:
    """Why the last run could not run, or "" when it worked (or never ran)."""
    last = read_state(root).get("last_run")
    if not isinstance(last, dict) or last.get("ok", True):
        return ""
    return str(last.get("error") or "unknown reason")


def today_brief(root: Path | str, today: date) -> dict | None:
    """Today's brief, when the morning brief switch made one today."""
    from .models import fmt_date

    brief = read_state(root).get("brief")
    if isinstance(brief, dict) and brief.get("date") == fmt_date(today):
        return brief
    return None


# ----------------------------------------------------------------------- run


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    made: int = 0          # drafts and proposals, for the cap


def _routine(name: str, select: str, prompt: str) -> routines.Routine:
    return routines.Routine(name=name, title=TITLES[name], action="draft", paused=False,
                            select=select, prompt=prompt, limit=routines.MAX_LIMIT)


def _picks(store, routine: routines.Routine, config: dict, today: date) -> list:
    """Who the built-in routine would write to, minus anyone who already has a
    draft waiting (from any routine, the user's own too) or whose thread any
    routine already drafted."""
    root = store.root
    waiting = {d.record for d in routines.drafts(root)}
    done = {(record, basis) for _, record, basis in routines.handled(root)}
    return [p for p in routines.select(store, routine, config, today)
            if not p.status and p.record not in waiting and (p.record, p.basis) not in done]


def _draft(store, routine: routines.Routine, ai, config: dict, now: datetime,
           room: int, report: Report) -> None:
    """One built-in draft routine: an AI run per pick, at most `room` of them."""
    picks = _picks(store, routine, config, now.date())
    if not picks:
        return
    label = TITLES[routine.name].split(": ", 1)[1]
    if room <= 0:
        report.lines.append(f"{label}: {len(picks)} waiting, but today's limit is reached")
        return
    enricher = ai()
    if not enricher.available:
        raise routines.RoutineError(enricher.unavailable_reason())
    if routines.ai_problem(enricher):
        raise routines.RoutineError(routines.ai_problem(enricher))
    failed: list[str] = []
    made = 0
    for pick in picks[:room]:
        try:
            answer = routines.ask_ai(store, routine, pick, enricher, config)
        except EnrichError as exc:
            failed.append(str(exc))
            report.lines.append(f"  skipped {pick.who}: {exc}")
            continue
        except routines.Rejected as exc:
            report.lines.append(f"  skipped {pick.who}: {exc}")
            continue
        with store.lock:
            if answer.skip:
                routines._mark_handled(store.root, routine.name, pick.record, pick.basis,
                                       f"skipped: {answer.skip}", now)
                report.lines.append(f"  skipped {pick.who}: the AI says {answer.skip}")
                continue
            draft = routines.write_draft(store.root, routines.Draft(
                id="", routine=routine.name, made=now, record=pick.record,
                company=pick.company.slug,
                contact=pick.contact.slug if pick.contact is not None else "",
                channel=answer.channel, subject=answer.subject, basis=pick.basis,
                reason=pick.reason, body=answer.body))
        made += 1
        report.lines.append(f"  drafted: {pick.who} | {answer.channel} | {draft.id}")
    report.made += made
    report.lines.insert(0, f"{label}: {made} draft{'' if made == 1 else 's'}")
    if failed and not made and len(failed) == len(picks[:room]):
        # Every call failed the same way (a lapsed login, say): that is not "skipped".
        raise routines.RoutineError(f"the AI tool failed: {failed[0]}")


def run(store, config: dict | None = None, apply: bool = False, enricher=None,
        now: datetime | None = None) -> list[str]:
    """Every part that is switched on, after the user's routines. Returns the
    report lines; [] when every switch is off (and then no AI call, no write).

    Without apply: who it would prepare for, with no AI and no writes. With
    apply: the drafts are one commit (`autopilot: <n> drafts`); a part that
    fails is recorded and the next part still runs."""
    on = switches(config)
    if not any(on.values()):
        return []
    root = store.root
    config = config or {}
    now = now or store.now()
    today = now.date()
    if not apply:
        return _dry_run(store, config, on, today)

    state = read_state(root)
    room = daily_cap(config) - made_today(state, today)
    shared = {"enricher": enricher}

    def ai():
        if shared["enricher"] is None:
            shared["enricher"] = routines.default_enricher(config)
        return shared["enricher"]

    parts = []
    if on[REPLY_DRAFTS]:
        parts.append(("reply drafts", lambda r: _draft(
            store, _routine(REPLY_ROUTINE, "replies_owed", REPLY_PROMPT),
            ai, config, now, room - r.made, r)))
    if on[FOLLOW_UP_DRAFTS]:
        parts.append(("follow-up drafts", lambda r: _draft(
            store, _routine(FOLLOW_UP_ROUTINE, "quiet_threads", FOLLOW_UP_PROMPT),
            ai, config, now, room - r.made, r)))
    for extra in EXTRA_PARTS:
        if on.get(extra.switch):
            parts.append((extra.label, lambda r, e=extra: e.run(
                store, config, ai, now, room - r.made, r)))

    total = Report()
    brief = None
    if on[MEETING_BRIEFS]:
        brief = routines.make_brief(store, config, now)
        total.lines.append(f"morning brief: {routines.brief_summary(brief)}")
    try:
        for label, part in parts:
            report = Report(made=total.made)
            try:
                part(report)
            except Exception as exc:  # one part never stops the others or the sync
                message = str(exc) if isinstance(exc, routines.RoutineError) else \
                    f"{type(exc).__name__}: {exc}"
                logger.warning("autopilot %s failed: %s", label, message)
                report.lines.append(f"{label}: failed: {message}")
                total.errors.append(f"{label}: {message}")
            total.made = report.made
            total.lines += report.lines
    finally:
        wrote = sum(1 for line in total.lines if line.startswith("  drafted: "))
        if wrote:  # a crash halfway still commits the drafts already written
            store.notify(f"autopilot: {wrote} draft{'' if wrote == 1 else 's'}",
                         [routines.DRAFTS_DIR])
        state = read_state(root)   # a part may have written proposals meanwhile
        state["day"] = today.isoformat()
        state["made"] = made_today(state, today) + total.made
        state["last_run"] = {"at": fmt_datetime(now), "ok": not total.errors,
                             "error": "; ".join(total.errors),
                             "summary": f"{total.made} prepared"}
        if brief is not None:
            state["brief"] = brief
        write_state(root, state)
    return [f"autopilot: {line}" if not line.startswith("  ") else line
            for line in total.lines] or ["autopilot: nothing to prepare"]


def _dry_run(store, config: dict, on: dict, today: date) -> list[str]:
    out = []
    for switch, name, select, prompt in (
            (REPLY_DRAFTS, REPLY_ROUTINE, "replies_owed", REPLY_PROMPT),
            (FOLLOW_UP_DRAFTS, FOLLOW_UP_ROUTINE, "quiet_threads", FOLLOW_UP_PROMPT)):
        if on[switch]:
            n = len(_picks(store, _routine(name, select, prompt), config, today))
            out.append(f"autopilot: {TITLES[name].split(': ', 1)[1]}: would draft for "
                       f"{n} record{'' if n == 1 else 's'} (dry run, no AI)")
    if on[MEETING_BRIEFS]:
        out.append("autopilot: morning brief: would be made (no AI)")
    for extra in EXTRA_PARTS:
        if on.get(extra.switch):
            out += extra.dry_run(store, config, today)
    return out


@dataclass(frozen=True)
class Part:
    """A part of the run beyond the drafts: next-step proposals, and the kinds a
    later feature adds. `run(store, config, ai, now, room, report)` prepares at
    most `room` items and adds them to `report.made`; `dry_run(store, config,
    today)` returns lines and calls no AI."""

    switch: str
    label: str
    run: object
    dry_run: object


EXTRA_PARTS: list[Part] = []


def settings_form(config: dict | None, root: Path | str) -> dict:
    """What the Settings section shows: each switch with what it sends, the
    daily limit, and how the last run went."""
    on = switches(config)
    last = read_state(root).get("last_run")
    last = last if isinstance(last, dict) else {}
    if not last:
        last_text = "Has not run yet." if any(on.values()) else ""
    elif last.get("ok", True):
        last_text = (f"Last run {str(last.get('at', '')).replace('T', ' ')}: "
                     f"{last.get('summary', '')}.")
    else:
        last_text = ""   # the failure has its own line
    return {"switches": [{"name": name, "label": LABELS[name][0], "text": LABELS[name][1],
                          "on": on[name]} for name in SWITCHES],
            "any_on": any(on.values()), "cap": daily_cap(config), "max_cap": MAX_CAP,
            "failure": failure(root), "last_run": last_text}
