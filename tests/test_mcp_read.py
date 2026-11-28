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

"""The MCP read tools of MCP 2: search, show_contact, list_tasks, list_outreach,
show_outreach and list_routines. Each goes through `handle` as a client would
send it, and each structured answer is checked against its own outputSchema."""

import pytest

from hermitcrm import mcp, outreach

from conftest import FIXED_NOW

ROUTINES = """[[routine]]
name = "nudge-quiet"
title = "Nudge quiet threads"
action = "draft"
select = "quiet_threads"
prompt = "A short, friendly nudge."
paused = true

[[routine]]
name = "broken"
title = "No action"

[[routine]]
name = "morning"
title = "Morning brief"
action = "brief"
paused = false
"""


@pytest.fixture
def tools(store):
    store.create_company(name="Acme BV", country="NL", stage="discovery",
                         product_oneliner="Churn dashboards")
    store.create_contact("acme", first_name="Jane", last_name="Roe", title="CTO",
                         email="jane@example.com")
    store.create_company(name="Borduro", country="DE")
    store.create_interaction("acme", "email", "out", contact="jane-roe",
                             subject="Pricing", date="2026-09-01",
                             body="Hi Jane,\n\nThe pricing for the churn dashboards "
                                  "is below. Kind regards\n")
    store.create_interaction("borduro", "call", "out", date="2026-09-12",
                             body="Talked about the pricing of a pilot.\n")
    store.add_task("acme", "Send the proposal", due="2026-09-10")
    store.add_task("acme", "Call back about pricing", due="2026-09-14", contact="jane-roe")
    store.add_task("acme", "Plan the demo", due="2026-09-18")
    store.add_task("borduro", "Someday maybe")
    store.add_task("borduro", "Old one", due="2026-09-01")
    store.set_task_done("borduro", 1)
    return {t.name: t for t in mcp.build_tools(store.root, store)}


def call(tools, tool, **arguments):
    """One tools/call: (text, data, failed)."""
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": arguments}}
    payload = mcp.handle(message, tools)["result"]
    data = payload.get("structuredContent")
    if data is not None:
        fits(data, tools[tool].output_schema)
    return payload["content"][0]["text"], data, bool(payload.get("isError"))


def fits(value, shape, where="data"):
    """A small JSON Schema check, enough for the shapes these tools declare:
    the protocol says a structured result MUST fit its outputSchema."""
    kinds = {"object": dict, "array": list, "string": str, "integer": int,
             "boolean": bool}
    kind = shape.get("type")
    if kind:
        assert isinstance(value, kinds[kind]), f"{where}: {value!r} is not {kind}"
        if kind == "integer":
            assert not isinstance(value, bool), where
    if "enum" in shape:
        assert value in shape["enum"], f"{where}: {value!r} not in {shape['enum']}"
    if kind == "object":
        for key in shape.get("required", []):
            assert key in value, f"{where}: {key} missing"
        for key, sub in shape.get("properties", {}).items():
            if key in value:
                fits(value[key], sub, f"{where}.{key}")
    if kind == "array" and "items" in shape:
        for i, item in enumerate(value):
            fits(item, shape["items"], f"{where}[{i}]")


def test_every_new_read_tool_declares_an_output_schema(tools):
    for name in ("search", "show_contact", "list_tasks", "list_outreach",
                 "show_outreach", "list_routines"):
        spec = tools[name].spec()
        assert spec["outputSchema"]["type"] == "object", name
        assert spec["annotations"]["readOnlyHint"] is True, name


# ------------------------------------------------------------------ search


