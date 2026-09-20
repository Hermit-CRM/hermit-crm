"""Report rows: the Rows registry behind every number, the /reports/rows page,
configurable message outcomes, and `hermitcrm report --md` staying byte-identical."""

from __future__ import annotations

import html
import re
import subprocess
from datetime import date, datetime
from urllib.parse import quote_plus, unquote_plus

import pytest
from fastapi.testclient import TestClient

from hermitcrm import cli as crm
from hermitcrm import reports
from hermitcrm.datafolder import init_folder
from hermitcrm.store import Store, load_config
from hermitcrm.web import create_app
from conftest import FIXED_NOW

TODAY = FIXED_NOW.date()  # 2026-09-14

# `hermitcrm report --md` for the demo folder (window 14d, today 2026-09-14, default
# outcomes): the rows registry must not change a single byte of it.
BASELINE_30D = """\
# Report 2026-08-16 to 2026-09-14 (30d; previous 2026-07-17 to 2026-08-15)

## Activity

| metric | period | previous | delta |
|---|---|---|---|
| interactions | 9 | 4 | +5 |
| companies touched | 5 | 3 | +2 |
| new companies | 0 | 8 | −8 |
| new contacts | 0 | 9 | −9 |

| week | email out | email in | linkedin out | linkedin in | call out | call in | meeting out | meeting in | total |
|---|---|---|---|---|---|---|---|---|---|
| 2026-W33 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-W34 | 0 | 1 | 0 | 0 | 1 | 0 | 1 | 0 | 3 |
| 2026-W35 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 0 | 2 |
| 2026-W36 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| 2026-W37 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 3 |
| 2026-W38 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Funnel

| stage | entered | previous | delta |
|---|---|---|---|
| prospect | 0 | 8 | −8 |
| engaged | 3 | 3 | ±0 |
| discovery | 3 | 0 | +3 |
| offer | 2 | 0 | +2 |
| won | 1 | 0 | +1 |
| lost | 1 | 0 | +1 |
| disqualified | 1 | 0 | +1 |
| temp-disqualified | 1 | 0 | +1 |

| from | to | reached from | reached to | conversion |
|---|---|---|---|---|
| prospect | engaged | 8 | 6 | 75% |
| engaged | discovery | 6 | 3 | 50% |
| discovery | offer | 3 | 2 | 67% |
| offer | won | 2 | 1 | 50% |

| stage | companies | median days |
|---|---|---|
| prospect | 8 | 13 |
| engaged | 6 | 6 |
| discovery | 3 | 20 |
| offer | 2 | 8 |
| won | 1 | 8 |
| lost | 1 | 12 |
| disqualified | 1 | 16 |
| temp-disqualified | 1 | 22 |

| pipeline stage | companies | EUR/month |
|---|---|---|
| prospect | 1 | 0 |
| engaged | 1 | 0 |
| discovery | 1 | 1,500 |
| offer | 1 | 4,000 |

## Outcomes

| stage | count | EUR/month | previous | delta |
|---|---|---|---|---|
| won | 1 | 6,000 | 0 | +1 |
| lost | 1 | 0 | 0 | +1 |
| disqualified | 1 | 0 | 0 | +1 |

win rate: 50% (previous -)

| lost reason | count |
|---|---|
| no budget this year | 1 |

## Messages

sent: 4 (previous 3, +1) | successful 1 | unsuccessful 2 | unknown 1 | successful rate 33% (window 14d)

| language | sent | successful | unsuccessful | unknown | rate |
|---|---|---|---|---|---|
| de | 1 | 1 | 0 | 0 | 100% |
| en | 1 | 0 | 1 | 0 | 0% |
| fr | 1 | 0 | 0 | 1 | - |
| nl | 1 | 0 | 1 | 0 | 0% |

| channel | sent | successful | unsuccessful | unknown | rate |
|---|---|---|---|---|---|
| call | 2 | 0 | 2 | 0 | 0% |
| email | 1 | 1 | 0 | 0 | 100% |
| linkedin | 1 | 0 | 0 | 1 | - |

| reused text | uses | successful rate |
|---|---|---|
| - |  |  |

## Sources

| source | created | won |
|---|---|---|
| inbound | 0 | 1 |

## Hygiene

| overdue next steps (1) | stage | due | next step |
|---|---|---|---|
| bluefin-analytics | discovery | 2026-09-12 | Send case study |

| silent 14+ days (2) | stage | days |
|---|---|---|
| tallpine-software | prospect | 39 |
| bluefin-analytics | discovery | 20 |

| contacts without email (0) | company |
|---|---|
| - |  |
"""

