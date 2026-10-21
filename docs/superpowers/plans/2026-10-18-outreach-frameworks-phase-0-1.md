# Outreach frameworks, phases 0 and 1: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the three quality fixes every draft gets (phase 0) and the framework library with its prompt, checks and recording (phase 1). When done, `hermitcrm outreach build --framework trigger-tension-trust` writes checked drafts with `framework` set, and a folder that never touches frameworks drafts exactly as it does after phase 0.

**Architecture:** A new `frameworks.py` owns the data: the shipped `default_frameworks.toml`, the data folder's `frameworks.toml` deep-merged over it, validation and resolution. `outreach.py` owns everything that turns a framework into prompt text and checks (`CheckContext.framework`, `framework_rules`, `framework_block`) and records the id on the item. The store copies the id onto the interaction when the message is logged, as it already does for `angle`. Learning, the Messages tab and export read the recorded id.

**Tech Stack:** Python 3.12, stdlib `tomllib`, PyYAML (already a dependency), FastAPI with Jinja templates, pytest.

**Spec:** `docs/superpowers/specs/2026-10-18-outreach-frameworks-design.md`. Phases 0 and 1 of section 10. Section 4 and the appendix hold the library, 4.6 the checks, 8 the recording.

## Before you start

- Work in the worktree `~/Code/HermitCRM-frameworks`: `git switch -c ai/outreach-frameworks spec/outreach-frameworks`. Never touch `~/Code/HermitCRM`. It is on `ai/learning-exemplars`, with uncommitted files of Gijs's.
- **Migration numbers (settled 21 Oct).** `origin/main` was merged into this branch on 21 Oct (commit `f92a511`). Main's migrations now run to 14, so this plan's are **15** (items) and **16** (interactions). Below, `N` is **15**, and the function is `m15_framework`.
- Main now also has, since the plan was first written:
  - exemplars and the angle policy (`AIDrafter._learned`, `exemplars_used`);
  - outreach notes: research findings become contact notes, and an item's `findings` are a snapshot of them (`notes.py`). A note you wrote becomes a finding with source `outreach.YOURS` and kind `person`;
  - sending (`send.py`, `sendqueue.py`, the item states `queued` and `failed`, the `SEND_KEYS`);
  - a `language` parameter on `AIDrafter.context`, `AIDrafter.draft` and `outreach.build`.

  The tasks below are written against that code.
- During a task, run only that task's tests: `.venv/bin/pytest -q -x tests/<file>`. Before every commit, run the full suite: `.venv/bin/pytest -q`. It takes about 7 minutes, so run it in the background.

## Global Constraints

- `.venv/bin/pytest` must pass before any commit.
- Commit messages start with `ai:` and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No new runtime dependencies.
- Never put real people, companies or email addresses in code, tests or docs; use fictional names and example.com / example.org. The one exception is the `after` credits; Task 4 writes it into `CLAUDE.md`.
- Front-matter key changes need a numbered migration in `migrations.py` (idempotent, front matter only) plus tests.
- Writes are deterministic and interaction bodies byte for byte. Every new key is written only when non-empty, so files without it keep their bytes.
- Copy (prompt text, UI text, docs) has no spaced em dashes and no "it's not X, it's Y" inversions.
- `house` is today's recipe. A folder with no `frameworks` key gets the phase-0 first-touch prompt text byte for byte.
- No framework may propose a time, ask for a meeting or a call, include a link, or invent familiarity. The time, link and calendar checks in `check_text` stay on for every framework. A framework asks at most one question.
- `after` and `example` never reach a prompt. These method names and brands appear nowhere in code, templates, prompts or the shipped TOML: "Triple T", "4T", "3x3", "SMYKM", "Show Me You Know Me", "Poke the Bear", "JM Spear". No id or `name` contains "spear" or "show you know".
- Frameworks shape first touches only. Reply-to-interest and follow-up items get no framework.

## Calls this plan makes (check while reviewing)

1. `parts` (the schema field and the card marks) moves to phase 2, together with the card that reads it. The design lists no item key for `parts`, so phase 2 adds one with its own migration.
2. Some keys are read only by people: `summary`, `best_for`, `watch_out`, `evidence`, `example`. The loader accepts them now, but the shipped file fills them in phase 2, with the popover and help page that show them. `fits` (the setup profiles) arrives in phase 4.
3. **The `needs` fallback lands now, not in phase 5.** If a framework's need is unmet, the item is drafted with the default framework (or `house`) and gets the flag from 6.2. Without this, choosing `connection-problem-objection` would draft without a connection. Phase 5 still adds the card's question and "Regenerate with X".
4. **Two migration entries, 15 (items) and 16 (interactions), share one function.** A `Migration` takes one glob. The design said one migration.
5. The validator caps `questions` at `[min, max]` with `max` = 1, so no user file can loosen Hermit's one-question rule.
6. The Messages tab's framework column is plain text, not an enum, so `message_columns` needs no library.
7. **The about-you count has three rules of its own.**
   - It counts plural first person (we, our, wir, wij, nous) as about the seller.
   - It is computed when the card is shown, not stored, so it follows edits and needs no key.
   - German formal Sie/Ihnen/Ihr... count only when capitalised and not first in a sentence.
8. Every non-house framework block ends with fixed rule lines: never open with "I", no meeting or link or time, the fallback with gaps, Voice wins, the question count, the offer and the proof. The appendix texts do not all repeat these, and today they come from the `SHAPES` paragraph that the block replaces.
9. `house` drafts use `house.instructions` from the merged library as the shape paragraph, so a user's override of `house` takes effect. A test pins the shipped text equal to `SHAPES[FIRST_TOUCH]`.
10. The critic's prompt does not change with the framework in phase 1.
11. Items record `framework: house` on every new first touch, so a later house-vs-framework test has its arm recorded. Items written before have no key and read as `""`.
12. `after` for the 3x3-derived framework is "30 Minutes to President's Club", the source as the research note names it.

## Review Focus

1. **A broken `frameworks.toml`** (invalid TOML, or one bad framework): the shipped library must keep working and `hermitcrm check` must say what is wrong. → Task 4.
2. **An approach naming a framework that no longer exists** (renamed or deleted in `frameworks.toml`): build and regenerate must draft with `house` and flag it, never crash. `check` must report it. → Tasks 5 and 8.
3. **A person edits a framework draft on the card:** Mark ready re-checks with the item's framework (60 words for trigger-tension-trust, not the channel's 120). An item whose framework has gone re-checks with house rules. → Task 8.
4. **Pronoun counting in German, French and unsupported languages:**
   - German formal Sie/Ihnen at a sentence start, and lowercase "ihnen" (them), are not miscounted;
   - French "je" is first person;
   - a language without word lists shows no line rather than "0, 0".
   → Task 3.
5. **Files from before this feature:**
   - items and interactions without `framework` keep their bytes through read, write and the migrations;
   - reply and follow-up items never get a framework, even when the approach has a default.
   → Tasks 8 and 9.

## File map

