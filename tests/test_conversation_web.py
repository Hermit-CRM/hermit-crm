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

"""The LinkedIn conversation import in the web app: the receiver page, the
preview (writes nothing) and the import (one commit).

The server holds no state between preview and import: every request carries the
payload again, and the server parses and plans it afresh. Nothing the client says
about a row is believed; only the person's choices are (the contact, answered
dates, flipped directions, ticks).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from hermitcrm import conversation
from hermitcrm.web import create_app
from conftest import FIXED_NOW
from test_layout import CONFIG, repo  # noqa: F401  (the same git-backed folder)

OWNER = "Sam Sample"
PREVIEW, IMPORT, SHELL = "/extension/conversation/preview", "/extension/conversation", "/extension/conversation"
CONTACT = "voorbeeld/alex-voorbeeld"
ATTACK = "</script><img src=x onerror=alert(1)>"


@pytest.fixture
def app(repo):  # noqa: F811
    return create_app(repo, config={**CONFIG, "owner_name": OWNER}, clock=lambda: FIXED_NOW)


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def store(app):
    s = app.state.store
    s.create_company("Voorbeeld", country="NL")
    s.create_contact("voorbeeld", "Alex", "Voorbeeld",
                     linkedin="https://www.linkedin.com/in/alex-voorbeeld")
    return s


# ---------------------------------------------------------------- helpers


def item(text, *, mine=False, day="", time="", urn=None, who=None, **kw):
    who = who or (OWNER if mine else "Alex Voorbeeld")
    return {"urn": urn, "is_other": not mine, "who": who,
            "who_href": "/in/ACoAAAexample", "day": day, "time": time,
            "inherited": False, "sent_title": "", "text": text, **kw}


def payload(*items, name="Alex Voorbeeld", **extra):
    return {"v": 1, "url": "https://www.linkedin.com/messaging/thread/2-abc/",
            "layout": "page", "other": {"name": name, "href": "/in/ACoAAAexample"},
            "lang": "en", "tz_min": -60, "items": list(items), **extra}


def thread3():
    return payload(
        item("Hi Sam", day="Sep 10", time="9:15 AM", urn="u1"),
        item("Hello Alex", mine=True, time="9:20 AM", urn="u2"),
        item("Great, call Friday?", day="Today", time="8:05 AM", urn="u3"))


def preview(client, data, **extra):
    return client.post(PREVIEW, json={"payload": data, **extra})


def do_import(client, app, data, ticked, **extra):
    return client.post(IMPORT, json={"payload": data, "ticked": ticked,
                                     "csrf_token": app.state.csrf_token,
                                     "contact": CONTACT, **extra})


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha1(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def commits(root: Path) -> int:
    done = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=root,
                          capture_output=True, text=True)
    return int(done.stdout.strip() or 0) if done.returncode == 0 else 0


def interactions(store):
    return sorted(store.get("voorbeeld", refresh=True).interactions,
                  key=lambda i: (i.date, i.id))


def rows(html: str) -> list[str]:
    """The review page's message rows, one string each."""
    return re.findall(r'<li class="cv-row.*?</li>', html, flags=re.S)


# --------------------------------------------------------------- the receiver


def test_the_receiver_page_is_a_shell_that_reads_and_writes_nothing(client, store, repo):
    before = snapshot(repo)
    response = client.get(SHELL)
    assert response.status_code == 200
    assert 'id="conversation"' in response.text
    assert "/static/conversation.js" in response.text
    assert "https://www.linkedin.com" in response.text     # the one origin it listens to
    assert 'class="cv-row' not in response.text             # no conversation text in it
    assert snapshot(repo) == before


def test_the_receiver_page_ignores_a_query_string(client, store):
    # (the Ask panel on every page repeats the address, so the query is in the page;
    # what matters is that the review area stays empty)
    response = client.get(SHELL + "?text=Hi+Sam&payload=x")
    assert response.status_code == 200
    assert '<div id="conversation-review"></div>' in response.text
    assert 'class="cv-row' not in response.text


