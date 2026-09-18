"""hermitcrm/help: the Markdown pages, the converter, the topic mapping, the /help
routes and `hermitcrm help`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import cli
from hermitcrm import help as helpdocs
from hermitcrm.datafolder import AGENT_RULES, init_folder
from hermitcrm.store import load_config
from hermitcrm.web import create_app


# ------------------------------------------------------------------ the pages


def test_every_topic_has_a_page_with_summary_and_related_line():
    for topic in helpdocs.topics():
        text = helpdocs.read(topic)
        assert text, topic
        assert text.startswith("# "), topic
        assert helpdocs.summary_of(text), f"{topic} has no one-line summary"
        assert re.search(r"^Related: .*\]\(/help/[a-z-]+\)", text, re.M), f"{topic}: no Related line"
        for link in re.findall(r"\]\(/help/([a-z-]+)\)", text):
            assert link in helpdocs.topics(), f"{topic} links to unknown topic {link}"


def test_folder_and_topic_list_agree_and_index_links_every_topic():
    on_disk = sorted(p.stem for p in helpdocs.HERE.glob("*.md"))
    assert on_disk == sorted(helpdocs.topics())
    index = helpdocs.read("index")
    for topic in helpdocs.topics():
        if topic != "index":
            assert f"(/help/{topic})" in index, topic
    assert helpdocs.read("nope") is None and helpdocs.read("../store") is None


def test_agent_rules_point_at_help():
    assert "`hermitcrm help <topic>` (topics: `hermitcrm help`)" in AGENT_RULES


# --------------------------------------------------------------- the converter


def test_render_blocks_and_inline():
    md = ("# Title\n\nA para with `code`, **bold** and a [link](/help/cli) "
          "plus <b>tags</b>.\ncontinued line\n\n## Sub\n\n- one\n- two\n  more\n\n"
          "1. first\n2. second\n\n```\nx = \"<y>\"\n```\n\n| a | b |\n|---|---|\n| 1 | `2` |\n")
    html = helpdocs.render(md)
    assert "<h1>Title</h1>" in html and "<h2>Sub</h2>" in html
    assert ("<p>A para with <code>code</code>, <strong>bold</strong> and a "
            '<a href="/help/cli">link</a> plus &lt;b&gt;tags&lt;/b&gt;. continued line</p>') in html
    assert "<ul><li>one</li><li>two more</li></ul>" in html
    assert "<ol><li>first</li><li>second</li></ol>" in html
    assert "<pre><code>x = &quot;&lt;y&gt;&quot;</code></pre>" in html
    assert "<table><thead><tr><th>a</th><th>b</th></tr></thead>" in html
    assert "<tr><td>1</td><td><code>2</code></td></tr>" in html


def test_render_escapes_and_refuses_unsafe_links():
    html = helpdocs.render("[x](javascript:alert(1)) and `**not bold**` <script>")
    assert "javascript:" not in html or 'href="javascript' not in html
    assert "<code>**not bold**</code>" in html
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert helpdocs.title_of("intro\n# The title\n") == "The title"
    assert helpdocs.summary_of("# T\n\nFirst line.\nSecond.\n") == "First line."


# ------------------------------------------------------------- topic mapping


@pytest.mark.parametrize("path,topic", [
    ("/", "pipeline"), ("/today", "pipeline"),
    ("/calendar", "calendar"), ("/calendar?month=2026-09", "calendar"),
    ("/companies", "companies"), ("/companies/new", "companies"),
    ("/companies/acme", "companies"), ("/companies/acme/", "companies"),
    ("/companies/acme/contacts/new", "contacts"),
    ("/companies/acme/contacts/jane-doe", "contacts"),
    ("/contacts", "contacts"),
    ("/companies/acme/interactions/new", "interactions"),
    ("/companies/acme/interactions/2026-09-14T1030-call-out-company/edit", "interactions"),
    ("/messages", "messages"), ("/reports", "reports"),
    ("/settings", "settings"), ("/setup", "settings"), ("/inbox", "settings"),
    ("/import", "import"), ("/import/preview", "import"),
    ("/extension", "extension"), ("/extension/new", "extension"),
    ("/capture", "extension"), ("/capture/new", "extension"),  # the old path
    ("/companies/acme/enrich", "enrich"), ("/companies/acme/enrich/apply", "enrich"),
    ("/companies/acme/fetch", "enrich"),
    ("/companies/acme/contacts/jane-doe/enrich", "enrich"),
    ("/companies/acme/merge", "merge"), ("/companies/acme/contacts/jane-doe/merge", "merge"),
    ("/help", "index"), ("/help/cli", "index"), ("/health", "index"),
])
def test_topic_for(path, topic):
    assert helpdocs.topic_for(path) == topic


# ------------------------------------------------------------------ the routes


@pytest.fixture
def client(tmp_path: Path):
    folder = init_folder(tmp_path / "demo", demo=True)
    config = {**load_config(folder), "push_enabled": False, "owner_email": "me@example.com"}
    app = create_app(folder, config)
    app.state.calendar_url = lambda refresh=False: ""
    return TestClient(app, follow_redirects=False)


def test_help_routes(client):
    r = client.get("/help")
    assert r.status_code == 200 and "<h1>Hermit CRM help</h1>" in r.text
    assert 'href="/help/pipeline"' in r.text
    r = client.get("/help/data-format")
    assert r.status_code == 200 and "<h1>Data format</h1>" in r.text
    assert "<table>" in r.text and "<td>stage_history</td>" in r.text
    assert 'class="current"><a href="/help/data-format">' in r.text
    assert "hermitcrm help data-format" in r.text
    r = client.get("/help/extension")
    assert r.status_code == 200 and "<h1>Extension</h1>" in r.text
    assert client.get("/help/nope").status_code == 404
    assert client.get("/help/..%2Fstore").status_code == 404


def test_every_page_links_to_its_help_topic(client):
    slug = next(iter(client.app.state.store.companies))
    for path, topic in [("/", "pipeline"), ("/calendar", "calendar"),
                        ("/companies", "companies"), (f"/companies/{slug}", "companies"),
                        ("/contacts", "contacts"), ("/messages", "messages"),
                        ("/reports", "reports"), ("/settings", "settings"),
                        ("/import", "import"), ("/extension", "extension"),
                        (f"/companies/{slug}/interactions/new", "interactions")]:
        nav = client.get(path).text.split("</nav>")[0]
        assert f'href="/help/{topic}"' in nav, path


# --------------------------------------------------------------------- CLI


def test_cli_help_prints_index_topic_and_errors(capsys):
    assert cli.main(["help"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Hermit CRM help") and "Topics: index, pipeline," in out
    assert cli.main(["help", "cli"]) == 0
    out = capsys.readouterr().out
    assert out == helpdocs.read("cli")
    assert cli.main(["help", "nope"]) == 2
    err = capsys.readouterr().err
    assert "unknown help topic 'nope'" in err and "settings" in err


def test_cli_help_needs_no_data_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HERMITCRM_DATA", raising=False)
    assert cli.main(["help", "ai-agents"]) == 0
