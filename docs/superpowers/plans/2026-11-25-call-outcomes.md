# Call Outcomes and Call Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An outbound call can record what happened on the line (call outcome) and what the call was for (call type). Both are lists you can edit in Settings, with defaults. They show on the log/edit form only for an outbound call, show on the timeline, can be set from the CLI and MCP, and are described in Help.

**Architecture:** Two new optional front-matter keys on interactions, `call_outcome` and `call_type`, left out of the file when empty (same pattern as `framework` and `lead_rule`). The allowed names come from two new `config.toml` keys, `call_outcomes` and `call_types`, handled exactly like the existing `outcomes`: defaults in code, a Settings section, the store checks against them, live reload without a restart. Values are stored as the configured name, verbatim. Migration 26 reserves the keys. The existing `outcome` key is **not** touched.

**Tech Stack:** Python 3, FastAPI + Jinja2 (`web.py`, `templates/`), TOML config (`setup.py`, `datafolder.py`), plain CSS, pytest.

**Spec:** this document. The source is Gijs's request of 2026-11-25:

> A. Call direction: Inbound, Outbound.
> For outbound calls: B. Call outcome: Connected, Conversation, Message to other human, Voicemail message, No answer, Busy, Rejected by automated call screening, Wrong number.
> C. Call type: Prospecting, Pipeline development.
> Describe them in help.

His decisions on follow-up questions (2026-11-25): call type is outbound only, the general outcome dropdown stays on calls, the lists are **editable in Settings**, and the help definitions below are approved as written.

## What exists already (read this first)

- **A. Call direction already exists.** Every interaction has `direction` (`out` / `in`, `models.Direction`), with radios on the form. Nothing new is stored for A. Help gets a short section saying what in and out mean for a call.
- **`outcome` is taken.** `Interaction.outcome` is the *message* outcome (config `outcomes`, `Store._coerce_outcome` at `store.py:863`, `Company.message_status` at `models.py:729`, the Messages tab). Do not reuse or rename it. It stays on the form for calls too.
- **The template to copy for editable lists is `outcomes`.** Follow every place it goes:
  - defaults: `models.DEFAULT_OUTCOMES`, and `store.DEFAULT_CONFIG["outcomes"]` (`store.py:159`), which `datafolder.render_config` writes into a new `config.toml` with a comment from `datafolder.CONFIG_DOCS` (`datafolder.py:102`)
  - `Store(outcomes=...)` (`store.py:365-383`) and its constructions at `web.py:946-952`, `cli.py:68` and `bulk.py:827`
  - live reload: `derived_settings` (`web.py:1068`) and the in-place update in `config_reloaded` (`web.py:1140`)
  - Settings: the parse/plan/save trio in `setup.py:826-862`, `POST /settings/outcomes` (`web.py:4428`), the form values at `web.py:3777`, the section `id="outcomes"` in `templates/settings.html:569-593`, the group list at `settings.html:14`
  - tests: `tests/test_settings.py:222-260`
- **The template to copy for a new interaction key is `lead_rule`:** `models.py` (dataclass, `interaction_to_frontmatter`, `INTERACTION_KEYS`, `interaction_from_dict`), `store.py` (`INTERACTION_COPY_FIELDS`, `create_interaction`, `update_interaction`), `export.py:73`, `migrations.m24_lead_rule`, `tests/test_lead_rule.py`.
- **An outbound call with a body already counts as a "message"** (`Interaction.is_message`, `models.py:441`) on the Messages tab. Leave that alone.
- **Do not build this as a custom field** (`fields.py`). A custom field shows on every channel and cannot be limited to outbound calls.

## Global Constraints

- Config keys and defaults (exact, lower case, the way the `outcomes` defaults are written):
  - `call_outcomes = ["connected", "conversation", "message to other human", "voicemail message", "no answer", "busy", "rejected by automated call screening", "wrong number"]`
  - `call_types = ["prospecting", "pipeline development"]`
