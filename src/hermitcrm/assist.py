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

"""The after-contact assistant: right after something is logged, Hermit
proposes what follows from it.

One switch, off unless the user turned it on in Settings (it is not in
DEFAULT_CONFIG, and only a real `true` counts):

    after_contact = true

When it is on, logging an interaction (the web form, BCC import, calendar
import, a LinkedIn conversation import, filing an item from the review queue)
starts one background job per interaction (jobs.JobRunner.start; the command
line runs it in place). The job makes ONE light-tier AI call with no tools.
The prompt holds that interaction, the three before it and the company's
fields; the answer is JSON against SCHEMA:

- a next step with a due date (stored as autopilot's next-step proposal),
- a stage move, only to a configured stage the rules allow, with one sentence
  of reason,
- up to five facts: the monthly value, a custom company field marked
  `enrich = true` in fields.toml, or a note.

Every one of them carries the exact sentence it came from. One whose sentence
is not in the interaction is dropped before anyone sees it, and so is one the
store would refuse (an unknown stage, a value that is not a number).

What is left is kept as autopilot proposals (autopilot.py, the `.git/` state
file), never on the record. They show as chips on the company and contact
pages (templates/assist_chips.html) and on Today under "Prepared for you".
Accept writes one with the normal store call (one commit, so it can be undone);
Dismiss drops it. The interaction itself is never changed.

Bulk imports queue at most MAX_PER_RUN jobs per run; the rest are named in the
import's summary line. With the switch off, nothing here builds an enricher,
starts a job or reads the folder (tests/test_assist.py proves it).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

from . import autopilot, routines
from . import fields as fields_mod
from .autopilot import Kind, Proposal
from .enrich import EnrichError
from .models import ValidationError, fmt_datetime

logger = logging.getLogger("hermitcrm.assist")

KEY = "after_contact"              # config.toml; not in DEFAULT_CONFIG
STATE_KEY = "after_contact"        # its last run, in autopilot's state file
JOB_KIND = "after-contact"
MAX_PER_RUN = 10                   # jobs one import may queue
BEFORE = 3                         # earlier interactions in the prompt
MIN_BODY = 20                      # characters of text below which nothing is asked
MIN_QUOTE = 12                     # a shorter "sentence" proves nothing
MAX_FACTS = 5
BODY_LIMIT = 6000                  # characters of the interaction in the prompt
EARLIER_LIMIT = 1500               # characters of each earlier one

STAGE_MOVE = "stage-move"          # proposal kinds (autopilot.KINDS)
FACT = "fact"                      # a field's value: "Label: value"
NOTE_KIND = "note"                 # a note to keep: just its text
VALUE = "value_eur_month"          # the facts a proposal may name
NOTE = "note"
VALUE_LABEL = "Monthly value (EUR)"

LABEL = "After-contact suggestions"
TEXT = ("Each time you log a call, a message or a meeting (by hand, BCC, the calendar "
        "or a LinkedIn import), that interaction, the three before it and the company's "
        "fields go to your AI tool on the light model, tools off. It suggests a next "
        "step, a stage move and facts to save; nothing is written to the record until "
        "you accept one.")


# ------------------------------------------------------------------ settings


def enabled(config: dict | None) -> bool:
    """Only a real `true` turns it on: a typo or a string stays off."""
    return (config or {}).get(KEY) is True


def save_settings(root: Path | str, on: bool) -> None:
    """Write the switch to config.toml. The caller commits it (setup.commit_config)."""
    from .setup import set_config_values

    set_config_values(Path(root) / "config.toml", {KEY: bool(on)})


def last_run(root: Path | str) -> dict:
    data = autopilot.read_state(root).get(STATE_KEY)
    return data if isinstance(data, dict) else {}


def failure(root: Path | str) -> str:
    """Why the last suggestion run failed, or "" when it worked (or never ran)."""
    last = last_run(root)
    if not last or last.get("ok", True):
        return ""
    return str(last.get("error") or "unknown reason")


def settings_form(config: dict | None, root: Path | str) -> dict:
    last = last_run(root)
    on = enabled(config)
    if not last:
        text = "Has not run yet." if on else ""
    elif last.get("ok", True):
        text = (f"Last run {str(last.get('at', '')).replace('T', ' ')}: "
                f"{last.get('summary', '')}.")
    else:
        text = ""   # the failure has its own line
    return {"on": on, "label": LABEL, "text": TEXT, "failure": failure(root),
            "last_run": text}


def _record(store, ok: bool, error: str = "", summary: str = "") -> None:
    """The last run, for Settings. Never raises: a run must not fail on its log."""
    try:
        with store.lock:
            state = autopilot.read_state(store.root)
            state[STATE_KEY] = {"at": fmt_datetime(store.now()), "ok": ok,
                                "error": error, "summary": summary}
            autopilot.write_state(store.root, state)
    except Exception:  # noqa: BLE001 - the log is a convenience
        logger.exception("could not record the after-contact run")


# -------------------------------------------------------------- the prompt


def enrich_fields(root: Path | str) -> list:
    """The custom company fields marked `enrich = true`: the facts besides
    the monthly value and a note. A fields.toml that cannot be read gives none."""
    try:
        defs = fields_mod.load(root)
    except fields_mod.FieldError:
        return []
    return [d for d in fields_mod.for_scope(defs, "company") if d.enrich]


def _text(it) -> str:
    """What a quote must be found in: the subject and the body."""
    return "\n".join(t for t in (it.subject, it.body) if t)


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _bare_quote(quote) -> str:
    """The AI's quote without the marks it may wrap around it."""
    text = _norm(quote if isinstance(quote, str) else "")
    return text.strip(" \"'“”‘’„«»").removesuffix("...").removesuffix("…").strip()


