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

"""Import a LinkedIn conversation the person is looking at.

The bookmarklet reads the page in the person's own tab and sends raw pieces
(sender text, time text, day heading, message text, the header's profile link).
Everything that needs judgement happens here, in plain Python pytest can reach:
language, dates, direction, matching a contact, and not logging a message twice.
Nothing is fetched from LinkedIn.

    parse(payload, now)  -> Thread       raw pieces to messages with real dates
    match(store, thread) -> Match        which contact the thread is with
    plan(store, ...)     -> Plan         each message new, logged or maybe a duplicate
    apply(store, plan, selected)         one commit, one `linkedin` interaction each

The payload is attacker-shaped text: a message can say anything. It is read as
data only. It is size-capped, stripped of control characters, never evaluated,
and never used as a path, a slug or a URL without being rebuilt from its parts.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta

from . import capture, scrape
from .models import Channel, Interaction, InteractionSource
from .store import Store, normalise_body

PAYLOAD_VERSION = 1
MAX_MESSAGES = 500
MAX_MESSAGE_CHARS = 20_000
MAX_TOTAL_BYTES = 1_000_000
MAX_FIELD_CHARS = 300  # a name, a heading, a time, an id
MAX_CLOCK_SKEW = timedelta(days=2)  # how far the browser's clock may be from ours

PROFILE_PREFIX = "https://www.linkedin.com/in/"


class ConversationError(Exception):
    """A payload that cannot be imported, with a reason fit to show the person."""


@dataclass
class Message:
    direction: str  # "in", "out", or "ask" when the page does not say whose it is
    when: datetime | None  # naive local time, as Store._coerce_datetime expects
    text: str  # as it will be stored: normalise_body applied
    urn: str = ""  # LinkedIn's id for the message, opaque
    who: str = ""  # the sender's name as the page showed it
    heading: str = ""  # what to ask the person about while `when` is None
    inherited: bool = False  # the time is the first message of the run's, not its own
    date_conflict: bool = False  # the page's own absolute time says another day
    clock: time | None = None  # the time of day as read, kept when only the day is asked for


@dataclass
class Thread:
    name: str  # the other person, from the header
    profile_urls: list[str]  # every address that may be the contact's, best first
    messages: list[Message]  # oldest first, as on the page
    needs_date: list[str] = field(default_factory=list)  # headings the parser could not read
    dropped: int = 0  # messages cut by the size caps (the oldest go first)

    @property
    def profile_url(self) -> str:
        return self.profile_urls[0] if self.profile_urls else ""


# --------------------------------------------------------------- reading text

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # \t \n \r stay


def _text(value, limit: int = MAX_FIELD_CHARS, multiline: bool = False) -> str:
    """A string from the payload, or "" when it is anything else."""
    if not isinstance(value, str):
        return ""
    value = _CONTROL.sub("", value)[:limit]
    return value if multiline else " ".join(value.split())


def _profile_url(value) -> str:
    """A LinkedIn profile address rebuilt from `value`, or "" when it is not one."""
    text = _text(value, 500)
    if not text.startswith(("/in/", "http://", "https://")):
        return ""
    url = scrape.profile_url(text)
    if not url.startswith(PROFILE_PREFIX) or not url[len(PROFILE_PREFIX):].strip("."):
        return ""
    return url


def fold(text: str) -> str:
    """Lower case, no accents, punctuation turned to spaces, one space between words."""
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'").replace("`", "'")
    return " ".join(re.sub(r"[.,]", " ", text).split())


# --------------------------------------------------------------- day headings


@dataclass(frozen=True)
class _Language:
    today: tuple[str, ...]
    yesterday: tuple[str, ...]
    weekdays: dict[str, int]  # name or abbreviation (folded) -> 0 Monday .. 6 Sunday
    months: dict[str, int]  # name or abbreviation (folded) -> 1 .. 12


def _language(today, yesterday, weekdays, months) -> _Language:
    return _Language(
        tuple(today.split()), tuple(yesterday.split()),
        {name: i for i, names in enumerate(weekdays) for name in names.split()},
        {name: i + 1 for i, names in enumerate(months) for name in names.split()},
    )


LANGUAGES = {
    "en": _language(
        "today", "yesterday",
        ["monday mon", "tuesday tue tues", "wednesday wed", "thursday thu thur thurs",
         "friday fri", "saturday sat", "sunday sun"],
        ["january jan", "february feb", "march mar", "april apr", "may", "june jun",
         "july jul", "august aug", "september sep sept", "october oct",
         "november nov", "december dec"]),
    "nl": _language(
        "vandaag", "gisteren",
        ["maandag ma", "dinsdag di", "woensdag wo", "donderdag do", "vrijdag vr",
         "zaterdag za", "zondag zo"],
        ["januari jan", "februari feb", "maart mrt", "april apr", "mei", "juni jun",
         "juli jul", "augustus aug", "september sep sept", "oktober okt",
         "november nov", "december dec"]),
    "de": _language(
        "heute", "gestern",
        ["montag mo", "dienstag di", "mittwoch mi", "donnerstag do", "freitag fr",
         "samstag sonnabend sa", "sonntag so"],
        ["januar janner jan", "februar feb", "marz maerz mar mrz", "april apr", "mai",
         "juni jun", "juli jul", "august aug", "september sep sept", "oktober okt",
         "november nov", "dezember dez"]),
    "fr": _language(
        "aujourd'hui", "hier",
        ["lundi lun", "mardi mar", "mercredi mer", "jeudi jeu", "vendredi ven",
         "samedi sam", "dimanche dim"],
        ["janvier janv jan", "fevrier fevr fev", "mars mar", "avril avr", "mai",
         "juin", "juillet juil", "aout", "septembre sept sep", "octobre oct",
         "novembre nov", "decembre dec"]),
    "es": _language(
        "hoy", "ayer",
        ["lunes lun", "martes mar", "miercoles mie", "jueves jue", "viernes vie",
         "sabado sab", "domingo dom"],
        ["enero ene", "febrero feb", "marzo mar", "abril abr", "mayo may", "junio jun",
         "julio jul", "agosto ago", "septiembre setiembre sep sept", "octubre oct",
         "noviembre nov", "diciembre dic"]),
}

_FILLER = {"de", "del"}  # "28 de octubre de 2025"
_ISO_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_FIRST = re.compile(r"^([a-z']+) (\d{1,2})(?: (\d{4}))?$")
_DAY_FIRST = re.compile(r"^(\d{1,2}) ([a-z']+)(?: (\d{4}))?$")


def _most_recent_year(month: int, day: int, today: date) -> date | None:
    """`Oct 28` with no year: this year's, or last year's when that is still ahead."""
    for year in range(today.year, today.year - 9, -1):  # a Feb 29 may be years back
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate <= today:
            return candidate
    return None


def _read_day(words: str, today: date, lang: _Language) -> date | None:
    if words in lang.today:
        return today
    if words in lang.yesterday:
        return date.fromordinal(today.toordinal() - 1)
    if words in lang.weekdays:
        # LinkedIn says "Today" for today, so a weekday is always 1 to 7 days back.
        back = (today.weekday() - lang.weekdays[words]) % 7 or 7
        return date.fromordinal(today.toordinal() - back)
    iso = _ISO_DAY.match(words)
    if iso:
        return _build(int(iso[1]), int(iso[2]), int(iso[3]))
    words = " ".join(w for w in words.split() if w not in _FILLER)
    if m := _MONTH_FIRST.match(words):
        month, day, year = lang.months.get(m[1]), int(m[2]), m[3]
    elif m := _DAY_FIRST.match(words):
        month, day, year = lang.months.get(m[2]), int(m[1]), m[3]
    else:
        return None
    if month is None:
        return None
    return _build(int(year), month, day) if year else _most_recent_year(month, day, today)


def _build(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _languages(lang: str) -> list[_Language]:
    """The page's own language when we know it, else every language we know."""
    primary = re.split(r"[-_]", (lang or "").strip().lower())[0]
    return [LANGUAGES[primary]] if primary in LANGUAGES else list(LANGUAGES.values())


