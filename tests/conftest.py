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

import sys
from datetime import datetime
from pathlib import Path

import pytest


from hermitcrm.store import Store  # noqa: E402
from hermitcrm import web  # noqa: E402

# Starlette's TestClient sends `Host: testserver`; the web app refuses host
# names it does not know (DNS rebinding), so the tests name theirs.
web.EXTRA_HOST_NAMES.add("testserver")

FIXED_NOW = datetime(2026, 9, 14, 10, 30)


@pytest.fixture(autouse=True)
def no_real_secret_tool(request, monkeypatch):
    """No test reaches a real secret-tool (a developer's keyring on Linux):
    it reads as not installed unless a test injects its own `which`. Tests
    marked real_secret_service opt out (the CI keyring job)."""
    if request.node.get_closest_marker("real_secret_service") is None:
        from hermitcrm import secrets
        monkeypatch.setattr(secrets, "_which", lambda name: None)


@pytest.fixture
def messages():
    return []


@pytest.fixture
def store(tmp_path, messages):
    """A Store rooted in tmp_path with a frozen clock and a recording on_write."""
    s = Store(tmp_path, on_write=messages.append, clock=lambda: FIXED_NOW)
    s.load()
    return s


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")
