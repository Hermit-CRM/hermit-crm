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

"""Outreach send, M4: the LinkedIn session. The person sends every touch on
linkedin.com themselves; Hermit paces them, keeps the caps and logs exactly what
was sent. Nothing here may touch the network, and the tests check that."""

from __future__ import annotations

import socket
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import URL, QueryParams

from hermitcrm import linkedin, outreach
from hermitcrm.store import load_config
from hermitcrm.web import create_app
from outreach_fakes import NOW, git
from send_fakes import make_folder

T0 = datetime(2026, 10, 19, 10, 0)
NOTE = "Hi Lena, I read about the second office. Where does it hurt most right now?"
PITCH = "Thanks for connecting, Lena. I help founders build a sales team that sells without them."
CFG = linkedin.LinkedInSettings()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the LinkedIn session reached for the network")
    for name in ("create_connection", "getaddrinfo", "gethostbyname"):
        monkeypatch.setattr(socket, name, refuse)


@pytest.fixture
def folder(tmp_path):
    root, store, settings = make_folder(tmp_path)
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "setup")
    return root, store


def add(root, store, n, kind="first-touch", **extra):
    """n ready LinkedIn items, each for its own company and contact."""
    saved, store.on_write = store.on_write, None
    ids = []
    try:
        for k in range(n):
            company = store.create_company(f"Li {len(store.companies):02d}", country="NL")
            contact = store.create_contact(
                company.slug, "Pat", f"L{len(store.companies):02d}",
                linkedin=f"https://www.linkedin.com/in/pat-{company.slug}")
            item = outreach.Item(
                id=f"li-{company.slug}", state="ready", kind=kind, channel="linkedin",
                company=company.slug, contact=contact.slug, body=NOTE, pitch=PITCH,
                language="en", ready=NOW, created=NOW, drafted=NOW, angle="hook",
                **extra)
            outreach.write_item(root, item)
            ids.append(item.id)
    finally:
        store.on_write = saved
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "items")
    return ids


def cfg(**kw) -> linkedin.LinkedInSettings:
    return linkedin.LinkedInSettings(**kw)


def started(store, now=T0, settings=CFG):
    return linkedin.start(store, now, settings)


# ----------------------------------------------------------- settings, pace


def test_the_settings_are_the_decided_ones_and_unreadable_values_fall_back():
    s = linkedin.settings_from_config({})
    assert (s.invites_per_day, s.invites_per_week, s.messages_per_day) == (20, 80, 40)
    assert (s.session_size, s.gap, s.break_minutes) == (10, (45, 120), 120)
    odd = linkedin.settings_from_config({"linkedin_invites_per_day": "many",
                                         "linkedin_gap_seconds": [120, 45],
                                         "linkedin_session_size": 0,
                                         "linkedin_session_break_minutes": 0})
    assert odd.invites_per_day == 20 and odd.gap == (45, 120) and odd.session_size == 10
    assert odd.break_minutes == 0
    assert linkedin.settings_from_config({"linkedin_gap_seconds": "x"}).gap == (45, 120)


def test_the_countdown_is_seeded_between_45_and_120_seconds():
    values = [linkedin.countdown(f"item-{k}", CFG) for k in range(300)]
    assert all(45 <= v <= 120 for v in values) and len(set(values)) > 40
    assert linkedin.countdown("item-3", CFG) == linkedin.countdown("item-3", CFG)
    assert linkedin.countdown("x", cfg(gap=(60, 60))) == 60


# ----------------------------------------------------------- the queue


def test_the_queue_is_answers_then_notes_then_pitches_oldest_first(folder):
    root, store = folder
    notes = add(root, store, 2)
    (reply,) = add(root, store, 1, kind="reply-to-interest")
    (pitch,) = add(root, store, 1)
    item = outreach.get_item(root, pitch)
    item.state, item.invite_sent, item.accepted = "sent", T0 - timedelta(days=3), T0 - timedelta(days=1)
    outreach.write_item(root, item)
    later = outreach.get_item(root, notes[0])
    later.ready = NOW + timedelta(hours=2)
    outreach.write_item(root, later)
    kinds = [(c.item.id, c.kind) for c in linkedin.queue(store, T0)]
    assert kinds == [(reply, "message"), (notes[1], "note"), (notes[0], "note"), (pitch, "pitch")]
    assert linkedin.queue(store, T0)[0].text == NOTE
    assert linkedin.queue(store, T0)[-1].text == PITCH
    assert all(c.limit in (300, 600) for c in linkedin.queue(store, T0))


