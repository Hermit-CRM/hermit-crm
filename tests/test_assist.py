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

"""The after-contact assistant (assist.py): the switch, the one AI call per
interaction (a fake AI, never a real one), the quote check, the proposals and
accepting them, the hook on every way an interaction is logged, and the pages."""

from __future__ import annotations

import re
import subprocess
from datetime import timedelta
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient

from hermitcrm import assist, autopilot, cli, routines, today
from hermitcrm.enrich import EnrichError, Enricher
from hermitcrm.store import Store
from hermitcrm.web import create_app
from conftest import CONFIG as APP_CONFIG, FIXED_NOW

ALL = lambda binary: f"/usr/local/bin/{binary}"  # noqa: E731
TODAY = FIXED_NOW.date()
SOON = (TODAY + timedelta(days=7)).isoformat()
ON = {"push_enabled": False, "owner_name": "Sam Example", "after_contact": True}
OFF = {"push_enabled": False, "owner_name": "Sam Example"}

CALL = ("Talked with Jane about the pilot. We agreed to start a pilot in October. "
        "Their budget is 1200 EUR a month. She will send the security questionnaire "
        "by Friday. Let's meet again next week to go through it.")


class FakeAI:
    """Stands in for the AI CLI: each answer is a value, a function of the prompt,
    or an exception to raise. Records every call."""

    def __init__(self, *answers):
        self.answers = list(answers) or [answer()]
        self.calls = []

    def __call__(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        got = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(got, BaseException):
            raise got
        return got(prompt) if callable(got) else got


def answer(step="Go through the questionnaire with Jane", due=SOON,
           step_quote="Let's meet again next week to go through it.",
           to="", reason="", stage_quote="", facts=()):
    return {"next_step": {"text": step, "due": due, "quote": step_quote},
            "stage": {"to": to, "reason": reason, "quote": stage_quote},
            "facts": [{"field": f, "value": v, "quote": q} for f, v, q in facts]}


def ai(*answers) -> Enricher:
    return Enricher(provider="claude", which=ALL, runner=FakeAI(*answers))


def at(days_ago: int, hour: int = 10) -> str:
    return (FIXED_NOW - timedelta(days=days_ago)).strftime(f"%Y-%m-%dT{hour:02d}:00")


def seed(store: Store) -> None:
    store.create_company("Acme GmbH", country="DE")
    store.create_contact("acme", "Jane", "Doe", email="jane@acme.example.com")
    for n, days in enumerate((20, 15, 10, 5), start=1):
        store.create_interaction("acme", channel="email", direction="out",
                                 contact="jane-doe", date=at(days),
                                 body=f"Earlier message number {n} about the product.")


@pytest.fixture
def folder(repo):
    store = Store(repo, clock=lambda: FIXED_NOW)
    store.load()
    store.on_write = cli._writer(store, repo, {"push_enabled": False})
    seed(store)
    return store


def log_call(store, body=CALL, days_ago=0, contact="jane-doe", slug="acme"):
    return store.create_interaction(slug, channel="call", direction="out", contact=contact,
                                    date=at(days_ago, 9), body=body)


def git_log(root) -> list[str]:
    return subprocess.run(["git", "log", "--format=%s"], cwd=root, capture_output=True,
                          text=True).stdout.splitlines()


# ------------------------------------------------------------------ the switch


@pytest.mark.parametrize("value, on", [(True, True), (False, False), ("true", False),
                                       (1, False), (None, False)])
def test_only_a_real_true_turns_it_on(value, on):
    assert assist.enabled({"after_contact": value}) is on
    assert assist.enabled({}) is False and assist.enabled(None) is False


def test_the_switch_is_not_in_new_folders(tmp_path):
    from hermitcrm.store import DEFAULT_CONFIG
    assert "after_contact" not in DEFAULT_CONFIG


def test_off_makes_no_ai_call_builds_no_enricher_and_starts_no_job(folder, monkeypatch):
    def boom(config):
        raise AssertionError("no enricher may be built with the switch off")

    monkeypatch.setattr(routines, "default_enricher", boom)
    fake = ai()
    it = log_call(folder)

    class NoJobs:
        def start(self, *a, **k):
            raise AssertionError("no job may start with the switch off")

    assert assist.after_logged(folder, OFF, [("acme", it.id)], jobs=NoJobs(),
                               enricher=fake) == ""
    assert assist.after_logged(folder, {**OFF, "after_contact": "yes"}, [("acme", it.id)],
                               enricher=fake) == ""
    assert fake.runner.calls == []
    watch = assist.Watch(folder, OFF)
    assert watch.before is None
    log_call(folder, days_ago=1)
    assert watch.queue(enricher=fake) == "" and fake.runner.calls == []
    assert autopilot.proposals(folder.root) == []


# ------------------------------------------------------------------- the call


def test_one_light_call_without_tools_with_the_interaction_three_before_and_fields(folder):
    fake = ai(answer())
    it = log_call(folder)
    result = assist.propose(folder, ON, "acme", it.id, fake)
    assert result == {"proposed": 1, "dropped": []}
    [call] = fake.runner.calls
    assert call["tools"] == ""
    assert call["schema"]["required"] == ["next_step", "stage", "facts"]
    prompt = call["prompt"]
    assert CALL in prompt
    assert "name: Acme GmbH" in prompt and "stage: engaged" in prompt
    for n in (2, 3, 4):
        assert f"Earlier message number {n}" in prompt
    assert "Earlier message number 1" not in prompt    # the fourth before it
    assert "Jane Doe" in prompt


def test_the_light_tier_is_asked_for(folder):
    seen = []
    base = Enricher(provider="claude", which=ALL, runner=FakeAI(answer()))
    real = base.with_tier

    def spy(tier):
        seen.append(tier)
        return real(tier)

    base.with_tier = spy
    assist.propose(folder, ON, "acme", log_call(folder).id, base)
    assert seen == ["light"]


def test_earlier_is_by_date_not_by_logging_order(folder):
    late = log_call(folder, body="A backdated call logged after the others.", days_ago=12)
    names = [i.body.strip() for i in assist.earlier(folder.get("acme"), late)]
    assert names == ["Earlier message number 2 about the product.",
                     "Earlier message number 1 about the product."]


# ---------------------------------------------------------------- the checks


@pytest.mark.parametrize("quote, ok", [
    ("We agreed to start a pilot in October.", True),
    ("  We agreed   to start a pilot\nin October.  ", True),
    ("“We agreed to start a pilot in October.”", True),
    ("We agreed to start a pilot in November.", False),   # not word for word
    ("we agreed to start a pilot in october.", False),     # exact, case too
    ("a pilot", False),                                    # too short to prove anything
    ("", False),
])
def test_a_quote_must_be_in_the_interaction_word_for_word(folder, quote, ok):
    assert assist.found(quote, log_call(folder)) is ok


def test_proposals_whose_sentence_is_not_in_the_interaction_are_dropped(folder):
    it = log_call(folder)
    data = answer(step_quote="We will meet on Monday at noon.", to="discovery",
                  reason="They agreed to a pilot.",
                  stage_quote="They signed the order form today.",
                  facts=[("value_eur_month", "1200", "Their budget is 2000 EUR a month."),
                         ("note", "Pilot starts in October",
                          "We agreed to start a pilot in October.")])
    made, dropped = assist.clean(data, folder, folder.get("acme"), it, TODAY, [], FIXED_NOW)
    assert [(p.kind, p.text) for p in made] == [("note", "Pilot starts in October")]
    assert len(dropped) == 3
    assert all("not in the interaction" in why for why in dropped)


def test_a_stage_move_only_to_a_configured_stage_it_may_move_to(folder):
    it = log_call(folder)
    company = folder.get("acme")
    quote = "We agreed to start a pilot in October."
    for to in ("negotiating-forever", "engaged"):   # unknown; where it already is
        made, dropped = assist.clean(answer(step="", to=to, reason="x", stage_quote=quote),
                                     folder, company, it, TODAY, [], FIXED_NOW)
        assert made == [] and "is not a stage" in dropped[0]
    made, _ = assist.clean(answer(step="", to="discovery", reason="They agreed to a pilot.",
                                  stage_quote=quote), folder, company, it, TODAY, [],
                           FIXED_NOW)
    assert [(p.kind, p.text) for p in made] == [("stage-move", "discovery")]
    assert made[0].why == ("after the call: They agreed to a pilot. “We agreed to start "
                           "a pilot in October.”")


def test_facts_value_custom_field_and_note(folder):
    (folder.root / "fields.toml").write_text(
        '[[field]]\nkey = "security_review"\ntype = "text"\nenrich = true\n\n'
        '[[field]]\nkey = "seats"\ntype = "number"\nenrich = true\n\n'
        '[[field]]\nkey = "hidden_field"\ntype = "text"\n', encoding="utf-8")
    defs = assist.enrich_fields(folder.root)
    assert [d.key for d in defs] == ["security_review", "seats"]
    it = log_call(folder)
    data = answer(step="", facts=[
        ("value_eur_month", "1,200", "Their budget is 1200 EUR a month."),
        ("security_review", "questionnaire by Friday",
         "She will send the security questionnaire by Friday."),
        ("seats", "many", "She will send the security questionnaire by Friday."),
        ("hidden_field", "x", "She will send the security questionnaire by Friday."),
        ("note", "Pilot in October", "We agreed to start a pilot in October."),
        ("note", "ignored: only five are read", "We agreed to start a pilot in October."),
    ])
    made, dropped = assist.clean(data, folder, folder.get("acme"), it, TODAY, defs,
                                 FIXED_NOW)
    assert [p.text for p in made] == ["Monthly value (EUR): 1200",
                                      "security review: questionnaire by Friday",
                                      "Pilot in October"]
    assert dropped == ["seats: seats wants a number, got 'many'",
                       "hidden_field: not a field it may fill"]
    assert [p.extra["field"] for p in made] == ["value_eur_month", "security_review", "note"]
    assert [p.kind for p in made] == ["fact", "fact", "note"]
    assert all(p.basis == it.id and p.contact == "jane-doe" for p in made)


def test_a_next_step_with_a_bad_date_is_dropped(folder):
    it = log_call(folder)
    far = (TODAY + timedelta(days=400)).isoformat()
    made, dropped = assist.clean(answer(due=far), folder, folder.get("acme"), it, TODAY, [],
                                 FIXED_NOW)
    assert made == [] and dropped[0].startswith("next step: the date")


def test_an_answer_that_is_not_an_object_is_rejected(folder):
    with pytest.raises(routines.Rejected):
        assist.clean(["no"], folder, folder.get("acme"), log_call(folder), TODAY, [],
                     FIXED_NOW)


def test_a_newer_proposal_replaces_the_one_waiting_in_its_slot(folder):
    first = log_call(folder, days_ago=1)
    assist.propose(folder, ON, "acme", first.id, ai(answer(step="Call Jane back")))
    second = log_call(folder)
    assist.propose(folder, ON, "acme", second.id, ai(answer()))
    steps = autopilot.proposals(folder.root, autopilot.NEXT_STEP)
    assert [(p.text, p.basis) for p in steps] == [
        ("Go through the questionnaire with Jane", second.id)]


# ------------------------------------------------------------------ accepting


def proposals_of(root, kind):
    return [p for p in autopilot.proposals(root) if p.kind == kind]


def test_accepting_each_kind_is_one_commit_and_the_interaction_stays_byte_for_byte(folder):
    (folder.root / "fields.toml").write_text(
        '[[field]]\nkey = "security_review"\ntype = "text"\nenrich = true\n',
        encoding="utf-8")
    it = log_call(folder)
    path = next((folder.root / "companies" / "acme" / "interactions").glob(f"{it.id}*"))
    before = path.read_bytes()
    quote = "We agreed to start a pilot in October."
    assist.propose(folder, ON, "acme", it.id, ai(answer(
        to="discovery", reason="A pilot is agreed.", stage_quote=quote,
        facts=[("value_eur_month", "1200", "Their budget is 1200 EUR a month."),
               ("security_review", "questionnaire by Friday",
                "She will send the security questionnaire by Friday."),
               ("note", "Pilot in October", quote)])))
    assert len(autopilot.proposals(folder.root)) == 5
    for p in autopilot.proposals(folder.root):
        commits = len(git_log(folder.root))
        autopilot.approve_proposal(folder, p.id)
        assert len(git_log(folder.root)) == commits + 1, p.kind
    folder.load()
    acme = folder.get("acme")
    assert acme.stage == "discovery"
    assert acme.value_eur_month == 1200
    assert acme.extra["security_review"] == "questionnaire by Friday"
    assert acme.next_todo().text == "Go through the questionnaire with Jane"
    assert any(i.is_note and i.body.strip() == "Pilot in October"
               and i.contact == "jane-doe" for i in acme.interactions)
    assert path.read_bytes() == before
    assert autopilot.proposals(folder.root) == []


def test_a_next_step_whose_person_was_deleted_goes_on_the_company(folder):
    it = log_call(folder)
    assist.propose(folder, ON, "acme", it.id, ai(answer()))
    [p] = autopilot.proposals(folder.root)
    folder.create_contact("acme", "Ann", "Lee")
    autopilot.update_proposal(folder, p.id, p.text, p.due)
    found = autopilot.get_proposal(folder.root, p.id)
    found.contact = "nobody-here"
    autopilot.remove_proposal(folder, p.id)
    autopilot.add_proposals(folder, [found])
    autopilot.approve_proposal(folder, found.id)
    todo = folder.get("acme").next_todo()
    assert todo.text == "Go through the questionnaire with Jane" and todo.contact is None


def test_an_edited_fact_keeps_its_label_or_takes_the_whole_text(folder):
    it = log_call(folder)
    assist.propose(folder, ON, "acme", it.id, ai(answer(step="", facts=[
        ("value_eur_month", "1200", "Their budget is 1200 EUR a month.")])))
    [p] = autopilot.proposals(folder.root)
    autopilot.update_proposal(folder, p.id, "1500", "")
    assert autopilot.approve_proposal(folder, p.id) == "Monthly value saved for Acme GmbH"
    assert folder.get("acme").value_eur_month == 1500


def test_a_value_the_store_refuses_stays_a_proposal(folder):
    from hermitcrm.models import ValidationError
    it = log_call(folder)
    assist.propose(folder, ON, "acme", it.id, ai(answer(step="", facts=[
        ("value_eur_month", "1200", "Their budget is 1200 EUR a month.")])))
    [p] = autopilot.proposals(folder.root)
    autopilot.update_proposal(folder, p.id, "Monthly value (EUR): lots", "")
    with pytest.raises(ValidationError):
        autopilot.approve_proposal(folder, p.id)
    assert [q.id for q in autopilot.proposals(folder.root)] == [p.id]


def test_today_shows_them_under_prepared_for_you(folder):
    it = log_call(folder)
    assist.propose(folder, ON, "acme", it.id, ai(answer(
        to="discovery", reason="A pilot is agreed.",
        stage_quote="We agreed to start a pilot in October.")))
    rows = [i for i in today.build(folder, ON, TODAY).items if i.kind == autopilot.PREPARED]
    # Today keeps one row per company and kind, standing for the rest (today.py).
    [row] = rows
    assert row.count == 2 and row.contact.slug == "jane-doe"
    assert row.title in ("Move to stage: discovery",
                         "Next step: Go through the questionnaire with Jane")
    assert row.reason.startswith("Proposed ") and "after the call: " in row.reason


# ------------------------------------------------------------- the hook, bulk


def test_one_job_per_person_newest_first_at_most_ten(folder):
    for n in range(12):
        folder.create_company(f"Lead {n:02d}")
        folder.create_interaction(f"lead-{n:02d}", channel="note", direction="",
                                  date=at(n), body="A note long enough to be worth asking.")
    pairs = [(f"lead-{n:02d}", folder.get(f"lead-{n:02d}").interactions[0].id)
             for n in range(12)]
    # Two messages of one thread logged at once: only the newest is asked about.
    older = log_call(folder, days_ago=3, body="An older message of the same thread here.")
    newer = log_call(folder, days_ago=2, body="The newer message of the same thread here.")
    short = log_call(folder, body="ok")
    chosen, more = assist.pick(folder, pairs + [("acme", older.id), ("acme", newer.id),
                                                ("acme", short.id)])
    assert len(chosen) == 10 and more == 3
    got = [(c.slug, i.id) for c, i in chosen]
    assert got[:4] == [pairs[0], pairs[1], pairs[2], ("acme", newer.id)]
    assert ("acme", older.id) not in got and ("acme", short.id) not in got


def test_an_import_names_what_it_skipped(folder):
    for n in range(12):
        folder.create_company(f"Lead {n:02d}")
    watch = assist.Watch(folder, ON)
    for n in range(12):
        folder.create_interaction(f"lead-{n:02d}", channel="email", direction="in",
                                  date=at(n), body="Please send me the price list today.")
    fake = ai(answer(step=""))
    line = watch.queue(enricher=fake)
    assert len(fake.runner.calls) == 10
    assert line == ("after-contact suggestions: 0 suggestions for 10 interactions; "
                    "2 more skipped (at most 10 per import)")


def test_without_an_ai_tool_nothing_is_asked_and_settings_says_why(folder):
    nothing = Enricher(provider="nonexistent-cli", which=lambda b: None)
    line = assist.after_logged(folder, ON, [("acme", log_call(folder).id)],
                               enricher=nothing)
    assert line.startswith("after-contact suggestions skipped: ")
    assert assist.failure(folder.root) == line.removeprefix(
        "after-contact suggestions skipped: ")


def test_a_failing_call_is_recorded_not_raised(folder):
    line = assist.after_logged(folder, ON, [("acme", log_call(folder).id)],
                               enricher=ai(EnrichError("the login lapsed")))
    assert line.endswith("1 failed: Acme GmbH: the login lapsed")
    assert assist.failure(folder.root) == "Acme GmbH: the login lapsed"


ME = "Sam Owner <me@work.example.com>"
BCC = {"bcc_address": "me+bcc@gmail.com", "my_addresses": ["me@work.example.com"],
       "push_enabled": False}


def mail(n: int) -> bytes:
    msg = EmailMessage()
    msg["From"] = ME
    msg["To"] = f"Person {n} <p{n}@lead{n}.example.com>"
    msg["Subject"] = f"Pricing {n}"
    msg["Date"] = f"Mon, {n + 1:02d} Sep 2026 10:30:00 -0000"
    msg["Message-ID"] = f"<m{n}@work.example.com>"
    msg.set_content("Here is the price list you asked for. Shall we talk next week?\n")
    return bytes(msg)


def test_bcc_import_queues_at_most_ten_and_says_so_in_its_summary(folder, tmp_path):
    paths = []
    for n in range(12):
        folder.create_company(f"Lead {n}", website=f"lead{n}.example.com")
        folder.create_contact(f"lead-{n}", "Person", str(n), email=f"p{n}@lead{n}.example.com")
        path = tmp_path / f"{n}.eml"
        path.write_bytes(mail(n))
        paths.append(path)
    fake = ai(answer(step="Call to talk about the price list",
                     step_quote="Shall we talk next week?"))
    text, code = cli.cmd_bcc(folder, folder.root, {**BCC, **ON}, apply=True, eml=paths,
                             enricher=fake)
    assert code == 0
    assert "12 interactions logged" in text
    assert text.splitlines()[-1] == ("After-contact suggestions: 10 suggestions for 10 "
                                     "interactions; 2 more skipped (at most 10 per import)")
    assert len(fake.runner.calls) == 10
    assert len(proposals_of(folder.root, autopilot.NEXT_STEP)) == 10


def test_bcc_import_with_the_switch_off_asks_nothing(folder, tmp_path):
    path = tmp_path / "one.eml"
    path.write_bytes(mail(1))
    fake = ai()
    text, _ = cli.cmd_bcc(folder, folder.root, BCC, apply=True, eml=[path], enricher=fake)
    assert "after-contact" not in text.lower() and fake.runner.calls == []


def test_a_dry_run_asks_nothing(folder, tmp_path):
    path = tmp_path / "one.eml"
    path.write_bytes(mail(1))
    fake = ai()
    cli.cmd_bcc(folder, folder.root, {**BCC, **ON}, apply=False, eml=[path], enricher=fake)
    assert fake.runner.calls == []


# ------------------------------------------------------------------ the web app


@pytest.fixture
def web(folder):
    def make(config, *answers):
        app = create_app(folder.root, config={**APP_CONFIG, **config})
        app.state.store.clock = lambda: FIXED_NOW
        app.state.enricher = ai(*answers)
        return TestClient(app, follow_redirects=False), app
    return make


def csrf(client) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get("/today").text).group(1)