def parse_day(heading: str, today: date, lang: str = "") -> date | None:
    """The date a day heading names, or None when it is not certain.

    Under a page language we know, only that language reads the heading. Without
    one every language tries, and the heading counts only when they all agree,
    so "mar" (Tuesday in French and Spanish) is read and a clash is asked about.
    """
    words = fold(heading)
    if not words:
        return None
    found = {_read_day(words, today, language) for language in _languages(lang)} - {None}
    return found.pop() if len(found) == 1 else None


# ---------------------------------------------------------------------- times

_TIME = re.compile(r"^(\d{1,2})[:.](\d{2})(?: ?([ap])\.? ?m\.?)?$")


def parse_time(text: str) -> time | None:
    """`6:24 PM`, `12:26 am`, `18:24`; None for anything else."""
    m = _TIME.match(" ".join((text or "").lower().split()))
    if not m:
        return None
    hour, minute, half = int(m[1]), int(m[2]), m[3]
    if minute > 59 or hour > (12 if half else 23) or (half and hour == 0):
        return None
    if half:
        hour = hour % 12 + (12 if half == "p" else 0)
    return time(hour, minute)


_SENT_TITLE = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4}),? +(\d{1,2}[:.]\d{2}(?: ?[ap]\.? ?m\.?)?)", re.I)


