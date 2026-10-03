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

"""Dashboards: dashboards/<slug>.toml, the /d/<slug> page, its links back to
the list pages and Reports, validation (`hermitcrm check`), and pinning."""

from __future__ import annotations

import html
import os
import re
import subprocess
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import pytest
from fastapi.testclient import TestClient

from hermitcrm import backup, cli, dashboards, doctor, migrations
from hermitcrm import help as helpdocs
from hermitcrm.datafolder import init_folder
from hermitcrm.store import Store
from hermitcrm.web import create_app
from conftest import FIXED_NOW

CONFIG = {"push_enabled": False, "owner_email": "me@example.com",
          "welcome_dismissed": True, "disclaimer_accepted": "2026-09-01T09:00:00"}

MONDAY = """\
title = "Monday review"
pin = true
description = "What to work on this week."

[[widget]]
type = "list"
title = "Best open deals"
scope = "companies"
filters = { stage = ["prospect", "engaged", "discovery", "offer"], my_score = ">4" }
columns = ["name", "my_score", "country", "next_step"]
sort = "-my_score"
limit = 2

[[widget]]
type = "count"
title = "SaaS companies"
scope = "companies"
filters = { tags = "saas" }

[[widget]]
type = "group"
scope = "companies"
by = "stage"

[[widget]]
type = "report"
section = "funnel"
period = "30d"
"""


# ------------------------------------------------------------------- fixtures


@pytest.fixture
def folder(tmp_path) -> Path:
    """The demo folder, built on the suite's fixed day."""
    return init_folder(tmp_path / "crm", demo=True, now=FIXED_NOW)


@pytest.fixture
def client(folder):
    app = create_app(folder, config=CONFIG, clock=lambda: FIXED_NOW)
    return TestClient(app, follow_redirects=False)


def write(folder: Path, slug: str, text: str) -> Path:
    path = folder / "dashboards" / f"{slug}.toml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    # A real edit moves the mtime; two writes inside one test may not.
    stamp = path.stat().st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(stamp, stamp))
    return path


def main_of(page: str) -> str:
    return page.split("<main>", 1)[1].split("</main>", 1)[0]


def nav_of(page: str) -> str:
    return page.split("</nav>", 1)[0]


def widgets_of(page: str) -> list[str]:
    return re.findall(r'<section class="widget.*?</section>', main_of(page), re.S)


def links(fragment: str) -> list[str]:
    return [html.unescape(h) for h in re.findall(r'href="([^"]+)"', fragment)]


def query(url: str) -> list[tuple[str, str]]:
    return parse_qsl(urlparse(url).query)


def company_slugs(page: str) -> list[str]:
    """The companies a Companies page lists, in its order."""
    return re.findall(r'<tr>\s*<td><a href="/companies/([a-z0-9-]+)">', main_of(page))


def contact_keys(page: str) -> list[str]:
    return re.findall(r'<tr>\s*<td><a href="/companies/([a-z0-9-]+/contacts/[a-z0-9-]+)">',
                      main_of(page))


def message_keys(page: str) -> list[tuple[str, str]]:
    """(sent, company slug) per row of the Messages page."""
    return re.findall(r'<td class="nowrap">([^<]*)</td>\s*<td><a href="/companies/([a-z0-9-]+)">',
                      main_of(page))


def task_texts(page: str) -> list[str]:
    return [t.strip() for t in re.findall(r'<td class="due[^"]*">[^<]*</td>\s*<td>([^<]*)',
                                          main_of(page))]


# --------------------------------------------------------------- the widgets


