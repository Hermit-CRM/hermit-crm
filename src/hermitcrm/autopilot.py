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
- `next_steps`: a proposed next step for a company that has none, kept as a
  proposal (below) until the user approves it on Today.

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
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import routines
from .enrich import EnrichError
from .models import fmt_date, fmt_datetime, parse_datetime
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


# ----------------------------------------------------------------- proposals
#
# A proposal is something autopilot prepared that is not a message draft: a next
# step for a company, and the kinds a later feature adds (the after-contact
# assistant). It lives in the state file under "proposals", never on the
# record, until the user approves it on Today; Approve writes it with the normal
# store call. A kind is a `Kind` in KINDS; another module adds its own with
# `register_kind` and stores its proposals with `add_proposals`.

PREPARED = "prepared"              # the Today kind of every autopilot row
HEADING = "Prepared for you"       # its group on Today
NEXT_STEP = "next-step"            # a proposal kind
NEXT_STEP_DAYS = 14                # a conversation at most this long ago
NEXT_STEP_TEXT_LIMIT = 200
NEXT_STEP_MAX_DAYS = 90            # a proposed date at most this far ahead
WHY_LIMIT = 300
RECORD_LIMIT = 12000
NEXT_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "next_step": {"type": "string",
                      "description": "one short action the user takes themselves; "
                                     "empty when there should be none"},
        "due": {"type": "string", "description": "the date to do it, YYYY-MM-DD"},
        "why": {"type": "string", "description": "one sentence: why this, why then"},
        "skip": {"type": "string",
                 "description": "when next_step is empty: why no next step makes sense"},
    },
    "required": ["next_step", "due", "why", "skip"],
    "additionalProperties": False,
}


@dataclass
class Proposal:
    id: str
    kind: str
    company: str                   # slug
    made: str                      # when, as fmt_datetime
    text: str                      # what is proposed
    due: str = ""                  # YYYY-MM-DD, for a kind with a date
    why: str = ""                  # the AI's one-line reason
    contact: str = ""              # slug, for a kind about one person
    basis: str = ""                # the interaction it was made from
    extra: dict = field(default_factory=dict)  # anything else a kind keeps

    @classmethod
    def from_json(cls, data) -> "Proposal | None":
        if not isinstance(data, dict):
            return None
        try:
            got = cls(**{f: data[f] for f in cls.__dataclass_fields__ if f in data})
        except TypeError:
            return None
        texts = (got.id, got.kind, got.company, got.made, got.text, got.due, got.why,
                 got.contact, got.basis)
        if not all(isinstance(t, str) for t in texts) or not isinstance(got.extra, dict):
            return None
        return got if got.id and got.kind and got.company else None

    def as_json(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}

    @property
    def due_date(self) -> date | None:
        try:
            return date.fromisoformat(self.due)
        except ValueError:
            return None


@dataclass(frozen=True)
class Kind:
    """A kind of proposal: what Today calls it, and what Approve does. `approve(store,
    proposal)` writes it with a normal store call (one commit) and returns the
    message to show; it raises ValidationError for a value the store refuses."""

    name: str
    label: str                     # "Next step"
    approve: object
    has_due: bool = True


KINDS: dict[str, Kind] = {}


def register_kind(kind: Kind) -> Kind:
    KINDS[kind.name] = kind
    return kind


def proposals(root: Path | str, kind: str | None = None) -> list[Proposal]:
    """Every open proposal (of one kind), oldest first; made in the same run, in
    the order they were made (the sort is stable, the ids are random)."""
    out = [p for p in (Proposal.from_json(d) for d in read_state(root).get("proposals") or [])
           if p is not None and (kind is None or p.kind == kind)]
    return sorted(out, key=lambda p: p.made)


def get_proposal(root: Path | str, proposal_id: str) -> Proposal | None:
    return next((p for p in proposals(root) if p.id == proposal_id), None)


def _save_proposals(root: Path | str, state: dict, items: list[Proposal]) -> None:
    state["proposals"] = [p.as_json() for p in items]
    write_state(root, state)


def add_proposals(store, new: list[Proposal]) -> list[Proposal]:
    """Keep new proposals, each with a fresh id. Under the store's write lock:
    the web app and the daily sync are different processes."""
    with store.lock:
        state = read_state(store.root)
        items = proposals(store.root)
        for p in new:
            p.id = p.id or uuid.uuid4().hex[:12]
            items.append(p)
        _save_proposals(store.root, state, items)
    return new


def update_proposal(store, proposal_id: str, text: str, due: str) -> Proposal | None:
    """Change what a proposal says (Edit); None when it is gone."""
    with store.lock:
        state = read_state(store.root)
        items = proposals(store.root)
        found = next((p for p in items if p.id == proposal_id), None)
        if found is not None:
            found.text, found.due = text, due
            _save_proposals(store.root, state, items)
    return found


