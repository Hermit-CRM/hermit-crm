"""Update check: is a newer OwnCRM on PyPI? At most once per 24 hours, never blocking.

GET https://pypi.org/pypi/owncrm/json with a 3 s timeout and no identifiers (no
cookies, no custom headers beyond a plain User-Agent), cached in
~/.cache/owncrm/update.json. Off when config ``update_check = false`` or env
``OWNCRM_NO_UPDATE_CHECK=1``. No `packaging` dependency: a small parser compares
release versions.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__

PYPI_URL = "https://pypi.org/pypi/owncrm/json"
TIMEOUT = 3.0
INTERVAL = 24 * 60 * 60
UPGRADE_HINT = "pipx upgrade owncrm"


def cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "owncrm" / "update.json"


def parse_version(text: str) -> tuple:
    """'1.2.10' > '1.2.9'; pre-releases ('1.3.0rc1', '1.3.0.dev2') sort before the release."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)(.*)$", str(text or ""))
    if not m:
        return ((0,), 0, "")
    nums = tuple(int(n) for n in m.group(1).split("."))
    while len(nums) > 1 and nums[-1] == 0:
        nums = nums[:-1]
    rest = m.group(2).strip().lstrip(".-")
    return (nums, 0 if rest else 1, rest)  # a final release beats any suffix


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def fetch_latest(url: str = PYPI_URL, timeout: float = TIMEOUT) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "owncrm",
                                                   "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        data = json.loads(response.read(1_000_000).decode("utf-8"))
    return str(data["info"]["version"])


def enabled(config: dict, env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    if str(env.get("OWNCRM_NO_UPDATE_CHECK", "")).strip() not in ("", "0"):
        return False
    return bool(config.get("update_check", True))


def check(config: dict, fetcher: Callable[[], str] = fetch_latest,
          cache: Path | None = None, now: float | None = None,
          env: dict | None = None, current: str = __version__) -> str:
    """The newer version available, or ''. Network only when the cache is stale."""
    if not enabled(config, env):
        return ""
    cache = cache or cache_path()
    now = time.time() if now is None else now
    latest = ""
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if now - float(cached.get("checked", 0)) < INTERVAL:
            latest = str(cached.get("latest", ""))
            return latest if latest and is_newer(latest, current) else ""
    except (OSError, ValueError, TypeError):
        pass
    try:
        latest = fetcher()
    except Exception:
        latest = ""  # offline, PyPI down, not published yet: try again tomorrow
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"checked": now, "latest": latest}), encoding="utf-8")
    except OSError:
        pass
    return latest if latest and is_newer(latest, current) else ""


class UpdateNotice:
    """Holds the result of a background check for templates to read."""

    def __init__(self) -> None:
        self.available = ""
        self.hint = UPGRADE_HINT

    def start(self, config: dict, fetcher: Callable[[], str] = fetch_latest,
              cache: Path | None = None) -> threading.Thread | None:
        if not enabled(config):
            return None

        def run() -> None:
            try:
                self.available = check(config, fetcher=fetcher, cache=cache)
            except Exception:
                self.available = ""

        thread = threading.Thread(target=run, name="owncrm-update-check", daemon=True)
        thread.start()
        return thread
