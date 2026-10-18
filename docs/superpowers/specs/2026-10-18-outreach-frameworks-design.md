# Outreach frameworks: a library, setup questions and compare mode

Status: design, 18 Oct 2026; its one open question (naming and credit) was
decided the same day. Nothing is built. Builds on
[the outreach bot spec](2026-10-16-outreach-bot-design.md) and
[the learning spec](2026-10-18-learning-approaches.md) (A and B are on `main`;
C, exemplars and the angle bandit, is on `ai/learning-exemplars`).

Source material: a research note on ten cold outreach methods by well-known
sales trainers (30MPC, John Barrows, Josh Braun, Jason Bay, Sam McKenna, Becc
Holland, Morgan J Ingram, Will Allred, Justin Michael, Jeb Blount), written 18
Oct 2026 from mostly secondary sources. Everything this design needs from it is
copied into section 4 and the appendix, adapted to Hermit's rules.

## 1. Intent

Every Hermit user gets the same first-touch structure today: one fixed recipe,
`SHAPES[FIRST_TOUCH]` in `outreach.py` (a finding, the offer in one line, one
diagnostic question, no meeting ask). The trainers disagree on almost everything
else: length, call to action, research time, polish, tone. Their own conclusion
is that **deal size and buyer seniority decide which side is right for you**. A
seller of a 3k tool to managers and a seller of a 60k engagement to founders
should not get the same message.

This feature gives Hermit a small library of message **frameworks** and uses it
four ways:

1. **Inspiration for the AI.** The chosen framework steers the draft's
   structure, length, call to action and use of proof.
2. **Inspiration for people.** The card says which framework built the draft,
   marks its parts, and offers another one. Reviewing a draft teaches the
   structure.
3. **Asking the person.** At setup (which frameworks fit how you sell), on a
   draft (when a framework needs a fact only the seller knows), and after a
   positive reply (what do you think did it).
4. **Seeing what works.** The framework is recorded on every draft and every
   message, so learning, Reports and the Messages tab can compare frameworks,
   with a split test for outcomes and compare mode for fast preference signals.

It is designed for every Hermit user from the start. The reference folder
(a fractional Head of Sales selling to founders of 10 to 60 person B2B SaaS
companies) is the first test case; section 9 has its plan.

### Success looks like

- A new user answers five questions and gets a default framework and one to
  test, with a plain reason, in under a minute and without AI.
- A folder that never touches frameworks gets the same draft prompt text it
  gets after phase 0 (the `house` framework is today's recipe; phase 0 changes
  one proof sentence and the critic rubric for everyone).
- After a few batches the Learning page can say, with counts, which framework
  the person prefers and, once there are enough sends, which one gets replies.

## 2. Non-goals and anti-goals

**Non-goals (v1).**
- Cadence frameworks (Triple Touch, three clusters, 21-day sequences, nurture).
  Follow-ups keep their current template.
- Frameworks for `reply-to-interest` and `follow-up`. They answer a thread and
  keep their templates. Frameworks shape the **first touch** only.