def found(quote: str, it) -> bool:
    """The quote, whitespace aside, is in the interaction word for word."""
    q = _bare_quote(quote)
    return len(q) >= MIN_QUOTE and q in _norm(_text(it))


def earlier(company, it, n: int = BEFORE) -> list:
    """The n interactions logged before `it` at this company, newest first."""
    key = (it.date or datetime.min, it.id)
    older = [i for i in company.interactions
             if i.id != it.id and (i.date or datetime.min, i.id) < key]
    return sorted(older, key=lambda i: (i.date or datetime.min, i.id), reverse=True)[:n]


def _who(company, it) -> str:
    contact = company.contacts.get(it.contact) if it.contact else None
    return contact.name if contact is not None else "the company as a whole"


def _describe(company, it, limit: int) -> str:
    when = it.date.strftime("%Y-%m-%d %H:%M") if it.date else "no date"
    head = f"{when} | {it.label} | {_who(company, it)}"
    if it.subject:
        head += f" | subject: {it.subject}"
    body = (it.body or "").strip()
    if len(body) > limit:
        body = body[:limit] + "\n[cut]"
    return head + ("\n" + body if body else "")


def _fields_block(store, company, defs) -> str:
    lines = [f"name: {company.name}", f"stage: {company.stage}"]
    if company.value_eur_month is not None:
        lines.append(f"{VALUE}: {company.value_eur_month}")
    for name in ("country", "website"):
        if getattr(company, name, ""):
            lines.append(f"{name}: {getattr(company, name)}")
    if company.tags:
        lines.append("tags: " + ", ".join(str(t) for t in company.tags))
    for d in fields_mod.for_scope(store_defs(store), "company"):
        value = company.extra.get(d.key)
        if value not in (None, ""):
            lines.append(f"{d.key}: {d.display(value)}")
    todos = company.open_todos()
    if todos:
        lines.append("open tasks: " + "; ".join(
            t.text + (f" (due {t.due})" if t.due else "") for t in todos[:5]))
    else:
        lines.append("open tasks: none")
    return "\n".join(lines)


def store_defs(store) -> list:
    try:
        return fields_mod.load(store.root)
    except fields_mod.FieldError:
        return []


