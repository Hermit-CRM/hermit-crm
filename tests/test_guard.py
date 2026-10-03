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

"""The data folder's Claude Code deny list: written at init, merged, migrated, checked."""

import json
import subprocess

import pytest

from hermitcrm import cli, datafolder, guard, migrations


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


def settings(root):
    return json.loads((root / guard.SETTINGS).read_text(encoding="utf-8"))


def at_format_5(root, claude_md=None, agents_md=None, gitignore_claude=False):
    """A folder as format 5 left it: no .claude/, agent rules without backups."""
    datafolder.init_folder(root)
    subprocess.run(["rm", "-rf", str(root / ".claude")], check=True)
    old = datafolder.AGENT_RULES.replace(datafolder.AGENT_BACKUP_RULES, "")
    (root / "CLAUDE.md").write_text(claude_md if claude_md is not None else old)
    (root / "AGENTS.md").write_text(agents_md if agents_md is not None else old)
    if gitignore_claude:
        with (root / ".gitignore").open("a") as f:
            f.write(".claude/\n")
    migrations.write_format(root, 5)
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "fmt 5")
    return root


def test_the_list_blocks_what_the_help_promises():
    for rule in ("Bash(git reset --hard:*)", "Bash(git commit --amend:*)",
                 "Bash(git rebase:*)", "Bash(git push --force:*)", "Bash(git push -f:*)",
                 "Bash(git clean -f:*)", "Bash(git -C * commit --amend*)",
                 "Bash(git -C * reset --hard*)", "Bash(rm -rf .git:*)",
                 "Edit(~/.hermitcrm/**)", "Edit(.claude/settings.json)"):
        assert rule in guard.DENY
    assert len(guard.DENY) == len(set(guard.DENY))
    assert not [rule for rule in guard.DENY if rule.startswith("Write(")]  # never matched


def test_init_writes_and_commits_it(tmp_path):
    root = datafolder.init_folder(tmp_path / "crm")
    assert settings(root)["permissions"]["deny"] == guard.DENY
    assert guard.SETTINGS in git(root, "ls-files").splitlines()  # a clone keeps it
    assert guard.missing(root) == []
    rules = (root / "CLAUDE.md").read_text()
    assert "these commands are blocked" in rules and "hermitcrm backup restore" in rules
    assert (root / "AGENTS.md").read_text() == rules


def test_merge_keeps_what_is_there_and_adds_once(tmp_path):
    (tmp_path / ".claude").mkdir()
    mine = {"model": "x", "permissions": {"allow": ["Bash(ls:*)"],
                                          "deny": ["Bash(curl:*)", guard.DENY[0]]}}
    (tmp_path / guard.SETTINGS).write_text(json.dumps(mine))
    added = guard.write(tmp_path)
    assert added == guard.DENY[1:]
    data = settings(tmp_path)
    assert data["model"] == "x" and data["permissions"]["allow"] == ["Bash(ls:*)"]
    assert data["permissions"]["deny"][:2] == ["Bash(curl:*)", guard.DENY[0]]
    assert guard.write(tmp_path) == []
    assert settings(tmp_path) == data


def test_dry_write_changes_nothing(tmp_path):
    assert guard.write(tmp_path, apply=False) == guard.DENY
    assert not (tmp_path / ".claude").exists()


@pytest.mark.parametrize("text", ["{not json", "[]", '{"permissions": []}',
                                  '{"permissions": {"deny": "x"}}'])
def test_a_file_it_cannot_merge_into_is_left_alone(tmp_path, text):
    (tmp_path / ".claude").mkdir()
    (tmp_path / guard.SETTINGS).write_text(text)
    with pytest.raises(guard.GuardError):
        guard.write(tmp_path)
    assert (tmp_path / guard.SETTINGS).read_text() == text


