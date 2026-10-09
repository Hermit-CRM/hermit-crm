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

"""scripts/downloads.py: the maintainer's download counter (not part of the package).

The network sources are not tested here; the parts that decide what a number
means are: what counts as a real install, which website requests are bots or
yours, and that a failing source never stops the others.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("downloads_script", ROOT / "scripts" / "downloads.py")
dl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dl)

TARBALL = "/download/hermitcrm-0.6.0.tar.gz"
FULL = 738969


def hit(n, *, ua="Mozilla/5.0 (Macintosh)", q="", status=200, bytes_=FULL, method="GET", path=TARBALL):
    return {"t": f"2026-10-04T10:00:{n:02d}+00:00", "id": f"id{n}", "method": method, "path": path,
            "q": q, "status": status, "bytes": bytes_, "ua": ua}


def pypi_row(installer, n=1, ci="false", day="2026-10-02"):
    return {"day": day, "version": "0.5.0", "type": "bdist_wheel", "installer": installer, "country": "DE",
            "python": "3.13", "system": "Darwin", "ci": ci, "downloads": n}


def test_merge_csv_replaces_the_same_key_and_keeps_the_rest(tmp_path):
    path = tmp_path / "x.csv"
    fields = ["day", "category", "downloads"]
    dl.merge_csv(path, fields, ["day", "category"], [
        {"day": "2026-10-02", "category": "a", "downloads": 5},
        {"day": "2026-10-03", "category": "a", "downloads": 1}])
    total = dl.merge_csv(path, fields, ["day", "category"], [{"day": "2026-10-03", "category": "a", "downloads": 9}])
    assert total == 2
    assert [(r["day"], r["downloads"]) for r in dl.read_csv(path)] == [("2026-10-02", "5"), ("2026-10-03", "9")]


def test_parse_log_skips_ssh_chatter_and_rows_without_an_id():
    text = "\n".join(["Connecting to fdaa::1... complete", json.dumps(hit(1)), "{not json",
                      json.dumps({"path": TARBALL}), json.dumps(hit(2))])
    assert [r["id"] for r in dl.parse_log(text)] == ["id1", "id2"]


def test_website_events_sorts_requests_into_mine_bots_aborted_and_downloads():
    rows = [
        hit(1),                                                   # a visitor
        hit(2, ua="curl/8.7.1"),                                  # curl is a person, not a bot
        hit(3, ua="Slackbot-LinkExpanding 1.0"),                  # link preview
        hit(4, ua=""),                                            # no user agent
        hit(5, q="own"),                                          # Gijs, with ?own on the link
        hit(6, ua="hermitcrm-selftest/1"),                        # Gijs, with curl -A
        hit(7, bytes_=10_000),                                    # gave up early
        hit(8, method="HEAD", bytes_=0),                          # ignored
        hit(9, status=206, bytes_=1_000),                         # ignored (a range request)
        hit(10, status=404, bytes_=150),                          # ignored
    ]
    out = dl.website_events(rows)
    assert [r["id"] for r in out["downloads"]] == ["id1", "id2"]
    assert [r["id"] for r in out["bots"]] == ["id3", "id4"]
    assert [r["id"] for r in out["mine"]] == ["id5", "id6"]
    assert [r["id"] for r in out["aborted"]] == ["id7"]


def test_a_browser_name_without_fetch_metadata_is_a_scanner_not_a_person():
    # A link scanner that borrows a browser's name sends no Sec-Fetch-Site; a person's browser does.
    person = dict(hit(1), sf="same-origin", su="?1")
    from_a_github_link = dict(hit(2), sf="cross-site", su="?1")
    typed_in_the_address_bar = dict(hit(3), sf="none", su="?1")
    scanner = dict(hit(4), sf="", su="")
    curl = dict(hit(5, ua="curl/8.7.1"), sf="", su="")           # not a browser, so not judged on it
    before_the_field_existed = hit(6)                            # no "sf" key: judged on the user agent alone
    out = dl.website_events([person, from_a_github_link, typed_in_the_address_bar, scanner, curl,
                             before_the_field_existed])
    assert [r["id"] for r in out["downloads"]] == ["id1", "id2", "id3", "id5", "id6"]
    assert [r["id"] for r in out["bots"]] == ["id4"]


def test_ignore_txt_moves_requests_to_yours_without_deleting_anything(tmp_path):
    (tmp_path / "ignore.txt").write_text("# verification curls, 4 Oct\nid2   # 0.5.0\n\n")
    assert dl.read_ignored(tmp_path) == {"id2"}
    assert dl.read_ignored(tmp_path / "nowhere") == set()
    out = dl.website_events([hit(1, ua="curl/8.7.1"), hit(2, ua="curl/8.7.1")], dl.read_ignored(tmp_path))
    assert [r["id"] for r in out["downloads"]] == ["id1"]
    assert [r["id"] for r in out["mine"]] == ["id2"]


def test_website_events_judges_completeness_per_file():
    old = "/download/hermitcrm-0.5.0.tar.gz"
    rows = [hit(1, path=old, bytes_=552796), hit(2), hit(3, path=old, bytes_=552796)]
    assert len(dl.website_events(rows)["downloads"]) == 3        # 0.5.0 is smaller; that is not "aborted"


def test_pypi_bucket_only_calls_a_package_manager_an_install():
    bucket = lambda i, ci="false": dl.pypi_bucket(pypi_row(i, ci=ci))
    assert bucket("pip") == bucket("uv") == "installs"
    assert bucket("uv", ci="true") == "ci"
    assert bucket("bandersnatch") == bucket("Nexus") == "mirrors"
    assert bucket("Browser") == "browser"
    assert bucket("requests") == "scripts"
    assert bucket("") == "unknown"
    assert bucket("Go-http-client") == "other"


def test_report_separates_installs_from_browsers_scripts_and_mirrors(tmp_path, capsys):
    dl.merge_csv(tmp_path / "pypi-downloads.csv", dl.PYPI_FIELDS, dl.PYPI_FIELDS[:-1],
                 [pypi_row("pip", 3), pypi_row("uv", 2), pypi_row("Browser", 40), pypi_row("requests", 30),
                  pypi_row("", 100), pypi_row("bandersnatch", 20)])
    dl.merge_csv(tmp_path / "github-assets.csv", dl.ASSET_FIELDS, ["day", "tag", "asset"],
                 [{"day": "2026-10-04", "tag": "v0.6.0", "asset": "hermitcrm-0.6.0.tar.gz", "downloads": 4}])
    (tmp_path / "website.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [hit(1), hit(2, q="own")]))
    dl.report(tmp_path)
    out = capsys.readouterr().out
    assert "PyPI     195 downloads in total" in out
    assert "5  pip/uv installs" in out
    assert "Best estimate of real downloads: 5 + 4 + 1 = 10" in out
    assert "Everything counted, bots and mirrors included: 195 + 4 + 2 = 201" in out


def test_report_before_any_collect_says_so(tmp_path, capsys):
    dl.report(tmp_path)
    assert "run `downloads.py collect` first" in capsys.readouterr().out


def test_the_log_pull_starts_a_stopped_machine_and_retries_while_it_boots(monkeypatch):
    # `flyctl ssh` refuses a stopped machine ("no started VMs"); the site's machine
    # is stopped whenever nobody is looking, so the pull has to start it itself.
    calls = []

    def fake_run(cmd, timeout=180):
        calls.append(cmd[1])
        if cmd[1] == "machines":
            return json.dumps([{"id": "m1", "state": "stopped"}])
        if calls.count("ssh") == 1:
            raise RuntimeError("flyctl exited 1: app hermitcrm has no started VMs")
        return "Connecting to fdaa::1... complete\n" + json.dumps(hit(1)) + "\n"

    started = []
    monkeypatch.setattr(dl, "run", fake_run)
    monkeypatch.setattr(dl.subprocess, "run", lambda cmd, **kw: started.append(cmd))
    monkeypatch.setattr(dl.time, "sleep", lambda seconds: None)
    assert [r["id"] for r in dl.parse_log(dl.ssh_cat("/data/downloads.log"))] == ["id1"]
    assert started and started[0][:3] == ["flyctl", "machine", "start"] and "m1" in started[0]


def test_the_log_pull_gives_up_after_six_tries(monkeypatch):
    def always_fails(cmd, timeout=180):
        if cmd[1] == "machines":
            return "[]"
        raise RuntimeError("no started VMs")

    monkeypatch.setattr(dl, "run", always_fails)
    monkeypatch.setattr(dl.time, "sleep", lambda seconds: None)
    try:
        dl.ssh_cat("/data/downloads.log")
    except RuntimeError as e:
        assert "no started VMs" in str(e)
    else:
        raise AssertionError("expected the failure to surface so collect reports it")


def test_collect_survives_a_failing_source_and_says_so(tmp_path, monkeypatch, capsys):
    def boom(_):
        raise RuntimeError("flyctl exited 1: no access token")
    monkeypatch.setattr(dl, "SOURCES", {"pypi": lambda _: "fine", "website": boom, "github": lambda _: "fine"})
    assert dl.collect(tmp_path) == 1
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["pypi"]["ok"] and status["github"]["ok"]
    assert not status["website"]["ok"] and "no access token" in status["website"]["error"]
    captured = capsys.readouterr()
    assert "collect FAILED: website" in captured.err
    assert "pypi: ok" in captured.out and "github: ok" in captured.out

    monkeypatch.setattr(dl, "SOURCES", {"website": lambda _: "fine"})
    assert dl.collect(tmp_path) == 0                              # the next good run clears the failure
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["website"]["ok"] and "error" not in status["website"]


def view(n, *, ua="Mozilla/5.0 (Macintosh)", sf="cross-site", sd="document", q="", status=200, host="hermitcrm.io",
         ref="news.example.com", path="/index.html", method="GET"):
    return {"t": f"2026-10-05T09:00:{n:02d}+00:00", "id": f"v{n}", "method": method, "h": host, "path": path,
            "q": q, "status": status, "ua": ua, "ref": ref, "sf": sf, "sd": sd, "sm": "navigate"}


def test_visit_events_sorts_page_views_into_people_ai_bots_scripts_and_mine():
    rows = [
        view(1),                                                         # a person from a link
        view(2, sf="same-origin", ref=""),                               # the same person, next page
        view(3, ua="Mozilla/5.0 (compatible; GPTBot/1.1)", sf="", sd=""),  # an AI crawler
        view(4, ua="Mozilla/5.0 AppleWebKit; ChatGPT-User/1.0", sf="", sd=""),
        view(5, ua="Slackbot-LinkExpanding 1.0", sf="", sd=""),          # a link preview
        view(6, ua=""),                                                  # no user agent
        view(7, ua="Mozilla/5.0 (X11)", sf="", sd=""),                   # a browser name, no fetch metadata
        view(8, ua="curl/8.7.1", sf="", sd=""),                          # a script, not a visitor
        view(9, q="own"),                                                # Gijs
        view(10, host="hermitcrm.fly.dev"),                              # the noindex copy
        view(11, status=404),                                            # ignored
        view(12, method="HEAD"),                                         # ignored
    ]
    out = dl.visit_events(rows)
    assert [r["id"] for r in out["people"]] == ["v1", "v2"]
    assert [r["id"] for r in out["ai"]] == ["v3", "v4"]
    assert [r["id"] for r in out["bots"]] == ["v5", "v6", "v7"]
    assert [r["id"] for r in out["scripts"]] == ["v8"]
    assert [r["id"] for r in out["mine"]] == ["v9", "v10"]


def test_an_arrival_is_a_view_that_began_outside_the_site():
    assert dl.is_arrival(view(1, sf="cross-site")) and dl.is_arrival(view(2, sf="none"))
    assert not dl.is_arrival(view(3, sf="same-origin"))
    assert dl.count_hosts([view(1), view(2), view(3, ref="")]) == {"news.example.com": 2, "direct": 1}


def test_ai_name_says_which_crawler():
    assert dl.ai_name("Mozilla/5.0 (compatible; GPTBot/1.1; +https://openai.com/gptbot)") == "GPTBot"
    assert dl.ai_name("Mozilla/5.0 (X11)") == ""


def test_visits_is_one_of_the_sources_collect_runs():
    assert list(dl.SOURCES) == ["pypi", "github", "website", "visits"]


def test_the_visit_pull_treats_a_missing_log_as_not_deployed_yet(tmp_path, monkeypatch):
    def no_file(path):
        raise RuntimeError("flyctl exited 1: cat: can't open '/data/visits.log': No such file or directory")
    monkeypatch.setattr(dl, "ssh_cat", no_file)
    assert "no page log" in dl.collect_visits(tmp_path)
    monkeypatch.setattr(dl, "ssh_cat", lambda path: (_ for _ in ()).throw(RuntimeError("no started VMs")))
    try:
        dl.collect_visits(tmp_path)
    except RuntimeError as e:
        assert "no started VMs" in str(e)
    else:
        raise AssertionError("a real failure must reach collect")


def test_the_visit_pull_merges_by_id_so_a_second_pull_loses_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "ssh_cat", lambda path: json.dumps(view(1)) + "\n" + json.dumps(view(2)) + "\n")
    dl.collect_visits(tmp_path)
    monkeypatch.setattr(dl, "ssh_cat", lambda path: json.dumps(view(2)) + "\n" + json.dumps(view(3)) + "\n")
    assert "3 saved" in dl.collect_visits(tmp_path)


def test_report_counts_arrivals_apart_from_page_views(tmp_path, capsys):
    rows = [view(1), view(2, sf="same-origin", ref=""), view(3, ua="GPTBot/1.1", sf="", sd="")]
    (tmp_path / "visits.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    dl.report(tmp_path)
    out = capsys.readouterr().out
    assert "Visitors 1 arrivals, 2 page views by people" in out
    assert "1  AI crawlers and assistants" in out and "from news.example.com" in out


def test_report_without_a_page_log_says_to_deploy(tmp_path, capsys):
    dl.report(tmp_path)
    assert "no page log saved yet" in capsys.readouterr().out


def test_stars_are_counted_per_day_and_the_newest_snapshot_wins():
    assert dl.stars_per_day(["2026-10-01T08:00:00Z", "2026-10-01T09:30:00Z", "2026-10-03T00:00:00Z"]) == {
        "2026-10-01": 2, "2026-10-03": 1}
    rows = [{"day": "2026-10-01", "referrer": "a.example.com", "uniques": "9"},
            {"day": "2026-10-02", "referrer": "a.example.com", "uniques": "2"},
            {"day": "2026-10-02", "referrer": "b.example.com", "uniques": "5"}]
    assert [r["referrer"] for r in dl.latest_snapshot(rows, "uniques")] == ["b.example.com", "a.example.com"]
    assert dl.latest_snapshot([], "uniques") == []


def test_collect_github_saves_stars_forks_referrers_and_pages(tmp_path, monkeypatch):
    answers = {
        "releases": [{"tag_name": "v0.7.0", "assets": [{"name": "hermitcrm-0.7.0.tar.gz", "download_count": 3}]}],
        "traffic/clones": {"clones": [{"timestamp": "2026-10-04T00:00:00Z", "count": 5, "uniques": 2}]},
        "traffic/views": {"views": [{"timestamp": "2026-10-04T00:00:00Z", "count": 7, "uniques": 3}]},
        "traffic/popular/referrers": [{"referrer": "news.example.com", "count": 8, "uniques": 4}],
        "traffic/popular/paths": [{"path": "/example-org/example-repo", "title": "x", "count": 9, "uniques": 5}],
    }

    def fake_run(cmd, timeout=180):
        endpoint = cmd[2]
        if "stargazers" in endpoint:
            return "2026-10-01T08:00:00Z\n2026-10-01T09:00:00Z\n"
        for key, value in answers.items():
            if endpoint.endswith(key) or (key == "releases" and "releases" in endpoint):
                return json.dumps(value)
        return json.dumps({"stargazers_count": 2, "forks_count": 1, "subscribers_count": 1})   # the repo itself

    monkeypatch.setattr(dl, "run", fake_run)
    assert "2 stars" in dl.collect_github(tmp_path)
    assert [(r["day"], r["stars"]) for r in dl.read_csv(tmp_path / "github-stars.csv")] == [("2026-10-01", "2")]
    assert [r["referrer"] for r in dl.read_csv(tmp_path / "github-referrers.csv")] == ["news.example.com"]
    assert [r["path"] for r in dl.read_csv(tmp_path / "github-paths.csv")] == ["/example-org/example-repo"]
    repo = dl.read_csv(tmp_path / "github-repo.csv")
    assert (repo[0]["stars"], repo[0]["forks"], repo[0]["watchers"]) == ("2", "1", "1")
