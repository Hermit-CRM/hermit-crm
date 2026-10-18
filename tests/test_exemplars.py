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

"""Learning by example (approach C): the exemplar index, retrieval, the prompt
block, pins and exclusions, the angle bandit, and the draft that carries them.
The AI is a fake; every name is made up."""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from hermitcrm import cli, exemplars, learning, messaging, migrations, outreach, playbook
from hermitcrm.exemplars import Exemplar
from hermitcrm.models import Interaction
from outreach_fakes import NOW, FakeAI, ai, default_draft, git
from test_learning import (  # noqa: F401  (fixture and builders)
    APPROACH, CONTACTS, ai_body, folder, make, shorter,
)

OFFICE = "Opened a second office this autumn"
TODAY = date(2026, 10, 16)


def answer(store, company, contact, when, outcome="", id_="in1"):
    store.get(company).interactions.append(Interaction(
        id=id_, date=when, channel="email", direction="in", contact=contact, outcome=outcome))


def worked(root, store, n, contact=0, *, days=20, findings=(OFFICE,), rung="positive", **kw):
    """A sent first touch that got a positive reply (or a deal, or a win)."""
    item = make(root, n, contact, state="sent", days=days, findings=findings, **kw)
    company, slug = CONTACTS[contact]
    # saved through the store, so an app opened on the folder sees the reply too
    store.create_interaction(company, "email", "in", contact=slug, outcome="interested",
                             date=item.sent + timedelta(days=2), body="Sounds interesting.")
    return item


def corrected(root, n, contact=0, *, note="Too chatty.", tags=("cliche",), days=10,
              findings=(OFFICE,), **kw):
    """A draft the person shortened, with their reason."""
    from test_learning import FIRSTS
    first = FIRSTS[CONTACTS[contact][1]]
    return make(root, n, contact, edits=[(shorter(ai_body(first)), note, tags)], days=days,
                findings=findings, **kw)


def query(**kw):
    base = dict(approach=APPROACH, channel="email", language="en", persona="founder",
                company="bluefin-analytics", findings=[OFFICE])
    base.update(kw)
    return exemplars.Query(**base)


# ---------------------------------------------------------------- settings


def test_the_settings_default_to_off_and_ignore_typos():
    assert exemplars.mode({}) == "off" and exemplars.mode(None) == "off"
    assert exemplars.mode({"learning_exemplars": "both"}) == "both"
    assert exemplars.mode({"learning_exemplars": " Corrections "}) == "corrections"
    assert exemplars.mode({"learning_exemplars": "yes please"}) == "off"
    assert exemplars.count({}) == 2
    assert exemplars.count({"learning_exemplar_count": 9}) == 3
    assert exemplars.count({"learning_exemplar_count": 0}) == 0
    assert exemplars.count({"learning_exemplar_count": "3"}) == 2     # not a number
    assert exemplars.sampling_on({}) is False
    assert exemplars.sampling_on({"learning_angle_sampling": True}) is True
    assert exemplars.sampling_on({"learning_angle_sampling": "true"}) is False


# ------------------------------------------------------------------- index


def test_a_message_that_got_a_positive_reply_is_an_outcome_exemplar(folder):
    root, store = folder
    worked(root, store, 1)
    found = exemplars.index(store)
    assert [e.id for e in found] == ["outcome:t01"]
    e = found[0]
    assert (e.kind, e.rung, e.approach, e.channel) == ("outcome", "positive", APPROACH, "email")
    assert e.persona == "founder" and e.company == "lindenhof-data"
    assert e.score == pytest.approx(learning.RUNG_VALUE["positive"] * 0.5 ** (18 / 60))
    assert e.label == "positive reply, 2 weeks ago"
    assert "Mara" not in e.text and "[CONTACT]" in e.text           # names are replaced
    assert e.subject == "Your second office"
    assert OFFICE in e.doc