def test_list_widget_rows_columns_sort_limit_and_link(client, folder):
    write(folder, "monday-review", MONDAY)
    page = client.get("/d/monday-review")
    assert page.status_code == 200
    first = widgets_of(page.text)[0]
    assert "<h2><a" in first and "Best open deals" in first
    assert [h for h in re.findall(r"<th>([^<]*)</th>", first)] == \
        ["name", "my score", "country", "next step"]
    # sorted on my_score, high to low, cut at 2 of the 3 that match
    rows = re.findall(r"<tr><td><a href=\"(/companies/[a-z-]+)\">([^<]*)</a></td><td>([^<]*)</td>",
                      first)
    assert rows == [("/companies/northwind-robotics", "Northwind Robotics", "8"),
                    ("/companies/bluefin-analytics", "Bluefin Analytics", "7")]
    assert "2 of 3" in first
    more = [u for u in links(first) if u.startswith("/companies?")][0]
    assert query(more) == [("f_stage", "prospect"), ("f_stage", "engaged"),
                           ("f_stage", "discovery"), ("f_stage", "offer"),
                           ("f_my_score", ">4"), ("sort", "my_score"), ("dir", "desc")]
    # the page the link opens lists the same records, in the same order
    assert company_slugs(client.get(more).text) == \
        ["northwind-robotics", "bluefin-analytics", "copperleaf-studio"]


def test_count_widget_counts_and_links_to_exactly_those_records(client, folder):
    write(folder, "monday-review", MONDAY)
    count = widgets_of(client.get("/d/monday-review").text)[1]
    assert "SaaS companies" in count
    number = re.search(r'<p class="widget-count"><a href="([^"]+)"[^>]*>(\d+)</a>', count)
    url, n = html.unescape(number.group(1)), int(number.group(2))
    assert url == "/companies?f_tags=saas" and n == 2
    assert sorted(company_slugs(client.get(url).text)) == \
        ["bluefin-analytics", "tallpine-software"]


def test_group_widget_bars_follow_the_stage_order_and_link_to_their_rows(client, folder):
    write(folder, "monday-review", MONDAY)
    group = widgets_of(client.get("/d/monday-review").text)[2]
    assert "Companies by stage" in group
    bars = re.findall(r'<tr><td><a href="([^"]+)">([^<]*)</a></td><td class="num">'
                      r'<a class="rows" href="[^"]+">(\d+)</a>', group)
    # temp-disqualified is parked, so hidden, exactly as on the Companies page
    assert [label for _, label, _ in bars] == \
        ["prospect", "engaged", "discovery", "offer", "won", "lost", "disqualified"]
    for url, label, n in bars:
        url = html.unescape(url)
        assert query(url) == [("f_stage", label)]
        assert len(company_slugs(client.get(url).text)) == int(n) == 1
    assert "7 in all" in group and 'class="bar"' in group


def test_group_on_tags_counts_each_tag_and_on_free_text_matches_exactly(client, folder):
    write(folder, "tags", """\
title = "Tags"
[[widget]]
type = "group"
scope = "companies"
by = "tags"
limit = 3

[[widget]]
type = "group"
scope = "companies"
by = "next_step"
filters = { stage = ["engaged", "discovery", "offer"] }
""")
    tags, steps = widgets_of(client.get("/d/tags").text)
    bars = re.findall(r'<tr><td><a href="([^"]+)">([^<]*)</a></td><td class="num">'
                      r'<a class="rows" href="[^"]+">(\d+)</a>', tags)
    assert [(label, int(n)) for _, label, n in bars] == \
        [("demo", 7), ("saas", 2), ("agency", 1)]
    assert "4 more values not shown" in tags
    for url, _, n in bars:
        assert len(company_slugs(client.get(html.unescape(url)).text)) == int(n)
    step_bars = re.findall(r'<tr><td><a href="([^"]+)">([^<]*)</a>', steps)
    assert len(step_bars) == 3
    for url, label in step_bars:
        url = html.unescape(url)
        assert ("f_next_step", "=" + label) in query(url)
        assert ("f_stage", "engaged") in query(url)
        assert len(company_slugs(client.get(url).text)) == 1