def remove_proposal(store, proposal_id: str, discarded: bool = False) -> Proposal | None:
    """Drop a proposal (approved or discarded). A discarded one is remembered
    with the interaction it came from, so the same conversation is not
    proposed again until something new is logged."""
    with store.lock:
        state = read_state(store.root)
        items = proposals(store.root)
        found = next((p for p in items if p.id == proposal_id), None)
        if found is None:
            return None
        if discarded and found.basis:
            dismissed = state.get("dismissed") if isinstance(state.get("dismissed"), dict) \
                else {}
            dismissed[f"{found.kind}:{found.company}"] = found.basis
            state["dismissed"] = dismissed
        _save_proposals(store.root, state, [p for p in items if p.id != proposal_id])
    return found


def approve_proposal(store, proposal_id: str) -> str:
    """Write a proposal with its kind's store call, then drop it. The message to
    show; raises KeyError when it is gone, ValidationError when the store refuses."""
    proposal = get_proposal(store.root, proposal_id)
    kind = KINDS.get(proposal.kind) if proposal is not None else None
    if proposal is None or kind is None:
        raise KeyError(proposal_id)
    message = kind.approve(store, proposal)
    remove_proposal(store, proposal_id)
    return message


# --------------------------------------------------------------- next steps


def _approve_next_step(store, proposal: Proposal) -> str:
    company = store.companies.get(proposal.company)
    # A proposal about one person (the after-contact assistant, assist.py) is
    # their task, while they are still on file; the company's next step either way.
    contact = proposal.contact if company and proposal.contact in company.contacts else ""
    store.add_task(proposal.company, proposal.text, due=proposal.due or None,
                   contact=contact,
                   message=f"task: {proposal.company} added (autopilot proposal)")
    return f"Next step added for {company.name if company else proposal.company}"


register_kind(Kind(NEXT_STEP, "Next step", _approve_next_step))


def next_step_candidates(store, today: date) -> list[tuple[object, object]]:
    """(company, its latest interaction) for each open company with no open next
    step and a conversation in the last NEXT_STEP_DAYS days, most recent first.
    Not one with a proposal waiting, nor one whose proposal was discarded with
    nothing new logged since. No AI."""
    root = store.root
    waiting = {p.company for p in proposals(root, NEXT_STEP)}
    dismissed = read_state(root).get("dismissed")
    dismissed = dismissed if isinstance(dismissed, dict) else {}
    out = []
    for company in store.companies.values():
        if company.is_sample or not company.is_active or company.open_todos():
            continue
        if company.slug in waiting:
            continue
        recent = [i for i in company.interactions if i.date
                  and 0 <= (today - i.date.date()).days <= NEXT_STEP_DAYS]
        if not recent:
            continue
        latest = max(recent, key=lambda i: (i.date, i.id))
        if dismissed.get(f"{NEXT_STEP}:{company.slug}") == latest.id:
            continue
        out.append((company, latest))
    out.sort(key=lambda pair: (pair[1].date, pair[0].slug), reverse=True)
    return out


def next_step_prompt(store, company, today: date) -> str:
    from .cli import cmd_show  # `hermitcrm show`, the agreed way to read one account

    record = cmd_show(store, company.slug, bodies=3)[:RECORD_LIMIT]
    return "\n\n".join([
        "You propose one next step in a sales conversation, for a person to approve, "
        "change or discard. Nothing you write is saved until they approve it.",
        f"Today is {today.isoformat()}. The company {company.name} has no open task; "
        f"its last conversation was in the last {NEXT_STEP_DAYS} days.",
        f"--- the record (hermitcrm show {company.slug}) ---\n{record}\n--- end ---",
        "Rules: next_step is one short action the user takes themselves (a call, a "
        f"message, a meeting to propose), plain text, at most {NEXT_STEP_TEXT_LIMIT} "
        f"characters. due is a date from today to {NEXT_STEP_MAX_DAYS} days ahead, as "
        "YYYY-MM-DD. why is one sentence. Never invent facts, numbers or meetings. If "
        "no next step makes sense (the deal is over, they said no), leave next_step "
        "empty and say why in skip.",
    ]) + "\n"


def clean_next_step(data, today: date) -> tuple[str, str, str, str]:
    """(text, due, why, skip) from the AI's JSON; routines.Rejected when unusable."""
    if not isinstance(data, dict):
        raise routines.Rejected("the AI returned no JSON object")
    values = [data.get(k) or "" for k in ("next_step", "due", "why", "skip")]
    if not all(isinstance(v, str) for v in values):
        raise routines.Rejected("the AI returned something other than text")
    text, due, why, skip = (" ".join(v.split()) for v in values)
    if not text:
        if skip:
            return "", "", "", skip[:WHY_LIMIT]
        raise routines.Rejected("the AI returned no next step")
    if len(text) > NEXT_STEP_TEXT_LIMIT:
        raise routines.Rejected(f"the next step is over {NEXT_STEP_TEXT_LIMIT} characters")
    try:
        when = date.fromisoformat(due)
    except ValueError:
        raise routines.Rejected(f"the date {due!r} is not YYYY-MM-DD") from None
    if not 0 <= (when - today).days <= NEXT_STEP_MAX_DAYS:
        raise routines.Rejected(f"the date {due} is not between today and "
                                f"{NEXT_STEP_MAX_DAYS} days ahead")
    return text, when.isoformat(), why[:WHY_LIMIT], ""


