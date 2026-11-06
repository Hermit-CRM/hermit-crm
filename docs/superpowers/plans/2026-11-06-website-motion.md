# Website Motion (press feedback, copy confirmation, FAQ accordion) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give hermitcrm.io three small, deliberate motions: a press-and-fade on its buttons, a visible "Copied" confirmation on the install Copy button, and an animated FAQ accordion.

**Architecture:** Pure CSS in `website/site/style.css`, in one new "Motion" section placed just above the existing `prefers-reduced-motion` block, so base rules, motion rules and reduced-motion overrides cascade in that order. The only script change is `build.py`'s inline copy script, which sets a `data-state` attribute (the CSP blocks inline `style=""`, so state goes through attributes and classes). Tests are static assertions over `style.css` and the rendered home page, the same style as `tests/test_website_features.py`; feel is checked in a real browser.

**Tech Stack:** Plain CSS (`::details-content`, `interpolate-size`, `@supports`), the inline JS in `website/build.py`, pytest, Playwright browser tools for verification.

**Spec:** the find-animation-opportunities audit of hermitcrm.io from 2026-11-06 (this conversation), rows 1 to 3. Its values are copied into the tasks below. Row 4 (screenshots settling in on scroll) is out of scope.

## Global Constraints

- Work on a new branch from main: `git switch -c ai/website-motion origin/main` (the checkout is currently on `ai/stage-transition-rules`, which is unrelated). Untracked `audit/`, `.impeccable/` and `tests/fixtures/` stay untouched.
- Easing token, added once to `:root`: `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`. No other easing curve is introduced.
- Budgets: press 160ms, colour fade 150ms, copy confirmation 200ms, accordion height 220ms, accordion fade 160ms, chevron 200ms.
- Animate `transform` and `opacity` wherever possible. The only exceptions are colour fades on the three controls (row 1) and the `block-size` of the accordion (row 3).
- Reduced motion is gentler, not zero: keep fades, drop transforms and height animation.
- Hover-only behaviour sits inside `@media (hover: hover) and (pointer: fine)`.
- No new runtime dependencies. No `style=""` attributes (CSP). No JS needed for rows 1 and 3.
- Commit messages start with `ai: website:` and end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. `.venv/bin/pytest` (the full suite) must pass before every commit.
- Changing `build.py` means regenerating `website/site/index.html` with `python3 website/build.py` and committing it; check `git status` shows only the files you meant to change.
- Never put real people or companies in code, tests or docs.
- Out of scope: deploying. Deploy steps are in the `hermitcrm-website-deploy` memory; do them only on the maintainer's go-ahead.

## Review Focus

- **Touch devices:** a tap must not leave a button stuck in a faded hover colour, and must still give press feedback. Colour fades live only inside the hover media query; the press scale does not. (Task 1 test.)
- **Reduced motion:** with `prefers-reduced-motion: reduce` there is no scale on press, no accordion height animation and no chevron rotation, but state changes are still visible. (Tasks 1 and 3 tests.)
- **Repeated Copy clicks, and failure after success:** clicking Copy again inside the 2s window restarts the timer and keeps the done state; a failed copy right after a success must clear the done state. (Task 2 tests plus the browser check.)
- **Print without the script:** a closed FAQ answer must still print in full even if `beforeprint` never fires. (Task 3 test.)
- **Browsers without `interpolate-size` or `::details-content`:** accordions must still open and close, with today's snap. (Task 3 `@supports` test.)

---

### Task 1: Motion section, easing token and button press feedback (row 1)

**Files:**
- Create: `tests/test_website_motion.py`
- Modify: `website/site/style.css` (`:root` at lines 16-36, `.btn:active` at line 134, `.copy:active` at line 166, new Motion section above the reduced-motion block at line 519)

**Interfaces:**
- Produces: the `--ease-out` custom property; a `/* ── Motion ─ */` section in `style.css` that Tasks 2 and 3 append to; in the new test file, `css() -> str` (returns `website/site/style.css`) and `block(css: str, prelude: str) -> str` (the text between the braces of the first block whose prelude is exactly `prelude`, brace-matched so nested `@media`/`@supports` bodies come back whole; raises `AssertionError` naming the prelude when absent). Tasks 2 and 3 import both.