def test_group_on_a_select_field_shows_empty_values_without_a_link(client, folder):
    (folder / "fields.toml").write_text("""\
[[field]]
key = "segment"
type = "select"
options = ["smb", "mid"]
applies_to = "company"
show_in = ["detail", "companies"]
""", encoding="utf-8")
    client.post("/reload")
    store = client.app.state.store
    store.update_company("bluefin-analytics", custom={"segment": "smb"})
    store.update_company("tallpine-software", custom={"segment": "smb"})
    write(folder, "segments", 'title = "Segments"\n[[widget]]\ntype = "group"\n'
                              'scope = "companies"\nby = "segment"\n')
    group = widgets_of(client.get("/d/segments").text)[0]
    assert re.search(r'<a href="/companies\?f_segment=smb">smb</a></td><td class="num">'
                     r'<a class="rows" href="[^"]+">2</a>', group)
    assert re.search(r'<span title="[^"]*">\(empty\)</span></td><td class="num">5</td>', group)


def test_report_widget_reuses_the_reports_section_and_its_rows(client, folder):
    write(folder, "monday-review", MONDAY)
    report = widgets_of(client.get("/d/monday-review").text)[3]
    assert "Funnel (30d)" in report and "pipeline now" in report
    ours = sorted(u for u in links(report) if u.startswith("/reports/rows"))
    reports_page = client.get("/reports?period=30d").text
    funnel = reports_page.split('<section id="funnel">')[1].split("</section>")[0]
    assert ours and ours == sorted(u for u in links(funnel) if u.startswith("/reports/rows"))
    rows = client.get(ours[0])
    assert rows.status_code == 200 and "Back to report" in rows.text


def test_report_period_all_runs_from_the_first_day_in_the_data(client, folder):
    write(folder, "all", 'title = "All time"\n[[widget]]\ntype = "report"\n'
                         'section = "sources"\nperiod = "all"\n')
    report = widgets_of(client.get("/d/all").text)[0]
    first = dashboards.first_day(client.app.state.store)
    assert first == FIXED_NOW.date() - timedelta(days=42)
    row_links = [u for u in links(report) if u.startswith("/reports/rows")]
    assert row_links
    for url in row_links:
        assert ("period", "custom") in query(url)
        assert ("from", first.isoformat()) in query(url)
        assert client.get(url).status_code == 200


def test_tasks_widget_with_date_buttons_matches_the_tasks_page(client, folder):
    write(folder, "tasks", """\
title = "This week"
[[widget]]
type = "list"
scope = "tasks"
when = ["overdue", "today", "week"]
columns = ["text", "due"]

[[widget]]
type = "count"
scope = "tasks"
when = "overdue"
""")
    listed, count = widgets_of(client.get("/d/tasks").text)
    texts = re.findall(r'<tr><td><a href="[^"]+">([^<]*)</a></td>', listed)
    url = [u for u in links(listed) if u.startswith("/tasks?")][0]
    assert query(url) == [("when", "overdue"), ("when", "today"), ("when", "week")]
    assert texts and texts == task_texts(client.get(url).text)
    number = re.search(r'<p class="widget-count"><a href="([^"]+)"[^>]*>(\d+)</a>', count)
    assert int(number.group(2)) == len(task_texts(client.get(html.unescape(number.group(1))).text)) == 1


def test_contacts_and_messages_widgets_link_rows_to_their_records(client, folder):
    write(folder, "people", """\
title = "People"
[[widget]]
type = "list"
scope = "contacts"
filters = { company_name = "northwind" }

[[widget]]
type = "list"
scope = "messages"
filters = { channel = ["linkedin"], status = ["unknown"] }
columns = ["date", "company_name", "channel"]
""")
    people, sent = widgets_of(client.get("/d/people").text)
    rows = re.findall(r'<tr><td><a href="/companies/([^"]+)">', people)
    assert rows == ["northwind-robotics/contacts/jonas-brandt",
                    "northwind-robotics/contacts/lena-vogt"]
    url = [u for u in links(people) if u.startswith("/contacts?")][0]
    assert contact_keys(client.get(url).text) == rows
    edit = re.findall(r'<tr><td><a href="(/companies/[^"]+/interactions/[^"]+/edit)">', sent)
    # sent in the last 14 days with no reply yet: only Copperleaf's
    assert edit == ["/companies/copperleaf-studio/interactions/"
                    "2026-09-09T1000-linkedin-out-camille-martin/edit"]
    assert client.get(edit[0]).status_code == 200
    url = [u for u in links(sent) if u.startswith("/messages?")][0]
    assert message_keys(client.get(url).text) == [("2026-09-09 10:00", "copperleaf-studio")]