def allowed_stages(store, company) -> list[str]:
    """Where this company may move: configured, not where it is, and allowed by
    the stage rules."""
    return [s for s in store.stages.names
            if s != company.stage and store.move_allowed(company.stage, s)]


def schema(defs) -> dict:
    """The answer's shape. Every key is required (an empty string or list for
    "nothing"), as the structured-output mode of the CLIs wants."""
    keys = [VALUE] + [d.key for d in defs] + [NOTE]
    quote = {"type": "string",
             "description": "the exact sentence from the NEW interaction this comes from, "
                            "copied word for word"}
    return {
        "type": "object",
        "properties": {
            "next_step": {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                             "description": "one short action the user takes themselves; "
                                            "empty when none follows"},
                    "due": {"type": "string", "description": "YYYY-MM-DD"},
                    "quote": quote,
                },
                "required": ["text", "due", "quote"],
                "additionalProperties": False,
            },
            "stage": {
                "type": "object",
                "properties": {
                    "to": {"type": "string",
                           "description": "one of the allowed stages; empty for no move"},
                    "reason": {"type": "string", "description": "one sentence"},
                    "quote": quote,
                },
                "required": ["to", "reason", "quote"],
                "additionalProperties": False,
            },
            "facts": {
                "type": "array",
                "maxItems": MAX_FACTS,
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": keys},
                        "value": {"type": "string"},
                        "quote": quote,
                    },
                    "required": ["field", "value", "quote"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["next_step", "stage", "facts"],
        "additionalProperties": False,
    }


def prompt(store, company, it, today: date, defs) -> str:
    before = earlier(company, it)
    stages = allowed_stages(store, company)
    facts = [f"- {VALUE}: what they would pay per month, in EUR, a whole number"]
    facts += [f"- {d.key}: {d.description or d.help or d.label}"
              + (f" (one of: {', '.join(d.options)})" if d.options else "")
              + (f" ({d.type})" if d.type in ("number", "date") else "")
              for d in defs]
    facts.append(f"- {NOTE}: one fact worth remembering that fits no field above, "
                 "in one short sentence")
    parts = [
        "You read one conversation that was just logged in a sales CRM and suggest what "
        "follows from it, for a person to accept or dismiss. Nothing you write is saved "
        "until they accept it.",
        f"Today is {today.isoformat()}.",
        f"--- the company ---\n{_fields_block(store, company, defs)}\n--- end ---",
        f"--- the NEW interaction ---\n{_describe(company, it, BODY_LIMIT)}\n--- end ---",
    ]
    if before:
        parts.append("--- the interactions before it, newest first (context only) ---\n"
                     + "\n\n".join(_describe(company, i, EARLIER_LIMIT) for i in before)
                     + "\n--- end ---")
    parts += [
        "Suggest, each only when the NEW interaction supports it:",
        "1. next_step: one short action for the user (a call, a message, a meeting to "
        f"propose), at most {autopilot.NEXT_STEP_TEXT_LIMIT} characters, due from today to "
        f"{autopilot.NEXT_STEP_MAX_DAYS} days ahead as YYYY-MM-DD. Leave text empty when "
        "an open task above already covers it or nothing follows.",
        "2. stage: a move to one of these stages only: "
        + (", ".join(stages) if stages else "(none: leave it empty)")
        + ". Leave `to` empty unless the conversation clearly shows the deal moved.",
        f"3. facts: at most {MAX_FACTS}, each a value for one of:\n" + "\n".join(facts),
        "Every suggestion has a quote: the exact sentence of the NEW interaction it comes "
        "from, copied word for word. A suggestion you cannot quote from it, leave out. "
        "Never invent facts, numbers, names or dates. Answer in the interaction's language "
        "where you write text.",
    ]
    return "\n\n".join(parts) + "\n"


# ------------------------------------------------------------ the answer


def _where(it) -> str:
    noun = {"linkedin": "LinkedIn message", "meeting": "meeting", "call": "call",
            "email": "email", "note": "note"}.get(it.channel, it.channel or "interaction")
    return f"after the {noun}"


