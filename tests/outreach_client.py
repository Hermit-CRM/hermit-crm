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

"""A demo folder, a fake AI and a web client for the Outreach page tests that
import it (fixtures `root`, `fake`, `client`). All names are made up."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import URL, QueryParams

from hermitcrm import outreach
from hermitcrm.datafolder import init_folder
from hermitcrm.store import load_config
from hermitcrm.web import create_app
from outreach_fakes import NOW, FakeAI, ai, fake_page, git

MARA = "lindenhof-data/mara-keller"
MARA_EMAIL = "mara@lindenhof.example.com"


@pytest.fixture
def root(tmp_path):
    return init_folder(tmp_path / "crm", demo=True, now=NOW)


@pytest.fixture
def fake():
    return FakeAI()


@pytest.fixture
def client(root, fake):
    app = create_app(root, {**load_config(root), "push_enabled": False,
                            "owner_name": "Sam Example"})
    app.state.setup_redirected = True
    app.state.enricher = ai(fake)
    app.state.outreach_fetcher = fake_page
    app.state.store.clock = lambda: NOW
    app.state.store.update_contact("lindenhof-data", "mara-keller", email=MARA_EMAIL)
    return TestClient(app, follow_redirects=False)


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.app.state.csrf_token, **data})


def query(response) -> dict:
    return dict(QueryParams(URL(response.headers["location"]).query))


def commits(root) -> list[str]:
    return git(root, "log", "--format=%s").splitlines()


def drafted(client, root) -> outreach.Item:
    """Research and draft Mara Keller through the page, as the button does."""
    response = post(client, "/outreach/build", contact=MARA, back="/outreach")
    assert response.status_code == 303, response.text
    return next(i for i in outreach.items(root) if i.record == MARA)
