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

"""Attachments in the web app: serving, uploading, the Files section
(docs/superpowers/plans/2026-10-31-attachments.md, Tasks 2 to 4)."""

from __future__ import annotations

import pytest

from hermitcrm.attachments import Incoming
from test_layout import app, client, repo  # noqa: F401  (the same git-backed folder)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PDF = b"%PDF-1.4 example\n"
SCRIPT = b"<script>fetch('/settings')</script>"


@pytest.fixture
def store(app):
    store = app.state.store
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe", email="jane@acme.example")
    return store


def attach(store, name: str, data: bytes):
    it = store.create_interaction("acme", "note", "", body="x",
                                  attachments=[Incoming(name, data)])
    return it.attachments[0]


def url(att) -> str:
    return f"/companies/acme/attachments/{att.file}"


# ------------------------------------------------------------------- serving


def test_png_is_inline_with_nosniff(store, client):
    r = client.get(url(attach(store, "pic.png", PNG)))
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-type"] == "image/png"


@pytest.mark.parametrize("name", ["evil.svg", "evil.html", "evil.htm", "tool.exe", "page.xhtml"])
def test_scripty_and_unknown_types_download(store, client, name):
    r = client.get(url(attach(store, name, SCRIPT)))
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_the_stored_type_cannot_make_a_script_inline(store, client, repo):
    att = attach(store, "evil.svg", SCRIPT)
    path = store.interaction_file("acme", store.get("acme").interactions[0].id)
    text = path.read_text(encoding="utf-8").replace("type: image/svg+xml", "type: image/png")
    path.write_text(text, encoding="utf-8")
    store.load()
    r = client.get(url(att))
    assert r.headers["content-disposition"].startswith("attachment")


def test_pdf_is_inline_and_text_has_a_charset(store, client):
    pdf = client.get(url(attach(store, "deck.pdf", PDF)))
    assert pdf.headers["content-disposition"].startswith("inline")
    assert pdf.headers["content-type"] == "application/pdf"
    assert "sandbox" not in pdf.headers["content-security-policy"]  # the viewer needs it
    txt = client.get(url(attach(store, "notes.txt", b"plain text")))
    assert txt.headers["content-disposition"].startswith("inline")
    assert txt.headers["content-type"].startswith("text/plain")


def test_download_flag_forces_a_download(store, client):
    r = client.get(url(attach(store, "pic.png", PNG)) + "?download=1")
    assert r.headers["content-disposition"].startswith("attachment")


def test_filename_header_cannot_be_injected(store, client):
    att = attach(store, 'a"b\r\nX-Evil: 1.pdf', PDF)
    r = client.get(url(att))
    assert r.status_code == 200
    assert "x-evil" not in r.headers
    assert len(r.headers.get_list("content-disposition")) == 1
    assert "\n" not in r.headers["content-disposition"]


def test_non_ascii_name_uses_the_extended_form(store, client):
    r = client.get(url(attach(store, "Überblick é.pdf", PDF)))
    assert "filename*=" in r.headers["content-disposition"]


def test_traversal_and_unknown_names_are_404(store, client):
    attach(store, "a.pdf", PDF)
    for bad in ("..%2f..%2fcompany.md", "company.md", "..%2fcompany.md", "%00",
                "0123456789ab-missing.pdf"):
        assert client.get(f"/companies/acme/attachments/{bad}").status_code == 404, bad


def test_a_file_nothing_refers_to_is_not_served(store, client):
    att = attach(store, "a.pdf", PDF)
    orphan = store.attachment_path("acme", "0123456789ab-orphan.pdf")
    orphan.write_bytes(b"secret")
    assert client.get("/companies/acme/attachments/0123456789ab-orphan.pdf").status_code == 404
    assert client.get(url(att)).status_code == 200


def test_a_referenced_file_missing_on_disk_is_404(store, client):
    att = attach(store, "a.pdf", PDF)
    store.attachment_path("acme", att.file).unlink()
    assert client.get(url(att)).status_code == 404


def test_unknown_company_is_404(client):
    assert client.get("/companies/nope/attachments/0123456789ab-a.pdf").status_code == 404


# --------------------------------------------------------- attaching in forms

import re
import subprocess

NOTE = {"channel": "note", "direction": "out", "contact": "", "date": "", "subject": "",
        "outcome": "", "body": "Sent the proposal."}


def git(repo, *args) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          check=True).stdout.strip()


def commits(repo) -> int:
    return int(git(repo, "rev-list", "--count", "HEAD"))


def post_note(client, files, data=None, headers=None):
    return client.post("/companies/acme/interactions", data=data or NOTE, files=files,
                       headers=headers or {})


def pdf_part(name="Proposal.pdf", data=PDF):
    return [("files", (name, data, "application/pdf"))]


