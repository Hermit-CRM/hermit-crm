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

"""Search everything (search.py): the full results page and its JSON twin.

`GET /search?q=` is what the top bar's search box opens, with or without
JavaScript. `GET /search.json?q=` returns the same results for the command
palette (static/palette.js). `only=<group>` shows one group with more rows,
the page's "Show all" link. Both only read.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .. import search as finder
from ._ctx import ctx

router = APIRouter()

# One group on its own ("Show all") lists this many; a page of results, not a dump.
ALL_LIMIT = 200


def _run(request: Request, q: str, only: str):
    store = ctx(request).store
    if only in finder.KINDS:
        return finder.search(store, q, limit=ALL_LIMIT, kinds=(only,))
    return finder.search(store, q)


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", only: str = ""):
    c = ctx(request)
    results = _run(request, q, only)
    return c.render(request, "search.html", {
        "q": results.q, "results": results,
        "only": only if only in finder.KINDS else "",
    })


@router.get("/search.json")
def search_json(request: Request, q: str = ""):
    return JSONResponse(finder.search(ctx(request).store, q).to_json(),
                        headers={"Cache-Control": "no-store"})
