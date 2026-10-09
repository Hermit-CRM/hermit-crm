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

"""Make it yours: the handoff (Python and its JavaScript mirror), the starters,
the hub, undo, pickup without a restart, the entry points and the recipes."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from hermitcrm import adjust, cli, history
from hermitcrm import fields as custom
from hermitcrm import help as helpdocs
from hermitcrm import setup as st
from hermitcrm import welcome
from hermitcrm.datafolder import init_folder
from hermitcrm.store import Store, load_config
from hermitcrm.web import create_app

JS = Path(adjust.__file__).parent / "static" / "adjust.js"
FOLDER = "/Users/jane/My CRM's folder"


# ------------------------------------------------------------------ fixtures


def git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=Agent", "-c", "user.email=agent@example.com",
                           *args], cwd=folder, check=True, capture_output=True,
                          text=True).stdout.strip()


def commit_file(folder: Path, name: str, text: str, message: str) -> str:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(folder, "add", name)
    git(folder, "commit", "-q", "-m", message)
    return git(folder, "rev-parse", "HEAD")


def settle(folder: Path) -> None:
    """Commit what the app wrote on its first start (config, a migration)."""
    if git(folder, "status", "--porcelain", "--untracked-files=no"):
        git(folder, "commit", "-qam", "test: settle")


def make(folder: Path, **extra):
    st.set_config_values(folder / "config.toml", {
        "push_enabled": False, "welcome_dismissed": True,
        "disclaimer_accepted": "2026-09-01T09:00:00", "owner_email": "me@example.com",
        **extra})
    settle(folder)
    app = create_app(folder, load_config(folder))
    app.state.calendar_url = lambda refresh=False: ""
    return app, TestClient(app, follow_redirects=False)


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "demo", demo=True)


@pytest.fixture
def empty(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "empty")


def token(client) -> str:
    return client.app.state.csrf_token


def post_company(client, name: str):
    return client.post("/companies", data={
        "name": name, "website": "", "linkedin": "", "source": "other", "stage": "prospect",
        "lost_reason": "", "value_eur_month": "", "next_step": "", "next_step_due": "",
        "next_step_status": "open", "tags": "", "notes": ""})


# ------------------------------------------------------------------ handoff


def test_which_agent():
    assert adjust.agent_for({}) == "copy"
    assert adjust.agent_for({"adjust_agent": "Cursor"}) == "cursor"
    assert adjust.agent_for({"adjust_agent": "nonsense", "enrich_provider": "codex"}) == "codex"
    assert adjust.agent_for({"enrich_provider": "claude"}) == "claude"
    assert adjust.agent_for({"enrich_provider": "grok"}) == "copy"
    assert adjust.agent_for({"enrich_command": "/opt/homebrew/bin/gemini --x"}) == "gemini"
    assert adjust.agent_for({"enrich_command": "claude"}) == "claude"
    assert adjust.agent_for({"enrich_command": "my-ai --fast"}) == "copy"
    # an explicit choice wins over the Enrich tool
    assert adjust.agent_for({"adjust_agent": "copy", "enrich_provider": "claude"}) == "copy"


def test_the_prompt_per_agent():
    assert adjust.prompt_for("claude", "Add a field.", "Acme", "/companies/acme") == \
        "/hermit Asked on Acme (/companies/acme): Add a field."
    assert adjust.prompt_for("codex", "Add a field.", "Acme", "/companies/acme") == \
        'Run "hermitcrm help adjust" first and follow it. Asked on Acme (/companies/acme): ' \
        "Add a field."
    # the hub has no page: no "Asked on"
    assert adjust.prompt_for("claude", "  Two\nlines  ") == "/hermit Two lines"
    assert adjust.prompt_for("copy", "x") == 'Run "hermitcrm help adjust" first and follow it. x'
    assert adjust.prompt_for("claude", "x", "", "/tasks") == "/hermit Asked on /tasks: x"


def test_links_and_commands_per_agent():
    claude = adjust.handoff("claude", FOLDER, "Make it blue & compact", "Home", "/")
    assert claude["link"].startswith("claude-cli://open?cwd=%2FUsers%2Fjane%2FMy%20CRM's%20folder&q=")
    q = claude["link"].split("&q=", 1)[1]
    assert unquote(q) == claude["prompt"] and "&" not in q
    cursor = adjust.handoff("cursor", FOLDER, "Make it blue")
    assert cursor["link"].startswith("cursor://anysphere.cursor-deeplink/prompt?text=")
    assert unquote(cursor["link"].split("text=", 1)[1]) == cursor["prompt"]
    for agent, tool in (("codex", ["codex"]), ("gemini", ["gemini", "-i"])):
        h = adjust.handoff(agent, FOLDER, "It's $HOME `rm -rf` \"quoted\"")
        assert h["link"] == "" and h["command"]
        # the shell sees exactly two commands: cd <folder> && <tool> <prompt>
        words = shlex.split(h["command"])
        assert words[:3] == ["cd", FOLDER, "&&"] and words[3:-1] == tool
        assert words[-1] == h["prompt"]
    copy = adjust.handoff("copy", FOLDER, "x")
    assert copy["link"] == copy["command"] == "" and copy["prompt"]
    assert adjust.handoff("unknown", FOLDER, "x")["agent"] == "copy"


def request_of(agent: str, size: int, char: str = "a") -> str:
    """A request whose prompt is exactly `size` UTF-8 bytes."""
    base = adjust.byte_size(adjust.prompt_for(agent, ""))
    n, rest = divmod(size - base, len(char.encode()))
    return char * n + "a" * rest


@pytest.mark.parametrize("char", ["a", "é", "€", "😀"])
@pytest.mark.parametrize("agent", ["claude", "cursor"])
def test_the_500_byte_guard(agent, char):
    for size, too_long in ((499, False), (500, False), (501, True)):
        h = adjust.handoff(agent, FOLDER, request_of(agent, size, char))
        assert h["bytes"] == size
        assert h["too_long"] is too_long and bool(h["link"]) is not too_long, (size, char)
    # command and copy agents have no link to guard
    long = adjust.handoff("codex", FOLDER, "x" * 2000)
    assert not long["too_long"] and long["command"]


CASES = [
    ("claude", "Add a [date] field [contract renewal] to [companies].", "Northwind Robotics",
     "/companies/northwind-robotics"),
    ("claude", "  tabs\tand\nnewlines and more  ", "A & B \"quoted\"", "/companies?f_stage=prospect"),
    ("cursor", "Ünïcödé: café, 東京, 😀 (and *stars*) !'~", "Home", "/"),
    ("codex", "It's got 'quotes' and $vars", "Tasks", "/tasks"),
    ("gemini", "plain", "", ""),
    ("copy", "copy me", "Settings", "/settings"),
    ("claude", "é" * 240, "", ""),
    ("claude", "é" * 246, "", ""),
    ("nonsense", "x", "", ""),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_browser_builds_exactly_what_python_builds(tmp_path):
    script = tmp_path / "run.js"
    script.write_text(
        "const a = require(%s);\n"
        "const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
        "console.log(JSON.stringify(cases.map(c => a.handoff(c[0], c[4], c[1], c[2], c[3], 500))));\n"
        % json.dumps(str(JS)))
    cases = [[*c, FOLDER] for c in CASES]
    out = subprocess.run(["node", str(script)], input=json.dumps(cases), capture_output=True,
                         text=True, check=True).stdout
    for case, js in zip(CASES, json.loads(out)):
        assert js == adjust.handoff(case[0], FOLDER, case[1], case[2], case[3]), case


def test_the_script_and_the_module_share_their_constants():
    """Without node the strings at least agree; with it, the test above runs both."""
    text = JS.read_text(encoding="utf-8")
    assert 'Run "hermitcrm help adjust" first and follow it. ' in text
    assert "/hermit " in text and "claude-cli://open?cwd=" in text
    assert "cursor://anysphere.cursor-deeplink/prompt?text=" in text
    assert "\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff" in text
    assert all(ord(ch) < 128 for ch in text.split("(function")[1])  # escapes, not raw spaces


# ---------------------------------------------------------------- starters


@pytest.mark.parametrize("path,kind", [
    ("/", "home"), ("/welcome", "home"), ("/companies", "companies"),
    ("/companies/new", "companies"), ("/companies/acme", "company"),
    ("/companies/acme/contacts/jane-roe", "contact"), ("/companies/acme/contacts/new", "company"),
    ("/contacts", "contacts"), ("/pipeline", "pipeline"), ("/tasks", "tasks"),
    ("/messages", "messages"), ("/reports", "reports"), ("/calendar", "calendar"),
    ("/settings", "settings"), ("/help/cli", "other"), ("/yours", "other"),
])
def test_page_kinds(path, kind):
    assert adjust.page_kind(path) == kind


def test_every_page_kind_gets_three_or_four_starters_that_fit_it():
    for kind in adjust.PAGE_KINDS:
        shown = adjust.starters_for(kind, adjust.DEFAULTS)
        assert 3 <= len(shown) <= 4, kind
        for s in shown:
            starter = adjust.BY_ID[s["id"]]
            assert kind in starter.kinds or (kind not in {k for x in adjust.STARTERS
                                                          for k in x.kinds}), (kind, s["id"])
            assert "{" not in s["text"] and "[" in s["text"]
    families = {s.family for s in adjust.STARTERS}
    assert families == set(adjust.FAMILIES)
    assert len({s.id for s in adjust.STARTERS}) == len(adjust.STARTERS)
    for section, sid in adjust.SETTINGS_STARTERS.items():
        assert sid in adjust.BY_ID, section


def test_starters_speak_the_users_data(demo):
    store = Store(demo)
    store.load()
    defs = custom.load(demo)
    values = adjust.prefill(store, defs, load_config(demo))
    assert values["score"] == "my score"          # their own number field, not "fit"
    countries = [c.country for c in store.companies.values() if c.country and not c.is_sample]
    assert countries.count(values["country"]) == max(countries.count(c) for c in countries)
    assert values["channel"] in ("LinkedIn", "email", "phone")
    monday = adjust.starter("dashboard-monday", values)
    assert "[my score] above [" in monday["text"]
    # an empty folder falls back to the design's own examples
    (demo.parent / "nothing").mkdir()
    empty = Store(demo.parent / "nothing")
    empty.load()
    defaults = adjust.prefill(empty, [], {})
    assert defaults["score"] == "fit" and defaults["country"] == "Germany"
    # the company page offers lookalikes of that company
    company = store.get("northwind-robotics")
    page = adjust.prefill(store, defs, {}, company=company)
    assert page["company_tag"] == company.tags[0]


# --------------------------------------------------------------------- hub


def test_the_hub_on_an_empty_folder(empty):
    app, client = make(empty)
    page = client.get("/yours")
    assert page.status_code == 200
    text = page.text
    assert "<h1>Make Hermit yours</h1>" in text and 'id="describe"' in text
    assert "not named yet" in text and 'href="/settings#enrichment"' in text
    assert "Nothing yet." in text and "No changes yet." in text     # intentional empty states
    assert text.count('class="recipe') == len(adjust.gallery(adjust.DEFAULTS))
    assert "You have no dashboards yet." in text                    # the one suggestion
    assert "Something Hermit can't do yet?" in text
    assert 'class="hub active" aria-current="page"' in text         # the sidebar link


def test_the_hub_on_a_demo_folder(demo):
    app, client = make(demo, adjust_agent="claude")
    text = client.get("/yours").text
    assert "Claude Code" in text and "Open in Claude Code" in text
    assert "my score, FTE estimate, AE count" in text               # what you've built
    assert "companies have a <strong>my score</strong> score" in text
    page = client.get("/yours?starter=look").text
    box = re.search(r'id="describe-request"[^>]*>(.*?)</textarea>', page, re.S).group(1)
    assert box == adjust.starter("look", {})["text"]
    page = client.get("/yours?request=Undo%20commit%20abc1234").text
    assert ">Undo commit abc1234</textarea>" in page
    page = client.get("/yours?family=Routines").text
    cards = re.findall(r'<article class="recipe[^"]*" data-family="([^"]+)"( hidden)?', page)
    assert {f for f, hidden in cards if not hidden} == {"Routines"}
    # the hub's own Adjust tab speaks of Hermit, not of a page
    assert 'data-path=""' in page


def test_a_toml_typo_in_config_is_a_message_not_a_traceback(empty, capsys):
    """config.toml is where an agent puts task types and outcomes. A typo there
    stopped every command with a traceback, `hermitcrm check` too, the very
    command an agent runs to find out what it got wrong."""
    with open(empty / "config.toml", "a", encoding="utf-8") as fh:
        fh.write('\ntask_types = [{name = "call", colour = "blue"\n')
    assert cli.main(["--data", str(empty), "check"]) == 1
    err = capsys.readouterr().err
    assert re.search(r"^config\.toml: line \d+: ", err, re.M) and "Traceback" not in err
    assert cli.main(["--data", str(empty), "digest"]) == 2
    assert "config.toml: line" in capsys.readouterr().err
    assert cli.main(["--data", str(empty), "doctor"]) in (0, 1)   # doctor reports on its own


def test_the_app_works_with_a_toml_typo_in_fields_toml(empty):
    """A fields.toml that is not even TOML raised TOMLDecodeError, which the
    start-up and the pages did not expect (they handle FieldError): the app
    would not start. It starts with no custom fields, every page loads, and the
    hub names the problem."""
    (empty / "fields.toml").write_text("[[field\nkey = ", encoding="utf-8")
    with pytest.raises(custom.FieldError, match="fields.toml: is not valid TOML"):
        custom.load(empty)
    app, client = make(empty)
    assert app.state.custom_fields == []
    for path in ("/", "/companies", "/contacts", "/pipeline", "/settings", "/yours", "/welcome"):
        assert client.get(path).status_code in (200, 303), path
    assert "fields.toml: line 1:" in client.get("/yours").text
    assert any(p.startswith("fields.toml: line 1:") for p in adjust.all_problems(empty))


def test_messages_with_languages_that_is_not_a_table_never_reach_the_pages(demo):
    """`languages = 3` merged fine and then failed every page that writes a
    draft (a 500 on each company and contact). It is refused like a TOML error:
    the app keeps the wording it has, and check says why."""
    app, client = make(demo)
    assert client.get("/companies/northwind-robotics").status_code == 200
    shipped = app.state.messages
    (demo / "messages.toml").write_text("languages = 3\n", encoding="utf-8")
    assert client.get("/companies/northwind-robotics").status_code == 200   # picked up, refused
    assert client.get("/companies/northwind-robotics/contacts/lena-vogt").status_code == 200
    assert app.state.messages == shipped
    assert "messages.toml: languages: must be a table of languages" in "\n".join(
        adjust.all_problems(demo))
    (demo / "messages.toml").write_text("[languages]\nen = 3\n", encoding="utf-8")
    assert client.get("/companies/northwind-robotics").status_code == 200
    assert any(p.startswith("messages.toml: languages:") for p in adjust.all_problems(demo))
    # and at start-up
    app2, client2 = make(demo)
    assert client2.get("/companies/northwind-robotics").status_code == 200
    assert app2.state.messages == adjust.messaging.default_messages()


def test_the_app_starts_with_a_broken_messages_file(empty):
    """messages.toml was read once at start-up without a guard, so one typo from
    an agent kept the app from starting at all, with a traceback. It starts on
    the shipped wording, and the hub and `check` say what is wrong."""
    (empty / "messages.toml").write_text("[[template\n", encoding="utf-8")
    app, client = make(empty)
    assert client.get("/").status_code in (200, 303)
    page = client.get("/yours")
    assert page.status_code == 200
    assert "messages.toml" in page.text and 'id="problems"' in page.text
    assert client.get("/companies").status_code == 200
    assert any(p.startswith("messages.toml") for p in adjust.all_problems(empty))
    assert app.state.messages == adjust.messaging.default_messages()


def test_every_suggestion_opens_a_starter_that_exists(demo, monkeypatch):
    """The hub's "Suggested for you" button links to a starter by id; an id with
    no starter opened the hub with an empty box (the unknown-outcomes rule did)."""
    store = Store(demo)
    store.load()
    company_class = type(next(iter(store.companies.values())))
    monkeypatch.setattr(company_class, "message_status", lambda self, *args: "unknown")
    values = adjust.prefill(store, custom.load(demo), load_config(demo))
    found = adjust.suggestions(store, custom.load(demo), load_config(demo), values,
                               store.today(), 14, ["replied", "no reply"], limit=10)
    assert any("outcome **unknown**" in s["text"] for s in found)     # the rule fired
    assert found
    for suggestion in found:
        assert adjust.starter(suggestion["starter"], values), suggestion


def test_recent_changes_lists_the_right_commits(empty):
    app, client = make(empty)
    commit_file(empty, "fields.toml", '[[field]]\nkey = "segment"\n', "settings: field segment added")
    commit_file(empty, "notes.txt", "x", "ai: adjust: a note")
    commit_file(empty, "companies/x/company.md", "x", "bulk: tag 3 companies")
    commit_file(empty, "routines.toml", "", "routine: nudge: drafted 2")
    commit_file(empty, "companies/y/company.md", "y", "company: y created")
    commit_file(empty, "dashboards/monday.toml", 'title = "Monday"\n', "dashboards: monday")
    st.set_config_values(empty / "config.toml", {"silent_days": 30})
    git(empty, "commit", "-qam", "settings: silent_days 14 -> 30")
    st.set_config_values(empty / "config.toml", {"theme": "dark"})
    git(empty, "commit", "-qam", "settings: theme light -> dark")
    subjects = [c.subject for c in history.recent_changes(empty)]
    assert subjects == ["settings: silent_days 14 -> 30", "dashboards: monday",
                        "routine: nudge: drafted 2", "bulk: tag 3 companies",
                        "ai: adjust: a note", "settings: field segment added"]
    bulk = next(c for c in history.recent_changes(empty) if c.subject.startswith("bulk:"))
    assert bulk.touched == "1 company" and bulk.can_undo
    page = client.get("/yours").text
    assert page.count('action="/yours/undo"') == 6 and "company: y created" not in page
    assert history.when_text(__import__("datetime").datetime(2026, 10, 1, 9),
                             __import__("datetime").datetime(2026, 10, 3, 9)) == "1 Oct"


# --------------------------------------------------------------------- undo


def test_undo_from_the_cli(empty, capsys):
    settle(empty)
    sha = commit_file(empty, "theme.css", ":root { --accent: blue; }\n", "ai: adjust: blue")
    assert cli.main(["--data", str(empty), "undo", sha[:7]]) == 0
    out = capsys.readouterr().out
    assert "Undone in a new commit" in out and 'Revert "ai: adjust: blue"' in out
    assert not (empty / "theme.css").exists()
    assert git(empty, "log", "-1", "--format=%s") == 'Revert "ai: adjust: blue"'
    assert f"This reverts commit {sha}." in git(empty, "log", "-1", "--format=%b")
    new = re.search(r"commit ([0-9a-f]{7})", out).group(1)
    # undoing the undo brings it back; undoing the same commit twice is refused
    assert cli.main(["--data", str(empty), "undo", new]) == 0
    assert (empty / "theme.css").exists()
    assert cli.main(["--data", str(empty), "undo", "deadbeef"]) == 1
    assert "no commit deadbeef" in capsys.readouterr().err


def test_undo_refuses_merges_dirty_folders_and_the_first_commit(empty, capsys):
    settle(empty)
    first = git(empty, "rev-list", "--max-parents=0", "HEAD")
    store = Store(empty)
    with pytest.raises(history.UndoError, match="first commit"):
        history.undo(store, first)
    with pytest.raises(history.UndoError, match="not a commit id"):
        history.undo(store, "HEAD; rm -rf /")
    git(empty, "checkout", "-q", "-b", "side")
    commit_file(empty, "layout.toml", "[company]\n", "ai: adjust: layout")
    git(empty, "checkout", "-q", "main")
    theme = commit_file(empty, "theme.css", ":root {}\n", "ai: adjust: theme")
    git(empty, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    merge = git(empty, "rev-parse", "HEAD")
    with pytest.raises(history.UndoError, match="merge"):
        history.undo(store, merge)
    assert all(c.can_undo != (c.sha == merge) or not c.merge
               for c in history.recent_changes(empty))
    # uncommitted changes to a tracked file: refused, nothing touched
    (empty / "theme.css").write_text(":root { --accent: red; }\n")
    head = git(empty, "rev-parse", "HEAD")
    assert cli.main(["--data", str(empty), "undo", theme[:7]]) == 1
    assert "not committed yet: theme.css" in capsys.readouterr().err
    assert git(empty, "rev-parse", "HEAD") == head
    assert (empty / "theme.css").read_text() == ":root { --accent: red; }\n"


def test_a_conflicting_undo_is_aborted_and_handed_to_the_agent(empty):
    app, client = make(empty)
    first = commit_file(empty, "theme.css", ":root { --accent: blue; }\n", "ai: adjust: blue")
    commit_file(empty, "theme.css", ":root { --accent: green; }\n", "ai: adjust: green")
    head = git(empty, "rev-parse", "HEAD")
    with pytest.raises(history.UndoError) as caught:
        history.undo(app.state.store, first)
    assert "Later changes touched the same lines" in str(caught.value)
    assert f"Ask your agent: undo commit {first[:7]} (ai: adjust: blue)" in str(caught.value)
    assert git(empty, "rev-parse", "HEAD") == head
    assert not git(empty, "status", "--porcelain")                  # exactly as it was
    assert not (empty / ".git" / "REVERT_HEAD").exists()
    r = client.post("/yours/undo", data={"csrf_token": token(client), "sha": first})
    assert r.status_code == 303
    location = unquote(r.headers["location"])
    assert location.startswith(f"/yours?request=Undo commit {first[:7]} (ai: adjust: blue)")
    assert location.endswith("#describe")


def test_undo_from_the_hub_reloads_and_regenerates_the_pipeline(demo):
    app, client = make(demo)
    csrf = token(client)
    assert post_company(client, "First Undo Co").status_code == 303
    created = git(demo, "rev-parse", "HEAD")
    assert post_company(client, "Second Co").status_code == 303
    assert "First Undo Co" in (demo / "PIPELINE.md").read_text()
    # no CSRF token, no undo
    assert client.post("/yours/undo", data={"sha": created}).status_code == 403
    r = client.post("/yours/undo", data={"csrf_token": csrf, "sha": created})
    assert r.status_code == 303 and "undo=1" in r.headers["location"]
    assert "Undone in a new commit" in unquote(r.headers["location"])
    assert "first-undo-co" not in app.state.store.companies          # reloaded
    assert "Second Co" in client.get("/companies").text
    pipeline = (demo / "PIPELINE.md").read_text()
    assert "First Undo Co" not in pipeline and "Second Co" in pipeline
    assert not git(demo, "status", "--porcelain")
    page = client.get(r.headers["location"]).text
    assert '<p class="flash">Undone in a new commit' in page.split('id="changes"')[1]
    r = client.post("/yours/undo", data={"csrf_token": csrf, "sha": "0000000"})
    assert "no commit 0000000" in unquote(r.headers["location"])


# ------------------------------------------------------------------ pickup


def test_edits_on_disk_show_without_a_restart(demo):
    app, client = make(demo)
    assert "ghosted" not in client.get("/messages").text
    st.set_config_values(demo / "config.toml", {"outcomes": ["replied", "ghosted"]})
    assert "ghosted" in client.get("/messages").text                # config.toml
    assert app.state.store.outcomes == ["replied", "ghosted"]
    (demo / "messages.toml").write_text('[signals]\ngrowing = "Booming right now"\n')
    assert "Booming right now" in client.get("/companies/northwind-robotics").text
    with open(demo / "fields.toml", "a") as fh:
        fh.write('\n[[field]]\nkey = "renewal_month"\nlabel = "renewal month"\n')
    assert "renewal month" in client.get("/companies/northwind-robotics").text
    # a file that no longer parses keeps what the app had, and check names it
    (demo / "messages.toml").write_text("[signals\n")
    assert client.get("/companies/northwind-robotics").status_code == 200
    assert "Booming right now" in client.get("/companies/northwind-robotics").text
    assert any(p.startswith("messages.toml: line 1:") for p in adjust.validate(demo))


def test_a_commit_made_outside_the_app_reloads_the_index(demo):
    app, client = make(demo)
    assert "Outside Co" not in client.get("/companies").text
    assert cli.main(["--data", str(demo), "add", "company", "Outside Co"]) == 0
    assert "Outside Co" in client.get("/companies").text


def test_reload_rereads_messages_and_fields(demo):
    app, client = make(demo)
    (demo / "messages.toml").write_text('[signals]\ngrowing = "Up and up"\n')
    app.state.messages = {}  # pretend the stat missed it
    client.post("/reload")
    assert app.state.messages["signals"]["growing"] == "Up and up"


# --------------------------------------------------------- the entry points


def test_ask_adjust_on_every_page(demo):
    app, client = make(demo, adjust_agent="claude")
    page = client.get("/companies/northwind-robotics").text
    assert "Ask &middot; Adjust" in page and 'data-tour="ask"' in page
    assert 'action="/ask"' in page and 'name="page" value="/companies/northwind-robotics"' in page
    panel = page.split('id="adjust-form"')[1].split("</details>")[0]
    assert 'data-page-title="Northwind Robotics"' in panel
    assert 'data-path="/companies/northwind-robotics"' in panel
    assert panel.count('class="starter"') == 4 and 'href="/yours"' in panel
    assert "Nothing opened? Run <code>claude</code> once in a terminal, then try again." in panel
    assert '<script src="/static/adjust.js' in page
    # the flash is not part of the page the agent hears about
    page = client.get("/companies?flash=Saved&f_stage=prospect").text
    assert 'data-path="/companies?f_stage=prospect"' in page
    # the sidebar: the Yours group above Settings, then the pins
    sidebar = page.split("</nav>")[0]
    assert sidebar.index("Make it yours") < sidebar.index('data-tour="settings"')
    assert 'class="nav-group"' in sidebar and 'class="nav-gap"' in sidebar


def test_pinned_items_come_from_the_yours_pins_global(demo):
    (demo / "dashboards" / "monday-review.toml").unlink()  # the sample's, pinned
    app, client = make(demo)
    sidebar = client.get("/pipeline").text.split("</nav>")[0]
    assert "Monday review" not in sidebar                            # the default: none
    # the dashboards module registers the real one under the same name
    app.state.templates.env.globals["yours_pins"] = lambda: [
        {"title": "Monday review", "url": "/d/monday-review"}]
    sidebar = client.get("/pipeline").text.split("</nav>")[0]
    pin = sidebar.split('href="/d/monday-review"')[1]
    assert sidebar.index("Make it yours") < sidebar.index("Monday review") \
        < sidebar.index('data-tour="settings"')
    assert "<span>Monday review</span>" in pin.split("</a>")[0]


def test_settings_entry_points_and_the_agent_choice(demo):
    app, client = make(demo)
    page = client.get("/settings").text
    general = page.split('id="tab-general"')[1].split('<div class="settings-group"')[0]
    assert general.index('id="make-it-yours"') < general.index('id="you"')
    assert 'href="/yours"' in general and 'action="/settings/adjust-agent"' in general
    for section, starter in adjust.SETTINGS_STARTERS.items():
        head = page.split(f'id="{section}"')[1].split("</div>")[0]
        assert f'href="/yours?starter={starter}#describe">or describe it' in head, section
    r = client.post("/settings/adjust-agent", data={"csrf_token": token(client),
                                                   "agent": "codex"})
    assert r.status_code == 303 and "Codex" in unquote(r.headers["location"])
    assert load_config(demo)["adjust_agent"] == "codex"
    assert git(demo, "log", "-1", "--format=%s").startswith("settings: ")
    hub = client.get("/yours").text
    assert "Copy command" in hub and 'data-agent="codex"' in hub
    assert client.post("/settings/adjust-agent", data={"csrf_token": token(client),
                                                       "agent": "skynet"}).status_code == 400
    assert client.post("/settings/adjust-agent", data={"agent": "claude"}).status_code == 403


def test_reports_help_and_home_lead_to_the_hub(demo):
    app, client = make(demo)
    assert 'href="/yours?starter=dashboard-report#describe">Describe it</a>' in \
        client.get("/reports").text
    index = client.get("/help").text.split('<article class="helpdoc">')[1]
    assert index.index('href="/help/adjust"') < index.index('href="/help/pipeline"')
    assert helpdocs.topic_for("/yours") == "adjust"
    assert 'href="/help/adjust"' in client.get("/yours").text.split("</nav>")[0]


def test_the_welcome_step_ticks_itself(demo):
    app, client = make(demo, welcome_dismissed=False)
    step = client.get("/welcome").text.split('id="yours"')[1].split("</li>")[0]
    assert "&#10003;" not in step and 'href="/yours?starter=look#describe"' in step
    commit_file(demo, "notes/x.md", "x", "ai: adjust: something small")
    step = client.get("/welcome").text.split('id="yours"')[1].split("</li>")[0]
    assert "&#10003;" in step
    store = Store(demo)
    store.load()
    keys = {s.key: s.done for s in welcome.steps(store, {}, {}, False)}
    assert keys["yours"] is False                                    # the default
    assert adjust.has_adjusted(demo)
    plain = init_folder(demo.parent / "plain")
    assert not adjust.has_adjusted(plain)
    (plain / "dashboards").mkdir()
    (plain / "dashboards" / "m.toml").write_text("")
    assert adjust.has_adjusted(plain)


# ------------------------------------------------------------- validation


def test_check_names_problems_in_the_files_an_agent_writes(demo, capsys):
    (demo / "fields.toml").write_text('[[field]]\nkey = "renewal"\ntype = "dat"\n')
    (demo / "theme.css").write_text(":root {\n  --acent: blue;\n  --my-own: 1px;\n}\n"
                                    "@import url(x.css);\n")
    (demo / "messages.toml").write_text('[languages.en]\nhook = "{observation} {segmnt}"\n')
    st.set_config_values(demo / "config.toml", {
        "task_types": [{"name": "call", "colour": "bleu"}], "adjust_agent": "claud",
        "silent_dayz": 3})
    problems = adjust.validate(demo)
    expected = [
        "config.toml: silent_dayz: not a setting Hermit reads (did you mean silent_days?)",
        "config.toml: adjust_agent: 'claud' is not one of claude, cursor, codex, gemini, copy "
        "(did you mean claude?)",
        "config.toml: task_types entry 1: colour 'bleu' is not one of green, blue, amber, red, "
        "violet, grey (did you mean blue?)",
        "fields.toml: renewal: type must be one of text, number, date, select (did you mean date?)",
        "theme.css: line 5: @import loads another file; the app blocks it",
        "theme.css: line 2: --acent is not a token the app uses (did you mean --accent?)",
    ]
    for line in expected:
        assert line in problems, (line, problems)
    assert any(p.startswith("messages.toml: languages.en: {segmnt}") for p in problems)
    assert not any("--my-own" in p for p in problems)               # own variables are fine
    assert cli.main(["--data", str(demo), "check"]) == 1
    out = capsys.readouterr().out
    assert "fields.toml: renewal:" in out and "theme.css: line 2:" in out
    # the hub shows the same lines as a banner
    app = create_app(demo, {**load_config(demo), "push_enabled": False})
    page = TestClient(app).get("/yours").text
    assert 'id="problems"' in page and "--acent is not a token" in page


def test_check_is_quiet_on_good_files(demo, capsys):
    (demo / "theme.css").write_text(":root { --accent: light-dark(#1a4fd6, #7ea6ff); }\n")
    (demo / "messages.toml").write_text('[languages.en]\nsignoff = "Best,\\n{owner_first_name}"\n')
    st.set_config_values(demo / "config.toml", {
        "task_types": [{"name": "call", "colour": "green"}, "demo"],
        "outcomes": ["replied", "no reply"], "silent_days": 21, "adjust_agent": "cursor"})
    assert adjust.validate(demo) == []
    assert cli.main(["--data", str(demo), "check"]) == 0
    assert capsys.readouterr().out.startswith("OK:")


def test_built_items_and_the_providers_list(demo):
    (demo / "theme.css").write_text(":root {}\n")
    (demo / "messages.toml").write_text('[languages.de]\nsignoff = "Gruß"\n')
    (demo / "layout.toml").write_text("[company]\n")
    kinds = [i["kind"] for i in adjust.all_built(demo)]
    # the demo also has the sample account's dashboard and routine
    assert kinds == ["fields", "look", "messages", "dashboard", "layout", "routine"]
    for item in adjust.all_built(demo):
        assert set(item) == {"kind", "title", "url", "detail", "adjust"}
    # the layout row is the layout module's own; a provider that fails costs
    # only its own rows
    assert [i["detail"] for i in adjust.all_built(demo) if i["kind"] == "layout"] == [
        "layout.toml changes nothing yet"]
    adjust.BUILT_PROVIDERS.append(lambda root: 1 / 0)
    try:
        items = adjust.all_built(demo)
    finally:
        del adjust.BUILT_PROVIDERS[-1]
    assert [i["kind"] for i in items] == kinds


# ------------------------------------------------------------------ recipes


@pytest.mark.parametrize("topic", ["adjust", "adjust-fields", "adjust-look", "adjust-messages",
                                   "adjust-connect", "adjust-feature"])
def test_recipes_render_and_print(demo, topic, capsys):
    app, client = make(demo)
    page = client.get(f"/help/{topic}")
    assert page.status_code == 200 and "<h1>Make it yours" in page.text
    assert cli.main(["help", topic]) == 0
    assert capsys.readouterr().out == helpdocs.read(topic)


def test_look_recipe_example_is_valid_and_moves_every_sidebar_colour(tmp_path):
    """A \"cooler\" look that leaves --sidebar-active alone shows a beige menu
    item on a blue-grey page, so the recipe lists those tokens and the example
    changes them. Its tokens must be real ones and its CSS must pass check."""
    text = helpdocs.read("adjust-look")
    tokens = adjust.shipped_tokens()
    listed = set(re.findall(r"^\| `(--[a-z0-9-]+)` \|", text, re.M))
    assert {"--sidebar", "--sidebar-hover", "--sidebar-active"} <= listed <= tokens
    css = re.search(r"```css\n(.*?)```", text, re.S).group(1)
    assert {"--sidebar", "--sidebar-hover", "--sidebar-active"} <= set(
        re.findall(r"^\s*(--[a-z0-9-]+):", css, re.M))
    (tmp_path / "theme.css").write_text(css, encoding="utf-8")
    assert adjust.validate_theme(tmp_path) == []


def test_feature_recipe_does_not_hand_a_generator_to_the_template_row():
    """"I want a quote generator" is the hub's own example of something Hermit
    cannot do. The recipe once sent every quote to a MESSAGING.md template, and
    the agent built that unasked; now a template covers the wording only, and a
    partial cover is asked about before anything is written."""
    text = helpdocs.read("adjust-feature")
    assert "The wording of a quote" in text and "| A quote, a proposal" not in text
    assert "ask before you\nbuild the partial version" in text
    assert "change nothing in the data folder until they say yes" in text


def test_the_rules_page_covers_every_recipe():
    text = helpdocs.read("adjust")
    for topic in ("adjust-fields", "adjust-look", "adjust-messages", "adjust-connect",
                  "adjust-feature", "adjust-dashboards", "adjust-layout", "adjust-bulk",
                  "adjust-routines", "adjust-stages"):
        assert f"`hermitcrm help {topic}`" in text, topic
    for rule in ("hermitcrm check", "ai: adjust:", "hermitcrm undo", "dry run",
                 ".secrets.toml", "PIPELINE.md", "Send anything"):
        assert rule in text, rule
    assert "hermitcrm help adjust" in helpdocs.read("ai-agents")


# ----------------------------------------- a file that reads but cannot be used


def test_a_wrong_typed_setting_keeps_the_old_settings_and_shows_a_banner(demo):
    app, client = make(demo)
    assert client.get("/").status_code == 200
    for line in ("outcomes = 5", 'followup_nudge_days = "soon"'):
        with open(demo / "config.toml", "a") as fh:
            fh.write(f"\n{line}\n")
        for path in ("/", "/reports", "/messages", "/yours"):
            page = client.get(path)
            assert page.status_code == 200, (line, path)
            assert 'class="warning-box file-problems"' in page.text, (line, path)
            assert "config.toml" in page.text.split("file-problems")[1].split("</div>")[0]
        # the app keeps what it had, and the bad value never reaches the config
        assert app.state.config.get("outcomes") != 5
        assert app.state.config.get("followup_nudge_days") != "soon"
        assert app.state.store.outcomes != [] and "ghosted" not in app.state.store.outcomes
        (demo / "config.toml").write_text(
            (demo / "config.toml").read_text().replace(f"\n{line}\n", "\n"))
        settle(demo)
        page = client.get("/")
        assert page.status_code == 200 and "file-problems" not in page.text, line


def test_a_bad_config_is_read_once_not_on_every_request(demo, monkeypatch):
    app, client = make(demo)
    with open(demo / "config.toml", "a") as fh:
        fh.write("\noutcomes = 5\n")
    seen = []
    real = adjust.validate_config
    monkeypatch.setattr(adjust, "validate_config", lambda root: seen.append(1) or real(root))
    for _ in range(3):
        assert client.get("/reports").status_code == 200
    assert len(seen) == 1


def test_a_wrong_shaped_messages_file_keeps_the_old_wording_and_shows_a_banner(demo):
    app, client = make(demo)
    (demo / "messages.toml").write_text('[signals]\ngrowing = "Booming right now"\n')
    assert "Booming right now" in client.get("/companies/northwind-robotics").text
    (demo / "messages.toml").write_text("languages = 5\n")
    page = client.get("/companies/northwind-robotics")
    assert page.status_code == 200
    assert "Booming right now" in page.text                          # the last good wording
    assert 'class="warning-box file-problems"' in page.text and "messages.toml" in page.text
    assert isinstance(app.state.messages["languages"], dict)
    (demo / "messages.toml").write_text('[signals]\ngrowing = "Up and up"\n')
    page = client.get("/companies/northwind-robotics")
    assert "Up and up" in page.text and "file-problems" not in page.text


def test_a_typo_in_config_is_shown_but_does_not_stop_the_rest_loading(demo):
    app, client = make(demo)
    st.set_config_values(demo / "config.toml", {"silent_dayz": 3, "outcomes": ["replied", "ghosted"]})
    page = client.get("/messages")
    assert "ghosted" in page.text and "silent_dayz" in page.text
    assert 'class="warning-box file-problems"' in page.text


def test_check_prints_the_problem_instead_of_a_traceback(demo, capsys):
    with open(demo / "config.toml", "a") as fh:
        fh.write("\noutcomes = 5\n")
    assert cli.main(["--data", str(demo), "check"]) == 1
    out = capsys.readouterr().out
    assert "config.toml: outcomes: must be a list" in out and "Traceback" not in out
    with open(demo / "config.toml", "a") as fh:
        fh.write("silent_days = [\n")
    assert cli.main(["--data", str(demo), "check"]) == 1
    # a file that does not parse stops every command alike, on stderr
    assert capsys.readouterr().err.startswith("config.toml: ")


# ------------------------------------------------- the suggestions' starters


def test_every_suggestion_opens_a_starter_that_exists_and_says_what_it_promises(
        empty, tmp_path):
    import inspect
    # whatever the code can suggest, not only what this folder happens to produce
    source = inspect.getsource(adjust.suggestions)
    named = set(re.findall(r'"starter": "([\w-]+)"', source))
    assert named and named <= set(adjust.BY_ID), named - set(adjust.BY_ID)
    # a folder that produces the "outcome unknown" suggestion
    store = Store(empty)
    store.load()
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe")
    when = store.now().strftime("%Y-%m-%dT10:00")
    for n in range(6):
        store.create_interaction("acme", channel="linkedin", direction="out",
                                 contact="jane-doe", date=when, body=f"Hi {n}")
    found = adjust.suggestions(store, [], {}, adjust.DEFAULTS, store.today(), 14,
                               ["replied", "no reply"], limit=10)
    assert {s["starter"] for s in found} >= {"dashboard-messages"}
    for s in found:
        card = adjust.starter(s["starter"], adjust.DEFAULTS)
        assert card and card["text"].strip(), s
        assert "weekly" not in (s["text"] + s["action"]).lower(), s    # routines run daily
    # and the hub's link for each one shows a request in the box
    app, client = make(empty)
    for s in found:
        page = client.get(f"/yours?starter={s['starter']}").text
        box = re.search(r'id="describe-request"[^>]*>(.*?)</textarea>', page, re.S).group(1)
        assert box.strip(), s


def test_no_starter_or_suggestion_text_calls_a_routine_weekly():
    for s in adjust.STARTERS:
        if s.family == "Routines":
            assert "weekly" not in (s.text + s.title).lower(), s.id


# ----------------------------------- which config.toml keys an agent may write


def test_every_list_of_agent_writable_config_keys_names_the_same_three(demo):
    from hermitcrm import mcp
    from hermitcrm.datafolder import AGENT_ADJUST_RULES
    three = ("task_types", "outcomes", "silent_days")
    assert adjust.AGENT_CONFIG_KEYS == mcp.CONFIG_KEYS == three
    rules = " ".join(AGENT_ADJUST_RULES.split())
    assert "the task_types, outcomes and silent_days keys of config.toml" in rules
    recipe = " ".join(helpdocs.read("adjust").split())
    assert "in `config.toml`, only the keys `task_types`, `outcomes` and `silent_days`" in recipe
    assert "In `config.toml`: `task_types`, `outcomes`, `silent_days` only." in helpdocs.read(
        "adjust-fields")
    for text in (rules, recipe, helpdocs.read("adjust-fields")):
        assert "message_window_days" not in text
    assert "message_window_days" not in adjust.AGENT_CONFIG_KEYS
    # `check` still names a wrong value for the user's own keys, stays quiet
    # about the user's other keys, and still helps with a typo of them
    st.set_config_values(demo / "config.toml", {
        "owner_name": "Jane Roe", "theme": "dark", "port": 9000, "message_window_days": 30})
    assert adjust.validate_config(demo) == []
    st.set_config_values(demo / "config.toml", {"message_window_days": 0})
    assert adjust.validate_config(demo) == [
        "config.toml: message_window_days: must be a whole number of days, 1 or more"]
    st.set_config_values(demo / "config.toml", {"message_window_days": 30, "message_windw_days": 7})
    assert adjust.validate_config(demo) == [
        "config.toml: message_windw_days: not a setting Hermit reads "
        "(did you mean message_window_days?)"]
