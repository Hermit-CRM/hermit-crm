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
from datetime import date
from urllib.parse import unquote

import pytest

from hermitcrm import capture_text as ct
from hermitcrm import search as finder
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


def confirm_form(app, job_id, **over):
    """What the preview form posts when nothing is changed."""
    job = app.state.jobs.get(job_id)
    values = ct.initial_values(job.result["proposal"])
    form = {"csrf_token": csrf(app), "company": values["company"],
            "new_company": values["new_company"], "contact": values["contact"],
            "new_contact": values["new_contact"], "do_interaction": "1",
            "channel": values["channel"], "direction": values["direction"],
            "date": values["date"], "subject": values["subject"],
            "outcome": values["outcome"], "stage": values["stage"], "lost_reason": ""}
    for n, task in enumerate(values["tasks"]):
        form.update({f"task_{n}_do": "1", f"task_{n}_text": task["text"],
                     f"task_{n}_due": task["due"]})
    form.update(over)
    return {k: v for k, v in form.items() if v is not None}


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


def test_confirm_writes_one_commit_with_the_interaction_and_the_task(crm, client):
    use_ai(crm)
    job_id = start(client)
    before = commits(crm)

    r = client.post(f"/quick-capture/{job_id}", data=confirm_form(crm, job_id))
    assert r.status_code == 303
    assert r.headers["location"].startswith("/companies/acme-robotics/contacts/jane-doe?flash=")
    assert commits(crm) == before + 1
    changed = subprocess.run(["git", "show", "--name-only", "--format=%s", "HEAD"],
                             cwd=crm.state.root, capture_output=True, text=True,
                             check=True).stdout.split("\n")
    assert changed[0].startswith("capture: acme-robotics")
    assert any(p.startswith("companies/acme-robotics/interactions/") for p in changed)
    assert "companies/acme-robotics/contacts/jane-doe.md" in changed

    store = crm.state.store
    company = store.get("acme-robotics")
    it = next(i for i in company.interactions if i.subject == "Wants a proposal")
    assert it.body == TEXT
    on_disk = store.interaction_file("acme-robotics", it.id).read_bytes()
    assert on_disk.endswith(TEXT.encode("utf-8"))
    assert [(t.text, t.due) for t in company.contacts["jane-doe"].tasks] == [
        ("Send Jane the proposal", date(2026, 9, 18))]


def test_a_second_confirm_files_nothing_more(crm, client):
    use_ai(crm)
    job_id = start(client)
    client.post(f"/quick-capture/{job_id}", data=confirm_form(crm, job_id))
    before = commits(crm)
    r = client.post(f"/quick-capture/{job_id}", data=confirm_form(crm, job_id))
    assert r.status_code == 303 and "Already filed" in unquote(r.headers["location"])
    assert commits(crm) == before
    assert "Already filed" in client.get(f"/quick-capture/{job_id}").text


def test_the_typed_text_is_the_body_whatever_the_form_says(crm, client):
    use_ai(crm)
    job_id = start(client, "Met Jane.\r\nShe   said *yes*.")
    client.post(f"/quick-capture/{job_id}",
                data=confirm_form(crm, job_id, body="the model's rewording"))
    it = next(i for i in crm.state.store.get("acme-robotics").interactions
              if i.subject == "Wants a proposal")
    assert it.body == "Met Jane.\nShe   said *yes*.\n"   # line endings as every form


def test_a_problem_shows_the_preview_again_and_writes_nothing(crm, client):
    use_ai(crm)
    job_id = start(client)
    before = commits(crm)
    r = client.post(f"/quick-capture/{job_id}",
                    data=confirm_form(crm, job_id, company="globex-logistics"))
    assert r.status_code == 400
    assert "that person is not at this company" in r.text
    # The people now listed are the newly picked company's.
    assert '<option value="sam-rivera">Sam Rivera</option>' in r.text
    assert commits(crm) == before


def test_a_name_not_in_the_crm_is_offered_not_created(crm, client):
    use_ai(crm, answer(company="Initech", company_slug="", contact="Bill Lumbergh",
                       contact_slug=""))
    job_id = start(client)
    page = client.get(f"/quick-capture/{job_id}").text
    assert "create a new company: Initech" in page
    assert "create a new contact: Bill Lumbergh" in page
    assert crm.state.store.get("initech") is None

    before = commits(crm)
    r = client.post(f"/quick-capture/{job_id}", data=confirm_form(crm, job_id))
    assert r.status_code == 303
    assert commits(crm) == before + 1
    initech = crm.state.store.get("initech")
    assert initech is not None and "bill-lumbergh" in initech.contacts


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


# ------------------------------------------------------------------ the palette


def test_the_palette_offers_capture_with_what_was_typed(crm):
    found = finder.search(crm.state.store, "jane proposal")
    entries = finder.actions(found)
    labels = [a["label"] for a in entries]
    assert labels[-1] == "Ask Hermit: jane proposal"
    capture = entries[-2]
    assert capture == {"label": "Capture: jane proposal", "kind": "go",
                       "url": "/quick-capture?text=jane+proposal"}
    assert not any(a["label"].startswith("Capture") for a in
                   finder.actions(finder.search(crm.state.store, "")))