def test_custom_fields_filter_and_one_not_shown_in_the_list_is_explained(client, folder):
    write(folder, "scores", """\
title = "Scores"
[[widget]]
type = "count"
scope = "companies"
filters = { my_score = ">6", fte_estimate = "*" }

[[widget]]
type = "count"
scope = "companies"
filters = { ae_count = ">1" }
""")
    page = client.get("/d/scores").text
    (count,) = widgets_of(page)  # the second widget has a problem, so it is not drawn
    number = re.search(r'<p class="widget-count"><a href="([^"]+)"[^>]*>(\d+)</a>', count)
    url = html.unescape(number.group(1))
    assert query(url) == [("f_my_score", ">6"), ("f_fte_estimate", "*")]
    expected = ["bluefin-analytics", "northwind-robotics", "quartzline-logistics"]
    assert int(number.group(2)) == 3
    assert sorted(company_slugs(client.get(url).text)) == expected
    assert ('dashboards/scores.toml: widget 2: unknown filter key ae_count (ae_count is a '
            'company field the companies list does not show; add "companies" to its '
            'show_in in fields.toml)') in html.unescape(page)


# ---------------------------------------------------------------- validation


def problems(folder: Path) -> list[str]:
    return dashboards.validate(folder)


def test_a_valid_dashboard_has_no_problems(folder):
    write(folder, "monday-review", MONDAY)
    assert problems(folder) == []


def test_near_miss_names_get_a_did_you_mean(folder):
    write(folder, "monday", """\
title = "Monday"
pinned = true

[[widget]]
type = "list"
scope = "companies"
columns = ["name", "myscore"]
filters = { stge = "prospect" }
sort = "-my_scor"

[[widget]]
type = "lst"
scope = "companies"

[[widget]]
type = "count"
scope = "company"

[[widget]]
type = "group"
scope = "companies"
by = "contry"

[[widget]]
type = "report"
section = "funel"
period = "30days"

[[widget]]
type = "count"
scope = "companies"
filtres = { stage = "prospect" }
columns = ["name"]
""")
    assert problems(folder) == [
        "dashboards/monday.toml: top level: unknown key pinned (did you mean pin?)",
        "dashboards/monday.toml: widget 1: unknown filter key stge (did you mean stage?)",
        "dashboards/monday.toml: widget 1: unknown column myscore (did you mean my_score?)",
        "dashboards/monday.toml: widget 1: unknown sort column my_scor (did you mean my_score?)",
        "dashboards/monday.toml: widget 2: unknown type lst (did you mean list?); "
        "use list, count, group or report",
        "dashboards/monday.toml: widget 3: unknown scope company (did you mean companies?); "
        "use companies, contacts, messages or tasks",
        "dashboards/monday.toml: widget 4: unknown by column contry (did you mean country?)",
        "dashboards/monday.toml: widget 5: unknown report section funel (did you mean funnel?); "
        "use activity, funnel, outcomes, messages, sources or hygiene",
        "dashboards/monday.toml: widget 5: unknown period 30days (did you mean 30d?); "
        "use 7d, 30d, 90d, quarter, ytd or all",
        "dashboards/monday.toml: widget 6: unknown key filtres (did you mean filters?)",
        "dashboards/monday.toml: widget 6: a count widget takes no columns",
    ]


def test_the_spec_example_message_word_for_word(folder):
    (folder / "fields.toml").write_text(
        '[[field]]\nkey = "fit_score"\ntype = "number"\nshow_in = ["detail", "companies"]\n',
        encoding="utf-8")
    write(folder, "monday", 'title = "Monday"\n[[widget]]\ntype = "count"\nscope = "companies"\n'
                            '[[widget]]\ntype = "list"\nscope = "companies"\n'
                            'columns = ["name", "fitscore"]\n')
    assert problems(folder) == [
        "dashboards/monday.toml: widget 2: unknown column fitscore (did you mean fit_score?)"]


