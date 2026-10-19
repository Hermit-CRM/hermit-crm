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

"""Outreach send, M2: schedule and spacing. The queue operations, the worker tick
(`hermitcrm send due`), the CLI that drives them, doctor's checks. SMTP and IMAP
are in-memory doubles and the clock is passed in; no test touches the network."""

from __future__ import annotations

import imaplib
import re
import smtplib
import socket
from datetime import datetime, timedelta

import pytest

from hermitcrm import cli, doctor, outreach, send, sendqueue
from hermitcrm.store import load_config
from outreach_fakes import NOW, git
from send_fakes import (GOOD_PASSWORD, MARA, FakeImap, FakeSmtp, auth_error, data_error,
                        make_folder, ready_item)

OPT_OUT = "If this is not for you, tell me and I will not write again."
MON = datetime(2026, 10, 19, 8, 0)
BODY = ("Hi Pat,\n\nThe second office this autumn caught my eye. Where does it hurt most "
        "right now: pipeline, conversion or deal size?\n\nSam\n\n" + OPT_OUT + "\n")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a test reached for the network")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setenv("HERMITCRM_SEND_PASSWORD", GOOD_PASSWORD)


@pytest.fixture
def folder(tmp_path):
    root, store, settings = make_folder(tmp_path)
    path = root / "MESSAGING.md"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "approaches:", f"opt_out: {OPT_OUT}\napproaches:", 1), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "setup")
    return root, store, settings


def many_ready(root, store, n, **kw):
    """n ready email items, each for its own company and contact."""
    saved, store.on_write = store.on_write, None
    ids = []
    try:
        for k in range(n):
            company = store.create_company(f"Co {k:02d}", country="NL")
            contact = store.create_contact(company.slug, "Pat", f"N{k:02d}",
                                           email=f"pat{k:02d}@co{k:02d}.example.org")
            item = ready_item(root, store, item_id=f"i{k:02d}", company=company.slug,
                              contact=contact.slug, body=BODY, **kw)
            ids.append(item.id)
    finally:
        store.on_write = saved
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "items")
    return ids


def scanned(root, now):
    """Say the delivery reports were read just now, so a tick is only about sending."""
    send.SendState.load(root).mark_scan(now)


def tick(root, store, now, smtp, imap, scan=False, **kw):
    if not scan:
        scanned(root, now)
    return sendqueue.due(root, now=now, store=store, smtp_factory=smtp.factory,
                         imap_factory=imap.factory, **kw)


# ------------------------------------------------------------------ schedule


def test_schedule_queues_ready_items_with_times_and_a_hash(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 4)
    before = git(root, "rev-list", "--count", "HEAD")
    result = sendqueue.schedule(store, ids, settings, MON)
    assert [i.id for i in result.scheduled] == ids and not result.refused
    items = [outreach.get_item(root, i) for i in ids]
    assert all(i.state == "queued" and i.queued == MON and i.send_at for i in items)
    assert all(i.send_hash == send.text_hash(i.subject, i.body) for i in items)
    times = [i.send_at for i in items]
    assert times == sorted(times) and len(set(times)) == 4
    assert times[0] >= MON + timedelta(minutes=10) and times[0] >= datetime(2026, 10, 19, 8, 30)
    assert all((b - a) >= timedelta(minutes=3) for a, b in zip(times, times[1:]))
    assert result.times == {i.id: i.send_at for i in items}
    commits = int(git(root, "rev-list", "--count", "HEAD")) - int(before)
    assert commits == 2                                  # the queueing, then the times
    assert git(root, "status", "--porcelain").strip() == ""


def test_a_dry_run_shows_the_times_the_real_run_gives_and_writes_nothing(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 5)
    head = git(root, "rev-parse", "HEAD")
    dry = sendqueue.schedule(store, ids, settings, MON, dry_run=True)
    assert git(root, "rev-parse", "HEAD") == head
    assert all(outreach.get_item(root, i).state == "ready" for i in ids)
    real = sendqueue.schedule(store, ids, settings, MON)
    assert dry.times == real.times and len(dry.times) == 5
    assert dry.lines()[0].startswith(f"{ids[0]} | Mon 19 Oct ")


def test_ten_items_scheduled_in_the_morning_fill_the_week_one_cap_of_10(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 13)
    sendqueue.schedule(store, ids, settings, MON)
    days = {}
    for i in ids:
        days.setdefault(outreach.get_item(root, i).send_at.date(), []).append(i)
    assert [len(v) for v in days.values()] == [10, 3]


