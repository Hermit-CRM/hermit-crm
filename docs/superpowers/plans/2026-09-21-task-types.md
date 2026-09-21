# Task Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a to-do carry an optional, user-defined, coloured **type** (set up in Settings) that shows and filters on `/tasks`, the company and contact pages, the Companies list, the board and PIPELINE.md, replacing #39's derived `kind` column.

**Architecture:** A small new module `task_types.py` owns the palette, parsing of the `task_types` config line and the Settings-form planning. `Task`, `Todo` and `Company` get a `type` / `next_step_type` string, written only when set. `Store` validates types like outcomes (empty, configured, or unchanged) and can rename a type across the folder in one batch commit. Web templates render one `type_chip` macro whose colour is looked up by name at render time.

**Tech Stack:** Python 3.13, FastAPI + Jinja2, YAML front matter, TOML config, pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-task-types-design.md`

## Global Constraints

- Palette, exactly: `green`, `blue`, `amber`, `red`, `violet`, `grey`. Unknown colour → `grey`.
- Type names: whitespace collapsed, unique case-insensitively, at most 40 characters.
- Config line: `task_types = [{name = "...", colour = "..."}, ...]`, written by `setup.set_config_values`.
- Front matter: task map key `type`, company key `next_step_type`; both absent when empty (untyped files byte-identical).
- The literal filter value for "no type" is `(none)`.
- A new data folder has no types; with none configured and none in the data, every type control and column is hidden.
- Tests: `.venv/bin/python -m pytest` from the worktree; frozen clocks only (`frozen_client`, `FIXED_NOW`); never move dates.
- Commits: message starts `ai: `, author `Gijs Bos <6464256+Gijs-Bos@users.noreply.github.com>` (pass `-c user.name=... -c user.email=...`), trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File map

| File | Responsibility |
|---|---|
| `src/hermitcrm/task_types.py` (new) | `TaskType`, `PALETTE`, `from_config`, `names`, `colour_of`, `plan_rows`, `to_config` |
| `src/hermitcrm/setup.py` | `toml_value` writes dicts; `save_task_types` |
| `src/hermitcrm/models.py` | `Task.type`, `Todo.type`, `Company.next_step_type`, (de)serialisation, `COMPANY_KEYS` |
| `src/hermitcrm/store.py` | `task_types` on `Store`, `_coerce_type`, `add_task(type=)`, `update_company(next_step_type=)`, `set_todo_type`, `rename_task_type`, copy fields |
| `src/hermitcrm/web.py` | config → `app.state.task_types`, Settings route, `todo-type` route, add-task `type`, `/tasks` type column + next chip, Companies column, Jinja globals |
| `src/hermitcrm/templates/{macros,settings,tasks,companies,board,contact}.html` | forms, chips, Settings section |
| `src/hermitcrm/static/tokens.css`, `style.css` | chip colour tokens (light, dark, fallback) and `.type-chip` rules |
| `src/hermitcrm/pipeline.py` | `[type]` after the next step |
| `src/hermitcrm/cli.py`, `mcp.py` | `next_step_type` settable |
| `tests/test_task_types.py` (new), `test_models.py`, `test_store.py`, `test_web.py`, `test_settings.py`, `test_settings_toc.py`, `test_tokens.py`, `test_pipeline.py` | tests |

---

### Task 1: `task_types` module and config writing

**Files:**
- Create: `src/hermitcrm/task_types.py`
- Modify: `src/hermitcrm/setup.py` (`toml_value` ~line 62; new `save_task_types` after `save_outcomes` ~line 551)
- Test: `tests/test_task_types.py`

**Interfaces:**
- Produces: `TaskType(name: str, colour: str)`, `PALETTE: tuple[str, ...]`, `NONE = "(none)"`, `from_config(raw) -> list[TaskType]`, `names(types) -> list[str]`, `colour_of(types, name) -> str | None`, `plan_rows(names, colours, olds, delete: str, move: str) -> tuple[list[TaskType], dict[str, str], dict[str, str]]` (types, renames old→new, errors), `to_config(types) -> list[dict]`; `setup.save_task_types(data_dir, types) -> None`.

- [ ] **Step 1: Write the failing tests** in `tests/test_task_types.py`:

```python
"""Task types: the user's own labels for to-dos, kept in config.toml."""

from __future__ import annotations

import tomllib

from hermitcrm import task_types as tt
from hermitcrm.setup import save_task_types, set_config_values


def test_from_config_keeps_order_defaults_colour_and_drops_bad_entries():
    raw = [{"name": " pipeline   follow-up ", "colour": "green"},
           {"name": "prospecting", "colour": "pink"},
           {"name": "Prospecting", "colour": "blue"},   # duplicate, any case
           {"name": ""}, "lost deals", 7]
    assert tt.from_config(raw) == [tt.TaskType("pipeline follow-up", "green"),
                                   tt.TaskType("prospecting", "grey"),
                                   tt.TaskType("lost deals", "grey")]
    assert tt.from_config(None) == [] and tt.from_config("x") == []


def test_colour_of_is_none_for_a_type_not_in_settings():
    types = [tt.TaskType("prospecting", "blue")]
    assert tt.colour_of(types, "prospecting") == "blue"
    assert tt.colour_of(types, "gone") is None
    assert tt.names(types) == ["prospecting"]


def test_plan_rows_adds_renames_deletes_and_moves():
    names = ["pipeline follow-up", "lost deal revival", "prospecting", "new one"]
    colours = ["green", "amber", "blue", "violet"]
    olds = ["pipeline follow-up", "lost deals", "prospecting", ""]
    types, renames, errors = tt.plan_rows(names, colours, olds, delete="", move="2-up")
    assert errors == {}
    assert tt.names(types) == ["pipeline follow-up", "prospecting",
                               "lost deal revival", "new one"]
    assert renames == {"lost deals": "lost deal revival"}

    types, renames, _ = tt.plan_rows(names, colours, olds, delete="1", move="")
    assert "lost deal revival" not in tt.names(types) and renames == {}