# ------------------------------------------------------------------- preview


def test_the_preview_shows_who_it_matched_and_one_row_per_message(client, store):
    response = preview(client, thread3())
    assert response.status_code == 200
    html = response.text
    assert "Alex Voorbeeld" in html and "Voorbeeld" in html
    assert "matched" in html.lower()
    found = rows(html)
    assert len(found) == 3
    assert all("checked" in r for r in found)                # all new: all ticked
    assert "Hi Sam" in found[0] and "Great, call Friday?" in found[2]
    assert 'data-direction="in"' in found[0] and 'data-direction="out"' in found[1]
    assert "Sep 10" in html or "2026-09-10" in html          # the first date
    assert "Import 3 messages" in html


def test_a_follow_up_message_shows_its_borrowed_time_with_a_tilde(client, store):
    follow = payload(
        item("One", day="Sep 10", time="9:15 AM", urn="u1"),
        item("Two", time="9:15 AM", urn="u2", inherited=True))
    found = rows(preview(client, follow).text)
    assert "~" not in found[0] and "~" in found[1]


def test_every_value_is_escaped_whether_it_is_a_message_or_a_name(client, store):
    data = payload(item(ATTACK, day="Today", time="8:05 AM", urn=ATTACK, who=ATTACK),
                   name=ATTACK)
    html = preview(client, data).text
    assert "<img src=x" not in html and "</script><img" not in html
    assert "&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;" in html


def test_a_message_that_is_markup_is_escaped_when_the_person_picks_the_contact(client, store):
    data = payload(item(ATTACK, day="Today", time="8:05 AM", urn="u1"))
    html = preview(client, data, contact=CONTACT).text
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_the_preview_writes_nothing(client, store, repo):
    before, count = snapshot(repo), commits(repo)
    assert preview(client, thread3()).status_code == 200
    assert preview(client, thread3(), contact=CONTACT, directions={"0": "out"}).status_code == 200
    assert snapshot(repo) == before and commits(repo) == count
    assert interactions(store) == []


def test_a_preview_over_the_size_cap_is_refused_413(client, store):
    big = payload(item("x" * 100, day="Today", time="8:05 AM"))
    big["junk"] = "y" * (conversation.MAX_TOTAL_BYTES + 400_000)
    assert preview(client, big).status_code == 413


def test_the_cap_does_not_depend_on_the_content_length_header(client, store):
    def chunks():
        for _ in range(40):
            yield b'{"payload": {"junk": "' + b"y" * 40_000 + b'"}}'   # no Content-Length
    response = client.post(PREVIEW, content=chunks(),
                           headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_a_payload_just_under_the_content_cap_still_gets_through(client, store):
    text = "word " * 190_000                                  # about 950 KB of message
    data = payload(item(text, day="Today", time="8:05 AM", urn="u1"))
    assert len(json.dumps(data)) < conversation.MAX_TOTAL_BYTES + 100_000
    assert preview(client, data).status_code == 200


def test_a_preview_sent_from_another_website_is_refused(client, store):
    response = client.post(PREVIEW, json={"payload": thread3()},
                           headers={"sec-fetch-site": "cross-site"})
    assert response.status_code == 403


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b'"text"', b"[" * 5000])
def test_a_body_that_is_not_a_json_object_is_a_400(client, store, body):
    response = client.post(PREVIEW, content=body,
                           headers={"content-type": "application/json"})
    assert response.status_code == 400


def test_a_group_conversation_is_a_clear_message_not_a_stack_trace(client, store):
    data = payload(item("Hi", day="Today", time="8:05 AM"),
                   item("Hello", day="Today", time="8:06 AM", who="Someone Else",
                        who_href="/in/ACoAAAelse"))
    response = preview(client, data)
    assert response.status_code == 200
    assert "group conversations are not supported" in response.text
    assert "Traceback" not in response.text and 'class="cv-row' not in response.text


