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

"""What an outreach costs: the model each call asks the CLI for, and what each
call carries. The real Enricher runs; only the `claude` binary is a stand-in, so
these tests read the command line it was started with. All names are made up."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hermitcrm import outreach
from hermitcrm.enrich import Enricher
from outreach_fakes import (
    ALL, NOW, default_critic, default_draft, default_research, demo, fake_page,
)

MARA = "lindenhof-data/mara-keller"


class ClaudeCli:
    """Stands in for the `claude` binary: answers each call from the shared fakes
    and keeps the command line it got. Every other command (git) really runs."""

    def __init__(self, real_run):
        self.real_run, self.calls = real_run, []

    def __call__(self, argv, *args, **kwargs):
        if Path(argv[0]).name != "claude":
            return self.real_run(argv, *args, **kwargs)
        props = json.loads(argv[argv.index("--json-schema") + 1]).get("properties", {})
        kind = ("web" if "sources" in props else "research" if "findings" in props else
                "critic" if "relevance" in props else "draft")
        answer = {"web": lambda prompt: {"findings": [], "sources": []},
                  "research": default_research, "critic": default_critic,
                  "draft": default_draft}[kind]
        self.calls.append({"kind": kind, "argv": list(argv),
                           "model": argv[argv.index("--model") + 1]})
        return subprocess.CompletedProcess(
            argv, 0, json.dumps({"structured_output": answer(kwargs["input"])}), "")


@pytest.fixture
def cli(monkeypatch):
    stand_in = ClaudeCli(subprocess.run)
    monkeypatch.setattr(subprocess, "run", stand_in)
    return stand_in


@pytest.fixture(params=[("medium", "claude-opus-5"), ("strong", "claude-fable-5-1")],
                ids=["medium", "strong"])
def built(request, tmp_path, cli):
    """One first touch built the way the pages and the command line build it: the
    same enricher handed to the researcher, the drafter and the critic."""
    tier, drafting_model = request.param
    root, store = demo(tmp_path)
    enricher = Enricher(provider="claude", which=ALL).with_tier(tier)
    config = {"owner_name": "Sam Example"}
    selection = outreach.select(store, where=["stage=prospect"], limit=1, config=config)
    result = outreach.build(
        store, selection,
        outreach.researcher_for("scrape", enricher, fetcher=fake_page, today=NOW.date()),
        outreach.AIDrafter(store, enricher, config), config, now=NOW,
        critic=outreach.AICritic(store, enricher))
    return result.items[0], drafting_model


def test_research_and_the_critic_run_on_the_light_model_and_the_draft_does_not(cli, built):
    item, drafting_model = built
    assert [(c["kind"], c["model"]) for c in cli.calls] == [
        ("research", "claude-haiku-4-5"), ("draft", drafting_model),
        ("critic", "claude-haiku-4-5")]
    assert (item.model, item.critic_model) == (drafting_model, "claude-haiku-4-5")


def test_none_of_the_three_calls_carries_the_users_mcp_connectors(cli, built):
    assert len(cli.calls) == 3
    assert all("--strict-mcp-config" in call["argv"] for call in cli.calls)


def test_ai_web_reads_the_scrape_on_the_light_model_and_searches_on_the_medium_one(
        cli, tmp_path):
    root, store = demo(tmp_path)
    company = store.get("lindenhof-data")
    contact = company.contacts["mara-keller"]
    enricher = Enricher(provider="claude", which=ALL)
    outreach.researcher_for("ai-web", enricher, fetcher=fake_page,
                            today=NOW.date()).research(company, contact)
    assert [(c["kind"], c["model"]) for c in cli.calls] == [
        ("research", "claude-haiku-4-5"), ("web", "claude-opus-5")]
    web = cli.calls[1]["argv"]
    assert web[web.index("--tools") + 1] == "WebSearch,WebFetch"
