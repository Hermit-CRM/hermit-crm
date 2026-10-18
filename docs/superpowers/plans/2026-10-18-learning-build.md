# Learning: build contract (section 7 of the spec)

Spec: `docs/superpowers/specs/2026-10-18-learning-approaches.md`. Scope decided
18 Oct: Phase 0 + A's extractor, trend line and suggestion cards + B in full
(cards, distill in `hermit` and `handoff` mode, Learning page, scoreboard,
phase promotion). C was built afterwards (`src/hermitcrm/exemplars.py`, migration 11). Open questions 2 to 4 use the spec's
assumptions (thresholds are config; reason chip asked above 15 words; `deal` =
first entry into a `valued` open stage).

Repo rules apply (CLAUDE.md): no new runtime deps, fictional names only,
deterministic writes, `.venv/bin/pytest` green, front-matter changes need a
numbered migration.

## Capture (outreach.py, migration 10) — done first, by the lead

- `EDIT_TAGS = ("too-long", "wrong-tone", "wrong-pain", "bad-finding",
  "wrong-fact", "cliche", "other")`. `TrackedEdit.tags: list[str]`, written only
  when non-empty (existing files keep their bytes). `track_edit(item, note,
  when, tags=())`; `save_text(..., tags=())` and `mark_ready(..., tags=())`
  pass them through; unknown tags are dropped.
- `Item.lessons_used: list[str]`: ids of the lesson lines that were in the
  draft prompt; written only when non-empty. Set in `_apply_draft` from
  `Draft.lessons_used` (filled by `AIDrafter.draft` via
  `learning.lesson_ids(playbook_text_for_the_approach)`).
- Migration 10, `outreach/*.md`: normalise `lessons_used` and edit `tags`
  (strings, lower case, known tags; empty dropped). No-op for existing files.
- `REASON_CHIP_WORDS = 15`: the Outreach page offers chips when an edit
  changes more than this many words.

## `learning.py` — pure, reads the store, writes nothing except via the B
## functions marked (writes)

Lessons and ids
- A *lesson line* is a Markdown list line (`- ...`) under one of the three
  `### ` parts of `## Lessons` in an approach block of MESSAGING.md.
- `lesson_id(text) -> str`: `"L" + sha1(normalised text)[:6]` (lower case,
  collapsed white space, leading `- ` stripped). Stable, no stored ids needed.
- `lessons(root_or_pb, approach) -> list[Lesson]` (`id, part` in
  `worked|failed|open`, `text`).
- `lesson_ids(prompt_playbook_text) -> list[str]`: ids of lesson lines found in
  that text (worked + open + failed), document order, unique.

Signals (Phase 0)
- `RUNGS = ("sent", "replied", "positive", "deal", "won")`,
  `RUNG_VALUE = {"replied": 1, "positive": 3, "deal": 6, "won": 12}`.
- `ladder(store, item) -> dict[str, date]`: rungs reached with dates. `sent` =
  item.sent; `replied`/`positive` from the same rule as `response_to()`
  (first inbound after sending; positive = outcome interested/successful or a
  `replies.json` verdict interested); `deal` = first `stage_history` entry
  after sending into a stage in `stages.valued_names()` (fallback: role
  `open` named `discovery`); `won` = first entry into a stage with role `won`.
  Credit rules of the spec: `deal` only for first-touch and reply-to-interest
  items, `won` for every item in the thread.
- `@dataclass Signal`: `item_id, approach, angle, persona, channel, language,
  kind, model, findings_used, state, drafted, ready, sent, edit_words,
  rubber_stamp: bool, weight: float, rungs: dict, edits: list[EditFeatures],
  tags, notes, skip_reason, skip_note, regenerate_whys, lessons_used`.
- `RUBBER_STAMP_SECONDS = 20`, `RUBBER_STAMP_WEIGHT = 0.25`: ready within 20 s
  of drafted, with no tracked edit, counts at 0.25.
- `signals(store, approach="") -> list[Signal]` (reviewed = state in
  ready/sent/skipped or has edits). Recency weight: half-life
  `learning_half_life_days` (default 60).
- `phase(counts, config) -> Phase(number, name, weights: dict, counts,
  reason)`; thresholds and weights as section 5, overridable from
  config.toml key `learning_phases` (list of tables) and pinnable with
  `learning_phase_pin`. Per approach.

A: features and suggestions (deterministic, zero tokens)
- `edit_features(before: (subject,pitch,body), after, situational_words:
  set[str]) -> EditFeatures`: `words_delta, sentences_delta, opening_changed,
  questions_delta, gaps_filled, subject_changed, finding_removed,
  signoff_changed, greeting_changed, removed_phrases: list[str],
  situational: bool` (all replaced words are in findings/brief/names).
- `feature_table(signals) -> list[Row]` and `patterns(signals, last=10,
  min_hits=5, min_contacts=3) -> list[Pattern]` (feature, direction, hits,
  of, item ids).
- `trend(signals, batches=5) -> list[BatchStat]`: per `batch`: drafts,
  median edit words, ready-without-edit rate. Powers the "Since last time"
  line.
