"""Reports: pure functions over the Store for a period [start, end].

Every section is computed for the period and, where a delta makes sense, for
the previous period of equal length ending the day before `start`. Nothing is
written; the web page (/reports) and `owncrm report` render the same dict.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from .models import CLOSED_STAGES, Channel, Company, Stage
from .store import Store

PERIODS = ["7d", "30d", "90d", "quarter", "ytd", "custom"]
# Board order, left to right; the funnel adds won at the end.
PIPELINE_STAGES = ["prospect", "reached-out", "discovery", "offer"]
FUNNEL_STAGES = PIPELINE_STAGES + ["won"]
STAGE_ORDER = [s.value for s in Stage]
CHANNELS = [c.value for c in Channel]  # every channel, including calendar "meeting"
DIRECTIONS = ["out", "in"]


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


# --------------------------------------------------------------------- activity


def activity(store: Store, period: Period) -> dict:
    """Interactions per ISO week x channel x direction (every week overlapping
    the period, empty ones included), plus totals with deltas: interactions,
    companies touched (at least one interaction), new companies (by `created`)
    and new contacts (by the contact's `created`)."""
    def totals(p: Period) -> dict:
        its = [(c, i) for c in store.companies.values() for i in c.interactions
               if i.date in p]
        return {
            "interactions": len(its),
            "companies_touched": len({c.slug for c, _ in its}),
            "new_companies": sum(1 for c in store.companies.values() if c.created in p),
            "new_contacts": sum(1 for c in store.companies.values()
                                for ct in c.contacts.values() if ct.created in p),
        }

    weeks: dict[str, Counter] = {}
    day = period.start - timedelta(days=period.start.weekday())
    while day <= period.end:
        year, week, _ = day.isocalendar()
        weeks[f"{year}-W{week:02d}"] = Counter()
        day += timedelta(days=7)
    for c in store.companies.values():
        for i in c.interactions:
            if i.date in period:
                year, week, _ = i.date.isocalendar()
                weeks[f"{year}-W{week:02d}"][f"{i.channel} {i.direction}"] += 1
    columns = [f"{ch} {d}" for ch in CHANNELS for d in DIRECTIONS]
    rows = [{"week": w, **{col: counts[col] for col in columns},
             "total": sum(counts.values())} for w, counts in weeks.items()]
    cur, prev = totals(period), totals(period.previous())
    return {"columns": columns, "weeks": rows, "totals": cur, "previous": prev,
            "max_week": max((r["total"] for r in rows), default=0)}


# ----------------------------------------------------------------------- funnel


def _entries_by_stage(c: Company, until: date) -> dict[str, list[date]]:
    out: dict[str, list[date]] = {}
    for e in c.stage_entries():
        if e.date <= until:
            out.setdefault(e.to_stage, []).append(e.date)
    return out


def funnel(store: Store, period: Period) -> dict:
    """Stage flow from the stage history (Company.stage_entries, so companies
    without a recorded history still count via `created` and `stage_changed`).

    - entered: per stage, how many transitions into it fall in the period
      (and in the previous period, for the delta).
    - conversion: for consecutive funnel stages X -> Y (prospect, reached-out,
      discovery, offer, won): of the companies that reached X or any later
      funnel stage on or before the period end, the share that reached Y or
      later. Reaching a later stage counts, so skipping a stage is no leak.
    - median_days: per stage, the median of Company.stage_durations(end) over
      the companies that visited it (the current stint runs to the period end).
    - pipeline: today's open stages with count and summed value_eur_month.
    """
    def entered(p: Period) -> Counter:
        counts = Counter()
        for c in store.companies.values():
            for e in c.stage_entries():
                if e.date in p:
                    counts[e.to_stage] += 1
        return counts

    cur, prev = entered(period), entered(period.previous())
    entered_rows = [{"stage": s, "count": cur[s], "previous": prev[s]}
                    for s in STAGE_ORDER]

    reached: dict[str, set[str]] = {s: set() for s in FUNNEL_STAGES}
    for c in store.companies.values():
        stages = _entries_by_stage(c, period.end)
        furthest = max((FUNNEL_STAGES.index(s) for s in stages if s in FUNNEL_STAGES),
                       default=-1)
        for s in FUNNEL_STAGES[:furthest + 1]:
            reached[s].add(c.slug)
    conversion = []
    for x, y in zip(FUNNEL_STAGES, FUNNEL_STAGES[1:]):
        base, hit = len(reached[x]), len(reached[y])
        conversion.append({"from": x, "to": y, "base": base, "reached": hit,
                           "rate": rate(hit, base)})

    spans: dict[str, list[int]] = {}
    for c in store.companies.values():
        for stage, days in c.stage_durations(period.end).items():
            spans.setdefault(stage, []).append(days)
    median_days = [{"stage": s, "companies": len(spans[s]), "median": median(spans[s])}
                   for s in STAGE_ORDER if spans.get(s)]

    pipeline = []
    for s in PIPELINE_STAGES:
        members = [c for c in store.companies.values() if c.stage == s]
        pipeline.append({"stage": s, "count": len(members), "value": _value(members)})
    return {"entered": entered_rows, "conversion": conversion, "median_days": median_days,
            "pipeline": pipeline, "max_pipeline": max(r["count"] for r in pipeline)}


# --------------------------------------------------------------------- outcomes


def closed_date(c: Company) -> date | None:
    """When a closed company closed: the last transition into a closed stage,
    falling back to `stage_changed` for companies without history."""
    return c.closed_on or c.stage_changed


def outcomes(store: Store, period: Period) -> dict:
    """Companies whose current stage is won, lost or disqualified and whose
    closed_date falls in the period: counts and summed value_eur_month, with
    the previous period. win_rate = won / (won + lost), None without either.
    lost_reasons: the 10 most common reasons of those lost in the period,
    lowercased and stripped (empty reasons skipped)."""
    def closed(p: Period) -> dict[str, list[Company]]:
        return {s: [c for c in store.companies.values()
                    if c.stage == s and closed_date(c) in p] for s in CLOSED_STAGES}

    cur, prev = closed(period), closed(period.previous())
    rows = [{"stage": s, "count": len(cur[s]), "value": _value(cur[s]),
             "previous": len(prev[s]), "previous_value": _value(prev[s])}
            for s in CLOSED_STAGES]
    reasons = Counter(" ".join(c.lost_reason.split()).lower()
                      for c in cur["lost"] if c.lost_reason.strip())
    won, lost = len(cur["won"]), len(cur["lost"])
    return {
        "rows": rows,
        "win_rate": rate(won, won + lost),
        "previous_win_rate": rate(len(prev["won"]), len(prev["won"]) + len(prev["lost"])),
        "lost_reasons": [{"reason": r, "count": n}
                         for r, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:10]],
    }


