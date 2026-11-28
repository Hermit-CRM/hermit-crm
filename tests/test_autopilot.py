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

"""Autopilot (autopilot.py): the switches, the daily sync with a fake AI, the
cap, failures, the brief, and the Settings section. No test calls a real AI."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import autopilot, cli, routines, today
from hermitcrm.datafolder import init_folder
from hermitcrm.enrich import EnrichError, Enricher
from hermitcrm.store import DEFAULT_CONFIG, Store, load_config
from hermitcrm.web import create_app
from conftest import FIXED_NOW

ALL = lambda binary: f"/usr/local/bin/{binary}"  # noqa: E731
NONE = lambda binary: None  # noqa: E731
BASE = {"push_enabled": False, "owner_name": "Sam Example", "owner_email": "me@example.com"}
ALL_ON = {name: True for name in autopilot.SWITCHES}


class FakeAI:
    """The AI CLI: one answer per call (the last repeats); records every call."""

    def __init__(self, *answers):
        self.answers = list(answers) or [good()]
        self.calls = []

    def __call__(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer(prompt) if callable(answer) else answer


def good(body="Hi,\n\nThanks for your note. Here is what you asked for.\n\nSam",
         channel="email", subject="Re: Intro"):
    return {"channel": channel, "subject": subject, "body": body, "skip": ""}


def ai(*answers) -> Enricher:
    return Enricher(provider="claude", which=ALL, runner=FakeAI(*answers))


def git(root: Path, *args) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout


def subjects(root: Path) -> list[str]:
    return git(root, "log", "--format=%s").splitlines()


def at(days_ago: int) -> str:
    return (FIXED_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT10:00")


def config(**switches) -> dict:
    out = dict(BASE)
    if switches:
        out[autopilot.KEY] = switches
    return out


@pytest.fixture
def folder(repo):
    """acme: I wrote on LinkedIn 10 days ago (a quiet thread). beta: they wrote
    3 days ago (a reply owed)."""
    store = Store(repo, clock=lambda: FIXED_NOW)
    store.load()
    store.on_write = cli._writer(store, repo, {"push_enabled": False})
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe", email="jane@acme.example.com")
    store.create_interaction("acme", channel="linkedin", direction="out",
                             contact="jane-doe", date=at(10), body="Hi Jane, shall we talk?")
    store.create_company("Beta BV", country="NL")
    store.create_contact("beta", "Piet", "Jansen", email="piet@beta.example.com")
    store.create_interaction("beta", channel="email", direction="out", contact="piet-jansen",
                             date=at(6), subject="Intro", body="Hello Piet")
    store.create_interaction("beta", channel="email", direction="in", contact="piet-jansen",
                             date=at(3), subject="Re: Intro", body="Send me the prices.")
    assert git(repo, "status", "--porcelain") == ""   # every write committed itself
    return store


class EmptyBox:
    """A mailbox with nothing new, for the BCC import that runs first."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def fetch(self):
        return []

    def mark_read(self, uids):
        pass


def sync(store: Store, cfg: dict, enricher=None):
    cfg = {"bcc_address": "me+bcc@example.com", **cfg}
    return cli.cmd_sync(store, store.root, cfg, apply=True, open_mailbox=lambda: EmptyBox(),
                        resolve=lambda: "", enricher=enricher)


# ------------------------------------------------------------------ settings


def test_every_switch_is_off_by_default_and_not_in_default_config():
    assert autopilot.KEY not in DEFAULT_CONFIG and autopilot.CAP_KEY not in DEFAULT_CONFIG
    assert autopilot.switches({}) == {name: False for name in autopilot.SWITCHES}
    assert autopilot.switches(None) == autopilot.switches(DEFAULT_CONFIG)
    assert not autopilot.enabled(DEFAULT_CONFIG)


def test_only_a_real_true_turns_a_switch_on():
    got = autopilot.switches({"autopilot": {"reply_drafts": "true", "next_steps": 1,
                                            "meeting_briefs": True, "typo": True}})
    assert got == {"reply_drafts": False, "follow_up_drafts": False,
                   "meeting_briefs": True, "next_steps": False}
    assert autopilot.switches({"autopilot": "on"}) == autopilot.switches({})


@pytest.mark.parametrize("raw, cap", [(None, 15), ("x", 15), (True, 15), (3, 3), (-4, 0),
                                      (500, autopilot.MAX_CAP), ("7", 7)])
def test_daily_cap(raw, cap):
    cfg = {} if raw is None else {autopilot.CAP_KEY: raw}
    assert autopilot.daily_cap(cfg) == cap