- **Create**
  - `src/hermitcrm/frameworks.py`: the library (load, merge, validate, resolve).
  - `src/hermitcrm/default_frameworks.toml`: the eight shipped frameworks.
  - `tests/test_frameworks.py`.
  - `tests/test_outreach_frameworks.py`: checks, prompt, build, recording.
  - `tests/test_outreach_about.py`: the about-you count.
- **Modify**
  - Code: `src/hermitcrm/outreach.py`, `playbook.py`, `models.py`, `store.py`, `migrations.py`, `learning.py`, `web.py`, `export.py`, `bulk.py`, `cli.py`, `adjust.py`.
  - Templates: `templates/outreach.html`, `templates/messages.html`, `templates/macros.html`.
  - Docs and rules: `CLAUDE.md`, `docs/ARCHITECTURE.md`, `help/outreach.md`, `help/playbook.md`, `help/data-format.md`, `help/cli.md`, `help/learning.md`.
  - Tests: `tests/outreach_fakes.py`, plus existing tests that pin key lists or format numbers.

New test files start with the Apache header that `tests/test_licensing.py` checks (copy it from `tests/test_angle.py`).

---

## Phase 0: better drafts for everyone

### Task 1: Proof in the message's language

**Files:**
- Modify: `src/hermitcrm/outreach.py`: the proof header in `draft_prompt` and the proof line of `SHAPES[REPLY]`.
- Test: `tests/test_outreach_draft.py`

**Interfaces:**
- Produces: the proof header text below, which `reply_draft` in `tests/outreach_fakes.py` keeps matching (its regex starts at "cite only these").

- [ ] **Step 1: Write the failing tests**

```python
PROOF = ("A made-up example: a 30-person software company doubled its qualified "
         "pipeline in two quarters.")


def test_the_prompt_asks_for_proof_in_the_message_language(folder):
    result, fake = built(folder, limit=1)
    prompt = fake.of("draft")[0]["prompt"]
    assert result.items[0].language == "de"
    assert ("--- proof (cite only these, word for word, in proof_used; in the message, say "
            "it in the message's language) ---") in prompt
    assert ("cite it word for word in proof_used; in the message, say it in the message's "
            "language") in outreach.SHAPES[outreach.REPLY]


def test_a_translated_proof_passes_when_proof_used_keeps_the_playbook_words():
    ctx = outreach.CheckContext(proof=[PROOF], rules={"subject_max": 60, "body_max_words": 120})
    data = {"subject": "Ihr zweites Büro", "angle": "hook", "pitch": "", "findings_used": [],
            "body": "Hallo Mara,\n\nDas zweite Büro ist mir aufgefallen. Ein Softwareunternehmen "
                    "mit 30 Leuten hat seine Pipeline in zwei Quartalen verdoppelt.\nWo hakt es "
                    "gerade am meisten?\n\nSam\n",
            "proof_used": [PROOF]}
    assert outreach.clean_answer(data, ctx).problems == []
```

- [ ] **Step 2: Run them**

Run: `.venv/bin/pytest -q tests/test_outreach_draft.py -k "proof_in_the_message or translated_proof"`

Expected: the first test FAILS (the old header). The second may already pass: it pins that the check does not change.

- [ ] **Step 3: Change the two strings in `outreach.py`**
  - In `draft_prompt`, the header becomes `"--- proof (cite only these, word for word, in proof_used; in the message, say it in the message's language) ---\n"`.
  - In `SHAPES[REPLY]`, `"(cite it word for word in proof_used)"` becomes `"(cite it word for word in proof_used; in the message, say it in the message's language)"`.

- [ ] **Step 4: Run `tests/test_outreach_draft.py tests/test_outreach_replies.py tests/test_draft_language.py`.** Expected: PASS.

- [ ] **Step 5: Run the full suite, then commit:** `ai: outreach: say the proof in the message's language`.

### Task 2: The deletion test in the critic's personal rubric

**Files:**
- Modify: `src/hermitcrm/outreach.py`: `CRITIC_PERSONAL[FIRST_TOUCH]`.
- Test: `tests/test_outreach_critic.py`

- [ ] **Step 1: Write the failing test**

```python
DELETION = ("Find the sentence that is about them. If it were removed, would the message "
            "still fit another company of the same kind? If so, score 2 or less.")


def test_the_deletion_test_is_in_the_first_touch_rubric_only():
    assert outreach.CRITIC_PERSONAL[outreach.FIRST_TOUCH].endswith(" " + DELETION)
    assert DELETION not in outreach.CRITIC_PERSONAL[outreach.REPLY]
    assert DELETION not in outreach.CRITIC_PERSONAL[outreach.FOLLOW_UP]
    assert DELETION in outreach.CRITIC_SCALE.format(
        personal=outreach.CRITIC_PERSONAL[outreach.FIRST_TOUCH])
```

Also add one assertion to an existing test in that file that builds a first touch with a critic: the recorded critic prompt (`fake.of("critic")[0]["prompt"]`) contains `DELETION`.

- [ ] **Step 2: Run it.** Expected: FAIL.

- [ ] **Step 3: Add the sentence to `CRITIC_PERSONAL[FIRST_TOUCH]`.** Append `" " + DELETION`, with the text exactly as in the test.

- [ ] **Step 4: Run `tests/test_outreach_critic.py`.** Expected: PASS.

- [ ] **Step 5: Run the full suite, then commit:** `ai: outreach critic: the deletion test for first touches`.

### Task 3: About you, about them

**Files:**
- Modify:
  - `src/hermitcrm/outreach.py`: `ABOUT_WORDS`, `about_counts`, `about_for_item`, and `render_item`.
  - `src/hermitcrm/web.py`: the Outreach page context.
  - `src/hermitcrm/templates/outreach.html`: the card.
  - `help/outreach.md`: one paragraph.
- Test: `tests/test_outreach_about.py` (new), plus one page test in `tests/test_outreach_page.py`.

