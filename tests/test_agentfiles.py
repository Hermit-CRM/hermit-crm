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

"""The agent files of Make it yours: the /hermit skill and the "Adjusting Hermit"
rules, written by `init`, brought to older folders by data format 8, checked by
`doctor` and put back by `hermitcrm migrate`."""

import subprocess

import pytest
import yaml

from hermitcrm import cli, datafolder, doctor, migrations
from hermitcrm.datafolder import (AGENT_ADJUST_RULES, AGENT_RULES, AGENT_SKILL, SKILL,
                                  init_folder)

ROUTINES_STATE = "inbox/.last-routines.json"


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


def commit_all(root, message="by hand"):
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", message)


def at_format_7(root, claude_md=None, agents_md=None, gitignore=None):
    """A folder as format 7 left it: no skill, rules without the adjust section,
    and a .gitignore from before routines existed."""
    init_folder(root)
    subprocess.run(["rm", "-rf", str(root / ".claude" / "skills")], check=True)
    old = AGENT_RULES.replace("\n" + AGENT_ADJUST_RULES, "")
    for name, text in (("CLAUDE.md", claude_md), ("AGENTS.md", agents_md)):
        if text is False:
            (root / name).unlink()
        else:
            (root / name).write_text(old if text is None else text, encoding="utf-8")
    ignore = root / ".gitignore"
    if gitignore is False:
        ignore.unlink()
    else:
        ignore.write_text(gitignore if gitignore is not None else
                          ignore.read_text().replace(ROUTINES_STATE + "\n", ""))
    migrations.write_format(root, 7)
    commit_all(root, "fmt 7")
    return root


def checks(root, tmp_path):
    found = doctor.run_checks(root, env={}, which=lambda n: "/usr/bin/git", platform="linux",
                              home=tmp_path / "home", update_fetcher=lambda: "0.0.1",
                              update_cache=tmp_path / "update.json")
    return {c.name: c for c in found}


# ---------------------------------------------------------------- the texts


def test_the_skill_is_a_thin_claude_code_skill():
    head, _, body = AGENT_SKILL.partition("\n---\n")
    meta = yaml.safe_load(head.removeprefix("---\n"))
    assert meta["name"] == "hermit"
    for word in ("Change, adjust, automate or customise this CRM", "fields", "dashboards",
                 "page layout", "bulk changes", "routines", "messages", "the look"):
        assert word in meta["description"]
    assert "hermitcrm help adjust" in body and "Asked on <title> (<path>)" in body
    assert len(body.strip().splitlines()) <= 12  # the substance lives in the help topics


def test_the_rules_section_says_the_rules_in_twelve_lines():
    lines = AGENT_ADJUST_RULES.strip().splitlines()
    assert len(lines) <= 12 and lines[0].startswith("Adjusting Hermit")
    text = " ".join(AGENT_ADJUST_RULES.split())
    for needle in ("hermitcrm help adjust", "fields.toml", "layout.toml", "dashboards/*.toml",
                   "routines.toml", "theme.css", "messages.toml", "MESSAGING.md",
                   "task_types", "outcomes", "silent_days", "hermitcrm add", "hermitcrm set",
                   "dry run", "wait for a yes", "hermitcrm check", "ai: adjust: <what>",
                   "hermitcrm undo <sha>", "Never send anything"):
        assert needle in text, needle
    assert max(len(line) for line in lines) <= 80


# --------------------------------------------------------------------- init


@pytest.mark.parametrize("demo", [False, True])
def test_init_writes_the_skill_and_the_section(tmp_path, demo):
    root = init_folder(tmp_path / "crm", demo=demo)
    assert (root / SKILL).read_text() == AGENT_SKILL
    assert SKILL in git(root, "ls-files").splitlines()  # a clone has it too
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (root / name).read_text()
        assert text.endswith(AGENT_ADJUST_RULES)
        assert text.index("Backups and undo") < text.index("Adjusting Hermit")
    assert ROUTINES_STATE in (root / ".gitignore").read_text().splitlines()
    assert git(root, "status", "--porcelain") == ""


# ------------------------------------------------------------- migration 8


