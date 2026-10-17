# Design review, 17 October 2026: what is left to do

Live design audit of the demo app (light and dark, 375 to 1280px), with a fix proposal per finding.
**Steps 1-4 are implemented** (PR "ai: design review quick wins": M-4 bars, M-5 faint text, M-6 radios,
P-1 footer, H-3 table scroll, H-2 mobile nav, M-2 Extension fold). Their proposals were removed from this
file; the code is in `git log --grep "ai: design"`. **Steps 5-8 are open**, and each is independent.

**Reading this cheaply:** read this header and the table below (about 50 lines), then
`grep -n '^## ' docs/superpowers/design-review-2026-10-17.md` and read only the section for the step you are
doing (`Read` with offset and limit). Sections are numbered as in the first version, so 2-5 are missing on
purpose.

| Step | Section | Finding | Effort | Risk |
|---|---|---|---|---|
| 5 | 6 | M-8 outreach card actions, M-9 Add to research copy | 1 h | Low |
| 6 | 7 | H-1 filter listboxes become checklists, data-driven options | 2-3 h | Medium, own branch |
| 7 | 8 | M-1 company page: read view with a folded Edit form | 1-2 h | Medium, own branch |
| 8 | 9 | M-3 Reports scroll hint, M-7 dashboard tiles, P-3 to P-8 | 1-2 h | Low |
| - | 2 | P-2 "none" printed as content (skipped on purpose, lowest value) | 30 min | Low |

Rules to keep (from `CLAUDE.md` and `DESIGN.md`): CSS uses `var(--*)` only and adds no tokens (no website
rebuild), `.venv/bin/pytest` before any commit, commit messages start with `ai:`, one fix per commit.
A footgun found on the way: `.small { margin: 2px 0 }` outranks a bare element selector such as `footer`;
check the computed style, not the stylesheet. Work in a worktree: the main checkout is shared with other sessions.

Screenshots and the full first report are outside the repo, in
`~/.gstack/projects/Hermit-CRM-hermit-crm/designs/design-audit-20261017/`.


## 6. M-8 and M-9 Outreach (step 5)

### M-8 The card's actions have no hierarchy

`outreach.html:198-216`. "Mark ready" is the only action that moves the work forward and is an unstyled
button; Save & check again and Copy are `secondary`; Regenerate, a checkbox, a select, a text field and Skip
sit on a second row. Five controls plus two fields for one decision.

```jinja
<div class="draft-actions">
  <button type="submit" class="primary" title="...">Mark ready</button>        {# was unstyled #}
  <button type="submit" formaction="/outreach/{{ i.id }}/check" class="secondary" ...>Save &amp; check again</button>
  <button type="button" class="secondary" data-copy-target="body-{{ i.id }}">Copy</button>
</div>
<details class="more-box">
  <summary>Regenerate or skip</summary>
  <div class="draft-actions"> ...the regenerate and skip forms exactly as they are... </div>
</details>
```

`button.primary` exists (`style.css:810`), so no CSS. Skipping is a permanent decision with a required
reason, so it belongs behind a fold more than Mark ready does. If the fold hides too much for the bot
workflow, keep Regenerate visible and fold only Skip. The technical line at the bottom of the card (id,
model name, seconds, norms) is debug information at the same weight as content; wrap it in
`<p class="small" title="...">` with `color: var(--muted)` or move it into the fold.

### M-9 Add to research (the new page)

Rendered via a scratch server with the fake AI used in `tests/test_outreach_page.py` (scratch only, not in
the repo). `outreach_add.html`:

