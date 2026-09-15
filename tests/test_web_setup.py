"""The /setup page, CSRF, the redirect-once and the empty-board cards."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from owncrm import secrets
from owncrm.bcc import BccError
from owncrm.datafolder import init_folder
from owncrm.store import load_config
from owncrm.web import create_app


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
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get("/setup").text).group(1)


def cfg(folder):
    return tomllib.loads((folder / "config.toml").read_text())


def test_redirects_to_setup_once_per_start(folder):
    app, client = make_client(folder)
    r = client.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    assert client.get("/").status_code == 200  # "Skip for now"
    page = client.get("/setup").text
    assert 'href="/">Skip for now' in page
    assert page.count("pending") >= 4


def test_no_redirect_when_owner_email_set(folder):
    (folder / "config.toml").write_text('owner_email = "me@example.com"\n')
    _, client = make_client(folder)
    assert client.get("/").status_code == 200


def test_empty_board_cards_and_setup_nav(folder):
    _, client = make_client(folder, setup_redirected=True)
    page = client.get("/").text
    for text, href in (("Import a spreadsheet", "/import"), ("Add a company", "/companies/new"),
                       ("Set up BCC capture", "/setup#bcc")):
        assert text in page and f'href="{href}"' in page
    assert '<a href="/setup">Setup</a>' in page.split("</nav>")[0]


def test_demo_board_has_no_start_cards(tmp_path):
    demo = init_folder(tmp_path / "demo", demo=True)
    _, client = make_client(demo, setup_redirected=True)
    assert "Import a spreadsheet" not in client.get("/").text


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
    assert r.status_code == 303 and r.headers["location"].startswith("/setup?flash=")
    after = (folder / "config.toml").read_text()
    assert "# Your name; its first word signs outreach drafts" in after
    assert len(after.splitlines()) == len(before.splitlines())
    c = cfg(folder)
    assert c["owner_email"] == "jane@example.com" and c["bcc_ignore_domains"] == ["example.com"]
    assert app.state.config["owner_name"] == "Jane Doe"
    page = client.get("/setup").text
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
    page = client.get("/setup").text
    assert "hunter2" not in page
    assert "Matches: to:(jane+crm@gmail.com) → Skip the Inbox, Mark as read, Apply label OwnCRM" in page
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
    page = client.get("/setup").text
    assert "s3cr3t" not in page and "PRIVATE" in page
    assert client.post("/setup/calendar", data={"csrf_token": t, "url": "x"}).status_code == 400