def test_plan_rows_skips_the_blank_add_row_and_refuses_bad_names():
    types, _, errors = tt.plan_rows(["a", ""], ["green", "green"], ["a", ""], "", "")
    assert tt.names(types) == ["a"] and errors == {}
    _, _, errors = tt.plan_rows(["a", "A"], ["green", "blue"], ["", ""], "", "")
    assert "Duplicate" in errors["task_types"]
    _, _, errors = tt.plan_rows(["x" * 41], ["green"], [""], "", "")
    assert "40" in errors["task_types"]
    _, _, errors = tt.plan_rows([""], ["green"], ["lost deals"], "", "")
    assert "Delete" in errors["task_types"]


def test_save_task_types_writes_one_line_that_toml_reads_back(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('# mine\nport = 8765\n', encoding="utf-8")
    types = [tt.TaskType('say "hi"', "green"), tt.TaskType("lost deals", "amber")]
    save_task_types(tmp_path, types)
    text = cfg.read_text(encoding="utf-8")
    assert text.startswith("# mine\nport = 8765\n")
    assert sum(1 for line in text.splitlines() if line.startswith("task_types")) == 1
    assert tt.from_config(tomllib.loads(text)["task_types"]) == types
    set_config_values(cfg, {"port": 9000})          # other writes leave it alone
    assert tt.from_config(tomllib.loads(cfg.read_text())["task_types"]) == types
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_task_types.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'hermitcrm.task_types'`.

- [ ] **Step 3: Implement** `src/hermitcrm/task_types.py`. Copy the Apache licence header from `src/hermitcrm/fields.py` (lines 1-13, the licensing test checks it), then:

```python
"""Task types: labels you define in Settings and put on a to-do.

A type is only a label with a colour. It changes no date, stage or order.
Stored as one config.toml line, `task_types = [{name = ..., colour = ...}]`,
and on a to-do by name, so a rename rewrites the to-dos (Store.rename_task_type).
"""

from __future__ import annotations

from dataclasses import dataclass

PALETTE = ("green", "blue", "amber", "red", "violet", "grey")
NONE = "(none)"          # the filter value for a to-do without a type
MAX_NAME = 40


@dataclass(frozen=True)
class TaskType:
    name: str
    colour: str = "grey"


def clean(name) -> str:
    return " ".join(str(name or "").split())


def from_config(raw) -> list[TaskType]:
    """The configured types, in order; bad or repeated entries are dropped."""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for entry in raw:
        if isinstance(entry, str):
            entry = {"name": entry}
        if not isinstance(entry, dict):
            continue
        name = clean(entry.get("name"))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        colour = str(entry.get("colour") or "").strip().lower()
        out.append(TaskType(name, colour if colour in PALETTE else "grey"))
    return out


def names(types: list[TaskType]) -> list[str]:
    return [t.name for t in types]


def colour_of(types: list[TaskType], name: str) -> str | None:
    """The colour of `name`, or None when Settings no longer has it."""
    return next((t.colour for t in types if t.name == name), None)


def to_config(types: list[TaskType]) -> list[dict]:
    return [{"name": t.name, "colour": t.colour} for t in types]


def plan_rows(row_names: list[str], colours: list[str], olds: list[str],
              delete: str = "", move: str = ""):
    """Read the Settings form: one row per type plus a blank row to add one.

    `olds` carries each row's saved name, so an edited name is a rename.
    `delete` is a row index; `move` is "<index>-up" or "<index>-down".
    Returns (types, renames {old: new}, errors).
    """
    rows = []
    errors: dict[str, str] = {}
    for i, raw in enumerate(row_names):
        if str(i) == delete:
            continue
        name = clean(raw)
        old = clean(olds[i] if i < len(olds) else "")
        colour = str(colours[i] if i < len(colours) else "").strip().lower()
        if not name:
            if old:
                errors["task_types"] = (f"Give {old!r} a name, or use Delete to "
                                        "remove it.")
            continue
        if len(name) > MAX_NAME:
            errors["task_types"] = f"{name[:20]}...: at most {MAX_NAME} characters."
        rows.append([name, colour if colour in PALETTE else "grey", old])
    seen: set[str] = set()
    for name, _, _ in rows:
        if name.lower() in seen:
            errors["task_types"] = f"Duplicate task type: {name}."
        seen.add(name.lower())
    index, _, direction = move.partition("-")
    if index.isdigit() and rows:
        # `move` counts rows as the form showed them, before any delete.
        shown = [i for i, raw in enumerate(row_names)
                 if str(i) != delete and clean(raw)]
        if int(index) in shown:
            at = shown.index(int(index))
            to = at - 1 if direction == "up" else at + 1
            if 0 <= to < len(rows):
                rows[at], rows[to] = rows[to], rows[at]
    types = [TaskType(name, colour) for name, colour, _ in rows]
    renames = {old: name for name, _, old in rows if old and old != name}
    return types, renames, errors
```

In `src/hermitcrm/setup.py`, make `toml_value` write inline tables. Add this branch **before** the `isinstance(value, (list, tuple))` branch, and make the list branch recurse:

```python
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k} = {toml_value(v)}" for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(v if isinstance(v, dict) else str(v))
                               for v in value) + "]"
```

After `save_outcomes`, add:

```python
def save_task_types(data_dir: Path, types) -> None:
    """Write the task types (a list of task_types.TaskType) to config.toml."""
    from hermitcrm import task_types
    set_config_values(Path(data_dir) / "config.toml",
                      {"task_types": task_types.to_config(types)})
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_task_types.py tests/test_setup.py tests/test_licensing.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hermitcrm/task_types.py src/hermitcrm/setup.py tests/test_task_types.py
git -c user.name="Gijs Bos" -c user.email="6464256+Gijs-Bos@users.noreply.github.com" commit -m "ai: task types: palette, config line and the Settings form planner

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Store the type on tasks and the next step

**Files:**
- Modify: `src/hermitcrm/models.py` (`Task` ~388, `Todo` ~406, `Company` ~440, `todos()` ~565, `next_todo()` ~583, `task_to_dict` ~775, `_tasks` ~786, `company_to_frontmatter` ~822, `COMPANY_KEYS` ~900, company parse ~1024)
- Modify: `src/hermitcrm/store.py` (`COMPANY_COPY_FIELDS` ~222)
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Task.type: str = ""`, `Todo.type: str = ""` (last field, keyword), `Company.next_step_type: str = ""`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_models.py`; reuse its existing imports of `parse_company`/`dump` helpers. If the names differ, use the same round-trip helpers the file's existing `done_on` tests use):

