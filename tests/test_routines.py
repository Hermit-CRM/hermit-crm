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

"""Routines (routines.toml): selection, AI drafts with a fake runner, commits,
the daily sync, preview, on/off, validation, Home and the web routes."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from markupsafe import escape

from hermitcrm import cli, routines
from hermitcrm.enrich import EnrichError, Enricher
from hermitcrm.store import Store
from hermitcrm.web import create_app
from conftest import FIXED_NOW

ALL = lambda binary: f"/usr/local/bin/{binary}"  # noqa: E731
CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "owner_name": "Sam Example", "owner_email": "me@example.com",
          "welcome_dismissed": True, "disclaimer_accepted": "2026-09-01T09:00:00"}

STARTERS = '''# My routines.

[[routine]]
name = "morning-brief"
title = "Morning brief"
action = "brief"

[[routine]]
name = "nudge-quiet-threads"
title = "Nudge quiet threads"
action = "draft"
select = "quiet_threads"   # I wrote last
channel = "linkedin"
days = 7
prompt = """
Write a short follow-up. One question.
"""

[[routine]]
name = "reply-drafts"
title = "Reply drafts"
action = "draft"
select = "replies_owed"
prompt = "Draft a reply to their last message."
'''


class FakeAI:
    """Stands in for the AI CLI: an answer per call (or a function of the prompt);
    records every call. An exception in the list is raised."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer(prompt) if callable(answer) else answer


def good(body="Hi there,\n\nA short follow-up. Any news?\n\nSam", channel="linkedin",
         subject=""):
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


def seed(store: Store) -> None:
    """acme: I wrote on LinkedIn 10 days ago. beta: they wrote 3 days ago.
    gamma: a prospect never contacted. delta: I wrote 8 days ago but a next step
    is planned. epsilon: lost, I wrote 30 days ago."""
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
    store.create_company("Gamma Ltd", country="GB")
    store.create_contact("gamma", "Sam", "Lee", title="CEO")
    store.create_company("Delta SARL", country="FR", next_step="Call them",
                         next_step_due=(FIXED_NOW + timedelta(days=6)).date().isoformat())
    store.create_contact("delta", "Luc", "Martin")
    store.create_interaction("delta", channel="email", direction="out", contact="luc-martin",
                             date=at(8), body="Bonjour Luc")
    store.create_company("Epsilon BV", country="SE", stage="lost", lost_reason="budget")
    store.create_contact("epsilon", "Eva", "Berg")
    store.create_interaction("epsilon", channel="linkedin", direction="out",
                             contact="eva-berg", date=at(30), body="Hej Eva")


@pytest.fixture
def folder(tmp_path):
    """A git data folder with seeded records; writes commit like the CLI's."""
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "CRM Test")
    git(tmp_path, "config", "user.email", "crm@test.local")
    (tmp_path / "companies").mkdir()
    (tmp_path / ".gitignore").write_text("inbox/.last-routines.json\n")
    store = Store(tmp_path, clock=lambda: FIXED_NOW)
    store.load()
    store.on_write = cli._writer(store, tmp_path, {"push_enabled": False})
    seed(store)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "seed")
    return store


def write_routines(store: Store, text: str = STARTERS, commit: bool = True) -> None:
    (store.root / "routines.toml").write_text(text, encoding="utf-8")
    if commit:
        git(store.root, "add", "routines.toml")
        git(store.root, "commit", "-qm", "ai: adjust: routines")


def routine(store: Store, name: str):
    loaded = routines.load(store.root, CONFIG)
    assert not loaded.errors, loaded.errors
    return loaded.get(name)


# ------------------------------------------------------------------ selection


def test_quiet_threads_selects_from_the_radar(folder):
    write_routines(folder)
    picks = routines.select(folder, routine(folder, "nudge-quiet-threads"), CONFIG)
    # acme only: beta owes me nothing (they wrote last), delta has a plan, epsilon is lost
    assert [(p.record, p.contact.slug, p.channel, p.status) for p in picks] == [
        ("acme", "jane-doe", "linkedin", "")]
    assert picks[0].reason == "you wrote Jane Doe, nothing back, 10 days ago"
    assert picks[0].basis == folder.get("acme").interactions[0].id

    write_routines(folder, STARTERS.replace("days = 7", "days = 11"), commit=False)
    assert routines.select(folder, routine(folder, "nudge-quiet-threads"), CONFIG) == []
    write_routines(folder, STARTERS.replace('channel = "linkedin"', 'channel = "email"'),
                   commit=False)
    assert routines.select(folder, routine(folder, "nudge-quiet-threads"), CONFIG) == []


def test_the_sample_company_is_never_selected(folder):
    from hermitcrm import followups, sample

    sample.add(folder)
    made_up = [c.slug for c in sample.samples(folder)]
    assert made_up
    # the sample really is on the radar, so only the guard keeps it out
    radar = {r.company.slug for r in followups.radar(folder, FIXED_NOW.date())}
    assert radar & set(made_up)
    write_routines(folder, STARTERS + '''
[[routine]]
name = "everyone"
action = "draft"
select = "records"
prompt = "Say hi."
''')
    for name in ("nudge-quiet-threads", "reply-drafts", "everyone"):
        picks = routines.select(folder, routine(folder, name), CONFIG)
        assert not {p.record.split("/")[0] for p in picks} & set(made_up), name
    assert "acme" in [p.record for p in routines.select(
        folder, routine(folder, "nudge-quiet-threads"), CONFIG)]


