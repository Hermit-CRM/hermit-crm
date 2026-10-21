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

"""Outreach frameworks in the hard checks (question bounds, the word limit, proof and the
framework id in the AI's answer) and in the draft prompt (the framework block)."""

from __future__ import annotations

import pytest

from hermitcrm import frameworks, outreach, playbook
from outreach_fakes import FakeAI, ai, demo
from test_frameworks import BRANDS

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
    ctx = ctx_for("pain-proof-yes-no", proof=[PROOF])
    assert outreach.clean_answer(answer(proof_used=[PROOF], framework="house"), ctx).problems == [
        "it says framework 'house'; this draft was asked for pain-proof-yes-no"]
    draft = outreach.clean_answer(answer(proof_used=[PROOF]), ctx)
    assert draft.problems == [] and draft.framework == "pain-proof-yes-no"
    assert "framework" not in outreach.DRAFT_SCHEMA["required"]


def test_house_asks_for_no_id_so_a_guess_in_the_answer_is_no_mismatch():
    ctx = ctx_for("house")
    draft = outreach.clean_answer(answer(framework="first-touch"), ctx)
    assert draft.problems == [] and draft.framework == "house"
    ttt = ctx_for("trigger-tension-trust", proof=[PROOF])
    assert outreach.clean_answer(answer(proof_used=[PROOF], framework="house"), ttt).problems == [
        "it says framework 'house'; this draft was asked for trigger-tension-trust"]


# ------------------------------------------------------------------ the prompt


@pytest.fixture
def folder(tmp_path):
    return demo(tmp_path)


def first_touch_prompt(store, framework, channel="email"):
    company = store.get("lindenhof-data")
    contact = company.contacts["mara-keller"]
    approach = playbook.load(store.root).approaches[0]
    research = outreach.Research(findings=[outreach.Finding(
        text="Opened a second office this autumn", source="https://example.com/news",
        kind="trigger", confidence="high")])
    drafter = outreach.AIDrafter(store, ai(FakeAI()), {"owner_name": "Sam Example"})
    ctx, _ = drafter.context(outreach.FIRST_TOUCH, company, contact, research, channel,
                             approach, framework=framework)
    brief = outreach.make_brief(store, company, contact, approach, research)
    return outreach.draft_prompt(outreach.FIRST_TOUCH, brief, ctx, approach, "", "Sam Example")


def test_house_gives_todays_prompt_byte_for_byte(folder):
    _, store = folder
    assert first_touch_prompt(store, LIB.house) == first_touch_prompt(store, None)
    assert outreach.SHAPES[outreach.FIRST_TOUCH] in first_touch_prompt(store, LIB.house)


def test_a_framework_block_replaces_the_shape_paragraph(folder):
    _, store = folder
    fw = LIB.get("trigger-tension-trust")
    prompt = first_touch_prompt(store, fw)
    assert outreach.SHAPES[outreach.FIRST_TOUCH] not in prompt
    assert ('--- framework "Trigger, tension, trust" ---\nSteps: Trigger, Tension, Trust, '
            "Question.\n" + fw.instructions + "\n--- end ---") in prompt
    assert ("- The playbook's Voice section wins over the framework on wording, greeting, "
            "sign-off and formality.") in prompt
    assert "the body at most 60 words" in prompt
    assert "- Exactly one question mark in the whole message." in prompt
    assert "- Do not state the offer line; it is below as background." in prompt
    assert '- Set framework to "trigger-tension-trust".' in prompt


def test_credit_and_example_never_reach_a_prompt(folder):
    root, store = folder
    (root / "frameworks.toml").write_text(
        '[frameworks.trigger-tension-trust]\nexample = "Hi Alex, a made-up example."\n',
        encoding="utf-8")
    lib = frameworks.load(root)
    for fid in lib.ids:
        fw = lib.get(fid)
        prompt = first_touch_prompt(store, fw)
        assert not fw.after or fw.after not in prompt, fid
        assert not fw.example or fw.example not in prompt, fid
        assert not [b for b in BRANDS if b in prompt.lower()], fid


def test_linkedin_framework_drafts_shape_the_pitch(folder):
    _, store = folder
    prompt = first_touch_prompt(store, LIB.get("trigger-tension-trust"), "linkedin")
    assert "built with the framework above" in prompt and "the offer in one line" not in prompt


def test_replies_and_follow_ups_get_no_framework(folder):
    _, store = folder
    company = store.get("lindenhof-data")
    drafter = outreach.AIDrafter(store, ai(FakeAI()), {})
    ctx, _ = drafter.context(outreach.REPLY, company, company.contacts["mara-keller"],
                             outreach.Research(), "email", None,
                             framework=LIB.get("trigger-tension-trust"))
    assert ctx.framework is None


def test_the_rule_lines_follow_the_framework(folder):
    root, store = folder
    (root / "frameworks.toml").write_text(
        '[frameworks.offer-first]\nname = "Offer first"\nsteps = ["Offer", "Ask"]\n'
        'offer_line = "required"\nproof = "optional"\nquestions = [0, 1]\n'
        'instructions = "State the offer, then invite a reply."\n', encoding="utf-8")
    prompt = first_touch_prompt(store, frameworks.load(root).get("offer-first"))
    assert "- Say the offer in one line." in prompt
    assert "- At most one question mark in the whole message." in prompt
    assert "Exactly one question mark" not in prompt
    assert "Do not state the offer line" not in prompt and "Cite one proof line" not in prompt


def test_the_drafter_uses_house_unless_a_framework_is_passed(folder):
    _, store = folder
    company = store.get("lindenhof-data")
    contact = company.contacts["mara-keller"]
    approach = playbook.load(store.root).approaches[0]
    research = outreach.Research(findings=[outreach.Finding(
        text="Opened a second office this autumn", source="https://example.com/news",
        kind="trigger", confidence="high")])

    def prompt_and_draft(**kw):
        fake = FakeAI()
        drafter = outreach.AIDrafter(store, ai(fake), {"owner_name": "Sam Example"})
        draft = drafter.draft(outreach.FIRST_TOUCH, company, contact, research, "email",
                              approach=approach, **kw)
        return fake.of("draft")[0]["prompt"], draft

    prompt, draft = prompt_and_draft()
    assert outreach.SHAPES[outreach.FIRST_TOUCH] in prompt and draft.framework == "house"
    prompt, draft = prompt_and_draft(framework=LIB.get("trigger-tension-trust"))
    assert '- Set framework to "trigger-tension-trust".' in prompt
    assert draft.framework == "trigger-tension-trust"
