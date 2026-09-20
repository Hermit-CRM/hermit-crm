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

"""Update check with a fake fetcher: cache, 24h interval, opt-outs, version parser."""

import json
import threading
import urllib.error

from hermitcrm import updates

DAY = 24 * 60 * 60


def fake(version, calls):
    def fetch():
        calls.append(1)
        return version
    return fetch


def test_version_parser():
    assert updates.is_newer("0.1.1", "0.1.0") and updates.is_newer("0.10.0", "0.9.9")
    assert updates.is_newer("1.0", "0.99.99") and not updates.is_newer("0.1.0", "0.1")
    assert not updates.is_newer("0.2.0rc1", "0.2.0") and updates.is_newer("0.2.0", "0.2.0rc1")
    assert updates.is_newer("0.2.0rc1", "0.1.9") and not updates.is_newer("garbage", "0.1.0")
    assert updates.is_newer("v2.0.0", "1.9")


def test_check_caches_for_24_hours(tmp_path):
    cache, calls = tmp_path / "c/update.json", []
    got = updates.check({}, fetcher=fake("9.9.9", calls), cache=cache, now=1000.0, env={},
                        current="0.1.0")
    assert got == "9.9.9" and len(calls) == 1
    assert json.loads(cache.read_text()) == {"checked": 1000.0, "latest": "9.9.9",
                                             "state": "current", "url": updates.PYPI_URL}
    again = updates.check({}, fetcher=fake("10.0.0", calls), cache=cache,
                          now=1000.0 + DAY - 1, env={}, current="0.1.0")
    assert again == "9.9.9" and len(calls) == 1  # cached, no request
    later = updates.check({}, fetcher=fake("10.0.0", calls), cache=cache,
                          now=1000.0 + DAY + 1, env={}, current="0.1.0")
    assert later == "10.0.0" and len(calls) == 2


def test_same_or_older_version_and_failures_show_nothing(tmp_path):
    calls = []
    assert updates.check({}, fetcher=fake("0.1.0", calls), cache=tmp_path / "a.json",
                         now=0.0, env={}, current="0.1.0") == ""

    def offline():
        raise OSError("no network")

    assert updates.check({}, fetcher=offline, cache=tmp_path / "b.json", now=0.0, env={},
                         current="0.1.0") == ""
    assert json.loads((tmp_path / "b.json").read_text())["latest"] == ""  # retry tomorrow


def test_opt_outs(tmp_path):
    calls = []
    assert updates.check({"update_check": False}, fetcher=fake("9.0", calls),
                         cache=tmp_path / "x.json", env={}) == ""
    assert updates.check({}, fetcher=fake("9.0", calls), cache=tmp_path / "x.json",
                         env={"HERMITCRM_NO_UPDATE_CHECK": "1"}) == ""
    assert calls == [] and not (tmp_path / "x.json").exists()


