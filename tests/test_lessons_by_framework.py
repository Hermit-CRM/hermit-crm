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

"""Lessons always reach the drafter, and can be tied to one outreach framework
(`learning_lessons` = approach | framework | both). Fictional names only."""

from hermitcrm import learning, playbook
from hermitcrm.learning import Card, Lesson

PLAYBOOK = """# Messaging playbook

General notes for every approach.

# Approach: Founder coaching

## Offer

Coaching for first-time founders.

## Worked examples

{filler}

## Lessons

<!-- what you learned -->

### Worked

- Ask about the team.
- [gap-question] Lead with the gap, never with the product.

### Didn't work

- [trigger-led] Opening with funding news.

### Still testing

- Short subjects.
"""


def body(filler: str = "Example text.") -> str:
    return playbook.body_for_ai(PLAYBOOK.format(filler=filler), "Founder coaching")


# --------------------------------------------------------- never cut off


def test_a_short_playbook_is_unchanged():
    text = body()
    assert playbook.fit_for_prompt(text, 12000) == text.strip()


def test_a_long_playbook_keeps_its_lessons_and_cuts_the_rest():
    text = body("Long worked example. " * 1500)          # ~31,500 characters
    assert text.find("## Lessons") > 12000               # a plain cut would drop them
    fitted = playbook.fit_for_prompt(text, 12000)
    assert len(fitted) <= 12000
    assert fitted.startswith("# Messaging playbook")
    assert "## Lessons" in fitted and "- Short subjects." in fitted
    assert "<!-- what you learned -->" not in fitted      # comments go to save room
    assert "[...]" in fitted
    # lessons_used is read from the prompt text, so it now names what was shown
    assert len(learning.lesson_ids(fitted)) == 4


def test_lessons_longer_than_the_limit_are_cut_last():
    fitted = playbook.fit_for_prompt(body("x " * 100), 60)
    assert fitted.startswith("## Lessons") and len(fitted) == 60


# ------------------------------------------------------ framework filter


def test_a_framework_sees_its_own_and_the_untagged_lessons():
    shown = playbook.filter_lessons(body(), "gap-question")
    assert "[gap-question] Lead with the gap" in shown
    assert "[trigger-led]" not in shown
    assert "- Ask about the team." in shown and "- Short subjects." in shown


def test_a_draft_without_framework_sees_only_untagged_lessons():
    shown = playbook.filter_lessons(body(), "")
    assert "[gap-question]" not in shown and "[trigger-led]" not in shown
    assert "- Ask about the team." in shown


def test_none_keeps_every_line_and_text_outside_lessons_is_untouched():
    text = body("- [trigger-led] an example bullet outside Lessons")
    assert playbook.filter_lessons(text, None) == text
    assert "- [trigger-led] an example bullet outside Lessons" in \
        playbook.filter_lessons(text, "gap-question")


def test_lesson_framework_reads_the_tag():
    assert playbook.lesson_framework("- [gap-question] Lead with the gap.") == "gap-question"
    assert playbook.lesson_framework("Lead with the gap.") == ""
    assert Lesson("L1", "open", "[house] Short.").framework == "house"


# ---------------------------------------------------------- validation

GAP = [Card(id=f"g{n}", contact=f"co{n}/p{n}", framework="gap-question") for n in range(3)]
HOUSE = [Card(id=f"h{n}", contact=f"hq{n}/p{n}", framework="house") for n in range(3)]
LESSONS = [Lesson(learning.lesson_id("Ask about the team."), "worked", "Ask about the team.")]


def prop(cites, **kw):
    base = {"op": "add", "part": "open", "text": "Name the gap in the first line.",
            "replaces": [], "cites": cites, "why": "seen thrice"}
    base.update(kw)
    return base


def check(*props, scope="framework", lessons=LESSONS, rejected=()):
    return learning.validate_proposals({"proposals": list(props)}, GAP + HOUSE, lessons,
                                       rejected, "Founder coaching", scope)


def test_framework_scope_tags_the_lesson_with_the_cards_framework():
    kept, problems = check(prop(["g0", "g1", "g2"]))
    assert problems == []
    assert kept[0].text == "[gap-question] Name the gap in the first line."


def test_framework_scope_refuses_a_lesson_across_frameworks():
    kept, problems = check(prop(["g0", "g1", "h0"]))
    assert kept == [] and "says which framework" in problems[0]


def test_a_framework_lesson_cites_only_its_own_cards():
    kept, problems = check(prop(["g0", "g1", "h0"], framework="gap-question"), scope="both")
    assert kept == [] and "cites only gap-question cards" in problems[0]


def test_both_scope_allows_a_lesson_for_every_framework():
    kept, problems = check(prop(["g0", "g1", "h0"]), scope="both")
    assert problems == [] and kept[0].text == "Name the gap in the first line."


def test_approach_scope_ignores_the_framework_field():
    kept, problems = check(prop(["g0", "g1", "g2"], framework="gap-question"),
                           scope="approach")
    assert problems == [] and kept[0].text == "Name the gap in the first line."


def test_a_tag_the_ai_wrote_in_the_text_is_kept_once():
    kept, _ = check(prop(["g0", "g1", "g2"], text="[gap-question] Name the gap first."))
    assert kept[0].text == "[gap-question] Name the gap first."


def test_a_rejected_framework_lesson_stays_rejected():
    kept, problems = check(prop(["g0", "g1", "g2"]),
                           rejected=["[gap-question] Name the gap in the first line."])
    assert kept == [] and "rejected this before" in problems[0]


def test_the_cap_counts_per_framework():
    full = [Lesson(learning.lesson_id(f"Untagged {n}."), "open", f"Untagged {n}.")
            for n in range(learning.LESSON_CAP)]
    kept, problems = check(prop(["g0", "g1", "g2"]), lessons=full)
    assert problems == [] and len(kept) == 1          # the untagged 12 do not block it
    kept, problems = check(prop(["g0", "g1", "h0"]), lessons=full, scope="both")
    assert kept == [] and "12 lessons already" in problems[0]


def test_the_prompt_explains_frameworks_only_when_asked():
    plain = learning.distill_prompt("Founder coaching", GAP, LESSONS)
    assert "framework" not in plain.split("--- current lessons ---")[0]
    both = learning.distill_prompt("Founder coaching", GAP, LESSONS, lesson_scope="both")
    assert "holds for every framework" in both


def test_scope_reads_the_setting():
    assert learning.scope({}) == "approach"
    assert learning.scope({"learning_lessons": "Both"}) == "both"
    assert learning.scope({"learning_lessons": "nonsense"}) == "approach"