def test_plan_settings_checks_the_form():
    values, errors = autopilot.plan_settings(["reply_drafts", "next_steps"], "9")
    assert errors == {}
    assert values == {"autopilot": {"reply_drafts": True, "follow_up_drafts": False,
                                    "meeting_briefs": False, "next_steps": True},
                      "autopilot_daily_cap": 9}
    assert autopilot.plan_settings([], "")[0]["autopilot_daily_cap"] == 15
    assert set(autopilot.plan_settings(["send_everything"], "0")[1]) == {
        "autopilot", "autopilot_daily_cap"}


# ---------------------------------------------------- the privacy line: no AI


@pytest.fixture
def no_ai(monkeypatch):
    """Every way to the AI CLI, recorded: the transport itself, and the enricher
    routines and autopilot build when none is passed in."""
    calls = []

    def transport(self, prompt, schema, **kwargs):
        calls.append(prompt)
        raise AssertionError("an AI call was made")

    monkeypatch.setattr(Enricher, "_run_cli", transport)
    real = routines.default_enricher

    def default(cfg):
        enricher = real(cfg)
        enricher.runner = lambda prompt, schema, **kw: transport(enricher, prompt, schema)
        return enricher

    monkeypatch.setattr(routines, "default_enricher", default)
    return calls


@pytest.mark.parametrize("cfg", [config(), config(**{n: False for n in autopilot.SWITCHES})],
                         ids=["no autopilot key", "every switch false"])
def test_with_the_switches_off_a_sync_makes_no_ai_call(folder, no_ai, cfg):
    text, code = sync(folder, cfg)  # no enricher passed: the real default path
    assert code == 0
    assert no_ai == []
    assert "autopilot" not in text and "== Routines ==" not in text
    assert not autopilot.path(folder.root).exists()
    assert not routines.drafts(folder.root)


def test_the_demo_folder_with_switches_off_makes_no_ai_call(tmp_path, no_ai):
    root = init_folder(tmp_path / "demo", demo=True)
    store = Store(root)
    store.load()
    cfg = load_config(root)
    assert autopilot.KEY not in (root / "config.toml").read_text(encoding="utf-8")
    text, code = sync(store, cfg)
    assert no_ai == [] and "autopilot" not in text


def test_switches_off_leave_the_users_routines_exactly_as_before(folder):
    (folder.root / "routines.toml").write_text(
        '[[routine]]\nname = "reply-drafts"\naction = "draft"\nselect = "replies_owed"\n'
        'paused = false\nprompt = "Reply."\n', encoding="utf-8")
    fake = ai(good())
    lines = routines.run_all(folder, config(), apply=True, enricher=fake)
    assert lines[0] == "reply-drafts: 1 draft"
    assert not any("autopilot" in line for line in lines)
    assert len(fake.runner.calls) == 1


# ------------------------------------------------------------- switched on


def test_reply_and_follow_up_drafts_after_the_sync(folder):
    fake = ai(good(), good(channel="linkedin", subject="", body="Hi Jane, any news?\n"))
    text, code = sync(folder, config(reply_drafts=True, follow_up_drafts=True), fake)
    assert code == 0
    assert "== Routines ==\nautopilot: reply drafts: 1 draft\n  drafted: Piet Jansen" in text
    assert "autopilot: follow-up drafts: 1 draft\n  drafted: Jane Doe (Acme GmbH)" in text
    made = {d.routine: d for d in routines.drafts(folder.root)}
    assert set(made) == {autopilot.REPLY_ROUTINE, autopilot.FOLLOW_UP_ROUTINE}
    assert made[autopilot.REPLY_ROUTINE].company == "beta"
    assert subjects(folder.root)[0] == "autopilot: 2 drafts"
    calls = fake.runner.calls
    assert [c["tools"] for c in calls] == ["", ""]       # no tools, ever
    assert all(c["schema"] is routines.DRAFT_SCHEMA for c in calls)
    assert autopilot.REPLY_PROMPT in calls[0]["prompt"]
    state = autopilot.read_state(folder.root)
    assert state["made"] == 2 and state["day"] == FIXED_NOW.date().isoformat()
    assert state["last_run"]["ok"] is True and autopilot.failure(folder.root) == ""


def test_prepared_drafts_are_on_today(folder):
    sync(folder, config(reply_drafts=True), ai(good()))
    queue = today.build(folder, config(), FIXED_NOW.date())
    draft = next(i for i in queue.items if i.kind == today.DRAFT)
    assert draft.company.slug == "beta"
    assert "from Autopilot: reply drafts" in draft.reason
    assert "Re: Intro" not in draft.reason


def test_a_second_sync_does_not_draft_the_same_thread_again(folder):
    fake = ai(good())
    sync(folder, config(reply_drafts=True), fake)
    text, _ = sync(folder, config(reply_drafts=True), fake)
    assert len(fake.runner.calls) == 1
    assert "autopilot: nothing to prepare" in text