# --------------------------------------------------------------------- messages


def _status_row(key: str, statuses: list[str]) -> dict:
    counts = Counter(statuses)
    return {"key": key, "sent": len(statuses), "success": counts["success"],
            "unsuccessful": counts["unsuccessful"], "unknown": counts["unknown"],
            "rate": rate(counts["success"], counts["success"] + counts["unsuccessful"])}


def messages(store: Store, period: Period, today: date, window_days: int = 14) -> dict:
    """Messages (outbound interactions with a body) sent in the period, with
    their status from Company.message_status as of `today`. rate = success /
    (success + unsuccessful); unknown is left out. Broken down by language
    (Company.language) and by channel. reused: the 5 texts (normalised: case
    and whitespace folded) sent more than once in the period, most used first."""
    def sent(p: Period):
        return [(c, i) for c in store.companies.values() for i in c.interactions
                if i.is_message and i.date in p]

    items = [(c, i, c.message_status(i, today, window_days)) for c, i in sent(period)]
    by_language: dict[str, list[str]] = {}
    by_channel: dict[str, list[str]] = {}
    by_text: dict[str, list[str]] = {}
    for c, i, status in items:
        by_language.setdefault(c.language, []).append(status)
        by_channel.setdefault(i.channel, []).append(status)
        by_text.setdefault(normalise_text(i.body), []).append(status)
    reused = sorted(((t, s) for t, s in by_text.items() if len(s) > 1),
                    key=lambda ts: (-len(ts[1]), ts[0]))[:5]
    return {
        "total": _status_row("all", [s for _, _, s in items]),
        "previous_sent": len(sent(period.previous())),
        "by_language": [_status_row(k, v) for k, v in sorted(by_language.items())],
        "by_channel": [_status_row(k, v) for k, v in sorted(by_channel.items())],
        "reused": [{**_status_row(t, s), "uses": len(s),
                    "preview": t[:80] + ("..." if len(t) > 80 else "")} for t, s in reused],
        "window": window_days,
    }


# ---------------------------------------------------------------------- sources


def sources(store: Store, period: Period) -> dict:
    """Per `source`: companies created in the period and companies won in the
    period (closed_date), sorted by created then wins; empty sources omitted."""
    created, wins = Counter(), Counter()
    for c in store.companies.values():
        if c.created in period:
            created[c.source] += 1
        if c.stage == "won" and closed_date(c) in period:
            wins[c.source] += 1
    keys = sorted(set(created) | set(wins), key=lambda k: (-created[k], -wins[k], k))
    return {"rows": [{"source": k, "created": created[k], "won": wins[k]} for k in keys],
            "max_created": max(created.values(), default=0)}


# ---------------------------------------------------------------------- hygiene


def hygiene(store: Store, today: date) -> dict:
    """Today's loose ends, not tied to the period: overdue next steps on
    companies that are not closed (as in PIPELINE.md), active accounts silent
    for store.silent_days or more, and contacts without an email at companies
    that are not closed."""
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
    }


# ------------------------------------------------------------------------ build


def build(store: Store, period: Period, today: date | None = None,
          window_days: int = 14) -> dict:
    """Every section for one period; `today` (default store.today()) drives
    message status and hygiene."""
    today = today or store.today()
    return {
        "period": period,
        "previous": period.previous(),
        "activity": activity(store, period),
        "funnel": funnel(store, period),
        "outcomes": outcomes(store, period),
        "messages": messages(store, period, today, window_days),
        "sources": sources(store, period),
        "hygiene": hygiene(store, today),
    }


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
    out.append(f"{h}Messages")
    out.append(f"sent: {t['sent']} (previous {m['previous_sent']}, "
               f"{delta(t['sent'], m['previous_sent'])}) | success {t['success']} | "
               f"unsuccessful {t['unsuccessful']} | unknown {t['unknown']} | "
               f"success rate {_pct(t['rate'])} (window {m['window']}d)")
    status_headers = ["sent", "success", "unsuccessful", "unknown", "rate"]

    def status_cells(r):
        return [r["sent"], r["success"], r["unsuccessful"], r["unknown"], _pct(r["rate"])]

    out.append(_table(["language"] + status_headers,
                      [[r["key"]] + status_cells(r) for r in m["by_language"]], md))
    out.append(_table(["channel"] + status_headers,
                      [[r["key"]] + status_cells(r) for r in m["by_channel"]], md))
    out.append(_table(["reused text", "uses", "success rate"],
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