def test_toml_syntax_errors_name_the_line(folder):
    write(folder, "broken", 'title = "Broken"\n\n[[widget]]\ntype = "list\nscope = "companies"\n')
    (msg,) = problems(folder)
    assert msg.startswith("dashboards/broken.toml: line 4: ") and "(column " in msg


def test_value_problems(folder):
    write(folder, "values", """\
description = 3
pin = "yes"

[[widget]]
type = "list"
scope = "companies"
limit = "ten"
filters = { stage = "prospekt", my_score = ">=5", last_touch = ">yesterday", name = "", tags = 5, country = ["DE", 7] }

[[widget]]
type = "list"
scope = "companies"
limit = 0
columns = []
filters = { next_step_due = "<=2026-10-01", name = ["a", "b"], source = "!" }

[[widget]]
type = "count"
scope = "companies"
when = "today"
filters = { my_score = "<x", tags = "!" }

[[widget]]
type = "list"
scope = "tasks"
when = ["overdu"]

[[widget]]
title = 7

[[widget]]
type = "group"
scope = "companies"
""")
    assert problems(folder) == [
        "dashboards/values.toml: top level: title is missing (every dashboard needs one)",
        "dashboards/values.toml: top level: pin must be true or false",
        "dashboards/values.toml: top level: description must be text in quotes",
        "dashboards/values.toml: widget 1: limit must be a whole number above 0, not 'ten'",
        "dashboards/values.toml: widget 1: filter stage: unknown value 'prospekt' (did you "
        "mean prospect?); one of: prospect, engaged, discovery, offer, won, lost, "
        "disqualified, temp-disqualified",
        "dashboards/values.toml: widget 1: filter my_score: '>=5': only > and < exist; "
        "for 5 or more write >4",
        "dashboards/values.toml: widget 1: filter last_touch: '>yesterday': last_touch is a "
        "date, so compare with YYYY-MM-DD",
        "dashboards/values.toml: widget 1: filter name: empty filter; leave the key out, or "
        "use \"-\" for empty",
        "dashboards/values.toml: widget 1: filter tags: write the filter in quotes, e.g. "
        "\">5\" or \"=5\", not 5",
        "dashboards/values.toml: widget 1: filter country: values must be text in quotes, "
        "not 7",
        "dashboards/values.toml: widget 2: limit must be a whole number above 0, not 0",
        "dashboards/values.toml: widget 2: filter next_step_due: '<=2026-10-01': only > and "
        "< exist; for 2026-10-01 or earlier write <2026-10-02",
        "dashboards/values.toml: widget 2: filter name: only a column with fixed values "
        "(like stage) takes a list; write one filter in quotes",
        "dashboards/values.toml: widget 2: filter source: unknown value '!'; one of: "
        "linkedin-search, referral, inbound, event, list, network, other",
        "dashboards/values.toml: widget 2: columns is empty; leave it out for the default "
        "columns",
        "dashboards/values.toml: widget 3: filter my_score: '<x': my_score is a number, so "
        "compare with a number",
        "dashboards/values.toml: widget 3: filter tags: '!' needs text after !",
        "dashboards/values.toml: widget 3: when is for tasks widgets only",
        "dashboards/values.toml: widget 4: unknown when overdu (did you mean overdue?); use "
        "overdue, today, week, later or none",
        "dashboards/values.toml: widget 5: type is missing (list, count, group or report)",
        "dashboards/values.toml: widget 6: by is missing (the column to count per value)",
    ]


