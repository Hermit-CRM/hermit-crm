"""Calendar import: log past meetings from a secret ICS feed (no OAuth).

Standard library only (urllib, zoneinfo, a small RFC 5545 parser). Once a day
launchd runs ``owncrm sync --apply`` (BCC, then this); /inbox and /calendar
have an "Import meetings now" button.

Per past event (end <= now, within ``calendar_lookback_days``), per external
attendee (attendees plus the organizer, minus your addresses, the ignored
domains and resource calendars), the BCC matching applies unchanged
(app/bcc.py ``handle_entry``): an exact contact email logs a ``meeting``
interaction there; one company with that domain gets the contact created (or a
same-named contact's email filled in) first; everything else waits in inbox/
as a ``meeting`` item. The dedup key is
``ical:<UID>:<RECURRENCE-ID>:<attendee email>`` in ``message_id``.

Recurring masters (RRULE) are skipped; single overrides (RECURRENCE-ID) are
ordinary events. Cancelled events are skipped. Matched events in the next
seven days are written to inbox/upcoming.json for the Calendar page.

The feed URL is a secret and never lives in config.toml: $OWNCRM_CALENDAR_ICS_URL,
then ``calendar_ics_url`` in .secrets.toml, then the macOS Keychain (service
``calendar_keychain_service``, account ``calendar_keychain_account``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import bcc
from . import secrets
from .models import fmt_datetime, normalise_email
from .store import Store, normalise_body

logger = logging.getLogger("crm.calendar")

LAST_RUN_FILE = ".last-calendar-run.json"
UPCOMING_FILE = "upcoming.json"
SECRETS_FILE = ".secrets.toml"
URL_ENV = "CRM_CALENDAR_URL"
MAX_BYTES = 10 * 1024 * 1024
FETCH_TIMEOUT = 30.0
DESCRIPTION_CHARS = 500
UPCOMING_DAYS = 7
RESOURCE_DOMAINS = ("resource.calendar.google.com", "group.calendar.google.com")


class CalendarError(Exception):
    """A readable reason the import could not run (no URL, network, bad feed)."""


# ------------------------------------------------------------------ settings


@dataclass
class Settings:
    keychain_service: str = "crm-calendar"
    keychain_account: str = "ics"
    lookback_days: int = 30
    ignore_titles: tuple[str, ...] = ()
    min_attendees: int = 2
    my_addresses: tuple[str, ...] = ()
    ignore_domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.my_addresses = tuple(sorted(
            {normalise_email(a) for a in self.my_addresses if a.strip()}))
        self.ignore_domains = tuple(sorted(
            {d.strip().lower().lstrip("@") for d in self.ignore_domains if d.strip()}))
        self.ignore_titles = tuple(t.strip().lower() for t in self.ignore_titles if t.strip())

    def is_me(self, address: str) -> bool:
        return normalise_email(address) in self.my_addresses

    def ignored(self, address: str) -> bool:
        return address.rpartition("@")[2] in self.ignore_domains

    def title_ignored(self, title: str) -> bool:
        low = (title or "").lower()
        return any(t in low for t in self.ignore_titles)


def settings_from_config(config: dict) -> Settings:
    return Settings(
        keychain_service=str(config.get("calendar_keychain_service", "crm-calendar")),
        keychain_account=str(config.get("calendar_keychain_account", "ics")),
        lookback_days=int(config.get("calendar_lookback_days", 30)),
        ignore_titles=tuple(config.get("calendar_ignore_titles", ())),
        min_attendees=int(config.get("calendar_min_attendees", 2)),
        my_addresses=tuple(config.get("my_addresses", ())),
        ignore_domains=tuple(config.get("bcc_ignore_domains", ())),
    )


def resolve_url(settings: Settings, root: Path, env: dict | None = None,
                runner=subprocess.run, platform: str | None = None) -> str:
    """The ICS URL via owncrm/secrets.py: $OWNCRM_CALENDAR_ICS_URL (or
    $CRM_CALENDAR_URL), .secrets.toml, then the macOS Keychain; '' if none."""
    config = {"calendar_keychain_service": settings.keychain_service,
              "calendar_keychain_account": settings.keychain_account}
    return secrets.get("calendar_ics_url", root, config, env=env, runner=runner,
                       platform=platform)


def setup_hint(settings: Settings) -> str:
    return ("Calendar import is not set up: no calendar URL configured. Set "
            "OWNCRM_CALENDAR_ICS_URL, add calendar_ics_url to .secrets.toml, or add it to the macOS Keychain with: security "
            f"add-generic-password -s {settings.keychain_service} "
            f"-a {settings.keychain_account} -w '<url>'")


# ------------------------------------------------------------------- fetch


def fetch_ics(url: str, timeout: float = FETCH_TIMEOUT, max_bytes: int = MAX_BYTES,
              opener=urllib.request.urlopen) -> str:
    """Download the feed. Errors name only the host: the URL itself is a secret."""
    url = (url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    host = urlparse(url).hostname or "the calendar host"
    if urlparse(url).scheme not in ("http", "https"):
        raise CalendarError("the calendar URL must start with https:// or webcal://")
    request = urllib.request.Request(url, headers={"User-Agent": "owncrm"})
    try:
        with opener(request, timeout=timeout) as resp:
            data = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise CalendarError(f"{host} answered HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise CalendarError(f"could not fetch the calendar from {host}: {reason}") from exc
    if len(data) > max_bytes:
        raise CalendarError(f"the calendar from {host} is larger than "
                            f"{max_bytes // (1024 * 1024)} MB")
    return data.decode("utf-8", "replace")


# ------------------------------------------------------------------- parsing


@dataclass
class Attendee:
    email: str
    name: str = ""
    partstat: str = ""
    cutype: str = ""


@dataclass
class Event:
    uid: str
    start: datetime
    end: datetime
    summary: str = ""
    description: str = ""
    location: str = ""
    recurrence_id: str = ""
    organizer: Attendee | None = None
    attendees: list[Attendee] = field(default_factory=list)
    all_day: bool = False
    cancelled: bool = False
    recurring: bool = False  # an RRULE master; skipped


def unfold(text: str) -> list[str]:
    """RFC 5545 §3.1: a line break followed by a space or tab continues the line."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]", "", text)
    return [line for line in text.split("\n") if line.strip()]