def test_replies_owed_and_filters_on_radar_rows(folder):
    write_routines(folder)
    picks = routines.select(folder, routine(folder, "reply-drafts"), CONFIG)
    assert [(p.record, p.contact.slug, p.channel) for p in picks] == [
        ("beta", "piet-jansen", "email")]
    text = STARTERS.replace('select = "replies_owed"',
                            'select = "replies_owed"\ndays = 4')
    write_routines(folder, text, commit=False)
    assert routines.select(folder, routine(folder, "reply-drafts"), CONFIG) == []
    text = STARTERS.replace('select = "replies_owed"',
                            'select = "replies_owed"\nfilters = { country = "DE" }')
    write_routines(folder, text, commit=False)
    assert routines.select(folder, routine(folder, "reply-drafts"), CONFIG) == []


def test_records_selector_uses_the_list_filters(folder):
    write_routines(folder, '''
[[routine]]
name = "first-touch"
action = "draft"
select = "records"
filters = { last_touch = "-", country = ["GB", "FR"] }
prompt = "First message."

[[routine]]
name = "ceos"
action = "draft"
select = "records"
scope = "contacts"
filters = { title = "=ceo" }
channel = "email"
prompt = "Hello."
limit = 1
''')
    picks = routines.select(folder, routine(folder, "first-touch"), CONFIG)
    assert [(p.record, p.contact.slug, p.reason, p.channel) for p in picks] == [
        ("gamma", "sam-lee", "never contacted", "linkedin")]  # no email on file
    picks = routines.select(folder, routine(folder, "ceos"), CONFIG)
    assert [(p.record, p.channel) for p in picks] == [("gamma/sam-lee", "email")]


def test_limit_and_no_contact_show_as_status(folder):
    folder.create_company("Zeta GmbH", country="FI")
    write_routines(folder, '''
[[routine]]
name = "all"
action = "draft"
select = "records"
filters = { stage = ["prospect", "engaged"] }
prompt = "x"
limit = 2
''')
    picks = routines.select(folder, routine(folder, "all"), CONFIG)
    status = {p.record: p.status for p in picks}
    assert status["zeta"] == routines.NO_CONTACT
    assert sorted(status.values()).count("") == 2
    assert "over this run's limit of 2" in status.values()


# ---------------------------------------------------------------------- runs


def test_run_drafts_attributes_commits_once_and_never_duplicates(folder):
    write_routines(folder)
    before = len(subjects(folder.root))
    fake = ai(good())
    result = routines.run(folder, routine(folder, "nudge-quiet-threads"), apply=True,
                          enricher=fake, config=CONFIG)
    assert (result.drafts, result.skipped, result.commit) == (1, 0, True)
    assert subjects(folder.root)[0] == "routine: nudge-quiet-threads: 1 draft"
    assert len(subjects(folder.root)) == before + 1
    changed = git(folder.root, "show", "--name-only", "--format=", "HEAD").split()
    assert [c for c in changed if c != "PIPELINE.md"] == [
        f"drafts/{routines.drafts(folder.root)[0].id}.md"]
    assert git(folder.root, "status", "--porcelain") == ""  # the state file is ignored

    (draft,) = routines.drafts(folder.root)
    assert (draft.routine, draft.record, draft.company, draft.contact, draft.channel) == (
        "nudge-quiet-threads", "acme", "acme", "jane-doe", "linkedin")
    assert draft.made == FIXED_NOW.replace(second=0, microsecond=0)
    assert draft.body.startswith("Hi there,") and draft.subject == ""
    call = fake.runner.calls[0]
    assert call["tools"] == "" and call["schema"] == routines.DRAFT_SCHEMA
    for part in ("Write a short follow-up. One question.", "Jane Doe at Acme GmbH",
                 "hermitcrm show acme", "Hi Jane, shall we talk?", "Channel: linkedin",
                 "Language: German", "Sign as: Sam"):
        assert part in call["prompt"], part

    again = routines.run(folder, routine(folder, "nudge-quiet-threads"), apply=True,
                         enricher=fake, config=CONFIG)
    assert (again.drafts, again.commit) == (0, False)
    assert len(fake.runner.calls) == 1  # a waiting draft is not asked for again
    assert again.lines == ["not this time: Jane Doe (Acme GmbH) | a draft is waiting on Home"]
    assert len(subjects(folder.root)) == before + 1
    state = routines.read_state(folder.root)["nudge-quiet-threads"]
    assert state["ok"] and state["summary"] == "0 drafts" and state["at"] == "2026-09-14T10:30"


