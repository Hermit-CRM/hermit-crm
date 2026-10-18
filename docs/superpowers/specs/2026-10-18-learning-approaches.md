# Learning: three approaches for the outreach bot

Status: A's extractor, Phase 0 and B are built (`learning.py`); C is built (`exemplars.py`,
behind `learning_exemplars` and `learning_angle_sampling`, both off). Written 18 Oct 2026. Extends part 06
("learning from results") of [the outreach bot spec](2026-10-16-outreach-bot/06-quality.md),
which only sketched examples, a "What was wrong?" prompt and A/B.

## 0. What "learning" has to mean in Hermit

**Goal.** Each batch needs less editing than the last (efficiency), and over
time the drafts that go out produce more positive replies, deals and wins
(effectiveness). The person can see what was learned, say no to it, and undo it.

**Non-goals.** No cloud, no telemetry, no model training, nothing shared
between data folders. Learning never changes what is sent without the person
reading it (the bot still only drafts).

**What is already captured** (verified in `src/hermitcrm/outreach.py`):

| Signal | Where | Notes |
|---|---|---|
| The AI's original | `Item.ai_subject/pitch/body` | never touched |
| Each tracked edit | `TrackedEdit`: full text after, `words` changed, optional `note` (≤ 500 chars) | append-only |
| Edit size before ready | `Item.edit_distance` (word-level Levenshtein) | set in `mark_ready` |
| Regenerated drafts | `Earlier`: old original, its edits, the person's `why` | |
| Skip reason | `skip_reason` (`bad-fit`, `wrong-person`, `bad-timing`, `bad-draft`, ...) + `skip_note` | |
| Critic scores | `critic` (relevance, personal, tone, honesty) | AI opinion, not the person's |
| Findings used | `findings[].used`, `proof_used` | |
| Reply and outcome | `response_to()` → positive / replied / no reply; `replies.json` verdicts | |
| Pipeline | `Company.stage_history` (append-only); stages have roles (`open`, `won`, `lost`, `closed`, `parked`); an open stage can be `valued` (`discovery`, `offer` by default) | |
| Seed of a report | `edits_report(positive_only=…, with_notes_only=…)` | already prints edit diffs next to the answer |
| Where knowledge lives | `MESSAGING.md` per approach, with `Lessons` → Worked / Didn't work / Still testing | rides in every draft prompt (`PLAYBOOK_LIMIT` = 12,000 chars) |

**The constraint that shapes everything.** The reference folder has about 24
real conversations, 4 positive replies and 0 won. Outcome statistics are
nearly empty for months, and a public launch means other people start with
empty folders too. Edits arrive 10 to 50 times faster than outcomes. So:

> Early on, outcomes can only **validate or retire** a hypothesis. Edits are
> what **create** hypotheses. Any design that tries to learn what works from
> 4 positive replies is learning noise.

### Definitions used throughout

- **Outcome ladder** (a rung is reached once, with a date):
  `sent` → `replied` → `positive` (verdict interested / outcome interested or
  successful) → `deal` (first entry of the company into a `valued` open stage,
  `discovery` by default) → `won` (stage with role `won`).
- **Credit.** A rung is credited to the outreach items sent to that contact
  before it: first-touch gets `replied`/`positive`; the reply-to-interest item
  gets `deal` as well; `won` is shared by every item in the thread. Simple,
  explainable, and wrong in known ways (section 6).
- **Evidence phase.** Chosen by *counts*, not by the calendar (section 5).

### Shared foundation, needed by all three (Phase 0)

Built once, so the approaches differ only in what sits on top.

1. `learning.py`, a pure module (no I/O besides reading the store): turns an
   `Item` plus the store into a `Signal` record: edit profile, ladder rung with
   dates, attributes (approach, angle, persona, channel, language, kind, model,
   findings used). Derived on demand from the existing files, nothing stored.
2. `ladder(store, item)`: extends `response_to()` with the `deal` and `won`
   rungs from `stage_history`.
3. `stage_of_learning(counts)` → phase and weights (section 5). Pure, tested.
4. Two small optional capture additions: reason chips on a tracked edit
   (`TrackedEdit.tags`) and `lessons_used` on an item (which learned lines were
   in its prompt). Both are front-matter keys, so they come with one numbered
   migration (no-op for existing files) and tests, per the repo rules.