def test_what_cannot_be_scheduled_is_listed_with_the_reason_and_left_alone(folder):
    root, store, settings = folder
    a, b, c, d = many_ready(root, store, 4)
    store.update_contact(outreach.get_item(root, a).company, outreach.get_item(root, a).contact,
                         email="")
    it = outreach.get_item(root, b)
    it.body = it.body.replace(OPT_OUT, "")
    outreach.write_item(root, it)
    it = outreach.get_item(root, c)
    it.state = "drafted"
    outreach.write_item(root, it)
    result = sendqueue.schedule(store, [a, b, c, d, "nope"], settings, MON)
    assert [i.id for i in result.scheduled] == [d]
    assert "no email address" in result.refused[a]
    assert "opt-out line" in result.refused[b]
    assert "only a ready item" in result.refused[c]
    assert result.refused["nope"] == "no such outreach item"
    assert outreach.get_item(root, a).state == "ready"
    assert any("not scheduled:" in line for line in result.lines())


def test_scheduling_needs_sending_on_and_a_sending_address(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 1)
    off = send.settings_from_config({**load_config(root), "send_enabled": False})
    with pytest.raises(outreach.OutreachError, match="sending is off"):
        sendqueue.schedule(store, ids, off, MON)
    nobody = send.settings_from_config({"send_enabled": True})
    with pytest.raises(outreach.OutreachError, match="no sending address"):
        sendqueue.schedule(store, ids, nobody, MON)


def test_the_country_guard_keeps_a_company_out_of_the_queue_when_it_is_on(folder):
    root, store, _ = folder
    ids = many_ready(root, store, 1)
    on = send.settings_from_config({**load_config(root), "send_email_block_countries": ["NL"]})
    result = sendqueue.schedule(store, ids, on, MON)
    assert not result.scheduled and "email to NL is switched off" in result.refused[ids[0]]
    off = send.settings_from_config(load_config(root))                    # the default: no guard
    assert sendqueue.schedule(store, ids, off, MON).scheduled


def test_schedule_all_ready_takes_every_ready_email_oldest_approval_first(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 3)
    it = outreach.get_item(root, ids[0])
    it.ready = NOW + timedelta(hours=1)                  # approved last
    outreach.write_item(root, it)
    result = sendqueue.schedule_all_ready(store, settings, MON)
    assert [i.id for i in result.scheduled] == [ids[1], ids[2], ids[0]]


def test_a_second_schedule_keeps_the_times_the_page_already_showed(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 8)
    sendqueue.schedule(store, ids[:5], settings, MON)
    first = {i: outreach.get_item(root, i).send_at for i in ids[:5]}
    sendqueue.schedule(store, ids[5:], settings, MON + timedelta(minutes=30))
    assert {i: outreach.get_item(root, i).send_at for i in ids[:5]} == first
    later = [outreach.get_item(root, i).send_at for i in ids[5:]]
    assert all(t not in first.values() for t in later)
    everything = sorted([*first.values(), *later])
    assert all((b - a) >= timedelta(minutes=3) for a, b in zip(everything, everything[1:]))


def test_unschedule_puts_it_back_to_ready_and_moves_nobody_else(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 4)
    sendqueue.schedule(store, ids, settings, MON)
    times = {i: outreach.get_item(root, i).send_at for i in ids}
    item = sendqueue.unschedule(store, ids[1])
    assert item.state == "ready" and item.send_at is None and item.send_hash == ""
    assert item.send_note == "unscheduled"
    assert {i: outreach.get_item(root, i).send_at for i in ids if i != ids[1]} == \
        {i: t for i, t in times.items() if i != ids[1]}
    with pytest.raises(outreach.OutreachError, match="only a queued item"):
        sendqueue.unschedule(store, ids[1])


def test_move_to_front_makes_it_next_and_shifts_the_rest(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 4)
    sendqueue.schedule(store, ids, settings, MON)
    order = lambda: [i.id for i in sendqueue.queued_items(root)]            # noqa: E731
    assert order() == ids
    sendqueue.move_to_front(store, ids[3], settings, MON)
    assert order() == [ids[3], *ids[:3]]
    assert outreach.get_item(root, ids[3]).send_at < outreach.get_item(root, ids[0]).send_at