def test_other_channels_and_other_states_are_not_in_the_queue(folder):
    root, store = folder
    (a, b, c) = add(root, store, 3)
    item = outreach.get_item(root, a)
    item.channel = "email"
    outreach.write_item(root, item)
    item = outreach.get_item(root, b)
    item.state = "drafted"
    outreach.write_item(root, item)
    assert [x.item.id for x in linkedin.queue(store, T0)] == [c]


# ----------------------------------------------------------- the session


def test_no_card_without_a_session_and_a_session_starts_once(folder):
    root, store = folder
    add(root, store, 2)
    assert linkedin.next_card(store, T0, CFG).reason == "no session is running"
    session = started(store)
    assert session.active and session.count == 0
    with pytest.raises(outreach.OutreachError, match="a session is running"):
        linkedin.start(store, T0, CFG)
    nxt = linkedin.next_card(store, T0, CFG)
    assert nxt.card is not None and nxt.wait == 0 and nxt.card.kind == "note"
    linkedin.end(store, T0 + timedelta(minutes=5))
    assert not linkedin.Session.load(root).active


def test_sent_logs_the_exact_text_marks_the_item_and_starts_the_countdown(folder):
    root, store = folder
    (item_id,) = add(root, store, 2, framework="connection-problem-objection")[:1]
    started(store)
    head = git(root, "rev-list", "--count", "HEAD")
    item = linkedin.sent(store, item_id, T0, CFG)
    assert item.state == "sent" and item.invite_sent == T0 and item.sent == T0
    assert item.pitch_sent is None and item.accepted is None
    company = store.get(item.company)
    (it,) = [i for i in company.interactions if i.source == "outreach"]
    assert (it.channel, it.direction, it.contact, it.date) == ("linkedin", "out", item.contact, T0)
    assert it.body.rstrip("\n") == NOTE and it.angle == "hook"
    assert it.framework == "connection-problem-objection"
    assert item.sent_with == it.id
    assert int(git(root, "rev-list", "--count", "HEAD")) == int(head) + 1       # one commit
    assert git(root, "status", "--porcelain").strip() == ""
    session = linkedin.Session.load(root)
    assert session.count == 1 and f"{item_id}:note" in session.handled
    assert session.unlock == T0 + timedelta(seconds=linkedin.countdown(item_id, CFG))
    nxt = linkedin.next_card(store, T0 + timedelta(seconds=10), CFG)
    assert nxt.card.item.id != item_id and nxt.wait == linkedin.countdown(item_id, CFG) - 10
    assert linkedin.next_card(store, T0 + timedelta(seconds=130), CFG).wait == 0


def test_a_sent_card_with_nothing_left_is_refused(folder):
    root, store = folder
    (item_id,) = add(root, store, 1)
    started(store)
    linkedin.sent(store, item_id, T0, CFG)
    with pytest.raises(outreach.OutreachError, match="nothing left to send"):
        linkedin.sent(store, item_id, T0 + timedelta(minutes=5), CFG)