- Stored value = the configured name, verbatim (`call_outcome: no answer`). Input matches a configured name case-insensitively, with surrounding whitespace trimmed and inner runs of whitespace collapsed, and is stored in the configured spelling. Nothing else is mapped.
- Both keys apply **only when `channel == "call"` and `direction == "out"`**.
- Each list needs at least one name; a duplicate (case-insensitive) is refused. Renaming or removing a name in Settings does **not** rewrite existing interactions. An old value stays readable and selectable on that interaction, the same rule as `outcome`.
- Agents keep their current config rights: `adjust.AGENT_CONFIG_KEYS`, `mcp.CONFIG_KEYS` and `history.CONFIG_KEYS` stay `("task_types", "outcomes", "silent_days")`. Do not add the new keys there.
- Front-matter key order on write: `... lead_rule, outcome, call_outcome, call_type, source, message_id, attachments`. Each new key is left out when empty, so existing files stay byte for byte the same.
- A new numbered migration (26) is required (repo CLAUDE.md: idempotent, front matter only, plus tests).
- Commit messages start with `ai:`. `.venv/bin/pytest` must pass before every commit. Fictional names only (`Acme GmbH`, `jane-doe`, `example.com`). No new runtime dependencies.

## Review Focus

1. **Switching channel or direction on the form after picking a call outcome.** Hidden `<select>`s still submit. Expected: an interaction saved as `email`, or as an inbound call, has neither key in its file, and the save is not refused. Test in Task 4 (`test_hidden_call_fields_are_not_saved_for_an_email`).
2. **Flip direction on an outbound call** (`POST /companies/{slug}/interactions/{id}/flip-direction`, `web.py:2455`, used on Pipeline radar rows). Expected: flipping to `in` works and clears both keys. Test in Task 2 (`test_flipping_an_outbound_call_to_in_clears_the_call_fields`).
3. **Settings changed after calls were logged** (a name renamed or removed). Expected: the interaction still reads; its edit form shows the old value as an extra selected option (as `macros.html:141` does for `outcome`); saving it unchanged keeps it; a *new* unknown value is refused, with the configured names in the message. Tests in Task 2 and Task 4.
4. **New names usable without a restart.** Expected: after `POST /settings/calls`, the store accepts the new names and the form offers them at once. Test in Task 3 (`test_new_call_names_usable_without_restart`).
5. **A custom interaction field already named `call_outcome` or `call_type`** in `fields.toml`. Expected: `fields.py:164` reports "already a built-in interaction field", not a crash, and the changelog tells the user to rename it. Test in Task 1 (`test_a_custom_field_named_call_outcome_is_reported_as_built_in`).

---

### Task 1: Model, defaults and serialisation

**Files:**
- Modify: `src/hermitcrm/models.py` (constants next to `DEFAULT_OUTCOMES` ~line 94; `Interaction` ~408; `interaction_to_frontmatter` ~982; `INTERACTION_KEYS` ~1019; `interaction_from_dict` ~1190)
- Modify: `src/hermitcrm/store.py` (`DEFAULT_CONFIG` after `"outcomes"` ~159, with a comment; `INTERACTION_COPY_FIELDS` ~306)
- Modify: `src/hermitcrm/datafolder.py` (`CONFIG_DOCS` entries for both keys, next to `"outcomes"` ~102)
- Modify: `src/hermitcrm/export.py:73`
- Test: `tests/test_call_outcomes.py` (new; copy the licence header and the `seeded` fixture from `tests/test_lead_rule.py`)

**Interfaces:**
- Produces:
  - `DEFAULT_CALL_OUTCOMES: tuple[str, ...]` and `DEFAULT_CALL_TYPES: tuple[str, ...]`, with the values from Global Constraints.
  - `is_outbound_call(channel: str, direction: str) -> bool`
  - `match_choice(value, choices: list[str]) -> str`: `""` for empty or `None`. Otherwise the configured spelling of the choice equal to the value case-insensitively (after the whitespace trimming and collapsing above). Otherwise the trimmed value unchanged, so an unknown value is never lost on read.
  - `Interaction.call_outcome: str = ""`, `Interaction.call_type: str = ""`
  - `DEFAULT_CONFIG["call_outcomes"]`, `DEFAULT_CONFIG["call_types"]` (lists)
  - `CONFIG_DOCS["call_outcomes"]` = `"Call outcome choices for an outbound call: what happened on the line."`; `CONFIG_DOCS["call_types"]` = `"Call type choices for an outbound call: what the call was for."`

