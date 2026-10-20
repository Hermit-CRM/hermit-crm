# Design review, 17 October 2026: findings and fix proposals

Status: **proposals only. Nothing in `src/` or `tests/` was changed.** The working tree has uncommitted
outreach 05d work (and another session may still be editing it), so every fix below waits for a clean
tree or its own branch. Not committed; this file is untracked.

Reviewed live against the demo folder (`hermitcrm init <dir> --demo`), Chrome engine, light and dark,
at 375 / 768 / 800 / 900 / 1024 / 1280. Screenshots are in
`~/.gstack/projects/Hermit-CRM-hermit-crm/designs/design-audit-20261017/screenshots/`. The proposals
marked **verified live** were injected into the running page as CSS or JS and checked; none touched a
source file.

Rules these proposals follow (from `CLAUDE.md` and `DESIGN.md`): CSS uses `var(--*)` only, no new tokens
(so no website rebuild), every `font-family` stays a token, `.venv/bin/pytest` before any commit, commit
messages start with `ai:`, and one fix per commit.

## 0. What changed since the first pass

New findings from the pages I had not reached, and a stricter score.

| New | Finding |
|---|---|
| H-3 (was M-3) | Wide tables push the **whole page** sideways on desktop: Messages at 1280px (page is 1653px wide), Companies at any window up to 1141px, Tasks/Contacts/Company page at 800-900px. Root cause found, see 3. |
| M-8 | Outreach card: "Mark ready" has the same weight as Skip and Regenerate, and the two button rows stack five controls. |
| M-9 | Add to research page (the branch's new UI, now rendered): instruction-first copy, jargon, textareas four times taller than their content. |

**Re-score.** The first pass was lenient: it did not subtract every medium finding. Counting each one by
the skill's formula (high = one letter, medium = half a letter) gives **Design Score B (3.05)**, not B+.
That is the same product with a stricter ruler, not a regression. After the high and medium fixes below
the same formula gives about **A- (3.7)**.

| Category | Weight | Before | After fixes |
|---|---|---|---|
| Visual hierarchy | 15% | B- (M-1, M-2, M-7) | A- |
| Typography | 15% | A | A |
| Spacing and layout | 15% | B- (H-3, M-3) | A |
| Color and contrast | 10% | B- (M-4, M-5, M-6) | A |
| Interaction states | 10% | B- (H-1, M-8) | A- |
| Responsive | 10% | B (H-2) | A- |
| Content | 10% | B+ (M-9) | A- |
| AI slop | 5% | B | B+ |
| Motion | 5% | A | A |
| Performance feel | 5% | A | A |

## 1. Order of work

| # | Fix | Files | Effort | Risk |
|---|---|---|---|---|
| 1 | CSS one-liners: M-4 bars, M-5 faint text, M-6 radios, P-1 footer, P-2 "none" | `style.css`, `test_tokens.py` | 30 min | None; token-only |
| 2 | H-3 tables scroll inside their box at every width | `style.css`, `test_web.py` (one assertion) | 20 min | Low; one pinned test changes on purpose |
| 3 | H-2 mobile nav in one row | `style.css` | 20 min | Low |
| 4 | M-2 Extension page: code behind a fold | `extension.html` | 15 min | None |
| 5 | M-8 + M-9 outreach card and Add to research | `outreach.html`, `outreach_add.html`, `style.css` | 1 h | Low; check `test_outreach_page.py` wording |
| 6 | H-1 filter checklists with data-driven options | `macros.html`, `web.py`, `filters.py`, `style.css`, tests | 2-3 h | Medium; touches every list page |
| 7 | M-1 Company page read view | `company.html`, `layout.py` docs, tests | 1-2 h | Medium; mirrors the Contact page |
| 8 | M-3, M-7, P-3..P-8 | various | 1-2 h | Low |

Steps 1-4 are independent and safe to land in a single PR of four commits. 6 and 7 deserve their own.

---

## 2. Quick CSS batch (step 1)

### M-4 Data bars are about 1.1:1 against their card (verified live)

Cause: `style.css:502` `.bar { background: var(--subtle); ... }`. `--subtle` on `--surface` is 1.17:1 light and
1.16:1 dark; graphical objects need 3:1.

```css
/* before */ .bar { background: var(--subtle); height: 10px; min-width: 1px; border-radius: 2px; }
/* after  */ .bar { background: var(--line-strong); height: 10px; min-width: 1px; border-radius: 2px; }
```

`--line-strong` is 3.38:1 on `--surface` in light and 3.34:1 in dark, and `test_tokens.py` already pins that
pair at 3:1, so the bar is covered by an existing test. A green bar (`--accent`) is the alternative; I
rejected it because the report tables already use green for links and the bars would read as links.
Screenshot: `proposal-dashboard.png`.

### M-5 `--faint` is used for text (verified live)

`--faint` is `#8f8778`. Measured: 2.99:1 on `--sidebar`, 3.16:1 on `--bg`, 3.38:1 on `--surface`. The test pins
`--faint` on `--surface` at 3.0 and nothing else, so text on the sidebar and page background is untested.
It is used as text colour in four places: the sidebar group label (`style.css:793`), the footer (`:511`),
`code.report-key` (`:554`, 11px) and `code.sha` (`:847`, 11px). `DESIGN.md` says text is 4.5:1.

```css
nav.sidebar .nav-group { ...; color: var(--muted); }   /* was --faint: 2.99 -> 6.03 on the sidebar */
footer                 { ...; color: var(--muted); }   /* was --faint: 3.16 -> 6.36 */
code.report-key        { ...; color: var(--muted); }
code.sha               { ...; color: var(--muted); }
```

Keep `--faint` for icons and borders (`.topbar .search .icon`, `.help-dot` border); those are non-text.
Add a regression test so it cannot come back:

```python
def test_faint_is_never_a_text_colour():
    """--faint is 3:1: fine for icons and borders, not for words (DESIGN.md: 4.5:1)."""
    assert not re.search(r"(?:^|[;{\s])color:\s*var\(--faint\)", STYLE)
```

Dark mode needs no change: `--muted` is 6.41:1 on the dark sidebar.

The sort arrows (`.sort`, 9px, links in `--line-strong`) are controls, so 3:1 is allowed, but 9px is
below the 12px floor and a hit area of about 9x12px. Raise them:

```css
.sort { white-space: nowrap; font-size: 11px; margin-left: 2px; }
.sort a { color: var(--muted); text-decoration: none; padding: 2px 1px; }   /* was --line-strong */
```

### M-6 Radios and checkboxes render the browser's blue (verified live)

`getComputedStyle(radio).accentColor` is `auto`. One line, token only:

```css
input[type="radio"], input[type="checkbox"] { accent-color: var(--accent); }
```

The disclaimer checkbox, Settings radios and the filter checkboxes all pick it up; the accent flips to
the light green in dark mode through the token. Screenshot: `proposal-settings.png`.

### P-1 Footer sits at x=208, not on the content edge (verified live)

`style.css:511`: `footer { margin: 2em 1em 1em; ... }` and `footer.small` is 12px, so the left margin is 12px;
`main` pads 24px (`:13`).

```css
footer { margin: 2em 24px 1em; color: var(--muted); }
```

### P-2 "none" printed as content

`last_touch_summary` returns `none`; it shows in Pipeline cards, Companies, Contacts and the Calendar table.
Cheapest fix is in presentation, not data (the summary string is also read by the AI and `show`): render
it through a tiny macro, `{{ m.dash_if_none(c.last_touch_summary) }}`, that prints `<span class="faint-text">&ndash;</span>`
for `none`. Skip if you would rather keep the word; it is the lowest-value item here.

---

## 3. H-3 Tables push the page sideways (step 2)

**Evidence** (page scrollWidth vs window):

| Window | /companies | /messages | /tasks | /contacts | company page |
|---|---|---|---|---|---|
| 1280 | 1280 | **1653** | 1280 | 1280 | 1280 |
| 1024 | **1141** | **1653** | 1024 | 1024 | 1024 |
| 900 | **1141** | **1653** | **922** | 900 | 900 |
| 800 | **1141** | **1653** | **922** | **876** | **849** |

Cause: `style.css:200`

```css
@media (max-width: 760px) { .table-scroll { overflow-x: auto; } }
```

The comment says "Above 760px the box is a plain div and changes nothing", and
`tests/test_web.py:2036-2037` pins it (`effective(wide, ".table-scroll") == {}`). That was a conservative
choice when the phone fix (#29) landed; it leaves everything between 761px and the table's natural width
(up to 1650px on Messages) pushing the page. The topbar's bottom border visibly stops at 1280 on Messages.

**Fix (verified live on /messages: page width 1653 to 1280, the box scrolls 1421 inside 1024):**

```css
/* A wide table scrolls inside its own box at every width, never the page. */
.table-scroll { overflow-x: auto; }
```

Delete the media-query line and its comment, and change the test, because it asserts the old decision:

```python
def test_a_wide_table_scrolls_in_its_own_box_at_every_width():
    """Messages was 1421px of table in a 1024px column and the whole page scrolled."""
    phone, wide = phone_and_wide_css()
    assert effective(wide, ".table-scroll") == {"overflow-x": "auto"}
```

(and drop `effective(phone, ".table-scroll")` from the phone test, or keep it as `== {}`).

Risk to check by eye after the change: anything absolutely positioned inside a `.table-scroll` would now be
clipped. I found none: the filter help popover (`.help .tip`) sits outside the table, native `<select>`
menus are not clipped by overflow, and the stage menu is in the page header. The step 6 filter checklist is
deliberately in flow (no popover) for the same reason.

**Optional, Messages only:** the 3 outcome buttons per row are the widest cell (about 290px). Reuse the
existing folded-button pattern so the row is narrower:

```jinja
{# messages.html:32-40 #}
<td class="actions nowrap">
  <details class="inline-edit">
    <summary class="button">Outcome</summary>
    {% for value in outcomes + [''] if value != r.explicit %}
    <form method="post" action="/companies/{{ r.company_slug }}/interactions/{{ r.id }}/outcome" class="inline">
      <input type="hidden" name="outcome" value="{{ value }}">
      <button type="submit">{{ value | capitalize if value else 'Unknown' }}</button>
    </form>
    {% endfor %}
  </details>
  <a href="...edit link as today...">edit</a>
</td>
```

That removes 21 buttons from a 7-row page and makes outcome a deliberate act. `details.inline-edit` exists
(`style.css:289`).

---

## 4. H-2 Mobile navigation takes a third of the first screen (step 3, verified live)

At 375px the sidebar becomes a wrapped block: 13 links in five rows, about 280px of 812px. Measured with
the fix below: **50px**, and the page title now starts at about y=110 instead of y=330. The existing mobile
block is `style.css:111-125`.

```css
@media (max-width: 760px) {
  nav.sidebar { position: static; height: auto; flex-direction: row;
    flex-wrap: nowrap; overflow-x: auto; align-items: center; padding: 6px 12px;
    scrollbar-width: none; border-right: 0; border-bottom: 1px solid var(--line); }
  nav.sidebar::-webkit-scrollbar { display: none; }
  nav.sidebar .brand { width: auto; flex: none; padding: 6px 12px 6px 0; }
  nav.sidebar a:not(.brand), nav.sidebar .nav-button { width: auto; flex: none; white-space: nowrap; }
  .sidebar-foot { margin: 0; padding: 0; border: 0; display: flex; flex: none; flex-wrap: nowrap; }
  ...
}
```

The half-cut item at the right edge is the scroll cue; a hard fade is not needed. One gap: the active page
can sit off-screen to the right. Three lines in `adjust.js` (CSP allows own scripts) fix that:

```js
// phone: bring the current page's link into view in the one-row nav
var here = document.querySelector('nav.sidebar a.active');
if (here && here.scrollIntoView) here.scrollIntoView({ inline: 'center', block: 'nearest' });
```

Alternative I rejected: a hamburger. It costs a template change and JS state for a 13-item menu that fits one
swipeable row. Trunk test on mobile: site (brand), page (active link, scrolled to), sections (the row),
search (below, one tap) all stay visible. `.nav-group`/`.nav-gap` are already hidden on phones
(`style.css:857`), so nothing else to change.

---

## 5. M-2 Extension page: the code is the loudest thing on it (step 4)

`extension.html:18` prints about 3 KB of JavaScript as a wall of monospace above the form that most people
use. The branch is adding to that script (`bookmarklet.js` +41/-5), so it will only get longer.

```jinja
<p><a class="bookmarklet" href="{{ bookmarklet }}">Add to Hermit CRM</a>
<span class="small">&larr; drag me</span></p>

<h2>Or paste a URL</h2>
<form method="get" action="/extension/new" class="record-form"> ... unchanged ... </form>

<details class="more-box">
  <summary>The bookmark will not drag? Copy the code instead</summary>
  <p class="small">Some browsers refuse to run a bookmarklet you click from a page. Dragging it to the bookmarks
  bar first is the way that always works. If your browser strips it, copy the code below into a new bookmark by hand.</p>
  <pre class="bookmarklet-code"><code>{{ bookmarklet }}</code></pre>
</details>

<h2>What it reads</h2> ...
```

`details.more-box` already exists (`style.css:889`). Two things this fixes at once: the URL box (the
fallback people actually use when the bookmark is blocked) moves above the fold, and the code stays one
click away. The page has `autofocus` on the URL field; keep it, it still works inside the flow.
`tests/test_web.py` / `test_capture.py` may assert the order of `bookmarklet-code` and the form; run them.

---

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
panel inside `.table-scroll` is clipped by the scroll box, and step 2 makes that box scroll at every width.
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

## 10. How to verify each step (so a clean tree can be checked without trust)

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
