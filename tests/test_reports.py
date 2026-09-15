"""Stage history (models, store paths, backfill) and reports (sections, web, CLI)."""

from __future__ import annotations

import subprocess
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from owncrm import cli as crm
from owncrm import reports
from owncrm.models import Company, StageChange, company_from_dict, company_to_frontmatter
from owncrm.store import Store, build_file, split_file
from owncrm.web import create_app
from conftest import FIXED_NOW, read

TODAY = FIXED_NOW.date()  # 2026-09-14


def clocked(store: Store, when: str):
    """Move the store's frozen clock."""
    store.clock = lambda: datetime.fromisoformat(when)


# --------------------------------------------------------------- model/serialise


def test_empty_history_writes_nothing(store):
    c = store.create_company("Acme GmbH")
    text = read(store.company_dir("acme") / "company.md")
    assert "stage_history" not in text
    assert c.stage_history == []


def test_history_round_trip_and_format(store):
    store.create_company("Acme GmbH")
    store.update_company("acme", stage="reached-out")
    store.update_company("acme", stage="lost", lost_reason="no budget, later")
    path = store.company_dir("acme") / "company.md"
    text = read(path)
    assert ("tags: []\nstage_history:\n"
            "  - {date: 2026-09-14, from: prospect, to: reached-out}\n"
            "  - {date: 2026-09-14, from: reached-out, to: lost, reason: 'no budget, later'}\n"
            "created: ") in text
    meta, body = split_file(text)
    c = company_from_dict(meta, body, "acme")
    assert c.stage_history[1] == StageChange(TODAY, "reached-out", "lost", "no budget, later")
    assert build_file(company_to_frontmatter(c), c.notes) == text


def test_invalid_history_is_a_problem(store):
    store.create_company("Acme GmbH")
    path = store.company_dir("acme") / "company.md"
    path.write_text(read(path).replace("tags: []\n", "tags: []\nstage_history:\n  - {to: nope}\n"))
    store.load()
    assert "acme" not in store.companies
    assert any("stage_history" in p.message for p in store.problems)


def test_derived_dates_and_durations():
    c = Company(name="A", slug="a", stage="won", created=datetime(2026, 1, 1, 9, 0),
                stage_changed=date(2026, 3, 1), stage_history=[
                    StageChange(date(2026, 1, 11), "prospect", "discovery"),
                    StageChange(date(2026, 2, 1), "discovery", "lost", "x"),
                    StageChange(date(2026, 2, 11), "lost", "discovery"),
                    StageChange(date(2026, 3, 1), "discovery", "won"),
                ])
    assert c.closed_on == date(2026, 3, 1)
    assert c.entered_stage_on("discovery") == date(2026, 2, 11)
    assert c.entered_stage_on("prospect") == date(2026, 1, 1)  # implicit start
    assert c.entered_stage_on("offer") is None
    assert c.stage_durations(date(2026, 3, 11)) == {
        "prospect": 10, "discovery": 21 + 18, "lost": 10, "won": 10}
    # Entries after `today` are ignored.
    assert c.stage_durations(date(2026, 2, 5)) == {"prospect": 10, "discovery": 21, "lost": 4}


def test_derived_without_history_uses_created_and_stage_changed():
    c = Company(name="A", slug="a", stage="offer", created=datetime(2026, 1, 1),
                stage_changed=date(2026, 1, 21))
    assert [(e.from_stage, e.to_stage) for e in c.stage_entries()] == [
        ("", "prospect"), ("prospect", "offer")]
    assert c.stage_durations(date(2026, 1, 31)) == {"prospect": 20, "offer": 10}
    assert c.closed_on is None
    assert Company(name="B", slug="b").stage_durations(TODAY) == {}


# ------------------------------------------------------------------ store paths


def test_create_in_non_prospect_stage_records_start(store):
    c = store.create_company("Beta AG", stage="discovery")
    assert c.stage_history == [StageChange(TODAY, "", "discovery")]


def test_update_appends_and_never_rewrites(store):
    store.create_company("Acme GmbH")
    first = store.update_company("acme", stage="reached-out").stage_history
    clocked(store, "2026-09-20T09:00")
    store.update_company("acme", next_step="Call")  # no stage change: no entry
    c = store.update_company("acme", stage="discovery")
    assert first == [StageChange(TODAY, "prospect", "reached-out")]  # old list untouched
    assert c.stage_history == first + [StageChange(date(2026, 9, 20), "reached-out", "discovery")]