1. **Copy leads with mechanism, not outcome.** The page opens with a sentence that says a card exists, then a
   three-sentence paragraph ("The text itself is not kept. It is read by the AI as data, not instructions,
   with no tools."). Users scan; the privacy promise is right but belongs under the form.
2. **"Top card"** is a label nobody outside the code uses. Use "Name and headline".
3. **Textareas are 8 rows for 1 to 3 lines of text**, so the page is 600px of empty boxes. The buttons start
   at y=770.
4. **Sidebar highlights Extension**, but the user is in an outreach flow; "Cancel" returns to the card, so
   the page should say which card.

```jinja
<h1>Add to research</h1>
<p>Add what you can see on {{ contact.name }}'s profile to the draft for {{ company.name }}.
   Remove anything you do not want read.</p>
<form ...> ...textareas... buttons ... </form>
<p class="small">The AI reads this once and keeps only short findings, each linked to this profile. The page
text itself is not stored. It is treated as data, not instructions, and has no tools. Nothing is sent
anywhere else.</p>
```

and size the boxes to content:

```jinja
<textarea name="{{ key }}" rows="{{ [[text.count('\n') + 2, 3] | max, 10] | min if text else 3 }}" spellcheck="false">
```

(or, in modern Chrome/Safari, `textarea { field-sizing: content; min-height: 4.5em; max-height: 16em; }`
with the `rows` attribute as the fallback). Check that `test_outreach_page.py` asserts only the
substrings it lists ("Add to research", the item action, the piece texts, "nothing read"); the label text
changes are safe, "nothing read" and "cannot take research now" must stay.

---

## 7. H-1 Filters: native multi-select listboxes (step 6, prototyped live)

**Problem.** `macros.html:18` renders every enum column as `<select multiple size=4>`; the country list is
all of `Country` (249 values, `web.py:113`, `COUNTRIES = [c.value for c in Country]`), shown as "AD AE AF AG"
in a 70px box, while the data has 7 countries. Stage/status/source/outcome do the same. The text filters'
placeholders are also clipped in narrow columns ("text, !text, =te").

**Why checkboxes are a safe swap.** A multi-select submits `f_country=NL&f_country=DE`. A group of checkboxes
that share `name="f_country"` and carry `form="..."` submits the identical query string, so
`filters.parse()` and all the saved URLs keep working. Nothing server-side has to understand a new shape.

**Prototype (live on /companies):** the three listboxes became compact `country`, `stage`, `source`
controls that open in place; country offered 7 values instead of 249. Screenshot `proposal-filter.png`.

### 7a. Markup, `macros.html:17-20`

```jinja
{% macro filter_control(col, active, form_id) %}
  {%- if col.kind == 'enum' -%}
  {% set chosen = active.get(col.key, []) %}
  <details class="filter-pick{% if chosen %} on{% endif %}"{% if chosen %} open{% endif %}>
    <summary>{{ col.label }}{% if chosen %} ({{ chosen | length }}){% endif %}</summary>
    <div class="options">
      {% for o in col.options %}
      <label><input type="checkbox" name="f_{{ col.key }}" form="{{ form_id }}" value="{{ o }}"{% if o in chosen %} checked{% endif %}> {{ o }}</label>
      {% endfor %}
    </div>
  </details>
  {%- else -%} ...text/number/date input as today... {%- endif -%}
{% endmacro %}
```

Open when a value is chosen, so the active filter is visible on load (a filter you cannot see is the usual
"why is my list short?" support question). The `?` help line "Lists: cmd-click (ctrl-click) to select
several" (`macros.html:41`) can then be deleted.

### 7b. CSS, no new tokens

```css
details.filter-pick { font-size: 12px; }
details.filter-pick > summary { list-style: none; cursor: pointer; white-space: nowrap; min-width: 70px;
  border: 1px solid var(--line-strong); border-radius: 4px; padding: 2px 6px; background: var(--surface); }
details.filter-pick > summary::-webkit-details-marker { display: none; }
details.filter-pick > summary::after { content: " \25BE"; color: var(--muted); }
details.filter-pick.on > summary { border-color: var(--accent); font-weight: 600; }
details.filter-pick .options { max-height: 140px; overflow: auto; margin-top: 2px; padding: 2px 6px;
  border: 1px solid var(--line); border-radius: 4px; background: var(--surface); }
details.filter-pick label { display: flex; gap: 6px; align-items: center; margin: 0; padding: 1px 0; white-space: nowrap; }
details.filter-pick input { width: auto; margin: 0; }
```

It opens **in flow**, growing the filter row, rather than as a floating panel. That is deliberate: a floating
panel inside `.table-scroll` is clipped by the scroll box, and the H-3 fix (done) makes that box scroll at every width.
`details.filter-pick summary` has the focus ring from the global `:focus-visible` rule and works by
keyboard (Enter/Space, Tab through the boxes).

### 7c. Only offer values that exist, `web.py` / `filters.py`

`COUNTRIES` stays the validation list; the *filter offer* shrinks to values in the data (plus anything
currently selected, so a saved URL is never silently dropped). In `filters.py`:

```python
def offered(col: Column, rows, active) -> list[str]:
    """Enum choices worth showing: those some row has, plus the ones already chosen.
    Short lists (stages, outcomes) are shown whole so an empty one can be chosen."""
    if len(col.options) <= 12:
        return col.options
    used = {str(v) for r in rows if (v := col.value(r)) not in (None, "")}
    return [o for o in col.options if o in used or o in active.get(col.key, [])]
```

and in each `*_listing` (`company_listing` at `web.py:403`, contacts, tasks, messages) build the columns for
the template with `dataclasses.replace(col, options=filters.offered(col, rows_before_filtering, active))`.
`Column` is a plain dataclass (`filters.py:37`), so `replace` works. Use the rows **before** the filters
apply, otherwise choosing NL would hide every other country from the list. Edge: custom enum fields have
short option lists and keep the "show whole" path.

### 7d. Placeholders

`macros.html:22` repeats "text, !text, =text, -, *" in every cell, which is why it clips. Use a short
placeholder (`filter`, `>5`, `>2026-09-01`) and keep the full syntax in the `?` popover that already
explains it. Shorter placeholders also fit the 4.5:1 check better because they are not cut mid-word.

### 7e. Tests

`tests/test_filters.py`, `test_web.py`, `test_bulk.py`, `test_dashboards.py`, `test_layout.py`,
`test_adjust.py` mention `multiple`, `f_country` or `f_stage`. Expect to update assertions on the
`<select ... multiple` markup; add one test that checkbox params round-trip
(`?f_country=NL&f_country=DE` selects both boxes and filters both) and one that `offered()` keeps a chosen
value that no row has. Mobile: the `.filters-fold` toggle (`style.css:683`) already collapses the strip
under one "Filter" button; checklists inside it behave the same as today's listboxes.

---

## 8. M-1 Company page leads with a 12-field form (step 7)

The first section under the header is `details`, a full edit form about 560px tall (`company.html:68-77`);
contacts, tasks, drafts and the timeline start about 650px down. The header already shows stage, score and
next step, so they appear twice. The **Contact page already solved this**: `contact.html:76-101` shows a
read-only `dl.fields` summary and a folded `details.edit-box` for the form. Mirror it:

```jinja
<section id="details">
  <h2>Company</h2>
  {{ m.errors_box(errors) }}
  {% set add = '?edit=1#details' %}
  <dl class="fields">
    <dt>website</dt><dd>{% if company.website %}<a href="{{ company.website | href }}" ...>open</a>{% else %}<a href="{{ add }}">+ website</a>{% endif %}</dd>
    <dt>country</dt><dd>{{ company.country or '' }}{% if not company.country %}<a href="{{ add }}">+ country</a>{% endif %}</dd>
    ... source, value, my score, FTE estimate, AE count, fit, tags, each honouring `'key' not in hide` ...
  </dl>
  <details class="edit-box"{% if errors or editing %} open{% endif %}>
    <summary class="button">Edit</summary>
    <form method="post" action="/companies/{{ company.slug }}" class="record-form">
      <input type="hidden" name="version" value="{{ record_version(company.slug) }}">
      {{ m.company_fields(values, errors) }}
      <button type="submit">Save company</button>
    </form>
  </details>
</section>
```

Result: about 650px of form becomes about 160px of summary, and contacts, tasks, drafts and timeline come
up the page. No CSS (`dl.fields`, `details.edit-box` exist, `style.css:881-887`) and no change to
`layout.toml`: section order stays user-controlled (`layout.py:44`), so people who reordered keep their
order. The `?edit=1` link pattern is the one the Contact page uses, so the handler for `editing` is the
only new code on the route side (`web.py`, company page: pass `editing=request.query_params.get('edit')`).
Also removes the 700px-vs-825px column-edge mismatch, because the form no longer sits in a narrower card above
the full-width tables. Tests: `test_web.py` asserts the company form in several places; most should still
pass because the form still renders (inside `details`, open on `?edit=1` and on errors).

---

## 9. M-3, M-7 and polish (step 8)

**M-3 Reports weekly table clipped.** `style.css:499` already scrolls `.report-grid > div` (`overflow-x: auto`),
so nothing is lost; it just gives no hint. The classic CSS-only scroll shadow, tokens only:

```css
.report-grid > div {
  background:
    linear-gradient(to right, var(--bg) 30%, transparent) left / 24px 100% no-repeat local,
    linear-gradient(to left,  var(--bg) 30%, transparent) right / 24px 100% no-repeat local,
    linear-gradient(to right, var(--line), transparent) left / 10px 100% no-repeat scroll,
    linear-gradient(to left,  var(--line), transparent) right / 10px 100% no-repeat scroll;
}
```

The real fix is at the source: the weekly table is 13 columns wide because every channel gets an in and an
out column. Showing only the channels that had activity in the period (a change to the weekly-activity
block in `report_sections.html`; I did not read that template, so check how the columns are built) removes
the overflow instead of hinting at it.

**M-7 Dashboard tiles.** The two KPI tiles take half a row for one digit each, and "Deals by stage" repeats
"Pipeline and its value". The dashboards are built in the user's data folder by their agent, so the app
change is only the tile size: `.start-cards.numbers .card { flex: 0 1 180px; }` (`style.css:420`) turns a
half-row tile into a stat chip, and the demo dashboard's duplicate table is content to trim in the
`demo` dashboard definition, not app chrome.

**P-3 dd/mm/yyyy next to ISO dates.** `type=date` follows the browser locale. If you want ISO everywhere,
use `<input type="text" inputmode="numeric" pattern="\d{4}-\d{2}-\d{2}" placeholder="yyyy-mm-dd">`; you lose
the picker. I would leave it: the picker matters more than matching, and the format is what the user's own
system uses.

**P-4 Visited links.** One rule, token only: `a:visited { color: var(--muted); }` scoped to prose
(`main p a:visited, main li a:visited`) so table links, which are navigation, keep one colour.
`--muted` on `--bg` is 6.36:1.

**P-5 Disclaimer left borders.** `style.css:762`: drop `border-left: 3px solid var(--accent)`; keep the
bold lead-in. Same hierarchy without the slop pattern.

**P-6 Welcome as 12 cards.** `.welcome-step.done { opacity: .7 }` already dims done steps; fold them:
render `done` steps as `<details>` closed with a one-line summary. Halves the scroll for anyone past step 6.

**P-7 Pipeline card stage select.** `board.html:52` puts a full-width bordered `<select>` in every card, as
heavy as the title. `form.stage-form select { border-color: transparent; background: transparent; padding-left: 0;
width: auto; color: var(--muted); }` with `:hover, :focus-visible { border-color: var(--line-strong); }` keeps it
discoverable and cuts the card's weight. The `onchange="this.form.submit()"` is allowed by the CSP
(`script-src 'unsafe-inline'`), so it keeps working.

**P-8 Breakpoints.** 21 distinct media-query values. Settle on 520 / 760 / 1000 (`760` is already the
phone/desktop line in the tests). Mechanical, but each move is a layout change; do it last, with screenshots.

---

## 10. How to verify each step

```bash
.venv/bin/pytest -q tests/test_tokens.py tests/test_web.py     # after steps 1-4
.venv/bin/pytest -q                                            # before every commit (CLAUDE.md)
.venv/bin/hermitcrm init /tmp/x --demo && .venv/bin/hermitcrm --data /tmp/x serve --port 8855
```

Then, per step, with the gstack browser: the same pages and widths as the tables above
(`scrollWidth == innerWidth` at 800/900/1024/1280 on /companies, /messages, /tasks, /contacts, a company
page), mobile nav height at 375px, `getComputedStyle(radio).accentColor`, and the contrast pairs in
`tests/test_tokens.py`.

Commit one fix per commit, message `ai: design: <FINDING-id> <what>` (the repo's `ai:` prefix wins over the
design-review skill's default `style(design):`).
