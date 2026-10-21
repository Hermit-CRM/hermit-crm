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

"""The outreach frameworks library: the shipped file, frameworks.toml and `check`."""

from __future__ import annotations

import pytest

from hermitcrm import cli, frameworks, outreach
from hermitcrm.datafolder import init_folder


ORDER = ["house", "trigger-tension-trust", "truth-think-proof-talk", "premise-body-ask",
         "problem-solution-question", "attention-interest-desire-action",
         "connection-problem-objection", "pain-proof-yes-no"]
BRANDS = ("triple t", "4t", "3x3", "smykm", "show me you know me", "poke the bear", "jm spear")


def test_the_shipped_library_loads_in_library_order():
    lib = frameworks.load()
    assert lib.problems == [] and lib.hints == [] and lib.ids == ORDER


@pytest.mark.parametrize("fid, cta, words, proof, offer, research, needs, questions", [
    ("house", "situation-question", None, "optional", "required", "trigger", (), (1, 1)),
    ("problem-solution-question", "interest-question", 70, "required", "optional", "trigger", (), (1, 1)),
    ("attention-interest-desire-action", "small-step-question", 90, "optional", "optional", "trigger", (), (1, 1)),
    ("truth-think-proof-talk", "easy-no", 80, "required", "never", "trigger", (), (1, 1)),
    ("trigger-tension-trust", "situation-question", 60, "required", "never", "trigger", (), (1, 1)),
    ("premise-body-ask", "easy-no", 80, "optional", "optional", "individual", ("premise",), (1, 1)),
    ("connection-problem-objection", "reply-invite", None, "optional", "never", "individual",
     ("personal-connection",), (0, 1)),
    ("pain-proof-yes-no", "yes-no", 45, "required", "never", "trigger", (), (1, 1)),
])
def test_each_shipped_framework_matches_the_design_table(fid, cta, words, proof, offer,
                                                          research, needs, questions):
    fw = frameworks.load().get(fid)
    assert (fw.cta, fw.max_words, fw.proof, fw.offer_line, fw.research, fw.needs,
            fw.questions) == (cta, words, proof, offer, research, needs, questions)
    assert 0 < len(fw.instructions) <= frameworks.INSTRUCTIONS_MAX


def test_house_is_todays_first_touch_recipe_word_for_word():
    house = frameworks.load().house
    assert house.instructions == outreach.SHAPES[outreach.FIRST_TOUCH]
    assert house.steps == ("Finding", "Offer", "Question") and house.after == ""


def test_no_method_brand_anywhere_in_the_library():
    assert not [b for b in BRANDS if b in frameworks.default_text().lower()]
    for fw in frameworks.load().frameworks.values():
        words = f"{fw.id.replace('-', ' ')} {fw.name.lower()}"
        assert "spear" not in words and "show you know" not in words


def test_a_folder_file_overrides_one_key_and_adds_a_framework(tmp_path):
    (tmp_path / "frameworks.toml").write_text(
        '[frameworks.trigger-tension-trust]\nmax_words = 50\n\n'
        '[frameworks.open-gap-question]\nname = "Open, gap, question"\n'
        'steps = ["Open", "Gap", "Question"]\n'
        'instructions = "Open with them. Name the gap. Ask one small question."\n',
        encoding="utf-8")
    lib = frameworks.load(tmp_path)
    assert lib.problems == [] and lib.ids == ORDER + ["open-gap-question"]
    ttt = lib.get("trigger-tension-trust")
    assert ttt.max_words == 50 and ttt.name == "Trigger, tension, trust"
    added = lib.get("open-gap-question")
    assert (added.cta, added.questions, added.proof, added.after) == (
        "situation-question", (1, 1), "optional", "")


GOOD = '[frameworks.x]\nname = "X"\nsteps = ["A"]\ninstructions = "Do it."\n'


@pytest.mark.parametrize("extra, expected", [
    ('cta = "meeting-ask"\n', "frameworks.toml: x.cta: unknown call to action 'meeting-ask'"),
    ('max_words = "sixty"\n', "frameworks.toml: x.max_words:"),
    ("questions = [1, 2]\n", "frameworks.toml: x.questions: [min, max] with max 1"),
    ('needs = ["budget"]\n', "frameworks.toml: x.needs: unknown need 'budget'"),
    ('proof = "always"\n', "frameworks.toml: x.proof:"),
])
def test_a_wrong_value_is_a_problem_and_the_framework_is_left_out(tmp_path, extra, expected):
    (tmp_path / "frameworks.toml").write_text(GOOD + extra, encoding="utf-8")
    lib = frameworks.load(tmp_path)
    assert any(p.startswith(expected) for p in lib.problems), lib.problems
    assert "x" not in lib.ids


