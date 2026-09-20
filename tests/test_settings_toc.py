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

"""The contents line at the top of /settings: every section of the page, in
page order, named by the start of its heading. Appearance went missing from it
when the section was added, and the AI section was listed as "Enrichment"."""

from __future__ import annotations

import re

from test_settings import demo, make_client  # noqa: F401  (demo is a fixture)


def text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_contents_line_lists_every_section_by_its_heading(demo, tmp_path):  # noqa: F811
    app, client = make_client(demo, tmp_path)
    page = client.get("/settings").text
    toc = re.search(r'<p class="small settings-toc">(.*?)</p>', page, re.S).group(1)
    listed = [(anchor, re.sub(r"\s*\(\d+\)$", "", text(label)))
              for anchor, label in re.findall(r'<a href="#([\w-]+)">(.*?)</a>', toc, re.S)]
    sections = [(anchor, text(heading)) for anchor, heading in re.findall(
        r'<section class="setup-step" id="([\w-]+)">\s*<h2>(.*?)</h2>', page, re.S)]

    assert [a for a, _ in listed] == [a for a, _ in sections]
    for (anchor, label), (_, heading) in zip(listed, sections):
        assert heading.startswith(label), (anchor, label, heading)