def _title_disagrees(title: str, when: datetime) -> bool:
    """The absolute time on an own message says a day other than the heading's.

    A US style title is ambiguous (1/11 is 1 November or 11 January), so it
    disagrees only when neither reading is the heading's day. A title in a
    format we do not know checks nothing.
    """
    m = _SENT_TITLE.search(title or "")
    if not m or parse_time(m[4]) is None:
        return False
    a, b, year = int(m[1]), int(m[2]), int(m[3])
    readings = {_build(year, a, b), _build(year, b, a)} - {None}
    return bool(readings) and when.date() not in readings


# ---------------------------------------------------------------------- parse


def _reference_clock(payload: dict, now: datetime) -> datetime:
    """The browser's clock when the payload has one, so "Today" is its today.

    The stamp is the payload's word, so it only counts when it is a plain local
    time within a couple of days of ours: a browser a few hours off is fine, a
    stamp from the year 1 or 9999 would overflow every date sum below.
    """
    try:
        stamp = datetime.fromisoformat(_text(payload.get("now_local"), 40))
    except ValueError:
        return now
    stamp = stamp.replace(tzinfo=None)
    return stamp if abs(stamp - now) <= MAX_CLOCK_SKEW else now


def _sender_key(entry: dict) -> str:
    return _profile_url(entry.get("who_href")) or fold(_text(entry.get("who")))


def parse(payload, now: datetime) -> Thread:
    """Raw bookmarklet pieces to a Thread. Raises ConversationError, never crashes."""
    if not isinstance(payload, dict) or payload.get("v") != PAYLOAD_VERSION:
        raise ConversationError("this is not a conversation Hermit can read")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ConversationError("this is not a conversation Hermit can read")
    entries = [e for e in raw_items if isinstance(e, dict)]

    header = payload.get("other")
    header = header if isinstance(header, dict) else {}
    name = _text(header.get("name"))
    header_url = _profile_url(header.get("href"))
    if not name and not header_url:
        raise ConversationError("group conversations are not supported")
    if len({k for e in entries if e.get("is_other") is True
            if (k := _sender_key(e))}) > 1:
        raise ConversationError("group conversations are not supported")
    profile_urls = list(dict.fromkeys(
        u for u in (header_url, _profile_url(payload.get("url"))) if u))

    reference = _reference_clock(payload, now)
    lang = _text(payload.get("lang"), 20)
    messages: list[Message] = []
    last_day = last_time = ""
    for entry in entries:
        own_day, own_time = _text(entry.get("day")), _text(entry.get("time"))
        day = own_day or last_day
        # A new day's first message names its own time; never borrow yesterday's.
        carried = not own_time and (not own_day or own_day == last_day) and bool(last_time)
        at = own_time or (last_time if carried else "")
        last_day, last_time = day, at
        text = _text(entry.get("text"), MAX_MESSAGE_CHARS, multiline=True)
        body = normalise_body(text)
        if not body.strip():
            continue
        is_other = entry.get("is_other")
        message = Message(
            direction="ask" if not isinstance(is_other, bool) else "in" if is_other else "out",
            when=None, text=body, urn=_text(entry.get("urn"), 500),
            who=_text(entry.get("who")), inherited=bool(entry.get("inherited")) or carried,
        )
        _date(message, day, at, reference, lang, _text(entry.get("sent_title"), 200))
        messages.append(message)

    kept = _within_caps(messages)
    needs_date = list(dict.fromkeys(m.heading for m in kept if m.when is None))
    return Thread(name=name, profile_urls=profile_urls, messages=kept,
                  needs_date=needs_date, dropped=len(messages) - len(kept))