BASELINE_90D = """\
# Report 2026-06-17 to 2026-09-14 (90d; previous 2026-03-19 to 2026-06-16)

## Activity

| metric | period | previous | delta |
|---|---|---|---|
| interactions | 13 | 0 | +13 |
| companies touched | 6 | 0 | +6 |
| new companies | 8 | 0 | +8 |
| new contacts | 9 | 0 | +9 |

| week | email out | email in | linkedin out | linkedin in | call out | call in | meeting out | meeting in | total |
|---|---|---|---|---|---|---|---|---|---|
| 2026-W25 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-W26 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-W27 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-W28 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-W29 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-W30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-W31 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-W32 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-W33 | 2 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 4 |
| 2026-W34 | 0 | 1 | 0 | 0 | 1 | 0 | 1 | 0 | 3 |
| 2026-W35 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 0 | 2 |
| 2026-W36 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| 2026-W37 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 3 |
| 2026-W38 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Funnel

| stage | entered | previous | delta |
|---|---|---|---|
| prospect | 8 | 0 | +8 |
| engaged | 6 | 0 | +6 |
| discovery | 3 | 0 | +3 |
| offer | 2 | 0 | +2 |
| won | 1 | 0 | +1 |
| lost | 1 | 0 | +1 |
| disqualified | 1 | 0 | +1 |
| temp-disqualified | 1 | 0 | +1 |

| from | to | reached from | reached to | conversion |
|---|---|---|---|---|
| prospect | engaged | 8 | 6 | 75% |
| engaged | discovery | 6 | 3 | 50% |
| discovery | offer | 3 | 2 | 67% |
| offer | won | 2 | 1 | 50% |

| stage | companies | median days |
|---|---|---|
| prospect | 8 | 13 |
| engaged | 6 | 6 |
| discovery | 3 | 20 |
| offer | 2 | 8 |
| won | 1 | 8 |
| lost | 1 | 12 |
| disqualified | 1 | 16 |
| temp-disqualified | 1 | 22 |

| pipeline stage | companies | EUR/month |
|---|---|---|
| prospect | 1 | 0 |
| engaged | 1 | 0 |
| discovery | 1 | 1,500 |
| offer | 1 | 4,000 |

## Outcomes

| stage | count | EUR/month | previous | delta |
|---|---|---|---|---|
| won | 1 | 6,000 | 0 | +1 |
| lost | 1 | 0 | 0 | +1 |
| disqualified | 1 | 0 | 0 | +1 |

win rate: 50% (previous -)

| lost reason | count |
|---|---|
| no budget this year | 1 |

## Messages

sent: 7 (previous 0, +7) | successful 3 | unsuccessful 3 | unknown 1 | successful rate 50% (window 14d)

| language | sent | successful | unsuccessful | unknown | rate |
|---|---|---|---|---|---|
| de | 2 | 2 | 0 | 0 | 100% |
| en | 2 | 0 | 2 | 0 | 0% |
| fr | 1 | 0 | 0 | 1 | - |
| nl | 2 | 1 | 1 | 0 | 50% |

| channel | sent | successful | unsuccessful | unknown | rate |
|---|---|---|---|---|---|
| call | 2 | 0 | 2 | 0 | 0% |
| email | 3 | 2 | 1 | 0 | 67% |
| linkedin | 2 | 1 | 0 | 1 | 100% |

| reused text | uses | successful rate |
|---|---|---|
| - |  |  |

## Sources

| source | created | won |
|---|---|---|
| event | 2 | 0 |
| list | 2 | 0 |
| inbound | 1 | 1 |
| linkedin-search | 1 | 0 |
| network | 1 | 0 |
| referral | 1 | 0 |

## Hygiene

| overdue next steps (1) | stage | due | next step |
|---|---|---|---|
| bluefin-analytics | discovery | 2026-09-12 | Send case study |

| silent 14+ days (2) | stage | days |
|---|---|---|
| tallpine-software | prospect | 39 |
| bluefin-analytics | discovery | 20 |

| contacts without email (0) | company |
|---|---|
| - |  |
"""


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    root = init_folder(tmp_path_factory.mktemp("data") / "demo", demo=True, now=FIXED_NOW)
    s = Store(root, clock=lambda: FIXED_NOW)
    s.load()
    return s


