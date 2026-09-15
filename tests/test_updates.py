"""Update check with a fake fetcher: cache, 24h interval, opt-outs, version parser."""

import json
import threading

from owncrm import updates

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
    assert json.loads(cache.read_text()) == {"checked": 1000.0, "latest": "9.9.9"}
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
                         env={"OWNCRM_NO_UPDATE_CHECK": "1"}) == ""
    assert calls == [] and not (tmp_path / "x.json").exists()


def test_background_notice_never_blocks(tmp_path, monkeypatch):
    monkeypatch.delenv("OWNCRM_NO_UPDATE_CHECK", raising=False)
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
    from owncrm import __version__
    from owncrm.web import create_app

    (tmp_path / "companies").mkdir()
    app = create_app(tmp_path, config={"push_enabled": False, "update_check": True})
    client = TestClient(app)
    page = client.get("/companies").text
    assert f"OwnCRM v{__version__}" in page and "available:" not in page
    app.state.update_notice.available = "9.9.9"
    page = client.get("/companies").text
    assert "v9.9.9 available: <code>pipx upgrade owncrm</code>" in page
