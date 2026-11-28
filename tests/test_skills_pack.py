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

"""The skills pack: five Claude Code skills (`/hermit-daily` and the rest)
written by `init`, brought to older folders by `hermitcrm migrate`, and never
written over a text of the user's own."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from hermitcrm import cli, datafolder, mcp, migrations
from hermitcrm.datafolder import (AGENT_SKILL, SKILL, SKILL_NAMES, init_folder, skill_path,
                                  skill_text, write_skills)
from hermitcrm.mcp_meta import PROMPTS
from hermitcrm.store import Store

PACK = [skill_path(name) for name in SKILL_NAMES]


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


def commit_all(root, message="by hand"):
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", message)


def without_pack(root):
    """A folder as an older Hermit left it: the /hermit skill, no pack."""
    for name in SKILL_NAMES:
        shutil.rmtree(root / ".claude" / "skills" / name)
    commit_all(root, "an older Hermit")
    return root


def split(text):
    head, _, body = text.partition("\n---\n")
    return yaml.safe_load(head.removeprefix("---\n")), body


# ---------------------------------------------------------------- the texts


def test_the_pack_is_five_skills_each_a_file_in_the_package():
    assert SKILL_NAMES == ("hermit-daily", "hermit-log", "hermit-research", "hermit-weekly",
                           "hermit-import")
    shipped = sorted(p.stem for p in (Path(datafolder.__file__).parent / "skills").glob("*.md"))
    assert shipped == sorted(SKILL_NAMES)
    assert set(datafolder.SKILLS_PREVIOUS) == set(SKILL_NAMES)


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_each_skill_is_short_and_says_when_what_and_the_rules(name):
    text = skill_text(name)
    meta, body = split(text)
    assert meta["name"] == name and set(meta) == {"name", "description"}
    assert "Use it when" in meta["description"]
    assert body.lstrip().startswith("Use it ")  # when to use it, first
    assert "Rules:" in body
    flat = " ".join(body.split()).lower()
    assert "never send" in flat
    assert "commit" in flat and "hermitcrm undo <sha>" in flat
    assert len(body.strip().splitlines()) <= 40
    assert len(meta["description"]) <= 300
    assert max(len(line) for line in body.splitlines()) <= 84
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_skills_that_change_many_records_say_dry_run_first():
    for name in ("hermit-import", "hermit-log", "hermit-research"):
        flat = " ".join(skill_text(name).split()).lower()
        assert "dry run" in flat and "yes" in flat, name


def test_every_mcp_name_a_skill_cites_is_a_real_tool_or_prompt(tmp_path):
    root = init_folder(tmp_path / "crm")
    store = Store(root)
    store.load()
    known = {t.name for t in mcp.build_tools(root, store)} | {p.name for p in PROMPTS}
    config_keys = {"call_outcomes"}
    for name in SKILL_NAMES:
        cited = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", skill_text(name))) - config_keys
        assert cited <= known, (name, cited - known)
    # the jobs each skill exists for
    for name, tools in {
        "hermit-daily": {"morning_review", "list_tasks", "followups", "brief", "list_outreach"},
        "hermit-log": {"search_companies", "show_company", "add_interaction", "add_task",
                       "move_stage"},
        "hermit-research": {"show_company", "add_interaction", "update_company"},
        "hermit-weekly": {"weekly_review", "list_pipeline", "report", "digest",
                          "keep_in_touch", "list_tasks"},
    }.items():
        for tool in tools:
            assert f"`{tool}`" in skill_text(name), (name, tool)


def test_every_command_a_skill_cites_exists():
    parser = cli._build_parser()
    commands = next(a for a in parser._actions if a.dest == "command").choices
    for name in SKILL_NAMES:
        for line in re.findall(r"hermitcrm ([a-z-]+)(?: ([a-z-]+))?", skill_text(name)):
            command, action = line
            assert command in commands, (name, command)
            sub = [a for a in commands[command]._actions
                   if a.dest in ("action", "what") and a.choices]
            if sub and action and not action.startswith("-"):
                assert action in sub[0].choices, (name, command, action)


# --------------------------------------------------------------------- init


@pytest.mark.parametrize("demo", [False, True])
def test_init_writes_the_five_skills_and_commits_them(tmp_path, demo):
    root = init_folder(tmp_path / "crm", demo=demo)
    tracked = git(root, "ls-files").splitlines()
    for name in SKILL_NAMES:
        assert (root / skill_path(name)).read_text() == skill_text(name)
        assert skill_path(name) in tracked
    assert (root / SKILL).read_text() == AGENT_SKILL
    assert git(root, "status", "--porcelain") == ""
    assert migrations.missing_agent_files(root) == []


def test_the_cli_init_writes_them_too(tmp_path, capsys):
    assert cli.main(["init", str(tmp_path / "crm"), "--demo"]) == 0
    for path in PACK:
        assert (tmp_path / "crm" / path).is_file()


# ------------------------------------------------------- an existing folder


def test_an_older_folder_gets_the_pack_from_migrate(tmp_path, capsys):
    root = without_pack(init_folder(tmp_path / "crm"))
    assert migrations.missing_agent_files(root) == PACK
    assert PACK[0] in migrations.dry_run(root)

    # Any other command leaves the folder alone: only `migrate` writes skills.
    assert cli.main(["--data", str(root), "check"]) == 0
    assert not (root / PACK[0]).exists()

    head = git(root, "rev-parse", "HEAD")
    capsys.readouterr()
    assert cli.main(["--data", str(root), "migrate"]) == 0
    assert "migrate: write 5 Claude Code skills" in capsys.readouterr().out
    for name in SKILL_NAMES:
        assert (root / skill_path(name)).read_text() == skill_text(name)
    assert git(root, "rev-list", "--count", f"{head}..HEAD") == "1"
    assert git(root, "log", "-1", "--format=%s") == "migrate: write 5 Claude Code skills"
    assert sorted(git(root, "show", "--name-only", "--format=", "HEAD").splitlines()) == \
        sorted(PACK)
    assert git(root, "status", "--porcelain") == ""

    assert cli.main(["--data", str(root), "migrate"]) == 0
    assert capsys.readouterr().out.strip() == f"Data format {migrations.LATEST} is current."


def test_migrate_never_overwrites_a_skill_the_user_edited(tmp_path, capsys):
    root = without_pack(init_folder(tmp_path / "crm"))
    mine = root / skill_path("hermit-daily")
    mine.parent.mkdir(parents=True)
    mine.write_text("---\nname: hermit-daily\ndescription: mine\n---\n\nMy own morning.\n")
    edited = root / skill_path("hermit-weekly")
    edited.parent.mkdir(parents=True)
    edited.write_text(skill_text("hermit-weekly") + "\n- Also check my dashboard.\n")
    commit_all(root, "my own skills")
    before = {p: p.read_bytes() for p in (mine, edited)}

    assert skill_path("hermit-daily") not in migrations.missing_agent_files(root)
    assert skill_path("hermit-weekly") not in migrations.missing_agent_files(root)
    capsys.readouterr()
    assert cli.main(["--data", str(root), "migrate"]) == 0
    assert "write 3 Claude Code skills" in capsys.readouterr().out
    assert {p: p.read_bytes() for p in (mine, edited)} == before
    assert (root / skill_path("hermit-log")).read_text() == skill_text("hermit-log")
    changed = git(root, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert skill_path("hermit-daily") not in changed and skill_path("hermit-weekly") not in changed


def test_a_text_an_older_hermit_wrote_is_replaced(tmp_path, monkeypatch, capsys):
    old = "---\nname: hermit-log\ndescription: old words\n---\n\nLog it.\n"
    monkeypatch.setitem(datafolder.SKILLS_PREVIOUS, "hermit-log", (old,))
    root = init_folder(tmp_path / "crm")
    (root / skill_path("hermit-log")).write_text(old)
    commit_all(root, "as Hermit 1.x wrote it")
    assert migrations.missing_agent_files(root) == [skill_path("hermit-log")]
    assert cli.main(["--data", str(root), "migrate"]) == 0
    assert (root / skill_path("hermit-log")).read_text() == skill_text("hermit-log")
    assert git(root, "log", "-1", "--format=%s") == "migrate: write 1 Claude Code skill"


def test_a_symlink_or_unreadable_file_is_left_alone(tmp_path):
    root = without_pack(init_folder(tmp_path / "crm"))
    target = root / skill_path("hermit-import")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "elsewhere.md")
    binary = root / skill_path("hermit-log")
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\xff\xfe\x00")
    written = write_skills(root)
    assert skill_path("hermit-import") not in written and skill_path("hermit-log") not in written
    assert target.is_symlink() and not (tmp_path / "elsewhere.md").exists()
    assert binary.read_bytes() == b"\xff\xfe\x00"


def test_a_dry_run_writes_nothing(tmp_path):
    root = without_pack(init_folder(tmp_path / "crm"))
    assert write_skills(root, apply=False) == PACK
    assert not any((root / p).exists() for p in PACK)


def test_hermit_and_the_pack_missing_together_is_one_commit(tmp_path, capsys):
    root = init_folder(tmp_path / "crm")
    shutil.rmtree(root / ".claude" / "skills")
    commit_all(root, "no skills at all")
    capsys.readouterr()
    assert cli.main(["--data", str(root), "migrate"]) == 0
    out = capsys.readouterr().out
    assert "migrate: put back the /hermit skill and 5 Claude Code skills" in out
    assert (root / SKILL).read_text() == AGENT_SKILL
    assert all((root / p).is_file() for p in PACK)
    assert len(git(root, "show", "--name-only", "--format=", "HEAD").splitlines()) == 6
