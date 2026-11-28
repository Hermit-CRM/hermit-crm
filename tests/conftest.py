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

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm.store import Store  # noqa: E402
from hermitcrm import web  # noqa: E402

# Starlette's TestClient sends `Host: testserver`; the web app refuses host
# names it does not know (DNS rebinding), so the tests name theirs.
web.EXTRA_HOST_NAMES.add("testserver")

FIXED_NOW = datetime(2026, 9, 14, 10, 30)

# The config of an established user, for the shared `app` fixture below: these
# tests are not about the first launch.
CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "owner_email": "me@example.com",
          "welcome_dismissed": True, "disclaimer_accepted": "2026-09-01T09:00:00"}

# A commit can start git's auto housekeeping, which detaches by default and
# keeps writing .git/objects/maintenance.lock after the commit returns. A test
# that then copies or deletes the folder races it (FileNotFoundError on the
# lock, seen on CI). In the foreground the housekeeping still runs, but is
# finished before the git call returns. Every git subprocess inherits this.
_GIT_CONFIG = {"maintenance.autoDetach": "false", "gc.autoDetach": "false"}
_base = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
for _i, (_key, _value) in enumerate(_GIT_CONFIG.items(), start=_base):
    os.environ[f"GIT_CONFIG_KEY_{_i}"] = _key
    os.environ[f"GIT_CONFIG_VALUE_{_i}"] = _value
os.environ["GIT_CONFIG_COUNT"] = str(_base + len(_GIT_CONFIG))


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


# ------------------------------------------------------------ git folders
#
# Most route tests need an empty data folder that is a git repository. Running
# `git init` and two `git config` calls for each of them starts three processes
# per test (about 55 ms on a laptop); copying a `.git` made once takes about
# 3 ms. The copy is the same repository: no commits, branch main, the test
# identity in its own config, and nothing in it names the folder it was made in.


@pytest.fixture(scope="session")
def git_template(tmp_path_factory) -> Path:
    """The `.git` of one empty repository, made once per run (once per worker
    under `-n auto`). Read-only: copy it with `copy_git`, never write to it."""
    folder = tmp_path_factory.mktemp("git-template")
    for args in (["init", "-b", "main"], ["config", "user.name", "CRM Test"],
                 ["config", "user.email", "crm@test.local"]):
        subprocess.run(["git", *args], cwd=folder, check=True, capture_output=True)
    # The sample hooks git copies in are inert (only files without .sample
    # run); dropping them makes every copy a dozen files instead of two dozen.
    for sample in (folder / ".git" / "hooks").glob("*.sample"):
        sample.unlink()
    return folder / ".git"


def copy_git(template: Path, folder: Path) -> Path:
    """Make `folder` the empty repository `template` is the `.git` of."""
    shutil.copytree(template, folder / ".git")
    return folder


@pytest.fixture
def repo(tmp_path: Path, git_template: Path) -> Path:
    """An empty data folder in tmp_path: a git repository with `companies/`."""
    copy_git(git_template, tmp_path)
    (tmp_path / "companies").mkdir()
    return tmp_path


@pytest.fixture
def app(repo: Path):
    app = web.create_app(repo, config=CONFIG)
    # Every page under test asks the store what day it is, while the tests write
    # dates of their own -- TODAY, and literals in September 2026. Leave the store
    # on the real clock and the gap between the two changes every day: a task due
    # "2026-09-24" sits in Future tasks, then moves to Top priority when that date
    # arrives, and once the month rolls over the calendar grid stops drawing it at
    # all. Fixing the store's day makes the tests mean what they say.
    app.state.store.clock = lambda: FIXED_NOW
    return app


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")
