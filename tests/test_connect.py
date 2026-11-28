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

"""Connect your AI: the Settings section that shows each AI app's exact line
or block for this folder, and the doctor line for the skills pack."""

import html
import json
import re
import shutil
import subprocess

import pytest
from conftest import CONFIG
from fastapi.testclient import TestClient

from hermitcrm import connect, doctor
from hermitcrm.datafolder import SKILL, SKILL_NAMES, init_folder, skill_path, skill_states
from hermitcrm.web import create_app


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


def commit_all(root, message="by hand"):
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", message)


# ------------------------------------------------------------ the values


def test_the_command_next_to_python_wins(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "python").touch()
    (tmp_path / "bin" / "hermitcrm").touch()
    found = connect.command_path(str(tmp_path / "bin" / "python"), which=lambda n: "/x/hermitcrm")
    assert found == (str(tmp_path / "bin" / "hermitcrm"), True)


def test_then_the_one_on_path_then_the_bare_name(tmp_path):
    python = str(tmp_path / "python")
    assert connect.command_path(python, which=lambda n: "/opt/bin/hermitcrm") == \
        ("/opt/bin/hermitcrm", True)
    assert connect.command_path(python, which=lambda n: None) == ("hermitcrm", False)


def test_the_blocks_for_each_app(tmp_path):
    root = tmp_path / "My CRM"
    facts = connect.facts(root, "/Users/jane/.local/bin/hermitcrm", True, "darwin",
                          [("hermit", "ok"), ("hermit-daily", "missing")])
    server = {"command": "/Users/jane/.local/bin/hermitcrm", "args": ["--data", str(root), "mcp"]}
    for app in ("desktop", "cursor"):
        assert json.loads(facts[app]["block"]) == {"mcpServers": {"hermitcrm": server}}
    assert facts["desktop"]["config_path"] == \
        "~/Library/Application Support/Claude/claude_desktop_config.json"
    assert facts["cursor"]["config_path"] == "~/.cursor/mcp.json"
    assert facts["claude_code"]["open"] == f"cd '{root}' && claude"
    assert facts["claude_code"]["mcp_add"] == (
        "claude mcp add --scope user hermitcrm -- /Users/jane/.local/bin/hermitcrm "
        f"--data '{root}' mcp")
    assert facts["skills_missing"] == ["hermit-daily"]
    # A folder with a space in its name: quoted, like the other lines.
    assert facts["migrate"] == f"hermitcrm --data '{root}' migrate"


@pytest.mark.parametrize("platform, path", [
    ("win32", r"%APPDATA%\Claude\claude_desktop_config.json"),
    ("linux", "~/.config/Claude/claude_desktop_config.json"),
])
def test_the_desktop_config_lives_elsewhere_off_a_mac(platform, path):
    assert connect.desktop_config_path(platform) == path


def test_windows_quotes_a_path_with_a_space():
    facts = connect.facts(r"C:\Users\Jane\My CRM", r"C:\tools\hermitcrm.exe", True, "win32")
    assert facts["claude_code"]["open"] == r'cd /d "C:\Users\Jane\My CRM" && claude'


# ------------------------------------------------------------- skill states


def test_skill_states_tell_ok_missing_yours_and_old(tmp_path, monkeypatch):
    from hermitcrm import datafolder

    root = init_folder(tmp_path / "crm")
    assert skill_states(root) == [("hermit", "ok"), *((n, "ok") for n in SKILL_NAMES)]
    (root / skill_path("hermit-daily")).unlink()
    (root / skill_path("hermit-log")).write_text("my own\n")
    monkeypatch.setitem(datafolder.SKILLS_PREVIOUS, "hermit-weekly", ("old\n",))
    (root / skill_path("hermit-weekly")).write_text("old\n")
    states = dict(skill_states(root))
    assert states["hermit-daily"] == "missing" and states["hermit-log"] == "yours"
    assert states["hermit-weekly"] == "old" and states["hermit"] == "ok"


# ------------------------------------------------------------------- doctor