def post_call(client):
    return client.post("/companies/acme/interactions",
                       data={"channel": "call", "direction": "out", "contact": "jane-doe",
                             "date": at(0, 9), "subject": "", "outcome": "", "body": CALL})


def test_logging_a_call_shows_a_suggestion_you_accept_in_one_click(web):
    client, app = web({"after_contact": True}, answer())
    r = post_call(client)
    assert r.status_code == 303
    assert "flash=Interaction%20logged%3B%20suggestions%20on%20the%20way" in r.headers["location"]
    page = client.get("/companies/acme/contacts/jane-doe").text
    assert 'id="suggestions"' in page and "Go through the questionnaire with Jane" in page
    [p] = autopilot.proposals(app.state.root)
    assert f'action="/assist/proposals/{p.id}/accept"' in page
    assert f'action="/assist/proposals/{p.id}/dismiss"' in page
    assert "Go through the questionnaire with Jane" in client.get("/companies/acme").text
    assert "Go through the questionnaire with Jane" in client.get("/today").text

    r = client.post(f"/assist/proposals/{p.id}/accept",
                    data={"csrf_token": csrf(client),
                          "back": "/companies/acme/contacts/jane-doe"})
    assert r.status_code == 303
    assert r.headers["location"].startswith("/companies/acme/contacts/jane-doe?flash=Next")
    assert r.headers["location"].endswith("#suggestions")
    store = app.state.store
    store.load()
    todo = store.get("acme").next_todo()
    assert todo.text == "Go through the questionnaire with Jane"
    assert todo.contact.slug == "jane-doe"      # the person the call was with
    assert "Go through the questionnaire with Jane" in client.get(
        "/companies/acme/contacts/jane-doe").text.split("Next for Jane")[1][:300]
    assert autopilot.proposals(app.state.root) == []
    assert 'id="suggestions"' not in client.get("/companies/acme/contacts/jane-doe").text
    # The single job is "ready" in the badge until opened; opening it goes to the record.
    [job] = [j for j in app.state.jobs.recent() if j.kind == assist.JOB_KIND]
    assert job.state == "done" and not job.seen
    r = client.get(f"/jobs/{job.id}")
    assert r.status_code == 303 and r.headers["location"].startswith("/companies/acme?flash=1")
    assert app.state.jobs.get(job.id).seen