_ESCAPE = re.compile(r"\\([\\;,nN])")


def unescape(value: str) -> str:
    return _ESCAPE.sub(lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)


def split_line(line: str) -> tuple[str, dict[str, str], str]:
    """``NAME;P1=a;P2="b:c":value`` -> (NAME, {P1: a, P2: b:c}, value)."""
    in_quotes, colon = False, -1
    for i, ch in enumerate(line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ":" and not in_quotes:
            colon = i
            break
    if colon == -1:
        return line.upper(), {}, ""
    head, value = line[:colon], line[colon + 1:]
    parts, buf, in_quotes = [], "", False
    for ch in head:
        if ch == '"':
            in_quotes = not in_quotes
        if ch == ";" and not in_quotes:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    params = {}
    for p in parts[1:]:
        key, _, val = p.partition("=")
        params[key.strip().upper()] = val.strip().strip('"')
    return parts[0].strip().upper(), params, value


def _local(dt: datetime) -> datetime:
    """Aware datetimes become naive local time, like every date in the store."""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.replace(second=0, microsecond=0)


def parse_dt(value: str, params: dict[str, str]) -> tuple[datetime, bool]:
    """(naive local datetime, all_day) for a DTSTART/DTEND/RECURRENCE-ID value."""
    value = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value[:8], "%Y%m%d")
        return d, True
    m = re.fullmatch(r"(\d{8}T\d{4})(\d{2})?(Z?)", value)
    if not m:
        raise ValueError(f"not an iCalendar date-time: {value!r}")
    dt = datetime.strptime(m.group(1), "%Y%m%dT%H%M")
    if m.group(3):
        return _local(dt.replace(tzinfo=timezone.utc)), False
    tzid = params.get("TZID", "")
    if tzid:
        try:
            return _local(dt.replace(tzinfo=ZoneInfo(tzid))), False
        except (ZoneInfoNotFoundError, ValueError):
            # e.g. Outlook's "W. Europe Standard Time": treat as floating local time
            logger.info("unknown TZID %r, using local time", tzid)
    return dt, False