def _why(it, quote: str, reason: str = "") -> str:
    text = f"{_where(it)}: " + (f"{_norm(reason)} " if reason else "") + f"“{_bare_quote(quote)}”"
    return text[:autopilot.WHY_LIMIT]


def _strings(data, *keys) -> list[str] | None:
    if not isinstance(data, dict):
        return None
    values = [data.get(k) if data.get(k) is not None else "" for k in keys]
    return values if all(isinstance(v, str) for v in values) else None


def _fact(store, company, it, item, defs, now: datetime) -> tuple[Proposal | None, str]:
    """One fact as a proposal, or (None, why it was dropped)."""
    got = _strings(item, "field", "value", "quote")
    if got is None:
        return None, "a fact that is not text"
    key, value, quote = (_norm(v) for v in got)
    if not value:
        return None, f"{key or 'a fact'} without a value"
    if not found(quote, it):
        return None, f"{key}: its sentence is not in the interaction"
    if key == VALUE:
        digits = value.replace(",", "").replace(".", "").replace(" ", "")
        if not digits.isdigit():
            return None, f"{VALUE}: {value!r} is not a whole number"
        value = str(int(digits))
        if company.value_eur_month is not None and str(company.value_eur_month) == value:
            return None, f"{VALUE}: already {value}"
        label = VALUE_LABEL
    elif key == NOTE:
        label = ""
    else:
        d = next((d for d in defs if d.key == key), None)
        if d is None:
            return None, f"{key}: not a field it may fill"
        try:
            coerced = d.coerce(value)
        except ValueError as exc:
            return None, f"{key}: {exc}"
        if d.display(company.extra.get(key)) == d.display(coerced):
            return None, f"{key}: already {value}"
        value = d.display(coerced)
        label = d.label
    text = f"{label}: {value}" if label else value
    if len(text) > autopilot.NEXT_STEP_TEXT_LIMIT:
        return None, f"{key}: longer than {autopilot.NEXT_STEP_TEXT_LIMIT} characters"
    return Proposal(id="", kind=FACT if label else NOTE_KIND, company=company.slug,
                    made=fmt_datetime(now),
                    text=text, why=_why(it, quote), contact=it.contact, basis=it.id,
                    extra={"field": key, "label": label, "quote": _bare_quote(quote)}), ""


def clean(data, store, company, it, today: date, defs,
          now: datetime) -> tuple[list[Proposal], list[str]]:
    """(the proposals worth showing, why each other one was dropped). Raises
    routines.Rejected when the answer is not the JSON object asked for."""
    if not isinstance(data, dict):
        raise routines.Rejected("the AI returned no JSON object")
    made, dropped = [], []
    step = _strings(data.get("next_step"), "text", "due", "quote")
    if step is None and data.get("next_step") not in (None, ""):
        dropped.append("next step: not text")
    elif step is not None and _norm(step[0]):
        text, due, quote = step
        try:
            text, due, _, _ = autopilot.clean_next_step(
                {"next_step": text, "due": due, "why": "", "skip": ""}, today)
        except routines.Rejected as exc:
            dropped.append(f"next step: {exc}")
        else:
            if not found(quote, it):
                dropped.append("next step: its sentence is not in the interaction")
            else:
                made.append(Proposal(id="", kind=autopilot.NEXT_STEP, company=company.slug,
                                     made=fmt_datetime(now), text=text, due=due,
                                     why=_why(it, quote), contact=it.contact, basis=it.id,
                                     extra={"source": JOB_KIND,
                                            "quote": _bare_quote(quote)}))
    move = _strings(data.get("stage"), "to", "reason", "quote")
    if move is None and data.get("stage") not in (None, ""):
        dropped.append("stage: not text")
    elif move is not None and _norm(move[0]):
        to, reason, quote = (_norm(v) for v in move)
        to = store.stages.resolve(to) or to
        if to not in allowed_stages(store, company):
            dropped.append(f"stage: {to!r} is not a stage {company.name} may move to")
        elif not found(quote, it):
            dropped.append("stage: its sentence is not in the interaction")
        else:
            made.append(Proposal(id="", kind=STAGE_MOVE, company=company.slug,
                                 made=fmt_datetime(now), text=to,
                                 why=_why(it, quote, reason), contact=it.contact,
                                 basis=it.id, extra={"from": company.stage,
                                                     "quote": _bare_quote(quote)}))
    facts = data.get("facts")
    if facts not in (None, "") and not isinstance(facts, list):
        dropped.append("facts: not a list")
        facts = []
    seen = set()
    for item in (facts or [])[:MAX_FACTS]:
        proposal, why = _fact(store, company, it, item, defs, now)
        if proposal is None:
            dropped.append(why)
            continue
        slot = (proposal.extra["field"], proposal.text)
        if slot in seen:
            continue
        seen.add(slot)
        made.append(proposal)
    return made, dropped


