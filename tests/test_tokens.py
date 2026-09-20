# Copyright 2026 Gijs Bos
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""static/tokens.css is the one place the default look lives: style.css only uses it,
the help template only names what it defines, and old browsers get a light fallback.
Also hermitcrm/usertheme.py, which finds and checks a user's theme.css."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hermitcrm import usertheme

STATIC = Path(__file__).resolve().parents[1] / "src" / "hermitcrm" / "static"
HELP = Path(__file__).resolve().parents[1] / "src" / "hermitcrm" / "help" / "settings.md"
TOKENS = (STATIC / "tokens.css").read_text(encoding="utf-8")
STYLE = (STATIC / "style.css").read_text(encoding="utf-8")

# Tokens that are the same in light and dark by design.
SCHEME_FREE = {"--brand", "--ink", "--sans", "--mono", "--serif", "--title-font", "--shadow"}

# (foreground, background, minimum): every pair that carries text or marks a
# control. DESIGN.md: 4.5:1 for text, 3:1 for control borders and hints.
CONTRAST = [
    ("--text", "--bg", 4.5), ("--text", "--surface", 4.5), ("--text", "--sidebar-active", 4.5),
    ("--text", "--info-bg", 4.5), ("--muted", "--bg", 4.5), ("--muted", "--surface", 4.5),
    ("--muted", "--sidebar", 4.5), ("--faint", "--surface", 3.0), ("--accent", "--bg", 4.5),
    ("--accent", "--surface", 4.5), ("--accent", "--info-bg", 4.5),
    ("--surface", "--accent", 4.5), ("--line-strong", "--surface", 3.0),
    ("--danger", "--surface", 4.5), ("--ok", "--surface", 4.5), ("--warn", "--warn-bg", 4.5),
]


def declarations(block: str) -> dict[str, str]:
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", block)}


def root_block(css: str) -> str:
    return re.search(r"^:root \{(.*?)^\}", css, re.S | re.M).group(1)


def fallback_block(css: str) -> str:
    inner = css.split("@supports not (color: light-dark(#000, #fff))", 1)[1]
    return re.search(r":root \{(.*?)\}", inner, re.S).group(1)


def rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """(selector, declarations) for every rule, including those inside @media."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(" ".join(sel.split()),
             {k: " ".join(v.split()) for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+);?", body)})
            for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def effective(css: str, selector: str) -> dict[str, str]:
    """The declarations for exactly this selector, a later rule winning over an
    earlier one, as the browser does for rules of equal specificity."""
    out: dict[str, str] = {}
    for sel, decls in rules(css):
        if sel == selector:
            out.update(decls)
    return out


DEFINED = declarations(root_block(TOKENS))


def light_dark(name: str, tokens: dict[str, str] = DEFINED) -> tuple[str, str]:
    return re.fullmatch(r"light-dark\((#\w+),\s*(#\w+)\)", tokens[name]).groups()


def contrast(a: str, b: str) -> float:
    """WCAG 2 contrast ratio of two #rgb or #rrggbb colours."""
    def luminance(colour: str) -> float:
        h = colour.lstrip("#")
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_every_var_used_by_the_app_is_defined_in_tokens():
    used = set(re.findall(r"var\((--[\w-]+)", STYLE))
    assert used, "style.css uses no tokens?"
    assert used - DEFINED.keys() == set()


def test_style_css_defines_no_tokens_and_no_font_stacks():
    assert re.findall(r"^\s*(--[\w-]+)\s*:", STYLE, re.M) == []
    for literal in ("-apple-system", "Menlo", "SFMono", "Helvetica", "Georgia", "serif;"):
        assert literal not in STYLE, literal
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", STYLE), "colour literal outside tokens.css"


def test_every_font_in_the_app_is_a_token():
    """So one line in theme.css changes any font, and style.css fixes none."""
    for selector, decls in rules(STYLE):
        if "font-family" in decls:
            assert re.fullmatch(r"var\(--[\w-]+\)|inherit", decls["font-family"]), selector
        if "font" in decls:
            assert re.fullmatch(r"inherit|.*\bvar\(--[\w-]+\)", decls["font"]), selector


def test_titles_use_the_title_font():
    for selector in ("h1", "nav.sidebar .brand span", ".start-cards.numbers .card h3"):
        assert effective(STYLE, selector).get("font-family") == "var(--title-font)", selector


def test_section_labels_are_small_caps_but_subtitles_are_not():
    """An h2 is a label (small caps, like the website's). An h2 that was never
    lowercased (text-transform: none) is a heading of its own and keeps its letters."""
    assert effective(STYLE, "h2").get("font-variant-caps") == "all-small-caps"
    normal = {s.strip() for sel, decls in rules(STYLE)
              if decls.get("font-variant-caps") == "normal" for s in sel.split(",")}
    subtitles = [sel for sel, decls in rules(STYLE)
                 if sel.endswith("h2") and decls.get("text-transform") == "none"]
    assert subtitles and set(subtitles) <= normal


def test_form_fields_have_borders_you_can_see():
    """DESIGN.md: control borders at least 3:1, which --line-strong is and --line is
    not. Of two rules for one selector the later wins: an earlier rule once said
    --line-strong while a later one kept every field on --line."""
    assert effective(STYLE, "input, select, textarea")["border"] == "1px solid var(--line-strong)"
    assert effective(STYLE, ".topbar .search")["border"] == "1px solid var(--line-strong)"


