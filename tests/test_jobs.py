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

"""Background jobs: the runner, its file under .git, and the /jobs/ pages."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi.responses import PlainTextResponse

from hermitcrm import jobs
from hermitcrm.enrich import EnrichError
from conftest import copy_git

CLOCK = iter(f"2026-09-14T10:{m:02d}:{s:02d}" for m in range(60) for s in range(60))


def tick() -> str:
    return next(CLOCK)


class Hold:
    """An executor that keeps what it is given: the job stays queued until `go`."""

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
def folder(tmp_path, git_template) -> Path:
    return copy_git(git_template, tmp_path / "crm")


def saved(folder: Path) -> list[dict]:
    return json.loads((folder / ".git" / "hermitcrm-jobs.json").read_text())["jobs"]


# ------------------------------------------------------------------ the runner


def test_a_job_runs_reports_steps_and_keeps_its_result(folder):
    runner = jobs.JobRunner(folder, executor=jobs.Inline(), clock=tick)
    seen = []

    def work(report):
        for n in range(1, 4):
            report(f"Contact {n}", done=n - 1, total=3)
            seen.append(runner.get(job_id).steps)
        report("Finished", done=3)
        return {"lines": ["a", "b", "c"]}

    job_id = None
    hold = Hold()
    runner.executor = hold
    job = runner.start("outreach-batch", "Build 3 drafts", work, back="/outreach")
    job_id = job.id
    assert job.state == "queued" and job.active and runner.active() == [job]
    hold.go()
    assert seen == ["0 of 3", "1 of 3", "2 of 3"]
    assert job.state == "done" and job.steps == "3 of 3" and job.progress == "Finished"
    assert job.result == {"lines": ["a", "b", "c"]} and job.error == ""
    assert job.started and job.ended and job.back == "/outreach"
    [line] = saved(folder)
    assert line["id"] == job.id and line["state"] == "done" and line["result"]["lines"]


def test_a_failed_job_keeps_the_message_the_page_shows(folder, caplog):
    runner = jobs.JobRunner(folder, executor=jobs.Inline(), clock=tick)

    def ai_says_no(report):
        raise EnrichError("No AI CLI found: install Claude Code")

    job = runner.start("ask", "Ask: who?", ai_says_no)
    assert job.state == "failed" and job.error == "No AI CLI found: install Claude Code"
    assert job.result == {} and "failed" not in caplog.text   # expected: not a crash

    def bug(report):
        raise KeyError("x")

    crashed = runner.start("ask", "Ask: why?", bug)
    assert crashed.state == "failed" and crashed.error == "'x'"
    assert "job %s" % crashed.id in caplog.text          # unexpected: logged
    assert [j["state"] for j in saved(folder)] == ["failed", "failed"]


def test_a_job_running_when_the_server_stopped_reads_back_as_interrupted(folder):
    first = jobs.JobRunner(folder, executor=Hold(), clock=tick)
    job = first.start("ask", "Ask: status?", lambda report: {"text": "never"})
    # Run it far enough to be "running" in the file, then lose the process.
    job.state, job.started = "running", tick()
    first._save()
    done = first.start("ask", "Ask: earlier?", lambda report: {})
    done.state, done.ended = "done", tick()
    first._save()

    again = jobs.JobRunner(folder, executor=jobs.Inline(), clock=tick)
    back = again.get(job.id)
    assert back.state == "interrupted" and "start it again" in back.error and back.ended
    assert again.get(done.id).state == "done"
    states = {j["id"]: j["state"] for j in saved(folder)}
    assert states == {job.id: "interrupted", done.id: "done"}
    # A third start finds nothing to change.
    assert jobs.JobRunner(folder, executor=jobs.Inline()).get(job.id).state == "interrupted"


def test_a_missing_or_damaged_file_reads_as_no_jobs(folder):
    assert jobs.JobRunner(folder, executor=jobs.Inline()).recent() == []
    (folder / ".git" / "hermitcrm-jobs.json").write_text("{not json")
    runner = jobs.JobRunner(folder, executor=jobs.Inline())
    assert runner.recent() == []
    (folder / ".git" / "hermitcrm-jobs.json").write_text(
        json.dumps({"jobs": [{"id": "ok1", "kind": "ask", "label": "x", "state": "done"},
                             {"kind": "no id"}, "junk", {"id": "", "kind": "a", "label": "b"}]}))
    assert [j.id for j in jobs.JobRunner(folder, executor=jobs.Inline()).recent()] == ["ok1"]


def test_the_file_keeps_the_newest_fifty(folder):
    runner = jobs.JobRunner(folder, executor=jobs.Inline(), clock=tick)
    made = [runner.start("ask", f"Ask {n}", lambda report: {}) for n in range(jobs.KEEP + 5)]
    kept = [j["id"] for j in saved(folder)]
    assert len(kept) == jobs.KEEP and kept[0] == made[-1].id and made[0].id not in kept
    assert len(runner.recent()) == jobs.KEEP


def test_a_folder_without_git_keeps_the_file_in_the_folder(tmp_path):
    runner = jobs.JobRunner(tmp_path, executor=jobs.Inline())
    runner.start("ask", "x", lambda report: {})
    assert (tmp_path / "hermitcrm-jobs.json").is_file()


def test_seen_jobs_leave_the_active_list(folder):
    runner = jobs.JobRunner(folder, executor=jobs.Inline(), clock=tick)
    job = runner.start("ask", "x", lambda report: {})
    assert runner.active() == [job]          # done, not opened yet: the badge says ready
    runner.mark_seen(job)
    assert runner.active() == [] and saved(folder)[0]["seen"] is True


def test_the_real_pool_runs_jobs_on_daemon_threads(folder):
    runner = jobs.JobRunner(folder, executor=jobs.Pool(), clock=tick)
    release, names = threading.Event(), []
    finished = threading.Event()

    def work(report):
        names.append((threading.current_thread().name, threading.current_thread().daemon))
        assert release.wait(5)
        return {}

    job = runner.start("ask", "x", work)
    second = runner.start("ask", "y", lambda report: finished.set() or {})
    assert finished.wait(5)                    # two workers: the second is not stuck
    assert job.active
    release.set()
    runner.executor.shutdown(wait=True)
    assert job.state == "done" and second.state == "done"
    assert names == [("hermitcrm-job-1", True)]


def test_the_steps_label():
    job = jobs.Job(id="a", kind="k", label="l")
    assert job.steps == ""
    job.total = 20
    assert job.steps == "0 of 20"
    job.done = 3
    assert job.steps == "3 of 20"
    data = job.as_json()
    assert data["steps"] == "3 of 20" and data["url"] == "/jobs/a" and "result" not in data


# -------------------------------------------------------------------- the pages


def test_the_json_endpoints(app, client):
    runner = app.state.jobs
    hold = Hold()
    runner.executor = hold
    # "demo": a kind without a page of its own (an Ask job opens on the Ask page)
    job = runner.start("demo", "Demo: who?", lambda report: report("Reading", 1, 2) or {"x": 1})
    r = client.get(f"/jobs/{job.id}.json")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["state"] == "queued" and r.json()["label"] == "Demo: who?"
    assert [j["id"] for j in client.get("/jobs/active.json").json()["jobs"]] == [job.id]
    hold.go()
    data = client.get(f"/jobs/{job.id}.json").json()
    assert data["state"] == "done" and data["steps"] == "1 of 2" and "result" not in data
    assert client.get("/jobs/nope.json").status_code == 404
    client.get(f"/jobs/{job.id}")                      # opening it
    assert client.get("/jobs/active.json").json() == {"jobs": []}


def test_the_job_page_while_running_refreshes_itself_without_javascript(app, client):
    runner = app.state.jobs
    hold = Hold()
    runner.executor = hold
    job = runner.start("outreach-batch", "Build 3 drafts", lambda report: {}, back="/outreach")
    job.state, job.progress, job.done, job.total = "running", "Mara Keller", 1, 3
    page = client.get(f"/jobs/{job.id}")
    assert page.status_code == 200 and "Build 3 drafts" in page.text
    assert '<noscript><meta http-equiv="refresh" content="3"></noscript>' in page.text
    assert f'data-job="{job.id}" data-job-active' in page.text
    assert "1 of 3" in page.text and "Mara Keller" in page.text and "You can leave" in page.text
    assert not job.seen                          # running: still in the badge


def test_the_job_page_when_done_shows_the_result_and_the_way_back(app, client):
    job = app.state.jobs.start(
        "outreach-batch", "Build 2 drafts",
        lambda report: {"lines": ["Mara Keller: drafted", "Jon Example: skipped"],
                        "link": "/outreach?tab=drafts", "link_text": "Review the drafts"},
        back="/outreach")
    page = client.get(f"/jobs/{job.id}").text
    assert "Done" in page and "http-equiv" not in page and "data-job-active" not in page
    assert "<li>Mara Keller: drafted</li>" in page
    assert 'href="/outreach?tab=drafts">Review the drafts</a>' in page
    assert job.seen


def test_the_job_page_shows_a_failure(app, client):
    def no(report):
        raise EnrichError("The AI run timed out after 300 s")

    job = app.state.jobs.start("demo", "Demo: who?", no)
    page = client.get(f"/jobs/{job.id}").text
    assert "Failed" in page and "The AI run timed out after 300 s" in page


def test_a_kind_with_its_own_view_shows_that_when_done(app, client):
    app.state.jobs.views["demo"] = lambda request, job: (
        PlainTextResponse(f"view {job.id}") if job.state == "done" else None)
    job = app.state.jobs.start("demo", "Demo", lambda report: {})
    assert client.get(f"/jobs/{job.id}").text == f"view {job.id}"

    def no(report):
        raise EnrichError("nope")

    failed = app.state.jobs.start("demo", "Demo", no)   # a failure is the job page's
    assert "nope" in client.get(f"/jobs/{failed.id}").text


def test_an_unknown_job_is_a_404_page(client):
    page = client.get("/jobs/does-not-exist")
    assert page.status_code == 404 and "Job not found" in page.text


def test_polling_starts_no_git_process(app, client, monkeypatch):
    calls = []
    monkeypatch.setattr(app.state.gitops, "last_commit_sha",
                        lambda *a, **k: calls.append(1) or "")
    job = app.state.jobs.start("ask", "x", lambda report: {})
    client.get("/jobs/active.json")
    client.get(f"/jobs/{job.id}.json")
    assert calls == []


def test_every_page_loads_the_badge_script(client):
    page = client.get("/companies").text
    assert '<span id="jobs-badge" hidden></span>' in page and "/static/jobs.js" in page