def _slot(p: Proposal) -> tuple | None:
    """What a newer proposal replaces: the company's waiting next step, stage
    move, or value of the same field. Notes add up, so they replace nothing."""
    if p.kind in (autopilot.NEXT_STEP, STAGE_MOVE):
        return (p.company, p.kind)
    if p.kind == FACT:
        return (p.company, p.kind, p.extra.get("field"))
    return None


def keep(store, new: list[Proposal]) -> list[Proposal]:
    """Store the proposals; each replaces an older one waiting in the same slot
    (the newer conversation knows more)."""
    if not new:
        return []
    slots = {_slot(p) for p in new} - {None}
    for old in autopilot.proposals(store.root):
        if _slot(old) in slots:
            autopilot.remove_proposal(store, old.id)
    return autopilot.add_proposals(store, new)


def propose(store, config: dict, slug: str, interaction_id: str, enricher,
            now: datetime | None = None) -> dict:
    """The job: one AI call for one interaction, then the proposals that survive
    the checks. Returns {"proposed", "dropped"}; raises EnrichError,
    routines.RoutineError or routines.Rejected when it cannot."""
    now = now or store.now()
    company = store.get(slug)
    it = next((i for i in company.interactions if i.id == interaction_id), None) \
        if company is not None else None
    if it is None:
        return {"proposed": 0, "dropped": ["the interaction is gone"]}
    light = enricher.with_tier("light")
    if not light.available:
        raise routines.RoutineError(light.unavailable_reason())
    if routines.ai_problem(light):
        raise routines.RoutineError(routines.ai_problem(light))
    defs = enrich_fields(store.root)
    data = light.runner(prompt(store, company, it, now.date(), defs), schema(defs), tools="")
    made, dropped = clean(data, store, company, it, now.date(), defs, now)
    keep(store, made)
    for why in dropped:
        logger.info("after-contact %s/%s dropped: %s", slug, interaction_id, why)
    return {"proposed": len(made), "dropped": dropped}


# --------------------------------------------------------------- the hook


def worth_asking(it) -> bool:
    return len(_norm(it.body)) >= MIN_BODY


def pick(store, pairs) -> tuple[list, int]:
    """(the interactions to ask about, newest first, at most MAX_PER_RUN; how
    many more were left out). One per company and person: the newest of a
    thread logged at once has the rest as its context."""
    found_: dict[tuple, tuple] = {}
    for slug, interaction_id in pairs:
        company = store.get(slug)
        it = next((i for i in company.interactions if i.id == interaction_id), None) \
            if company is not None else None
        if it is None or not worth_asking(it):
            continue
        key = (slug, it.contact)
        best = found_.get(key)
        if best is None or (it.date or datetime.min, it.id) > (best[1].date or datetime.min,
                                                                best[1].id):
            found_[key] = (company, it)
    chosen = sorted(found_.values(), key=lambda pair: (pair[1].date or datetime.min,
                                                       pair[1].id), reverse=True)
    return chosen[:MAX_PER_RUN], max(0, len(chosen) - MAX_PER_RUN)


def _skipped(n: int) -> str:
    return (f"; {n} more skipped (at most {MAX_PER_RUN} per import)" if n else "")


