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

"""Ask Hermit (CRM index first, then the whole CRM), model tiers, theme and the sidebar."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from conftest import FIXED_NOW

from hermitcrm import ask as asking
from hermitcrm.datafolder import init_folder
from hermitcrm.enrich import EnrichError, Enricher
from hermitcrm.store import Store, load_config
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


def test_scope_deep_goes_straight_to_the_walk_and_errors(tmp_path):
    e = enricher({"answer": "x", "sources": []})
    assert asking.ask(e, "q", "/", "", tmp_path, scope="deep").scope == "crm"
    assert len(e.runner.calls) == 1
    with pytest.raises(EnrichError, match="question"):
        asking.ask(enricher(), "   ", "/", "", tmp_path)
    with pytest.raises(EnrichError, match="empty answer"):
        asking.ask(enricher({"answer": " ", "sources": []}), "q", "/", "", tmp_path,
                   scope="deep")
    none = Enricher(provider="claude", which=lambda b: None)
    with pytest.raises(EnrichError, match="not found|no AI CLI"):
        asking.ask(none, "q", "/", "", tmp_path)


# ------------------------------------------------------------- CRM index


@pytest.fixture
def crm(store):
    """Fictional CRM, clock frozen at 2026-09-14: five people over four companies."""
    store.create_company("Acme Ltd", stage="engaged")
    store.create_contact("acme", "Jane", "Doe")
    store.create_contact("acme", "Tom", "Roe")
    store.create_company("Bolt Inc", stage="disqualified", lost_reason="no budget")
    store.create_contact("bolt", "Ann", "Lee")
    store.create_company("Cedar Co", stage="temp-disqualified", requalify_on="2027-01-01",
                         lost_reason="later")
    store.create_company("Dune BV")                      # no contacts at all
    store.create_interaction("acme", "email", "out", contact="jane-doe",
                             date="2026-09-12T09:00")
    store.create_interaction("acme", "note", "", contact="tom-roe",
                             date="2026-09-13T09:00", body="met at a fair")
    store.create_interaction("acme", "call", "in", date="2026-09-10T09:00")
    store.create_interaction("bolt", "meeting", "out", contact="ann-lee",
                             date="2026-08-01T09:00")
    store.add_task("acme", "send the offer", due="2026-09-30", contact="jane-doe")
    store.add_task("bolt", "chase invoice", due="2026-09-01", contact="ann-lee")
    store.add_task("acme", "someday", due=None)
    return store


def index_rows(text: str) -> dict[str, str]:
    rows = [line for line in text.splitlines() if line.startswith("| [") or "(no contacts)" in line]
    # keyed by the person's name, or by the company's for a row without contacts
    return {(line.split("]")[0].lstrip("| [") if "(no contacts)" not in line
             else line.split("[")[1].split("]")[0]): line for line in rows}


def test_crm_index_has_exact_links_stage_roles_and_dates(crm):
    text = asking.crm_index(crm)
    assert text.startswith("Today: 2026-09-14")
    rows = index_rows(text)
    jane = rows["Jane Doe"]
    assert "[Jane Doe](/companies/acme/contacts/jane-doe)" in jane
    assert "[Acme Ltd](/companies/acme)" in jane
    assert "engaged (open)" in jane and "2026-09-12 email out (2d)" in jane
    assert "same" in jane and jane.rstrip().endswith("| 2 |")            # days since touch
    assert "2026-09-10 call in (4d)" in jane                             # company-level touch
    assert "2026-09-30: send the offer" in jane
    assert "disqualified (closed)" in rows["Ann Lee"]
    assert "temp-disqualified (parked)" in rows["Cedar Co"]
    assert rows["Dune BV"].startswith("| (no contacts) | [Dune BV](/companies/dune) |")
    assert rows["Dune BV"].split(" | ")[3:5] == ["none", "none"]      # nothing logged is not "same"


def test_crm_index_sorts_newest_first_and_counts_notes_as_logged_not_touch(crm):
    text = asking.crm_index(crm)
    order = [name for name in ("Tom Roe", "Jane Doe", "Ann Lee") if name in text]
    assert sorted(order, key=text.index) == ["Tom Roe", "Jane Doe", "Ann Lee"]
    tom = index_rows(text)["Tom Roe"]
    assert "| none |" in tom and "2026-09-13 note (1d)" in tom        # logged, not a touch
    assert tom.rstrip().endswith("| - |")


def test_crm_index_next_task_is_none_future_overdue_or_undated(crm):
    rows = index_rows(asking.crm_index(crm))
    assert "2026-09-01 overdue: chase invoice" in rows["Ann Lee"]
    assert "2026-09-30: send the offer" in rows["Jane Doe"] and "overdue" not in rows["Jane Doe"]
    assert "open, no date: someday" in rows["Tom Roe"]       # company-level task counts for everyone
    assert rows["Dune BV"].split(" | ")[-2] == "none"


def test_crm_index_is_capped_with_a_left_out_line(crm, monkeypatch):
    monkeypatch.setattr(asking, "INDEX_LIMIT", 1200)
    text = asking.crm_index(crm)
    assert len(text) <= 1300 and "older rows left out]" in text
    assert "Jane Doe" in text                     # newest rows stay, oldest go
    monkeypatch.undo()
    assert "left out" not in asking.crm_index(crm)


def test_ask_auto_is_one_call_without_tools_that_holds_index_and_question(crm, tmp_path):
    e = enricher({"answerable": True,
                  "answer": "See [Jane Doe](/companies/acme/contacts/jane-doe)."})
    answer = asking.ask(e, "Who did I write recently?", "/pipeline",
                        '<main><a href="/tasks">Tasks board</a></main>', tmp_path, store=crm)
    assert answer.scope == "index" and answer.seconds >= 0
    (call,) = e.runner.calls
    assert call["tools"] == "" and "cwd" not in call
    prompt = call["prompt"]
    assert "Who did I write recently?" in prompt and "--- CRM index ---" in prompt
    assert "[Jane Doe](/companies/acme/contacts/jane-doe)" in prompt
    assert "Tasks board (/tasks)" in prompt and "Never link to files" not in prompt
    assert "never link to files" in prompt


def test_ask_scope_crm_leaves_the_page_out_of_the_index_call(crm, tmp_path):
    e = enricher({"answerable": True, "answer": "ok"})
    asking.ask(e, "q", "/pipeline", "<main>PAGEWORDS</main>", tmp_path, scope="crm", store=crm)
    assert "PAGEWORDS" not in e.runner.calls[0]["prompt"]


def test_index_not_answerable_falls_back_to_the_walk_with_repaired_links(crm, tmp_path):
    e = enricher({"answerable": False, "answer": ""},
                 {"answer": "[Jane](companies/acme/contacts/jane-doe.md) and [Bolt](bolt)",
                  "sources": ["x"]})
    answer = asking.ask(e, "What did the notes say?", "/", "", tmp_path, store=crm)
    first, second = e.runner.calls
    assert first["tools"] == "" and second["tools"] == asking.CRM_TOOLS
    assert answer.scope == "crm"
    assert answer.text == ("[Jane](/companies/acme/contacts/jane-doe) and "
                           "[Bolt](/companies/bolt)")
    assert "/companies/<company-slug>/contacts/<contact-slug>" in second["prompt"]


def test_fix_links(crm):
    known = asking.link_lookup(crm)
    fix = lambda md: asking.fix_links(md, known)  # noqa: E731
    good = "[Jane](/companies/acme/contacts/jane-doe)"
    assert fix(good) == good
    assert fix("[J](companies/acme/contacts/jane-doe.md)") == good.replace("Jane", "J")
    assert fix("[Acme](companies/acme/company.md)") == "[Acme](/companies/acme)"
    assert fix("[Acme](companies/acme/)") == "[Acme](/companies/acme)"
    assert fix("[Jane](jane-doe)") == good
    assert fix("[Jane](/contacts/jane)") == "Jane"                       # invented: plain text
    assert fix("[x](#top) [y](javascript:void) [z](//evil.example)") == "x y z"
    assert fix("[Site](https://example.com/a)") == "[Site](https://example.com/a)"
    assert fix("[Mail](mailto:a@example.com)") == "[Mail](mailto:a@example.com)"
    assert fix("`[a](/nope)` and [b](/nope)") == "`[a](/nope)` and b"
    assert fix("```\n[a](/nope)\n```") == "```\n[a](/nope)\n```"
    assert fix(good + "?x=1") == good + "?x=1"


def test_a_link_the_page_itself_showed_survives(crm, tmp_path):
    e = enricher({"answerable": True, "answer": "[Tasks](/tasks?status=open)"})
    answer = asking.ask(e, "q", "/", '<main><a href="/tasks?status=open">Tasks</a></main>',
                        tmp_path, store=crm)
    assert answer.text == "[Tasks](/tasks?status=open)"


def test_page_text_keeps_internal_links_and_drops_the_rest():
    html = """<main><a href="/companies/acme/contacts/jane">Jane Doe</a>
      <a href="#top">Top</a> <a href="/static/x.css">css</a> <a href="/ask?page=/">Ask</a>
      <a href="https://example.com/p">Out</a> <a href="/empty"></a>
      <nav><a href="/pipeline">Pipeline</a></nav></main>"""
    text = asking.page_text(html)
    assert "Jane Doe (/companies/acme/contacts/jane)" in text
    for gone in ("(#top)", "/static", "/ask", "example.com", "/empty", "/pipeline"):
        assert gone not in text, gone
    assert "Top" in text and "Out" in text


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
    assert "<strong>fine</strong>" in r.text and "Answered from the CRM index" in r.text
    assert "Retry with Fable" in r.text and "Search every file instead" in r.text
    assert "Sonnet" in r.text and 'data-busy="Asking' in r.text   # Ask's own model, and a spinner
    name = app.state.store.companies[slug].name
    assert name in runner.calls[0]["prompt"]

    runner.replies.append({"answer": "Deeper.", "sources": []})
    r = client.post("/ask", data={"csrf_token": token, "question": "Status?", "tier": "strong",
                                  "scope": "deep", "page": f"/companies/{slug}"})
    assert "Searched the whole CRM" in r.text and "Retry with" not in r.text
    assert client.post("/ask", data={"question": "x"}).status_code == 403


def test_ask_route_answers_with_working_links(app_client):
    app, client = app_client
    store = app.state.store
    slug = next(s for s, c in store.companies.items() if c.contacts)
    person = next(iter(store.companies[slug].contacts.values()))
    runner = ScriptedRunner({"answerable": True, "answer":
                             f"- [{person.name}](companies/{slug}/contacts/{person.slug}.md)\n"
                             "- [Ghost](/contacts/ghost)"})
    app.state.enricher = Enricher(provider="claude", which=ALL, runner=runner)
    r = client.post("/ask", data={"csrf_token": app.state.csrf_token, "question": "Who?",
                                  "page": "/"})
    link = f'<a href="/companies/{slug}/contacts/{person.slug}">{person.name}</a>'
    assert link in r.text and "Ghost" in r.text and "/contacts/ghost" not in r.text
    assert "CRM index" in r.text and " s</p>" in r.text           # label and elapsed time
    assert client.get(f"/companies/{slug}/contacts/{person.slug}").status_code == 200


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
    assert r.status_code == 303 and 'data-theme="dark"' in client.get("/pipeline").text
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
