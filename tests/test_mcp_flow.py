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

"""The three jobs MCP 2 is for, done the way a client with only this server
would: over the stdio loop, on the demo folder. A morning review (the prompt,
then every tool it names), a call logged with a follow-up task, and a deal
moved on."""

import io
import json
import re
import subprocess

import pytest

from hermitcrm import cli, mcp
from hermitcrm.datafolder import init_folder
from hermitcrm.setup import set_config_values


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def demo(tmp_path):
    root = init_folder(tmp_path / "demo", demo=True)
    set_config_values(root / "config.toml", {"push_enabled": False})
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam",
        "nopush")
    return root


class Client:
    """Sends JSON-RPC lines through `serve`, as a client on the pipe would."""

    def __init__(self, root):
        self.root, self.next_id = root, 0

    def send(self, *messages):
        lines = []
        for method, params in messages:
            self.next_id += 1
            lines.append(json.dumps({"jsonrpc": "2.0", "id": self.next_id,
                                     "method": method, "params": params}))
        out = io.StringIO()
        mcp.serve(self.root, cli.build_store(self.root), stdin=io.StringIO("\n".join(lines)),
                  stdout=out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def tool(self, name, **arguments):
        [reply] = self.send(("tools/call", {"name": name, "arguments": arguments}))
        payload = reply["result"]
        assert not payload.get("isError"), (name, payload["content"][0]["text"])
        return payload["content"][0]["text"], payload.get("structuredContent")


def test_a_morning_review_with_only_the_server(demo):
    client = Client(demo)
    before = git(demo, "rev-parse", "HEAD")
    init, prompt = client.send(("initialize", {"protocolVersion": mcp.PROTOCOL_VERSION}),
                               ("prompts/get", {"name": "morning_review"}))
    assert "prompts" in init["result"]["capabilities"]
    instruction = prompt["result"]["messages"][0]["content"]["text"]
    named = re.findall(r"`([a-z_]+)`", instruction)
    assert named == ["list_pipeline", "list_tasks", "followups", "brief", "list_outreach"]
    text, _ = client.tool("list_pipeline")
    assert "# Pipeline" in text
    _, overdue = client.tool("list_tasks", when="overdue")
    _, today = client.tool("list_tasks", when="today")
    assert overdue["total"] + today["total"] >= 0
    client.tool("followups")
    client.tool("brief", days=1)
    client.tool("list_outreach")
    # a review reads: nothing was committed
    assert git(demo, "rev-parse", "HEAD") == before


def test_log_a_call_with_a_follow_up_and_move_the_deal(demo):
    client = Client(demo)
    store = cli.build_store(demo)
    company = next(c for c in sorted(store.companies.values(), key=lambda c: c.slug)
                   if c.stage == "engaged" and c.contacts)
    person = sorted(company.contacts)[0]

    _, found = client.tool("search", query=company.name.split()[0], kinds=["company"])
    assert company.slug in [r["company"] for r in found["results"]]

    text, _ = client.tool("add_interaction", company=company.slug, channel="call",
                          direction="out", contact=person,
                          body="Walked through the pilot. They want a proposal.\n")
    assert "Logged" in text
    text, _ = client.tool("add_task", company=company.slug, contact=person,
                          text="Send the pilot proposal", due="2099-01-15")
    task = re.search(r"as (\S+/\S+/\d+/[0-9a-f]{6})\.", text).group(1)
    _, tasks = client.tool("list_tasks", company=company.slug)
    assert task in [t["id"] for t in tasks["tasks"]]

    text, _ = client.tool("move_stage", company=company.slug, stage="discovery")
    assert f"Moved {company.slug} engaged -> discovery" in text
    assert cli.build_store(demo).get(company.slug).stage == "discovery"
    log = git(demo, "log", "-3", "--format=%s").splitlines()
    assert log[0] == f"company: {company.slug} stage engaged -> discovery"
    assert log[1] == f"task: {company.slug}/{person} added"

    # and the move can be taken back
    sha = re.search(r"Undo: undo\(([0-9a-f]{7})\)", text).group(1)
    client.tool("undo", sha=sha)
    assert cli.build_store(demo).get(company.slug).stage == "engaged"
