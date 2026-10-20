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

"""Outreach: the AI's original is write-once and every change to the text is a
tracked edit with an optional explainer. The AI and the web are fakes; all
names are made up."""

from __future__ import annotations

import pytest

from hermitcrm import cli, outreach
from hermitcrm.store import Store
from test_outreach_web import (  # noqa: F401  (fixtures)
    MARA, client, commits, drafted, fake, post, query, root,
)


def reread(root, item_id):
    return outreach.get_item(root, item_id)


def test_a_save_with_a_changed_text_is_one_tracked_edit_with_its_explainer(client, root):
    item = drafted(client, root)
    original = item.ai_body
    body = item.body.replace("caught my eye", "stood out")
    before = len(commits(root))
    response = post(client, f"/outreach/{item.id}/check", subject=item.subject, body=body,
                    note="  Too   gushy\nfor a CTO. ")
    assert "tracked edit" in query(response)["flash"]
    assert len(commits(root)) == before + 1
    saved = reread(root, item.id)
    assert saved.ai_body == original and saved.body == body        # original untouched
    [edit] = saved.edits
    assert edit.note == "Too gushy for a CTO." and edit.words == 3 and edit.body == body
    assert len(edit.at) == 16 and edit.at[10] == "T"


def test_a_save_without_a_change_adds_no_edit_and_says_the_note_was_dropped(client, root):
    item = drafted(client, root)
    response = post(client, f"/outreach/{item.id}/check", subject=item.subject,
                    body=item.body, note="because")
    assert "explainer was not kept" in query(response)["flash"]
    assert reread(root, item.id).edits == []


def test_edits_chain_and_each_is_measured_against_the_one_before(client, root):
    item = drafted(client, root)
    first = item.body.replace("caught my eye", "stood out")
    second = first.replace("stood out", "impressed me")
    post(client, f"/outreach/{item.id}/check", subject=item.subject, body=first, note="one")
    post(client, f"/outreach/{item.id}/ready", subject=item.subject, body=second, note="two")
    ready = reread(root, item.id)
    assert [e.note for e in ready.edits] == ["one", "two"]
    assert [e.words for e in ready.edits] == [3, 2]
    assert ready.ai_body == item.ai_body and ready.body == second
    assert ready.edit_distance == outreach.edit_distance(
        item.ai_subject + "\n" + item.ai_body, ready.subject + "\n" + ready.body)


def test_a_hand_edit_of_the_file_is_tracked_at_the_next_step(client, root):
    item = drafted(client, root)
    path = root / item.path
    head, body = path.read_text().split("\n---\n", 1)
    path.write_text(head + "\n---\n" + body.replace("caught my eye", "stood out"),
                    encoding="utf-8")
    post(client, f"/outreach/{item.id}/ready", subject=item.subject)
    ready = reread(root, item.id)
    assert len(ready.edits) == 1 and ready.edits[0].body == ready.body


def test_a_too_long_explainer_is_refused_and_nothing_is_written(client, root):
    item = drafted(client, root)
    before = commits(root)
    response = post(client, f"/outreach/{item.id}/check", subject=item.subject,
                    body=item.body + "x", note="w" * 501)
    assert "keep it under 500" in query(response)["flash"]
    assert commits(root) == before and reread(root, item.id).edits == []


def test_the_original_and_the_edits_cannot_be_overwritten(client, root):
    item = drafted(client, root)
    post(client, f"/outreach/{item.id}/check", subject=item.subject,
         body=item.body + "More.\n", note="added a line")
    current = reread(root, item.id)

    tampered = reread(root, item.id)
    tampered.ai_body = "A friendlier original, written afterwards."
    with pytest.raises(outreach.OutreachError, match="cannot be changed"):
        outreach.write_item(root, tampered)

    rewritten = reread(root, item.id)
    rewritten.edits[0].note = "Changed my mind about why."
    with pytest.raises(outreach.OutreachError, match="cannot be changed"):
        outreach.write_item(root, rewritten)

    dropped = reread(root, item.id)
    dropped.edits = []
    with pytest.raises(outreach.OutreachError, match="cannot be changed"):
        outreach.write_item(root, dropped)

    assert reread(root, item.id).ai_body == current.ai_body
    assert reread(root, item.id).edits == current.edits


def test_regenerate_archives_the_old_draft_with_its_edits_and_the_reason(client, root, fake):
    item = drafted(client, root)
    post(client, f"/outreach/{item.id}/check", subject=item.subject,
         body=item.body.replace("caught my eye", "stood out"), note="softer")
    response = post(client, f"/outreach/{item.id}/regenerate", note="  sounds like a template ")
    assert "Regenerated" in query(response)["flash"]
    again = reread(root, item.id)
    [old] = again.earlier
    assert old.ai_body == item.ai_body and old.why == "sounds like a template"
    assert [e.note for e in old.edits] == ["softer"]
    assert again.edits == [] and again.ai_body == again.body
    page = client.get("/outreach")
    assert "1 regenerated away" in page.text and "sounds like a template" in page.text


