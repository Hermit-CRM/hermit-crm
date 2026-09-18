"""The /settings page: sections, the /setup and /inbox redirects, the enrichment
and outcomes forms, and the review queue (the former inbox) inside it."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import setup as st
from hermitcrm.datafolder import init_folder
from hermitcrm.store import load_config
from hermitcrm.web import create_app

SECTIONS = ("you", "bcc", "calendar", "backup", "appearance", "enrichment", "outcomes", "inbox",
            "schedule", "about")


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "demo", demo=True)


def make_client(folder: Path, tmp_path: Path, **state):
    config = load_config(folder)
    config["push_enabled"] = False
    config["owner_email"] = config.get("owner_email") or "me@example.com"
    app = create_app(folder, config)
    app.state.setup_platform = "linux"
    app.state.schedule_home = tmp_path / "home"  # never the real ~/.config
    app.state.calendar_url = lambda refresh=False: ""
    for key, value in state.items():
        setattr(app.state, key, value)
    return app, TestClient(app, follow_redirects=False)


def token(client) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get("/settings").text).group(1)


def cfg(folder: Path) -> dict:
    return tomllib.loads((folder / "config.toml").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ the page


def test_settings_page_renders_every_section(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    r = client.get("/settings")
    assert r.status_code == 200
    page = r.text
    for section in SECTIONS:
        assert f'id="{section}"' in page, section
    nav = page.split("</nav>")[0]
    assert 'href="/settings"' in nav and "<span>Settings</span>" in nav
    for gone in ("/inbox", "/setup", "/companies/new", "/import"):
        assert f'href="{gone}"' not in nav
    assert 'href="/help/settings"' in nav
    # Enrichment: the resolved provider, or the reason with the launchd hint.
    if app.state.enricher.available:
        assert f"In use: {app.state.enricher.provider_name}" in page
    else:
        assert "Unavailable:" in page and "/opt/homebrew/bin" in page
    # Outcomes: the defaults, one per line, plus the two day counts.
    assert ">successful\nunsuccessful</textarea>" in page
    assert 'name="message_window_days" value="14"' in page
    assert 'name="silent_days" value="14"' in page
    # Review queue, schedule and about.
    assert "Nothing to review." in page and "Import meetings now" in page
    assert "hermitcrm-sync.timer: not installed" in page
    assert f"hermitcrm --data {demo} schedule install --serve" in page
    assert f"<code>{demo}</code>" in page and "hermitcrm --data" in page
    assert "Skip for now" in page  # BCC and backup are still pending in a demo folder
    assert '<span class="setup-status done">done</span>' in page.split('id="bcc"')[0]


def test_settings_page_offers_skip_while_setup_pending(tmp_path):
    folder = init_folder(tmp_path / "crm")
    config = load_config(folder)
    config["push_enabled"] = False
    app = create_app(folder, config)
    app.state.setup_platform = "linux"
    app.state.schedule_home = tmp_path / "home"
    client = TestClient(app, follow_redirects=False)
    assert client.get("/").headers["location"] == "/welcome"
    page = client.get("/settings").text
    assert 'href="/">Skip for now' in page


def test_old_urls_redirect_permanently(demo, tmp_path):
    _, client = make_client(demo, tmp_path)
    r = client.get("/setup")
    assert r.status_code == 301 and r.headers["location"] == "/settings"
    r = client.get("/inbox")
    assert r.status_code == 301 and r.headers["location"] == "/settings#inbox"


def test_setup_post_paths_work_under_both_prefixes(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    t = token(client)
    r = client.post("/settings/you", data={"csrf_token": t, "name": "Jane Doe",
                                           "addresses": "jane@example.com"})
    assert r.status_code == 303 and r.headers["location"].endswith("#you")
    assert r.headers["location"].startswith("/settings?flash=")
    r = client.post("/setup/you", data={"csrf_token": t, "name": "Jane Roe",
                                        "addresses": "jane@example.org"})
    assert r.status_code == 303 and r.headers["location"].startswith("/settings?flash=")
    assert cfg(demo)["owner_name"] == "Jane Roe"
    assert client.post("/settings/you", data={"name": "x", "addresses": "x@example.com"}
                       ).status_code == 403
    bad = client.post("/settings/you", data={"csrf_token": t, "name": "", "addresses": "nope"})
    assert bad.status_code == 400 and "Give your name." in bad.text
    assert 'id="inbox"' in bad.text  # the whole page re-renders, values kept


# ---------------------------------------------------------------- enrichment


def test_enrichment_saves_config_and_rebuilds_enricher(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    t = token(client)
    r = client.post("/settings/enrichment", data={
        "csrf_token": t, "provider": "custom", "command": "/nonexistent/bin/my-llm --json",
        "model": "big", "timeout": "42"})
    assert r.status_code == 303
    assert r.headers["location"].startswith("/settings?flash=Enrichment%20saved")
    assert r.headers["location"].endswith("#enrichment")
    c = cfg(demo)
    assert c["enrich_provider"] == "custom"
    assert c["enrich_command"] == "/nonexistent/bin/my-llm --json"
    assert c["enrich_model"] == "big" and c["enrich_timeout"] == 42
    assert "# AI CLI for Enrich: auto, claude, codex, gemini, grok or custom." in \
        (demo / "config.toml").read_text()
    assert app.state.config["enrich_provider"] == "custom"
    assert app.state.enricher.requested == "custom"
    assert app.state.enricher.timeout == 42.0
    page = client.get("/settings").text
    assert '<option value="custom" selected>' in page
    assert 'value="/nonexistent/bin/my-llm --json"' in page


def test_the_account_type_is_saved_and_reaches_the_enricher(demo, tmp_path):
    """Settings has to be able to say 'this CLI is signed in with a plan'."""
    app, client = make_client(demo, tmp_path)
    t = token(client)
    assert cfg(demo).get("enrich_account", "subscription") == "subscription"

    r = client.post("/settings/enrichment", data={
        "csrf_token": t, "provider": "codex", "account": "api", "timeout": "42"})
    assert r.status_code == 303
    assert cfg(demo)["enrich_account"] == "api"
    assert app.state.enricher.account == "api"

    r = client.post("/settings/enrichment", data={
        "csrf_token": t, "provider": "codex", "account": "nonsense", "timeout": "42"})
    assert r.status_code == 400 and "Account must be one of" in r.text
    assert cfg(demo)["enrich_account"] == "api"  # the bad value was not written


def test_enrichment_validation(demo, tmp_path):
    _, client = make_client(demo, tmp_path)
    t = token(client)
    r = client.post("/settings/enrichment", data={"csrf_token": t, "provider": "custom",
                                                  "command": "", "timeout": "x"})
    assert r.status_code == 400
    assert "A custom provider needs a command line." in r.text
    assert "Timeout (seconds) must be a whole number of at least 1." in r.text
    r = client.post("/settings/enrichment", data={"csrf_token": t, "provider": "nope",
                                                  "timeout": "10"})
    assert r.status_code == 400 and "Unknown provider" in r.text
    assert "enrich_provider" not in cfg(demo)
    assert client.post("/settings/enrichment", data={"provider": "auto"}).status_code == 403


def test_save_enrichment_function(tmp_path):
    folder = init_folder(tmp_path / "crm")
    assert st.ENRICH_PROVIDERS == ("auto", "claude", "codex", "gemini", "grok", "custom")
    r = st.save_enrichment(folder, " Codex ", "", " gpt-x ", " 90 ")
    assert r.ok and r.values == {"enrich_provider": "codex", "enrich_account": "subscription",
                                 "enrich_command": "",
                                 "enrich_model": "gpt-x", "enrich_model_strong": "",
                                 "ai_tier": "medium", "enrich_timeout": 90}
    assert cfg(folder)["enrich_provider"] == "codex" and cfg(folder)["enrich_timeout"] == 90
    bad = st.save_enrichment(folder, "custom", "", "", "0")
    assert not bad.ok and set(bad.errors) == {"command", "timeout"}
    assert cfg(folder)["enrich_provider"] == "codex"  # nothing written on error


# ------------------------------------------------------------------ outcomes


def test_outcomes_saved_one_per_line_and_windows_applied(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    t = token(client)
    r = client.post("/settings/outcomes", data={
        "csrf_token": t, "outcomes": "replied\n  meeting booked \n\nno answer\n",
        "message_window_days": "21", "silent_days": "30"})
    assert r.status_code == 303 and r.headers["location"].endswith("#outcomes")
    c = cfg(demo)
    assert c["outcomes"] == ["replied", "meeting booked", "no answer"]
    assert c["message_window_days"] == 21 and c["silent_days"] == 30
    assert app.state.config["outcomes"] == ["replied", "meeting booked", "no answer"]
    assert app.state.store.silent_days == 30
    page = client.get("/settings").text
    assert ">replied\nmeeting booked\nno answer</textarea>" in page
    # The silent threshold is live on the Calendar page without a restart.
    assert "silent for 30+" in client.get("/calendar").text.lower()


def test_outcomes_validation(demo, tmp_path):
    _, client = make_client(demo, tmp_path)
    t = token(client)
    before = (demo / "config.toml").read_text()
    r = client.post("/settings/outcomes", data={"csrf_token": t, "outcomes": "\n  \n",
                                                "message_window_days": "14", "silent_days": "14"})
    assert r.status_code == 400 and "Give at least one outcome" in r.text
    r = client.post("/settings/outcomes", data={"csrf_token": t, "outcomes": "won\nlost\nWon",
                                                "message_window_days": "14", "silent_days": "14"})
    assert r.status_code == 400 and "Duplicate outcome: Won." in r.text
    assert ">won\nlost\nWon</textarea>" in r.text  # values kept
    r = client.post("/settings/outcomes", data={"csrf_token": t, "outcomes": "a\nb",
                                                "message_window_days": "0", "silent_days": "-1"})
    assert r.status_code == 400
    assert "Message window (days) must be a whole number" in r.text
    assert "Silent after (days) must be a whole number" in r.text
    assert (demo / "config.toml").read_text() == before
    assert client.post("/settings/outcomes", data={"outcomes": "a"}).status_code == 403


def test_plan_outcomes_function():
    ok = st.plan_outcomes(["reply", "silence"], "7", "10")
    assert ok.ok and ok.values == {"outcomes": ["reply", "silence"], "message_window_days": 7,
                                   "silent_days": 10}
    assert st.plan_outcomes("only one").ok
    assert st.parse_outcomes(" a \n\nb\n") == ["a", "b"]
    assert set(st.plan_outcomes("", "x", "1").errors) == {"outcomes", "message_window_days"}


# -------------------------------------------------------------- review queue


def test_review_queue_actions_redirect_to_settings_inbox(demo, tmp_path, monkeypatch):
    from hermitcrm import bcc

    class Box:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def fetch(self):
            return [(b"1", RAW_MAIL)]

        def mark_read(self, uids):
            pass

    app, client = make_client(demo, tmp_path, open_mailbox=lambda: Box())
    app.state.bcc_settings = bcc.Settings(address="me+crm@gmail.com",
                                          my_addresses=["me@example.com"])
    r = client.post("/bcc/import")
    assert r.status_code == 303
    assert r.headers["location"].startswith("/settings?flash=BCC%20import")
    assert r.headers["location"].endswith("#inbox")
    items = app.state.inbox.items()
    assert len(items) == 1
    page = client.get("/settings").text
    assert '<span class="badge">1</span>' in page.split("</nav>")[0]
    assert 'href="/settings#inbox"' in page.split("</nav>")[0]
    assert "Review queue (1)" in page and "someone@nowhere.example" in page
    r = client.post(f"/inbox/{items[0].id}/assign", data={"company": "no-such-company"})
    assert r.status_code == 400 and "unknown company" in r.text and 'id="inbox"' in r.text
    r = client.post(f"/inbox/{items[0].id}/discard")
    assert r.status_code == 303 and r.headers["location"].endswith("#inbox")
    assert r.headers["location"].startswith("/settings?flash=Discarded")
    assert app.state.inbox.items() == []
    r = client.post("/calendar/import", data={"back": "/settings"})
    assert r.headers["location"].startswith("/settings?flash=Calendar%20import%20failed")
    assert r.headers["location"].endswith("#inbox")
    r = client.post("/calendar/import", data={"back": "/inbox"})  # the old name still works
    assert r.headers["location"].startswith("/settings?flash=") and \
        r.headers["location"].endswith("#inbox")


RAW_MAIL = b"""From: me@example.com
To: Someone <someone@nowhere.example>
Subject: Hello
Date: Mon, 14 Sep 2026 10:00:00 +0200
Message-ID: <m-settings-1@example.com>
Content-Type: text/plain; charset=utf-8