def test_a_payload_of_the_wrong_shape_is_a_message_too(client, store):
    response = client.post(PREVIEW, json={"payload": {"v": 99}})
    assert response.status_code == 200
    assert "not a conversation Hermit can read" in response.text


def test_an_empty_thread_says_there_is_nothing_to_import(client, store):
    response = preview(client, payload())
    assert response.status_code == 200
    assert "nothing to import" in response.text.lower()


# ------------------------------------------------------------- the contact


def test_two_people_with_one_name_get_a_picker_and_no_rows(client, store):
    other = store.create_company("Other BV", country="NL")
    store.create_contact(other.slug, "Alex", "Voorbeeld")
    html = preview(client, thread3()).text
    assert 'id="cv-contact"' in html
    assert "voorbeeld/alex-voorbeeld" in html and f"{other.slug}/alex-voorbeeld" in html
    assert "more than one" in html.lower()
    assert rows(html) == [] and "matched" not in html.lower()


def test_an_unknown_person_gets_a_picker_and_a_prefilled_create_link(client, store):
    html = preview(client, payload(item("Hi", day="Today", time="8:05 AM", urn="u1"),
                                   name="Nova Nieuw")).text
    assert 'id="cv-contact"' in html and rows(html) == []
    link = re.search(r'href="(/contacts/new\?[^"]+)"', html)
    assert link, "no Create contact link"
    query = parse_qs(urlparse(link[1].replace("&amp;", "&")).query)
    assert query["name"] == ["Nova Nieuw"]


def test_the_picker_lists_every_contact_and_the_persons_pick_wins(client, store):
    store.create_contact("voorbeeld", "Mara", "Mulder")
    html = preview(client, thread3(), contact="voorbeeld/mara-mulder").text
    assert "voorbeeld/mara-mulder" in html and "voorbeeld/alex-voorbeeld" in html
    assert re.search(r'<option value="voorbeeld/mara-mulder"[^>]* selected', html)
    assert len(rows(html)) == 3


def test_a_contact_that_does_not_exist_is_a_message_not_a_crash(client, store):
    response = preview(client, thread3(), contact="voorbeeld/nobody")
    assert response.status_code == 200
    assert "unknown contact" in response.text and rows(response.text) == []


def test_a_contact_value_that_is_not_two_slugs_is_ignored(client, store):
    response = preview(client, thread3(), contact="../../etc/passwd")
    assert response.status_code == 200 and "etc/passwd" not in response.text


def test_the_create_contact_page_opens_prefilled_from_the_query(client, store):
    response = client.get("/contacts/new?name=Nova+Nieuw&linkedin=https%3A%2F%2Fwww.linkedin.com%2Fin%2Fnova")
    assert response.status_code == 200
    assert 'value="Nova Nieuw"' in response.text
    assert 'value="https://www.linkedin.com/in/nova"' in response.text
    assert 'value="&lt;' not in client.get("/contacts/new?name=%3Cb%3E").text.replace("&lt;b&gt;", "")


# --------------------------------------------------- statuses, dates, directions


def test_a_message_already_logged_is_shown_unticked_and_labelled(client, app, store):
    assert do_import(client, app, thread3(), [0, 1, 2]).status_code == 303
    found = rows(preview(client, thread3()).text)
    assert len(found) == 3
    assert all("checked" not in r for r in found)
    assert all("already logged" in r.lower() for r in found)
    assert 'disabled' in found[0]


def test_a_look_alike_is_unticked_labelled_and_can_be_ticked(client, store):
    store.create_interaction("voorbeeld", "linkedin", "in", contact="alex-voorbeeld",
                             date=FIXED_NOW.replace(day=10, hour=9, minute=15), body="Hi Sam")
    found = rows(preview(client, thread3()).text)
    assert "checked" not in found[0] and "may already" in found[0].lower()
    assert "disabled" not in found[0]
    assert "checked" in found[1] and "checked" in found[2]