- [ ] **Step 1: Write the failing tests:**

```python
def test_the_defaults_are_the_agreed_lists_in_order():
    assert models.DEFAULT_CALL_OUTCOMES == (
        "connected", "conversation", "message to other human", "voicemail message",
        "no answer", "busy", "rejected by automated call screening", "wrong number")
    assert models.DEFAULT_CALL_TYPES == ("prospecting", "pipeline development")
    assert DEFAULT_CONFIG["call_outcomes"] == list(models.DEFAULT_CALL_OUTCOMES)

@pytest.mark.parametrize("typed,stored", [
    ("No Answer", "no answer"), ("  voicemail   message ", "voicemail message"),
    ("", ""), (None, ""), ("left a message", "left a message")])
def test_match_choice_finds_the_configured_spelling(typed, stored):
    assert models.match_choice(typed, list(models.DEFAULT_CALL_OUTCOMES)) == stored

def test_an_outbound_call_round_trips_both_keys_in_order(): ...
    # list(meta) has call_outcome, call_type right after "outcome", before "source".

def test_an_interaction_without_call_fields_writes_no_such_keys(): ...

def test_a_new_config_toml_documents_both_keys():
    # datafolder.render_config() contains "# call_outcomes = [" and "# call_types = [".

def test_a_custom_field_named_call_outcome_is_reported_as_built_in(): ...
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_call_outcomes.py -v`. Expected: FAIL (`no attribute 'DEFAULT_CALL_OUTCOMES'`).
- [ ] **Step 3: Implement** the Produces list. On read, `interaction_from_dict` only trims (it has no config); matching against the list happens in the store (Task 2). Add both keys to `INTERACTION_KEYS`, `INTERACTION_COPY_FIELDS` and the export columns, after `outcome`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: all pass. (`tests/test_datafolder.py` may pin the rendered config; update it if it does.)
- [ ] **Step 5: Commit** `ai: interactions can carry a call outcome and a call type`.

---

### Task 2: Store validation against the configured lists

**Files:**
- Modify: `src/hermitcrm/store.py` (`Store.__init__` ~365; new `_coerce_call_fields` next to `_coerce_outcome` ~863; `create_interaction` ~1749; `update_interaction` ~1826)
- Modify: the `Store(...)` constructions at `src/hermitcrm/web.py:946-952`, `src/hermitcrm/cli.py:68` and `src/hermitcrm/bulk.py:827` (pass the config lists, or `store.call_outcomes` / `store.call_types` for the bulk copy)
- Test: `tests/test_call_outcomes.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `Store(..., call_outcomes: list[str] | None = None, call_types: list[str] | None = None)`, with attributes `self.call_outcomes` and `self.call_types` (defaults when `None` or empty).
  - `Store._coerce_call_fields(channel: str, direction: str, call_outcome, call_type, current_outcome: str = "", current_type: str = "") -> tuple[str, str]`
  - `create_interaction(..., call_outcome="", call_type="", ...)` and `update_interaction(..., call_outcome=..., call_type=...)`. `cli.create_fields` reads the signature, so `--set call_outcome=...` works for free.

Rules for `_coerce_call_fields`, per key:
1. `match_choice` against the store's list.
2. Not an outbound call: a non-empty value that differs from `current_*` raises `ValidationError({"call_outcome": "a call outcome is only for an outbound call"})` (for `call_type`: "a call type is only for an outbound call"). A value equal to `current_*` (carried over by an edit that changed channel or direction) is cleared to `""`.
3. Outbound call: `""`, a configured name, or a value equal to `current_*` is accepted. Anything else raises `ValidationError({"call_outcome": "unknown call outcome 'x' (allowed: connected, conversation, ...)"})`, the same shape as `_coerce_outcome`.

In `update_interaction`, run it after channel and direction are settled. Pass the given value when the key is in `fields`, else the old value, with `current_*` = the old values.

- [ ] **Step 1: Write the failing tests** (the `seeded` fixture):

```python
def test_an_outbound_call_keeps_its_outcome_and_type(seeded):
    it = seeded.create_interaction("acme", "call", "out", contact="jane-doe",
                                   call_outcome="Voicemail message", call_type="prospecting")
    meta, _ = split_file((seeded.root / "companies/acme/interactions" / f"{it.id}.md").read_text())
    assert meta["call_outcome"] == "voicemail message" and meta["call_type"] == "prospecting"