_DURATION = re.compile(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")


def parse_duration(value: str) -> timedelta | None:
    m = _DURATION.fullmatch(value.strip())
    if not m:
        return None
    sign, weeks, days, hours, minutes, seconds = m.groups()
    delta = timedelta(weeks=int(weeks or 0), days=int(days or 0), hours=int(hours or 0),
                      minutes=int(minutes or 0), seconds=int(seconds or 0))
    return -delta if sign == "-" else delta


def _person(params: dict[str, str], value: str) -> Attendee | None:
    address = value.strip()
    if address.lower().startswith("mailto:"):
        address = address[7:]
    address = normalise_email(address)
    if "@" not in address:
        return None
    return Attendee(email=address, name=" ".join(params.get("CN", "").split()),
                    partstat=params.get("PARTSTAT", "").upper(),
                    cutype=params.get("CUTYPE", "").upper())


def _event(props: list[tuple[str, dict, str]]) -> Event | None:
    ev: dict = {"attendees": []}
    start = end = None
    duration = None
    for name, params, value in props:
        try:
            if name == "DTSTART":
                start, ev["all_day"] = parse_dt(value, params)
            elif name == "DTEND":
                end, _ = parse_dt(value, params)
            elif name == "DURATION":
                duration = parse_duration(value)
            elif name == "UID":
                ev["uid"] = value.strip()
            elif name == "SUMMARY":
                ev["summary"] = " ".join(unescape(value).split())
            elif name == "DESCRIPTION":
                ev["description"] = unescape(value)[:DESCRIPTION_CHARS]
            elif name == "LOCATION":
                ev["location"] = " ".join(unescape(value).split())
            elif name == "RECURRENCE-ID":
                ev["recurrence_id"] = value.strip()
            elif name == "RRULE":
                ev["recurring"] = True
            elif name == "STATUS":
                ev["cancelled"] = value.strip().upper() == "CANCELLED"
            elif name == "ORGANIZER":
                ev["organizer"] = _person(params, value)
            elif name == "ATTENDEE":
                person = _person(params, value)
                if person is not None:
                    ev["attendees"].append(person)
        except ValueError as exc:
            logger.warning("skipping %s in event %s: %s", name, ev.get("uid", "?"), exc)
    if start is None:
        return None
    if end is None:
        if duration is not None:
            end = start + duration
        else:
            end = start + timedelta(days=1) if ev.get("all_day") else start
    if ev.get("recurrence_id"):
        ev["recurring"] = False  # a single override of a series
    return Event(uid=ev.pop("uid", ""), start=start, end=end, **ev)


def parse_ics(text: str) -> list[Event]:
    """Every VEVENT in the feed, in feed order (cancelled and RRULE masters flagged)."""
    events: list[Event] = []
    stack: list[str] = []
    props: list[tuple[str, dict, str]] = []
    for line in unfold(text):
        name, params, value = split_line(line)
        if name == "BEGIN":
            stack.append(value.strip().upper())
            if stack[-1] == "VEVENT":
                props = []
        elif name == "END":
            kind = stack.pop() if stack else ""
            if kind == "VEVENT":
                ev = _event(props)
                if ev is not None:
                    events.append(ev)
        elif stack and stack[-1] == "VEVENT":  # not VALARM or other sub-components
            props.append((name, params, value))
    return events


# -------------------------------------------------------------------- import


def is_resource(person: Attendee) -> bool:
    domain = person.email.rpartition("@")[2]
    return (person.cutype in ("RESOURCE", "ROOM")
            or any(domain == d or domain.endswith("." + d) for d in RESOURCE_DOMAINS))


def participants(event: Event) -> list[Attendee]:
    """Organizer and attendees, one per address, without meeting rooms."""
    seen, out = set(), []
    people = ([event.organizer] if event.organizer else []) + event.attendees
    for p in people:
        if p.email in seen or is_resource(p):
            continue
        seen.add(p.email)
        out.append(p)
    return out


def external_attendees(event: Event, settings: Settings) -> list[Attendee]:
    """People to log: not you, not a colleague, not a room, and did not decline."""
    return [p for p in participants(event)
            if not settings.is_me(p.email) and not settings.ignored(p.email)
            and p.partstat != "DECLINED"]


def direction_for(event: Event, settings: Settings) -> str:
    if event.organizer is None or settings.is_me(event.organizer.email):
        return "out"
    return "in"


def dedup_key(event: Event, address: str) -> str:
    return f"ical:{event.uid}:{event.recurrence_id or ''}:{address}"


@dataclass
class RunResult:
    events: int = 0  # past events in the window with an external attendee
    logged: int = 0
    contacts: int = 0
    review: int = 0
    duplicates: int = 0
    skipped: int = 0
    recurring: int = 0
    cancelled: int = 0
    lines: list[str] = field(default_factory=list)
    upcoming: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.events} meetings read: {self.logged} interactions logged, "
                f"{self.contacts} contacts created, {self.review} to review, "
                f"{self.duplicates} already imported, {self.skipped} skipped, "
                f"{self.recurring} recurring skipped, {self.cancelled} cancelled, "
                f"{len(self.upcoming)} upcoming this week")

    def commit_message(self) -> str:
        events = "1 event" if self.events == 1 else f"{self.events} events"
        return (f"calendar: imported {events} ({self.logged} interactions, "
                f"{self.contacts} contacts, {self.review} to review)")


