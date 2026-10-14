# Edit a Task Implementation Plan

> **For agentic workers:** execute task by task, in order. Steps use checkbox
> (`- [ ]`) syntax for tracking. Read `CLAUDE.md` first; its rules win over
> anything here.

**Goal:** Let the user change the **text** and the **due date** of an open
to-do (a company task, a person's task, or the company's `next_step` fields)
from every table that lists it: the company page (`/companies/{slug}#tasks`),
the contact page (`/companies/{slug}/contacts/{contact}`) and the Tasks page
(`/tasks`). Today a to-do can only be added, ticked off, reopened, retyped or
deleted; fixing a typo or moving a date means delete and re-add.

**Architecture:** One new store method, `Store.edit_todo`, shaped like the
existing `Store.set_todo_type`: `index=None` means the company's `next_step`
fields, otherwise task `index` of the company or of `contact`, with the same
stale-page check (`text`) that Done and Delete use. One new route,
`POST /companies/{slug}/todo-edit`, shaped like `POST /companies/{slug}/todo-type`.
One new Jinja macro, `todo_edit`, renders an **Edit** button that opens a small
inline form (`<details class="inline-edit">`, the pattern the company header
already uses) inside the row's actions cell.

**Tech stack:** Python 3.13, FastAPI + Jinja2, YAML front matter, pytest.

## Decisions (already made; do not reopen)

- **What can be edited:** text and due date. The type already has its own
  inline dropdown (`todo-type`), and who the task is *for* (company vs a person)
  stays fixed: moving a task between files is out of scope.
- **Only open to-dos are editable.** The Edit button is not rendered on done
  rows, and the store refuses with `{"task": "reopen the task before editing it"}`.
  Reason: `update_company` reopens a done next step whenever its text changes
  (ARCHITECTURE.md §3, `next_step_status`), so allowing edits on done items
  would behave differently for the two storage kinds.
- **Empty text is refused** (`{"text": "a task needs a line of text"}`, the
  message `add_task` already uses). **Empty due is allowed** and means "no date".
- **Text is whitespace-collapsed** (`" ".join(text.split())`), as `add_task` does.
- **Nothing changed → nothing written, no commit**, and the flash still says
  "Task saved". Keeps writes deterministic and git history clean.
- **No data format change.** No front-matter keys or values change, so **no
  migration**. `done`, `done_on` and `type` of an edited task are kept as is.
- **The next step is still derived** (`Company.next_todo()`: open to-do due
  first). Changing a due date may therefore change which row carries the
  `next step` tag. That is intended; the help text already says "change a due
  date to change what is next".
- **Commit messages** (they become the git log via `on_write`):
  - company task: `task: <slug> edited`
  - contact task: `task: <slug>/<contact> edited`
  - next-step fields: `task: <slug> next step edited`
- **Flash:** `Task saved`, anchored at `#tasks` (same `flashed(back, ..., "tasks")`
  call the other task routes use).
- **Where the Edit button appears:** company page Tasks table, contact page task
  table, Tasks page. Not on Home's "What needs doing" list and not on the small
  next-step line at the top of the company page (both keep Done only).

## Global constraints

- Tests: `.venv/bin/pytest` must pass before every commit. Use fixed dates in
  tests (the `store` fixture and `frozen_client` already freeze the clock at
  `FIXED_NOW = 2026-09-14 10:30`); never compute dates relative to today.
- Commits: message starts with `ai: `, ends with the attribution trailers the
  session tells you to use.
- Fictional names only (Acme, Jane Roe, example.com).
- No new dependencies.
- Try it by hand: `.venv/bin/hermitcrm init /tmp/x --demo`, then run the web app
  on that folder and edit a task on a company page and on a contact page.

## File map

| File | Change |
|---|---|
| `src/hermitcrm/store.py` | new `edit_todo` after `set_todo_type` (~line 1097) |
| `src/hermitcrm/web.py` | new route `todo_edit` after `todo_type` (~line 2414) |
| `src/hermitcrm/templates/macros.html` | new macro `todo_edit`; call it in `task_section` and `task_list` |
| `src/hermitcrm/templates/tasks.html` | call `m.todo_edit` in the actions cell |
| `src/hermitcrm/static/style.css` | layout of the open edit form inside `td.actions` |
| `src/hermitcrm/help/tasks.md` | new "Changing a task" section |
| `docs/ARCHITECTURE.md` | route table row for `POST /companies/{slug}/todo-edit`; mention Edit on the company page row |
| `tests/test_store.py`, `tests/test_web.py` | tests below |

