"""Enrichment proposals and CLI providers via fakes; nothing here shells out."""

import json
import subprocess
from pathlib import Path

import pytest

from hermitcrm import cli as crm
from hermitcrm.enrich import (
    COMPANY_FIELDS, EnrichError, Enricher, Proposal, extract_json, model_label,
    resolve_provider,
)


class FakeRunner:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, prompt, schema):
        self.calls.append((prompt, schema))
        return self.reply


def on_path(*names):
    return lambda binary: f"/usr/local/bin/{binary}" if binary in names else None


ALL = on_path("claude", "codex", "gemini", "grok", "my-llm", "claude-cli",
              "definitely-not-a-command-xyz")


def test_company_proposal_asks_only_for_missing_fields(store):
    store.create_company("Acme", website="https://acme.de", product_oneliner="Does X.")
    runner = FakeRunner({"linkedin": "https://www.linkedin.com/company/acme",
                         "country": "de", "fte_estimate": " ~25 ", "ae_count": "3",
                         "sources": ["https://acme.de/about"], "notes": "high confidence"})
    proposal = Enricher(runner=runner).propose_company(store.get("acme"))
    prompt, schema = runner.calls[0]
    assert proposal.missing == ["linkedin", "country", "fte_estimate", "ae_count"]
    assert set(schema["properties"]) == {"linkedin", "country", "fte_estimate",
                                         "ae_count", "sources", "notes"}
    assert "website" not in schema["properties"]
    assert "- name: Acme" in prompt and "- website: https://acme.de" in prompt
    assert proposal.fields == {"linkedin": "https://www.linkedin.com/company/acme",
                               "country": "DE", "fte_estimate": "~25", "ae_count": 3}
    assert proposal.sources == ["https://acme.de/about"]
    assert proposal.notes == "high confidence"


def test_proposal_drops_unusable_values(store):
    store.create_company("Acme")
    runner = FakeRunner({"website": None, "linkedin": "", "country": "France",
                         "fte_estimate": None, "ae_count": "many",
                         "product_oneliner": "Sells  things.", "sources": [], "notes": ""})
    proposal = Enricher(runner=runner).propose_company(store.get("acme"))
    assert proposal.fields == {"product_oneliner": "Sells things."}
    assert proposal.missing == list(COMPANY_FIELDS)


def test_nothing_missing_means_no_cli_call(store):
    store.create_company("Acme", website="https://acme.de", linkedin="https://l/acme",
                         country="DE", fte_estimate="10", ae_count=1,
                         product_oneliner="X.")
    runner = FakeRunner({})
    proposal = Enricher(runner=runner).propose_company(store.get("acme"))
    assert proposal.missing == [] and runner.calls == []


def test_contact_proposal(store):
    store.create_company("Acme", website="https://acme.de")
    store.create_contact("acme", "Jane", "Doe", linkedin="https://www.linkedin.com/in/jd")
    runner = FakeRunner({"title": "CEO", "sources": [], "notes": ""})
    company = store.get("acme")
    proposal = Enricher(runner=runner).propose_contact(company, company.contacts["jane-doe"])
    prompt, schema = runner.calls[0]
    assert proposal.missing == ["title"] and proposal.fields == {"title": "CEO"}
    assert "- name: Jane Doe" in prompt and "- company: Acme" in prompt
    assert list(schema["properties"]) == ["title", "sources", "notes"]


# ------------------------------------------------------------ transport


class FakeRun:
    """Stands in for subprocess.run; optionally writes the codex output file."""

    def __init__(self, stdout="", out_file_text=None, returncode=0, stderr=""):
        self.stdout, self.out_file_text = stdout, out_file_text
        self.returncode, self.stderr = returncode, stderr
        self.seen = {}

    def __call__(self, argv, **kwargs):
        self.seen.update(argv=list(argv), **kwargs)
        if "--output-schema" in argv:
            schema_file = Path(argv[argv.index("--output-schema") + 1])
            self.seen["schema_file"] = schema_file
            self.seen["schema"] = json.loads(schema_file.read_text())
        if self.out_file_text is not None:
            out = Path(argv[argv.index("--output-last-message") + 1])
            out.write_text(self.out_file_text)
            self.seen["out_file"] = out
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout,
                                           stderr=self.stderr)