def test_a_deal_scores_above_a_positive_and_a_win_above_a_deal(folder):
    root, store = folder
    from hermitcrm.models import StageChange
    worked(root, store, 1, 0)
    deal = worked(root, store, 2, 1)
    won = worked(root, store, 3, 2)
    day = deal.sent.date()
    store.get("kestrel-metrics").stage_history = [
        StageChange(day + timedelta(days=3), "engaged", "discovery")]
    store.get("ravenmoor-systems").stage_history = [
        StageChange(day + timedelta(days=3), "engaged", "discovery"),
        StageChange(day + timedelta(days=9), "offer", "won")]
    by_id = {e.id: e for e in exemplars.index(store)}
    assert [by_id[f"outcome:t0{n}"].rung for n in (1, 2, 3)] == ["positive", "deal", "won"]
    assert (by_id["outcome:t01"].score < by_id["outcome:t02"].score
            < by_id["outcome:t03"].score)
    assert won.id == "t03"


def test_a_message_with_no_reply_or_not_sent_is_no_outcome_exemplar(folder):
    root, store = folder
    make(root, 1, state="sent", days=20)                  # sent, nobody answered
    make(root, 2, state="ready", days=3)                  # not sent
    answer(store, "lindenhof-data", "mara-keller", NOW, "", "plain")   # a reply, no interest
    assert exemplars.index(store) == []


def test_a_correction_with_a_reason_is_a_pair_of_the_paragraph_that_changed(folder):
    root, store = folder
    corrected(root, 1)
    [e] = exemplars.index(store)
    assert (e.id, e.kind) == ("correction:t01", "correction")
    assert "I hope this finds you well." in e.before
    assert "I hope this finds you well." not in e.after
    assert "Hi [CONTACT]," not in e.before            # only the paragraph that differs
    assert e.note == "Too chatty." and e.tags == ["cliche"]
    assert e.shown.startswith("You wrote: ") and "They changed it to: " in e.shown
    assert "Their reason: Too chatty.; cliche" in e.shown


def test_a_small_unexplained_edit_or_a_skipped_draft_is_not_a_correction(folder):
    root, store = folder
    body = ai_body("Mara")
    make(root, 1, edits=[(body.replace("autumn", "fall"), "", ())])        # one word, no reason
    make(root, 2, edits=[(shorter(ai_body("Daan")), "Cut it.", ())], contact=1,
         state="skipped")
    assert [e for e in exemplars.index(store) if e.kind == "correction"] == []


def test_only_first_touch_drafts_make_exemplars(folder):
    root, store = folder
    corrected(root, 1, kind="follow-up")
    corrected(root, 2, contact=1, kind="reply-to-interest")
    assert exemplars.index(store) == []


def test_differing_paragraphs_keep_the_first_changed_run():
    before = "Hi A,\n\nOne.\nTwo.\n\nThree.\n\nBye"
    after = "Hi A,\n\nOne.\n\nThree.\n\nBye"
    assert exemplars.differing_paragraphs(before, after) == ("One.\nTwo.", "One.")
    assert exemplars.differing_paragraphs("Same.", "Same.") == ("", "")
    assert exemplars.differing_paragraphs("A\n\nB", "A\n\nB\n\nC") == ("", "C")


# --------------------------------------------------------------- retrieval


def test_nothing_close_enough_means_no_example(folder):
    root, store = folder
    worked(root, store, 1, findings=("Sponsors the regional chess league",))
    picked = exemplars.pick(store, query(persona="", findings=["Hiring a head of data"]))
    assert picked.choices == [] and "none close enough" in picked.why_none
    assert picked.pool == 1 and picked.block == "" and picked.tokens == 0