def test_an_unknown_call_outcome_is_refused_with_the_allowed_list(seeded):
    with pytest.raises(ValidationError, match="allowed: connected, conversation"):
        seeded.create_interaction("acme", "call", "out", contact="jane-doe", call_outcome="maybe")

def test_the_store_checks_against_its_own_lists(tmp_path):
    # Store(..., call_outcomes=["reached", "not reached"]) accepts "reached" and
    # refuses "connected".

@pytest.mark.parametrize("channel,direction", [("email", "out"), ("call", "in")])
def test_call_fields_on_anything_but_an_outbound_call_are_refused(seeded, channel, direction):
    with pytest.raises(ValidationError, match="only for an outbound call"):
        seeded.create_interaction("acme", channel, direction, contact="jane-doe", call_outcome="busy")

def test_flipping_an_outbound_call_to_in_clears_the_call_fields(seeded): ...
def test_editing_the_subject_keeps_the_call_fields(seeded): ...
def test_a_value_no_longer_in_settings_survives_an_unrelated_edit(seeded):
    # log with "busy", then seeded.call_outcomes = ["reached"];
    # update_interaction(subject="x", call_outcome="busy") keeps "busy".
```

- [ ] **Step 2: Run** them. Expected: FAIL (`unexpected keyword argument 'call_outcome'`).
- [ ] **Step 3: Implement** as described, and pass the config lists into every `Store(...)` listed under Files.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `ai: the store checks call outcome and type against the configured lists`.

---

### Task 3: The Calls section in Settings

**Files:**
- Modify: `src/hermitcrm/setup.py` (new trio after `save_outcomes` ~862)
- Modify: `src/hermitcrm/web.py` (`derived_settings` ~1068 and `config_reloaded` ~1140; settings page values ~3777; new route next to `/settings/outcomes` ~4428; template globals ~1426)
- Modify: `src/hermitcrm/templates/settings.html` (group list line 14: `'calls'` after `'outcomes'`; new section after the outcomes section, ending ~593)
- Modify: `src/hermitcrm/help/settings.md` (a `## Calls` subsection after the outcomes one, three sentences that point to Interactions)
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: Task 2's `store.call_outcomes` / `store.call_types`.
- Produces:
  - `setup.plan_calls(call_outcomes_raw: str | list[str], call_types_raw: str | list[str]) -> StepResult`: one name per line, via `parse_outcomes`. Errors keyed `call_outcomes` / `call_types`: `"Give at least one call outcome, one per line."`, `"Give at least one call type, one per line."`, `"Duplicate call outcome: X."`, `"Duplicate call type: X."`. `values = {"call_outcomes": [...], "call_types": [...]}`.
  - `setup.save_calls(data_dir: Path, call_outcomes_raw, call_types_raw) -> StepResult`: writes both with `set_config_values` and adds the message `"Call outcomes and types saved."`.
  - `POST /settings/calls` (form fields `csrf_token`, `call_outcomes`, `call_types`), redirects to `/settings#calls`, built like `settings_outcomes`.
  - Template globals `call_outcomes` and `call_types`: lists updated in place on reload, like `outcomes`, so the form sees new names without a restart.

Section copy: heading **Calls**, `how('/help/interactions#calls')`, summary `"What an outbound call can record: its outcome (what happened on the line) and its type (what it was for). One per line. Renaming one does not change calls already logged."`, then two textareas labelled **Call outcomes (one per line)** (rows 8) and **Call types (one per line)** (rows 3), and a Save button.

- [ ] **Step 1: Write the failing tests** in `tests/test_settings.py` (use `demo`, `make_client`, `token`, `cfg` as the outcomes tests do):

