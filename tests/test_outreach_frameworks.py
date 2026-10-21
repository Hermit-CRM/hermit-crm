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
framework id in the AI's answer), in the draft prompt (the framework block) and on the item
(build, regenerate, ready and the CLI)."""

from __future__ import annotations

import pytest

from hermitcrm import cli, frameworks, outreach, playbook, scrape
from hermitcrm.datafolder import init_folder
from outreach_fakes import FakeAI, ai, demo, fake_page, git, proof_draft
from test_frameworks import BRANDS
from test_outreach_draft import built, fake_cli  # noqa: F401  (fake_cli is a fixture)

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


# ------------------------------------------------------------ the item records it


def test_done_when_build_with_a_framework_writes_checked_drafts_with_it_set(
        tmp_path, monkeypatch, capsys):
    fake = FakeAI(drafts=[proof_draft])
    monkeypatch.setattr(outreach, "default_enricher", lambda config, tier="medium": ai(fake))
    monkeypatch.setattr(scrape, "fetch", lambda url, timeout=10: fake_page(url))
    root = init_folder(tmp_path / "x", demo=True)
    code = cli.main(["outreach", "build", "--where", "stage=prospect", "--limit", "3",
                     "--framework", "trigger-tension-trust"], root=root)
    assert code == 0, capsys.readouterr().out
    found = outreach.items(root)
    assert len(found) == 3
    assert all(i.framework == "trigger-tension-trust" and i.checks == [] for i in found)
    assert all('--- framework "Trigger, tension, trust" ---' in c["prompt"]
               for c in fake.of("draft"))
    assert "\nframework: trigger-tension-trust\n" in (root / found[0].path).read_text()
    assert git(root, "status", "--porcelain") == ""


def test_a_folder_without_frameworks_builds_with_house(folder):
    result, fake = built(folder, limit=1)
    assert result.items[0].framework == "house"
    assert outreach.SHAPES[outreach.FIRST_TOUCH] in fake.of("draft")[0]["prompt"]


def set_default(root, framework, name="Scaling the sales team"):
    """The approach the demo's first contact gets, with `frameworks: default` set."""
    path = root / playbook.FILENAME
    a = playbook.parse(path.read_text()).approach(name)
    path.write_text(playbook.apply_approach(path.read_text(), name,
                                            {**a.front, "frameworks": {"default": framework}}))


def test_the_approach_default_is_used(folder):
    root, _ = folder
    set_default(root, "trigger-tension-trust")
    item = built(folder, limit=1, drafts=[proof_draft])[0].items[0]
    assert item.framework == "trigger-tension-trust" and item.flags == []


def test_a_gone_approach_default_falls_back_to_house_with_a_flag(folder):
    root, _ = folder
    set_default(root, "gone")
    item = built(folder, limit=1)[0].items[0]
    assert item.framework == "house"
    assert "framework gone is not in the library; drafted with house" in item.flags


def test_the_flag_beats_the_approach_default(folder):
    root, _ = folder
    set_default(root, "trigger-tension-trust")
    item = built(folder, limit=1, framework="pain-proof-yes-no")[0].items[0]
    assert item.framework == "pain-proof-yes-no"


def test_an_unmet_need_falls_back_to_the_approach_default_when_it_needs_nothing(folder):
    root, _ = folder
    set_default(root, "trigger-tension-trust")
    item = built(folder, limit=1, drafts=[proof_draft],
                 framework="connection-problem-objection")[0].items[0]
    assert item.framework == "trigger-tension-trust"
    assert ("connection-problem-objection needs a personal connection; drafted with "
            "trigger-tension-trust") in item.flags


def test_an_approach_default_with_needs_of_its_own_is_no_fallback(folder):
    root, _ = folder
    set_default(root, "premise-body-ask")
    item = built(folder, limit=1, framework="connection-problem-objection")[0].items[0]
    assert item.framework == "house"
    assert ("connection-problem-objection needs a personal connection; drafted with house"
            in item.flags)


def test_unknown_framework_or_a_thread_kind_is_refused(tmp_path, fake_cli, capsys):
    root = init_folder(tmp_path / "x", demo=True)
    assert cli.main(["outreach", "build", "--framework", "gone"], root=root) == 1
    assert "unknown framework 'gone'" in capsys.readouterr().err
    assert cli.main(["outreach", "build", "--kind", "follow-up", "--framework", "house"],
                    root=root) == 1
    assert "frameworks shape first touches only" in capsys.readouterr().err
    assert fake_cli.calls == [] and not (root / "outreach").exists()