CLAUDE_STDOUT = json.dumps({
    "type": "result", "subtype": "success", "is_error": False, "duration_ms": 41234,
    "num_turns": 4, "result": "Found the website.", "session_id": "3f1c-…",
    "total_cost_usd": 0.41, "structured_output": {"website": "https://acme.de"}})

GEMINI_STDOUT = json.dumps({
    "response": "Here is what I found:\n```json\n{\"website\": \"https://acme.de\", "
                "\"sources\": [\"https://acme.de/impressum\"], \"notes\": \"from {imprint}\"}\n```",
    "stats": {"models": {"gemini-2.5-pro": {"api": {"totalRequests": 3}}},
              "tools": {"totalCalls": 2, "byName": {"google_web_search": {"count": 2}}}}})

GROK_STDOUT = json.dumps([
    {"role": "user", "content": "You are filling gaps…"},
    {"role": "assistant", "content": "Searching…"},
    {"role": "assistant", "content": '{"title": "CTO", "sources": [], "notes": ""}'}])

CODEX_LAST_MESSAGE = '{"linkedin": "https://www.linkedin.com/company/acme", "sources": [], "notes": "ok"}\n'


def test_claude_argv_env_and_structured_output(monkeypatch):
    run = FakeRun(CLAUDE_STDOUT)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    enricher = Enricher(provider="claude", command="claude-cli", model="sonnet",
                        timeout=5, which=ALL)
    assert enricher.available and enricher.provider_name == "claude"
    assert enricher.runner("the prompt", {"type": "object"}) == {"website": "https://acme.de"}
    argv = run.seen["argv"]
    assert argv[0].endswith("claude-cli") and argv[1:3] == ["-p", "--output-format"]
    assert json.loads(argv[argv.index("--json-schema") + 1]) == {"type": "object"}
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--allowedTools") + 1] == "WebSearch,WebFetch"
    assert run.seen["input"] == "the prompt"
    assert "CLAUDECODE" not in run.seen["env"] and "ANTHROPIC_API_KEY" not in run.seen["env"]


def test_claude_without_model_uses_the_medium_default(monkeypatch):
    run = FakeRun(CLAUDE_STDOUT)
    monkeypatch.setattr(subprocess, "run", run)
    Enricher(provider="claude", which=ALL).runner("p", {})
    argv = run.seen["argv"]
    assert argv[0].endswith("/claude") and argv[argv.index("--model") + 1] == "claude-opus-5"


def test_tiers_overrides_and_with_tier(monkeypatch):
    run = FakeRun(CLAUDE_STDOUT)
    monkeypatch.setattr(subprocess, "run", run)
    e = Enricher(provider="claude", which=ALL)
    assert (e.model, e.strong_model) == ("claude-opus-5", "claude-fable-5-1")
    strong = e.with_tier("strong")
    assert strong.model == "claude-fable-5-1" and e.model == "claude-opus-5"
    strong.runner("p", {})
    assert run.seen["argv"][run.seen["argv"].index("--model") + 1] == "claude-fable-5-1"
    assert Enricher(provider="claude", model="x", model_strong="y", tier="strong",
                    which=ALL).model == "y"
    assert Enricher(provider="custom", command="llm", which=ALL).model == ""
    assert model_label("claude-fable-5-1") == "Fable" and model_label("gpt-5") == "gpt-5"


def test_tools_and_cwd_per_call(monkeypatch):
    run = FakeRun(CLAUDE_STDOUT)
    monkeypatch.setattr(subprocess, "run", run)
    Enricher(provider="claude", which=ALL).runner("p", {}, tools="Read,Grep", cwd="/tmp",
                                                   extra_path="/venv/bin")
    argv = run.seen["argv"]
    assert argv[argv.index("--allowedTools") + 1] == "Read,Grep"
    assert run.seen["env"]["PATH"].startswith("/venv/bin")