```python
def test_call_lists_saved_one_per_line(demo, tmp_path):
    # POST /settings/calls call_outcomes="reached\n  left voicemail \n\nno answer\n",
    # call_types="cold\nexpansion" -> 303 to #calls; cfg(demo)["call_outcomes"] ==
    # ["reached", "left voicemail", "no answer"]; the settings page shows both textareas filled.

def test_call_lists_refuse_empty_and_duplicates(demo, tmp_path):
    # empty call_types -> 400 with "Give at least one call type"; "busy\nBusy" -> "Duplicate call outcome: Busy."

def test_new_call_names_usable_without_restart(demo, tmp_path):
    # after saving ["reached"], app.state.store accepts call_outcome="reached" and
    # GET .../interactions/new?channel=call offers "reached".

def test_a_folder_without_the_keys_offers_the_defaults(demo, tmp_path):
    # the settings page textarea holds the eight defaults.
```

Add `"calls"` to `SECTIONS` in `tests/test_settings.py:33` if that tuple is meant to list every section (read the test that uses it first).

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_settings.py -v`. Expected: the new tests FAIL (404 on `/settings/calls`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: all pass (`tests/test_settings_toc.py` checks the section list; update it if it pins one).
- [ ] **Step 5: Commit** `ai: Settings lets you edit the call outcomes and call types`.

---

### Task 4: The form and the timeline

**Files:**
- Modify: `src/hermitcrm/web.py`: `interaction_values` ~1659 (defaults `""`); `interaction_create` ~3462, `interaction_edit` ~3503, `interaction_save` ~3518 (new `Form("")` params and values entries).
- Modify: `src/hermitcrm/templates/macros.html`: `interaction_form` ~104 (new row) and the timeline entry ~398.
- Modify: `src/hermitcrm/static/style.css:290`.
- Test: `tests/test_call_outcomes.py` (web tests; copy the `repo` / `app` / `client` fixtures from `tests/test_web.py:49-76`).

**Interfaces:**
- Consumes: the template globals from Task 3; `is_outbound_call` (Task 1); the store kwargs (Task 2).
- Produces: form field names `call_outcome` and `call_type`.

Behaviour:
- A new `<div class="row call-fields">` under the subject/outcome row with two selects, **call outcome** and **call type**. The first option of each is `""` with the text "not set", then the configured names. A current value that is not in the list stays as an extra selected option (copy `macros.html:141`).
- Visibility: the form has the class `is-call-out` when `values.channel == 'call'` and the direction is `out` (or empty, since out is the default). Extend the inline `onchange` on the channel select, and add one on the direction radios, so both recompute it. CSS: `form.interaction-form:not(.is-call-out) .call-fields { display: none; }`. No new JS file.
- Server side: in `interaction_create` and `interaction_save`, when `not is_outbound_call(channel, direction)`, set both to `""` before calling the store.
- Timeline: after the outcome line, when either is set: `<div class="call-outcome">call: {{ i.call_outcome }}{% if i.call_outcome and i.call_type %} · {% endif %}{{ i.call_type }}</div>`.

- [ ] **Step 1: Write the failing tests:** `test_the_form_offers_call_outcome_and_call_type` (`?channel=call` has both selects, "rejected by automated call screening", "pipeline development", and `is-call-out`), `test_the_form_hides_call_fields_for_linkedin`, `test_logging_an_outbound_call_saves_both` (303; the file has both; the contact page shows `call: no answer · prospecting`), `test_hidden_call_fields_are_not_saved_for_an_email` (303, not 400; no key in the file), `test_an_unknown_call_outcome_on_the_form_shows_the_error` (400, "unknown call outcome"), and `test_the_edit_form_keeps_a_value_no_longer_in_settings`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: all pass. Then check it by hand: `.venv/bin/hermitcrm init /tmp/x --demo`, start the app on it, and log an outbound call with "voicemail message" / "prospecting". Switch the channel to email and back, flip the direction radio, and confirm the row hides and shows. Rename a call outcome in Settings and confirm the form offers the new name at once. Take a screenshot as proof.
- [ ] **Step 5: Commit** `ai: log and edit forms ask an outbound call's outcome and type`.

