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

"""The LinkedIn session (spec part 08, option A): one approved touch at a time in
front of the person, who sends it on linkedin.com themselves.

LinkedIn's User Agreement (8.2) forbids automated sending, and an account that is
restricted loses the channel for good. So nothing here talks to LinkedIn: no
request, no browser, no extension. The page copies the text, opens the contact's
profile in a new tab and waits; the person clicks Connect, Add a note, pastes and
Send, then comes back and says what happened. Hermit does what a machine is good
at: it paces the person (a countdown between cards, a session of ten, a break
between sessions), keeps the caps (invites a day and over a rolling week, messages
a day) and logs every touch with its exact text.

    ready note ──Sent──> sent (invite_sent) ──Accepted──> pitch card ──Sent──> pitch_sent
        └──Already connected──> pitch card

The queue is: answers and follow-ups to people you already talk to, then
connection notes, then pitches to people who accepted. An item becomes `sent` with
its first message out, so cooldowns and the Messages statistics work as they do
for email; `accepted` and `pitch_sent` track the second step on the same item.
Realistic volume is about 20 invites and 30-40 messages a day: 50-100 invites a day
is not available by any method.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import outreach
from .send import runtime_dir
from .store import Store

STATE_FILE = "hermitcrm-linkedin.json"
WAITING_REMINDER_DAYS = 21     # a pending invite older than this gets a "withdraw it?"
REASONS = ("profile-gone", "other", "weekly-limit")
NOTE_KIND, PITCH_KIND, MESSAGE_KIND = "note", "pitch", "message"
KIND_LABELS = {NOTE_KIND: "connection note", PITCH_KIND: "message after they accepted",
               MESSAGE_KIND: "message"}


# ---------------------------------------------------------------- settings


@dataclass(frozen=True)
class LinkedInSettings:
    invites_per_day: int = 20
    invites_per_week: int = 80
    messages_per_day: int = 40
    session_size: int = 10
    gap: tuple = (45, 120)               # seconds between two cards
    break_minutes: int = 120             # between two sessions


def _int(config: dict, key: str, default: int, low: int = 1) -> int:
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value >= low else default


def settings_from_config(config: dict) -> LinkedInSettings:
    c = config or {}
    d = LinkedInSettings()
    raw = c.get("linkedin_gap_seconds")
    try:
        low, high = sorted(int(x) for x in raw)[:2] if isinstance(raw, list) and len(raw) >= 2 \
            else d.gap
        gap = (max(low, 1), max(high, low, 1))
    except (TypeError, ValueError):
        gap = d.gap
    return LinkedInSettings(
        invites_per_day=_int(c, "linkedin_invites_per_day", d.invites_per_day),
        invites_per_week=_int(c, "linkedin_invites_per_week", d.invites_per_week),
        messages_per_day=_int(c, "linkedin_messages_per_day", d.messages_per_day),
        session_size=_int(c, "linkedin_session_size", d.session_size),
        gap=gap, break_minutes=_int(c, "linkedin_session_break_minutes", d.break_minutes, 0))


def countdown(item_id: str, cfg: LinkedInSettings) -> int:
    """Seconds before the next card unlocks: seeded by the item just done, so the
    page and the tests agree, and it is not the same pause every time."""
    digest = hashlib.sha256(str(item_id).encode("utf-8")).digest()
    fraction = int.from_bytes(digest[:8], "big") / 2 ** 64
    return cfg.gap[0] + int(round((cfg.gap[1] - cfg.gap[0]) * fraction))


# ----------------------------------------------------------------- the state


def _stamp(when: datetime | None) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%S") if when else ""


def _parse(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S") if text else None
    except ValueError:
        return None


@dataclass
class Session:
    """Where the person is: kept in .git/hermitcrm-linkedin.json, never committed."""

    root: Path
    started: datetime | None = None
    ended: datetime | None = None
    count: int = 0                         # touches sent this session
    handled: list = field(default_factory=list)   # "<item>:<kind>" done or passed this session
    unlock: datetime | None = None         # the next card shows at this time
    block_count: int = 0                   # LinkedIn refused invites at this weekly count...
    block_at: datetime | None = None       # ...at this time

    @property
    def path(self) -> Path:
        return runtime_dir(self.root) / STATE_FILE

    @classmethod
    def load(cls, root: Path | str) -> "Session":
        s = cls(root=Path(root))
        try:
            data = json.loads(s.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError
        except (OSError, ValueError):
            return s
        s.started, s.ended = _parse(data.get("started", "")), _parse(data.get("ended", ""))
        s.unlock, s.block_at = _parse(data.get("unlock", "")), _parse(data.get("block_at", ""))
        s.count = int(data.get("count") or 0)
        s.block_count = int(data.get("block_count") or 0)
        s.handled = [str(x) for x in data.get("handled") or []]
        return s

    def save(self) -> None:
        self.path.write_text(json.dumps({
            "started": _stamp(self.started), "ended": _stamp(self.ended), "count": self.count,
            "handled": self.handled, "unlock": _stamp(self.unlock),
            "block_count": self.block_count, "block_at": _stamp(self.block_at)},
            indent=1, sort_keys=True) + "\n", encoding="utf-8")

    @property
    def active(self) -> bool:
        return self.started is not None and self.ended is None

    def finish(self, now: datetime) -> None:
        self.ended = now
        self.save()


# ------------------------------------------------------------------ counters


@dataclass
class Counters:
    invites_today: int
    invites_week: int
    messages_today: int
    session: int
    cfg: LinkedInSettings
    blocked: bool = False       # LinkedIn's own weekly limit message was seen recently

    @property
    def invites_left(self) -> int:
        if self.blocked:
            return 0
        return max(0, min(self.cfg.invites_per_day - self.invites_today,
                          self.cfg.invites_per_week - self.invites_week))

    @property
    def messages_left(self) -> int:
        return max(0, self.cfg.messages_per_day - self.messages_today)


def linkedin_items(root: Path | str) -> list:
    return [i for i in outreach.items(root) if i.channel == "linkedin"]


def counters(store: Store, now: datetime, cfg: LinkedInSettings, session: Session | None = None
             ) -> Counters:
    session = session or Session.load(store.root)
    items = linkedin_items(store.root)
    invites = [i.invite_sent for i in items if i.invite_sent is not None]
    today = now.date()
    week_ago = now - timedelta(days=7)
    invites_week = sum(1 for t in invites if t > week_ago)
    sent_today = 0
    for company in store.companies.values():
        for it in company.interactions:
            if (it.source == "outreach" and it.channel == "linkedin" and it.direction == "out"
                    and it.date is not None and it.date.date() == today):
                sent_today += 1
    invites_today = sum(1 for t in invites if t.date() == today)
    # LinkedIn's own "weekly limit" message: invites wait until our 7-day count drops below
    # what it was then. With nothing of ours to drop (the limit came from invites sent
    # elsewhere) they wait for the 7 days themselves.
    blocked = bool(session.block_at is not None and session.block_at > week_ago
                   and (session.block_count == 0 or invites_week >= session.block_count))
    return Counters(invites_today=invites_today, invites_week=invites_week,
                    messages_today=max(0, sent_today - invites_today),
                    session=session.count, cfg=cfg, blocked=blocked)


# --------------------------------------------------------------------- cards


@dataclass
class Card:
    item: outreach.Item
    kind: str                       # note | pitch | message
    text: str
    limit: int

    @property
    def label(self) -> str:
        return KIND_LABELS[self.kind]

    @property
    def length(self) -> int:
        return len(self.text.strip())


def _rules(root: Path | str) -> dict:
    from . import messaging
    return outreach.channel_rules("linkedin", messaging.load_messages(root))


def card_for(item, rules: dict) -> Card | None:
    """The card an item shows now, or None when it has nothing left to send here."""
    note_max = int(rules.get("note_max_chars", 300))
    pitch_max = int(rules.get("pitch_max_chars", 600))
    if item.state == "ready" and outreach.in_thread(item.kind) and item.body.strip():
        return Card(item, MESSAGE_KIND, item.body, pitch_max)
    if item.state == "ready" and item.accepted is None and item.invite_sent is None \
            and item.body.strip():
        return Card(item, NOTE_KIND, item.body, note_max)
    pitched = item.accepted is not None and item.pitch_sent is None and item.pitch.strip()
    if pitched and item.state in ("ready", "sent"):
        return Card(item, PITCH_KIND, item.pitch, pitch_max)
    return None


def queue(store: Store, now: datetime, session: Session | None = None) -> list[Card]:
    """Everything that could be shown, in order: answers to people you already talk
    to, then connection notes, then pitches to people who accepted; oldest first."""
    session = session or Session.load(store.root)
    rules = _rules(store.root)
    cards = [c for c in (card_for(i, rules) for i in linkedin_items(store.root)) if c]
    cards = [c for c in cards if f"{c.item.id}:{c.kind}" not in session.handled]
    order = {MESSAGE_KIND: 0, NOTE_KIND: 1, PITCH_KIND: 2}
    key = lambda c: (order[c.kind], c.item.accepted or c.item.ready or datetime.min, c.item.id)  # noqa: E731
    return sorted(cards, key=key)


@dataclass
class Next:
    card: Card | None
    reason: str = ""               # why there is none
    wait: int = 0                  # seconds until the next card unlocks


def next_card(store: Store, now: datetime, cfg: LinkedInSettings,
              session: Session | None = None) -> Next:
    session = session or Session.load(store.root)
    if not session.active:
        return Next(None, "no session is running")
    if session.count >= cfg.session_size:
        return Next(None, f"that is {cfg.session_size} touches: the session is done")
    cards = queue(store, now, session)
    if not cards:
        return Next(None, "nothing is waiting: approve more LinkedIn drafts, or mark who accepted")
    have = counters(store, now, cfg, session)
    for card in cards:
        if card.kind == NOTE_KIND and have.invites_left <= 0:
            continue
        if card.kind != NOTE_KIND and have.messages_left <= 0:
            continue
        wait = max(0, int((session.unlock - now).total_seconds())) if session.unlock else 0
        return Next(card, "", wait)
    if have.blocked:
        return Next(None, "LinkedIn's weekly invite limit was hit: invites wait until the "
                          "7-day count drops")
    notes_blocked = any(c.kind == NOTE_KIND for c in cards) and have.invites_left <= 0
    return Next(None, ("the invite cap is reached"
                       f" ({have.invites_today}/{cfg.invites_per_day} today, "
                       f"{have.invites_week}/{cfg.invites_per_week} this week)" if notes_blocked
                       else f"today's message cap is reached ({have.messages_today}/"
                            f"{cfg.messages_per_day})"))


def next_session_at(session: Session, cfg: LinkedInSettings) -> datetime | None:
    """When the next session may start: the break after the last one, or None now."""
    if session.ended is None:
        return None
    return session.ended + timedelta(minutes=cfg.break_minutes)


def can_start(session: Session, now: datetime, cfg: LinkedInSettings) -> tuple[bool, str]:
    if session.active:
        return False, "a session is running"
    at = next_session_at(session, cfg)
    if at is not None and now < at:
        return False, f"the next session can start at {at:%H:%M} (a break of {cfg.break_minutes} minutes)"
    return True, ""


# ------------------------------------------------------------------ actions


def start(store: Store, now: datetime, cfg: LinkedInSettings) -> Session:
    session = Session.load(store.root)
    ok, why = can_start(session, now, cfg)
    if not ok:
        raise outreach.OutreachError(f"No new session: {why}.")
    fresh = Session(root=session.root, started=now, unlock=now, block_count=session.block_count,
                    block_at=session.block_at)
    fresh.save()
    return fresh


def end(store: Store, now: datetime) -> Session:
    session = Session.load(store.root)
    if session.active:
        session.finish(now)
    return session


def _done(session: Session, item_id: str, kind: str, now: datetime, cfg: LinkedInSettings,
          sent: bool) -> None:
    session.handled.append(f"{item_id}:{kind}")
    if sent:
        session.count += 1
        session.unlock = now + timedelta(seconds=countdown(item_id, cfg))
    if session.count >= cfg.session_size:
        session.ended = now
    session.save()


def sent(store: Store, item_id: str, now: datetime, cfg: LinkedInSettings) -> outreach.Item:
    """You sent the card's text on LinkedIn: one outbound interaction with the exact
    text, `invite_sent` or `pitch_sent` set, and the item `sent`: one commit."""
    item = outreach._refresh(store, item_id)
    card = card_for(item, _rules(store.root))
    if card is None:
        raise outreach.OutreachError(f"{item.id} has nothing left to send on LinkedIn")
    message = f"outreach: sent {card.label} to {item.record} (linkedin)"
    with store.batch(message):
        store.create_interaction(item.company, "linkedin", "out", contact=item.contact,
                                 date=now, body=card.text, source="outreach",
                                 angle=item.angle, framework=item.framework,
                                 approach=item.approach)
        item = outreach._refresh(store, item_id)       # create_interaction may have flipped it
        if card.kind == NOTE_KIND:
            item.invite_sent = now
        elif card.kind == PITCH_KIND:
            item.pitch_sent = now
        if item.state != "sent":
            item.state, item.sent = "sent", now
        outreach.write_item(store.root, item)
        store.notify(message, [item.path])
    session = Session.load(store.root)
    _done(session, item_id, card.kind, now, cfg, sent=True)
    return outreach._refresh(store, item_id)


def already_connected(store: Store, item_id: str, now: datetime) -> outreach.Item:
    """The note is not needed: they are a connection already, so the card becomes the
    message that would have followed it."""
    item = outreach._refresh(store, item_id)
    if item.state != "ready" or item.accepted is not None or item.invite_sent is not None:
        raise outreach.OutreachError(f"{item.id} is not waiting for a connection note")
    if not item.pitch.strip():
        raise outreach.OutreachError(f"{item.id} has no message to send to a connection: "
                                     "skip it, or write one and mark it ready again")
    item.accepted = now
    message = f"outreach: {item.record} is already connected on LinkedIn"
    with store.lock:
        outreach.write_item(store.root, item)
        store.notify(message, [item.path])
    return item


def couldnt_send(store: Store, item_id: str, reason: str, note: str, now: datetime,
                 cfg: LinkedInSettings) -> str:
    """It could not be sent. `profile-gone` skips the item; `weekly-limit` is LinkedIn's
    own message that no more invites are possible, so invites wait until the 7-day
    count drops; `other` leaves it for another time. Returns what to tell the person."""
    if reason not in REASONS:
        raise outreach.OutreachError(f"say why: {', '.join(REASONS)}")
    item = outreach._refresh(store, item_id)
    session = Session.load(store.root)
    card = card_for(item, _rules(store.root))
    kind = card.kind if card is not None else "other"
    text = " ".join((note or "").split())[:200]
    if reason == "profile-gone":
        gone = "LinkedIn profile gone" + (f": {text}" if text else "")
        if item.is_open:
            outreach.skip(store, item_id, "other", gone)
        else:                                  # a pitch to someone who accepted: nothing to skip
            item.send_note = gone
            with store.lock:
                outreach.write_item(store.root, item)
                store.notify(f"outreach: {item.record} LinkedIn profile gone", [item.path])
        _done(session, item_id, kind, now, cfg, sent=False)
        return "Skipped: the profile is gone."
    item.send_note = (f"could not send on LinkedIn: {text}" if text else
                      "could not send on LinkedIn")
    if reason == "weekly-limit":
        have = counters(store, now, cfg, session)
        session.block_count, session.block_at = have.invites_week, now
        item.send_note = "LinkedIn said the weekly invite limit is reached"
    with store.lock:
        outreach.write_item(store.root, item)
        store.notify(f"outreach: could not send {item.record} on LinkedIn ({reason})", [item.path])
    _done(session, item_id, kind, now, cfg, sent=False)
    return ("Invites are paused until the 7-day count drops." if reason == "weekly-limit"
            else "Left for another time.")


def waiting(store: Store, now: datetime) -> list[dict]:
    """Invites sent and not yet accepted: {item, days, remind}."""
    out = []
    for item in linkedin_items(store.root):
        if (item.state == "sent" and item.invite_sent is not None and item.accepted is None
                and item.pitch_sent is None and item.send_note != "withdrawn"):
            days = (now - item.invite_sent).days
            out.append({"item": item, "days": days, "remind": days >= WAITING_REMINDER_DAYS})
    return sorted(out, key=lambda r: r["item"].invite_sent)


def accepted(store: Store, item_id: str, now: datetime) -> outreach.Item:
    """They accepted the invite: the item's pitch joins the session queue."""
    item = outreach._refresh(store, item_id)
    if (item.state != "sent" or item.invite_sent is None or item.accepted is not None
            or item.send_note == "withdrawn"):
        raise outreach.OutreachError(f"{item.id} is not a pending invite")
    item.accepted = now
    message = f"outreach: {item.record} accepted on LinkedIn"
    with store.lock:
        outreach.write_item(store.root, item)
        store.notify(message, [item.path])
    return item


def withdrawn(store: Store, item_id: str, now: datetime) -> outreach.Item:
    """You withdrew the pending invite on LinkedIn (many pending invites count against
    the account): it leaves the waiting list."""
    item = outreach._refresh(store, item_id)
    if (item.state != "sent" or item.invite_sent is None or item.accepted is not None
            or item.send_note == "withdrawn"):
        raise outreach.OutreachError(f"{item.id} is not a pending invite")
    item.send_note = "withdrawn"
    message = f"outreach: {item.record} invite withdrawn on LinkedIn"
    with store.lock:
        outreach.write_item(store.root, item)
        store.notify(message, [item.path])
    return item
