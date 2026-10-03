# Make it yours: the look

A recipe for your AI agent: change Hermit's colours, fonts and density with one `theme.css` in the data folder.

Read `hermitcrm help adjust` first; its rules apply here too.

## What the user can ask for

"Make it blue", "cooler and more compact", "darker sidebar", "titles in the
same font as the rest", "bigger text", "less rounded". Anything about colour,
font, spacing and borders. Not: moving or hiding parts of a page (that is
`hermitcrm help adjust-layout`).

## The file you may write

`theme.css` in the data folder, nothing else. The app loads it after its own
styles, so whatever it sets wins, and it is read on every page: the change shows
on the next page load. Deleting the file brings the default look back. Never
edit `static/tokens.css` or `style.css` in the Hermit CRM package.

## Tokens

Most looks need one `:root` block of tokens. A colour is
`light-dark(<light value>, <dark value>)`, so one line covers night mode off and
on. The tokens worth changing, with their defaults:

| Token | What it colours | Default |
|---|---|---|
| `--accent` | links, buttons, focus | `light-dark(#166b4a, #6bc49a)` |
| `--bg` | page background | `light-dark(#f5f1e8, #1c1b18)` |
| `--surface` | cards and tables | `light-dark(#fbf9f4, #24221e)` |
| `--surface-2` | quiet boxes | `light-dark(#f2eee6, #292723)` |
| `--subtle` | table headers, buttons | `light-dark(#ece7dc, #302d28)` |
| `--text` | body text | `light-dark(#17181a, #ece7dc)` |
| `--muted` | secondary text | `light-dark(#5c574e, #a8a193)` |
| `--line` | borders | `light-dark(#d2c8b4, #3f3a33)` |
| `--line-strong` | borders of fields you type in | `light-dark(#8f8778, #7a7264)` |
| `--sidebar` | the menu on the left | `light-dark(#efebe2, #211f1c)` |
| `--sidebar-hover` | a menu item under the mouse | `light-dark(#e7e1d5, #2b2924)` |
| `--sidebar-active` | the menu item you are on | `light-dark(#ded7c8, #35322c)` |
| `--sans` | the main font | the system's sans-serif |
| `--title-font` | page titles, the name in the menu, the numbers on Home | `var(--serif)` |
| `--mono` | code and text boxes | the system's monospace |

The full list is `static/tokens.css` in the installed package: read it there,
never change it.

A warmer or cooler look means every grey moves together: `--bg`, `--surface`,
`--surface-2`, `--subtle`, `--line`, `--sidebar`, `--sidebar-hover` and
`--sidebar-active`. Change one and leave the rest, and the old colour shows as
a beige menu item or a brown border.

## Worked example

"Make Hermit cooler and more compact: a blue accent and tighter table rows."
Write `theme.css`:

```css
/* My look for Hermit CRM. Delete this file to go back to the default. */
:root {
  --accent: light-dark(#1a4fd6, #7ea6ff);
  --bg: light-dark(#fbfbfc, #16171b);
  --surface: light-dark(#ffffff, #1e1f24);
  --surface-2: light-dark(#f7f7f9, #23242a);
  --subtle: light-dark(#f2f2f5, #2a2b32);
  --line: light-dark(#d9d9de, #34353d);
  --sidebar: light-dark(#eeeef1, #1b1c21);
  --sidebar-hover: light-dark(#e4e4e8, #25262c);
  --sidebar-active: light-dark(#dadae0, #2f3037);
  --title-font: var(--sans);
}
/* tighter tables */
th, td { padding: 2px 6px; }
```

Then:

```bash
hermitcrm check
git add theme.css && git commit -m "ai: adjust: cooler, more compact look"
```

If `theme.css` already exists, change it rather than starting over: keep what
the user had unless they asked for a fresh look.

## Check

`hermitcrm check` names each line the app will block and each token that is
almost a real one:

```text
theme.css: line 4: url(https://fonts.example.com/a.woff) loads a file; the app blocks it (only data: URLs work)
theme.css: line 2: --acent is not a token the app uses (did you mean --accent?)
```

## Safety

- The file cannot load anything: `@import` and `url()` to another file or site
  are blocked, so fonts must be ones already on the computer.
- Keep text readable: at least 4.5:1 contrast against its background, in both
  light and dark.
- Plain CSS rules may follow the `:root` block, but keep them few: class names
  in the app can change between versions, tokens do not.
- Commit: `ai: adjust: <what>`. Undo: `hermitcrm undo <commit>`, or delete the
  file and commit that.

Related: [Make it yours](/help/adjust), [Settings](/help/settings)
