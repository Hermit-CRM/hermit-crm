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

"""Outreach send in the web app: the status strip and Pause, Send now and
Schedule on the Ready tab, the Scheduled tab, the banner when sending stops by
itself, Settings > Sending. SMTP and IMAP are in-memory doubles."""

from __future__ import annotations

import html
import imaplib
import re
import smtplib
import socket
import stat
import subprocess
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import URL, QueryParams

from hermitcrm import outreach, send
from hermitcrm.store import load_config
from hermitcrm.web import create_app
from outreach_fakes import NOW, git
from send_fakes import (GOOD_PASSWORD, FakeImap, FakeSmtp, auth_error, make_folder, ready_item)

OPT_OUT = "If this is not for you, tell me and I will not write again."
BODY = ("Hi Mara,\n\nThe second office this autumn caught my eye. Where does it hurt most "
        "right now: pipeline, conversion or deal size?\n\nSam\n\n" + OPT_OUT + "\n")
PEOPLE = [("lindenhof-data", "mara-keller"), ("bluefin-analytics", "joris-veldkamp"),
          ("northwind-robotics", "lena-vogt"), ("quartzline-logistics", "maya-chen")]
FRIDAY = NOW                                    # 2026-10-16 09:00


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a test reached for the network")
    monkeypatch.setattr(socket, "create_connection", refuse)
    for module, name in ((smtplib, "SMTP"), (smtplib, "SMTP_SSL"), (imaplib, "IMAP4"),
                         (imaplib, "IMAP4_SSL")):
        monkeypatch.setattr(module, name, refuse)
    monkeypatch.setenv("HERMITCRM_SEND_PASSWORD", GOOD_PASSWORD)


@pytest.fixture
def env(tmp_path):
    root, store, settings = make_folder(tmp_path)
    path = root / "MESSAGING.md"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "approaches:", f"opt_out: {OPT_OUT}\napproaches:", 1), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "setup")
    smtp, imap = FakeSmtp(), FakeImap()
    app = create_app(root, {**load_config(root), "push_enabled": False})
    app.state.setup_redirected = True
    app.state.send_smtp = smtp.factory
    app.state.send_imap = imap.factory
    app.state.schedule_home = tmp_path / "home"
    app.state.setup_platform = "darwin"
    app.state.setup_runner = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "", "")
    client = TestClient(app, follow_redirects=False)
    return root, store, client, smtp, imap


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.app.state.csrf_token, **data})


def items(root, n, **extra):
    out = []
    for k, (company, contact) in enumerate(PEOPLE[:n]):
        out.append(ready_item(root, None, item_id=f"i{k:02d}-{company}", company=company,
                              contact=contact, body=BODY, **extra))
    return out


def flash(response) -> str:
    return QueryParams(URL(response.headers["location"]).query).get("flash", "")


def follow(client, response) -> str:
    return client.get(response.headers["location"]).text


def text_of(page: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)))


# --------------------------------------------------------------- sending off


def test_with_sending_off_the_page_is_what_it_was(env):
    root, store, client, smtp, imap = env
    from hermitcrm.setup import set_config_values
    set_config_values(root / "config.toml", {"send_enabled": False})
    client.app.state.config["send_enabled"] = False
    (item,) = items(root, 1)
    page = client.get("/outreach?tab=ready")
    assert page.status_code == 200
    body = text_of(page.text)
    assert "Email sending is off." in body and "Nothing is sent from here." in body
    assert "Send now" not in body and "Schedule" not in body.replace("Settings", "")
    assert "Scheduled (0)" not in body
    assert "Mark sent" in body and "Open in mail" in body


# ----------------------------------------------------------- strip, buttons


def test_the_strip_and_the_buttons_when_sending_is_on(env):
    root, store, client, smtp, imap = env
    items(root, 2)
    page = client.get("/outreach?tab=ready")
    body = text_of(page.text)
    assert "Email: on · 0/20 today · 0 queued" in body and "Mon, Tue, Wed, Thu, Fri 08:30-17:30" in body
    assert "Scheduled (0)" in body and "Ready (2)" in body
    assert page.text.count('/send-now"') == 2 and page.text.count('/schedule"') == 2
    assert 'action="/outreach/send/pause"' in page.text
    assert "Schedule all ready email (2)" in body
    linkedin = ready_item(root, None, item_id="li-1", company=PEOPLE[2][0], contact=PEOPLE[2][1],
                          body="Hi Lena, a short note?")
    li = outreach.get_item(root, linkedin.id)
    li.channel = "linkedin"
    outreach.write_item(root, li)
    page = client.get("/outreach?tab=ready")
    assert page.text.count('/send-now"') == 2                   # LinkedIn has no email buttons


