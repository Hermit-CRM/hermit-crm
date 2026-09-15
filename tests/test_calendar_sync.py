"""Calendar import (app/calendar_sync.py): parser, matching, secrets, CLI and routes."""

from __future__ import annotations

import io
import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from owncrm import cli as crm
from owncrm import bcc, calendar_sync as cal
from owncrm.web import create_app
from test_bcc import FakeBox, raw_mail

ME = "me@work.example.com"
SETTINGS = cal.Settings(my_addresses=(ME,), ignore_domains=("work.example.com",))


@pytest.fixture(autouse=True)
def amsterdam():
    """UTC and TZID conversions land in local time; pin it."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Amsterdam"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def ics(*events: str) -> str:
    body = "\r\n".join(e.strip("\n").replace("\n", "\r\n") for e in events)
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n{body}\r\nEND:VCALENDAR\r\n"


def vevent(uid="ev1", start="20260910T080000Z", end="20260910T090000Z", summary="Intro",
           organizer=f"mailto:{ME}", attendees=("mailto:jane@acme.de",), extra="") -> str:
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTART:{start}" if ":" not in start
             else f"DTSTART;{start}"]
    if end:
        lines.append(f"DTEND:{end}" if ":" not in end else f"DTEND;{end}")
    lines.append(f"SUMMARY:{summary}")
    if organizer:
        lines.append(f"ORGANIZER:{organizer}" if organizer.startswith("mailto:")
                     else f"ORGANIZER;{organizer}")
    lines += [f"ATTENDEE:{a}" if a.startswith("mailto:") else f"ATTENDEE;{a}"
              for a in attendees]
    if extra:
        lines += extra.strip("\n").split("\n")
    lines.append("END:VEVENT")
    return "\n".join(lines)


def seed(store):
    store.create_company("Acme GmbH", website="acme.de")
    store.create_contact("acme", "Jane", "Doe", email="jane@acme.de")
    store.create_company("Beta", website="https://www.beta.io")


# ------------------------------------------------------------------- parser


def test_folding_escaping_people_and_utc():
    text = ics(r"""
BEGIN:VEVENT
UID:utc-1@google.com
DTSTART:20260910T080000Z
DTEND:20260910T090000Z
SUMMARY:Intro call\, Acme
DESCRIPTION:Agenda:\nPricing\; next steps\\done and a long line th
 at is fo
	lded