def test_bad_answers_skip_with_a_reason_and_write_nothing(folder):
    write_routines(folder, STARTERS.replace('select = "replies_owed"',
                                            'select = "records"\nlimit = 6'))
    fake = ai({"channel": "email", "subject": "", "body": "", "skip": ""},
              EnrichError("claude (claude-opus-5) failed: boom"),
              ["not", "a", "dict"],
              {"channel": "email", "subject": "", "body": "```json\n{}\n```", "skip": ""},
              {"channel": "email", "subject": "", "body": "x" * 6000, "skip": ""},
              {"channel": "email", "subject": "", "body": {"text": "hi"}, "skip": ""})
    before = subjects(folder.root)
    result = routines.run(folder, routine(folder, "reply-drafts"), apply=True,
                          enricher=fake, config=CONFIG)
    assert (result.drafts, result.skipped, result.commit) == (0, 5, False)
    reasons = " | ".join(result.lines)
    for reason in ("empty message", "boom", "no JSON object", "looks like code",
                   "over 5000 characters"):
        assert reason in reasons, reason
    assert routines.drafts(folder.root) == [] and subjects(folder.root) == before
    assert not (folder.root / "drafts" / "handled.tsv").exists()  # failures are retried


def test_ai_skip_is_remembered_and_not_asked_again(folder):
    write_routines(folder)
    fake = ai({"channel": "email", "subject": "", "body": "", "skip": "They said no."})
    r = routine(folder, "reply-drafts")
    result = routines.run(folder, r, apply=True, enricher=fake, config=CONFIG)
    assert (result.drafts, result.skipped) == (0, 1)
    assert subjects(folder.root)[0] == "routine: reply-drafts: 0 drafts, 1 skipped"
    assert routines.select(folder, r, CONFIG)[0].status == routines.HANDLED
    routines.run(folder, r, apply=True, enricher=fake, config=CONFIG)
    assert len(fake.runner.calls) == 1


def test_dry_run_and_preview_write_nothing_and_run_no_ai(folder):
    write_routines(folder)
    fake = ai(good())
    status = git(folder.root, "status", "--porcelain")
    before = subjects(folder.root)
    text, code = cli.cmd_routines(folder, folder.root, CONFIG, "preview",
                                  "nudge-quiet-threads", enricher=fake)
    assert code == 0
    assert "Would draft for 1:\n- Jane Doe (Acme GmbH) | you wrote Jane Doe" in text
    assert "No AI was run and nothing was written" in text
    text, code = cli.cmd_routines(folder, folder.root, CONFIG, "run", enricher=fake)
    assert code == 0 and "No routine is on." in text and "Dry run" in text
    text, code = cli.cmd_routines(folder, folder.root, CONFIG, "run", "reply-drafts",
                                  enricher=fake)
    assert "reply-drafts is paused; running it once" in text
    assert "would draft: Piet Jansen (Beta BV)" in text
    text, _ = cli.cmd_routines(folder, folder.root, CONFIG, "preview", "morning-brief")
    assert "Brief for 2026-09-14: 0 meetings, 0 tasks due, 1 reply owed" in text
    assert fake.runner.calls == []
    assert subjects(folder.root) == before
    assert git(folder.root, "status", "--porcelain") == status
    assert not (folder.root / "drafts").exists()
    assert not routines.state_path(folder.root).exists()


def test_preview_try_shows_one_draft_and_saves_nothing(folder):
    write_routines(folder)
    fake = ai(good(body="Hello Piet,\n\nHere are the prices: [prices].", channel="email",
                   subject="Re: Intro"))
    before = subjects(folder.root)
    text, code = cli.cmd_routines(folder, folder.root, CONFIG, "preview", "reply-drafts",
                                  try_ai=True, enricher=fake)
    assert code == 0
    assert "Draft for Piet Jansen (Beta BV) (email), not saved:\nSubject: Re: Intro\n" \
           "Hello Piet," in text
    assert len(fake.runner.calls) == 1 and subjects(folder.root) == before
    assert routines.drafts(folder.root) == []


def test_brief_is_stored_without_a_commit(folder):
    write_routines(folder)
    folder.add_task("gamma", "Send the deck", due=FIXED_NOW.date().isoformat())
    before = subjects(folder.root)
    result = routines.run(folder, routine(folder, "morning-brief"), apply=True,
                          config=CONFIG)
    assert result.summary() == "0 meetings, 1 task due, 1 reply owed"
    assert subjects(folder.root) == before
    brief = routines.read_state(folder.root)["morning-brief"]["brief"]
    assert brief["date"] == "2026-09-14"
    sections = {s["title"]: s["items"] for s in brief["sections"]}
    assert sections["Tasks due"] == [{"text": "Send the deck (Gamma Ltd)",
                                      "url": "/companies/gamma"}]
    assert sections["Replies you owe"][0]["url"] == "/companies/beta"


# ------------------------------------------------------------------- the sync


class EmptyBox:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def fetch(self):
        return []

    def mark_read(self, uids):
        pass


def sync(store, enricher=None, config=None):
    config = {**CONFIG, "bcc_address": "me+bcc@example.com", **(config or {})}
    return cli.cmd_sync(store, store.root, config, apply=True,
                        open_mailbox=lambda: EmptyBox(), resolve=lambda: "",
                        enricher=enricher)


def test_sync_runs_only_routines_that_are_on(folder):
    write_routines(folder)
    fake = ai(good(channel="email"))
    text, code = sync(folder, fake)
    assert code == 0 and text.endswith("== Routines ==\nNo routine is on.")
    assert fake.runner.calls == []
    assert routines.set_paused(folder, "reply-drafts", False, CONFIG)
    text, code = sync(folder, fake)
    assert code == 0
    assert "reply-drafts: 1 draft\n  drafted: Piet Jansen (Beta BV) | email" in text
    assert "nudge-quiet-threads" not in text and "morning-brief" not in text
    assert subjects(folder.root)[:2] == ["routine: reply-drafts: 1 draft",
                                         "routine: reply-drafts: turned on"]


