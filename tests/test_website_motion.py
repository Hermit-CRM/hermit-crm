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


"""website/site/style.css motion: static checks on the stylesheet and the rendered
home page (maintainer tooling, not part of the package or the download).

How the motion feels is checked in a browser, not here; these tests pin the values
that were decided (durations, the easing token, reduced-motion and hover gating).
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "website" / "site" / "style.css"
_spec = importlib.util.spec_from_file_location("website_build", ROOT / "website" / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def home() -> str:
    c = tomllib.loads(build.CONTENT.read_text(encoding="utf-8"))
    build.use_shots(c, build.load_shots())
    return build.render(c)


def css() -> str:
    return CSS.read_text(encoding="utf-8")


def block(text: str, prelude: str) -> str:
    """The text between the braces of the first block whose prelude is exactly
    `prelude` (a selector list or an at-rule line). Braces are matched, so the
    body of an @media or @supports comes back whole."""
    found = re.search(r"(?:^|[{};\n])\s*" + re.escape(prelude) + r"\s*\{", text)
    assert found, f"no block for {prelude!r}"
    depth, i = 1, found.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[found.end():i - 1]


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