def _next_steps(store, config: dict, ai, now: datetime, room: int, report: Report) -> None:
    today = now.date()
    candidates = next_step_candidates(store, today)
    if not candidates:
        return
    if room <= 0:
        report.lines.append(f"next steps: {len(candidates)} waiting, but today's limit "
                            "is reached")
        return
    enricher = ai()
    if not enricher.available:
        raise routines.RoutineError(enricher.unavailable_reason())
    light = enricher.with_tier("light")
    if routines.ai_problem(light):
        raise routines.RoutineError(routines.ai_problem(light))
    made, failed = [], []
    for company, latest in candidates[:room]:
        try:
            data = light.runner(next_step_prompt(store, company, today), NEXT_STEP_SCHEMA,
                                tools="")
            text, due, why, skip = clean_next_step(data, today)
        except EnrichError as exc:
            failed.append(str(exc))
            report.lines.append(f"  skipped {company.name}: {exc}")
            continue
        except routines.Rejected as exc:
            report.lines.append(f"  skipped {company.name}: {exc}")
            continue
        if skip:
            report.lines.append(f"  skipped {company.name}: the AI says {skip}")
            with store.lock:   # not again until something new is logged
                state = read_state(store.root)
                dismissed = state.get("dismissed") if isinstance(state.get("dismissed"),
                                                                 dict) else {}
                dismissed[f"{NEXT_STEP}:{company.slug}"] = latest.id
                state["dismissed"] = dismissed
                write_state(store.root, state)
            continue
        made.append(Proposal(id="", kind=NEXT_STEP, company=company.slug,
                             made=fmt_datetime(now), text=text, due=due, why=why,
                             basis=latest.id))
        report.lines.append(f"  proposed: {company.name} | {due} | {text}")
    if made:
        add_proposals(store, made)
    report.made += len(made)
    report.lines.insert(0, f"next steps: {len(made)} proposed")
    if failed and not made and len(failed) == len(candidates[:room]):
        raise routines.RoutineError(f"the AI tool failed: {failed[0]}")


def _next_steps_dry_run(store, config: dict, today: date) -> list[str]:
    n = len(next_step_candidates(store, today))
    return [f"autopilot: next steps: would propose for {n} compan"
            f"{'y' if n == 1 else 'ies'} (dry run, no AI)"]


EXTRA_PARTS.append(Part(NEXT_STEPS, "next steps", _next_steps, _next_steps_dry_run))


# ---------------------------------------------------------------------- Today


def prepared_items(store, config: dict, today_: date) -> list:
    """Today's "Prepared for you": a run that could not run (while a switch is on),
    and every open proposal with Approve, Edit and Discard. (Drafts come through Today's routine
    provider: they are routine drafts, with the routine draft's own actions.)"""
    from .today import Action, Item

    root = store.root
    out = []
    reason = failure(root) if enabled(config) else ""   # switched off: no warning left over
    if reason:
        out.append(Item(
            kind=PREPARED, company=None, contact=None,
            title=f"Autopilot could not run: {reason}",
            reason="It tries again after the next daily sync. Settings has the details.",
            due=today_, href="/settings#autopilot",
            actions=(Action("Settings", "/settings#autopilot", secondary=True),),
            key="autopilot-failed"))
    for p in proposals(root):
        company = store.companies.get(p.company)
        kind = KINDS.get(p.kind)
        if company is None or kind is None:
            continue
        when = p.due_date
        bits = [f"for {fmt_date(when)}" if when else "", p.why]
        out.append(Item(
            kind=PREPARED, company=company, contact=company.contacts.get(p.contact)
            if p.contact else None,
            title=f"{kind.label}: {p.text}",
            reason="Proposed " + "; ".join(b for b in bits if b),
            due=parse_datetime(p.made).date() if parse_datetime(p.made) else today_,
            href=f"/companies/{company.slug}",
            actions=(Action("Approve", f"/autopilot/proposals/{p.id}/approve", "post"),
                     Action("Edit", f"/autopilot/proposals/{p.id}"),
                     Action("Discard", f"/autopilot/proposals/{p.id}/discard", "post",
                            secondary=True)),
            key=f"proposal-{p.id}"))
    return out


def _register_today() -> None:
    """Put "Prepared for you" on Today (its kind is in today.ORDER)."""
    from . import today

    today.register(prepared_items)


_register_today()
