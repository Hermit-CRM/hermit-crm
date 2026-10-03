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

"""The MCP write tools of Make it yours: adjust_help, adjust_read, adjust_write,
adjust_config, bulk_preview, bulk_apply and undo. The rules an agent with a shell
reads in `hermitcrm help adjust` are enforced here, so every refusal is tested
for leaving the folder exactly as it was."""

import re
import subprocess

import pytest

from hermitcrm import adjust, cli, history, mcp
from hermitcrm import help as helptext
from hermitcrm.datafolder import init_folder
from hermitcrm.setup import set_config_values
from hermitcrm.store import load_config

FIELD = """[[field]]
key = "renewal"
label = "renewal"
type = "date"
applies_to = "company"
show_in = ["detail", "companies"]
"""

DASHBOARD = """title = "Monday review"
pin = true

[[widget]]
type = "list"
scope = "companies"
filters = { stage = "prospect" }
columns = ["name", "country"]
"""

NEW_TOOLS = ["adjust_help", "adjust_read", "adjust_write", "adjust_config", "bulk_preview",
             "bulk_apply", "undo"]


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def folder(tmp_path):
    root = init_folder(tmp_path / "crm")
    set_config_values(root / "config.toml", {"push_enabled": False})  # no remote here
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam", "nopush")
    return root


@pytest.fixture
def tools(folder):
    store = cli.build_store(folder)
    found = {t.name: t for t in mcp.build_tools(folder, store)}
    for name, country in (("Acme", "NL"), ("Borduro", "DE"), ("Cygne", "NL")):
        call(found, "add_company", name=name, country=country)
    return found


def call(tools, tool, **arguments):
    """One tools/call: (text, failed)."""
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": arguments}}
    payload = mcp.handle(message, tools)["result"]
    return payload["content"][0]["text"], bool(payload.get("isError"))


def head(root):
    return git(root, "rev-parse", "HEAD")


def touched(root, rev="HEAD"):
    return git(root, "show", "--name-only", "--format=", rev).splitlines()


def undo_id(text):
    return re.search(r"Undo: undo\(([0-9a-f]{7})\)", text).group(1)


# ---------------------------------------------------------------- the list


def test_the_tool_list_has_the_make_it_yours_tools(tools):
    assert len(tools) == 17
    assert set(NEW_TOOLS) <= set(tools)
    rules = {"adjust_write": ["checked", "nothing is written", "paused", "ONE", "undo"],
             "bulk_preview": ["Writes nothing", "ALWAYS show it to the user", "preview_id"],
             "bulk_apply": ["preview_id", "Refused", "ONE commit"],
             "adjust_config": ["task_types", "ONE commit", "Settings"],
             "undo": ["new commit"]}
    for name, words in rules.items():
        for word in words:
            assert word in tools[name].description, (name, word)


def test_the_allowlist_is_the_extension_files():
    assert mcp.WRITABLE == history.EXTENSION_FILES
    assert set(mcp.RECIPES) == {t for t in helptext.topics() if t.startswith("adjust")}


def test_the_help_page_lists_every_tool(tools):
    page = helptext.read("ai-agents")
    for name in tools:
        assert f"| `{name}` |" in page, name


def test_initialize_points_at_adjust_help(tools):
    r = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, tools)
    assert "adjust_help" in r["result"]["instructions"]


# ------------------------------------------------------------- help, read


def test_adjust_help_returns_a_recipe(tools):
    text, failed = call(tools, "adjust_help")
    assert not failed and "# Make it yours" in text and "adjust_write" in text
    text, failed = call(tools, "adjust_help", topic="adjust-dashboards")
    assert not failed and "dashboards/<name>.toml" in text
    text, failed = call(tools, "adjust_help", topic="adjust-fieldz")
    assert failed and "did you mean adjust-fields?" in text
    text, failed = call(tools, "adjust_help", topic="backups")
    assert failed and "unknown topic" in text


def test_adjust_read(tools, folder):
    text, failed = call(tools, "adjust_read", path="layout.toml")
    assert not failed and text == ""  # absent
    (folder / "theme.css").write_text(":root { --accent: red; }\n")
    assert call(tools, "adjust_read", path="theme.css") == (":root { --accent: red; }\n", False)
    text, failed = call(tools, "adjust_read")
    assert not failed and "theme.css" in text and "MESSAGING.md" in text
    text, failed = call(tools, "adjust_read", path="config.toml")
    assert not failed and "silent_days = 14" in text and "outcomes = [" in text
    assert "owner_email" not in text and "push_enabled" not in text  # only its three keys