```python
def test_a_task_type_round_trips_and_is_absent_when_empty(tmp_path):
    from hermitcrm.models import Task, _tasks, task_to_dict
    assert task_to_dict(Task("send deck")) == {"text": "send deck"}
    item = task_to_dict(Task("send deck", type="lost deals: EU #2"))
    assert item["type"] == "lost deals: EU #2"
    assert _tasks([item], {})[0].type == "lost deals: EU #2"
    assert _tasks([{"text": "x", "type": "  a   b "}], {})[0].type == "a b"


def test_next_step_type_is_written_only_when_set():
    from hermitcrm.models import Company, company_to_frontmatter
    c = Company(name="Acme", slug="acme", next_step="call")
    assert "next_step_type" not in company_to_frontmatter(c)
    c.next_step_type = "prospecting"
    assert company_to_frontmatter(c)["next_step_type"] == "prospecting"


def test_todos_carry_the_type_of_what_they_come_from():
    from hermitcrm.models import Company, Task
    c = Company(name="Acme", slug="acme", next_step="call", next_step_type="prospecting",
                tasks=[Task("deck", type="pipeline follow-up")])
    assert [t.type for t in c.todos()] == ["prospecting", "pipeline follow-up"]
```

Also add a byte-identity test using the file's existing store fixture pattern: write a company with a task and a next step but no type through `store.create_company` + `store.add_task`, read the file bytes, `store.load()`, `store.write_company(store.companies["acme"])`, and assert the bytes are unchanged and contain no `type`.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_models.py -q -k "type"`
Expected: FAIL, `TypeError: Task.__init__() got an unexpected keyword argument 'type'`.

- [ ] **Step 3: Implement**

`Task`: add `type: str = ""  # a task type from Settings; "" for none` after `done_on`.
`Todo`: add `type: str = ""` as the last field (after `index`).
`Company`: add `next_step_type: str = ""` after `next_step_status`.

`todos()`:

```python
        if self.has_next_step:
            out.append(Todo(self.next_step, self.next_step_due, self.next_step_done,
                            self.next_step_done_on, type=self.next_step_type))
        for i, t in enumerate(self.tasks):
            out.append(Todo(t.text, t.due, t.done, t.done_on, None, i, type=t.type))
        for person in self.contacts.values():
            for i, t in enumerate(person.tasks):
                out.append(Todo(t.text, t.due, t.done, t.done_on, person, i, type=t.type))
```

`next_todo()` done-fallback: `return Todo(self.next_step, self.next_step_due, True, self.next_step_done_on, type=self.next_step_type)`.

`task_to_dict`: after the `done` block, `if t.type: item["type"] = t.type`.
`_tasks`: before `out.append`, `kind = " ".join(str(item.get("type") or "").split())`, then pass `type=kind` to `Task(...)`.
`company_to_frontmatter`: after the `next_step_done_on` block, add
`if c.next_step_type:  # absent unless set, so older files stay byte-identical` / `meta["next_step_type"] = c.next_step_type`.
`COMPANY_KEYS`: add `"next_step_type"`. Company parse: `next_step_type=" ".join(_str(meta, "next_step_type").split()),` after `next_step_done_on=`.
`store.py` `COMPANY_COPY_FIELDS`: add `"next_step_type"` after `"next_step_done_on"`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_models.py tests/test_store.py tests/test_extra_keys.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**: `ai: tasks and next steps can carry a type (written only when set)`, with the same author and trailer as Task 1.

---

### Task 3: Store validation, retyping and rename

**Files:**
- Modify: `src/hermitcrm/store.py` (`Store.__init__` ~302, next to `_coerce_outcome` ~595, `update_company` ~725, `add_task` ~891, new methods after `delete_task`)
- Modify: `src/hermitcrm/cli.py:66` (pass `task_types=`)
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `task_types.from_config`, `task_types.names`, `Task.type`, `Company.next_step_type`.
- Produces: `Store(..., task_types: list[str] | None = None)`, `store.task_types: list[str]`, `store.add_task(slug, text, due=None, contact="", message=None, type="")`, `store.update_company(slug, next_step_type=...)`, `store.set_todo_type(slug, index: int | None, type: str, contact="", text="") -> None`, `store.rename_task_type(old: str, new: str) -> int`, `store.type_names_in_use() -> list[str]`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_store.py`, using its `store` fixture from conftest; set `store.task_types` directly):

```python
def test_task_types_are_checked_like_outcomes(store):
    store.task_types = ["prospecting", "lost deals"]
    store.create_company(name="Acme")
    store.add_task("acme", "send deck", type="prospecting")
    assert store.companies["acme"].tasks[0].type == "prospecting"
    with pytest.raises(ValidationError):
        store.add_task("acme", "x", type="nope")
    store.update_company("acme", next_step="call", next_step_type="lost deals")
    store.task_types = ["prospecting"]              # "lost deals" deleted in Settings
    store.update_company("acme", next_step_due="2026-09-30",
                         next_step_type="lost deals")   # unchanged legacy value is kept
    assert store.companies["acme"].next_step_type == "lost deals"
    with pytest.raises(ValidationError):
        store.update_company("acme", next_step_type="other")


def test_set_todo_type_changes_a_task_or_the_next_step(store):
    store.task_types = ["prospecting", "lost deals"]
    store.create_company(name="Acme")
    store.update_company("acme", next_step="call")
    store.add_task("acme", "send deck")
    store.set_todo_type("acme", 0, "prospecting", text="send deck")
    store.set_todo_type("acme", None, "lost deals")
    c = store.companies["acme"]
    assert c.tasks[0].type == "prospecting" and c.next_step_type == "lost deals"
    store.set_todo_type("acme", 0, "", text="send deck")
    assert store.companies["acme"].tasks[0].type == ""
    with pytest.raises(ValidationError):
        store.set_todo_type("acme", 0, "prospecting", text="something else")