- Video and voice scripts (Ingram's 10-30-10), phone scripts.
- A framework bandit. Section 8 records everything one would need later
  (next to C's angle bandit).
- Teaching the full methods. Hermit carries a short, adapted summary with its
  evidence note, and points nowhere for the rest.
- Anything shared between data folders, any telemetry, any new runtime
  dependency.

**Anti-goals (a failure even if it technically works).**
- **A framework loosening Hermit's honesty or call-to-action rules.** No
  framework may propose a time, ask for a meeting or a call, include a link or
  booking link in a first touch, or invent familiarity. Where a trainer's method
  does one of these (Holland and Blount propose a time; Michael asks for "10
  minutes, yes or no"), the shipped version is adapted, and the adaptation is
  written down (appendix). These rules come from the reference folder's own data
  (3 of 4 positive replies went quiet after a booking link or proposed times).
- **Noise reported as a finding.** Ten frameworks tested on 13 sends a week
  would say nothing for a year. One test at a time per approach, a planned size,
  and counts instead of verdicts below it.
- **One voice for everyone.** A framework decides structure. The playbook's
  Voice section and the culture norms still decide wording, greeting, sign-off
  and formality.

## 3. Concepts

Three dimensions, each with one home:

| | Answers | Lives in | Example |
|---|---|---|---|
| approach | what you sell to whom | `MESSAGING.md` front matter | "Interim with team" |
| angle | what this message argues | `ANGLES`, `messages.toml` | scale, unblock, hook |
| **framework** (new) | how this message is built | `frameworks.toml` | trigger-tension-trust |

Angle and framework combine: an `unblock` argument written as
`trigger-tension-trust`. Neither replaces the other.

The source mixes four kinds of advice. Only the first becomes frameworks:

| Kind | From the source | Where it goes |
|---|---|---|
| How one message is built | 30MPC 3x3, Barrows AIDA, Braun 4T, Bay Triple T, Holland premise/body/CTA, McKenna SMYKM, Michael's Spear | **frameworks** (section 4) |
| Quality checks for any message | Allred's deletion test and you-vs-I ratio, Holland's "sins", Bay's "opener that does not connect to the rest" | the critic and the hard checks, for every framework (section 4.6) |
| Research method | Holland's premise buckets, McKenna's LinkedIn-first research, Bay's trigger groups | later (section 11); v1 uses the existing findings |
| Cadence and rhythm | Triple Touch, Michael's clusters, McKenna's 48-hour bump and nurture, Blount, Hormozi | not in v1 |

Blount's Hook, Relate, Bridge, Ask is **not shipped**: the source says its
definitions were inferred, not read. Ingram is a video format, not a text one.

## 4. The framework library

### 4.1 Format and loading

A new package file `src/hermitcrm/default_frameworks.toml`, deep-merged with an
optional `frameworks.toml` in the data folder, exactly as
`default_messages.toml` and `messages.toml` work today. A user can change a
shipped framework or add their own; `hermitcrm help frameworks` documents the
format for people and AI agents (a natural "Make it yours" target).

One table per framework, keyed by an id (lower case, hyphens):

```toml
[frameworks.trigger-tension-trust]
name = "Trigger, tension, trust"
after = "Jason Bay"                  # shown as "After Jason Bay"; never in a prompt (4.7)
summary = "Why you, why now, why believe it: a trigger, the problem it creates, one proof line."
steps = ["Trigger", "Tension", "Trust", "Question"]
max_words = 60                       # email body; min() with the channel rule
cta = "situation-question"           # vocabulary in 4.3
questions = [1, 1]                   # min and max question marks; default [1, 1]
proof = "required"                   # required | optional | never
offer_line = "never"                 # required | optional | never, in a first touch
needs = []                           # facts the draft cannot do without (6.2)
research = "trigger"                 # none | trigger | individual (shown to people only)
best_for = "A clear list of buying triggers and a repeatable ICP."
watch_out = "The trigger must be true and recent; a stale one reads as spam."
evidence = "From a 30MPC write-up of a talk; no reply-rate data."
instructions = """..."""             # goes into the prompt; at most 900 characters
example = """..."""                  # fictional; help page only, never in a prompt
```

Who reads what:
- **Python:** `max_words`, `questions`, `proof`, `offer_line`, `cta`, `needs`,
  `research`. Validated by `hermitcrm check` (unknown keys are a warning,
  wrong types an error, an unknown `cta` an error, `instructions` over 900
  characters an error).
- **The AI:** `name`, `steps` and `instructions` only. `after` and `example`
  never reach a prompt.
- **People:** everything, on the card popover and the help page.

`after` is optional: a framework a user adds in their own folder usually has
none, and then no credit line is shown.

### 4.2 Shipped frameworks

| id | After | CTA | Words | Proof | Offer line | Research | Needs |
|---|---|---|---|---|---|---|---|
| `house` | Hermit's current first touch | situation-question | channel max | optional | required | trigger | |
| `problem-solution-question` | 30MPC 3x3 | interest-question | 70 | required | optional | trigger | |
| `attention-interest-desire-action` | Barrows AIDA | small-step-question | 90 | optional | optional | trigger | |
| `truth-think-proof-talk` | Braun 4T | easy-no | 80 | required | never | trigger | |
| `trigger-tension-trust` | Bay Triple T | situation-question | 60 | required | never | trigger | |
| `premise-body-ask` | Holland | easy-no | 80 | optional | optional | individual | `premise` |
| `connection-problem-objection` | McKenna SMYKM | reply-invite | channel max | optional | never | individual | `personal-connection` |
| `pain-proof-yes-no` | Michael | yes-no | 45 | required | never | trigger | |

`house` is the default for every approach that names none, and its
`instructions` are today's `SHAPES[FIRST_TOUCH]` text word for word. Its steps
are `["Finding", "Offer", "Question"]`, so its drafts can be marked too. The
appendix has every other `instructions` text and the adaptation each one needed.

File order in `default_frameworks.toml` is `house`, then the order of the
fit-profile table in 6.1. "Library order" in this design means that order.

The `name` of each is its id in words, describing the structure (4.7): "House
style", "Problem, solution, question", "Attention, interest, desire, action",
"Truth, think, proof, talk", "Trigger, tension, trust", "Premise, body, ask",
"Connection, problem, objection", "Pain, proof, yes or no". The "After" column
above is the `after` credit plus, for this design only, the source method.

### 4.3 Call-to-action vocabulary

| `cta` | Means | Example |
|---|---|---|
| `situation-question` | a diagnostic question about their situation (today's default) | "Where does it hurt most right now: pipeline, conversion or deal size?" |
| `interest-question` | whether the idea is worth a look | "Worth a look at how?" |
| `small-step-question` | a step smaller than a meeting that the seller can really offer | "Would a one-page version help?" (only if the playbook's Offer says one exists) |
| `easy-no` | a question that makes no easy | "Worth a quick look? A no is fine too." |
| `yes-no` | a question answerable yes or no, about their situation | "Is ramp time a problem this quarter, yes or no?" |
| `reply-invite` | an invitation to reply, may have no question mark | "If it is not relevant, tell me and I will drop it." |

There is deliberately no `time-slot`, `meeting-ask` or `link` value. The
existing time, link and calendar checks in `check_text` stay on for every
framework.

### 4.7 Names and credit (decided 18 Oct)

- **Neutral names in the product.** Ids and `name` describe the structure
  ("Trigger, tension, trust", `trigger-tension-trust`). The trainers' own
  method names and brands ("Triple T", "4T", "Show Me You Know Me", "Poke the
  Bear", "JM Spear", "SMYKM") appear nowhere in code, templates, prompts or the
  shipped TOML.
- **Credit as one line, in two places only:** the help page `frameworks` and
  the card's framework popover, rendered from `after` as "After Jason Bay".
  Nowhere else in the UI, never in a prompt, never in a draft.
- **An exception to the repo rule, written down.** `CLAUDE.md` says never to put
  real people in code, tests or docs. Phase 1 adds one line to it: the trainer
  names in `after` (and in this spec and its help page) are credit for authors
  of published methods, and the only allowed exception; prospects, customers and
  every test fixture stay fictional. Without that line a later session would
  "fix" the credits away.
- **Evidence stays honest.** Next to the credit the popover and help page show
  the `evidence` note (secondary sources, self-reported numbers) and say that
  the examples are made up for Hermit.
- **The design's own tables keep the trainer names** (sections 3, 4.2 and the
  appendix), so a builder can trace each framework to its source.

### 4.4 Where the choice lives

Per approach, in the `MESSAGING.md` front matter (it is per approach because
lessons and learning phases are per approach):

```yaml
approaches:
- name: Interim with team
  offer_line: ...
  frameworks:
    default: trigger-tension-trust
    testing: [house]            # 0 or 1 for a split test; up to 2 for compare mode
    answers: {deal: large, buyer: exec, volume: low, research: five, tone: plain}
```

- No `frameworks` key: `default` is `house`, `testing` is empty. Nothing changes
  for existing folders.
- `APPROACH_KEYS` gains `frameworks`. `hermitcrm check` validates the ids against
  the merged library and the `answers` values against 6.1.
- This is the playbook file, not a record, so it needs no `migrations.py`
  migration (the same rule the outreach spec used for the playbook's front
  matter). The Settings form and `playbook upgrade` keep every other line byte
  for byte.

### 4.5 The prompt

`draft_prompt()` for a first touch replaces the `SHAPES[FIRST_TOUCH]` paragraph
with a framework block when the framework is not `house`:

```
--- framework "Trigger, tension, trust" ---
Steps: Trigger, Tension, Trust, Question.
<instructions>
--- end ---
```

Everything else stays: channel rules (with `max_words` lowered to the
framework's), language and culture norms, the brief, findings, offer line and
proof as data, the playbook body, the honesty rules. The playbook's Voice
section wins over a framework on wording, greeting, sign-off and formality;
the prompt says so in one line.

Two small changes to `DRAFT_SCHEMA`, both **optional** properties (not in
`required`), so the `house` prompt text stays as it is:
- `framework` (string, the id that was asked for; Python checks it matches when
  given, and fills it in when absent).
- `parts`: list of `{step, quote}`, where `quote` is the first few words of the
  sentence that carries that step. The card uses it to mark the parts. A
  `quote` that is not found in the body is dropped silently; `parts` is never a
  hard check. The framework block asks for it; `house` drafts may omit it.

Token cost: a framework block is at most ~230 tokens and replaces a ~150-token
paragraph, so about +50 to +100 tokens per draft, plus ~30 for `parts`.

### 4.6 Checks

**Per framework**, through `CheckContext` (new field `framework: dict`):
- question count must be inside `questions`, intersected with the channel's
  rule (a LinkedIn connection note still allows 0 or 1);
- body words at most `min(max_words, body_max_words)`;
- `proof = "required"`: `proof_used` must hold at least one line;
- `framework` in the answer must be the one asked for.

`offer_line = "never"` is a prompt instruction only. A paraphrased offer
cannot be detected reliably, so it is not a check.

**For every draft, any framework** (from Allred and Holland):
- **The deletion test** goes into the critic's `personal` rubric for first
  touches: "Find the sentence that is about them. If it were removed, would the
  message still fit another company of the same kind? If so, score 2 or less."
  No schema change.
- **About you vs about them:** a deterministic count of second-person words
  (you, your, du, dein, euch, je, jij, jullie, tu, vous, ...) against
  first-person words (I, my, ich, mein, ik, mijn, je, mon, ...) per language,
  shown on the card ("about you 3, about them 5") and flagged when first person
  wins. A flag, not a refusal: the offer line is first person by nature. French
  `je` is first person; `tu`/`vous` second.
- **Proof in the message's language.** Today the prompt says "cite only these,
  word for word, in proof_used", and drafts copy English proof lines into German
  messages (seen in the reference folder on 17 Oct). The prompt changes to:
  "In the message, say the proof in the message's language; `proof_used` keeps
  the playbook's exact words." `clean_answer` already checks only `proof_used`,
  so no check changes. This is a prerequisite for every `proof = "required"`
  framework, and worth shipping on its own.

## 5. What people see

**Build form (Outreach page and `hermitcrm outreach build`).** A "Frameworks"
control with three modes, preset from the approach:
- **Default:** every draft uses `default`.
- **Split test:** `default` against `testing[0]`, one framework per contact,
  assigned by Hermit (7.2). Preselected while the approach has a test running
  (`testing` holds one id), so batches do not quietly skip the test.
- **Compare:** two or three frameworks per contact, the person picks (7.1).
  Shows the token multiple before building ("about 2x the drafting cost").

CLI: `--framework ID`, `--split ID`, `--compare ID,ID[,ID]`.

**Card.**
- "Built with: Trigger, tension, trust" with a popover: summary, steps,
  best for, watch out, evidence, and the "After <trainer>" line when the
  framework has one (4.7).
- The draft with its parts marked (a small label per sentence from `parts`).
- The about-you/about-them line.
- **Try another framework** next to Regenerate: a framework picker, then the
  normal regenerate path (the old text moves to `earlier` with
  `why = "framework: <old> -> <new>"`).
- In a split test, a "Test: A vs B" label. Changing the framework on a test
  item takes it out of the test, and the card says so.

**Help page `frameworks`.** The library as a readable page: one section per
framework with its "After <trainer>" line, evidence note and fictional
example, the CTA vocabulary, the "where they disagree" table from the source
(with neutral framework names), and how to add your own.

## 6. Asking the person

### 6.1 Setup: which frameworks fit how you sell

Where: a **Frameworks** panel per approach in Settings → Playbook; a link from
the welcome step "Say what you sell"; `hermitcrm playbook frameworks
[--approach NAME]` asks the same in the terminal. No AI.

Five multiple-choice questions:

| Key | Question | Choices |
|---|---|---|
| `deal` | What is a customer worth to you in their first year? | `small` under 5k · `mid` 5k to 25k · `large` 25k to 100k · `xl` over 100k (your currency) |
| `buyer` | Who do you usually write to? | `exec` founders and C-level · `lead` heads and VPs · `staff` managers and specialists |
| `volume` | How many new people do you contact in a week? | `low` under 20 · `mid` 20 to 75 · `high` over 75 |
| `research` | How long will you spend researching one person? | `minute` about a minute · `five` about five minutes · `fifteen` fifteen or more |
| `tone` | Which tone sounds like you? | `plain` plain and direct · `warm` warm and personal · `blunt` short and blunt |

**Recommendation, deterministic.** Each framework has a fit profile in
`default_frameworks.toml` (`[frameworks.<id>.fits]`, one list per key). Score =
number of answers inside the profile. Hard exclusions first:
- `connection-problem-objection` only when `research = fifteen` and
  `volume = low`;
- `pain-proof-yes-no` never when `buyer = exec` and `tone` is not `blunt` (the
  source: it "can read as pushy to senior or conservative buyers");
- `house` is never recommended; it is the baseline you compare against.

Default = highest score (ties: library order). Challenger = the next highest
with a **different `cta`**, so a test of the two changes something. Shown with
"why" lines built from the matching answers and the challenger's `watch_out`.

Starting profiles (config, tuned later; the tests pin the table):

| Framework | deal | buyer | volume | research | tone |
|---|---|---|---|---|---|
| trigger-tension-trust | mid, large | exec, lead | low, mid | minute, five | plain |
| truth-think-proof-talk | mid, large, xl | exec, lead | low, mid | five | plain, warm |
| premise-body-ask | large, xl | exec, lead | low, mid | five, fifteen | warm, plain |
| problem-solution-question | small, mid | lead, staff | mid, high | minute, five | plain, blunt |
| attention-interest-desire-action | mid, large | lead, staff | low, mid | five | plain, warm |
| connection-problem-objection | large, xl | exec | low | fifteen | warm |
| pain-proof-yes-no | small, mid | lead, staff | high | minute | blunt |

Accepting writes `frameworks.default`, `frameworks.testing` and
`frameworks.answers` for that approach in one commit
(`playbook: frameworks for <approach>`). The person can pick anything else by
hand; the recommendation is a suggestion, as everywhere in Hermit.

A new approach starts on `house` until the questions are answered. The
Outreach page shows a one-line hint ("Answer five questions to pick a framework")
until then.

### 6.2 On a draft: one question instead of a guess

A framework's `needs` names a fact the draft cannot do without. v1 has two:

| Need | Satisfied by | The card asks |
|---|---|---|
| `personal-connection` | a finding the person added (`source = "you"`) | "What do you share with them: a past employer, a school, a client, an interest?" |
| `premise` | a usable finding of kind `person` | "Something they wrote, said or shared? Paste it or add the page." |

When a need is not met at build time, the item is drafted with the approach's
`default` framework (or `house` if the default has the same need) and flagged:
"connection-problem-objection needs a personal connection; drafted with
trigger-tension-trust." The answer box writes a finding through the existing
`set_findings` path (source "you"), and **Regenerate with
connection-problem-objection** follows. Such an item is never part of a split
test, because a framework with `needs` is never a split-test arm (7.2).

The prompt keeps its rule "never invent familiarity", and the
`connection-problem-objection` instructions say a connection may only come from
a finding the seller added.

### 6.3 After a positive reply: what do you think did it?

When the person confirms interest (`confirm_reply`) or sets a positive outcome
on a message that came from an outreach item, the confirmation offers chips,
any number, all optional:

`the opening` · `the problem named` · `the proof` · `the question` · `the timing` · `the offer` · `don't know`

They are stored on the outreach item the reply answers, as `credit: [...]`.
They feed learning B's evidence cards ("positive; credited: the proof"). This is
the only signal that links an outcome to a reason, so it is asked, but one tap
skips it.

## 7. Compare mode and split tests

They answer different questions and are kept apart:

| | Compare | Split test |
|---|---|---|
| Question | Which do **I** prefer? | Which works on **prospects**? |
| Per contact | 2 to 3 versions, the person picks | 1 version, assigned by Hermit |
| Signal | a preference, at edit speed | an outcome, weeks later |
| Bias | the person's taste (fine: that is what it measures) | none by design |
| Learning use | evidence cards and lessons about voice | rates by framework, the experiment view |

### 7.1 Compare mode

- Build drafts one version per framework for each contact, each with its own
  critic pass. The card shows them side by side (stacked on a phone) with the
  framework name, the parts marked, and the checks.
- **Use this one** makes the chosen version the item's text: `ai_subject`,
  `ai_body`, `ai_pitch`, `angle`, `framework`, `proof_used`, `checks`, `critic`
  come from it. Editing, Mark ready and Regenerate work as today, on the chosen
  version only. Mark ready is not offered until one is chosen.
- The versions not chosen stay on the item in `variants` (with their
  framework, angle, AI text, checks, critic scores and `picked: false`), never
  edited, like `earlier`.
- An optional one-line reason with chips: `shorter` · `sounds like me` ·
  `better opening` · `stronger proof` · `better question` · `other`. Stored as
  `pick_tags` and `pick_note` on the item.
- Cost: N times the drafting and critic calls. Compare mode is off by default,
  N is 2 or 3, and the build form suggests a batch of 5. There is no cost cap
  (decided 16 Oct); the form shows the multiple.
- Findings are researched once and shared by all versions.
- **All versions use the same angle**, so they differ by framework only: the
  first version chooses the angle as today, and the others are asked for that
  angle (`ctx.angles` narrowed to it).

### 7.2 Split test

- **Assignment is Hermit's, deterministic and balanced.** Within one batch and
  one approach, contacts are ordered by fit (highest first, as Select already
  orders them) and alternate A, B, A, B. Both arms get a similar spread of fit,
  which is the main confounder the learning spec names. The batch id seeds
  which arm goes first, so a rebuild gives the same assignment.
- The web page builds one contact per request. The assignment is therefore a
  pure function of (batch id, the ordered selection), computed when the batch
  is previewed and passed with each per-contact request; the CLI computes the
  same function once. A contact dropped from the selection does not shift the
  others' arms within a batch already started.
- A framework with `needs` cannot be a split-test arm in v1: at build time
  half its arm would fall back to the default and the test would compare the
  default with itself. It can be the default, a compare version or a manual
  choice.
- The item records `framework` and `assigned: true`. Choosing another framework
  on it sets `assigned: false` (it leaves the test; the card says so).
- One split test per approach at a time: `testing` holds at most one id when
  used for a split.
- **Planned size and a stop rule.** `learning_test_sends` (default 40 per arm).
  Below it the experiment view shows counts only: "A: 14 sent, 2 replied, 1
  positive · B: 13 sent, 1 replied, 0 positive · 27 of 80 planned". At or
  above it, it shows the Beta-smoothed rates the learning module already
  computes and says which arm is ahead **and by how little**. Hermit never ends
  a test by itself; the person moves the winner to `default` with one click
  (one commit).

## 8. Recording and learning

- **`framework`** on the outreach item and, when sent, copied onto the
  interaction, exactly as `angle` is today (`sent_by_interaction`). The manual
  log form and `hermitcrm set` get a framework field like angle, so messages
  written by hand can be tagged and compared.
- **Item keys added:** `framework`, `assigned`, `variants`, `pick_tags`,
  `pick_note`, `credit`. **Interaction key added:** `framework`. All written
  only when non-empty, so existing files keep their bytes. One numbered
  migration covers both (idempotent, front matter only, normalises values,
  no-op for existing files), plus tests. Its number is the next free one when
  this is built; migration 11 is taken by `exemplars_used` on
  `ai/learning-exemplars`.
- **Learning:** `learning.DIMENSIONS` gains `framework`; `Signal` gains
  `framework`, `assigned`, `picked_over` (the frameworks not chosen),
  `pick_tags`, `credit`. `rates()` and the n ≥ 10 rule work unchanged.
  Evidence cards include the framework, the pick ("picked trigger-tension-trust
  over pain-proof-yes-no: shorter") and credit chips, so the distiller can propose lessons
  such as "For founders you choose trigger-tension-trust over pain-proof-yes-no (7 of 9)".
  A compare pick counts as a reviewed draft for the learning phases.
- **Experiment view** on the Learning page, per approach: the running split
  test (7.2), and a "Your picks" table from compare mode (framework, times
  shown, times picked, top pick reasons).
- **Messages tab and Reports:** a framework column and filter, and framework as
  a dimension in the outreach quality block, one dimension at a time, cells
  under 10 hidden (existing rules).

## 9. First test case: the reference folder

The reference folder sells interim and fractional sales leadership to
founders of 10 to 60 person B2B SaaS companies, in English, German and Dutch, by
email and LinkedIn, in batches of about 13.

- **Likely setup answers** (to be confirmed in the panel): deal `large`, buyer
  `exec`, volume `low`, research `five`, tone `plain`. With the profiles above
  that gives `trigger-tension-trust` as default and `truth-think-proof-talk` as
  challenger.
- **First experiment:** a split test of `house` against `trigger-tension-trust`
  on first-touch emails. In practice it tests "offer line, no required proof"
  against "proof line, no offer line". In the 13 drafts of 17 Oct the AI added a
  proof line to 6 and left it out of 7 on its own, so this turns an uncontrolled
  variable into a test. At about 13 a week, 40 per arm is about six weeks.
- **One compare batch of 5** with `house`, `trigger-tension-trust` and
  `truth-think-proof-talk` before the split test starts, to see which the seller
  prefers to send at all.
- **A custom framework** in the folder's own `frameworks.toml`: the seller's
  hand-written shape from section 1 of `MESSAGING.md` (open with them, name the
  gap, take the objection away, one low-commitment question). This exercises
  "add your own" and is a natural later challenger.
- **Prerequisite:** the proof-language fix in 4.6, since these drafts are mostly
  German.

## 10. Build order

| Phase | Scope | Done when |
|---|---|---|
| 0 | Proof in the message's language (prompt); deletion test in the critic rubric; about-you/about-them count and flag | a German draft says its proof in German; the flag shows on a card; existing tests green |
| 1 | `default_frameworks.toml` (all 8) + data-folder override + loader + `check`; `frameworks` in the approach front matter; framework block in `draft_prompt`; framework checks in `check_text`; `framework` on item and interaction + migration; Messages column; learning dimension; the `CLAUDE.md` credit exception line (4.7) | `outreach build --framework trigger-tension-trust` on the demo folder writes checked drafts with `framework` set; a folder without `frameworks` gets the same prompt text as after phase 0 |
| 2 | Build-form modes Default and Split; split assignment; card "Built with" + parts + popover; Try another framework; help page | a split batch of 6 on the demo folder gives 3 + 3, balanced by fit, stable on rebuild |
| 3 | Compare mode: variants, Use this one, pick chips, cost multiple | a compare batch of 3 contacts x 2 versions, one picked each, shows in the evidence cards |
| 4 | Setup questions: Settings panel, CLI, recommendation table, welcome link | the five answers in the table of 9 produce the default and challenger named there |
| 5 | `needs` and the per-draft question; credit chips after a positive reply; experiment view on the Learning page | a connection-problem-objection draft without a connection falls back with the flag; adding one and regenerating uses it |

Phases 0 and 1 are useful on their own. Phase 2 is the earliest point the
reference folder's split test can start.

## 11. Later

- Premise buckets: a `premise` rank (1 to 5, Holland's order) on findings, from
  the research prompt; individual-research frameworks open with the best one.
  Needs a findings key, so a migration.
- Cadence frameworks as task templates when an item is marked sent.
- A framework arm next to C's angle bandit, once a folder has 30+ sends per
  framework.
- A LinkedIn voice-note script kind.

## 12. Tests

- Library: the package file loads; a data-folder file overrides one key and adds
  a framework; `check` reports an unknown key (warning), a bad `cta`, bad types
  and over-long `instructions` (errors); an approach naming an unknown framework
  is an error.
- `house` prompt text equals the phase-0 first-touch prompt byte for byte; a
  folder with no `frameworks` key builds exactly as before; `framework` and
  `parts` are optional in the schema.
- Prompt: the framework block replaces the shape paragraph; Voice-wins line
  present; `example` and `after` never in the prompt.
- Names (4.7): no shipped id or `name`, template or prompt contains a trainer's
  method name or brand (a fixed list: "Triple T", "4T", "3x3",
  "SMYKM", "Show Me You Know Me", "Poke the Bear", "JM Spear", and
  "Spear" or "Show you know" in an id or name); the popover and help page show
  "After <trainer>" only when `after` is set.
- Checks: question bounds (incl. `reply-invite` with 0), `max_words` takes the
  lower limit, `proof = required` without `proof_used` is refused once and then
  shown, a mismatched `framework` answer is a problem; time, link and calendar
  checks still fire for every framework.
- About-you count per language, including French `je`; deletion test text in the
  critic prompt for first touches only.
- Split assignment: balanced by fit, deterministic per batch, the same from the
  web's per-contact requests as from the CLI, one test per approach, a framework
  with `needs` refused as an arm, `assigned` cleared by a framework change.
- Compare: N versions, shared findings, one angle across versions, Mark ready
  blocked until a pick, pick copies the right fields, unpicked versions
  untouched, pick tags stored.
- Recommendation: each hard exclusion; ties by library order; the challenger has
  a different `cta`; the reference answers give the pair named in section 9.
- Needs: fallback with flag; satisfied by a "you" finding; split arm follows the
  framework actually used.
- Migration: idempotent, front matter only, bodies byte for byte; files without
  the new keys unchanged.
- Learning: `framework` dimension in `rates()`; cards carry pick and credit.
- Web: the card, popover, compare view and the setup panel render on the demo
  folder; fixtures use fictional names only.

## 13. Decisions and calls

Decided by Gijs (18 Oct):
- Build for every Hermit user from the start, with the framework library, the
  setup questions and compare mode; the reference folder is the first test case.
- Names and credit, option (b): neutral framework names in the product, with an
  "After <trainer>" credit on the help page and the card popover, as a written
  exception to the no-real-people rule for authors of published methods (4.7).
  Rejected: (a) no credit anywhere; (c) the trainers' own method names.
  Following from it, the two ids that echoed a brand were renamed:
  `pain-proof-yes-no` (was `spear`) and `connection-problem-objection` (was
  `show-you-know-them`).

Calls made in this design (check while reading):
1. Frameworks are called **frameworks**, since "approach" already means offer
   plus ICP in Hermit.
2. Frameworks shape the **first touch only**; replies and follow-ups keep their
   templates.
3. **Hermit's call-to-action and honesty rules win over every framework.** The
   time-proposing and meeting-asking methods ship adapted (appendix).
4. `house` (today's recipe) is the default everywhere until a person chooses,
   so nothing changes on upgrade.
5. Choice of frameworks is **per approach**, in the `MESSAGING.md` front matter.
6. **Compare and split are separate modes**, because they measure different
   things.
7. Split assignment alternates by fit order inside a batch rather than random,
   for balance with small batches.
8. Planned split size 40 sends per arm, a setting; no automatic winner.
9. Hand-written messages can be tagged with a framework but are never part of a
   split test.
10. On LinkedIn the framework shapes the message after acceptance (`pitch`);
    the connection note keeps today's rule (no pitch, at most one question).
11. Blount's Hook, Relate, Bridge, Ask is left out because its definitions were
    inferred in the source.
12. "Ask them questions" is read as asking the person using Hermit (setup, a
    missing fact, credit after a reply), not as a change to how prospects are
    questioned.
13. Compare versions share one angle, so a pick says something about the
    framework rather than the argument.
14. A framework with `needs` is never a split-test arm in v1.

## 14. Open questions

None left. The naming question was decided on 18 Oct (section 13 and 4.7).

## Appendix: framework instructions

The text that goes into the prompt (`instructions`). The `house` text is
`SHAPES[FIRST_TOUCH]` unchanged. Every text below is written to Hermit's rules:
one question unless `questions` says otherwise, no meeting or time, no link,
never "I" as the first word, findings and proof only as given.

**problem-solution-question** (after 30MPC's 3x3).
Three short parts. First, a problem this person likely has right now, tied to
one usable finding they will recognise, in plain problem words, never a
category or buzzword. Second, one sentence on how the seller solves it, carried
by one proof line. Third, one small question about whether the idea is worth a
look. Never ask for a meeting. Under 70 words. The subject is short, tied to the
finding, and reads like a note between colleagues, not a promotion.
*Adaptation: none needed.*

**attention-interest-desire-action** (after John Barrows' AIDA).
Four steps. Attention: the first sentence is a specific fact about them from a
usable finding; no self-introduction in the first ten words. Interest: tie it
to a business problem their role cares about. Desire: what becomes possible
once it is fixed, with one concrete example (a proof line if one fits). Action:
one step smaller than a meeting that the seller can really offer according to
the playbook's Offer section, asked as the only question. Under 90 words. The
subject is about them.
*Adaptation: "a one-pager" only when the playbook offers one, so nothing is
promised that does not exist.*

**truth-think-proof-talk** (after Josh Braun's 4T).
Four parts. Truth: something observable and true about them, from a usable
finding, that shows this is not a mass mail. Think: one neutral observation, a
statement and not a question, that names a problem they may not have noticed;
do not steer them toward a yes. Third-party proof: one proof line about similar
companies, never a claim about the product. Talk: a low-pressure question that
makes no an easy answer. Use the words the playbook's Personas and Voice
sections use for the problem, not marketing words. Under 80 words. The subject
names the Truth.
*Adaptation: Think is a statement, so the message keeps one question.*

**trigger-tension-trust** (after Jason Bay's Triple T).
The first line makes clear the message is meant for them: a usable finding,
ideally a trigger such as a hire, a launch or a funding round. Then one
sentence on the problem that trigger usually creates, in plain words; never
"all-in-one", "single source of truth", "AI-powered" or similar. Then one proof
line in a sentence; do not explain how the offer works and do not state the
offer line. End with one easy-to-answer question, such as whether this is on
their radar right now. Under 60 words. The opener must connect to the rest of
the message.
*Adaptation: none needed.*

**premise-body-ask** (after Becc Holland).
Four to five short lines. Premise: the reason for writing to this person, taken
from the best usable finding in this order: something they wrote or said;
something they shared or commented on; their profile or headline; a personal
interest; a company signal. Body: value that follows directly from that
premise. Ask: one concrete question tied to the issue raised, followed by a
clean way out (for example: if it is not relevant, say so and there will be no
chasing). No self-praise such as awards or rankings, no "just checking in", no
telling them to report back, no slang or false familiarity. Under 80 words.
*Adaptation: Holland asks for a specific time; Hermit never proposes a time in a
first touch, so the ask is a question plus a clean exit.*

**connection-problem-objection** (after Sam McKenna's SMYKM).
Subject: two or three facts about them that only they would recognise together,
from usable findings. Open with the connection the seller added (a finding from
"you") and the seller's own view on it; never a bare name-drop, and never a
connection that was not given. Bridge to a specific, recognisable problem
people in their role commonly have. Name the objection they are probably
thinking and answer it in one sentence. Close with an open invitation to reply;
it may be a statement rather than a question (for example: if it is not
relevant, tell me and I will drop it). At most one question.
*Adaptation: McKenna's no-calendar-link close already fits; `questions = [0, 1]`.*

**pain-proof-yes-no** (after Justin Michael).
One to three sentences after the greeting. A pain or fear this person has, or a
recent event about them; a hint at the fix; one proof line with its specific
number. End with a question they can answer yes or no about their situation.
Never ask for minutes of their time or a meeting. No small talk, no "my name
is". Assertive and plain. The subject is one to three words. Greeting and
sign-off follow the culture norms. Under 45 words.
*Adaptation: "Worth 10 minutes, yes or no?" is a meeting ask, so the yes-or-no
question is about their situation; the greeting stays because the culture norms
win.*
