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

"""Client folders in the web app, the CLI, doctor and MCP."""

from __future__ import annotations

from html import unescape
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import doctor, mcp
from hermitcrm.cli import cmd_folders, cmd_show
from hermitcrm.datafolder import init_folder
from hermitcrm.web import create_app
from test_doctor import checks as doctor_checks
from test_layout import CONFIG, FIXED_NOW, repo  # noqa: F401  (the same git-backed folder)

PDF = b"%PDF-1.4 example\n"
LOCAL = ("127.0.0.1", 50000)
PHONE = ("192.168.1.20", 50000)


@pytest.fixture
def clients(tmp_path_factory) -> Path:
    """The client folders root: outside the data folder (which is tmp_path)."""
    return tmp_path_factory.mktemp("clients")


@pytest.fixture
def app(repo, clients):  # noqa: F811
    app = create_app(repo, config={**CONFIG, "client_files_root": str(clients)},
                     clock=lambda: FIXED_NOW)
    app.state.calls = []
    app.state.folder_runner = lambda cmd, **kw: app.state.calls.append(cmd)
    app.state.folder_platform = "darwin"
    store = app.state.store
    store.create_company("Example Labs BV", country="NL")
    store.create_contact("example-labs", "Jane", "Doe", email="jane@example.com")
    return app


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False, client=LOCAL)


@pytest.fixture
def phone(app):
    return TestClient(app, follow_redirects=False, client=PHONE)


