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

"""The MCP server's use of the protocol itself: tool titles and annotations,
structured results, paging with an opaque cursor, and the safety line that no
tool can mark a draft ready, schedule or send it."""

import pytest

from hermitcrm import mcp

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

# The tools that only read. Every other tool writes, and a new tool has to be
# put on one side or the other here on purpose.
READ_ONLY = {"list_pipeline", "show_company", "company_folder", "search_companies",
             "digest", "report", "followups", "keep_in_touch", "brief", "adjust_help",
             "adjust_read", "bulk_preview", "search", "show_contact", "list_tasks",
             "list_outreach", "show_outreach", "list_routines"}


@pytest.fixture
def tools(store):
    return {t.name: t for t in mcp.build_tools(store.root, store)}


def listed(tools, **params):
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    if params:
        message["params"] = params
    return mcp.handle(message, tools)["result"]


# ------------------------------------------------------------- annotations


def test_every_tool_has_a_title_and_all_four_hints(tools):
    for spec in listed(tools)["tools"]:
        assert spec["title"].strip(), spec["name"]
        annotations = spec["annotations"]
        assert set(annotations) == set(HINTS), spec["name"]
        assert all(isinstance(annotations[h], bool) for h in HINTS), spec["name"]
        # Nothing here talks to the outside world: one data folder, that is all.
        assert annotations["openWorldHint"] is False, spec["name"]


def test_read_tools_say_so_and_write_tools_do_not(tools):
    for spec in listed(tools)["tools"]:
        hints = spec["annotations"]
        if spec["name"] in READ_ONLY:
            assert hints["readOnlyHint"] is True, spec["name"]
            assert hints["destructiveHint"] is False, spec["name"]
        else:
            assert hints["readOnlyHint"] is False, spec["name"]


def test_the_add_tools_only_add_and_undo_is_destructive(tools):
    for name in ("add_company", "add_contact", "add_interaction"):
        hints = tools[name].annotations
        assert (hints["destructiveHint"], hints["idempotentHint"]) == (False, False)
    assert tools["undo"].annotations["destructiveHint"] is True
    assert tools["adjust_write"].annotations["destructiveHint"] is True


def test_a_tool_spec_uses_the_protocols_field_names(tools):
    spec = tools["show_company"].spec()
    assert list(spec) == ["name", "title", "description", "inputSchema", "annotations"]
    bare = mcp.Tool("bare", "A tool with nothing extra.", mcp.schema({}), lambda a: "ok")
    assert bare.spec() == {"name": "bare", "description": "A tool with nothing extra.",
                           "inputSchema": mcp.schema({})}


# ------------------------------------------------------- structured results


def structured_tool():
    out = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    return mcp.Tool("count", "Counts.", mcp.schema({}), lambda a: ("one thing", {"n": 1}),
                    title="Count", annotations=mcp.READS, output_schema=out)


def call(tools, name, **arguments):
    message = {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
               "params": {"name": name, "arguments": arguments}}
    return mcp.handle(message, tools)["result"]


def test_a_text_and_data_answer_becomes_structured_content():
    tool = structured_tool()
    payload = call({"count": tool}, "count")
    assert payload == {"content": [{"type": "text", "text": "one thing"}],
                       "structuredContent": {"n": 1}}
    assert tool.spec()["outputSchema"]["type"] == "object"


def test_a_plain_text_answer_has_no_structured_content(tools):
    payload = call(tools, "list_pipeline")
    assert "structuredContent" not in payload and not payload.get("isError")


def test_a_failing_structured_tool_is_an_error_without_data():
    def boom(args):
        raise mcp.ToolError("slug is required")

    tool = mcp.Tool("boom", "Fails.", mcp.schema({}), boom,
                    output_schema={"type": "object"})
    payload = call({"boom": tool}, "boom")
    assert payload["isError"] is True and "structuredContent" not in payload


def test_tools_list_takes_a_cursor_and_returns_every_tool_in_one_page(tools):
    result = listed(tools, cursor="anything")
    assert {t["name"] for t in result["tools"]} == set(tools)
    assert "nextCursor" not in result


# ------------------------------------------------------------------ paging


ROWS = list(range(45))


def test_a_page_and_its_cursor_walk_the_whole_list():
    seen, args = [], {"when": "all"}
    while True:
        rows, cursor = mcp.page(ROWS, args, "list_x")
        seen += rows
        if cursor is None:
            break
        args = {"when": "all", "cursor": cursor}
    assert seen == ROWS
    assert len(mcp.page(ROWS, {}, "list_x")[0]) == mcp.PAGE


def test_limit_sets_the_page_size_and_is_checked():
    rows, cursor = mcp.page(ROWS, {"limit": 40}, "list_x")
    assert rows == ROWS[:40] and cursor
    rows, cursor = mcp.page(ROWS, {"limit": 40, "cursor": cursor}, "list_x")
    assert rows == ROWS[40:] and cursor is None
    for bad in (0, mcp.MOST + 1, "lots"):
        with pytest.raises(mcp.ToolError, match="limit must"):
            mcp.page(ROWS, {"limit": bad}, "list_x")


def test_a_cursor_only_fits_the_query_it_came_from():
    _, cursor = mcp.page(ROWS, {"when": "today"}, "list_x")
    with pytest.raises(mcp.ToolError, match="cursor is not one"):
        mcp.page(ROWS, {"when": "week", "cursor": cursor}, "list_x")
    with pytest.raises(mcp.ToolError, match="cursor is not one"):
        mcp.page(ROWS, {"when": "today", "cursor": cursor}, "list_y")
    for rubbish in ("not a cursor", "e30", 12):
        with pytest.raises(mcp.ToolError, match="cursor is not one"):
            mcp.page(ROWS, {"cursor": rubbish}, "list_x")


def test_a_changed_limit_keeps_the_cursor_valid():
    _, cursor = mcp.page(ROWS, {"limit": 10}, "list_x")
    rows, _ = mcp.page(ROWS, {"limit": 5, "cursor": cursor}, "list_x")
    assert rows == ROWS[10:15]


def test_the_more_line_names_the_cursor_only_when_there_is_more():
    assert mcp.more(None, 20, 20) == ""
    assert "cursor 'abc'" in mcp.more("abc", 20, 45)


# ----------------------------------------------------------- the safety line


def test_no_tool_can_send_schedule_or_mark_ready(tools):
    """Approving, scheduling and sending a message are a person's acts in the
    web app. An agent over MCP may read, edit and skip a draft, nothing more."""
    for name in tools:
        for word in ("send", "ready", "schedule"):
            assert word not in name, name