def test_disqualify_and_requalify_due_append(store):
    store.create_company("Acme GmbH")
    store.update_company("acme", stage="temp-disqualified", lost_reason="too early",
                         requalify_on="2026-10-01")
    clocked(store, "2026-10-01T08:00")
    assert store.requalify_due() == ["acme"]
    assert store.get("acme").stage_history == [
        StageChange(TODAY, "prospect", "temp-disqualified", "too early"),
        StageChange(date(2026, 10, 1), "temp-disqualified", "prospect"),
    ]


def test_merge_combines_histories_sorted(store):
    store.create_company("Acme GmbH")
    clocked(store, "2026-09-16T09:00")
    store.update_company("acme", stage="reached-out")
    clocked(store, "2026-09-14T09:00")
    store.create_company("Acme Two", stage="discovery")
    clocked(store, "2026-09-18T09:00")
    merged = store.merge_companies("acme", "acme-two", {"stage": "keep"})
    assert [(e.date.day, e.to_stage) for e in merged.stage_history] == [
        (14, "discovery"), (16, "reached-out")]
    assert "stage_history" in read(store.company_dir("acme") / "company.md")


def test_merge_taking_other_stage_appends(store):
    store.create_company("Acme GmbH")
    store.create_company("Acme Two")
    store.update_company("acme-two", stage="offer")
    store.update_company("acme", stage="reached-out")
    merged = store.merge_companies("acme", "acme-two", {"stage": "drop"})
    assert merged.stage == "offer"
    # The combined history already ends in offer (acme-two's entry): nothing added.
    assert merged.stage_history[-1] == StageChange(TODAY, "prospect", "offer")
    assert len(merged.stage_history) == 2
    store.update_company("acme", stage="discovery")
    store.create_company("Acme Three", stage="won")
    merged = store.merge_companies("acme", "acme-three", {"stage": "keep"})
    # Keeping ours while the other's entry sorts last records the move back.
    assert merged.stage_history[-1] == StageChange(TODAY, "won", "discovery")


def test_merge_without_history_and_same_stage_writes_nothing(store):
    store.create_company("Acme GmbH")
    store.create_company("Acme Two")
    merged = store.merge_companies("acme", "acme-two")
    assert merged.stage_history == []


# --------------------------------------------------------------------- backfill


def version(stage: str, reason: str = "") -> str:
    return (f"---\nname: Acme\nstage: {stage}\nlost_reason: {reason}\n---\n"
            f"stage: won\n")  # the body line must never be read


class FakeGit:
    """git log / git show from a list of (sha, date, path, text), newest last."""

    def __init__(self, commits):
        self.commits = commits
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "log":
            if not args[-1].endswith("acme/company.md"):
                return ""
            return "".join(f"{sha * 40} {day}\n\n{path}\n\n"
                           for sha, day, path, _ in reversed(self.commits))
        sha, path = args[1].split(":", 1)
        for s, _, p, text in self.commits:
            if s * 40 == sha and p == path:
                return text
        return ""


def test_backfill_builds_transitions_from_commits(store, messages):
    store.create_company("Acme GmbH")
    store.create_company("Beta AG")  # no git history: skipped
    acme = store.get("acme")
    acme.stage, acme.lost_reason, acme.stage_changed = "lost", "no budget", date(2026, 9, 14)
    fake = FakeGit([
        ("a", "2026-09-01", "companies/acme-old/company.md", version("prospect")),
        ("b", "2026-09-03", "companies/acme/company.md", version("prospect")),
        ("c", "2026-09-05", "companies/acme/company.md", version("discovery")),
        ("d", "2026-09-09", "companies/acme/company.md", version("temp-disqualified", "later")),
        # working copy moved on to lost, not committed
    ])
    text = crm.cmd_backfill_history(store, git_log=fake, git_show=fake)
    assert "acme | 4 entries | start -> prospect -> discovery -> temp-disqualified -> lost" in text
    assert "1 companies to backfill" in text and "dry run" in text
    assert messages == ["company: acme created", "company: beta created"]
    assert ["show", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:companies/acme-old/company.md"] in fake.calls
    assert store.get("acme").stage_history == []

    text = crm.cmd_backfill_history(store, apply=True, git_log=fake, git_show=fake)
    assert "applied in one commit" in text
    assert messages[-1] == "ai: backfill stage history for 1 companies"
    assert len(messages) == 3
    assert store.get("acme").stage_history == [
        StageChange(date(2026, 9, 1), "", "prospect"),  # first commit predates created
        StageChange(date(2026, 9, 5), "prospect", "discovery"),
        StageChange(date(2026, 9, 9), "discovery", "temp-disqualified", "later"),
        StageChange(date(2026, 9, 14), "temp-disqualified", "lost", "no budget"),
    ]
    # A second run leaves companies with a history alone.
    assert crm.cmd_backfill_history(store, apply=True, git_log=fake, git_show=fake).startswith(
        "0 companies to backfill, 1 already have a history")
    assert len(messages) == 3


def test_backfill_against_real_git(tmp_path, messages):
    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=tmp_path, check=True, capture_output=True)
    git("init", "-b", "main")
    s = Store(tmp_path, on_write=messages.append, clock=lambda: FIXED_NOW)
    s.load()
    s.create_company("Acme GmbH")
    git("add", "-A")
    git("commit", "-m", "created")
    path = s.company_dir("acme") / "company.md"
    path.write_text(read(path).replace("stage: prospect", "stage: offer"))
    git("commit", "-am", "offer")
    s.load()
    crm.cmd_backfill_history(s, apply=True)
    assert [(e.from_stage, e.to_stage) for e in s.get("acme").stage_history] == [
        ("", "prospect"), ("prospect", "offer")]