**Interfaces:**
- Produces:
  - `outreach.ABOUT_WORDS: dict[str, tuple[frozenset[str], frozenset[str]]]`: language → (seller's words, their words), for `en`, `de`, `nl`, `fr`.
  - `outreach.about_counts(text: str, language: str) -> tuple[int, int] | None`: (about you, about them); `None` for a language without lists.
  - `outreach.about_for_item(root, item: Item) -> tuple[int, int] | None`: the body without the opt-out line, plus the pitch.

The word lists, all lower case:

| lang | about you (the seller) | about them |
|---|---|---|
| en | i, i'm, i've, i'd, i'll, me, my, mine, myself, we, we're, we've, we'd, we'll, us, our, ours | you, you're, you've, you'd, you'll, your, yours, yourself, yourselves |
| de | ich, mich, mir, mein, meine, meinen, meinem, meiner, meines, wir, uns, unser, unsere, unseren, unserem, unserer, unseres | du, dich, dir, dein, deine, deinen, deinem, deiner, deines, euch, euer, eure, euren, eurem, eurer, eures |
| nl | ik, me, mij, mijn, wij, we, ons, onze | je, jij, jou, jouw, jullie, u, uw |
| fr | je, j', me, m', moi, mon, ma, mes, nous, notre, nos | tu, te, t', toi, ton, ta, tes, vous, votre, vos |

**Counting rules.**
- Replace `’` with `'`.
- Tokens are `re.findall(r"[^\W\d_]+(?:'[^\W\d_]*)?", text)`, compared lower case.
- A token counts if it is in a list. A token with an apostrophe also counts if the part up to and including its first `'` is in a list (`j'aide` counts as `j'`).
- German formal: `Sie`, `Ihnen`, `Ihr`, `Ihre`, `Ihren`, `Ihrem`, `Ihrer`, `Ihres` count as about them only when written with a capital letter and not first in a sentence. A sentence starts at the start of the text, after a newline, or after `.`, `!`, `?` or `:` plus white space.

- [ ] **Step 1: Write the failing tests** (in `tests/test_outreach_about.py`)

```python
@pytest.mark.parametrize("language, text, counts", [
    ("en", "Hi Mara,\n\nYour second office caught my eye. We help founders like you build a "
           "team. Is hiring on your radar?\n\nSam", (2, 3)),
    ("de", "Hallo Mara,\n\nDein zweites Büro ist mir aufgefallen. Wir helfen Gründern wie dir. "
           "Ist das gerade dein Thema?\n\nSam", (2, 3)),
    ("de", "Guten Tag Frau Weber,\n\nwie geht es Ihnen mit Ihrem neuen Team? Sie wissen, wie "
           "das ist. Ich helfe ihnen gern.\n\nSam", (1, 2)),
    ("nl", "Hoi Daan,\n\nJe tweede kantoor viel me op. Wij helpen oprichters zoals jij. Is "
           "werven nu jouw prioriteit?\n\nSam", (2, 3)),
    ("fr", "Bonjour Claire,\n\nJe vois que vous ouvrez un bureau. J'aide des fondateurs comme "
           "vous. Votre équipe recrute-t-elle ?\n\nSam", (2, 3)),
])
def test_about_you_and_about_them_per_language(language, text, counts):
    assert outreach.about_counts(text, language) == counts


def test_a_language_without_word_lists_has_no_count():
    assert outreach.about_counts("Hola Marta, ¿te interesa?", "es") is None
```

Then two more:
- **`about_for_item`.** In a demo folder whose playbook has an English `opt_out` (set up as `test_1_the_opt_out_line_is_optional_and_set_in_the_playbook` in `test_outreach_draft.py` does), the count for an item equals the count for the same body without the opt-out line.
- **The card.** In `tests/test_outreach_page.py`:
  - a drafted English item whose body is "Hi Alex,\n\nWe help teams. Our clients grow. I can show you?\n\nSam" shows `About you 3, about them 1: more about you than about them`;
  - an item whose body is "Hi Alex,\n\nYour team grew. We see you hiring. Is your pipeline ready?\n\nSam" shows `About you 1, about them 3` with no warning.

- [ ] **Step 2: Run them.** Expected: FAIL (`about_counts` is not defined).

- [ ] **Step 3: Implement `ABOUT_WORDS`, `about_counts` and `about_for_item` in `outreach.py`.** `about_for_item` gets the opt-out line from `opt_out_line(root, item.kind, item.channel, item.language or "en", channel_rules(item.channel, messaging.load_messages(root)))`.

- [ ] **Step 4: Show the count.**
  - **Card** (`outreach.html`): next to both critic lines, the drafted form and the ready card. The line is `<p class="small">About you {a}, about them {t}</p>`. When `a > t`, add the class `warning` and append `: more about you than about them`. Nothing is shown when the count is `None`.
  - **`outreach_page`** (`web.py`): pass `about = {i.id: outreach.about_for_item(root, i) for i in <the items the page shows>}`.
  - **`render_item`:** add the same line after "Proof cited". In `help/outreach.md`, say it is a flag, not a check: the offer line is first person by nature.

- [ ] **Step 5: Run `tests/test_outreach_about.py tests/test_outreach_page.py tests/test_outreach_draft.py`.** Expected: PASS.

- [ ] **Step 6: Run the full suite, then commit:** `ai: outreach: about you vs about them on the card`.

---

## Phase 1: the framework library

### Task 4: The library, its file and `check`

**Files:**
- Create: `src/hermitcrm/frameworks.py`, `src/hermitcrm/default_frameworks.toml`, `tests/test_frameworks.py`.
- Modify:
  - `src/hermitcrm/adjust.py`: `VALIDATORS` gains `_late("frameworks", "validate")`.
  - `src/hermitcrm/cli.py`: `cmd_check` adds `frameworks.hints(root)` to its hint lines.
  - `CLAUDE.md`, and `docs/ARCHITECTURE.md` (the data-folder files list).

**Interfaces:**
- Produces (in `frameworks.py`):

```python
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
    frameworks: dict[str, Framework]      # library order: shipped file order, then the folder's additions
    problems: list[str] = field(default_factory=list)   # errors
    hints: list[str] = field(default_factory=list)      # unknown keys
    def get(self, fid: str) -> Framework | None: ...
    @property
    def ids(self) -> list[str]: ...
    @property
    def house(self) -> Framework: ...

def default_text() -> str: ...                     # the packaged file, like messaging._default_text
def from_table(fid: str, table) -> tuple[Framework | None, list[str], list[str]]: ...  # (framework, errors, hints)
def load(root: Path | str | None = None) -> Library: ...
def validate(root: Path | str) -> list[str]: ...   # load(root).problems
def hints(root: Path | str) -> list[str]: ...      # load(root).hints
def resolve(library: Library, default: str = "", override: str = "") -> tuple[Framework, str]: ...
```

**Loading.**
- Parse `default_text()` with `tomllib`.
- If `<root>/frameworks.toml` exists, `messaging.deep_merge` its `frameworks` table over the shipped one. This keeps the shipped order and appends new ids.
- A top-level key other than `frameworks` in the folder file is a hint.
- If the folder file is not valid TOML, the library is the shipped one, plus the problem `frameworks.toml: not valid TOML (<error>)`.
- A framework with any error is left out of the library. Every error it has is reported, not only the first.
- If the merged `house` has an error, the shipped `house` is kept and the error is still reported.

**Messages.** Each is `frameworks.toml: <id>.<key>: <what>`; a bad id is `frameworks.toml: <id>: an id is lower case letters, digits and hyphens`.
- `name`, `steps` (a non-empty list of strings) and `instructions` are required: `<key>: missing`.
- `max_words`: a whole number above 0.
- `questions`: two whole numbers, `[0, 1]` or `[1, 1]`. Otherwise `questions: [min, max] with max 1 (Hermit asks at most one question)`.
- `cta`: in `CTAS`, or `cta: unknown call to action '<value>' (known: ...)`.
- `proof` and `offer_line` in `LEVELS`, `research` in `RESEARCH`.
- `needs`: a list of `NEEDS` keys, or `needs: unknown need '<value>'`.
- `instructions` at most 900 characters: `instructions: at most 900 characters (<n>)`.
- Text keys are strings. `fits` is accepted as any table, until phase 4.
- An unknown key is a hint: `frameworks.toml: <id>.<key>: not a framework key (known: <KEYS>)`.

**`resolve`.**
- `override` set: `library.get(override)`, or raise `ValueError(f"unknown framework {override!r} (known: {', '.join(library.ids)})")`.
- Else `default` set and known: that framework.
- Else `default` set and unknown: `(library.house, f"framework {default} is not in the library; drafted with house")`.
- Else `(library.house, "")`.

**The shipped file.** It opens with a comment header in the style of `default_messages.toml`:
- "Do not edit this file in the package. Put a frameworks.toml in your data folder; it is deep-merged over this one."
- One line per key on who reads it: the AI reads `name`, `steps`, `instructions`; Python reads the limits; people read everything.

Then one table per framework, in this order, with these values:

| id | name | after | steps | max_words | cta | questions | proof | offer_line | research | needs |
|---|---|---|---|---|---|---|---|---|---|---|
| house | House style | | Finding, Offer, Question | | situation-question | [1, 1] | optional | required | trigger | |
| trigger-tension-trust | Trigger, tension, trust | Jason Bay | Trigger, Tension, Trust, Question | 60 | situation-question | [1, 1] | required | never | trigger | |
| truth-think-proof-talk | Truth, think, proof, talk | Josh Braun | Truth, Think, Proof, Talk | 80 | easy-no | [1, 1] | required | never | trigger | |
| premise-body-ask | Premise, body, ask | Becc Holland | Premise, Body, Ask | 80 | easy-no | [1, 1] | optional | optional | individual | premise |
| problem-solution-question | Problem, solution, question | 30 Minutes to President's Club | Problem, Solution, Question | 70 | interest-question | [1, 1] | required | optional | trigger | |
| attention-interest-desire-action | Attention, interest, desire, action | John Barrows | Attention, Interest, Desire, Action | 90 | small-step-question | [1, 1] | optional | optional | trigger | |
| connection-problem-objection | Connection, problem, objection | Sam McKenna | Connection, Problem, Objection, Invitation | | reply-invite | [0, 1] | optional | never | individual | personal-connection |
| pain-proof-yes-no | Pain, proof, yes or no | Justin Michael | Pain, Fix, Proof, Yes or no | 45 | yes-no | [1, 1] | required | never | trigger | |

**`instructions`.**
- For `house`: `SHAPES[FIRST_TOUCH]` exactly. Use a TOML literal string `'''...'''`, so its quotes need no escaping.
- For every other framework: the appendix paragraph for that id, verbatim, as one line of text. The `*Adaptation*` line stays in the spec.

- [ ] **Step 1: Write the failing tests** (in `tests/test_frameworks.py`)

```python
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
```

- [ ] **Step 2: Run `tests/test_frameworks.py`.** Expected: FAIL (`No module named hermitcrm.frameworks`).

- [ ] **Step 3: Write `default_frameworks.toml` and `frameworks.py`** to the interfaces and rules above. Then wire `check`:
  - add `_late("frameworks", "validate")` to `adjust.VALIDATORS`;
  - in `cmd_check`, add `frameworks.hints(store.root)` to `stray`, next to `pb_hints`.

- [ ] **Step 4: Add the credit exception to `CLAUDE.md`.** Insert this line directly after the "Never put real people..." bullet:

```markdown
- The one exception: the `after` credits in `src/hermitcrm/default_frameworks.toml`
  (and the outreach frameworks spec, plans and help page) name the authors of
  published sales methods, as credit. Prospects, customers and every test fixture
  stay fictional; do not "fix" the credits away.
```

Then add `frameworks.toml` (optional, deep-merged over the shipped library) to the data-folder files list in `docs/ARCHITECTURE.md`.

- [ ] **Step 5: Run `tests/test_frameworks.py tests/test_cli.py tests/test_adjust.py`.** Expected: PASS.

- [ ] **Step 6: Run the full suite, then commit:** `ai: outreach frameworks: the library, frameworks.toml and check`.

### Task 5: `frameworks` in the approach front matter

**Files:**
- Modify: `src/hermitcrm/playbook.py`, `src/hermitcrm/help/playbook.md`.
- Test: `tests/test_playbook.py`

**Interfaces:**
- Consumes: `frameworks.ID`, `frameworks.ANSWERS`, `frameworks.load(root).ids`.
- Produces:
  - `playbook.APPROACH_KEYS` ends with `"frameworks"` (after `"personas"`, so `dump_front` keeps today's order).
  - `Approach.frameworks -> dict`: `{}` when absent or not a mapping.
  - `Approach.default_framework -> str`: the `default` id, `""` when unset.
  - `Approach.testing_frameworks -> list[str]`.

**`_validate_approach` rules**, each line `"{where}.frameworks...: ..."`:
- `frameworks` must be a mapping with keys from `default`, `testing`, `answers`. Problems:
  - not a mapping: `frameworks: must be keys default, testing, answers`;
  - an unknown key: `frameworks.<key>: not a frameworks key (known: default, testing, answers)`.
- `default`: one string matching `frameworks.ID`. Otherwise `frameworks.default: one framework id, like trigger-tension-trust`.
- `testing`: a list of ids, at most two, no repeats, not the default. Problems: `frameworks.testing: at most two`, `frameworks.testing: <id> twice`, `frameworks.testing: <id> is the default`.
- `answers`: a mapping. Problems:
  - a key outside `ANSWERS`: `frameworks.answers.<key>: not a question (known: deal, buyer, volume, research, tone)`;
  - a value outside the key's choices: `frameworks.answers.<key>: one of <choices joined by ", ">`.

**`check_lines(root)`** also checks every id in `default` and `testing` against `frameworks.load(root).ids`. An unknown one is a problem: `MESSAGING.md: <approach name>: frameworks.<default|testing>: unknown framework '<id>' (known: ...)`.

- [ ] **Step 1: Write the failing tests**

```python
def front(frameworks_value):
    return {"approaches": [{"name": "A", "offer_line": "We do X.",
                            "frameworks": frameworks_value}]}


def test_frameworks_in_an_approach_is_valid():
    assert playbook.validate_front(front({
        "default": "trigger-tension-trust", "testing": ["house"],
        "answers": {"deal": "large", "buyer": "exec", "volume": "low", "research": "five",
                    "tone": "plain"}})) == []
    a = playbook.Approach(name="A", front={"frameworks": {"default": "trigger-tension-trust"}})
    assert a.default_framework == "trigger-tension-trust" and a.testing_frameworks == []
    assert playbook.Approach(name="B").default_framework == ""


@pytest.mark.parametrize("value, expected", [
    ("trigger-tension-trust", "frameworks: must be keys default, testing, answers"),
    ({"default": "Trigger Tension"}, "frameworks.default: one framework id"),
    ({"testing": ["house", "pain-proof-yes-no", "premise-body-ask"]}, "frameworks.testing: at most two"),
    ({"default": "house", "testing": ["house"]}, "frameworks.testing: house is the default"),
    ({"answers": {"deal": "huge"}}, "frameworks.answers.deal: one of small, mid, large, xl"),
    ({"answers": {"budget": "low"}}, "frameworks.answers.budget: not a question"),
    ({"winner": "house"}, "frameworks.winner: not a frameworks key"),
])
def test_a_wrong_frameworks_entry_is_a_problem(value, expected):
    assert any(expected in p for p in playbook.validate_front(front(value)))


def test_check_names_an_unknown_framework(tmp_path):
    root = init_folder(tmp_path / "x", demo=True)
    path = root / playbook.FILENAME
    a = playbook.parse(path.read_text()).approaches[0]
    path.write_text(playbook.apply_approach(path.read_text(), a.name,
                                            {**a.front, "frameworks": {"default": "gone"}}))
    problems, _ = playbook.check_lines(root)
    assert any(f"{a.name}: frameworks.default: unknown framework 'gone'" in p for p in problems)


def test_a_settings_save_keeps_the_frameworks_entry_byte_for_byte(tmp_path):
    root = init_folder(tmp_path / "x", demo=True)
    text = (root / playbook.FILENAME).read_text()
    a = playbook.parse(text).approaches[0]
    text = playbook.apply_approach(text, a.name,
                                   {**a.front, "frameworks": {"default": "trigger-tension-trust"}})
    values = playbook.form_values(playbook.parse(text).approaches[0])
    saved, errors = playbook.save_form(text, a.name, values)
    assert errors == {} and saved == text
```

- [ ] **Step 2: Run `tests/test_playbook.py -k frameworks`.** Expected: FAIL.

- [ ] **Step 3: Implement** the key, the three properties, the validation and the `check_lines` id check, as specified above.

- [ ] **Step 4: Document the key in `help/playbook.md`.** Write: optional; no key means `house`; ids are those of `hermitcrm help frameworks` (phase 2) or the library file; `testing` and `answers` are used from phase 2 and phase 4.

- [ ] **Step 5: Run `tests/test_playbook.py tests/test_web_playbook.py tests/test_help.py`.** Expected: PASS.

- [ ] **Step 6: Run the full suite, then commit:** `ai: playbook: an approach can name its frameworks`.

### Task 6: Framework checks

**Files:**
- Modify: `src/hermitcrm/outreach.py`: `CheckContext`, `framework_rules`, `check_text`, `DRAFT_SCHEMA`, `Draft`, `clean_answer`.
- Test: `tests/test_outreach_frameworks.py` (new).

**Interfaces:**
- Consumes: `frameworks.Framework`, `frameworks.load()`.
- Produces:
  - `CheckContext.framework: Framework | None = None`: set only for first touches.
  - `outreach.framework_rules(rules: dict, framework: Framework | None, channel: str, kind: str) -> dict`. It returns a copy. On an email first touch whose framework has `max_words`, `body_max_words` becomes `min(rules.get("body_max_words", 120), framework.max_words)`. Everything else is unchanged.
  - `Draft.framework: str = ""`.
  - `DRAFT_SCHEMA["properties"]["framework"] = {"type": "string", "description": "the framework id given in the prompt"}`, not in `required`.

**Question bounds in `check_text`.**
- A thread: `(1,)`.
- A LinkedIn connection note: `(0, 1)`.
- An email message, or a LinkedIn pitch, on a first touch with `ctx.framework`: `tuple(range(lo, hi + 1))` from `framework.questions`.
- Anything else: `(1,)`.

The existing wording ("exactly one" / "at most one") covers both shapes the validator allows.

**In `clean_answer`, for a first touch with `ctx.framework`:**
- `proof == "required"`, `ctx.proof` non-empty and nothing in `draft.proof_used`: problem `the <name> framework cites one proof line from the playbook in proof_used (it cites none)`.
- A non-empty `framework` in the answer that is not `ctx.framework.id`: problem `it says framework '<given>'; this draft was asked for <id>`.
- `draft.framework = ctx.framework.id`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run `tests/test_outreach_frameworks.py`.** Expected: FAIL.

- [ ] **Step 3: Implement** the interfaces and rules above.

- [ ] **Step 4: Run `tests/test_outreach_frameworks.py tests/test_outreach_draft.py`.** Expected: PASS. All existing check tests run with `framework=None`.

- [ ] **Step 5: Run the full suite, then commit:** `ai: outreach: framework checks (questions, words, proof)`.

### Task 7: The framework block in the draft prompt

**Files:**
- Modify: `src/hermitcrm/outreach.py`: `FRAMEWORK_CHANNEL_TEXT`, `framework_block`, `draft_prompt`, and `AIDrafter.context` / `AIDrafter.draft`.
- Test: `tests/test_outreach_frameworks.py`

**Interfaces:**
- Consumes: `framework_rules` and `CheckContext.framework` (Task 6); `frameworks.load` and `HOUSE` (Task 4).
- Produces:
  - `outreach.framework_block(framework: Framework) -> str`.
  - `AIDrafter.context(kind, company, contact, research, channel, approach=None, language="", framework=None) -> tuple[CheckContext, dict]`. `framework` comes after the existing `language` parameter, and callers pass it by keyword. `ctx.framework` is the framework on a first touch, else `None`. `ctx.rules` is `framework_rules(...)`. `_learned` (the angle policy and examples) runs as before, on the same `ctx`.
  - `AIDrafter.draft(..., framework: Framework | None = None, ...)`. `None` on a first touch means the library's `house` (`frameworks.load(self.store.root).house`).

**`draft_prompt` on a first touch:**
- `ctx.framework` is `None`: `SHAPES[FIRST_TOUCH]`, as today.
- `ctx.framework.id == HOUSE`: `ctx.framework.instructions`.
- Any other framework: `framework_block(ctx.framework)`, and the channel line comes from `FRAMEWORK_CHANNEL_TEXT[channel]` instead of `CHANNEL_TEXT`.

Everything else in the prompt stays as it is.

Exact copy:

```python
FRAMEWORK_CHANNEL_TEXT = {
    "email": ("Channel: email. A subject of at most {subject_max} characters; the body at "
              "most {body_max_words} words, greeting and sign-off included."),
    "linkedin": ("Channel: LinkedIn. body is the connection note: at most {note_max_chars} "
                 "characters, no pitch, at most one question. pitch is the message sent once "
                 "they accept: at most {pitch_max_chars} characters, built with the framework "
                 "below. No subject."),
}
```

`framework_block(fw)` returns these lines, joined by `"\n"`, with conditional lines only when they apply:

```
This is a first touch: they have never had a message from the seller.
--- framework "<fw.name>" ---
Steps: <fw.steps joined by ", ">.
<fw.instructions>
--- end ---
- Never open with "I" (or Ich, Ik, Je): the first word is about them.
- No meeting ask, no call ask, no link, no proposed day or time.
- When no finding is usable, write from one of the playbook's angles instead and mark what only the seller can fill in with [square brackets].
- The playbook's Voice section wins over the framework on wording, greeting, sign-off and formality.
- Exactly one question mark in the whole message.           # questions == (1, 1)
- At most one question mark in the whole message.           # questions == (0, 1)
- Do not state the offer line; it is below as background.   # offer_line == "never"
- Say the offer in one line.                                 # offer_line == "required"
- Cite one proof line in proof_used, word for word.         # proof == "required"
- Set framework to "<fw.id>".
```

- [ ] **Step 1: Write the failing tests**

```python
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
    assert "built with the framework below" in prompt and "the offer in one line" not in prompt


def test_replies_and_follow_ups_get_no_framework(folder):
    _, store = folder
    company = store.get("lindenhof-data")
    drafter = outreach.AIDrafter(store, ai(FakeAI()), {})
    ctx, _ = drafter.context(outreach.REPLY, company, company.contacts["mara-keller"],
                             outreach.Research(), "email", None,
                             framework=LIB.get("trigger-tension-trust"))
    assert ctx.framework is None
```

`BRANDS` is the tuple from Task 4. Import it from `tests/test_frameworks.py`, or repeat it.

- [ ] **Step 2: Run the new tests.** Expected: FAIL.

- [ ] **Step 3: Implement** `FRAMEWORK_CHANNEL_TEXT`, `framework_block`, the `draft_prompt` branch and the `AIDrafter` changes, as specified above.

- [ ] **Step 4: Run `tests/test_outreach_frameworks.py tests/test_outreach_draft.py tests/test_draft_language.py tests/test_outreach_replies.py tests/test_outreach_followups.py`.** Expected: PASS.

- [ ] **Step 5: Run the full suite, then commit:** `ai: outreach: the framework block in the draft prompt`.

### Task 8: `framework` on the item: build, regenerate, ready, CLI

**Files:**
- Modify:
  - `src/hermitcrm/outreach.py`: `Item`, `ITEM_KEYS`, `to_frontmatter`, `item_from_text`, `unmet_needs`, `build`, `redraft`, `check_item`, `render_item`.
  - `src/hermitcrm/cli.py`: `--framework`.
  - `src/hermitcrm/migrations.py`: migration 15.
  - `tests/outreach_fakes.py`: `proof_draft`.
  - Docs: `help/outreach.md`, `help/cli.md`, `docs/ARCHITECTURE.md`.
- Test: `tests/test_outreach_frameworks.py`, `tests/test_migrations.py`, `tests/test_outreach_replies.py`, `tests/test_outreach_draft.py` (the `built()` helper).

**Interfaces:**
- Consumes: `frameworks.load`, `resolve` and `NEEDS` (Task 4); `Approach.default_framework` (Task 5); the `AIDrafter.draft(framework=...)` kwarg (Task 7).
- Produces:
  - **`Item.framework: str = ""`.** `"framework"` sits in `ITEM_KEYS` right after `"angle"`. `to_frontmatter` leaves it out when empty: add it to the tuple of keys it already skips when empty (`lessons_used`, `exemplars_used`, `language_pick`, `notes_linked`). `item_from_text` reads it stripped and lower case.
  - **`outreach.unmet_needs(framework: Framework, findings: list[Finding]) -> list[str]`.** A usable finding with `source == YOURS` meets `personal-connection`. A usable finding with `kind == "person"` meets `premise`. Findings are now a snapshot of the contact's notes, so a note the person wrote (source `YOURS`, kind `person`) meets both.
  - **`outreach.build(store, selection, researcher, drafter, config=None, now=None, batch="", critic=None, language="", framework: str = "") -> BuildResult`.** `framework` comes after the existing `language`, so the web's positional call (`..., batch_id, critic, pick`) keeps working.
  - **`migrations.m15_framework(meta: dict) -> dict`**, plus `Migration(15, "outreach drafts record their framework", "outreach/*.md", m15_framework)`.
  - **`hermitcrm outreach build --framework ID`.**

**`build` rules.**
- Load the library once. With `framework` set:
  - a selection kind other than first touch raises `OutreachError("frameworks shape first touches only; leave out --framework for a reply or follow-up")`;
  - an unknown id raises `OutreachError` with `resolve`'s message.

  The CLI makes the same two checks before it selects anyone. Otherwise an empty selection ("Nothing to build", exit 0) would hide the refusal.
- For each first-touch candidate:
  - resolve `(fw, note) = resolve(library, approach.default_framework if approach else "", framework)`, set `item.framework = fw.id`, and add `note` to `item.flags` when it is non-empty;
  - after research, if `unmet_needs(fw, research.findings)` is non-empty, take the fallback: the approach's default when it has no `needs` and differs from `fw`, else `house`. Set `item.framework` to it, flag `f"{fw.id} needs {' and '.join(NEEDS[n] for n in missing)}; drafted with {fallback.id}"`, and draft with the fallback;
  - pass `framework=<the Framework>` to `drafter.draft`.
- Thread kinds pass no framework and leave `item.framework` empty.

**`redraft`.**
- A first touch drafts with `library.get(item.framework)`.
- An empty `item.framework` (an item from before) means `house`, and the item then records `house`.
- An id that is no longer in the library means `house`, with the flag `framework <id> is not in the library; drafted with house`.

**`check_item`:** builds the context with the item's framework (same lookup as `redraft`, without the flag) and `framework_rules`.

**`render_item`:** the Approach line gets `| framework: <id>` after the angle, only when set.

**`m15_framework`:** does what `m9_angle` does, for the key `framework`. Absent: returned as is. `None` or blank: the key is dropped. Otherwise stripped and lower case. An unchanged value returns the same dict.

- [ ] **Step 1: Write the failing tests**

Add this fake to `tests/outreach_fakes.py`, and give `built()` a `framework=""` argument that it passes to `outreach.build`:

```python
def proof_draft(prompt):
    """A trigger, tension, trust draft: one proof line cited, under 60 words."""
    first = re.search(r"^Person: (\S+)", prompt, re.M).group(1)
    proof = re.search(r"--- proof \(cite only these[^\n]*\n- (.*)\n", prompt).group(1)
    usable = re.search(r"^(\d+)\. \[\w+, (?:high|medium), usable; source (?!crm)", prompt, re.M)
    return {"subject": "Your second office", "angle": "hook", "framework": "trigger-tension-trust",
            "body": f"Hi {first},\n\nA second office usually means hiring sales next.\nThat is "
                    f"where founders lose time. {proof}\nIs that on your radar right now?\n\nSam",
            "pitch": "", "findings_used": [int(usable.group(1))] if usable else [],
            "proof_used": [proof]}
```

Tests:

```python
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


def test_the_approach_default_is_used_and_a_gone_one_falls_back(folder):
    root, _ = folder
    path = root / playbook.FILENAME
    a = playbook.parse(path.read_text()).approaches[0]
    path.write_text(playbook.apply_approach(path.read_text(), a.name,
                                            {**a.front, "frameworks": {"default": "gone"}}))
    item = built(folder, limit=1)[0].items[0]
    assert item.framework == "house"
    assert "framework gone is not in the library; drafted with house" in item.flags


def test_unknown_framework_or_a_thread_kind_is_refused(tmp_path, fake_cli, capsys):
    root = init_folder(tmp_path / "x", demo=True)
    assert cli.main(["outreach", "build", "--framework", "gone"], root=root) == 1
    assert "unknown framework 'gone'" in capsys.readouterr().out
    assert cli.main(["outreach", "build", "--kind", "follow-up", "--framework", "house"],
                    root=root) == 1
    assert "frameworks shape first touches only" in capsys.readouterr().out


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
```

In `tests/test_migrations.py`:

```python
@pytest.mark.parametrize("meta, expected", [
    ({"state": "drafted"}, {"state": "drafted"}),
    ({"state": "drafted", "framework": ""}, {"state": "drafted"}),
    ({"state": "drafted", "framework": None}, {"state": "drafted"}),
    ({"state": "drafted", "framework": " Trigger-Tension-Trust "},
     {"state": "drafted", "framework": "trigger-tension-trust"}),
])
def test_the_framework_migration_normalises_and_is_idempotent(meta, expected):
    once = migrations.m15_framework(meta)
    assert once == expected and migrations.m15_framework(once) == once
```

Also add these:
- **Migration integration.** Add a test in the style of the existing ones: a demo folder at the previous format, with one item holding `framework: " House"` and one without the key, runs `ensure_current`. Afterwards the first reads `house`, and the second's bytes are unchanged.
- **Reply items.** In `tests/test_outreach_replies.py`, add `"framework"` to the keys its key-list assertion excludes (`list(meta) == [k for k in outreach.ITEM_KEYS if k not in (...)]`), and assert `"framework" not in meta` even when the approach has a `frameworks.default`.

- [ ] **Step 2: Run `tests/test_outreach_frameworks.py tests/test_migrations.py`.** Expected: FAIL.

- [ ] **Step 3: Implement** the item key, `unmet_needs`, the `build` / `redraft` / `check_item` / `render_item` rules, the CLI flag and the migration, as specified above. For the CLI:
  - `o.add_argument("--framework", default="", help="the framework for first touches (default: the approach's, else house)")` under `if verb == "build"`;
  - pass `framework=args.framework` to `outreach.build`.

- [ ] **Step 4: Fix the tests that pin the format number.** Run `grep -rn "LATEST\|hermitcrm-format\|== 10\b" tests/test_migrations.py tests/test_datafolder.py`. Each pinned format number moves up by one.

- [ ] **Step 5: Update the docs.**
  - `help/outreach.md`: `--framework`, the needs flag, and that the item records `framework`.
  - `help/cli.md`: the build flags line.
  - `docs/ARCHITECTURE.md`, outreach items: `framework` (after `angle`, absent when empty; covered by migration N).

- [ ] **Step 6: Run `tests/test_outreach_frameworks.py tests/test_outreach_draft.py tests/test_outreach_replies.py tests/test_outreach_followups.py tests/test_outreach_web.py tests/test_migrations.py tests/test_cli.py`.** Expected: PASS.

- [ ] **Step 7: Run the full suite, then commit:** `ai: outreach: drafts record their framework; outreach build --framework`.

### Task 9: `framework` on interactions

**Files:**
- Modify:
  - `src/hermitcrm/models.py`: `Interaction`, `INTERACTION_KEYS`, `interaction_to_frontmatter`, the from-dict, `normalise_framework`.
  - `src/hermitcrm/store.py`: `create_interaction`, `update_interaction`, the copy on sent.
  - `src/hermitcrm/send.py`: the interaction it logs for a mail it sent.
  - `src/hermitcrm/migrations.py`: migration 16.
  - Docs: `help/data-format.md`, `docs/ARCHITECTURE.md`.
- Test: `tests/test_angle.py` (it already covers the parallel `angle` cases; add the framework ones beside them), `tests/test_send_email.py`.

**Interfaces:**
- Consumes: `Item.framework` (Task 8); `frameworks.ID` (Task 4); `m15_framework` (Task 8).
- Produces:
  - **`Interaction.framework: str = ""`.** The field comes after `angle`. In the file it is written after `angle` and before `approach`, only when non-empty.
  - **`models.normalise_framework(value) -> str`:** stripped and lower case.
  - **`Store.create_interaction(..., framework: str = "")`.** `update_interaction` accepts `"framework"` in its fields. A non-empty value that does not match `frameworks.ID` after normalising raises `ValidationError({"framework": "a framework id: lower case letters, digits and hyphens"})`. Library membership is not checked: an old message keeps an id that was later removed.
  - **On sent:** `it.framework = it.framework or item.framework`, next to the angle line in `Store.create_interaction`. `send.py` (the method around line 444 that logs a mail it sent) passes `angle=item.angle` explicitly; pass `framework=item.framework` beside it.
  - **`Migration(16, "interactions get an optional framework", "companies/*/interactions/*.md", m15_framework)`.**

- [ ] **Step 1: Write the failing tests**

```python
def test_logging_a_ready_item_copies_its_framework(folder):
    root, store = folder
    item = built(folder, limit=1, drafts=[proof_draft],
                 framework="trigger-tension-trust")[0].items[0]
    outreach.mark_ready(store, item.id)
    it = store.create_interaction(item.company, "email", "out", subject=item.subject,
                                  contact=item.contact, body=item.body)
    assert it.framework == "trigger-tension-trust"
    text = store.interaction_file(item.company, it.id).read_text()
    assert text.index("angle:") < text.index("framework:") < text.index("approach:")


def test_a_hand_logged_message_may_carry_a_framework(folder):
    _, store = folder
    it = store.create_interaction("lindenhof-data", "email", "out", subject="Hello",
                                  contact="mara-keller", body="Hi\n", framework=" House ")
    assert it.framework == "house"
    with pytest.raises(ValidationError):
        store.create_interaction("lindenhof-data", "email", "out", subject="Hello",
                                 contact="mara-keller", body="Hi\n", framework="Trigger tension")
    assert store.update_interaction("lindenhof-data", it.id, framework="").framework == ""
```

Then:
- **Bytes.** An interaction file without `framework` keeps its bytes when read and written.
- **Migration.** A folder at the previous format with an interaction holding `framework: " Trigger-Tension-Trust "` reads `trigger-tension-trust` after `ensure_current`; a file without the key is unchanged.
- **The registry.** `{m.version: m.glob for m in migrations.MIGRATIONS}` holds `15: "outreach/*.md"` and `16: "companies/*/interactions/*.md"`.
- **Sent by Hermit.** In `tests/test_send_email.py`, next to the existing assertion `it.angle == "hook"` (around line 264): give the item `framework="trigger-tension-trust"` and assert the logged interaction's `framework` is the same.

`ValidationError` comes from `hermitcrm.models`.

- [ ] **Step 2: Run `tests/test_angle.py`.** Expected: FAIL.

- [ ] **Step 3: Implement** the interfaces and the second migration entry, as specified above.

- [ ] **Step 4: Update the docs.** `help/data-format.md` (the interaction keys and the migration note) and `docs/ARCHITECTURE.md` (the interaction keys line, and "copies its angle, framework and approach").

- [ ] **Step 5: Run `tests/test_angle.py tests/test_store.py tests/test_models.py tests/test_migrations.py tests/test_bcc.py tests/test_send_email.py tests/test_send_foundations.py`.** Expected: PASS.

- [ ] **Step 6: Run the full suite, then commit:** `ai: interactions record the framework a message was built with`.

### Task 10: Framework on the Messages tab, export, bulk set and the log form

**Files:**
- Modify:
  - `src/hermitcrm/web.py`: `MessageRow.framework`, `message_columns`, `interaction_create` / `interaction_save` / `interaction_edit`.
  - Templates: `messages.html`, `macros.html`.
  - `src/hermitcrm/export.py` and `src/hermitcrm/bulk.py`.
- Test: `tests/test_angle.py` (mirror each angle test for the web form, Messages and bulk), `tests/test_export.py`.

**Interfaces:**
- Consumes: `Interaction.framework` and `Store.create_interaction(framework=)` (Task 9); `frameworks.load(root).ids` (Task 4).
- Produces:
  - **`message_columns`:** `Column("framework", "framework")` (plain text) right after the angle column. In `messages.html`, `<td>{{ r.framework }}</td>` goes after the angle cell.
  - **Export:** `"framework"` right after `"angle"` in the interaction columns.
  - **`bulk.py`:** interactions settable `"framework": True`. Value checks come from the store.
  - **The log and edit form** (`macros.html`): a `framework` select after angle.
    - Options: "not known" (empty), then the library ids, then the current value if it is not in the library, as the angle select does.
    - The web handlers take `framework: str = Form("")` and pass it through; the context gains `frameworks` (the library ids).

- [ ] **Step 1: Write the failing tests.** For each, mirror the angle test next to it in `tests/test_angle.py`:
  - the Messages page shows `trigger-tension-trust` in a row logged with it, and filtering `framework=trigger` keeps that row only;
  - logging from the form with `framework=trigger-tension-trust` saves it, and the edit form shows it selected;
  - `hermitcrm set` on interactions with `framework=house` changes the matching messages (dry run first, as the bulk tests do);
  - the export's interactions CSV header has `framework` right after `angle`.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement** the column, the export column, the bulk key and the form select, as specified above.

- [ ] **Step 4: Run `tests/test_angle.py tests/test_export.py tests/test_bulk.py tests/test_web.py tests/test_dashboards.py`.** Expected: PASS. If a dashboards test pins the message column list, add `framework` there.

- [ ] **Step 5: Run the full suite, then commit:** `ai: Messages, export, bulk set and the log form show the framework`.

### Task 11: Learning by framework

**Files:**
- Modify: `src/hermitcrm/learning.py`: `Signal.framework`, `signal_of`, `DIMENSIONS`, `Card.framework`, `Card.text`, and the card builder. Also `src/hermitcrm/help/learning.md`.
- Test: `tests/test_learning.py`

**Interfaces:**
- Consumes: `Item.framework` (Task 8).
- Produces:
  - `learning.DIMENSIONS == ("angle", "persona", "channel", "language", "framework")`;
  - `Signal.framework: str = ""`, filled from the item;
  - `Card.framework: str = ""`. Its first line gets ` | framework <id>` after the angle part, only when set, so cards of older items read as before.

- [ ] **Step 1: Write the failing tests**

```python
def test_framework_is_a_learning_dimension():
    assert learning.DIMENSIONS == ("angle", "persona", "channel", "language", "framework")
    sigs = [learning.Signal(item_id=str(n), rungs={"sent": "2026-10-01"},
                            framework="house" if n % 2 else "trigger-tension-trust")
            for n in range(4)]
    assert [(r.value, r.n) for r in learning.rates(sigs, "framework")] == [
        ("house", 2), ("trigger-tension-trust", 2)]


def test_a_card_names_its_framework_only_when_it_has_one():
    card = learning.Card(id="x", angle="hook", framework="trigger-tension-trust",
                         kind="first-touch", channel="email", language="de")
    assert card.text.splitlines()[0] == ("card x | first-touch, email, de | angle hook | "
                                         "framework trigger-tension-trust | rung none")
    assert "framework" not in learning.Card(id="x", angle="hook").text


def test_a_signal_carries_the_items_framework(folder):
    root, store = folder
    item = built(folder, limit=1, drafts=[proof_draft],
                 framework="trigger-tension-trust")[0].items[0]
    outreach.mark_ready(store, item.id)
    assert [s.framework for s in learning.signals(store)] == ["trigger-tension-trust"]
```

`built` and `proof_draft` come from the outreach test helpers; import them or repeat the build.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement** the field, the dimension and the card line, as specified above.

- [ ] **Step 4: Run `tests/test_learning.py tests/test_learning_cli.py tests/test_learning_web.py tests/test_reports.py`.** Expected: PASS. The CLI report (`cli.py`, the loop over `learning.DIMENSIONS`) and the web quality block (`web.py`, same loop) gain a framework block on their own. Update any test that pins the whole report text, and add a line to `help/learning.md`.

- [ ] **Step 5: Run the full suite, then commit:** `ai: learning: framework as a dimension and on evidence cards`.

### Task 12: Acceptance on a demo folder

No code. This checks the phase 0 and phase 1 "done when" with the real AI CLI. It uses a fictional demo folder (3 drafts plus critic calls on the medium tier). Skip Steps 2 to 5 when no AI CLI is set up, and say so in the report.

- [ ] **Step 1: Make a demo folder.**

```bash
rm -rf /tmp/fw-demo && .venv/bin/hermitcrm init /tmp/fw-demo --demo
```

- [ ] **Step 2: Build three drafts with a framework.**

```bash
.venv/bin/hermitcrm --data /tmp/fw-demo outreach build --where stage=prospect --limit 3 --framework trigger-tension-trust
```

Expected: three `drafted:` lines.

- [ ] **Step 3: Read every item.** Run `.venv/bin/hermitcrm --data /tmp/fw-demo outreach show <id>` for each, and check:
  - `framework: trigger-tension-trust` is on the Approach line;
  - there is an About line;
  - the checks passed, or the problems are listed;
  - the Lindenhof Data item (German) says its proof in German in the body, while "Proof cited" keeps the English playbook line (the phase 0 done-when).

- [ ] **Step 4: Check the folder.**

```bash
.venv/bin/hermitcrm --data /tmp/fw-demo check
```

Expected: `OK: ...`. Then `git -C /tmp/fw-demo status --porcelain` should be empty.

- [ ] **Step 5: Build once more without a framework.** Expected: drafts record `house`, and none of the prompts has a `--- framework` block. To confirm, add a temporary print, or rerun `test_a_folder_without_frameworks_builds_with_house`.

- [ ] **Step 6: Run the full suite one last time.** Then report in the branch's PR description:
  - what the real drafts looked like (one quoted per framework used);
  - every check that fired;
  - anything that surprised you.

---

## Deferred to later phases (not in this plan)

- **Phase 2:** build-form modes Default and Split, and the split assignment. The card's "Built with", popover and parts (`parts` in the schema and as an item key, with a migration). "Try another framework" and the `frameworks` help page. The people-facing texts (`summary`, `best_for`, `watch_out`, `evidence`, `example`).
- **Phase 3:** compare mode.
- **Phase 4:** `fits` and the setup questions.
- **Phase 5:** the card question for an unmet need and "Regenerate with X". Credit chips, and the experiment view.