- [ ] **Step 1: Write the failing tests** in `tests/test_website_motion.py` (Apache header like the other test files; docstring: "website/site/style.css motion: static checks; feel is checked in a browser"):

```python
def test_ease_out_token_is_defined_once():
    assert css().count("--ease-out: cubic-bezier(0.23, 1, 0.32, 1);") == 1

def test_buttons_press_with_a_scale_not_a_shift():
    assert "translateY(1px)" not in css()
    assert "transform: scale(0.97)" in block(css(), ".btn:active, .copy:active")

def test_buttons_animate_the_press_in_160ms_everywhere():
    assert "transform 160ms var(--ease-out)" in block(css(), ".btn, .copy")

def test_colour_fades_only_where_hover_exists():
    hover = block(css(), "@media (hover: hover) and (pointer: fine)")
    for part in ("background-color 150ms var(--ease-out)", "border-color 150ms var(--ease-out)"):
        assert part in hover
    assert "color 150ms var(--ease-out)" in block(hover, ".site-nav a.nav-features")

def test_reduced_motion_drops_the_press_scale_and_keeps_colour_fades():
    reduce = block(css(), "@media (prefers-reduced-motion: reduce)")
    assert "transform: none" in block(reduce, ".btn:active, .copy:active")
    assert "transition-property: background-color, border-color, color" in block(reduce, ".btn, .copy")
    assert "scroll-behavior: auto !important" in block(reduce, "*")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_website_motion.py -v`
Expected: 5 FAIL (token missing, `translateY(1px)` still present, blocks not found).

- [ ] **Step 3: Implement in `website/site/style.css`**
  - Add `--ease-out: cubic-bezier(0.23, 1, 0.32, 1);` to `:root`.
  - Remove `transform: translateY(1px);` from `.btn:active` and `.copy:active`, leaving their colour declarations.
  - Insert a `/* ── Motion ──… */` section directly above the `prefers-reduced-motion` line, containing: `.btn, .copy { transition: transform 160ms var(--ease-out); }`, `.btn:active, .copy:active { transform: scale(0.97); }`, then `@media (hover: hover) and (pointer: fine)` holding `.btn, .copy { transition: transform 160ms var(--ease-out), background-color 150ms var(--ease-out), border-color 150ms var(--ease-out), color 150ms var(--ease-out); }` and `.site-nav a.nav-features { transition: background-color 150ms var(--ease-out), color 150ms var(--ease-out); }`.
  - Extend the existing `@media (prefers-reduced-motion: reduce)` block (keep its `*` scroll-behavior rule) with `.btn:active, .copy:active { transform: none; }` and `.btn, .copy { transition-property: background-color, border-color, color; }`.
  - Existing hover rules do not move.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_website_motion.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Check it in a browser.** Serve with `python3 -m http.server 8077 -d website/site` (background), open `http://localhost:8077/` with the Playwright browser tools. Confirm: (a) the Download `.btn` computed `transitionProperty` includes `transform`; (b) with the mouse held down on it, `getComputedStyle(btn).transform` is `matrix(0.97, 0, 0, 0.97, 0, 0)`; (c) after `browser_emulate_media` with `reducedMotion: "reduce"` the same press gives `none`; (d) hovering the Features pill fades its fill instead of snapping (sample `backgroundColor` at about 60ms). Stop the server afterwards.

- [ ] **Step 6: Commit.** Run `.venv/bin/pytest`, then:

```bash
git add tests/test_website_motion.py website/site/style.css
git commit -m "ai: website: press scale and colour fades on the buttons"
```

---

### Task 2: Copy confirmation (row 2)

**Files:**
- Modify: `website/build.py:585-588` (`show()` and `done()` inside the inline script of `render()`; the script sits in an f-string, so every brace is doubled as `{{ }}`)
- Modify: `website/site/style.css` (`.copy` at line 156; Motion section)
- Regenerate: `website/site/index.html`
- Test: `tests/test_website_motion.py`

**Interfaces:**
- Consumes: `--ease-out`, `css()`, `block()` from Task 1; `build.render(c)` as used by `home()` in `tests/test_website_features.py` (copy its three-line `home()` helper into the new test file).
- Produces: the attribute `data-state="done"` on the `.copy` button while "Copied" shows, absent otherwise.

