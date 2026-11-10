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

"""A model can paraphrase a string it was told to quote. The quote check: every
quoted string of a first-touch draft must appear, word for word, in a usable
finding. Fictional names only."""

from __future__ import annotations

import pytest

from hermitcrm import outreach
from hermitcrm.outreach import Finding

URL = "https://acme.example.com/contact"
EVIDENCE = Finding('The contact form has a "Book a call" button that only opens a form',
                   URL, "gap", "high", rule="r08")
LOW = Finding('The footer says "Talk to our team today" in small print', URL, "company", "low")


def email(body, subject="Your contact page", findings=(EVIDENCE,), **kw):
    ctx = outreach.CheckContext(kind="first-touch", channel="email",
                                rules=outreach.channel_rules("email"),
                                findings=list(findings), **kw)
    return outreach.check_text(subject, body, "", ctx)


def body(quote):
    return (f"Hi Mara,\n\nYour contact page offers a {quote} button.\nWe help founders turn "
            "that into a booked call.\nWhat happens after someone clicks it today?\n\nSam")


def quote_problems(found):
    return [p for p in found if "quotes" in p]


@pytest.mark.parametrize("quote", ['"Book a call"', "“Book a call”", "„Book a call“",
                                   "«Book a call»"])
def test_a_quote_that_a_finding_says_word_for_word_passes(quote):
    assert quote_problems(email(body(quote))) == []


def test_case_spacing_and_the_dot_at_the_end_do_not_matter():
    assert quote_problems(email(body('"book  a CALL."'))) == []


def test_a_paraphrased_quote_is_refused_and_named():
    (problem,) = quote_problems(email(body('"Schedule a call"')))
    assert "Schedule a call" in problem and "word for word" in problem


def test_a_quote_inside_a_longer_phrase_of_the_finding_passes():
    assert quote_problems(email(body('"only opens a form"'))) == []


def test_a_single_quoted_word_is_not_checked():
    """Scare quotes and a term kept in English are not claims about a page."""
    assert quote_problems(email(body('"fractional"'))) == []


def test_a_quote_found_only_in_a_low_confidence_finding_is_refused():
    found = email(body('"Talk to our team today"'), findings=(EVIDENCE, LOW))
    assert len(quote_problems(found)) == 1


def test_a_draft_without_findings_is_not_checked():
    assert quote_problems(email(body('"Schedule a call"'), findings=())) == []


def test_the_subject_is_checked_too():
    found = email(body("link"), subject='Your "Schedule a call" button')
    assert len(quote_problems(found)) == 1


def test_the_linkedin_pitch_is_checked_but_a_note_without_quotes_passes():
    ctx = outreach.CheckContext(kind="first-touch", channel="linkedin",
                                rules=outreach.channel_rules("linkedin"),
                                findings=[EVIDENCE])
    note = "Hi Mara, your contact page only opens a form. What happens after the click?"
    pitch = 'Thanks for connecting. Your "Schedule a call" button opens a form.'
    found = outreach.check_text("", note, pitch, ctx)
    assert len(quote_problems(found)) == 1
    assert quote_problems(outreach.check_text("", note, "", ctx)) == []


def test_a_reply_or_a_follow_up_is_not_checked():
    for kind in (outreach.REPLY, outreach.FOLLOW_UP):
        ctx = outreach.CheckContext(kind=kind, channel="email",
                                    rules=outreach.channel_rules("email"),
                                    findings=[EVIDENCE])
        assert quote_problems(outreach.check_text("Re: hi", body('"Schedule a call"'), "",
                                                  ctx)) == []


def test_the_question_inside_a_quote_is_still_not_counted():
    """The old rule about quotes stays: a question mark inside one is not ours."""
    text = ('Hi Mara,\n\nYour page says "Book a call" and asks "Anything else?" on the form.'
            "\nWhat happens after the click?\n\nSam")
    found = email(text, findings=(EVIDENCE, Finding('It asks "Anything else?" on the form',
                                                    URL, "company", "high")))
    assert [p for p in found if "question" in p] == []