def test_an_unreadable_day_asks_for_a_date_and_cannot_be_ticked_until_answered(client, store):
    data = payload(item("Hi", day="Fri the 13th", time="9:15 AM", urn="u1"),
                   item("Again", day="Today", time="8:05 AM", urn="u2"))
    html = preview(client, data).text
    assert 'type="date"' in html and "Fri the 13th" in html
    assert 'aria-label="Which day was &#34;Fri the 13th&#34;?"' in html or \
        'aria-label="Which day was &quot;Fri the 13th&quot;?"' in html
    first = rows(html)[0]
    assert "disabled" in first and "checked" not in first
    answered = preview(client, data, dates={"0": "2026-09-04"}).text
    first = rows(answered)[0]
    assert "disabled" not in first and "checked" in first
    assert 'value="2026-09-04"' in answered and "~" not in first


def test_an_unreadable_time_asks_for_the_moment(client, store):
    data = payload(item("Hi", day="Today", time="sometime", urn="u1"))
    assert 'type="datetime-local"' in preview(client, data).text


def test_a_garbled_answer_leaves_the_question_open(client, store):
    data = payload(item("Hi", day="Fri the 13th", time="9:15 AM", urn="u1"))
    html = preview(client, data, dates={"0": "not a date", "7": "2026-01-01", "x": 1}).text
    assert "disabled" in rows(html)[0]


def test_a_flipped_direction_is_what_the_preview_shows(client, store):
    html = preview(client, thread3(), directions={"0": "out", "9": "in", "1": "sideways"}).text
    found = rows(html)
    assert 'data-direction="out"' in found[0]
    assert 'data-direction="out"' in found[1]                 # a nonsense pick changes nothing


def test_a_message_from_a_name_that_does_not_fit_asks_which_way_it_went(client, store):
    data = payload(item("Hi", day="Today", time="8:05 AM", urn="u1", mine=True, who="Pat Else"))
    first = rows(preview(client, data).text)[0]
    assert 'data-direction="ask"' in first and "disabled" in first and "checked" not in first
    chosen = rows(preview(client, data, directions={"0": "out"}).text)[0]
    assert "checked" in chosen and "disabled" not in chosen


def test_a_date_that_is_probably_wrong_carries_a_visible_warning(client, store):
    data = payload(item("Hi", day="Today", time="8:05 AM", urn="u1",
                        sent_title="Sent at 1/2/2024, 8:05 AM"))
    assert "check the date" in rows(preview(client, data).text)[0].lower()


def test_messages_the_page_showed_beyond_the_caps_are_reported(client, store):
    many = payload(*[item(f"m{i}", day="Today", time="8:05 AM", urn=f"u{i}")
                     for i in range(conversation.MAX_MESSAGES + 7)])
    html = preview(client, many).text
    assert "7 older messages were not read" in html


def test_the_ticks_the_person_made_survive_a_preview(client, store):
    found = rows(preview(client, thread3(), ticks={"0": False}).text)
    assert "checked" not in found[0] and "checked" in found[1]


def test_a_long_message_shows_its_first_line_and_the_rest_behind_more(client, store):
    data = payload(item("First line\nsecond line\nthird", day="Today", time="8:05 AM", urn="u1"))
    row = rows(preview(client, data).text)[0]
    assert "<details" in row and "more" in row and "second line" in row


# ----------------------------------------------------- stage and outreach effects


def test_the_review_says_the_company_will_move_before_import(client, store):
    html = preview(client, thread3()).text
    entry, target = store.stages.entry, store.stages.advance_target
    assert f"{entry} to {target}" in html or f"{entry} -&gt; {target}" in html
    do_import(client, client.app, thread3(), [0, 1, 2])
    again = preview(client, payload(*thread3()["items"],
                                    item("Newer", day="Today", time="9:00 AM", urn="u9"))).text
    assert f"{entry} to {target}" not in again


