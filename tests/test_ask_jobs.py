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

"""Ask the Hermit as a background job: post, leave, come back to the answer."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from hermitcrm import ask as asking
from hermitcrm import jobs
from hermitcrm.datafolder import init_folder
from hermitcrm.enrich import EnrichError, Enricher
from hermitcrm.store import load_config
from hermitcrm.web import create_app

ALL = lambda binary: f"/usr/local/bin/{binary}"  # noqa: E731


class Scripted:
    """Answers in order (an exception is raised); records the progress line the job
    showed when each call came in."""

    def __init__(self, app, *replies):
        self.app, self.replies, self.lines = app, list(replies), []

    def __call__(self, prompt, schema, **kwargs):
        running = [j for j in self.app.state.jobs.recent() if j.active]
        self.lines.append(running[0].progress if running else None)
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


class Hold:
    def __init__(self):
        self.waiting = []

    def submit(self, fn, *args):
        self.waiting.append((fn, args))

    def go(self):
        while self.waiting:
            fn, args = self.waiting.pop(0)
            fn(*args)

    def shutdown(self, wait=True):
        pass


@pytest.fixture
def app(tmp_path):
    folder = init_folder(tmp_path / "demo", demo=True)
    app = create_app(folder, {**load_config(folder), "push_enabled": False,
                              "owner_email": "me@example.com"})
    app.state.setup_redirected = True
    app.state.calendar_url = lambda refresh=False: ""
    return app


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False)


def ai(app, *replies) -> Scripted:
    runner = Scripted(app, *replies)
    app.state.enricher = Enricher(provider="claude", which=ALL, runner=runner)
    return runner


def ask(client, question="Who needs a follow-up?", **data):
    return client.post("/ask", data={"csrf_token": client.app.state.csrf_token,
                                     "question": question, "page": "/companies", **data})


def job_of(response):
    return parse_qs(urlparse(response.headers["location"]).query)["job"][0]


def test_asking_starts_a_job_and_the_ask_page_shows_its_progress(app, client):
    hold = Hold()
    app.state.jobs.executor = hold
    runner = ai(app, {"answerable": False, "answer": ""},
                {"answer": "Mara Keller, see her note.", "sources": ["contacts/x.md"]})
    r = ask(client)
    assert r.status_code == 303
    job_id = job_of(r)
    assert r.headers["location"] == f"/ask?job={job_id}&page=%2Fcompanies"
    job = app.state.jobs.get(job_id)
    assert job.kind == "ask" and job.label == "Ask: Who needs a follow-up?"
    assert job.back == "/companies" and job.params["question"] == "Who needs a follow-up?"

    waiting = client.get(r.headers["location"]).text      # before it runs
    assert "Who needs a follow-up?" in waiting and "Waiting to start" in waiting
    assert '<noscript><meta http-equiv="refresh" content="3"></noscript>' in waiting
    assert f'data-job="{job_id}" data-job-active' in waiting

    # Meanwhile, any other page: the badge script asks for the running job.
    assert client.get("/jobs/active.json").json()["jobs"][0]["id"] == job_id
    assert client.get("/companies").status_code == 200

    hold.go()
    assert runner.lines == ["Reading this page", "Looking through the whole CRM"]
    assert client.get("/jobs/active.json").json()["jobs"][0]["state"] == "done"  # "ready"
    done = client.get(r.headers["location"]).text
    assert "Mara Keller, see her note." in done and "Searched the whole CRM" in done
    assert "contacts/x.md" in done and "http-equiv" not in done
    assert "data-job-active" not in done
    assert client.get("/jobs/active.json").json() == {"jobs": []}   # opened: badge gone


def test_the_badge_link_opens_the_ask_page(app, client):
    ai(app, {"answerable": True, "answer": "Fine."})
    job_id = job_of(ask(client))
    r = client.get(f"/jobs/{job_id}")
    assert r.status_code == 303 and r.headers["location"] == f"/ask?job={job_id}&page=%2Fcompanies"


def test_a_failed_ask_shows_the_same_message_as_before(app, client):
    ai(app, EnrichError("The AI run timed out after 300 s"))
    r = client.get(ask(client).headers["location"])
    assert r.status_code == 200
    assert "The AI run timed out after 300 s" in r.text
    assert "Who needs a follow-up?" in r.text   # back in the box, to try again


def test_no_question_or_no_ai_is_said_at_once_without_a_job(app, client):
    ai(app)
    r = ask(client, question="  ")
    assert r.status_code == 400 and "Type a question first." in r.text
    app.state.enricher = Enricher(provider=None, which=lambda b: None)
    r = ask(client)
    assert r.status_code == 502 and "errors" in r.text
    assert app.state.jobs.recent() == []


def test_an_answer_survives_a_restart_and_a_running_one_is_interrupted(app, client, tmp_path):
    ai(app, {"answerable": True, "answer": "It survived."})
    kept = job_of(ask(client))
    hold = Hold()
    app.state.jobs.executor = hold
    stuck = ask(client, question="Still running?")
    app.state.jobs.get(job_of(stuck)).state = "running"
    app.state.jobs._save()

    again = create_app(app.state.root, {**load_config(app.state.root), "push_enabled": False,
                                        "owner_email": "me@example.com"})
    again.state.setup_redirected = True
    again.state.calendar_url = lambda refresh=False: ""
    other = TestClient(again, follow_redirects=False)
    assert "It survived." in other.get(f"/ask?job={kept}&page=/companies").text
    page = other.get(stuck.headers["location"]).text
    assert "stopped while this was running" in page and "Still running?" in page
    assert again.state.jobs.get(job_of(stuck)).state == jobs.INTERRUPTED


def test_an_unknown_job_says_so(client):
    page = client.get("/ask?job=gone&page=/").text
    assert "no longer kept" in page


def test_a_retry_from_the_answer_is_a_new_job(app, client):
    runner = ai(app, {"answerable": True, "answer": "First."},
                {"answer": "Deeper.", "sources": []})
    first = job_of(ask(client))
    second = job_of(ask(client, scope="deep", tier="strong"))
    assert first != second
    assert "Deeper." in client.get(f"/ask?job={second}&page=/companies").text
    assert runner.lines == ["Reading this page", "Looking through the whole CRM"]
    assert isinstance(asking.Answer(**app.state.jobs.get(second).result["answer"]),
                      asking.Answer)
