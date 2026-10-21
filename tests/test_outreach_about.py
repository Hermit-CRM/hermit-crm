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

"""Outreach: the words about you (the seller) against the words about them, per
language. A flag on the card, never a check. All names are made up."""

from __future__ import annotations

import pytest

from hermitcrm import outreach
from outreach_fakes import demo

OPT_OUT = "Not for you? Say so and I won't write again."


@pytest.mark.parametrize("language, text, counts", [
    ("en", "Hi Mara,\n\nYour second office caught my eye. We help founders like you build a "
           "team. Is hiring on your radar?\n\nSam", (2, 3)),
    ("de", "Hallo Mara,\n\nDein zweites Büro ist mir aufgefallen. Wir helfen Gründern wie dir. "
           "Ist das gerade dein Thema?\n\nSam", (2, 3)),
    ("de", "Guten Tag Frau Weber,\n\nwie geht es Ihnen mit Ihrem neuen Team? Sie wissen, wie "
           "das ist. Ich helfe ihnen gern.\n\nSam", (1, 2)),
    ("nl", "Hoi Daan,\n\nJe tweede kantoor viel me op. Wij helpen oprichters zoals jij. Is "
           "werven nu jouw prioriteit?\n\nSam", (2, 3)),
    ("fr", "Bonjour Claire,\n\nJe vois que vous ouvrez un bureau. J'aide des fondateurs comme "
           "vous. Votre équipe recrute-t-elle ?\n\nSam", (2, 3)),
])
def test_about_you_and_about_them_per_language(language, text, counts):
    assert outreach.about_counts(text, language) == counts


def test_a_language_without_word_lists_has_no_count():
    assert outreach.about_counts("Hola Marta, ¿te interesa?", "es") is None
    assert set(outreach.ABOUT_WORDS) == {"en", "de", "nl", "fr"}


def test_apostrophes_and_curly_quotes():
    # I'm, we're and a curly apostrophe are in the English list as written
    assert outreach.about_counts("I’m glad you’re here. We’ve met.", "en") == (2, 1)
    # j'aide counts as j' ; l'équipe and qu'il are not in the list
    assert outreach.about_counts("J'aide l'équipe, t'aide qu'il.", "fr") == (1, 1)
    # digits and underscores end a word
    assert outreach.about_counts("we2 you_ 4we", "en") == (2, 1)
    assert outreach.about_counts("", "en") == (0, 0)


def test_german_formal_you_counts_only_in_capitals_and_not_first_in_a_sentence():
    text = ("Sie haben ein neues Büro.\nSie wachsen. Wie geht es Ihnen? Ihr Team: Sie sind "
            "gut. Haben Sie Zeit? Was macht ihr Team? Ich frage Sie.")
    # counted: Ihnen, Ihr (a possessive counts at the start of a sentence too), Haben Sie, Sie
    # (last). Not counted: Sie at the start of the text, after a newline, after ". " and after
    # ": ", and the lower case ihr.
    assert outreach.about_counts(text, "de") == (1, 4)
    # a full stop with no white space after it does not start a sentence
    assert outreach.about_counts("Danke.Sie wissen", "de") == (0, 1)


def test_a_capital_possessive_counts_at_the_start_of_a_sentence_but_sie_does_not():
    assert outreach.about_counts("Ihr zweites Büro in Köln ist mir aufgefallen. Wir helfen "
                                 "Gründern.", "de") == (2, 1)
    assert outreach.about_counts("Sie wissen, wie das ist.", "de") == (0, 0)


def test_a_word_in_capitals_is_no_pronoun_but_a_lone_capital_i_is():
    assert outreach.about_counts("We sell in the US and EU.", "en") == (1, 0)
    assert outreach.about_counts("WIR HELFEN. Wir helfen.", "de") == (1, 0)
    assert outreach.about_counts("WE HELP YOU. I help you.", "en") == (1, 1)


def test_the_count_for_an_item_leaves_out_the_opt_out_line(tmp_path):
    root, _ = demo(tmp_path)
    path = root / "MESSAGING.md"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "approaches:\n", f"opt_out:\n  en: {OPT_OUT}\napproaches:\n", 1), encoding="utf-8")
    body = "Hi Alex,\n\nWe help teams. Is your pipeline ready?\n\nSam"
    item = outreach.Item(id="x", kind="first-touch", channel="email", language="en",
                         body=body + "\n\n" + OPT_OUT + "\n")
    assert outreach.about_counts(item.body, "en") == (2, 2)   # the line has "you" and "I"
    assert outreach.about_for_item(root, item) == outreach.about_counts(body, "en") == (1, 1)
    # the line is only added to a cold email: elsewhere it is part of the text
    item.channel = "linkedin"
    assert outreach.about_for_item(root, item) == (2, 2)


def test_the_pitch_counts_with_the_body_and_a_missing_language_is_english(tmp_path):
    root, _ = demo(tmp_path)
    item = outreach.Item(id="x", channel="linkedin", body="Hi Alex,\n\nYour team grew.",
                         pitch="We help teams like yours.")
    assert outreach.about_for_item(root, item) == (1, 2)
    item.language = "es"
    assert outreach.about_for_item(root, item) is None


def test_a_messages_file_that_does_not_read_does_not_stop_the_count(tmp_path):
    root, _ = demo(tmp_path)
    (root / "messages.toml").write_text("[languages\n", encoding="utf-8")
    item = outreach.Item(id="x", language="en", body="Hi Alex,\n\nWe help you.\n\nSam")
    assert outreach.about_for_item(root, item) == (1, 1)


def test_the_line_in_the_text_view_says_when_it_leans_to_you(tmp_path):
    root, store = demo(tmp_path)
    item = outreach.Item(id="x", language="en", body="Hi Alex,\n\nWe help teams. Our clients "
                         "grow. I can show you?\n\nSam")
    assert "About you 3, about them 1: more about you than about them" in \
        outreach.render_item(store, item)
    item.body = "Hi Alex,\n\nYour team grew. We see you hiring.\n\nSam"
    text = outreach.render_item(store, item)
    assert "About you 1, about them 2\n" in text and "more about you" not in text
    item.language = "es"
    assert "About you" not in outreach.render_item(store, item)
