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

"""Quick capture (capture_text.py): type what happened, check the preview, file it.

    GET  /quick-capture          one text box (?text= fills it: the palette's
                                 "Capture: ..." entry); nothing runs yet
    POST /quick-capture          starts a "capture" job, then its progress page
    GET  /quick-capture/{job}    the preview of a finished job: what it would file

Not /capture: that path still sends old bookmarklets to /extension (web.py), and
the sidebar marks /capture... as Extension. The job's progress is the shared job
page (/jobs/{id}, pages/jobs.py: it polls, and refreshes itself without
JavaScript); the "capture" view sends a finished job back here.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from .. import capture_text as ct
from ._ctx import ctx

router = APIRouter()

KIND = "capture"


def _goto(path: str):
    from ..web import goto
    return goto(path)


def _jobs(request: Request):
    jobs = request.app.state.jobs
    # The badge opens every job at /jobs/<id>; a finished capture opens its preview.
    jobs.views.setdefault(KIND, _job_view)
    return jobs


def _job_view(request: Request, job):
    return None if job.active else _goto(f"/quick-capture/{job.id}")


def _label(text: str) -> str:
    flat = " ".join(text.split())
    return "Capture: " + (flat if len(flat) <= 60 else flat[:57] + "...")


def _form_page(request: Request, text: str = "", error: str = "", status_code: int = 200):
    c = ctx(request)
    _jobs(request)
    return c.render(request, "capture.html", {
        "mode": "form", "text": text, "error": error, "ai": c.enricher,
    }, status_code=status_code)


def _preview_page(request: Request, job, values: dict, errors: dict | None = None,
                  status_code: int = 200):
    c = ctx(request)
    store = c.store
    companies = sorted(store.companies.values(), key=lambda co: co.name.casefold())
    picked = store.companies.get(values.get("company", ""))
    return c.render(request, "capture.html", {
        "mode": "preview", "job": job, "text": job.params.get("text", ""),
        "proposal": job.result.get("proposal", {}), "values": values,
        "errors": errors or {}, "companies": companies, "picked": picked,
        "people": sorted(picked.contacts.values(), key=lambda p: p.name.casefold())
        if picked else [],
        "channels": ct.CHANNELS, "directions": ["out", "in"], "outcomes": store.outcomes,
        "stages": store.stages.names, "needs_reason": [
            s for s in store.stages.names if store.stages.requires_reason(s)],
        "new": ct.NEW,
    }, status_code=status_code)


@router.get("/quick-capture", response_class=HTMLResponse)
def capture_page(request: Request, text: str = ""):
    return _form_page(request, text=text)


@router.post("/quick-capture")
def capture_start(request: Request, csrf_token: str = Form(""), text: str = Form("")):
    """Start reading the text as a background job. What fails before any AI runs
    (no text, no AI CLI) is said at once, on the same page, with the text kept."""
    c = ctx(request)
    c.check_csrf(csrf_token)
    if not " ".join(text.split()):
        return _form_page(request, text, "Type what happened first.", status_code=400)
    enricher = c.enricher
    if not enricher.available:
        return _form_page(request, text, enricher.unavailable_reason(), status_code=502)
    store = c.store

    def read(report):
        report("Reading what you wrote")
        return {"proposal": ct.parse(store, enricher, text)}

    jobs = _jobs(request)
    job = jobs.start(KIND, _label(text), read, back="/quick-capture",
                     params={"text": text})
    job.back = f"/quick-capture/{job.id}"   # the job page's way back: the preview
    return _goto(f"/jobs/{job.id}")


def _capture_job(request: Request, job_id: str):
    job = _jobs(request).get(job_id)
    return job if job is not None and job.kind == KIND else None


@router.get("/quick-capture/{job_id}", response_class=HTMLResponse)
def capture_preview(request: Request, job_id: str):
    jobs = _jobs(request)
    job = _capture_job(request, job_id)
    if job is None:
        return _form_page(request, error="That capture is no longer kept (Hermit keeps "
                          "the last 50 jobs). Type it again.", status_code=404)
    if job.active:
        return _goto(f"/jobs/{job.id}")
    jobs.mark_seen(job)
    text = job.params.get("text", "")
    if job.state != "done" or "proposal" not in job.result:
        return _form_page(request, text, job.error or "The AI returned no answer.",
                          status_code=502)
    filed = job.result.get("filed")
    if filed:
        c = ctx(request)
        return c.render(request, "capture.html", {"mode": "filed", "filed": filed,
                                                  "text": text})
    try:
        values = ct.initial_values(job.result["proposal"])
    except (KeyError, TypeError):   # a hand-edited or older jobs file
        return _form_page(request, text, "That preview can no longer be read. Try again.",
                          status_code=502)
    return _preview_page(request, job, values)