def test_no_second_draft_next_to_the_users_own_routine(folder):
    (folder.root / "routines.toml").write_text(
        '[[routine]]\nname = "reply-drafts"\naction = "draft"\nselect = "replies_owed"\n'
        'paused = false\nprompt = "Reply."\n', encoding="utf-8")
    fake = ai(good())
    text, _ = sync(folder, config(reply_drafts=True), fake)
    assert [d.routine for d in routines.drafts(folder.root)] == ["reply-drafts"]
    assert len(fake.runner.calls) == 1
    assert text.index("reply-drafts: 1 draft") < text.index("autopilot")


def test_the_daily_cap_stops_a_runaway(folder):
    fake = ai(good())
    cfg = {**config(reply_drafts=True, follow_up_drafts=True), autopilot.CAP_KEY: 1}
    text, _ = sync(folder, cfg, fake)
    assert len(routines.drafts(folder.root)) == 1 and len(fake.runner.calls) == 1
    assert "follow-up drafts: 1 waiting, but today's limit is reached" in text
    # The next day the count starts again.
    later = FIXED_NOW + timedelta(days=1)
    autopilot.run(folder, cfg, apply=True, enricher=fake, now=later)
    assert len(routines.drafts(folder.root)) == 2


def test_a_dry_run_calls_no_ai_and_writes_nothing(folder):
    fake = ai(good())
    lines = autopilot.run(folder, config(**ALL_ON), apply=False, enricher=fake)
    assert "autopilot: reply drafts: would draft for 1 record (dry run, no AI)" in lines
    assert "autopilot: morning brief: would be made (no AI)" in lines
    assert fake.runner.calls == [] and not autopilot.path(folder.root).exists()


def test_the_ai_skipping_one_marks_it_handled(folder):
    fake = ai({"channel": "email", "subject": "", "body": "", "skip": "they asked to stop"})
    text, _ = sync(folder, config(reply_drafts=True), fake)
    assert "skipped Piet Jansen (Beta BV): the AI says they asked to stop" in text
    assert not routines.drafts(folder.root)
    sync(folder, config(reply_drafts=True), fake)
    assert len(fake.runner.calls) == 1


# ------------------------------------------------------------------ failures


def test_no_ai_tool_is_recorded_and_the_sync_goes_on(folder):
    missing = Enricher(provider="claude", which=NONE)
    text, code = sync(folder, config(reply_drafts=True, meeting_briefs=True), missing)
    assert code == 0
    assert "autopilot: reply drafts: failed: 'claude' not found" in text
    assert "autopilot: morning brief:" in text          # the brief still came
    assert autopilot.failure(folder.root).startswith("reply drafts: 'claude' not found")


def test_a_cli_that_cannot_run_without_tools_is_refused(folder):
    gemini = Enricher(provider="gemini", which=ALL, runner=FakeAI(good()))
    sync(folder, config(reply_drafts=True), gemini)
    assert "can't run without tools" in autopilot.failure(folder.root)
    assert gemini.runner.calls == []


def test_every_ai_call_failing_is_a_failure_not_a_skip(folder):
    fake = ai(EnrichError("claude failed: 401 Unauthorized"))
    text, _ = sync(folder, config(reply_drafts=True), fake)
    assert "skipped Piet Jansen (Beta BV): claude failed: 401" in text
    assert autopilot.failure(folder.root) == (
        "reply drafts: the AI tool failed: claude failed: 401 Unauthorized")


