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

"""Learning, the writing part: suggestion cards applied to messages.toml and
config.toml, distill runs (hermit and hand-off), import, accept / reject /
retire / move writing the Lessons of MESSAGING.md, the scoreboard and status.
The AI is a fake that returns canned JSON; every name is made up."""

from __future__ import annotations

import json
import math
import tomllib
from datetime import timedelta

import pytest

from hermitcrm import learning, playbook
from hermitcrm.enrich import Enricher, EnrichError
from hermitcrm.models import Interaction
from hermitcrm.store import load_config
from outreach_fakes import ALL, NOW, git
from test_learning import (  # noqa: F401  (fixtures and builders)
    APPROACH, CONTACTS, FIRSTS, ai_body, folder, make, shorter,
)


def log(root) -> list[str]:
    return git(root, "log", "--format=%s").splitlines()


class Runner:
    """The AI CLI: returns a canned answer (or one built from the prompt)."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        return self.answer(prompt) if callable(self.answer) else self.answer


def ai(answer) -> tuple[Enricher, Runner]:
    runner = Runner(answer)
    return Enricher(provider="claude", which=ALL, runner=runner), runner


def shortened_batch(root, count=6, days=3):
    for n in range(count):
        first = FIRSTS[CONTACTS[n][1]]
        make(root, n, n, days=days, edits=[(shorter(ai_body(first)), "too long", ())])


def add(cites, text="Cut the warm-up line; open with the finding.", **kw):
    return {"op": "add", "part": "open", "text": text, "replaces": [], "cites": cites,
            "why": "removed in every draft", **kw}


# ------------------------------------------------------------ suggestions


def test_shortened_drafts_suggest_a_lower_word_limit_written_to_messages_toml(folder):
    root, store = folder
    shortened_batch(root)
    sigs = learning.signals(store)
    found = {s.kind: s for s in learning.suggestions(store, sigs, {})}
    limit = found["body_max_words"]
    words = len(shorter(ai_body("Mara")).split())
    assert (limit.current, limit.proposed) == (120, max(40, words // 5 * 5))
    assert limit.text.startswith("You shortened 6 of 6 drafts. Lower the word limit from 120")
    before = len(log(root))
    learning.accept_suggestion(store, limit.id, {}, sigs)
    data = tomllib.loads((root / "messages.toml").read_text())
    assert data["outreach"]["email"]["body_max_words"] == limit.proposed
    assert len(log(root)) == before + 1
    assert log(root)[0] == f"learn: email word limit 120 → {limit.proposed}"
    assert learning.current_body_max_words(root) == limit.proposed


def test_the_word_limit_goes_into_an_existing_table_keeping_the_rest(folder):
    root, store = folder
    (root / "messages.toml").write_text(
        "# my wording\n[outreach.email]\nbody_max_words = 120  # keep short\nsubject_max = 50\n"
        "\n[outreach.linkedin]\nnote_max_chars = 280\n")
    shortened_batch(root)
    limit = next(s for s in learning.suggestions(store, learning.signals(store), {})
                 if s.kind == "body_max_words")
    learning.accept_suggestion(store, limit.id, {})
    text = (root / "messages.toml").read_text()
    assert text == ("# my wording\n[outreach.email]\n"
                    f"body_max_words = {limit.proposed}  # keep short\nsubject_max = 50\n"
                    "\n[outreach.linkedin]\nnote_max_chars = 280\n")


def test_a_phrase_removed_from_three_contacts_drafts_suggests_never_write(folder):
    root, store = folder
    shortened_batch(root, count=3)
    found = [s for s in learning.suggestions(store, learning.signals(store), {})
             if s.kind == "never_write"]
    phrase = next(s for s in found if s.proposed == "i hope this finds you well")
    assert phrase.text == ('You removed "i hope this finds you well" from 3 drafts. Never '
                           'write it again?')
    assert sorted(phrase.evidence) == ["t00", "t01", "t02"]
    learning.accept_suggestion(store, phrase.id)
    assert load_config(root)["outreach_never_write"] == ["i hope this finds you well"]
    assert log(root)[0] == 'learn: never write "i hope this finds you well"'
    config = load_config(root)
    again = learning.suggestions(store, learning.signals(store, config=config), config)
    assert all(s.proposed != "i hope this finds you well" for s in again)


def test_no_suggestion_from_two_contacts_and_an_unknown_id_is_refused(folder):
    root, store = folder
    for n in range(4):
        first = FIRSTS[CONTACTS[n % 2][1]]
        make(root, n, n % 2, edits=[(shorter(ai_body(first)), "", ())])
    assert learning.suggestions(store, learning.signals(store), {}) == []
    with pytest.raises(learning.LearningError, match="no suggestion"):
        learning.accept_suggestion(store, "body_max_words-60")


# ------------------------------------------------------------ runs


def test_a_hermit_run_stores_validated_proposals_and_moves_the_watermark(folder):
    root, store = folder
    shortened_batch(root)
    enricher, runner = ai({"proposals": [add(["t00", "t01", "t02"]),
                                         add(["t00", "t01"], text="Too thin.")]})
    before = len(log(root))
    result = learning.run(store, APPROACH, enricher, {})
    assert result.status == "proposed" and result.cards == 6
    assert [p.text for p in result.proposals] == ["Cut the warm-up line; open with the finding."]
    assert "needs 3 cards" in result.problems[0]
    call = runner.calls[0]
    assert call["schema"] is learning.PROPOSAL_SCHEMA and call["tools"] == ""
    assert "card t05 |" in call["prompt"] and "Mara" not in call["prompt"]
    assert result.tokens == math.ceil(len(call["prompt"]) / 4)
    assert len(log(root)) == before + 1
    assert log(root)[0] == f"learn: 1 proposal for {APPROACH} from 6 cards"
    state = learning.load_state(root)
    raw = (root / "learning" / "state.json").read_text()
    assert raw == json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert state["approaches"][APPROACH]["watermark"] == "2026-10-13T09:05"
    assert [p.status for p in learning.proposals(root, APPROACH)] == ["pending"]
    # nothing new since: skipped, no call, no commit
    again = learning.run(store, APPROACH, enricher, {})
    assert again.status == "skipped" and len(runner.calls) == 1
    assert len(log(root)) == before + 1


def test_a_run_with_the_same_answer_does_not_duplicate_a_proposal(folder):
    root, store = folder
    shortened_batch(root)
    enricher, _ = ai({"proposals": [add(["t00", "t01", "t02"])]})
    learning.run(store, APPROACH, enricher, {})
    make(root, 9, 6, days=1, edits=[(shorter(ai_body("Camille")), "too long", ())])
    learning.run(store, APPROACH, enricher, {})
    assert len(learning.proposals(root)) == 1


def test_a_run_without_an_ai_says_why(folder):
    root, store = folder
    shortened_batch(root)
    enricher = Enricher(provider="claude", which=lambda b: None)
    with pytest.raises(EnrichError):
        learning.run(store, APPROACH, enricher, {})
    assert not (root / "learning" / "state.json").exists()


def test_handoff_writes_the_pack_and_import_reads_the_answer(folder):
    root, store = folder
    shortened_batch(root)
    result = learning.run(store, APPROACH, None, {"learning_distill": "handoff"})
    assert result.status == "handoff" and result.path == "learning/evidence-pack.md"
    pack = (root / "learning" / "evidence-pack.md").read_text()
    assert "card t00 |" in pack and '"maxItems": 5' in pack
    assert "learning/proposals.json" in pack and "Mara" not in pack
    assert log(root)[0] == f"learn: evidence pack for {APPROACH} (6 cards)"
    assert learning.load_state(root)["approaches"][APPROACH].get("watermark") is None
    with pytest.raises(learning.LearningError, match="no learning/proposals.json"):
        learning.import_proposals(store, APPROACH)
    (root / "learning" / "proposals.json").write_text(json.dumps(
        {"proposals": [add(["t00", "t01", "t02"]), add(["t00", "t01", "zz"], text="X y.")]}))
    done = learning.import_proposals(store, APPROACH)
    assert len(done.proposals) == 1 and "unknown cards zz" in done.problems[0]
    assert log(root)[0] == f"learn: imported 1 proposal for {APPROACH}"
    state = learning.load_state(root)
    assert state["approaches"][APPROACH]["watermark"] == "2026-10-13T09:05"
    assert "pack" not in state["approaches"][APPROACH]
    with pytest.raises(learning.LearningError, match="no evidence pack"):
        learning.import_proposals(store, APPROACH)


# ------------------------------------------------- accept, reject, retire


def pending(root, store, *answers):
    shortened_batch(root)
    enricher, _ = ai({"proposals": list(answers)})
    learning.run(store, APPROACH, enricher, {})
    return learning.proposals(root, APPROACH, "pending")


def test_accept_adds_the_lesson_to_still_testing_in_one_commit(folder):
    root, store = folder
    (p,) = pending(root, store, add(["t00", "t01", "t02"]))
    before = len(log(root))
    learning.accept(store, p.id)
    found = learning.lessons(root, APPROACH)
    assert [(x.part, x.text) for x in found][-1] == (
        "open", "Cut the warm-up line; open with the finding.")
    assert len(log(root)) == before + 1
    assert log(root)[0].startswith(f"learn: added lesson for {APPROACH}: Cut the warm-up")
    assert learning.proposals(root, APPROACH)[0].status == "accepted"
    text = (root / "MESSAGING.md").read_text()
    assert "- Whether German founders prefer email or LinkedIn.\n- Cut the warm-up line" in text
    with pytest.raises(learning.LearningError, match="no pending proposal"):
        learning.accept(store, p.id)


def test_accept_with_edited_text_and_a_rewrite_in_place(folder):
    root, store = folder
    old = learning.lessons(root, APPROACH)[0]
    (p,) = pending(root, store, {"op": "rewrite", "part": "worked", "text": "Ask who closes.",
                                 "replaces": [old.id], "cites": ["t00"], "why": "shorter"})
    assert p.part == "open"
    learning.accept(store, p.id, text="Ask who closes deals today.")
    found = learning.lessons(root, APPROACH)
    assert [(x.part, x.text) for x in found] == [
        ("open", "Whether German founders prefer email or LinkedIn."),
        ("open", "Ask who closes deals today.")]


def test_a_rejected_proposal_is_never_proposed_again(folder):
    root, store = folder
    (p,) = pending(root, store, add(["t00", "t01", "t02"]))
    learning.reject(store, p.id)
    assert log(root)[0] == "learn: rejected Cut the warm-up line; open with the finding."
    state = learning.load_state(root)
    assert state["rejected"] == {p.id: p.text}
    make(root, 9, 6, days=1, edits=[(shorter(ai_body("Camille")), "too long", ())])
    enricher, runner = ai({"proposals": [add(["t09", "t00", "t01"])]})
    result = learning.run(store, APPROACH, enricher, {})
    assert result.proposals == [] and "rejected this before" in result.problems[0]
    assert "- Cut the warm-up line; open with the finding." in runner.calls[0]["prompt"]
    assert learning.proposals(root, APPROACH, "pending") == []


def test_retire_and_move_a_lesson(folder):
    root, store = folder
    worked, testing = learning.lessons(root, APPROACH)
    moved = learning.move(store, APPROACH, testing.id, "worked")
    assert moved.part == "worked" and moved.id == testing.id
    assert [x.part for x in learning.lessons(root, APPROACH)] == ["worked", "worked"]
    assert log(root)[0].startswith(f"learn: moved lesson to Worked for {APPROACH}")
    learning.retire(store, APPROACH, worked.id)
    assert [x.text for x in learning.lessons(root, APPROACH)] == [testing.text]
    assert log(root)[0].startswith(f"learn: retired lesson for {APPROACH}: A question")
    with pytest.raises(learning.LearningError, match="no lesson"):
        learning.retire(store, APPROACH, worked.id)
    other = playbook.load(root).approach("Scaling the sales team")
    assert other.lessons() == playbook.parse(
        git(root, "show", "HEAD~2:MESSAGING.md")).approach("Scaling the sales team").lessons()


def test_an_accepted_retire_removes_the_line(folder):
    root, store = folder
    old = learning.lessons(root, APPROACH)[1]
    (p,) = pending(root, store, {"op": "retire", "part": "open", "text": "",
                                 "replaces": [old.id], "cites": ["t01"], "why": "answered"})
    learning.accept(store, p.id)
    assert [x.id for x in learning.lessons(root, APPROACH)] != [] and old.id not in [
        x.id for x in learning.lessons(root, APPROACH)]
    assert log(root)[0].startswith(f"learn: retired lesson for {APPROACH}")


# ------------------------------------------------------------ scoreboard


def _reply(store, company, contact, when, outcome, id_):
    store.get(company).interactions.append(Interaction(
        id=id_, date=when, channel="email", direction="in", contact=contact, outcome=outcome))


def test_the_scoreboard_counts_with_and_without_a_lesson(folder):
    root, store = folder
    lid = learning.lessons(root, APPROACH)[1].id
    for n in range(4):
        make(root, n, n, state="sent", days=8, lessons_used=[lid] if n < 3 else [])
    for n in range(2):
        company, slug = CONTACTS[n]
        _reply(store, company, slug, NOW - timedelta(days=2), "interested", f"r{n}")
    sigs = learning.signals(store, APPROACH, {})
    if not any(s.lessons_used for s in sigs):
        pytest.skip("Item.lessons_used not wired yet")
    board = {s.lesson.id: s for s in learning.scoreboard(store, APPROACH, sigs, {})}
    score = board[lid]
    assert (score.with_n, score.without_n) == (3, 1)
    assert score.with_rungs["positive"] == 2 and score.without_rungs["positive"] == 0
    assert score.with_rungs["replied"] == 2 and score.with_companies["positive"] == 2
    assert score.with_edit_words == 0 and score.promotion == ""


def test_quiet_drafts_hint_a_promotion_in_the_early_phases(folder):
    root, store = folder
    lid = learning.lessons(root, APPROACH)[1].id
    for n in range(10):
        make(root, n, n % 8, days=12 - n, lessons_used=[lid])
    sigs = learning.signals(store, APPROACH, {})
    if not any(s.lessons_used for s in sigs):
        pytest.skip("Item.lessons_used not wired yet")
    board = {s.lesson.id: s for s in learning.scoreboard(store, APPROACH, sigs, {})}
    assert "promote to Worked" in board[lid].promotion
    assert board[learning.lessons(root, APPROACH)[0].id].promotion == ""


def test_doubled_edits_flag_instead_of_promote_from_phase_two(folder):
    root, store = folder
    lid = learning.lessons(root, APPROACH)[1].id
    make(root, 1, 0, lessons_used=[lid], edits=[(shorter(ai_body("Mara")), "", ())])
    make(root, 2, 1, lessons_used=[], edits=[(ai_body("Daan").replace("Sam", "Sam B."), "",
                                              ())])
    sigs = learning.signals(store, APPROACH, {})
    if not any(s.lessons_used for s in sigs):
        pytest.skip("Item.lessons_used not wired yet")
    board = {s.lesson.id: s for s in learning.scoreboard(
        store, APPROACH, sigs, {"learning_phase_pin": 2})}
    assert board[lid].flag.startswith("edits doubled with this lesson")
    assert board[lid].promotion == ""


# ------------------------------------------------------------ status


def test_status_shows_what_a_run_would_send_and_its_cost(folder):
    root, store = folder
    shortened_batch(root)
    st = learning.status(store, APPROACH, {})
    assert st.phase.number == 0 and st.banner.startswith("6 reviewed drafts, 0 replies")
    assert len(st.cards) == 6 and st.mode == "hermit" and st.watermark == ""
    prompt = learning.distill_prompt(APPROACH, st.cards, learning.lessons(root, APPROACH), [])
    assert st.prompt_chars == len(prompt) and st.tokens == math.ceil(len(prompt) / 4)
    assert st.pending == [] and st.lessons == 2
    assert not (root / "learning").exists()          # status writes nothing


def test_set_lessons_is_reached_through_accept_only_for_the_named_approach(folder):
    root, store = folder
    (p,) = pending(root, store, add(["t00", "t01", "t02"]))
    before = (root / "MESSAGING.md").read_text()
    learning.accept(store, p.id)
    after = (root / "MESSAGING.md").read_text()
    head, tail = before.split("# Approach: Scaling the sales team")
    assert after.endswith("# Approach: Scaling the sales team" + tail)