def test_hard_filters_keep_other_channels_languages_approaches_and_the_same_company_out(folder):
    root, store = folder
    worked(root, store, 1, 0, channel="linkedin")
    worked(root, store, 2, 1, language="de")
    worked(root, store, 3, 2, approach="Scaling the sales team")
    worked(root, store, 4, 3)
    worked(root, store, 5, 4)
    picked = exemplars.pick(store, query(company="tallpine-software"))
    assert picked.ids == ["outcome:t05"]            # t04 is the company asked about
    assert picked.pool == 1


def test_the_persona_the_angle_and_the_findings_decide_relevance(folder):
    root, store = folder
    worked(root, store, 1, 0, angle="hook")
    worked(root, store, 2, 1, angle="scale")
    picked = exemplars.pick(store, query(angle="scale"), k=3)
    assert picked.ids == ["outcome:t02", "outcome:t01"]       # the same angle wins
    top, other = picked.choices
    assert "same persona (founder)" in top.reason and "same angle (scale)" in top.reason
    assert "same angle" not in other.reason and "findings overlap: " in other.reason
    assert top.relevance == pytest.approx(other.relevance + exemplars.W_ANGLE, abs=1e-3)
    unrelated = exemplars.pick(store, query(persona="", findings=["Sponsors a chess league"]))
    assert "none close enough" in unrelated.why_none      # no persona, nothing in common


def test_an_excluded_exemplar_is_never_shown_and_a_pinned_one_leads(folder):
    root, store = folder
    worked(root, store, 1, 0)
    worked(root, store, 2, 1, findings=("Opened an office",))
    exemplars.set_mark(store, "outcome:t01", "exclude")
    assert exemplars.pick(store, query(), k=3).ids == ["outcome:t02"]
    exemplars.set_mark(store, "outcome:t01", "pin")
    exemplars.set_mark(store, "outcome:t02", "exclude")
    assert exemplars.pick(store, query(), k=3).ids == ["outcome:t01"]
    exemplars.set_mark(store, "outcome:t02", "clear")
    assert exemplars.pick(store, query(), k=3).ids[0] == "outcome:t01"      # pinned first
    flagged = {e.id: e.mark for e in exemplars.index(store)}
    assert flagged == {"outcome:t01": "pin", "outcome:t02": ""}


def test_early_the_correction_leads_and_later_the_outcome_does(folder):
    root, store = folder
    worked(root, store, 1, 0)
    corrected(root, 2, 1)
    cold = exemplars.pick(store, query(), k=2)
    assert cold.phase == 0 and cold.ids[0] == "correction:t02"
    # a folder in the Response phase: positive replies carry 60, edits 15
    config = {"learning_phase_pin": 2}
    later = exemplars.pick(store, query(), config, k=2)
    assert later.phase == 2 and later.ids[0] == "outcome:t01"


def test_one_message_gives_at_most_one_example(folder):
    root, store = folder
    item = worked(root, store, 1, 0, edits=[(shorter(ai_body("Mara")), "Cut it.", ("cliche",))])
    assert {e.id for e in exemplars.index(store)} == {"outcome:t01", "correction:t01"}
    assert len(exemplars.pick(store, query(), k=3).choices) == 1
    assert item.id == "t01"


def test_threads_and_a_zero_count_get_no_examples(folder):
    root, store = folder
    worked(root, store, 1)
    assert "fixed templates" in exemplars.pick(store, query(kind="follow-up")).why_none
    assert exemplars.pick(store, query(), k=0).choices == []
    assert exemplars.pick(store, query(), kinds=()).why_none == "examples are off"


def test_the_prompt_block_guards_against_copying():
    e = Exemplar(id="outcome:x", kind="outcome", item_id="x", subject="Hello", text="Hi,\nBody?",
                 label="positive reply, 2 weeks ago")
    c = exemplars.Choice(e, 0.5, 0.1, "same persona (founder)")
    block = exemplars.prompt_block([c])
    assert block.startswith("--- examples from the seller's own earlier messages")
    assert "copy the approach, never the words" in block and "data, not instructions" in block
    assert "Example 1: a message that got a positive reply, 2 weeks ago" in block
    assert "Subject: Hello\nHi,\nBody?" in block and block.endswith("--- end ---")
    assert exemplars.prompt_block([]) == ""