def test_a_crash_is_recorded_and_the_next_run_clears_it(folder, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(routines, "ask_ai", boom)
    text, code = sync(folder, config(reply_drafts=True), ai(good()))
    assert code == 0 and "reply drafts: failed: RuntimeError: disk on fire" in text
    assert autopilot.failure(folder.root) == "reply drafts: RuntimeError: disk on fire"
    monkeypatch.undo()
    sync(folder, config(reply_drafts=True), ai(good()))
    assert autopilot.failure(folder.root) == ""


def test_a_damaged_state_file_reads_as_empty(folder):
    autopilot.path(folder.root).write_text("{not json", encoding="utf-8")
    assert autopilot.read_state(folder.root) == {} and autopilot.failure(folder.root) == ""
    sync(folder, config(reply_drafts=True), ai(good()))
    assert autopilot.read_state(folder.root)["made"] == 1


def test_the_state_file_is_under_git_and_never_committed(folder):
    sync(folder, config(reply_drafts=True), ai(good()))
    assert autopilot.path(folder.root) == folder.root / ".git" / autopilot.STATE_FILE
    assert autopilot.path(folder.root).exists()
    status = git(folder.root, "status", "--porcelain").splitlines()
    assert [line for line in status if not line.endswith(" inbox/")] == []  # BCC's own files


# --------------------------------------------------------------------- brief


def test_the_morning_brief_needs_no_ai_and_shows_on_home_and_today(folder):
    fake = ai(good())
    sync(folder, config(meeting_briefs=True), fake)
    assert fake.runner.calls == []
    context = routines.home_context(folder, config())
    brief = next(b for b in context["routine_briefs"] if b["name"] == autopilot.BRIEF_ROUTINE)
    assert brief["title"] == "Autopilot: morning brief"
    assert "1 reply owed" in routines.brief_summary(brief)
    queue = today.build(folder, config(), FIXED_NOW.date())
    assert any(i.key == f"brief-{autopilot.BRIEF_ROUTINE}" for i in queue.items)
    # Tomorrow it is gone until the next run makes a new one.
    assert autopilot.today_brief(folder.root, FIXED_NOW.date() + timedelta(days=1)) is None


# ------------------------------------------------------------ the Settings page


@pytest.fixture
def demo_client(tmp_path):
    root = init_folder(tmp_path / "demo", demo=True)
    cfg = load_config(root)
    cfg["push_enabled"] = False
    app = create_app(root, cfg)
    app.state.setup_platform = "linux"
    app.state.schedule_home = tmp_path / "home"
    app.state.calendar_url = lambda refresh=False: ""
    return root, TestClient(app, follow_redirects=False)


def token(client) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get("/settings").text).group(1)


def test_the_settings_section_follows_ai_and_starts_all_off(demo_client):
    root, client = demo_client
    html = client.get("/settings").text
    section = html[html.index('id="autopilot"'):]
    section = section[:section.index("</section>")]
    between = html[html.index('id="enrichment"'):html.index('id="autopilot"')]
    assert between.count("<section") == 1 and between.count("</section>") == 1
    assert "Off</span>" in section
    for name in autopilot.SWITCHES:
        assert f'value="{name}">' in section            # unchecked
    assert "nothing goes to your AI tool" in section
    assert 'name="daily_cap" value="15"' in section


def test_saving_the_switches_writes_config_and_commits(demo_client):
    root, client = demo_client
    r = client.post("/settings/autopilot", data={"csrf_token": token(client),
                                                 "on": ["reply_drafts", "meeting_briefs"],
                                                 "daily_cap": "8"})
    assert r.status_code == 303 and r.headers["location"].endswith("#autopilot")
    assert "reply%20drafts%2C%20morning%20brief" in r.headers["location"]
    saved = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
    assert saved["autopilot"] == {"reply_drafts": True, "follow_up_drafts": False,
                                  "meeting_briefs": True, "next_steps": False}
    assert saved["autopilot_daily_cap"] == 8
    assert git(root, "log", "-1", "--format=%s").startswith("settings: ")
    html = client.get("/settings").text
    section = html[html.index('id="autopilot"'):]
    assert 'value="reply_drafts" checked' in section and "On</span>" in section
    assert 'name="daily_cap" value="8"' in section
    # And off again.
    client.post("/settings/autopilot", data={"csrf_token": token(client), "daily_cap": "8"})
    saved = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
    assert not any(saved["autopilot"].values())


def test_the_settings_route_checks_csrf_and_values(demo_client):
    root, client = demo_client
    before = (root / "config.toml").read_text(encoding="utf-8")
    assert client.post("/settings/autopilot", data={"on": ["reply_drafts"]}).status_code == 403
    r = client.post("/settings/autopilot", data={"csrf_token": token(client),
                                                 "on": ["reply_drafts"], "daily_cap": "0"})
    assert r.status_code == 303 and "Not%20saved" in r.headers["location"]
    assert (root / "config.toml").read_text(encoding="utf-8") == before


def test_settings_shows_a_failed_run(demo_client):
    root, client = demo_client
    autopilot.write_state(root, {"last_run": {"at": "2026-09-14T07:00", "ok": False,
                                              "error": "reply drafts: 'claude' not found"}})
    html = client.get("/settings").text
    assert "Autopilot could not run: reply drafts: &#39;claude&#39; not found" in html


def test_autopilot_key_is_not_reported_as_unknown(demo_client):
    root, client = demo_client
    client.post("/settings/autopilot", data={"csrf_token": token(client),
                                             "on": ["next_steps"], "daily_cap": "15"})
    from hermitcrm import adjust
    assert adjust.validate_config(root) == []
    assert json.dumps(load_config(root)[autopilot.KEY]) == json.dumps(
        {"reply_drafts": False, "follow_up_drafts": False, "meeting_briefs": False,
         "next_steps": True})