def test_retry_puts_a_failed_item_back_to_ready_keeping_its_message_id(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 1)
    it = outreach.get_item(root, ids[0])
    it.state, it.send_error, it.send_tries, it.message_id = "failed", "421 busy", 3, "<m@x.example>"
    outreach.write_item(root, it)
    back = sendqueue.retry(store, ids[0])
    assert back.state == "ready" and back.send_error == "" and back.send_tries == 0
    assert back.message_id == "<m@x.example>"            # so a retry still asks Sent first
    with pytest.raises(outreach.OutreachError, match="only a failed item"):
        sendqueue.retry(store, ids[0])


def test_pause_and_resume_are_committed_and_lift_every_pause(folder):
    root, store, settings = folder
    sendqueue.pause(store)
    assert load_config(root)["send_paused"] is True
    assert git(root, "log", "--format=%s", "-1").strip() == "settings: send_paused unset -> true"
    send.SendState.load(root).pause(send.AUTH, "535 nope", NOW)
    lifted = sendqueue.resume(store)
    assert lifted == ["the Pause button", "535 nope"]
    assert load_config(root)["send_paused"] is False and not send.SendState.load(root).paused
    assert sendqueue.resume(store) == []


def test_status_and_the_strip(folder):
    root, store, settings = folder
    off = sendqueue.status(store, send.settings_from_config({}), MON)
    assert sendqueue.strip_line(off) == "Email sending: off"
    ids = many_ready(root, store, 3)
    sendqueue.schedule(store, ids, settings, MON)
    info = sendqueue.status(store, settings, MON)
    assert (info["sent_today"], info["cap"], info["queued"]) == (0, 10, 3)
    assert info["window"] == "08:30-17:30" and info["days"] == "Mon, Tue, Wed, Thu, Fri"
    assert info["next"] == outreach.get_item(root, ids[0]).send_at
    line = sendqueue.strip_line(info)
    assert line.startswith("Email: on · 0/10 today · 3 queued · next Mon ")
    sendqueue.pause(store)
    paused = sendqueue.status(store, send.settings_from_config(load_config(root)), MON)
    assert paused["paused_by"] == "the Pause button"
    assert "paused: the Pause button" in sendqueue.strip_line(paused)


# --------------------------------------------------------------- the worker


def test_the_tick_says_why_it_does_nothing(folder):
    root, store, settings = folder
    smtp, imap = FakeSmtp(), FakeImap()
    assert tick(root, store, MON, smtp, imap) == ["nothing queued"]
    ids = many_ready(root, store, 2)
    sendqueue.schedule(store, ids, settings, MON)
    first = outreach.get_item(root, ids[0]).send_at
    out = tick(root, store, MON, smtp, imap)
    assert out[0].startswith("nothing due; next at Mon 19 Oct") and "(2 queued)" in out[0]
    assert not smtp.sent
    from hermitcrm.setup import set_config_values
    set_config_values(root / "config.toml", {"send_enabled": False})
    assert tick(root, store, first, smtp, imap) == ["sending is off (Settings > Sending)"]
    set_config_values(root / "config.toml", {"send_enabled": True, "send_paused": True})
    assert tick(root, store, first, smtp, imap) == ["paused: the Pause button is on"]
    set_config_values(root / "config.toml", {"send_paused": False})
    send.SendState.load(root).pause(send.AUTH, "535 nope", MON)
    assert tick(root, store, first, smtp, imap) == ["paused (auth): 535 nope"]
    assert not smtp.sent


def test_a_quiet_tick_does_not_open_the_store(folder, monkeypatch):
    root, store, settings = folder
    ids = many_ready(root, store, 1)
    sendqueue.schedule(store, ids, settings, MON)
    monkeypatch.setattr(sendqueue, "open_store",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("opened")))
    scanned(root, MON)
    assert sendqueue.due(root, now=MON)[0].startswith("nothing due")


def test_one_mail_per_tick_however_many_are_due(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 3)
    sendqueue.schedule(store, ids, settings, MON)
    smtp, imap = FakeSmtp(), FakeImap()
    now = datetime(2026, 10, 19, 12, 0)
    for k, item_id in enumerate(ids):                    # all three are due, none overdue
        it = outreach.get_item(root, item_id)
        it.send_at = now - timedelta(minutes=2 * (3 - k))
        outreach.write_item(root, it)
    first = tick(root, store, now, smtp, imap)
    assert len(smtp.sent) == 1 and first[0].startswith(f"sent: {ids[0]}")
    again = tick(root, store, now, smtp, imap)
    assert len(smtp.sent) == 1 and "less than 3 minutes ago" in again[-1]
    for step in (1, 2):
        tick(root, store, now + timedelta(minutes=3 * step), smtp, imap)
    assert len(smtp.sent) == 3
    assert [m["To"] for m in smtp.sent] == [f"pat{k:02d}@co{k:02d}.example.org" for k in range(3)]