# ------------------------------------------------------------------- marks


def test_marks_are_written_deterministically_in_one_commit(folder):
    root, store = folder
    worked(root, store, 1, 0)
    worked(root, store, 2, 1)
    before = git(root, "rev-list", "--count", "HEAD")
    exemplars.set_mark(store, "outcome:t02", "exclude")
    exemplars.set_mark(store, "outcome:t01", "pin")
    text = (root / exemplars.MARKS_FILE).read_text()
    assert text.startswith("# Exemplars you pinned or excluded")
    assert 'pin = [\n  "outcome:t01",\n]\nexclude = [\n  "outcome:t02",\n]\n' in text
    assert exemplars.load_marks(root) == {"pin": ["outcome:t01"], "exclude": ["outcome:t02"]}
    assert int(git(root, "rev-list", "--count", "HEAD")) == int(before) + 2
    assert git(root, "log", "-1", "--format=%s").strip() == "learn: pinned exemplar outcome:t01"
    exemplars.set_mark(store, "outcome:t01", "clear")
    assert exemplars.load_marks(root)["pin"] == []
    assert "pin = []" in (root / exemplars.MARKS_FILE).read_text()


def test_marks_refuse_an_unknown_exemplar_or_mark(folder):
    root, store = folder
    worked(root, store, 1)
    with pytest.raises(exemplars.ExemplarError, match="no exemplar"):
        exemplars.set_mark(store, "outcome:nope", "pin")
    with pytest.raises(exemplars.ExemplarError, match="mark is one of"):
        exemplars.set_mark(store, "outcome:t01", "love")
    assert not (root / exemplars.MARKS_FILE).exists()


def test_a_broken_marks_file_reads_as_empty(tmp_path):
    (tmp_path / exemplars.MARKS_FILE).write_text("pin = [", encoding="utf-8")
    assert exemplars.load_marks(tmp_path) == {"pin": [], "exclude": []}
    (tmp_path / exemplars.MARKS_FILE).write_text('pin = ["nonsense", "outcome:a"]\n')
    assert exemplars.load_marks(tmp_path)["pin"] == ["outcome:a"]


# ------------------------------------------------------- the draft carries it


TARGET = 7          # bluefin-analytics / joris-veldkamp: nobody wrote to them yet


def drafter_and_inputs(store, config, fake=None):
    fake = fake or FakeAI()
    drafter = outreach.AIDrafter(store, ai(fake), {"owner_name": "Sam Example", **config})
    company = store.get(CONTACTS[TARGET][0])
    contact = company.contacts[CONTACTS[TARGET][1]]
    approach = playbook.load(store.root).approach(APPROACH)
    research = outreach.Research(findings=[
        outreach.Finding(OFFICE, "https://a.example.com", "trigger", "high")])
    return drafter, fake, company, contact, approach, research


def draft_for_target(store, config, fake=None, kind="first-touch"):
    drafter, fake, company, contact, approach, research = drafter_and_inputs(store, config, fake)
    return drafter.draft(kind, company, contact, research, "email", approach=approach), fake


def language_of_target(store):
    company = store.get(CONTACTS[TARGET][0])
    return messaging.draft_language(company, company.contacts[CONTACTS[TARGET][1]])


def test_with_the_setting_off_the_prompt_has_no_examples_and_is_unchanged(folder):
    root, store = folder
    lang = language_of_target(store)
    worked(root, store, 1, 0, language=lang)
    draft, fake = draft_for_target(store, {})
    prompt = fake.of("draft")[0]["prompt"]
    assert "examples from the seller" not in prompt and draft.exemplars_used == []
    assert "Angle: one of " in prompt and draft.angle_note == ""
    again, fake2 = draft_for_target(store, {"learning_exemplars": "off"})
    assert fake2.of("draft")[0]["prompt"] == prompt