def test_search_finds_companies_people_tasks_and_message_bodies(tools):
    text, data, failed = call(tools, "search", query="pricing")
    assert not failed
    kinds = [r["kind"] for r in data["results"]]
    assert kinds == ["task", "interaction", "interaction"]
    # messages newest first, with the words around the hit
    assert data["results"][1]["company"] == "borduro"
    assert "pricing for the churn" in data["results"][2]["detail"]
    assert data["results"][0]["id"].startswith("acme/jane-roe/0/")
    assert "acme/jane-roe" in text

    _, data, _ = call(tools, "search", query="ROE")
    assert [(r["kind"], r["contact"]) for r in data["results"]] == [("contact", "jane-roe")]

    _, data, _ = call(tools, "search", query="churn", kinds=["company"])
    assert [r["company"] for r in data["results"]] == ["acme"]


def test_search_says_when_nothing_matches_and_needs_a_query(tools):
    text, data, failed = call(tools, "search", query="zeppelin")
    assert not failed and "Nothing matches" in text and data["total"] == 0

    text, _, failed = call(tools, "search", query=" ")
    assert failed and "query is required" in text

    text, _, failed = call(tools, "search", query="x", kinds=["email"])
    assert failed and "kinds are" in text


def test_search_pages_with_a_cursor(tools):
    _, first, _ = call(tools, "search", query="a", limit=2)
    assert len(first["results"]) == 2 and first["next_cursor"]
    _, second, _ = call(tools, "search", query="a", limit=2, cursor=first["next_cursor"])
    assert second["results"][0] not in first["results"]
    text, _, failed = call(tools, "search", query="b", cursor=first["next_cursor"])
    assert failed and "cursor is not one" in text


# ------------------------------------------------------------ show_contact


def test_show_contact_gives_fields_tasks_and_history(tools):
    text, data, failed = call(tools, "show_contact", company="acme", contact="jane-roe")
    assert not failed
    assert (data["name"], data["title"], data["email"]) == ("Jane Roe", "CTO",
                                                           "jane@example.com")
    assert [t["text"] for t in data["tasks"]] == ["Call back about pricing"]
    assert [i["subject"] for i in data["interactions"]] == ["Pricing"]
    assert "Jane Roe at Acme BV" in text and "The pricing for the churn" in text


def test_show_contact_shows_custom_fields(tools, store):
    (store.root / "fields.toml").write_text(
        '[[field]]\nkey = "nickname"\nlabel = "nickname"\ntype = "text"\n'
        'applies_to = "contact"\n', encoding="utf-8")
    store.update_contact("acme", "jane-roe", custom={"nickname": "JR"})
    _, data, _ = call(tools, "show_contact", company="acme", contact="jane-roe")
    assert data["custom"] == {"nickname": "JR"}


def test_show_contact_refuses_what_is_not_there(tools):
    text, _, failed = call(tools, "show_contact", company="acme", contact="nobody")
    assert failed and "unknown contact 'nobody'" in text and "jane-roe" in text
    text, _, failed = call(tools, "show_contact", company="ghost", contact="x")
    assert failed and "unknown company: ghost" in text
    text, _, failed = call(tools, "show_contact", company="acme")
    assert failed and "required" in text


# -------------------------------------------------------------- list_tasks


def texts(data):
    return [t["text"] for t in data["tasks"]]


def test_list_tasks_by_when(tools):
    # FIXED_NOW is 14 September 2026
    assert FIXED_NOW.date().isoformat() == "2026-09-14"
    _, data, _ = call(tools, "list_tasks")
    assert texts(data) == ["Send the proposal", "Call back about pricing", "Plan the demo",
                           "Someday maybe"]
    assert data["tasks"][0]["overdue"] is True
    _, data, _ = call(tools, "list_tasks", when="overdue")
    assert texts(data) == ["Send the proposal"]
    _, data, _ = call(tools, "list_tasks", when="today")
    assert texts(data) == ["Call back about pricing"]
    _, data, _ = call(tools, "list_tasks", when="week")
    assert texts(data) == ["Call back about pricing", "Plan the demo"]
    _, data, _ = call(tools, "list_tasks", when="done")
    assert texts(data) == ["Old one"] and data["tasks"][0]["done_on"] == "2026-09-14"