---

### Task 5: CLI and MCP

**Files:**
- Modify: `src/hermitcrm/cli.py` (`NAMED_FIELDS` ~727; `add interaction` flags ~1588; the listing lines at ~457 and ~507 that print `outcome:`)
- Modify: `src/hermitcrm/mcp.py` (`add_interaction_tool` `given(...)` ~229; the tool schema ~641)
- Test: `tests/test_cli.py`, `tests/test_mcp.py`

**Interfaces:**
- Consumes: the store kwargs (Task 2).
- Produces: `hermitcrm add interaction COMPANY --channel call --direction out --call-outcome NAME --call-type NAME`, plus MCP `add_interaction` fields `call_outcome` and `call_type`.

- [ ] **Step 1: Write the failing tests:** `test_add_interaction_takes_call_outcome_and_type` (CLI, the file has both keys) and `test_add_interaction_tool_takes_call_outcome` (MCP: the same; an inbound call with `call_outcome` returns the store's "only for an outbound call" error as a tool error).
- [ ] **Step 2: Run** them. Expected: FAIL (`unrecognized arguments: --call-outcome`).
- [ ] **Step 3: Implement.** No argparse `choices`, because the lists come from config and the store checks them. The help text is `"outbound calls only; one of call_outcomes in config.toml"`. MCP schema: plain `text(description=...)` with the same wording, no `enum`. Print `call: <outcome> · <type>` in the two listing lines when set.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `ai: call outcome and type from the command line and MCP`.

---

### Task 6: Migration 26

**Files:**
- Modify: `src/hermitcrm/migrations.py` (new `m26_call_fields` after `m24_lead_rule` ~566; entry in `MIGRATIONS` ~629)
- Modify: tests pinning format 25 → 26: `tests/test_lead_rule.py:172`, `tests/test_migrations.py:78,100,133`, `tests/test_agentfiles.py:121,169`, `tests/test_outcomes.py:123,127`
- Test: `tests/test_call_outcomes.py`

**Interfaces:**
- Produces: `m26_call_fields(meta: dict) -> dict` and `Migration(26, "interactions may record a call outcome and a call type", "companies/*/interactions/*.md", m26_call_fields)`.

Behaviour for each of `call_outcome` and `call_type`: if the key is absent, nothing changes. If it is empty or `None`, drop the key. Otherwise trim it, collapse inner whitespace, and write the result if it differs. No matching against config (a migration has none), and never drop a value someone wrote. Return the **same object** when nothing changes.

- [ ] **Step 1: Write the failing tests:**
  - parametrised `test_the_call_fields_migration_normalises_and_is_idempotent`. Cases: `""` drops the key, `None` drops it, `"  no   answer "` becomes `"no answer"`, `"Left a message"` stays, a file without the keys stays.
  - `test_the_call_fields_migration_returns_an_unchanged_file_as_it_is` (`is meta`)
  - `test_interactions_have_migration_26` (`LATEST == 26`, the interactions glob)
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement**, then change the pinned `25`s listed above to `26`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: all pass. Also make a format-25 folder (`.venv/bin/hermitcrm init /tmp/y --demo`, then `echo 25 > /tmp/y/.hermitcrm-format`) and check that `.venv/bin/hermitcrm migrate --dry-run`, run in it, lists "Data format 25 → 26".
- [ ] **Step 5: Commit** `ai: migration 26 reserves call_outcome and call_type on interactions`.

---

### Task 7: Help, data format, architecture and changelog

**Files:**
- Modify: `src/hermitcrm/help/interactions.md`: add the two fields to the field list in "Logging one", and add a new `## Calls` section after `## Outcome`.
- Modify: `src/hermitcrm/help/data-format.md` ~164 (after `outcome`) and the config key list on that page, if it has one.
- Modify: `docs/ARCHITECTURE.md` ~150 (interaction keys, after `outcome`) and wherever it lists the config keys.
- Modify: `src/hermitcrm/help/changelog.md` (`## Unreleased`, new first bullet)
- Test: `tests/test_help.py` (existing tests still pass), plus `test_help_describes_every_default_call_name` in `tests/test_call_outcomes.py`.

Exact copy for `## Calls` (definitions approved by Gijs on 2026-11-25):

```markdown
## Calls

A call is logged like any interaction, with channel `call`. Its **direction**
says who rang: **out** (outbound) when you called them, **in** (inbound) when they
called you.

An **outbound** call has two more fields, which the form shows only when the
channel is `call` and the direction is `out`. Both are optional. You can change
both lists in [Settings](/settings#calls). These are the defaults:

**Call outcome**: what happened on the line.

- **connected**: you reached the person you called, but there was no real
  conversation: it was a bad time, they asked you to call back, or they hung up.
- **conversation**: you reached the person and talked with them about why you
  called.
- **message to other human**: someone else answered (a colleague, an assistant,
  reception) and you left a message with them.
- **voicemail message**: you left a message on their voicemail.
- **no answer**: it rang out and you left no message.
- **busy**: the line was busy, or the call dropped before it rang.
- **rejected by automated call screening**: an automated screen on their phone
  answered, asked who you were, and did not put you through.
- **wrong number**: the number does not belong to this person. Fix or remove it
  on the contact.

**Call type**: what the call was for.

- **prospecting**: opening a conversation with someone who is not yet a real
  opportunity in your pipeline.
- **pipeline development**: moving an existing opportunity forward: a follow-up,
  discovery, or agreeing next steps with an account already in your pipeline.

The call outcome is separate from **outcome** above. Outcome is what came of an
interaction and drives the Messages tab. Call outcome is only what happened on
the line. A voicemail can still lead to a reply.

In the file they are `call_outcome` and `call_type`, left out when empty, stored
as the name from your list. In `config.toml` the lists are `call_outcomes` and
`call_types`. Renaming or removing a name in Settings does not change calls
already logged: they keep the old name, and their edit form still offers it.
Changing a call's channel or direction so that it is no longer outbound clears
both. From the command line:
`hermitcrm add interaction COMPANY --channel call --direction out --call-outcome
"voicemail message" --call-type prospecting`.
```

Changelog bullet (top of `## Unreleased`):

```markdown
- **Outbound calls record a call outcome and a call type.** Log a call with
  direction out and the form asks what happened on the line (connected,
  conversation, message to other human, voicemail message, no answer, busy,
  rejected by automated call screening, wrong number) and what the call was for
  (prospecting or pipeline development). You can change both lists under
  **Settings > Calls**. Both show on the timeline and can be set with
  `--call-outcome` and `--call-type`. Your folder is migrated to format 26
  (nothing changes in your files unless they already had these keys). A custom
  interaction field named `call_outcome` or `call_type` now clashes with the
  built-in one: rename it in `fields.toml`. See [Interactions](/help/interactions#calls).
```

- [ ] **Step 1: Write the failing test** `test_help_describes_every_default_call_name`: the rendered `/help/interactions` contains every name in `DEFAULT_CALL_OUTCOMES` and `DEFAULT_CALL_TYPES`, and an element with `id="calls"` (see `tests/test_help.py:191`).
- [ ] **Step 2: Run** it. Expected: FAIL.
- [ ] **Step 3: Write** the help section, the data-format and ARCHITECTURE lines (in the style of the `lead_rule` and `outcome` entries: "optional, omitted when empty; one of `call_outcomes` in config.toml; ... migration 26 trims a hand-written one"), and the changelog bullet.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `ai: help describes call direction, call outcome and call type`.

---

## Out of scope (possible follow-ups, not in this plan)

- Reports / dashboards by call outcome (connect rate, conversations per 100 dials) and a call outcome filter on lists.
- Letting agents change `call_outcomes` / `call_types` through MCP `set_config` (agents' config rights stay as they are).
- Renaming a call outcome in Settings and rewriting the logged calls with it (as task types do with `rename_task_type`).
- `bulk.py` `set interactions` for call fields; a Wrong number outcome flagging the contact's phone; whether an outbound call should keep counting as a message on the Messages tab.