def test_the_session_ends_after_its_size_and_the_next_waits_for_the_break(folder):
    root, store = folder
    ids = add(root, store, 4)
    small = cfg(session_size=3, break_minutes=120)
    started(store, settings=small)
    now = T0
    for item_id in ids[:3]:
        linkedin.sent(store, item_id, now, small)
        now += timedelta(minutes=3)
    session = linkedin.Session.load(root)
    assert session.count == 3 and not session.active and session.ended is not None
    nxt = linkedin.next_card(store, now, small, session)
    assert nxt.card is None and nxt.reason == "no session is running"
    ok, why = linkedin.can_start(session, now, small)
    assert not ok and why == f"the next session can start at {session.ended + timedelta(minutes=120):%H:%M} (a break of 120 minutes)"
    with pytest.raises(outreach.OutreachError, match="No new session"):
        linkedin.start(store, now, small)
    assert linkedin.can_start(session, session.ended + timedelta(minutes=120), small) == (True, "")
    again = linkedin.start(store, session.ended + timedelta(minutes=121), small)
    assert again.active and again.count == 0 and again.handled == []


def test_a_full_ten_card_session_end_to_end(folder):
    root, store = folder
    ids = add(root, store, 12)
    started(store)
    now = T0
    for k in range(10):
        nxt = linkedin.next_card(store, now, CFG)
        assert nxt.card is not None, k
        now += timedelta(seconds=nxt.wait)
        linkedin.sent(store, nxt.card.item.id, now, CFG)
        now += timedelta(seconds=30)
    assert not linkedin.Session.load(root).active
    logged = [i for c in store.companies.values() for i in c.interactions
              if i.source == "outreach" and i.channel == "linkedin"]
    assert len(logged) == 10 and all(i.body.rstrip("\n") == NOTE for i in logged)
    assert sum(1 for i in ids if outreach.get_item(root, i).state == "sent") == 10


# ------------------------------------------------------------------- caps


def test_the_counters_count_invites_by_day_and_rolling_week_and_messages_by_day(folder):
    root, store = folder
    ids = add(root, store, 4)
    for k, when in enumerate([T0 - timedelta(days=8), T0 - timedelta(days=3), T0 - timedelta(hours=1),
                              T0 - timedelta(minutes=5)]):
        item = outreach.get_item(root, ids[k])
        item.state, item.invite_sent, item.sent = "sent", when, when
        outreach.write_item(root, item)
    store.create_interaction(outreach.get_item(root, ids[3]).company, "linkedin", "out",
                             contact=outreach.get_item(root, ids[3]).contact, body=NOTE,
                             source="outreach", date=T0 - timedelta(minutes=5))
    store.create_interaction(outreach.get_item(root, ids[2]).company, "linkedin", "out",
                             contact=outreach.get_item(root, ids[2]).contact, body="hello",
                             source="outreach", date=T0 - timedelta(hours=1))
    store.create_interaction(outreach.get_item(root, ids[2]).company, "linkedin", "out",
                             contact=outreach.get_item(root, ids[2]).contact, body="by hand",
                             date=T0 - timedelta(hours=1))
    have = linkedin.counters(store, T0, CFG)
    assert (have.invites_today, have.invites_week) == (2, 3)       # the 8-day-old one is out
    assert have.messages_today == 0                                # both outreach touches were invites
    assert have.invites_left == 18 and have.messages_left == 40
    store.create_interaction(outreach.get_item(root, ids[0]).company, "linkedin", "out",
                             contact=outreach.get_item(root, ids[0]).contact, body="a message",
                             source="outreach", date=T0 - timedelta(minutes=1))
    assert linkedin.counters(store, T0, CFG).messages_today == 1
    assert linkedin.counters(store, T0 + timedelta(days=1), CFG).invites_today == 0


def test_the_invite_caps_hold_per_day_and_per_week_while_messages_still_go(folder):
    root, store = folder
    notes = add(root, store, 3)
    (pitch,) = add(root, store, 1)
    item = outreach.get_item(root, pitch)
    item.state, item.invite_sent, item.accepted = "sent", T0 - timedelta(days=2), T0 - timedelta(hours=2)
    outreach.write_item(root, item)
    day = cfg(invites_per_day=1)
    started(store, settings=day)
    linkedin.sent(store, notes[0], T0, day)
    nxt = linkedin.next_card(store, T0 + timedelta(minutes=5), day)
    assert nxt.card.kind == "pitch" and nxt.card.item.id == pitch          # notes wait, pitches go
    linkedin.sent(store, pitch, T0 + timedelta(minutes=5), day)
    nothing = linkedin.next_card(store, T0 + timedelta(minutes=10), day)
    assert nothing.card is None and nothing.reason == "the invite cap is reached (1/1 today, 2/80 this week)"
    week = cfg(invites_per_week=2, invites_per_day=20)
    assert linkedin.counters(store, T0 + timedelta(days=1), week).invites_left == 0   # 2 in the last 7 days
    assert linkedin.next_card(store, T0 + timedelta(days=1), week,
                              linkedin.Session(root=root, started=T0, unlock=T0)).card is None


