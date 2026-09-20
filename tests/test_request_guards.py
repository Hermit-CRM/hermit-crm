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

"""The three high findings of the 2026-09 audit, kept fixed.

* DNS rebinding: requests for a host name the app does not know are refused.
* CSRF: a write another website's page sent is refused, on every route.
* Lost updates: a write never puts back what another process changed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm.store import Store
from hermitcrm.web import create_app, cross_site, host_allowed, host_name

CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "welcome_dismissed": True}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for args in (["init", "-b", "main"], ["config", "user.name", "CRM Test"],
                 ["config", "user.email", "crm@test.local"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    return tmp_path


def make_client(repo: Path, **config) -> TestClient:
    app = create_app(repo, config={**CONFIG, **config})
    app.state.setup_redirected = True
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def client(repo: Path) -> TestClient:
    return make_client(repo)


def company_file(repo: Path, slug: str) -> Path:
    return repo / "companies" / slug / "company.md"


def stage_of(repo: Path, slug: str) -> str:
    text = company_file(repo, slug).read_text(encoding="utf-8")
    return re.search(r"^stage: (\S+)$", text, re.M).group(1)


# ---------------------------------------------------------------- host names


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765", "[::1]:8765",
                                  "192.168.1.20:8765", "100.101.102.103", ""])
def test_ip_addresses_and_localhost_are_answered(host):
    assert host_allowed(host, {"localhost"})


@pytest.mark.parametrize("host", ["attacker.example:8765", "attacker.example",
                                  "127.0.0.1.attacker.example:8765", "localhost.evil"])
def test_other_host_names_are_refused(host):
    assert not host_allowed(host, {"localhost"})


def test_host_name_strips_port_and_brackets():
    assert host_name("Example.COM:8765") == "example.com"
    assert host_name("[::1]:8765") == "::1"
    assert host_name("::1") == "::1"


def test_a_rebinding_page_cannot_read_the_crm(client):
    client.post("/companies", data={"name": "Secret BV"})
    for path in ("/companies", "/health", "/pipeline"):
        resp = client.get(path, headers={"host": "attacker.example:8765"})
        assert resp.status_code == 400
        assert "Secret BV" not in resp.text
    assert client.get("/companies", headers={"host": "127.0.0.1:8765"}).status_code == 200


def test_allowed_hosts_names_an_extra_host(repo):
    c = make_client(repo, allowed_hosts=["mymac.tail1234.ts.net"])
    assert c.get("/companies", headers={"host": "mymac.tail1234.ts.net:8765"}).status_code == 200
    assert c.get("/companies", headers={"host": "other.ts.net:8765"}).status_code == 400


def test_a_named_bind_host_is_answered(repo):
    c = make_client(repo, host="crm.lan")
    assert c.get("/companies", headers={"host": "crm.lan:8765"}).status_code == 200


# --------------------------------------------------------------------- CSRF


CROSS_SITE = [
    {"sec-fetch-site": "cross-site"},
    {"sec-fetch-site": "same-site"},  # another port on localhost is another app
    {"origin": "https://evil.example"},
    {"origin": "null"},
    {"origin": "http://127.0.0.1:3000"},
    {"referer": "https://evil.example/page"},
]
SAME_SITE = [
    {"sec-fetch-site": "same-origin"},
    {"sec-fetch-site": "none"},  # typed or bookmarked by the user
    {"origin": "http://testserver"},
    {"referer": "http://testserver/companies"},
    {},  # not a browser: curl, scripts
]


@pytest.mark.parametrize("headers", CROSS_SITE)
def test_a_form_from_another_site_is_refused(client, repo, headers):
    resp = client.post("/companies", data={"name": "Pwned BV"}, headers=headers)
    assert resp.status_code == 403
    assert not (repo / "companies" / "pwned").exists()


@pytest.mark.parametrize("headers", SAME_SITE)
def test_a_form_from_the_app_itself_is_accepted(client, repo, headers):
    resp = client.post("/companies", data={"name": "Acme BV"}, headers=headers)
    assert resp.status_code == 303
    assert company_file(repo, "acme").exists()


def test_fetch_metadata_wins_over_origin(client):
    # Sec-Fetch-Site is set by the browser and cannot be forged by the page.
    headers = {"sec-fetch-site": "cross-site", "origin": "http://testserver"}
    assert client.post("/companies", data={"name": "X"}, headers=headers).status_code == 403


@pytest.mark.parametrize("path", [
    "/companies/acme/merge", "/companies/acme/stage", "/companies/acme/next-step",
    "/companies/acme/contacts/jane-doe/delete", "/reload", "/bcc/import", "/import",
    "/companies/acme/enrich", "/inbox/x/discard",
])
def test_every_write_route_is_guarded(client, repo, path):
    client.post("/companies", data={"name": "Acme BV"})
    before = company_file(repo, "acme").read_text(encoding="utf-8")
    resp = client.post(path, data={"drop": "acme", "stage": "won"},
                       headers={"origin": "https://evil.example"})
    assert resp.status_code == 403
    assert company_file(repo, "acme").read_text(encoding="utf-8") == before


def test_reads_are_not_affected_by_the_csrf_check(client):
    # Following a link from another site to the app is normal.
    assert client.get("/companies", headers={"sec-fetch-site": "cross-site"}).status_code == 200


def test_cross_site_reads_the_host_header():
    class Req:
        def __init__(self, **h):
            self.headers = h
    assert not cross_site(Req(host="127.0.0.1:8765", origin="http://127.0.0.1:8765"))
    assert cross_site(Req(host="127.0.0.1:8765", origin="http://localhost:8765"))


# ------------------------------------------------------------- lost updates


def test_a_stale_store_does_not_revert_another_process(tmp_path):
    (tmp_path / "companies").mkdir()
    web = Store(tmp_path)
    web.load()
    web.create_company("Race BV")
    sync = Store(tmp_path)  # the daily `hermitcrm sync`, loaded later
    sync.load()
    sync.create_interaction("race", channel="email", direction="in", body="hi")
    assert stage_of(tmp_path, "race") == "engaged"

    web.update_company("race", next_step="call them")  # web's index is stale
    assert stage_of(tmp_path, "race") == "engaged"
    assert len(web.get("race").interactions) == 1


def test_stale_stores_keep_each_others_tasks_and_contacts(tmp_path):
    (tmp_path / "companies").mkdir()
    a = Store(tmp_path)
    a.load()
    a.create_company("Acme BV")
    b = Store(tmp_path)
    b.load()
    b.add_task("acme", "from b")
    b.create_contact("acme", "Jane", "Doe")
    a.add_task("acme", "from a")
    a.create_contact("acme", "Jane", "Doe")  # must not overwrite b's jane-doe
    fresh = Store(tmp_path)
    fresh.load()
    assert [t.text for t in fresh.get("acme").tasks] == ["from b", "from a"]
    assert sorted(fresh.get("acme").contacts) == ["jane-doe", "jane-doe-2"]


def test_a_store_write_refuses_a_company_that_no_longer_parses(tmp_path):
    (tmp_path / "companies").mkdir()
    s = Store(tmp_path)
    s.load()
    s.create_company("Acme BV")
    path = company_file(tmp_path, "acme")
    broken = "---\nname: [unclosed\n---\n"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(Exception):
        s.update_company("acme", next_step="x")
    assert path.read_text(encoding="utf-8") == broken


def test_the_web_app_sees_another_process_without_a_reload(client, repo):
    client.post("/companies", data={"name": "Race BV"})
    client.get("/pipeline")
    sync = Store(repo)
    sync.load()
    sync.create_company("Newco BV")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "sync"], cwd=repo, check=True,
                   capture_output=True)
    assert "Newco BV" in client.get("/companies").text


def test_the_web_app_does_not_revert_a_sync_run(client, repo):
    client.post("/companies", data={"name": "Race BV"})
    sync = Store(repo)
    sync.load()
    sync.create_interaction("race", channel="email", direction="in", body="hi")
    resp = client.post("/companies/race/tasks", data={"text": "call them"})
    assert resp.status_code == 303
    assert stage_of(repo, "race") == "engaged"
    assert "call them" in company_file(repo, "race").read_text(encoding="utf-8")


def version_in(page: str) -> str:
    return re.search(r'name="version" value="([0-9a-f]*)"', page).group(1)


FORM = {"name": "Race BV", "website": "", "linkedin": "", "source": "other",
        "stage": "prospect", "lost_reason": "", "value_eur_month": "", "next_step": "",
        "next_step_due": "", "next_step_status": "open", "tags": "", "notes": "mine"}


def test_a_company_form_opened_before_a_sync_run_is_not_saved(client, repo):
    client.post("/companies", data={"name": "Race BV"})
    version = version_in(client.get("/companies/race").text)
    sync = Store(repo)
    sync.load()
    sync.create_interaction("race", channel="email", direction="in", body="hi")

    resp = client.post("/companies/race", data={**FORM, "version": version})
    assert resp.status_code == 409
    assert "Not saved" in resp.text and "stage" in resp.text
    assert stage_of(repo, "race") == "engaged"

    # Saving again from the page it showed is a deliberate choice, and goes through.
    resp = client.post("/companies/race", data={**FORM, "stage": "engaged",
                                                "version": version_in(resp.text)})
    assert resp.status_code == 303
    assert "mine" in company_file(repo, "race").read_text(encoding="utf-8")


def test_a_company_form_with_a_current_version_saves(client, repo):
    client.post("/companies", data={"name": "Race BV"})
    version = version_in(client.get("/companies/race").text)
    resp = client.post("/companies/race", data={**FORM, "version": version})
    assert resp.status_code == 303


def test_a_contact_form_opened_before_another_change_is_not_saved(client, repo):
    client.post("/companies", data={"name": "Acme BV"})
    other = Store(repo)
    other.load()
    other.create_contact("acme", "Jane", "Doe")
    version = version_in(client.get("/companies/acme/contacts/jane-doe").text)
    other.update_contact("acme", "jane-doe", email="jane@acme.example")

    form = {"first_name": "Jane", "last_name": "Doe", "title": "CFO", "linkedin": "",
            "email": "", "phone": "", "role": "", "notes": "", "version": version}
    resp = client.post("/companies/acme/contacts/jane-doe", data=form)
    assert resp.status_code == 409
    assert "email" in resp.text
    text = (repo / "companies/acme/contacts/jane-doe.md").read_text(encoding="utf-8")
    assert "jane@acme.example" in text and "CFO" not in text
