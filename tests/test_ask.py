"""Ask Hermit (page first, then the whole CRM), model tiers, theme and the sidebar."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import ask as asking
from hermitcrm.datafolder import init_folder
from hermitcrm.enrich import EnrichError, Enricher
from hermitcrm.store import load_config
from hermitcrm.web import create_app, safe_page

ALL = lambda binary: f"/usr/local/bin/{binary}"  # noqa: E731


class ScriptedRunner:
    """Replies in order; records prompt, schema and keyword arguments."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        return self.replies.pop(0)


def enricher(*replies) -> Enricher:
    return Enricher(provider="claude", which=ALL, runner=ScriptedRunner(*replies))


# ------------------------------------------------------------------ module


def test_page_text_keeps_content_and_drops_chrome():
    html = """<html><head><style>x{}</style></head><body>
      <nav><a href="/">Pipeline</a></nav><header class="topbar">Ask Hermit</header>
      <main><h1>Acme GmbH</h1><table><tr><th>stage</th><td>qualified</td></tr></table>
      <form><select name="outcome"><option>lost</option><option selected>unsuccessful</option></select><input name="title" value="CTO">
      <input type="hidden" name="csrf_token" value="secret"><button>Save</button></form>
      <script>alert(1)</script><p>Next step: call &amp; demo</p></main>
      <footer>v1</footer></body></html>"""
    text = asking.page_text(html)
    assert "Acme GmbH" in text and "qualified" in text and "call & demo" in text
    assert "[title: CTO]" in text and "[outcome: unsuccessful]" in text
    for gone in ("Pipeline", "Ask Hermit", "lost", "secret", "Save", "alert", "v1"):
        assert gone not in text, gone
    assert asking.page_text("<p>" + "x" * 50 + "</p>", limit=10).endswith("cut off here]")


def test_answer_from_page_does_not_search_the_crm(tmp_path):
    e = enricher({"answerable": True, "answer": "Acme is **qualified**."})
    answer = asking.ask(e, " What stage is Acme? ", "/companies/acme",
                        "<main><h1>Acme</h1></main>", tmp_path)
    assert (answer.scope, answer.text, answer.model) == ("page", "Acme is **qualified**.",
                                                        "claude-opus-5")
    (call,) = e.runner.calls
    assert call["tools"] == "" and "cwd" not in call
    assert "What stage is Acme?" in call["prompt"] and "Acme" in call["prompt"]


def test_falls_back_to_the_whole_crm_read_only(tmp_path):
    e = enricher({"answerable": False, "answer": ""},
                 {"answer": "Three companies.", "sources": ["PIPELINE.md", ""]})
    answer = asking.ask(e, "How many are qualified?", "/", "<main>board</main>", tmp_path)
    assert answer.scope == "crm" and answer.sources == ["PIPELINE.md"]
    first, second = e.runner.calls
    assert second["cwd"] == str(tmp_path) and second["tools"] == asking.CRM_TOOLS
    assert "Edit" not in second["tools"] and "Write" not in second["tools"]
    assert second["extra_path"] and "CLAUDE.md" in second["prompt"]


def test_scope_crm_skips_the_page_step_and_errors(tmp_path):
    e = enricher({"answer": "x", "sources": []})
    assert asking.ask(e, "q", "/", "", tmp_path, scope="crm").scope == "crm"
    assert len(e.runner.calls) == 1
    with pytest.raises(EnrichError, match="question"):
        asking.ask(enricher(), "   ", "/", "", tmp_path)
    with pytest.raises(EnrichError, match="empty answer"):
        asking.ask(enricher({"answer": " ", "sources": []}), "q", "/", "", tmp_path,
                   scope="crm")
    none = Enricher(provider="claude", which=lambda b: None)
    with pytest.raises(EnrichError, match="not found|no AI CLI"):
        asking.ask(none, "q", "/", "", tmp_path)