---

### Task 1: `Store.edit_todo`

**Files:** `src/hermitcrm/store.py`, `tests/test_store.py`

**Interface:**

```python
def edit_todo(self, slug: str, index: int | None, new_text: str, due=None,
              contact: str = "", text: str = "") -> None
```

- `index is None` → the company's `next_step` fields; `contact` is ignored.
- `text` is the text the page showed (stale-page check); `""` skips the check
  (used by tests and future callers that already hold the record).
- `due` accepts what `_coerce_date` accepts (`""`/`None` → no date, `date`,
  `"YYYY-MM-DD"`); a bad value raises `ValidationError({"due": ...})`.

- [ ] **Step 1: write the failing tests** at the end of the tasks block in
  `tests/test_store.py` (next to `test_set_todo_type_changes_a_task_or_the_next_step`,
  ~line 1116). Check how that file imports `date`, `ValidationError` and reads
  the commit messages (the `messages` fixture is the list `on_write` appends to)
  and follow it.

```python
def test_edit_todo_changes_text_and_due_of_a_task(store, messages):
    store.create_company(name="Acme")
    store.add_task("acme", "send deck", due="2026-09-20")
    store.edit_todo("acme", 0, "  send the  new deck ", due="2026-09-25",
                    text="send deck")
    t = store.companies["acme"].tasks[0]
    assert (t.text, t.due, t.done) == ("send the new deck", date(2026, 9, 25), False)
    assert messages[-1] == "task: acme edited"

    store.edit_todo("acme", 0, "send the new deck", due="", text="send the new deck")
    assert store.companies["acme"].tasks[0].due is None      # date cleared


def test_edit_todo_on_a_contact_task_and_the_next_step(store, messages):
    store.create_company(name="Acme")
    store.create_contact("acme", first_name="Jane", last_name="Roe")
    store.add_task("acme", "call her", contact="jane-roe")
    store.edit_todo("acme", 0, "call Jane", due="2026-10-01", contact="jane-roe",
                    text="call her")
    t = store.companies["acme"].contacts["jane-roe"].tasks[0]
    assert (t.text, t.due) == ("call Jane", date(2026, 10, 1))
    assert messages[-1] == "task: acme/jane-roe edited"

    store.update_company("acme", next_step="book demo", next_step_due="2026-09-30")
    store.edit_todo("acme", None, "book the demo", due="2026-10-02", text="book demo")
    c = store.companies["acme"]
    assert (c.next_step, c.next_step_due, c.next_step_status) == \
        ("book the demo", date(2026, 10, 2), "open")
    assert messages[-1] == "task: acme next step edited"


def test_edit_todo_keeps_type_and_writes_nothing_when_unchanged(store, messages):
    store.task_types = ["prospecting"]
    store.create_company(name="Acme")
    store.add_task("acme", "send deck", due="2026-09-20", type="prospecting")
    path = store.company_dir("acme") / "company.md"
    before, n = path.read_text(), len(messages)
    store.edit_todo("acme", 0, "send deck", due="2026-09-20", text="send deck")
    assert path.read_text() == before and len(messages) == n   # no write, no commit
    store.edit_todo("acme", 0, "send deck", due="2026-09-21", text="send deck")
    assert store.companies["acme"].tasks[0].type == "prospecting"


def test_edit_todo_refuses_bad_input_and_stale_pages(store):
    store.create_company(name="Acme")
    store.add_task("acme", "send deck")
    with pytest.raises(ValidationError) as e:
        store.edit_todo("acme", 0, "   ", text="send deck")
    assert "text" in e.value.errors
    with pytest.raises(ValidationError) as e:
        store.edit_todo("acme", 0, "x", due="next week", text="send deck")
    assert "due" in e.value.errors
    with pytest.raises(ValidationError):                       # page is stale
        store.edit_todo("acme", 0, "x", text="something else")
    with pytest.raises(ValidationError):                       # row is gone
        store.edit_todo("acme", 5, "x")
    store.set_task_done("acme", 0)
    with pytest.raises(ValidationError) as e:                  # done: reopen first
        store.edit_todo("acme", 0, "x", text="send deck")
    assert "reopen" in e.value.errors["task"]

    store.update_company("acme", next_step="call")
    with pytest.raises(ValidationError):                       # next step changed
        store.edit_todo("acme", None, "x", text="email")
    store.update_company("acme", next_step_status="done")
    with pytest.raises(ValidationError):
        store.edit_todo("acme", None, "x", text="call")
    store.update_company("acme", next_step="")
    with pytest.raises(ValidationError):                       # no next step at all
        store.edit_todo("acme", None, "x")
```

  If `store.create_contact` has a different signature, use whatever
  `test_store.py` already uses to make a contact (search for `create_contact(`).