def test_outside_the_window_and_over_the_cap_it_waits(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 2)
    sendqueue.schedule(store, ids, settings, MON)
    smtp, imap = FakeSmtp(), FakeImap()
    for item_id in ids:
        it = outreach.get_item(root, item_id)
        it.send_at = datetime(2026, 10, 19, 17, 40)      # the window ended at 17:30
        outreach.write_item(root, it)
    out = tick(root, store, datetime(2026, 10, 19, 17, 45), smtp, imap)
    assert out == ["nothing due after planning"] or any("outside the sending window" in l for l in out)
    assert not smtp.sent
    for k in range(10):                                    # week 1 cap: 10 already today
        store.create_interaction(MARA[0], "email", "out", subject=f"Old {k}", contact=MARA[1],
                                 body="x\n", source="outreach",
                                 message_id=f"<o{k}@mail.example.com>",
                                 date=datetime(2026, 10, 19, 9, 0) + timedelta(minutes=k))
    for item_id in ids:
        it = outreach.get_item(root, item_id)
        it.send_at = datetime(2026, 10, 19, 14, 0)
        outreach.write_item(root, it)
    out = tick(root, store, datetime(2026, 10, 19, 14, 0), smtp, imap)
    assert any("cap of 10 is reached" in l for l in out) and not smtp.sent


def test_ten_items_scheduled_in_the_morning_go_out_at_the_times_the_page_showed(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 10)
    sendqueue.schedule(store, ids, settings, MON)
    planned = {i: outreach.get_item(root, i).send_at for i in ids}
    smtp, imap = FakeSmtp(), FakeImap()
    sent_at = {}
    now = MON
    while now <= datetime(2026, 10, 19, 17, 40):
        before = len(smtp.sent)
        tick(root, store, now, smtp, imap)
        if len(smtp.sent) > before:
            sent_at[smtp.sent[-1]["To"]] = now
        now += timedelta(minutes=3)
    assert len(smtp.sent) == 10
    for k, item_id in enumerate(ids):
        when = sent_at[f"pat{k:02d}@co{k:02d}.example.org"]
        assert planned[item_id] <= when <= planned[item_id] + timedelta(minutes=6), item_id
        assert outreach.get_item(root, item_id).state == "sent"
    times = sorted(sent_at.values())
    assert all((b - a) >= timedelta(minutes=3) for a, b in zip(times, times[1:]))
    assert git(root, "status", "--porcelain").strip() == ""


def test_a_mac_asleep_for_two_hours_resumes_with_spacing_not_a_burst(folder):
    root, store, _ = folder
    from hermitcrm.setup import set_config_values
    set_config_values(root / "config.toml", {"send_ramp": [], "send_daily_cap": 100})
    settings = send.settings_from_config(load_config(root))
    ids = many_ready(root, store, 12)
    sendqueue.schedule(store, ids, settings, MON)
    smtp, imap = FakeSmtp(), FakeImap()
    woke = datetime(2026, 10, 19, 12, 30)                # nothing ran before this
    assert max(outreach.get_item(root, i).send_at for i in ids) < woke
    first = tick(root, store, woke, smtp, imap)
    assert first[0].startswith("12 overdue; planned again") and not smtp.sent
    stamps = []
    now = woke
    while now <= datetime(2026, 10, 19, 17, 30):
        before = len(smtp.sent)
        tick(root, store, now, smtp, imap)
        if len(smtp.sent) > before:
            stamps.append(now)
        now += timedelta(minutes=3)
    assert len(stamps) == 12 and stamps[0] >= woke + timedelta(minutes=10)
    assert all((b - a) >= timedelta(minutes=3) for a, b in zip(stamps, stamps[1:]))
    assert all(outreach.get_item(root, i).state == "sent" for i in ids)


