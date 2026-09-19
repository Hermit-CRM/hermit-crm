"""Palettes for the app/site alignment proposal, their contrast checks, and preview theme.css files.

Today = src/hermitcrm/static/tokens.css on main (fd8a0f5..b83a372).
A     = today + the site's link green as the accent (+ info tint, focus ring).
B     = A + the site's warm paper neutrals, and the site's serif for titles.

Run: python3 palettes.py  -> prints the contrast table (Markdown) and writes theme-A.css, theme-B.css.
"""
from pathlib import Path

HERE = Path(__file__).parent

TODAY = {  # token: (light, dark)
    "bg": ("#fbfbfc", "#16171b"),
    "surface": ("#ffffff", "#1e1f24"),
    "surface-2": ("#f7f7f9", "#23242a"),
    "subtle": ("#f2f2f5", "#2a2b32"),
    "text": ("#1b1b1f", "#e6e6ea"),
    "muted": ("#5c5c66", "#a4a4ae"),
    "faint": ("#8e8e98", "#7c7c86"),
    "line": ("#d9d9de", "#34353d"),
    "line-strong": ("#c4c4cc", "#44454e"),
    "accent": ("#1a4fd6", "#7ea6ff"),
    "danger": ("#b00020", "#ff7a8a"),
    "info-bg": ("#eef4ff", "#1d2a44"),
    "info-line": ("#c7d8ff", "#2f4675"),
    "warn-bg": ("#fff6e3", "#362a14"),
    "warn": ("#8a5300", "#f0c46c"),
    "ok-bg": ("#e6f4ea", "#1b3325"),
    "ok": ("#1b7f3b", "#6fd28f"),
    "sidebar": ("#eeeef1", "#1b1c21"),
    "sidebar-hover": ("#e2e2e7", "#26272e"),
    "sidebar-active": ("#d9d9e0", "#30313a"),
}

# A: only what is blue today turns into the site's green. --accent takes the site's
# --green-ink (its link and focus colour), not --brand: #1E8A60 is 4.3:1 on white,
# below AA for the app's 12-14px links and for white text on the Ask button.
A_CHANGES = {
    "accent": ("#166B4A", "#6BC49A"),      # site --green-ink
    "info-bg": ("#E8F0ED", "#273332"),     # accent at 10% / 12% over the surface
    "info-line": ("#B9D3C9", "#355147"),   # accent at 30% over the surface
}

# B: A + the site's paper palette. Site values are used as they are where one exists
# (paper, card, rule, ink, muted, window bar, copy border); the rest are steps
# between them.
B_CHANGES = dict(A_CHANGES) | {
    "bg": ("#F5F1E8", "#1C1B18"),          # site --paper
    "surface": ("#FBF9F4", "#24221E"),     # site --card
    "surface-2": ("#F2EEE6", "#292723"),
    "subtle": ("#ECE7DC", "#302D28"),
    "text": ("#17181A", "#ECE7DC"),        # site --text (ink)
    "muted": ("#5C574E", "#A8A193"),       # site --muted
    "faint": ("#8F8778", "#7A7264"),       # site --copy-border
    "line": ("#D2C8B4", "#3F3A33"),        # site --rule
    "line-strong": ("#8F8778", "#7A7264"), # site --copy-border: control borders reach 3:1
    "info-bg": ("#E4EBE3", "#2D352D"),     # accent tint over the warm card
    "info-line": ("#B6CEC1", "#395343"),
    "sidebar": ("#EFEBE2", "#211F1C"),     # light: site --window-bar
    "sidebar-hover": ("#E7E1D5", "#2B2924"),  # dark: site --window-bar
    "sidebar-active": ("#DED7C8", "#35322C"),
}

PALETTES = {
    "Today": TODAY,
    "A": TODAY | A_CHANGES,
    "B": TODAY | B_CHANGES,
}

# (foreground, background, minimum, what it is)
PAIRS = [
    ("text", "bg", 4.5, "body text"),
    ("text", "surface", 4.5, "text on cards, tables, inputs"),
    ("text", "sidebar-active", 4.5, "active menu item"),
    ("text", "info-bg", 4.5, "flash message"),
    ("muted", "bg", 4.5, "12px secondary text"),
    ("muted", "surface", 4.5, "12px secondary text on cards"),
    ("muted", "sidebar", 4.5, "menu icons, sidebar notes"),
    ("faint", "surface", 3.0, "hints, placeholders (non-essential)"),
    ("accent", "bg", 4.5, "links"),
    ("accent", "surface", 4.5, "links on cards"),
    ("accent", "info-bg", 4.5, "link inside a flash message"),
    ("surface", "accent", 4.5, "Ask button, badge text"),
    ("accent", "surface", 3.0, "focus ring against a card"),
    ("line-strong", "surface", 3.0, "input and select borders"),
    ("danger", "surface", 4.5, "errors, overdue"),
    ("ok", "surface", 4.5, "won / successful"),
    ("warn", "warn-bg", 4.5, "warning text"),
]


