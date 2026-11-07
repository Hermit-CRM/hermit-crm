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

"""The Files panel on an Outreach card: attach to a draft or ready email, remove, attach
again, and what is refused.
The AI is a fake; all names are made up."""

from __future__ import annotations

import re

from hermitcrm import outreach
from hermitcrm.attachments import Incoming
from hermitcrm.setup import set_config_values
from outreach_client import MARA, client, commits, drafted, post, query, root  # noqa: F401
from outreach_client import fake  # noqa: F401

PDF = b"%PDF-1.4 one-pager\n"


def panel(client, item, tab: str = "drafts") -> str:
    """The Files panel of one card: from its id to what follows it on the card."""
    page = client.get(f"/outreach?tab={tab}").text
    assert f'id="files-{item.id}"' in page, "the card has no Files panel"
    rest = page.split(f'id="files-{item.id}"', 1)[1]
    for end in ('<div class="draft-actions">', f'id="skip-{item.id}"'):
        rest = rest.split(end, 1)[0]
    return rest


def upload(client, item, name="One pager.pdf", data=PDF, token=True, **extra):
    fields = {"csrf_token": client.app.state.csrf_token} if token else {}
    return client.post(f"/outreach/{item.id}/attach", data={**fields, **extra},
                       files=[("files", (name, data, "application/pdf"))])


def test_a_draft_card_has_a_files_panel_with_a_plain_form(client, root, fake):
    item = drafted(client, root)
    block = panel(client, item)
    assert "none attached" in block
    assert f'action="/outreach/{item.id}/attach"' in block
    assert 'enctype="multipart/form-data"' in block and "data-attach" in block


def test_attaching_a_file_saves_it_and_shows_it(client, root, fake):
    item = drafted(client, root)
    before = len(commits(root))
    r = upload(client, item)
    assert r.status_code == 303 and "Attached 1 file" in query(r)["flash"]
    saved = outreach.get_item(root, item.id)
    assert [a.name for a in saved.attachments] == ["One pager.pdf"]
    assert len(commits(root)) == before + 1 and commits(root)[0].startswith("outreach: attachments")
    block = panel(client, item)
    assert "One pager.pdf" in block and f"/outreach/{item.id}/detach" in block
    assert "filtered as spam" in block           # a cold first email with a file


def test_removing_a_file_takes_it_off_and_deletes_it(client, root, fake):
    item = drafted(client, root)
    upload(client, item)
    att = outreach.get_item(root, item.id).attachments[0]
    r = post(client, f"/outreach/{item.id}/detach", file=att.file)
    assert r.status_code == 303 and "taken off" in query(r)["flash"]
    assert outreach.get_item(root, item.id).attachments == []
    assert not (root / "companies" / item.company / "attachments" / att.file).exists()


def test_attach_again_offers_a_file_already_on_the_company(client, root, fake):
    item = drafted(client, root)
    store = client.app.state.store
    note = store.create_interaction(item.company, "note", "", contact=item.contact, body="x",
                                    attachments=[Incoming("Deck.pdf", PDF)])
    assert "attach again" in panel(client, item) and "Deck.pdf" in panel(client, item)
    r = client.post(f"/outreach/{item.id}/attach", data={
        "csrf_token": client.app.state.csrf_token, "reuse": note.attachments[0].file})
    assert r.status_code == 303 and "Attached 1 file" in query(r)["flash"]
    assert outreach.get_item(root, item.id).attachments == note.attachments
    assert "attach again" not in panel(client, item)        # nothing left to offer


def test_the_forgotten_attachment_is_flagged_on_the_card(client, root, fake):
    item = drafted(client, root)
    item.body = "Hi Mara,\n\nI attached our one-pager.\n"
    outreach.write_item(root, item)
    assert "mentions an attachment, but no file is attached" in panel(client, item)


def test_attach_needs_the_csrf_token_and_refuses_another_site(client, root, fake):
    item = drafted(client, root)
    assert upload(client, item, token=False).status_code == 403
    r = client.post(f"/outreach/{item.id}/attach", headers={
        "Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        data={"csrf_token": client.app.state.csrf_token},
        files=[("files", ("a.pdf", PDF, "application/pdf"))])
    assert r.status_code == 403
    assert outreach.get_item(root, item.id).attachments == []


def test_nothing_chosen_over_the_limit_and_an_unknown_item(client, root, fake):
    item = drafted(client, root)
    r = client.post(f"/outreach/{item.id}/attach", data={"csrf_token": client.app.state.csrf_token})
    assert r.status_code == 303 and "choose a file" in query(r)["flash"]
    set_config_values(root / "config.toml", {"send_attachment_max_mb": 1})
    r = upload(client, item, name="big.bin", data=b"0" * (1024 * 1024 + 1))
    assert r.status_code == 303 and "Not attached" in query(r)["flash"]
    assert outreach.get_item(root, item.id).attachments == []
    assert not (root / "companies" / item.company / "attachments").exists()
    assert upload(client, type("I", (), {"id": "nope"})()).status_code == 404


def test_a_huge_request_is_refused_before_it_is_parsed(client, root, fake):
    item = drafted(client, root)
    set_config_values(root / "config.toml", {"attachment_max_mb": 1})
    assert upload(client, item, name="big.bin", data=b"0" * (6 * 1024 * 1024)).status_code == 413


def test_a_queued_item_shows_its_files_but_cannot_change_them(client, root, fake):
    item = drafted(client, root)
    upload(client, item)
    saved = outreach.get_item(root, item.id)
    saved.state = "queued"
    outreach.write_item(root, saved)
    block = panel(client, saved, "scheduled")
    assert "One pager.pdf" in block and "Unschedule it to change the files" in block
    assert "/detach" not in block and f'action="/outreach/{item.id}/attach"' not in block
    r = post(client, f"/outreach/{item.id}/detach", file=saved.attachments[0].file)
    assert "Not removed" in query(r)["flash"] and "unschedule" in query(r)["flash"]


def test_a_linkedin_card_has_no_files_panel(client, root, fake):
    item = drafted(client, root)
    item.channel = "linkedin"
    outreach.write_item(root, item)
    assert f'id="files-{item.id}"' not in client.get("/outreach").text
    r = upload(client, item)
    assert r.status_code == 303 and "LinkedIn" in query(r)["flash"]


def test_the_card_names_the_files_of_a_sent_email_in_show(client, root, fake):
    item = drafted(client, root)
    upload(client, item)
    text = outreach.render_item(client.app.state.store, outreach.get_item(root, item.id))
    assert re.search(r"Files: One pager\.pdf \(\d+ B\)", text)
    assert "first email with a file attached" in text