def test_keyboard_focus_is_a_ring_in_the_accent():
    assert effective(STYLE, ":focus-visible").get("outline") == "2px solid var(--accent)"
    # The search input sets outline: none, so the search box shows the ring instead.
    ring = effective(STYLE, ".topbar .search:focus-within").get("outline")
    assert ring == "2px solid var(--accent)"


def test_every_colour_token_is_light_dark_or_scheme_free():
    for name, value in DEFINED.items():
        if name in SCHEME_FREE:
            assert "light-dark(" not in value, name
        else:
            assert value.startswith("light-dark("), f"{name}: {value}"


def test_fallback_gives_every_colour_token_its_light_value():
    fallback = declarations(fallback_block(TOKENS))
    colour = {n: v for n, v in DEFINED.items() if v.startswith("light-dark(")}
    assert fallback.keys() == colour.keys()
    for name, value in colour.items():
        light = re.match(r"light-dark\((.*),\s*(?:#|rgba?\()", value).group(1).strip()
        assert fallback[name] == light, name


@pytest.mark.parametrize("scheme", [0, 1], ids=["light", "dark"])
@pytest.mark.parametrize("fg, bg, minimum", CONTRAST)
def test_default_colours_meet_the_contrast_rules(fg, bg, minimum, scheme):
    ratio = contrast(light_dark(fg)[scheme], light_dark(bg)[scheme])
    assert ratio >= minimum, f"{fg} on {bg}: {ratio:.2f}"


def test_titles_have_a_font_token_of_their_own():
    """Page titles, the wordmark and the Home numbers are in the website's serif; a
    user's theme.css puts them back in sans with one line: --title-font: var(--sans)."""
    assert DEFINED["--title-font"] == "var(--serif)"


def test_each_theme_sets_its_colour_scheme():
    assert re.search(r'\[data-theme="dark"\]\s*\{\s*color-scheme: dark;', TOKENS)
    assert re.search(r'\[data-theme="system"\]\s*\{\s*color-scheme: light dark;', TOKENS)


def help_theme_blocks() -> list[str]:
    """The css blocks under "Your own look: theme.css" in Help > Settings."""
    text = HELP.read_text(encoding="utf-8")
    section = re.search(r"### Your own look: theme\.css\n(.*?)\n## ", text, re.S).group(1)
    return re.findall(r"```css\n(.*?)```", section, re.S)


def test_help_templates_parse_and_name_only_real_tokens():
    blocks = help_theme_blocks()
    assert len(blocks) == 2  # the defaults, and a ready-made cooler look
    for css in blocks:
        names = declarations(root_block(css))
        assert names and set(names) <= DEFINED.keys()
        assert usertheme.lint(css) == []
    example = declarations(root_block(usertheme.EXAMPLE))
    assert example and set(example) <= DEFINED.keys()


def test_help_lists_the_real_defaults():
    """An AI tool reading the help starts from the colours the app shows."""
    for name, value in declarations(root_block(help_theme_blocks()[0])).items():
        assert value.lower() == DEFINED[name].lower(), name


@pytest.mark.parametrize("scheme", [0, 1], ids=["light", "dark"])
def test_the_ready_made_look_in_the_help_meets_the_contrast_rules(scheme):
    look = DEFINED | declarations(root_block(help_theme_blocks()[1]))
    for fg, bg, minimum in CONTRAST:
        ratio = contrast(light_dark(fg, look)[scheme], light_dark(bg, look)[scheme])
        assert ratio >= minimum, f"{fg} on {bg}: {ratio:.2f}"


def test_the_settings_example_changes_something():
    """Settings > Appearance shows it when no theme.css is in use."""
    for name, value in declarations(root_block(usertheme.EXAMPLE)).items():
        assert value != DEFINED[name], name


# ----------------------------------------------------------- usertheme.py


def test_path_only_for_a_regular_file_inside_the_folder(tmp_path):
    root = tmp_path / "crm"
    root.mkdir()
    assert usertheme.path(root) is None
    (root / "theme.css").mkdir()
    assert usertheme.path(root) is None
    (root / "theme.css").rmdir()
    outside = tmp_path / "secret.css"
    outside.write_text("x")
    (root / "theme.css").symlink_to(outside)
    assert usertheme.path(root) is None
    (root / "theme.css").unlink()
    (root / "theme.css").write_text(":root{}")
    assert usertheme.path(root) == (root / "theme.css").resolve()


@pytest.mark.parametrize("css, expected", [
    (":root { --accent: red; }", []),
    ("@import url(https://example.com/x.css);", [1]),
    ("\n\nbody { background: url('https://example.com/p.png'); }", [3]),
    ('body { background: url("/static/x.png"); }', [1]),
    ("body { background: url(data:image/png;base64,AAAA); }", []),
    ("/* @import url(https://example.com/x.css) */\n:root{}", []),
    ("/* one\ntwo */ @import 'x.css';", [2]),
])
def test_lint_names_what_the_app_blocks(css, expected):
    assert [line for line, _ in usertheme.lint(css)] == expected


def test_status(tmp_path):
    assert usertheme.status(tmp_path) == {"path": str(tmp_path / "theme.css"),
                                          "active": False, "problems": []}
    (tmp_path / "theme.css").write_bytes(b"\xff @import 'x';")
    state = usertheme.status(tmp_path)
    assert state["active"] and state["problems"][0][0] == 1