@pytest.fixture
def folder(clients) -> Path:
    folder = clients / "Example Labs BV"
    folder.mkdir()
    (folder / "notes.md").write_text("# Kick-off\n", encoding="utf-8")
    (folder / "Q3 deck.pptx").write_bytes(b"PK\x03\x04 deck")
    (folder / "contract.pdf").write_bytes(PDF)
    (folder / "page.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    for f in folder.iterdir():
        f.chmod(0o644)
    return folder


CO = "/companies/example-labs"
CONTACT = CO + "/contacts/jane-doe"


# ------------------------------------------------------------------ pages


def test_off_shows_nothing(repo):  # noqa: F811
    app = create_app(repo, config=CONFIG, clock=lambda: FIXED_NOW)
    app.state.store.create_company("Example Labs BV", country="NL")
    page = TestClient(app, client=LOCAL).get(CO).text
    assert "Client folder" not in page and "folder/create" not in page


def test_missing_folder_offers_create(client, clients):
    page = unescape(client.get(CO).text)
    path = str(clients / "Example Labs BV")
    assert "No folder yet for Example Labs BV" in page
    assert f'data-copy-text="{path}"' in page
    assert 'action="/companies/example-labs/folder/create"' in page


def test_create_makes_the_folder(client, clients, app):
    r = client.post(CO + "/folder/create", data={"back": CO})
    assert r.status_code in (302, 303)
    assert (clients / "Example Labs BV").is_dir()
    assert "Folder created" in unescape(r.headers["location"].replace("%20", " "))
    assert app.state.calls == []                     # nothing opened


def test_create_refused_when_the_root_is_missing(repo, clients):  # noqa: F811
    missing = clients / "typo"
    app = create_app(repo, config={**CONFIG, "client_files_root": str(missing)},
                     clock=lambda: FIXED_NOW)
    app.state.store.create_company("Example Labs BV", country="NL")
    web = TestClient(app, follow_redirects=False, client=LOCAL)
    assert "does not exist" in unescape(web.get(CO).text)
    r = web.post(CO + "/folder/create", data={})
    assert r.status_code in (302, 303)
    assert not missing.exists()


def test_create_refused_inside_the_data_folder(repo):  # noqa: F811
    app = create_app(repo, config={**CONFIG, "client_files_root": str(repo / "clients")},
                     clock=lambda: FIXED_NOW)
    app.state.store.create_company("Example Labs BV", country="NL")
    web = TestClient(app, follow_redirects=False, client=LOCAL)
    assert "Client folder" not in web.get(CO).text
    web.post(CO + "/folder/create", data={})
    assert not (repo / "clients").exists()


def test_folder_lists_files_on_company_and_contact(client, folder):
    for url in (CO, CONTACT):
        page = unescape(client.get(url).text)
        assert "notes.md" in page and "Q3 deck.pptx" in page
        assert f'data-copy-text="{folder}"' in page
        assert 'action="/companies/example-labs/folder/open"' in page
        assert "Show in Finder" in page
        assert "No folder yet" not in page


def test_phone_gets_links_not_open_buttons(phone, folder):
    page = unescape(phone.get(CO).text)
    assert "/companies/example-labs/folder/file?path=notes.md" in page
    assert "folder/open" not in page and "Show in Finder" not in page


# ------------------------------------------------------------------ open


def test_open_runs_open_on_the_file(client, folder, app):
    r = client.post(CO + "/folder/open", data={"path": "Q3 deck.pptx", "back": CONTACT})
    assert r.status_code in (302, 303)
    assert r.headers["location"].startswith(CONTACT)
    assert app.state.calls == [["open", str((folder / "Q3 deck.pptx").resolve())]]


def test_open_reveals_a_script(client, folder, app):
    script = folder / "run.command"
    script.write_text("echo hi\n", encoding="utf-8")
    client.post(CO + "/folder/open", data={"path": "run.command"})
    assert app.state.calls == [["open", "-R", str(script.resolve())]]


def test_open_refuses_a_path_out(client, folder, app, clients):
    (clients / "secret.txt").write_text("x", encoding="utf-8")
    for path in ("../secret.txt", str(clients / "secret.txt"), "", "nope.md"):
        assert client.post(CO + "/folder/open", data={"path": path}).status_code == 404
    assert app.state.calls == []


def test_open_refused_cross_site(client, folder, app):
    r = client.post(CO + "/folder/open", data={"path": "notes.md"},
                    headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert app.state.calls == []


def test_open_and_reveal_refused_from_a_phone(phone, folder, app):
    assert phone.post(CO + "/folder/open", data={"path": "notes.md"}).status_code == 403
    assert phone.post(CO + "/folder/reveal", data={}).status_code == 403
    assert app.state.calls == []


def test_reveal_shows_the_folder(client, folder, app):
    r = client.post(CO + "/folder/reveal", data={})
    assert r.status_code in (302, 303)
    assert app.state.calls == [["open", "-R", str(folder.resolve())]]


def test_open_without_a_folder_is_404(client, app):
    assert client.post(CO + "/folder/open", data={"path": "x.md"}).status_code == 404


# ------------------------------------------------------------------ GET file


def test_file_pdf_inline_with_csp(phone, folder):
    r = phone.get(CO + "/folder/file", params={"path": "contract.pdf"})
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["content-security-policy"] == "default-src 'none'"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_file_html_downloads(phone, folder):
    r = phone.get(CO + "/folder/file", params={"path": "page.html"})
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in r.headers["content-security-policy"]


def test_file_refuses_a_path_out(phone, folder, clients):
    (clients / "secret.txt").write_text("x", encoding="utf-8")
    assert phone.get(CO + "/folder/file", params={"path": "../secret.txt"}).status_code == 404
    assert phone.get(CO + "/folder/file", params={"path": "."}).status_code == 404


# ------------------------------------------------------------------ settings


def test_settings_saves_the_root(client, app, clients, repo):  # noqa: F811
    target = clients / "elsewhere"
    r = client.post("/settings/client-folders",
                    data={"csrf_token": app.state.csrf_token, "client_files_root": str(target)})
    assert r.status_code in (302, 303)
    assert str(target) in (repo / "config.toml").read_text(encoding="utf-8")


def test_settings_refuses_a_root_in_the_data_folder(client, app, repo):  # noqa: F811
    r = client.post("/settings/client-folders",
                    data={"csrf_token": app.state.csrf_token,
                          "client_files_root": str(repo / "clients")})
    assert r.status_code == 400
    assert "inside the data folder" in unescape(r.text)


# ------------------------------------------------------------------ CLI


def test_cli_folders_defaults_to_won(app, clients):
    store = app.state.store
    store.create_company("Example Won BV", country="NL")
    store.update_company("example-won", stage="won", force=True)
    config = {"client_files_root": str(clients)}
    text, code = cmd_folders(store, config)
    assert code == 0 and "missing  example-won" in text
    assert "example-labs" not in text
    assert not (clients / "Example Won BV").exists()          # a dry run
    text, code = cmd_folders(store, config, create=True)
    assert code == 0 and (clients / "Example Won BV").is_dir()
    assert not (clients / "Example Labs BV").exists()
    text, _ = cmd_folders(store, config, every=True)
    assert "found    example-won" in text and "missing  example-labs" in text
    text, _ = cmd_folders(store, config, stage_names=["prospect"])
    assert "example-labs" in text and "example-won" not in text
    assert cmd_folders(store, config, stage_names=["nope"])[1] == 1
    assert cmd_folders(store, {})[1] == 1                       # off


def test_cli_show_has_a_folder_line(app, clients, repo):  # noqa: F811
    (repo / "config.toml").write_text(f'client_files_root = "{clients}"\n', encoding="utf-8")
    text = cmd_show(app.state.store, "example-labs")
    assert f"folder: (none yet) {clients / 'Example Labs BV'}" in text


# ------------------------------------------------------------------ doctor, MCP


def test_doctor_line(tmp_path, clients):
    data = init_folder(tmp_path / "crm")
    with (data / "config.toml").open("a", encoding="utf-8") as fh:
        fh.write(f'\nclient_files_root = "{clients}"\n')
    line = doctor_checks(data, tmp_path)["client folders"]
    assert line.status == doctor.OK and "0 company folder(s)" in line.detail


def test_doctor_warns(tmp_path, clients):
    data = init_folder(tmp_path / "crm")
    assert "client folders" not in doctor_checks(data, tmp_path)      # off: no line
    for root, why in ((data / "clients", "inside the data folder"),
                      (clients / "typo", "does not exist")):
        text = (data / "config.toml").read_text(encoding="utf-8")
        text = "\n".join(l for l in text.splitlines() if not l.startswith("client_files_root"))
        (data / "config.toml").write_text(text + f'\nclient_files_root = "{root}"\n',
                                          encoding="utf-8")
        line = doctor_checks(data, tmp_path)["client folders"]
        assert line.status == doctor.WARN and why in line.detail


def test_mcp_company_folder(app, repo, clients, folder):  # noqa: F811
    (repo / "config.toml").write_text(f'client_files_root = "{clients}"\n', encoding="utf-8")
    tools = {t.name: t for t in mcp.build_tools(repo, app.state.store)}
    text = tools["company_folder"].handler({"slug": "example-labs"})
    assert f"folder: {folder}" in text and "Q3 deck.pptx" in text
