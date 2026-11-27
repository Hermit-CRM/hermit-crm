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

"""The contact card behind Save to phone: its lines, what it leaves out, and
the QR code that carries it."""

from __future__ import annotations

import sys

import pytest
import segno

from hermitcrm import vcard
from hermitcrm.models import Company, Contact, Task


def company(name: str = "Acme GmbH") -> Company:
    return Company(name=name, slug="acme")


def jane(**fields) -> Contact:
    values = {"title": "CTO", "email": "jane@acme.example", "phone": "+49 30 1234567",
              "linkedin": "https://www.linkedin.com/in/jane-doe", **fields}
    return Contact(first_name="Jane", last_name="Doe", slug="jane-doe", **values)


def lines(contact: Contact, at: Company | None = None) -> list[str]:
    return vcard.card(contact, at or company()).split("\r\n")


def test_the_card_holds_the_contact_fields():
    assert vcard.card(jane(), company()) == "\r\n".join([
        "BEGIN:VCARD", "VERSION:3.0", "N:Doe;Jane;;;", "FN:Jane Doe", "ORG:Acme GmbH",
        "TITLE:CTO", "TEL:+49 30 1234567", "EMAIL:jane@acme.example",
        "URL:https://www.linkedin.com/in/jane-doe", "END:VCARD", ""])


def test_empty_fields_are_left_out():
    max_ = Contact(first_name="Max", last_name="", slug="max", phone="  ")
    assert lines(max_) == ["BEGIN:VCARD", "VERSION:3.0", "N:;Max;;;", "FN:Max",
                           "ORG:Acme GmbH", "END:VCARD", ""]


def test_commas_semicolons_backslashes_and_line_breaks_cannot_break_the_card():
    contact = jane(title="Head of Risk\r\nEND:VCARD\nTEL:+1\rx\x00y")
    out = lines(contact, company("Acme, Inc; \\ Co"))
    assert "ORG:Acme\\, Inc\\; \\\\ Co" in out
    assert "TITLE:Head of Risk\\nEND:VCARD\\nTEL:+1\\nxy" in out
    assert out.count("END:VCARD") == 1
    assert [x for x in out if x.startswith("TEL:")] == ["TEL:+49 30 1234567"]


def test_a_tab_is_ordinary_text():
    assert "TITLE:Head\tof Risk" in lines(jane(title="Head\tof Risk"))


def test_a_semicolon_in_a_name_stays_inside_its_part():
    contact = Contact(first_name="Ann;Marie", last_name="Roe, Jr", slug="a")
    assert "N:Roe\\, Jr;Ann\\;Marie;;;" in lines(contact)


def test_notes_tasks_and_your_own_fields_never_go_on_the_card():
    contact = jane(notes="private remark", extra={"my_score": "secret score"},
                   tasks=[Task(text="secret errand")], role="champion")
    text = vcard.card(contact, company())
    for private in ("private remark", "secret score", "secret errand", "champion"):
        assert private not in text


@pytest.mark.parametrize("stored", ["javascript:alert(1)", "linkedin.com/in/jane",
                                    "https://example.com/a\r\nTEL:+1", ""])
def test_only_a_web_address_goes_on_the_card(stored):
    assert not [x for x in lines(jane(linkedin=stored)) if x.startswith("URL:")]


# ------------------------------------------------------------------ the code


def test_the_code_carries_utf8_so_accented_names_survive(monkeypatch):
    seen = []
    real = segno.make_qr

    def spy(content, **options):
        seen.append(content)
        return real(content, **options)

    monkeypatch.setattr(segno, "make_qr", spy)
    vcard.qr_svg("FN:Zoë Łukasz")
    assert seen == ["FN:Zoë Łukasz".encode("utf-8")]


def test_the_code_is_a_scalable_black_on_white_svg_without_text():
    svg = vcard.qr_svg(vcard.card(jane(), company()))
    assert svg.startswith("<svg ") and "viewBox=" in svg
    assert 'width="' not in svg  # sized by the page's CSS
    assert 'fill="#fff"' in svg and 'stroke="#000"' in svg
    assert "Jane" not in svg and "<text" not in svg


def test_a_card_too_long_for_one_code_says_so():
    with pytest.raises(vcard.CardError, match="too long"):
        vcard.qr_svg("x" * 3000)


def test_without_segno_installed_it_says_what_to_do(monkeypatch):
    monkeypatch.setitem(sys.modules, "segno", None)  # makes `import segno` fail
    with pytest.raises(vcard.CardError, match="pip install segno"):
        vcard.qr_svg("x")