def lum(hexcolour: str) -> float:
    h = hexcolour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


SOURCES = {  # where each option B value comes from on the site
    "bg": "site `--paper`", "surface": "site `--card`", "surface-2": "step between card and subtle",
    "subtle": "step between paper and window bar", "text": "site `--text` (`--ink`)",
    "muted": "site `--muted`", "faint": "site `--copy-border`", "line": "site `--rule`",
    "line-strong": "site `--copy-border` (3:1 for controls)", "accent": "site `--green-ink`",
    "info-bg": "accent over the card, 10-12%", "info-line": "accent over the card, 30%",
    "sidebar": "light: site `--window-bar`", "sidebar-hover": "dark: site `--window-bar`",
    "sidebar-active": "one step darker (light) / lighter (dark)",
}


def tokens_table() -> str:
    rows = ["| Token | Today light | B light | Today dark | B dark | From |", "|---|---|---|---|---|---|"]
    for token, (light, dark) in B_CHANGES.items():
        t_light, t_dark = TODAY[token]
        rows.append(f"| `--{token}` | `{t_light}` | `{light}` | `{t_dark}` | `{dark}` | {SOURCES[token]} |")
    return "\n".join(rows)


def table() -> str:
    rows = ["| Pair | Min | Today light | A light | B light | Today dark | A dark | B dark |",
            "|---|---|---|---|---|---|---|---|"]
    fails = []
    for fg, bg, minimum, what in PAIRS:
        cells = []
        for scheme in (0, 1):
            for name, pal in PALETTES.items():
                r = ratio(pal[fg][scheme], pal[bg][scheme])
                mark = "" if r >= minimum else " ✗"
                if r < minimum:
                    fails.append(f"{name} {'dark' if scheme else 'light'}: {fg} on {bg} = {r:.2f} (< {minimum})")
                cells.append(f"{r:.2f}{mark}")
        rows.append(f"| {what}: `--{fg}` on `--{bg}` | {minimum} | " + " | ".join(cells) + " |")
    return "\n".join(rows) + "\n\nBelow minimum:\n" + ("\n".join(f"- {f}" for f in fails) or "- none")


FOCUS = """
/* Keyboard focus in the accent, like the site (today the browser's own blue ring). */
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
"""

TYPE_B = """
/* Titles in the site's serif; everything you work in stays sans. */
h1, nav.sidebar .brand span, .start-cards.numbers .card h3 { font-family: var(--serif); }
h1 { font-size: 24px; font-weight: 500; letter-spacing: -.005em; }
nav.sidebar .brand span { font-size: 17px; font-weight: 500; }
.start-cards.numbers .card h3 { font-weight: 500; font-variant-numeric: lining-nums; }
/* Section labels: the site's small caps instead of lowercase. */
h2 { text-transform: none; font-variant-caps: all-small-caps; letter-spacing: .06em; font-weight: 600; }
.month-nav h2, .setup-step h2, .helpdoc h2, .feedback-saved h2, .welcome-step h2 { font-variant-caps: normal; letter-spacing: 0; }
/* Links drawn like the site's. */
a { text-decoration-thickness: 1px; text-underline-offset: 2px; }
"""


def theme_css(name: str, changes: dict, extra: str) -> str:
    lines = [f"/* Preview of option {name} from the app/site alignment proposal.",
             "   Delete this file to go back to the default look. */", ":root {"]
    for token, (light, dark) in changes.items():
        lines.append(f"  --{token}: light-dark({light}, {dark});")
    if name == "B":
        lines.append("  --shadow-color: light-dark(rgba(40, 32, 20, .16), rgba(0, 0, 0, .5));")
    lines.append("}")
    return "\n".join(lines) + "\n" + extra


if __name__ == "__main__":
    print(table())
    (HERE / "theme-A.css").write_text(theme_css("A", A_CHANGES, FOCUS), encoding="utf-8")
    (HERE / "theme-B.css").write_text(theme_css("B", B_CHANGES, FOCUS + TYPE_B), encoding="utf-8")
    print("\nwrote theme-A.css and theme-B.css")