- [ ] **Step 1: Write the failing tests** in `tests/test_website_motion.py`:

```python
def test_copy_script_sets_done_state_and_clears_it_on_every_other_path():
    page = home()
    assert 'show(btn.dataset.done, 2000, "done")' in page
    assert 'show(btn.dataset.failed, 4000)' in page          # failure passes no state
    assert page.count("delete btn.dataset.state") == 2         # in show() and in its timer

def test_copy_button_confirms_with_an_opacity_wash():
    c = css()
    copy = block(c, ".copy")
    assert "position: relative" in copy and "isolation: isolate" in copy
    wash = block(c, ".copy::before")
    for part in ("opacity: 0", "z-index: -1", "background: var(--green-ink)",
                 "transition: opacity 200ms var(--ease-out)"):
        assert part in wash
    assert "opacity: .12" in block(c, '.copy[data-state="done"]::before')
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_website_motion.py -v`
Expected: the two new tests FAIL.

- [ ] **Step 3: Implement the script change in `website/build.py`.** `show(text, ms)` becomes `show(text, ms, state)`: it sets `btn.dataset.state = state` when `state` is given and otherwise deletes it, before restarting the timer; the timer callback restores the label and also deletes `btn.dataset.state`. `done()` calls `show(btn.dataset.done, 2000, "done")`; `failed()` keeps `show(btn.dataset.failed, 4000)`. (`btn.dataset.done` and `.failed` are the existing label attributes; `state` is a new, separate name.)

- [ ] **Step 4: Implement the CSS in `website/site/style.css`.** Add `position: relative; isolation: isolate;` to the existing `.copy` rule. In the Motion section add `.copy::before { content: ""; position: absolute; inset: 0; z-index: -1; border-radius: inherit; background: var(--green-ink); opacity: 0; transition: opacity 200ms var(--ease-out); }` and `.copy[data-state="done"]::before { opacity: .12; }`. The reduced-motion block needs no change (opacity is the gentle form).

- [ ] **Step 5: Regenerate and verify**

Run: `python3 website/build.py && git status --short`
Expected: only `build.py`, `style.css`, `website/site/index.html` and the test file differ. If other generated files changed (sitemap dates, docs), inspect the diff and drop changes that are not yours.
Run: `.venv/bin/pytest tests/test_website_motion.py -v`
Expected: all PASS.

- [ ] **Step 6: Check it in a browser.** Serve the site as in Task 1. Stub the clipboard so the check does not depend on permissions: `navigator.clipboard.writeText = () => Promise.resolve()`. Click Copy: the label reads the done text, `btn.dataset.state === "done"`, and `getComputedStyle(btn, "::before").opacity` ends near 0.12 within about 250ms. Click again at about 1.5s: the state stays and the timer restarts (still "done" at about 3s from the first click, gone by about 3.7s). Then stub `writeText` to reject and make `document.execCommand` return false, click: the label shows the failed text and `data-state` is absent. After about 2.2s with no click the label and wash are back to idle.

- [ ] **Step 7: Commit.** Run `.venv/bin/pytest`, then:

```bash
git add website/build.py website/site/style.css website/site/index.html tests/test_website_motion.py
git commit -m "ai: website: Copy button washes green while it says Copied"
```

---

### Task 3: FAQ accordion (row 3)

**Files:**
- Modify: `website/site/style.css` (`details p` at line 235, `summary::after` and `details[open] summary::after` at lines 233-234, Motion section, existing reduced-motion block, the `@media print` block at lines 520-525)
- Test: `tests/test_website_motion.py`

**Interfaces:**
- Consumes: `--ease-out`, `css()`, `block()`, and the Motion section from Task 1.
- Produces: nothing later tasks rely on.

`<details>` appears only on the home page (11 items from `content.toml` `[questions]`). Compare pages use plain `h3`/`p`, so nothing else changes.

- [ ] **Step 1: Record the at-rest baseline** before editing. Serve the site, and in the browser run `[...document.querySelectorAll("details")].map(d => d.getBoundingClientRect().height)` and save the array in your notes (closed and open items alike).

- [ ] **Step 2: Write the failing tests** in `tests/test_website_motion.py`:

