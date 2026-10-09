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

"""`hermitcrm stages`: list, and rename / add / move / set / remove with a dry run."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from hermitcrm import cli
from hermitcrm import stages as st
from hermitcrm.datafolder import init_folder


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "demo", demo=True)


def run(root: Path, capsys, *argv) -> tuple[int, str, str]:
    code = cli.main(["stages", *argv], root=root)
    out = capsys.readouterr()
    return code, out.out, out.err


def head(root: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                          text=True, check=True).stdout.strip()


def log(root: Path, n: int = 6) -> list[str]:
    return subprocess.run(["git", "log", f"-{n}", "--format=%s"], cwd=root,
                          capture_output=True, text=True, check=True).stdout.splitlines()


def configured(root: Path) -> list[str]:
    return [s["name"] for s in tomllib.loads((root / "config.toml").read_text())["stages"]]


def test_listing_shows_roles_counts_and_the_entry_stage(demo, capsys):
    code, out, _ = run(demo, capsys)
    assert code == 0
    assert "prospect" in out and "temp-disqualified  parked" in out.replace("  ", "  ")
    assert "Entry stage: prospect; the first outbound touch moves it to engaged" in out
    assert run(demo, capsys, "list")[1] == out


def test_rename_dry_run_says_what_it_would_do_and_writes_nothing(demo, capsys):
    before = head(demo)
    code, out, _ = run(demo, capsys, "rename", "engaged", "contacted")
    assert code == 0
    # One company is in it now; others passed through it and have it in their history.
    assert ('Rename "engaged" to "contacted": 6 companies rewritten '
            '(1 in it now, the rest only in their stage_history)') in out
    assert "(was engaged)" in out and "1 company (was engaged)" in out
    assert "Dry run; add --apply" in out
    assert head(demo) == before and "stages" not in tomllib.loads(
        (demo / "config.toml").read_text())


def test_rename_apply_rewrites_companies_and_commits_with_the_ai_prefix(demo, capsys):
    code, out, _ = run(demo, capsys, "rename", "engaged", "contacted", "--apply")
    assert code == 0, out
    assert f"Undo: hermitcrm undo {head(demo)[:7]}" in out
    assert configured(demo)[:3] == ["prospect", "contacted", "discovery"]
    text = (demo / "companies" / "copperleaf-studio" / "company.md").read_text()
    assert "stage: contacted" in text and "engaged" not in text
    # One commit for the config line and every rewritten company, so one undo.
    assert log(demo, 1) == ['ai: adjust: stage "engaged" renamed to "contacted" (6 companies)']
    changed = set(subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=demo,
                                 capture_output=True, text=True, check=True).stdout.split())
    assert {"config.toml", "PIPELINE.md", "companies/copperleaf-studio/company.md"} <= changed
    store = cli.build_store(demo)
    assert cli.cmd_check(store)[1] == 1       # the demo dashboard still says engaged ...
    assert "monday-review.toml" in cli.cmd_check(store)[0]    # ... and check names it
    assert "monday-review.toml" in out        # as did the apply


def test_add_puts_an_open_stage_after_the_last_open_one(demo, capsys):
    code, out, _ = run(demo, capsys, "add", "qualified", "--apply")
    assert code == 0, out
    assert configured(demo) == ["prospect", "engaged", "discovery", "offer", "qualified",
                                "won", "lost", "disqualified", "temp-disqualified"]
    assert log(demo, 1) == ["ai: adjust: stages changed"]
    code, out, _ = run(demo, capsys, "add", "snoozed", "--role", "parked", "--after", "won",
                       "--apply")
    assert configured(demo)[5:7] == ["won", "snoozed"]


def test_add_a_valued_stage(demo, capsys):
    run(demo, capsys, "add", "proposal", "--valued", "--after", "discovery", "--apply")
    cfg = tomllib.loads((demo / "config.toml").read_text())["stages"]
    assert {"name": "proposal", "role": "open", "valued": True} in cfg
    assert "## proposal (0, 0 EUR/month)" in (demo / "PIPELINE.md").read_text()


def test_move_reorders_and_a_first_move_writes_the_implied_history_first(demo, capsys):
    code, out, _ = run(demo, capsys, "move", "offer", "--after", "prospect", "--apply")
    assert code == 0 and configured(demo)[:4] == ["prospect", "offer", "engaged", "discovery"]
    code, out, _ = run(demo, capsys, "add", "inbox", "--apply")
    assert configured(demo)[-1:] != ["inbox"]
    code, out, _ = run(demo, capsys, "move", "inbox", "--first")
    assert ("The entry stage changes from prospect to inbox; 1 company gets its start "
            "written into stage_history first.") in out
    code, out, _ = run(demo, capsys, "move", "inbox", "--first", "--apply")
    assert code == 0 and configured(demo)[0] == "inbox"
    assert log(demo, 1) == ["ai: adjust: stages changed"]
    assert cli.build_store(demo).companies["tallpine-software"].stage_history[0].to_stage == \
        "prospect"


def test_set_changes_a_role_but_not_to_lost_for_companies_without_a_reason(demo, capsys):
    code, out, err = run(demo, capsys, "set", "engaged", "--role", "lost", "--apply")
    assert code == 2 and "have no reason" in err
    assert "stages" not in tomllib.loads((demo / "config.toml").read_text())
    code, out, _ = run(demo, capsys, "set", "disqualified", "--role", "parked", "--apply")
    assert code == 0 and st.load(demo).role_of("disqualified") == "parked"


def test_remove_needs_a_move_to_when_companies_are_in_the_stage(demo, capsys):
    before = head(demo)
    code, out, err = run(demo, capsys, "remove", "temp-disqualified", "--apply")
    assert code == 2 and "--move-to STAGE" in err and "1 company is still in" in err
    assert head(demo) == before
    code, out, _ = run(demo, capsys, "remove", "temp-disqualified", "--move-to", "prospect")
    assert code == 0 and "1 company moves to prospect" in out and "Dry run" in out
    assert head(demo) == before
    code, out, _ = run(demo, capsys, "remove", "temp-disqualified", "--move-to", "prospect",
                       "--apply")
    assert code == 0, out
    assert "temp-disqualified" not in configured(demo)
    store = cli.build_store(demo)
    assert store.companies["glasshouse-health"].stage == "prospect"
    assert 'ai: adjust: stage "temp-disqualified" removed, 1 company moved to "prospect"' \
        in log(demo)


def test_moving_into_a_lost_stage_needs_a_reason_from_the_command_line(demo, capsys):
    code, _, err = run(demo, capsys, "remove", "engaged", "--move-to", "lost", "--apply")
    assert code == 2 and "--reason TEXT" in err
    code, out, _ = run(demo, capsys, "remove", "engaged", "--move-to", "lost", "--reason",
                       "retired", "--apply")
    assert code == 0, out
    assert cli.build_store(demo).companies["copperleaf-studio"].lost_reason == "retired"


@pytest.mark.parametrize("argv,needle", [
    (("rename", "nothing", "x"), "no stage called 'nothing'"),
    (("rename", "engaged", "prospect"), "Duplicate stage"),
    (("rename", "engaged", "yes"), "reserved"),
    (("add", "Bad Name!"), "a-z"),
    (("move", "offer", "--after", "nowhere"), "no stage called 'nowhere'"),
    (("remove", "nowhere"), "no stage called 'nowhere'"),
])
def test_refusals_say_what_is_wrong_and_change_nothing(demo, capsys, argv, needle):
    before = head(demo)
    code, out, err = run(demo, capsys, *argv, "--apply")
    assert code == 2 and needle in err, (out, err)
    assert head(demo) == before


def test_an_unchanged_request_is_not_an_error(demo, capsys):
    code, out, _ = run(demo, capsys, "set", "engaged", "--role", "open", "--apply")
    assert code == 0 and "Nothing to change" in out


def test_the_stages_command_appears_in_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["stages", "--help"])
    out = capsys.readouterr().out
    for action in ("rename", "add", "move", "set", "remove"):
        assert action in out
