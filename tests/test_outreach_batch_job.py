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

"""Build queue and company enrich as background jobs (jobs.py): one click builds
the whole batch with "n of total" progress, one failing contact does not stop it,
and enrich ends on the same preview page as before."""

from __future__ import annotations

from hermitcrm import jobs, outreach
from hermitcrm.enrich import EnrichError, Enricher
from outreach_client import client, commits, post, query, root, fake  # noqa: F401
from outreach_fakes import ALL, FakeAI, default_draft


def job_of(client, response):
    assert response.status_code == 303, response.text
    assert response.headers["location"].startswith("/jobs/"), response.headers["location"]
    return client.app.state.jobs.get(response.headers["location"].rsplit("/", 1)[1])


def build(client, **form):
    return post(client, "/outreach/build", where="stage=prospect", **form)


def running(client):
    return next(j for j in client.app.state.jobs.recent() if j.active)


def test_one_click_builds_three_drafts_with_n_of_total_progress(client, root):
    seen = []

    def draft(prompt):
        job = running(client)
        seen.append((job.steps, job.progress))
        return default_draft(prompt)

    client.app.state.enricher = Enricher(provider="claude", which=ALL,
                                         runner=FakeAI(drafts=[draft]))
    before = len(commits(root))
    job = job_of(client, build(client, limit="3"))
    assert job.kind == "outreach-batch" and job.label == "Build 3 email drafts"
    assert job.state == "done" and job.steps == "3 of 3", job.error
    assert [s for s, _ in seen] == ["0 of 3", "1 of 3", "2 of 3"]
    assert all(p.startswith("Drafting for ") for _, p in seen)
    built = outreach.items(root)
    assert len(built) == 3 and {i.state for i in built} == {"drafted"}
    # Each draft is still its own commits: the research, then the draft.
    assert len(commits(root)) == before + 6
    assert job.result["drafted"] == 3 and len(job.result["lines"]) == 3
    assert all(line.endswith(": drafted") for line in job.result["lines"])
    assert job.result["link"].startswith("/outreach?") and "tab=drafts" in job.result["link"]

    page = client.get(f"/jobs/{job.id}").text
    assert "Build 3 email drafts" in page and "3 of 3" in page and "Review the drafts" in page


def test_one_failing_contact_is_a_line_and_the_batch_goes_on(client, root):
    def draft(prompt):
        if "Person: Mara" in prompt:
            raise RuntimeError("the AI tool crashed")
        return default_draft(prompt)

    client.app.state.enricher = Enricher(provider="claude", which=ALL,
                                         runner=FakeAI(drafts=[draft]))
    job = job_of(client, build(client, limit="3"))
    assert job.state == "done" and job.steps == "3 of 3"
    failed = [line for line in job.result["lines"] if "not built" in line]
    assert len(failed) == 1 and "Mara Keller" in failed[0] and "crashed" in failed[0]
    assert job.result["drafted"] == 2
    assert sum(i.state == "drafted" for i in outreach.items(root)) == 2
    assert "not built (the AI tool crashed)" in client.get(f"/jobs/{job.id}").text


def test_a_second_batch_waits_for_the_first(client, root):
    hold = []
    client.app.state.jobs.executor = type("Hold", (), {
        "submit": lambda self, fn, *a: hold.append((fn, a)),
        "shutdown": lambda self, wait=True: None})()
    first = job_of(client, build(client, limit="2"))
    again = build(client, limit="2")
    assert again.headers["location"].startswith(f"/jobs/{first.id}?")
    assert "already building" in query(again)["flash"]
    assert [j.kind for j in client.app.state.jobs.recent()] == ["outreach-batch"]
    fn, args = hold.pop()
    fn(*args)
    assert first.state == "done" and len(outreach.items(root)) == 2


def test_nothing_to_build_is_said_at_once_without_a_job(client, root):
    response = post(client, "/outreach/build", where="stage=won", limit="3")
    assert response.status_code == 303 and response.headers["location"].startswith("/outreach")
    assert "Nothing to build" in query(response)["flash"]
    assert client.app.state.jobs.recent() == []


def test_the_generate_panel_still_drafts_one_person_in_the_request(client, root):
    response = post(client, "/outreach/build", contact="lindenhof-data/mara-keller",
                    back="/outreach")
    assert response.headers["location"].startswith("/outreach")
    assert client.app.state.jobs.recent() == []
    assert [i.record for i in outreach.items(root)] == ["lindenhof-data/mara-keller"]


def test_a_batch_interrupted_by_a_restart_says_so(client, root):
    hold = []
    client.app.state.jobs.executor = type("Hold", (), {
        "submit": lambda self, fn, *a: hold.append((fn, a)),
        "shutdown": lambda self, wait=True: None})()
    job = job_of(client, build(client, limit="2"))
    job.state, job.done, job.total = "running", 1, 2
    client.app.state.jobs._save()
    again = jobs.JobRunner(root, executor=jobs.Inline())
    back = again.get(job.id)
    assert back.state == "interrupted" and back.steps == "1 of 2"


# ------------------------------------------------------------------ enrich


def test_enrich_runs_as_a_job_then_shows_the_preview(client, root):
    calls = []

    def runner(prompt, schema, **kwargs):
        job = running(client)
        calls.append((job.kind, job.progress))
        return {"website": "https://lindenhof.example.com", "sources": [], "notes": ""}

    client.app.state.enricher = Enricher(provider="claude", which=ALL, runner=runner)
    slug = "lindenhof-data"
    client.app.state.store.update_company(slug, website="")
    name = client.app.state.store.companies[slug].name
    job = job_of(client, client.post(f"/companies/{slug}/enrich"))
    assert job.kind == "enrich" and job.label == f"Enrich {name}" and job.state == "done"
    assert calls == [("enrich", f"Looking up {name}")]
    page = client.get(f"/jobs/{job.id}")
    assert page.status_code == 200 and f"Enrich {name}" in page.text
    assert 'value="https://lindenhof.example.com"' in page.text
    assert f'action="/companies/{slug}/enrich/apply"' in page.text
    assert job.seen


def test_a_failed_enrich_shows_the_same_message_on_the_company_page(client, root):
    def runner(prompt, schema, **kwargs):
        raise EnrichError("'claude' timed out after 180 s")

    client.app.state.enricher = Enricher(provider="claude", which=ALL, runner=runner)
    slug = next(iter(client.app.state.store.companies))
    job = job_of(client, client.post(f"/companies/{slug}/enrich"))
    assert job.state == "failed"
    r = client.get(f"/jobs/{job.id}")
    assert r.status_code == 303 and r.headers["location"].startswith(f"/companies/{slug}?")
    assert query(r)["flash"] == "'claude' timed out after 180 s"


def test_an_enrich_job_while_it_runs_is_the_progress_page(client, root):
    hold = []
    client.app.state.jobs.executor = type("Hold", (), {
        "submit": lambda self, fn, *a: hold.append((fn, a)),
        "shutdown": lambda self, wait=True: None})()
    slug = next(iter(client.app.state.store.companies))
    job = job_of(client, client.post(f"/companies/{slug}/enrich"))
    page = client.get(f"/jobs/{job.id}")
    assert page.status_code == 200 and "Waiting to start" in page.text
    assert 'http-equiv="refresh"' in page.text