def test_the_review_names_an_outreach_item_an_outbound_message_would_mark_sent(client, store, repo):
    from hermitcrm import outreach
    ready = FIXED_NOW.replace(day=9, hour=8)
    outreach.write_item(repo, outreach.Item(
        id="li-1", state="ready", kind="first-touch", channel="linkedin",
        company="voorbeeld", contact="alex-voorbeeld", body="Hi Alex", language="en",
        ready=ready, created=ready, drafted=ready))
    html = preview(client, thread3()).text
    assert "li-1" in html and "sent" in html.lower()


# -------------------------------------------------------------------- import


def test_import_needs_the_csrf_token(client, app, store, repo):
    before = snapshot(repo)
    bad = client.post(IMPORT, json={"payload": thread3(), "ticked": [0], "contact": CONTACT})
    wrong = client.post(IMPORT, json={"payload": thread3(), "ticked": [0], "contact": CONTACT,
                                      "csrf_token": "nope"})
    assert bad.status_code == 403 and wrong.status_code == 403
    assert snapshot(repo) == before


def test_import_logs_only_the_ticked_messages_in_one_commit(client, app, store, repo):
    count = commits(repo)
    response = do_import(client, app, thread3(), [0, 2])
    assert response.status_code == 303
    target = urlparse(response.headers["location"])
    assert target.path == "/companies/voorbeeld/contacts/alex-voorbeeld"
    assert "2 messages imported" in parse_qs(target.query)["flash"][0]
    logged = interactions(store)
    assert [i.body.strip() for i in logged] == ["Hi Sam", "Great, call Friday?"]
    assert all(i.channel == "linkedin" and i.source == "linkedin-import" for i in logged)
    assert commits(repo) == count + 1


def test_import_applies_a_flipped_direction(client, app, store):
    do_import(client, app, thread3(), [0], directions={"0": "out"})
    assert [i.direction for i in interactions(store)] == ["out"]


def test_import_applies_an_answered_date(client, app, store):
    data = payload(item("Hi", day="Fri the 13th", time="9:15 AM", urn="u1"))
    response = do_import(client, app, data, [0], dates={"0": "2026-09-04"})
    assert response.status_code == 303
    assert interactions(store)[0].date.isoformat().startswith("2026-09-04T09:15")


def test_a_second_import_of_the_same_thread_adds_nothing_and_says_so(client, app, store, repo):
    do_import(client, app, thread3(), [0, 1, 2])
    count, before = commits(repo), len(interactions(store))
    response = do_import(client, app, thread3(), [0, 1, 2])
    assert response.status_code == 303
    flash = parse_qs(urlparse(response.headers["location"]).query)["flash"][0]
    assert flash == "0 messages imported, 3 already logged"
    assert commits(repo) == count and len(interactions(store)) == before


def test_the_flash_counts_what_was_logged_before(client, app, store):
    do_import(client, app, thread3(), [0])
    grown = payload(*thread3()["items"], item("Newer", day="Today", time="9:00 AM", urn="u9"))
    response = do_import(client, app, grown, [0, 1, 2, 3])
    flash = parse_qs(urlparse(response.headers["location"]).query)["flash"][0]
    assert flash == "3 messages imported, 1 already logged"


def test_one_message_is_singular(client, app, store):
    response = do_import(client, app, thread3(), [1])
    assert parse_qs(urlparse(response.headers["location"]).query)["flash"][0] == "1 message imported"


def test_import_refuses_a_row_that_still_needs_an_answer_and_writes_nothing(client, app, store, repo):
    data = payload(item("Hi", day="Fri the 13th", time="9:15 AM", urn="u1"),
                   item("Ok", day="Today", time="8:05 AM", urn="u2"))
    count = commits(repo)
    response = do_import(client, app, data, [0, 1])
    assert response.status_code == 400 and "no date yet" in response.text
    assert commits(repo) == count and interactions(store) == []


