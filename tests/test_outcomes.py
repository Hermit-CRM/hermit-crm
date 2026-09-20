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

"""One outcome field: migration 3, the form dropdown, the Messages buttons, and
the same front-matter key seen from both sides."""

from __future__ import annotations

import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import migrations
from hermitcrm.models import ValidationError
from hermitcrm.store import Store, build_file, split_file
from hermitcrm.web import create_app

CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "owner_email": "me@example.com"}
TODAY = date.today()


# ------------------------------------------------------------------- fixtures


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "CRM Test"], cwd=tmp_path,
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "crm@test.local"], cwd=tmp_path,
                   check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    return tmp_path


@pytest.fixture
def app(repo: Path):
    return create_app(repo, config=CONFIG)


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False)


def last_commit(repo: Path) -> str:
    out = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo,
                         capture_output=True, text=True)
    return out.stdout.strip()


def interaction_form(**fields) -> dict:
    return {"channel": "email", "direction": "out", "contact": "", "date": "",
            "subject": "", "outcome": "", "body": "", **fields}


def interaction_file(repo: Path, slug: str, id: str) -> Path:
    return repo / "companies" / slug / "interactions" / f"{id}.md"


# ---------------------------------------------------------------- migration 3


def old_interaction(outcome, result, with_outcome_key=True) -> str:
    meta = {"date": "2026-09-01T09:00", "channel": "email", "direction": "out",
            "contact": "", "subject": "s"}
    if with_outcome_key:
        meta["outcome"] = outcome
    meta["result"] = result
    meta["source"] = "manual"
    return build_file(meta, "Body stays  byte for byte.\nresult: success in a body\n")


CASES = {
    # file -> (outcome before, result before) => outcome after
    "a": (("", "success"), "successful"),
    "b": (("", "unsuccessful"), "unsuccessful"),
    "c": (("Succesful", "unsuccessful"), "successful"),   # list value in outcome wins
    "d": (("Pending", ""), ""),
    "e": (("unknown", "success"), "successful"),           # "unknown" is empty: result fills it
    "f": (("Wants a proposal", "success"), "Wants a proposal"),  # free text kept verbatim
    "g": (("", ""), ""),
    "h": (("SUCCESS", ""), "successful"),
}


@pytest.fixture
def old_folder(tmp_path):
    root = tmp_path / "crm"
    folder = root / "companies" / "acme" / "interactions"
    folder.mkdir(parents=True)
    (root / "companies" / "acme" / "company.md").write_text(
        build_file({"name": "Acme", "slug": "acme"}, ""), encoding="utf-8")
    for name, ((outcome, result), _) in CASES.items():
        (folder / f"{name}.md").write_text(old_interaction(outcome, result), encoding="utf-8")
    (folder / "no-outcome-key.md").write_text(
        old_interaction("", "success", with_outcome_key=False), encoding="utf-8")
    migrations.write_format(root, 2)
    return root


def test_m3_before_after(old_folder):
    folder = old_folder / "companies" / "acme" / "interactions"
    before = {name: (folder / f"{name}.md").read_text() for name in CASES}
    text = migrations.dry_run(old_folder)
    assert "Data format 2 → 6" in text
    assert "3. interaction result folded into outcome: 9 file(s)" in text

    summary = migrations.ensure_current(old_folder)
    assert summary.startswith("migrate: data format 2 → 6 (interaction result folded into "
                              "outcome; stage reached-out renamed to engaged; scores and "
                              "team size become fields you define; agents may not "
                              "rewrite history (.claude/settings.json))")
    for name, (_, after) in CASES.items():
        meta, body = split_file((folder / f"{name}.md").read_text())
        assert str(meta.get("outcome") or "") == after, name
        assert "result" not in meta, name
        assert body == split_file(before[name])[1]  # bodies untouched
        assert list(meta) == ["date", "channel", "direction", "contact", "subject",
                              "outcome", "source"], name
    meta, _ = split_file((folder / "no-outcome-key.md").read_text())
    assert meta["outcome"] == "successful" and "result" not in meta
    assert list(meta).index("outcome") == list(meta).index("subject") + 1
    assert (old_folder / ".hermitcrm-format").read_text() == "6\n"
    store = Store(old_folder)
    assert store.load() == []
    assert {i.id: i.outcome for i in store.get("acme").interactions}["f"] == "Wants a proposal"


