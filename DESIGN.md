# Hermit CRM design

How the app and the website look, where each value lives, and how the two stay
in step. The short version: **one file holds the defaults, users override on
top, and the website build fails if it drifts.**

```
 src/hermitcrm/static/tokens.css      the only place defaults live
   brand + type    --brand --ink --sans --mono --serif --title-font   (same in light and dark)
   app palette     --bg --surface --text --muted --line --accent ...
                   each one light-dark(light, dark)
        |                                        |
        | app: loaded first                      | website/build.py copies it into
        v                                        v site/app-tokens.css on every build
 static/style.css                         brand + type for the whole page,
   uses var(--*) only                     app palette only inside the drawn app
        |                                 (.mock-box); build FAILS on a missing token
        v loaded last, only if it exists
 <data folder>/theme.css                  a user's own look, written by their AI tool
```

## One look, two densities

| | App | Website |
|---|---|---|
| Palette | warm paper: `--bg`, `--surface`, `--line`, `--muted` ... | the same values: `--paper`, `--card`, `--rule`, `--muted` ... |
| Accent | the link green, `--accent` (#166b4a, dark #6bc49a) | the same, `--green-ink`; large fills in `--brand` |
| Titles | `--title-font` = `--serif`, 24px, weight 500 | `--serif` |
| Section labels | small caps | small caps |
| What you work in / read | `--sans`, 12-14px: the board, tables, forms | `--serif`, 19px: the page is for reading |
| Code font | `--mono` | `--mono` |
| Dark mode | Settings > Appearance: off, on, follow the system | follows the system |
| Logo | green `--brand`, ink parts `currentColor` | same mark, same rules |

The app and the website are one product: the same paper, the same greens, the
same serif titles and small-caps labels, in light and dark. They differ in
density only. The app is a working tool, so what you work in stays in the system
sans at 12 to 14px; the website is a page to read, so its text is serif. No web
fonts anywhere: every font is already on the computer, so nothing is downloaded
and no font host is ever asked.

Decided on 19 Sep 2026, replacing "the app stays blue" of the day before; the
options, pictures and contrast figures are in
`docs/superpowers/specs/2026-09-19-app-site-look-design.md`.

## Tokens

**Shared, in `src/hermitcrm/static/tokens.css`:**

- Brand and type, the same in light and dark: `--brand` (#1E8A60, the logo green),
  `--ink` (#17181A), `--sans`, `--mono`, `--serif`, and `--title-font` (page
  titles, the sidebar wordmark, the numbers on Home; `var(--serif)`), which lets
  a user's `theme.css` change every title with one line.
- The app palette, each `light-dark(light, dark)`: `--bg`, `--surface`,
  `--surface-2`, `--subtle`, `--text`, `--muted`, `--faint`, `--line`,
  `--line-strong`, `--accent`, `--danger`, `--info-bg`, `--info-line`,
  `--error-bg`, `--error-line`, `--warn-bg`, `--warn-line`, `--warn`, `--ok-bg`,
  `--ok`, `--sidebar`, `--sidebar-hover`, `--sidebar-active`, `--shadow-color`,
  and `--shadow` built from it.

`[data-theme]` on `<html>` only sets `color-scheme` (`light`, `dark`, or
`light dark` for "follow the system"); `light-dark()` does the rest. Browsers
without `light-dark()` (Safari before 17.5) get the light palette from an
`@supports` fallback, never a page without colours.

**Site only, in `website/site/style.css`:** `--paper`, `--card`, `--rule`,
`--text` (its light value is `--ink`), `--muted`, `--green` (= `--brand`),
`--green-press`, `--green-ink`, `--green-deep`, `--copy-border`, `--window`,
`--window-bar`, `--window-dot`, `--shadow-color`, and the layout sizes `--col`,
`--wide`, `--gutter`, `--gap`. Contrast ratios are next to each value there.
Five of them hold the app's values: `--paper` = `--bg`, `--card` = `--surface`,
`--rule` = `--line`, `--muted` = `--muted`, `--green-ink` = `--accent`. Change
them together.

## Rules

- The app's CSS uses `var(--*)` only: no colour or font literal outside
  `tokens.css`, and every `font-family` is a token, so a `theme.css` reaches
  every font. `tests/test_tokens.py` enforces this, and that every token used
  is defined, every colour is `light-dark()`, the fallback covers them all, and
  every text and control pair meets the contrast rule below in light and dark.
- To change a default, change `tokens.css`, run the tests, and rebuild the
  website (`python3 website/build.py`). If the site used a token you renamed or
  removed, the build stops and names it. Commit `site/app-tokens.css` with it.
- Never edit `website/site/app-tokens.css`; it is generated.
- Text contrast at least 4.5:1 (WCAG AA), 3:1 for large text and control
  borders, in both light and dark. Fields you type in have `--line-strong`
  borders (3:1); `--line` is for dividers and cards. Focus is always visible:
  a 2px ring in `--accent`.

## A user's own look: theme.css

Users restyle their own app, never the defaults. A `theme.css` in the data folder
holds a `:root` block of token overrides (and any ordinary rules), usually written
by their AI tool; the app links it last so it wins, and it is committed with the
rest of the data. Delete it to go back. Every look decision is a token, so most
changes are one line: `--accent` for the green, `--title-font: var(--sans);` for
sans titles. Help > Settings lists the defaults and has a ready-made cooler look
(the white, grey and blue of before 19 Sep 2026); Settings > Appearance shows
whether a theme is in use. Never rename or remove a token: a user's file names it.

It is served from one fixed path (`/theme.css`), only as a regular file inside
the data folder, as written, never cached stale. Every page carries a
Content-Security-Policy that allows only the app's own files, so a theme cannot
load or send anything elsewhere; `hermitcrm doctor` and Settings name any
`@import` or `url()` that tries. Code: `src/hermitcrm/usertheme.py`.
