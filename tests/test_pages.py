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

"""src/hermitcrm/pages/: routes outside create_app get the same page context and CSRF
check as the routes inside it, and the polling paths skip the per-request sweep."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi import APIRouter, Form, Request
from fastapi.testclient import TestClient

from hermitcrm import pages
from hermitcrm.pages._ctx import ctx
from hermitcrm.web import create_app
from conftest import FIXED_NOW

CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "owner_email": "me@example.com",
          "welcome_dismissed": True, "disclaimer_accepted": "2026-09-01T09:00:00"}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "CRM Test"], cwd=tmp_path,
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "crm@test.local"], cwd=tmp_path,
                   check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    return tmp_path


def throwaway_router() -> APIRouter:
    router = APIRouter()

    @router.get("/throwaway")
    def page(request: Request):
        c = ctx(request)
        return c.render(request, "base.html", {"flash": f"{len(c.store.companies)} companies"})

    @router.post("/throwaway")
    def post(request: Request, csrf_token: str = Form("")):
        c = ctx(request)
        c.check_csrf(csrf_token)
        return {"root": str(c.root), "push": c.config["push_enabled"],
                "same": (c.store, c.gitops, c.enricher, c.templates)
                == (request.app.state.store, request.app.state.gitops,
                    request.app.state.enricher, request.app.state.templates)}

    return router


def test_a_router_in_pages_renders_the_full_page_and_checks_csrf(repo, monkeypatch):
    monkeypatch.setattr(pages, "ROUTERS", pages.ROUTERS + (throwaway_router(),))
    app = create_app(repo, config=CONFIG, clock=lambda: FIXED_NOW)
    client = TestClient(app, follow_redirects=False)

    page = client.get("/throwaway")
    assert page.status_code == 200
    body = page.text
    assert '<p class="flash">0 companies</p>' in body        # its own context
    assert 'nav class="sidebar"' in body                     # base.html's
    assert f'value="{app.state.csrf_token}"' in body         # render()'s full context
    assert 'id="toasts" aria-live="polite"' in body          # the hooks WP1 adds
    assert '<span id="jobs-badge" hidden></span>' in body
    assert '<div id="palette-root" hidden></div>' in body
    for name in ("live.js", "palette.js", "jobs.js"):
        assert f'src="/static/{name}?v=' in body
    for name in ("live.css", "palette.css", "jobs.css", "today.css"):
        assert f'href="/static/{name}?v=' in body
        assert client.get(f"/static/{name}").status_code == 200
    assert "Content-Security-Policy" in page.headers         # the app's middleware ran

    assert client.post("/throwaway", data={"csrf_token": "wrong"}).status_code == 403
    assert client.post("/throwaway").status_code == 403
    ok = client.post("/throwaway", data={"csrf_token": app.state.csrf_token})
    assert ok.status_code == 200
    assert ok.json() == {"root": str(repo), "push": False, "same": True}


def test_routes_inside_create_app_win_over_pages(repo, monkeypatch):
    router = APIRouter()
    router.add_api_route("/health", lambda: {"shadowed": True})
    monkeypatch.setattr(pages, "ROUTERS", pages.ROUTERS + (router,))
    client = TestClient(create_app(repo, config=CONFIG, clock=lambda: FIXED_NOW))
    assert "shadowed" not in client.get("/health").json()


def test_polling_paths_skip_the_sweep(repo):
    app = create_app(repo, config=CONFIG, clock=lambda: FIXED_NOW)
    client = TestClient(app, follow_redirects=False)
    swept, heads = [], []
    app.state.store.requalify_due = lambda: swept.append(1)
    real_sha = app.state.gitops.last_commit_sha
    app.state.gitops.last_commit_sha = lambda: heads.append(1) or real_sha()

    for path in ("/jobs/x", "/live/x", "/jobs/", "/live/a/b", "/static/style.css"):
        client.get(path)
    assert (swept, heads) == ([], [])

    client.get("/health")                  # an ordinary GET still sweeps
    assert len(swept) == 1 and heads       # (/health asks git for HEAD itself too)
    client.get("/jobsx")                   # only the /jobs/ folder is exempt
    assert len(swept) == 2