def _upcoming_row(store: Store, event: Event, people: list[Attendee]) -> dict | None:
    companies: dict[str, str] = {}
    for p in people:
        match = bcc.match_address(store, p.email)
        if match.action in ("log", "create-contact"):
            companies[match.company] = store.companies[match.company].name
    if not companies:
        return None
    return {
        "start": fmt_datetime(event.start), "end": fmt_datetime(event.end),
        "all_day": event.all_day, "title": event.summary, "location": event.location,
        "companies": [{"slug": s, "name": n} for s, n in sorted(companies.items())],
        "attendees": [p.name or p.email for p in people],
    }


def import_events(store: Store, inbox: bcc.Inbox, events: Iterable[Event],
                  settings: Settings, now: datetime | None = None,
                  apply: bool = False) -> RunResult:
    """Plan (and with apply, write) meeting interactions; one commit for the run."""
    now = now or store.now()
    since = now - timedelta(days=settings.lookback_days)
    until = now + timedelta(days=UPCOMING_DAYS)
    result = RunResult()
    seen = inbox.seen()
    planned: dict[str, str] = {}
    with store.batch("calendar: import") as batch:
        for event in sorted(events, key=lambda e: (e.start, e.uid)):
            label = f"{event.start:%Y-%m-%d %H:%M} | {event.summary or '-'}"
            if event.cancelled:
                result.cancelled += 1
                continue
            if event.recurring:
                result.recurring += 1
                continue
            past = event.end <= now
            if past and event.start < since:
                continue
            if not past and event.start >= until:
                continue
            reason = ""
            if settings.title_ignored(event.summary):
                reason = "ignored title"
            elif len(participants(event)) < settings.min_attendees:
                reason = f"fewer than {settings.min_attendees} attendees"
            people = external_attendees(event, settings) if not reason else []
            if not reason and not people:
                reason = "no external attendee"
            if not past:
                row = _upcoming_row(store, event, people) if people else None
                if row is not None:
                    result.upcoming.append(row)
                continue
            if reason:
                result.skipped += 1
                result.lines.append(f"{label} | skipped: {reason}")
                continue
            result.events += 1
            direction = direction_for(event, settings)
            body = normalise_body(event.description.strip())
            for p in people:
                entry = bcc.Entry(dedup_key(event, p.email), event.start, direction,
                                  p.email, p.name, event.summary, body,
                                  channel="meeting", source="calendar-import")
                outcome = bcc.handle_entry(store, inbox, entry, seen, planned, result, apply)
                result.lines.append(f"{label} | meeting {direction} | {p.email} | {outcome}")
        batch["message"] = result.commit_message()
    return result


def write_upcoming(inbox: bcc.Inbox, rows: list[dict], at: datetime) -> None:
    inbox.dir.mkdir(parents=True, exist_ok=True)
    data = {"generated": fmt_datetime(at), "events": rows}
    (inbox.dir / UPCOMING_FILE).write_text(json.dumps(data, indent=2) + "\n",
                                           encoding="utf-8")


def read_upcoming(inbox: bcc.Inbox, now: datetime, days: int = UPCOMING_DAYS) -> list[dict]:
    """Rows from the last import still ending after now and starting within ``days``."""
    try:
        data = json.loads((inbox.dir / UPCOMING_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    until = now + timedelta(days=days)
    rows = []
    for row in data.get("events", []) if isinstance(data, dict) else []:
        try:
            start = datetime.fromisoformat(str(row["start"]))
            end = datetime.fromisoformat(str(row["end"]))
        except (KeyError, ValueError, TypeError):
            continue
        if end > now and start < until:
            rows.append(dict(row, start=start, end=end))
    return sorted(rows, key=lambda r: r["start"])


def run_calendar(store: Store, inbox: bcc.Inbox, settings: Settings, apply: bool,
                 fetch: Callable[[], str]) -> RunResult:
    """Fetch, parse and import; with apply records the run and writes upcoming.json."""
    try:
        result = import_events(store, inbox, parse_ics(fetch()), settings,
                               store.now(), apply)
    except Exception as exc:
        if apply:
            message = (str(exc) if isinstance(exc, CalendarError)
                       else f"{type(exc).__name__}: {exc}")
            inbox.record_run(False, store.now(), error=message, file=LAST_RUN_FILE)
        raise
    if apply:
        write_upcoming(inbox, result.upcoming, store.now())
        inbox.record_run(True, store.now(), summary=result.summary(), file=LAST_RUN_FILE)
    return result
