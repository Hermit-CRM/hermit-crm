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

"""The outreach frameworks: how a first-touch message is built.

A framework is a recipe for the message: its parts (`steps`), the words the
draft prompt gets (`instructions`), and limits Python checks (`max_words`,
`cta`, `questions`, `proof`, `offer_line`, `needs`, `research`). The library is
`default_frameworks.toml` in the package, deep-merged with an optional
`frameworks.toml` in the data folder: one key overrides one key, and a new
`[frameworks.<id>]` table adds a framework. `house` is today's first-touch
recipe and is always there.

A framework with an error is left out of the library (the error goes to
`hermitcrm check` and the hub's banner); an unknown key is only a hint.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from hermitcrm.messaging import deep_merge

FILENAME = "frameworks.toml"
HOUSE = "house"
ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CTAS = ("situation-question", "interest-question", "small-step-question", "easy-no",
        "yes-no", "reply-invite")
LEVELS = ("required", "optional", "never")          # proof and offer_line
RESEARCH = ("none", "trigger", "individual")
NEEDS = {"premise": "a premise (something they wrote, said or shared)",
         "personal-connection": "a personal connection"}
ANSWERS = {"deal": ("small", "mid", "large", "xl"), "buyer": ("exec", "lead", "staff"),
           "volume": ("low", "mid", "high"), "research": ("minute", "five", "fifteen"),
           "tone": ("plain", "warm", "blunt")}
KEYS = ("name", "after", "summary", "steps", "max_words", "cta", "questions", "proof",
        "offer_line", "needs", "research", "best_for", "watch_out", "evidence",
        "instructions", "example", "fits")
INSTRUCTIONS_MAX = 900
_TEXT_KEYS = ("after", "summary", "best_for", "watch_out", "evidence", "example")


@dataclass(frozen=True)
class Framework:
    id: str
    name: str
    steps: tuple[str, ...]
    instructions: str
    max_words: int | None = None          # None = the channel's limit
    cta: str = "situation-question"
    questions: tuple[int, int] = (1, 1)
    proof: str = "optional"
    offer_line: str = "optional"
    needs: tuple[str, ...] = ()
    research: str = "trigger"
    after: str = ""
    summary: str = ""
    best_for: str = ""
    watch_out: str = ""
    evidence: str = ""
    example: str = ""


@dataclass
class Library:
    frameworks: dict[str, Framework]      # shipped file order, then the folder's additions
    problems: list[str] = field(default_factory=list)   # errors
    hints: list[str] = field(default_factory=list)      # unknown keys

    def get(self, fid: str) -> Framework | None:
        return self.frameworks.get(fid)

    @property
    def ids(self) -> list[str]:
        return list(self.frameworks)

    @property
    def house(self) -> Framework:
        return self.frameworks[HOUSE]


def default_text() -> str:
    return resources.files("hermitcrm").joinpath("default_frameworks.toml").read_text(
        encoding="utf-8")


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def from_table(fid: str, table) -> tuple[Framework | None, list[str], list[str]]:
    """(framework, errors, hints) for one `[frameworks.<id>]` table. Every error is
    reported, not only the first; with any error there is no framework."""
    if not isinstance(table, dict):
        return None, [f"{FILENAME}: {fid}: a framework is a table of keys"], []
    errors: list[str] = []
    hints = [f"{FILENAME}: {fid}.{key}: not a framework key (known: {', '.join(KEYS)})"
             for key in table if key not in KEYS]

    def bad(key: str, what: str) -> None:
        errors.append(f"{FILENAME}: {fid}.{key}: {what}")

    def text(key: str, required: bool = False) -> str:
        value = table.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                bad(key, "missing")
            return ""
        if not isinstance(value, str):
            bad(key, "must be text")
            return ""
        return value

    def choice(key: str, known: tuple[str, ...], default: str, what: str) -> str:
        value = table.get(key, default)
        if not isinstance(value, str) or value not in known:
            bad(key, f"unknown {what} '{value}' (known: {', '.join(known)})")
            return default
        return value

    if not ID.fullmatch(fid):
        errors.append(f"{FILENAME}: {fid}: an id is lower case letters, digits and hyphens")
    name = text("name", required=True)
    steps = table.get("steps")
    if not steps:
        bad("steps", "missing")
    elif not isinstance(steps, list) or not all(isinstance(s, str) and s.strip() for s in steps):
        bad("steps", "must be a list of text, one entry per step")
    instructions = text("instructions", required=True)
    if len(instructions) > INSTRUCTIONS_MAX:
        bad("instructions", f"at most {INSTRUCTIONS_MAX} characters ({len(instructions)})")
    max_words = table.get("max_words")
    if "max_words" in table and (not _whole(max_words) or max_words < 1):
        bad("max_words", "a whole number above 0")
        max_words = None
    questions = table.get("questions", [1, 1])
    if not (isinstance(questions, list) and len(questions) == 2
            and all(_whole(q) for q in questions) and questions in ([0, 1], [1, 1])):
        bad("questions", "[min, max] with max 1 (Hermit asks at most one question)")
        questions = [1, 1]
    cta = choice("cta", CTAS, "situation-question", "call to action")
    proof = choice("proof", LEVELS, "optional", "level")
    offer_line = choice("offer_line", LEVELS, "optional", "level")
    research = choice("research", RESEARCH, "trigger", "research depth")
    needs = table.get("needs", [])
    if not isinstance(needs, list):
        bad("needs", f"a list of needs (known: {', '.join(NEEDS)})")
        needs = []
    for need in needs:
        if not isinstance(need, str) or need not in NEEDS:
            bad("needs", f"unknown need '{need}'")
    texts = {key: text(key) for key in _TEXT_KEYS}
    if "fits" in table and not isinstance(table["fits"], dict):
        bad("fits", "must be a table")
    if errors:
        return None, errors, hints
    return Framework(
        id=fid, name=name, steps=tuple(steps), instructions=instructions,
        max_words=max_words, cta=cta, questions=(questions[0], questions[1]), proof=proof,
        offer_line=offer_line, needs=tuple(needs), research=research, **texts), errors, hints


def load(root: Path | str | None = None) -> Library:
    """The shipped library, with `<root>/frameworks.toml` merged over it."""
    shipped = tomllib.loads(default_text())["frameworks"]
    problems: list[str] = []
    hints: list[str] = []
    merged = shipped
    path = Path(root) / FILENAME if root is not None else None
    if path is not None and path.is_file():
        mine = None
        try:
            mine = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            problems.append(f"{FILENAME}: not valid TOML ({exc})")
        except OSError as exc:
            problems.append(f"{FILENAME}: cannot be read ({exc})")
        if mine is not None:
            hints += [f"{FILENAME}: {key}: not read (the file holds [frameworks.<id>] tables)"
                      for key in mine if key != "frameworks"]
            if isinstance(mine.get("frameworks", {}), dict):
                merged = deep_merge(shipped, mine.get("frameworks", {}))
            else:
                problems.append(f"{FILENAME}: frameworks: must be a table of "
                                "[frameworks.<id>] tables")
    library: dict[str, Framework] = {}
    for fid, table in merged.items():
        framework, errors, unknown = from_table(fid, table)
        problems += errors
        hints += unknown
        if framework is not None:
            library[fid] = framework
    if HOUSE not in library:          # house is always there: the shipped one stands in
        library = {HOUSE: from_table(HOUSE, shipped[HOUSE])[0], **library}
    return Library(library, problems, hints)


def validate(root: Path | str) -> list[str]:
    return load(root).problems


def hints(root: Path | str) -> list[str]:
    return load(root).hints


def resolve(library: Library, default: str = "", override: str = "") -> tuple[Framework, str]:
    """(framework, note): the override if given, else the default, else house. A
    default that is no longer in the library falls back to house, and says so."""
    if override:
        framework = library.get(override)
        if framework is None:
            raise ValueError(f"unknown framework {override!r} "
                             f"(known: {', '.join(library.ids)})")
        return framework, ""
    if default:
        framework = library.get(default)
        if framework is not None:
            return framework, ""
        return library.house, f"framework {default} is not in the library; drafted with house"
    return library.house, ""