def test_note_with_a_file_is_one_commit(store, client, repo):
    before = commits(repo)
    r = post_note(client, pdf_part())
    assert r.status_code == 303
    (note,) = store.get("acme").interactions
    (att,) = note.attachments
    assert att.name == "Proposal.pdf" and note.body == "Sent the proposal.\n"
    assert commits(repo) == before + 1
    changed = git(repo, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert f"companies/acme/attachments/{att.file}" in changed
    assert f"companies/acme/interactions/{note.id}.md" in changed


@pytest.mark.parametrize("files", [None, [("files", ("", b"", "application/octet-stream"))]])
def test_note_form_still_works_without_files(store, client, files):
    r = post_note(client, files) if files else client.post("/companies/acme/interactions",
                                                           data=NOTE)
    assert r.status_code == 303
    (note,) = store.get("acme").interactions
    assert note.attachments == []
    assert "attachments" not in store.interaction_file("acme", note.id).read_text()


def test_several_files_and_a_nameless_zero_byte_part(store, client):
    r = post_note(client, pdf_part() + [("files", ("notes.txt", b"hello", "text/plain")),
                                        ("files", ("empty.txt", b"", "text/plain"))])
    assert r.status_code == 303
    names = [a.name for a in store.get("acme").interactions[0].attachments]
    assert names == ["Proposal.pdf", "notes.txt"]  # an empty file is not worth keeping


def test_over_cap_upload_writes_nothing(store, client, repo):
    (repo / "config.toml").write_text("attachment_max_mb = 1\n")
    before = commits(repo)
    r = post_note(client, pdf_part("big.bin", b"0" * (1024 * 1024 + 1)))
    assert r.status_code == 400
    assert "larger than 1 MB" in r.text and "Sent the proposal." in r.text  # typed text kept
    assert store.get("acme").interactions == []
    assert not (repo / "companies" / "acme" / "attachments").exists()
    assert commits(repo) == before


def test_a_huge_request_is_refused_before_it_is_parsed(store, client, repo):
    (repo / "config.toml").write_text("attachment_max_mb = 1\n")
    r = post_note(client, pdf_part("big.bin", b"0" * (6 * 1024 * 1024)))
    assert r.status_code == 413
    assert store.get("acme").interactions == []


def test_a_cross_site_upload_is_refused(store, client):
    r = post_note(client, pdf_part(), headers={"Origin": "https://evil.example",
                                               "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and store.get("acme").interactions == []


def test_edit_save_can_add_a_file(store, client):
    note = store.create_interaction("acme", "note", "", body="x")
    r = client.post(f"/companies/acme/interactions/{note.id}/edit",
                    data={**NOTE, "body": "x", "date": "2026-09-14T10:30"}, files=pdf_part())
    assert r.status_code == 303
    assert [a.name for a in store.get("acme").interactions[0].attachments] == ["Proposal.pdf"]


def test_add_and_remove_on_an_existing_note(store, client):
    note = store.create_interaction("acme", "note", "", body="x")
    r = client.post(f"/companies/acme/interactions/{note.id}/attachments", files=pdf_part(),
                    headers={"Accept": "application/json"})
    assert r.status_code == 200 and r.json()["ok"] is True
    (att,) = store.get("acme").interactions[0].attachments
    assert r.json()["attachments"][0]["file"] == att.file
    r = client.post(f"/companies/acme/interactions/{note.id}/attachments/{att.file}/delete")
    assert r.status_code == 303
    assert store.get("acme").interactions[0].attachments == []
    assert not store.attachment_path("acme", att.file).exists()


def test_add_to_an_unknown_note_is_404(store, client):
    r = client.post("/companies/acme/interactions/nope/attachments", files=pdf_part())
    assert r.status_code == 404


def test_edit_page_lists_files_with_remove(store, client):
    att = attach(store, "Proposal.pdf", PDF)
    note = store.get("acme").interactions[0]
    page = client.get(f"/companies/acme/interactions/{note.id}/edit").text
    assert "Proposal.pdf" in page and url(att) in page
    assert f"/interactions/{note.id}/attachments/{att.file}/delete" in page
    assert 'enctype="multipart/form-data"' in page and 'name="files"' in page


def test_timeline_shows_chip_and_thumbnail_for_png(store, client):
    png, pdf = attach(store, "pic.png", PNG), attach(store, "Proposal.pdf", PDF)
    page = client.get("/companies/acme").text
    assert f'href="{url(pdf)}"' in page and "Proposal.pdf" in page
    assert re.search(rf'<img[^>]+src="{re.escape(url(png))}"', page)
    assert not re.search(rf'<img[^>]+src="{re.escape(url(pdf))}"', page)
    assert "17 B" in page or "17&nbsp;B" in page   # the size, humanised


def test_note_form_offers_the_picker_and_the_script(store, client):
    page = client.get("/companies/acme/interactions/new?channel=note&whole=1").text
    assert 'enctype="multipart/form-data"' in page and 'type="file"' in page
    assert "/static/attach.js" in page
    assert client.get("/static/attach.js").status_code == 200