def after_logged(store, config: dict | None, pairs, jobs=None, enricher=None) -> str:
    """The hook: called with (company slug, interaction id) for each interaction
    just created. With the switch off it returns "" at once: no enricher, no job,
    no AI call. With `jobs` (the web app's JobRunner) each one is a background
    job; without (the command line) they run here, one after the other.
    Returns one line for the summary the caller shows ("" when nothing).
    Never raises: the interaction is logged already, and that must stand."""
    if not enabled(config):
        return ""
    try:
        return _after_logged(store, config, list(pairs), jobs, enricher)
    except Exception as exc:  # noqa: BLE001 - logging must not fail on a suggestion
        logger.exception("after-contact suggestions failed")
        reason = f"{type(exc).__name__}: {exc}"
        _record(store, False, error=reason)
        return f"after-contact suggestions failed: {reason}"


def _after_logged(store, config: dict, pairs: list, jobs, enricher) -> str:
    chosen, more = pick(store, pairs)
    if not chosen:
        return f"after-contact suggestions: none asked{_skipped(more)}" if more else ""
    if enricher is None:
        enricher = routines.default_enricher(config)
    light = enricher.with_tier("light")
    problem = (light.unavailable_reason() if not light.available
               else routines.ai_problem(light))
    if problem:
        _record(store, False, error=problem)
        return f"after-contact suggestions skipped: {problem}"
    if jobs is not None:
        n = len(chosen)
        for company, it in chosen:   # one job: the badge says when it is ready
            _start(jobs, store, config, company, it, enricher, quiet=n > 1)
        if n == 1:
            return "suggestions on the way" + _skipped(more)
        return (f"after-contact suggestions on the way for {n} interactions"
                f"{_skipped(more)}")
    proposed, failed = 0, []
    for company, it in chosen:
        try:
            proposed += propose(store, config, company.slug, it.id, enricher)["proposed"]
        except (EnrichError, routines.RoutineError, routines.Rejected) as exc:
            failed.append(f"{company.name}: {exc}")
    summary = f"{proposed} suggestion{'' if proposed == 1 else 's'} for {len(chosen)} " \
              f"interaction{'' if len(chosen) == 1 else 's'}"
    _record(store, len(failed) < len(chosen), error="; ".join(failed), summary=summary)
    line = f"after-contact suggestions: {summary}{_skipped(more)}"
    return line + (f"; {len(failed)} failed: {failed[0]}" if failed else "")


def _job_view(request, job):
    """/jobs/<id> for a finished suggestion job: the record page, where the
    chips are (the badge's "ready" link goes here)."""
    if job.active:
        return None   # the job page, with its progress
    from .web import flashed  # web imports this module

    request.app.state.jobs.mark_seen(job)
    back = job.back.split("#", 1)[0] or "/"
    if job.state != "done":
        return flashed(back, f"No suggestions: {job.error}")
    n = int(job.result.get("proposed") or 0)
    if not n:
        return flashed(back, "No suggestions from that conversation")
    return flashed(back, f"{n} suggestion{'' if n == 1 else 's'} ready",
                   anchor="suggestions")


def _start(jobs, store, config, company, it, enricher, quiet: bool = False):
    """One background job. A quiet one (one of an import's) leaves the badge
    when it worked; a single one stays there as "ready" until opened."""
    from . import jobs as jobs_mod

    jobs.views.setdefault(JOB_KIND, _job_view)
    box: dict = {}

    def run(report):
        report(f"Reading the {it.channel or 'interaction'} with {_who(company, it)}")
        try:
            result = propose(store, config, company.slug, it.id, enricher)
        except Exception as exc:
            _record(store, False, error=f"{company.name}: {exc}")
            raise
        n = result["proposed"]
        _record(store, True, summary=f"{n} suggestion{'' if n == 1 else 's'} for "
                                     f"{company.name}")
        if quiet and "job" in box:   # done well: Today shows it, the badge need not
            box["job"].seen = True
        return result

    job = jobs.start(JOB_KIND, f"Suggestions after: {company.name}", run,
                     back=f"/companies/{company.slug}#suggestions",
                     params={"slug": company.slug, "interaction": it.id})
    box["job"] = job
    if quiet and job.state == jobs_mod.DONE:   # an inline executor ran it already
        jobs.mark_seen(job)
    return job