def test_the_message_cap_holds_and_notes_still_go(folder):
    root, store = folder
    (reply,) = add(root, store, 1, kind="follow-up")
    (note,) = add(root, store, 1)
    (earlier,) = add(root, store, 1)                    # someone you messaged an hour ago
    small = cfg(messages_per_day=1)
    store.create_interaction(outreach.get_item(root, earlier).company, "linkedin", "out",
                             contact=outreach.get_item(root, earlier).contact, body="earlier",
                             source="outreach", date=T0 - timedelta(hours=1))
    started(store, settings=small)
    nxt = linkedin.next_card(store, T0, small)
    assert nxt.card.item.id == note and nxt.card.kind == "note"         # the follow-up waits
    assert reply not in (c.item.id for c in [nxt.card])
    linkedin.sent(store, note, T0, small)
    done = linkedin.next_card(store, T0 + timedelta(minutes=5), small)
    assert done.card is None and "message cap is reached" in done.reason


def test_a_weekly_limit_message_from_linkedin_pauses_invites_until_the_count_drops(folder):
    root, store = folder
    ids = add(root, store, 3)
    old = outreach.get_item(root, ids[2])
    old.state, old.invite_sent = "sent", T0 - timedelta(days=6)
    outreach.write_item(root, old)
    started(store)
    text = linkedin.couldnt_send(store, ids[0], "weekly-limit", "", T0, CFG)
    assert text == "Invites are paused until the 7-day count drops."
    assert outreach.get_item(root, ids[0]).send_note == "LinkedIn said the weekly invite limit is reached"
    assert outreach.get_item(root, ids[0]).state == "ready"
    nxt = linkedin.next_card(store, T0 + timedelta(minutes=5), CFG)
    assert nxt.card is None and "LinkedIn's weekly invite limit was hit" in nxt.reason
    assert linkedin.counters(store, T0, CFG).blocked
    # a day later the old invite (6 days old) has dropped out of the 7 days: invites may go again
    later = T0 + timedelta(days=1, hours=1)
    assert not linkedin.counters(store, later, CFG).blocked
    assert linkedin.counters(store, T0 + timedelta(days=8), CFG).blocked is False


# --------------------------------------------------------------- the actions


def test_already_connected_turns_the_card_into_the_message(folder):
    root, store = folder
    (item_id,) = add(root, store, 1)
    started(store)
    item = linkedin.already_connected(store, item_id, T0)
    assert item.accepted == T0 and item.invite_sent is None and item.state == "ready"
    card = linkedin.queue(store, T0)[0]
    assert card.kind == "pitch" and card.text == PITCH
    done = linkedin.sent(store, item_id, T0, CFG)
    assert done.state == "sent" and done.pitch_sent == T0 and done.invite_sent is None
    (it,) = [i for c in store.companies.values() for i in c.interactions if i.source == "outreach"]
    assert it.body.rstrip("\n") == PITCH
    assert linkedin.counters(store, T0, CFG).invites_today == 0          # a message, not an invite
    assert linkedin.counters(store, T0, CFG).messages_today == 1
    with pytest.raises(outreach.OutreachError, match="not waiting for a connection note"):
        linkedin.already_connected(store, item_id, T0)


def test_already_connected_needs_a_message_to_send(folder):
    root, store = folder
    (item_id,) = add(root, store, 1)
    item = outreach.get_item(root, item_id)
    item.pitch = ""
    outreach.write_item(root, item)
    with pytest.raises(outreach.OutreachError, match="no message to send to a connection"):
        linkedin.already_connected(store, item_id, T0)