def test_m3_is_idempotent_and_leaves_other_files_alone(old_folder):
    migrations.ensure_current(old_folder)
    snapshot = {p: p.read_bytes() for p in old_folder.rglob("*.md")}
    (old_folder / ".hermitcrm-format").write_text("2\n")
    assert migrations.ensure_current(old_folder).endswith(": 0 file(s) changed")
    assert {p: p.read_bytes() for p in old_folder.rglob("*.md")} == snapshot
    assert migrations.m3_outcome({"name": "Acme"}) == {"name": "Acme"}
    assert migrations.m3_outcome({"outcome": "successful"}) == {"outcome": "successful"}


# ------------------------------------------------------------------ the store


def test_store_accepts_list_values_empty_or_unchanged(store):
    store.create_company("Acme")
    it = store.create_interaction("acme", channel="email", direction="out",
                                  outcome="unsuccessful", body="Hi")
    assert it.outcome == "unsuccessful"
    with pytest.raises(ValidationError, match="unknown outcome 'maybe'"):
        store.create_interaction("acme", channel="email", direction="out", outcome="maybe")
    # A value outside the list that is already in the file may be kept on edit.
    path = store.company_dir("acme") / "interactions" / f"{it.id}.md"
    path.write_text(path.read_text().replace("outcome: unsuccessful", "outcome: old text"))
    store.load()
    same = store.update_interaction("acme", it.id, outcome="old text", subject="edited")
    assert same.outcome == "old text" and same.subject == "edited"
    with pytest.raises(ValidationError):
        store.update_interaction("acme", it.id, outcome="other text")
    assert store.update_interaction("acme", it.id, outcome="").outcome == ""


def test_store_takes_outcomes_from_config(tmp_path):
    store = Store(tmp_path, outcomes=["won", "meh", "lost"])
    store.load()
    store.create_company("Acme")
    assert store.create_interaction("acme", channel="call", direction="out",
                                    outcome="meh").outcome == "meh"
    with pytest.raises(ValidationError):
        store.create_interaction("acme", channel="call", direction="out",
                                 outcome="successful")


# -------------------------------------------------------------------- the web


def test_form_dropdown_lists_outcomes_and_keeps_a_stray_value(client, app, repo):
    client.post("/companies", data={"name": "Acme"})
    form = client.get("/companies/acme/interactions/new").text
    select = form.split('<select name="outcome">')[1].split("</select>")[0]
    assert '<option value="" selected>not yet known</option>' in select
    assert '<option value="successful">successful</option>' in select
    assert '<option value="unsuccessful">unsuccessful</option>' in select
    r = client.post("/companies/acme/interactions",
                    data=interaction_form(body="Hi", outcome="successful"))
    assert r.status_code == 303
    r = client.post("/companies/acme/interactions",
                    data=interaction_form(body="Hi", outcome="maybe"))
    assert r.status_code == 400 and "unknown outcome" in r.text

    it = app.state.store.get("acme").interactions[0]
    path = interaction_file(repo, "acme", it.id)
    path.write_text(path.read_text().replace("outcome: successful", "outcome: Wants a demo"))
    edit = client.get(f"/companies/acme/interactions/{it.id}/edit").text
    select = edit.split('<select name="outcome">')[1].split("</select>")[0]
    assert '<option value="Wants a demo" selected>Wants a demo</option>' in select
    assert select.count("selected") == 1


