"""The serve log, without what a capture read off a page.

The bookmarklet hands the running app what it read on a profile -- a name, a
headline, an employer -- in the query string of a local address, because a
new tab is the one thing a bookmarklet may open from any page. uvicorn writes
every address it answers to the serve log, so without this the log would keep
a copy of each person captured, outside the data folder and its history.

The request line stays (path, status, time); only the query goes, and only on
the capture paths. Everything else is logged exactly as uvicorn logs it.
"""

from __future__ import annotations

import copy
import logging

from uvicorn.config import LOGGING_CONFIG

# The page's own words arrive here; /capture/new is the old bookmarklet's path.
QUIET_PATHS = ("/extension/new", "/capture/new")


class QuietCaptures(logging.Filter):
    """Drop the query of a capture request from uvicorn's access line."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn: (client, method, path with query, http version, status)
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path, _, query = args[2].partition("?")
            if query and path in QUIET_PATHS:
                record.args = (*args[:2], path + "?…", *args[3:])
        return True


def log_config() -> dict:
    """uvicorn's own logging setup, with QuietCaptures on its access log."""
    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["quiet_captures"] = {"()": QuietCaptures}
    access = config["loggers"].setdefault("uvicorn.access", {})
    access["filters"] = [*access.get("filters", []), "quiet_captures"]
    return config
