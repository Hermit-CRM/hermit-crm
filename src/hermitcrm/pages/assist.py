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

"""Routes for the assistant features: autopilot (autopilot.py) and, next to it,
the after-contact assistant. Registered by pages.register."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request

from .. import autopilot
from ._ctx import ctx

router = APIRouter()


def _flashed(path: str, message: str, anchor: str = ""):
    from ..web import flashed  # web imports this package

    return flashed(path, message, anchor=anchor)


@router.post("/settings/autopilot")
def settings_autopilot(request: Request, csrf_token: str = Form(""),
                       on: list[str] = Form([]), daily_cap: str = Form("")):
    """Settings, Autopilot: the switches and the daily limit, in config.toml.
    Turning a switch on is the consent: nothing runs before the next sync."""
    c = ctx(request)
    c.check_csrf(csrf_token)
    errors = autopilot.save_settings(c.root, on, daily_cap)
    if errors:
        return _flashed("/settings", "Not saved: " + " ".join(errors.values()),
                        anchor="autopilot")
    from ..setup import commit_config

    commit_config(c.root, c.store.notify)   # the next page reads config.toml again
    chosen = [autopilot.LABELS[s][0].lower() for s in autopilot.SWITCHES if s in on]
    message = ("Autopilot saved: " + ", ".join(chosen) + " after each daily sync"
               if chosen else "Autopilot saved: everything off")
    return _flashed("/settings", message, anchor="autopilot")