def test_a_crashing_routine_does_not_break_the_sync(folder, monkeypatch):
    write_routines(folder, STARTERS.replace('name = "nudge-quiet-threads"',
                                            'name = "nudge-quiet-threads"\npaused = false')
                   .replace('name = "reply-drafts"', 'name = "reply-drafts"\npaused = false'))
    fake = ai(RuntimeError("the CLI exploded"), good(channel="email"))
    text, code = sync(folder, fake)
    assert code == 0
    assert "nudge-quiet-threads: 0 drafts, 1 skipped" not in text  # not an EnrichError
    assert "nudge-quiet-threads: failed: RuntimeError: the CLI exploded" in text
    assert "reply-drafts: 1 draft" in text  # the next one still ran
    state = routines.read_state(folder.root)
    assert not state["nudge-quiet-threads"]["ok"]
    assert "exploded" in state["nudge-quiet-threads"]["error"]
    assert state["reply-drafts"]["ok"]

    monkeypatch.setattr(routines, "load", lambda *a, **k: 1 / 0)
    text, code = sync(folder, fake)
    assert code == 0 and "Routines failed: ZeroDivisionError" in text


def test_no_ai_cli_is_one_line_per_routine(folder):
    write_routines(folder, STARTERS.replace('name = "reply-drafts"',
                                            'name = "reply-drafts"\npaused = false'))
    missing = Enricher(provider="auto", which=lambda name: None)
    text, code = sync(folder, missing)
    assert code == 0 and "reply-drafts: failed: no AI CLI found" in text


def test_without_routines_toml_nothing_changes(folder, tmp_path):
    text, code = sync(folder, ai(good()))
    assert "Routines" not in text
    assert text.endswith("== Calendar ==\nCalendar import skipped: no calendar URL configured")
    assert routines.run_all(folder, CONFIG, apply=True) == []
    assert routines.validate(folder.root) == []
    assert routines.built_items(folder.root) == []
    assert routines.home_context(folder, CONFIG) == {"routine_drafts": [],
                                                     "routine_briefs": []}
    text, code = cli.cmd_check(folder)
    assert code == 0 and text.startswith("OK:")
    text, code = cli.cmd_routines(folder, folder.root, CONFIG, "list")
    assert code == 0 and "No routines.toml" in text
    assert not (folder.root / "drafts").exists()


# ----------------------------------------------------------------- on and off