def test_the_card_shows_the_original_and_each_edit_as_a_change(client, root):
    item = drafted(client, root)
    post(client, f"/outreach/{item.id}/check", subject=item.subject,
         body=item.body.replace("caught my eye", "stood out"), note="plainer verb")
    page = client.get("/outreach").text
    assert "AI original and 1 tracked edit" in page
    assert "plainer verb" in page
    assert "<del>caught my eye.</del><ins>stood out.</ins>" in page
    assert 'name="note"' in page


def test_old_items_without_the_new_keys_still_read(client, root):
    item = drafted(client, root)
    path = root / item.path
    text = path.read_text()
    lines = [ln for ln in text.split("\n") if not ln.startswith(("edits:", "earlier:"))]
    path.write_text("\n".join(lines), encoding="utf-8")
    old = reread(root, item.id)
    assert old.edits == [] and old.earlier == []


def test_the_item_file_round_trips_byte_for_byte_with_edits(client, root):
    item = drafted(client, root)
    post(client, f"/outreach/{item.id}/check", subject=item.subject,
         body='Hi "Mara":\n\ttab, colon: and ünïcode\n', note="quotes: \"x\" and: colons")
    path = root / item.path
    again = reread(root, item.id)
    assert outreach.item_text(again) == path.read_text()
    assert again.edits[0].note == 'quotes: "x" and: colons'
    assert again.edits[0].body == 'Hi "Mara":\n\ttab, colon: and ünïcode\n'


def _send_and_answer(root, item, outcome):
    """Mark the item sent, then log a reply from the contact with `outcome`."""
    outreach.mark_sent(_store(root), item.id)
    store = _store(root)
    when = store.now()
    store.create_interaction("lindenhof-data", "email", "in", contact="mara-keller",
                             body="Yes, tell me more.", outcome=outcome, date=when)


def _store(root):
    store = Store(root)
    store.load()
    return store


def test_the_edits_report_pairs_the_change_with_the_answer(client, root, capsys):
    item = drafted(client, root)
    post(client, f"/outreach/{item.id}/ready", subject=item.subject,
         body=item.body.replace("caught my eye", "stood out"), note="plainer verb")
    ready = reread(root, item.id)
    _send_and_answer(root, ready, "interested")
    assert cli.main(["outreach", "edits"], root=root) == 0
    out = capsys.readouterr().out
    assert ": positive" in out and "plainer verb" in out
    assert "[-caught my eye.-]{+stood out.+}" in out
    assert "AI original:" in out and "What went out:" in out
    assert cli.main(["outreach", "edits", "--positive", "--noted"], root=root) == 0
    assert "plainer verb" in capsys.readouterr().out


def test_the_edits_report_leaves_out_other_answers_and_says_when_empty(client, root, capsys):
    assert cli.main(["outreach", "edits"], root=root) == 0
    assert "No tracked edits yet" in capsys.readouterr().out
    item = drafted(client, root)
    post(client, f"/outreach/{item.id}/ready", subject=item.subject,
         body=item.body.replace("caught my eye", "stood out"), note="plainer verb")
    assert cli.main(["outreach", "edits", "--positive"], root=root) == 0
    assert "plainer verb" not in capsys.readouterr().out


def card_form(page: str, item_id: str) -> str:
    """The Mark ready form of one card, from its opening tag to its closing tag."""
    start = page.index(f'action="/outreach/{item_id}/ready"')
    return page[start:page.index("</form>", start)]


def test_one_reason_box_serves_the_edit_and_the_regenerate(client, root):
    item = drafted(client, root)
    page = client.get("/outreach").text
    form = card_form(page, item.id)
    assert form.count('name="note"') == 1                      # one box, not one per action
    label = form[form.rindex("<label", 0, form.index('name="note"')):]
    assert "hidden" not in label[:label.index(">")]            # regenerate needs it at any time
    assert f'formaction="/outreach/{item.id}/regenerate"' in form
    assert 'name="strong"' in form                             # the stronger-model choice rides along
    assert f'<form method="post" action="/outreach/{item.id}/regenerate"' not in page
    assert "helps improve the AI" in page
    assert "Why this change?" not in page and "what was wrong?" not in page


def test_a_regenerate_posted_from_the_edit_form_keeps_the_reason_and_drops_unsaved_text(
        client, root, fake):
    item = drafted(client, root)
    response = post(client, f"/outreach/{item.id}/regenerate", subject=item.subject,
                    body=item.body.replace("caught my eye", "stood out"), pitch="",
                    note="too formal", tags="too-long", strong="1")
    assert "Regenerated" in query(response)["flash"]
    again = reread(root, item.id)
    [old] = again.earlier
    assert old.why == "too formal" and old.edits == []         # the box was never saved as an edit
    assert again.edits == []