def test_with_the_switch_off_logging_makes_no_ai_call(web):
    client, app = web({}, answer())
    r = post_call(client)
    assert r.status_code == 303
    assert r.headers["location"].split("#")[0].endswith("flash=Interaction%20logged")
    assert app.state.enricher.runner.calls == []
    assert [j for j in app.state.jobs.recent() if j.kind == assist.JOB_KIND] == []
    assert 'id="suggestions"' not in client.get("/companies/acme").text


def test_dismiss_drops_it_and_a_second_click_is_a_message(web):
    client, app = web({"after_contact": True}, answer())
    post_call(client)
    [p] = autopilot.proposals(app.state.root)
    token = csrf(client)
    r = client.post(f"/assist/proposals/{p.id}/dismiss",
                    data={"csrf_token": token, "back": "/companies/acme"})
    assert r.headers["location"] == "/companies/acme?flash=Suggestion%20dismissed#suggestions"
    assert autopilot.proposals(app.state.root) == []
    for action in ("accept", "dismiss"):
        r = client.post(f"/assist/proposals/{p.id}/{action}",
                        data={"csrf_token": token, "back": "https://example.com/x"})
        assert r.status_code == 303
        assert r.headers["location"].startswith("/today?flash=That%20suggestion%20is%20gone")


def test_accept_and_dismiss_need_the_csrf_token(web):
    client, app = web({"after_contact": True}, answer())
    post_call(client)
    [p] = autopilot.proposals(app.state.root)
    for action in ("accept", "dismiss"):
        assert client.post(f"/assist/proposals/{p.id}/{action}",
                           data={"back": "/today"}).status_code == 403
    assert len(autopilot.proposals(app.state.root)) == 1


