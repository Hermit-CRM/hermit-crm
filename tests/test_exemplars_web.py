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

"""Learning by example on the web: the Examples section of the Learning page
(pin, exclude, clear), the Settings switches, and the Outreach card's "Modeled
on" line. The AI is a fake; names are made up."""

from __future__ import annotations

from hermitcrm import exemplars
from hermitcrm.store import load_config
from test_exemplars import TARGET, corrected, language_of_target, worked
from test_learning import APPROACH, folder, make  # noqa: F401
from test_learning_web import flash, make_client, post, text


def test_the_page_says_none_yet(folder):
    root, store = folder
    page = text(make_client(root).get(f"/learning?approach={APPROACH}"))
    assert 'id="examples"' in page and "None yet. Corrections appear" in page
    assert "Setting</a>: <strong>off</strong>" in page
    assert "the draft prompt is not changed" in page
    assert "angle" not in page.lower()


def test_the_page_lists_exemplars_and_what_the_drafter_would_see(folder):
    root, store = folder
    worked(root, store, 1, 0)
    corrected(root, 2, 1)
    client = make_client(root, learning_exemplars="both")
    page = text(client.get(f"/learning?approach={APPROACH}"))
    assert "1 from messages that worked, 1 from your corrections" in page
    assert "<strong>Worked</strong>: positive reply" in page
    assert "<strong>Corrected</strong>: your correction" in page
    assert "You wrote: " in page and "They changed it to: " in page
    assert 'name="exemplar" value="outcome:t01"' in page
    assert "<strong>both</strong>, 2 per first-touch draft" in page


def test_pin_exclude_and_clear_from_the_page(folder):
    root, store = folder
    worked(root, store, 1, 0)
    client = make_client(root)
    pinned = flash(post(client, "/learning/exemplar", approach=APPROACH,
                        exemplar="outcome:t01", mark="pin"))
    assert pinned.startswith("Pinned: it leads when it is close enough.")
    assert exemplars.load_marks(root)["pin"] == ["outcome:t01"]
    page = text(client.get(f"/learning?approach={APPROACH}"))
    assert '<span class="tag">pinned</span>' in page and "1 pinned" in page
    assert 'name="mark" value="exclude"' in page and 'name="mark" value="clear"' in page
    assert 'name="mark" value="pin"' not in page          # already pinned
    assert flash(post(client, "/learning/exemplar", approach=APPROACH,
                      exemplar="outcome:t01", mark="exclude")).startswith("Excluded: ")
    assert "1 excluded" in text(client.get(f"/learning?approach={APPROACH}"))
    assert flash(post(client, "/learning/exemplar", approach=APPROACH,
                      exemplar="outcome:t01", mark="clear")).startswith("Back to normal.")
    assert exemplars.load_marks(root) == {"pin": [], "exclude": []}


def test_a_bad_mark_or_exemplar_is_a_flash_not_an_error(folder):
    root, store = folder
    client = make_client(root)
    assert "no exemplar" in flash(post(client, "/learning/exemplar", approach=APPROACH,
                                       exemplar="outcome:nope", mark="pin"))
    worked(root, store, 1, 0)
    assert "mark is one of" in flash(post(client, "/learning/exemplar", approach=APPROACH,
                                          exemplar="outcome:t01", mark="love"))
    assert client.post("/learning/exemplar", data={"exemplar": "outcome:t01",
                                                   "mark": "pin"}).status_code == 403
    assert not (root / exemplars.MARKS_FILE).exists()


def test_the_settings_save_examples_and_leave_others_alone(folder):
    root, store = folder
    client = make_client(root)
    page = client.get("/settings").text
    assert 'name="learning_exemplars"' in page and "learning_angle_sampling" not in page
    assert flash(post(client, "/settings/learning", learning_distill="hermit",
                      learning_exemplars="both")).startswith(
        "Learning saved: hermit, examples both.")
    config = load_config(root)
    assert config["learning_exemplars"] == "both"
    assert 'value="both" selected' in client.get("/settings").text
    # a form that only knows the distil setting changes nothing else
    flash(post(client, "/settings/learning", learning_distill="handoff"))
    config = load_config(root)
    assert config["learning_distill"] == "handoff"
    assert config["learning_exemplars"] == "both"
    assert "Examples are off" in flash(post(client, "/settings/learning",
                                            learning_distill="hermit", learning_exemplars="all"))
    assert load_config(root)["learning_exemplars"] == "both"
    flash(post(client, "/settings/learning", learning_distill="hermit",
               learning_exemplars="off"))
    assert load_config(root)["learning_exemplars"] == "off"


def test_the_card_says_what_the_draft_was_modeled_on(folder):
    root, store = folder
    lang = language_of_target(store)
    worked(root, store, 1, 0, language=lang)
    make(root, 5, TARGET, state="drafted", days=0, exemplars_used=["outcome:t01", "outcome:gone"])
    client = make_client(root)
    body = text(client.get("/outreach?tab=drafts"))
    assert "Modeled on: " in body and "positive reply, " in body
    assert 'href="/outreach?tab=sent#item-t01"' in body       # the message it was modeled on
    assert body.count("positive reply, ") == 1               # the deleted one is left out
    quiet = make(root, 6, TARGET - 1, state="drafted", days=0)
    assert quiet.exemplars_used == []