def test_background_notice_never_blocks(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMITCRM_NO_UPDATE_CHECK", raising=False)
    gate = threading.Event()

    def slow():
        gate.wait(5)
        return "99.0.0"

    notice = updates.UpdateNotice()
    thread = notice.start({}, fetcher=slow, cache=tmp_path / "u.json")
    assert thread is not None and notice.available == ""  # returned immediately
    gate.set()
    thread.join(5)
    assert notice.available == "99.0.0"
    assert updates.UpdateNotice().start({"update_check": False}) is None


def test_footer_version_and_nav_notice(tmp_path):
    from fastapi.testclient import TestClient
    from hermitcrm import __version__
    from hermitcrm.web import create_app

    (tmp_path / "companies").mkdir()
    app = create_app(tmp_path, config={"push_enabled": False, "update_check": True})
    client = TestClient(app)
    page = client.get("/companies").text
    assert f"Hermit CRM v{__version__}" in page and "available:" not in page
    app.state.update_notice.available = "9.9.9"
    page = client.get("/companies").text
    assert "v9.9.9 available: <code>pipx upgrade hermitcrm</code>" in page


# ---------------------------------------------------------- what the check knows
# The old check returned "" for three different things -- up to date, nothing
# published yet, and no network -- so `doctor` said "is the latest" for a check that
# had never once succeeded. These tests exist to keep those three apart.


def http_error(code):
    def fetch():
        raise urllib.error.HTTPError(updates.PYPI_URL, code, "nope", {}, None)
    return fetch


def test_a_404_says_nothing_is_published_not_that_we_are_current(tmp_path):
    result = updates.look({}, fetcher=http_error(404), cache=tmp_path / "a.json",
                          now=0.0, env={}, current="0.3.0")
    assert result.state == updates.ABSENT and result.newer == ""
    assert result.sentence("0.3.0") == "v0.3.0; no release published at pypi.org yet"
    assert "is the latest" not in result.sentence("0.3.0")


def test_offline_and_a_500_are_unreachable_not_current(tmp_path):
    def offline():
        raise OSError("no network")

    for name, fetcher in (("b", offline), ("c", http_error(500))):
        result = updates.look({}, fetcher=fetcher, cache=tmp_path / f"{name}.json",
                              now=0.0, env={}, current="0.3.0")
        assert result.state == updates.UNREACHABLE
        assert result.sentence("0.3.0").endswith("could not reach pypi.org to check")


def test_reaching_the_index_is_the_only_way_to_be_current(tmp_path):
    result = updates.look({}, fetcher=fake("0.3.0", []), cache=tmp_path / "d.json",
                          now=0.0, env={}, current="0.3.0")
    assert result.state == updates.CURRENT and result.sentence("0.3.0") == "v0.3.0 is the latest"


def test_a_custom_url_is_asked_and_changes_the_upgrade_hint(tmp_path):
    """Any URL answering {"version": ...} works, so a static file on a site is enough."""
    config = {"update_url": "https://hermitcrm.example/latest.json"}
    assert updates.source_url(config) == "https://hermitcrm.example/latest.json"
    result = updates.look(config, fetcher=fake("0.4.0", []), cache=tmp_path / "e.json",
                          now=0.0, env={}, current="0.3.0")
    assert result.state == updates.NEWER and result.newer == "0.4.0"
    assert result.hint == "download it from hermitcrm.example"
    assert updates.upgrade_hint(updates.PYPI_URL) == updates.UPGRADE_HINT


def test_changing_the_url_invalidates_a_fresh_cache(tmp_path):
    """Yesterday's answer was about somewhere else; it must not be reused."""
    cache, calls = tmp_path / "f.json", []
    updates.look({}, fetcher=fake("0.4.0", calls), cache=cache, now=1000.0, env={},
                 current="0.3.0")
    again = updates.look({"update_url": "https://elsewhere.example/v.json"},
                         fetcher=fake("0.9.0", calls), cache=cache, now=1001.0, env={},
                         current="0.3.0")
    assert again.newer == "0.9.0" and len(calls) == 2


def test_both_answer_shapes_parse():
    assert updates.version_in({"info": {"version": "1.2.3"}}) == "1.2.3"
    assert updates.version_in({"version": "1.2.3"}) == "1.2.3"
    assert updates.version_in({"latest": "1.2.3"}) == "1.2.3"


def test_a_fresh_notice_has_not_checked_anything():
    notice = updates.UpdateNotice()
    assert notice.result.state == updates.PENDING and notice.available == ""
    assert updates.note(notice.result) == "update check has not run yet"


def test_a_failed_check_is_retried_within_the_hour_not_the_day(tmp_path):
    """A check started at boot can miss the network by a second. Honest is not the
    same as stuck: only an answer earns a full day in the cache."""
    def offline():
        raise OSError("no network")

    cache, calls = tmp_path / "g.json", []
    assert updates.look({}, fetcher=offline, cache=cache, now=0.0, env={},
                        current="0.3.0").state == updates.UNREACHABLE
    still = updates.look({}, fetcher=fake("9.9.9", calls), cache=cache, now=600.0, env={},
                         current="0.3.0")
    assert still.state == updates.UNREACHABLE and calls == []  # 10 minutes: cached
    later = updates.look({}, fetcher=fake("9.9.9", calls), cache=cache,
                         now=updates.RETRY_INTERVAL + 1, env={}, current="0.3.0")
    assert later.newer == "9.9.9" and len(calls) == 1  # an hour on: asked again

    # An answer, even "nothing published here", still holds for the full day.
    absent = tmp_path / "h.json"
    updates.look({}, fetcher=http_error(404), cache=absent, now=0.0, env={}, current="0.3.0")
    held = updates.look({}, fetcher=fake("9.9.9", calls), cache=absent,
                        now=updates.RETRY_INTERVAL + 1, env={}, current="0.3.0")
    assert held.state == updates.ABSENT and len(calls) == 1  # not asked again