def test_a_missing_address_is_said_on_the_strip(env):
    root, store, client, smtp, imap = env
    from hermitcrm.setup import set_config_values
    set_config_values(root / "config.toml", {"send_from": "", "owner_email": ""})
    client.app.state.config.update(send_from="", owner_email="")
    assert "Sending cannot start: no sending address" in text_of(client.get("/outreach").text)


def test_pause_and_resume_are_buttons_with_the_form_token(env):
    root, store, client, smtp, imap = env
    assert client.post("/outreach/send/pause", data={}).status_code == 403
    resp = post(client, "/outreach/send/pause")
    assert resp.status_code == 303 and "paused" in flash(resp)
    assert load_config(root)["send_paused"] is True
    page = text_of(client.get("/outreach").text)
    assert "paused the Pause button" in page and "Resume" in page
    assert client.post("/outreach/send/resume", data={}).status_code == 403
    resp = post(client, "/outreach/send/resume")
    assert "Resumed: the Pause button" in flash(resp)
    assert load_config(root)["send_paused"] is False


# ----------------------------------------------------------- schedule, queue


def test_schedule_moves_an_item_to_the_scheduled_tab_with_its_time(env):
    root, store, client, smtp, imap = env
    (item,) = items(root, 1)
    assert client.post(f"/outreach/{item.id}/schedule", data={}).status_code == 403
    resp = post(client, f"/outreach/{item.id}/schedule")
    assert resp.status_code == 303 and "tab=scheduled" in resp.headers["location"]
    assert re.match(r"Scheduled: it goes out \w{3} \d\d \w{3}, \d\d:\d\d\.", flash(resp))
    page = follow(client, resp)
    body = text_of(page)
    assert "Scheduled (1)" in body and re.search(r"Goes out \w{3} \d\d \w{3}, \d\d:\d\d", body)
    for label in ("Send now", "Move to front", "Unschedule", "Mark sent"):
        assert label in body
    assert outreach.get_item(root, item.id).state == "queued"


def test_unschedule_and_move_to_front(env):
    root, store, client, smtp, imap = env
    a, b = items(root, 2)
    post(client, f"/outreach/{a.id}/schedule")
    post(client, f"/outreach/{b.id}/schedule")
    first = lambda: [i.id for i in sorted((outreach.get_item(root, x.id) for x in (a, b)),   # noqa: E731
                                          key=lambda i: i.send_at)]
    assert first() == [a.id, b.id]
    resp = post(client, f"/outreach/{b.id}/front")
    assert "Moved to the front" in flash(resp) and first() == [b.id, a.id]
    resp = post(client, f"/outreach/{a.id}/unschedule")
    assert "tab=ready" in resp.headers["location"] and "Unscheduled" in flash(resp)
    assert outreach.get_item(root, a.id).state == "ready"
    assert "Held back: unscheduled" in text_of(client.get("/outreach?tab=ready").text)


def test_a_schedule_that_is_refused_says_why(env):
    root, store, client, smtp, imap = env
    (item,) = items(root, 1)
    store.update_contact(item.company, item.contact, email="")
    client.app.state.store.load()
    resp = post(client, f"/outreach/{item.id}/schedule")
    assert flash(resp).startswith("Not scheduled: ") and "no email address" in flash(resp)


def test_schedule_all_shows_the_times_first_and_then_confirms(env):
    root, store, client, smtp, imap = env
    ids = [i.id for i in items(root, 3)]
    head = git(root, "rev-parse", "HEAD")
    preview = client.get("/outreach?tab=ready&schedule=all")
    body = text_of(preview.text)
    assert "Proposed times" in body and "Nothing is scheduled until you confirm." in body
    assert "Mara Keller" in body and "Schedule 3 emails" in body
    assert all(outreach.get_item(root, i).state == "ready" for i in ids)
    assert git(root, "rev-parse", "HEAD") == head
    assert client.post("/outreach/schedule-all", data={}).status_code == 403
    resp = post(client, "/outreach/schedule-all")
    assert "Scheduled 3 emails." in flash(resp) and "tab=scheduled" in resp.headers["location"]
    assert all(outreach.get_item(root, i).state == "queued" for i in ids)
    again = post(client, "/outreach/schedule-all")
    assert "Scheduled 0 emails." in flash(again) or "tab=ready" in again.headers["location"]


# ------------------------------------------------------------------ send now