def test_codex_argv_schema_file_and_output_file(monkeypatch):
    run = FakeRun(stdout="[2026-09-15T10:00:00] codex\nthinking…\n",
                  out_file_text=CODEX_LAST_MESSAGE)
    monkeypatch.setattr(subprocess, "run", run)
    schema = {"type": "object", "properties": {"linkedin": {"type": ["string", "null"]}}}
    data = Enricher(provider="codex", model="gpt-5", which=ALL).runner("the prompt", schema)
    assert data["linkedin"] == "https://www.linkedin.com/company/acme"
    argv = run.seen["argv"]
    assert argv[0].endswith("/codex") and argv[1:3] == ["exec", "--skip-git-repo-check"]
    assert argv[argv.index("-m") + 1] == "gpt-5" and argv[-1] == "-"
    assert run.seen["schema"] == schema and run.seen["input"] == "the prompt"
    # Temp files are gone afterwards.
    assert not run.seen["schema_file"].exists() and not run.seen["out_file"].exists()


def test_codex_empty_output_file_is_an_error(monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRun(stdout="done\n", out_file_text=""))
    with pytest.raises(EnrichError, match="no JSON object"):
        Enricher(provider="codex", which=ALL).runner("p", {})


def test_gemini_argv_prompt_on_stdin_and_response_field(monkeypatch):
    run = FakeRun(GEMINI_STDOUT)
    monkeypatch.setattr(subprocess, "run", run)
    schema = {"type": "object", "properties": {"website": {"type": "string"}}}
    data = Enricher(provider="gemini", model="gemini-2.5-pro", which=ALL).runner(
        "the prompt", schema)
    assert data == {"website": "https://acme.de", "sources": ["https://acme.de/impressum"],
                    "notes": "from {imprint}"}
    argv = run.seen["argv"]
    assert argv[0].endswith("/gemini") and argv[1] == "-p"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("-m") + 1] == "gemini-2.5-pro"
    assert run.seen["input"].startswith("the prompt\nReturn ONLY a JSON object")
    assert json.dumps(schema) in run.seen["input"]


def test_gemini_error_envelope(monkeypatch):
    stdout = json.dumps({"error": {"type": "ApiError", "message": "quota exceeded"}})
    monkeypatch.setattr(subprocess, "run", FakeRun(stdout))
    with pytest.raises(EnrichError, match="quota exceeded"):
        Enricher(provider="gemini", which=ALL).runner("p", {})


def test_grok_prompt_in_argv_and_message_list(monkeypatch):
    run = FakeRun(GROK_STDOUT)
    monkeypatch.setattr(subprocess, "run", run)
    data = Enricher(provider="grok", which=ALL).runner("the prompt", {"type": "object"})
    assert data == {"title": "CTO", "sources": [], "notes": ""}
    argv = run.seen["argv"]
    assert argv[0].endswith("/grok") and argv[1] == "-p" and argv[2].startswith("the prompt\n")
    assert "--output-format" in argv and argv[argv.index("-m") + 1] == "grok-4-fast"
    assert run.seen["input"] is None


def test_grok_plain_text_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRun('Sure! {"title": "CEO"} Hope this helps.'))
    assert Enricher(provider="grok", which=ALL).runner("p", {}) == {"title": "CEO"}


def test_custom_command_substitutes_placeholders(monkeypatch):
    run = FakeRun('{"title": "VP Sales"}')
    monkeypatch.setattr(subprocess, "run", run)
    enricher = Enricher(provider="custom",
                        command="my-llm --schema {schema_file} --model={model} --flag 'two words'",
                        model="big", which=ALL)
    assert enricher.provider_name == "custom"
    assert enricher.runner("the prompt", {"type": "object"}) == {"title": "VP Sales"}
    argv = run.seen["argv"]
    assert argv[0].endswith("/my-llm") and argv[2].endswith("schema.json")
    assert argv[3] == "--model=big" and argv[-1] == "two words"
    assert run.seen["input"] == "the prompt"
    assert not Path(argv[2]).exists()