def test_import_refuses_a_row_number_the_thread_does_not_have(client, app, store):
    response = do_import(client, app, thread3(), [0, 99])
    assert response.status_code == 400 and interactions(store) == []


@pytest.mark.parametrize("ticked", ["0", [True], [-1], [None], {"0": 1}])
def test_import_ticks_of_the_wrong_shape_are_a_400(client, app, store, ticked):
    assert do_import(client, app, thread3(), ticked).status_code == 400


def test_import_needs_a_contact_that_exists(client, app, store):
    for contact in ("", "voorbeeld/nobody", "../x", 7):
        response = client.post(IMPORT, json={"payload": thread3(), "ticked": [0],
                                             "csrf_token": app.state.csrf_token,
                                             "contact": contact})
        assert response.status_code == 400, contact
    assert interactions(store) == []


def test_import_over_the_cap_is_refused_413(client, app, store):
    big = thread3()
    big["junk"] = "y" * (conversation.MAX_TOTAL_BYTES + 400_000)
    assert do_import(client, app, big, [0]).status_code == 413
    assert interactions(store) == []


def test_import_from_another_website_is_refused(client, app, store):
    response = client.post(IMPORT, json={"payload": thread3(), "ticked": [0],
                                         "csrf_token": app.state.csrf_token,
                                         "contact": CONTACT},
                           headers={"sec-fetch-site": "cross-site"})
    assert response.status_code == 403 and interactions(store) == []


def test_import_of_a_group_conversation_is_a_400(client, app, store):
    data = payload(item("Hi", day="Today", time="8:05 AM"),
                   item("Hello", day="Today", time="8:06 AM", who="Someone Else",
                        who_href="/in/ACoAAAelse"))
    response = do_import(client, app, data, [0])
    assert response.status_code == 400 and "group conversations" in response.text


# ---------------------------------------------------- the receiver's script

JS = Path(__file__).parent.parent / "src" / "hermitcrm" / "static" / "conversation.js"
NODE = shutil.which("node")


def test_the_receiver_script_never_puts_text_into_the_page_as_markup():
    code = JS.read_text(encoding="utf-8")
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                   "eval(", "new Function"):
        assert banned not in code, banned
    assert "https://www.linkedin.com" in code


HARNESS = r"""
const [code, scenario] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const log = [];
const listeners = {};
const mk = () => ({ children: [], dataset: {}, style: {}, textContent: '', hidden: false,
  addEventListener() {}, replaceChildren(...n) { this.children = n; log.push('render'); },
  setAttribute() {}, appendChild(n) { this.children.push(n); }, querySelector: () => null,
  querySelectorAll: () => [], closest: () => null });
const status = mk(), review = mk();
const root = Object.assign(mk(), { dataset: { origin: 'https://www.linkedin.com',
  preview: '/extension/conversation/preview', import: '/extension/conversation',
  csrf: 'tok' } });
const els = { conversation: root, 'conversation-status': status, 'conversation-review': review };
const opener = { postMessage: (m, o) => log.push(['opener', m, o]) };
const win = { opener: scenario.noOpener ? null : opener,
  addEventListener: (t, f) => { listeners[t] = f; }, setTimeout: (f) => { listeners.timer = f; return 1; },
  clearTimeout() {}, location: { assign: (u) => log.push(['go', u]) } };
const fetched = [];
const fetchStub = (url, opts) => { fetched.push([url, JSON.parse(opts.body)]);
  return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('<p>review</p>') }); };
const doc = { getElementById: (id) => els[id] || null, createElement: () => mk(),
  addEventListener(t, f) { (listeners['doc-' + t] = f); }, readyState: 'complete' };
globalThis.DOMParser = class { parseFromString() { return { body: { childNodes: [{}] } }; } };
new Function('window', 'document', 'fetch', 'DOMParser', 'setTimeout', 'clearTimeout', code)(
  win, doc, fetchStub, globalThis.DOMParser, win.setTimeout, win.clearTimeout);
(async () => {
  for (const ev of scenario.events || []) {
    listeners.message && listeners.message({ origin: ev.origin, source: ev.fromOpener === false ? {} : opener, data: ev.data });
    await new Promise((r) => setImmediate(r));
  }
  if (scenario.timeout && listeners.timer) { listeners.timer(); }
  await new Promise((r) => setImmediate(r));
  process.stdout.write(JSON.stringify({ log, fetched, status: status.textContent }));
})();
"""