LOCATION:Google Meet
ORGANIZER;CN=Sam Owner:mailto:me@work.example.com
ATTENDEE;CN="Doe, Jane";PARTSTAT=ACCEPTED;ROLE=REQ-PARTICIPANT:mailto:Jane@Acme.de
ATTENDEE;CUTYPE=RESOURCE;CN=Room:mailto:c_1@resource.calendar.google.com
BEGIN:VALARM
DESCRIPTION:reminder
END:VALARM
END:VEVENT
""")
    [ev] = cal.parse_ics(text)
    assert ev.uid == "utc-1@google.com" and ev.summary == "Intro call, Acme"
    assert ev.description == "Agenda:\nPricing; next steps\\done and a long line that is folded"
    assert ev.location == "Google Meet"
    assert (ev.start, ev.end, ev.all_day) == (datetime(2026, 9, 10, 10, 0),
                                              datetime(2026, 9, 10, 11, 0), False)
    assert ev.organizer == cal.Attendee("me@work.example.com", "Sam Owner")
    assert ev.attendees[0] == cal.Attendee("jane@acme.de", "Doe, Jane", "ACCEPTED")
    assert [p.email for p in cal.participants(ev)] == ["me@work.example.com", "jane@acme.de"]
    assert [p.email for p in cal.external_attendees(ev, SETTINGS)] == ["jane@acme.de"]
    assert cal.direction_for(ev, SETTINGS) == "out"


def test_tzid_floating_all_day_duration():
    text = ics(
        vevent("tz", start="TZID=Europe/Amsterdam:20260911T140000",
               end="TZID=America/New_York:20260911T090000"),
        vevent("float", start="20260911T090000", end=""),
        vevent("day", start="VALUE=DATE:20260912", end="VALUE=DATE:20260913"),
        vevent("dur", start="20260911T090000", end="", extra="DURATION:PT1H30M"),
        vevent("win", start="TZID=W. Europe Standard Time:20260911T100000", end=""),
    )
    by_uid = {e.uid: e for e in cal.parse_ics(text)}
    assert (by_uid["tz"].start, by_uid["tz"].end) == (datetime(2026, 9, 11, 14, 0),
                                                      datetime(2026, 9, 11, 15, 0))
    assert by_uid["float"].start == by_uid["float"].end == datetime(2026, 9, 11, 9, 0)
    day = by_uid["day"]
    assert day.all_day and (day.start, day.end) == (datetime(2026, 9, 12), datetime(2026, 9, 13))
    assert by_uid["dur"].end == datetime(2026, 9, 11, 10, 30)
    assert by_uid["win"].start == datetime(2026, 9, 11, 10, 0)  # unknown zone: floating


def test_cancelled_recurring_and_override_flags():
    text = ics(vevent("c", extra="STATUS:CANCELLED"),
               vevent("series", extra="RRULE:FREQ=WEEKLY;BYDAY=TH"),
               vevent("series", start="20260910T100000Z", end="20260910T110000Z",
                      extra="RECURRENCE-ID:20260910T080000Z"))
    cancelled, master, override = cal.parse_ics(text)
    assert cancelled.cancelled and not cancelled.recurring
    assert master.recurring and not override.recurring
    assert override.recurrence_id == "20260910T080000Z"


def test_fetch_converts_webcal_and_caps_size():
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    def opener(request, timeout):
        seen["url"], seen["timeout"] = request.full_url, timeout
        return Resp(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")

    assert cal.fetch_ics("webcal://p01.example.com/secret.ics", timeout=5,
                         opener=opener).startswith("BEGIN:VCALENDAR")
    assert seen == {"url": "https://p01.example.com/secret.ics", "timeout": 5}
    with pytest.raises(cal.CalendarError, match="larger than") as exc:
        cal.fetch_ics("https://p01.example.com/secret.ics", max_bytes=10, opener=opener)
    assert "secret" not in str(exc.value)
    with pytest.raises(cal.CalendarError, match="https://"):
        cal.fetch_ics("ftp://x/y.ics", opener=opener)


# ------------------------------------------------------------------- import


def test_import_logs_creates_and_queues_in_one_commit(store, messages):
    seed(store)
    messages.clear()
    events = cal.parse_ics(ics(vevent(
        "utc-1", summary="Intro call",
        attendees=("mailto:jane@acme.de", "CN=Bob Stone:mailto:bob@beta.io",
                   "CN=Xavier Ray:mailto:x@gmail.com", "mailto:col@work.example.com",
                   f"mailto:{ME}", "CUTYPE=ROOM:mailto:room@group.calendar.google.com"),
        extra="DESCRIPTION:  Pricing and next steps\\n  ")))
    inbox = bcc.Inbox(store.root)
    result = cal.import_events(store, inbox, events, SETTINGS, store.now(), apply=True)
    assert (result.events, result.logged, result.contacts, result.review) == (1, 2, 1, 1)
    assert messages == ["calendar: imported 1 event (2 interactions, 1 contacts, 1 to review)"]

    [it] = store.companies["acme"].interactions
    assert (it.channel, it.direction, it.source, it.contact, it.subject) == (
        "meeting", "out", "calendar-import", "jane-doe", "Intro call")
    assert it.message_id == "ical:utc-1::jane@acme.de"
    assert it.date == datetime(2026, 9, 10, 10, 0) and it.body == "Pricing and next steps\n"
    assert store.companies["beta"].contacts["bob-stone"].email == "bob@beta.io"
    assert store.companies["beta"].interactions[0].channel == "meeting"

    [item] = inbox.items()
    assert (item.kind, item.address, item.reason) == ("meeting", "x@gmail.com",
                                                      "personal address (gmail.com)")

    messages.clear()
    again = cal.import_events(store, inbox, events, SETTINGS, store.now(), apply=True)
    assert (again.logged, again.contacts, again.review, again.duplicates) == (0, 0, 0, 3)
    assert messages == [] and len(store.companies["acme"].interactions) == 1


def test_dry_run_writes_nothing(store, messages):
    seed(store)
    messages.clear()
    events = cal.parse_ics(ics(vevent(attendees=("mailto:bob@beta.io", "mailto:y@nowhere.org"))))
    result = cal.import_events(store, bcc.Inbox(store.root), events, SETTINGS,
                               store.now(), apply=False)
    assert (result.logged, result.contacts, result.review) == (1, 1, 1)
    assert messages == [] and not (store.root / "inbox").exists()
    assert store.companies["beta"].contacts == {}


def test_filters_direction_window_recurring_and_upcoming(store, messages):
    seed(store)
    settings = cal.Settings(my_addresses=(ME,), ignore_domains=("work.example.com",),
                            ignore_titles=("focus",), min_attendees=2)
    events = cal.parse_ics(ics(
        vevent("theirs", organizer="CN=Jane:mailto:jane@acme.de", attendees=(f"mailto:{ME}",)),
        vevent("focus", summary="FOCUS time"),
        vevent("solo", organizer="", attendees=("mailto:jane@acme.de",)),
        vevent("internal", attendees=("mailto:col@work.example.com",)),
        vevent("declined", attendees=("PARTSTAT=DECLINED:mailto:jane@acme.de",)),
        vevent("old", start="20260801T080000Z", end="20260801T090000Z"),
        vevent("c", extra="STATUS:CANCELLED"),
        vevent("series", extra="RRULE:FREQ=WEEKLY"),
        vevent("series", start="20260911T080000Z", end="20260911T090000Z",
               extra="RECURRENCE-ID:20260911T080000Z"),
        vevent("soon", start="20260915T120000Z", end="20260915T130000Z", summary="Demo",
               attendees=("CN=Jane Doe:mailto:jane@acme.de",)),
        vevent("later", start="20260930T120000Z", end="20260930T130000Z"),
        vevent("soon-unknown", start="20260915T120000Z", end="20260915T130000Z",
               attendees=("mailto:y@nowhere.org",)),
    ))
    result = cal.import_events(store, bcc.Inbox(store.root), events, settings,
                               store.now(), apply=True)
    assert (result.events, result.logged, result.skipped) == (2, 2, 4)
    assert (result.recurring, result.cancelled) == (1, 1)
    reasons = sorted(line.rsplit("skipped: ", 1)[1] for line in result.lines if "skipped" in line)
    assert reasons == ["fewer than 2 attendees", "ignored title", "no external attendee",
                       "no external attendee"]
    by_id = {i.message_id: i for i in store.companies["acme"].interactions}
    assert by_id["ical:theirs::jane@acme.de"].direction == "in"
    assert "ical:series:20260911T080000Z:jane@acme.de" in by_id
    assert result.upcoming == [{
        "start": "2026-09-15T14:00", "end": "2026-09-15T15:00", "all_day": False,
        "title": "Demo", "location": "", "companies": [{"slug": "acme", "name": "Acme GmbH"}],
        "attendees": ["Jane Doe"]}]

    strict = cal.Settings(my_addresses=(ME,), min_attendees=3)
    none = cal.import_events(store, bcc.Inbox(store.root),
                             cal.parse_ics(ics(vevent("two"))), strict, store.now())
    assert none.skipped == 1 and none.logged == 0


def test_assign_meeting_item_logs_a_meeting(store, messages):
    seed(store)
    inbox = bcc.Inbox(store.root)
    cal.import_events(store, inbox, cal.parse_ics(ics(vevent(
        attendees=("CN=Ann Lee:mailto:ann@lee.com",)))), SETTINGS, store.now(), apply=True)
    [item] = inbox.items()
    messages.clear()
    slug, it = bcc.assign(store, inbox, item.id, "beta")
    assert (slug, it.channel, it.source, it.contact) == ("beta", "meeting",
                                                         "calendar-import", "ann-lee")
    assert messages == [f"calendar: {item.id} assigned to beta/ann-lee"]


def test_run_calendar_records_run_and_upcoming(store):
    seed(store)
    inbox = bcc.Inbox(store.root)
    text = ics(vevent(), vevent("soon", start="20260915T120000Z", end="20260915T130000Z"))
    result = cal.run_calendar(store, inbox, SETTINGS, True, lambda: text)
    assert result.logged == 1
    assert inbox.last_run(cal.LAST_RUN_FILE)["summary"] == result.summary()
    assert inbox.last_run() is None  # the BCC run file is untouched
    [row] = cal.read_upcoming(inbox, store.now())
    assert row["start"] == datetime(2026, 9, 15, 14, 0) and row["companies"][0]["slug"] == "acme"
    assert cal.read_upcoming(inbox, store.now() + timedelta(days=2)) == []

    def boom():
        raise cal.CalendarError("p01.example.com answered HTTP 404")

    with pytest.raises(cal.CalendarError):
        cal.run_calendar(store, inbox, SETTINGS, True, boom)
    assert inbox.last_run(cal.LAST_RUN_FILE)["error"] == "p01.example.com answered HTTP 404"


# ------------------------------------------------------------------ secrets


def test_resolve_url_order(tmp_path):
    calls = []

    def keychain(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="https://kc.example/a.ics\n")

    settings = cal.settings_from_config({"calendar_keychain_account": "me"})
    env = {"OWNCRM_CALENDAR_ICS_URL": "https://env.example/a.ics"}
    get = lambda env: cal.resolve_url(settings, tmp_path, env=env, runner=keychain,
                                      platform="darwin")
    assert get(env) == "https://env.example/a.ics" and calls == []
    assert get({"CRM_CALENDAR_URL": "https://legacy.example/a.ics"}) == \
        "https://legacy.example/a.ics"
    assert get({}) == "https://kc.example/a.ics"
    assert calls == [["security", "find-generic-password", "-s", "crm-calendar", "-a", "me", "-w"]]
    (tmp_path / ".secrets.toml").write_text('calendar_ics_url = "webcal://file.example/a.ics"\n')
    (tmp_path / ".secrets.toml").chmod(0o600)
    assert get({}) == "webcal://file.example/a.ics"  # the file beats the Keychain


def test_settings_from_config_and_gitignore():
    s = cal.settings_from_config({"my_addresses": ["Me@X.com"], "bcc_ignore_domains": ["x.com"],
                                  "calendar_ignore_titles": [" Lunch "],
                                  "calendar_min_attendees": 3, "calendar_lookback_days": 7})
    assert (s.my_addresses, s.ignore_domains, s.ignore_titles) == (("me@x.com",), ("x.com",),
                                                                   ("lunch",))
    assert (s.min_attendees, s.lookback_days, s.keychain_service) == (3, 7, "crm-calendar")
    ignored = (Path(__file__).resolve().parents[1] / ".gitignore").read_text().split()
    assert {".secrets.toml", "inbox/upcoming.json", "inbox/.last-calendar-run.json"} <= set(ignored)


# ---------------------------------------------------------------------- cli


def test_cmd_calendar_with_ics_file_and_unconfigured(store, messages, tmp_path):
    seed(store)
    path = tmp_path / "cal.ics"
    path.write_text(ics(vevent(summary="Intro call")))
    config = {"my_addresses": [ME], "bcc_ignore_domains": ["work.example.com"]}
    text, code = crm.cmd_calendar(store, store.root, config, ics=[path])
    messages.clear()
    assert code == 0
    assert text.splitlines() == [
        "2026-09-10 10:00 | Intro call | meeting out | jane@acme.de | acme/jane-doe | log",
        "1 meetings read: 1 interactions logged, 0 contacts created, 0 to review, "
        "0 already imported, 0 skipped, 0 recurring skipped, 0 cancelled, 0 upcoming this week",
        "Dry run; add --apply to write.",
    ]
    assert store.companies["acme"].interactions == [] and messages == []

    text, code = crm.cmd_calendar(store, store.root, config, resolve=lambda: "")
    assert code == 1 and "security add-generic-password -s crm-calendar -a ics" in text
    text, code = crm.cmd_sync(store, store.root, {**config, "bcc_address": "me+bcc@gmail.com"},
                              open_mailbox=lambda: FakeBox([raw_mail()]), resolve=lambda: "")
    assert code == 0
    assert text.startswith("== BCC ==\n2026-09-14 10:30 | email out | jane@acme.de")
    assert text.endswith("== Calendar ==\nCalendar import skipped: no calendar URL configured")

    text, code = crm.cmd_calendar(store, store.root, config, fetch=lambda: ics(vevent()))
    assert code == 0 and "1 interactions logged" in text


def test_parser_has_calendar_and_sync():
    parser = crm._build_parser()
    args = parser.parse_args(["calendar", "--apply", "--ics", "a.ics", "b.ics"])
    assert args.apply and args.ics == [Path("a.ics"), Path("b.ics")]
    assert parser.parse_args(["sync", "--apply"]).apply


# ---------------------------------------------------------------------- web


@pytest.fixture
def client(tmp_path):
    for args in (["init", "-b", "main"], ["config", "user.name", "CRM Test"],
                 ["config", "user.email", "crm@test.local"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    app = create_app(tmp_path, config={"port": 8765, "silent_days": 14, "push_enabled": False, "owner_email": "me@example.com",
                                       "remote": "origin", "my_addresses": [ME],
                                       "bcc_ignore_domains": ["work.example.com"]})
    app.state.calendar_url = lambda refresh=False: ""
    c = TestClient(app, follow_redirects=False)
    c.app_state, c.repo = app.state, tmp_path
    return c


def floating(dt: datetime) -> str:
    return f"{dt:%Y%m%dT%H%M00}"


def test_calendar_import_route_upcoming_and_inbox(client):
    client.post("/companies", data={"name": "Acme GmbH", "website": "acme.de",
                                    "source": "other", "stage": "prospect"})
    r = client.post("/calendar/import", data={"back": "/inbox"})
    assert r.headers["location"].startswith("/settings?flash=Calendar%20import%20failed")

    now = datetime.now().replace(second=0, microsecond=0)
    past, soon = now - timedelta(days=2), now + timedelta(days=1)
    feed = ics(
        vevent("p1", start=floating(past), end=floating(past + timedelta(hours=1)),
               summary="Discovery", attendees=("CN=Jane Doe:mailto:jane@acme.de",
                                               "CN=Ann Lee:mailto:ann@lee.com")),
        vevent("s1", start=floating(soon), end=floating(soon + timedelta(hours=1)),
               summary="Demo with Acme", attendees=("CN=Jane Doe:mailto:jane@acme.de",)))
    client.app_state.calendar_url = lambda refresh=False: "https://example.test/secret.ics"
    client.app_state.fetch_calendar = lambda url: feed
    r = client.post("/calendar/import", data={"back": "/calendar"})
    assert r.status_code == 303
    assert r.headers["location"].startswith("/calendar?flash=Calendar%20import%3A%201%20meetings")
    log = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=client.repo,
                         capture_output=True, text=True).stdout.strip()
    assert log == "calendar: imported 1 event (1 interactions, 1 contacts, 1 to review)"

    page = client.get("/calendar").text
    assert "Meetings this week (1)" in page and "Demo with Acme" in page
    assert '<a href="/companies/acme">Acme GmbH</a>' in page

    page = client.get("/settings").text
    assert 'class="tag">meeting</span>' in page and "ann@lee.com" in page
    assert "Import meetings now" in page and "Last meeting import" in page

    client.app_state.fetch_calendar = lambda url: (_ for _ in ()).throw(
        cal.CalendarError("example.test answered HTTP 404"))
    r = client.post("/calendar/import", data={"back": "/inbox"})
    assert "HTTP%20404" in r.headers["location"]
    assert 'title="calendar import failed: example.test answered HTTP 404"' in client.get("/").text
    client.app_state.calendar_url = lambda refresh=False: ""
    assert 'class="alert"' not in client.get("/").text  # not set up: no alert