```python
def test_faq_height_and_fade_run_inside_a_support_check():
    s = block(css(), "@supports (interpolate-size: allow-keywords)")
    for part in ("interpolate-size: allow-keywords", "block-size 220ms var(--ease-out)",
                 "opacity 160ms var(--ease-out)", "content-visibility 220ms allow-discrete",
                 "block-size: 0", "overflow: clip"):
        assert part in s
    assert "block-size: auto" in block(s, "details[open]::details-content")

def test_faq_marker_rotates_instead_of_swapping_glyphs():
    c = css()
    assert "\\2212" not in c
    assert "transition: transform 200ms var(--ease-out)" in block(c, "summary::after")
    assert "rotate(45deg)" in block(c, "details[open] summary::after")

def test_answer_spacing_is_padding_so_the_clip_box_keeps_it():
    p = block(css(), "details p")
    assert "margin: 0;" in p and "padding-bottom: 24px" in p

def test_print_shows_every_answer_without_the_script():
    p = block(block(css(), "@media print"), "details::details-content")
    assert "block-size: auto" in p and "opacity: 1" in p

def test_reduced_motion_drops_height_and_rotation():
    reduce = block(css(), "@media (prefers-reduced-motion: reduce)")
    assert "transition: opacity 160ms var(--ease-out)" in block(reduce, "details::details-content")
    assert "transition: none" in block(reduce, "summary::after")
```

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_website_motion.py -v`
Expected: the five new tests FAIL.

- [ ] **Step 4: Implement in `website/site/style.css`.**
  - `details p` becomes `margin: 0; padding-bottom: 24px;`. The old bottom margin would collapse out of the clipped box and add a 24px jump when the opening animation ends.
  - `summary::after` keeps `content: "+"; color: var(--muted); font-weight: 400;` and gains `transition: transform 200ms var(--ease-out);`. Replace the `\2212` rule with `details[open] summary::after { transform: rotate(45deg); }`.
  - In the Motion section add `@supports (interpolate-size: allow-keywords) { :root { interpolate-size: allow-keywords; } details::details-content { block-size: 0; overflow: clip; opacity: 0; transition: block-size 220ms var(--ease-out), opacity 160ms var(--ease-out), content-visibility 220ms allow-discrete; } details[open]::details-content { block-size: auto; opacity: 1; } }`.
  - Reduced-motion block gains `details::details-content { transition: opacity 160ms var(--ease-out); }` and `summary::after { transition: none; }`.
  - In the existing `@media print` block, extend its `details::details-content` rule with `block-size: auto; opacity: 1;`. The print block stays after the Motion section so it wins.

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_website_motion.py -v`
Expected: all PASS.

- [ ] **Step 6: Check it in a browser.** Re-run the baseline measurement: heights must match Step 1 within 1px, and the two `open` items must not animate on first load (heights are stable from the first frame). Click "Does it run on Linux?": sample the details height with `requestAnimationFrame` over 400ms. It rises monotonically from the closed height to the open height with no 24px jump at the end, and the marker is a centred ×. Click again to close: the same in reverse. Under `reducedMotion: "reduce"` the height changes at once and the marker does not rotate. Under `browser_emulate_media` `media: "print"` every answer is visible at full height. Note in the PR that Safari and Firefox were not tested (only Chromium is available); they keep today's snap if they lack support.

- [ ] **Step 7: Commit.** Run `.venv/bin/pytest`, then:

```bash
git add website/site/style.css tests/test_website_motion.py
git commit -m "ai: website: FAQ answers open and close with a short height and fade"
```

---

## Self-Review

- **Spec coverage:** row 1 → Task 1 (token, press, hover fades, reduced motion); row 2 → Task 2; row 3 → Task 3 (including the marker and the print safeguard). Row 4 is out of scope by decision.
- **Corrected from the audit:** FAQs exist only on the home page (11), not on the compare pages.
- **Type and name consistency:** `css()`, `block()`, `home()` are defined in Task 1 (and `home()` copied in Task 2) and used with the same signatures later. `data-state` is set and read under one name. `--ease-out` is the only token added.
- **Review Focus:** each of the five lines has a named test or browser check in the task that owns the code.
- **Known limit:** the tests pin the CSS, not how it feels; the browser steps carry that. Durations can be tuned there without changing the structure.
