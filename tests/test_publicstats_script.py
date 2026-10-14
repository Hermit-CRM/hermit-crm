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

"""scripts/publicstats.py: the numbers on https://hermitcrm.io/stats/ (not part of the package).

The counting rules are tested in test_downloads_script.py and test_dashboard_script.py;
here: what is kept out of public view (small counts, the hide list, user agents, ids,
"yours"), that the output is the same bytes for the same input, and that `publish`
uploads only when something changed and reports a failure.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import downloads as dl  # noqa: E402
import publicstats as ps  # noqa: E402

TODAY = "2026-10-14"
SECRET_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) Fixture/9.9"


def view(n, day="2026-10-10", **kw):
    row = {"t": f"{day}T09:00:{n % 60:02d}+00:00", "id": f"req-{n:04d}", "method": "GET", "h": "hermitcrm.io",
           "path": "/index.html", "q": "", "status": 200, "ua": SECRET_UA, "ref": "news.example.com",
           "sf": "cross-site", "sd": "document", "sm": "navigate"}
    return {**row, **kw}


def seed(tmp_path):
    rows = []
    n = 0

    def add(count, **kw):
        nonlocal n
        for _ in range(count):
            n += 1
            rows.append(view(n, **kw))

    add(5)                                                    # news.example.com: 5, listed
    add(3, ref="blog.example.org")                            # exactly K, listed
    add(2, ref="mail.someone.example")                        # below K, into Other
    add(50, ref="hidden.example.net")                         # hidden by public-hide.txt
    add(4, ref="<b>x</b>.example.com")                        # needs escaping
    add(3, q="ref=launch")                                    # a tagged link
    add(4, ua="Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)", sf="", sd="")
    add(2, ua="Mozilla/5.0 (compatible; GPTBot/1.1)", sf="", sd="")
    add(1, q="own")                                           # yours
    add(3, day="2026-06-01", ref="old.example.com")           # before the 90 days
    (tmp_path / "visits.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    dl.merge_csv(tmp_path / "pypi-downloads.csv", dl.PYPI_FIELDS, dl.PYPI_FIELDS[:-1], [
        {"day": "2026-10-01", "version": "0.7.0", "type": "bdist_wheel", "installer": "pip", "country": "DE",
         "python": "3.13", "system": "Darwin", "ci": "false", "downloads": 7},
        {"day": "2026-10-02", "version": "0.7.0", "type": "bdist_wheel", "installer": "uv", "country": "IS",
         "python": "3.12", "system": "Linux", "ci": "false", "downloads": 1}])
    dl.merge_csv(tmp_path / "github-repo.csv", dl.REPO_FIELDS, ["day"],
                 [{"day": "2026-10-13", "stars": 42, "forks": 3, "watchers": 2}])
    (tmp_path / "public-hide.txt").write_text("# private\nhidden.example.net\n")
    (tmp_path / "status.json").write_text(json.dumps({
        "pypi": {"ok": True, "last_ok": "2026-10-14T04:00:00+00:00", "detail": "secret detail"},
        "github": {"ok": False, "last_ok": "2026-10-11T04:00:00+00:00", "error": "token expired"},
        "visits": {"ok": True, "last_ok": "2026-10-14T04:00:00+00:00"}}))


def test_fold_keeps_k_and_up_and_sums_the_rest_into_other():
    counts = {"a.example.com": 5, "b.example.com": 3, "c.example.com": 2, "d.example.com": 1, "e.example.com": 9}
    assert ps.fold(counts, hide={"e.example.com"}) == [["a.example.com", 5], ["b.example.com", 3], ["Other", 3]]
    assert ps.fold({"x": 4, "y": 4, "z": 5}, top=2) == [["z", 5], ["x", 4], ["Other", 4]]
    assert ps.fold({"x": 1}, hide={"x"}) == []


def test_small_hosts_go_to_other_and_hidden_ones_disappear(tmp_path):
    seed(tmp_path)
    v = ps.public_numbers(tmp_path, TODAY)["visitors"]
    sources = dict(v["sources"])
    assert sources["news.example.com"] == 5 + 3 and sources["blog.example.org"] == 3   # the tagged link came from news
    assert "mail.someone.example" not in sources and sources["Other"] == 2
    assert "old.example.com" not in sources                                            # outside the window
    assert v["tags"] == [["launch", 3]]
    out = json.dumps(ps.public_numbers(tmp_path, TODAY))
    assert "hidden.example.net" not in out and "mail.someone.example" not in out


def test_nothing_identifying_is_published(tmp_path):
    seed(tmp_path)
    out = json.dumps(ps.public_numbers(tmp_path, TODAY)) + ps.render_fragment(ps.public_numbers(tmp_path, TODAY))
    assert SECRET_UA not in out and "Fixture/9.9" not in out and "req-0" not in out
    assert "claudebot@anthropic.com" not in out and "T09:00" not in out
    assert "secret detail" not in out and "token expired" not in out
    assert "yours" not in out.lower()
    names = dict(ps.public_numbers(tmp_path, TODAY)["ai"]["names"])
    assert names == {"ClaudeBot": 4, "GPTBot": 2}


def test_series_cover_ninety_days_ending_today(tmp_path):
    seed(tmp_path)
    n = ps.public_numbers(tmp_path, TODAY)
    assert len(n["days"]) == 90 and n["days"][-1] == TODAY and n["days"][0] == "2026-07-17"
    for series in (n["visitors"]["per_day"], n["downloads"]["per_day"], n["github"]["stars_per_day"]):
        assert all(len(values) == 90 for values in series.values())
    assert n["visitors"]["per_day"]["Arrivals"][n["days"].index("2026-10-10")] == 5 + 3 + 2 + 50 + 4 + 3
    assert n["tiles"] == {"arrivals_30d": 67, "downloads": 8, "stars": 42, "ai_30d": 6}
    assert n["downloads"]["countries"] == [["DE", 7], ["Other", 1]]


def test_a_failed_source_shows_as_stale_with_its_last_good_day(tmp_path):
    seed(tmp_path)
    n = ps.public_numbers(tmp_path, TODAY)
    assert n["sources"]["github"] == {"ok": False, "last_ok": "2026-10-11"}
    page = ps.render_fragment(n)
    assert "The GitHub numbers have not been updated since 11 October 2026." in page
    assert "The PyPI numbers" not in page


def test_the_fragment_is_safe_for_the_sites_csp_and_escapes_names(tmp_path):
    seed(tmp_path)
    page = ps.render_fragment(ps.public_numbers(tmp_path, TODAY))
    assert "style=" not in page and "<script" not in page
    assert "<b>x</b>" not in page and "&lt;b&gt;x&lt;/b&gt;.example.com" in page
    assert page.startswith('<section class="stats">') and "<html" not in page and "<body" not in page
    assert "Numbers up to 14 October 2026. Updated every day." in page
    assert 'role="img" aria-label="Arrivals per day, last 90 days, 67 arrivals in total"' in page
    assert "<title>2026-10-10: 67 arrivals</title>" in page


def test_build_gives_the_same_bytes_twice(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    seed(data)
    first = ps.build(data, TODAY, tmp_path / "a")
    second = ps.build(data, TODAY, tmp_path / "b")
    assert first == second
    assert (tmp_path / "a" / "numbers.html").read_bytes() == (tmp_path / "b" / "numbers.html").read_bytes()
    stats = json.loads((tmp_path / "a" / "stats.json").read_text())
    assert stats["schema"] == 1 and stats["generated"] == "2026-10-14T00:00:00Z"


def test_an_empty_data_folder_still_renders(tmp_path):
    files = ps.build(tmp_path, TODAY, tmp_path / "public")
    page = files["numbers.html"].decode()
    assert "No data yet." in page and "Numbers up to 14 October 2026." in page
    assert json.loads(files["stats.json"])["visitors"] is None


def test_publish_uploads_only_when_the_numbers_changed(tmp_path, monkeypatch):
    seed(tmp_path)
    calls = []
    monkeypatch.setattr(dl, "fly_ssh", lambda cmd: calls.append(("ssh", cmd)))
    monkeypatch.setattr(dl, "fly_put", lambda path, data: calls.append(("put", path)))
    assert ps.publish(tmp_path, TODAY) == 0
    assert calls == [("ssh", "mkdir -p /data/public"), ("put", "/data/public/numbers.html"),
                     ("put", "/data/public/stats.json")]
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["publish"]["ok"] and status["pypi"]["detail"] == "secret detail"   # collect's entries stay

    calls.clear()
    assert ps.publish(tmp_path, TODAY) == 0
    assert calls == []                                             # unchanged: nothing uploaded
    assert ps.publish(tmp_path, TODAY, force=True) == 0 and len(calls) == 3
    calls.clear()
    assert ps.publish(tmp_path, "2026-10-15") == 0 and len(calls) == 3   # a new day is a change


def test_a_failed_upload_exits_1_and_is_recorded(tmp_path, monkeypatch):
    seed(tmp_path)
    monkeypatch.setattr(dl, "fly_ssh", lambda cmd: None)

    def boom(path, data):
        raise RuntimeError("flyctl exited 1: no access token")
    monkeypatch.setattr(dl, "fly_put", boom)
    assert ps.publish(tmp_path, TODAY) == 1
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["publish"]["ok"] is False and "no access token" in status["publish"]["error"]
    assert not (tmp_path / "public" / ".published.sha256").exists()   # the next run tries again

    monkeypatch.setattr(dl, "fly_put", lambda path, data: None)
    assert ps.publish(tmp_path, TODAY) == 0
    assert "error" not in json.loads((tmp_path / "status.json").read_text())["publish"]


def test_it_runs_from_a_copy_of_the_three_scripts(tmp_path):
    # launchd runs copies in the data folder, with no checkout around them.
    for name in ("downloads.py", "dashboard.py", "publicstats.py"):
        shutil.copy(ROOT / "scripts" / name, tmp_path / name)
    data = tmp_path / "data"
    data.mkdir()
    seed(data)
    done = subprocess.run([sys.executable, "publicstats.py", "--data-dir", str(data), "build", "--today", TODAY],
                          cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert (data / "public" / "numbers.html").exists() and (data / "public" / "stats.json").exists()
