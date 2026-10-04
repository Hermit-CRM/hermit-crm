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
