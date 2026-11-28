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

"""The MCP write tools of MCP 2: update_company, update_contact, move_stage,
add_task, complete_task, reopen_task, edit_outreach_draft and skip_outreach.

Each one is checked three ways, in a real git folder: the file it changed, the
one commit it made, and that `undo` with the id from its answer puts the file
back exactly as it was."""

import re
import subprocess
from datetime import datetime

import pytest

from hermitcrm import cli, mcp, outreach
from hermitcrm.datafolder import init_folder
from hermitcrm.setup import set_config_values

WRITE_TOOLS = ("update_company", "update_contact", "move_stage", "add_task",
               "complete_task", "reopen_task", "edit_outreach_draft", "skip_outreach")
ITEM = "2026-09-10T0900-email-acme-jane-roe"


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


def commit_all(root, message):
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", message)


@pytest.fixture
def folder(tmp_path):
    root = init_folder(tmp_path / "crm")
    set_config_values(root / "config.toml", {"push_enabled": False})  # no remote here
    commit_all(root, "nopush")
    return root


@pytest.fixture
def tools(folder):
    store = cli.build_store(folder)
    found = {t.name: t for t in mcp.build_tools(folder, store)}
    call(found, "add_company", name="Acme BV", country="NL")
    call(found, "add_contact", company="acme", name="Jane Roe", title="CTO")
    call(found, "add_company", name="Borduro", country="DE")
    return found


def call(tools, tool, **arguments):
    """One tools/call: (text, failed)."""
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": arguments}}
    payload = mcp.handle(message, tools)["result"]
    return payload["content"][0]["text"], bool(payload.get("isError"))


def undo_id(text):
    return re.search(r"Undo: undo\(([0-9a-f]{7})\)", text).group(1)


def subject(root):
    return git(root, "log", "-1", "--format=%s")


def touched(root):
    return git(root, "show", "--name-only", "--format=", "HEAD").splitlines()


def company_file(root, slug="acme"):
    return (root / "companies" / slug / "company.md").read_text(encoding="utf-8")


def contact_file(root):
    return (root / "companies" / "acme" / "contacts" / "jane-roe.md").read_text(
        encoding="utf-8")


def test_the_write_tools_are_there_and_say_they_write(tools):
    for name in WRITE_TOOLS:
        assert tools[name].annotations["readOnlyHint"] is False, name
        assert "undo" in tools[name].description.lower() or "commit" in \
            tools[name].description.lower(), name


# --------------------------------------------------------- update_company


def test_update_company_writes_one_commit_and_undo_restores_it(tools, folder):
    before = company_file(folder)
    n = int(git(folder, "rev-list", "--count", "HEAD"))
    text, failed = call(tools, "update_company", company="acme",
                        website="https://acme.example.com", tags="saas, nl")
    assert not failed, text
    assert "acme.example.com" in company_file(folder)
    assert int(git(folder, "rev-list", "--count", "HEAD")) == n + 1
    assert subject(folder) == "company: acme updated"
    assert "companies/acme/company.md" in touched(folder)
    text, failed = call(tools, "undo", sha=undo_id(text))
    assert not failed and company_file(folder) == before


def test_update_company_takes_custom_fields(tools, folder):
    (folder / "fields.toml").write_text(
        '[[field]]\nkey = "renewal"\nlabel = "renewal"\ntype = "date"\n'
        'applies_to = "company"\n', encoding="utf-8")
    commit_all(folder, "fields")
    text, failed = call(tools, "update_company", company="acme",
                        custom={"renewal": "2027-01-31"})
    assert not failed, text
    assert "renewal: 2027-01-31" in company_file(folder)
    text, failed = call(tools, "update_company", company="acme",
                        custom={"renewal": "soon"})
    assert failed and "renewal" in text
    text, failed = call(tools, "update_company", company="acme", custom={"colour": "red"})
    assert failed and "unknown custom field 'colour'" in text and "renewal" in text


def test_update_company_refuses_stage_and_nothing(tools, folder):
    before = git(folder, "rev-parse", "HEAD")
    text, failed = call(tools, "update_company", company="acme")
    assert failed and "nothing to change" in text
    text, failed = call(tools, "update_company", company="ghost", website="x.example.com")
    assert failed and "unknown company" in text
    text, failed = call(tools, "update_company", company="acme", country="ZZZZ")
    assert failed and "country" in text
    # stage is not one of the fields: move_stage is the way, with the rules
    assert "stage" not in tools["update_company"].schema["properties"]
    assert git(folder, "rev-parse", "HEAD") == before


# --------------------------------------------------------- update_contact


def test_update_contact_writes_one_commit_and_undo_restores_it(tools, folder):
    before = contact_file(folder)
    text, failed = call(tools, "update_contact", company="acme", contact="jane-roe",
                        title="CEO", email="jane@example.com")
    assert not failed, text
    assert "title: CEO" in contact_file(folder)
    assert subject(folder) == "contact: acme/jane-roe updated"
    assert touched(folder)[0] == "companies/acme/contacts/jane-roe.md"
    text, failed = call(tools, "undo", sha=undo_id(text))
    assert not failed and contact_file(folder) == before