def test_couldnt_send_skips_a_gone_profile_and_leaves_the_rest(folder):
    root, store = folder
    a, b = add(root, store, 2)
    started(store)
    assert linkedin.couldnt_send(store, a, "profile-gone", "404", T0, CFG) == "Skipped: the profile is gone."
    skipped = outreach.get_item(root, a)
    assert skipped.state == "skipped" and skipped.skip_reason == "other"
    assert skipped.skip_note == "LinkedIn profile gone: 404"
    assert linkedin.couldnt_send(store, b, "other", "page would not load", T0, CFG) == "Left for another time."
    left = outreach.get_item(root, b)
    assert left.state == "ready" and left.send_note == "could not send on LinkedIn: page would not load"
    assert linkedin.next_card(store, T0, CFG).card is None          # not offered again this session
    assert linkedin.Session.load(root).count == 0                   # it was not sent
    with pytest.raises(outreach.OutreachError, match="say why"):
        linkedin.couldnt_send(store, b, "bored", "", T0, CFG)
    linkedin.end(store, T0)
    started(store, now=T0 + timedelta(hours=3))
    assert linkedin.next_card(store, T0 + timedelta(hours=3), CFG).card.item.id == b


def test_a_gone_profile_on_a_pitch_card_does_not_try_to_skip_a_sent_item(folder):
    root, store = folder
    (item_id,) = add(root, store, 1)
    item = outreach.get_item(root, item_id)
    item.state, item.invite_sent, item.accepted = "sent", T0 - timedelta(days=2), T0
    outreach.write_item(root, item)
    started(store)
    linkedin.couldnt_send(store, item_id, "profile-gone", "", T0, CFG)
    after = outreach.get_item(root, item_id)
    assert after.state == "sent" and after.send_note == "LinkedIn profile gone"


# ------------------------------------------------- waiting, accepted, reminder


def test_accepted_brings_the_pitch_into_the_queue_and_a_sent_pitch_closes_the_loop(folder):
    root, store = folder
    (item_id,) = add(root, store, 1, framework="connection-problem-objection")
    started(store)
    linkedin.sent(store, item_id, T0, CFG)
    (row,) = linkedin.waiting(store, T0 + timedelta(days=2))
    assert row["item"].id == item_id and row["days"] == 2 and not row["remind"]
    assert linkedin.queue(store, T0) == []                           # the note is done; the pitch is not yet
    item = linkedin.accepted(store, item_id, T0 + timedelta(days=2))
    assert item.accepted == T0 + timedelta(days=2)
    assert linkedin.waiting(store, T0 + timedelta(days=2)) == []
    (card,) = linkedin.queue(store, T0)
    assert card.kind == "pitch" and card.text == PITCH
    linkedin.end(store, T0)
    later = T0 + timedelta(days=2, hours=3)
    started(store, now=later)
    done = linkedin.sent(store, item_id, later, CFG)
    assert done.pitch_sent == later and done.state == "sent"
    assert linkedin.queue(store, later) == []
    bodies = sorted(i.body.rstrip("\n") for c in store.companies.values() for i in c.interactions
                    if i.source == "outreach")
    assert bodies == sorted([NOTE, PITCH])
    # the pitch goes out after the item is `sent`, so only the explicit pass gives it the framework
    assert {i.framework for c in store.companies.values() for i in c.interactions
            if i.source == "outreach"} == {"connection-problem-objection"}
    with pytest.raises(outreach.OutreachError, match="not a pending invite"):
        linkedin.accepted(store, item_id, later)


