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

"""/today: the Today queue on its own, without the rest of Home.

Home (`web.py` `home_page`) shows the same queue as its "next" section through
`queue_context`; both include templates/today.html. Read-only: every action on
a row posts to a route the app already has.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import today as queue
from ._ctx import ctx

router = APIRouter()

LIMIT = 25           # rows shown before "Show all"
ALL_URL = "/today?all=1"


def queue_context(store, config: dict, back: str, show_all: bool = False) -> dict:
    """What templates/today.html needs, for Home and for /today."""
    return {"queue": queue.build(store, config, store.today()),
            "today_limit": None if show_all else LIMIT,
            "today_back": back, "today_all_url": ALL_URL}


@router.get("/today", response_class=HTMLResponse)
def today_page(request: Request, all: str = ""):
    c = ctx(request)
    show_all = all == "1"
    back = ALL_URL if show_all else "/today"
    return c.render(request, "today_page.html",
                    queue_context(c.store, c.config, back, show_all))