def test_with_the_setting_on_the_prompt_shows_the_examples_and_the_draft_records_them(folder):
    root, store = folder
    lang = language_of_target(store)
    worked(root, store, 1, 0, language=lang)
    corrected(root, 2, 1, language=lang)
    draft, fake = draft_for_target(store, {"learning_exemplars": "both"})
    prompt = fake.of("draft")[0]["prompt"]
    assert prompt.count("\nExample ") == 2
    assert "--- examples from the seller's own earlier messages" in prompt
    assert sorted(draft.exemplars_used) == ["correction:t02", "outcome:t01"]
    assert "Mara" not in prompt.split("--- examples")[1].split("--- end ---")[0]
    # the examples sit between the playbook and the rules
    assert prompt.index("the seller's playbook") < prompt.index("--- examples") \
        < prompt.index("Rules: plain text")
    only = draft_for_target(store, {"learning_exemplars": "outcomes"})[0]
    assert only.exemplars_used == ["outcome:t01"]
    fixed = draft_for_target(store, {"learning_exemplars": "corrections"})[0]
    assert fixed.exemplars_used == ["correction:t02"]


def test_replies_and_follow_ups_never_get_examples(folder):
    root, store = folder
    lang = language_of_target(store)
    worked(root, store, 1, 0, language=lang)
    drafter, fake, company, contact, approach, research = drafter_and_inputs(
        store, {"learning_exemplars": "both"})
    draft = drafter.draft("follow-up", company, contact, research, "email", approach=approach)
    assert draft.exemplars_used == []
    assert "examples from the seller" not in fake.of("draft")[0]["prompt"]


def test_a_failure_in_learning_never_stops_a_draft(folder, monkeypatch):
    root, store = folder

    def boom(*a, **k):
        raise RuntimeError("index broke")
    monkeypatch.setattr(exemplars, "for_draft", boom)
    monkeypatch.setattr(exemplars, "sample_for_draft", boom)
    draft, fake = draft_for_target(store, {"learning_exemplars": "both",
                                           "learning_angle_sampling": True})
    assert draft.failed == "" and draft.exemplars_used == [] and draft.body


def test_the_item_records_the_examples_it_was_shown(folder):
    item = outreach.Item(id="x", exemplars_used=["outcome:a", "outcome:a", "bad id", " "])
    meta = item.to_frontmatter()
    assert meta["exemplars_used"] == ["outcome:a", "outcome:a", "bad id", " "]
    again = outreach.item_from_text("x", outreach.item_text(item))
    assert again.exemplars_used == ["outcome:a"]
    assert "exemplars_used" not in outreach.Item(id="y").to_frontmatter()
    assert outreach.clean_exemplar_ids(["outcome:a", "outcome:a", "bad id", "x:y", " "]) \
        == ["outcome:a"]


def test_apply_draft_sets_the_examples_and_one_angle_flag(folder):
    item = outreach.Item(id="x", state="researching", channel="email",
                         findings=[outreach.Finding("f", "https://a.example.com", "trigger",
                                                    "high")])
    draft = outreach.Draft(subject="S", body="Hi,\nQ?\n", angle="scale",
                           exemplars_used=["outcome:a"], angle_note="angle scale chosen: 1 of 4")
    when = outreach.datetime(2026, 10, 16, 9, 0)
    outreach._apply_draft(item, draft, False, when)
    assert item.exemplars_used == ["outcome:a"]
    assert item.flags == [f"{outreach.ANGLE_FLAG}angle scale chosen: 1 of 4"]
    draft.angle_note = "angle hook chosen: exploring"
    outreach._apply_draft(item, draft, False, when)
    assert item.flags == [f"{outreach.ANGLE_FLAG}angle hook chosen: exploring"]
    draft.angle_note, draft.exemplars_used = "", []
    outreach._apply_draft(item, draft, False, when)
    assert item.flags == [] and item.exemplars_used == []