def run_receiver(scenario: dict) -> dict:
    code = JS.read_text(encoding="utf-8")
    done = subprocess.run([NODE, "-e", HARNESS], input=json.dumps([code, scenario]),
                          capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_receiver_asks_linkedins_tab_for_the_conversation_only_on_linkedins_origin():
    out = run_receiver({})
    assert ["opener", "ready", "https://www.linkedin.com"] in out["log"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_receiver_takes_a_payload_from_linkedins_origin_and_previews_it():
    out = run_receiver({"events": [{"origin": "https://www.linkedin.com", "data": thread3()}]})
    assert [f[0] for f in out["fetched"]] == ["/extension/conversation/preview"]
    assert out["fetched"][0][1]["payload"]["v"] == 1


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("origin", ["https://evil.example", "http://www.linkedin.com",
                                    "https://www.linkedin.com.evil.example", "null", ""])
def test_the_receiver_ignores_a_message_from_any_other_origin(origin):
    out = run_receiver({"events": [{"origin": origin, "data": thread3()}], "timeout": True})
    assert out["fetched"] == []
    assert "did not receive" in out["status"].lower()


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_receiver_ignores_a_message_that_did_not_come_from_the_opener():
    out = run_receiver({"events": [{"origin": "https://www.linkedin.com", "data": thread3(),
                                    "fromOpener": False}], "timeout": True})
    assert out["fetched"] == []


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_message_that_is_not_a_conversation_is_ignored():
    out = run_receiver({"events": [{"origin": "https://www.linkedin.com", "data": "hello"}]})
    assert out["fetched"] == []


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_without_an_opener_the_receiver_says_what_to_try_at_once():
    out = run_receiver({"noOpener": True})
    assert "did not receive" in out["status"].lower()
    assert not any(entry[0] == "opener" for entry in out["log"] if isinstance(entry, list))


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_nothing_arriving_in_a_few_seconds_says_so_and_what_to_try():
    out = run_receiver({"timeout": True})
    assert "did not receive" in out["status"].lower() and "bookmark" in out["status"].lower()


# ------------------------------------------------------------ the Extension page


def test_the_extension_page_offers_both_bookmarks_and_keeps_the_old_one(client):
    html = client.get("/extension").text
    links = re.findall(r'<a class="bookmarklet" href="(javascript:[^"]*)">([^<]*)</a>', html)
    names = [name for _, name in links]
    assert "Add to Hermit CRM" in names and "Hermit: conversation" in names
    conversation_link = next(href for href, name in links if name == "Hermit: conversation")
    link = conversation_link.replace("&#39;", "'")
    assert "var B = 'http://testserver'" in link and "'/extension/conversation'" in link
    assert 'action="/extension/new"' in html                       # the URL box still works


def test_the_extension_page_explains_the_conversation_bookmark_in_plain_words(client):
    text = re.sub(r"<[^>]+>", " ", client.get("/extension").text)
    text = " ".join(text.split())
    assert "nothing is fetched and nothing goes to LinkedIn" in text
    assert "User Agreement" in text and "8.2" in text
    assert "not something LinkedIn has approved" in text
    for step in ("open the conversation", "click the bookmark", "review"):
        assert step in text.lower()


def test_the_extension_help_page_mentions_the_conversation_bookmark(client):
    text = client.get("/help/extension").text
    assert "Hermit: conversation" in text and "User Agreement" in text