def test_rename_rewrites_every_todo_in_one_commit(store):
    written = []
    store.on_write = written.append
    store.task_types = ["lost deals", "prospecting"]
    store.create_company(name="Acme")
    store.create_contact("acme", first_name="Jane", last_name="Roe")
    store.update_company("acme", next_step="call", next_step_type="lost deals")
    store.add_task("acme", "a", type="lost deals")
    store.add_task("acme", "b", type="prospecting")
    store.add_task("acme", "c", contact="jane-roe", type="lost deals")
    written.clear()
    assert store.rename_task_type("lost deals", "lost deal revival") == 3
    assert written == ['settings: task type "lost deals" renamed to '
                       '"lost deal revival" (3 to-dos)']
    c = store.companies["acme"]
    assert c.next_step_type == "lost deal revival"
    assert [t.type for t in c.tasks] == ["lost deal revival", "prospecting"]
    assert c.contacts["jane-roe"].tasks[0].type == "lost deal revival"
    assert store.type_names_in_use() == ["lost deal revival", "prospecting"]
    written.clear()
    assert store.rename_task_type("nobody", "x") == 0 and written == []
```

(`create_contact` is the store's existing contact constructor; if its name differs, use the one `tests/test_store.py` already calls.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_store.py -q -k "type"`
Expected: FAIL, `TypeError: ... unexpected keyword argument 'type'`.

- [ ] **Step 3: Implement** in `store.py`:

`__init__`: new parameter `task_types: list[str] | None = None`; body:
`# Allowed task types (config task_types, by name); "" is always allowed.` / `self.task_types = [str(t) for t in (task_types or [])]`.

Next to `_coerce_outcome`:

```python
    def _coerce_type(self, value, current: str = "", key: str = "type") -> str:
        """Empty, one of the configured task types, or unchanged (a type deleted
        in Settings stays on the to-dos that have it)."""
        value = " ".join(str(value or "").split())
        if value and value != current and value not in self.task_types:
            allowed = ", ".join(self.task_types) or "none set up in Settings"
            raise ValidationError({key: f"unknown task type {value!r} (allowed: {allowed})"})
        return value
```

`update_company`, after the `next_step_due` block:

```python
        if "next_step_type" in fields:
            new.next_step_type = self._coerce_type(fields["next_step_type"],
                                                   company.next_step_type, "next_step_type")
```

`add_task`: add `type: str = ""` after `message`; build `Task(text=text, due=..., type=self._coerce_type(type))`.

After `delete_task`:

```python
    @_locked
    def set_todo_type(self, slug: str, index: int | None, type: str,
                      contact: str = "", text: str = "") -> None:
        """Retype one to-do: task `index` of the company or `contact`, or the
        next-step fields when `index` is None."""
        if index is None:
            company = self._current(slug)
            if company is None:
                raise ValidationError({"slug": f"unknown company {slug!r}"})
            self.update_company(slug, next_step_type=type,
                                message=f"task: {slug} next step retyped")
            return
        company, record = self._task_owner(slug, contact)
        task = self._task_at(record, index, text)
        task.type = self._coerce_type(type, task.type)
        record.updated = self.now()
        where = f"{slug}/{contact}" if contact else slug
        self._write_owner(company, record)
        self._notify(f"task: {where} retyped")

    def type_names_in_use(self) -> list[str]:
        """Every type some to-do carries, sorted; the filters offer these too."""
        return sorted({t.type for c in self.companies.values() for t in c.todos()
                       if t.type})

    def rename_task_type(self, old: str, new: str) -> int:
        """Put `new` on every to-do typed `old`, in one commit. Returns the count."""
        count = 0
        with self.batch(f'settings: task type "{old}" renamed to "{new}"') as ctx:
            for company in list(self.companies.values()):
                changed = company.next_step_type == old
                if changed:
                    company.next_step_type = new
                    count += 1
                for t in company.tasks:
                    if t.type == old:
                        t.type, changed = new, True
                        count += 1
                if changed:
                    self.write_company(company)
                for person in company.contacts.values():
                    hit = [t for t in person.tasks if t.type == old]
                    for t in hit:
                        t.type = new
                    if hit:
                        count += len(hit)
                        self.write_contact(company.slug, person)
            ctx["message"] += f" ({count} to-do{'s' if count != 1 else ''})"
        return count
```

`WriteLock` is re-entrant (a `threading.RLock` plus a depth counter, `store.py` ~259), so the locked `set_todo_type` may call the locked `update_company`, and `rename_task_type` may write inside `batch`.

`cli.py:66`: `Store(root, silent_days=..., outcomes=config["outcomes"], task_types=task_types.names(task_types.from_config(config.get("task_types"))))` with `from hermitcrm import task_types` added to the imports.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_store.py tests/test_cli.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**: `ai: the store checks task types, retypes a to-do and renames a type everywhere in one commit`.

---

### Task 4: Settings section "Task types"

**Files:**
- Modify: `src/hermitcrm/web.py` (Store creation ~684, `refresh_config` ~752, Jinja globals ~852, `settings_page` context ~2431, new route after `/settings/outcomes` ~2720)
- Modify: `src/hermitcrm/templates/settings.html` (contents line 10; new section before `id="outcomes"` ~261)
- Modify: `src/hermitcrm/templates/macros.html` (new `type_chip` macro)
- Test: `tests/test_settings.py`, `tests/test_settings_toc.py` (must still pass unchanged)

**Interfaces:**
- Consumes: Task 1 and Task 3 APIs.
- Produces: `app.state.task_types: list[TaskType]`; Jinja globals `task_types()` → list of `TaskType`, `type_names()` → configured names plus names in use, `type_colour(name) -> str | None`, `palette`; macro `m.type_chip(name)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_settings.py`, using its `demo` fixture and `make_client`, as `test_settings_toc.py` does):

