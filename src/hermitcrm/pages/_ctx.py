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

"""What a route outside `create_app` needs, read from `app.state` on each request.

    from ._ctx import ctx

    @router.get("/today/x")
    def page(request: Request):
        c = ctx(request)
        return c.render(request, "x.html", {"rows": c.store.open_tasks()})

Read per request, not at import: a Settings save replaces the enricher on
`app.state`, and a test app has its own store and folder.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import Request


@dataclass(frozen=True)
class Ctx:
    store: Any                      # store.Store
    root: Path                      # the data folder
    config: dict                    # config.toml, kept current by Settings saves
    render: Callable[..., Any]      # render(request, name, ctx, status_code=200)
    check_csrf: Callable[[str], None]  # raises 403; call it first in every POST
    enricher: Any                   # enrich.Enricher
    gitops: Any                     # gitops.GitOps
    templates: Any                  # Jinja2Templates


def ctx(request: Request) -> Ctx:
    state = request.app.state
    return Ctx(store=state.store, root=state.root, config=state.config,
               render=state.render, check_csrf=state.check_csrf,
               enricher=state.enricher, gitops=state.gitops,
               templates=state.templates)
