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

"""Support Hermit: a plain Ko-fi link at the foot of the sidebar on every page
and a section of its own in Settings. It opens in a new tab and the page loads
nothing from Ko-fi, so the CSP needs no exception."""

from __future__ import annotations

import re

from hermitcrm.web import CSP, SUPPORT_URL
from test_settings import demo, make_client  # noqa: F401  (demo is a fixture)


def links_to_support(html: str) -> list[str]:
    return re.findall(r'<a [^>]*href="' + re.escape(SUPPORT_URL) + r'"[^>]*>', html)


def test_sidebar_foot_links_to_ko_fi_on_every_page(demo, tmp_path):  # noqa: F811
    app, client = make_client(demo, tmp_path)
    for path in ("/pipeline", "/companies", "/help"):
        page = client.get(path).text
        foot = re.search(r'<div class="sidebar-foot">(.*?)</div>', page, re.S).group(1)
        assert "Support Hermit" in foot, path
        [tag] = links_to_support(foot)
        assert 'target="_blank"' in tag and 'rel="noopener"' in tag


def test_settings_has_a_support_section(demo, tmp_path):  # noqa: F811
    app, client = make_client(demo, tmp_path)
    page = client.get("/settings").text
    section = re.search(r'<section class="setup-step" id="support">(.*?)</section>', page, re.S).group(1)
    assert "<h2>Support Hermit</h2>" in section
    [tag] = links_to_support(section)
    assert 'rel="noopener"' in tag
    # Sidebar plus the section: nothing else on the page points there.
    assert len(links_to_support(page)) == 2


def test_the_link_needs_no_csp_exception():
    assert SUPPORT_URL == "https://ko-fi.com/gijsbos"
    assert "ko-fi" not in CSP