5. Rubber-stamp guard: a draft marked ready within seconds without edits
   (`drafted` → `ready` timestamps) counts at a fraction of the weight.
   Otherwise the system "learns" from a person who did not read the draft.

Phase 0 is useful alone: it powers the edit-trend line and the phase banner.

---

## 1. Approach A: "Counters and knobs" (deterministic, zero tokens)

**Idea.** Learning is counting. Describe every edit with features computed in
plain Python, count them, and when a pattern is consistent, propose a change to
a *setting or hard check*, not to prose.

### Small edits
- **Features per edit, free:** words shorter or longer; sentences removed or
  added; opening line replaced (`opening_line()`); question count changed
  (`count_questions()`); gaps `[ ]` filled; subject rewritten; a finding
  removed from the text; sign-off changed. `diff_parts()` already gives the hunks.
- **Situational vs style:** an edit whose replaced words appear in the
  findings, the brief, or the company/contact name is about *this prospect*
  and is not counted. What remains is style.
- **Pattern:** a (feature, direction) that appears in ≥ 5 of the last 10
  reviewed drafts, over ≥ 3 contacts. Example: "shortened the body in 8 of 10".
- **Applied as knobs:** lower `body_max_words`; add a phrase to a "never write"
  list enforced in `check_text`; set a preferred opening type; swap a greeting
  by post-processing (find/replace, no prompt tokens).
- **Reason chips** (too long / wrong tone / wrong pain / bad finding) give the
  counters a label without any AI.

### Positive responses, deals, wins
- Per-dimension rates (angle, persona, channel, language) with the existing
  rule of part 06: hide a cell under n = 10; show "n = 4, too few".
- **Weighting by shrinkage:** each cell's score is a Beta-smoothed rate pulled
  toward the folder average, so 1 of 1 never beats 12 of 30. Rungs combine by
  fixed value weights (replied 1, positive 3, deal 6, won 12) applied per phase
  (section 5).
- Outcome-conditioned feature check: do replied messages differ from the rest
  in length, question count, opening type? Reported as a difference *with n*,
  never as an instruction.