def test_update_contact_errors(tools):
    text, failed = call(tools, "update_contact", company="acme", contact="nobody",
                        title="CEO")
    assert failed and "unknown contact" in text
    text, failed = call(tools, "update_contact", company="acme", contact="jane-roe",
                        email="not an email")
    assert failed and "email" in text


# ------------------------------------------------------------- move_stage


def test_move_stage_moves_and_undo_moves_back(tools, folder):
    before = company_file(folder)
    text, failed = call(tools, "move_stage", company="acme", stage="discovery")
    assert not failed, text
    assert "stage: discovery" in company_file(folder)
    assert subject(folder) == "company: acme stage prospect -> discovery"
    text, failed = call(tools, "undo", sha=undo_id(text))
    assert not failed and company_file(folder) == before


def test_move_stage_to_lost_needs_a_reason_and_keeps_it(tools, folder):
    text, failed = call(tools, "move_stage", company="acme", stage="lost")
    assert failed and "reason" in text
    text, failed = call(tools, "move_stage", company="acme", stage="lost",
                        reason="Chose a competitor")
    assert not failed and "lost_reason: Chose a competitor" in company_file(folder)


def test_move_stage_parks_with_a_requalify_date(tools, folder):
    text, failed = call(tools, "move_stage", company="acme", stage="temp-disqualified",
                        reason="Budget next year", requalify_on="2027-03-01")
    assert not failed, text
    assert "requalify_on: 2027-03-01" in company_file(folder)
    assert "until 2027-03-01" in text


def test_move_stage_follows_the_stage_rules_and_has_no_force(tools, folder):
    set_config_values(folder / "config.toml", {
        "stage_rules": "enforce",
        "stages": [{"name": "prospect", "to": ["engaged"]}, {"name": "engaged"},
                   {"name": "discovery", "valued": True}, {"name": "offer", "valued": True},
                   {"name": "won", "role": "won"}, {"name": "lost", "role": "lost"},
                   {"name": "disqualified", "role": "closed"},
                   {"name": "temp-disqualified", "role": "parked"}]})
    commit_all(folder, "rules")
    store = cli.build_store(folder)
    tools = {t.name: t for t in mcp.build_tools(folder, store)}
    before = company_file(folder)
    text, failed = call(tools, "move_stage", company="acme", stage="offer")
    assert failed and "is not allowed" in text and "engaged" in text
    assert company_file(folder) == before
    assert "force" not in tools["move_stage"].schema["properties"]
    # a force sent anyway is not an argument of the tool: the rules still apply
    text, failed = call(tools, "move_stage", company="acme", stage="offer", force=True)
    assert failed and "is not allowed" in text
    assert company_file(folder) == before
    text, failed = call(tools, "move_stage", company="acme", stage="engaged")
    assert not failed, text


def test_move_stage_says_when_nothing_moves(tools, folder):
    before = git(folder, "rev-parse", "HEAD")
    text, failed = call(tools, "move_stage", company="acme", stage="prospect")
    assert not failed and "already" in text
    text, failed = call(tools, "move_stage", company="acme", stage="nowhere")
    assert failed and "nowhere" in text
    assert git(folder, "rev-parse", "HEAD") == before


# ------------------------------------------------------------------ tasks


def task_ids(tools, **args):
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "list_tasks", "arguments": args}}
    data = mcp.handle(message, tools)["result"]["structuredContent"]
    return {t["text"]: t["id"] for t in data["tasks"]}


def test_add_task_then_complete_then_reopen_each_one_undoable(tools, folder):
    before = contact_file(folder)
    text, failed = call(tools, "add_task", company="acme", contact="jane-roe",
                        text="Call back about pricing", due="2026-12-01")
    assert not failed, text
    assert "Call back about pricing" in contact_file(folder)
    assert subject(folder) == "task: acme/jane-roe added"
    added = contact_file(folder)
    task = task_ids(tools)["Call back about pricing"]
    assert task in text   # the answer gives the id for complete_task

    text, failed = call(tools, "complete_task", task=task)
    assert not failed, text
    assert "done: true" in contact_file(folder)
    assert subject(folder) == "task: acme/jane-roe done"
    text_again, failed = call(tools, "complete_task", task=task)
    assert not failed and "already done" in text_again

    reopened, failed = call(tools, "reopen_task", task=task)
    assert not failed and subject(folder) == "task: acme/jane-roe reopened"
    assert contact_file(folder) == added

    _, failed = call(tools, "undo", sha=undo_id(reopened))
    assert not failed and "done: true" in contact_file(folder)
    _, failed = call(tools, "undo", sha=undo_id(text))
    assert not failed and contact_file(folder) == added
    assert before != added


