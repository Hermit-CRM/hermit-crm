# Hermit CRM design

How the app and the website look, where each value lives, and how the two stay
in step. The short version: **one file holds the defaults, users override on
top, and the website build fails if it drifts.**

```
 src/hermitcrm/static/tokens.css      the only place defaults live
   brand + type    --brand --ink --sans --mono --serif   (same in light and dark)
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

## The two looks

| | App | Website |
|---|---|---|
| Accent | blue, `--accent` | logo green, `--green` = `--brand` |
| Text font | `--sans` (system sans) | `--serif` (New York, Iowan Old Style, Charter, Georgia) |
| Code font | `--mono` | `--mono` |
| Dark mode | Settings > Appearance: off, on, follow the system | follows the system |
| Logo | green `--brand`, ink parts `currentColor` | same mark, same rules |

They differ on purpose (a working tool against a quiet page) and share the brand
green, the mark and every font stack. No web fonts anywhere: every font is already
on the computer, so nothing is downloaded and no font host is ever asked.

## Tokens

**Shared, in `src/hermitcrm/static/tokens.css`:**

- Brand and type, the same in light and dark: `--brand` (#1E8A60, the logo green),
  `--ink` (#17181A), `--sans`, `--mono`, `--serif`.
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

## Rules

- The app's CSS uses `var(--*)` only: no colour or font literal outside
  `tokens.css`. `tests/test_tokens.py` enforces this, and that every token used
  is defined, every colour is `light-dark()`, and the fallback covers them all.
- To change a default, change `tokens.css`, run the tests, and rebuild the
  website (`python3 website/build.py`). If the site used a token you renamed or
  removed, the build stops and names it. Commit `site/app-tokens.css` with it.
- Never edit `website/site/app-tokens.css`; it is generated.
- Text contrast at least 4.5:1 (WCAG AA), 3:1 for large text and control
  borders, in both light and dark. Focus is always visible.

## A user's own look: theme.css

Users restyle their own app, never the defaults. A `theme.css` in the data folder
holds one `:root` block of overrides, usually written by their AI tool; the app
links it last so it wins, and it is committed with the rest of the data. Delete
it to go back. Help > Settings has the template; Settings > Appearance shows
whether it is in use.

It is served from one fixed path (`/theme.css`), only as a regular file inside
the data folder, as written, never cached stale. Every page carries a
Content-Security-Policy that allows only the app's own files, so a theme cannot
load or send anything elsewhere; `hermitcrm doctor` and Settings name any
`@import` or `url()` that tries. Code: `src/hermitcrm/usertheme.py`.
