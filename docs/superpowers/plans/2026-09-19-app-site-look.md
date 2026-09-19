# The app takes the website's look: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make option B of the proposal the app's default look (the website's green, paper
palette and serif titles), keep every part of it one line away for a user's `theme.css`,
and put it live on Gijs's own instance.

**Architecture:** The look is data, not structure: new values in `static/tokens.css`, a
handful of rules in `static/style.css` that read tokens, and one new type token
(`--title-font`) so titles can change back in one line. The website's drawing of the app
reads the same tokens at build time. No template, layout or data change.

**Tech stack:** plain CSS (`light-dark()`, `@supports` fallback), FastAPI + Jinja,
pytest, the website's `build.py`, Playwright for screenshots.

**Spec:** `docs/superpowers/specs/2026-09-19-app-site-look-design.md` (approved by Gijs on
2026-09-19: "build green + paper + serif as described in the proposal; ensure users can
continue to easily change the look and feel; deploy for my instance").

## Global constraints

- Every colour and font in `style.css` stays a `var(--*)`; no literal outside `tokens.css`.
- No token is renamed or removed: every existing `theme.css` keeps working.
- Contrast: text 4.5:1, focus ring, control borders and hints 3:1, in light and dark.
- Everything you work in (board, tables, forms, 12-14px text) stays `--sans` at today's size.
- Never run the dev code with `--data ~/Code/CRM`; screenshots use the fictional demo folder.
- Commits start with `ai:`; no history rewrites (no rebase, amend or force-push).
- Deploy only from `main` (`uv tool install ... @main`), after pytest on main and a
  `migrate --dry-run`.

## Deviations from the spec, and why

1. **One token is added: `--title-font`** (default `var(--serif)`), used by page titles,
   the sidebar wordmark and the Home numbers. Gijs asked that users can keep changing the
   look easily; without it, sans titles back need three selectors of different
   specificity. Adding a token breaks no existing `theme.css`.
2. **Inputs actually get `--line-strong`.** The proposal measured `--line-strong`, but a
   later `input, select, textarea` rule in `style.css` overrides it with `--line`, so
   today's field borders are 1.35:1, not 1.73:1. The dead earlier rule goes; the live
   rule and the top-bar search box use `--line-strong`.
3. **The subtitle `h2`s are six, not five:** `.helpdoc-topics h2` is one too.
   `.welcome-step h2` never had `text-transform: none`. The `text-transform: none`
   declarations stay, so a user's "lowercase labels" rule cannot lowercase subtitles.
4. **The search box shows the focus ring** (`:focus-within`): its input sets
   `outline: none`, which would hide the new ring.
5. **Static URLs carry a hash of the files** instead of the version number. An update
   within one version (0.3.0 now, a rebuilt tarball for testers) otherwise keeps the old
   stylesheet in the browser's cache for up to a tenth of the file's age.

## Files

- Modify `src/hermitcrm/static/tokens.css`: 15 colour values + shadow, fallback, `--title-font`.
- Modify `src/hermitcrm/static/style.css`: `h1`, `h2`, `a`, focus, wordmark, Home numbers,
  subtitles, field borders.
- Modify `src/hermitcrm/usertheme.py` (`EXAMPLE`), `src/hermitcrm/templates/settings.html`,
  `src/hermitcrm/help/settings.md`: the theme help shows today's defaults, the fonts, and a
  ready-made earlier look.
- Modify `src/hermitcrm/web.py`, `src/hermitcrm/templates/base.html`: `asset_version`.
- Modify `website/site/style.css`, rebuild `website/site/app-tokens.css` and `index.html`.
- Modify `DESIGN.md`, `CHANGELOG.md`, `docs/ARCHITECTURE.md`, `TODO.md`, `.gitattributes`,
  the spec's status line.
- Tests: `tests/test_tokens.py`, `tests/test_web.py`.

---

### Task 1: Worktree and baseline

- [ ] Branch `feat/app-site-look` from `spec-app-site-look` in the existing worktree.
- [ ] `uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -e '.[dev]'`
- [ ] `.venv/bin/pytest -q -x` passes on the untouched branch (baseline).

### Task 2: The palette and the title token

**Files:** `tests/test_tokens.py`, `src/hermitcrm/static/tokens.css`

- [ ] **Failing tests** in `tests/test_tokens.py`: a WCAG contrast check over the pairs of
  the spec's contrast table, light and dark, reading `tokens.css`; `--title-font` defined
  as `var(--serif)` and listed in `SCHEME_FREE`.

```python
CONTRAST = [  # (foreground, background, minimum): pairs that carry text or mark a control
    ("--text", "--bg", 4.5), ("--text", "--surface", 4.5), ("--text", "--sidebar-active", 4.5),
    ("--text", "--info-bg", 4.5), ("--muted", "--bg", 4.5), ("--muted", "--surface", 4.5),
    ("--muted", "--sidebar", 4.5), ("--faint", "--surface", 3.0), ("--accent", "--bg", 4.5),
    ("--accent", "--surface", 4.5), ("--accent", "--info-bg", 4.5),
    ("--surface", "--accent", 4.5), ("--line-strong", "--surface", 3.0),
    ("--danger", "--surface", 4.5), ("--ok", "--surface", 4.5), ("--warn", "--warn-bg", 4.5),
]

@pytest.mark.parametrize("scheme", [0, 1], ids=["light", "dark"])
@pytest.mark.parametrize("fg, bg, minimum", CONTRAST)
def test_default_colours_meet_the_contrast_rules(fg, bg, minimum, scheme):
    ratio = contrast(light_dark(fg)[scheme], light_dark(bg)[scheme])
    assert ratio >= minimum, f"{fg} on {bg}: {ratio:.2f}"
```

- [ ] Run: `.venv/bin/pytest tests/test_tokens.py -q`. Expected: `--line-strong` on
  `--surface` fails (1.73), `--title-font` missing.
- [ ] **Implement** `tokens.css`: the B values from the spec's token table (lowercase
  hex, like the rest of the file), `--shadow-color` warm in light, the same light values
  in the `@supports` fallback, and under type:

