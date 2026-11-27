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

"""A contact as a vCard, and the QR code a phone camera saves it from.

The card carries what a phone's address book needs and nothing else: never
notes, tasks or interactions. It is drawn on this computer and sent nowhere.

The card is written here rather than by segno's own helper, which escapes the
colon in a web address and leaves commas and line breaks as they are.
"""

from __future__ import annotations

import re

from .models import Company, Contact, safe_href

# Control characters have no place in a card. A tab is allowed, and a line break
# (\x0a) is escaped instead.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class CardError(Exception):
    """Why no code can be shown, in words for the page."""


def _text(value: str) -> str:
    """A value as vCard 3.0 text (RFC 2426): one line, separators escaped."""
    value = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    value = _CONTROL.sub("", value).strip()
    return (value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\n", "\\n"))


def card(contact: Contact, company: Company) -> str:
    """The contact as a vCard 3.0, empty fields left out."""
    fields = [("ORG", _text(company.name)),
              ("TITLE", _text(contact.title)),
              ("TEL", _text(contact.phone)),
              ("EMAIL", _text(contact.email)),
              # An address, not text: a comma in it stays a comma.
              ("URL", safe_href(contact.linkedin))]
    name = f"{_text(contact.first_name)} {_text(contact.last_name)}".strip()
    lines = ["BEGIN:VCARD", "VERSION:3.0",
             f"N:{_text(contact.last_name)};{_text(contact.first_name)};;;",
             f"FN:{name}",
             *(f"{key}:{value}" for key, value in fields if value),
             "END:VCARD", ""]
    return "\r\n".join(lines)


def qr_svg(text: str) -> str:
    """`text` as a QR code: an inline SVG, black on white in every theme (a
    camera needs the contrast), sized by the page."""
    try:
        import segno
    except ImportError:  # code updated without reinstalling: segno is newer
        raise CardError("The code needs the segno package: update Hermit CRM "
                        "(or pip install segno).") from None
    try:
        # UTF-8 bytes: left to choose, segno may pick Latin-1, which phones
        # can read back as the wrong accents.
        code = segno.make_qr(text.encode("utf-8"), error="m")
    except segno.DataOverflowError:
        raise CardError("This contact's details are too long for one code: shorten "
                        "the title or the LinkedIn address.") from None
    return code.svg_inline(border=4, dark="#000", light="#fff", omitsize=True)