def test_on_and_off_change_only_the_paused_line_and_commit(folder):
    write_routines(folder)
    assert routines.set_paused(folder, "nudge-quiet-threads", False, CONFIG)
    diff = git(folder.root, "show", "--format=%s", "HEAD", "--", "routines.toml")
    assert diff.splitlines()[0] == "routine: nudge-quiet-threads: turned on"
    added = [l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    removed = [l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
    assert added == ["+paused = false"] and removed == []
    text = (folder.root / "routines.toml").read_text()
    assert text.replace("paused = false\n", "", 1) == STARTERS
    assert not routines.set_paused(folder, "nudge-quiet-threads", False, CONFIG)  # already on

    assert routines.set_paused(folder, "nudge-quiet-threads", True, CONFIG)
    assert subjects(folder.root)[0] == "routine: nudge-quiet-threads: turned off"
    assert (folder.root / "routines.toml").read_text() == text.replace(
        "paused = false", "paused = true")


def test_with_paused_keeps_comments_and_ignores_multiline_strings():
    text = ('[[routine]]\r\nname = "a"\r\nprompt = """\r\npaused = true\r\nname = "b"\r\n"""\r\n'
            'paused = true   # new ones start paused\r\naction = "draft"\r\n'
            '[routine.filters]\r\nstage = "prospect"\r\n\r\n'
            "[[routine]]\r\nname = 'b'\r\naction = \"brief\"")
    on = routines.with_paused(text, "a", False)
    assert on == text.replace("paused = true   #", "paused = false   #")
    on_b = routines.with_paused(text, "b", False)
    assert on_b == text.replace("name = 'b'\r\n", "name = 'b'\r\npaused = false\r\n")
    with pytest.raises(routines.RoutineError, match="no routine named c"):
        routines.with_paused(text, "c", False)
    weird = '[[routine]]\nname = "a"\naction = "brief"\n[[routine]]\nname = "a"\n'
    with pytest.raises(routines.RoutineError, match="safely"):
        routines.with_paused(weird, "a", False)


def test_a_routine_with_problems_is_not_turned_on(folder):
    write_routines(folder, STARTERS + '\n[[routine]]\nname = "bad"\naction = "draft"\n'
                   'select = "quiet_thread"\nprompt = "x"\n')
    with pytest.raises(routines.RoutineError, match="did you mean quiet_threads"):
        routines.set_paused(folder, "bad", False, CONFIG)
    assert routines.set_paused(folder, "bad", True, CONFIG) is False  # already paused
    with pytest.raises(routines.RoutineError, match="no routine named nudge"):
        routines.set_paused(folder, "nudge", False, CONFIG)
    text, code = cli.cmd_routines(folder, folder.root, CONFIG, "on", "nudge")
    assert code == 1 and "did you mean" in text


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize("text, message", [
    ('[[routine]]\nname = "x"\naction = "draft"\nselect = "records"\nprompt = "p"\n'
     'promt = "q"\n', "routines.toml: routine x: unknown key promt (did you mean prompt?)"),
    ('[[routine]]\nname = "x"\naction = "drafts"\n',
     "routines.toml: routine x: unknown action drafts (did you mean draft?); use draft or brief"),
    ('[[routine]]\nname = "x"\naction = "draft"\nselect = "replies"\nprompt = "p"\n',
     "routines.toml: routine x: unknown select replies (did you mean replies_owed?)"),
    ('[[routine]]\nname = "x"\naction = "draft"\nselect = "records"\nprompt = "p"\n'
     'channel = "linkdin"\n',
     "routines.toml: routine x: unknown channel linkdin (did you mean linkedin?)"),
    ('[[routine]]\nname = "x"\naction = "brief"\n[[routine]]\nname = "x"\naction = "brief"\n',
     "routines.toml: routine x: the name x is used twice; names must be unique"),
    ('[[routine]]\nname = "x"\naction = "draft"\nselect = "records"\nprompt = "' + "p" * 2001
     + '"\n', "routines.toml: routine x: prompt is 2001 characters; the limit is 2000"),
    ('[[routine]]\nname = "x"\naction = "draft"\nselect = "records"\nprompt = "p"\n'
     'filters = { stge = "prospect" }\n',
     "routines.toml: routine x: filters: unknown column stge (did you mean stage?)"),
    ('[[routine]]\nname = "x"\naction = "draft"\nselect = "records"\nprompt = "p"\n'
     'filters = { stage = "prospekt" }\n',
     "routines.toml: routine x: filters: stage: unknown value prospekt (did you mean prospect?)"),
    ('[[routine]]\nname = "x"\naction = "draft"\nselect = "records"\nprompt = "p"\n'
     'filters = { next_step_due = ">soon" }\n',
     "routines.toml: routine x: filters: next_step_due: >soon needs a date as YYYY-MM-DD "
     "after >"),
    ('[[routine]]\nname = "x"\naction = "draft"\nselect = "records"\nprompt = "p"\n'
     'filters = { tags = 5 }\n',
     'routines.toml: routine x: filters: tags: write the value as text in quotes'),
    ('[[routine]]\nname = "x"\naction = "brief"\nselect = "records"\n',
     "routines.toml: routine x: select is not used by a brief; remove it"),
    ('[[routine]]\nname = "x"\naction = "draft"\nselect = "records"\nprompt = "p"\nlimit = 0\n',
     "routines.toml: routine x: limit must be a whole number from 1 to 50"),
    ('[[routine]]\nname = "x"\naction = "draft"\nselect = "records"\nprompt = "p"\ndays = 3\n',
     "routines.toml: routine x: days is only for quiet_threads and replies_owed"),
    ('[[routine]]\nname = "x"\naction = "draft"\nselect = "quiet_threads"\n',
     "routines.toml: routine x: needs a prompt: what the AI should write"),
    ('[[routine]]\nname = "My Routine"\naction = "brief"\n',
     "routines.toml: routine My Routine: name My Routine must be lowercase letters, digits "
     "and dashes, e.g. my-routine"),
    ('[[routine]]\naction = "brief"\npaused = "no"\n',
     "routines.toml: routine 1: paused must be true or false"),
    ('[[routine]]\nname = "x"\naction = "brief\n', "routines.toml: line 3: "),
    ('routine = "x"\n', "routines.toml: top level: write each routine as a [[routine]] table"),
    ('[[routines]]\nname = "x"\n',
     "routines.toml: top level: unknown key routines (did you mean routine?)"),
])
def test_validation_messages(tmp_path, text, message):
    (tmp_path / "routines.toml").write_text(text, encoding="utf-8")
    errors = routines.validate(tmp_path)
    assert any(e.startswith(message) for e in errors), errors


def test_custom_field_filters_validate_and_select(folder):
    (folder.root / "fields.toml").write_text(
        '[[field]]\nkey = "fit_score"\ntype = "number"\nshow_in = ["detail", "companies"]\n')
    folder.update_company("gamma", custom={"fit_score": 8})
    text = ('[[routine]]\nname = "fit"\naction = "draft"\nselect = "records"\nprompt = "p"\n'
            'filters = { fit_score = ">7" }\n')
    write_routines(folder, text, commit=False)
    assert [p.record for p in routines.select(folder, routine(folder, "fit"), CONFIG)] == [
        "gamma"]
    write_routines(folder, text.replace("fit_score =", "fitscore ="), commit=False)
    assert routines.validate(folder.root) == [
        "routines.toml: routine fit: filters: unknown column fitscore (did you mean "
        "fit_score?)"]


def test_check_prints_routine_problems_and_fails(folder):
    write_routines(folder, '[[routine]]\nname = "x"\naction = "draft"\nselect = "records"\n'
                   'prompt = "p"\npromt = "q"\n')
    text, code = cli.cmd_check(folder)
    assert code == 1
    assert text == "routines.toml: routine x: unknown key promt (did you mean prompt?)"
    write_routines(folder)
    text, code = cli.cmd_check(folder)
    assert code == 0 and text.startswith("OK:")


def test_main_routines_command_end_to_end(folder, capsys):
    write_routines(folder)
    assert cli.main(["routines"], root=folder.root) == 0
    out = capsys.readouterr().out
    assert "nudge-quiet-threads | paused | Nudge quiet threads | quiet_threads -> draft" in out
    assert cli.main(["routines", "on", "morning-brief"], root=folder.root) == 0
    assert "morning-brief is on." in capsys.readouterr().out
    assert subjects(folder.root)[0] == "routine: morning-brief: turned on"
    assert cli.main(["routines", "preview", "nope"], root=folder.root) == 1
    assert "no routine named 'nope'" in capsys.readouterr().out
    assert cli.main(["routines", "run", "morning-brief", "--apply"], root=folder.root) == 0
    assert "morning-brief: 0 meetings" in capsys.readouterr().out
    assert routines.read_state(folder.root)["morning-brief"]["ok"]


# ------------------------------------------------------------- drafts on Home


@pytest.fixture
def app(folder):
    app = create_app(folder.root, config=CONFIG, clock=lambda: FIXED_NOW)
    app.state.enricher = ai(good(channel="email", subject="Re: Intro",
                                 body="Hello Piet,\n\nThe prices: [prices].\n\nSam"))
    return app


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False)


def make_draft(folder, enricher=None):
    write_routines(folder)
    routines.run(folder, routine(folder, "reply-drafts"), apply=True,
                 enricher=enricher or ai(good(channel="email", subject="Re: Intro",
                                              body="Hello Piet,\n\nPrices: [prices].")),
                 config=CONFIG)
    return routines.drafts(folder.root)[0]


def test_home_shows_drafts_and_todays_brief(folder, client):
    page = client.get("/").text
    assert "Drafts from routines" not in page and "routine-brief" not in page
    draft = make_draft(folder)
    routines.run(folder, routine(folder, "morning-brief"), apply=True, config=CONFIG)
    page = client.get("/").text
    assert 'id="routine-drafts"' in page and "Drafts from routines (1)" in page
    assert "Prices: [prices]." in page and 'value="Re: Intro"' in page
    assert '<a href="/companies/beta/contacts/piet-jansen">Piet Jansen</a>' in page
    assert f'action="/yours/routines/reply-drafts/drafts/{draft.id}/sent"' in page
    assert f'formaction="/yours/routines/reply-drafts/drafts/{draft.id}/discard"' in page
    assert ">Reply drafts</a>" in page
    assert 'id="brief-morning-brief"' in page and "Replies you owe (1)" in page

    state = routines.read_state(folder.root)
    state["morning-brief"]["brief"]["date"] = "2026-09-13"  # yesterday's brief
    routines.state_path(folder.root).write_text(json.dumps(state))
    assert 'id="brief-morning-brief"' not in client.get("/").text


def test_i_sent_it_logs_the_edited_message_and_closes_the_draft(folder, app, client):
    draft = make_draft(folder)
    token = app.state.csrf_token
    r = client.post(f"/yours/routines/reply-drafts/drafts/{draft.id}/sent",
                    data={"csrf_token": token, "subject": "Re: Intro (prices)",
                          "body": "Hello Piet,\n\nThe prices are attached.", "back": "/"})
    assert r.status_code == 303 and "Logged%20the%20message%20to%20Piet%20Jansen" in \
        r.headers["location"]
    assert routines.drafts(folder.root) == []
    assert subjects(folder.root)[0] == f"routine: reply-drafts: draft for beta sent"
    company = folder.get("beta", refresh=True)
    latest = max(company.interactions, key=lambda i: i.date)
    assert (latest.channel, latest.direction, latest.contact, latest.subject) == (
        "email", "out", "piet-jansen", "Re: Intro (prices)")
    assert latest.body == "Hello Piet,\n\nThe prices are attached.\n"
    handled = (folder.root / "drafts" / "handled.tsv").read_text()
    assert handled.startswith(f"reply-drafts\tbeta\t{draft.basis}\tsent\t")
    assert git(folder.root, "status", "--porcelain") == ""


def test_discard_is_remembered_so_the_thread_is_not_drafted_again(folder, app, client):
    draft = make_draft(folder)
    r = client.post(f"/yours/routines/reply-drafts/drafts/{draft.id}/discard",
                    data={"csrf_token": app.state.csrf_token, "body": "ignored"})
    assert r.status_code == 303 and "Draft%20for%20Piet%20Jansen%20discarded" in \
        r.headers["location"]
    assert subjects(folder.root)[0] == "routine: reply-drafts: draft for beta discarded"
    company = folder.get("beta", refresh=True)
    assert len(company.interactions) == 2  # nothing logged
    fake = ai(good(channel="email"))
    r = routine(folder, "reply-drafts")
    assert routines.select(folder, r, CONFIG)[0].status == routines.HANDLED
    routines.run(folder, r, apply=True, enricher=fake, config=CONFIG)
    assert fake.runner.calls == []
    # Something new on the thread: a new basis, so the routine may draft again.
    folder.create_interaction("beta", channel="email", direction="in", contact="piet-jansen",
                              date=at(2), body="Any news?")
    assert routines.select(folder, r, CONFIG)[0].status == ""


def test_draft_routes_check_csrf_and_ids(folder, app, client):
    draft = make_draft(folder)
    base = "/yours/routines/reply-drafts"
    for path, data in ((f"{base}/on", {}), (f"{base}/off", {}), (f"{base}/try", {}),
                       (f"{base}/drafts/{draft.id}/sent", {"body": "x"}),
                       (f"{base}/drafts/{draft.id}/discard", {})):
        assert client.post(path, data={"csrf_token": "wrong", **data}).status_code == 403
    token = app.state.csrf_token
    assert client.post(f"/yours/routines/other/drafts/{draft.id}/sent",
                       data={"csrf_token": token, "body": "x"}).status_code == 404
    assert client.post(f"{base}/drafts/nope/sent",
                       data={"csrf_token": token, "body": "x"}).status_code == 404
    assert client.post(f"{base}/drafts/{draft.id}/send",
                       data={"csrf_token": token}).status_code == 404
    r = client.post(f"{base}/drafts/{draft.id}/sent", data={"csrf_token": token, "body": " "})
    assert r.status_code == 303 and "empty" in r.headers["location"]
    assert routines.drafts(folder.root) != []


# ---------------------------------------------------------- the routine pages


def test_preview_page_and_on_off_routes(folder, app, client):
    write_routines(folder)
    page = client.get("/yours/routines/nudge-quiet-threads")
    assert page.status_code == 200
    html = page.text
    assert "Nudge quiet threads" in html and ">paused<" in html
    assert "Picks people you messaged on linkedin at least 7 days ago" in html
    assert '<a href="/companies/acme/contacts/jane-doe">Jane Doe (Acme GmbH)</a>' in html
    assert "Try the AI on the first one" in html and "Turn on" in html
    assert client.get("/yours/routines/nope").status_code == 404
    page = client.get("/yours/routines/morning-brief").text
    assert "What it would show on Home now" in page and "Replies you owe (1)" in page
    index = client.get("/yours/routines").text
    assert '<a href="/yours/routines/reply-drafts">Reply drafts</a>' in index

    token = app.state.csrf_token
    r = client.post("/yours/routines/nudge-quiet-threads/on", data={"csrf_token": token})
    assert r.status_code == 303 and r.headers["location"].startswith(
        "/yours/routines/nudge-quiet-threads?flash=On")
    assert subjects(folder.root)[0] == "routine: nudge-quiet-threads: turned on"
    assert ">on<" in client.get("/yours/routines/nudge-quiet-threads").text
    client.post("/yours/routines/nudge-quiet-threads/off", data={"csrf_token": token})
    assert subjects(folder.root)[0] == "routine: nudge-quiet-threads: turned off"


def test_try_route_shows_a_draft_and_saves_nothing(folder, app, client):
    write_routines(folder)
    before = subjects(folder.root)
    r = client.post("/yours/routines/reply-drafts/try",
                    data={"csrf_token": app.state.csrf_token})
    assert r.status_code == 200
    assert "The prices: [prices]." in r.text and "not saved" in r.text
    assert app.state.enricher.runner.calls[0]["tools"] == ""
    assert subjects(folder.root) == before and routines.drafts(folder.root) == []

    app.state.enricher = ai(EnrichError("claude failed: no credits"))
    r = client.post("/yours/routines/reply-drafts/try",
                    data={"csrf_token": app.state.csrf_token})
    assert r.status_code == 502 and "no credits" in r.text
    r = client.post("/yours/routines/morning-brief/try",
                    data={"csrf_token": app.state.csrf_token})
    assert r.status_code == 400


def test_problem_banner_and_refused_turn_on(folder, app, client):
    write_routines(folder, STARTERS + '\n[[routine]]\nname = "bad"\naction = "draft"\n'
                   'select = "records"\nprompt = "p"\nfilters = { stge = "x" }\n')
    page = client.get("/yours/routines/bad")
    assert page.status_code == 200 and "did you mean stage?" in page.text
    r = client.post("/yours/routines/bad/on", data={"csrf_token": app.state.csrf_token})
    assert r.status_code == 400 and "fix these first" in r.text
    assert "has a problem" in client.get("/yours/routines").text


def test_built_items_for_the_hub(folder):
    write_routines(folder, STARTERS + '\n[[routine]]\nname = "bad"\naction = "nope"\n')
    routines.record_run(folder.root, "reply-drafts", datetime(2026, 9, 14, 7, 2), True,
                        "2 drafts")
    items = routines.built_items(folder.root)
    assert [i["title"] for i in items] == ["Morning brief", "Nudge quiet threads",
                                           "Reply drafts", "bad"]
    reply = items[2]
    assert set(reply) == {"kind", "title", "url", "detail", "adjust"}
    assert reply["kind"] == "routine" and reply["url"] == "/yours/routines/reply-drafts"
    assert reply["detail"] == "paused · last run 2026-09-14 07:02: 2 drafts"
    assert "Reply drafts" in reply["adjust"]
    assert items[3]["detail"] == "has a problem: run hermitcrm check"


def test_help_topic_renders(client):
    r = client.get("/help/adjust-routines")
    assert r.status_code == 200 and "Three starters" in r.text
    text, code = cli.cmd_help("adjust-routines")
    assert code == 0 and 'select = "quiet_threads"' in text


def test_a_crash_halfway_still_commits_the_drafts_written(folder):
    write_routines(folder, STARTERS.replace('select = "replies_owed"',
                                            'select = "records"\nlimit = 3'))
    fake = ai(good(channel="email"), RuntimeError("the CLI exploded"))
    with pytest.raises(RuntimeError):
        routines.run(folder, routine(folder, "reply-drafts"), apply=True, enricher=fake,
                     config=CONFIG)
    assert subjects(folder.root)[0] == "routine: reply-drafts: 1 draft"
    assert git(folder.root, "status", "--porcelain") == ""


# ------------------------------------------- a CLI that cannot run without tools


def unrestricted(*answers) -> Enricher:
    """An AI CLI with no no-tools switch (Gemini), with a fake runner behind it."""
    return Enricher(provider="gemini", which=ALL, runner=FakeAI(*answers))


REFUSED = "gemini can't run without tools, so routines that draft need Claude Code or Codex"


def test_a_cli_without_a_no_tools_switch_is_refused_not_run(folder):
    write_routines(folder)
    fake = unrestricted(good())
    before = subjects(folder.root)
    with pytest.raises(routines.RoutineError, match=REFUSED):
        routines.run(folder, routine(folder, "nudge-quiet-threads"), apply=True,
                     enricher=fake, config=CONFIG)
    with pytest.raises(routines.RoutineError, match=REFUSED):
        routines.try_first(folder, routine(folder, "reply-drafts"), fake, CONFIG)
    assert fake.runner.calls == [] and subjects(folder.root) == before
    assert routines.drafts(folder.root) == []


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_claude_and_codex_still_draft(folder, provider):
    write_routines(folder)
    fake = Enricher(provider=provider, which=ALL, runner=FakeAI(good()))
    result = routines.run(folder, routine(folder, "nudge-quiet-threads"), apply=True,
                          enricher=fake, config=CONFIG)
    assert result.drafts == 1 and fake.runner.calls[0]["tools"] == ""


def test_the_sync_says_why_in_one_line(folder):
    write_routines(folder, STARTERS.replace('name = "reply-drafts"',
                                            'name = "reply-drafts"\npaused = false'))
    fake = unrestricted(good())
    text, code = sync(folder, fake)
    assert code == 0 and f"reply-drafts: failed: {REFUSED}" in text
    assert fake.runner.calls == [] and routines.drafts(folder.root) == []
    assert "can't run without tools" in routines.read_state(folder.root)["reply-drafts"]["error"]


def test_the_reason_shows_in_list_preview_and_a_dry_run(folder):
    write_routines(folder)
    fake = unrestricted(good())
    text, code = cli.cmd_routines(folder, folder.root, CONFIG, "list", enricher=fake)
    assert code == 0 and f"Drafting is refused: {REFUSED}" in text
    text, code = cli.cmd_routines(folder, folder.root, CONFIG, "preview", "reply-drafts",
                                  enricher=fake)
    assert code == 0 and f"The AI step is refused: {REFUSED}" in text
    assert "No AI was run" not in text and "Would draft for 1" in text
    text, code = cli.cmd_routines(folder, folder.root, CONFIG, "preview", "reply-drafts",
                                  try_ai=True, enricher=fake)
    assert code == 1 and f"Try failed: {REFUSED}" in text
    text, _ = cli.cmd_routines(folder, folder.root, CONFIG, "run", "reply-drafts",
                               enricher=fake)
    assert f"a real run would be refused: {REFUSED}" in text
    # a folder with only a brief has nothing to refuse
    write_routines(folder, '[[routine]]\nname = "morning-brief"\naction = "brief"\n')
    text, _ = cli.cmd_routines(folder, folder.root, CONFIG, "list", enricher=fake)
    assert "refused" not in text
    # and the same folder with Claude says nothing about it
    write_routines(folder)
    text, _ = cli.cmd_routines(folder, folder.root, CONFIG, "list", enricher=ai(good()))
    assert "refused" not in text
    assert fake.runner.calls == []


def test_the_reason_shows_on_the_routine_pages_and_the_button_goes(folder, app, client):
    write_routines(folder)
    page = client.get("/yours/routines/reply-drafts").text
    assert "The AI step will not run" not in page and "Try the AI on the first one" in page
    app.state.enricher = unrestricted(good())
    page = client.get("/yours/routines/reply-drafts").text
    shown = str(escape(REFUSED))                                     # can't is escaped
    assert "The AI step will not run." in page and shown in page
    assert "Try the AI on the first one" not in page
    assert "Routines that draft will not run." in client.get("/yours/routines").text
    r = client.post("/yours/routines/reply-drafts/try",
                    data={"csrf_token": app.state.csrf_token})
    assert r.status_code == 400 and shown in r.text
    assert app.state.enricher.runner.calls == []
    # a brief uses no AI, so its page has nothing to say
    assert "The AI step will not run" not in client.get("/yours/routines/morning-brief").text
