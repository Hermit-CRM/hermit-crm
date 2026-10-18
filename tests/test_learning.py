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

"""Learning, the pure part: lesson ids, the outcome ladder and its credit
rules, signals, phases, edit features, patterns, trend, rates, evidence cards
and the proposal validator. No AI is called; every name is made up."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from hermitcrm import learning, outreach, playbook
from hermitcrm.learning import Card, Lesson, Signal
from hermitcrm.models import Interaction, StageChange
from outreach_fakes import NOW, demo

APPROACH = "Founder coaching"
CONTACTS = [("lindenhof-data", "mara-keller"), ("kestrel-metrics", "daan-visser"),
            ("ravenmoor-systems", "ines-moreau"), ("tallpine-software", "oliver-hart"),
            ("saltmarsh-labs", "ciaran-doyle"), ("saltmarsh-labs", "niamh-walsh"),
            ("copperleaf-studio", "camille-martin"), ("bluefin-analytics", "joris-veldkamp")]
FIRSTS = {"mara-keller": "Mara", "daan-visser": "Daan", "ines-moreau": "Ines",
          "oliver-hart": "Oliver", "ciaran-doyle": "Ciaran", "niamh-walsh": "Niamh",
          "camille-martin": "Camille", "joris-veldkamp": "Joris"}
CLICHE = "I hope this finds you well."


def ai_body(first="Mara"):
    return (f"Hi {first},\n\n{CLICHE}\nThe second office this autumn caught my eye.\n"
            "We help founders build a sales team that sells without them, step by step, "
            "with weekly coaching and a clear plan.\n"
            "Where does it hurt most right now: pipeline, conversion or deal size?\n\nSam")


def shorter(body):
    """The edit people keep making: the cliché out, the long line cut."""
    return body.replace(CLICHE + "\n", "").replace(
        ", step by step, with weekly coaching and a clear plan", "")


def make(root, n, contact=0, *, edits=(), state="ready", minutes=5, days=0, sent=None,
         skipped=None, kind="first-touch", channel="email", approach=APPROACH, angle="hook",
         language="en", batch="b1", lessons_used=(), findings=(), skip_reason="",
         skip_note="", why="", body=None, subject="Your second office"):
    """One outreach item written to the folder. `edits`: (body, note, tags)
    tuples; `minutes` from drafted to ready; `days` before NOW it was drafted."""
    company, slug = CONTACTS[contact]
    first = FIRSTS[slug]
    drafted = NOW - timedelta(days=days)
    original = body or ai_body(first)
    item = outreach.Item(
        id=f"t{n:02d}", state=state, kind=kind, channel=channel, company=company,
        contact=slug, approach=approach, angle=angle, language=language, subject=subject,
        batch=batch, created=drafted, drafted=drafted, ai_subject=subject, ai_body=original,
        body=original, findings=[outreach.Finding(t, "https://example.com", "trigger", "high",
                                                  used=True) for t in findings])
    before = original
    for k, (text, note, tags) in enumerate(edits):
        edit = outreach.TrackedEdit(at=outreach.fmt_datetime(drafted + timedelta(minutes=k + 1)),
                                    words=outreach.edit_distance(before, text), note=note,
                                    subject=subject, body=text)
        if hasattr(edit, "tags"):
            edit.tags = list(tags)
        item.edits.append(edit)
        before = text
    item.body = before
    if why:
        item.earlier = [outreach.Earlier(ai_body="An older draft.", why=why)]
    if state in ("ready", "sent"):
        item.ready = drafted + timedelta(minutes=minutes)
        item.edit_distance = outreach.edit_distance(subject + "\n" + original,
                                                    subject + "\n" + item.body)
    if state == "sent":
        item.sent = sent or item.ready
    if state == "skipped":
        item.skipped = skipped or drafted + timedelta(minutes=minutes)
        item.skip_reason, item.skip_note = skip_reason or "bad-draft", skip_note
    if hasattr(item, "lessons_used"):
        item.lessons_used = list(lessons_used)
    outreach.write_item(root, item)
    return item


@pytest.fixture
def folder(tmp_path):
    return demo(tmp_path)


def sig(**kw) -> Signal:
    base = dict(item_id="x", company="c", contact="p", state="sent",
                rungs={"sent": date(2026, 10, 1)})
    base.update(kw)
    return Signal(**base)


# ------------------------------------------------------------- lesson ids


def test_a_lesson_id_ignores_the_bullet_case_and_spacing():
    a = learning.lesson_id("- Keep it   short.")
    assert a == learning.lesson_id("keep it short.") == learning.lesson_id("*  KEEP IT SHORT.")
    assert a.startswith("L") and len(a) == 7
    assert a != learning.lesson_id("Keep it shorter.")


def test_lessons_reads_the_three_parts_in_order(folder):
    root, _ = folder
    found = learning.lessons(root, APPROACH)
    assert [(x.part, x.text) for x in found] == [
        ("worked", "A question about who closes deals today got the most replies "
                   "(made-up example)."),
        ("open", "Whether German founders prefer email or LinkedIn.")]
    assert learning.lessons(playbook.load(root), "No such approach") == []


def test_lesson_ids_of_a_prompt_text_are_unique_and_in_order():
    text = ("# Approach: X\n\n## Voice\n\n- Plain words.\n\n## Lessons\n\n<!-- - not this -->\n"
            "### Worked\n\n- Ask about the team.\n\n### Didn't work\n\n- Long intros.\n"
            "- ask about   the team.\n\n### Still testing\n\n* Short subjects\n\n"
            "### Other\n\n- not a part\n\n## Don'ts\n\n- No buzzwords.\n")
    assert learning.lesson_ids(text) == [learning.lesson_id("Ask about the team."),
                                         learning.lesson_id("Long intros."),
                                         learning.lesson_id("Short subjects")]


def test_lesson_ids_of_the_drafted_playbook_text_match_lessons(folder):
    root, _ = folder
    text = playbook.body_for_ai((root / "MESSAGING.md").read_text(), APPROACH)
    assert learning.lesson_ids(text) == [x.id for x in learning.lessons(root, APPROACH)]


# ------------------------------------------------------- ladder and credit


def _answer(store, company, contact, when, outcome="", id_="in1"):
    store.get(company).interactions.append(Interaction(
        id=id_, date=when, channel="email", direction="in", contact=contact, outcome=outcome))


def test_the_ladder_of_a_sent_item_from_replies_and_stages(folder):
    root, store = folder
    item = make(root, 1, state="sent", days=10)
    sent = item.sent
    assert learning.ladder(store, item) == {"sent": sent.date()}
    _answer(store, "lindenhof-data", "mara-keller", sent - timedelta(days=1), "interested", "old")
    assert "replied" not in learning.ladder(store, item)          # before it went out
    _answer(store, "lindenhof-data", "mara-keller", sent + timedelta(days=2))
    _answer(store, "lindenhof-data", "mara-keller", sent + timedelta(days=3), "interested", "i2")
    company = store.get("lindenhof-data")
    company.stage_history = [StageChange(sent.date() - timedelta(days=5), "", "discovery"),
                             StageChange(sent.date() + timedelta(days=4), "prospect", "discovery"),
                             StageChange(sent.date() + timedelta(days=8), "offer", "won")]
    rungs = learning.ladder(store, item)
    assert rungs == {"sent": sent.date(), "replied": sent.date() + timedelta(days=2),
                     "positive": sent.date() + timedelta(days=3),
                     "deal": sent.date() + timedelta(days=4),
                     "won": sent.date() + timedelta(days=8)}


def test_deal_is_credited_to_first_touch_and_reply_but_won_to_every_item(folder):
    root, store = folder
    follow = make(root, 2, state="sent", days=10, kind="follow-up")
    reply = make(root, 3, state="sent", days=9, kind="reply-to-interest")
    day = follow.sent.date()
    store.get("lindenhof-data").stage_history = [
        StageChange(day + timedelta(days=3), "engaged", "discovery"),
        StageChange(day + timedelta(days=6), "offer", "won")]
    assert set(learning.ladder(store, follow)) == {"sent", "won"}
    assert set(learning.ladder(store, reply)) == {"sent", "deal", "won"}


def test_an_unsent_item_has_no_rungs_and_a_confirmed_verdict_is_positive(folder):
    root, store = folder
    assert learning.ladder(store, make(root, 4)) == {}
    item = make(root, 5, state="sent", days=5)
    _answer(store, "lindenhof-data", "mara-keller", item.sent + timedelta(days=1), id_="r9")
    by_ai = {"lindenhof-data/r9": {"verdict": "interested", "by": "ai"}}
    by_you = {"lindenhof-data/r9": {"verdict": "interested", "by": "you"}}
    assert "positive" not in learning.ladder(store, item, by_ai)
    assert "positive" in learning.ladder(store, item, by_you)


# ------------------------------------------------------------- signals


def test_signals_keep_reviewed_items_with_their_attributes(folder):
    root, store = folder
    make(root, 1, edits=[(shorter(ai_body()), "too long", ("too-long",))],
         findings=["Opened a second office this autumn"], lessons_used=["Labc123"], why="stiff")
    make(root, 2, contact=1, state="drafted")                 # not reviewed: left out
    make(root, 3, contact=2, state="skipped", skip_reason="bad-fit", skip_note="too small")
    make(root, 4, contact=3, approach="Scaling the sales team")
    found = learning.signals(store, APPROACH)
    assert [s.item_id for s in found] == ["t01", "t03"]
    s = found[0]
    assert (s.persona, s.channel, s.kind, s.angle) == ("founder", "email", "first-touch", "hook")
    assert s.notes == ["too long"] and s.regenerate_whys == ["stiff"]
    assert s.findings_used == ["Opened a second office this autumn"]
    assert s.edit_words > 0 and len(s.edits) == 1 and s.overall.words_delta < 0
    if hasattr(outreach.TrackedEdit(at="", words=0), "tags"):
        assert s.tags == ["too-long"] and s.lessons_used == ["Labc123"]
    assert found[1].skip_reason == "bad-fit" and found[1].skip_note == "too small"
    assert len(learning.signals(store)) == 3


def test_a_rubber_stamp_counts_at_a_quarter(folder):
    root, store = folder
    make(root, 1, minutes=0)                                   # ready in the same minute
    make(root, 2, contact=1, minutes=10)                       # read for ten minutes
    make(root, 3, contact=2, minutes=0, edits=[(shorter(ai_body("Ines")), "", ())])
    by_id = {s.item_id: s for s in learning.signals(store)}
    assert by_id["t01"].rubber_stamp and by_id["t01"].weight == learning.RUBBER_STAMP_WEIGHT
    assert not by_id["t02"].rubber_stamp and by_id["t02"].weight == 1.0
    assert not by_id["t03"].rubber_stamp


def test_recency_halves_the_weight_every_half_life(folder):
    root, store = folder
    make(root, 1, days=60)
    assert learning.signals(store)[0].weight == pytest.approx(0.5, abs=0.01)
    config = {"learning_half_life_days": 30}
    assert learning.signals(store, config=config)[0].weight == pytest.approx(0.25, abs=0.01)


# ------------------------------------------------------------- phases


@pytest.mark.parametrize("counts, number", [
    ({}, 0),
    ({"reviewed": 19}, 0),
    ({"reviewed": 20}, 1),
    ({"reviewed": 40, "sent": 30, "replied": 7}, 1),
    ({"reviewed": 40, "sent": 30, "replied": 8}, 2),
    ({"reviewed": 40, "sent": 30, "replied": 8, "deal": 5}, 3),
    ({"reviewed": 40, "sent": 30, "replied": 8, "deal": 5, "won": 3}, 4),
])
def test_the_phase_is_chosen_by_counts(counts, number):
    ph = learning.phase(counts)
    assert ph.number == number
    assert sum(ph.weights.values()) == 100


def test_the_phase_can_be_pinned_and_its_thresholds_changed():
    assert learning.phase({}, {"learning_phase_pin": 2}).number == 2
    assert learning.phase({}, {"learning_phase_pin": 2}).pinned
    per = {"learning_phase_pin": {"Founder coaching": 3}}
    assert learning.phase({}, per, "founder coaching").number == 3
    assert learning.phase({}, per, "Other").number == 0
    lower = {"learning_phases": [{"number": 1, "when": {"reviewed": 5}, "name": "Early"}]}
    ph = learning.phase({"reviewed": 5}, lower)
    assert (ph.number, ph.name) == (1, "Early") and "5 reviewed drafts (needs 5)" in ph.reason


def test_the_banner_says_the_counts_and_what_it_learns_from():
    ph = learning.phase({"reviewed": 31, "sent": 20, "replied": 6, "positive": 2})
    assert learning.banner(ph) == ("31 reviewed drafts, 6 replies, 2 positive: phase 1 "
                                   "(Style settles), learning mainly from your edits and "
                                   "replies")


def test_counts_use_distinct_companies_for_deals_and_wins():
    d = date(2026, 10, 1)
    sigs = [sig(company="a", rungs={"sent": d, "replied": d, "deal": d}),
            sig(company="a", rungs={"sent": d, "deal": d, "won": d}),
            sig(company="b", rungs={"sent": d, "positive": d, "replied": d}),
            sig(company="c", state="skipped", rungs={})]
    assert learning.counts(sigs) == {"reviewed": 4, "sent": 3, "replied": 2, "positive": 1,
                                     "deal": 1, "won": 1}


# ------------------------------------------------------------- edit features


def test_edit_features_name_what_changed():
    before = ("Your second office", "", "Hi Mara,\n\nI hope this finds you well.\n"
              "The second office caught my eye.\nWhat is [the pain] now? And why?\n\nBest,\nSam")
    after = ("Second office", "", "Hello Mara,\n\nYour new Lisbon team caught my eye.\n"
             "What is pipeline now?\n\nSam")
    f = learning.edit_features(before, after, set(),
                               findings=["Opened a second office in Lisbon this autumn"])
    assert f.words_delta < 0 and f.sentences_delta < 0
    assert f.opening_changed and f.questions_delta == -1 and f.gaps_filled == 1
    assert f.subject_changed and f.signoff_changed and f.greeting_changed
    assert "i hope this finds you well" in f.removed_phrases
    assert not f.situational and not f.typo_only


def test_an_edit_about_this_prospect_only_is_situational():
    body = "Hi Mara,\n\nThe Lisbon office caught my eye.\nHow do you sell?\n\nSam"
    after = body.replace("Lisbon", "Porto")
    words = learning.situational_words(["Moved from Lisbon to Porto"], ["Mara Keller"])
    f = learning.edit_features(("", "", body), ("", "", after), words)
    assert f.situational and f.changed_words == 2
    assert not learning.edit_features(("", "", body), ("", "", body.replace(
        "caught my eye", "stood out")), words).situational


def test_a_typo_fix_is_typo_only():
    body = "Hi Mara,\n\nThe secnd office caught my eye.\n\nSam"
    f = learning.edit_features(("", "", body), ("", "", body.replace("secnd", "second")))
    assert f.typo_only
    assert not learning.edit_features(("", "", body), ("", "", body.replace(
        "secnd office", "new team"))).typo_only


# ------------------------------------------------------------- patterns


def _shortened(root, n, contact, **kw):
    first = FIRSTS[CONTACTS[contact][1]]
    return make(root, n, contact, edits=[(shorter(ai_body(first)), "", ())], **kw)


def test_a_pattern_needs_five_of_the_last_ten_over_three_contacts(folder):
    root, store = folder
    for n in range(5):
        _shortened(root, n, n % 3, days=10 - n)
    for n in range(5, 10):
        make(root, n, n % 3, days=10 - n)
    found = learning.patterns(learning.signals(store))
    words = next(p for p in found if p.feature == "words")
    assert (words.direction, words.hits, words.of) == ("shorter", 5, 10)
    assert words.text == "shortened the text in 5 of 10"
    assert sorted(words.item_ids) == ["t00", "t01", "t02", "t03", "t04"]


def test_no_pattern_with_too_few_hits_or_contacts(folder):
    root, store = folder
    for n in range(5):
        _shortened(root, n, n % 2, days=10 - n)                 # two contacts only
    assert learning.patterns(learning.signals(store)) == []
    assert learning.patterns(learning.signals(store), min_contacts=2) != []
    assert learning.patterns(learning.signals(store), min_hits=6, min_contacts=2) == []


def test_situational_edits_never_make_a_pattern(folder):
    root, store = folder
    for n in range(6):
        first = FIRSTS[CONTACTS[n][1]]
        make(root, n, n, findings=["Opened an office in Porto this autumn"],
             edits=[(ai_body(first).replace("second office", "Porto office"), "", ())])
    assert learning.patterns(learning.signals(store)) == []


def test_the_feature_table_has_a_row_per_edited_draft(folder):
    root, store = folder
    _shortened(root, 1, 0)
    make(root, 2, 1)
    rows = learning.feature_table(learning.signals(store))
    assert [r.item_id for r in rows] == ["t01"] and rows[0].words_delta < 0
    assert rows[0].contact == "lindenhof-data/mara-keller"


# ------------------------------------------------------------- trend


def test_the_trend_gives_median_edits_and_unchanged_rate_per_batch(folder):
    root, store = folder
    for n in range(3):
        _shortened(root, n, n, batch="b1", days=9)
    _shortened(root, 3, 3, batch="b2", days=2)
    make(root, 4, 4, batch="b2", days=2)
    make(root, 5, 5, batch="b2", days=2)
    stats = learning.trend(learning.signals(store))
    assert [(s.batch, s.drafts, s.ready_without_edit) for s in stats] == [("b1", 3, 0),
                                                                         ("b2", 3, 2)]
    assert stats[0].median_edit_words > stats[1].median_edit_words == 0
    assert stats[1].rate == pytest.approx(0.667, abs=0.001)
    line = learning.since_line(stats, new_lessons=2)
    assert line.startswith("2 new lessons, median edit ") and "→ 0 words over the last 2" in line
    assert learning.trend(learning.signals(store), batches=1)[0].batch == "b2"
    assert learning.since_line(stats[:1]) == ""


# ------------------------------------------------------------- rates


def test_rates_shrink_toward_the_average_and_flag_small_cells():
    d = date(2026, 10, 1)
    sigs = [sig(angle="hook", rungs={"sent": d, "replied": d, "positive": d})]
    sigs += [sig(angle="scale", rungs={"sent": d, "replied": d, "positive": d})
             for _ in range(12)]
    sigs += [sig(angle="scale") for _ in range(18)]
    rows = {r.value: r for r in learning.rates(sigs, "angle")}
    assert rows["hook"].counts["positive"] == 1 and rows["hook"].n == 1
    assert rows["hook"].too_few and not rows["scale"].too_few
    # 1 of 1 is pulled to the average; it does not beat 12 of 30 by much
    assert rows["hook"].rates["positive"] < 0.5
    base = 13 / 31
    assert rows["hook"].rates["positive"] == pytest.approx((1 + 10 * base) / 11, abs=1e-4)
    with pytest.raises(ValueError):
        learning.rates(sigs, "colour")


# ------------------------------------------------------------- cards


def test_cards_keep_style_edits_and_drop_noise(folder):
    root, store = folder
    _shortened(root, 1, 0, days=3)                                         # kept
    body = ai_body("Daan")
    make(root, 2, 1, days=3, edits=[(body.replace("caught", "caugth"), "", ())])   # typo
    make(root, 3, 2, days=3, findings=["Opened an office in Porto this autumn"],
         edits=[(ai_body("Ines").replace("second office", "Porto office"), "", ())])  # situational
    make(root, 4, 3, days=3, edits=[(ai_body("Oliver").replace("Sam", "Sam B."), "", ())])  # small
    make(root, 5, 4, days=3, edits=[(ai_body("Ciaran").replace("Sam", "S."), "sign shorter",
                                     ())])                                 # small, with a note
    make(root, 6, 5, days=3)                                               # approved as is
    make(root, 7, 6, days=3, state="skipped", skip_reason="bad-fit", skip_note="agency")
    make(root, 8, 7, days=3, state="drafted",
         edits=[(shorter(ai_body("Joris")), "", ())])                     # not final
    ids = [c.id for c in learning.cards(store, APPROACH)]
    assert ids == ["t01", "t05", "t06", "t07"]


def test_a_card_is_short_pseudonymous_and_says_what_changed(folder):
    root, store = folder
    body = ai_body("Mara") + "\nLindenhof Data is growing fast."
    make(root, 1, body=body, edits=[(shorter(body).replace("Lindenhof Data is growing fast.",
                                                         "Mara, you are growing fast."),
                                     "Mara hates fluff", ())], why="Lindenhof sounded stiff")
    make(root, 2, 1)
    card, plain = learning.cards(store, APPROACH)
    assert "Mara" not in card.text and "Lindenhof" not in card.text
    assert "[CONTACT]" in card.text and "[COMPANY]" in card.text
    assert "- I hope this finds you well." in card.text
    assert "note: [CONTACT] hates fluff" in card.text
    assert learning.estimate_tokens(card.text) <= 200
    assert plain.text.endswith("\napproved as is") and plain.text.count("\n") == 1
    assert card.contact == "lindenhof-data/mara-keller"


def test_small_edits_are_kept_when_the_same_phrase_is_removed_again(folder):
    root, store = folder
    for n in range(2):
        first = FIRSTS[CONTACTS[n][1]]
        make(root, n, n, edits=[(ai_body(first).replace("Sam", "").rstrip() + "\n", "", ())])
    make(root, 5, 4, edits=[(ai_body("Ciaran").replace("autumn", "fall"), "", ())])
    assert [c.id for c in learning.cards(store, APPROACH)] == ["t00", "t01"]


def test_cards_start_after_the_watermark(folder):
    root, store = folder
    make(root, 1, days=5)
    make(root, 2, 1, days=1)
    since = NOW - timedelta(days=3)
    assert [c.id for c in learning.cards(store, APPROACH, since)] == ["t02"]
    assert learning.cards(store, "Scaling the sales team") == []


def test_the_distill_prompt_carries_lessons_rejected_and_cards():
    cards = [Card(id="t01", kind="first-touch", channel="email", unchanged=True)]
    text = learning.distill_prompt("Founder coaching", cards,
                                   [Lesson("Labc123", "open", "Short subjects")], ["Use emojis"])
    assert "Labc123 [open] Short subjects" in text and "- Use emojis" in text
    assert "card t01 |" in text and "approved as is" in text
    assert "at most 5 changes" in text


# ------------------------------------------------------------- validator


CARDS = [Card(id=f"c{n}", contact=f"co{n % 3}/p{n}") for n in range(5)]
LESSONS = [Lesson(learning.lesson_id("Ask about the team."), "worked", "Ask about the team."),
           Lesson(learning.lesson_id("Short subjects."), "open", "Short subjects."),
           Lesson(learning.lesson_id("Always offer an opt-out line."), "worked",
                  "Always offer an opt-out line.")]


def prop(**kw):
    base = {"op": "add", "part": "open", "text": "Lead with their hiring.",
            "replaces": [], "cites": ["c0", "c1", "c2"], "why": "seen thrice"}
    base.update(kw)
    return base


TWO = [Card(id=f"c{n}", contact=f"co{n % 2}/p{n % 2}") for n in range(5)]


def check(*props, lessons=LESSONS, rejected=(), cards=CARDS):
    return learning.validate_proposals({"proposals": list(props)}, cards, lessons, rejected,
                                       "Founder coaching")


def test_a_good_add_passes_with_a_stable_id():
    kept, problems = check(prop())
    assert problems == [] and len(kept) == 1
    p = kept[0]
    assert (p.op, p.part, p.text, p.cites, p.status) == ("add", "open",
                                                         "Lead with their hiring.",
                                                         ["c0", "c1", "c2"], "pending")
    assert p.id == check(prop())[0][0].id and p.id.startswith("P")


def test_an_add_needs_three_cards_from_three_contacts():
    assert "needs 3 cards from 3 people" in check(prop(cites=["c0", "c1"]))[1][0]
    assert "has 3 from 2" in check(prop(cites=["c0", "c3", "c1"]), cards=TWO)[1][0]


def test_cites_must_exist():
    kept, problems = check(prop(cites=["c0", "c1", "zz"]))
    assert kept == [] and "unknown cards zz" in problems[0]
    assert "cites no card" in check(prop(cites=[]))[1][0]


def test_worked_is_never_proposed_from_cards():
    kept, _ = check(prop(part="worked"))
    assert kept[0].part == "open"


def test_the_cap_of_twelve_lessons_asks_to_merge_first():
    many = [Lesson(learning.lesson_id(f"Lesson {n}"), "open", f"Lesson {n}") for n in range(12)]
    kept, problems = check(prop(), lessons=many)
    assert kept == [] and "merge or retire first" in problems[0]
    merge = prop(op="merge", text="Lessons 0 and 1 together.",
                 replaces=[many[0].id, many[1].id])
    kept, problems = check(merge, prop(), lessons=many)
    assert [p.op for p in kept] == ["merge", "add"] and problems == []


def test_honesty_and_opt_out_lessons_are_never_touched():
    opt = LESSONS[2].id
    assert "never changed by learning" in check(prop(op="retire", text="", replaces=[opt]))[1][0]
    assert "weaken" in check(prop(text="Drop the opt-out line for founders."))[1][0]


def test_rejected_texts_are_never_proposed_again():
    kept, problems = check(prop(text="lead with  their hiring."),
                           rejected=["Lead with their hiring."])
    assert kept == [] and "rejected this before" in problems[0]


def test_ops_parts_and_replaces_are_checked():
    _, problems = check(prop(op="delete"), prop(part="maybe"), prop(op="rewrite", replaces=[]),
                        prop(op="merge", replaces=[LESSONS[0].id]),
                        prop(op="retire", replaces=["Lnope00"]))
    assert len(problems) == 5
    assert "op must be one of" in problems[0] and "part must be one of" in problems[1]
    assert "says which lesson" in problems[2] and "two lessons or more" in problems[3]
    assert "unknown lessons Lnope00" in problems[4]
    kept, _ = check(prop(op="retire", text="", replaces=[LESSONS[1].id], part="worked"))
    assert (kept[0].part, kept[0].text) == ("open", "Short subjects.")
    assert "already there" in check(prop(text="Ask about the team."))[1][0]


def test_more_than_five_proposals_and_a_broken_answer():
    kept, problems = check(*[prop(text=f"Lesson number {n}.") for n in range(7)])
    assert len(kept) == 5 and "only the first 5" in problems[0]
    assert learning.validate_proposals("nonsense", CARDS, LESSONS) == (
        [], ["the answer has no list of proposals"])
    assert json.loads(json.dumps(learning.PROPOSAL_SCHEMA))["properties"]["proposals"][
        "maxItems"] == 5


def test_the_lesson_count_constant_and_date_types():
    assert learning.LESSON_CAP == 12 and learning.RUNGS[-1] == "won"
    assert isinstance(NOW, datetime)