```python
def test_task_types_are_added_renamed_moved_and_deleted_in_settings(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    page = client.get("/settings").text
    assert '<section class="setup-step" id="task-types">' in page

    token = csrf(client)       # use the CSRF helper this file already uses for posts
    r = client.post("/settings/task-types", data={
        "csrf_token": token, "name": ["lost deals", "prospecting", ""],
        "colour": ["amber", "blue", "green"], "old": ["", "", ""]})
    assert r.status_code == 303
    assert [t.name for t in app.state.task_types] == ["lost deals", "prospecting"]
    assert app.state.store.task_types == ["lost deals", "prospecting"]   # live, no restart

    store = app.state.store
    slug = next(iter(store.companies))
    store.add_task(slug, "revive", type="lost deals")
    client.post("/settings/task-types", data={
        "csrf_token": token, "name": ["lost deal revival", "prospecting", ""],
        "colour": ["amber", "blue", "grey"], "old": ["lost deals", "prospecting", ""],
        "move": "1-up"})
    assert [t.name for t in app.state.task_types] == ["prospecting", "lost deal revival"]
    assert store.companies[slug].tasks[-1].type == "lost deal revival"

    client.post("/settings/task-types", data={
        "csrf_token": token, "name": ["prospecting", "lost deal revival", ""],
        "colour": ["blue", "amber", "grey"],
        "old": ["prospecting", "lost deal revival", ""], "delete": "1"})
    assert [t.name for t in app.state.task_types] == ["prospecting"]
    assert store.companies[slug].tasks[-1].type == "lost deal revival"   # kept

    r = client.post("/settings/task-types", data={
        "csrf_token": token, "name": ["a", "A", ""], "colour": ["green"] * 3,
        "old": ["", "", ""]})
    assert r.status_code == 400 and "Duplicate task type" in r.text
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_settings.py -q -k task_types`
Expected: FAIL (no `task-types` section).

- [ ] **Step 3: Implement**

`web.py`, next to the `outcomes = ...` line (~681):

```python
    app.state.task_types = task_types.from_config(config.get("task_types"))
```

Pass `task_types=task_types.names(app.state.task_types)` to `Store(...)`. In `refresh_config` add:

```python
        app.state.task_types = task_types.from_config(config.get("task_types"))
        store.task_types = task_types.names(app.state.task_types)
```

Import `from hermitcrm import task_types` at the top with the other `hermitcrm` imports.

Jinja globals (add to `templates.env.globals.update(...)`):

```python
        task_types=lambda: app.state.task_types,
        type_names=lambda: task_type_options(),
        type_colour=lambda name: task_types.colour_of(app.state.task_types, name),
        palette=task_types.PALETTE,
```

and define inside `create_app`, before the globals:

```python
    def task_type_options() -> list[str]:
        """Configured types in Settings order, then types only the data still has."""
        configured = task_types.names(app.state.task_types)
        return configured + [n for n in store.type_names_in_use() if n not in configured]
```

`settings_page` context: `"task_types_form": {"rows": app.state.task_types}` (the template adds one blank row).

Route, right after `settings_outcomes`:

```python
    @app.post("/settings/task-types")
    def settings_task_types(request: Request, csrf_token: str = Form(""),
                            name: list[str] = Form([]), colour: list[str] = Form([]),
                            old: list[str] = Form([]), delete: str = Form(""),
                            move: str = Form("")):
        check_csrf(csrf_token)
        types, renames, errors = task_types.plan_rows(name, colour, old, delete, move)
        if errors:
            result = setup_steps.StepResult(ok=False, errors=errors)
            return setup_invalid(request, result, "task-types")
        setup_steps.save_task_types(root, types)
        refresh_config()      # store.task_types first, so renamed values validate
        done = [f"{o} → {n} ({store.rename_task_type(o, n)})" for o, n in renames.items()]
        return flashed("/settings", "Task types saved" + (": renamed " + ", ".join(done)
                                                          if done else "."),
                       anchor="task-types")
```

`macros.html`, a new macro near `todo_actions`:

```jinja
{% macro type_chip(name) -%}
{%- if name -%}
{%- set colour = type_colour(name) -%}
<span class="type-chip type-{{ colour or 'grey' }}{% if not colour %} unknown{% endif %}"{% if not colour %} title="not in Settings"{% endif %}>{{ name }}</span>
{%- endif -%}
{%- endmacro %}
```

`settings.html`: in the contents line, insert `<a href="#task-types">Task types</a> &middot; ` before the Outcomes link. Before the Outcomes section:

```jinja
<section class="setup-step" id="task-types">
  <h2>Task types</h2>
  <p class="small">Your own labels for tasks and next steps, e.g. <em>pipeline follow-up</em>, <em>prospecting</em>, <em>lost deals</em>. A type is a label and a filter; it changes no dates. Renaming a type renames it on every task that has it. Deleting one leaves it on its tasks, in grey.</p>
  {{ step_errors('task-types') }}
  <form method="post" action="/settings/task-types" class="record-form">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <table class="task-types">
      {% for t in task_types_form.rows %}
      <tr>
        <td><input name="name" value="{{ t.name }}" maxlength="40" aria-label="type name"><input type="hidden" name="old" value="{{ t.name }}"></td>
        <td><select name="colour" aria-label="colour">{% for p in palette %}<option value="{{ p }}"{% if p == t.colour %} selected{% endif %}>{{ p }}</option>{% endfor %}</select></td>
        <td>{{ m.type_chip(t.name) }}</td>
        <td class="actions">
          {% if not loop.first %}<button type="submit" name="move" value="{{ loop.index0 }}-up" title="Move up">Up</button>{% endif %}
          {% if not loop.last %}<button type="submit" name="move" value="{{ loop.index0 }}-down" title="Move down">Down</button>{% endif %}
          <button type="submit" name="delete" value="{{ loop.index0 }}">Delete</button>
        </td>
      </tr>
      {% endfor %}
      <tr>
        <td><input name="name" value="" maxlength="40" placeholder="new type" aria-label="new type name"><input type="hidden" name="old" value=""></td>
        <td><select name="colour" aria-label="colour">{% for p in palette %}<option value="{{ p }}">{{ p }}</option>{% endfor %}</select></td>
        <td></td><td></td>
      </tr>
    </table>
    <button type="submit">Save task types</button>
  </form>
</section>
```