Hi there
"""


# ------------------------------------------------------------------- fields


def test_fields_can_be_added_one_at_a_time(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    t = token(client)
    r = client.post("/settings/fields/add", data={
        "csrf_token": t, "key": " Deal Source ", "label": "how we met",
        "type": "select", "options": "inbound, outbound, referral",
        "show_in": ["detail", "companies"]})
    assert r.status_code == 303 and "Field%20deal_source%20added" in r.headers["location"]

    added = [d for d in app.state.custom_fields if d.key == "deal_source"]
    assert len(added) == 1
    assert added[0].label == "how we met" and added[0].options == \
        ["inbound", "outbound", "referral"]
    assert 'key = "deal_source"' in (demo / "fields.toml").read_text()
    assert "how we met" in client.get("/settings").text


def test_a_field_that_would_shadow_a_built_in_one_is_refused(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    before = (demo / "fields.toml").read_text()
    r = client.post("/settings/fields/add",
                    data={"csrf_token": token(client), "key": "stage"})
    assert r.status_code == 400 and "already a built-in company field" in r.text
    assert (demo / "fields.toml").read_text() == before


def test_the_whole_file_can_be_edited_at_once(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    t = token(client)
    good = ('[[field]]\nkey = "segment"\ntype = "select"\n'
            'options = ["smb", "enterprise"]\nshow_in = ["detail"]\n')
    r = client.post("/settings/fields", data={"csrf_token": t, "fields_toml": good})
    assert r.status_code == 303 and "Fields%20saved%3A%201" in r.headers["location"]
    assert [d.key for d in app.state.custom_fields] == ["segment"]

    r = client.post("/settings/fields", data={"csrf_token": t, "fields_toml": "key = ["})
    assert r.status_code == 400 and "not valid TOML" in r.text
    assert [d.key for d in app.state.custom_fields] == ["segment"]   # unchanged

    r = client.post("/settings/fields", data={"csrf_token": t, "fields_toml": ""})
    assert r.status_code == 303 and "fields.toml%20removed" in r.headers["location"]
    assert app.state.custom_fields == [] and not (demo / "fields.toml").exists()


def test_the_two_draft_roles_point_at_fields_that_exist(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    t = token(client)
    # the demo folder defines fte_estimate and ae_count
    r = client.post("/settings/messaging", data={
        "csrf_token": t, "size_field": "fte_estimate", "team_field": ""})
    assert r.status_code == 303
    assert cfg(demo)["messaging_size_field"] == "fte_estimate"
    assert cfg(demo)["messaging_team_field"] == ""

    r = client.post("/settings/messaging", data={
        "csrf_token": t, "size_field": "nonesuch", "team_field": ""})
    assert r.status_code == 400 and "No company field called" in r.text
    assert cfg(demo)["messaging_size_field"] == "fte_estimate"   # unchanged