# ---------------------------------------------------------------------- periods


def test_period_resolution_and_previous():
    p = reports.period_for("7d", TODAY)
    assert (p.start, p.end, p.days) == (date(2026, 9, 8), TODAY, 7)
    assert p.previous() == reports.Period(date(2026, 9, 1), date(2026, 9, 7))
    assert reports.period_for("quarter", TODAY).start == date(2026, 7, 1)
    assert reports.period_for("ytd", TODAY).start == date(2026, 1, 1)
    assert reports.period_for("custom", TODAY, None, None).days == 30
    assert datetime(2026, 9, 14, 23, 59) in p and date(2026, 9, 7) not in p and None not in p
    with pytest.raises(ValueError):
        reports.period_for("custom", TODAY, date(2026, 9, 2), date(2026, 9, 1))
    with pytest.raises(ValueError):
        reports.period_for("week", TODAY)


def test_delta_and_rate():
    assert [reports.delta(5, 3), reports.delta(1, 4), reports.delta(0, 0)] == ["+2", "−3", "±0"]
    assert reports.rate(1, 0) is None and reports.rate(1, 4) == 0.25


# ---------------------------------------------------------------------- sections


def test_empty_store_every_section(store):
    report = reports.build(store, reports.period_for("30d", TODAY))
    assert report["activity"]["totals"] == {"interactions": 0, "companies_touched": 0,
                                            "new_companies": 0, "new_contacts": 0}
    assert len(report["activity"]["weeks"]) == 6  # Sun 2026-08-16 is in W33; W33..W38
    assert all(r["rate"] is None for r in report["funnel"]["conversion"])
    assert report["funnel"]["median_days"] == []
    assert report["outcomes"]["win_rate"] is None
    assert report["messages"]["total"]["sent"] == 0 and report["messages"]["reused"] == []
    assert report["sources"]["rows"] == []
    assert report["hygiene"] == {"overdue": [], "silent": [], "no_email": [], "silent_days": 14}
    text = reports.render_text(report, md=True)
    assert "## Hygiene" in text and "| - |" in text


@pytest.fixture
def seeded(store):
    """Previous 7d period: 2026-09-01..07. Current: 2026-09-08..14."""
    clocked(store, "2026-09-02T09:00")
    store.create_company("Old AG", source="referral")  # previous period
    store.create_contact("old", "Otto", "Old", email="otto@old.de")
    store.update_company("old", stage="lost", lost_reason="No Budget ")
    clocked(store, "2026-09-08T09:00")  # first day of the period
    store.create_company("Acme GmbH", source="linkedin-search", country="DE",
                         value_eur_month=4000)
    store.create_contact("acme", "Jane", "Doe")  # no email
    store.create_company("Beta AG", source="linkedin-search", stage="reached-out")
    store.create_contact("beta", "Bob", "Beta", email="bob@beta.com")
    store.create_company("Gamma", source="referral", next_step="Call", next_step_due="2026-09-10")
    body = "Hi there,\nquick question"
    store.create_interaction("acme", channel="linkedin", direction="out", contact="jane-doe",
                             date="2026-09-08T09:30", body=body)
    store.create_interaction("beta", channel="linkedin", direction="out", contact="bob-beta",
                             date="2026-09-08T09:40", body="hi there, QUICK question")
    store.create_interaction("beta", channel="email", direction="in", contact="bob-beta",
                             date="2026-09-09T10:00", body="Sure")
    store.create_interaction("old", channel="email", direction="out", contact="otto-old",
                             date="2026-09-07T23:59", body=body)  # previous period, boundary
    clocked(store, "2026-09-10T09:00")
    store.update_company("acme", stage="reached-out")
    store.update_company("acme", stage="discovery")
    store.update_company("beta", stage="lost", lost_reason="no budget")
    clocked(store, "2026-09-14T10:00")
    store.update_company("acme", stage="won")
    return store