- `suggestions(store, signals, config) -> list[Suggestion]` with
  `id, kind in {"body_max_words", "never_write"}, text, current, proposed,
  evidence item ids`. Only length and banned phrases (spec A step 3).
- `accept_suggestion(store, suggestion_id)` (writes): `body_max_words` into
  messages.toml channel rules (or the existing override place for those
  rules), `never_write` into config.toml `outreach_never_write` (list,
  max 10). One commit `"ai: learn: <text>"` via the store's commit helper.
  `check_text` reports a phrase from `outreach_never_write` as a hard-check
  problem (wire in outreach.py, one test).
- `rates(signals, dimension) -> list[RateRow]`: Beta-smoothed (toward folder
  average, prior strength 10) per angle/persona/channel/language; `n < 10`
  flagged `too_few`.

B: cards, distill, lessons
- `cards(store, approach, since=watermark) -> list[Card]`: ~100–150 tokens
  each: id (item id), diff hunks only (`diff_parts`, del/add runs), names
  replaced by `[CONTACT]`/`[COMPANY]`, note, tags, skip reason+note,
  regenerate why, approach, angle, rung; unchanged drafts one line
  ("approved as is"). Pre-filter: drop situational edits, edits < 3 words
  unless the same removed phrase repeats, typo-only edits.
- `estimate_tokens(text) = ceil(len/4)`.
- `distill_prompt(approach, cards, current_lessons, rejected) -> str`;
  `PROPOSAL_SCHEMA` (JSON): `{"proposals": [{"op": add|merge|rewrite|
  retire, "part": worked|failed|open, "text", "replaces": [lesson ids],
  "cites": [card ids], "why"}]}`, max 5.
- `validate_proposals(data, cards, lessons, rejected) -> (list[Proposal],
  list[str] problems)`: cites must exist, ≥ 3 cards from ≥ 3 contacts for an
  `add`, `worked` never proposed directly from cards (forced to `open`),
  ≤ 12 active lessons after applying (else problem "merge or retire first"),
  never touches honesty/opt-out text, rejected texts never re-proposed.
- Data folder `learning/`: `state.json` (watermark per approach: last item
  `ready`/`skipped` time seen; rejected proposal texts by id; proposal list
  with status pending/accepted/rejected), `proposals.json` (handoff answer),
  `evidence-pack.md` (handoff prompt + schema). JSON with sorted keys and a
  trailing newline (deterministic). If the repo already has a TOML writer,
  `state.toml` is fine instead.
- `run(store, approach, enricher, config) -> RunResult` (writes): skips when
  no card passes the filter; `learning_distill = "hermit"` → strong-tier
  `enricher.runner(prompt, PROPOSAL_SCHEMA, tools="")`; `"handoff"` → writes
  the evidence pack and returns instructions. Then validate and store
  proposals as pending; advance watermark. One commit.
- `import_proposals(store, approach)` (writes): reads `proposals.json`,
  same validator, stored as pending.
- `accept(store, proposal_id, text=None)` / `reject(store, proposal_id)` /
  `retire(store, approach, lesson_id)` (writes): accept applies to
  MESSAGING.md through a new `playbook.set_lessons(text, approach, parts)`
  that reuses `_fill_lessons`; one commit each, message `"ai: learn: ..."`.
- `scoreboard(store, approach, signals) -> list[LessonScore]`: per lesson,
  items with/without it (`lessons_used`) by rung, counts only, plus edit
  words with/without; `promotion` hint per phase rules (section 5 rules 1,
  2, 3): edits stopped in its area for 10 drafts (phase ≤ 1); ≥ N positives
  with vs without (phase 2); deal/won ≥ 3 companies (phase ≥ 3); guardrail
  "edits doubled" flags instead of promotes. Hints only: the person moves a
  lesson with Accept/Retire.
- `status(store, approach, config) -> Status`: phase banner text, counts,
  cards that would be sent, prompt size and token estimate, pending
  proposals.

## Surfaces

CLI (`cli.py`): `hermitcrm learn report|status|run|import|accept ID|reject ID
|retire LESSON_ID|suggest|apply SUGGESTION_ID [--approach NAME]`. Plain text
output, exit 0/1 like the other commands. `help` docs page `learning`.

Web (`web.py` + `templates/learning.html`): `/learning` page: phase banner,
efficiency trend, pending proposals (Accept / Edit / Reject), lessons grouped
Worked / Didn't work / Still testing with scoreboard and evidence links,
suggestion cards (Apply), "Run now" / "Write evidence pack" / "Import".
Reports page: a "Style profile" + "Outreach quality" block whose numbers link
to rows (existing `/reports/rows` pattern). Outreach page header: "Since last
time" line. Draft card: "Followed N lessons" popover from `lessons_used`.
Reason chips on the edit form when the change > `REASON_CHIP_WORDS`.

Settings (config.toml): `learning_distill` (`hermit`), `learning_half_life_days`
(60), `learning_phases`, `learning_phase_pin`, `outreach_never_write`.