```css
  /* page titles, the sidebar wordmark and the numbers on Home; everything you
     work in (the board, tables, forms) stays in --sans */
  --title-font: var(--serif);
```

- [ ] Run the file's tests: pass. Commit `ai: the website's palette and green as the app's defaults`.

### Task 3: The rules

**Files:** `tests/test_tokens.py`, `src/hermitcrm/static/style.css`

- [ ] **Failing tests:** a small rule reader (`effective(css, selector)`: the declarations
  of exactly that selector, later rules winning) and:
  - `h1`, `nav.sidebar .brand span`, `.start-cards.numbers .card h3` use `var(--title-font)`;
  - `input, select, textarea` ends with `border: 1px solid var(--line-strong)`, and
    `.topbar .search` uses `--line-strong`;
  - every `font-family` in `style.css` is `var(--…)` or `inherit`, and every `font`
    shorthand ends in a `var(--…)` or is `inherit` (so `theme.css` reaches every font);
  - `:focus-visible` draws a ring in `var(--accent)`.
- [ ] Run: fail. **Implement** in `style.css`:

```css
nav.sidebar .brand span { font-family: var(--title-font); font-size: 17px; font-weight: 500; }
h1 { font-family: var(--title-font); font-size: 24px; font-weight: 500; letter-spacing: -.005em; margin: 10px 0 6px; }
/* Section labels in small caps, like the website's. The h2s that are headings of
   their own (a month, a Settings section, a help page) keep ordinary letters. */
h2 { font-size: 15px; margin: 22px 0 8px; font-weight: 600; font-variant-caps: all-small-caps; letter-spacing: .06em; }
.month-nav h2, .setup-step h2, .helpdoc-topics h2, .helpdoc h2, .feedback-saved h2,
.welcome-step h2 { font-variant-caps: normal; letter-spacing: 0; }
a { color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 2px; }
/* Keyboard focus: a ring in the accent, like the website's (not the browser's own). */
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.topbar .search:focus-within { outline: 2px solid var(--accent); outline-offset: 2px; }
.start-cards.numbers .card h3 { font-family: var(--title-font); font-size: 26px; font-weight: 500; font-variant-numeric: lining-nums; margin: 0 0 2px; }
```

  Delete the dead `input, select, textarea { background…; border… var(--line-strong)… }`
  line near the top; in the live `input, select, textarea` rule and in `.topbar .search`,
  `var(--line)` becomes `var(--line-strong)`.
- [ ] Run `.venv/bin/pytest -q`: all pass. Commit `ai: serif titles, small-caps labels, a focus ring and visible field borders`.

### Task 4: Easy to change, and said so