def test_a_reply_holds_their_item_and_the_others_still_go(folder):
    root, store, _ = folder
    from hermitcrm.setup import set_config_values
    set_config_values(root / "config.toml", {"send_ramp": [], "send_daily_cap": 100})
    settings = send.settings_from_config(load_config(root))      # spacing is not the point here
    ids = many_ready(root, store, 2)
    sendqueue.schedule(store, ids, settings, MON)
    first = outreach.get_item(root, ids[0])
    store.create_interaction(first.company, "email", "in", subject="Re: hi", contact=first.contact,
                             body="Not now\n", date=NOW + timedelta(hours=1))
    smtp, imap = FakeSmtp(), FakeImap()
    now = datetime(2026, 10, 19, 9, 0)
    for step in range(12):
        tick(root, store, now + timedelta(minutes=3 * step), smtp, imap)
    held = outreach.get_item(root, ids[0])
    assert held.state == "ready" and "they wrote to you" in held.send_note
    assert outreach.get_item(root, ids[1]).state == "sent" and len(smtp.sent) == 1


def test_pause_stops_the_next_tick(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 2)
    sendqueue.schedule(store, ids, settings, MON)
    smtp, imap = FakeSmtp(), FakeImap()
    when = outreach.get_item(root, ids[0]).send_at
    sendqueue.pause(store)
    assert tick(root, store, when, smtp, imap) == ["paused: the Pause button is on"]
    assert not smtp.sent
    sendqueue.resume(store)
    out = tick(root, store, when, smtp, imap)
    assert out[0].startswith("sent:")


def test_a_bad_password_in_a_tick_pauses_everything_with_the_servers_text(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 2)
    sendqueue.schedule(store, ids, settings, MON)
    smtp, imap = FakeSmtp(login_error=auth_error()), FakeImap()
    when = outreach.get_item(root, ids[0]).send_at
    out = tick(root, store, when, smtp, imap)
    assert out[0].startswith("paused:") and "Username and Password not accepted" in out[0]
    again = tick(root, store, when + timedelta(minutes=3), smtp, imap)
    assert again[0].startswith("paused (auth): 535 5.7.8")
    assert smtp.connections == 1                          # nothing retried, no login loop
    assert all(outreach.get_item(root, i).state == "queued" for i in ids)


def test_the_quota_pause_ends_by_itself_and_the_items_are_planned_again(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 1)
    sendqueue.schedule(store, ids, settings, MON)
    smtp = FakeSmtp(send_errors=[data_error(550, b"5.4.5 Daily user sending quota exceeded.")])
    when = outreach.get_item(root, ids[0]).send_at
    out = tick(root, store, when, smtp, FakeImap())
    assert out[0].startswith("paused:") and "quota" in out[0]
    assert send.SendState.load(root).until == "2026-10-20T08:30"
    nxt = tick(root, store, datetime(2026, 10, 20, 8, 31), smtp, FakeImap())
    assert any("overdue; planned again" in l for l in nxt)
    sent = None
    now = datetime(2026, 10, 20, 8, 40)
    while sent is None and now < datetime(2026, 10, 20, 12, 0):
        tick(root, store, now, smtp, FakeImap())
        sent = smtp.sent[0] if smtp.sent else None
        now += timedelta(minutes=3)
    assert sent is not None


def test_a_tick_while_another_holds_the_lock_does_nothing(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 1)
    sendqueue.schedule(store, ids, settings, MON)
    smtp, imap = FakeSmtp(), FakeImap()
    when = outreach.get_item(root, ids[0]).send_at
    with send.SendLock(root):
        out = tick(root, store, when, smtp, imap)
    assert out == ["another send is running; this tick does nothing"] and not smtp.sent


def test_a_dry_run_sends_and_writes_nothing(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 2)
    sendqueue.schedule(store, ids, settings, MON)
    when = outreach.get_item(root, ids[0]).send_at
    head = git(root, "rev-parse", "HEAD")
    smtp, imap = FakeSmtp(), FakeImap()
    out = tick(root, store, when, smtp, imap, dry_run=True)
    assert out == [f"would send {ids[0]}"]
    late = tick(root, store, datetime(2026, 10, 19, 15, 0), smtp, imap, dry_run=True)
    assert "overdue; would plan again" in late[0]
    assert not smtp.sent and git(root, "rev-parse", "HEAD") == head
    assert all(outreach.get_item(root, i).state == "queued" for i in ids)


def test_the_worker_opens_its_own_store_commits_and_leaves_the_folder_clean(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 1)
    sendqueue.schedule(store, ids, settings, MON)
    when = outreach.get_item(root, ids[0]).send_at
    smtp, imap = FakeSmtp(), FakeImap()
    out = sendqueue.due(root, now=when, smtp_factory=smtp.factory, imap_factory=imap.factory)
    assert out[0].startswith("sent:") and len(smtp.sent) == 1
    assert git(root, "status", "--porcelain").strip() == ""
    assert "outreach" in git(root, "log", "--format=%s", "-1")