def test_file_level_problems(folder):
    write(folder, "Weekly Review", 'title = "Weekly"\n[[widget]]\ntype = "count"\n'
                                   'scope = "companies"\n')
    write(folder, "empty", 'title = "Empty"\n')
    write(folder, "single", 'title = "Single"\n[widget]\ntype = "count"\nscope = "companies"\n')
    write(folder, "unknown-key", 'title = "Keys"\n[[widget]]\ntype = "count"\n'
                                 'scope = "companies"\nfilters = { value_eur_month = ">1" }\n')
    assert problems(folder) == [
        "dashboards/Weekly Review.toml: file name: use lower-case letters, digits and hyphens, "
        "like monday-review.toml (the page is /d/<file name>)",
        "dashboards/empty.toml: top level: no widgets yet: add one [[widget]] table per widget",
        "dashboards/single.toml: top level: write each widget as a [[widget]] table (two "
        "brackets)",
        "dashboards/unknown-key.toml: widget 1: unknown filter key value_eur_month; the "
        "companies list has: name, country, stage, source, my_score, fte_estimate, tags, "
        "last_touch, next_step, next_step_due",
    ]


def test_check_prints_the_problems_and_fails(folder, capsys):
    assert cli.main(["--data", str(folder), "check"]) == 0
    clean = capsys.readouterr().out
    write(folder, "monday-review", MONDAY)
    assert cli.main(["--data", str(folder), "check"]) == 0
    assert capsys.readouterr().out == clean  # a valid dashboard changes nothing
    write(folder, "bad", 'title = "Bad"\n[[widget]]\ntype = "count"\nscope = "companys"\n')
    assert cli.main(["--data", str(folder), "check"]) == 1
    assert capsys.readouterr().out == (
        "dashboards/bad.toml: widget 1: unknown scope companys (did you mean companies?); "
        "use companies, contacts, messages or tasks\n")


def test_check_knows_the_task_types_in_use(folder, capsys):
    store = Store(folder, clock=lambda: FIXED_NOW)
    store.load()
    write(folder, "calls", 'title = "Calls"\n[[widget]]\ntype = "count"\nscope = "companies"\n'
                           'filters = { next_type = ["call"] }\n')
    assert any("unknown filter key next_type" in m
               for m in dashboards.validate(folder, store=store))
    (folder / "config.toml").write_text(
        (folder / "config.toml").read_text() + '\ntask_types = ["call", "email"]\n')
    assert dashboards.validate(folder, store=store) == []


# ------------------------------------------------------------ the page itself


def test_an_invalid_file_shows_a_banner_and_the_widgets_that_work(client, folder):
    write(folder, "half", """\
title = "Half"
[[widget]]
type = "count"
scope = "companies"
filters = { tags = "saas" }

[[widget]]
type = "list"
scope = "companies"
columns = ["name", "fitscore"]
""")
    page = client.get("/d/half")
    assert page.status_code == 200
    body = html.unescape(main_of(page.text))
    assert "1 problem in dashboards/half.toml." in re.sub(r"<[^>]+>", "", body)
    assert "dashboards/half.toml: widget 2: unknown column fitscore" in body
    assert "hermitcrm check" in body
    assert len(widgets_of(page.text)) == 1 and ">2</a></p>" in widgets_of(page.text)[0]


def test_a_file_that_does_not_parse_still_renders(client, folder):
    write(folder, "broken", 'title = "Broken"\n[[widget]\n')
    page = client.get("/d/broken")
    assert page.status_code == 200
    assert "dashboards/broken.toml: line 2: " in html.unescape(page.text)
    assert widgets_of(page.text) == []


def test_a_widget_that_fails_while_drawing_joins_the_problems(client, folder, monkeypatch):
    write(folder, "monday-review", MONDAY)

    def boom(*a, **kw):
        raise RuntimeError("kaput")

    monkeypatch.setattr(dashboards, "_count_view", boom)
    page = client.get("/d/monday-review")
    assert page.status_code == 200
    assert "dashboards/monday-review.toml: widget 2: could not be drawn (kaput)" in page.text
    assert len(widgets_of(page.text)) == 3