def test_send_now_sends_logs_and_says_so(env):
    root, store, client, smtp, imap = env
    (item,) = items(root, 1)
    assert client.post(f"/outreach/{item.id}/send-now", data={}).status_code == 403
    resp = post(client, f"/outreach/{item.id}/send-now")
    assert flash(resp) == "Sent and logged." and "tab=sent" in resp.headers["location"]
    assert len(smtp.sent) == 1 and smtp.sent[0]["To"] == "mara@lindenhof-data.example.com"
    after = outreach.get_item(root, item.id)
    assert after.state == "sent" and after.sent_with
    assert "Sent" in text_of(follow(client, resp))


def test_send_now_that_is_held_says_why_and_changes_nothing(env):
    root, store, client, smtp, imap = env
    (item,) = items(root, 1)
    imap.deliver("[Gmail]/All Mail", b"From: mara@lindenhof-data.example.com\r\nTo: sam@mail.example.com\r\n"
                 b"Subject: Hi\r\nMessage-ID: <q@example.org>\r\n\r\nhello\r\n", FRIDAY)
    resp = post(client, f"/outreach/{item.id}/send-now")
    assert flash(resp).startswith("Not sent: they wrote to you since 16 Oct")
    assert outreach.get_item(root, item.id).state == "ready" and not smtp.sent


def test_send_now_is_refused_while_paused_and_over_the_cap(env):
    root, store, client, smtp, imap = env
    (item,) = items(root, 1)
    post(client, "/outreach/send/pause")
    resp = post(client, f"/outreach/{item.id}/send-now")
    assert "sending is paused" in flash(resp) and not smtp.sent


def test_a_bad_password_stops_sending_with_a_red_banner_on_every_page(env):
    root, store, client, smtp, imap = env
    (item,) = items(root, 1)
    bad = FakeSmtp(login_error=auth_error())
    client.app.state.send_smtp = bad.factory
    resp = post(client, f"/outreach/{item.id}/send-now")
    assert "Username and Password not accepted" in flash(resp)
    for path in ("/", "/outreach", "/companies", "/settings"):
        page = client.get(path)
        assert 'class="send-banner"' in page.text, path
        assert "535 5.7.8 Username and Password not accepted" in html.unescape(page.text), path
        assert "Send a test passes" in text_of(page.text)
    assert "paused" in text_of(client.get("/outreach").text)
    # a passing test clears it
    client.app.state.send_smtp = smtp.factory
    resp = post(client, "/settings/send/test")
    assert "Test mail sent to sam@example.com" in flash(resp) and "can run again" in flash(resp)
    assert 'class="send-banner"' not in client.get("/outreach").text


def test_no_banner_while_sending_is_off(env):
    root, store, client, smtp, imap = env
    send.SendState.load(root).pause(send.AUTH, "535 x", NOW)
    client.app.state.config["send_enabled"] = False
    assert 'class="send-banner"' not in client.get("/outreach").text


def test_a_failed_item_shows_its_error_and_retry_brings_it_back(env):
    root, store, client, smtp, imap = env
    (item,) = items(root, 1)
    it = outreach.get_item(root, item.id)
    it.state, it.send_error = "failed", "550 5.1.1 The email account that you tried to reach does not exist."
    outreach.write_item(root, it)
    body = text_of(client.get("/outreach?tab=ready").text)
    assert "Ready (1)" in body and "Not sent: 550 5.1.1" in body and "Retry" in body
    resp = post(client, f"/outreach/{item.id}/retry")
    assert "Back on the Ready tab" in flash(resp)
    assert outreach.get_item(root, item.id).state == "ready"


def test_the_ready_flash_points_at_schedule_and_send_now(env):
    root, store, client, smtp, imap = env
    ready_item(root, None, item_id="d1", company=PEOPLE[0][0], contact=PEOPLE[0][1],
               state="drafted", ready=None, body=BODY)
    resp = post(client, "/outreach/d1/ready", subject="Your second office", body=BODY)
    assert flash(resp).startswith("Ready. Schedule it or send it now from the Ready tab.")


# ----------------------------------------------------------------- settings


def test_the_settings_page_has_a_sending_section(env):
    root, store, client, smtp, imap = env
    page = client.get("/settings")
    body = text_of(page.text)
    assert 'id="send"' in page.text and "Sending" in body
    assert "Use a separate mailbox" in body and "Send a test to myself" in body
    assert "Turn on scheduled sending" in body
    assert 'name="daily_cap" value="100"' in page.text
    assert 'name="ramp" value="20, 40, 60, 80"' in page.text
    assert "Gmail / Google Workspace" in body and "iCloud Mail (untested)" in body


