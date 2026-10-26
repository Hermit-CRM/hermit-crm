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

"""Outreach: a scrape-level build that finds nothing usable escalates to one
ai-web pass (Generate, batch builds, the command line). The AI and the web are
fakes; all names are made up."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import URL, QueryParams

from hermitcrm import cli, enrich, outreach, scrape
from hermitcrm.datafolder import init_folder
from hermitcrm.enrich import Enricher, EnrichError
from hermitcrm.store import Store, load_config
from hermitcrm.web import create_app
from outreach_fakes import ALL, NOW, FakeAI, ai, default_research, fake_page

MARA = "lindenhof-data/mara-keller"
NEWS = "https://news.example.org/lindenhof-opens-office"


def web_answer(prompt):
    if "web search" not in prompt:
        return default_research(prompt)
    return {"findings": [{"text": "Opened an office in Hamburg", "source": NEWS,
                          "kind": "trigger", "confidence": "high", "date": "2026-10-01"}],
            "sources": [NEWS]}


@pytest.fixture
def root(tmp_path):
    return init_folder(tmp_path / "crm", demo=True, now=NOW)


def store_of(root, website_less=("lindenhof-data",)):
    store = Store(root, clock=lambda: NOW)
    store.load()
    for slug in website_less:
        store.update_company(slug, website="")
    return store


def pair(store, slug="lindenhof-data"):
    company = store.get(slug)
    return company, company.contacts["mara-keller"] if slug == "lindenhof-data" \
        else next(iter(company.contacts.values()))


def web_calls(fake):
    return [c for c in fake.of("research") if c["tools"] == enrich.WEB_ONLY]


def escalating(fake, enricher=None, fetcher=fake_page):
    return outreach.researcher_for("scrape", enricher or ai(fake), fetcher=fetcher,
                                   today=NOW.date(), escalate=True)


# ------------------------------------------------------------- the researcher


def test_escalates_when_scrape_has_no_usable_findings(root):
    fake = FakeAI(research=web_answer)
    company, contact = pair(store_of(root))
    out = escalating(fake).research(company, contact)
    assert len(web_calls(fake)) == 1 and out.level == "ai-web"
    assert any(f.source == NEWS for f in out.findings)
    assert any("ai-web research ran" in n for n in out.notes)


def test_no_escalation_when_scrape_found_something(root):
    fake = FakeAI(research=web_answer)
    company, contact = pair(store_of(root, website_less=()))
    out = escalating(fake).research(company, contact)
    assert web_calls(fake) == [] and out.level == "scrape"
    assert any(f.usable and f.source != "crm" for f in out.findings)


def test_the_scrape_is_not_fetched_twice_when_it_escalates(root):
    fake, fetched = FakeAI(research=web_answer), []
    company, contact = pair(store_of(root))
    store = store_of(root)
    store.update_contact("lindenhof-data", "mara-keller", linkedin="https://www.linkedin.com/in/mara-keller")
    company, contact = pair(store)

    def fetcher(url):
        fetched.append(url)
        return fake_page(url)

    escalating(fake, fetcher=fetcher).research(company, contact)
    assert fetched.count("https://www.linkedin.com/in/mara-keller") == 1


def test_no_escalation_when_ai_web_unavailable(root):
    fake = FakeAI(research=web_answer)
    codex = Enricher(provider="codex", which=ALL, runner=fake)
    company, contact = pair(store_of(root))
    out = escalating(fake, enricher=codex).research(company, contact)
    assert fake.calls == [] and out.level == "scrape"
    assert any("ai-web" in n and "can't be limited" in n for n in out.notes)


def test_ai_web_failing_keeps_the_scrape_result_with_a_note(root):
    fake = FakeAI(research=EnrichError("boom"))
    company, contact = pair(store_of(root))
    out = escalating(fake).research(company, contact)
    assert len(web_calls(fake)) == 1
    assert any("ai-web research failed" in n for n in out.notes)


def test_explicit_ai_web_level_unchanged(root):
    got = outreach.researcher_for("ai-web", ai(), escalate=True)
    assert type(got) is outreach.AiWebResearcher


def test_escalate_false_keeps_scrape_only(root):
    assert type(outreach.researcher_for("scrape", ai())) is outreach.ScrapeResearcher


def test_a_batch_escalates_only_the_companies_with_nothing(root):
    fake = FakeAI(research=web_answer)
    store = store_of(root, website_less=("lindenhof-data", "kestrel-metrics"))
    researcher = escalating(fake)
    levels = {}
    for slug in ("lindenhof-data", "kestrel-metrics", "saltmarsh-labs"):
        company, contact = pair(store, slug)
        levels[slug] = researcher.research(company, contact).level
    assert levels == {"lindenhof-data": "ai-web", "kestrel-metrics": "ai-web",
                      "saltmarsh-labs": "scrape"}
    assert len(web_calls(fake)) == 2


# ------------------------------------------------------------- the pages


@pytest.fixture
def fake():
    return FakeAI(research=web_answer)


@pytest.fixture
def client(root, fake):
    store_of(root, website_less=("lindenhof-data", "kestrel-metrics", "saltmarsh-labs",
                                 "tallpine-software"))
    app = create_app(root, {**load_config(root), "push_enabled": False,
                            "owner_name": "Sam Example"})
    app.state.setup_redirected = True
    app.state.enricher = ai(fake)
    app.state.outreach_fetcher = fake_page
    app.state.store.clock = lambda: NOW
    return TestClient(app, follow_redirects=False)


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.app.state.csrf_token, **data})


def test_generate_button_escalates(client, root, fake):
    response = post(client, "/outreach/build", contact=MARA, where="stage=prospect",
                    limit="1", research="scrape")
    assert response.status_code == 303
    [item] = outreach.items(root)
    assert item.research_level == "ai-web" and any(f.source == NEWS for f in item.findings)
    assert len(web_calls(fake)) == 1


def test_batch_build_escalates(client, root, fake):
    post(client, "/outreach/build", where="stage=prospect", limit="1", research="scrape")
    [item] = outreach.items(root)
    assert item.research_level == "ai-web"
    assert len(web_calls(fake)) == 1


def test_the_panel_says_it_escalates(client):
    assert "scrape, then ai-web automatically if it finds nothing" in client.get(f"/outreach?contact={MARA}").text


def test_cli_build_escalates(root, monkeypatch, capsys):
    store_of(root, website_less=("lindenhof-data",))
    fake = FakeAI(research=web_answer)
    monkeypatch.setattr(outreach, "default_enricher", lambda config, tier="medium": ai(fake))
    monkeypatch.setattr(scrape, "fetch", lambda url, timeout=10: fake_page(url))
    code = cli.main(["outreach", "build", "--contact", MARA], root=root)
    assert code == 0, capsys.readouterr().err
    [item] = outreach.items(root)
    assert item.research_level == "ai-web"
    assert len(web_calls(fake)) == 1