def test_activity(seeded):
    a = reports.activity(seeded, reports.period_for("7d", TODAY))
    assert a["totals"] == {"interactions": 3, "companies_touched": 2,
                           "new_companies": 3, "new_contacts": 2}
    assert a["previous"] == {"interactions": 1, "companies_touched": 1,
                             "new_companies": 1, "new_contacts": 1}
    weeks = {r["week"]: r for r in a["weeks"]}
    # Tue 2026-09-08 is in W37; Mon 2026-09-14 starts W38 (empty, still listed).
    assert list(weeks) == ["2026-W37", "2026-W38"]
    assert weeks["2026-W38"]["total"] == 0 and a["max_week"] == 3
    assert weeks["2026-W37"]["linkedin out"] == 2 and weeks["2026-W37"]["email in"] == 1


def test_activity_counts_meetings(store):
    """Calendar-imported meetings show up in the week table like any other channel."""
    clocked(store, "2026-09-08T09:00")
    store.create_company("Delta Ltd", source="referral")
    store.create_contact("delta", "Dana", "Delta", email="dana@delta.example.com")
    store.create_interaction("delta", channel="meeting", direction="out",
                             contact="dana-delta", date="2026-09-09T14:00", body="Intro call")
    a = reports.activity(store, reports.period_for("7d", TODAY))
    assert "meeting out" in a["columns"] and "meeting in" in a["columns"]
    weeks = {r["week"]: r for r in a["weeks"]}
    assert weeks["2026-W37"]["meeting out"] == 1 and weeks["2026-W37"]["total"] == 1


def test_funnel(seeded):
    f = reports.funnel(seeded, reports.period_for("7d", TODAY))
    entered = {r["stage"]: (r["count"], r["previous"]) for r in f["entered"]}
    assert entered["prospect"] == (2, 1)  # acme and gamma implicit; beta started in reached-out
    assert entered["reached-out"] == (2, 0)
    assert entered["won"] == (1, 0) and entered["lost"] == (1, 1)
    conv = {(r["from"], r["to"]): (r["base"], r["reached"]) for r in f["conversion"]}
    # beta skipped prospect but still counts as having reached it; old never left prospect.
    assert conv[("prospect", "reached-out")] == (4, 2)
    assert conv[("reached-out", "discovery")] == (2, 1)
    assert conv[("offer", "won")] == (1, 1)  # acme skipped offer
    medians = {r["stage"]: r["median"] for r in f["median_days"]}
    assert medians["won"] == 0 and medians["lost"] == 8  # old 12d, beta 4d
    pipeline = {r["stage"]: (r["count"], r["value"]) for r in f["pipeline"]}
    assert pipeline["prospect"] == (1, 0) and pipeline["discovery"] == (0, 0)


def test_outcomes(seeded):
    o = reports.outcomes(seeded, reports.period_for("7d", TODAY))
    rows = {r["stage"]: r for r in o["rows"]}
    assert (rows["won"]["count"], rows["won"]["value"]) == (1, 4000)
    assert (rows["lost"]["count"], rows["lost"]["previous"]) == (1, 1)
    assert o["win_rate"] == 0.5 and o["previous_win_rate"] == 0.0
    assert o["lost_reasons"] == [{"reason": "no budget", "count": 1}]
    wide = reports.outcomes(seeded, reports.period_for("30d", TODAY))
    assert wide["lost_reasons"] == [{"reason": "no budget", "count": 2}]  # normalised together