- [ ] **Step 2: run them and see them fail**
  `.venv/bin/pytest tests/test_store.py -k edit_todo` → `AttributeError: ... edit_todo`.

- [ ] **Step 3: implement** in `src/hermitcrm/store.py`, directly after
  `set_todo_type`:

```python
    @_locked
    def edit_todo(self, slug: str, index: int | None, new_text: str, due=None,
                  contact: str = "", text: str = "") -> None:
        """Change the text and due date of one open to-do: task `index` of the
        company or `contact`, or the next-step fields when `index` is None.
        `text` is what the page showed, so a stale page is refused. Nothing
        is written when nothing changes."""
        new_text = " ".join((new_text or "").split())
        if not new_text:
            raise ValidationError({"text": "a task needs a line of text"})
        new_due = self._coerce_date(due, "due")
        if index is None:
            company = self._current(slug)
            if company is None:
                raise ValidationError({"slug": f"unknown company {slug!r}"})
            if not company.has_next_step:
                raise ValidationError({"task": "that task is no longer there; reload the page"})
            if text and " ".join(text.split()) != " ".join(company.next_step.split()):
                raise ValidationError({"task": "that task has changed since the page was "
                                               "loaded; reload and try again"})
            if company.next_step_done:
                raise ValidationError({"task": "reopen the task before editing it"})
            if (new_text, new_due) == (company.next_step, company.next_step_due):
                return
            self.update_company(slug, next_step=new_text, next_step_due=new_due,
                                message=f"task: {slug} next step edited")
            return
        company, record = self._task_owner(slug, contact)
        task = self._task_at(record, index, text)
        if task.done:
            raise ValidationError({"task": "reopen the task before editing it"})
        if (new_text, new_due) == (task.text, task.due):
            return
        task.text, task.due = new_text, new_due
        record.updated = self.now()
        where = f"{slug}/{contact}" if contact else slug
        self._write_owner(company, record)
        self._notify(f"task: {where} edited")
```

  Notes for the implementer:
  - `set_todo_type` already calls `self.update_company` from inside a
    `@_locked` method, so the lock is re-entrant; do the same.
  - Check that `update_company` accepts a `date` (not only a string) for
    `next_step_due`; `_coerce_date` → `parse_date` should pass a `date`
    through. If it does not, pass `fmt_date(new_due) if new_due else ""`.
  - `company.has_next_step` and `company.next_step_done` exist on `Company`
    in `models.py` (used in `todos()`); confirm the names.

- [ ] **Step 4: run** `.venv/bin/pytest tests/test_store.py` → all pass.

- [ ] **Step 5: commit** `ai: tasks: Store.edit_todo changes the text and due date of an open to-do`.

---

### Task 2: the `todo-edit` route

**Files:** `src/hermitcrm/web.py`, `tests/test_web.py`

- [ ] **Step 1: write the failing tests** in `tests/test_web.py`, after
  `test_a_stale_page_cannot_tick_off_the_wrong_task` (~line 814). Use the
  helpers that file already has (`post_company`, `post_contact`, `last_commit`).

