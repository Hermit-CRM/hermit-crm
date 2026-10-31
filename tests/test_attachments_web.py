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