@pytest.mark.parametrize("path", ["../outside.toml", "/etc/passwd", "~/.ssh/config",
                                  "dashboards/../config.toml", "C:\\x.toml", "..\\x.toml"])
def test_paths_outside_the_folder_are_refused(tools, path):
    for tool in ("adjust_read", "adjust_write"):
        text, failed = call(tools, tool, path=path, content="x", summary="x")
        assert failed and "not a path inside the data folder" in text, (tool, path)


@pytest.mark.parametrize("path", ["PIPELINE.md", ".secrets.toml", ".hermitcrm-format",
                                  "CLAUDE.md", ".claude/settings.json",
                                  "companies/acme/company.md", "dashboards/Monday.toml",
                                  "dashboards/sub/x.toml", "field.toml"])
def test_files_off_the_allowlist_are_refused(tools, folder, path):
    before = head(folder)
    text, failed = call(tools, "adjust_write", path=path, content="x = 1\n", summary="x")
    assert failed and text.startswith("Refused"), path
    assert head(folder) == before
    if path == "field.toml":
        assert "did you mean fields.toml?" in text


def test_config_toml_goes_through_adjust_config(tools):
    text, failed = call(tools, "adjust_write", path="config.toml", content="", summary="x")
    assert failed and "adjust_config" in text


# ------------------------------------------------------------------ write


def test_adjust_write_checks_then_makes_one_commit_of_that_file(tools, folder):
    (folder / "scratch.txt").write_text("the user's own unfinished file\n")
    text, failed = call(tools, "adjust_write", path="fields.toml", content=FIELD,
                        summary="contract renewal field")
    assert not failed, text
    sha = undo_id(text)
    assert sha in text and "ai: adjust: contract renewal field" in text
    assert git(folder, "log", "-1", "--format=%h %s") == f"{sha} ai: adjust: contract renewal field"
    assert touched(folder) == ["fields.toml"]
    assert (folder / "fields.toml").read_text() == FIELD
    assert git(folder, "status", "--porcelain") == "?? scratch.txt"  # left alone
    assert cli.cmd_check(cli.build_store(folder))[1] == 0
    # Writing the same text again is no change and no commit.
    text, failed = call(tools, "adjust_write", path="fields.toml", content=FIELD, summary="x")
    assert not failed and text.startswith("No change") and git(folder, "log", "-1",
                                                                "--format=%h") == sha


def test_a_new_dashboard_in_a_new_folder(tools, folder):
    text, failed = call(tools, "adjust_write", path="dashboards/monday-review.toml",
                        content=DASHBOARD, summary="Monday review dashboard")
    assert not failed, text
    assert touched(folder) == ["dashboards/monday-review.toml"]
    assert adjust.all_problems(folder) == []


@pytest.mark.parametrize("path,content,problem", [
    ("fields.toml", FIELD.replace('"date"', '"dat"'), "fields.toml: renewal: type"),
    ("fields.toml", "[[field]\n", "fields.toml: line 1"),
    ("dashboards/monday.toml", DASHBOARD.replace('"country"', '"countri"'),
     "did you mean country?"),
    ("routines.toml", '[[routine]]\nname = "x"\naction = "brif"\n', "did you mean brief?"),
    ("theme.css", ":root { --acent: red; }\n", "did you mean --accent?"),
    ("layout.toml", '[company]\nsections = ["timelin"]\n', "layout.toml"),
    ("messages.toml", '[languages.en]\nscale = "Hi {frist}"\n', "messages.toml"),
])
def test_invalid_content_leaves_the_file_and_makes_no_commit(tools, folder, path, content,
                                                             problem):
    (folder / "fields.toml").write_text(FIELD)
    git(folder, "add", "fields.toml")
    git(folder, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "f")
    target = folder / path
    before_bytes = target.read_bytes() if target.exists() else None
    before = head(folder)
    text, failed = call(tools, "adjust_write", path=path, content=content, summary="broken")
    assert failed and "Not written" in text and problem in text, text
    assert (target.read_bytes() if target.exists() else None) == before_bytes
    assert head(folder) == before and git(folder, "status", "--porcelain") == ""


def test_a_change_that_breaks_another_file_is_refused(tools, folder):
    call(tools, "adjust_write", path="fields.toml", content=FIELD, summary="renewal")
    dash = DASHBOARD.replace('"country"', '"renewal"')
    text, failed = call(tools, "adjust_write", path="dashboards/monday.toml", content=dash,
                        summary="dashboard")
    assert not failed, text
    before = head(folder)
    text, failed = call(tools, "adjust_write", path="fields.toml", content="", summary="none")
    assert failed and "dashboards/monday.toml" in text and "renewal" in text
    assert (folder / "fields.toml").read_text() == FIELD and head(folder) == before