```python
def test_a_task_can_be_edited_from_its_row(client, app, repo):
    post_company(client, name="Acme")
    client.post("/companies/acme/tasks", data={"text": "send deck", "due": "2026-09-20"})

    r = client.post("/companies/acme/todo-edit",
                    data={"index": "0", "text": "send deck", "new_text": "send the deck",
                          "due": "2026-09-24"},
                    headers={"referer": "http://testserver/companies/acme"})
    assert r.status_code == 303
    assert r.headers["location"].endswith("flash=Task%20saved#tasks")
    assert r.headers["location"].startswith("/companies/acme?")
    assert last_commit(repo) == "task: acme edited"
    t = app.state.store.get("acme").tasks[0]
    assert (t.text, str(t.due)) == ("send the deck", "2026-09-24")


def test_a_contact_task_and_the_next_step_can_be_edited(client, app, repo):
    post_company(client, name="Acme", next_step="Call Jane", next_step_due="2026-09-20")
    post_contact(client, "acme", first_name="Jane", last_name="Roe")
    client.post("/companies/acme/tasks", data={"text": "send her the deck",
                                               "contact": "jane-roe"})

    r = client.post("/companies/acme/todo-edit",
                    data={"index": "0", "contact": "jane-roe", "text": "send her the deck",
                          "new_text": "send Jane the deck", "due": ""},
                    headers={"referer": "http://testserver/companies/acme/contacts/jane-roe"})
    assert r.headers["location"].startswith("/companies/acme/contacts/jane-roe?")
    assert last_commit(repo) == "task: acme/jane-roe edited"
    assert app.state.store.get("acme").contacts["jane-roe"].tasks[0].text == \
        "send Jane the deck"

    r = client.post("/companies/acme/todo-edit",
                    data={"index": "", "text": "Call Jane", "new_text": "Call Jane Roe",
                          "due": "2026-09-22"})
    assert last_commit(repo) == "task: acme next step edited"
    c = app.state.store.get("acme")
    assert (c.next_step, str(c.next_step_due)) == ("Call Jane Roe", "2026-09-22")


def test_editing_a_task_from_a_stale_page_or_with_bad_input_is_refused(client, app):
    post_company(client, name="Acme")
    client.post("/companies/acme/tasks", data={"text": "first"})
    r = client.post("/companies/acme/todo-edit",
                    data={"index": "0", "text": "something else", "new_text": "x"})
    assert "has%20changed%20since" in r.headers["location"]
    r = client.post("/companies/acme/todo-edit",
                    data={"index": "0", "text": "first", "new_text": " "})
    assert "needs%20a%20line%20of%20text" in r.headers["location"]
    r = client.post("/companies/acme/todo-edit",
                    data={"index": "nope", "text": "first", "new_text": "x"})
    assert "no%20longer%20there" in r.headers["location"]
    assert [t.text for t in app.state.store.get("acme").tasks] == ["first"]
    assert client.post("/companies/nobody/todo-edit",
                       data={"index": "0", "new_text": "x"}).status_code == 404


def test_edit_from_the_tasks_page_returns_to_the_same_filtered_view(client, app):
    post_company(client, name="Acme")
    client.post("/companies/acme/tasks", data={"text": "first"})
    back = "/tasks?when=none"
    r = client.post("/companies/acme/todo-edit",
                    data={"index": "0", "text": "first", "new_text": "first!", "back": back})
    assert r.headers["location"].startswith("/tasks?when=none&flash=Task%20saved")
```

  Check `post_company` accepts `next_step`/`next_step_due` (the existing test
  `test_a_company_keeps_a_list_of_tasks_beside_its_next_step` does). Check what
  `flashed` puts in the location with a query string already present (the
  last test) and adjust the assertion to the real format if it differs; do not
  change `flashed`.

- [ ] **Step 2: run them and see them fail** (`404` for the unknown route).

- [ ] **Step 3: implement** in `src/hermitcrm/web.py`, directly after the
  `todo_type` route:

