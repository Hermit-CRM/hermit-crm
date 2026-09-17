"""Reports: pure functions over the Store for a period [start, end].

Every section is computed for the period and, where a delta makes sense, for
the previous period of equal length ending the day before `start`. Nothing is
written; the web page (/reports) and `hermitcrm report` render the same dict.

Every number in a section also records the rows behind it in a `Rows`
registry under a key such as "funnel.entered.stage:discovery"; the section
dicts carry those keys next to the numbers (`key`, `<field>_key`,
`status_keys`) and /reports/rows?key=... lists the rows.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from urllib.parse import urlencode

from .models import CLOSED_STAGES, Channel, Company, Contact, Interaction, Stage
from .store import DEFAULT_CONFIG, Store

PERIODS = ["7d", "30d", "90d", "quarter", "ytd", "custom"]
# Board order, left to right; the funnel adds won at the end.
PIPELINE_STAGES = ["prospect", "engaged", "discovery", "offer"]
FUNNEL_STAGES = PIPELINE_STAGES + ["won"]
STAGE_ORDER = [s.value for s in Stage]
CHANNELS = [c.value for c in Channel]  # every channel, including calendar "meeting"
DIRECTIONS = ["out", "in"]
UNKNOWN = "unknown"
OTHER = "other"  # a message status outside the configured outcomes


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous(self) -> "Period":
        """The period of equal length that ends the day before this one starts."""
        end = self.start - timedelta(days=1)
        return Period(end - timedelta(days=self.days - 1), end)

    def __contains__(self, d) -> bool:
        if d is None:
            return False
        if hasattr(d, "date"):  # datetime
            d = d.date()
        return self.start <= d <= self.end


def period_for(name: str, today: date, start: date | None = None,
               end: date | None = None) -> Period:
    """Resolve a named period ending today: 7d, 30d and 90d count today in;
    quarter and ytd run from the first day of the quarter / year. custom takes
    `start` and `end` (either may be missing: end defaults to today, start to
    30 days before end). Raises ValueError for an unknown name or start > end."""
    if name in ("7d", "30d", "90d"):
        return Period(today - timedelta(days=int(name[:-1]) - 1), today)
    if name == "quarter":
        return Period(date(today.year, 3 * ((today.month - 1) // 3) + 1, 1), today)
    if name == "ytd":
        return Period(date(today.year, 1, 1), today)
    if name == "custom":
        end = end or today
        start = start or end - timedelta(days=29)
        if start > end:
            raise ValueError("from must be on or before to")
        return Period(start, end)
    raise ValueError(f"unknown period {name!r} (allowed: {', '.join(PERIODS)})")


def period_query(period: str, start: str = "", end: str = "") -> str:
    """The query string that reproduces a report page's period: `period=30d`,
    or `period=custom&from=...&to=...` (empty from/to left out)."""
    params = {"period": period}
    if period == "custom":
        if start:
            params["from"] = start
        if end:
            params["to"] = end
    return urlencode(params)


def delta(current, previous) -> str:
    """+n / −n / ±0 between two numbers (a real minus sign)."""
    diff = (current or 0) - (previous or 0)
    if diff > 0:
        return f"+{diff:,}"
    if diff < 0:
        return f"−{-diff:,}"
    return "±0"


def rate(part: int, whole: int) -> float | None:
    """part / whole, or None when whole is 0 (shown as "-")."""
    return part / whole if whole else None


def normalise_text(text: str) -> str:
    return " ".join((text or "").split()).lower()


def _value(companies) -> int:
    return sum(c.value_eur_month or 0 for c in companies)


# ------------------------------------------------------------------------- rows


@dataclass(frozen=True)
class Row:
    """One record behind a report number: a company, a contact or an
    interaction, plus the columns the rows page shows for it."""
    kind: str                  # company | contact | interaction
    slug: str                  # company slug
    company: str               # company name
    label: str                 # link text of the record itself
    cslug: str = ""            # contact slug (contact rows, interactions with a known contact)
    contact: str = ""          # contact name (or the slug an interaction refers to)
    id: str = ""               # interaction id
    date: date | datetime | None = None
    channel: str = ""          # "email out"
    stage: str = ""
    status: str = ""           # message status, lost reason, ...
    value: int | None = None   # value_eur_month
    note: str = ""             # next step, days silent, ...

    @property
    def url(self) -> str:
        if self.kind == "interaction":
            return f"/companies/{self.slug}/interactions/{self.id}/edit"
        if self.kind == "contact":
            return f"/companies/{self.slug}/contacts/{self.cslug}"
        return f"/companies/{self.slug}"

    @property
    def when(self) -> str:
        if self.date is None:
            return ""
        if isinstance(self.date, datetime):
            return f"{self.date:%Y-%m-%d %H:%M}"
        return f"{self.date:%Y-%m-%d}"


ROW_COLUMNS = ["company", "contact", "interaction", "date", "channel", "stage",
               "status", "value", "note"]


def row_columns(rows: list[Row]) -> list[str]:
    """The ROW_COLUMNS that at least one row fills (company always)."""
    present = {"company"}
    for r in rows:
        if r.kind == "contact" or r.contact:
            present.add("contact")
        if r.kind == "interaction":
            present.add("interaction")
        if r.date is not None:
            present.add("date")
        for col in ("channel", "stage", "status", "note"):
            if getattr(r, col):
                present.add(col)
        if r.value is not None:
            present.add("value")
    return [c for c in ROW_COLUMNS if c in present]


def _sort_key(r: Row):
    d = r.date
    if isinstance(d, date) and not isinstance(d, datetime):
        d = datetime.combine(d, datetime.min.time())
    return (d or datetime.min, r.company, r.label)


class Rows:
    """The rows behind every number of one report build, by key. `put`
    replaces; keys are stable for the same store and period."""

    def __init__(self):
        self._rows: dict[str, list[Row]] = {}
        self._labels: dict[str, str] = {}

    def put(self, key: str, label: str, rows) -> str:
        self._rows[key] = sorted(rows, key=_sort_key, reverse=True)
        self._labels[key] = label
        return key

    def get(self, key: str) -> list[Row] | None:
        return self._rows.get(key)

    def label(self, key: str) -> str:
        return self._labels.get(key, key)

    def keys(self) -> list[str]:
        return list(self._rows)

    def __contains__(self, key) -> bool:
        return key in self._rows

    def __len__(self) -> int:
        return len(self._rows)


def company_row(c: Company, when=None, stage: str | None = None, status: str = "",
                note: str = "") -> Row:
    return Row("company", c.slug, c.name, c.name, date=when,
               stage=c.stage if stage is None else stage, status=status,
               value=c.value_eur_month, note=note)


def contact_row(c: Company, ct: Contact) -> Row:
    return Row("contact", c.slug, c.name, ct.name, cslug=ct.slug, contact=ct.name,
               date=ct.created, stage=c.stage)


def interaction_row(c: Company, i: Interaction, status: str = "") -> Row:
    contact = c.contacts.get(i.contact) if i.contact else None
    return Row("interaction", c.slug, c.name, i.subject or i.id,
               cslug=contact.slug if contact else "",
               contact=contact.name if contact else (i.contact or ""),
               id=i.id, date=i.date, channel=f"{i.channel} {i.direction}",
               stage=c.stage, status=status)


PREVIOUS = " (previous period)"


def _rows(rows: Rows | None) -> Rows:
    return rows if rows is not None else Rows()


# --------------------------------------------------------------------- activity


def activity(store: Store, period: Period, rows: Rows | None = None) -> dict:
    """Interactions per ISO week x channel x direction (every week overlapping
    the period, empty ones included), plus totals with deltas: interactions,
    companies touched (at least one interaction), new companies (by `created`)
    and new contacts (by the contact's `created`)."""
    rows = _rows(rows)

    def totals(p: Period, suffix: str, when: str) -> tuple[dict, dict]:
        its = [(c, i) for c in store.companies.values() for i in c.interactions
               if i.date in p]
        touched = Counter(c.slug for c, _ in its)
        new_companies = [c for c in store.companies.values() if c.created in p]
        new_contacts = [(c, ct) for c in store.companies.values()
                        for ct in c.contacts.values() if ct.created in p]
        row_keys = {
            "interactions": rows.put(
                f"activity.interactions{suffix}", f"Interactions{when}",
                [interaction_row(c, i) for c, i in its]),
            "companies_touched": rows.put(
                f"activity.companies_touched{suffix}", f"Companies touched{when}",
                [company_row(store.companies[slug], note=f"{n} interactions")
                 for slug, n in touched.items()]),
            "new_companies": rows.put(
                f"activity.new_companies{suffix}", f"New companies{when}",
                [company_row(c, when=c.created) for c in new_companies]),
            "new_contacts": rows.put(
                f"activity.new_contacts{suffix}", f"New contacts{when}",
                [contact_row(c, ct) for c, ct in new_contacts]),
        }
        counts = {
            "interactions": len(its),
            "companies_touched": len(touched),
            "new_companies": len(new_companies),
            "new_contacts": len(new_contacts),
        }
        return counts, row_keys

    weeks: dict[str, dict[str, list[Row]]] = {}
    day = period.start - timedelta(days=period.start.weekday())
    while day <= period.end:
        year, week, _ = day.isocalendar()
        weeks[f"{year}-W{week:02d}"] = {}
        day += timedelta(days=7)
    for c in store.companies.values():
        for i in c.interactions:
            if i.date in period:
                year, week, _ = i.date.isocalendar()
                col = f"{i.channel} {i.direction}"
                weeks[f"{year}-W{week:02d}"].setdefault(col, []).append(interaction_row(c, i))
    columns = [f"{ch} {d}" for ch in CHANNELS for d in DIRECTIONS]
    week_rows = []
    for w, cells in weeks.items():
        row_keys = {}
        for col in columns:
            ch, d = col.split()
            row_keys[col] = rows.put(f"activity.interactions.week:{w}.channel:{ch}.dir:{d}",
                                     f"Interactions in {w}, {col}", cells.get(col, []))
        row_keys["total"] = rows.put(f"activity.interactions.week:{w}", f"Interactions in {w}",
                                     [r for col in columns for r in cells.get(col, [])])
        week_rows.append({"week": w, **{col: len(cells.get(col, [])) for col in columns},
                          "total": sum(len(v) for v in cells.values()),
                          "row_keys": row_keys})
    cur, row_keys = totals(period, "", "")
    prev, previous_row_keys = totals(period.previous(), ".previous", PREVIOUS)
    return {"columns": columns, "weeks": week_rows, "totals": cur, "previous": prev,
            "row_keys": row_keys, "previous_row_keys": previous_row_keys,
            "max_week": max((r["total"] for r in week_rows), default=0)}


# ----------------------------------------------------------------------- funnel


def _entries_by_stage(c: Company, until: date) -> dict[str, list[date]]:
    out: dict[str, list[date]] = {}
    for e in c.stage_entries():
        if e.date <= until:
            out.setdefault(e.to_stage, []).append(e.date)
    return out


def funnel(store: Store, period: Period, rows: Rows | None = None) -> dict:
    """Stage flow from the stage history (Company.stage_entries, so companies
    without a recorded history still count via `created` and `stage_changed`).

    - entered: per stage, how many transitions into it fall in the period
      (and in the previous period, for the delta).
    - conversion: for consecutive funnel stages X -> Y (prospect, engaged,
      discovery, offer, won): of the companies that reached X or any later
      funnel stage on or before the period end, the share that reached Y or
      later. Reaching a later stage counts, so skipping a stage is no leak.
    - median_days: per stage, the median of Company.stage_durations(end) over
      the companies that visited it (the current stint runs to the period end).
    - pipeline: today's open stages with count and summed value_eur_month.
    """
    rows = _rows(rows)

    def entered(p: Period) -> dict[str, list[Row]]:
        out: dict[str, list[Row]] = {s: [] for s in STAGE_ORDER}
        for c in store.companies.values():
            for e in c.stage_entries():
                if e.date in p:
                    out.setdefault(e.to_stage, []).append(company_row(
                        c, when=e.date, stage=e.to_stage,
                        note=f"from {e.from_stage or 'start'}"))
        return out

    cur, prev = entered(period), entered(period.previous())
    entered_rows = [{
        "stage": s, "count": len(cur[s]), "previous": len(prev[s]),
        "key": rows.put(f"funnel.entered.stage:{s}", f"Entered {s}", cur[s]),
        "previous_key": rows.put(f"funnel.entered.stage:{s}.previous",
                                 f"Entered {s}{PREVIOUS}", prev[s]),
    } for s in STAGE_ORDER]

    reached: dict[str, list[Company]] = {s: [] for s in FUNNEL_STAGES}
    for c in store.companies.values():
        stages = _entries_by_stage(c, period.end)
        furthest = max((FUNNEL_STAGES.index(s) for s in stages if s in FUNNEL_STAGES),
                       default=-1)
        for s in FUNNEL_STAGES[:furthest + 1]:
            reached[s].append(c)
    reached_keys = {s: rows.put(f"funnel.reached.stage:{s}",
                                f"Reached {s} or later by {period.end:%Y-%m-%d}",
                                [company_row(c) for c in reached[s]])
                    for s in FUNNEL_STAGES}
    conversion = []
    for x, y in zip(FUNNEL_STAGES, FUNNEL_STAGES[1:]):
        base, hit = len(reached[x]), len(reached[y])
        conversion.append({"from": x, "to": y, "base": base, "reached": hit,
                           "rate": rate(hit, base),
                           "base_key": reached_keys[x], "reached_key": reached_keys[y]})

    spans: dict[str, list[tuple[Company, int]]] = {}
    for c in store.companies.values():
        for stage, days in c.stage_durations(period.end).items():
            spans.setdefault(stage, []).append((c, days))
    median_days = [{
        "stage": s, "companies": len(spans[s]),
        "median": median(days for _, days in spans[s]),
        "key": rows.put(f"funnel.visited.stage:{s}", f"Visited {s} (days in stage)",
                        [company_row(c, note=f"{days} days") for c, days in spans[s]]),
    } for s in STAGE_ORDER if spans.get(s)]

    pipeline = []
    for s in PIPELINE_STAGES:
        members = [c for c in store.companies.values() if c.stage == s]
        pipeline.append({"stage": s, "count": len(members), "value": _value(members),
                         "key": rows.put(f"funnel.pipeline.stage:{s}", f"Pipeline: {s}",
                                         [company_row(c) for c in members])})
    return {"entered": entered_rows, "conversion": conversion, "median_days": median_days,
            "pipeline": pipeline, "max_pipeline": max(r["count"] for r in pipeline)}


# --------------------------------------------------------------------- outcomes


def closed_date(c: Company) -> date | None:
    """When a closed company closed: the last transition into a closed stage,
    falling back to `stage_changed` for companies without history."""
    return c.closed_on or c.stage_changed


def outcomes(store: Store, period: Period, rows: Rows | None = None) -> dict:
    """Companies whose current stage is won, lost or disqualified and whose
    closed_date falls in the period: counts and summed value_eur_month, with
    the previous period. win_rate = won / (won + lost), None without either.
    lost_reasons: the 10 most common reasons of those lost in the period,
    lowercased and stripped (empty reasons skipped)."""
    rows = _rows(rows)

    def closed(p: Period) -> dict[str, list[Company]]:
        return {s: [c for c in store.companies.values()
                    if c.stage == s and closed_date(c) in p] for s in CLOSED_STAGES}

    def closed_rows(companies: list[Company]) -> list[Row]:
        return [company_row(c, when=closed_date(c), status=c.lost_reason) for c in companies]

    cur, prev = closed(period), closed(period.previous())
    out_rows = [{
        "stage": s, "count": len(cur[s]), "value": _value(cur[s]),
        "previous": len(prev[s]), "previous_value": _value(prev[s]),
        "key": rows.put(f"outcomes.{s}", f"Closed {s}", closed_rows(cur[s])),
        "previous_key": rows.put(f"outcomes.{s}.previous", f"Closed {s}{PREVIOUS}",
                                 closed_rows(prev[s])),
    } for s in CLOSED_STAGES]
    by_reason: dict[str, list[Company]] = {}
    for c in cur["lost"]:
        if c.lost_reason.strip():
            by_reason.setdefault(" ".join(c.lost_reason.split()).lower(), []).append(c)
    reasons = sorted(by_reason.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:10]
    won, lost = len(cur["won"]), len(cur["lost"])
    return {
        "rows": out_rows,
        "win_rate": rate(won, won + lost),
        "previous_win_rate": rate(len(prev["won"]), len(prev["won"]) + len(prev["lost"])),
        "lost_reasons": [{"reason": r, "count": len(cs),
                          "key": rows.put(f"outcomes.lost_reason:{r}", f"Lost: {r}",
                                          closed_rows(cs))}
                         for r, cs in reasons],
    }


# --------------------------------------------------------------------- messages


def resolve_outcomes(store: Store, outcomes=None) -> list[str]:
    """The configured outcome values: the argument, else the store's config
    (when it carries one), else the default. Always at least one value."""
    if not outcomes:
        config = getattr(store, "config", None) or {}
        outcomes = config.get("outcomes") if isinstance(config, dict) else None
    return [str(o) for o in (outcomes or DEFAULT_CONFIG["outcomes"])]


def _status_row(rows: Rows, prefix: str, label: str, key: str, items,
                outcomes: list[str]) -> dict:
    """items: (company, interaction, status) triples. `counts` has one entry
    per configured outcome plus "unknown"; any other status only counts in
    `sent` and `other` (legacy or free-text outcomes), so the rate is the first
    outcome's share of the messages with a configured outcome."""
    statuses = outcomes + [UNKNOWN]
    counts = Counter(s for _, _, s in items)
    other = [t for t in items if t[2] not in statuses]
    status_keys = {s: rows.put(f"{prefix}.status.{s}", f"{label}: {s}",
                               [interaction_row(c, i, st) for c, i, st in items if st == s])
                   for s in statuses}
    status_keys[OTHER] = rows.put(f"{prefix}.status.{OTHER}",
                                  f"{label}: outcome outside the configured list",
                                  [interaction_row(c, i, st) for c, i, st in other])
    return {
        "key": key, "sent": len(items),
        "counts": {s: counts[s] for s in statuses},
        "other": len(other),
        "other_statuses": sorted({t[2] for t in other}),
        "rate": rate(counts[outcomes[0]], sum(counts[o] for o in outcomes)),
        "sent_key": rows.put(f"{prefix}.sent", f"{label}: sent",
                             [interaction_row(c, i, st) for c, i, st in items]),
        "status_keys": status_keys,
    }


def messages(store: Store, period: Period, today: date, window_days: int = 14,
             outcomes=None, rows: Rows | None = None) -> dict:
    """Messages (outbound interactions with a body) sent in the period, with
    their status from Company.message_status as of `today`, counted per
    configured outcome value (`outcomes`, see resolve_outcomes) plus unknown.
    rate = first outcome / messages with any configured outcome; unknown is
    left out. Broken down by language (Company.language) and by channel.
    reused: the 5 texts (normalised: case and whitespace folded) sent more
    than once in the period, most used first."""
    rows = _rows(rows)
    outcomes = resolve_outcomes(store, outcomes)

    def sent(p: Period):
        return [(c, i) for c in store.companies.values() for i in c.interactions
                if i.is_message and i.date in p]

    items = [(c, i, c.message_status(i, today, window_days, outcomes))
             for c, i in sent(period)]
    previous = sent(period.previous())
    by_language: dict[str, list] = {}
    by_channel: dict[str, list] = {}
    by_text: dict[str, list] = {}
    for c, i, status in items:
        by_language.setdefault(c.language, []).append((c, i, status))
        by_channel.setdefault(i.channel, []).append((c, i, status))
        by_text.setdefault(normalise_text(i.body), []).append((c, i, status))
    reused = sorted(((t, s) for t, s in by_text.items() if len(s) > 1),
                    key=lambda ts: (-len(ts[1]), ts[0]))[:5]
    return {
        "total": _status_row(rows, "messages", "Messages", "all", items, outcomes),
        "previous_sent": len(previous),
        "previous_sent_key": rows.put("messages.sent.previous", f"Messages sent{PREVIOUS}",
                                      [interaction_row(c, i) for c, i in previous]),
        "by_language": [_status_row(rows, f"messages.language:{k}", f"Messages in {k}",
                                    k, v, outcomes)
                        for k, v in sorted(by_language.items())],
        "by_channel": [_status_row(rows, f"messages.channel:{k}", f"Messages by {k}",
                                   k, v, outcomes)
                       for k, v in sorted(by_channel.items())],
        "reused": [{**_status_row(rows, f"messages.reused:{n}", f"Reused text #{n}",
                                  t, s, outcomes),
                    "uses": len(s), "preview": t[:80] + ("..." if len(t) > 80 else "")}
                   for n, (t, s) in enumerate(reused, 1)],
        "window": window_days,
        "outcomes": outcomes,
        "statuses": outcomes + [UNKNOWN],
    }


# ---------------------------------------------------------------------- sources


def sources(store: Store, period: Period, rows: Rows | None = None) -> dict:
    """Per `source`: companies created in the period and companies won in the
    period (closed_date), sorted by created then wins; empty sources omitted."""
    rows = _rows(rows)
    created: dict[str, list[Company]] = {}
    wins: dict[str, list[Company]] = {}
    for c in store.companies.values():
        if c.created in period:
            created.setdefault(c.source, []).append(c)
        if c.stage == "won" and closed_date(c) in period:
            wins.setdefault(c.source, []).append(c)
    keys = sorted(set(created) | set(wins),
                  key=lambda k: (-len(created.get(k, [])), -len(wins.get(k, [])), k))
    return {"rows": [{
        "source": k, "created": len(created.get(k, [])), "won": len(wins.get(k, [])),
        "created_key": rows.put(f"sources.source:{k}.created", f"Created from {k}",
                                [company_row(c, when=c.created) for c in created.get(k, [])]),
        "won_key": rows.put(f"sources.source:{k}.won", f"Won from {k}",
                            [company_row(c, when=closed_date(c)) for c in wins.get(k, [])]),
    } for k in keys],
        "max_created": max((len(v) for v in created.values()), default=0)}


# ---------------------------------------------------------------------- hygiene


def hygiene(store: Store, today: date, rows: Rows | None = None) -> dict:
    """Today's loose ends, not tied to the period: overdue next steps on
    companies that are not closed (as in PIPELINE.md), active accounts silent
    for store.silent_days or more, and contacts without an email at companies
    that are not closed."""
    rows = _rows(rows)
    companies = store.all()
    overdue = sorted((c for c in companies if not c.is_closed and c.next_step_overdue(today)),
                     key=lambda c: (c.next_step_due, c.slug))
    silent = sorted((c for c in companies
                     if c.is_active and c.silent_days(today) >= store.silent_days),
                    key=lambda c: (-c.silent_days(today), c.slug))
    no_email = [(c, ct) for c in companies if not c.is_closed
                for ct in sorted(c.contacts.values(), key=lambda ct: ct.slug) if not ct.email]
    return {
        "overdue": [{"slug": c.slug, "name": c.name, "stage": c.stage,
                     "due": c.next_step_due, "next_step": c.next_step} for c in overdue],
        "silent": [{"slug": c.slug, "name": c.name, "stage": c.stage,
                    "days": c.silent_days(today)} for c in silent],
        "no_email": [{"slug": c.slug, "company": c.name, "contact": ct.slug,
                      "name": ct.name} for c, ct in no_email],
        "silent_days": store.silent_days,
        "row_keys": {
            "overdue": rows.put("hygiene.overdue", "Overdue next steps",
                                [company_row(c, when=c.next_step_due, note=c.next_step)
                                 for c in overdue]),
            "silent": rows.put("hygiene.silent", f"Silent {store.silent_days}+ days",
                               [company_row(c, note=f"{c.silent_days(today)} days silent")
                                for c in silent]),
            "no_email": rows.put("hygiene.no_email", "Contacts without email",
                                 [contact_row(c, ct) for c, ct in no_email]),
        },
    }


# ------------------------------------------------------------------------ build


def build(store: Store, period: Period, today: date | None = None,
          window_days: int = 14, outcomes=None) -> dict:
    """Every section for one period; `today` (default store.today()) drives
    message status and hygiene, `outcomes` the message status columns (see
    resolve_outcomes). `rows` is the Rows registry behind every number."""
    today = today or store.today()
    rows = Rows()
    return {
        "period": period,
        "previous": period.previous(),
        "activity": activity(store, period, rows),
        "funnel": funnel(store, period, rows),
        "outcomes": outcomes_section(store, period, rows),
        "messages": messages(store, period, today, window_days, outcomes, rows),
        "sources": sources(store, period, rows),
        "hygiene": hygiene(store, today, rows),
        "rows": rows,
    }


outcomes_section = outcomes  # `outcomes` is also build()'s parameter name


# --------------------------------------------------------------------- markdown


def _pct(r: float | None) -> str:
    return "-" if r is None else f"{r:.0%}"


def _table(headers: list[str], rows: list[list], md: bool) -> str:
    cells = [[str(h) for h in headers]] + [[str(v) for v in row] for row in rows]
    if not rows:
        cells.append(["-"] + [""] * (len(headers) - 1))
    if md:
        lines = ["| " + " | ".join(cells[0]) + " |",
                 "|" + "|".join("---" for _ in headers) + "|"]
        lines += ["| " + " | ".join(r) + " |" for r in cells[1:]]
        return "\n".join(lines)
    widths = [max(len(r[n]) for r in cells) for n in range(len(headers))]
    return "\n".join("  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip()
                     for r in cells)


def render_text(report: dict, md: bool = False) -> str:
    """The report as text: aligned columns by default, Markdown tables with md."""
    p, prev = report["period"], report["previous"]
    h = "## " if md else ""
    out = [f"{'# ' if md else ''}Report {p.start:%Y-%m-%d} to {p.end:%Y-%m-%d} "
           f"({p.days}d; previous {prev.start:%Y-%m-%d} to {prev.end:%Y-%m-%d})"]

    a = report["activity"]
    out.append(f"{h}Activity")
    labels = {"interactions": "interactions", "companies_touched": "companies touched",
              "new_companies": "new companies", "new_contacts": "new contacts"}
    out.append(_table(["metric", "period", "previous", "delta"],
                      [[labels[k], v, a["previous"][k], delta(v, a["previous"][k])]
                       for k, v in a["totals"].items()], md))
    out.append(_table(["week"] + a["columns"] + ["total"],
                      [[r["week"]] + [r[c] for c in a["columns"]] + [r["total"]]
                       for r in a["weeks"]], md))

    f = report["funnel"]
    out.append(f"{h}Funnel")
    out.append(_table(["stage", "entered", "previous", "delta"],
                      [[r["stage"], r["count"], r["previous"], delta(r["count"], r["previous"])]
                       for r in f["entered"]], md))
    out.append(_table(["from", "to", "reached from", "reached to", "conversion"],
                      [[r["from"], r["to"], r["base"], r["reached"], _pct(r["rate"])]
                       for r in f["conversion"]], md))
    out.append(_table(["stage", "companies", "median days"],
                      [[r["stage"], r["companies"], f"{r['median']:g}"]
                       for r in f["median_days"]], md))
    out.append(_table(["pipeline stage", "companies", "EUR/month"],
                      [[r["stage"], r["count"], f"{r['value']:,}"] for r in f["pipeline"]], md))

    o = report["outcomes"]
    out.append(f"{h}Outcomes")
    out.append(_table(["stage", "count", "EUR/month", "previous", "delta"],
                      [[r["stage"], r["count"], f"{r['value']:,}", r["previous"],
                        delta(r["count"], r["previous"])] for r in o["rows"]], md))
    out.append(f"win rate: {_pct(o['win_rate'])} (previous {_pct(o['previous_win_rate'])})")
    out.append(_table(["lost reason", "count"],
                      [[r["reason"], r["count"]] for r in o["lost_reasons"]], md))

    m = report["messages"]
    t = m["total"]
    statuses, positive = m["statuses"], m["outcomes"][0]
    out.append(f"{h}Messages")
    out.append(f"sent: {t['sent']} (previous {m['previous_sent']}, "
               f"{delta(t['sent'], m['previous_sent'])}) | "
               + " | ".join(f"{s} {t['counts'][s]}" for s in statuses)
               + f" | {positive} rate {_pct(t['rate'])} (window {m['window']}d)")
    status_headers = ["sent"] + statuses + ["rate"]

    def status_cells(r):
        return [r["sent"]] + [r["counts"][s] for s in statuses] + [_pct(r["rate"])]

    out.append(_table(["language"] + status_headers,
                      [[r["key"]] + status_cells(r) for r in m["by_language"]], md))
    out.append(_table(["channel"] + status_headers,
                      [[r["key"]] + status_cells(r) for r in m["by_channel"]], md))
    out.append(_table(["reused text", "uses", f"{positive} rate"],
                      [[r["preview"].replace("|", "/"), r["uses"], _pct(r["rate"])]
                       for r in m["reused"]], md))

    s = report["sources"]
    out.append(f"{h}Sources")
    out.append(_table(["source", "created", "won"],
                      [[r["source"], r["created"], r["won"]] for r in s["rows"]], md))

    hy = report["hygiene"]
    out.append(f"{h}Hygiene")
    out.append(_table([f"overdue next steps ({len(hy['overdue'])})", "stage", "due", "next step"],
                      [[r["slug"], r["stage"], f"{r['due']:%Y-%m-%d}", r["next_step"]]
                       for r in hy["overdue"]], md))
    out.append(_table([f"silent {hy['silent_days']}+ days ({len(hy['silent'])})", "stage", "days"],
                      [[r["slug"], r["stage"], r["days"]] for r in hy["silent"]], md))
    out.append(_table([f"contacts without email ({len(hy['no_email'])})", "company"],
                      [[r["name"], r["slug"]] for r in hy["no_email"]], md))
    return "\n\n".join(out) + "\n"