def _date(message: Message, day: str, at: str, reference: datetime, lang: str,
          sent_title: str) -> None:
    """Fill in `when`, or `heading` as the thing to ask about."""
    when_day = parse_day(day, reference.date(), lang)
    when_time = parse_time(at)
    message.clock = when_time
    if when_day is None or when_time is None:
        # Only the day is unknown: ask for a day. Anything else: ask for the moment.
        message.heading = day if when_time is not None else f"{day} {at}".strip()
        return
    message.when = datetime.combine(when_day, when_time)
    message.date_conflict = _title_disagrees(sent_title, message.when)


def _within_caps(messages: list[Message]) -> list[Message]:
    """The newest messages that fit: at most MAX_MESSAGES and MAX_TOTAL_BYTES of text."""
    kept: list[Message] = []
    total = 0
    for message in reversed(messages):
        size = len(message.text.encode("utf-8"))
        if len(kept) >= MAX_MESSAGES or total + size > MAX_TOTAL_BYTES:
            break
        kept.append(message)
        total += size
    kept.reverse()
    return kept


# ------------------------------------------------------------------ direction

_PARENTHESES = re.compile(r"\([^)]*\)")  # "(He/Him)", should a page ever put it in the name


def _name_key(name: str) -> str:
    return fold(_PARENTHESES.sub(" ", name or ""))


def same_name(a: str, b: str) -> bool:
    """One person's name written twice: case, accents, spacing and pronouns aside."""
    key = _name_key(a)
    return bool(key) and key == _name_key(b)


def direction_for(marker: str, who: str, other_name: str, owner_name: str) -> str:
    """"in", "out", or "ask" when the page and the names do not agree.

    The page's own marker (`marker`, "in"/"out" as parse read it) is the primary
    signal. The sender's name is a second opinion: a wrong direction silently
    inverts "who is waiting on whom", so a disagreement, or a sender who is
    neither the other person nor you, is never imported until the person picks.
    Without a configured `owner_name` an own message cannot be checked and the
    marker stands.
    """
    if marker not in ("in", "out"):
        return "ask"
    if not _name_key(who):
        return marker
    if marker == "in":
        return "in" if same_name(who, other_name) or not _name_key(other_name) else "ask"
    if same_name(who, other_name):
        return "ask"
    if not _name_key(owner_name):
        return "out"
    return "out" if same_name(who, owner_name) else "ask"


def check_directions(thread: Thread, owner_name: str) -> Thread:
    """A copy of the thread with every message's direction cross-checked."""
    return replace(thread, messages=[
        replace(m, direction=direction_for(m.direction, m.who, thread.name, owner_name))
        for m in thread.messages])


# ------------------------------------------------------------------- matching


@dataclass
class Match:
    kind: str  # "profile", "name", "ambiguous" or "none"
    company: str = ""  # slugs; empty unless exactly one contact was found
    contact: str = ""
    candidates: list[tuple[str, str]] = field(default_factory=list)  # (company, contact)


