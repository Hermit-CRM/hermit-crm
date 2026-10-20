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

"""Update check: is a newer Hermit CRM published? At most once per 24 hours, never blocking.

GET the index URL with a 3 s timeout and no identifiers (no cookies, no custom headers
beyond a plain User-Agent), cached in ~/.cache/hermitcrm/update.json. Off when config
``update_check = false`` or env ``HERMITCRM_NO_UPDATE_CHECK=1``. No `packaging`
dependency: a small parser compares release versions.

Two things this module is careful about, both learned from getting them wrong:

* **It never claims to be up to date on a failed check.** A 404 (nothing published at
  that URL yet) and an unreachable network are distinct from "asked, and we are
  current". ``Result.state`` keeps them apart so the wording can be honest; the old
  code collapsed all three into "" and `doctor` reported "is the latest" for a check
  that had never succeeded.
* **The index is configurable** (``update_url``). The default is PyPI, but any URL
  serving ``{"version": "0.4.0"}`` works, so a static file on a download site is
  enough -- no package index required.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, NamedTuple

from . import __version__

PYPI_URL = "https://pypi.org/pypi/hermitcrm/json"
TIMEOUT = 3.0
INTERVAL = 24 * 60 * 60
# A failed check is not an answer, so it is not worth a day. The web app starts its
# check in a thread the moment the process does, and under launchd that can be before
# the network is up: one unlucky second at boot should not leave "could not reach
# pypi.org" on the Settings page until tomorrow.
RETRY_INTERVAL = 60 * 60


def upgrade_argv(prefix: str | Path | None = None) -> list[str]:
    """The command that moves *this* install to the latest release on PyPI, as words.

    `uv tool upgrade` and `pipx upgrade` keep a tool on the source it was installed
    from, and for a download that is the unpacked folder, so they say "nothing to
    upgrade" for ever. `uv tool install hermitcrm@latest` and `pipx install --force`
    switch it to PyPI from wherever it came. Each tool leaves a file in the
    environment it made, which says which one this is.

    The words are fixed text: the one-click upgrade runs exactly these, and nothing
    from the network or a request is ever put into them.
    """
    env = Path(sys.prefix if prefix is None else prefix)
    if (env / "uv-receipt.toml").exists():
        return ["uv", "tool", "install", "hermitcrm@latest"]
    if (env / "pipx_metadata.json").exists():
        return ["pipx", "install", "--force", "hermitcrm"]
    return ["pip", "install", "--upgrade", "hermitcrm"]


def upgrade_command(prefix: str | Path | None = None) -> str:
    """:func:`upgrade_argv` as the line a person would type."""
    return " ".join(upgrade_argv(prefix))


UPGRADE_HINT = upgrade_command()

# Result.state
PENDING = "pending"          # nobody has asked yet (a fresh UpdateNotice)
OFF = "off"                  # switched off in config or the environment
CURRENT = "current"          # the index answered, and it is not newer than us
NEWER = "newer"              # the index answered with a version worth having
ABSENT = "absent"            # the index answered 404: nothing published there yet
UNREACHABLE = "unreachable"  # offline, timeout, or an answer we could not read


class Result(NamedTuple):
    """What the last check actually established. ``newer`` is non-empty only for NEWER."""

    state: str
    newer: str = ""
    latest: str = ""
    url: str = ""

    @property
    def available(self) -> str:
        """Backwards-compatible alias: the version to upgrade to, or ''."""
        return self.newer

    @property
    def hint(self) -> str:
        return upgrade_hint(self.url)

    def sentence(self, current: str = __version__) -> str:
        """One honest line for `doctor` and the Settings About table."""
        if self.state == PENDING:
            return f"v{current}; update check has not run yet"
        if self.state == OFF:
            return f"v{current}; update check is off"
        if self.state == NEWER:
            return f"v{self.newer} available: {self.hint}"
        if self.state == CURRENT:
            return f"v{current} is the latest"
        if self.state == ABSENT:
            return f"v{current}; no release published at {host_of(self.url)} yet"
        return f"v{current}; could not reach {host_of(self.url)} to check"


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(str(url or "")).netloc or str(url or "the update index")


def upgrade_hint(url: str = PYPI_URL) -> str:
    """The upgrade command only helps if PyPI is where the check looked; otherwise, download it."""
    if not url or host_of(url) == "pypi.org":
        return UPGRADE_HINT
    return f"download it from {host_of(url)}"


def source_url(config: dict) -> str:
    return str(config.get("update_url") or "").strip() or PYPI_URL


def cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "hermitcrm" / "update.json"


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


def version_in(data) -> str:
    """PyPI answers {"info": {"version": ...}}; a plain file may just say {"version": ...}."""
    if isinstance(data, dict):
        info = data.get("info")
        if isinstance(info, dict) and info.get("version"):
            return str(info["version"])
        for key in ("version", "latest"):
            if data.get(key):
                return str(data[key])
    raise ValueError("no version in the answer")


def fetch_latest(url: str = PYPI_URL, timeout: float = TIMEOUT) -> str:
    """The published version. Raises HTTPError(404) when nothing is published there."""
    request = urllib.request.Request(url, headers={"User-Agent": "hermitcrm",
                                                   "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        data = json.loads(response.read(1_000_000).decode("utf-8"))
    return version_in(data)


def installed_version(paths=None) -> str:
    """The version installed *on disk*, which is not always the one running.

    A server keeps the code it started with in memory while an upgrade replaces
    the files under it; the two then disagree until the next restart. This reads
    the ``hermitcrm-*.dist-info/METADATA`` an installer leaves on ``sys.path``
    (read from disk on purpose: the PR safety check flags ``importlib``, and
    ``test_no_telemetry`` does the same). '' when it cannot be told, for instance
    in the middle of an install. The newest wins if two environments are on the
    path.
    """
    best = ""
    for entry in (sys.path if paths is None else paths):
        if not entry:  # '' is the current directory, which may be a data folder
            continue
        try:
            infos = list(Path(entry).glob("hermitcrm-*.dist-info"))
        except OSError:
            continue
        for info in infos:
            try:
                head = (info / "METADATA").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fields = {}
            for line in head.splitlines():
                if not line.strip():  # the headers end at the first blank line
                    break
                key, _, value = line.partition(":")
                fields.setdefault(key.strip().lower(), value.strip())
            version = fields.get("version", "")
            if fields.get("name", "").lower().replace("_", "-") == "hermitcrm" and version \
                    and (not best or parse_version(version) > parse_version(best)):
                best = version
    return best


class DiskWatch:
    """Is the program on disk newer than the one running? Cheap enough for every page.

    The answer is memoised for a few seconds, so a page load costs a dictionary
    lookup, and a reinstall is noticed on the next page after that.
    """

    def __init__(self, running: str = __version__, read: Callable[[], str] = installed_version,
                 ttl: float = 5.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._running, self._read, self._ttl, self._clock = running, read, ttl, clock
        self._at: float | None = None
        self._seen = ""

    def newer(self) -> str:
        """The version on disk when it is newer than the running code, else ''."""
        now = self._clock()
        if self._at is None or now - self._at >= self._ttl:
            self._at = now
            try:
                self._seen = str(self._read() or "")
            except Exception:
                self._seen = ""
        return self._seen if self._seen and is_newer(self._seen, self._running) else ""


def enabled(config: dict, env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    if str(env.get("HERMITCRM_NO_UPDATE_CHECK", "")).strip() not in ("", "0"):
        return False
    return bool(config.get("update_check", True))


def _ask(fetcher: Callable[[], str]) -> tuple[str, str]:
    """(state, latest) from one call. A 404 is a fact about the index, not a failure."""
    try:
        latest = str(fetcher() or "")
    except urllib.error.HTTPError as exc:
        return (ABSENT if exc.code == 404 else UNREACHABLE), ""
    except Exception:
        return UNREACHABLE, ""
    return (CURRENT, latest) if latest else (UNREACHABLE, "")


def look(config: dict, fetcher: Callable[[], str] | None = None,
         cache: Path | None = None, now: float | None = None,
         env: dict | None = None, current: str = __version__) -> Result:
    """The full outcome. Network only when the cache is stale or points elsewhere."""
    url = source_url(config)
    if not enabled(config, env):
        return Result(OFF, url=url)
    cache = cache or cache_path()
    now = time.time() if now is None else now

    state, latest = "", ""
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        age = now - float(cached.get("checked", 0))
        fresh = age < (RETRY_INTERVAL if cached.get("state") == UNREACHABLE else INTERVAL)
        # A changed index invalidates the cache; yesterday's answer was about
        # somewhere else.
        if fresh and str(cached.get("url", "")) == url:
            state, latest = str(cached.get("state", "")), str(cached.get("latest", ""))
    except (OSError, ValueError, TypeError):
        pass

    if not state:
        state, latest = _ask(fetcher or (lambda: fetch_latest(url)))
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"checked": now, "latest": latest,
                                         "state": state, "url": url}), encoding="utf-8")
        except OSError:
            pass

    if state == CURRENT and latest and is_newer(latest, current):
        return Result(NEWER, newer=latest, latest=latest, url=url)
    return Result(state or UNREACHABLE, latest=latest, url=url)


def check(config: dict, fetcher: Callable[[], str] | None = None,
          cache: Path | None = None, now: float | None = None,
          env: dict | None = None, current: str = __version__) -> str:
    """The newer version available, or ''. Thin wrapper over :func:`look`."""
    return look(config, fetcher=fetcher, cache=cache, now=now, env=env, current=current).newer


def note(result: Result) -> str:
    """The short parenthetical for the Settings About row; empty when the row says it."""
    if result.state == NEWER:
        return ""
    if result.state == PENDING:
        return "update check has not run yet"
    if result.state == OFF:
        return "update check is off"
    if result.state == CURRENT:
        return "the latest, checked at most a day ago"
    if result.state == ABSENT:
        return f"no release published at {host_of(result.url)} yet"
    return f"could not reach {host_of(result.url)} to check"


class UpdateNotice:
    """Holds the result of a background check for templates to read."""

    def __init__(self) -> None:
        self.result = Result(PENDING)
        self.available = ""
        self.hint = UPGRADE_HINT
        self._thread: threading.Thread | None = None
        self._last: float | None = None  # when a check was last started; None = never
        self._fetcher: Callable[[], str] | None = None
        self._cache: Path | None = None

    def start(self, config: dict, fetcher: Callable[[], str] | None = None,
              cache: Path | None = None) -> threading.Thread | None:
        if not enabled(config):
            self.result = Result(OFF, url=source_url(config))
            return None
        self._fetcher, self._cache = fetcher, cache
        return self._spawn(config, time.time())

    def tick(self, config: dict, now: float | None = None) -> threading.Thread | None:
        """Ask again when the last check is over an hour old.

        `start` runs once, when the process does, and a server that stays up for
        weeks would never hear of a release. Page loads call this; `look` still
        decides whether the network is touched, so the cache and its 24 hours
        stand. A notice that was never started (the tests) stays quiet.
        """
        now = time.time() if now is None else now
        if self._last is None or not enabled(config):
            return None
        if now - self._last < RETRY_INTERVAL or (self._thread and self._thread.is_alive()):
            return None
        return self._spawn(config, now)

    def _spawn(self, config: dict, now: float) -> threading.Thread:
        self._last = now

        def run() -> None:
            try:
                self.result = look(config, fetcher=self._fetcher, cache=self._cache)
            except Exception:
                self.result = Result(UNREACHABLE, url=source_url(config))
            self.available = self.result.newer
            self.hint = self.result.hint

        self._thread = threading.Thread(target=run, name="hermitcrm-update-check", daemon=True)
        self._thread.start()
        return self._thread
