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


"""website/nginx.conf's security headers, and the pages that have to live with them
(maintainer tooling, not part of the package or the download).
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "website" / "site"
_spec = importlib.util.spec_from_file_location("website_build", ROOT / "website" / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

HSTS = 'add_header Strict-Transport-Security "max-age=31536000" always;'


def conf() -> str:
    """nginx.conf without its comments."""
    return re.sub(r"(?m)^\s*#.*$", "", (ROOT / "website" / "nginx.conf").read_text(encoding="utf-8"))


def blocks(text: str, keyword: str) -> list[str]:
    """The text between the braces of every `keyword ... {` block, braces matched."""
    out = []
    for found in re.finditer(rf"(?m)^\s*{keyword}\b[^{{;]*\{{", text):
        depth, i = 1, found.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        out.append(text[found.end():i - 1])
    return out


def own(block: str) -> str:
    """A server block without its nested location blocks."""
    for inner in blocks(block, "location"):
        block = block.replace(inner, "")
    return block


class Scripts(HTMLParser):
    """What a page would ask the browser to run from its own markup."""

    def __init__(self) -> None:
        super().__init__()
        self.inline: list[str] = []
        self._open = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.inline += [f"<{tag} {name}=>" for name in a if name.startswith("on")]
        if (a.get("href") or "").strip().lower().startswith("javascript:"):
            self.inline.append(f"<{tag} href=javascript:>")
        # JSON-LD is data: the browser never runs it, so the CSP does not apply.
        self._open = tag == "script" and "src" not in a and a.get("type") != "application/ld+json"

    def handle_endtag(self, tag):
        self._open = False

    def handle_data(self, data):
        if self._open and data.strip():
            self.inline.append(data.strip()[:60])


def inline_scripts(page: str) -> list[str]:
    parser = Scripts()
    parser.feed(page)
    return parser.inline


def home() -> str:
    c = tomllib.loads(build.CONTENT.read_text(encoding="utf-8"))
    build.use_shots(c, build.load_shots())
    return build.render(c)


def test_every_server_sends_hsts():
    servers = blocks(conf(), "server")
    assert len(servers) == 2, "expected the site and the www redirect"
    for server in servers:
        assert HSTS in own(server)


def test_a_location_with_its_own_headers_repeats_hsts():
    # One add_header in a location drops every header the server block set.
    with_headers = [b for b in blocks(conf(), "location") if "add_header" in b]
    assert with_headers, "stats.json sets headers of its own"
    for location in with_headers:
        assert HSTS in location


def test_scripts_may_only_come_from_the_site_itself():
    policies = re.findall(r'add_header Content-Security-Policy "([^"]*)"', conf())
    assert policies
    for policy in policies:
        assert "script-src 'unsafe-inline'" not in policy
        assert "'unsafe-eval'" not in policy
    page_policy = next(p for p in policies if "img-src" in p)
    assert "script-src 'self';" in page_policy


def test_the_built_home_page_has_no_inline_script():
    assert inline_scripts(home()) == []


def test_no_committed_page_has_an_inline_script():
    pages = sorted(SITE.rglob("*.html"))
    assert len(pages) > 10, "the file list looks wrong"
    found = {p.relative_to(SITE).as_posix(): inline_scripts(p.read_text(encoding="utf-8"))
             for p in pages}
    assert {page: scripts for page, scripts in found.items() if scripts} == {}


def test_the_home_page_loads_its_script_from_a_file_the_site_ships():
    page = home()
    assert page.count('<script src="home.js"></script>') == 1
    # At the end of the body: the script looks the buttons up as soon as it runs.
    assert page.index('<script src="home.js">') > page.index("</footer>")
    assert 'querySelectorAll("[data-copy]")' in (SITE / "home.js").read_text(encoding="utf-8")