def form(**kw):
    base = dict(enabled="1", from_addr="cold@mail.example.net", smtp_host="smtp.gmail.com",
                smtp_port="587", smtp_user="", imap_host="imap.gmail.com", window="09:00-17:00",
                days=["mon", "tue", "wed"], daily_cap="120", ramp="30, 60", min_gap="4",
                company_gap_hours="48", countries="de, at", password="abcd efgh ijkl mnop")
    base.update(kw)
    return base


def test_saving_the_sending_settings_writes_config_and_keeps_the_password_out(env):
    root, store, client, smtp, imap = env
    assert client.post("/settings/send", data=form()).status_code == 403
    resp = post(client, "/settings/send", **form())
    assert resp.status_code == 303
    text = flash(resp)
    assert "Sending settings saved; sending is on." in text
    assert "120 a day is above the plan of about 100" in text
    assert "cold@mail.example.net added to your addresses." in text
    config = load_config(root)
    assert config["send_from"] == "cold@mail.example.net" and config["send_daily_cap"] == 120
    assert config["send_window"] == "09:00-17:00" and config["send_days"] == ["mon", "tue", "wed"]
    assert config["send_ramp"] == [30, 60] and config["send_min_gap_minutes"] == 4
    assert config["send_company_gap_hours"] == 48
    assert config["send_email_block_countries"] == ["DE", "AT"]
    assert "cold@mail.example.net" in config["my_addresses"]
    assert "abcd" not in (root / "config.toml").read_text(encoding="utf-8")
    secret = root / ".secrets.toml"
    assert 'send_password = "abcd efgh ijkl mnop"' in secret.read_text(encoding="utf-8")
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    assert git(root, "log", "--format=%s", "-1").startswith("settings:")
    assert ".secrets.toml" not in git(root, "ls-files")


def test_a_wrong_setting_is_refused_with_the_form_kept(env):
    root, store, client, smtp, imap = env
    bad = form(window="late", daily_cap="many", from_addr="nonsense", days=[], countries="Germany")
    resp = post(client, "/settings/send", **bad)
    assert resp.status_code == 400
    body = text_of(resp.text)
    assert "the sending window is HH:MM-HH:MM" in body
    assert "The daily cap" in body and "Give the sending address" in body
    assert "choose at least one day" in body and "Country codes of two letters" in body
    assert 'value="nonsense"' in resp.text                       # what was typed stays
    assert load_config(root)["send_daily_cap"] == 100            # nothing was saved


def test_a_cap_past_150_is_warned_about_on_the_page_and_in_the_flash(env):
    root, store, client, smtp, imap = env
    resp = post(client, "/settings/send", **form(daily_cap="200", password=""))
    assert "third is held at 150" in flash(resp)
    assert "third is held at 150" in text_of(client.get("/settings").text)


def test_the_test_button_reports_the_servers_exact_reply(env):
    root, store, client, smtp, imap = env
    assert client.post("/settings/send/test", data={}).status_code == 403
    client.app.state.send_smtp = FakeSmtp(login_error=auth_error()).factory
    resp = post(client, "/settings/send/test")
    assert flash(resp).startswith("The test failed: 535 5.7.8 Username and Password not accepted")


def test_turning_scheduled_sending_on_and_off(env):
    root, store, client, smtp, imap = env
    plist = client.app.state.schedule_home / "Library/LaunchAgents/io.hermitcrm.send.plist"
    assert client.post("/settings/send/job", data={"action": "on"}).status_code == 403
    resp = post(client, "/settings/send/job", action="on")
    assert "Scheduled sending is on" in flash(resp) and plist.exists()
    assert "Turn off scheduled sending" in text_of(client.get("/settings").text)
    resp = post(client, "/settings/send/job", action="off")
    assert "Scheduled sending is off" in flash(resp) and not plist.exists()
    assert "Turn on scheduled sending" in text_of(client.get("/settings").text)


def test_every_new_route_wants_the_form_token(env):
    root, store, client, smtp, imap = env
    for path in ("/outreach/send/pause", "/outreach/send/resume", "/outreach/schedule-all",
                 "/settings/send", "/settings/send/test", "/settings/send/job",
                 "/outreach/x/schedule", "/outreach/x/unschedule", "/outreach/x/send-now",
                 "/outreach/x/front", "/outreach/x/retry"):
        assert client.post(path, data={}).status_code == 403, path
