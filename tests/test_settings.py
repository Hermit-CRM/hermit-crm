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

"""The /settings page: sections, the /setup and /inbox redirects, the enrichment
and outcomes forms, and the review queue (the former inbox) inside it."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import setup as st
from hermitcrm.datafolder import init_folder
from hermitcrm.store import load_config
from hermitcrm.web import create_app

SECTIONS = ("you", "bcc", "calendar", "backup", "appearance", "enrichment", "outcomes",
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


def test_settings_title_is_plain_and_provider_script_runs_in_body(demo, tmp_path):
    # The provider picker's script once sat inside the title block; <title> is
    # RCDATA, so the tab showed the code and the script never ran.
    app, client = make_client(demo, tmp_path)
    html = client.get("/settings").text
    assert "<title>Settings</title>" in html
    select = html.index('id="bcc-provider"')
    script = html.index("// Picking a provider fills the server")
    assert select < script
    assert html.index("</title>") < script


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
    # Import status under BCC capture and Calendar (the queue itself is on Home), schedule, about.
    assert "No import has run yet." in page and "Import meetings now" in page
    assert "Nothing to review." not in page and 'href="#inbox"' not in page
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
    assert r.status_code == 301 and r.headers["location"] == "/#to-file"


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
    assert 'id="schedule"' in bad.text  # the whole page re-renders, values kept


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


def test_new_outcomes_usable_without_restart(demo, tmp_path):
    """Outcomes saved in Settings are live at once: the store accepts them, the
    interaction form offers them and the Messages tab counts them."""
    app, client = make_client(demo, tmp_path)
    slug = "bluefin-analytics"
    r = client.post("/settings/outcomes", data={
        "csrf_token": token(client), "outcomes": "positive\nmeeting booked\nsilent",
        "message_window_days": "14", "silent_days": "14"})
    assert r.status_code == 303
    assert app.state.store.outcomes == ["positive", "meeting booked", "silent"]
    page = client.get(f"/companies/{slug}/interactions/new").text
    assert '<option value="meeting booked"' in page
    person = next(iter(app.state.store.companies[slug].contacts))
    r = client.post(f"/companies/{slug}/interactions", data={
        "channel": "email", "direction": "out", "contact": person, "date": "2026-09-01",
        "subject": "Intro", "outcome": "meeting booked", "body": "Hello"})
    assert r.status_code == 303, r.text
    logged = [i for i in app.state.store.companies[slug].interactions
              if i.subject == "Intro"]
    assert [i.outcome for i in logged] == ["meeting booked"]
    assert "1 meeting booked" in client.get("/messages").text
    # And the old list is gone from validation too.
    r = client.post(f"/companies/{slug}/interactions", data={
        "channel": "email", "direction": "out", "contact": person, "date": "2026-09-02",
        "subject": "Old", "outcome": "successful", "body": "Hi"})
    assert r.status_code != 303


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


def test_to_file_lives_on_home_and_import_status_in_settings(demo, tmp_path, monkeypatch):
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
                                          my_addresses=["me@example.com"],
                                          create_companies=False)
    r = client.post("/bcc/import")
    assert r.status_code == 303
    assert r.headers["location"].startswith("/settings?flash=BCC%20import")
    assert r.headers["location"].endswith("#bcc")
    items = app.state.inbox.items()
    assert len(items) == 1
    # The count rides on Home in the nav; Settings carries no count any more.
    page = client.get("/settings").text
    nav = page.split("</nav>")[0]
    assert 'href="/#to-file"' in nav and '<span class="badge" title="To file">1</span>' in nav
    assert "#inbox" not in nav and "someone@nowhere.example" not in page
    # While the walkthrough is Home, / lands on it, and it carries the list too.
    assert client.get("/").headers["location"] == "/welcome"
    welcome_page = client.get("/welcome").text
    assert "To file (1)" in welcome_page and "someone@nowhere.example" in welcome_page
    client.post("/welcome/dismiss", data={"csrf_token": token(client), "dismissed": "1"})
    home = client.get("/")
    assert home.status_code == 200
    assert "To file (1)" in home.text and "someone@nowhere.example" in home.text
    assert home.text.index('id="doing"') < home.text.index('id="to-file"')
    r = client.post(f"/inbox/{items[0].id}/assign", data={"company": ""})
    assert r.status_code == 400 and "pick a company" in r.text and 'id="to-file"' in r.text
    r = client.post(f"/inbox/{items[0].id}/discard")
    assert r.status_code == 303 and r.headers["location"].endswith("#to-file")
    assert r.headers["location"].startswith("/?flash=Discarded")
    assert app.state.inbox.items() == []
    home = client.get("/").text
    assert 'id="to-file"' not in home  # shown only while there is something to file
    assert '<span class="badge"' not in home.split("</nav>")[0]
    r = client.post("/calendar/import", data={"back": "/settings"})
    assert r.headers["location"].startswith("/settings?flash=Calendar%20import%20failed")
    assert r.headers["location"].endswith("#calendar")
    r = client.post("/calendar/import", data={"back": "/inbox"})  # the old name still works
    assert r.headers["location"].startswith("/settings?flash=") and \
        r.headers["location"].endswith("#calendar")


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


def test_backup_section_shows_the_local_backup(demo, tmp_path):
    from hermitcrm import backup

    app, client = make_client(demo, tmp_path)
    page = client.get("/settings").text
    section = page.split('id="backup"')[1].split("</section>")[0]
    assert "On this computer" in section and 'href="/help/backups"' in section
    assert "No backup yet." in section and "Start local backups" in section
    assert "Online copy (optional)" in section and "backup_dir" in section
    assert backup.run(demo, {}, home=tmp_path / "home").code == 0
    page = client.get("/settings").text
    section = page.split('id="backup"')[1].split("</section>")[0]
    assert "Last backup just now" in section and "does not repeat on its own yet" in section
    assert "last good run" in section and ".hermitcrm/backups/" in section
    assert "Start local backups" in section  # the job is still missing


def fake_launchctl():
    calls = []

    def runner(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1 if argv[0] == "plutil" else 0, "", "")
    return runner, calls


def test_start_local_backups_runs_one_and_schedules_only_the_backup(demo, tmp_path):
    runner, calls = fake_launchctl()
    app, client = make_client(demo, tmp_path, setup_platform="darwin", setup_runner=runner)
    assert not app.state.setup_state or not app.state.setup_state["backup"]
    r = client.post("/settings/backup/local", data={"csrf_token": token(client)})
    assert r.status_code == 303 and r.headers["location"].endswith("#backup")
    assert "Local%20backups%20started" in r.headers["location"]
    agents = tmp_path / "home/Library/LaunchAgents"
    assert (agents / "io.hermitcrm.backup.plist").exists()
    assert not (agents / "io.hermitcrm.sync.plist").exists()  # the daily sync is not touched
    assert any(a[:2] == ["launchctl", "bootstrap"] for a in calls)
    assert app.state.setup_state["backup"] is True
    section = client.get("/settings").text.split('id="backup"')[1].split("</section>")[0]
    assert "Last backup just now" in section and "Start local backups" not in section
    assert '<span class="setup-status done">done</span>' in section.split("<h3>")[0]


def test_start_local_backups_leaves_another_folders_job_alone(demo, tmp_path):
    from hermitcrm import backup, schedule

    runner, _ = fake_launchctl()
    other = init_folder(tmp_path / "other")
    schedule.install(schedule.Context(data_dir=other, home=tmp_path / "home",
                                      platform="darwin", runner=runner, env={}),
                     backup_every=5)
    plist = tmp_path / "home/Library/LaunchAgents/io.hermitcrm.backup.plist"
    before = plist.read_bytes()
    app, client = make_client(demo, tmp_path, setup_platform="darwin", setup_runner=runner)
    section = client.get("/settings").text.split('id="backup"')[1].split("</section>")[0]
    assert "set up for another folder" in section and "Start local backups" not in section
    r = client.post("/settings/backup/local", data={"csrf_token": token(client)})
    assert r.status_code == 303 and "Not%20started" in r.headers["location"]
    assert plist.read_bytes() == before
    assert not backup.backup_path(demo, {}, tmp_path / "home").exists()


def test_start_local_backups_needs_the_csrf_token(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    assert client.post("/settings/backup/local", data={"csrf_token": "nope"}).status_code == 403


def test_help_backups_page_renders(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    r = client.get("/help/backups")
    assert r.status_code == 200 and "Rolling back" in r.text


def test_task_types_are_added_renamed_moved_and_deleted_in_settings(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    page = client.get("/settings").text
    assert '<section class="setup-step" id="task-types">' in page
    t = token(client)
    names = lambda: [x.name for x in app.state.task_types]

    r = client.post("/settings/task-types", data={
        "csrf_token": t, "name": ["lost deals", "prospecting", ""],
        "colour": ["amber", "blue", "green"], "old": ["", "", ""]})
    assert r.status_code == 303
    assert names() == ["lost deals", "prospecting"]
    assert app.state.store.task_types == ["lost deals", "prospecting"]   # live, no restart
    assert 'task_types = [{name = "lost deals", colour = "amber"}' in \
        (demo / "config.toml").read_text()

    store = app.state.store
    slug = next(iter(store.companies))
    store.add_task(slug, "revive", type="lost deals")
    r = client.post("/settings/task-types", data={
        "csrf_token": t, "name": ["lost deal revival", "prospecting", ""],
        "colour": ["amber", "blue", "grey"], "old": ["lost deals", "prospecting", ""],
        "move": "1-up"})
    assert names() == ["prospecting", "lost deal revival"]
    assert store.companies[slug].tasks[-1].type == "lost deal revival"
    assert "renamed" in r.headers["location"]

    client.post("/settings/task-types", data={
        "csrf_token": t, "name": ["prospecting", "lost deal revival", ""],
        "colour": ["blue", "amber", "grey"],
        "old": ["prospecting", "lost deal revival", ""], "delete": "1"})
    assert names() == ["prospecting"]
    assert store.companies[slug].tasks[-1].type == "lost deal revival"   # kept

    r = client.post("/settings/task-types", data={
        "csrf_token": t, "name": ["a", "A", ""], "colour": ["green"] * 3,
        "old": ["", "", ""]})
    assert r.status_code == 400 and "Duplicate task type" in r.text
    assert names() == ["prospecting"]
    assert client.post("/settings/task-types", data={"name": ["x"]}).status_code == 403