def test_the_worker_waits_for_a_held_index_lock(folder, monkeypatch):
    root, store, _ = folder
    (root / ".git" / "index.lock").write_text("", encoding="utf-8")
    assert sendqueue.wait_for_git(root, seconds=0.3) is False
    (root / ".git" / "index.lock").unlink()
    assert sendqueue.wait_for_git(root, seconds=0.3) is True


# ---------------------------------------------------------------------- CLI


def run_cli(root, *argv, monkeypatch=None):
    return cli.main(["--data", str(root), *argv], root=root)


def test_the_cli_schedules_shows_and_unschedules(folder, capsys):
    root, store, settings = folder
    ids = many_ready(root, store, 2)
    assert run_cli(root, "outreach", "schedule", ids[0], "--dry-run") == 0
    assert "Proposed times (nothing was written):" in capsys.readouterr().out
    assert run_cli(root, "outreach", "schedule", "--all-ready") == 0
    out = capsys.readouterr().out
    assert "Scheduled 2:" in out and ids[1] in out
    assert run_cli(root, "send", "status") == 0
    assert "Email: on · 0/10 today · 2 queued" in capsys.readouterr().out
    assert run_cli(root, "outreach", "unschedule", ids[0]) == 0
    assert run_cli(root, "outreach", "front", ids[1]) == 0
    assert run_cli(root, "outreach", "unschedule", ids[0]) == 1
    assert "only a queued item" in capsys.readouterr().err
    assert run_cli(root, "outreach", "schedule") == 1
    assert "--all-ready" in capsys.readouterr().err


def test_the_cli_sends_now_through_the_default_connections(folder, capsys, monkeypatch):
    root, store, settings = folder
    ids = many_ready(root, store, 1)
    smtp, imap = FakeSmtp(), FakeImap()
    monkeypatch.setattr(smtplib, "SMTP", smtp.factory)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", imap.factory)
    assert run_cli(root, "outreach", "send-now", ids[0]) == 0
    assert capsys.readouterr().out.startswith(f"sent: {ids[0]}")
    assert len(smtp.sent) == 1 and outreach.get_item(root, ids[0]).state == "sent"


def test_the_cli_pause_resume_and_test(folder, capsys, monkeypatch):
    root, store, settings = folder
    assert run_cli(root, "send", "pause") == 0
    assert load_config(root)["send_paused"] is True
    assert run_cli(root, "send", "status") == 0
    assert "paused: the Pause button" in capsys.readouterr().out
    assert run_cli(root, "send", "resume") == 0
    assert "Resumed: the Pause button." in capsys.readouterr().out
    smtp, imap = FakeSmtp(), FakeImap()
    monkeypatch.setattr(smtplib, "SMTP", smtp.factory)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", imap.factory)
    assert run_cli(root, "send", "test") == 0
    assert "Test mail sent to sam@example.com" in capsys.readouterr().out
    bad = FakeSmtp(login_error=auth_error())
    monkeypatch.setattr(smtplib, "SMTP", bad.factory)
    assert run_cli(root, "send", "test") == 1
    assert "The test failed: 535" in capsys.readouterr().err


def test_send_due_from_the_cli_prints_the_tick(folder, capsys):
    root, store, settings = folder
    assert run_cli(root, "send", "due") == 0
    out = capsys.readouterr().out.strip()
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d nothing queued", out), out
    assert run_cli(root, "send", "due", "--dry-run") == 0


# ------------------------------------------------------------ jobs, doctor


def test_the_send_job_files_are_written_for_mac_linux_and_windows(tmp_path):
    from test_schedule import EXE, ctx
    import plistlib
    from hermitcrm import schedule
    mac = ctx(tmp_path, "darwin", env={"HERMITCRM_DRY_SCHEDULE": "1"})
    schedule.install(mac, send=True, backup=False, sync=False)
    plist = plistlib.loads((tmp_path / "home/Library/LaunchAgents/io.hermitcrm.send.plist")
                           .read_bytes())
    data = str((tmp_path / "my crm").resolve())
    assert plist["ProgramArguments"] == [*EXE, "--data", data, "send", "due"]
    assert plist["StartInterval"] == 180 and plist["RunAtLoad"] is True
    assert plist["StandardOutPath"].endswith("hermitcrm-send.log")
    assert not (tmp_path / "home/Library/LaunchAgents/io.hermitcrm.sync.plist").exists()
    (tmp_path / "l").mkdir()
    lin = ctx(tmp_path / "l", "linux", env={"HERMITCRM_DRY_SCHEDULE": "1"})
    schedule.install(lin, send=True, backup=False, sync=False)
    units = tmp_path / "l/home/.config/systemd/user"
    assert "OnUnitActiveSec=3min" in (units / "hermitcrm-send.timer").read_text()
    assert "send due" in (units / "hermitcrm-send.service").read_text()
    (tmp_path / "w").mkdir()
    win = ctx(tmp_path / "w", "win32")
    lines = schedule.install(win, send=True, backup=False)
    assert any('/SC MINUTE /MO 3 /TN "Hermit CRM\\send"' in l for l in lines)


