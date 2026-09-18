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
SCHEME_FREE = {"--brand", "--ink", "--sans", "--mono", "--serif", "--shadow"}


def declarations(block: str) -> dict[str, str]:
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", block)}


def root_block(css: str) -> str:
    return re.search(r"^:root \{(.*?)^\}", css, re.S | re.M).group(1)


def fallback_block(css: str) -> str:
    inner = css.split("@supports not (color: light-dark(#000, #fff))", 1)[1]
    return re.search(r":root \{(.*?)\}", inner, re.S).group(1)


DEFINED = declarations(root_block(TOKENS))


def test_every_var_used_by_the_app_is_defined_in_tokens():
    used = set(re.findall(r"var\((--[\w-]+)", STYLE))
    assert used, "style.css uses no tokens?"
    assert used - DEFINED.keys() == set()


def test_style_css_defines_no_tokens_and_no_font_stacks():
    assert re.findall(r"^\s*(--[\w-]+)\s*:", STYLE, re.M) == []
    for literal in ("-apple-system", "Menlo", "SFMono", "Helvetica", "Georgia", "serif;"):
        assert literal not in STYLE, literal
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", STYLE), "colour literal outside tokens.css"


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


def test_each_theme_sets_its_colour_scheme():
    assert re.search(r'\[data-theme="dark"\]\s*\{\s*color-scheme: dark;', TOKENS)
    assert re.search(r'\[data-theme="system"\]\s*\{\s*color-scheme: light dark;', TOKENS)


def test_help_template_parses_and_names_only_real_tokens():
    text = HELP.read_text(encoding="utf-8")
    css = re.search(r"### Your own look: theme\.css.*?```css\n(.*?)```", text, re.S).group(1)
    names = declarations(root_block(css))
    assert names and set(names) <= DEFINED.keys()
    assert usertheme.lint(css) == []
    example = declarations(root_block(usertheme.EXAMPLE))
    assert example and set(example) <= DEFINED.keys()


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