def test_an_unmet_need_falls_back_with_a_flag(folder):
    item = built(folder, limit=1, framework="connection-problem-objection")[0].items[0]
    assert item.framework == "house"
    assert ("connection-problem-objection needs a personal connection; drafted with house"
            in item.flags)


def test_unmet_needs():
    def finding(source, kind):
        return outreach.Finding(text="Something true", source=source, kind=kind,
                                confidence="high")
    cpo, pba = LIB.get("connection-problem-objection"), LIB.get("premise-body-ask")
    assert outreach.unmet_needs(cpo, [finding("https://example.com/a", "person")]) == \
        ["personal-connection"]
    assert outreach.unmet_needs(cpo, [finding(outreach.YOURS, "person")]) == []
    assert outreach.unmet_needs(pba, [finding("https://example.com/a", "company")]) == ["premise"]
    assert outreach.unmet_needs(pba, [finding("https://example.com/a", "person")]) == []


def test_a_draft_without_the_required_proof_is_retried_once_then_shown(folder):
    item = built(folder, limit=1, framework="trigger-tension-trust")[0].items[0]  # default_draft cites no proof
    assert item.attempts == 2 and any("cites one proof line" in c for c in item.checks)


def test_ready_rechecks_with_the_items_framework(folder):
    root, store = folder
    item = built(folder, limit=1, drafts=[proof_draft],
                 framework="trigger-tension-trust")[0].items[0]
    long = item.body.replace("Is that", "word " * 40 + "Is that")
    gone = outreach.get_item(root, item.id)
    gone.framework, gone.body = "gone", long          # its framework was deleted: house rules
    assert not any("at most 60" in p for p in outreach.check_item(store, gone))
    _, found = outreach.mark_ready(store, item.id, subject=item.subject, body=long)
    assert any("at most 60" in p for p in found)


def test_regenerate_keeps_the_framework_and_records_house_for_an_old_item(folder):
    root, store = folder
    item = built(folder, limit=1, drafts=[proof_draft],
                 framework="trigger-tension-trust")[0].items[0]
    drafter = outreach.AIDrafter(store, ai(FakeAI(drafts=[proof_draft])), {})
    assert outreach.redraft(store, item.id, drafter).framework == "trigger-tension-trust"
    path = root / item.path
    path.write_text(path.read_text().replace("framework: trigger-tension-trust\n", ""))
    assert outreach.redraft(store, item.id, outreach.AIDrafter(store, ai(FakeAI()), {})
                            ).framework == "house"
    path.write_text(path.read_text().replace("framework: house\n", "framework: gone\n"))
    again = outreach.redraft(store, item.id, outreach.AIDrafter(store, ai(FakeAI()), {}))
    assert again.framework == "house"
    assert "framework gone is not in the library; drafted with house" in again.flags


def test_an_item_without_framework_keeps_its_bytes(folder):
    root, _ = folder
    item = built(folder, limit=1)[0].items[0]
    path = root / item.path
    old = path.read_text().replace("framework: house\n", "")
    path.write_text(old)
    again = outreach.get_item(root, item.id)
    assert again.framework == "" and outreach.item_text(again) == old


def test_a_hand_written_framework_reads_stripped_and_lower_case(folder):
    root, _ = folder
    item = built(folder, limit=1)[0].items[0]
    text = (root / item.path).read_text().replace("framework: house\n",
                                                  'framework: " Trigger-Tension-Trust "\n')
    assert outreach.item_from_text(item.id, text).framework == "trigger-tension-trust"


def test_the_card_names_the_framework_after_the_angle(folder):
    _, store = folder
    item = built(folder, limit=1)[0].items[0]
    assert f"| angle: {item.angle} | framework: house | language: " in \
        outreach.render_item(store, item)
    item.framework = ""
    assert "framework:" not in outreach.render_item(store, item)


def test_build_refuses_a_framework_for_a_thread_kind_before_any_work(folder):
    _, store = folder
    fake = FakeAI()
    drafter = outreach.AIDrafter(store, ai(fake), {})
    sel = outreach.select(store, kind=outreach.FOLLOW_UP)
    with pytest.raises(outreach.OutreachError, match="frameworks shape first touches only"):
        outreach.build(store, sel, outreach.ScrapeResearcher(ai(fake)), drafter,
                       framework="house")
    assert fake.calls == []