### Insights to the person
- New "Style profile" and "Outreach quality" blocks in Reports (existing
  pattern): every number links to its rows ("a number without its rows is a
  claim").
- **Suggestion cards:** "You shortened 8 of 10 drafts. Lower the word limit
  from 120 to 95?" Accept writes `config.toml`/`messages.toml` in one commit;
  Undo is the git revert already in the app.

### Technical architecture
```
outreach/*.md ─┐
interactions ──┼─► learning.signals() ─► features/aggregates (pure, in memory)
stage_history ─┘                              │
                                              ├─► Reports blocks (web.py)
                                              └─► suggestions ─► accept ─► config.toml
                                                                   (one commit, "ai: learn: ...")
```
New: `learning.py` (extractor, aggregator, suggester), a Reports block, a CLI
`hermitcrm learn report`. No new files in the data folder besides the settings
that already exist.

### Token efficiency
Zero extra AI calls. The only prompt growth is a short "never write" list
(≤ 10 phrases ≈ 100 tokens) if the person accepts it. Best possible.

### Build plan
1. Phase 0.
2. Feature extractor + tests on fixtures (`tests/outreach_fakes.py`). Done when
   a folder's edits print a feature table.
3. Reports block + suggestion cards for length and banned phrases only.
4. Outcome rates with shrinkage and the n ≥ 10 rule.

### Advantages
- Cheapest, fully deterministic, easy to test, explainable ("8 of 10, here are
  the rows"). Matches the repo's "keep writes deterministic".
- Works with the tiniest data and never hallucinates a lesson.
- Findings become *enforced* rules (hard checks), not suggestions the model may ignore.

### Disadvantages
- Learns *what* changed, not *why*. "Removed the first sentence" could be
  tone, a wrong fact or a cliché; the knob it proposes may be the wrong fix.
- Features are surface-level and language-bound (German `du` vs `Sie`,
  French formulas); every new feature is code.
- Cannot capture voice, structure or argument quality, which is most of what a
  good salesperson edits.
- Rules accumulate and fight each other; "never write X" lists grow stale.
- Outcome learning at n ≈ 24 shows mostly "too few"; the later phases feel empty.

---

## 2. Approach B: "Lessons distiller" (AI-curated playbook, human-approved)

**Idea.** Learning is writing things down. A periodic run turns *new* evidence
into short natural-language lessons in the place Hermit already reads them:
the `Lessons` section of the approach in `MESSAGING.md` (Worked / Didn't work /
Still testing). The person accepts, edits or rejects each one.

### Small edits
- **Evidence cards**, not raw texts. Each reviewed draft becomes ~100 to 150
  tokens: the diff hunks only (`diff_parts`, names replaced by `[CONTACT]`,
  `[COMPANY]`), the explainer note and chips if any, the skip/regenerate reason,
  the Approach and angle. Unchanged drafts become one line ("approved as is").
- **Deterministic pre-filter** (borrowed from A): drop situational edits, typo
  fixes, and edits under 3 words unless they repeat. This is what keeps the
  prompt small.
- **Distillation call** (one strong-tier call per run): "Here are 30 evidence
  cards and the current Lessons. Propose ≤ 5 changes: add, merge, rewrite or
  retire a lesson. Each must cite card ids." The reply is JSON (the Enricher
  already does schema-bound answers with no tools).
- **Lesson lifecycle:** `Still testing` (hypothesis) → `Worked` (confirmed) or
  `Didn't work` (refuted) → retired. A hypothesis needs ≥ 3 cards from ≥ 3
  contacts before it is even shown.
- **Applied for free:** the lessons are in the playbook, so every draft prompt
  already carries them. No retrieval, no new plumbing.

### Positive responses, deals, wins
- **Outcomes validate and retire, they do not invent.** A lesson in `Still
  testing` gets a scoreboard: items drafted with it (`lessons_used`) vs without,
  by rung. At small n this is shown as counts, not verdicts.
- **Contrastive step when positives exist:** feed *matched pairs* (positive vs
  no-reply, same persona, channel, language) to the same call; it proposes
  hypotheses, which go to `Still testing`, never straight to `Worked`.
- **Promotion rules by phase:** `Worked` requires the rung the phase cares
  about (section 5): early, "edits stopped happening in this area for 10 drafts";
  later, "≥ N positives with, fewer without"; later still, a deal or win in the
  thread. Contradicting evidence demotes it.
- **Hold-out (only when volume allows, Phase ≥ 2):** 1 draft in 5 omits a
  `Still testing` lesson so it can be compared. Off by default; it costs
  comparisons the folder may not have.

### Insights to the person
- A **Learning page** is the product: the phase banner ("31 reviewed drafts, 6
  replies, 2 positive: learning mainly from your edits and replies"), then
  lessons grouped Worked / Didn't work / Still testing, each with its evidence
  links, status chip, Accept / Edit / Reject / Retire.
- **Since last time** line on the Outreach page header: "2 new lessons, median
  edit 41 → 18 words over the last 3 batches".
- **On a draft card:** "Followed 3 lessons" popover. Seeing a lesson applied
  is how trust is built.
- The efficiency line (median edit size per batch, ready-without-edit rate) is
  the honest proof that learning works.

### Technical architecture
```
Phase 0 signals ─► pre-filter (deterministic) ─► evidence cards (watermarked)
                                                     │  one strong-tier AI call / run
                                                     ▼
                             proposals (stored, not applied) ◄── rejected list (never re-proposed)
                                                     │ person accepts
                                                     ▼
                    MESSAGING.md › Lessons  (playbook.py _fill_lessons, one commit)
                                                     │
                                  every draft prompt (body_for_ai) carries it
```
New: `learning.py` (cards, proposal schema, validation), `learning/state.toml`
in the data folder (watermark, rejected proposals, lesson ids; small, committed),
a Learning page, `hermitcrm learn run|status|accept`. `playbook._fill_lessons`
already rewrites only the Lessons part and keeps comments.
**Who runs the distillation is a setting (decided 18 Oct):**
`learning_distill = "hermit" | "handoff"`, default `"hermit"`.

- `hermit`: Hermit makes the strong-tier call itself through the Enricher and
  stores the validated proposals.
- `handoff`: Hermit writes `learning/evidence-pack.md` (the same prompt and the
  same JSON schema it would have sent) and the person's own agent answers into
  `learning/proposals.json`. `hermitcrm learn import` validates that file.
- Both modes end in the **same proposals file, the same validator, and the same
  accept/reject flow on the Learning page**. The setting only changes who reads
  the evidence pack, so the extra cost of supporting both is one pack writer
  and one `learn import` command. If the hand-off mode proves awkward, ship
  `hermit` only; nothing else depends on it.

### Token efficiency
Estimates, using characters ÷ 4:
- A draft prompt already carries up to 12,000 characters (~3,000 tokens) of
  playbook. Lessons must live inside a budget: **≤ 12 active lessons, ≤ ~600
  tokens**; a run that proposes a 13th must merge or retire one.
- A run is **~8k tokens in, ~1k out** for 30 cards plus current lessons. Run
  after each batch of ≥ 10 reviewed drafts, or weekly, whichever is later, and
  only on evidence past the watermark. A 10-draft batch costs ~50k tokens to
  draft, so learning adds roughly 10 to 15%.
- Evidence is compressed three ways: hunks not texts, pseudonyms, unchanged
  drafts as one line. Cheap tier for tagging if used; strong tier only for the
  one distillation call.
- Skip the run when nothing new passes the pre-filter.

### Build plan
1. Phase 0.
2. Cards + pre-filter + `learn status` (prints what a run *would* send, and its
   size). Done when the token estimate is visible before spending anything.
3. Distillation (`hermit` mode) + Learning page with accept/reject writing
   Lessons. Then `handoff` mode (`learn import`) if it stays small.
4. Lesson scoreboard (`lessons_used`), phase promotion rules, retirement.
5. Optional: hold-out, matched-pair hypotheses.

### Advantages
- Captures the *why* (explainer notes, reason chips, regenerate reasons), which
  is the actual voice.
- Reuses what exists: the `Lessons` section, the prompt plumbing, the playbook
  editor, `edits_report`, "proposals not writes". Least new surface for the
  value.
- Insight and application are the same artifact: the lessons a person reads
  are what the model gets. Nothing hidden.
- Works at small n; outcomes arrive later and slot into the lifecycle.
- Human-approved, git-versioned, trivially undoable.

### Disadvantages
- Nondeterministic and costs tokens per run; quality depends on the model.
- Overgeneralising from 3 cards is the main risk. Needs the support threshold,
  the confidence labels and contradiction checks, all extra logic.
- The prompt grows with every lesson; the cap forces curation work.
- Outcome attribution is weak: a reply cannot be tied to one sentence, so
  `Worked` stays partly a judgement.
- Lessons are advice to the model, not enforcement; it may ignore them (so
  hard rules still belong in checks, as in A).
- Needs the person to review proposals; if they never open the Learning page,
  nothing learns.

---

## 3. Approach C: "Exemplars and experiments" (memory by example, bandit by outcome)

**Idea.** Don't write rules, show good cases. The bot keeps a memory of
messages that worked and of corrections the person made, retrieves the closest
ones at draft time, and chooses angles with a small exploration policy.

### Small edits
- **Correction pairs.** A draft the person changed a lot, stored as
  (AI version → final version) with its note. Retrieved as **few-shot
  corrections** for similar drafts (same approach, persona, channel, language).
  The model sees "you wrote this, the user changed it to this", the strongest
  form of feedback for style and structure.
- **Retrieval without new dependencies:** features first (approach, persona,
  channel, language, kind), then word overlap (TF-IDF in plain Python) over
  findings and opening line. No embeddings, no vector database.
- **Quality filter:** only corrections with a note, or a repeated pattern, or
  the heaviest edits, so the memory stays small and meaningful.

### Positive responses, deals, wins
- **Positive exemplars.** The *final sent text* of messages that reached a rung
  becomes an exemplar scored by rung (`positive` 3, `deal` 6, `won` 12) and
  decayed by age. Draft prompts get the top 2 closest, with the instruction to
  copy the approach, not the words.
- **Angle selection by Thompson sampling** over (approach × persona × angle):
  Beta priors that start from the playbook's own ordering, updated by rung
  outcomes, so exploration is automatic and shrinks as evidence grows. It
  replaces "the AI chooses an angle" with "the AI chooses within the sampled
  angle", and shows *why* ("exploring: 4 sends so far").
- **Weights by phase** act on the exemplar score: early, correction pairs
  dominate retrieval; later, rung-scored positive exemplars do (section 5).

### Insights to the person
- On the card: "Modeled on: your message to Acme Robotics (positive reply, 3
  weeks ago)" with a link. Concrete and checkable.
- Angle table with credible intervals ("scale: 5 sends, 2 positive; wide,
  still exploring") and the next experiment.
- Exemplar manager: pin, exclude or delete an exemplar (a good message that
  worked for a one-off reason).

### Technical architecture
```
Phase 0 signals ─► exemplar index (derived, rebuilt on demand)
                      ├─ correction pairs   (AI→final, note, features)
                      └─ outcome exemplars  (final text, rung, age)
draft time: features ─► retrieve k=2 closest ─► {examples} block in draft_prompt()
            angle bandit (Beta per cell) ─► angle given to the drafter
decisions kept in data folder: pins/exclusions only (small toml)
```
New: `learning.py` (index, retrieval, bandit), a section in `draft_prompt()`,
`exemplars.toml` for pins and exclusions, an exemplar page.

### Token efficiency
- **Pay on every draft, forever:** 2 exemplars at ~150 to 250 tokens each is
  +300 to 500 tokens per draft (about +6 to 10% on a 5k-token prompt). There is
  no learning *run*, so the total can still be smaller than B at low volume,
  and larger at high volume.
- Cap the example length (opening plus the one differing paragraph only),
  retrieve 0 when nothing is close enough, and skip examples entirely for
  reply/follow-up kinds, which use fixed templates.

### Build plan
1. Phase 0.
2. Exemplar index + retrieval + a "what would be shown" preview. Done when
   a draft's prompt shows the chosen examples and their reason.
3. Correction pairs in the prompt (edits learning) behind a setting, off by default.
4. Outcome exemplars with rung scores.
5. Angle bandit, only once ≥ 30 sends exist per approach.

### Advantages
- Best at *voice and structure*, which are hard to put into rules.
- Adapts per draft and per segment; no long rule list to maintain.
- Outcome learning is the most direct here (the final text of what worked).
- Needs no AI call for learning itself; fewer moving parts to evaluate.

### Disadvantages
- Cold start is the worst of the three: with 4 positives there are ≤ 4
  exemplars, and 0 for deals and wins.
- **Parroting and homogenisation:** examples get copied, openers converge, and
  the "personal" quality drops. Needs the "copy the approach, not the words" guard.
- **Privacy:** other prospects' words enter a prompt; pseudonymisation of
  names is imperfect for free text.
- **Survivorship bias:** the exemplar set is whatever got replies, including
  luck and timing; there is no check that the text caused the reply.
- The bandit needs more volume than a solo seller has; with 10 sends per
  cell it mostly explores, which can look like randomness to the person.
- Hard to explain what was *learned*; "here is an example" is not a lesson.
- Token cost is permanent and scales with draft volume.

---

## 4. Side-by-side

| | A: Counters and knobs | B: Lessons distiller | C: Exemplars and experiments |
|---|---|---|---|
| Memory type | rules in settings | prose in the playbook | examples and priors |
| Learns from small edits | features only, no why | edits + notes → lessons | before/after pairs |
| Learns from outcomes | rates with n ≥ 10 | validates or retires lessons | scores exemplars, bandit |
| Works with 24 conversations | yes (little to say) | yes | weak (few exemplars) |
| Learning-run tokens | 0 | ~8k per run | 0 |
| Per-draft token cost | ~0 | ~0 (lessons capped ~600, already in prompt) | +300 to 500 |
| Explains itself | numbers with rows | readable lessons with evidence | "modeled on" + table |
| Deterministic | yes | writes yes, proposals no | retrieval yes, bandit random |
| New surface | Reports block | Learning page | exemplar page, prompt block |
| Main risk | wrong fix for right symptom | overgeneralising from 3 cards | parroting, cold start |
| Build size | smallest | medium | medium-large |

## 5. How the weighting changes over time

**Phase is chosen by counts, per approach**, never by date, so a slow folder
stays in the early phase and a fast one moves on. The banner on the Learning
page shows the phase and the numbers behind it; the person can pin a phase.

| Phase | Entered when (counts reached) | Optimises | Edits | Reply | Positive | Deal | Won |
|---|---|---|---|---|---|---|---|
| 0 Cold start | start | efficiency: fewer edits | 80 | 0 | 0 | 0 | 0 |
| 1 Style settles | ≥ 20 reviewed drafts | efficiency + first response | 50 | 30 | 20 | 0 | 0 |
| 2 Response | ≥ 30 sent, ≥ 8 replies | positive replies | 15 | 25 | 60 | 0 | 0 |
| 3 Pipeline | ≥ 5 deals created | deals | 10 | 10 | 30 | 50 | 0 |
| 4 Revenue | ≥ 3 won | wins | 10 | 5 | 15 | 30 | 40 |

(Percent of the learning weight. The remaining 20 in phase 0 is skips, regenerate
reasons and critic scores. The thresholds are starting guesses, not measured.)

**Rules that keep it honest:**
1. **Edits never reach zero.** From phase 2 they are a **guardrail**: a lesson
   that raises replies but doubles edit size is flagged, not auto-promoted.
2. **Later rungs outrank earlier ones, but only with support.** A rung is not
   used for *promotion* until it has ≥ 3 events from ≥ 3 distinct companies.
   Until then it is shown, not used.
3. **Outcome-conditioned edits:** from phase 2, edits made to messages that
   later reached `positive` are weighted up, and edits to no-reply messages are
   not trusted as much. This links the two signals: "what the person fixes"
   becomes "what the person fixes *when it worked*". `edits_report(positive_only=True)`
   is the starting point.
4. **Recency:** half-life ~60 days, so voice drift and a changed offer fade out.
5. **Per approach.** A lesson belongs to one approach; a second approach starts
   at phase 0.
6. **Smooth variant** (used in A and C): rung weight × n/(n + m), with m from
   a prior strength per rung (edits 15, reply 20, positive 10, deal 6, won 4),
   so weight moves as evidence arrives instead of switching at a threshold.

## 6. Known weak points (all approaches)

- **Credit assignment.** Deals come weeks later, from several messages and
  from things outside messaging (a referral, a demo). The ladder credits
  messages anyway; lessons derived from `deal`/`won` stay `Still testing`
  until backed by the same pattern in ≥ 3 companies.
- **Automation bias.** A person who approves without reading teaches nothing or
  the wrong thing; the rubber-stamp weight (Phase 0, item 5) is the guard.
- **Confounders.** Fit score, seniority and timing drive replies more than
  wording. Compare like with like (same persona, channel, language) or say "no
  comparison possible".
- **Telling a lesson from a fact.** "Don't mention X" can be a lesson or a
  correction of an error about one prospect. Notes and the situational filter
  decide; ambiguous ones go to `Still testing`.
- **Honesty rules always win.** Learning can add to the checks and the
  playbook, never remove an honesty or opt-out rule.

## 7. Recommendation

**Build B as the spine, fed by A's extractor, with C kept for later.**

- With 24 conversations, edits and the person's reasons are the only abundant
  signal, and B is the only approach that turns *why* into something reusable.
- B asks for the least new plumbing: the `Lessons` section, `_fill_lessons`,
  the prompt path and "proposals, not writes" all exist.
- A's deterministic extractor is the front end of B (it is what keeps B's token
  bill small) and A's hard-check rules cover what the model may ignore.
- C's exemplars become worth their permanent token cost once there are
  roughly 30 positives per approach. Phase 0 already stores everything C needs,
  so deferring it costs nothing.

Order of work: Phase 0 → A's extractor and the efficiency trend line (value on
day one, zero tokens) → B's cards, run and Learning page → B's scoreboard and
phase promotion → C's exemplar slot behind a setting.

## 8. Open questions (collected, none blocks Phase 0)

1. **Resolved 18 Oct: Hermit runs the distillation by default, with a
   `learning_distill = "handoff"` setting as an option.** Drafts, critic and
   reply classification already call the user's AI CLI, and lessons are
   proposals only, so the default stays inside D2 ("Hermit never builds a
   change itself"). If hand-off mode turns out hard, `hermit` only.
2. **Are 5 phases and these thresholds right for how many messages you send
   per week?** They are guesses; they are config, so safe to change.
3. **Should a person be asked for a reason chip on every edit, or only above N
   words?** Assumed: only above 15 words or on a repeated pattern.
4. **Is `valued` stage entry the right meaning of "deal created"?** Assumed yes
   (default: `discovery`).

Assumptions made without asking: learning is per data folder and local;
token figures are estimates (characters ÷ 4) to be replaced by measured counts
once `learn status` exists; derived signals are recomputed, not stored.
