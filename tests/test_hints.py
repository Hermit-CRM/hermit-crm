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

"""The short lead lines: the detail a page needs once sits behind a "?" (the `hint`
macro), and a long list of days is shown as a range."""

from __future__ import annotations

import re

import pytest

from hermitcrm import sendplan
from test_web import app, client, repo  # noqa: F401  (the fixtures)


@pytest.mark.parametrize("days, shown", [
    ("Mon, Tue, Wed, Thu, Fri", "Mon–Fri"),
    ("Mon, Tue, Wed, Thu, Fri, Sat, Sun", "every day"),
    ("Tue, Wed, Thu", "Tue–Thu"),
    ("Mon, Wed, Fri", "Mon, Wed, Fri"),          # a gap stays listed
    ("Sat, Sun", "Sat, Sun"),                    # two days read fine as they are
    ("Mon", "Mon"),
    ("", ""),
    ("Someday, Mon", "Someday, Mon"),            # not a list of days: left alone
])
def test_a_run_of_days_is_shortened_for_reading(days, shown):
    assert sendplan.compact_days(days) == shown


@pytest.mark.parametrize("path", ["/tasks", "/messages", "/reports", "/outreach"])
def test_every_hint_is_described_by_its_own_tip(client, path):
    page = client.get(path)
    assert page.status_code == 200
    tips = re.findall(r'<span class="tip" role="tooltip" id="([^"]+)"', page.text)
    described = re.findall(r'class="help hint"[^>]*aria-describedby="([^"]+)"', page.text)
    assert tips, f"{path} has no hint"
    assert tips == described and len(set(tips)) == len(tips)


def test_tasks_and_messages_keep_their_explanation_in_a_hint(client):
    tasks = client.get("/tasks").text
    assert "Tasks for companies and their people." in tasks
    assert 'aria-describedby="next-step-help"' in tasks and "open task due first" in tasks
    messages = client.get("/messages").text
    assert 'aria-describedby="outcome-help"' in messages
    assert "when a reply from the same contact was logged afterwards" in messages