**Files:** `src/hermitcrm/usertheme.py`, `src/hermitcrm/templates/settings.html`,
`src/hermitcrm/help/settings.md`, `tests/test_tokens.py`, `tests/test_web.py`

- [ ] **Failing tests:** every css block under "Your own look: theme.css" names only real
  tokens and lints clean; the first block's colours equal the defaults in `tokens.css`;
  `usertheme.EXAMPLE` changes the accent (differs from the default); the Settings page
  shows `usertheme.EXAMPLE` (replaces the literal green in
  `test_settings_appearance_shows_the_theme_file`).
- [ ] **Implement:** `EXAMPLE` = the old blue accent, one line. Settings hint: "for example
  "make my Hermit CRM blue"". Help: the colour defaults block; a fonts paragraph
  (`--sans`, `--title-font`, `--mono`, with `--title-font: var(--sans);` as the example);
  a ready-made "cooler look" block (the earlier grey and blue palette, sans titles,
  lowercase labels, field borders at 3:1); a line that the file can also hold ordinary
  CSS rules.
- [ ] Run tests, commit `ai: the theme help shows the new defaults and a ready-made cooler look`.

### Task 5: Static URLs that change with the files

**Files:** `src/hermitcrm/web.py`, `src/hermitcrm/templates/base.html`, `tests/test_web.py`

- [ ] **Failing test:** the page links `/static/style.css?v=<asset_version()>`, and
  `asset_version(folder)` changes when a file in the folder changes.
- [ ] **Implement** `asset_version(folder=HERE / "static")` (sha256 over sorted relative
  paths and bytes, first 10 hex), a Jinja global, and `?v={{ asset_version }}` on the six
  static links in `base.html`. The footer keeps the version number.
- [ ] Run tests, commit `ai: static URLs carry a hash of the files, so an update shows its new stylesheet`.

### Task 6: The website's drawing, the docs

- [ ] `website/site/style.css`: `.mock-brand` and `.mock-title` get
  `font-family: var(--title-font); font-weight: 500;`. Run `python3 website/build.py`
  (passes the drift check; `--title-font` lands in the `.mock-box` block).
- [ ] `DESIGN.md`: "The two looks" becomes one look at two densities; `--title-font` in the
  token list; D0 replaced; field borders use `--line-strong`; the site's paper tokens hold
  the app's values (change both together).
- [ ] `CHANGELOG.md` entry after "Your own look, in one file."; `docs/ARCHITECTURE.md:236`
  dark mode; `TODO.md` "Now": send testers a new build; `.gitattributes`:
  `docs/superpowers/ export-ignore`; spec status line: decided and built.
- [ ] Commit `ai: the website's drawing and the docs follow the new look`.

### Task 7: Verify

- [ ] `.venv/bin/pytest -q` all pass; `git diff --check`.
- [ ] Serve the demo folder with the branch code on :8791; Playwright, Chromium, 1440x900
  light and dark and 390 wide: Home, Pipeline, a company, Calendar, Settings, Help. No
  console errors; computed styles: accent, page colour, `h1` serif 24px, field border
  colour, focus ring after Tab.
- [ ] `theme.css` in the demo folder with the help's cooler-look block: accent blue, `h1`
  in sans, labels lowercase. Then with `--title-font: var(--sans);` alone.
- [ ] One look in WebKit (Safari's engine) for the serif.
- [ ] The website renders its drawing in light and dark.

### Task 8: Ship and deploy (Gijs asked for the deploy)

- [ ] Leak scan (company names, slugs, domains, contact names and emails from
  `~/Code/CRM/companies` against the branch diff and history); author check
  `git log --format='%an <%ae>' origin/main..HEAD`.
- [ ] Push the branch, open the PR with what to click, squash-merge with the noreply author.
- [ ] `git -C ~/Code/HermitCRM pull --ff-only`; pytest on main;
  `hermitcrm --data ~/Code/CRM migrate --dry-run` with main's code (read-only).
- [ ] `uv tool install --reinstall --python 3.13 "hermitcrm @ git+file:///Users/gijsbos/Code/HermitCRM@main"`;
  `launchctl kickstart -k gui/$(id -u)/io.hermitcrm.serve`; curl the pages (200) and the
  new tokens; Playwright GETs of the live app for the computed look.
- [ ] Remind Gijs: testers still run the old build (new tarball, `uv tool install --reinstall .`).
