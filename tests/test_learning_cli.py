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

"""`hermitcrm learn ...` and `outreach ready --tag`: the CLI over learning.py.
The AI is a fake returning canned JSON; every name is made up."""

from __future__ import annotations

import json

import pytest

from hermitcrm import cli, learning, outreach
from hermitcrm.enrich import Enricher
from outreach_fakes import ALL
from test_learning import APPROACH, CONTACTS, FIRSTS, ai_body, folder, make, shorter  # noqa: F401
from test_learning_writes import add, ai, shortened_batch


def learn(store, root, *argv, enricher=None, config=None):
    args = cli._build_parser().parse_args(["learn", *argv])
    return cli.cmd_learn(store, root, config if config is not None else {}, args,
                         enricher=enricher)


def one_proposal(root, store):
    shortened_batch(root)
    enricher, _ = ai({"proposals": [add(["t00", "t01", "t02"])]})
    text, code = learn(store, root, "run", enricher=enricher)
    assert code == 0, text
    return learning.proposals(root, APPROACH, "pending")[0]


def test_report_shows_banner_trend_patterns_rates_and_features(folder):
    root, store = folder
    shortened_batch(root)
    text, code = learn(store, root, "report")
    assert code == 0
    assert "reviewed drafts" in text and "phase" in text
    assert "Efficiency" in text and "shortened the text in 6 of 6" in text
    assert "Outcome rates" in text and "by angle:" in text and "nothing sent yet" in text
    assert "by framework:" in text
    assert "t00 " in text and "words -" in text


def test_report_on_an_unknown_approach_is_not_an_error_but_empty(folder):
    root, store = folder
    text, code = learn(store, root, "report", "--approach", "Nope")
    assert code == 0 and "no reviewed drafts yet" in text


def test_status_lists_cards_tokens_and_pending(folder):
    root, store = folder
    shortened_batch(root)
    text, code = learn(store, root, "status")
    assert code == 0
    assert "Cards a run would send: 6" in text and "tokens" in text
    assert "Pending proposals: 0" in text and "Distill mode: hermit" in text
    p = one_proposal(root, store)
    text, _ = learn(store, root, "status")
    assert p.id in text and "Pending proposals: 1" in text


def test_run_stores_proposals_and_points_to_accept(folder):
    root, store = folder
    shortened_batch(root)
    enricher, runner = ai({"proposals": [add(["t00", "t01", "t02"])]})
    text, code = learn(store, root, "run", enricher=enricher)
    assert code == 0 and "1 new proposal" in text and "learn accept" in text
    assert runner.calls
    again, code = learn(store, root, "run", enricher=enricher)
    assert code == 0 and again.startswith("Skipped")


def test_run_without_an_ai_is_an_error(folder):
    root, store = folder
    shortened_batch(root)
    dead = Enricher(provider="claude", which=lambda b: None)
    text, code = learn(store, root, "run", enricher=dead)
    assert code == 1 and text


def test_handoff_run_then_import(folder):
    root, store = folder
    shortened_batch(root)
    text, code = learn(store, root, "run", config={"learning_distill": "handoff"})
    assert code == 0
    assert "learning/evidence-pack.md" in text and "learn import" in text
    text, code = learn(store, root, "import")
    assert code == 1 and "no learning/proposals.json" in text
    (root / "learning" / "proposals.json").write_text(
        json.dumps({"proposals": [add(["t00", "t01", "t02"])]}))
    text, code = learn(store, root, "import")
    assert code == 0 and "1 new proposal imported" in text
    assert len(learning.proposals(root, APPROACH, "pending")) == 1


def test_accept_with_text_and_reject(folder):
    root, store = folder
    p = one_proposal(root, store)
    text, code = learn(store, root, "accept", p.id, "--text", "Open with the finding.")
    assert code == 0 and p.id in text
    assert learning.lessons(root, APPROACH)[-1].text == "Open with the finding."
    assert learn(store, root, "accept", p.id)[1] == 1
    text, code = learn(store, root, "accept", "nope")
    assert code == 1 and "no pending proposal" in text


def test_reject_a_proposal(folder):
    root, store = folder
    p = one_proposal(root, store)
    text, code = learn(store, root, "reject", p.id)
    assert code == 0 and "will not be proposed again" in text
    assert learn(store, root, "reject", p.id)[1] == 1


def test_retire_and_move_a_lesson(folder):
    root, store = folder
    worked, testing = learning.lessons(root, APPROACH)
    text, code = learn(store, root, "move", testing.id, "worked")
    assert code == 0 and "worked" in text
    assert [x.part for x in learning.lessons(root, APPROACH)] == ["worked", "worked"]
    text, code = learn(store, root, "retire", worked.id, "--approach", APPROACH)
    assert code == 0 and worked.id in text
    text, code = learn(store, root, "retire", worked.id)
    assert code == 1 and "no lesson" in text


def test_suggest_and_apply(folder):
    root, store = folder
    shortened_batch(root)
    text, code = learn(store, root, "suggest")
    assert code == 0 and "body_max_words" in text
    sid = text.splitlines()[0].split(":")[0]
    text, code = learn(store, root, "apply", sid)
    assert code == 0 and sid in text
    text, code = learn(store, root, "apply", "nope")
    assert code == 1 and "no suggestion" in text


def test_suggest_with_nothing_to_say(folder):
    root, store = folder
    text, code = learn(store, root, "suggest")
    assert code == 0 and "No suggestions" in text


def test_outreach_ready_takes_repeatable_tags(folder):
    root, store = folder
    make(root, 0, 0, state="drafted")
    parser = cli._build_parser()
    args = parser.parse_args(["outreach", "ready", "t00", "--tag", "too-long", "--tag", "cliche"])
    assert args.tag == ["too-long", "cliche"]
    seen = {}
    real = outreach.mark_ready

    def spy(store_, item_id, **kw):
        seen.update(kw)
        return real(store_, item_id, **kw)

    outreach.mark_ready = spy
    try:
        text, code = cli.cmd_outreach(store, root, {}, args)
    finally:
        outreach.mark_ready = real
    assert code == 0, text
    assert seen["tags"] == ["too-long", "cliche"]


def test_outreach_ready_refuses_an_unknown_tag(folder, capsys):
    with pytest.raises(SystemExit):
        cli._build_parser().parse_args(["outreach", "ready", "t00", "--tag", "bogus"])
