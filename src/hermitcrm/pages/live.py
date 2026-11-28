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

"""Undo from where a change was made (WP8). Registered by pages.register.

Every write is one commit (web.py `on_write`), and `record_write` keeps the
newest one on `app.state.last_write`. The page that reports it carries an Undo
button (templates/undo_form.html, under the flash line; live.js moves it into
the toast): for two minutes under a flash, and on the first page shown right
after a write that has no flash of its own (a stage move, a task ticked off),
with a line in plain words saying what was done. The button posts the commit to
`POST /live/undo`, which is `history.undo`: a new commit that reverses it, so
an undo can itself be undone the same way.

Every company and contact page also links to its own history
(`/companies/{slug}/history`, `.../contacts/{cslug}/history`): the commits
that touched its files, newest first, in plain words, field by field, each with
the same Undo. Nothing new is stored: git is the history.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import history
from ._ctx import ctx

router = APIRouter()

UNDO_WINDOW = 120.0   # seconds a reload of that page keeps offering Undo
FIRST_PAGE = 10.0     # the page a write redirects to is shown within this
clock = time.monotonic  # tests move it


def record_write(state, sha: str | None, message: str) -> None:
    """Called from on_write with what `gitops.commit` returned: the newest write,
    or None when that write committed nothing (so an older one is not offered
    under the flash of a save that changed nothing)."""
    state.last_write = ({"sha": sha, "message": message, "time": clock(), "page": None}
                        if sha else None)


def page_address(request: Request) -> str:
    """This page's path and query without the flash: where an undo returns."""
    query = [(k, v) for k, v in request.query_params.multi_items() if k != "flash"]
    return request.url.path + ("?" + urlencode(query) if query else "")


def undo_offer(state, request: Request, flash: str) -> dict | None:
    """What templates/undo_form.html needs, or None.

    The offer belongs to the first page shown after the write (the page it
    redirected to, within a few seconds), and to reloads of that same page with
    the same flash for two minutes; a write without a flash of its own (a stage
    move) gets `note`, a line in plain words saying what was done, on that one
    page only, and only when it was reached from another page (it has a
    referer, as the page a form's answer redirects to does), not opened afresh. Either way only while that write is still the newest commit (the
    page's git HEAD, which the request sweep in web.py has just read), so the
    button never takes back something other than what it names.
    """
    last = getattr(state, "last_write", None)
    if not last:
        return None
    head = str(getattr(state, "index_head", "") or "")
    sha = last["sha"]
    if not head or not (sha.startswith(head) or head.startswith(sha)):
        return None
    age = clock() - last["time"]
    page = (request.url.path, flash)
    if last["page"] is None:
        if age >= FIRST_PAGE or not (flash or request.headers.get("referer")):
            return None
        last["page"] = page
    elif last["page"] != page or not flash or age >= UNDO_WINDOW:
        return None
    words = history.plain_subject(last["message"])
    return {"sha": sha, "message": words, "note": "" if flash else words + ".",
            "back": page_address(request)}


_RECORD = re.compile(r"^/companies/([^/]+)(?:/contacts/([^/]+)|/interactions/([^/]+))?")


def landing(store, back: str) -> str:
    """`back` while the record it shows is still there; an undone "created"
    removes it, so then the nearest page that is."""
    found = _RECORD.match(back)
    if not found:
        return back
    slug, cslug, iid = found.groups()
    company = store.get(slug)
    if company is None:
        return "/companies"
    if cslug and cslug not in company.contacts:
        return f"/companies/{slug}"
    if iid and not any(i.id == iid for i in company.interactions):
        return f"/companies/{slug}"
    return back


@router.post("/live/undo")
def undo(request: Request, csrf_token: str = Form(""), sha: str = Form(""),
         back: str = Form("")):
    """Take one change back and return to the page it was made on. A refusal or
    a conflict comes back as history.undo's own words; there is no force."""
    from ..web import flashed, safe_back   # web.py imports this package

    c = ctx(request)
    c.check_csrf(csrf_token)
    back = safe_back(back, "/")
    try:
        new, subject = history.undo(c.store, sha)
    except history.UndoError as exc:
        return flashed(landing(c.store, back), str(exc))
    c.store.load()
    record_write(request.app.state, c.gitops.last_commit_sha(), subject)
    c.gitops.push_async()
    return flashed(landing(c.store, back), history.plain_subject(subject) + ".")


# ------------------------------------------------------------ record history


def history_page(request: Request, name: str, back: str, paths: list[str], main: str,
                 page: int):
    c = ctx(request)
    changes, more = history.record_history(c.root, paths, main, page=page)
    if page > 1 and not changes:
        raise HTTPException(status_code=404, detail="no such page of history")
    here = request.url.path
    return c.render(request, "history.html", {
        "record_name": name, "record_url": back, "changes": changes,
        "when_text": history.when_text, "page": page,
        "newer_url": (f"{here}?page={page - 1}" if page > 2 else here) if page > 1 else "",
        "older_url": f"{here}?page={page + 1}" if more else "",
        "here": page_address(request), "per_page": history.PER_PAGE,
    })


def _page(page: str) -> int:
    return int(page) if page.isdigit() and 0 < int(page) < 100000 else 1


@router.get("/companies/{slug}/history", response_class=HTMLResponse)
def company_history(request: Request, slug: str, page: str = "1"):
    company = ctx(request).store.get(slug)
    if company is None:
        raise HTTPException(status_code=404, detail=f"unknown company {slug!r}")
    folder = f"companies/{company.slug}"
    return history_page(request, company.name, f"/companies/{company.slug}", [folder],
                        f"{folder}/company.md", _page(page))


@router.get("/companies/{slug}/contacts/{cslug}/history", response_class=HTMLResponse)
def contact_history(request: Request, slug: str, cslug: str, page: str = "1"):
    company = ctx(request).store.get(slug)
    person = company.contacts.get(cslug) if company is not None else None
    if person is None:
        raise HTTPException(status_code=404, detail=f"unknown contact {slug}/{cslug}")
    main = f"companies/{company.slug}/contacts/{person.slug}.md"
    return history_page(request, f"{person.name} ({company.name})",
                        f"/companies/{company.slug}/contacts/{person.slug}", [main], main,
                        _page(page))
