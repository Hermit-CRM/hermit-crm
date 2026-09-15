import sys
from datetime import datetime
from pathlib import Path

import pytest


from owncrm.store import Store  # noqa: E402

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
