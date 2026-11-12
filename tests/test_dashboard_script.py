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

"""scripts/dashboard.py: the local page over what downloads.py collected (not part of the package).

The counting rules are tested in test_downloads_script.py; here: the page uses
them (so it cannot disagree with `report`), fills quiet days with zeros, escapes
what it prints, and the Refresh button runs `collect` and reports failures.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import dashboard as db  # noqa: E402
import downloads as dl  # noqa: E402

TARBALL = "/download/hermitcrm-0.7.0.tar.gz"


def pypi_row(installer, n, day, ci="false", version="0.7.0", country="DE"):
    return {"day": day, "version": version, "type": "bdist_wheel", "installer": installer, "country": country,
            "python": "3.13", "system": "Darwin", "ci": ci, "downloads": n}


def hit(n, day, *, ua="Mozilla/5.0 (Macintosh)", q=""):
    return {"t": f"{day}T10:00:{n:02d}+00:00", "id": f"id{n}", "method": "GET", "path": TARBALL, "q": q,
            "status": 200, "bytes": 738969, "ua": ua, "sf": "cross-site", "su": "?1"}


def seed(tmp_path):
    dl.merge_csv(tmp_path / "pypi-downloads.csv", dl.PYPI_FIELDS, dl.PYPI_FIELDS[:-1], [
        pypi_row("pip", 3, "2026-10-01"), pypi_row("uv", 2, "2026-10-04", country="NL"),
        pypi_row("uv", 5, "2026-10-04", ci="true"), pypi_row("Browser", 40, "2026-10-04"),
        pypi_row("bandersnatch", 20, "2026-10-04")])
    dl.merge_csv(tmp_path / "github-assets.csv", dl.ASSET_FIELDS, ["day", "tag", "asset"],
                 [{"day": "2026-10-05", "tag": "v0.7.0", "asset": "hermitcrm-0.7.0.tar.gz", "downloads": 4}])
    dl.merge_csv(tmp_path / "github-traffic.csv", dl.TRAFFIC_FIELDS, ["day"],
                 [{"day": "2026-10-03", "clones": 9, "clones_unique": 3, "views": 7, "views_unique": 2}])
    rows = [hit(1, "2026-10-02"), hit(2, "2026-10-04", ua="Slackbot-LinkExpanding 1.0"),
            hit(3, "2026-10-04", q="own"), hit(4, "2026-10-04")]
    (tmp_path / "website.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_summary_counts_what_report_counts_and_leaves_out_the_rest(tmp_path):
    seed(tmp_path)
    s = db.summarize(tmp_path, today="2026-10-05")
    assert s["tiles"] == {"best": 5 + 4 + 2, "pypi": 5, "github": 4, "website": 2}
    assert dict(s["filtered"])["PyPI: pip/uv in CI"] == 5
    assert dict(s["filtered"])["PyPI: browser downloads"] == 40
    assert dict(s["filtered"])["PyPI: mirrors"] == 20
    assert dict(s["filtered"])["Website: bots and crawlers"] == 1
    assert dict(s["filtered"])["Website: yours (?own, selftest, ignore.txt)"] == 1


def test_summary_has_a_column_for_every_day_including_quiet_ones(tmp_path):
    seed(tmp_path)
    s = db.summarize(tmp_path, today="2026-10-05")
    assert s["days"] == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"]
    assert s["downloads_per_day"]["PyPI installs"] == [3, 0, 0, 2, 0]
    assert s["downloads_per_day"]["Website downloads"] == [0, 1, 0, 1, 0]
    assert s["github_traffic"]["Unique visitors"] == [0, 0, 2, 0, 0]
    assert all(len(v) == len(s["days"]) for v in s["downloads_per_day"].values())


def test_summary_of_an_empty_folder_is_all_zeros_and_renders(tmp_path):
    s = db.summarize(tmp_path, today="2026-10-05")
    assert s["tiles"]["best"] == 0 and s["days"] == ["2026-10-05"]
    page = db.render(s, live=True)
    assert "No data saved yet" in page and 'id="refresh"' in page


def test_versions_table_puts_each_channel_in_its_own_column(tmp_path):
    seed(tmp_path)
    s = db.summarize(tmp_path, today="2026-10-05")
    assert s["versions"] == {"0.7.0": {"pypi": 5, "website": 2, "github": 4}}


def test_page_escapes_what_it_prints_and_keeps_data_from_closing_its_script(tmp_path):
    seed(tmp_path)
    dl.merge_csv(tmp_path / "pypi-downloads.csv", dl.PYPI_FIELDS, dl.PYPI_FIELDS[:-1],
                 [pypi_row("pip", 1, "2026-10-02", country="<script>x</script>")])
    (tmp_path / "status.json").write_text(json.dumps({"pypi": {"ok": False, "error": "</script><b>no</b>"}}))
    page = db.render(db.summarize(tmp_path, today="2026-10-05"), live=False)
    assert "<script>x</script>" not in page and "&lt;script&gt;x&lt;/script&gt;" in page
    assert "<b>no</b>" not in page
    assert 'id="refresh"' not in page and "Static copy" in page


def serve_in_thread(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), db.make_handler(tmp_path))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_server_shows_the_page_and_refresh_runs_collect_and_names_failures(tmp_path, monkeypatch):
    seed(tmp_path)
    calls = []

    def fake_collect(data_dir):
        calls.append(data_dir)
        (data_dir / "status.json").write_text(json.dumps({"pypi": {"ok": True}, "website": {"ok": False}}))
        return 1

    monkeypatch.setattr(dl, "collect", fake_collect)
    server, url = serve_in_thread(tmp_path)
    try:
        page = urllib.request.urlopen(url + "/").read().decode()
        assert "Hermit CRM numbers" in page and 'id="refresh"' in page
        reply = json.loads(urllib.request.urlopen(urllib.request.Request(url + "/refresh", method="POST")).read())
        assert reply == {"ok": False, "failed": ["website"]} and calls == [tmp_path]
        try:
            urllib.request.urlopen(url + "/refresh")                # a GET must not collect
        except urllib.error.HTTPError as e:
            assert e.code == 404
        assert len(calls) == 1
    finally:
        server.shutdown()


def seed_visits(tmp_path):
    def view(n, day, **kw):
        row = {"t": f"{day}T09:00:{n:02d}+00:00", "id": f"v{n}", "method": "GET", "h": "hermitcrm.io",
               "path": "/index.html", "q": "", "status": 200, "ua": "Mozilla/5.0 (Macintosh)",
               "ref": "news.example.com", "sf": "cross-site", "sd": "document", "sm": "navigate"}
        return {**row, **kw}
    rows = [view(1, "2026-10-04"), view(2, "2026-10-04", path="/compare/folk/index.html", sf="same-origin", ref=""),
            view(3, "2026-10-05", ref=""), view(4, "2026-10-05", ua="GPTBot/1.1", sf="", sd=""),
            view(5, "2026-10-05", ua="Slackbot 1.0", sf="", sd="")]
    (tmp_path / "visits.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_summary_counts_arrivals_not_clicks_between_pages_and_names_the_home_page(tmp_path):
    seed(tmp_path)
    seed_visits(tmp_path)
    v = db.summarize(tmp_path, today="2026-10-05")["visits"]
    assert (v["arrivals"], v["page_views"], v["ai"]) == (2, 3, 1)
    assert v["per_day"]["Arrivals"] == [0, 0, 0, 1, 1]
    assert v["ai_per_day"]["AI crawlers and assistants"] == [0, 0, 0, 0, 1]
    assert v["pages"] == {"/": 2, "/compare/folk/": 1}
    assert v["sources"] == {"news.example.com": 1, "direct": 1}
    assert v["ai_names"] == {"GPTBot": 1}
    assert dict(v["left_out"])["Bots and link previews"] == 1


def test_page_without_a_page_log_says_so_and_with_one_has_the_charts(tmp_path):
    seed(tmp_path)
    assert db.summarize(tmp_path, today="2026-10-05")["visits"] is None
    assert "No page log saved yet" in db.render(db.summarize(tmp_path, today="2026-10-05"), live=True)
    seed_visits(tmp_path)
    page = db.render(db.summarize(tmp_path, today="2026-10-05"), live=True)
    assert 'data-chart="visits"' in page and "Arrivals on the website" in page


def test_a_tagged_link_is_counted_by_its_ref_or_utm_source(tmp_path):
    seed(tmp_path)
    seed_visits(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / "visits.jsonl").read_text().splitlines()]
    rows[0]["q"] = "ref=hn"
    rows[2]["q"] = "utm_source=newsletter&utm_medium=mail"
    (tmp_path / "visits.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert db.summarize(tmp_path, today="2026-10-05")["visits"]["campaigns"] == {"hn": 1, "newsletter": 1}
    assert db.campaign({"q": ""}) == "" and db.campaign({}) == ""


def test_github_section_shows_the_latest_snapshot_and_new_stars_per_day(tmp_path):
    seed(tmp_path)
    dl.merge_csv(tmp_path / "github-repo.csv", dl.REPO_FIELDS, ["day"],
                 [{"day": "2026-10-04", "stars": 3, "forks": 0, "watchers": 1},
                  {"day": "2026-10-05", "stars": 5, "forks": 1, "watchers": 1}])
    dl.merge_csv(tmp_path / "github-stars.csv", dl.STARS_FIELDS, ["day"], [{"day": "2026-10-03", "stars": 2}])
    dl.merge_csv(tmp_path / "github-referrers.csv", dl.REFERRER_FIELDS, ["day", "referrer"],
                 [{"day": "2026-10-04", "referrer": "old.example.com", "count": 9, "uniques": 9},
                  {"day": "2026-10-05", "referrer": "news.example.com", "count": 4, "uniques": 3}])
    s = db.summarize(tmp_path, today="2026-10-05")
    assert (s["github"]["stars"], s["github"]["forks"], s["github"]["as_of"]) == (5, 1, "2026-10-05")
    assert s["github"]["referrers"] == {"news.example.com": 3}
    assert s["stars_per_day"]["New stars"] == [0, 0, 2, 0, 0]
    assert 'data-chart="stars"' in db.render(s, live=True)
    assert "<h2>GitHub</h2>" not in db.render(db.summarize(tmp_path / "nowhere", today="2026-10-05"), live=True)


def test_the_default_port_is_not_the_apps_own_and_a_busy_port_is_explained(capsys):
    assert db.PORT != 8765                                        # `hermitcrm serve` uses it
    taken = ThreadingHTTPServer(("127.0.0.1", 0), db.make_handler(Path(".")))
    try:
        assert db.serve(Path("."), taken.server_address[1], open_browser=False) == 1
    finally:
        taken.server_close()
    assert "--port" in capsys.readouterr().err


def test_visitors_come_above_the_downloads_and_the_range_buttons_above_both(tmp_path):
    seed(tmp_path)
    for with_log in (False, True):
        if with_log:
            seed_visits(tmp_path)
        page = db.render(db.summarize(tmp_path, today="2026-10-05"), live=True)
        assert page.index("data-range") < page.index("<h2>Visitors</h2>") < page.index("<h2>All time</h2>")


# --- live view: the last 24 hours in 10-minute columns ---------------------------------

NOW = datetime(2026, 10, 5, 14, 37, 20, tzinfo=timezone.utc)     # inside the 14:30 slot


def seen(n, minutes_ago, **kw):
    """A page request `minutes_ago` before NOW, written the way nginx writes it."""
    t = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    row = {"t": t, "id": f"live{n}", "method": "GET", "h": "hermitcrm.io", "path": "/index.html", "q": "",
           "status": 200, "ua": "Mozilla/5.0 (Macintosh)", "ref": "news.example.com", "sf": "cross-site",
           "sd": "document", "sm": "navigate"}
    return {**row, **kw}


def live_of(tmp_path, rows, now=NOW):
    (tmp_path / "visits.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return db.live_for(tmp_path, now)


def test_live_has_144_ten_minute_slots_ending_in_the_one_still_filling(tmp_path):
    live = live_of(tmp_path, [])
    assert len(live["slots"]) == 144 and all(len(v) == 144 for v in live["series"].values())
    assert live["slots"][-1] == "2026-10-05T14:30:00Z" and live["slots"][0] == "2026-10-04T14:40:00Z"
    assert live["now"] == "2026-10-05T14:37:20Z" and live["last_arrival"] is None and live["recent"] == []


def test_live_puts_each_request_in_its_slot_and_keeps_arrivals_views_and_ai_apart(tmp_path):
    live = live_of(tmp_path, [
        seen(1, 2),                                                      # 14:35 -> the last slot, an arrival
        seen(2, 6, sf="same-origin", ref=""),                            # 14:31 -> last slot, a click inside the site
        seen(3, 8),                                                      # 14:29 -> the slot before
        seen(4, 3, ua="GPTBot/1.1", sf="", sd=""),                       # an AI fetch
        seen(5, 1, ua="Slackbot 1.0", sf="", sd=""),                     # a link preview: not a person
        seen(6, 1, q="own"),                                             # yours
        seen(7, 24 * 60 + 30),                                           # older than the window
    ])
    s = live["series"]
    assert s["Arrivals"][-2:] == [1, 1] and s["Other page views"][-2:] == [0, 1]
    assert s["AI crawlers and assistants"][-1] == 1
    assert sum(s["Arrivals"]) == 2 and sum(s["Other page views"]) == 1


def test_live_tiles_slide_with_the_clock_instead_of_the_slot_edges(tmp_path):
    live = live_of(tmp_path, [seen(1, 9), seen(2, 11), seen(3, 59), seen(4, 61), seen(5, 600)])
    assert live["tiles"] == {"arrivals_10m": 1, "arrivals_1h": 3, "arrivals_24h": 5, "views_1h": 3}
    assert live["last_arrival"] == "2026-10-05T14:28:20Z"


def test_live_lists_the_newest_page_views_first_with_where_they_came_from_and_their_tag(tmp_path):
    live = live_of(tmp_path, [seen(1, 30, q="ref=hn"), seen(2, 5, path="/compare/folk/index.html", sf="same-origin", ref=""),
                              seen(3, 12, ref="")])
    assert [r["page"] for r in live["recent"]] == ["/compare/folk/", "/", "/"]
    assert [r["arrival"] for r in live["recent"]] == [False, True, True]
    assert [r["from"] for r in live["recent"]] == ["direct", "direct", "news.example.com"]
    assert [r["tag"] for r in live["recent"]] == ["", "", "hn"]
    assert len(live_of(tmp_path, [seen(n, n) for n in range(1, 40)])["recent"]) == db.LIVE_RECENT


def test_live_follows_the_time_zone_of_the_log_not_of_this_computer(tmp_path):
    row = seen(1, 2)
    row["t"] = "2026-10-05T16:35:20+02:00"                               # the same moment as 14:35 UTC
    assert live_of(tmp_path, [row])["series"]["Arrivals"][-1] == 1


def test_live_leaves_out_what_ignore_txt_says_is_yours(tmp_path):
    (tmp_path / "ignore.txt").write_text("live1  # my own check\n")
    assert live_of(tmp_path, [seen(1, 2), seen(2, 3)])["tiles"]["arrivals_10m"] == 1


def test_there_is_no_live_view_before_a_page_log_exists(tmp_path):
    seed(tmp_path)
    assert db.live_for(tmp_path, NOW) is None and db.summarize(tmp_path, today="2026-10-05")["live"] is None
    assert 'id="live-status"' not in db.render(db.summarize(tmp_path, today="2026-10-05"), live=True)


def test_the_page_has_the_live_panel_above_the_range_buttons_and_says_where_it_came_from(tmp_path):
    seed(tmp_path)
    (tmp_path / "status.json").write_text(json.dumps({"visits": {"ok": True, "last_ok": "2026-10-05T14:36:00+00:00"}}))
    (tmp_path / "visits.jsonl").write_text(json.dumps(seen(1, 2)) + "\n")
    s = db.summarize(tmp_path, today="2026-10-05", now=NOW)
    assert s["live"]["collected"] == "2026-10-05T14:36:00+00:00"
    page = db.render(s, live=True)
    assert page.index("<h2>Live</h2>") < page.index("data-range") < page.index("<h2>Visitors</h2>")
    assert "data-live-chart" in page and 'id="live-recent"' in page and '<body data-live="on">' in page
    assert '<body data-live="off">' in db.render(s, live=False)


def test_what_visitors_put_in_the_log_cannot_break_out_of_the_page(tmp_path):
    seed(tmp_path)
    (tmp_path / "visits.jsonl").write_text(json.dumps(seen(1, 2, path="/</script><b>x</b>/", ref="</script>.example")) + "\n")
    page = db.render(db.summarize(tmp_path, today="2026-10-05", now=NOW), live=True)
    assert "</script><b>" not in page and "<\\/script><b>x<\\/b>" in page
    # The page writes these strings with textContent, never innerHTML.
    assert "innerHTML" not in page


def test_the_live_refresh_collects_only_the_page_log_and_answers_with_the_new_numbers(tmp_path, monkeypatch):
    seed(tmp_path)
    fresh = datetime.now(timezone.utc) - timedelta(minutes=2)
    ran = []

    def pull(data_dir):
        ran.append(data_dir)
        row = {**seen(1, 0), "t": fresh.isoformat()}
        (data_dir / "visits.jsonl").write_text(json.dumps(row) + "\n")
        return "1 lines on the volume, 1 saved"

    monkeypatch.setattr(dl, "LIVE_SOURCES", {"visits": pull})
    monkeypatch.setattr(dl, "SOURCES", {"pypi": lambda _: (_ for _ in ()).throw(AssertionError("ran the full collect"))})
    server, url = serve_in_thread(tmp_path)
    try:
        reply = json.loads(urllib.request.urlopen(urllib.request.Request(url + "/live/refresh", method="POST")).read())
        assert reply["ok"] and reply["error"] == "" and ran == [tmp_path]
        assert reply["live"]["tiles"]["arrivals_10m"] == 1 and reply["live"]["recent"][0]["page"] == "/"
        try:
            urllib.request.urlopen(url + "/live/refresh")                  # a GET must not collect
        except urllib.error.HTTPError as e:
            assert e.code == 404
        assert len(ran) == 1
    finally:
        server.shutdown()


def test_a_failed_live_refresh_still_answers_with_what_is_saved_and_says_why(tmp_path, monkeypatch):
    seed(tmp_path)
    (tmp_path / "visits.jsonl").write_text(json.dumps(seen(1, 2)) + "\n")

    def down(_):
        raise RuntimeError("flyctl exited 1: no started VMs")

    monkeypatch.setattr(dl, "LIVE_SOURCES", {"visits": down})
    server, url = serve_in_thread(tmp_path)
    try:
        reply = json.loads(urllib.request.urlopen(urllib.request.Request(url + "/live/refresh", method="POST")).read())
        assert reply["ok"] is False and "no started VMs" in reply["error"]
        assert reply["live"] is not None and reply["live"]["slots"]
    finally:
        server.shutdown()
