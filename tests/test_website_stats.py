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


"""website/build.py: the /stats/ page shell (maintainer tooling, not part of the package
or the download). The numbers are scripts/publicstats.py's; nginx includes them with SSI.

Nothing here writes into website/site/: the page is rendered to a string.
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


def content() -> dict:
    return tomllib.loads(build.CONTENT.read_text(encoding="utf-8"))


def test_stats_page_includes_the_numbers_with_a_fallback():
    c = content()
    hub, _ = build.load_compare()
    page = build.render_stats(c, hub)
    assert page.count("<h1") == 1
    assert '<!--# block name="nostats" --><p class="stats-fallback">' in page
    assert '<!--# include virtual="/stats/_numbers" stub="nostats" -->' in page
    # The block must come first: nginx only knows a stub it has already read.
    assert page.index('block name="nostats"') < page.index("include virtual")
    assert not re.search(r"\sstyle=", page), "the site's CSP blocks inline styles"
    assert '<link rel="canonical" href="https://hermitcrm.io/stats/">' in page
    assert '<a href="stats.json">stats.json</a>' in page
    assert '<a href="./">Stats</a>' in page
    assert '"@type": "WebPage"' in page and '"@type": "BreadcrumbList"' in page


def test_every_footer_links_to_the_stats_page():
    c = content()
    hub, pages = build.load_compare()
    assert "[Stats](stats/)" in c["footer"]["text"]
    assert '<a href="../stats/">Stats</a>' in build.render_about(c, hub, build.load_about())
    assert '<a href="../../stats/">Stats</a>' in build.render_compare(c, hub, pages[0], pages)
    assert '<a href="../stats/">Stats</a>' in build.render_hub(c, hub, pages)


def test_sitemap_and_llms_txt_list_the_stats_page(tmp_path, monkeypatch):
    c = content()
    hub, pages = build.load_compare()
    docs = build.read_help(ROOT / "src" / "hermitcrm" / "help", "0.7.0", date=None, source="working tree",
                           path="src/hermitcrm/help/")
    llms = build.llms_txt(c, hub, pages, build.load_about(), docs)
    assert "- [Stats](https://hermitcrm.io/stats/): " in llms and "https://hermitcrm.io/stats/stats.json" in llms
    monkeypatch.setattr(build, "SITE", tmp_path)
    build.crawl("https://hermitcrm.io", stats=True)
    assert "<loc>https://hermitcrm.io/stats/</loc><changefreq>daily</changefreq>" in (tmp_path / "sitemap.xml").read_text()


def test_the_stats_text_passes_the_tone_checks():
    problems, _ = build.check(content())
    assert not [p for p in problems if p.startswith("stats")]


def test_nginx_serves_the_numbers_from_the_volume_and_keeps_the_fragment_internal():
    conf = (ROOT / "website" / "nginx.conf").read_text()
    stats = conf[conf.index("location /stats/ {"):]
    assert "ssi on;" in stats[:stats.index("}")]
    numbers = conf[conf.index("location = /stats/_numbers {"):]
    assert "internal;" in numbers[:numbers.index("}")] and "alias /data/public/numbers.html;" in numbers
    json_block = conf[conf.index("location = /stats/stats.json {"):]
    json_block = json_block[:json_block.index("}")]
    for header in ("X-Content-Type-Options", "Referrer-Policy", "X-Robots-Tag"):
        assert header in json_block, f"an add_header in the block drops the server's {header}"