def test_unknown_dashboard_is_a_404_page_listing_the_others(client, folder):
    write(folder, "monday-review", MONDAY)
    page = client.get("/d/nope")
    assert page.status_code == 404
    assert "No dashboard called" in page.text and 'href="/d/monday-review"' in page.text
    assert client.get("/d/..%2Fconfig").status_code == 404


def test_title_description_and_adjust_link(client, folder):
    write(folder, "monday-review", MONDAY)
    page = client.get("/d/monday-review").text
    assert "<title>Monday review</title>" in page
    assert "<h1>Monday review</h1>" in page and "What to work on this week." in page
    assert '<a class="button" href="/yours">Adjust</a>' in page
    assert 'href="/help/adjust-dashboards"' in nav_of(page)


# ------------------------------------------------------------------ pinning


def test_pinned_dashboards_are_in_the_sidebar_of_every_page(client, folder):
    write(folder, "monday-review", MONDAY)
    write(folder, "accounts", 'title = "Accounts"\npin = true\n[[widget]]\ntype = "count"\n'
                              'scope = "companies"\n')
    write(folder, "hidden", 'title = "Hidden"\n[[widget]]\ntype = "count"\nscope = "companies"\n')
    assert dashboards.pins(folder) == [{"title": "Accounts", "url": "/d/accounts"},
                                       {"title": "Monday review", "url": "/d/monday-review"}]
    for path in ("/", "/pipeline", "/companies", "/reports", "/settings", "/d/hidden"):
        nav = nav_of(client.get(path).text)
        assert re.findall(r'href="(/d/[^"]+)"', nav) == ["/d/accounts", "/d/monday-review"], path
        # in the nav, just before Settings
        assert nav.index("/d/monday-review") < nav.index('href="/settings')
    nav = nav_of(client.get("/d/monday-review").text)
    assert re.search(r'<a href="/d/monday-review" data-tour="dashboard" class="active"', nav)
    assert "Monday review</span>" in nav


def test_an_edit_shows_on_the_next_request_without_a_restart(client, folder):
    write(folder, "monday-review", MONDAY)
    assert "Monday review</span>" in nav_of(client.get("/companies").text)
    write(folder, "monday-review", MONDAY.replace("Monday review", "Weekly review"))
    page = client.get("/companies").text
    assert "Weekly review</span>" in nav_of(page) and "Monday review" not in page
    write(folder, "monday-review", MONDAY.replace("pin = true", "pin = false"))
    assert "/d/monday-review" not in nav_of(client.get("/companies").text)
    write(folder, "monday-review", MONDAY.replace("limit = 2", "limit = 1"))
    first = widgets_of(client.get("/d/monday-review").text)[0]
    assert "1 of 3" in first
    (folder / "dashboards" / "monday-review.toml").unlink()
    assert client.get("/d/monday-review").status_code == 404


def test_no_dashboards_folder_is_todays_behaviour(client, folder, capsys):
    assert not (folder / "dashboards").exists()
    for path in ("/", "/companies", "/reports"):
        page = client.get(path)
        assert page.status_code == 200 and "/d/" not in nav_of(page.text)
    assert dashboards.load_all(folder) == [] and dashboards.pins(folder) == []
    assert dashboards.validate(folder) == [] and dashboards.built_items(folder) == []
    assert cli.main(["--data", str(folder), "check"]) == 0
    assert capsys.readouterr().out.startswith("OK: 8 companies")
    (folder / "dashboards").mkdir()
    (folder / "dashboards" / "README.md").write_text("notes, not a dashboard\n")
    assert dashboards.load_all(folder) == [] and dashboards.validate(folder) == []


# ------------------------------------------------------------- built items