@pytest.fixture(scope="module")
def client(demo):
    config = load_config(demo.root)
    config["push_enabled"] = False
    app = create_app(demo.root, config)
    app.state.store.clock = lambda: FIXED_NOW
    app.state.setup_redirected = True
    return TestClient(app, follow_redirects=False)


def build(store, name="30d", **kw):
    return reports.build(store, reports.period_for(name, TODAY), TODAY, 14, **kw)


# ------------------------------------------------------------------ text output


def test_markdown_unchanged(demo):
    assert reports.render_text(build(demo, "30d"), md=True) == BASELINE_30D
    assert reports.render_text(build(demo, "90d"), md=True) == BASELINE_90D
    # The CLI takes the same path (store without a config: default outcomes).
    assert crm.cmd_report(demo, days=30, md=True) == BASELINE_30D
    assert crm.cmd_report(demo, days=90, md=True) == BASELINE_90D
    assert "| language | sent | successful | unsuccessful | unknown | rate |" in BASELINE_30D


# --------------------------------------------------------- counts match rows


def shown(report):
    """Every (number, key) pair the report shows, in section order."""
    a = report["activity"]
    for k, n in a["totals"].items():
        yield n, a["row_keys"][k]
    for k, n in a["previous"].items():
        yield n, a["previous_row_keys"][k]
    for w in a["weeks"]:
        for col in a["columns"]:
            yield w[col], w["row_keys"][col]
        yield w["total"], w["row_keys"]["total"]
    f = report["funnel"]
    for r in f["entered"]:
        yield r["count"], r["key"]
        yield r["previous"], r["previous_key"]
    for r in f["conversion"]:
        yield r["base"], r["base_key"]
        yield r["reached"], r["reached_key"]
    for r in f["median_days"]:
        yield r["companies"], r["key"]
    for r in f["pipeline"]:
        yield r["count"], r["key"]
    o = report["outcomes"]
    for r in o["rows"]:
        yield r["count"], r["key"]
        yield r["previous"], r["previous_key"]
    for r in o["lost_reasons"]:
        yield r["count"], r["key"]
    m = report["messages"]
    yield m["previous_sent"], m["previous_sent_key"]
    for r in [m["total"], *m["by_language"], *m["by_channel"], *m["reused"]]:
        yield r["sent"], r["sent_key"]
        for s, n in r["counts"].items():
            yield n, r["status_keys"][s]
        yield r["other"], r["status_keys"]["other"]
    for r in report["sources"]["rows"]:
        yield r["created"], r["created_key"]
        yield r["won"], r["won_key"]
    hy = report["hygiene"]
    for k in ("overdue", "silent", "no_email"):
        yield len(hy[k]), hy["row_keys"][k]


@pytest.mark.parametrize("name", ["7d", "30d", "90d", "ytd"])
def test_every_number_has_exactly_that_many_rows(demo, name):
    report = build(demo, name)
    rows = report["rows"]
    seen = set()
    for count, key in shown(report):
        assert key in rows, key
        assert len(rows.get(key)) == count, key
        seen.add(key)
    assert seen == set(rows.keys())  # nothing registered that the page does not show
    assert len(rows) > 50 and report["messages"]["total"]["sent"] > 0
    # Money sums are the summed value of the same rows.
    for r in report["funnel"]["pipeline"]:
        assert sum(x.value or 0 for x in rows.get(r["key"])) == r["value"]
    for r in report["outcomes"]["rows"]:
        assert sum(x.value or 0 for x in rows.get(r["key"])) == r["value"]
        assert sum(x.value or 0 for x in rows.get(r["previous_key"])) == r["previous_value"]
    # Sent = configured outcomes + unknown + anything else.
    for r in [report["messages"]["total"], *report["messages"]["by_language"]]:
        assert r["sent"] == sum(r["counts"].values()) + r["other"]