Match the existing CSRF field and `m` import in `settings.html`: copy exactly how the Outcomes form includes its token and whether the template imports `macros.html as m`. If the Outcomes form carries no hidden token (the CSRF value may be injected differently), do the same.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_settings.py tests/test_settings_toc.py tests/test_web_setup.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**: `ai: Settings has a Task types section: add, rename, move, delete, colour`.

---

### Task 5: Set the type where to-dos are made and listed

**Files:**
- Modify: `src/hermitcrm/web.py` (`task_add` ~1876, `task_create` ~1259, company form values/`company_values` for `next_step_type`, new route `POST /companies/{slug}/todo-type`)
- Modify: `src/hermitcrm/templates/macros.html` (`company_fields` next-step row ~186, `task_section` ~275, `task_list` ~312), `tasks.html` add form
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `store.add_task(type=)`, `store.set_todo_type`, `update_company(next_step_type=)`, `type_names()`, `m.type_chip`.
- Produces: form field `type` on every add-task form; `next_step_type` on the company form; route `POST /companies/{slug}/todo-type` (form: `index` str, `contact`, `text`, `type`, `back`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_web.py`; build a client whose config has types):

```python
@pytest.fixture
def typed_client(repo):
    config = dict(CONFIG, task_types=[{"name": "prospecting", "colour": "blue"},
                                      {"name": "lost deals", "colour": "amber"}])
    app = create_app(repo, config=config)
    app.state.store.clock = lambda: FIXED_NOW
    return TestClient(app, follow_redirects=False)


def test_a_task_gets_a_type_when_made_and_can_be_retyped(typed_client, client):
    c = typed_client
    post_company(c, name="Acme", next_step="Call Jane", next_step_due="2026-09-10",
                 next_step_type="lost deals")
    post_contact(c, "acme", first_name="Jane", last_name="Roe")
    c.post("/companies/acme/tasks", data={"text": "send deck", "type": "prospecting"})
    c.post("/tasks", data={"text": "ask Jane", "company": "Acme", "contact": "Jane",
                           "type": "prospecting", "back": "/tasks"})
    page = c.get("/companies/acme").text
    assert 'class="type-chip type-blue"' in page and 'class="type-chip type-amber"' in page
    assert '<select name="type"' in page

    r = c.post("/companies/acme/todo-type", data={"index": "0", "text": "send deck",
                                                  "type": "lost deals"})
    assert r.status_code == 303
    r = c.post("/companies/acme/todo-type", data={"index": "", "type": ""})
    page = c.get("/companies/acme").text
    assert page.count("type-amber") >= 1
    r = c.post("/companies/acme/todo-type", data={"index": "0", "text": "send deck",
                                                  "type": "nope"})
    assert "unknown task type" in r.headers["location"].replace("%20", " ")

    # without types set up, the forms have no type field at all
    post_company(client, name="Plain")
    assert '<select name="type"' not in client.get("/companies/plain").text
```

(If `post_company` does not pass unknown keys through to the form, post `next_step_type` with `c.post("/companies/acme/edit", ...)` the way `post_company` does internally.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_web.py -q -k retyped`
Expected: FAIL.

- [ ] **Step 3: Implement**

A shared select macro in `macros.html`:

```jinja
{% macro type_select(current='', autosubmit=false) -%}
{%- set options = type_names() -%}
{%- if options -%}
<select name="type" aria-label="type"{% if autosubmit %} onchange="this.form.submit()"{% endif %}>
  <option value="">{{ '(no type)' if autosubmit else '' }}</option>
  {% for n in options %}<option value="{{ n }}"{% if n == current %} selected{% endif %}>{{ n }}</option>{% endfor %}
</select>
{%- endif -%}
{%- endmacro %}
```

- `company_fields` next-step row: after the status select add `{% if type_names() %}<label>type {{ type_select(values.next_step_type) | replace('name="type"', 'name="next_step_type"') }}</label>{% endif %}`.
- `company_values` in `web.py` (and the company form POST handler that maps form fields to `update_company` / `create_company`): include `next_step_type`, the same way `next_step_due` is passed through. If `create_company` has no `next_step_type` parameter, call `update_company(slug, next_step_type=...)` right after creating when the value is non-empty.
- `task_section`: add a `type` column. Header `<th>type</th>` after `task`. Cell:

```jinja
<td>{% if type_names() and not t.done %}<form method="post" action="/companies/{{ company.slug }}/todo-type" class="inline">
  <input type="hidden" name="index" value="{{ '' if t.index is none else t.index }}">
  <input type="hidden" name="contact" value="{{ t.contact.slug if t.contact else '' }}">
  <input type="hidden" name="text" value="{{ t.text }}">
  {{ type_select(t.type, autosubmit=true) }}</form>{% else %}{{ type_chip(t.type) }}{% endif %}</td>
```

  The `{% else %}` branch already shows a chip on done rows and when no types are configured, so the first cell needs no change. Add `<label>type {{ type_select() }}</label>` to the add form (guarded by `{% if type_names() %}`). Bump the empty-row `colspan` to 6.
- `task_list` (contact page): the same type cell with `index` = `loop.index0` and `contact` = `contact`, plus `type_select()` in the add form. Bump `colspan` to 5.
- `tasks.html` add form: `{% if type_names() %}<label>type {{ m.type_select(form.type or '') }}</label>{% endif %}`; add `form["type"] = type` in `refused()`.
- `task_add` and `task_create`: add `type: str = Form("")` and pass `type=type` to `store.add_task`.
- New route next to `task_done`:

```python
    @app.post("/companies/{slug}/todo-type")
    def todo_type(request: Request, slug: str, index: str = Form(""), contact: str = Form(""),
                  text: str = Form(""), type: str = Form(""), back: str = Form("")):
        back = _task_back(request, slug, contact, back)
        try:
            store.set_todo_type(slug, int(index) if index.strip() else None, type,
                                contact=contact, text=text)
        except (ValidationError, ValueError) as exc:
            errors = exc.errors.values() if isinstance(exc, ValidationError) else [str(exc)]
            return flashed(back, "; ".join(errors), "tasks")
        return flashed(back, "Type saved", "tasks")
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_web.py tests/test_contact_new.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**: `ai: pick a task type when adding a task or next step, and retype from the list`.

---

### Task 6: `/tasks`: the type column and the "Next steps only" chip

**Files:**
- Modify: `src/hermitcrm/web.py` (`TodoRow` ~175, `task_columns` ~217, `_tasks_page` ~1213)
- Modify: `src/hermitcrm/templates/tasks.html`
- Test: `tests/test_web.py` (update `test_the_tasks_page_filters_every_task_in_one_table`)

**Interfaces:**
- Consumes: `Todo.type`, `task_type_options()`, `task_types.NONE`.
- Produces: `TodoRow.type`, `task_columns(type_options: list[str])`, query param `next=1`.

- [ ] **Step 1: Update the test.** In `test_the_tasks_page_filters_every_task_in_one_table`:
  - replace `kind = table("/tasks?f_kind=task")` / its assert with
    `nexts = table("/tasks?next=1")` / `assert "Call Jane" in nexts and "send the deck" not in nexts`.
  - replace both `back` / `location` values `"/tasks?f_kind=task"` with `"/tasks?next=1"` (the expected location becomes `"/tasks?next=1&flash=Task%20done#tasks"`).
  - replace `assert rows.count("next step</span>") == 3` with `assert rows.count('class="tag next-step"') == 3`.
  - add `assert 'Next steps only <span class="count">3</span>' in page`.

  Then add:

```python
def test_the_tasks_page_filters_by_type(typed_client):
    c = typed_client
    post_company(c, name="Acme", next_step="Call Jane", next_step_due="2026-09-10")
    c.post("/companies/acme/tasks", data={"text": "send deck", "type": "prospecting"})
    c.post("/companies/acme/tasks", data={"text": "untyped one"})
    table = lambda url: c.get(url).text.split('class="filters"')[1].split("</table>")[0]
    assert "send deck" in table("/tasks?f_type=prospecting")
    assert "untyped one" not in table("/tasks?f_type=prospecting")
    assert "untyped one" in table("/tasks?f_type=(none)")
    assert "send deck" not in table("/tasks?f_type=(none)")
    assert 'class="type-chip type-blue"' in table("/tasks")
    assert c.get("/tasks?f_kind=task").status_code == 200     # old links still load
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_web.py -q -k "tasks_page"`
Expected: FAIL.

- [ ] **Step 3: Implement**

`TodoRow.__init__`: replace `self.kind = ...` with `self.type = todo.type`.

```python
def task_columns(type_options: list[str] | None = None) -> list[Column]:
    cols = [
        Column("due", "due", "date"),
        Column("text", "what"),
    ]
    if type_options:
        cols.append(Column("type", "type", "enum", [*type_options, task_types.NONE],
                           getter=lambda r: r.type or task_types.NONE))
    return cols + [
        Column("who", "for"),
        Column("company_name", "company"),
        Column("stage", "stage", "enum", STAGES),
        Column("status", "status", "enum", ["open", "done"]),
        Column("done_on", "done on", "date"),
    ]
```

`_tasks_page`: `cols = task_columns(task_type_options())`. After the `when` filtering and before sorting:

```python
        nexts = params.get("next") == "1"
        next_count = sum(1 for r in rows if r.is_next)
        if nexts:
            rows = [r for r in rows if r.is_next]
```

(Count `next_count` *after* the column filters and the `when` filter, so it matches the view.) Add `"nexts": nexts, "next_count": next_count, "next_url": with_params(("next",), [] if nexts else [("next", "1")])` to the render context.

`tasks.html`:
- In `<p class="chips" id="when">`, after the date chips: `<a class="chip{% if nexts %} on{% endif %}" href="{{ next_url }}"{% if nexts %} aria-current="true"{% endif %}>Next steps only <span class="count">{{ next_count }}</span></a>`, and `{% if nexts %}<input type="hidden" name="next" value="1" form="task-filters">{% endif %}` after the `when` hidden inputs.
- Row cells: the *what* cell becomes `<td>{{ r.text or '(no text)' }}{% if r.is_next %} <span class="tag next-step">next step</span>{% endif %}</td>`. Replace the kind cell with `{% if type_names() %}<td>{{ m.type_chip(r.type) }}</td>{% endif %}`. Set the empty-row `colspan` to `{{ filter_columns | length + 1 }}`.
- Intro line: add "Filter by type to see one kind of work."

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_web.py tests/test_filters.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**: `ai: /tasks filters by task type; "Next steps only" replaces the kind column`.

---

### Task 7: Chips on the Companies list, the board and in PIPELINE.md, plus chip colours

**Files:**
- Modify: `src/hermitcrm/web.py` (`company_columns` ~147 and its caller ~1500)
- Modify: `src/hermitcrm/templates/companies.html`, `board.html`
- Modify: `src/hermitcrm/pipeline.py` (`_next_field` ~35)
- Modify: `src/hermitcrm/static/tokens.css`, `style.css`
- Test: `tests/test_web.py`, `tests/test_pipeline.py`, `tests/test_tokens.py`

**Interfaces:**
- Consumes: `Todo.type`, `task_type_options()`, `type_chip`.
- Produces: `company_columns(defs, type_options=None)` with column key `next_type`; CSS tokens `--type-<colour>-bg`, `--type-<colour>-fg` for each palette colour.

- [ ] **Step 1: Write the failing tests**

`tests/test_web.py`:

```python
def test_the_next_step_type_shows_on_companies_and_board(typed_client, client):
    c = typed_client
    post_company(c, name="Acme", next_step="Call Jane", next_step_due="2026-09-10")
    c.post("/companies/acme/todo-type", data={"index": "", "type": "prospecting"})
    companies = c.get("/companies").text
    assert "next type" in companies and 'class="type-chip type-blue"' in companies
    assert "Acme" in c.get("/companies?f_next_type=prospecting").text
    assert "Acme" not in c.get("/companies?f_next_type=(none)").text.split('class="filters"')[1]
    assert 'class="type-chip type-blue"' in c.get("/pipeline").text
    post_company(client, name="Plain")
    assert "next type" not in client.get("/companies").text
```

`tests/test_pipeline.py` (follow its existing company-building helper):

```python
def test_the_next_step_line_names_its_type():
    from hermitcrm.models import Company
    from hermitcrm.pipeline import _next_field
    c = Company(name="Acme", slug="acme", next_step="send deck", next_step_type="prospecting")
    assert _next_field(c) == "next: send deck [prospecting]"
    c.next_step_type = ""
    assert _next_field(c) == "next: send deck"
```

`tests/test_tokens.py`: extend the parametrised contrast list used by `test_default_colours_meet_the_contrast_rules` with one entry per palette colour and scheme, `("--type-<c>-fg", "--type-<c>-bg", 4.5, scheme)`, using the same tuple shape the list already has.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_web.py tests/test_pipeline.py tests/test_tokens.py -q -k "type or contrast"`
Expected: FAIL.

- [ ] **Step 3: Implement**

`company_columns(defs=None, type_options=None)`: after the `next_step` column, add

```python
        *([Column("next_type", "next type", "enum", [*type_options, task_types.NONE],
                  getter=lambda c: _next_type(c) or task_types.NONE)]
          if type_options else []),
```

with a module-level helper:

```python
def _next_type(company) -> str:
    todo = company.next_todo()
    return todo.type if todo and not todo.done else ""
```

Caller ~1500: `company_columns(app.state.custom_fields, task_type_options())`.

`companies.html`: after the next-step `<td>`, add `{% if type_names() %}<td>{{ m.type_chip(nxt.type if nxt and not nxt.done else '') }}</td>{% endif %}`. The header loops `filter_columns`, so it stays aligned because both use `type_names()`: `task_type_options()` is the same list.

`board.html`: inside the `next:` div, after the due text, add `{% if not nxt.done %} {{ m.type_chip(nxt.type) }}{% endif %}`. Add `{% import "macros.html" as m %}` at the top if the file does not import it yet.

`pipeline.py` `_next_field`: after the contact suffix, `if todo.type and next_step: next_step = f"{next_step} [{todo.type}]"`.

`tokens.css`, in `:root` after `--ok`:

```css
  /* task type chips: one pair per Settings colour */
  --type-green-bg: light-dark(#e3f1e8, #1d3527);
  --type-green-fg: light-dark(#17603f, #8fdcb0);
  --type-blue-bg: light-dark(#e3ecf7, #1d2b3d);
  --type-blue-fg: light-dark(#1f4f8a, #9cc3f0);
  --type-amber-bg: light-dark(#fbefd6, #3a2e14);
  --type-amber-fg: light-dark(#7a4a00, #f0c46c);
  --type-red-bg: light-dark(#fbe6e8, #3d1f24);
  --type-red-fg: light-dark(#9a1b2e, #ff9aa6);
  --type-violet-bg: light-dark(#eee6f6, #2e2340);
  --type-violet-fg: light-dark(#5b2d8a, #c9a8f0);
  --type-grey-bg: light-dark(#ece7dc, #302d28);
  --type-grey-fg: light-dark(#4d493f, #c4bdae);
```

and the light values of all twelve in the `@supports not (color: light-dark(...))` fallback block (`test_fallback_gives_every_colour_token_its_light_value` checks this). If a contrast test fails, darken the light `fg` or lighten the dark `fg` until it passes at 4.5. Keep the hue.

`style.css`, next to the `table.tasks .tag` rules:

```css
.type-chip { display: inline-block; border-radius: 3px; padding: 0 6px; font-size: 12px; white-space: nowrap; background: var(--type-grey-bg); color: var(--type-grey-fg); }
.type-chip.type-green { background: var(--type-green-bg); color: var(--type-green-fg); }
.type-chip.type-blue { background: var(--type-blue-bg); color: var(--type-blue-fg); }
.type-chip.type-amber { background: var(--type-amber-bg); color: var(--type-amber-fg); }
.type-chip.type-red { background: var(--type-red-bg); color: var(--type-red-fg); }
.type-chip.type-violet { background: var(--type-violet-bg); color: var(--type-violet-fg); }
.type-chip.unknown { font-style: italic; }
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_web.py tests/test_pipeline.py tests/test_tokens.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**: `ai: the next step's type shows on Companies, the board and PIPELINE.md, in its colour`.

---

### Task 8: CLI and MCP, help text, full suite

**Files:**
- Modify: `src/hermitcrm/cli.py` (field lists at lines 43 and 524), `src/hermitcrm/mcp.py` (lines 189 and 274)
- Modify: the Tasks help page under `src/hermitcrm/help/` that describes the kind column or next step (grep for `kind` / `next step`)
- Test: `tests/test_mcp.py`, `tests/test_cli.py`

- [ ] **Step 1: Write the failing test** in `tests/test_mcp.py`, following how that file calls its company-update tool with `next_step_due`: call it with `next_step_type="prospecting"` on a store whose `task_types = ["prospecting"]`, and assert that `store.companies[slug].next_step_type == "prospecting"`. Then call it with `"nope"` and assert that the tool reports the `unknown task type` error.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_mcp.py -q -k type`
Expected: FAIL.

- [ ] **Step 3: Implement.** Add `"next_step_type"` after `"next_step_due"` in the four field lists. In the MCP schema (~274), add `"next_step_type": text(description="A task type from Settings, or empty."),`. In `src/hermitcrm/help/`, replace any sentence about the `kind` column with one about types: "Give tasks a type (Settings → Task types) and filter the Tasks page by it; *Next steps only* shows each company's next step."

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS (1111+ tests from #39, plus the new ones).

- [ ] **Step 5: Commit**: `ai: next_step_type through the CLI and MCP; help explains task types`.

---

## After the tasks

1. Run the app on a free port against a **copy** of the sample data, never `~/Code/CRM` (check the port with `lsof -nP -iTCP:<port> -sTCP:LISTEN`). Click through the spec's 2-minute test in both themes and at 390px width.
2. Push `feat/task-types` and open the PR against `main`. The body contains the spec's "Gijs's 2-minute test" and the `🤖 Generated with [Claude Code](https://claude.com/claude-code)` line.
3. Stop. Gijs tests, then merges. The deploy and adding his three types follow the spec's Rollout.
