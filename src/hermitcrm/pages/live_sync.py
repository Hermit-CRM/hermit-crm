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

"""Live sync: open pages follow changes made elsewhere. Registered by pages.register.

`GET /live/head.json` says what git HEAD is; static/live.js asks every five
seconds while its tab is visible and refreshes the page when the answer
changes. Every write by any Hermit process (the CLI, the MCP server, the daily
sync, an agent's own commit) moves HEAD. The store itself is reloaded where it
always was, by `refresh_if_moved` in web.py on the next page request: this
endpoint only reads, and as it is under /live/ the per-request sweep skips it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ._ctx import ctx

router = APIRouter()

NO_STORE = {"Cache-Control": "no-store"}


@router.get("/live/head.json")
def live_head(request: Request):
    """{"head": the commit HEAD points at, 10 characters, or "" without one}."""
    return JSONResponse({"head": ctx(request).gitops.head() or ""}, headers=NO_STORE)