def test_missing_keys_long_instructions_and_bad_ids(tmp_path):
    (tmp_path / "frameworks.toml").write_text(
        '[frameworks.x]\nsteps = ["A"]\ninstructions = "' + "a" * 901 + '"\n\n'
        '[frameworks."Bad Id"]\nname = "B"\nsteps = ["A"]\ninstructions = "Do it."\n',
        encoding="utf-8")
    problems = frameworks.load(tmp_path).problems
    assert "frameworks.toml: x.name: missing" in problems
    assert "frameworks.toml: x.instructions: at most 900 characters (901)" in problems
    assert "frameworks.toml: Bad Id: an id is lower case letters, digits and hyphens" in problems


def test_an_unknown_key_is_a_hint_not_a_problem(tmp_path):
    (tmp_path / "frameworks.toml").write_text('[frameworks.house]\ntone = "warm"\n',
                                             encoding="utf-8")
    lib = frameworks.load(tmp_path)
    assert lib.problems == [] and lib.hints[0].startswith(
        "frameworks.toml: house.tone: not a framework key (known: name, after, ")


def test_a_file_that_is_not_toml_leaves_the_shipped_library(tmp_path):
    (tmp_path / "frameworks.toml").write_text("[frameworks.house\n", encoding="utf-8")
    lib = frameworks.load(tmp_path)
    assert lib.ids == ORDER and lib.problems[0].startswith("frameworks.toml: not valid TOML")


def test_a_broken_house_keeps_the_shipped_one(tmp_path):
    (tmp_path / "frameworks.toml").write_text("[frameworks.house]\nquestions = [2, 2]\n",
                                             encoding="utf-8")
    lib = frameworks.load(tmp_path)
    assert lib.house == frameworks.load().house and lib.problems


def test_resolve_takes_the_override_then_the_default_then_house():
    lib = frameworks.load()
    assert frameworks.resolve(lib) == (lib.house, "")
    assert frameworks.resolve(lib, "trigger-tension-trust")[0].id == "trigger-tension-trust"
    assert frameworks.resolve(lib, "trigger-tension-trust", "pain-proof-yes-no")[0].id == \
        "pain-proof-yes-no"
    assert frameworks.resolve(lib, "gone") == (
        lib.house, "framework gone is not in the library; drafted with house")
    with pytest.raises(ValueError, match=r"unknown framework 'gone' \(known: house, "):
        frameworks.resolve(lib, "", "gone")


def test_hermitcrm_check_reports_frameworks_toml(tmp_path, capsys):
    root = init_folder(tmp_path / "x", demo=True)
    (root / "frameworks.toml").write_text('[frameworks.house]\ntone = "warm"\n', encoding="utf-8")
    assert cli.main(["check"], root=root) == 0
    assert "frameworks.toml: house.tone: not a framework key" in capsys.readouterr().out
    (root / "frameworks.toml").write_text('[frameworks.house]\ncta = "meeting-ask"\n',
                                          encoding="utf-8")
    assert cli.main(["check"], root=root) == 1
    assert "frameworks.toml: house.cta: unknown call to action" in capsys.readouterr().out


def test_every_error_of_one_framework_is_reported(tmp_path):
    (tmp_path / "frameworks.toml").write_text(
        '[frameworks.x]\ncta = "no"\nproof = "no"\nresearch = "no"\n', encoding="utf-8")
    problems = frameworks.load(tmp_path).problems
    assert [p.split(": ")[1] for p in problems] == [
        "x.name", "x.steps", "x.instructions", "x.cta", "x.proof", "x.research"]


def test_a_top_level_key_other_than_frameworks_is_a_hint(tmp_path):
    (tmp_path / "frameworks.toml").write_text('extra = 1\n[frameworks.house]\nmax_words = 50\n',
                                             encoding="utf-8")
    lib = frameworks.load(tmp_path)
    assert lib.problems == [] and lib.hints == [
        "frameworks.toml: extra: not read (the file holds [frameworks.<id>] tables)"]
    assert lib.house.max_words == 50


def test_a_frameworks_key_that_is_not_a_table_leaves_the_shipped_library(tmp_path):
    (tmp_path / "frameworks.toml").write_text("frameworks = 3\n", encoding="utf-8")
    lib = frameworks.load(tmp_path)
    assert lib.ids == ORDER and lib.problems == [
        "frameworks.toml: frameworks: must be a table of [frameworks.<id>] tables"]