def test_migration_11_normalises_exemplars_used():
    plain = {"state": "sent"}
    assert migrations.m11_exemplars(plain) is plain
    messy = {"state": "sent", "exemplars_used": ["outcome:a", "outcome:a", "nope", ""]}
    assert migrations.m11_exemplars(messy)["exemplars_used"] == ["outcome:a"]
    clean = {"exemplars_used": ["outcome:a"]}
    assert migrations.m11_exemplars(clean) is clean
    assert "exemplars_used" not in migrations.m11_exemplars({"exemplars_used": ["junk"]})
    m = migrations.MIGRATIONS[-1]
    assert m.version == 11 and m.glob == "outreach/*.md" and m.apply is migrations.m11_exemplars


# -------------------------------------------------------------- angle bandit


def send(angle, hit, days=5, persona="founder", company="c1", kind="first-touch"):
    rungs = {"sent": TODAY - timedelta(days=days)}
    if hit:
        rungs["positive"] = TODAY - timedelta(days=days - 1)
    return learning.Signal(item_id=f"{angle}{days}{hit}{company}", approach=APPROACH,
                           angle=angle, kind=kind, persona=persona, company=company,
                           state="sent", rungs=rungs)


ANGLES = ("scale", "unblock", "hook")


def many(angle, n, hits, **kw):
    return [send(angle, i < hits, company=f"c{i}", **kw) for i in range(n)]


def test_the_table_learns_which_angle_gets_replies():
    sigs = many("hook", 20, 8) + many("scale", 10, 1) + many("unblock", 2, 0)
    rows = {r.angle: r for r in exemplars.angle_table(sigs, APPROACH, ANGLES, today=TODAY)}
    assert (rows["hook"].n, rows["hook"].hits) == (20, 8)
    assert rows["hook"].mean > rows["scale"].mean
    assert rows["unblock"].exploring and "still exploring" in rows["unblock"].note
    assert rows["hook"].low < rows["hook"].mean < rows["hook"].high
    assert rows["unblock"].high - rows["unblock"].low > rows["hook"].high - rows["hook"].low


def test_an_angle_without_sends_starts_from_the_approach_rate_and_the_playbook_order():
    sigs = many("hook", 10, 5)
    rows = exemplars.angle_table(sigs, APPROACH, ANGLES, today=TODAY)
    by = {r.angle: r for r in rows}
    assert by["scale"].n == 0 and by["unblock"].n == 0
    assert by["scale"].mean > by["unblock"].mean         # first in the list is trusted a bit more
    assert 0.0 < by["scale"].mean < 0.9
    assert [r.angle for r in rows] == list(ANGLES)       # `custom` is never an arm
    assert [r.angle for r in exemplars.angle_table(sigs, APPROACH, (*ANGLES, "custom"),
                                                   today=TODAY)] == list(ANGLES)


def test_old_sends_count_less_than_new_ones():
    fresh = exemplars.angle_table(many("hook", 10, 10, days=5) + many("scale", 10, 0, days=5),
                                  APPROACH, ("hook", "scale"), today=TODAY)
    stale = exemplars.angle_table(many("hook", 10, 10, days=400) + many("scale", 10, 0, days=400),
                                  APPROACH, ("hook", "scale"), today=TODAY)
    assert fresh[0].mean > stale[0].mean > 0.5 - 0.3
    assert fresh[1].mean < stale[1].mean                 # old failures fade toward the prior too


def test_a_persona_with_enough_sends_uses_its_own_evidence():
    sigs = (many("hook", 12, 0, persona="cto") + many("scale", 12, 6, persona="cto")
            + many("hook", 12, 6, persona="founder") + many("scale", 12, 0, persona="founder"))
    cto = {r.angle: r for r in exemplars.angle_table(sigs, APPROACH, ("hook", "scale"),
                                                     persona="cto", today=TODAY)}
    founder = {r.angle: r for r in exemplars.angle_table(sigs, APPROACH, ("hook", "scale"),
                                                         persona="founder", today=TODAY)}
    assert cto["scale"].mean > cto["hook"].mean
    assert founder["hook"].mean > founder["scale"].mean
    assert cto["scale"].n == 12