def test_migration_6_adds_the_list_and_the_rules_in_one_commit(tmp_path):
    root = at_format_5(tmp_path / "crm",
                       claude_md="# Rules\n\nRead PIPELINE.md.\n\n## Personal\n\n- mine\n",
                       agents_md="# Rules\n\nRead PIPELINE.md.\n")
    before = git(root, "rev-parse", "HEAD")
    note = migrations.ensure_current(root)
    assert "agents may not rewrite history" in note
    assert guard.missing(root) == []
    claude = (root / "CLAUDE.md").read_text()
    # before the user's own heading, not after it
    assert claude.index("Backups and undo") < claude.index("## Personal")
    assert claude.endswith("## Personal\n\n- mine\n")
    # format 8 adds the Make it yours rules after them, in the same commit
    agents = (root / "AGENTS.md").read_text()
    assert agents.endswith(datafolder.AGENT_BACKUP_RULES + "\n" + datafolder.AGENT_ADJUST_RULES)
    assert git(root, "rev-list", "--count", f"{before}..HEAD") == "1"
    committed = git(root, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert set(committed) == {".hermitcrm-format", guard.SETTINGS, "CLAUDE.md", "AGENTS.md",
                              datafolder.SKILL}
    assert git(root, "status", "--porcelain") == ""
    assert migrations.ensure_current(root) == ""  # once


def test_migration_6_leaves_rules_that_already_cover_backups(tmp_path):
    root = at_format_5(tmp_path / "crm", claude_md="see hermitcrm backup list\n")
    (root / "AGENTS.md").unlink()
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam", "rm")
    migrations.ensure_current(root)
    claude = (root / "CLAUDE.md").read_text()
    assert claude.startswith("see hermitcrm backup list\n")
    assert "Backups and undo" not in claude  # format 8 adds only its own section
    assert not (root / "AGENTS.md").exists()  # not recreated


def test_migration_6_with_claude_folder_gitignored(tmp_path):
    root = at_format_5(tmp_path / "crm", gitignore_claude=True)
    (root / ".claude").mkdir()
    (root / guard.SETTINGS).write_text('{"permissions": {"allow": ["Bash(ls:*)"]}}')
    note = migrations.ensure_current(root)
    assert "4 file(s) changed" in note  # settings.json, the /hermit skill, CLAUDE/AGENTS.md
    assert guard.missing(root) == []  # on disk ...
    assert settings(root)["permissions"]["allow"] == ["Bash(ls:*)"]
    assert guard.SETTINGS not in git(root, "ls-files").splitlines()  # ... not in git
    assert migrations.current_format(root) == migrations.LATEST
    assert git(root, "status", "--porcelain") == ""


def test_migration_6_skips_a_broken_settings_file(tmp_path):
    root = at_format_5(tmp_path / "crm")
    (root / ".claude").mkdir()
    (root / guard.SETTINGS).write_text("{oops")
    migrations.ensure_current(root)
    assert (root / guard.SETTINGS).read_text() == "{oops"
    assert migrations.current_format(root) == migrations.LATEST


def test_dry_run_lists_it(tmp_path):
    root = at_format_5(tmp_path / "crm")
    text = migrations.dry_run(root)
    assert guard.SETTINGS in text and "CLAUDE.md" in text
    assert not (root / ".claude").exists()


def test_cli_backup_guard_puts_rules_back(tmp_path, capsys):
    root = datafolder.init_folder(tmp_path / "crm")
    data = settings(root)
    data["permissions"]["deny"].remove("Bash(git rebase:*)")
    (root / guard.SETTINGS).write_text(json.dumps(data))
    assert guard.missing(root) == ["Bash(git rebase:*)"]
    assert cli.main(["--data", str(root), "backup", "guard"]) == 0
    assert "added 1 deny rule" in capsys.readouterr().out
    assert cli.main(["--data", str(root), "backup", "guard"]) == 0
    assert "already blocks all" in capsys.readouterr().out
    (root / guard.SETTINGS).write_text("{oops")
    assert cli.main(["--data", str(root), "backup", "guard"]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_help_says_it_is_blocked():
    from hermitcrm import help as helptext

    backups = helptext.read("backups")
    assert "## Dangerous git commands are blocked" in backups
    assert "seat belt, not a lock" in backups and "Claude Code only" in backups
    assert "blocked, not just discouraged" in helptext.read("ai-agents")