def test_safe_page():
    assert safe_page("/companies/acme?tab=x") == "/companies/acme?tab=x"
    for bad in ("https://evil.example", "//evil.example", "/ask", "/static/style.css", ""):
        assert safe_page(bad) == "/"


# --------------------------------------------------------------------- web


@pytest.fixture
def app_client(tmp_path: Path):
    folder = init_folder(tmp_path / "demo", demo=True)
    config = {**load_config(folder), "push_enabled": False, "owner_email": "me@example.com"}
    app = create_app(folder, config)
    app.state.calendar_url = lambda refresh=False: ""
    app.state.enricher = Enricher(provider="claude", which=ALL, runner=ScriptedRunner())
    return app, TestClient(app, follow_redirects=False)


def test_every_page_has_sidebar_icons_and_ask_box(app_client):
    app, client = app_client
    page = client.get("/companies").text
    sidebar = page.split("</nav>")[0]
    assert 'class="sidebar"' in sidebar and sidebar.count('class="icon"') >= 8
    assert 'class="active" aria-current="page"' in sidebar
    assert 'data-theme="light"' in page
    assert 'action="/ask"' in page and 'name="page" value="/companies"' in page


def test_ask_route_uses_the_rendered_page_then_offers_retry(app_client):
    app, client = app_client
    slug = next(iter(app.state.store.companies))
    runner = ScriptedRunner({"answerable": True, "answer": "It is **fine**."})
    app.state.enricher = Enricher(provider="claude", which=ALL, runner=runner)
    token = app.state.csrf_token
    r = client.post("/ask", data={"csrf_token": token, "question": "Status?",
                                  "page": f"/companies/{slug}"})
    assert r.status_code == 200
    assert "<strong>fine</strong>" in r.text and "Answered from this page" in r.text
    assert "Retry with Fable" in r.text and "Search the whole CRM instead" in r.text
    name = app.state.store.companies[slug].name
    assert name in runner.calls[0]["prompt"]

    runner.replies.append({"answer": "Deeper.", "sources": []})
    r = client.post("/ask", data={"csrf_token": token, "question": "Status?", "tier": "strong",
                                  "scope": "crm", "page": f"/companies/{slug}"})
    assert "Searched the whole CRM" in r.text and "Retry with" not in r.text
    assert client.post("/ask", data={"question": "x"}).status_code == 403


def test_ask_route_shows_errors(app_client):
    app, client = app_client
    token = app.state.csrf_token
    r = client.post("/ask", data={"csrf_token": token, "question": " ", "page": "/"})
    assert r.status_code == 400 and "Type a question" in r.text
    assert client.get("/ask?page=/reports").status_code == 200


def test_theme_setting_and_ai_tier_switch(app_client):
    app, client = app_client
    token = app.state.csrf_token
    page = client.get("/settings").text
    assert 'id="appearance"' in page and "Night mode" in page
    assert "Medium: Opus" in page and "Strong: Fable" in page
    r = client.post("/settings/appearance", data={"csrf_token": token, "theme": "dark"})
    assert r.status_code == 303 and 'data-theme="dark"' in client.get("/").text
    assert client.post("/settings/appearance",
                       data={"csrf_token": token, "theme": "pink"}).status_code == 400
    r = client.post("/settings/enrichment", data={"csrf_token": token, "provider": "claude",
                                                  "tier": "strong", "timeout": "60"})
    assert r.status_code == 303
    assert app.state.config["ai_tier"] == "strong"


def test_enrich_preview_offers_retry_with_strong(app_client):
    app, client = app_client
    slug = next(s for s, c in app.state.store.companies.items() if not c.linkedin)
    runner = ScriptedRunner({"linkedin": "https://www.linkedin.com/company/x", "sources": [],
                             "notes": ""})
    app.state.enricher = Enricher(provider="claude", which=ALL, runner=runner)
    r = client.post(f"/companies/{slug}/enrich")
    assert r.status_code == 200 and "Retry with Fable" in r.text
    assert f'action="/companies/{slug}/enrich?tier=strong"' in r.text