def test_a_thread_logged_at_once_is_asked_about_once_with_its_newest_message(web):
    client, app = web({"after_contact": True}, answer(step=""))
    store = app.state.store
    ids = [store.create_interaction("acme", channel="linkedin", direction=d,
                                    contact="jane-doe", date=at(n, 9),
                                    body=f"LinkedIn message number {n} in the thread.").id
           for n, d in ((2, "out"), (1, "in"))]
    line = assist.after_logged(store, app.state.config, [("acme", i) for i in ids],
                               jobs=app.state.jobs, enricher=app.state.enricher)
    assert line == "suggestions on the way"
    [call] = app.state.enricher.runner.calls
    assert "LinkedIn message number 1 in the thread." in call["prompt"].split(
        "--- the NEW interaction ---")[1].split("--- end ---")[0]


class FakeBox:
    def __init__(self, raws):
        self.raws = list(raws)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def fetch(self):
        return [(str(i).encode(), raw) for i, raw in enumerate(self.raws)]

    def mark_read(self, uids):
        pass


def test_the_bcc_import_button_queues_jobs_and_says_so(web):
    client, app = web({**BCC, "after_contact": True},
                      answer(step="Call to talk about the price list",
                             step_quote="Shall we talk next week?"))
    store = app.state.store
    for n in (1, 2):
        store.create_company(f"Lead {n}", website=f"lead{n}.example.com")
        store.create_contact(f"lead-{n}", "Person", str(n), email=f"p{n}@lead{n}.example.com")
    app.state.open_mailbox = lambda: FakeBox([mail(1), mail(2)])
    r = client.post("/bcc/import")
    assert r.status_code == 303
    assert "after-contact%20suggestions%20on%20the%20way%20for%202%20interactions" \
        in r.headers["location"]
    assert sorted(p.company for p in autopilot.proposals(app.state.root)) == ["lead-1",
                                                                             "lead-2"]
    # Jobs of an import leave the badge once they worked: Today shows the result.
    assert [j for j in app.state.jobs.active() if j.kind == assist.JOB_KIND] == []


