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

"""The queue behind scheduled email (spec part 08): schedule, unschedule, retry,
move to the front, pause, and the worker tick `hermitcrm send due`.

    ready ──schedule──> queued ──tick──> sent        unschedule / a guard ──> ready
                         (send_at)                    failed ──retry──> ready

`sendplan` decides when, `send` does the sending; this module is the glue that
reads and writes items, so the page, the CLI and the launchd job all do exactly
the same things. A queue change rewrites the `send_at` values that changed in
one commit.

The worker runs every few minutes (launchd or a systemd timer), so it is cheap
when there is nothing to do: it looks at the queued items first and opens the
store (every company) only when one is due. One send per tick, whatever is
overdue: a Mac that slept for two hours re-plans, it does not catch up in a burst.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import outreach, send, sendplan, setup, suppress
from .models import normalise_email
from .store import Store, load_config

MAX_PER_TICK = 1
GIT_WAIT_SECONDS = 5.0
SCAN_EVERY_MINUTES = 30       # the delivery-report scan runs at most this often
SCAN_FIRST_DAYS = 14          # how far back the very first scan looks
SENT_RECENTLY_DAYS = 3        # no scan when nothing was sent for this long and nothing is queued


# --------------------------------------------------------------- store, git


def wait_for_git(root: Path | str, seconds: float = GIT_WAIT_SECONDS) -> bool:
    """Wait for another git process (the web app, the daily sync) to let go of
    the index; True when it is free. A lock left by a crash is not ours to remove."""
    lock = Path(root) / ".git" / "index.lock"
    deadline = time.monotonic() + seconds
    while lock.exists():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)
    return True


def open_store(root: Path | str, config: dict | None = None) -> tuple[Store, "Pusher"]:
    """The store the way the CLI opens it, committing through the same write path,
    waiting for a held index.lock first. The pusher pushes once, after the tick."""
    from . import cli, pipeline
    from .gitops import GitOps

    config = config if config is not None else load_config(root)
    store = cli.build_store(Path(root))
    git = GitOps(root, push_enabled=bool(config.get("push_enabled", True)),
                 remote=config.get("remote", "origin"))
    pusher = Pusher(git)

    def on_write(message: str) -> None:
        paths = store.take_touched()
        pipeline.write(store)
        wait_for_git(root)
        if git.commit(message, [*paths, "PIPELINE.md"]):
            pusher.dirty = True

    store.on_write = on_write
    return store, pusher


@dataclass
class Pusher:
    git: object
    dirty: bool = False

    def push(self) -> None:
        """One push for everything the tick committed, in the foreground: the
        process ends right after, and a background thread would not finish."""
        if self.dirty and self.git.push_enabled and self.git.has_remote():
            self.git.push_sync()
        self.dirty = False


# ------------------------------------------------------------------- queue


def queued_items(root: Path | str) -> list:
    """Queued items by when they go out (those without a time last)."""
    rows = [i for i in outreach.items(root) if i.state == "queued"]
    return sorted(rows, key=lambda i: (i.send_at is None, i.send_at or datetime.max,
                                       i.queued or datetime.min, i.id))


def _slot(store: Store, item, send_at) -> sendplan.Slot:
    return sendplan.Slot(id=item.id, company=item.company, domain=send._domain(
        _contact_email(store, item)), follow_up=outreach.in_thread(item.kind),
        queued=item.queued or datetime.min, send_at=send_at)


def _contact_email(store: Store, item) -> str:
    company = store.get(item.company)
    contact = company.contacts.get(item.contact) if company is not None else None
    return contact.email if contact is not None else ""


def replan(store: Store, settings: send.SendSettings, now: datetime, *, front: str = "",
           everything: bool = False, write: bool = True,
           message: str = "") -> dict[str, datetime]:
    """Give every queued item a time. By default an item keeps the time it was shown
    unless it is overdue or outside the window; `everything` re-plans all of them,
    `front` puts one item first. Returns {id: send_at} for the whole queue and,
    with `write`, saves the ones that changed in one commit."""
    queue = [i for i in outreach.items(store.root) if i.state == "queued"]
    slots = []
    for item in queue:
        keep = None if everything or item.id == front else item.send_at
        slot = _slot(store, item, keep)
        if item.id == front:
            slot = sendplan.Slot(slot.id, slot.company, slot.domain, True, datetime.min, None)
        slots.append(slot)
    times = sendplan.plan(slots, send.sent_history(store), now, settings.plan)
    if not write:
        return times
    changed = []
    for item in queue:
        new = times.get(item.id)
        if new != item.send_at:
            item.send_at = new
            changed.append(item)
    if changed:
        text = message or (f"outreach: plan {len(changed)} send time"
                           f"{'s' if len(changed) != 1 else ''}")
        with store.lock:
            for item in changed:
                outreach.write_item(store.root, item)
            store.notify(text, [i.path for i in changed])
    return times


@dataclass
class ScheduleResult:
    scheduled: list = field(default_factory=list)       # items (queued, with send_at)
    refused: dict = field(default_factory=dict)         # item id -> why not
    times: dict = field(default_factory=dict)           # item id -> send_at
    dry_run: bool = False

    def lines(self, store: Store | None = None) -> list[str]:
        out = []
        for item in self.scheduled:
            at = self.times.get(item.id)
            out.append(f"{item.id} | {at:%a %d %b %H:%M}" if at else
                       f"{item.id} | no free slot in {sendplan.HORIZON_DAYS} days")
        out += [f"{i} | not scheduled: {why}" for i, why in self.refused.items()]
        return out


def _schedulable(store: Store, item, settings: send.SendSettings, config: dict) -> str:
    if item.state != "ready":
        return f"it is {item.state}; only a ready item can be scheduled"
    if item.channel != "email":
        return "only email is scheduled (LinkedIn is a session)"
    why = send.local_hold(store, item, settings, scheduled=False, config=config)
    return why or send.opt_out_problem(store, item)


def schedule(store: Store, item_ids, settings: send.SendSettings | None = None,
             now: datetime | None = None, *, dry_run: bool = False) -> ScheduleResult:
    """Approved items into the queue, with a time each. What cannot be scheduled is
    listed with the reason and left alone. One commit; `dry_run` writes nothing and
    shows the times."""
    config = load_config(store.root)
    settings = settings or send.settings_from_config(config)
    now = now or store.now()
    if not settings.enabled:
        raise outreach.OutreachError("sending is off: turn it on in Settings > Sending")
    if settings.missing:
        raise outreach.OutreachError(settings.missing)
    result = ScheduleResult(dry_run=dry_run)
    taken = []
    for item_id in item_ids:
        item = outreach.get_item(store.root, item_id)
        if item is None:
            result.refused[item_id] = "no such outreach item"
            continue
        try:
            why = _schedulable(store, item, settings, config)
        except send.SendError as err:
            why = err.text
        if why:
            result.refused[item_id] = why
            continue
        item.state, item.queued, item.send_at = "queued", now, None
        item.send_hash = send.text_hash(item.subject, item.body)
        item.send_note = item.send_error = ""
        taken.append(item)
    if not taken:
        return result
    if dry_run:
        slots = [_slot(store, i, None) for i in taken]
        mine = {i.id for i in taken}
        slots += [_slot(store, i, i.send_at) for i in outreach.items(store.root)
                  if i.state == "queued" and i.id not in mine]
        result.times = {k: v for k, v in sendplan.plan(slots, send.sent_history(store), now,
                                                       settings.plan).items() if k in mine}
        for item in taken:
            item.send_at = result.times.get(item.id)
        result.scheduled = taken
        return result
    with store.lock:
        for item in taken:
            outreach.write_item(store.root, item)
        store.notify(f"outreach: schedule {len(taken)} email{'s' if len(taken) != 1 else ''}",
                     [i.path for i in taken])
    times = replan(store, settings, now, message="outreach: plan send times")
    result.times = {i.id: times.get(i.id) for i in taken}
    result.scheduled = [outreach.get_item(store.root, i.id) for i in taken]
    return result


def schedule_all_ready(store: Store, settings: send.SendSettings | None = None,
                       now: datetime | None = None, *, dry_run: bool = False) -> ScheduleResult:
    """Every ready email item, oldest approval first."""
    ready = sorted((i for i in outreach.items(store.root)
                    if i.state == "ready" and i.channel == "email"),
                   key=lambda i: (i.ready or datetime.min, i.id))
    return schedule(store, [i.id for i in ready], settings, now, dry_run=dry_run)


def unschedule(store: Store, item_id: str, now: datetime | None = None) -> outreach.Item:
    """Back to ready, nothing else touched. The others keep their times: a gap in
    the plan is harmless, and moving them would change what the page showed."""
    item = outreach._refresh(store, item_id)
    if item.state != "queued":
        raise outreach.OutreachError(f"{item.id} is {item.state}; only a queued item can "
                                     "be unscheduled")
    item.state, item.send_note = "ready", "unscheduled"
    item.queued = item.send_at = None
    item.send_hash = ""
    with store.lock:
        outreach.write_item(store.root, item)
        store.notify(f"outreach: unschedule {item.record}", [item.path])
    return item


def retry(store: Store, item_id: str) -> outreach.Item:
    """A failed item back to ready, to schedule or send again."""
    item = outreach._refresh(store, item_id)
    if item.state != "failed":
        raise outreach.OutreachError(f"{item.id} is {item.state}; only a failed item can "
                                     "be retried")
    # The Message-ID stays: it is how a later send knows to ask Sent first.
    item.state, item.send_note, item.send_error = "ready", "retry", ""
    item.send_tries = 0
    with store.lock:
        outreach.write_item(store.root, item)
        store.notify(f"outreach: retry {item.record}", [item.path])
    return item


def move_to_front(store: Store, item_id: str, settings: send.SendSettings | None = None,
                  now: datetime | None = None) -> outreach.Item:
    """Make this the next to go out; every other queued item moves one slot later
    (the whole queue is planned again, with this one first)."""
    settings = settings or send.settings_from_config(load_config(store.root))
    item = outreach._refresh(store, item_id)
    if item.state != "queued":
        raise outreach.OutreachError(f"{item.id} is {item.state}; only a queued item can "
                                     "be moved")
    replan(store, settings, now or store.now(), front=item.id, everything=True,
           message=f"outreach: {item.record} to the front of the queue")
    return outreach._refresh(store, item_id)


# ------------------------------------------------------------ pause, resume


def pause(store: Store, root: Path | str | None = None) -> None:
    """The kill switch: `send_paused = true`, committed. Effective from the next tick."""
    _set_paused(store, True)


def resume(store: Store) -> list[str]:
    """Lift both pauses: the button and any automatic one (login, quota, bounces).
    Returns what was lifted, for the message."""
    lifted = []
    if load_config(store.root).get("send_paused"):
        _set_paused(store, False)
        lifted.append("the Pause button")
    state = send.SendState.load(store.root)
    if state.paused:
        lifted.append(state.message or f"the {state.kind} pause")
        state.resume()
    return lifted


def _set_paused(store: Store, value: bool) -> None:
    setup.set_config_values(Path(store.root) / "config.toml", {"send_paused": value})
    setup.commit_config(store.root, store.notify)


# ------------------------------------------------------------------ status


def status(store: Store, settings: send.SendSettings, now: datetime | None = None) -> dict:
    """What the strip on the Outreach page and `send status` show."""
    now = now or store.now()
    state = send.SendState.load(store.root)
    history = send.sent_history(store)
    count, cap = send.cap_status(store, settings, now, history)
    queue = queued_items(store.root)
    timed = [i.send_at for i in queue if i.send_at is not None]
    paused_by = ("the Pause button" if settings.paused else
                 state.message if state.is_paused(now) else "")
    overdue = [i for i in queue if i.send_at is not None
               and i.send_at <= now - timedelta(minutes=settings.overdue)]
    return {"enabled": settings.enabled, "paused": bool(paused_by), "paused_by": paused_by,
            "pause_kind": "manual" if settings.paused else state.kind,
            "missing": settings.missing, "sent_today": count, "cap": cap,
            "queued": len(queue), "overdue": len(overdue),
            "next": min((t for t in timed if t >= now), default=None),
            "last_sent": history[-1].when if history else None,
            "window": f"{settings.window[0] // 60:02d}:{settings.window[0] % 60:02d}-"
                      f"{settings.window[1] // 60:02d}:{settings.window[1] % 60:02d}",
            "days": ", ".join(sendplan.WEEKDAYS[d].capitalize() for d in settings.days),
            "problems": list(settings.problems)}


def strip_line(info: dict) -> str:
    """'Email: on · 23/35 today · next 10:42 · 08:30-17:30 · [Pause]' as text."""
    if not info["enabled"]:
        return "Email sending: off"
    head = "paused: " + info["paused_by"] if info["paused"] else "on"
    nxt = f" · next {info['next']:%a %H:%M}" if info["next"] and not info["paused"] else ""
    return (f"Email: {head} · {info['sent_today']}/{info['cap']} today · "
            f"{info['queued']} queued{nxt} · {info['days']} {info['window']}")


# ------------------------------------------------- bounces and opt-outs (M3)


def _when(item) -> datetime:
    return item.sent or item.queued or item.ready or datetime.min


def bounce_counts(root: Path | str) -> tuple[int, int]:
    """(sends, bounces) over the last BOUNCE_WINDOW mails the app sent: a bounce is a
    sent (or refused) mail whose address went on the list as bounced."""
    mine = [i for i in outreach.items(root) if i.message_id and i.state in ("sent", "failed")]
    last = sorted(mine, key=_when, reverse=True)[:suppress.BOUNCE_WINDOW]
    try:
        bounced = {e.item for e in suppress.load(root) if e.reason == "bounced" and e.item}
    except suppress.SuppressError:
        bounced = set()
    return len(last), sum(1 for i in last if i.id in bounced)


def _owner_of(store: Store, address: str):
    """(company slug, contact slug) of whoever has this address, or None."""
    for company in store.companies.values():
        for contact in company.contacts.values():
            if send.normalise_email(contact.email) == address:
                return company.slug, contact.slug
    return None


def apply_bounce(store: Store, bounce: suppress.Bounce, now: datetime) -> str:
    """One hard bounce: the address on the suppression list, a note on the contact's
    timeline, the item flagged, in one commit. '' when the address was already on
    the list (a report read twice changes nothing)."""
    if suppress.is_suppressed(store.root, bounce.address):
        return ""
    every = outreach.items(store.root)
    item = next((i for i in every if bounce.message_id and i.message_id == bounce.message_id),
                None)
    owner = (item.company, item.contact) if item is not None else _owner_of(store, bounce.address)
    if item is None and owner is not None:
        mine = [i for i in every if (i.company, i.contact) == owner and i.message_id]
        item = max(mine, key=_when, default=None)
    why = f"{bounce.status} {bounce.reason}".strip()
    message = f"outreach: {bounce.address} bounced ({bounce.status})"
    with store.batch(message):
        suppress.add(store.root, bounce.address, "bounced", now.strftime("%Y-%m-%d"),
                     item.id if item is not None else "")
        paths = [suppress.FILE]
        if item is not None:
            item.send_note = f"bounced: {why}"[:300]
            outreach.write_item(store.root, item)
            paths.append(item.path)
        store.notify(message, paths)
        if owner is not None:
            store.create_interaction(
                owner[0], "note", "", contact=owner[1], date=now, source="outreach",
                body=f"The email to {bounce.address} bounced ({why}). The address is on the "
                     "suppression list: nothing more is sent to it.\n")
    return f"{bounce.address} bounced ({why})"


def scan_bounces(store: Store, settings: send.SendSettings, state: send.SendState,
                 now: datetime, imap_factory=None, password: str | None = None) -> list[str]:
    """Read the delivery reports that came in since the last scan, suppress what bounced
    and pause sending when too many did. Raises send.SendError when the mailbox cannot
    be read; the scan time moves only after a scan that worked."""
    since = (datetime.strptime(state.bounce_scan, "%Y-%m-%dT%H:%M") - timedelta(days=1)
             if state.bounce_scan else now - timedelta(days=SCAN_FIRST_DAYS)).date()
    pw = password or send.get_password(settings, store.root)
    with send.Mailbox(settings, pw, imap_factory) as box:
        raws = box.reports_since(since)
    lines = []
    for raw in raws:
        for bounce in suppress.parse_dsn(raw):
            done = apply_bounce(store, bounce, now)
            if done:
                lines.append(done)
    state.mark_scan(now)
    sends, bounced = bounce_counts(store.root)
    if suppress.bounce_pause(sends, bounced):
        text = (f"{bounced} of the last {sends} emails bounced (more than {suppress.BOUNCE_MAX}, "
                f"or over {suppress.BOUNCE_RATE:.0%}). That is a list-quality problem: check "
                "where the addresses came from")
        state.pause("bounces", text, now)
        lines.append("paused: " + text)
    return lines


def opt_out(store: Store, company: str, contact: str, now: datetime | None = None) -> str:
    """They asked not to be written to: the address on the suppression list, every open
    outreach item for them skipped, a note on the timeline; one commit. The planner never
    schedules a suppressed address and the worker never sends to one."""
    now = now or store.now()
    found = store.get(company)
    person = found.contacts.get(contact) if found is not None else None
    if person is None:
        raise outreach.OutreachError(f"no contact {company}/{contact}")
    address = send.normalise_email(person.email)
    if not send.valid_email(address):
        raise outreach.OutreachError(f"{person.name} has no email address to put on the list")
    open_items = [i for i in outreach.items(store.root)
                  if i.company == company and i.contact == contact and i.is_open]
    message = f"outreach: {person.name} opted out"
    with store.batch(message):
        suppress.add(store.root, address, "opted-out", now.strftime("%Y-%m-%d"))
        paths = [suppress.FILE]
        for item in open_items:
            item.state, item.skip_reason, item.skipped = "skipped", "other", now
            item.skip_note = "opted out"
            item.queued = item.send_at = None
            outreach.write_item(store.root, item)
            paths.append(item.path)
        store.notify(message, paths)
        store.create_interaction(
            company, "note", "", contact=contact, date=now, source="outreach",
            body=f"{person.name} opted out. {address} is on the suppression list"
                 + (f" and {len(open_items)} open outreach item"
                    f"{'s' if len(open_items) != 1 else ''} skipped" if open_items else "")
                 + ": nothing more is written to them.\n")
    return (f"{person.name} opted out: {address} is on the suppression list"
            + (f", {len(open_items)} open item{'s' if len(open_items) != 1 else ''} skipped"
               if open_items else "") + ".")


# ------------------------------------------------------------------ worker


def due(root: Path | str, *, now: datetime | None = None, dry_run: bool = False,
        smtp_factory=None, imap_factory=None, password: str | None = None,
        store: Store | None = None) -> list[str]:
    """One tick of `hermitcrm send due`: returns the report lines. At most one
    mail per tick. `dry_run` writes and sends nothing and says what it would do."""
    root = Path(root)
    now = now or datetime.now().replace(second=0, microsecond=0)
    config = load_config(root)
    settings = send.settings_from_config(config)
    if not settings.enabled:
        return ["sending is off (Settings > Sending)"]
    if settings.paused:
        return ["paused: the Pause button is on"]
    state = send.SendState.load(root)
    if state.is_paused(now):
        return [f"paused ({state.kind}): {state.message}"]
    if settings.missing:
        return [settings.missing]
    queue = queued_items(root)
    soon = [i for i in queue if i.send_at is None or i.send_at <= now]
    scan = _scan_due(root, settings, state, queue, now)
    if not soon and not scan:
        if not queue:
            return ["nothing queued"]
        return [f"nothing due; next at {queue[0].send_at:%a %d %b %H:%M} ({len(queue)} queued)"]
    try:
        with send.SendLock(root):
            owned = store is None
            pusher = None
            if owned:
                store, pusher = open_store(root, config)
            try:
                lines = []
                if scan:
                    lines += (["would read the sending mailbox for delivery reports"]
                              if dry_run else _scan(store, settings, state, now, imap_factory,
                                                    password))
                    if not dry_run and state.is_paused(now):
                        return lines + [f"paused ({state.kind}): {state.message}"]
                if soon:
                    lines += _tick(store, settings, config, state, now, dry_run, smtp_factory,
                                   imap_factory, password)
                elif not queue:
                    lines.append("nothing queued")
            finally:
                if owned and pusher is not None:
                    pusher.push()
            return lines
    except send.SendBusy:
        return ["another send is running; this tick does nothing"]


def _scan_due(root: Path, settings: send.SendSettings, state: send.SendState, queue: list,
              now: datetime) -> bool:
    """Is it time to read the delivery reports? Not more often than every half hour, and
    only while something is queued or went out in the last few days."""
    if not settings.imap_host:
        return False
    if state.bounce_scan:
        try:
            last = datetime.strptime(state.bounce_scan, "%Y-%m-%dT%H:%M")
        except ValueError:
            last = datetime.min
        if now - last < timedelta(minutes=SCAN_EVERY_MINUTES):
            return False
    if queue:
        return True
    cutoff = now - timedelta(days=SENT_RECENTLY_DAYS)
    return any(i.state == "sent" and i.message_id and i.sent and i.sent >= cutoff
               for i in outreach.items(root))


def _scan(store: Store, settings: send.SendSettings, state: send.SendState, now: datetime,
          imap_factory, password) -> list[str]:
    try:
        return scan_bounces(store, settings, state, now, imap_factory, password)
    except send.SendError as err:
        if err.kind in (send.AUTH, send.REFUSED):
            state.pause(err.kind, err.text, now)
            return [f"paused: {err.text}"]
        return [f"could not read delivery reports ({err.text}); trying again next time"]


def _tick(store: Store, settings: send.SendSettings, config: dict, state: send.SendState,
          now: datetime, dry_run: bool, smtp_factory, imap_factory, password) -> list[str]:
    lines: list[str] = []
    late = [i for i in queued_items(store.root)
            if i.send_at is None or i.send_at <= now - timedelta(minutes=settings.overdue)]
    if late:
        times = replan(store, settings, now, write=not dry_run)
        moved = ", ".join(f"{k}: {times[k]:%a %H:%M}" for k in sorted(times)
                          if k in {i.id for i in late} and k in times)
        lines.append(f"{len(late)} overdue; {'would plan' if dry_run else 'planned'} again"
                     + (f" ({moved})" if moved else ""))
    queue = queued_items(store.root)
    due_now = [i for i in queue if i.send_at is not None and i.send_at <= now]
    if not due_now:
        return lines + ["nothing due after planning"]
    if not sendplan.in_window(now, settings.plan):
        return lines + ["outside the sending window; waiting"]
    history = send.sent_history(store)
    count, cap = send.cap_status(store, settings, now, history)
    if count >= cap:
        return lines + [f"today's cap of {cap} is reached ({count} sent); waiting"]
    if history and now - history[-1].when < timedelta(minutes=settings.min_gap):
        return lines + [f"the last send was less than {settings.min_gap} minutes ago; waiting"]
    for item in due_now[:MAX_PER_TICK]:
        if dry_run:
            try:
                why = send.local_hold(store, item, settings, scheduled=True, config=config)
            except send.SendError as err:
                why = err.text
            lines.append(f"would send {item.id}" if not why else
                         f"would hold {item.id}: {why}")
            continue
        out = send.deliver(store, item.id, settings=settings, now=now, scheduled=True,
                           smtp_factory=smtp_factory, imap_factory=imap_factory,
                           password=password, config=config, state=state)
        lines.append(f"{out.kind}: {item.id}" + (f" ({out.detail})" if out.detail else ""))
    return lines
