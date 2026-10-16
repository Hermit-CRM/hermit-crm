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

"""Outreach, part 04a: the Outreach page. Build one contact per request,
review a card (save and check, ready, regenerate, skip, sent, findings), the
contact page's card and Research & draft button. The AI and the web are
fakes; all names are made up."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from hermitcrm import outreach
from hermitcrm.datafolder import init_folder
from hermitcrm.store import Store, load_config, split_file
from hermitcrm.web import create_app
from outreach_fakes import NOW, FakeAI, ai, fake_page, git

MARA = "lindenhof-data/mara-keller"


@pytest.fixture
def root(tmp_path):
    return init_folder(tmp_path / "crm", demo=True, now=NOW)


@pytest.fixture
def fake():
    return FakeAI()


@pytest.fixture
def client(root, fake):
    app = create_app(root, {**load_config(root), "push_enabled": False,
                            "owner_name": "Sam Example"})
    app.state.setup_redirected = True
    app.state.enricher = ai(fake)
    app.state.outreach_fetcher = fake_page
    return TestClient(app, follow_redirects=False)


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.app.state.csrf_token, **data})


def commits(root) -> list[str]:
    return git(root, "log", "--format=%s").splitlines()


def query(response) -> dict:
    url = urlparse(response.headers["location"])
    return {k: v[0] for k, v in parse_qs(url.query).items()}


def build_one(client, **form):
    form.setdefault("where", "stage=prospect")
    return post(client, "/outreach/build", **form)


def items(root):
    return outreach.items(root)


def drafted(client, root, contact=MARA) -> outreach.Item:
    response = post(client, "/outreach/build", contact=contact, back="/outreach")
    assert response.status_code == 303, response.text
    return next(i for i in items(root) if i.record == contact)


# ------------------------------------------------------------------ the page


def test_the_page_renders_empty_and_in_the_nav(client):
    page = client.get("/outreach")
    assert page.status_code == 200
    assert 'href="/outreach"' in page.text and "Build queue" in page.text
    assert "No drafts to review" in page.text
    assert "Drafts (0)" in page.text and "Ready (0)" in page.text


def test_preview_runs_no_ai_and_writes_nothing(client, root, fake):
    before = commits(root)
    page = client.get("/outreach", params={"preview": "1", "where": "stage=prospect",
                                           "channel": "email", "limit": "3"})
    assert page.status_code == 200
    assert "would get a draft" in page.text and "Mara Keller" in page.text
    assert "Not this time" in page.text
    assert fake.calls == [] and commits(root) == before


def test_a_bad_filter_says_why(client):
    page = client.get("/outreach", params={"preview": "1", "where": "nonsense=1"})
    assert "unknown filter key" in page.text


# -------------------------------------------------------------------- build


def test_build_makes_one_item_per_request_and_counts_down(client, root, fake):
    first = build_one(client, limit="3")
    assert first.status_code == 303
    q = query(first)
    assert q["left"] == "2" and q["batch"].endswith("-email") and q["tab"] == "drafts"
    assert len(items(root)) == 1 and len(fake.of("draft")) == 1
    second = build_one(client, limit="3", left=q["left"], batch=q["batch"])
    q2 = query(second)
    assert q2["left"] == "1" and q2["batch"] == q["batch"]
    built = items(root)
    assert len(built) == 2 and {i.batch for i in built} == {q["batch"]}
    assert len({i.record for i in built}) == 2
    # the page continues the batch by itself while something is left
    page = client.get("/outreach?" + urlparse(second.headers["location"]).query)
    assert "requestSubmit" in page.text and "Build the next one" in page.text
    # the last one says so and stops
    third = build_one(client, limit="3", left="1", batch=q["batch"])
    assert "left" not in query(third)


def test_build_refuses_with_the_reason_when_the_ai_is_missing(client, root):
    client.app.state.enricher = outreach.default_enricher({"enrich_provider": "none"})
    response = build_one(client)
    assert "Not built" in query(response)["flash"]
    assert items(root) == []


def test_build_refuses_until_the_playbook_is_ready(client, root):
    (root / "MESSAGING.md").write_text("# Just notes\n", encoding="utf-8")
    page = client.get("/outreach")
    assert "will not run yet" in page.text and "Settings &gt; Playbook" in page.text
    response = build_one(client)
    assert query(response)["flash"].startswith("Not built")
    assert "playbook" in query(response)["flash"]
    assert items(root) == []


# --------------------------------------------------------------- card actions


def test_save_and_check_again_is_one_commit_and_keeps_the_text(client, root):
    item = drafted(client, root)
    before = len(commits(root))
    odd = "Hi Mara,  \r\n\r\n\tThe second office caught my eye?\r\nAnd?\r\n\r\nSam"
    response = post(client, f"/outreach/{item.id}/check", subject=item.subject, body=odd)
    assert response.status_code == 303 and response.headers["location"].endswith(
        f"#item-{item.id}")
    assert len(commits(root)) == before + 1
    assert commits(root)[0].startswith(f"outreach: edit {MARA} (email): 1 problem")
    saved = outreach.get_item(root, item.id)
    assert saved.body == odd.replace("\r\n", "\n")          # only the line endings
    assert split_file((root / saved.path).read_text())[1] == saved.body
    assert saved.state == "drafted" and saved.checks == [
        "the message asks 2 questions; it must ask exactly one"]
    page = client.get("/outreach")
    assert "it must ask exactly one" in page.text


def test_mark_ready_with_an_edit_is_one_commit_and_logs_nothing(client, root):
    item = drafted(client, root)
    before = len(commits(root))
    body = item.body.replace("caught my eye", "stood out")
    response = post(client, f"/outreach/{item.id}/ready", subject=item.subject, body=body)
    assert response.status_code == 303
    assert len(commits(root)) == before + 1
    assert commits(root)[0] == f"outreach: ready {MARA} (email)"
    ready = outreach.get_item(root, item.id)
    assert ready.state == "ready" and ready.body == body and ready.edit_distance == 3
    store = Store(root)
    store.load()
    touches = [i for i in store.get("lindenhof-data").interactions
               if i.contact == "mara-keller" and not i.is_note]
    assert not any(i.direction == "out" and i.date and i.date.date() == NOW.date()
                   for i in touches if i.body == body)
    page = client.get("/outreach?tab=ready")
    assert "Ready (1)" in page.text and "Log it" in page.text and "Mark sent" in page.text


def test_mark_ready_with_a_failing_check_warns_and_keeps_it(client, root):
    item = drafted(client, root)
    body = item.body.replace("deal size?", "deal size.")
    response = post(client, f"/outreach/{item.id}/ready", subject=item.subject, body=body)
    assert "Warning" in query(response)["flash"]
    ready = outreach.get_item(root, item.id)
    assert ready.state == "ready"
    assert ready.checks == ["the message asks 0 questions; it must ask exactly one"]


def test_skip_needs_a_reason_and_is_one_commit(client, root):
    item = drafted(client, root)
    before = len(commits(root))
    refused = post(client, f"/outreach/{item.id}/skip", reason="")
    assert "say why" in query(refused)["flash"] and len(commits(root)) == before
    post(client, f"/outreach/{item.id}/skip", reason="bad-timing", note="  after  summer ")
    skipped = outreach.get_item(root, item.id)
    assert skipped.state == "skipped" and skipped.skip_note == "after summer"
    assert len(commits(root)) == before + 1
    assert "Skipped (1)" in client.get("/outreach?tab=skipped").text


def test_mark_sent_changes_only_the_state(client, root):
    item = drafted(client, root)
    post(client, f"/outreach/{item.id}/ready", subject=item.subject, body=item.body)
    post(client, f"/outreach/{item.id}/sent")
    sent = outreach.get_item(root, item.id)
    assert sent.state == "sent" and sent.sent_with == "" and sent.body == item.body
    # a sent item cannot be edited, regenerated or get other findings
    for what in ("check", "regenerate", "findings"):
        response = post(client, f"/outreach/{item.id}/{what}", body="x", add="x")
        assert "only a drafted item" in query(response)["flash"]
    assert outreach.get_item(root, item.id) == sent


def test_regenerate_keeps_the_findings_and_replaces_the_ai_text(client, root, fake):
    item = drafted(client, root)
    fake.drafts = [lambda prompt: {
        "subject": "Another subject", "angle": "scale",
        "body": "Hi Mara,\n\nYour second office stood out.\nWhere does it hurt most?"
                "\n\nSam", "pitch": "", "findings_used": [2], "proof_used": []}]
    research_calls = len(fake.of("research"))
    before = len(commits(root))
    post(client, f"/outreach/{item.id}/regenerate", strong="1")
    again = outreach.get_item(root, item.id)
    assert len(fake.of("research")) == research_calls      # no new research
    assert again.subject == again.ai_subject == "Another subject"
    assert again.angle == "scale" and again.state == "drafted"
    assert [f.text for f in again.findings] == [f.text for f in item.findings]
    assert len(commits(root)) == before + 1
    assert commits(root)[0].startswith(f"outreach: regenerate {MARA}")


def test_a_finding_of_your_own_is_used_by_a_regenerate(client, root, fake):
    item = drafted(client, root)
    n = len(item.findings)
    post(client, f"/outreach/{item.id}/findings", add="  Hiring a  second AE ",
         kind="trigger", remove="1")
    changed = outreach.get_item(root, item.id)
    assert len(changed.findings) == n            # one removed, one added
    mine = changed.findings[-1]
    assert (mine.text, mine.source, mine.confidence, mine.kind) == (
        "Hiring a second AE", outreach.YOURS, "high", "trigger")
    assert commits(root)[0] == f"outreach: findings {MARA}: removed 1, added 1"
    fake.drafts = [lambda prompt: {
        "subject": "Your second AE", "angle": "hook",
        "body": "Hi Mara,\n\nHiring a second AE is a big step.\nWho will coach them?"
                "\n\nSam", "pitch": "", "findings_used": [n], "proof_used": []}]
    post(client, f"/outreach/{item.id}/regenerate")
    again = outreach.get_item(root, item.id)
    assert "Hiring a second AE" in fake.of("draft")[-1]["prompt"]
    assert again.checks == [] and again.findings[-1].used


def test_every_post_checks_csrf_and_ids(client, root):
    item = drafted(client, root)
    for what in outreach_actions():
        assert client.post(f"/outreach/{item.id}/{what}",
                           data={"csrf_token": "wrong"}).status_code == 403
        assert post(client, f"/outreach/no-such-item/{what}").status_code == 404
    assert client.post("/outreach/build", data={"csrf_token": "x"}).status_code == 403
    assert post(client, f"/outreach/{item.id}/delete").status_code == 404


def outreach_actions():
    return ("check", "ready", "regenerate", "skip", "sent", "findings")


# --------------------------------------------------------------- contact page


def test_the_contact_page_has_the_button_then_the_card(client, root):
    page = client.get("/companies/lindenhof-data/contacts/mara-keller")
    assert "Research &amp; draft" in page.text and f'value="{MARA}"' in page.text
    item = drafted(client, root)
    page = client.get("/companies/lindenhof-data/contacts/mara-keller")
    assert "Research &amp; draft" not in page.text
    assert f"#item-{item.id}" in page.text and "drafted" in page.text


def test_the_contact_button_refuses_with_the_reason(client, root):
    back = "/companies/ravenmoor-systems/contacts/"
    store = Store(root)
    store.load()
    company = store.get("ravenmoor-systems")
    contact = next(iter(company.contacts))
    response = post(client, "/outreach/build", contact=f"ravenmoor-systems/{contact}",
                    back=back + contact)
    assert response.headers["location"].startswith(back + contact)
    assert "do not contact" in query(response)["flash"].lower() or \
        "do-not-contact" in query(response)["flash"]
    assert items(root) == []