def test_outcome_propagates_between_messages_page_and_edit_form(client, app, repo):
    client.post("/companies", data={"name": "Acme"})
    client.post("/companies/acme/interactions", data=interaction_form(
        channel="linkedin", body="Hi there", date=f"{TODAY - timedelta(days=1)}T09:00"))
    it = app.state.store.get("acme").interactions[0]
    path = interaction_file(repo, "acme", it.id)

    # Messages page -> file -> edit form
    page = client.get("/messages").text
    assert '<td class="outcome-unknown">unknown</td>' in page
    buttons = re.findall(r'name="outcome" value="([^"]*)"', page)
    assert buttons == ["successful", "unsuccessful"]  # "Unknown" hidden: it is the current value
    r = client.post(f"/companies/acme/interactions/{it.id}/outcome",
                    data={"outcome": "successful"})
    assert r.status_code == 303 and "Message%20marked%20successful" in r.headers["location"]
    assert "outcome: successful\n" in path.read_text()
    assert last_commit(repo) == f"interaction: acme {it.id} outcome successful"
    edit = client.get(f"/companies/acme/interactions/{it.id}/edit").text
    assert '<option value="successful" selected>' in edit
    page = client.get("/messages").text
    assert '<td class="outcome-successful">successful</td>' in page
    assert re.findall(r'name="outcome" value="([^"]*)"', page) == ["unsuccessful", ""]
    assert "Messages (1)" in client.get("/messages?f_status=successful").text

    # edit form -> file -> Messages page
    r = client.post(f"/companies/acme/interactions/{it.id}/edit", data=interaction_form(
        channel="linkedin", body="Hi there", date=f"{TODAY - timedelta(days=1)}T09:00",
        outcome="unsuccessful"))
    assert r.status_code == 303
    assert "outcome: unsuccessful\n" in path.read_text()
    page = client.get("/messages").text
    assert '<td class="outcome-unsuccessful">unsuccessful</td>' in page
    assert "1 unsuccessful" in page and "0 successful" in page
    assert re.findall(r'name="outcome" value="([^"]*)"', page) == ["successful", ""]
    r = client.post(f"/companies/acme/interactions/{it.id}/outcome", data={"outcome": ""})
    assert "outcome:\n" in path.read_text()
    assert last_commit(repo) == f"interaction: acme {it.id} outcome unknown"
    r = client.post(f"/companies/acme/interactions/{it.id}/outcome", data={"outcome": "meh"})
    assert r.status_code == 303 and "unknown%20outcome" in r.headers["location"]
    assert client.post("/companies/acme/interactions/nope/outcome",
                       data={"outcome": ""}).status_code == 404


def test_messages_page_follows_configured_outcomes(repo):
    app = create_app(repo, config={**CONFIG, "outcomes": ["replied", "no reply"]})
    client = TestClient(app, follow_redirects=False)
    client.post("/companies", data={"name": "Acme"})
    client.post("/companies/acme/interactions", data=interaction_form(
        channel="linkedin", body="Hi", date=f"{TODAY - timedelta(days=30)}T09:00"))
    page = client.get("/messages").text
    assert '<td class="outcome-no-reply">no reply <span class="small">(auto)</span></td>' in page
    assert re.findall(r'name="outcome" value="([^"]*)"', page) == ["replied", "no reply"]
    assert "0 replied &middot; 1 no reply &middot; 0 unknown" in page
    assert "Messages (1)" in client.get("/messages?f_status=no+reply").text
    assert "Messages (0)" in client.get("/messages?f_status=unknown").text
    form = client.get("/companies/acme/interactions/new").text
    assert '<option value="replied">replied</option>' in form
    assert "successful" not in form.split('<select name="outcome">')[1].split("</select>")[0]


# ------------------------------------------------------- message cell (part 2)


def test_message_cell_shows_preview_or_body_not_both(client, app):
    client.post("/companies", data={"name": "Acme"})
    body = "Hello there, " + "this sentence is long enough to be cut in the preview. " * 3
    client.post("/companies/acme/interactions", data=interaction_form(
        channel="linkedin", body=body, date=f"{TODAY - timedelta(days=1)}T09:00"))
    page = client.get("/messages").text
    cell = page.split('<td class="message">')[1].split("</td>")[0]
    summary = cell.split("<summary>")[1].split("</summary>")[0]
    assert summary.startswith('<span class="preview">Hello there, ')
    assert summary.endswith('&hellip;</span><span class="hide">hide</span>')
    assert cell.count("<pre>") == 1 and page.count(body.strip()) == 1
    css = Path(create_app.__code__.co_filename).parent / "static" / "style.css"
    assert "details[open] > summary > .preview { display: none; }" in css.read_text()


