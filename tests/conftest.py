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