def test_turning_scheduled_sending_off_removes_only_the_send_job(tmp_path):
    from test_schedule import ctx
    from hermitcrm import schedule
    c = ctx(tmp_path, "darwin", env={"HERMITCRM_DRY_SCHEDULE": "1"})
    schedule.install(c, send=True)
    agents = tmp_path / "home/Library/LaunchAgents"
    assert (agents / "io.hermitcrm.send.plist").exists()
    schedule.remove(c, only_send=True)
    assert not (agents / "io.hermitcrm.send.plist").exists()
    assert (agents / "io.hermitcrm.sync.plist").exists() and (agents / "io.hermitcrm.backup.plist").exists()
    assert schedule.status(c)["send_installed"] is False
    schedule.install(c, send=True)
    assert schedule.status(c)["send_installed"] is True
    schedule.remove(c)
    assert not (agents / "io.hermitcrm.send.plist").exists()


def doctor_rows(root, **kw):
    rows = doctor.run_checks(root, env={"HERMITCRM_SEND_PASSWORD": GOOD_PASSWORD, **kw.pop("env", {})},
                             platform=kw.pop("platform", "darwin"), **kw)
    return {c.name: c for c in rows}


def test_doctor_is_silent_about_sending_while_it_is_off(tmp_path):
    root, store, settings = make_folder(tmp_path, {"send_enabled": False})
    names = doctor_rows(root, runner=lambda *a, **k: _done())
    assert not [n for n in names if n.startswith("send")]


def _done(out="", code=0):
    import subprocess
    return subprocess.CompletedProcess([], code, out, "")


def test_doctor_checks_the_sending_setup(folder):
    root, store, settings = folder
    ids = many_ready(root, store, 2)
    sendqueue.schedule(store, ids, settings, MON)
    pmset = ("Battery Power:\n sleep 1\nAC Power:\n sleep 10\n displaysleep 10\n")
    smtp, imap = FakeSmtp(), FakeImap()
    rows = doctor_rows(root, online=True, send_smtp=smtp.factory, send_imap=imap.factory,
                       now=datetime(2026, 10, 19, 12, 0),
                       runner=lambda argv, **k: _done(pmset) if argv[0] == "pmset" else _done())
    assert rows["send password"].status == "ok"
    assert rows["smtp login"].status == "ok" and rows["send imap login"].status == "ok"
    assert rows["send job"].status == "warn" and "schedule install --send" in rows["send job"].detail
    assert rows["send queue"].status == "warn" and "2 of 2 queued are overdue" in rows["send queue"].detail
    assert rows["mac sleep"].status == "warn" and "after 10 min on power" in rows["mac sleep"].detail
    assert not smtp.sent


def test_doctor_shows_the_servers_words_for_a_failing_login_and_a_pause(folder):
    root, store, settings = folder
    send.SendState.load(root).pause(send.AUTH, "535 5.7.8 Username and Password not accepted", NOW)
    rows = doctor_rows(root, online=True, send_smtp=FakeSmtp(login_error=auth_error()).factory,
                       send_imap=FakeImap().factory, now=NOW,
                       runner=lambda argv, **k: _done("AC Power:\n sleep 0\n"))
    assert rows["smtp login"].status == "fail" and "Username and Password not accepted" in rows["smtp login"].detail
    assert rows["send queue"].status == "warn" and "paused (auth)" in rows["send queue"].detail
    assert rows["mac sleep"].status == "ok"


