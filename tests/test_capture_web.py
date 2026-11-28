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

"""Quick capture in the web app (pages/capture.py): the text box, the job, the
preview and the one commit it files. The AI is a fake runner and jobs run inline
(conftest), so every test sees the finished job at once. No JavaScript anywhere:
each step is a plain form post and a redirect."""

import re
import subprocess

import pytest

from hermitcrm.enrich import Enricher

TEXT = "Called Jane at Acme: she wants a proposal by Friday.\n"


def answer(**over):
    data = {"company": "Acme Robotics", "company_slug": "acme-robotics",
            "contact": "Jane Doe", "contact_slug": "jane-doe", "channel": "call",
            "direction": "out", "date": "", "subject": "Wants a proposal", "outcome": "",
            "stage": "", "tasks": [{"text": "Send Jane the proposal", "due": "Friday"}]}
    data.update(over)
    return data


class FakeRunner:
    def __init__(self, data):
        self.data, self.calls = data, []

    def __call__(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if isinstance(self.data, BaseException):
            raise self.data
        return self.data


def use_ai(app, data=None, found=True):
    runner = FakeRunner(answer() if data is None else data)
    app.state.enricher = Enricher(provider="claude", runner=runner,
                                  which=(lambda b: f"/usr/local/bin/{b}") if found
                                  else (lambda b: None))
    return runner


@pytest.fixture
def crm(app):
    store = app.state.store
    store.create_company("Acme Robotics")
    store.create_contact("acme-robotics", "Jane", "Doe", email="jane@example.com")
    store.create_company("Globex Logistics")
    store.create_contact("globex-logistics", "Sam", "Rivera")
    return app


def commits(app) -> int:
    out = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=app.state.root,
                         capture_output=True, text=True, check=True).stdout
    return int(out.strip())


def csrf(app) -> str:
    return app.state.csrf_token


def start(client, text=TEXT):
    r = client.post("/quick-capture", data={"csrf_token": csrf(client.app), "text": text})
    assert r.status_code == 303, r.text
    job = re.fullmatch(r"/jobs/([0-9a-f]+)", r.headers["location"]).group(1)
    return job



# ------------------------------------------------------------------ the box


def test_the_box_is_a_plain_form_and_the_palette_fills_it(crm, client):
    use_ai(crm)
    page = client.get("/quick-capture?text=Met+Sam").text
    assert 'method="post" action="/quick-capture"' in page
    assert '<textarea name="text"' in page and ">Met Sam</textarea>" in page
    assert 'name="csrf_token"' in page


def test_without_an_ai_tool_the_page_says_so_and_points_at_the_forms(crm, client):
    runner = use_ai(crm, found=False)
    page = client.get("/quick-capture").text
    assert "No AI tool is set up" in page
    assert 'href="/companies"' in page and 'href="/settings#enrichment"' in page
    assert '<textarea name="text"' not in page
    r = client.post("/quick-capture", data={"csrf_token": csrf(crm), "text": TEXT})
    assert r.status_code == 502 and "No AI tool is set up" in r.text
    assert runner.calls == [] and crm.state.jobs.recent() == []


def test_an_empty_box_or_a_missing_token_starts_nothing(crm, client):
    runner = use_ai(crm)
    assert client.post("/quick-capture", data={"csrf_token": csrf(crm), "text": "  "}
                       ).status_code == 400
    assert client.post("/quick-capture", data={"text": TEXT}).status_code == 403
    assert runner.calls == []


# ------------------------------------------------------------------ the preview


def test_a_sentence_naming_a_contact_gives_a_preview_and_writes_nothing(crm, client):
    runner = use_ai(crm)
    before = commits(crm)
    job_id = start(client)

    assert len(runner.calls) == 1 and runner.calls[0]["tools"] == ""
    r = client.get(f"/jobs/{job_id}")       # the badge's link: on to the preview
    assert r.status_code == 303 and r.headers["location"] == f"/quick-capture/{job_id}"
    page = client.get(f"/quick-capture/{job_id}").text
    assert "Check before filing" in page
    assert '<option value="acme-robotics" selected>Acme Robotics</option>' in page
    assert '<option value="jane-doe" selected>Jane Doe</option>' in page
    assert '<option value="call" selected>call</option>' in page
    assert 'value="Send Jane the proposal"' in page and 'value="2026-09-18"' in page
    assert "due: you wrote “Friday”" in page
    assert "Called Jane at Acme: she wants a proposal by Friday." in page
    assert f'action="/quick-capture/{job_id}"' in page
    assert commits(crm) == before


def test_a_name_not_in_the_crm_is_offered_not_created(crm, client):
    use_ai(crm, answer(company="Initech", company_slug="", contact="Bill Lumbergh",
                       contact_slug=""))
    job_id = start(client)
    page = client.get(f"/quick-capture/{job_id}").text
    assert "create a new company: Initech" in page
    assert "create a new contact: Bill Lumbergh" in page
    assert crm.state.store.get("initech") is None



def test_a_failed_read_keeps_the_text(crm, client):
    from hermitcrm.enrich import EnrichError
    use_ai(crm, EnrichError("claude (claude-haiku-5-5) failed: overloaded"))
    job_id = start(client)
    page = client.get(f"/quick-capture/{job_id}")
    assert page.status_code == 502
    assert "overloaded" in page.text and "Called Jane at Acme" in page.text


def test_an_unknown_job_says_so(crm, client):
    use_ai(crm)
    assert client.get("/quick-capture/deadbeef0000").status_code == 404