def match(store: Store, thread: Thread) -> Match:
    """The contact a thread is with: by profile address, else by full name.

    LinkedIn's thread header links the member id (`/in/ACoAAA...`), which most
    saved contacts do not carry, so the page's own address is tried as well. Two
    people with one name, or two contacts with one address, are returned as
    candidates for the person to choose from, never settled by a guess.
    """
    everyone = [(company.slug, contact) for company in store.companies.values()
                for contact in company.contacts.values()]
    by_profile = sorted((slug, c.slug) for slug, c in everyone
                        if any(capture.same_profile(c.linkedin, url)
                               for url in thread.profile_urls))
    by_name = sorted((slug, c.slug) for slug, c in everyone
                     if same_name(c.name, thread.name))
    for kind, found in (("profile", by_profile), ("name", by_name)):
        if len(found) == 1:
            return Match(kind, found[0][0], found[0][1])
        if found:
            return Match("ambiguous", candidates=found)
    return Match("none")


# ------------------------------------------------------- plan and de-duplicate

LOOK_ALIKE_WINDOW = timedelta(hours=24)
FUTURE_GRACE = timedelta(days=1)  # a browser clock a little ahead of ours is not an error
LINKEDIN_FOUNDED = 2003  # an older date is a misread, not a message


@dataclass
class Row:
    index: int  # the message's place in the thread: what the review page's tick boxes name
    message: Message  # with the direction and date as they will be stored
    status: str  # "new", "logged", "maybe" (a look-alike), "ask" (direction) or "undated"
    message_id: str = ""
    existing: str = ""  # the interaction that makes it "logged" or "maybe"
    suspect: bool = False  # its date is probably wrong: in the future, or the page disagrees


@dataclass
class Plan:
    company: str
    contact: str
    thread: Thread
    rows: list[Row]
    stage_change: str = ""  # "prospect -> engaged" when importing would move the company
    outreach_sent: list[str] = field(default_factory=list)  # items it would mark sent

    @property
    def default_selection(self) -> list[int]:
        """What the review page ticks: the new messages, never a look-alike."""
        return [r.index for r in self.rows if r.status == "new"]


@dataclass
class Result:
    ids: list[str]  # the interactions written
    skipped: int = 0  # ticked, but already logged by the time of the write


def _loose(text: str) -> str:
    return " ".join((text or "").split())


def message_id_for(contact: str, message: Message) -> str:
    """The dedup key: LinkedIn's own id when the page has one, else a hash.

    The hash covers what makes two messages the same message to a person
    (who sent it, the minute, the words), not LinkedIn's markup.
    """
    if message.urn:
        return f"linkedin:{message.urn}"
    digest = hashlib.sha1(
        f"{message.direction}\n{message.when:%Y-%m-%dT%H:%M}\n{_loose(message.text)}"
        .encode("utf-8")).hexdigest()
    return f"linkedin:{contact}:{digest[:16]}"


def _answered(message: Message, dates: Mapping[str, date]) -> Message:
    """The person's answer for a heading the parser could not read, if given."""
    answer = dates.get(message.heading) if message.when is None else None
    if isinstance(answer, datetime):
        return replace(message, when=answer)
    if isinstance(answer, date) and message.clock is not None:
        return replace(message, when=datetime.combine(answer, message.clock))
    return message


def plan(store: Store, company_slug: str, contact_slug: str, thread: Thread, now: datetime,
         *, dates: Mapping[str, date] | None = None,
         directions: Mapping[int, str] | None = None, owner_name: str = "") -> Plan:
    """Say what importing `thread` into this contact would do, and write nothing.

    `dates` answers the headings in `thread.needs_date`; `directions` is the
    person's pick or flip per message index. Both come from the review page.
    """
    company = store.get(company_slug, refresh=True)
    if company is None:
        raise ConversationError(f"unknown company {company_slug!r}")
    if contact_slug not in company.contacts:
        raise ConversationError(f"unknown contact {contact_slug!r} for {company_slug!r}")
    logged = {i.message_id: i.id for i in company.interactions
              if i.contact == contact_slug and i.message_id}
    by_hand = [i for i in company.interactions
               if i.contact == contact_slug and i.channel == Channel.LINKEDIN.value
               and i.source != InteractionSource.LINKEDIN_IMPORT.value and i.date]
    rows = []
    for index, message in enumerate(check_directions(thread, owner_name).messages):
        message = _answered(message, dates or {})
        if (directions or {}).get(index) in ("in", "out"):
            message = replace(message, direction=directions[index])
        rows.append(_row(index, message, contact_slug, logged, by_hand, now))
    result = Plan(company_slug, contact_slug, thread, rows)
    fresh = result.default_selection
    entry, target = store.stages.entry, store.stages.advance_target
    if fresh and target and company.stage == entry:
        result.stage_change = f"{entry} -> {target}"
    outgoing = [r.message.when for r in rows if r.status == "new" and r.message.direction == "out"]
    if outgoing:
        from . import outreach  # imports the store; the module itself must not need it
        probe = Interaction(id="", date=max(outgoing), channel=Channel.LINKEDIN.value,
                            direction="out", contact=contact_slug)
        result.outreach_sent = [i.id for i in
                                outreach.sent_by_interaction(store.root, company_slug, probe)]
    return result


