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

"""The MCP server: JSON-RPC over stdio, and the tools bound to a data folder."""

import io
import json
import sys

import pytest

from hermitcrm import mcp

from conftest import FIXED_NOW


@pytest.fixture
def tools(store):
    store.create_company(name="Acme BV", country="NL", stage="discovery",
                         product_oneliner="Churn dashboards")
    store.create_contact("acme", first_name="Jane", last_name="Roe")
    return {t.name: t for t in mcp.build_tools(store.root, store)}


def call(tools, tool, **arguments):
    """One tools/call, returning (text, failed).

    The parameter is `tool`, not `name`, because `name` is an argument several
    of the tools themselves take.
    """
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": arguments}}
    payload = mcp.handle(message, tools)["result"]
    return payload["content"][0]["text"], bool(payload.get("isError"))


# ---------------------------------------------------------------- protocol


def test_initialize_states_the_protocol_and_the_server(tools):
    r = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"}}, tools)
    assert r["result"]["protocolVersion"] == mcp.PROTOCOL_VERSION
    assert r["result"]["serverInfo"]["name"] == "hermitcrm"
    assert "list_pipeline" in r["result"]["instructions"]


def test_a_notification_is_never_answered(tools):
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"},
                      tools) is None
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/cancelled",
                       "params": {"requestId": 1}}, tools) is None


def test_tools_list_describes_every_tool(tools):
    r = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, tools)
    specs = r["result"]["tools"]
    assert {s["name"] for s in specs} == set(tools)
    for spec in specs:
        assert spec["description"].strip()
        assert spec["inputSchema"]["type"] == "object"


def test_unknown_method_and_unknown_tool_are_protocol_errors(tools):
    r = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "wat"}, tools)
    assert r["error"]["code"] == mcp.METHOD_NOT_FOUND

    r = mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "nope", "arguments": {}}}, tools)
    assert r["error"]["code"] == mcp.INVALID_PARAMS


def test_ping_answers_empty(tools):
    assert mcp.handle({"jsonrpc": "2.0", "id": 5, "method": "ping"}, tools)["result"] == {}


def test_serve_reads_lines_and_survives_rubbish(store):
    lines = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
        "",
        "not json at all",
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ])
    out = io.StringIO()
    assert mcp.serve(store.root, store, stdin=io.StringIO(lines), stdout=out) == 0

    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, None, 2]
    assert replies[1]["error"]["code"] == mcp.PARSE_ERROR


# ------------------------------------------------------------------- reads


def test_pipeline_and_show_and_search(tools):
    text, failed = call(tools, "list_pipeline")
    assert not failed and "# Pipeline" in text and "acme" in text

    text, failed = call(tools, "show_company", slug="acme")
    assert not failed and "Acme BV" in text and "jane-roe" in text

    text, failed = call(tools, "search_companies", query="churn")
    assert not failed and "acme" in text

    text, failed = call(tools, "search_companies", query="nothing here")
    assert not failed and "No company matches" in text


def test_a_missing_required_argument_is_a_tool_error_not_a_crash(tools):
    text, failed = call(tools, "show_company")
    assert failed and "slug is required" in text

    text, failed = call(tools, "search_companies", query="  ")
    assert failed and "query is required" in text


def test_a_days_argument_that_is_not_a_number_says_so(tools):
    text, failed = call(tools, "digest", days="soon")
    assert failed and "days must be a whole number" in text


def test_followups_and_brief_answer_on_an_empty_folder(tools):
    text, failed = call(tools, "followups")
    assert not failed and "Nothing waiting" in text

    text, failed = call(tools, "brief")
    assert not failed and "No meetings with known companies" in text


# ------------------------------------------------------------------ writes


def test_add_company_writes_and_reports_the_slug(tools, store, messages):
    text, failed = call(tools, "add_company", name="Borduro", country="NL")
    assert not failed and "as borduro" in text
    assert (store.root / "companies" / "borduro" / "company.md").exists()


def test_add_interaction_reports_the_stage_move(tools):
    call(tools, "add_company", name="Borduro", country="NL")
    text, failed = call(tools, "add_interaction", company="borduro", channel="email",
                        direction="out", body="Hi there,\n\nWorth a chat?")
    assert not failed and "moved prospect -> engaged" in text


def test_a_rejected_value_is_reported_and_nothing_is_written(tools, store):
    text, failed = call(tools, "add_company", name="Nope", country="ZZZZ")
    assert failed and "could not write: country:" in text
    assert "nope" not in store.companies
    # the 249-code list is clipped rather than dumped into the model's context
    assert len(text) < 300


def test_writing_under_an_unknown_company_fails_cleanly(tools):
    text, failed = call(tools, "add_contact", company="ghost", name="Nobody")
    assert failed and "unknown company 'ghost'" in text

    text, failed = call(tools, "add_contact", company="", name="Nobody")
    assert failed and "company and name are required" in text


def test_an_absent_field_is_not_the_same_as_an_empty_one(tools, store):
    call(tools, "add_company", name="Borduro")
    # source was not sent, so the store's default stands
    assert store.get("borduro").source == "other"
    assert store.get("borduro").stage == "prospect"


def test_a_log_handler_aimed_at_stdout_is_detached(store):
    """Serving must take away anything that would write into the protocol stream."""
    import logging

    bad = logging.StreamHandler(sys.stdout)
    logging.getLogger("crm").addHandler(bad)
    try:
        mcp.serve(store.root, store, stdin=io.StringIO(""), stdout=io.StringIO())
        assert bad not in logging.getLogger("crm").handlers
    finally:
        logging.getLogger("crm").removeHandler(bad)


def test_nothing_but_protocol_messages_reach_stdout(store, capsys, monkeypatch):
    """A stray line on stdout desynchronises the client for the rest of the session."""
    import logging

    lines = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    out = io.StringIO()
    mcp.serve(store.root, store, stdin=io.StringIO(lines), stdout=out)
    logging.getLogger("crm.test").warning("a warning that must not corrupt the stream")

    assert capsys.readouterr().out == ""
    assert [json.loads(line) for line in out.getvalue().splitlines()] == [
        {"jsonrpc": "2.0", "id": 1, "result": {}}]


def test_add_company_takes_a_next_step_type_from_settings(tools, store):
    store.task_types = ["prospecting"]
    text, failed = call(tools, "add_company", name="Borduro", next_step="call",
                        next_step_type="prospecting")
    assert not failed and store.companies["borduro"].next_step_type == "prospecting"
    text, failed = call(tools, "add_company", name="Nope", next_step_type="other")
    assert failed and "unknown task type" in text and "nope" not in store.companies