def test_rows_carry_the_right_kind_and_link(demo):
    rows = build(demo, "30d")["rows"]
    for r in rows.get("activity.interactions"):
        assert r.kind == "interaction" and r.id and r.channel
        assert r.url == f"/companies/{r.slug}/interactions/{r.id}/edit"
    dates = [r.date for r in rows.get("activity.interactions")]
    assert dates == sorted(dates, reverse=True)  # newest first
    for r in rows.get("funnel.pipeline.stage:offer"):
        assert r.kind == "company" and r.url == f"/companies/{r.slug}" and r.stage == "offer"
    won = rows.get("outcomes.won")
    assert len(won) == 1 and won[0].value == 6000 and isinstance(won[0].date, date)
    assert rows.label("outcomes.won") == "Closed won"
    assert rows.label("activity.interactions.week:2026-W37.channel:linkedin.dir:out") \
        == "Interactions in 2026-W37, linkedin out"
    assert rows.label("nope") == "nope" and rows.get("nope") is None and "nope" not in rows
    assert rows.get("messages.status.other") == []  # every demo outcome is a configured one
    successful = build(demo, "90d")["rows"].get("messages.status.successful")
    assert successful and all(r.status == "successful" and r.kind == "interaction"
                              for r in successful)
    assert rows.label("messages.status.other") == "Messages: outcome outside the configured list"
    for r in rows.get("activity.new_contacts.previous"):
        assert r.kind == "contact" and r.url == f"/companies/{r.slug}/contacts/{r.cslug}"


def test_row_columns_and_when():
    company = reports.Row("company", "acme", "Acme", "Acme", value=100)
    contact = reports.Row("contact", "acme", "Acme", "Jane", cslug="jane", contact="Jane",
                          date=datetime(2026, 9, 1, 9, 5))
    interaction = reports.Row("interaction", "acme", "Acme", "Hello", id="x",
                              date=date(2026, 9, 2), channel="email out", status="unknown")
    assert reports.row_columns([]) == ["company"]
    assert reports.row_columns([company]) == ["company", "value"]
    assert reports.row_columns([contact]) == ["company", "contact", "date"]
    assert reports.row_columns([interaction]) == ["company", "interaction", "date", "channel",
                                                  "status"]
    assert (company.when, contact.when, interaction.when) == ("", "2026-09-01 09:05",
                                                              "2026-09-02")


# ------------------------------------------------------------------ outcomes


def test_configurable_outcomes(store):
    store.clock = lambda: datetime(2026, 9, 1, 9, 0)
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe")
    store.create_company("Beta AG")
    store.create_contact("beta", "Bob", "Beta")
    store.create_interaction("acme", channel="email", direction="out", contact="jane-doe",
                             date="2026-09-01T09:30", body="Hello")  # replied: first outcome
    store.create_interaction("acme", channel="email", direction="in", contact="jane-doe",
                             date="2026-09-02T09:30", body="Hi")
    store.create_interaction("beta", channel="email", direction="out", contact="bob-beta",
                             date="2026-08-20T09:30", body="Hello")  # silent: last outcome
    store.create_interaction("beta", channel="linkedin", direction="out", contact="bob-beta",
                             date="2026-09-12T09:30", body="Ping")  # too fresh: unknown
    call = store.create_interaction("beta", channel="call", direction="out", contact="bob-beta",
                                    date="2026-09-10T09:30", body="Notes")
    call.outcome = "Sent"  # a value outside the configured list (legacy free text)
    period = reports.period_for("30d", TODAY)
    m = reports.messages(store, period, TODAY, 14, outcomes=["yes", "maybe", "no"])
    assert m["outcomes"] == ["yes", "maybe", "no"]
    assert m["statuses"] == ["yes", "maybe", "no", "unknown"]
    t = m["total"]
    assert t["sent"] == 4 and t["counts"] == {"yes": 1, "maybe": 0, "no": 1, "unknown": 1}
    assert (t["other"], t["other_statuses"], t["rate"]) == (1, ["Sent"], 0.5)
    assert {r["key"]: r["counts"]["yes"] for r in m["by_language"]} == {"de": 1, "en": 0}
    text = reports.render_text(reports.build(store, period, TODAY, outcomes=["yes", "maybe", "no"]),
                               md=True)
    assert "| language | sent | yes | maybe | no | unknown | rate |" in text
    assert "| yes 1 | maybe 0 | no 1 | unknown 1 | yes rate 50%" in text
    assert "| reused text | uses | yes rate |" in text
    # Without a config on the store the default applies; a config wins over it.
    assert reports.resolve_outcomes(store) == ["successful", "unsuccessful"]
    assert reports.messages(store, period, TODAY)["statuses"] == ["successful", "unsuccessful",
                                                                  "unknown"]
    store.config = {"outcomes": ["won", "lost"]}
    assert reports.resolve_outcomes(store) == ["won", "lost"]
    assert reports.build(store, period, TODAY)["messages"]["total"]["counts"] == {
        "won": 1, "lost": 1, "unknown": 1}
    assert reports.resolve_outcomes(store, ["a"]) == ["a"]