def test_settings_switch_saves_commits_and_shows(web):
    client, app = web({})
    html = client.get("/settings").text
    section = html.split('id="after-contact"')[1].split("</section>")[0]
    assert html.index('id="autopilot"') < html.index('id="after-contact"') < \
        html.index('id="appearance"')
    assert 'action="/settings/after-contact"' in section and "checked" not in section
    r = client.post("/settings/after-contact", data={"csrf_token": csrf(client), "on": "1"})
    assert r.status_code == 303 and r.headers["location"].endswith("#after-contact")
    text = (app.state.root / "config.toml").read_text(encoding="utf-8")
    assert "after_contact = true" in text
    assert "after_contact" in git_log(app.state.root)[0]
    section = client.get("/settings").text.split('id="after-contact"')[1].split("</section>")[0]
    assert "checked" in section and "Has not run yet." in section
    assert app.state.config.get("after_contact") is True
    r = client.post("/settings/after-contact", data={"csrf_token": csrf(client)})
    assert "after_contact = false" in (app.state.root / "config.toml").read_text("utf-8")
    assert client.post("/settings/after-contact", data={"on": "1"}).status_code == 403


def test_settings_shows_a_failed_run(web, folder):
    client, app = web({"after_contact": True})
    assist.after_logged(folder, {"after_contact": True}, [("acme", log_call(folder).id)],
                        enricher=ai(EnrichError("the login lapsed")))
    section = client.get("/settings").text.split('id="after-contact"')[1].split("</section>")[0]
    assert "Could not run" in section and "the login lapsed" in section


