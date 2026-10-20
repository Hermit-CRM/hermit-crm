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

"""One click copies an email address: on an Outreach card and on the contact
page (docs/superpowers/specs/2026-10-20-outreach-notes-and-drafts-design.md,
part A). The address stays a mailto link."""

from __future__ import annotations

import re

from outreach_client import MARA_EMAIL, client, drafted, root, fake  # noqa: F401

CONTACT = "/companies/lindenhof-data/contacts/mara-keller"


def test_outreach_card_has_a_copy_button_next_to_the_email(client, root):
    drafted(client, root)
    page = client.get("/outreach").text
    assert f'data-copy-text="{MARA_EMAIL}"' in page
    assert f'href="mailto:{MARA_EMAIL}"' in page


def test_contact_details_row_has_a_copy_button_and_keeps_the_mailto_link(client):
    page = client.get(CONTACT).text
    row = re.search(r"<dt>email</dt><dd>(.*?)</dd>", page, re.S).group(1)
    assert f'data-copy-text="{MARA_EMAIL}"' in row
    assert f'href="mailto:{MARA_EMAIL}"' in row


def test_copy_script_is_served_and_loaded_on_every_page(client):
    assert client.get("/static/copy.js").status_code == 200
    assert "/static/copy.js" in client.get(CONTACT).text