def test_web_uses_the_configured_outcomes(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    app = create_app(tmp_path, config={"push_enabled": False, "outcomes": ["hit", "miss"]})
    app.state.setup_redirected = True
    c = TestClient(app, follow_redirects=False)
    r = c.get("/reports?period=30d")
    assert r.status_code == 200
    assert '<th class="num">hit</th><th class="num">miss</th><th class="num">unknown</th>' in r.text
    assert "hit rate" in r.text and "counts as miss" in r.text
    assert "count in sent only" not in r.text
    assert c.get("/reports/rows?key=messages.status.hit&period=30d").status_code == 200
    assert c.get("/reports/rows?key=messages.status.successful&period=30d").status_code == 404


def test_web_notes_outcomes_outside_the_configured_list(tmp_path):
    """An outcome value the config does not list (legacy data, a hand edit) is
    counted in sent only, with a note linking to its own rows page."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    app = create_app(tmp_path, config={"push_enabled": False, "outcomes": ["hit", "miss"]})
    app.state.setup_redirected = True
    store = app.state.store
    store.clock = lambda: FIXED_NOW
    store.create_company("Acme GmbH")
    store.create_contact("acme", "Jane", "Doe")
    store.create_interaction("acme", channel="email", direction="out", contact="jane-doe",
                             date="2026-09-10T09:30", subject="Intro", body="Hello")
    odd = store.create_interaction("acme", channel="linkedin", direction="out",
                                   contact="jane-doe", date="2026-09-11T09:30", body="Ping")
    odd.outcome = "Sent"  # outside hit / miss, as a hand edit would leave it
    store.write_interaction("acme", odd)  # on disk: the app re-reads the folder
    c = TestClient(app, follow_redirects=False)
    r = c.get("/reports?period=30d")
    assert r.status_code == 200
    assert (">1</a> message with an outcome outside the configured list (Sent) "
            "count in sent only.") in r.text
    assert 'href="/reports/rows?key=messages.status.other&amp;period=30d">1</a>' in r.text
    assert 'href="/reports/rows?key=messages.status.unknown&amp;period=30d">1</a>' in r.text
    assert 'href="/reports/rows?key=messages.sent&amp;period=30d">2</a>' in r.text
    r = c.get("/reports/rows?key=messages.status.other&period=30d")
    assert r.status_code == 200 and "1 row " in r.text
    assert f'href="{odd_url(odd.id)}">{odd.id}</a>' in r.text and "<td>Sent</td>" in r.text
    assert "<td>Intro</td>" not in r.text and "Intro" not in r.text.split("<main", 1)[1]


def odd_url(interaction_id: str) -> str:
    return f"/companies/acme/interactions/{interaction_id}/edit"


# ------------------------------------------------------------------------ web


LINK = re.compile(r'href="/reports/rows\?key=([^&"]+)&amp;([^"]+)"')


def test_report_page_links_numbers_to_registered_keys(client, demo):
    r = client.get("/reports?period=30d")
    assert r.status_code == 200
    links = LINK.findall(r.text)
    assert links and all(query == "period=30d" for _, query in links)
    linked = {unquote_plus(k) for k, _ in links}
    keys = set(build(demo, "30d")["rows"].keys())
    assert linked <= keys
    for key in ("activity.interactions", "activity.interactions.week:2026-W37.channel:linkedin.dir:out",
                "funnel.entered.stage:discovery", "funnel.pipeline.stage:offer",
                "outcomes.won", "outcomes.lost_reason:no budget this year",
                "messages.sent", "messages.status.unknown", "messages.language:fr.sent",
                "sources.source:inbound.won", "hygiene.overdue", "hygiene.silent"):
        assert key in linked, key
    # Zero counts stay plain text: nothing links to an empty row list.
    rows = build(demo, "30d")["rows"]
    assert all(rows.get(k) for k in linked)
    assert re.search(r'<a class="rows" href="[^"]*">0</a>', r.text) is None
    assert re.search(r'<a class="rows" href="[^"]*">4,000</a>', r.text)  # money sums link too
    assert "count in sent only" not in r.text  # every demo outcome is a configured one


@pytest.mark.parametrize("name", ["30d", "90d"])
def test_rows_page_renders_every_key(client, demo, name):
    report = build(demo, name)
    rows = report["rows"]
    for key in rows.keys():
        r = client.get(f"/reports/rows?period={name}&key={quote_plus(key)}")
        assert r.status_code == 200, key
        assert f"<h1>{html.escape(rows.label(key))}</h1>" in r.text, key
        assert f'href="/reports?period={name}"' in r.text
        table = r.text.split('class="report report-rows"', 1)[1]
        assert table.count("<tr>") == 1 + max(len(rows.get(key)), 1), key  # header + rows or "none"
        for row in rows.get(key):
            assert f'href="{row.url}"' in table, (key, row)
            assert f'href="/companies/{row.slug}"' in table


def test_rows_page_columns(client, demo):
    rows = build(demo, "30d")["rows"]
    r = client.get("/reports/rows?key=activity.interactions&period=30d")
    assert "<th>company</th><th>contact</th><th>interaction</th><th>date</th><th>channel</th>" in r.text
    for row in rows.get("activity.interactions"):
        assert row.when in r.text and f"<td>{row.channel}</td>" in r.text
        assert f'href="/companies/{row.slug}/contacts/{row.cslug}">{row.contact}</a>' in r.text
    assert "linkedin out" in r.text
    r = client.get("/reports/rows?key=funnel.pipeline.stage:offer&period=30d")
    assert "<th>stage</th>" in r.text and '<th class="num">EUR/month</th>' in r.text
    assert "4,000" in r.text and "<th>interaction</th>" not in r.text
    r = client.get("/reports/rows?key=hygiene.silent&period=30d")
    assert "39 days silent" in r.text and "<th>note</th>" in r.text
    r = client.get("/reports/rows?key=outcomes.disqualified&period=30d")
    assert 'href="/companies/driftwood-media"' in r.text
    r = client.get("/reports/rows?key=outcomes.won&period=custom&from=2026-08-01&to=2026-08-02")
    assert 'class="empty">none</td>' in r.text and "0 rows" in r.text


def test_rows_page_custom_period_keeps_the_back_link(client):
    r = client.get("/reports/rows?key=hygiene.overdue&period=custom&from=2026-08-01&to=2026-09-14")
    assert r.status_code == 200
    assert 'href="/reports?period=custom&amp;from=2026-08-01&amp;to=2026-09-14"' in r.text
    assert "2026-08-01 to 2026-09-14 (45d)" in r.text
    r = client.get("/reports?period=custom&from=2026-08-01&to=2026-09-14")
    assert "&amp;period=custom&amp;from=2026-08-01&amp;to=2026-09-14\"" in r.text
    # A bad custom period on the report falls back to 30d, and so do its links.
    r = client.get("/reports?period=custom&from=2026-09-14&to=2026-08-01")
    assert 'class="error"' in r.text and "&amp;period=30d\"" in r.text
    assert "period=custom" not in r.text.split("<section", 1)[1]


def test_rows_page_errors(client):
    assert client.get("/reports/rows?key=nope&period=30d").status_code == 404
    assert client.get("/reports/rows?period=30d").status_code == 404
    assert client.get("/reports/rows?key=hygiene.overdue&period=week").status_code == 400
    r = client.get("/reports/rows?key=hygiene.overdue&period=custom&from=2026-02-01&to=2026-01-01")
    assert r.status_code == 400 and "from must be on or before to" in r.text
    assert client.get("/reports/rows?key=hygiene.overdue&period=custom&from=garbage").status_code == 400


def test_period_query():
    assert reports.period_query("30d") == "period=30d"
    assert reports.period_query("30d", "2026-01-01", "2026-02-01") == "period=30d"
    assert reports.period_query("custom", "2026-01-01", "") == "period=custom&from=2026-01-01"
    assert reports.period_query("custom", "2026-01-01", "2026-02-01") \
        == "period=custom&from=2026-01-01&to=2026-02-01"
