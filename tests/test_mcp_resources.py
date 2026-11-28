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

"""MCP resources (the pipeline, the playbook, one company by slug) and prompts
(morning_review, prep_meeting, log_call, weekly_review), with the field names
and error codes of the protocol revision the server speaks."""

import io
import json

import pytest

from hermitcrm import mcp

PROMPTS = ("morning_review", "prep_meeting", "log_call", "weekly_review")


@pytest.fixture
def server(store):
    store.create_company(name="Acme BV", country="NL", stage="discovery")
    store.create_contact("acme", first_name="Jane", last_name="Roe")
    tools = {t.name: t for t in mcp.build_tools(store.root, store)}
    return tools, mcp.build_catalog(store.root, store)


def ask(server, method, **params):
    tools, catalog = server
    message = {"jsonrpc": "2.0", "id": 9, "method": method}
    if params:
        message["params"] = params
    return mcp.handle(message, tools, catalog)


def test_initialize_advertises_tools_resources_and_prompts(server):
    r = ask(server, "initialize", protocolVersion=mcp.PROTOCOL_VERSION)["result"]
    assert r["capabilities"] == {"tools": {"listChanged": False},
                                 "resources": {"subscribe": False, "listChanged": False},
                                 "prompts": {"listChanged": False}}
    words = r["instructions"]
    for name in ("list_pipeline", "search", "list_tasks", "move_stage", "morning_review"):
        assert name in words, name
    assert "send" in words   # it says what it will not do


# --------------------------------------------------------------- resources


def test_resources_list_names_the_pipeline_and_the_playbook(server):
    r = ask(server, "resources/list")["result"]
    assert [x["uri"] for x in r["resources"]] == ["hermitcrm://pipeline",
                                                  "hermitcrm://playbook"]
    for x in r["resources"]:
        assert set(x) == {"uri", "name", "title", "description", "mimeType"}
        assert x["mimeType"] == "text/markdown"
    assert "nextCursor" not in r


def test_the_company_template(server):
    r = ask(server, "resources/templates/list")["result"]
    [template] = r["resourceTemplates"]
    assert template["uriTemplate"] == "hermitcrm://companies/{slug}"
    assert set(template) == {"uriTemplate", "name", "title", "description", "mimeType"}


def test_reading_the_pipeline(server):
    r = ask(server, "resources/read", uri="hermitcrm://pipeline")["result"]
    [content] = r["contents"]
    assert content["uri"] == "hermitcrm://pipeline"
    assert content["mimeType"] == "text/markdown"
    assert "# Pipeline" in content["text"] and "acme" in content["text"]


def test_reading_the_playbook(server, store):
    r = ask(server, "resources/read", uri="hermitcrm://playbook")["result"]
    assert "No MESSAGING.md" in r["contents"][0]["text"]
    (store.root / "MESSAGING.md").write_text("# Messaging\n\nBe brief.\n", encoding="utf-8")
    r = ask(server, "resources/read", uri="hermitcrm://playbook")["result"]
    assert r["contents"][0]["text"] == "# Messaging\n\nBe brief.\n"


def test_reading_one_company_by_slug(server):
    r = ask(server, "resources/read", uri="hermitcrm://companies/acme")["result"]
    [content] = r["contents"]
    assert content["uri"] == "hermitcrm://companies/acme"
    assert "Acme BV" in content["text"] and "jane-roe" in content["text"]


def test_an_unknown_resource_is_the_protocols_not_found(server):
    for uri in ("hermitcrm://companies/ghost", "hermitcrm://nothing",
                "file:///etc/passwd", "hermitcrm://companies/../config"):
        r = ask(server, "resources/read", uri=uri)
        assert r["error"]["code"] == mcp.RESOURCE_NOT_FOUND == -32002, uri
        assert r["error"]["data"] == {"uri": uri}
    r = ask(server, "resources/read")
    assert r["error"]["code"] == mcp.INVALID_PARAMS


# ----------------------------------------------------------------- prompts


def test_prompts_list(server):
    r = ask(server, "prompts/list")["result"]
    assert [p["name"] for p in r["prompts"]] == list(PROMPTS)
    by_name = {p["name"]: p for p in r["prompts"]}
    assert by_name["morning_review"]["arguments"] == []
    assert by_name["prep_meeting"]["arguments"][0] == {
        "name": "company", "description": by_name["prep_meeting"]["arguments"][0]
        ["description"], "required": True}
    assert [a["name"] for a in by_name["log_call"]["arguments"]] == ["notes", "company"]
    for p in r["prompts"]:
        assert p["title"] and p["description"]


def text_of(r):
    [message] = r["result"]["messages"]
    assert message["role"] == "user" and message["content"]["type"] == "text"
    return message["content"]["text"]


def test_every_prompt_names_only_tools_that_exist(server):
    tools, _ = server
    args = {"prep_meeting": {"company": "acme"}, "log_call": {"notes": "Spoke to Jane."}}
    import re
    for name in PROMPTS:
        r = ask(server, "prompts/get", name=name, arguments=args.get(name, {}))
        text = text_of(r)
        assert r["result"]["description"]
        named = set(re.findall(r"`([a-z_]+)`", text))
        assert named, name
        assert named <= set(tools), (name, named - set(tools))


def test_morning_review_reads_and_changes_nothing(server):
    text = text_of(ask(server, "prompts/get", name="morning_review"))
    for tool in ("list_pipeline", "list_tasks", "followups", "brief", "list_outreach"):
        assert f"`{tool}`" in text
    assert "change nothing" in text.lower()


def test_prompt_arguments_are_filled_in(server):
    text = text_of(ask(server, "prompts/get", name="prep_meeting",
                       arguments={"company": "acme"}))
    assert "acme" in text and "`show_company`" in text
    notes = "Jane wants a demo next Tuesday; send the deck first."
    text = text_of(ask(server, "prompts/get", name="log_call",
                       arguments={"notes": notes, "company": "acme"}))
    assert notes in text and "`add_interaction`" in text and "`add_task`" in text


def test_prompt_errors_are_invalid_params(server):
    r = ask(server, "prompts/get", name="nope")
    assert r["error"]["code"] == mcp.INVALID_PARAMS
    r = ask(server, "prompts/get", name="prep_meeting", arguments={})
    assert r["error"]["code"] == mcp.INVALID_PARAMS and "company" in r["error"]["message"]
    r = ask(server, "prompts/get", name="log_call", arguments={"notes": 5})
    assert r["error"]["code"] == mcp.INVALID_PARAMS


def test_serve_answers_resources_and_prompts(store):
    lines = "\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 2, "method": "prompts/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/read",
         "params": {"uri": "hermitcrm://pipeline"}},
    ])
    out = io.StringIO()
    mcp.serve(store.root, store, stdin=io.StringIO(lines), stdout=out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [len(r["result"]) > 0 for r in replies] == [True, True, True]
    assert len(replies[1]["result"]["prompts"]) == 4


def test_handle_without_a_catalog_still_answers(store):
    tools = {t.name: t for t in mcp.build_tools(store.root, store)}
    r = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/list"}, tools)
    assert r["result"] == {"resources": []}
    r = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "prompts/list"}, tools)
    assert r["result"] == {"prompts": []}
