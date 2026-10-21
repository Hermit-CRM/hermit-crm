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

"""Outreach frameworks in the hard checks: question bounds, the word limit, proof and the
framework id in the AI's answer."""

from __future__ import annotations

from hermitcrm import frameworks, outreach

LIB = frameworks.load()
PROOF = ("A made-up example: a 30-person software company doubled its qualified "
         "pipeline in two quarters.")


def ctx_for(fid, channel="email", proof=()):
    fw = LIB.get(fid)
    rules = outreach.framework_rules(outreach.channel_rules(channel), fw, channel,
                                     outreach.FIRST_TOUCH)
    return outreach.CheckContext(channel=channel, rules=rules, proof=list(proof), framework=fw)


def answer(**over):
    return {"subject": "Your second office", "angle": "hook", "pitch": "", "findings_used": [],
            "proof_used": [],
            "body": "Hi Mara,\n\nA second office this autumn usually means a sales hire.\n"
                    "Is that on your radar right now?\n\nSam\n", **over}


def test_max_words_takes_the_lower_limit_on_email_first_touches_only():
    ttt = LIB.get("trigger-tension-trust")
    rules = outreach.framework_rules
    assert rules({"body_max_words": 120}, ttt, "email", "first-touch")["body_max_words"] == 60
    assert rules({"body_max_words": 50}, ttt, "email", "first-touch")["body_max_words"] == 50
    assert rules({"body_max_words": 120}, LIB.house, "email", "first-touch") == {"body_max_words": 120}
    assert rules({"body_max_words": 120}, ttt, "email", "reply-to-interest") == {"body_max_words": 120}
    li = {"note_max_chars": 300, "pitch_max_chars": 600}
    assert rules(li, ttt, "linkedin", "first-touch") == li


def test_a_long_email_breaks_the_framework_word_limit():
    body = "Hi Mara,\n\n" + "word " * 70 + "\nIs this on your radar?\n\nSam\n"
    assert any("at most 60" in p for p in
               outreach.check_text("Your office", body, "", ctx_for("trigger-tension-trust")))
    assert not any("at most 60" in p for p in
                   outreach.check_text("Your office", body, "", ctx_for("house")))


def test_a_reply_invite_framework_may_ask_nothing_on_email_and_in_the_pitch():
    body = ("Hi Mara,\n\nThe second office caught my eye.\nIf it is not relevant, tell me and "
            "I will drop it.\n\nSam\n")
    assert outreach.check_text("Your office", body, "", ctx_for("connection-problem-objection")) == []
    assert any("exactly one" in p for p in outreach.check_text("Your office", body, "", ctx_for("house")))
    note = "Hi Mara, the second office caught my eye."
    assert outreach.check_text("", note, body, ctx_for("connection-problem-objection", "linkedin")) == []


def test_time_link_and_calendar_checks_fire_for_every_framework():
    body = ("Hi Mara,\n\nThe second office caught my eye. Free on Tuesday at 10:00? "
            "https://example.com/book\n\nSam\n")
    for fid in LIB.ids:
        found = outreach.check_text("Your office", body, "", ctx_for(fid))
        assert any("proposes a time" in p for p in found) and \
            any("link" in p for p in found), fid


def test_a_proof_required_framework_refuses_a_draft_without_proof():
    ttt = ctx_for("trigger-tension-trust", proof=[PROOF])
    assert outreach.clean_answer(answer(), ttt).problems == [
        "the Trigger, tension, trust framework cites one proof line from the playbook in "
        "proof_used (it cites none)"]
    assert outreach.clean_answer(answer(proof_used=[PROOF]), ttt).problems == []
    assert outreach.clean_answer(answer(), ctx_for("house", proof=[PROOF])).problems == []


def test_the_framework_in_the_answer_must_be_the_one_asked_for():
    ctx = ctx_for("house")
    assert outreach.clean_answer(answer(framework="pain-proof-yes-no"), ctx).problems == [
        "it says framework 'pain-proof-yes-no'; this draft was asked for house"]
    draft = outreach.clean_answer(answer(), ctx)
    assert draft.problems == [] and draft.framework == "house"
    assert "framework" not in outreach.DRAFT_SCHEMA["required"]