```python
    @app.post("/companies/{slug}/todo-edit")
    def todo_edit(request: Request, slug: str, index: str = Form(""), contact: str = Form(""),
                  text: str = Form(""), new_text: str = Form(""), due: str = Form(""),
                  back: str = Form("")):
        """Change the text and due date of one to-do from its row; an empty
        `index` is the next-step fields."""
        need_company(slug)
        back = _task_back(request, slug, contact, back)
        try:
            store.edit_todo(slug, int(index) if index.strip() else None, new_text,
                            due=due, contact=contact, text=text)
        except ValidationError as exc:
            return flashed(back, "; ".join(exc.errors.values()), "tasks")
        except ValueError:
            return flashed(back, "that task is no longer there; reload the page", "tasks")
        return flashed(back, "Task saved", "tasks")
```

  The form field for the new text is `new_text`, because `text` is already the
  stale-page check in every task form.

- [ ] **Step 4: run** `.venv/bin/pytest tests/test_web.py -k "edit"` → pass;
  then the full `.venv/bin/pytest`.

- [ ] **Step 5: commit** `ai: tasks: POST /companies/{slug}/todo-edit`.

---

### Task 3: the Edit button on company, contact and Tasks pages

**Files:** `src/hermitcrm/templates/macros.html`, `src/hermitcrm/templates/tasks.html`,
`src/hermitcrm/static/style.css`, `tests/test_web.py`

- [ ] **Step 1: write the failing test** in `tests/test_web.py`:

```python
def test_open_tasks_have_an_edit_form_and_done_ones_do_not(client, app):
    post_company(client, name="Acme", next_step="Call Jane", next_step_due="2026-09-20")
    post_contact(client, "acme", first_name="Jane", last_name="Roe")
    client.post("/companies/acme/tasks", data={"text": "open one", "due": "2026-09-21"})
    client.post("/companies/acme/tasks", data={"text": "finished one"})
    client.post("/companies/acme/tasks/1/done", data={"done": "1", "text": "finished one"})
    client.post("/companies/acme/tasks", data={"text": "her task", "contact": "jane-roe"})

    page = client.get("/companies/acme").text
    # one edit form per open to-do: next step, "open one", "her task"
    assert page.count('action="/companies/acme/todo-edit"') == 3
    assert 'name="new_text" value="open one"' in page
    assert 'name="due" value="2026-09-21"' in page
    assert 'name="new_text" value="finished one"' not in page

    contact_page = client.get("/companies/acme/contacts/jane-roe").text
    assert contact_page.count('action="/companies/acme/todo-edit"') == 1
    assert 'name="new_text" value="her task"' in contact_page

    tasks_page = client.get("/tasks").text
    assert tasks_page.count('action="/companies/acme/todo-edit"') == 3
    assert 'name="back" value="/tasks' in tasks_page
```

  The `value="2026-09-21"` assertion assumes `<input type="date">` gets an ISO
  date. Use `due.isoformat()` in the template (not `fmt_date`, which may be a
  display format); check `fmt_date` in `models.py` and pick whatever yields
  `YYYY-MM-DD`.

- [ ] **Step 2: run it and see it fail.**

- [ ] **Step 3: add the macro** to `macros.html`, right after `todo_actions`:

```jinja
{# Edit the text and due date of one open to-do. `index` is None for the
   company's next-step fields; `contact` is the person's slug or ''. #}
{% macro todo_edit(company, t, index, contact='', back='') -%}
{%- if not t.done -%}
<details class="inline-edit todo-edit">
  <summary class="button">Edit</summary>
  <form method="post" action="/companies/{{ company.slug }}/todo-edit" class="inline-form">
    {% if back %}<input type="hidden" name="back" value="{{ back }}">{% endif %}
    <input type="hidden" name="index" value="{{ '' if index is none else index }}">
    <input type="hidden" name="contact" value="{{ contact }}">
    <input type="hidden" name="text" value="{{ t.text }}">
    <input name="new_text" value="{{ t.text }}" aria-label="task" required>
    <input type="date" name="due" value="{{ t.due.isoformat() if t.due else '' }}" aria-label="due">
    <button type="submit">Save</button>
  </form>
</details>
{%- endif -%}
{%- endmacro %}
```

