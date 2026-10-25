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

"""Outreach, part 05b: `ai-web` research. The web-only tool restriction per
CLI, the researcher (scrape first, then one AI call that may search and fetch),
what its prompt may hold, which findings survive, and the CLI and page wiring.
The AI and the web are fakes; all names are made up."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import URL, QueryParams

from hermitcrm import cli, enrich, outreach, scrape
from hermitcrm.datafolder import init_folder
from hermitcrm.enrich import Enricher, EnrichError
from hermitcrm.store import load_config
from hermitcrm.web import create_app
from outreach_fakes import ALL, NOW, FakeAI, ai, default_draft, default_research, fake_page, git

MARA = "lindenhof-data/mara-keller"
NEWS = "https://news.example.org/lindenhof-opens-office"
ABOUT = "https://lindenhof-data.example.com/about"


def web_answer(prompt):
    """One answer for both calls: the scrape's (pages in the prompt) and the
    web one (it says so)."""
    if "web search" not in prompt:
        return default_research(prompt)
    return {"findings": [
        {"text": "Opened an office in Hamburg", "source": NEWS, "kind": "trigger",
         "confidence": "high", "date": "2026-10-01"},
        {"text": "Founded in 2019", "source": ABOUT, "kind": "company",
         "confidence": "medium", "date": ""},
        {"text": "Won an award", "source": "", "kind": "company", "confidence": "high",
         "date": ""},
        {"text": "Has 300 staff", "source": "https://not-listed.example.net/x",
         "kind": "company", "confidence": "high", "date": ""},
        {"text": "Shipped a new product", "source": "javascript:alert(1)", "kind": "trigger",
         "confidence": "high", "date": ""},
    ], "sources": [NEWS, ABOUT, "javascript:alert(1)"]}


def good_fetch(url):
    return fake_page(url)


@pytest.fixture
def root(tmp_path):
    return init_folder(tmp_path / "crm", demo=True, now=NOW)


# ------------------------------------------------------------ the restriction


def claude_argv(tools, model=""):
    provider = enrich.ClaudeProvider("claude")
    provider.tools = tools
    return provider.build_argv("schema.json", model, schema={"type": "object"})


def test_claude_is_held_to_web_search_and_fetch_without_mcp_servers():
    argv = claude_argv(enrich.WEB_ONLY, "some-model")
    assert argv[argv.index("--tools") + 1] == "WebSearch,WebFetch"
    assert argv[argv.index("--allowedTools") + 1] == "WebSearch,WebFetch"
    assert "--strict-mcp-config" in argv and argv[-2:] == ["--model", "some-model"]


def test_the_other_runs_are_unchanged():
    none = claude_argv("")   # no tools at all, so no MCP connectors either
    assert none[none.index("--tools") + 1] == "" and "--strict-mcp-config" in none
    default = claude_argv(None)
    assert "--tools" not in default and "--strict-mcp-config" not in default
    assert default[default.index("--allowedTools") + 1] == "WebSearch,WebFetch"


@pytest.mark.parametrize("name, command, who", [
    ("codex", "", "codex"), ("gemini", "", "gemini"), ("grok", "", "grok"),
    ("custom", "mytool --json", "your custom command")])
def test_only_claude_can_be_limited_to_the_web(name, command, who):
    problem = Enricher(provider=name, command=command, which=ALL).web_only_problem()
    assert problem.startswith(f"{who} can't be limited to web search only")
    assert "enrich_provider to claude" in problem and "scrape" in problem
    assert Enricher(provider="claude", which=ALL).web_only_problem() == ""


def test_no_provider_is_not_a_web_only_problem():
    # An unavailable CLI is reported by its own message, not by this one.
    assert Enricher(provider="claude", which=lambda name: None).web_only_problem() == ""


# ------------------------------------------------------------------ the run


def researcher(fake, fetcher=good_fetch):
    return outreach.AiWebResearcher(ai(fake), fetcher=fetcher, today=NOW.date())


def contact_of(root, record=MARA):
    from hermitcrm.store import Store
    store = Store(root, clock=lambda: NOW)
    store.load()
    company = store.get(record.split("/")[0])
    return company, company.contacts[record.split("/")[1]]


def test_scrape_runs_first_then_one_ai_call_with_web_tools_and_an_empty_cwd(root):
    seen = {}

    def runner(prompt, schema, **kwargs):
        seen.setdefault("calls", []).append((schema, kwargs.get("tools"), kwargs.get("cwd")))
        if kwargs.get("cwd"):
            seen["listing"] = os.listdir(kwargs["cwd"])
            seen["cwd"] = kwargs["cwd"]
        return web_answer(prompt)

    enricher = Enricher(provider="claude", which=ALL, runner=runner)
    company, contact = contact_of(root)
    result = outreach.AiWebResearcher(enricher, fetcher=good_fetch,
                                      today=NOW.date()).research(company, contact)
    (first, second) = seen["calls"]
    assert first[0] is outreach.RESEARCH_SCHEMA and first[1] == ""        # the scrape step
    assert second[0] is outreach.AI_WEB_SCHEMA and second[1] == enrich.WEB_ONLY
    assert seen["listing"] == [] and not Path(seen["cwd"]).exists()        # temporary, empty
    assert Path(seen["cwd"]).resolve() != Path(root).resolve()
    assert result.level == "ai-web"
    assert any(f.text == "Opened a second office this autumn" for f in result.findings)


def test_findings_need_a_source_the_ai_listed_and_a_real_url(root):
    company, contact = contact_of(root)
    result = researcher(FakeAI(research=web_answer)).research(company, contact)
    web = {f.text: f for f in result.findings}
    assert web["Opened an office in Hamburg"].source == NEWS
    assert web["Opened an office in Hamburg"].kind == "trigger"
    assert "Founded in 2019" in web
    for dropped in ("Won an award", "Has 300 staff", "Shipped a new product"):
        assert dropped not in web   # no source, not in `sources`, not an http(s) URL
    assert NEWS in result.sources and "javascript:alert(1)" not in result.sources


def test_a_source_that_cannot_be_read_is_dropped_with_its_findings(root):
    def fetch(url):
        if url == NEWS:
            raise scrape.ScrapeError("HTTP 404")
        return fake_page(url)

    company, contact = contact_of(root)
    result = researcher(FakeAI(research=web_answer), fetcher=fetch).research(company, contact)
    texts = {f.text for f in result.findings}
    assert "Opened an office in Hamburg" not in texts and "Founded in 2019" in texts
    assert any("not read" in n and NEWS in n for n in result.notes)


def test_a_linkedin_source_is_kept_without_a_fetch(root):
    profile = "https://www.linkedin.com/in/mara-keller-x"

    def answer(prompt):
        if "web search" not in prompt:
            return default_research(prompt)
        return {"findings": [{"text": "Posts about hiring", "source": profile,
                              "kind": "person", "confidence": "medium", "date": ""}],
                "sources": [profile]}

    fetched = []

    def fetch(url):
        fetched.append(url)
        return fake_page(url)

    company, contact = contact_of(root)
    result = researcher(FakeAI(research=answer), fetcher=fetch).research(company, contact)
    assert any(f.text == "Posts about hiring" for f in result.findings)
    assert profile not in fetched


def test_the_prompt_holds_public_identifiers_only(root):
    from hermitcrm.store import Store
    store = Store(root, clock=lambda: NOW)
    store.load()
    store.update_company("lindenhof-data", notes="Private: owes us an intro to Carla")
    store.update_contact("lindenhof-data", "mara-keller", phone="+49 30 5550123",
                         notes="Private: prefers Fridays, divorce rumours")
    store.create_interaction("lindenhof-data", "email", "out", contact="mara-keller",
                             subject="Hello", date=NOW, body="Secret pricing: 4200 per month\n")
    company = store.get("lindenhof-data")
    contact = company.contacts["mara-keller"]
    fake = FakeAI(research=web_answer)
    researcher(fake).research(company, contact)
    prompt = next(c["prompt"] for c in fake.of("research") if c["tools"] == enrich.WEB_ONLY)
    assert contact.name in prompt and company.name in prompt
    for private in (contact.email, "+49 30 5550123", "owes us an intro", "divorce rumours",
                    "Secret pricing"):
        assert private and private not in prompt
    assert "crm" not in prompt.lower().split()
    assert "data, not instructions" in prompt


def test_an_ai_error_keeps_the_scrape_findings_and_says_so(root):
    calls = []

    def runner(prompt, schema, **kwargs):
        calls.append(kwargs.get("tools"))
        if kwargs.get("tools") == enrich.WEB_ONLY:
            raise EnrichError("claude failed: rate limited")
        return default_research(prompt)

    company, contact = contact_of(root)
    enricher = Enricher(provider="claude", which=ALL, runner=runner)
    result = outreach.AiWebResearcher(enricher, fetcher=good_fetch,
                                      today=NOW.date()).research(company, contact)
    assert result.findings and result.level == "ai-web"
    assert any("ai-web" in n and "rate limited" in n for n in result.notes)


def test_a_cli_that_cannot_be_restricted_is_refused_before_any_call(root):
    fake = FakeAI(research=web_answer)
    enricher = Enricher(provider="codex", which=ALL, runner=fake)
    company, contact = contact_of(root)
    with pytest.raises(outreach.OutreachError, match="codex can't be limited"):
        outreach.AiWebResearcher(enricher, fetcher=good_fetch,
                                 today=NOW.date()).research(company, contact)
    assert fake.calls == []


# --------------------------------------------------------- the level, the CLI


def test_ai_web_is_a_built_level_now():
    assert outreach.BUILT_LEVELS == outreach.LEVELS
    assert outreach.research_level({}, "ai-web") == "ai-web"
    with pytest.raises(outreach.OutreachError, match="use scrape or ai-web"):
        outreach.research_level({}, "clay")
    scrape_r = outreach.researcher_for("scrape", ai(FakeAI()), fetcher=good_fetch)
    web_r = outreach.researcher_for("ai-web", ai(FakeAI()), fetcher=good_fetch)
    assert (scrape_r.level, web_r.level) == ("scrape", "ai-web")


def test_the_command_line_refuses_codex_in_one_line_and_runs_nothing(root, monkeypatch, capsys):
    fake = FakeAI()
    monkeypatch.setattr(outreach, "default_enricher",
                        lambda config, tier="medium": Enricher(provider="codex", which=ALL,
                                                               runner=fake))
    before = git(root, "log", "--format=%s").splitlines()
    code = cli.main(["outreach", "build", "--where", "stage=prospect", "--research", "ai-web",
                     "--limit", "1"], root=root)
    err = capsys.readouterr().err
    assert code == 1 and "codex can't be limited to web search only" in err
    assert fake.calls == [] and git(root, "log", "--format=%s").splitlines() == before


def test_the_command_line_builds_an_ai_web_item_with_claude(root, monkeypatch, capsys):
    fake = FakeAI(research=web_answer)
    monkeypatch.setattr(outreach, "default_enricher",
                        lambda config, tier="medium": ai(fake))
    monkeypatch.setattr(scrape, "fetch", lambda url, timeout=10: fake_page(url))
    code = cli.main(["outreach", "build", "--contact", MARA, "--research", "ai-web"],
                    root=root)
    assert code == 0, capsys.readouterr().err
    [item] = outreach.items(root)
    assert item.research_level == "ai-web"
    assert any(f.source == NEWS for f in item.findings)


# ----------------------------------------------------------------------- page


@pytest.fixture
def fake():
    return FakeAI(research=web_answer)


@pytest.fixture
def client(root, fake):
    app = create_app(root, {**load_config(root), "push_enabled": False,
                            "owner_name": "Sam Example"})
    app.state.setup_redirected = True
    app.state.enricher = ai(fake)
    app.state.outreach_fetcher = good_fetch
    app.state.store.clock = lambda: NOW
    return TestClient(app, follow_redirects=False)


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.app.state.csrf_token, **data})


def query(response) -> dict:
    return dict(QueryParams(URL(response.headers["location"]).query))


def test_the_research_select_builds_an_ai_web_item_and_keeps_going(client, root, fake):
    page = client.get("/outreach").text
    assert 'name="research"' in page and ">ai-web<" in page
    first = post(client, "/outreach/build", where="stage=prospect", limit="2",
                 research="ai-web")
    assert first.status_code == 303 and query(first)["research"] == "ai-web"
    [item] = outreach.items(root)
    assert item.research_level == "ai-web" and any(f.source == NEWS for f in item.findings)
    web_calls = [c for c in fake.of("research") if c["tools"] == enrich.WEB_ONLY]
    assert len(web_calls) == 1


def test_the_select_is_off_with_the_reason_when_the_cli_cannot_be_restricted(client, root):
    fake = FakeAI()
    client.app.state.enricher = Enricher(provider="codex", which=ALL, runner=fake)
    page = client.get("/outreach").text
    assert "be limited to web search only" in page and "Claude Code only" in page
    refused = post(client, "/outreach/build", where="stage=prospect", research="ai-web")
    assert "can't be limited" in query(refused)["flash"]
    assert fake.calls == [] and outreach.items(root) == []


def test_the_default_level_comes_from_the_config(client, root):
    client.app.state.config["outreach_research"] = "ai-web"
    page = client.get("/outreach").text
    assert 'value="ai-web" selected' in page
    response = post(client, "/outreach/build", where="stage=prospect")
    assert [i.research_level for i in outreach.items(root)] == ["ai-web"] \
        or "flash" in query(response)