def test_list_tasks_for_one_company_and_its_errors(tools):
    text, data, _ = call(tools, "list_tasks", company="borduro")
    assert texts(data) == ["Someday maybe"] and "Borduro" in text
    text, _, failed = call(tools, "list_tasks", company="ghost")
    assert failed and "unknown company" in text
    text, _, failed = call(tools, "list_tasks", when="tomorrow")
    assert failed and "when is one of" in text
    text, data, failed = call(tools, "list_tasks", when="today", company="borduro")
    assert not failed and data["total"] == 0 and "No today tasks for borduro" in text


def test_list_tasks_pages(tools):
    text, data, _ = call(tools, "list_tasks", limit=3)
    assert len(data["tasks"]) == 3 and data["total"] == 4 and "next_cursor" in data
    assert "3 of 4 shown" in text
    _, rest, _ = call(tools, "list_tasks", limit=3, cursor=data["next_cursor"])
    assert texts(rest) == ["Someday maybe"] and "next_cursor" not in rest


# ---------------------------------------------------------------- outreach


@pytest.fixture
def drafts(tools, store):
    for n, (state, subject) in enumerate([("drafted", "Quick idea"),
                                          ("skipped", "Old idea")]):
        outreach.write_item(store.root, outreach.Item(
            id=f"2026-09-1{n}T0900-email-acme-jane-roe", state=state, company="acme",
            contact="jane-roe", subject=subject, body="Hi Jane,\n\nA quick idea.\n",
            ai_body="Hi Jane,\n\nA quick idea.\n", skip_reason="bad-timing" if n else "",
            created=FIXED_NOW.replace(day=10 + n)))
    return tools


def test_list_outreach_by_status(drafts):
    text, data, failed = call(drafts, "list_outreach")
    assert not failed and data["status"] == "drafted"
    assert [i["subject"] for i in data["items"]] == ["Quick idea"]
    _, data, _ = call(drafts, "list_outreach", status="all")
    assert [i["subject"] for i in data["items"]] == ["Old idea", "Quick idea"]
    _, data, _ = call(drafts, "list_outreach", status="open")
    assert [i["state"] for i in data["items"]] == ["drafted"]
    text, data, _ = call(drafts, "list_outreach", status="ready")
    assert data["total"] == 0 and "No outreach items are ready" in text
    text, _, failed = call(drafts, "list_outreach", status="approved")
    assert failed and "status is one of" in text


def test_show_outreach_gives_the_whole_draft(drafts):
    text, data, failed = call(drafts, "show_outreach", id="2026-09-10T0900-email-acme-jane-roe")
    assert not failed
    assert data["body"] == "Hi Jane,\n\nA quick idea.\n" and data["state"] == "drafted"
    assert "Subject: Quick idea" in text and "Contact: Jane Roe" in text
    text, _, failed = call(drafts, "show_outreach", id="nope")
    assert failed and "unknown outreach item" in text
    text, _, failed = call(drafts, "show_outreach", id="../../etc/passwd")
    assert failed and "unknown outreach item" in text


# ---------------------------------------------------------------- routines


def test_list_routines_without_a_file(tools):
    text, data, failed = call(tools, "list_routines")
    assert not failed and "No routines.toml" in text and data["total"] == 0


def test_list_routines_says_what_each_does(tools, store):
    (store.root / "routines.toml").write_text(ROUTINES, encoding="utf-8")
    text, data, failed = call(tools, "list_routines")
    assert not failed
    assert [(r["name"], r["state"]) for r in data["routines"]] == [
        ("nudge-quiet", "paused"), ("broken", "problem"), ("morning", "on")]
    assert "people you messaged" in data["routines"][0]["does"]
    assert data["routines"][2]["last_run"] == "never run"
    assert data["problems"] and "broken" in data["problems"][0]
    assert "Drafts waiting on Home: 0" in text