def test_the_bandit_counts_deals_only_with_support():
    sigs = many("hook", 40, 10)
    assert exemplars.bandit_rung(sigs, {}, APPROACH) == "positive"
    for s in sigs[:3]:
        s.rungs["deal"] = TODAY
    for s in sigs[3:12]:
        s.rungs["replied"] = TODAY
    deals = exemplars.bandit_rung(sigs, {"learning_phase_pin": 3}, APPROACH)
    assert deals == "deal"                                  # 3 events from 3 companies
    for s in sigs[:3]:
        s.company = "same"
    assert exemplars.bandit_rung(sigs, {"learning_phase_pin": 3}, APPROACH) == "positive"


class StubRng:
    def __init__(self, *draws):
        self.draws = list(draws)

    def betavariate(self, a, b):
        return self.draws.pop(0)


def test_thompson_sampling_picks_the_highest_draw_and_says_why():
    rows = exemplars.angle_table(many("hook", 20, 8) + many("scale", 10, 1)
                                 + many("unblock", 2, 0), APPROACH, ANGLES, today=TODAY)
    explore = exemplars.choose_angle(rows, StubRng(0.1, 0.9, 0.2))
    assert explore.angle == "unblock"
    assert explore.reason == ("angle unblock chosen by the exploration policy: exploring: "
                              "2 sends so far")
    lead = exemplars.choose_angle(rows, StubRng(0.1, 0.2, 0.9))
    assert lead.angle == "hook" and "8 of 20 sends reached positive" in lead.reason


def test_the_bandit_mostly_picks_the_better_angle_but_not_always():
    import random
    rows = exemplars.angle_table(many("hook", 30, 15) + many("scale", 30, 3), APPROACH,
                                 ("hook", "scale"), today=TODAY)
    picks = [exemplars.choose_angle(rows, random.Random(i)).angle for i in range(300)]
    assert picks.count("hook") > 270            # the better angle, nearly always
    assert "scale" in picks                     # but the other one is still tried sometimes


def test_next_experiment_names_the_least_tried_angle():
    rows = exemplars.angle_table(many("hook", 20, 8) + many("scale", 10, 1)
                                 + many("unblock", 2, 0), APPROACH, ANGLES, today=TODAY)
    assert exemplars.next_experiment(rows).startswith("unblock has 2 sends so far")
    assert exemplars.next_experiment(rows[:1]) == ""
    steady = exemplars.angle_table(many("hook", 400, 200) + many("scale", 400, 40),
                                   APPROACH, ("hook", "scale"), today=TODAY)
    assert "mostly picks the leader" in exemplars.next_experiment(steady)


def sends(root, store, n):
    """n sent first touches, alternating two angles, a few with positive replies."""
    for k in range(n):
        item = make(root, k, k % len(CONTACTS), state="sent", days=40 - k % 20,
                    angle="hook" if k % 2 else "scale")
        if k % 5 == 0:
            company, slug = CONTACTS[k % len(CONTACTS)]
            answer(store, company, slug, item.sent + timedelta(days=1), "interested", f"r{k}")


def pick_angle(prompt):
    return {**default_draft(prompt),
            "angle": re.search(r"^Angle: (\w+) \(", prompt, re.M).group(1)}


