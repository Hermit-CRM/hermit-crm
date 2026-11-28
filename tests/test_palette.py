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

"""static/palette.js: what it may do and what the help page promises about it.

The script's behaviour is checked in a browser (see the pull request); these tests
pin the parts a later edit could quietly break: it only reads, it only asks
/search.json, every key it binds is on the help page and goes to a page that
exists, and the page it lives on gives it the hooks it needs."""

import re
from pathlib import Path

from hermitcrm import help as helpdocs

STATIC = Path(__file__).resolve().parents[1] / "src" / "hermitcrm" / "static"
SCRIPT = (STATIC / "palette.js").read_text(encoding="utf-8")


def go_keys() -> dict[str, str]:
    block = re.search(r"var GO = \{(.*?)\};", SCRIPT).group(1)
    return dict(re.findall(r'(\w): "([^"]+)"', block))


def key_list() -> list[tuple[str, str, str]]:
    block = re.search(r"var KEYS = \[(.*?)\n  \];", SCRIPT, re.S).group(1)
    return re.findall(r'\[(?:MOD \+ )?"([^"]+)", "([^"]+)", "([^"]*)"\]', block)


def test_the_palette_only_reads():
    assert "POST" not in SCRIPT and "method" not in SCRIPT and ".submit(" not in SCRIPT
    assert re.findall(r'fetch\("([^"?]+)', SCRIPT) == ["/search.json"]
    assert "innerHTML" not in SCRIPT, "results are text; build nodes, never parse HTML"


def test_the_g_keys_are_the_briefed_ones():
    assert go_keys() == {"h": "/", "p": "/pipeline", "t": "/tasks", "c": "/companies",
                         "o": "/outreach"}


def test_every_key_is_on_the_help_page():
    text = helpdocs.read("search")
    table = text.split("## Keyboard", 1)[1]
    for letter, url in go_keys().items():
        label = next(what for keys, what, where in key_list() if where == url)
        assert f"| g then {letter} | {label} |" in table, letter
    for keys, what, _ in key_list():
        if " " not in keys or keys.endswith(" K"):
            first = "Cmd K / Ctrl K" if keys.endswith("K") else keys
            assert re.search(rf"^\| {re.escape(first)} \|", table, re.M), keys
    # the palette's own "Keys" link lands on that section
    assert 'href: "/help/search#keyboard"' in SCRIPT
    assert 'id="keyboard"' in helpdocs.render(text)


def test_every_key_goes_to_a_page_that_opens(client):
    for _, _, url in key_list():
        if url:
            assert client.get(url).status_code == 200, url


def test_the_page_has_the_hooks_the_palette_needs(client):
    page = client.get("/pipeline").text
    assert '<div id="palette-root" hidden></div>' in page
    assert re.search(r'<script src="/static/palette\.js\?v=[^"]+" defer>', page)
    # "Ask Hermit: ..." fills these; without them it falls back to /ask
    assert "<details class=\"ask\" data-ask>" in page and 'id="ask-question"' in page
    assert 'id="ask-tab-ask"' in page
    # the search box still works without the script
    assert '<form class="search" action="/search" role="search"' in page