def _row(index: int, message: Message, contact: str, logged: dict[str, str],
         by_hand: list[Interaction], now: datetime) -> Row:
    by_urn = f"linkedin:{message.urn}" if message.urn else ""
    if by_urn in logged:  # LinkedIn's id needs neither a date nor a direction
        return Row(index, message, "logged", by_urn, logged[by_urn])
    if message.when is None:
        return Row(index, message, "undated", by_urn)
    suspect = (message.date_conflict or message.when > now + FUTURE_GRACE
               or message.when.year < LINKEDIN_FOUNDED)
    if message.direction not in ("in", "out"):
        return Row(index, message, "ask", by_urn, suspect=suspect)
    message_id = message_id_for(contact, message)
    if message_id in logged:
        return Row(index, message, "logged", message_id, logged[message_id], suspect)
    text = _loose(message.text)
    for i in by_hand:
        if (i.direction == message.direction and _loose(i.body) == text
                and abs(i.date - message.when) <= LOOK_ALIKE_WINDOW):
            return Row(index, message, "maybe", message_id, i.id, suspect)
    return Row(index, message, "new", message_id, suspect=suspect)


# ---------------------------------------------------------------------- apply


def apply(store: Store, plan: Plan, selected: Collection[int]) -> Result:
    """Log the ticked messages as `linkedin` interactions, in one commit.

    A tick on a message that is already logged (a second click, a second tab) is
    skipped, not written again. A tick on one that still needs a date or a
    direction is refused: it is never guessed.
    """
    rows = {r.index: r for r in plan.rows}
    chosen = sorted(set(selected))
    for n in chosen:
        if n not in rows:
            raise ConversationError(f"no such row: {n}")
    for n in chosen:
        if rows[n].status == "undated":
            raise ConversationError(f"message {n + 1} has no date yet: give it one first")
        if rows[n].status == "ask":
            raise ConversationError(f"message {n + 1} needs a direction first")
    company = store.get(plan.company, refresh=True)
    if company is None:
        raise ConversationError(f"unknown company {plan.company!r}")
    logged = {i.message_id for i in company.interactions
              if i.contact == plan.contact and i.message_id}
    todo = [rows[n] for n in chosen if rows[n].status != "logged"
            and rows[n].message_id not in logged]
    skipped = len(chosen) - len(todo)
    if not todo:
        return Result([], skipped)
    ids: list[str] = []
    stage = company.stage
    with store.batch("interaction: linkedin import") as commit:
        for row in todo:
            ids.append(store.create_interaction(
                plan.company, Channel.LINKEDIN.value, row.message.direction,
                contact=plan.contact, date=row.message.when, body=row.message.text,
                source=InteractionSource.LINKEDIN_IMPORT.value,
                message_id=row.message_id).id)
        noun = "message" if len(ids) == 1 else "messages"
        commit["message"] = (f"interaction: {plan.company} linkedin import "
                             f"{plan.contact} ({len(ids)} {noun})")
        moved = store.get(plan.company).stage
        if moved != stage:
            commit["message"] += f"; stage {stage} -> {moved}"
    return Result(ids, skipped)