def test_doctor_says_when_there_is_no_password_or_address(tmp_path):
    root, store, settings = make_folder(tmp_path, {"send_from": ""})
    from hermitcrm.setup import set_config_values
    set_config_values(root / "config.toml", {"send_from": "", "owner_email": ""})
    rows = doctor_rows(root, runner=lambda *a, **k: _done())
    assert rows["sending"].status == "fail" and "no sending address" in rows["sending"].detail
    root2, _, _ = make_folder(tmp_path / "two")
    rows = doctor.run_checks(root2, env={}, platform="linux",
                             runner=lambda *a, **k: _done())
    names = {c.name: c for c in rows}
    assert names["send password"].status == "fail"


def test_outreach_show_says_when_it_goes_out_and_what_went_wrong(folder, capsys):
    root, store, settings = folder
    ids = many_ready(root, store, 2)
    sendqueue.schedule(store, ids, settings, MON)
    queued = outreach.render_item(store, outreach.get_item(root, ids[0]))
    assert "(queued, first-touch by email)" in queued and "Scheduled: goes out Mon 2026-10-19 " in queued
    it = outreach.get_item(root, ids[1])
    it.state, it.send_error, it.message_id, it.send_tries = "failed", "550 5.1.1 no such user", "<a@b.example>", 2
    it.send_note, it.invite_sent = "bounced: 5.1.1", datetime(2026, 10, 1, 9, 0)
    outreach.write_item(root, it)
    failed = outreach.render_item(store, outreach.get_item(root, ids[1]))
    assert "Not sent: 550 5.1.1 no such user (hermitcrm outreach retry)" in failed
    assert "Message-ID: <a@b.example> (2 tries)" in failed and "Note: bounced: 5.1.1" in failed
    assert "LinkedIn: invited 2026-10-01 09:00" in failed


def test_a_stale_view_never_puts_a_sent_item_back_in_the_queue(folder, monkeypatch):
    """The page plans from a copy of the queue it read; a tick may send an item in between.
    Writing the old copy back would queue a mail that already went out: it would go twice."""
    root, store, settings = folder
    ids = many_ready(root, store, 3)
    sendqueue.schedule(store, ids, settings, MON)
    stale = outreach.items(root)                           # what a slow page read
    sent_since = outreach.get_item(root, ids[1])
    sent_since.state, sent_since.sent = "sent", MON + timedelta(minutes=30)
    outreach.write_item(root, sent_since)                  # the tick sent it meanwhile
    monkeypatch.setattr(outreach, "items", lambda r: stale)
    sendqueue.replan(store, settings, MON + timedelta(minutes=31), everything=True)
    assert outreach.get_item(root, ids[1]).state == "sent"
    assert {outreach.get_item(root, i).state for i in (ids[0], ids[2])} == {"queued"}


def test_an_item_that_changed_while_it_was_being_scheduled_is_left_alone(folder, monkeypatch):
    root, store, settings = folder
    a, b = many_ready(root, store, 2)
    real = sendqueue._schedulable

    def changes_a(store_, item, settings_, config):
        why = real(store_, item, settings_, config)
        if item.id == a:                                   # skipped on another screen, just now
            other = outreach.get_item(root, a)
            other.state, other.skipped = "skipped", MON
            outreach.write_item(root, other)
        return why

    monkeypatch.setattr(sendqueue, "_schedulable", changes_a)
    result = sendqueue.schedule(store, [a, b], settings, MON)
    assert [i.id for i in result.scheduled] == [b]
    assert result.refused[a] == "it changed while it was being scheduled"
    assert outreach.get_item(root, a).state == "skipped"


def test_an_item_that_blows_up_is_held_back_with_the_reason_and_does_not_block_the_queue(folder, monkeypatch):
    root, store, settings = folder
    ids = many_ready(root, store, 2)
    sendqueue.schedule(store, ids, settings, MON)
    real = send.deliver

    def broken_for_the_first(store_, item_id, **kw):
        if item_id == ids[0]:
            raise RuntimeError("boom")
        return real(store_, item_id, **kw)

    monkeypatch.setattr(send, "deliver", broken_for_the_first)
    smtp, imap = FakeSmtp(), FakeImap()
    start = outreach.get_item(root, ids[0]).send_at
    out = tick(root, store, start, smtp, imap)
    assert out[-1] == f"error: {ids[0]}: Hermit could not send it (RuntimeError: boom)"
    held = outreach.get_item(root, ids[0])
    assert held.state == "ready" and held.send_note == "Hermit could not send it (RuntimeError: boom)"
    later = outreach.get_item(root, ids[1]).send_at
    out = tick(root, store, later, smtp, imap)
    assert out[-1].startswith(f"sent: {ids[1]}") and len(smtp.sent) == 1