def test_built_items(folder):
    write(folder, "monday-review", MONDAY)
    write(folder, "one", 'title = "One"\n[[widget]]\ntype = "count"\nscope = "companys"\n')
    write(folder, "broken", 'title = "Broken"\n[[widget]\n')
    assert dashboards.built_items(folder) == [
        {"kind": "dashboard", "title": "broken", "url": "/d/broken",
         "detail": "cannot be read; run hermitcrm check",
         "adjust": "Change the dashboard broken: …"},
        {"kind": "dashboard", "title": "Monday review", "url": "/d/monday-review",
         "detail": "4 widgets, pinned",
         "adjust": "Change the dashboard Monday review: …"},
        {"kind": "dashboard", "title": "One", "url": "/d/one",
         "detail": "1 widget, not pinned; 1 problem",
         "adjust": "Change the dashboard One: …"},
    ]


# ---------------------------------------------- the rest of Hermit ignores it


def git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=folder, check=True, capture_output=True,
                          text=True).stdout.strip()


def commit_dashboard(folder: Path, text: str, message: str) -> None:
    write(folder, "monday-review", text)
    git(folder, "add", "dashboards")
    git(folder, "-c", "user.name=CRM Test", "-c", "user.email=crm@test.local",
        "commit", "-q", "-m", message)


def test_store_rebuild_migrate_and_doctor_leave_the_folder_alone(folder, tmp_path, capsys):
    commit_dashboard(folder, MONDAY, "ai: adjust: dashboard Monday review")
    before = (folder / "dashboards" / "monday-review.toml").read_bytes()
    store = Store(folder, clock=lambda: FIXED_NOW)
    assert store.load() == [] and len(store.companies) == 8
    assert cli.main(["--data", str(folder), "rebuild"]) == 0
    # A pending migration scans the folder for its files; dashboards are not among them.
    migrations.write_format(folder, migrations.LATEST - 1)
    planned = migrations.dry_run(folder)
    assert f"{migrations.LATEST - 1}" in planned and "dashboards" not in planned
    migrations.write_format(folder, migrations.LATEST)
    checks = doctor.run_checks(folder, env={}, which=lambda n: "/usr/bin/git",
                               platform="linux", home=tmp_path / "home",
                               update_fetcher=lambda: "0.0.1",
                               update_cache=tmp_path / "update.json")
    assert not [c for c in checks if c.status == doctor.FAIL]
    assert (folder / "dashboards" / "monday-review.toml").read_bytes() == before
    assert git(folder, "status", "--porcelain") == ""


def test_backup_and_restore_carry_dashboards(folder, tmp_path):
    commit_dashboard(folder, MONDAY, "ai: adjust: dashboard Monday review")
    good = git(folder, "rev-parse", "HEAD")
    home = tmp_path / "home"
    assert backup.run(folder, {}, home=home, now=FIXED_NOW).code == 0
    commit_dashboard(folder, MONDAY.replace("Monday", "Broken"), "ai: adjust: oops")
    out, sha = backup.restore(folder, good[:10], ["dashboards/monday-review.toml"],
                              apply=True, home=home, now=FIXED_NOW)
    assert out.code == 0 and sha
    assert (folder / "dashboards" / "monday-review.toml").read_text() == MONDAY


# --------------------------------------------------------------------- help


def test_the_recipe_lists_every_scope_column_and_widget_option(folder):
    text = helpdocs.read("adjust-dashboards")
    assert text and helpdocs.topic_for("/d/monday-review") == "adjust-dashboards"
    columns, _ = dashboards.folder_columns(folder)
    from hermitcrm.web import company_columns, task_columns
    every = {
        "companies": [c.key for c in company_columns([], ["call"])],
        "contacts": [c.key for c in columns["contacts"]],
        "messages": [c.key for c in columns["messages"]],
        "tasks": [c.key for c in task_columns(["call"])],
    }
    for scope, keys in every.items():
        assert f"`{scope}`" in text
        for key in keys:
            assert f"`{key}`" in text, (scope, key)
    for word in (*dashboards.TYPES, *dashboards.SECTIONS, *dashboards.PERIODS,
                 *dashboards.WHEN, *dashboards.ALL_WIDGET_KEYS, *dashboards.TOP_KEYS):
        assert f"`{word}`" in text, word
    assert "hermitcrm check" in text and "ai: adjust: dashboard" in text
    assert "Monday review" in text