def test_migration_8_brings_a_format_7_folder_level_with_a_new_one(tmp_path):
    root = at_format_7(tmp_path / "crm")
    before = git(root, "rev-parse", "HEAD")
    note = migrations.ensure_current(root)
    assert note.startswith("migrate: data format 7 → 8 (agents learn to adjust Hermit "
                           "(/hermit skill)): 4 file(s) changed")
    assert git(root, "rev-list", "--count", f"{before}..HEAD") == "1"
    committed = git(root, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert set(committed) == {".hermitcrm-format", SKILL, "CLAUDE.md", "AGENTS.md",
                              ".gitignore"}
    fresh = init_folder(tmp_path / "fresh")
    for name in ("CLAUDE.md", "AGENTS.md", SKILL):
        assert (root / name).read_bytes() == (fresh / name).read_bytes(), name
    ignored = (root / ".gitignore").read_text().splitlines()
    assert sorted(ignored) == sorted((fresh / ".gitignore").read_text().splitlines())
    assert ignored[-1] == ROUTINES_STATE  # added at the end, the rest as it was
    assert git(root, "status", "--porcelain") == ""


def test_migration_8_is_idempotent(tmp_path):
    root = at_format_7(tmp_path / "crm")
    migrations.ensure_current(root)
    head = git(root, "rev-parse", "HEAD")
    snapshot = {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git/" not in
                p.as_posix()}
    assert migrations.ensure_current(root) == ""
    assert migrations.m8_adjust_skill(root, {}, write=True) == []
    migrations.write_format(root, 7)
    assert migrations.ensure_current(root).endswith(": 0 file(s) changed")
    assert {p: p.read_bytes() for p in snapshot} == snapshot
    assert git(root, "rev-parse", "HEAD") == head


def test_migration_8_dry_run_lists_exactly_what_it_would_change(tmp_path):
    root = at_format_7(tmp_path / "crm", agents_md=False)
    claude = (root / "CLAUDE.md").read_bytes()
    text = migrations.dry_run(root)
    assert "Data format 7 → 8:" in text
    assert "8. agents learn to adjust Hermit (/hermit skill): 3 file(s)" in text
    listed = [line.strip() for line in text.splitlines()[2:-1]]
    assert listed == [SKILL, "CLAUDE.md", ".gitignore"]
    assert not (root / SKILL).exists() and (root / "CLAUDE.md").read_bytes() == claude
    assert migrations.current_format(root) == 7


def test_migration_8_puts_the_section_before_the_users_own_headings(tmp_path):
    mine = "# Rules\n\nRead PIPELINE.md.\n\n## Personal\n\n- mine\n"
    root = at_format_7(tmp_path / "crm", claude_md=mine)
    migrations.ensure_current(root)
    claude = (root / "CLAUDE.md").read_text()
    assert claude.index("Adjusting Hermit") < claude.index("## Personal")
    assert claude.endswith("## Personal\n\n- mine\n")
    assert claude.startswith("# Rules\n\nRead PIPELINE.md.\n\n")


def test_migration_8_without_claude_or_agents_md_writes_only_the_skill(tmp_path):
    root = at_format_7(tmp_path / "crm", claude_md=False, agents_md=False)
    migrations.ensure_current(root)
    assert not (root / "CLAUDE.md").exists() and not (root / "AGENTS.md").exists()
    assert (root / SKILL).read_text() == AGENT_SKILL


def test_migration_8_leaves_rules_that_already_point_at_adjust(tmp_path):
    root = at_format_7(tmp_path / "crm", claude_md="Run `hermitcrm help adjust` first.\n")
    migrations.ensure_current(root)
    assert (root / "CLAUDE.md").read_text() == "Run `hermitcrm help adjust` first.\n"
    assert "Adjusting Hermit" in (root / "AGENTS.md").read_text()


def test_migration_8_keeps_a_skill_of_the_users_own(tmp_path):
    root = at_format_7(tmp_path / "crm")
    own = "---\nname: hermit\ndescription: my own\n---\n\nDo it my way.\n"
    (root / SKILL).parent.mkdir(parents=True)
    (root / SKILL).write_text(own)
    commit_all(root)
    assert SKILL not in migrations.dry_run(root)
    migrations.ensure_current(root)
    assert (root / SKILL).read_text() == own
    assert SKILL not in git(root, "show", "--name-only", "--format=", "HEAD").splitlines()


def test_migration_8_replaces_a_skill_an_older_hermit_wrote(tmp_path, monkeypatch):
    old = "---\nname: hermit\ndescription: old words\n---\n\nRun hermitcrm help adjust.\n"
    monkeypatch.setattr(datafolder, "AGENT_SKILL_PREVIOUS", (old,))
    root = at_format_7(tmp_path / "crm")
    (root / SKILL).parent.mkdir(parents=True)
    (root / SKILL).write_text(old)
    commit_all(root)
    migrations.ensure_current(root)
    assert (root / SKILL).read_text() == AGENT_SKILL
    assert SKILL in git(root, "show", "--name-only", "--format=", "HEAD").splitlines()


def test_migration_8_with_claude_folder_gitignored(tmp_path):
    root = at_format_7(tmp_path / "crm")
    with (root / ".gitignore").open("a") as f:
        f.write(".claude/\n")
    git(root, "rm", "-rq", "--cached", ".claude")
    commit_all(root, "keep .claude out of git")
    note = migrations.ensure_current(root)
    assert "4 file(s) changed" in note
    assert (root / SKILL).read_text() == AGENT_SKILL                      # on disk ...
    assert SKILL not in git(root, "ls-files").splitlines()               # ... not in git
    assert git(root, "check-ignore", SKILL) == SKILL                     # never force-added
    assert migrations.current_format(root) == migrations.LATEST
    assert git(root, "status", "--porcelain") == ""


def test_migration_8_gitignore_keeps_every_other_byte(tmp_path):
    root = at_format_7(tmp_path / "crm", gitignore="# mine\n*.tmp")  # no final newline
    migrations.ensure_current(root)
    assert (root / ".gitignore").read_text() == f"# mine\n*.tmp\n{ROUTINES_STATE}\n"

    bare = at_format_7(tmp_path / "bare", gitignore=False)
    migrations.ensure_current(bare)
    assert (bare / ".gitignore").read_text() == f"{ROUTINES_STATE}\n"
    assert ".gitignore" in git(bare, "show", "--name-only", "--format=", "HEAD").splitlines()


# ------------------------------------------------------------ doctor, repair


def test_doctor_warns_when_the_skill_is_missing_and_migrate_puts_it_back(tmp_path, capsys):
    root = init_folder(tmp_path / "crm")
    assert checks(root, tmp_path)["agent skill"].status == "ok"
    (root / SKILL).unlink()
    commit_all(root, "removed")
    found = checks(root, tmp_path)["agent skill"]
    assert found.status == "warn" and SKILL in found.detail
    assert "hermitcrm migrate" in found.detail

    # Any other command leaves it gone: only `migrate` puts it back.
    assert cli.main(["--data", str(root), "check"]) == 0
    assert not (root / SKILL).exists()
    capsys.readouterr()
    assert cli.main(["--data", str(root), "migrate", "--dry-run"]) == 0
    assert SKILL in capsys.readouterr().out and not (root / SKILL).exists()

    assert cli.main(["--data", str(root), "migrate"]) == 0
    assert "put back the /hermit skill" in capsys.readouterr().out
    assert (root / SKILL).read_text() == AGENT_SKILL
    assert git(root, "log", "-1", "--format=%s") == "migrate: put back the /hermit skill"
    assert checks(root, tmp_path)["agent skill"].status == "ok"
    assert cli.main(["--data", str(root), "migrate"]) == 0
    assert capsys.readouterr().out.strip() == f"Data format {migrations.LATEST} is current."


def test_doctor_leaves_the_skill_to_a_pending_migration(tmp_path):
    root = at_format_7(tmp_path / "crm")
    found = checks(root, tmp_path)
    assert "agent skill" not in found and found["data format"].status == "warn"


def test_repair_in_a_folder_that_keeps_claude_out_of_git(tmp_path):
    root = init_folder(tmp_path / "crm")
    with (root / ".gitignore").open("a") as f:
        f.write(".claude/\n")
    git(root, "rm", "-rq", "--cached", ".claude")
    subprocess.run(["rm", "-rf", str(root / ".claude" / "skills")], check=True)
    commit_all(root, "a clone without .claude/skills")
    head = git(root, "rev-parse", "HEAD")
    assert migrations.repair(root).startswith("migrate: put back the /hermit skill")
    assert (root / SKILL).read_text() == AGENT_SKILL
    assert git(root, "rev-parse", "HEAD") == head  # ignored, so nothing to commit
    assert git(root, "status", "--porcelain") == ""
    assert migrations.repair(root) == ""
