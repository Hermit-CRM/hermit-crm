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


"""website/build.py: the features on the home page and the one list of screenshots
(maintainer tooling, not part of the package or the download).

Nothing here writes into website/site/: pages are rendered to strings.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("website_build", ROOT / "website" / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def home() -> str:
    c = tomllib.loads(build.CONTENT.read_text(encoding="utf-8"))
    build.use_shots(c, build.load_shots())
    return build.render(c)


def images(page: str) -> set[str]:
    """The files of img/ a page shows, thumbnails and screenshots alike."""
    return set(re.findall(r'(?:src|href)="(?:\.\./)*img/([^"]+\.png)"', page))


def test_every_shot_has_its_file_its_words_and_its_address():
    shots = build.load_shots()
    assert shots
    for key, shot in shots.items():
        assert (build.SITE / "img" / shot["file"]).is_file(), key
        assert shot["alt"].strip() and shot["address"].strip(), key
    files = [s["file"] for s in shots.values()]
    assert len(files) == len(set(files)), "two shots write the same file"


def test_a_shot_is_light_enough_for_a_page():
    for shot in build.load_shots().values():
        size = (build.SITE / "img" / shot["file"]).stat().st_size
        assert size <= build.SHOT_LIMIT, f"{shot['file']} is {size // 1000} KB"


def test_an_unknown_shot_stops_the_build():
    import pytest

    with pytest.raises(build.BuildError, match="nowhere"):
        build.with_shot({"shot": "nowhere"}, build.load_shots(), "test", ("image", "alt", "address"))


def test_a_section_can_say_its_own_words_for_a_shot():
    shots = build.load_shots()
    key = next(iter(shots))
    item = build.with_shot({"shot": key, "alt": "Mine"}, shots, "test", ("image", "alt", "address"))
    assert item["alt"] == "Mine" and item["image"] == shots[key]["file"]


def test_the_home_page_has_a_tile_for_every_feature_page_under_the_hero():
    page = home()
    _, features = build.load_features()
    assert len(features) >= 13
    tiles = page[page.index('class="showcase'):page.index('class="idea')]
    for p in features:
        assert f'<a class="tile" href="features/{p["slug"]}/">' in tiles, p["slug"]
        assert f'<span class="tile-name">{p["name"]}</span>' in tiles
    assert page.index('class="hero') < page.index('class="showcase') < page.index('class="idea')
    # The tiles are the overview, so there is no "all the pages" link under them; the header's Features link leads there.
    assert 'href="features/"' not in tiles
    assert 'href="features/"' in page


def test_the_home_page_and_the_feature_pages_show_the_same_screenshot_files():
    page = home()
    fhub, features = build.load_features()
    hub, _ = build.load_compare()
    c = tomllib.loads(build.CONTENT.read_text(encoding="utf-8"))
    overview = build.render_features_hub(c, hub, fhub, features)
    thumbs = lambda text: {i for i in images(text) if i.startswith("thumbs/")}  # noqa: E731
    assert thumbs(overview) == thumbs(page) and len(thumbs(page)) == len(features)
    # Every screenshot the home page shows is also on a feature page.
    on_pages = {s["image"] for p in features for s in p["sections"] if "image" in s}
    shown = {i for i in images(page) if not i.startswith(("thumbs/", "favicon", "apple-touch", "og."))}
    assert shown and shown <= on_pages
    # Each feature page can be reached from the overview and the home page, and shows its own shots.
    for p in features:
        full = build.render_feature(c, hub, fhub, p, features)
        assert {s["image"] for s in p["sections"] if "image" in s} <= images(full)


def test_each_home_section_that_has_a_page_ends_with_a_link_to_it():
    page = home()
    slugs = {p["slug"] for p in build.load_features()[1]}
    c = tomllib.loads(build.CONTENT.read_text(encoding="utf-8"))
    for section in ("file", "yours", "outreach"):
        link = c[section]["more_link"]
        assert link.removeprefix("features/").rstrip("/") in slugs, section
        assert f'<p class="more-link' in page and f'href="{link}"' in page, section


def test_the_header_has_one_features_button_on_every_page():
    c = tomllib.loads(build.CONTENT.read_text(encoding="utf-8"))
    for root in ("", "../", "../../"):
        nav = build.site_nav(c, root)
        assert nav.count("nav-features") == 1
        assert f'<a href="{root}features/" class="nav-features">Features</a>' in nav
