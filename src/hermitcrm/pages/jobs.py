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

"""Background jobs (jobs.py): the progress page and the two JSON endpoints that
static/jobs.js polls. Registered by pages.register.

Everything here is a GET under /jobs/, which the per-request sweep in web.py skips:
a poll a second must not start a git process each time.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ._ctx import ctx

router = APIRouter()

REFRESH_SECONDS = 3   # the job page reloads itself this often while JavaScript is off

NO_STORE = {"Cache-Control": "no-store"}


def runner(request: Request):
    return request.app.state.jobs


@router.get("/jobs/active.json")
def jobs_active(request: Request):
    """Running jobs, and finished ones not opened yet: what the top-bar badge shows."""
    return JSONResponse({"jobs": [j.as_json() for j in runner(request).active()]},
                        headers=NO_STORE)


@router.get("/jobs/{job_id}.json")
def job_json(request: Request, job_id: str):
    job = runner(request).get(job_id)
    if job is None:
        return JSONResponse({"error": "unknown job"}, status_code=404, headers=NO_STORE)
    return JSONResponse(job.as_json(), headers=NO_STORE)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    """Progress while it runs; when done, what the job's own view shows (an answer,
    an enrich preview) or the result lines here, with the way back."""
    jobs = runner(request)
    job = jobs.get(job_id)
    c = ctx(request)
    if job is None:
        return c.render(request, "job.html", {"job": None}, status_code=404)
    view = jobs.views.get(job.kind)
    shown = view(request, job) if view is not None else None
    if shown is not None:   # the kind's own page (Ask's answer, an enrich preview)
        return shown
    if job.finished:
        jobs.mark_seen(job)
    # While it runs the page refreshes itself without JavaScript: a <meta refresh>
    # inside <noscript>, so with JavaScript on it does not exist and jobs.js polls
    # instead, reloading once when the job finishes. (Not a Refresh header: a script
    # cannot cancel that, and the page would reload every few seconds anyway.)
    response = c.render(request, "job.html", {"job": job,
                                              "refresh": REFRESH_SECONDS if job.active else 0})
    response.headers["Cache-Control"] = "no-store"
    return response
