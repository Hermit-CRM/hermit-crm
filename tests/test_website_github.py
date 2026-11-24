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


"""website/build.py: the GitHub link in the top bar and "Star on GitHub" on the home page.

The star count is fetched at build time and baked into the HTML; a page never asks
GitHub or a badge service itself. Without a count the link says "GitHub". Nothing
here touches the network or writes into website/site/.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("website_build", ROOT / "website" / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

REPO = "https://github.com/Hermit-CRM/hermit-crm"


def content(stars=None) -> dict:
    c = tomllib.loads(build.CONTENT.read_text(encoding="utf-8"))
    c["links"]["github_stars"] = stars
    return c


def nav_github(html: str) -> str:
    return re.search(r'<a class="nav-github".*?</a>', html).group(0)


def test_nav_shows_the_baked_in_star_count():
    a = nav_github(build.site_nav(content(41), ""))
    assert f'href="{REPO}"' in a
    assert 'rel="noopener"' in a and 'aria-label="Hermit CRM on GitHub"' in a
    assert "target=" not in a  # same tab
    assert "<span>★ 41</span>" in a


def test_nav_falls_back_to_the_word_github_without_a_count():
    a = nav_github(build.site_nav(content(None), "../"))
    assert "★" not in a
    assert '<span class="nav-github-word">GitHub</span>' in a


def test_every_page_and_the_home_page_carry_the_link():
    c = content(7)
    hub, pages = build.load_compare()
    for page in (build.render(c), build.render_hub(c, hub, pages),
                 build.render_about(c, hub, build.load_about())):
        assert "<span>★ 7</span>" in nav_github(page)


def test_star_button_sits_beside_download_on_the_home_page_only():
    c = content(3)
    home = build.render(c)
    actions = re.search(r'<div class="actions">.*?</div>', home).group(0)
    assert actions.index('class="btn"') < actions.index('class="btn btn-secondary"')
    assert "Star on GitHub" in actions and 'rel="noopener"' in actions
    assert home.count("Star on GitHub") == 1  # not in the closing section
    hub, _ = build.load_compare()
    assert "Star on GitHub" not in build.render_about(c, hub, build.load_about())


def test_no_github_request_from_the_page():
    home = build.render(content(41))
    assert "api.github.com" not in home and "shields.io" not in home


def test_empty_github_link_hides_both():
    c = content(41)
    c["links"]["github"] = ""
    home = build.render(c)
    assert "nav-github" not in home and "Star on GitHub" not in home


@pytest.mark.parametrize("n, text", [(0, "0"), (41, "41"), (999, "999"), (1000, "1k"),
                                     (1234, "1.2k"), (9999, "10k"), (12345, "12k")])
def test_star_text(n, text):
    assert build.star_text(n) == text


def test_fetch_failure_means_no_number(monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.delenv("HERMIT_SITE_OFFLINE", raising=False)
    monkeypatch.setattr(build, "urlopen", boom)
    assert build.fetch_stars(REPO) is None
    assert "no GitHub star count" in capsys.readouterr().out


def test_offline_switch_and_odd_urls_skip_the_request(monkeypatch):
    def never(*a, **k):
        raise AssertionError("must not be called")
    monkeypatch.setattr(build, "urlopen", never)
    monkeypatch.setenv("HERMIT_SITE_OFFLINE", "1")
    assert build.fetch_stars(REPO) is None
    monkeypatch.delenv("HERMIT_SITE_OFFLINE")
    assert build.fetch_stars("https://example.com/a/b") is None
    assert build.fetch_stars("https://github.com/only-owner") is None


def test_fetch_reads_stargazers_count(monkeypatch):
    class Reply:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self, *a):
            return b'{"stargazers_count": 41}'
    seen = {}
    def fake(req, timeout):
        seen["url"] = req.full_url
        return Reply()
    monkeypatch.delenv("HERMIT_SITE_OFFLINE", raising=False)
    monkeypatch.setattr(build, "urlopen", fake)
    assert build.fetch_stars(REPO) == 41
    assert seen["url"] == "https://api.github.com/repos/Hermit-CRM/hermit-crm"
    assert isinstance(urllib.request.Request("https://example.com"), build.Request)