def test_outcomes_fall_back_to_stage_changed(store):
    store.create_company("Acme GmbH")
    path = store.company_dir("acme") / "company.md"
    path.write_text(read(path).replace("stage: prospect", "stage: won")
                    .replace("stage_changed: 2026-09-14", "stage_changed: 2026-09-12"))
    store.load()
    o = reports.outcomes(store, reports.period_for("7d", TODAY))
    assert o["rows"][0]["count"] == 1 and o["win_rate"] == 1.0


def test_messages(seeded):
    m = reports.messages(seeded, reports.period_for("7d", TODAY), TODAY, window_days=14)
    assert m["total"]["sent"] == 2 and m["previous_sent"] == 1
    assert (m["total"]["success"], m["total"]["unknown"], m["total"]["rate"]) == (1, 1, 1.0)
    assert {r["key"]: r["sent"] for r in m["by_language"]} == {"de": 1, "en": 1}
    assert [r["key"] for r in m["by_channel"]] == ["linkedin"]
    assert m["reused"] == [{"key": "hi there, quick question", "sent": 2, "success": 1,
                            "unsuccessful": 0, "unknown": 1, "rate": 1.0, "uses": 2,
                            "preview": "hi there, quick question"}]
    short = reports.messages(seeded, reports.period_for("7d", TODAY), TODAY, window_days=3)
    assert short["total"]["unsuccessful"] == 1 and short["total"]["rate"] == 0.5


def test_sources(seeded):
    s = reports.sources(seeded, reports.period_for("7d", TODAY))
    assert s["rows"] == [{"source": "linkedin-search", "created": 2, "won": 1},
                         {"source": "referral", "created": 1, "won": 0}]


def test_hygiene(seeded):
    h = reports.hygiene(seeded, TODAY)
    assert [r["slug"] for r in h["overdue"]] == ["gamma"]
    assert h["silent"] == []
    assert [r["contact"] for r in h["no_email"]] == []  # jane is at won acme (closed)
    later = reports.hygiene(seeded, date(2026, 9, 30))
    assert [r["slug"] for r in later["silent"]] == ["gamma"]


# -------------------------------------------------------------------- web + CLI


@pytest.fixture
def client(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    app = create_app(tmp_path, config={"port": 8765, "silent_days": 14,
                                       "push_enabled": False, "remote": "origin"})
    app.state.store.create_company("Acme GmbH", stage="discovery")
    return TestClient(app, follow_redirects=False)


@pytest.mark.parametrize("query", ["", "?period=7d", "?period=30d", "?period=90d",
                                   "?period=quarter", "?period=ytd",
                                   "?period=custom&from=2026-01-01&to=2026-02-01",
                                   "?period=custom"])
def test_reports_route(client, query):
    r = client.get("/reports" + query)
    assert r.status_code == 200
    assert "Funnel" in r.text and 'href="/reports"' in r.text


def test_reports_route_bad_custom_falls_back(client):
    r = client.get("/reports?period=custom&from=2026-02-01&to=2026-01-01")
    assert r.status_code == 200 and "from must be on or before to" in r.text
    r = client.get("/reports?period=custom&from=garbage")
    assert r.status_code == 200 and 'class="error"' in r.text


def test_company_page_shows_history(client):
    r = client.get("/companies/acme")
    assert "Stage history (1)" in r.text and "<td>discovery</td>" in r.text


def test_cli_report(tmp_path, capsys):
    s = Store(tmp_path, clock=lambda: FIXED_NOW)
    s.load()
    s.create_company("Acme GmbH", source="referral")
    text = crm.cmd_report(s, days=7)
    assert text.startswith("Report 2026-09-08 to 2026-09-14 (7d; previous 2026-09-01 to 2026-09-07)")
    assert "new companies      1       0         +1" in text
    md = crm.cmd_report(s, start=date(2026, 9, 1), end=date(2026, 9, 14), md=True)
    assert "## Sources" in md and "| referral | 1 | 0 |" in md
    assert max(len(line) for line in text.splitlines()) <= 120
    assert crm.main(["report", "--from", "2026-09-01", "--to", "2026-09-14", "--md"],
                    root=tmp_path) == 0
    assert "# Report 2026-09-01 to 2026-09-14" in capsys.readouterr().out
    assert crm.main(["report", "--from", "2026-09-14", "--to", "2026-09-01"], root=tmp_path) == 2


def test_cli_backfill_dry_run(tmp_path, capsys):
    (tmp_path / "companies").mkdir()
    assert crm.main(["backfill-history"], root=tmp_path) == 0
    assert "0 companies to backfill" in capsys.readouterr().out