- [ ] **Step 4: call it** in three places, each inside the existing
  `<td class="actions">`, **before** the Done/Delete forms (so Edit comes first):
  - `task_section` (company page): `{{ todo_edit(company, t, t.index, t.contact.slug if t.contact else '') }}`
    (`t` is a `Todo`; `t.index` is None for the next-step fields).
  - `task_list` (contact page): `{{ todo_edit(company, t, loop.index0, contact) }}`
    (`t` is a raw `Task`; it has `text`, `due`, `done`).
  - `tasks.html`: `{{ m.todo_edit(r.company, r.todo, r.todo.index, r.contact.slug if r.contact else '', back=here) }}`.
    `TodoRow` has `.contact` (see `web.py` `TodoRow.__init__`).

  Do not add it to `home.html` or to the next-step line in `company.html`.

- [ ] **Step 5: style** in `static/style.css`, next to the
  `td.actions form.inline` rules (~line 325). The actions cell is
  `white-space: nowrap`; when the form is open it should sit on its own line
  under the buttons and the text input should be wide enough to read:

```css
td.actions details.todo-edit { margin-left: 0; }
td.actions details.todo-edit[open] { display: block; white-space: normal; }
td.actions details.todo-edit form.inline-form { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 0; }
td.actions details.todo-edit input[name="new_text"] { min-width: 16em; flex: 1; }
```

  Check `test_tokens.py`: it reads style.css and may forbid raw colours; the
  rules above use none. Look at the result in a browser on the demo folder
  (company page, contact page, `/tasks`, at desktop and phone width) and adjust
  spacing so nothing overlaps.

- [ ] **Step 6: run** `.venv/bin/pytest` → all pass (several existing tests
  count forms or match HTML; fix the test only if it counted something this
  change legitimately adds, never by weakening what it checks).

- [ ] **Step 7: try it by hand** on `.venv/bin/hermitcrm init /tmp/x --demo`:
  edit a company task's date so it becomes due first and see the `next step`
  tag move to it; edit a contact task on the contact page; edit from `/tasks`
  with a filter on and see you come back to the same filtered view.

- [ ] **Step 8: commit** `ai: tasks: Edit button on company, contact and Tasks pages`.

---

### Task 4: docs

**Files:** `src/hermitcrm/help/tasks.md`, `docs/ARCHITECTURE.md`

- [ ] **Step 1:** in `help/tasks.md`, add after "## Adding a task":

```markdown
## Changing a task

**Edit** in a task's row opens its text and due date; change either and
**Save**. Clearing the date leaves the task undated. Changing a date can change
which task is the next step. Done tasks have no Edit button: reopen one first.
To change who a task is for, delete it and add it again.
```

- [ ] **Step 2:** in `docs/ARCHITECTURE.md` §8 route table, add a row after the
  `POST /companies/{slug}/next-step` row (~line 279):

```markdown
| POST `/companies/{slug}/todo-edit` | Changes the text and due date of one open to-do (`index`, `contact`, `text` as on Done; `new_text`, `due`); an empty `index` is the next-step fields. Refuses a stale page, empty text, a bad date or a done to-do. No write when nothing changed. Commit `task: <slug>[/<contact>] edited` or `task: <slug> next step edited`. Redirects back (anchored at `#tasks`). |
```

  In the `GET /companies/{slug}` row, change "Done / Reopen / Delete each" to
  "Edit (open ones) / Done / Reopen / Delete each".

- [ ] **Step 3:** if any test checks help pages or the architecture doc for
  structure (`tests/test_help.py`), run `.venv/bin/pytest` and fix what the
  new section needs (for example a heading list).

- [ ] **Step 4: commit** `ai: docs: editing a task`.

---

## Out of scope (say so in the PR, do not build)

- Changing who a task is for (company ↔ person, person ↔ person).
- Editing done tasks.
- Editing from Home's "What needs doing" list or the next-step line.
- An MCP tool or CLI command for editing tasks (neither exposes tasks today).

## Done when

- `.venv/bin/pytest` passes.
- On the demo folder, an open task on a company page, on a contact page and on
  `/tasks` can have its text and date changed, each change is one git commit
  with the message above, and a no-op Save makes no commit.
- No front-matter key or value changed, so no migration was added.
