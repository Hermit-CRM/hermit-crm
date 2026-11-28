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

"""`hermitcrm tasks list|add|done`: the to-do list on the command line, for the
skills pack, with the ids the MCP task tools use."""

import subprocess
from datetime import date, timedelta

import pytest

from hermitcrm import cli, mcp
from hermitcrm.datafolder import init_folder
from hermitcrm.store import Store


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def root(tmp_path, capsys):
    root = init_folder(tmp_path / "crm")
    run = lambda *a: cli.main(["--data", str(root), *a])  # noqa: E731
    assert run("add", "company", "Acme BV", "--country", "NL") == 0
    assert run("add", "contact", "acme", "Jane Roe", "--title", "CTO") == 0
    capsys.readouterr()
    return root


def tasks(root, capsys, *args):
    code = cli.main(["--data", str(root), "tasks", *args])
    out = capsys.readouterr()
    return code, out.out.strip(), out.err.strip()


def ids(text):
    return [line.rsplit("| id ", 1)[1] for line in text.splitlines() if "| id " in line]


def test_an_empty_list_says_so(root, capsys):
    assert tasks(root, capsys) == (0, "No open tasks.", "")
    assert tasks(root, capsys, "list", "--when", "overdue") == (0, "No overdue tasks.", "")
    assert tasks(root, capsys, "list", "--company", "acme")[1] == "No open tasks for acme."


def test_add_list_done_each_one_commit(root, capsys):
    soon = (date.today() + timedelta(days=2)).isoformat()
    head = git(root, "rev-parse", "HEAD")
    code, out, _ = tasks(root, capsys, "add", "acme", "Send  the\tpricing sheet", "--due",
                         soon, "--contact", "jane-roe")
    assert code == 0
    assert out.startswith(f"Added 'Send the pricing sheet' to acme/jane-roe, due {soon} "
                          "as acme/jane-roe/0/")
    sha = git(root, "rev-parse", "--short=7", "HEAD")
    assert out.endswith(f"Committed as {sha}. Undo: hermitcrm undo {sha}")
    assert git(root, "rev-list", "--count", f"{head}..HEAD") == "1"
    assert git(root, "status", "--porcelain") == ""

    code, out, _ = tasks(root, capsys, "add", "acme", "Book the demo")
    assert code == 0 and "due" not in out

    code, listed, _ = tasks(root, capsys, "list")
    assert code == 0
    lines = listed.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(f"- {soon} | Acme BV/jane-roe | Send the pricing sheet | id ")
    assert lines[1].startswith("- no date | Acme BV | Book the demo | id ")
    assert tasks(root, capsys, "list", "--when", "week")[1].count("\n") == 0  # one row

    first = ids(listed)[0]
    code, out, _ = tasks(root, capsys, "done", first)
    assert code == 0 and out.startswith("Done: 'Send the pricing sheet' (acme). Committed as")
    assert "Send the pricing sheet" not in tasks(root, capsys, "list")[1]
    assert "Send the pricing sheet" in tasks(root, capsys, "list", "--when", "done")[1]
    head = git(root, "rev-parse", "HEAD")
    assert tasks(root, capsys, "done", first) == (0, "That task is already done. Nothing "
                                                     "changed.", "")
    assert git(root, "rev-parse", "HEAD") == head


def test_a_next_step_is_a_task_too(root, capsys):
    assert cli.main(["--data", str(root), "add", "company", "Bluefin Analytics", "--next-step",
                     "Call back", "--next-step-due", date.today().isoformat()]) == 0
    capsys.readouterr()
    code, listed, _ = tasks(root, capsys, "list", "--when", "today")
    assert code == 0 and "Bluefin Analytics | Call back | id bluefin-analytics/-/next/" in listed
    assert tasks(root, capsys, "done", ids(listed)[0])[0] == 0
    assert "status: done" in (root / "companies/bluefin-analytics/company.md").read_text() or \
        "next_step_status: done" in (root / "companies/bluefin-analytics/company.md").read_text()


def test_the_ids_are_the_mcp_ids(root, capsys):
    tasks(root, capsys, "add", "acme", "Write the proposal")
    cli_ids = ids(tasks(root, capsys, "list")[1])
    store = Store(root)
    store.load()
    tool = {t.name: t for t in mcp.build_tools(root, store)}["list_tasks"]
    result = tool.handler({})
    text = result[0] if isinstance(result, tuple) else result
    assert ids(text) == cli_ids


@pytest.mark.parametrize("args, says", [
    (("add", "nobody", "x"), "unknown company: nobody"),
    (("add", "acme", "x", "--contact", "ghost"), "unknown contact 'ghost' at acme"),
    (("add", "acme", "x", "--due", "2026-13-40"), "could not add: due:"),
    (("add", "acme", "   "), "could not add: text:"),
    (("done", "acme"), "task must be an id as list_tasks gives it"),
    (("done", "acme/-/0/abcdef"), "run hermitcrm tasks list"),
    (("list", "--company", "nobody"), "unknown company: nobody"),
])
def test_a_refusal_writes_nothing_and_exits_2(root, capsys, args, says):
    head = git(root, "rev-parse", "HEAD")
    code, out, err = tasks(root, capsys, *args)
    assert code == 2 and out == "" and says in err
    assert git(root, "rev-parse", "HEAD") == head
    assert git(root, "status", "--porcelain") == ""