def test_add_task_on_the_company_and_its_errors(tools, folder):
    text, failed = call(tools, "add_task", company="acme", text="Send the proposal")
    assert not failed and "Send the proposal" in company_file(folder)
    text, failed = call(tools, "add_task", company="acme", text=" ")
    assert failed and "line of text" in text
    text, failed = call(tools, "add_task", company="acme", text="x", due="someday")
    assert failed and "due" in text
    text, failed = call(tools, "add_task", company="acme", text="x", contact="nobody")
    assert failed and "nobody" in text


def test_a_stale_task_id_is_refused(tools, folder):
    call(tools, "add_task", company="acme", text="First")
    task = task_ids(tools)["First"]
    # the task changes under the agent (in the web app, say)
    store = cli.build_store(folder)
    store.edit_todo("acme", 0, "First, changed")
    text, failed = call(tools, "complete_task", task=task)
    assert failed and "not there any more" in text
    text, failed = call(tools, "complete_task", task="rubbish")
    assert failed and "task must be an id" in text


def test_the_next_step_fields_complete_too(tools, folder):
    call(tools, "update_company", company="acme", next_step="Book a demo",
         next_step_due="2026-12-02")
    task = task_ids(tools)["Book a demo"]
    assert "/next/" in task
    text, failed = call(tools, "complete_task", task=task)
    assert not failed, text
    assert "next_step_status: done" in company_file(folder)
    assert subject(folder) == "company: acme next step done"
    task = task_ids(tools, when="done")["Book a demo"]
    text, failed = call(tools, "reopen_task", task=task)
    assert not failed and "next_step_status: open" in company_file(folder)


# --------------------------------------------------------------- outreach


@pytest.fixture
def draft(tools, folder):
    outreach.write_item(folder, outreach.Item(
        id=ITEM, state="drafted", company="acme", contact="jane-roe",
        subject="Quick idea", body="Hi Jane,\n\nA quick idea.\n",
        ai_subject="Quick idea", ai_body="Hi Jane,\n\nA quick idea.\n",
        created=datetime(2026, 9, 10, 9, 0)))
    commit_all(folder, "a draft")
    return folder / "outreach" / f"{ITEM}.md"


def test_edit_outreach_draft_saves_a_tracked_edit_and_undo_restores_it(tools, draft):
    folder = draft.parents[1]
    before = draft.read_text(encoding="utf-8")
    text, failed = call(tools, "edit_outreach_draft", id=ITEM,
                        body="Hi Jane,\n\nA shorter idea.\n", note="shorter")
    assert not failed, text
    item = outreach.get_item(folder, ITEM)
    assert item.body == "Hi Jane,\n\nA shorter idea.\n" and item.state == "drafted"
    assert item.ai_body == "Hi Jane,\n\nA quick idea.\n"   # the AI's original is kept
    assert len(item.edits) == 1 and item.edits[0].note == "shorter"
    assert subject(folder).startswith("outreach: edit acme/jane-roe (email)")
    assert f"outreach/{ITEM}.md" in touched(folder)
    text, failed = call(tools, "undo", sha=undo_id(text))
    assert not failed and draft.read_text(encoding="utf-8") == before


def test_edit_outreach_draft_asks_no_ai_and_refuses_what_is_not_a_draft(tools, draft):
    folder = draft.parents[1]
    text, failed = call(tools, "edit_outreach_draft", id=ITEM)
    assert failed and "subject, body or pitch" in text
    text, failed = call(tools, "edit_outreach_draft", id=ITEM, body="  ")
    assert failed and "empty" in text
    item = outreach.get_item(folder, ITEM)
    item.state = "ready"
    outreach.write_item(folder, item)
    commit_all(folder, "ready by the user")
    text, failed = call(tools, "edit_outreach_draft", id=ITEM, body="Hi.\n")
    assert failed and "only a drafted item" in text
    text, failed = call(tools, "edit_outreach_draft", id="nope", body="Hi.\n")
    assert failed and "unknown outreach item" in text


def test_skip_outreach_skips_with_a_reason_and_undo_restores_it(tools, draft):
    folder = draft.parents[1]
    before = draft.read_text(encoding="utf-8")
    text, failed = call(tools, "skip_outreach", id=ITEM, reason="bad-timing",
                        note="after the summer")
    assert not failed, text
    item = outreach.get_item(folder, ITEM)
    assert (item.state, item.skip_reason, item.skip_note) == (
        "skipped", "bad-timing", "after the summer")
    assert subject(folder) == "outreach: skip acme/jane-roe: bad-timing"
    text, failed = call(tools, "undo", sha=undo_id(text))
    assert not failed and draft.read_text(encoding="utf-8") == before


def test_skip_outreach_takes_only_the_reasons_a_person_can_pick(tools, draft):
    text, failed = call(tools, "skip_outreach", id=ITEM, reason="company-closed")
    assert failed and "bad-fit" in text
    text, failed = call(tools, "skip_outreach", id=ITEM)
    assert failed and "reason" in text
    call(tools, "skip_outreach", id=ITEM, reason="other")
    text, failed = call(tools, "skip_outreach", id=ITEM, reason="other")
    assert failed and "only an open item can be skipped" in text
