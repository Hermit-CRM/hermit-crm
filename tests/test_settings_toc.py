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

"""The tabs at the top of /settings. Every section sits in exactly one tab, the
tab bar names every tab in page order, and every place the app sends you to
(a save's redirect, the red "!" in the nav, the walkthrough's links) is a
section inside a tab, so the page script can open the right one."""

from __future__ import annotations

import re
from pathlib import Path

import hermitcrm
from test_settings import demo, make_client  # noqa: F401  (demo is a fixture)

SRC = Path(hermitcrm.__file__).parent


def groups_of(page: str) -> dict[str, list[str]]:
    """Each tab's id and the section ids inside it, in page order."""
    parts = re.split(r'<div class="settings-group" id="([\w-]+)"[^>]*>', page)
    return {gid: re.findall(r'<section class="setup-step" id="([\w-]+)">', body)
            for gid, body in zip(parts[1::2], parts[2::2])}


def test_every_section_is_in_one_tab_and_the_bar_names_every_tab(demo, tmp_path):  # noqa: F811
    app, client = make_client(demo, tmp_path)
    page = client.get("/settings").text
    groups = groups_of(page)
    bar = re.search(r'<nav class="settings-tabs"[^>]*>(.*?)</nav>', page, re.S).group(1)
    assert re.findall(r'data-group="([\w-]+)"', bar) == list(groups)
    assert list(groups) == ["tab-general", "tab-mail", "tab-crm", "tab-backup", "tab-advanced"]
    sections = [s for ids in groups.values() for s in ids]
    assert len(sections) == len(set(sections))
    assert sections == re.findall(r'<section class="setup-step" id="([\w-]+)">', page)
    assert "enrichment" in groups["tab-general"]   # AI is not tucked away


def test_every_link_into_settings_lands_in_a_tab(demo, tmp_path):  # noqa: F811
    web = (SRC / "web.py").read_text()
    anchors = set(re.findall(r'anchor="([\w-]+)"', web)) - {"to-file"}   # to-file is on Home
    anchors |= set(re.findall(r'setup_done\(result, "([\w-]+)"\)', web))
    for src in [SRC / "welcome.py", *(SRC / "templates").glob("*.html")]:
        anchors |= set(re.findall(r'(?<!/help)/settings#([\w-]+)', src.read_text()))
    anchors |= {"bcc", "calendar"}   # base.html's inbox_alert_anchor
    assert {"you", "bcc", "backup", "fields", "enrichment"} <= anchors   # the scan works

    app, client = make_client(demo, tmp_path)
    page = client.get("/settings").text
    inside = {s for ids in groups_of(page).values() for s in ids}
    assert anchors <= inside, anchors - inside


def test_a_form_error_marks_its_tab(demo, tmp_path):  # noqa: F811
    """A 400 re-renders the page at the form's own URL, with no #section; the
    tab holding the error is marked so the script opens it, with a dot."""
    app, client = make_client(demo, tmp_path)
    t = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/settings").text).group(1)
    r = client.post("/settings/outcomes", data={"csrf_token": t, "outcomes": ""})
    assert r.status_code == 400
    crm = re.search(r'<div class="settings-group" id="tab-crm"([^>]*)>', r.text).group(1)
    assert "data-error" in crm
    general = re.search(r'<div class="settings-group" id="tab-general"([^>]*)>', r.text).group(1)
    assert "data-error" not in general
    bar = re.search(r'<nav class="settings-tabs"[^>]*>(.*?)</nav>', r.text, re.S).group(1)
    assert re.search(r'data-group="tab-crm">Your CRM<span class="dot"', bar)