def test_the_bandit_waits_for_thirty_sends_and_for_the_setting(folder):
    root, store = folder
    drafter, _, company, contact, approach, _ = drafter_and_inputs(store, {})
    angles = ("scale", "hook", "custom")
    config = {"learning_angle_sampling": True}
    sends(root, store, 12)
    assert exemplars.sample_for_draft(store, company, contact, approach, angles, config) is None
    sends(root, store, 31)
    assert exemplars.sample_for_draft(store, company, contact, approach, angles, {}) is None
    chosen = exemplars.sample_for_draft(store, company, contact, approach, angles, config)
    assert chosen.angle in ("scale", "hook") and "exploration policy" in chosen.reason
    again = exemplars.sample_for_draft(store, company, contact, approach, angles, config)
    assert again == chosen                                  # a preview matches the draft
    only_one = exemplars.sample_for_draft(store, company, contact, approach, ("scale",), config)
    assert only_one is None


def test_a_sampled_angle_narrows_the_prompt_and_the_checks_to_it(folder):
    root, store = folder
    sends(root, store, 31)
    config = {"learning_angle_sampling": True, "outreach_angles": ["scale", "hook", "custom"]}
    draft, fake = draft_for_target(store, config, FakeAI(drafts=[pick_angle]))
    prompt = fake.of("draft")[0]["prompt"]
    assert "Angle: one of " not in prompt and "chosen by the exploration policy" in prompt
    assert draft.angle in ("scale", "hook") and draft.problems == []
    assert draft.angle_note.startswith(f"angle {draft.angle} chosen by the exploration policy")
    off, fake_off = draft_for_target(store, {"outreach_angles": ["scale", "hook", "custom"]},
                                     FakeAI(drafts=[default_draft]))
    assert "Angle: one of scale, hook, custom" in fake_off.of("draft")[0]["prompt"]
    assert off.angle_note == ""


# --------------------------------------------------------------------- CLI


def learn(store, root, *argv, config=None):
    args = cli._build_parser().parse_args(["learn", *argv])
    return cli.cmd_learn(store, root, config if config is not None else {}, args)


def test_the_exemplars_command_lists_them_and_previews_a_prompt_block(folder):
    root, store = folder
    worked(root, store, 1, 0)
    corrected(root, 2, 1)
    target = make(root, 3, TARGET, state="drafted", findings=(OFFICE,))
    text, code = learn(store, root, "exemplars")
    assert code == 0
    assert "Setting learning_exemplars = off" in text
    assert "Exemplars: 1 outcome, 1 correction; 0 pinned, 0 excluded" in text
    assert "outcome:t01  positive reply" in text and "correction:t02" in text
    text, _ = learn(store, root, "exemplars", "--item", target.id,
                    config={"learning_exemplars": "both"})
    assert "Prompt block for t03 - phase 0, 2 to choose from:" in text
    assert "correction:t02: relevance" in text and "same persona (founder)" in text
    assert "--- examples from the seller's own earlier messages" in text
    assert "tokens added to the prompt" in text
    text, code = learn(store, root, "exemplars", "--item", "nope")
    assert "No outreach item 'nope'" in text.splitlines()[-1]


def test_pin_exclude_and_unmark_commands(folder):
    root, store = folder
    worked(root, store, 1)
    text, code = learn(store, root, "pin", "outcome:t01")
    assert code == 0 and text.startswith("outcome:t01: pin (positive reply")
    assert "pinned" in learn(store, root, "exemplars")[0].replace("1 pinned", "pinned")
    assert learn(store, root, "exclude", "outcome:t01")[0].startswith("outcome:t01: exclude")
    assert learn(store, root, "unmark", "outcome:t01")[0].startswith("outcome:t01: no mark")
    text, code = learn(store, root, "pin", "outcome:zzz")
    assert code == 1 and "no exemplar" in text


def test_the_angles_command_shows_the_table_and_the_gate(folder):
    root, store = folder
    sends(root, store, 12)
    text, code = learn(store, root, "angles")
    assert code == 0
    assert "First-touch sends: 12 (the bandit acts from 30)" in text
    assert "Setting learning_angle_sampling = off" in text
    assert "  scale: " in text and "  hook: " in text and "Next experiment: " in text