def test_an_invite_pending_for_21_days_gets_a_reminder_and_withdrawn_clears_it(folder):
    root, store = folder
    a, b = add(root, store, 2)
    for item_id, days in ((a, 22), (b, 5)):
        item = outreach.get_item(root, item_id)
        item.state, item.invite_sent = "sent", T0 - timedelta(days=days)
        outreach.write_item(root, item)
    rows = linkedin.waiting(store, T0)
    assert [(r["item"].id, r["days"], r["remind"]) for r in rows] == [(a, 22, True), (b, 5, False)]
    linkedin.withdrawn(store, a, T0)
    assert [r["item"].id for r in linkedin.waiting(store, T0)] == [b]
    assert outreach.get_item(root, a).send_note == "withdrawn"
    with pytest.raises(outreach.OutreachError, match="not a pending invite"):
        linkedin.withdrawn(store, a, T0)               # it is no longer pending
    with pytest.raises(outreach.OutreachError, match="no outreach item"):
        linkedin.withdrawn(store, "li-missing", T0)


# ------------------------------------------------------------------- the web


@pytest.fixture
def client(folder):
    root, store = folder
    app = create_app(root, {**load_config(root), "push_enabled": False})
    app.state.setup_redirected = True
    return TestClient(app, follow_redirects=False)


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.app.state.csrf_token, **data})


def flash(response) -> str:
    return QueryParams(URL(response.headers["location"]).query).get("flash", "")


def test_the_session_page_walks_through_a_card(folder, client):
    root, store = folder
    (item_id,) = add(root, store, 1)
    client.app.state.store.load()
    page = client.get("/outreach/linkedin").text
    assert "Start session" in page and "Invites today <strong>0/20</strong>" in page
    assert client.post("/outreach/linkedin/start", data={}).status_code == 403
    resp = post(client, "/outreach/linkedin/start")
    assert "Session started" in flash(resp)
    page = client.get("/outreach/linkedin").text
    assert "Open profile &amp; copy" in page and NOTE in page and 'data-url="https://www.linkedin.com/in/pat-' in page
    assert "/ 300 characters" in page and "Already connected" in page and "Couldn't send" in page
    assert client.post(f"/outreach/linkedin/{item_id}/sent", data={}).status_code == 403
    resp = post(client, f"/outreach/linkedin/{item_id}/sent")
    assert "Logged: the message is on the contact exactly as you sent it." in flash(resp)
    page = client.get("/outreach/linkedin").text
    assert "Waiting to accept (1)" in page and "Accepted" in page and "Withdrawn" in page
    assert "Invites today <strong>1/20</strong>" in page
    resp = post(client, f"/outreach/linkedin/{item_id}/accepted")
    assert "Accepted: their message is in the queue." in flash(resp)
    assert "Waiting to accept (0)" in client.get("/outreach/linkedin").text


def test_the_page_shows_the_break_and_refuses_an_early_start(folder, client):
    root, store = folder
    add(root, store, 1)
    ended = datetime.now().replace(microsecond=0) - timedelta(minutes=30)
    linkedin.Session(root=root, started=ended - timedelta(minutes=10), ended=ended, count=10).save()
    page = client.get("/outreach/linkedin").text
    assert "the next session can start at" in page and "Start session" not in page
    assert "No new session" in flash(post(client, "/outreach/linkedin/start"))


def test_the_actions_say_what_went_wrong_and_the_strip_shows_the_counters(folder, client):
    root, store = folder
    (item_id,) = add(root, store, 1)
    client.app.state.store.load()
    post(client, "/outreach/linkedin/start")
    assert "not a pending invite" in flash(post(client, f"/outreach/linkedin/{item_id}/accepted"))
    resp = post(client, f"/outreach/linkedin/{item_id}/failed", reason="weekly-limit")
    assert flash(resp) == "Invites are paused until the 7-day count drops."
    page = client.get("/outreach/linkedin").text
    assert "invites paused: LinkedIn's weekly limit was hit" in page
    strip = client.get("/outreach").text
    assert "LinkedIn:" in strip and "invites 0/20 today" in strip and "this week" in strip
    assert client.post("/outreach/linkedin/nope/sent", data={"csrf_token": client.app.state.csrf_token}).status_code == 404
    assert post(client, f"/outreach/linkedin/{item_id}/dance").status_code == 404
    assert "Session ended." in flash(post(client, "/outreach/linkedin/end"))