# --------------------------------------------------------- delete (part 3)


def test_store_delete_interaction(store, messages):
    store.create_company("Acme")
    it = store.create_interaction("acme", channel="email", direction="out", body="Hi")
    keep = store.create_interaction("acme", channel="call", direction="out",
                                    date="2026-09-01T09:00")
    path = store.company_dir("acme") / "interactions" / f"{it.id}.md"
    messages.clear()
    assert store.delete_interaction("acme", it.id).id == it.id
    assert not path.exists()
    assert [i.id for i in store.get("acme").interactions] == [keep.id]
    assert messages == [f"interaction: acme deleted {it.id}"]
    with pytest.raises(ValidationError):
        store.delete_interaction("acme", it.id)
    with pytest.raises(ValidationError):
        store.delete_interaction("ghost", keep.id)
    store.load()  # the index built from disk agrees
    assert [i.id for i in store.get("acme").interactions] == [keep.id]


def test_delete_interaction_routes(client, app, repo):
    client.post("/companies", data={"name": "Acme"})
    client.post("/companies/acme/contacts", data={"first_name": "Jane", "last_name": "Doe"})
    client.post("/companies/acme/interactions", data=interaction_form(
        channel="linkedin", contact="jane-doe", body="Hello Jane, unique text",
        subject="Kept message", date=f"{TODAY - timedelta(days=3)}T09:00"))
    client.post("/companies/acme/interactions", data=interaction_form(
        channel="email", contact="jane-doe", body="Goodbye Jane, doomed text",
        subject="Doomed message", date=f"{TODAY - timedelta(days=2)}T09:00"))
    doomed, kept = app.state.store.get("acme").interactions[:2]
    assert doomed.subject == "Doomed message"
    path = interaction_file(repo, "acme", doomed.id)

    company_page = client.get("/companies/acme").text
    assert f'action="/companies/acme/interactions/{doomed.id}/delete"' in company_page
    assert 'onclick="return confirm(' in company_page
    edit = client.get(f"/companies/acme/interactions/{doomed.id}/edit").text
    assert f'action="/companies/acme/interactions/{doomed.id}/delete"' in edit
    assert "Delete interaction" in edit
    assert "doomed text" in client.get("/messages").text

    r = client.post(f"/companies/acme/interactions/{doomed.id}/delete",
                    headers={"referer": f"http://testserver/companies/acme/interactions/{doomed.id}/edit"})
    assert r.status_code == 303
    assert r.headers["location"] == "/companies/acme?flash=Interaction%20deleted"
    assert not path.exists()
    assert last_commit(repo) == f"interaction: acme deleted {doomed.id}"
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True,
                          text=True).stdout == ""
    company_page = client.get("/companies/acme").text
    assert "Doomed message" not in company_page and "Kept message" in company_page
    assert "Timeline (1)" in company_page
    messages_page = client.get("/messages").text
    assert "doomed text" not in messages_page and "unique text" in messages_page
    assert client.post(f"/companies/acme/interactions/{doomed.id}/delete").status_code == 404
    assert client.post("/companies/nope/interactions/x/delete").status_code == 404
    contact_page = client.get("/companies/acme/contacts/jane-doe").text
    assert "Doomed message" not in contact_page and "Kept message" in contact_page
    # from a contact page the redirect goes back there
    r = client.post(f"/companies/acme/interactions/{kept.id}/delete",
                    headers={"referer": "http://testserver/companies/acme/contacts/jane-doe"})
    assert r.headers["location"].startswith("/companies/acme/contacts/jane-doe?flash=")
    assert app.state.store.get("acme").interactions == []