class Watch:
    """Which interactions a run created: the ids before, compared after. Made
    with the switch off it remembers nothing and `queue` returns ""."""

    def __init__(self, store, config: dict | None, active: bool = True):
        self.store, self.config = store, config
        self.before = self._ids() if active and enabled(config) else None

    def _ids(self) -> set[tuple[str, str]]:
        return {(c.slug, i.id) for c in self.store.companies.values()
                for i in c.interactions}

    def created(self) -> list[tuple[str, str]]:
        if self.before is None:
            return []
        return sorted(self._ids() - self.before)

    def queue(self, jobs=None, enricher=None) -> str:
        if self.before is None:
            return ""
        return after_logged(self.store, self.config, self.created(), jobs=jobs,
                            enricher=enricher)


# ------------------------------------------------------- accepting a kind


def _value_of(proposal: Proposal) -> str:
    """The value from a fact's text, "Label: value"; an edit that dropped the
    label leaves the whole text as the value."""
    label = str(proposal.extra.get("label") or "")
    text = _norm(proposal.text)
    return text[len(label) + 1:].strip() if label and text.startswith(label + ":") else text


def _approve_fact(store, proposal: Proposal) -> str:
    company = store.companies.get(proposal.company)
    name = company.name if company else proposal.company
    key = str(proposal.extra.get("field") or "")
    value = _value_of(proposal)
    if not value:
        raise ValidationError({"value": "write the value to save"})
    message = f"company: {proposal.company} {key} (after-contact suggestion)"
    if key == NOTE:
        if proposal.contact and company and proposal.contact in company.contacts:
            store.update_contact(proposal.company, proposal.contact, notes=value)
        else:
            store.update_company(proposal.company, notes=value)
        return f"Note saved for {name}"
    if key == VALUE:
        store.update_company(proposal.company, message=message, value_eur_month=value)
        return f"Monthly value saved for {name}"
    d = next((d for d in enrich_fields(store.root) if d.key == key), None)
    if d is None:
        raise ValidationError({key: f"{key} is no longer a field to fill (fields.toml)"})
    try:
        coerced = d.coerce(value)
    except ValueError as exc:
        raise ValidationError({key: str(exc)}) from None
    store.update_company(proposal.company, message=message, custom={key: coerced})
    return f"{d.label} saved for {name}"


def _approve_stage(store, proposal: Proposal) -> str:
    to = _norm(proposal.text)
    store.update_company(proposal.company, stage=to)
    company = store.companies.get(proposal.company)
    return f"{company.name if company else proposal.company} moved to {to}"


autopilot.register_kind(Kind(STAGE_MOVE, "Move to stage", _approve_stage, has_due=False))
autopilot.register_kind(Kind(FACT, "Fact", _approve_fact, has_due=False))
autopilot.register_kind(Kind(NOTE_KIND, "Note", _approve_fact, has_due=False))


# ------------------------------------------------------------- the pages


def chips(root: Path | str, store, slug: str, contact: str = "") -> list[dict]:
    """The proposals waiting for one company (one person: only theirs), for
    the chips on its page. Autopilot's own next steps show here too."""
    out = []
    for p in autopilot.proposals(root):
        kind = autopilot.KINDS.get(p.kind)
        if p.company != slug or kind is None or (contact and p.contact != contact):
            continue
        out.append({"id": p.id, "label": kind.label, "text": p.text, "why": p.why,
                    "due": p.due_date, "has_due": kind.has_due})
    return out


class PageHelper:
    """The Jinja global `after_contact`: what the chips and Settings show,
    read from the app's state on every call."""

    def __init__(self, app):
        self.app = app

    def chips(self, slug: str, contact: str = "") -> list[dict]:
        state = self.app.state
        return chips(state.root, state.store, slug, contact)

    def settings(self) -> dict:
        state = self.app.state
        return settings_form(state.config, state.root)
