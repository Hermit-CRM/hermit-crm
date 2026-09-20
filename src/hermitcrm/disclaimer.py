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

"""The one-time acknowledgement shown over the web app until it is ticked.

Three points, no more: there is no warranty, the backups are yours, and the
integrations you connect are yours to answer for. DISCLAIMER.md has the rest
and the modal links to it.

Where the answer is kept, and why it is not a cookie: ``disclaimer_accepted``
in the data folder's ``config.toml``, holding the local time it was ticked.
That is the same place ``welcome_dismissed`` lives, it is a plain line in a
file the user owns, and it survives a browser with no cookies at all. It is
never sent anywhere -- there is nowhere to send it -- and nothing reads it but
this module.

An empty value means "not yet"; any non-empty one means accepted, so a hand
edit of the file works the way someone would expect.
"""

from __future__ import annotations

from datetime import datetime

KEY = "disclaimer_accepted"

# (heading, the sentence under it). Kept short on purpose: three things a
# person will actually read beat a wall they will click past.
POINTS = [
    ("No warranty",
     "Hermit CRM is free, alpha software. It may lose or corrupt your data, "
     "and nobody is liable if it does."),
    ("Your backups are yours",
     "The commit per change and the copy every few minutes are a convenience, "
     "not a guarantee. Keep your own backups and check that they restore."),
    ("Integrations are your responsibility",
     "Mail, calendar, LinkedIn and AI tools use your own keys. Their terms and "
     "your GDPR obligations are yours, not the author's."),
]


def accepted(config: dict) -> bool:
    """Has someone ticked the box for this data folder?"""
    return bool(str(config.get(KEY) or "").strip())


def stamp(now: datetime | None = None) -> str:
    """The value written when the box is ticked: local time, to the second."""
    return (now or datetime.now()).replace(microsecond=0).isoformat()
