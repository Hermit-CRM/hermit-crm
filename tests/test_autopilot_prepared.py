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

"""Autopilot step 2: next-step proposals (a fake AI, never a real one), the
proposals file, and Today's "Prepared for you" group with Approve, Edit and
Discard."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from hermitcrm import autopilot, cli, routines, today
from hermitcrm.enrich import EnrichError, Enricher
from hermitcrm.store import Store
from hermitcrm.web import create_app
from conftest import CONFIG as APP_CONFIG, FIXED_NOW

ALL = lambda binary: f"/usr/local/bin/{binary}"  # noqa: E731
TODAY = FIXED_NOW.date()
SOON = (TODAY + timedelta(days=5)).isoformat()


class FakeAI:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer(prompt) if callable(answer) else answer


def step(text="Send the pricing overview", due=SOON, why="They asked for prices.", skip=""):
    return {"next_step": text, "due": due, "why": why, "skip": skip}


def ai(*answers) -> Enricher:
    return Enricher(provider="claude", which=ALL, runner=FakeAI(*answers))


def at(days_ago: int) -> str:
    return (FIXED_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT10:00")


def config(**switches) -> dict:
    return {"push_enabled": False, "owner_name": "Sam Example", "autopilot": switches}


def seed(store: Store) -> None:
    """acme: talked 3 days ago, no task (a candidate). beta: talked 2 days ago but
    has a task. gamma: last talk 40 days ago. delta: lost. omega: talked 1 day
    ago, no task (a candidate, the most recent)."""
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe", email="jane@acme.example.com")
    store.create_interaction("acme", channel="email", direction="in", contact="jane-doe",
                             date=at(3), subject="Prices?", body="What does it cost?")
    store.create_company("Beta BV", country="NL")
    store.create_interaction("beta", channel="call", direction="out", date=at(2),
                             body="Good call.")
    store.add_task("beta", "Send the deck", due=TODAY + timedelta(days=2))
    store.create_company("Gamma Ltd", country="GB")
    store.create_interaction("gamma", channel="email", direction="out", date=at(40),
                             body="Hello")
    store.create_company("Delta SARL", country="FR", stage="lost", lost_reason="budget")
    store.create_interaction("delta", channel="email", direction="out", date=at(1),
                             body="Bonjour")
    store.create_company("Omega", country="FI")
    store.create_interaction("omega", channel="linkedin", direction="out", date=at(1),
                             body="Hei")


@pytest.fixture
def folder(repo):
    store = Store(repo, clock=lambda: FIXED_NOW)
    store.load()
    store.on_write = cli._writer(store, repo, {"push_enabled": False})
    seed(store)
    return store


def run(store, enricher, **switches):
    return autopilot.run(store, config(**(switches or {"next_steps": True})), apply=True,
                         enricher=enricher)


# ---------------------------------------------------------------- selection


def test_candidates_are_open_quiet_recent_companies_without_a_task(folder):
    got = [c.slug for c, _ in autopilot.next_step_candidates(folder, TODAY)]
    assert got == ["omega", "acme"]


def test_a_dry_run_counts_them_and_calls_no_ai(folder):
    fake = ai(step())
    lines = autopilot.run(folder, config(next_steps=True), apply=False, enricher=fake)
    assert lines == ["autopilot: next steps: would propose for 2 companies (dry run, no AI)"]
    assert fake.runner.calls == []


# ------------------------------------------------------------------ proposing


def test_one_light_no_tools_call_per_company_and_nothing_on_the_record(folder):
    fake = ai(step())
    head = folder.root.joinpath(".git", "HEAD").read_text()
    log_before = routines_log(folder)
    lines = run(folder, fake)
    assert lines[0] == "autopilot: next steps: 2 proposed"
    calls = fake.runner.calls
    assert len(calls) == 2 and all(c["tools"] == "" for c in calls)
    assert all(c["schema"] is autopilot.NEXT_STEP_SCHEMA for c in calls)
    assert "hermitcrm show omega" in calls[0]["prompt"]
    assert f"Today is {TODAY.isoformat()}" in calls[0]["prompt"]
    got = autopilot.proposals(folder.root)
    assert [(p.kind, p.company, p.text, p.due) for p in got] == [
        (autopilot.NEXT_STEP, "omega", "Send the pricing overview", SOON),
        (autopilot.NEXT_STEP, "acme", "Send the pricing overview", SOON)]
    assert folder.companies["acme"].open_todos() == []          # not on the record
    assert routines_log(folder) == log_before                    # no commit at all
    assert folder.root.joinpath(".git", "HEAD").read_text() == head


def routines_log(store):
    import subprocess
    return subprocess.run(["git", "log", "--format=%s"], cwd=store.root,
                          capture_output=True, text=True).stdout


def test_the_light_tier_is_used(folder, monkeypatch):
    tiers = []
    real = Enricher.with_tier

    def spy(self, tier):
        tiers.append(tier)
        return real(self, tier)

    monkeypatch.setattr(Enricher, "with_tier", spy)
    run(folder, ai(step()))
    assert "light" in tiers


def test_a_waiting_proposal_is_not_asked_again(folder):
    fake = ai(step())
    run(folder, fake)
    run(folder, fake)
    assert len(fake.runner.calls) == 2


@pytest.mark.parametrize("answer, why", [
    (step(text=""), "the AI returned no next step"),
    (step(due="next week"), "is not YYYY-MM-DD"),
    (step(due=(TODAY - timedelta(days=1)).isoformat()), "is not between today"),
    (step(text="x" * 300), "over 200 characters"),
    ("not json", "no JSON object"),
])
def test_an_unusable_answer_skips_that_company(folder, answer, why):
    lines = run(folder, ai(answer))
    assert any(why in line for line in lines), lines
    assert autopilot.proposals(folder.root) == []
    assert autopilot.failure(folder.root) == ""


def test_the_ai_saying_no_next_step_is_remembered(folder):
    fake = ai(step(text="", skip="They said no."))
    lines = run(folder, fake)
    assert "  skipped Omega: the AI says They said no." in lines
    run(folder, fake)
    assert len(fake.runner.calls) == 2          # not asked again
    folder.create_interaction("omega", channel="email", direction="in", date=at(0),
                              body="Actually, tell me more.")
    run(folder, fake)
    assert len(fake.runner.calls) == 3          # something new: asked again


def test_every_call_failing_is_a_failure(folder):
    run(folder, ai(EnrichError("claude failed: 401")))
    assert autopilot.failure(folder.root) == "next steps: the AI tool failed: claude failed: 401"


def test_the_cap_counts_proposals(folder):
    fake = ai(step())
    cfg = {**config(next_steps=True), autopilot.CAP_KEY: 1}
    lines = autopilot.run(folder, cfg, apply=True, enricher=fake)
    assert lines[0] == "autopilot: next steps: 1 proposed"
    assert len(autopilot.proposals(folder.root)) == 1
    lines = autopilot.run(folder, cfg, apply=True, enricher=fake)
    assert "autopilot: next steps: 1 waiting, but today's limit is reached" in lines


def test_switched_off_no_proposal_and_no_call(folder):
    fake = ai(step())
    assert autopilot.run(folder, config(next_steps=False), apply=True, enricher=fake) == []
    assert fake.runner.calls == []


def test_a_proposals_file_from_a_later_kind_survives(folder):
    """WP10 adds kinds of its own to the same list: an unknown one is kept, not shown."""
    autopilot.add_proposals(folder, [autopilot.Proposal(
        id="", kind="after-contact", company="acme", made="2026-09-14T08:00",
        text="Log the call outcome", extra={"interaction": "x"})])
    run(folder, ai(step()))
    kinds = sorted(p.kind for p in autopilot.proposals(folder.root))
    assert kinds == ["after-contact", "next-step", "next-step"]
    rows = autopilot.prepared_items(folder, {}, TODAY)
    assert not any("Log the call outcome" in r.title for r in rows)


def test_a_damaged_entry_in_the_file_is_left_out(folder):
    autopilot.write_state(folder.root, {"proposals": [{"id": 3}, "x", {"kind": "next-step"}]})
    assert autopilot.proposals(folder.root) == []


# ---------------------------------------------------------------------- Today


def test_proposals_and_a_failure_show_under_prepared_for_you(folder):
    run(folder, ai(step()))
    autopilot.write_state(folder.root, {**autopilot.read_state(folder.root),
                                        "last_run": {"ok": False, "error": "reply drafts: "
                                                     "'claude' not found"}})
    queue = today.build(folder, config(next_steps=True), TODAY)
    prepared = [i for i in queue.items if i.kind == autopilot.PREPARED]
    assert prepared[0].title == "Autopilot could not run: reply drafts: 'claude' not found"
    row = next(i for i in prepared if i.company and i.company.slug == "acme")
    assert row.title == "Next step: Send the pricing overview"
    assert row.reason.startswith("Proposed for ") and "They asked for prices." in row.reason
    assert [a.label for a in row.actions] == ["Approve", "Edit", "Discard"]
    assert autopilot.PREPARED == today.PREPARED
    assert today.heading_of(today.PREPARED) == today.heading_of(today.DRAFT) == autopilot.HEADING


# ------------------------------------------------------------ the web routes


@pytest.fixture
def web(folder):
    app = create_app(folder.root, config=APP_CONFIG)
    app.state.store.clock = lambda: FIXED_NOW
    return TestClient(app, follow_redirects=False), app.state.store


def csrf(client) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get("/today").text).group(1)


def proposal_for(root, slug):
    return next(p for p in autopilot.proposals(root) if p.company == slug)


def test_today_page_shows_the_group_with_its_buttons(folder, web):
    run(folder, ai(step()))
    client, store = web
    html = client.get("/today").text
    assert "Prepared for you" in html
    p = proposal_for(folder.root, "acme")
    assert f'action="/autopilot/proposals/{p.id}/approve"' in html
    assert f'href="/autopilot/proposals/{p.id}"' in html
    assert f'action="/autopilot/proposals/{p.id}/discard"' in html


def test_approve_writes_the_task_with_the_normal_store_call(folder, web):
    run(folder, ai(step()))
    client, store = web
    p = proposal_for(folder.root, "acme")
    r = client.post(f"/autopilot/proposals/{p.id}/approve",
                    data={"csrf_token": csrf(client), "back": "/today"})
    assert r.status_code == 303 and r.headers["location"].startswith("/today?flash=Next")
    store.load()
    todo = store.companies["acme"].next_todo()
    assert (todo.text, todo.due.isoformat()) == ("Send the pricing overview", SOON)
    assert routines_log(store).splitlines()[0] == "task: acme added (autopilot proposal)"
    assert all(q.id != p.id for q in autopilot.proposals(folder.root))


def test_edit_then_approve(folder, web):
    run(folder, ai(step()))
    client, store = web
    p = proposal_for(folder.root, "acme")
    page = client.get(f"/autopilot/proposals/{p.id}")
    assert page.status_code == 200 and 'value="Send the pricing overview"' in page.text
    later = (TODAY + timedelta(days=9)).isoformat()
    r = client.post(f"/autopilot/proposals/{p.id}/approve",
                    data={"csrf_token": csrf(client), "text": "Call Jane about prices",
                          "due": later, "back": "/today"})
    assert r.status_code == 303
    store.load()
    todo = store.companies["acme"].next_todo()
    assert (todo.text, todo.due.isoformat()) == ("Call Jane about prices", later)


def test_an_empty_edit_is_refused_and_keeps_the_proposal(folder, web):
    run(folder, ai(step()))
    client, store = web
    p = proposal_for(folder.root, "acme")
    r = client.post(f"/autopilot/proposals/{p.id}/approve",
                    data={"csrf_token": csrf(client), "text": "  ", "due": SOON})
    assert "Not%20approved" in r.headers["location"]
    assert autopilot.get_proposal(folder.root, p.id) is not None
    assert store.companies["acme"].open_todos() == []


def test_discard_drops_it_and_writes_nothing(folder, web):
    run(folder, ai(step()))
    client, store = web
    p = proposal_for(folder.root, "acme")
    before = routines_log(store)
    r = client.post(f"/autopilot/proposals/{p.id}/discard",
                    data={"csrf_token": csrf(client), "back": "/today"})
    assert r.status_code == 303 and "discarded" in r.headers["location"]
    assert autopilot.get_proposal(folder.root, p.id) is None
    assert routines_log(store) == before
    assert "acme" not in [c.slug for c, _ in autopilot.next_step_candidates(store, TODAY)]


def test_the_routes_need_the_token_and_a_real_proposal(folder, web):
    run(folder, ai(step()))
    client, store = web
    p = proposal_for(folder.root, "acme")
    assert client.post(f"/autopilot/proposals/{p.id}/approve", data={}).status_code == 403
    assert client.post(f"/autopilot/proposals/{p.id}/discard", data={}).status_code == 403
    token = csrf(client)
    assert client.post("/autopilot/proposals/nope/approve",
                       data={"csrf_token": token}).status_code == 404
    assert client.get("/autopilot/proposals/nope").status_code == 404
    r = client.post(f"/autopilot/proposals/{p.id}/approve",
                    data={"csrf_token": token, "back": "https://example.com/x"})
    assert r.headers["location"].startswith("/today?")      # never off-site


def test_sync_with_next_steps_on_leaves_prepared_items_on_today(folder):
    """The package's done-when: switches on, a fake runner, a sync run, and
    prepared items waiting on Today."""

    class EmptyBox:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def fetch(self):
            return []

        def mark_read(self, uids):
            pass

    cfg = {**config(next_steps=True, reply_drafts=True), "bcc_address": "me+bcc@example.com"}
    answers = lambda prompt: (step() if "next step" in prompt.split("\n")[0]  # noqa: E731
                              else {"channel": "email", "subject": "Re: Prices",
                                    "body": "Hi Jane,\n\nHere are the prices.\n\nSam",
                                    "skip": ""})
    text, code = cli.cmd_sync(folder, folder.root, cfg, apply=True,
                              open_mailbox=lambda: EmptyBox(), resolve=lambda: "",
                              enricher=ai(answers))
    assert code == 0 and "autopilot: next steps: 2 proposed" in text
    queue = today.build(folder, cfg, TODAY)
    kinds = {i.kind for i in queue.items}
    assert autopilot.PREPARED in kinds and today.DRAFT in kinds


def test_with_every_switch_off_no_failure_row_is_left_over(folder):
    autopilot.write_state(folder.root, {"last_run": {"ok": False, "error": "x"}})
    assert autopilot.prepared_items(folder, config(), TODAY) == []
    assert autopilot.prepared_items(folder, {}, TODAY) == []
    rows = autopilot.prepared_items(folder, config(reply_drafts=True), TODAY)
    assert [r.key for r in rows] == ["autopilot-failed"]