def test_auto_detection_order_and_unavailable():
    assert resolve_provider("auto", which=on_path("gemini", "grok")).name == "gemini"
    assert resolve_provider("auto", which=ALL).name == "claude"
    assert resolve_provider("auto", which=on_path("grok")).name == "grok"
    assert resolve_provider("auto", which=on_path()) is None
    # An explicit command under auto keeps its provider, or becomes custom.
    found = resolve_provider("auto", command="/opt/bin/codex", which=lambda b: b)
    assert found.name == "codex" and found.binary == "/opt/bin/codex"
    assert resolve_provider("auto", command="my-llm {schema_file}", which=ALL).name == "custom"
    # A named provider that is not installed is unavailable.
    assert resolve_provider("codex", which=on_path("claude")) is None
    assert resolve_provider("custom", which=ALL) is None

    enricher = Enricher(which=on_path())
    assert not enricher.available and enricher.provider_name == ""
    with pytest.raises(EnrichError, match="no AI CLI found"):
        enricher.runner("p", {})
    bad = Enricher(provider="chatgpt", which=ALL)
    assert not bad.available and "unknown enrich_provider" in bad.unavailable_reason()


def test_extract_json_edge_cases():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": {"b": [1, 2]}}\n```') == {"a": {"b": [1, 2]}}
    assert extract_json('Sure, here you go: {"a": "brace } in string \\" quote"} done') == \
        {"a": 'brace } in string " quote'}
    assert extract_json('{not json} then {"ok": true}') == {"ok": True}
    assert extract_json('{"first": 1} {"second": 2}') == {"first": 1}
    for bad in ("", "no json here", "[1, 2, 3]", '{"unterminated": '):
        with pytest.raises(EnrichError, match="no JSON object"):
            extract_json(bad)


def test_cli_runner_error_paths(monkeypatch):
    with pytest.raises(EnrichError, match="not found"):
        Enricher(command="definitely-not-a-command-xyz", timeout=5,
                 which=on_path()).runner("p", {})

    enricher = Enricher(provider="claude", timeout=5, which=ALL)

    def missing(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(EnrichError, match="not found"):
        enricher.runner("p", {})

    monkeypatch.setattr(subprocess, "run", FakeRun("", returncode=1,
                                                   stderr="boom\nnot logged in"))
    with pytest.raises(EnrichError, match="not logged in"):
        enricher.runner("p", {})

    monkeypatch.setattr(subprocess, "run", FakeRun(json.dumps(
        {"is_error": False, "result": '{"title": "CTO"}'})))
    assert enricher.runner("p", {}) == {"title": "CTO"}

    monkeypatch.setattr(subprocess, "run", FakeRun(json.dumps(
        {"is_error": True, "result": "Invalid API key"})))
    with pytest.raises(EnrichError, match="Invalid API key"):
        enricher.runner("p", {})

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 5)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(EnrichError, match="timed out"):
        enricher.runner("p", {})


def test_cli_enrich_reports_unavailable(tmp_path, capsys, monkeypatch):
    import hermitcrm.enrich as enrich
    (tmp_path / "companies").mkdir()
    monkeypatch.setattr(enrich.shutil, "which", lambda binary: None)
    monkeypatch.setattr(enrich, "resolve_provider",
                        lambda p, c, which=None: None)
    assert crm.main(["enrich", "acme"], root=tmp_path) == 1
    assert "enrichment unavailable: no AI CLI found" in capsys.readouterr().out


def test_failed_claude_run_reports_the_envelope_message(monkeypatch):
    stdout = json.dumps({"type": "result", "is_error": True,
                         "result": "API Error: 400 this model needs a newer CLI"})
    monkeypatch.setattr(subprocess, "run", FakeRun(stdout, returncode=1))
    with pytest.raises(EnrichError) as exc:
        Enricher(provider="claude", which=ALL).runner("p", {})
    assert str(exc.value).endswith("API Error: 400 this model needs a newer CLI")
