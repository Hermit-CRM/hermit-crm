"""The /settings page (the former /setup), CSRF, the redirect-once and the empty-board cards."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import secrets
from hermitcrm.bcc import BccError
from hermitcrm.datafolder import init_folder
from hermitcrm.store import load_config
from hermitcrm.web import create_app


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "crm")


def make_client(folder: Path, **state):
    config = load_config(folder)
    config["push_enabled"] = False
    app = create_app(folder, config)
    app.state.setup_platform = "linux"
    for key, value in state.items():
        setattr(app.state, key, value)
    return app, TestClient(app, follow_redirects=False)


def token(client) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get("/settings").text).group(1)


def cfg(folder):
    return tomllib.loads((folder / "config.toml").read_text())


def test_a_first_start_lands_on_the_walkthrough_once(folder):
    """Its first step is the Settings form, so nothing is lost by going there first."""
    app, client = make_client(folder)
    r = client.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/welcome"
    assert client.get("/").status_code == 200        # once per start, then home
    page = client.get("/welcome").text
    assert "0 of 10" in page and 'href="/settings#you"' in page


def test_no_redirect_once_the_walkthrough_is_dismissed(folder):
    (folder / "config.toml").write_text('owner_email = "me@example.com"\n'
                                        "welcome_dismissed = true\n")
    _, client = make_client(folder)
    assert client.get("/").status_code == 200


def test_the_settings_page_still_offers_skip_for_now(folder):
    _, client = make_client(folder)
    page = client.get("/settings").text
    assert 'href="/">Skip for now' in page
    assert page.count("pending") >= 4


def test_the_empty_home_page_says_where_to_start(folder):
    """The ways in live on the home page now, not on an empty board."""
    _, client = make_client(folder, setup_redirected=True)
    page = client.get("/").text
    for text, href in (("Import a spreadsheet", "/import"), ("Add a company", "/companies/new"),
                       ("Set up BCC capture", "/settings#bcc")):
        assert text in page and f'href="{href}"' in page
    assert 'href="/settings"' in page.split("</nav>")[0]
    # and the board itself just points back here
    board = client.get("/pipeline").text
    assert "Import a spreadsheet" not in board
    assert 'The home page</a> has the ways to start' in board


def test_a_folder_with_data_gets_the_numbers_instead(tmp_path):
    demo = init_folder(tmp_path / "demo", demo=True)
    _, client = make_client(demo, setup_redirected=True)
    page = client.get("/").text
    assert "Import a spreadsheet" not in page
    assert "What needs doing" in page and "How it is going" in page


def test_the_first_company_does_not_take_the_beginner_help_with_it(folder):
    """The old rule hid it as soon as one company existed -- two steps into ten."""
    app, client = make_client(folder, setup_redirected=True)
    app.state.store.create_company("Real Customer BV")
    page = client.get("/").text
    assert "What needs doing" in page and "How it is going" in page   # the real home
    assert "Getting started" in page and "1 of 10" in page            # and the help below it
    assert "What this thing does" in page
    assert 'action="/sample"' in page and 'href="/welcome"' in page


def test_hide_the_tutorial_takes_the_beginner_help_off_home(folder):
    """One switch for the walkthrough and for home: /welcome/dismiss."""
    app, client = make_client(folder, setup_redirected=True)
    app.state.store.create_company("Real Customer BV")
    page = client.get("/").text
    # the button says what it takes away, and both names are on the page it says it
    assert "Hide the tutorial" in page
    offer = page.split("Hide the tutorial")[1].split("</form>")[0]
    assert "Getting started" in offer and "What this thing does" in offer
    r = client.post("/welcome/dismiss", data={"csrf_token": token(client), "dismissed": "1"})
    assert r.status_code == 303 and r.headers["location"].startswith("/?flash=")
    assert cfg(folder)["welcome_dismissed"] is True
    page = client.get("/").text
    assert "Getting started" not in page and "What this thing does" not in page
    assert "What needs doing" in page
    # and it comes back the same way
    client.post("/welcome/dismiss", data={"csrf_token": token(client), "dismissed": ""})
    assert "What this thing does" in client.get("/").text


def test_a_finished_walkthrough_needs_no_hiding(folder):
    from hermitcrm import welcome
    steps = [welcome.Step("a", "", "", "", "/", done=True)]
    assert welcome.should_show({}, steps) is False
    assert welcome.should_show({}, steps + [welcome.Step("b", "", "", "", "/")]) is True


def test_csrf_required(folder):
    _, client = make_client(folder)
    data = {"name": "Jane", "addresses": "jane@example.com"}
    assert client.post("/setup/you", data=data).status_code == 403
    assert client.post("/setup/you", data={**data, "csrf_token": "wrong"}).status_code == 403
    for path in ("/setup/bcc", "/setup/bcc/test", "/setup/backup", "/setup/calendar"):
        assert client.post(path, data={}).status_code == 403
    assert cfg(folder) == {}


def test_setup_you_saves_keeps_comments_and_clears_redirect(folder):
    app, client = make_client(folder)
    before = (folder / "config.toml").read_text()
    r = client.post("/setup/you", data={"csrf_token": token(client), "name": "Jane Doe",
                                        "addresses": "jane@example.com, jane@gmail.com"})
    assert r.status_code == 303 and r.headers["location"].startswith("/settings?flash=")
    after = (folder / "config.toml").read_text()
    assert "# Your name; its first word signs outreach drafts" in after
    assert len(after.splitlines()) == len(before.splitlines())
    c = cfg(folder)
    assert c["owner_email"] == "jane@example.com" and c["bcc_ignore_domains"] == ["example.com"]
    assert app.state.config["owner_name"] == "Jane Doe"
    page = client.get("/settings").text
    assert 'value="jane+crm@gmail.com"' not in page  # main address is not Gmail
    assert 'value="Jane Doe"' in page


def test_setup_you_validation_rerenders(folder):
    _, client = make_client(folder)
    r = client.post("/setup/you", data={"csrf_token": token(client), "name": "",
                                        "addresses": "nope"})
    assert r.status_code == 400
    assert "Give your name." in r.text and 'value="nope"' in r.text


def test_setup_bcc_never_echoes_password_and_test_hint(folder):
    def refused():
        raise BccError("Gmail refused the login for jane@gmail.com: invalid credentials")

    app, client = make_client(folder, open_mailbox=refused)
    t = token(client)
    r = client.post("/setup/bcc", data={"csrf_token": t, "address": "jane+crm@gmail.com",
                                        "imap_host": "", "password": "hunter2-secret"})
    assert r.status_code == 303 and "hunter2" not in r.headers["location"]
    assert secrets.get("bcc_password", folder, env={}, platform="linux") == "hunter2-secret"
    page = client.get("/settings").text
    assert "hunter2" not in page
    assert "Matches: to:(jane+crm@gmail.com) → Skip the Inbox, Mark as read, Apply label Hermit CRM" in page
    assert app.state.bcc_settings.address == "jane+crm@gmail.com"
    r = client.post("/setup/bcc/test", data={"csrf_token": t})
    assert r.status_code == 303
    assert "use%20an%20app%20password" in r.headers["location"]
    bad = client.post("/setup/bcc", data={"csrf_token": t, "address": "x",
                                          "imap_host": "", "password": "pw-zzz"})
    assert bad.status_code == 400 and "pw-zzz" not in bad.text


def test_setup_backup_and_calendar(folder, tmp_path):
    bare = tmp_path / "r.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    app, client = make_client(folder)
    app.state.fetch_calendar = lambda url: "BEGIN:VCALENDAR\nEND:VCALENDAR\n"
    t = token(client)
    r = client.post("/setup/backup", data={"csrf_token": t, "url": str(bare)})
    assert r.status_code == 303 and "test%20push%20worked" in r.headers["location"]
    assert app.state.gitops.push_enabled is True
    assert client.post("/setup/backup", data={"csrf_token": t, "url": ""}).status_code == 400
    r = client.post("/setup/calendar", data={"csrf_token": t,
                                             "url": "https://cal.example.com/s3cr3t.ics"})
    assert r.status_code == 303 and "s3cr3t" not in r.headers["location"]
    page = client.get("/settings").text
    assert "s3cr3t" not in page and "PRIVATE" in page
    assert client.post("/setup/calendar", data={"csrf_token": t, "url": "x"}).status_code == 400


def test_access_section_shows_the_phone_and_mcp_commands(folder):
    """The Access section is where you look for the two front doors that are
    started from a terminal, so it must name both and say the port is open."""
    app, client = make_client(folder)
    page = client.get("/settings").text
    assert 'id="access"' in page and 'href="#access">Access' in page
    assert f"--data {folder} serve --host 0.0.0.0" in page
    assert f"--data {folder} mcp" in page
    assert "&#34;mcpServers&#34;" in page  # the JSON to paste, escaped
    assert "Hermit CRM has no password" in page
    assert 'href="/help/ai-agents"' in page
