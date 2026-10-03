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


def test_the_walkthrough_is_home_until_it_is_finished(folder):
    """Every visit to /, not just the first: visiting other pages changes nothing."""
    app, client = make_client(folder)
    for page in ("/", "/settings", "/welcome", "/pipeline", "/"):
        r = client.get(page)
    assert r.status_code == 303 and r.headers["location"] == "/welcome"
    page = client.get("/welcome").text
    assert "0 of 10" in page and 'href="/settings#you"' in page
    assert 'href="/" data-tour="home" class="active"' in page   # Home is this page


def test_the_way_out_is_at_the_top_as_well_as_the_bottom(folder):
    _, client = make_client(folder)
    page = client.get("/welcome").text
    assert page.count("Don't open this at startup") == 2
    top = page.split('class="welcome-steps"')[0]
    assert "Don't open this at startup" in top and 'value="1"' in top
    assert page.count('action="/welcome/dismiss"') == 2
    assert page.count(f'name="csrf_token" value="{client.app.state.csrf_token}"') >= 2


def test_show_me_around_keeps_the_tour_through_the_redirect(folder):
    _, client = make_client(folder)
    assert 'href="/?tour=1" data-start-tour' in client.get("/welcome").text
    assert client.get("/?tour=1").headers["location"] == "/welcome?tour=1"


def test_home_is_the_dashboard_once_every_step_is_done(folder, monkeypatch):
    from hermitcrm import welcome
    monkeypatch.setattr(welcome, "progress", lambda steps: (len(steps), len(steps)))
    _, client = make_client(folder)
    assert client.get("/").status_code == 200


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


def _moved(folder) -> bool:
    from hermitcrm import welcome
    from hermitcrm.store import Store
    store = Store(folder)
    store.load()
    return next(s for s in welcome.steps(store, {}, {}, False) if s.key == "move").done


def test_logging_an_interaction_does_not_tick_move_a_deal(folder):
    """The first interaction moves prospect -> engaged by itself; that is not
    the user moving a deal, and the steps are done in exactly that order."""
    from hermitcrm.store import Store
    store = Store(folder)
    store.load()
    co = store.create_company("Acme")
    store.create_interaction(co.slug, "email", "out", subject="Hello")
    assert store.get(co.slug).stage == "engaged"
    assert not _moved(folder)

    store.update_company(co.slug, stage="discovery")
    assert _moved(folder)


def test_creating_a_company_in_a_later_stage_is_not_a_move(folder):
    from hermitcrm.store import Store
    store = Store(folder)
    store.load()
    store.create_company("Acme", stage="discovery")
    assert not _moved(folder)


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


def test_settings_says_where_secrets_live_on_each_platform(folder, monkeypatch):
    """Without a keyring the page says the secrets are plain text rather than
    leaving it to be discovered, and offers the keyring only where one answers."""
    app, client = make_client(folder)
    page = client.get("/settings").text  # Linux, secret-tool missing (conftest)
    assert "No system keyring was found" in page and "libsecret-tools" in page
    assert "macOS Keychain" not in page and 'name="keychain"' not in page
    app.state.setup_platform = "darwin"
    page = client.get("/settings").text
    assert "or the macOS Keychain" in page
    assert "Store the password in the macOS Keychain" in page
    assert "No system keyring" not in page
    app.state.setup_platform = "win32"
    page = client.get("/settings").text
    assert "plain text" in page and "libsecret" not in page
    assert 'name="keychain"' not in page

    monkeypatch.setattr(secrets, "_which", lambda n: "/usr/bin/" + n)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    probes = []

    def runner(argv, **kw):
        probes.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "")

    app.state.setup_runner = runner
    app.state.setup_platform = "linux"
    for _ in range(2):
        page = client.get("/settings").text
    assert [p[0] for p in probes].count("secret-tool") == 1  # probed once, then cached
    assert "or the system keyring (Secret Service)" in page
    assert "locked while you are logged out" in page
    assert re.search(r'name="keychain" value="1" checked[^>]*> Store the password in '
                     r'the system keyring \(Secret Service\)', page)


# ------------------------------------------------- small fixes on the page (Oct 2026)

def test_a_stored_calendar_address_is_said_to_be_kept(folder):
    """The address field is a password field, so it shows empty once saved; the
    BCC password says "stored; leave empty to keep it" and now so does this one."""
    app, client = make_client(folder)
    app.state.fetch_calendar = lambda url: "BEGIN:VCALENDAR\nEND:VCALENDAR\n"

    def field():
        return re.search(r'<input type="password" name="url"[^>]*>',
                         client.get("/settings").text).group(0)

    assert "stored" not in field()
    client.post("/setup/calendar", data={"csrf_token": token(client),
                                         "url": "https://cal.example.com/s.ics"})
    assert 'placeholder="stored; leave empty to keep it"' in field()


def test_a_github_remote_gets_one_private_warning_not_two(folder):
    subprocess.run(["git", "-C", str(folder), "remote", "add", "origin",
                    "git@github.com:me/crm.git"], check=True)
    _, client = make_client(folder)
    page = client.get("/settings").text
    assert "github.com hosts public repositories too" in page
    assert page.count("PRIVATE") == 1


def test_the_field_form_offers_only_places_the_record_has(folder):
    """Each "Shown in" box names the records it fits, from VIEWS_FOR_SCOPE, so
    the page can hide the rest; before, a contact field could tick "board" and
    be refused on save."""
    _, client = make_client(folder)
    page = client.get("/settings").text
    offered = {view: set(scopes.split()) for scopes, view in re.findall(
        r'<label data-scopes="([^"]*)"><input type="checkbox" name="show_in" '
        r'value="(\w+)"', page)}
    assert offered == {"detail": {"company", "contact", "interaction"},
                       "board": {"company"}, "companies": {"company"},
                       "contacts": {"contact"}, "messages": {"interaction"}}
    assert 'id="field-applies-to"' in page and 'id="field-show-in"' in page


def test_checkboxes_sit_beside_their_words(folder):
    """A bare checkbox inherits the full-width block every input gets; the
    outreach box showed up detached in the middle of the field form."""
    app, client = make_client(folder)
    app.state.setup_platform = "darwin"
    page = client.get("/settings").text
    assert '<label class="check"><input type="checkbox" name="messaging"' in page
    assert '<label class="check"><input type="checkbox" name="keychain"' in page
    assert 'style="display:inline' not in page


def test_unticking_outreach_use_sticks(folder):
    """An unticked checkbox sends nothing; the route read that as "on"."""
    app, client = make_client(folder)
    t = token(client)
    client.post("/settings/fields/add", data={"csrf_token": t, "key": "private_note"})
    client.post("/settings/fields/add", data={"csrf_token": t, "key": "segment",
                                              "messaging": "on"})
    defs = {d.key: d for d in app.state.custom_fields}
    assert defs["private_note"].messaging is False
    assert defs["segment"].messaging is True
    assert "messaging = false" in (folder / "fields.toml").read_text()