def checks(root, tmp_path):
    found = doctor.run_checks(root, env={}, which=lambda n: "/usr/bin/git", platform="linux",
                              home=tmp_path / "home", update_fetcher=lambda: "0.0.1",
                              update_cache=tmp_path / "update.json")
    return {c.name: c for c in found}


def test_doctor_reports_the_skills_pack(tmp_path):
    root = init_folder(tmp_path / "crm")
    found = checks(root, tmp_path)
    assert found["agent skill"].status == "ok"
    assert found["agent skills"].status == "ok"
    assert "5 everyday skills" in found["agent skills"].detail

    (root / skill_path("hermit-import")).unlink()
    (root / skill_path("hermit-log")).write_text("mine\n")
    commit_all(root)
    found = checks(root, tmp_path)
    assert found["agent skill"].status == "ok"  # /hermit itself is fine
    pack = found["agent skills"]
    assert pack.status == "warn"
    assert "hermit-import" in pack.detail and "hermitcrm migrate" in pack.detail
    assert "hermit-log" not in pack.detail  # the user's own text is fine


def test_doctor_without_hermit_but_with_the_pack(tmp_path):
    root = init_folder(tmp_path / "crm")
    (root / SKILL).unlink()
    commit_all(root)
    found = checks(root, tmp_path)
    assert found["agent skill"].status == "warn" and SKILL in found["agent skill"].detail
    assert found["agent skills"].status == "ok"


# ------------------------------------------------------------- the section


@pytest.fixture
def folder(tmp_path):
    return init_folder(tmp_path / "crm", demo=True)


def section(client) -> str:
    page = client.get("/settings").text
    start = page.index('<section class="setup-step" id="connect">')
    return page[start:page.index("</section>", start)]


def test_the_section_shows_this_folders_values(folder, monkeypatch):
    monkeypatch.setattr(connect, "command_path", lambda: ("/opt/hermit/bin/hermitcrm", True))
    client = TestClient(create_app(folder, config={**CONFIG, "update_check": False}))
    page = client.get("/settings").text
    assert page.index('id="connect"') < page.index('id="mcp"')
    text = html.unescape(section(client))
    assert "Connect your AI" in text
    block = json.dumps({"mcpServers": {"hermitcrm": {
        "command": "/opt/hermit/bin/hermitcrm", "args": ["--data", str(folder), "mcp"]}}},
        indent=2)
    assert text.count(block) >= 2  # Claude Desktop and Cursor, each shown ...
    copies = [html.unescape(v) for v in re.findall(r'data-copy-text="([^"]*)"', section(client))]
    assert copies.count(block) == 2  # ... and each with its copy button
    assert f"cd {folder} && claude" in copies
    assert ("claude mcp add --scope user hermitcrm -- /opt/hermit/bin/hermitcrm "
            f"--data {folder} mcp") in copies
    for name in SKILL_NAMES:
        assert f"/{name}" in text
    assert "~/.cursor/mcp.json" in text and "claude_desktop_config.json" in text
    assert f"hermitcrm --data {folder} migrate" not in text  # every skill is there
    assert "not in this folder yet" not in text


def test_the_section_says_when_the_command_or_skills_are_missing(folder, monkeypatch):
    monkeypatch.setattr(connect, "command_path", lambda: ("hermitcrm", False))
    shutil.rmtree(folder / ".claude" / "skills" / "hermit-weekly")
    client = TestClient(create_app(folder, config={**CONFIG, "update_check": False}))
    text = html.unescape(section(client))
    assert "which hermitcrm" in text
    assert f"hermitcrm --data {folder} migrate" in text
    assert "/hermit-weekly</code> (not in this folder yet)" in text


def test_the_page_writes_nothing(folder):
    head = git(folder, "rev-parse", "HEAD")
    TestClient(create_app(folder, config={**CONFIG, "update_check": False})).get("/settings")
    assert git(folder, "status", "--porcelain") == ""
    assert git(folder, "rev-parse", "HEAD") == head


def test_the_how_it_works_link_lands_on_its_heading():
    from hermitcrm import help as helpdocs

    assert 'id="connect-your-ai"' in helpdocs.render(helpdocs.read("ai-agents"))