def test_a_crash_in_the_assistant_never_fails_the_logging(web, monkeypatch):
    client, app = web({"after_contact": True}, answer())

    def broken(*args, **kwargs):
        raise RuntimeError("something unexpected")

    monkeypatch.setattr(assist, "pick", broken)
    r = post_call(client)
    assert r.status_code == 303
    assert "after-contact%20suggestions%20failed" in r.headers["location"]
    assert app.state.store.get("acme").interactions[0].body.startswith("Talked with Jane")
    assert assist.failure(app.state.root) == "RuntimeError: something unexpected"


def test_today_names_a_note_once(folder):
    it = log_call(folder)
    assist.propose(folder, ON, "acme", it.id, ai(answer(step="", facts=[
        ("note", "Pilot in October", "We agreed to start a pilot in October.")])))
    [row] = [i for i in today.build(folder, ON, TODAY).items if i.kind == autopilot.PREPARED]
    assert row.title == "Note: Pilot in October"


def test_accepted_changes_read_plainly_in_the_undo_line(folder):
    from hermitcrm import history
    (folder.root / "fields.toml").write_text(
        '[[field]]\nkey = "security_review"\ntype = "text"\nenrich = true\n',
        encoding="utf-8")
    it = log_call(folder)
    assist.propose(folder, ON, "acme", it.id, ai(answer(
        step="", to="discovery", reason="A pilot is agreed.",
        stage_quote="We agreed to start a pilot in October.",
        facts=[("value_eur_month", "1200", "Their budget is 1200 EUR a month."),
               ("security_review", "questionnaire by Friday",
                "She will send the security questionnaire by Friday.")])))
    said = []
    for p in autopilot.proposals(folder.root):
        autopilot.approve_proposal(folder, p.id)
        said.append(history.plain_subject(git_log(folder.root)[0]))
    assert said == ["Stage engaged → discovery", "Company details changed",
                    "Company details changed"]
