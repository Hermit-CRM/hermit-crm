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

"""Save to phone on the contact page: the button, its code, and what the panel
says when there is no number or no code."""

from __future__ import annotations

import re
import sys

import pytest

from hermitcrm import vcard
from test_layout import app, client, repo  # noqa: F401  (the same git-backed folder)

JANE = "/companies/acme/contacts/jane-doe"
# A popover: hidden until pressed, then centred on the screen, so a button at the
# end of the row cannot push the code off the page.
OPEN = '<div id="phone-card" class="phone-card" popover>'
CLOSE = 'popovertargetaction="hide"'


@pytest.fixture
def store(app):
    store = app.state.store
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe", title="CTO", email="jane@acme.example")
    return store


def panel(response) -> str:
    assert response.status_code == 200
    page = response.text
    assert page.count(OPEN) == 1
    return page.split(OPEN, 1)[1].split(CLOSE, 1)[0]


def test_the_contact_page_holds_this_contacts_code_behind_a_button(store, client):
    response = client.get(JANE)
    html = panel(response)
    assert re.search(r'<button type="button" popovertarget="phone-card">'
                     r'(?:(?!</button>).)*Save to phone</button>', response.text, re.S)
    company = store.get("acme")
    expected = vcard.qr_svg(vcard.card(company.contacts["jane-doe"], company))
    assert expected in html


def test_without_a_number_it_says_so_and_links_to_add_one(store, client):
    html = panel(client.get(JANE))
    assert "No phone number yet" in html
    assert 'href="?edit=1#details"' in html


def test_with_a_number_there_is_no_such_note(store, client):
    store.update_contact("acme", "jane-doe", phone="+49 30 1234567")
    html = panel(client.get(JANE))
    assert "No phone number yet" not in html
    assert "<svg " in html


def test_details_too_long_for_a_code_are_explained_on_the_page(store, client):
    store.update_contact("acme", "jane-doe", title="x" * 3000)
    html = panel(client.get(JANE))
    assert "too long for one code" in html
    assert 'class="segno"' not in html


def test_without_segno_the_page_still_renders(store, client, monkeypatch):
    monkeypatch.setitem(sys.modules, "segno", None)
    assert "pip install segno" in panel(client.get(JANE))


def test_a_name_with_markup_in_it_stays_text(store, client):
    store.create_contact("acme", "<script>alert(1)</script>", "Roe")
    slug = next(s for s in store.get("acme").contacts if s != "jane-doe")
    response = client.get(f"/companies/acme/contacts/{slug}")
    assert "<script>alert(1)" not in panel(response)
    assert "<script>alert(1)" not in response.text