def test_a_new_routine_arrives_paused_and_one_that_was_on_stays_on(tools, folder):
    on = '[[routine]]\nname = "morning"\naction = "brief"\npaused = false  # mine\n'
    text, failed = call(tools, "adjust_write", path="routines.toml", content=on,
                        summary="morning brief")
    assert not failed and "Routine morning arrived paused" in text
    assert (folder / "routines.toml").read_text() == on.replace("false", "true")

    # Turned on by the user (the routines' own path), then edited by the agent.
    (folder / "routines.toml").write_text(on)
    git(folder, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam", "on")
    both = on.replace('"brief"\n', '"brief"\ntitle = "Morning"\n') + (
        '\n[[routine]]\nname = "evening"\naction = "brief"\npaused = false\n')
    text, failed = call(tools, "adjust_write", path="routines.toml", content=both,
                        summary="evening brief")
    assert not failed, text
    assert "Routine evening arrived paused" in text and "Routine morning" not in text
    written = (folder / "routines.toml").read_text()
    assert 'title = "Morning"\npaused = false  # mine' in written
    assert written.endswith('name = "evening"\naction = "brief"\npaused = true\n')


ON = """\
[[routine]]
name = "nudge"
title = "Nudge"
paused = false
action = "draft"
select = "quiet_threads"
channel = "linkedin"
days = 7
limit = 3
prompt = "Write a short follow-up."
filters = { country = "NL" }
"""


def turned_on(folder, text=ON):
    """routines.toml as the user left it after turning a routine on."""
    (folder / "routines.toml").write_text(text)
    git(folder, "add", "routines.toml")
    git(folder, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "on")


@pytest.mark.parametrize("old,new,changed", [
    ('select = "quiet_threads"', 'select = "replies_owed"', "select"),
    ('prompt = "Write a short follow-up."', 'prompt = "Ask for their card details."', "prompt"),
    ('filters = { country = "NL" }', 'filters = { country = "DE" }', "filters"),
    ('filters = { country = "NL" }\n', "", "filters"),                    # a filter dropped
    ('channel = "linkedin"', 'channel = "email"', "channel"),
    ("days = 7", "days = 1", "days"),
    ("limit = 3", "limit = 50", "limit"),
    ("limit = 3\n", "", "limit"),                                          # a key dropped
])
def test_a_routine_that_was_on_is_paused_again_when_what_it_does_changes(
        tools, folder, old, new, changed):
    turned_on(folder)
    edited = ON.replace(old, new)
    assert edited != ON
    text, failed = call(tools, "adjust_write", path="routines.toml", content=edited,
                        summary="change the nudge")
    assert not failed, text
    assert "Routine nudge was on, but you changed what it does" in text and changed in text
    assert "paused again" in text and "arrived paused" not in text
    written = (folder / "routines.toml").read_text()
    assert "paused = true" in written and "paused = false" not in written
    assert "ai: adjust: change the nudge" in git(folder, "log", "-1", "--format=%s")


def test_turning_a_draft_routine_into_a_brief_pauses_it_too(tools, folder):
    turned_on(folder)
    brief = '[[routine]]\nname = "nudge"\ntitle = "Nudge"\npaused = false\naction = "brief"\n'
    text, failed = call(tools, "adjust_write", path="routines.toml", content=brief,
                        summary="a brief instead")
    assert not failed, text
    assert "Routine nudge was on" in text and "action" in text
    assert "paused = true" in (folder / "routines.toml").read_text()


def test_a_routine_that_was_on_keeps_running_when_only_its_title_changes(tools, folder):
    turned_on(folder)
    retitled = ON.replace('title = "Nudge"', 'title = "Nudge quiet threads"')
    text, failed = call(tools, "adjust_write", path="routines.toml", content=retitled,
                        summary="rename")
    assert not failed and "paused" not in text.split("Undo")[0]
    assert "paused = false" in (folder / "routines.toml").read_text()
    # and another routine added next to it arrives paused, the first stays on
    both = retitled + retitled.replace("nudge", "second").replace("Nudge quiet threads", "Two")
    text, failed = call(tools, "adjust_write", path="routines.toml", content=both,
                        summary="a second one")
    assert not failed and "Routine second arrived paused" in text and "Routine nudge" not in text
    written = (folder / "routines.toml").read_text()
    assert written.count("paused = false") == 1 and written.count("paused = true") == 1


def test_a_file_with_uncommitted_changes_is_not_overwritten(tools, folder):
    (folder / "theme.css").write_text("/* the user is editing this */\n")
    before = head(folder)
    text, failed = call(tools, "adjust_write", path="theme.css", content=":root {}\n",
                        summary="look")
    assert failed and "not committed yet" in text
    assert (folder / "theme.css").read_text() == "/* the user is editing this */\n"
    assert head(folder) == before


def test_a_link_out_of_the_folder_is_not_written_through(tools, folder, tmp_path):
    outside = tmp_path / "outside.css"
    outside.write_text("x\n")
    (folder / "theme.css").symlink_to(outside)
    git(folder, "add", "theme.css")
    git(folder, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "ln")
    text, failed = call(tools, "adjust_write", path="theme.css", content=":root {}\n",
                        summary="look")
    assert failed and "link" in text and outside.read_text() == "x\n"


def test_adjust_write_needs_content_and_a_summary(tools):
    text, failed = call(tools, "adjust_write", path="theme.css", summary="x")
    assert failed and "content is required" in text
    text, failed = call(tools, "adjust_write", path="theme.css", content=":root {}\n",
                        summary="  ")
    assert failed and "summary is required" in text


def test_undo_takes_an_adjust_write_back(tools, folder):
    text, _ = call(tools, "adjust_write", path="theme.css", content=":root {}\n",
                   summary="my look")
    text, failed = call(tools, "undo", sha=undo_id(text))
    assert not failed and 'Revert "ai: adjust: my look"' in text
    assert not (folder / "theme.css").exists()
    back = re.search(r"undo\(([0-9a-f]{7})\)", text).group(1)
    text, failed = call(tools, "undo", sha=back)
    assert not failed and (folder / "theme.css").exists()


def test_undo_refuses_what_hermitcrm_undo_refuses(tools, folder):
    text, failed = call(tools, "undo", sha="not-a-sha")
    assert failed and "is not a commit id" in text
    text, failed = call(tools, "undo", sha="abcdef1")
    assert failed and "no commit abcdef1" in text
    first = git(folder, "rev-list", "--max-parents=0", "HEAD")
    text, failed = call(tools, "undo", sha=first[:7])
    assert failed and "first commit" in text


# ----------------------------------------------------------------- config


def test_adjust_config_saves_one_key_in_one_commit(tools, folder):
    text, failed = call(tools, "adjust_config", key="silent_days", value=21)
    assert not failed, text
    assert load_config(folder)["silent_days"] == 21
    assert git(folder, "log", "-1", "--format=%s").startswith("ai: adjust: silent_days")
    assert touched(folder) == ["config.toml"]
    assert "message_window_days = " not in (folder / "config.toml").read_text().replace(
        "# message_window_days = ", "")  # the other keys are left as they were
    assert call(tools, "adjust_config", key="silent_days", value="21")[0].startswith(
        "No change")
    text, failed = call(tools, "undo", sha=undo_id(text))
    assert not failed and load_config(folder)["silent_days"] == 14


@pytest.mark.parametrize("key,value,problem", [
    ("silent_days", 0, "Silent after"), ("silent_days", "soon", "Silent after"),
    ("outcomes", ["yes", "Yes"], "Duplicate outcome"), ("outcomes", "yes", "a list"),
    ("outcomes", [], "at least one"),
    ("task_types", [{"name": "call", "colour": "pink"}], "not one of"),
    ("task_types", "call", "must be a list"), ("task_types", [{"colour": "red"}], "needs a name"),
    ("theme", "dark", "key must be one of"), ("owner_email", "x@example.com", "Settings"),
])
def test_adjust_config_refuses_bad_values_and_changes_nothing(tools, folder, key, value,
                                                              problem):
    config = (folder / "config.toml").read_bytes()
    before = head(folder)
    text, failed = call(tools, "adjust_config", key=key, value=value)
    assert failed and problem in text, text
    assert (folder / "config.toml").read_bytes() == config and head(folder) == before


def test_adjust_config_leaves_a_hand_edited_config_alone(tools, folder):
    mine = (folder / "config.toml").read_text() + "\nowner_name = \"Jane Roe\"\n"
    (folder / "config.toml").write_text(mine)
    before = head(folder)
    text, failed = call(tools, "adjust_config", key="silent_days", value=21)
    assert failed and "config.toml has changes that are not committed yet" in text
    assert "(the user may be editing it)" in text
    assert (folder / "config.toml").read_text() == mine and head(folder) == before
    # once the user has saved it, the same call goes through, in a commit of its own
    git(folder, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam", "mine")
    text, failed = call(tools, "adjust_config", key="silent_days", value=21)
    assert not failed, text
    assert load_config(folder)["silent_days"] == 21 and touched(folder) == ["config.toml"]


def test_adjust_config_outcomes_and_task_types(tools, folder):
    text, failed = call(tools, "adjust_config", key="outcomes", value=["replied", "no reply"])
    assert not failed and load_config(folder)["outcomes"] == ["replied", "no reply"]
    call(tools, "adjust_config", key="task_types",
         value=[{"name": "call", "colour": "blue"}, "email"])
    assert load_config(folder)["task_types"] == [{"name": "call", "colour": "blue"},
                                                 {"name": "email", "colour": "grey"}]
    # A type named again without a colour keeps the one it has.
    call(tools, "adjust_config", key="task_types", value=["email", "call"])
    assert load_config(folder)["task_types"] == [{"name": "email", "colour": "grey"},
                                                 {"name": "call", "colour": "blue"}]
    assert git(folder, "status", "--porcelain") == ""


# ------------------------------------------------------------------- bulk

NL_PRIORITY = {"scope": "companies", "where": ["country=NL"], "ops": {"add_tags": ["priority"]}}


def preview_id(text):
    return re.search(r"preview_id '([0-9a-f]+)'", text).group(1)


def test_bulk_preview_then_apply_in_one_commit_then_undo(tools, folder):
    before = head(folder)
    text, failed = call(tools, "bulk_preview", **NL_PRIORITY)
    assert not failed and "2 companies match. 2 would change." in text
    assert "acme: tags: (empty) -> priority" in text and "Show this to the user" in text
    assert head(folder) == before  # a preview writes nothing
    text, failed = call(tools, "bulk_apply", preview_id=preview_id(text), **NL_PRIORITY)
    assert not failed, text
    assert "2 companies changed in one commit" in text and "bulk: add tag priority" in text
    assert git(folder, "rev-list", "--count", f"{before}..HEAD") == "1"
    files = set(touched(folder))
    assert {"companies/acme/company.md", "companies/cygne/company.md"} <= files
    assert files <= {"companies/acme/company.md", "companies/cygne/company.md", "PIPELINE.md"}
    text, failed = call(tools, "undo", sha=undo_id(text))
    assert not failed and "priority" not in (folder / "companies/acme/company.md").read_text()


def test_bulk_apply_needs_a_fresh_preview_of_the_same_arguments(tools, folder):
    text, _ = call(tools, "bulk_preview", **NL_PRIORITY)
    pid = preview_id(text)
    before = head(folder)
    for args in ({**NL_PRIORITY, "where": ["country=DE"]},
                 {**NL_PRIORITY, "ops": {"add_tags": ["other"]}},
                 {**NL_PRIORITY, "scope": "contacts"}):
        text, failed = call(tools, "bulk_apply", preview_id=pid, **args)
        assert failed and "Refused, nothing changed" in text
    text, failed = call(tools, "bulk_apply", **NL_PRIORITY)
    assert failed and "preview_id is required" in text
    # Anything committed after the preview makes it stale.
    call(tools, "add_company", name="Dune BV", country="NL")
    text, failed = call(tools, "bulk_apply", preview_id=pid, **NL_PRIORITY)
    assert failed and "Call bulk_preview again" in text
    assert git(folder, "rev-list", "--count", f"{before}..HEAD") == "1"  # only the add


def test_bulk_refusals_speak_in_the_tools_own_words(tools, folder):
    text, failed = call(tools, "bulk_preview", scope="companies", ops={"add_tags": ["x"]})
    assert failed and "all=true" in text and "--" not in text
    text, failed = call(tools, "bulk_preview", scope="companies", where=["country=NL"],
                        ops={})
    assert failed and "ops.set" in text and "--set" not in text
    text, failed = call(tools, "bulk_preview", scope="interactions", where=["channel=email"],
                        ops={"set": {"body": "x"}})
    assert failed and "never rewritten" in text
    text, failed = call(tools, "bulk_preview", scope="companies", where=["country=NL"],
                        ops={"tags": ["x"]})
    assert failed and "unknown op 'tags'" in text
    text, failed = call(tools, "bulk_preview", scope="companies", where=["country=SE"],
                        ops={"add_tags": ["x"]})
    assert not failed and text.startswith("No companies match")
    assert "preview_id" not in text
