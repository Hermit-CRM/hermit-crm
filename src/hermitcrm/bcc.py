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

"""BCC import: log the mails you BCC (or forward) to the tracking address.

Standard library only (imaplib, email, html.parser); no AI, no credits. Once
a day launchd runs ``hermitcrm bcc --apply``; the Inbox page has an Import now
button. A Gmail filter marks the mails read the moment they arrive (see
README); the import marks everything it reads as read as well.

Per external address in a mail:
- an existing contact with that email: log the interaction there;
- else exactly one company whose website (or a contact's email) has that
  domain: create the contact, then log;
- else, for mail you sent or forwarded yourself (``bcc_create_companies``, on
  by default): create the company, named after the domain, then the contact,
  then log. Not for no-reply senders, nor when a company of that name exists;
- else: an item in inbox/ that you assign to a company in the review queue,
  which creates the company when the name you type is new.

Mails are never imported twice: the Message-ID is stored as ``message_id`` on
the interaction, on inbox items, and in inbox/discarded.tsv.
"""

from __future__ import annotations

import hashlib
import imaplib
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from email import message_from_bytes, policy
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlparse

from . import secrets
from .models import (
    ValidationError, fmt_datetime, normalise_email, normalise_website, slugify,
    split_name, unique_slug,
)
from .store import Store, build_file, normalise_body, split_file

logger = logging.getLogger("crm.bcc")

DEFAULT_ADDRESS = ""
LAST_RUN_FILE = ".last-run.json"
DISCARDED_FILE = "discarded.tsv"
STALE_AFTER_DAYS = 2

# Senders that are a machine, not a person at a company: never a new company.
NO_REPLY = re.compile(r"^(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounces?"
                      r"|notifications?)\b")

# Personal mailboxes never identify a company by their domain.
FREEMAIL = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "msn.com", "yahoo.com", "icloud.com", "me.com", "mac.com", "aol.com",
    "proton.me", "protonmail.com", "gmx.de", "gmx.net", "gmx.at", "gmx.ch",
    "web.de", "t-online.de", "freenet.de", "posteo.de", "mailbox.org",
    "hotmail.fr", "orange.fr", "free.fr", "laposte.net", "wanadoo.fr",
    "ziggo.nl", "kpnmail.nl", "planet.nl", "home.nl", "xs4all.nl", "bluewin.ch",
}


class BccError(Exception):
    """A readable reason the import could not run (login, network, Keychain)."""


# ------------------------------------------------------------------ settings



# Where each common provider's mail lives, and how to get the app password
# every one of them wants instead of your normal password. `works` is honest
# about Microsoft: it switched off password sign-in for IMAP on most accounts,
# and no app password brings it back.
MAIL_PROVIDERS = {
    "gmail": {
        "label": "Gmail / Google Workspace",
        "imap_host": "imap.gmail.com",
        "password_url": "https://myaccount.google.com/apppasswords",
        "note": "Turn on 2-step verification first; the app password page is "
                "hidden until you do. A Workspace admin can switch IMAP off.",
        "works": True,
    },
    "icloud": {
        "label": "iCloud Mail",
        "imap_host": "imap.mail.me.com",
        "password_url": "https://account.apple.com",
        "note": "Sign-In and Security, then App-Specific Passwords. The IMAP user "
                "is your iCloud address.",
        "works": True,
    },
    "fastmail": {
        "label": "Fastmail",
        "imap_host": "imap.fastmail.com",
        "password_url": "",
        "note": "Settings, then Privacy & Security, then App passwords; give it "
                "IMAP access.",
        "works": True,
    },
    "outlook": {
        "label": "Outlook.com / Microsoft 365",
        "imap_host": "outlook.office365.com",
        "password_url": "",
        "note": "Microsoft has switched off password sign-in for IMAP on most "
                "accounts, so this usually fails however the password is made. "
                "What works: forward or BCC to a Gmail or Fastmail address kept "
                "for the purpose, and point Hermit CRM at that one.",
        "works": False,
    },
}

@dataclass
class Settings:
    address: str = DEFAULT_ADDRESS
    imap_user: str = ""
    imap_host: str = "imap.gmail.com"
    keychain_service: str = "crm-bcc"
    my_addresses: tuple[str, ...] = ()
    ignore_domains: tuple[str, ...] = ()
    lookback_days: int = 30
    create_companies: bool = True

    def __post_init__(self) -> None:
        self.address = normalise_email(self.address)
        if not self.imap_user and self.address:
            local, _, domain = self.address.partition("@")
            self.imap_user = f"{local.split('+')[0]}@{domain}"
        self.imap_user = normalise_email(self.imap_user)
        mine = {normalise_email(a) for a in self.my_addresses}
        mine |= {self.address, self.imap_user}
        self.my_addresses = tuple(sorted(m for m in mine if m))
        self.ignore_domains = tuple(sorted(
            {d.strip().lower().lstrip("@") for d in self.ignore_domains if d.strip()}))

    def is_me(self, address: str) -> bool:
        return normalise_email(address) in self.my_addresses

    def ignored(self, address: str) -> bool:
        return address.rpartition("@")[2] in self.ignore_domains


def settings_from_config(config: dict) -> Settings:
    return Settings(
        address=str(config.get("bcc_address", DEFAULT_ADDRESS)),
        imap_user=str(config.get("bcc_imap_user", "")),
        imap_host=str(config.get("bcc_imap_host", "imap.gmail.com")),
        keychain_service=str(config.get("bcc_keychain_service", "crm-bcc")),
        my_addresses=tuple(config.get("my_addresses", ())),
        ignore_domains=tuple(config.get("bcc_ignore_domains", ())),
        lookback_days=int(config.get("bcc_lookback_days", 30)),
        create_companies=bool(config.get("bcc_create_companies", True)),
    )


# ------------------------------------------------------------------- parsing


@dataclass
class Mail:
    message_id: str
    date: datetime
    sender: tuple[str, str]  # (display name, address)
    to: list[tuple[str, str]]
    cc: list[tuple[str, str]]
    subject: str
    text: str


def _local(dt: datetime) -> datetime:
    """Aware datetimes become naive local time, like every date in the store."""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.replace(second=0, microsecond=0)


def _addresses(values: Iterable[str]) -> list[tuple[str, str]]:
    out = []
    for name, addr in getaddresses([str(v) for v in values if v]):
        addr = normalise_email(addr)
        if "@" in addr:
            out.append((" ".join(name.replace("*", "").split()), addr))
    return out


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "tr", "li", "ul", "ol", "table", "blockquote",
             "h1", "h2", "h3", "h4", "h5", "h6", "hr"}
    SKIP = {"style", "script", "head", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "br" or tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")


def _mail_text(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError):
        content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    if part.get_content_type() == "text/html":
        content = html_to_text(content)
    return content.replace("\r\n", "\n").replace("\r", "\n")


def parse_mail(raw: bytes, now: datetime) -> Mail:
    msg = message_from_bytes(raw, policy=policy.default)
    message_id = str(msg.get("Message-ID") or "").strip()
    if not message_id:
        message_id = f"<{hashlib.sha1(raw).hexdigest()}@crm.local>"
    when = now
    if msg.get("Date"):
        try:
            when = _local(parsedate_to_datetime(str(msg["Date"])))
        except (TypeError, ValueError, IndexError):
            pass
    senders = _addresses([msg.get("From", "")])
    return Mail(
        message_id=message_id,
        date=when,
        sender=senders[0] if senders else ("", ""),
        to=_addresses(msg.get_all("To") or []),
        cc=_addresses(msg.get_all("Cc") or []),
        subject=" ".join(str(msg.get("Subject") or "").split()),
        text=_mail_text(msg),
    )


# ----------------------------------------------------- quoted text, forwards

_REPLY_HEADERS = [re.compile(p, re.IGNORECASE) for p in (
    r"^On\b.*\d.*\bwrote:$",
    r"^Am\b.*\d.*\bschrieb\b.*:$",
    r"^Op\b.*\d.*\bschreef\b.*:$",
    r"^Le\b.*\d.*\ba écrit ?:$",
    r"^-+ ?(Original Message|Ursprüngliche Nachricht|Oorspronkelijk bericht|"
    r"Message d'origine) ?-+$",
)]
_FORWARD_MARKER = re.compile(
    r"^-{2,} ?(Forwarded message|Weitergeleitete Nachricht|Doorgestuurd bericht|"
    r"Message transféré) ?-{2,}$", re.IGNORECASE)
_FORWARD_SUBJECT = re.compile(r"^\s*(fwd?|fw|wg|tr|doorst)\s*:\s*", re.IGNORECASE)
_HEADER_KEYS = {
    "from": "from", "von": "from", "van": "from", "de": "from",
    "date": "date", "sent": "date", "datum": "date", "gesendet": "date",
    "verzonden": "date", "envoyé": "date",
    "subject": "subject", "betreff": "subject", "onderwerp": "subject",
    "objet": "subject",
    "to": "to", "an": "to", "aan": "to", "à": "to",
    "cc": "cc",
}
_HEADER = re.compile(r"^\*?\s*([^\W\d_]{1,9})\s*\*?\s*:\s*\*?\s*(.*)$")


def _header(line: str) -> tuple[str, str] | None:
    m = _HEADER.match(line.strip())
    if not m or m.group(1).lower() not in _HEADER_KEYS:
        return None
    return _HEADER_KEYS[m.group(1).lower()], m.group(2).replace("*", "").strip()


def _is_header_block(lines: list[str], i: int) -> bool:
    """An Outlook-style 'From: … / Sent: …' block starting at line i."""
    first = _header(lines[i])
    if not first or first[0] != "from" or not first[1]:
        return False
    return any((h := _header(lines[j])) and h[0] == "date"
               for j in range(i + 1, min(i + 5, len(lines))))


def strip_quoted(text: str) -> str:
    """Your new text (and signature) without the quoted thread below it."""
    lines = text.replace("\r\n", "\n").split("\n")
    cut = len(lines)
    for i, line in enumerate(lines):
        s = line.strip()
        joined = f"{s} {lines[i + 1].strip()}" if i + 1 < len(lines) else s
        if any(p.match(s) or p.match(joined) for p in _REPLY_HEADERS) \
                or _is_header_block(lines, i):
            cut = i
            break
        if s.startswith(">") and all(not x.strip() or x.strip().startswith(">")
                                     for x in lines[i:]):
            cut = i
            break
    j = cut - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if cut < len(lines) and j >= 0 and re.fullmatch(r"[_\-]{8,}", lines[j].strip()):
        cut = j
    return normalise_body("\n".join(x.rstrip() for x in lines[:cut]).strip("\n"))


def _parse_loose_date(value: str) -> datetime | None:
    s = " ".join(value.replace(" ", " ").replace(" at ", " ").split())
    if not s:
        return None
    for fmt in ("%a, %b %d, %Y %I:%M %p", "%A, %B %d, %Y %I:%M %p",
                "%a, %d %b %Y %H:%M", "%A, %d %B %Y %H:%M", "%d %B %Y %H:%M",
                "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return _local(parsedate_to_datetime(s))
    except (TypeError, ValueError, IndexError):
        return None


@dataclass
class Forwarded:
    sender: tuple[str, str]
    date: datetime | None
    subject: str
    to: list[tuple[str, str]]
    cc: list[tuple[str, str]]
    body: str


def _address_value(value: str) -> list[tuple[str, str]]:
    value = value.replace("[mailto:", "<").replace("]", ">").replace(";", ",")
    return _addresses([value])


def parse_forward(text: str, subject: str) -> Forwarded | None:
    """The original mail inside a forward (Gmail marker or Outlook header block)."""
    lines = text.split("\n")
    start = next((i + 1 for i, line in enumerate(lines)
                  if _FORWARD_MARKER.match(line.strip())), None)
    if start is None:
        if not _FORWARD_SUBJECT.match(subject):
            return None
        start = next((i for i in range(len(lines)) if _is_header_block(lines, i)), None)
        if start is None:
            return None
    while start < len(lines) and not lines[start].strip():
        start += 1
    fields: dict[str, str] = {}
    i = start
    while i < len(lines):
        header = _header(lines[i])
        if header is None:
            break
        fields.setdefault(header[0], header[1])
        i += 1
    senders = _address_value(fields.get("from", ""))
    if not senders:
        return None
    return Forwarded(
        sender=senders[0],
        date=_parse_loose_date(fields.get("date", "")),
        subject=fields.get("subject", "") or _FORWARD_SUBJECT.sub("", subject),
        to=_address_value(fields.get("to", "")),
        cc=_address_value(fields.get("cc", "")),
        body="\n".join(lines[i:]).strip("\n"),
    )


# ------------------------------------------------------------------ matching


@dataclass
class Entry:
    """One interaction to log: a mail seen from one external person."""
    message_id: str
    date: datetime
    direction: str
    address: str
    name: str
    subject: str
    body: str
    channel: str = "email"
    source: str = "bcc-import"

    @property
    def kind(self) -> str:
        """Inbox kind: "meeting" for calendar imports, else "mail"."""
        return "meeting" if self.channel == "meeting" else "mail"


def kind_prefix(kind: str) -> str:
    """Commit message prefix for an inbox item of this kind."""
    return "calendar" if kind == "meeting" else "bcc"


def entries_for_mail(mail: Mail, settings: Settings) -> list[Entry]:
    subject, when, text = mail.subject, mail.date, mail.text
    if settings.is_me(mail.sender[1]):
        fwd = parse_forward(mail.text, mail.subject)
        if fwd is None:
            direction, people = "out", mail.to + mail.cc
        else:
            subject, when, text = fwd.subject, fwd.date or mail.date, fwd.body
            if settings.is_me(fwd.sender[1]):  # your own mail, forwarded later
                direction, people = "out", fwd.to + fwd.cc
            else:  # a reply you forwarded
                direction, people = "in", [fwd.sender]
    else:
        direction, people = "in", [mail.sender]
    body = strip_quoted(text)
    seen: set[str] = set()
    entries = []
    for name, address in people:
        if (not address or address in seen or settings.is_me(address)
                or settings.ignored(address)):
            continue
        seen.add(address)
        entries.append(Entry(mail.message_id, when, direction, address, name,
                             subject, body))
    return entries


def name_parts(name: str, address: str) -> tuple[str, str]:
    name = (name or "").strip().strip("'\"")
    if "@" in name:
        name = ""
    if "," in name:
        last, _, first = name.partition(",")
        name = f"{first.strip()} {last.strip()}"
    if not name:
        local = address.partition("@")[0].split("+")[0]
        name = " ".join(p.capitalize() for p in re.split(r"[._-]+", local) if p)
    return split_name(name)


def _domain(address: str) -> str:
    return address.rpartition("@")[2]


def name_from_domain(domain: str) -> str:
    """acme-labs.de -> 'Acme-labs'; acme.co.uk -> 'Acme'."""
    labels = [label for label in domain.lower().split(".") if label]
    if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "net", "ac", "gov") \
            and len(labels[-1]) == 2:
        label = labels[-3]
    else:
        label = labels[-2] if len(labels) >= 2 else (labels[0] if labels else "")
    return label[:1].upper() + label[1:]


def website_for_address(address: str) -> str:
    """https://<the address's domain>, or "" for a personal mailbox."""
    domain = _domain(normalise_email(address))
    return f"https://{domain}" if domain and domain not in FREEMAIL else ""


def is_no_reply(address: str) -> bool:
    return bool(NO_REPLY.match(address.partition("@")[0].lower()))


def _host(url: str) -> str:
    host = (urlparse(normalise_website(url)).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def company_domains(company) -> set[str]:
    domains = {_host(company.website)} if company.website else set()
    domains |= {_domain(c.email) for c in company.contacts.values() if c.email}
    return {d for d in domains if d and d not in FREEMAIL}


@dataclass
class Match:
    action: str  # log | create-contact | review
    company: str = ""
    contact: str = ""
    reason: str = ""
    new_domain: str = ""  # set when the review is only because no company has this domain


def match_address(store: Store, address: str) -> Match:
    hits = [(c.slug, ct.slug) for c in store.companies.values()
            for ct in c.contacts.values() if ct.email == address]
    if len(hits) == 1:
        return Match("log", *hits[0])
    if hits:
        return Match("review", reason="this email is on contacts at "
                     + ", ".join(sorted({h[0] for h in hits})))
    domain = _domain(address)
    if domain in FREEMAIL:
        return Match("review", reason=f"personal address ({domain})")
    companies = sorted(
        c.slug for c in store.companies.values()
        if any(domain == d or domain.endswith("." + d) for d in company_domains(c)))
    if len(companies) == 1:
        return Match("create-contact", companies[0])
    if companies:
        return Match("review", reason=f"domain {domain} matches " + ", ".join(companies))
    return Match("review", reason=f"no company with domain {domain}", new_domain=domain)


def resolve_company(store: Store, text: str) -> str:
    text = (text or "").strip()
    if text in store.companies:
        return text
    by_name = [c.slug for c in store.companies.values() if c.name.lower() == text.lower()]
    if len(by_name) == 1:
        return by_name[0]
    raise ValidationError({"company": f"unknown company {text!r}" if text
                           else "pick a company"})


def company_named(store: Store, name: str):
    """The one company with this name, ignoring case and legal suffixes (GmbH, BV...)."""
    key = slugify(name or "", strip_legal=True, default="")
    hits = [c for c in store.companies.values()
            if key and slugify(c.name, strip_legal=True, default="") == key]
    return hits[0] if len(hits) == 1 else None


def existing_contact(company, address: str, first_name: str, last_name: str):
    """The contact a mail belongs to: same email, else same name with no email yet."""
    by_email = next((c for c in company.contacts.values() if c.email == address), None)
    if by_email is not None:
        return by_email
    wanted = f"{first_name} {last_name}".strip().lower()
    if not wanted:
        return None
    return next((c for c in company.contacts.values()
                 if not c.email and c.name.lower() == wanted), None)


def log_entry(store: Store, company_slug: str, contact_slug: str, entry: Entry):
    return store.create_interaction(
        company_slug, channel=entry.channel, direction=entry.direction,
        subject=entry.subject, contact=contact_slug, date=entry.date,
        body=entry.body, source=entry.source, message_id=entry.message_id,
    )


# --------------------------------------------------------------------- inbox


@dataclass
class InboxItem:
    id: str
    message_id: str
    date: datetime
    direction: str
    address: str
    name: str
    subject: str
    reason: str
    body: str
    kind: str = "mail"  # mail (BCC import) | meeting (calendar import)

    @property
    def first_name(self) -> str:
        return name_parts(self.name, self.address)[0]

    @property
    def last_name(self) -> str:
        return name_parts(self.name, self.address)[1]

    def entry(self) -> Entry:
        if self.kind == "meeting":
            return Entry(self.message_id, self.date, self.direction, self.address,
                         self.name, self.subject, self.body, "meeting", "calendar-import")
        return Entry(self.message_id, self.date, self.direction, self.address,
                     self.name, self.subject, self.body)


class Inbox:
    """Mails waiting for a company: inbox/<id>.md, plus run bookkeeping."""

    def __init__(self, root: Path):
        self.dir = Path(root) / "inbox"

    def _path(self, item_id: str) -> Path | None:
        if not re.fullmatch(r"[0-9A-Za-z-]+", item_id or ""):
            return None
        return self.dir / f"{item_id}.md"

    def count(self) -> int:
        return len(list(self.dir.glob("*.md"))) if self.dir.is_dir() else 0

    def _read(self, path: Path) -> InboxItem:
        meta, body = split_file(path.read_text(encoding="utf-8"))
        when = meta.get("date")
        if not isinstance(when, datetime):
            when = datetime.fromisoformat(str(when))
        return InboxItem(
            id=path.stem, message_id=str(meta.get("message_id") or ""), date=when,
            direction=str(meta.get("direction") or "out"),
            address=normalise_email(str(meta.get("address") or "")),
            name=str(meta.get("name") or ""), subject=str(meta.get("subject") or ""),
            reason=str(meta.get("reason") or ""), body=body,
            kind="meeting" if meta.get("kind") == "meeting" else "mail",
        )

    def items(self) -> list[InboxItem]:
        out = []
        for path in sorted(self.dir.glob("*.md")) if self.dir.is_dir() else []:
            try:
                out.append(self._read(path))
            except (ValidationError, ValueError, OSError) as exc:
                logger.warning("unreadable inbox item %s: %s", path, exc)
        return sorted(out, key=lambda i: (i.date, i.id), reverse=True)

    def get(self, item_id: str) -> InboxItem | None:
        path = self._path(item_id)
        if path is None or not path.exists():
            return None
        return self._read(path)

    def add(self, entry: Entry, reason: str) -> InboxItem:
        self.dir.mkdir(parents=True, exist_ok=True)
        base = f"{entry.date:%Y-%m-%dT%H%M}-{entry.direction}-{slugify(entry.address, default='mail')}"
        item_id = unique_slug(base, {p.stem for p in self.dir.glob("*.md")})
        item = InboxItem(item_id, entry.message_id, entry.date, entry.direction,
                         entry.address, entry.name, entry.subject, reason, entry.body,
                         entry.kind)
        meta = {"kind": item.kind, "message_id": item.message_id, "date": item.date,
                "direction": item.direction, "address": item.address,
                "name": item.name, "subject": item.subject, "reason": reason}
        (self.dir / f"{item_id}.md").write_text(build_file(meta, item.body),
                                                encoding="utf-8")
        return item

    def remove(self, item_id: str) -> None:
        path = self._path(item_id)
        if path is not None:
            path.unlink(missing_ok=True)

    def discarded(self) -> set[tuple[str, str]]:
        path = self.dir / DISCARDED_FILE
        if not path.exists():
            return set()
        pairs = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            mid, _, address = line.partition("\t")
            if mid and address:
                pairs.add((mid, address))
        return pairs

    def discard(self, item: InboxItem) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / DISCARDED_FILE).open("a", encoding="utf-8") as fh:
            fh.write(f"{item.message_id}\t{item.address}\n")
        self.remove(item.id)

    def seen(self) -> set[tuple[str, str]]:
        return {(i.message_id, i.address) for i in self.items()} | self.discarded()

    def last_run(self, file: str = LAST_RUN_FILE) -> dict | None:
        path = self.dir / file
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def record_run(self, ok: bool, at: datetime, summary: str = "",
                   error: str = "", file: str = LAST_RUN_FILE) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        data = {"at": fmt_datetime(at), "ok": ok, "summary": summary, "error": error}
        (self.dir / file).write_text(json.dumps(data, indent=2) + "\n",
                                              encoding="utf-8")


def run_alert(last_run: dict | None, now: datetime, label: str = "BCC import") -> str:
    """Why the nav should flag the Inbox: a failed or stale daily import."""
    if not last_run:
        return ""
    if not last_run.get("ok"):
        return f"{label} failed: {last_run.get('error', '')}"
    try:
        at = datetime.fromisoformat(str(last_run.get("at")))
    except ValueError:
        return ""
    days = (now - at).days
    return f"no {label} for {days} days" if days >= STALE_AFTER_DAYS else ""


# -------------------------------------------------------------------- import


@dataclass
class RunResult:
    mails: int = 0
    logged: int = 0
    companies: int = 0
    contacts: int = 0
    review: int = 0
    duplicates: int = 0
    skipped: int = 0
    lines: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.mails} mails read: {self.logged} interactions logged, "
                f"{self.companies} companies created, "
                f"{self.contacts} contacts created, {self.review} to review, "
                f"{self.duplicates} already imported, {self.skipped} skipped")

    def commit_message(self) -> str:
        mails = "1 mail" if self.mails == 1 else f"{self.mails} mails"
        return (f"bcc: imported {mails} ({self.logged} interactions, "
                f"{self.companies} companies, {self.contacts} contacts, "
                f"{self.review} to review)")


def import_mails(store: Store, inbox: Inbox, raws: Iterable[bytes],
                 settings: Settings, apply: bool = False) -> RunResult:
    """Plan (and with apply, write) interactions for raw RFC 822 mails."""
    result = RunResult()
    seen = inbox.seen()
    planned: dict[str, str] = {}  # dry run: address -> company of a new contact
    with store.batch("bcc: import") as batch:
        for raw in raws:
            result.mails += 1
            mail = parse_mail(raw, store.now())
            entries = entries_for_mail(mail, settings)
            if not entries:
                result.skipped += 1
                result.lines.append(f"{mail.date:%Y-%m-%d %H:%M} | {mail.subject or '-'} "
                                    f"| skipped: no external address")
                continue
            # Anyone who learns the tracking address can mail it; only your own
            # mail (sent, or a reply you forwarded) may create a company.
            refuse = "" if settings.is_me(mail.sender[1]) else "mail not sent by you"
            for entry in entries:
                outcome = handle_entry(store, inbox, entry, seen, planned, result, apply,
                                       create=settings.create_companies, refuse=refuse)
                result.lines.append(f"{entry.date:%Y-%m-%d %H:%M} | email {entry.direction} "
                                    f"| {entry.address} | {outcome}")
        batch["message"] = result.commit_message()
    return result


def handle_entry(store: Store, inbox: Inbox, entry: Entry, seen: set, planned: dict,
                 result, apply: bool, create: bool = False, refuse: str = "") -> str:
    """Log, create-and-log, or queue one entry (shared by BCC and calendar import).

    ``result`` needs integer ``logged``, ``contacts``, ``review`` and
    ``duplicates`` attributes (and ``companies`` when ``create``); ``planned``
    remembers dry-run contacts, and dry-run companies under "@<domain>".
    ``create`` lets an unknown domain become a new company unless ``refuse``
    gives the reason it may not (the calendar import never passes it)."""
    if entry.address in planned:
        result.logged += 1
        return f"{planned[entry.address]} | log"
    match = match_address(store, entry.address)
    if match.action == "log":
        company = store.companies[match.company]
        if any(i.message_id == entry.message_id and i.contact == match.contact
               for i in company.interactions):
            result.duplicates += 1
            return f"{match.company}/{match.contact} | already imported"
        if apply:
            log_entry(store, match.company, match.contact, entry)
        result.logged += 1
        return f"{match.company}/{match.contact} | log"
    if match.action == "create-contact":
        first, last = name_parts(entry.name, entry.address)
        result.logged += 1
        same = existing_contact(store.companies[match.company], entry.address, first, last)
        if same is not None:  # known person, email not on file yet
            if apply:
                store.update_contact(match.company, same.slug, email=entry.address)
                log_entry(store, match.company, same.slug, entry)
            else:
                planned[entry.address] = f"{match.company}/{same.slug}"
            return f"{match.company}/{same.slug} | email added, log"
        result.contacts += 1
        if not apply:
            planned[entry.address] = f"{match.company} (new contact)"
            return f"{match.company} | new contact {first} {last}".rstrip() + ", log"
        contact = store.create_contact(match.company, first, last, email=entry.address)
        log_entry(store, match.company, contact.slug, entry)
        return f"{match.company}/{contact.slug} | new contact, log"
    key = (entry.message_id, entry.address)
    if key in seen:  # waiting in the queue or discarded: never a new company either
        result.duplicates += 1
        return "already in the inbox or discarded"
    reason = match.reason
    if match.new_domain and create:
        name = name_from_domain(match.new_domain)
        # A dry run's second person at a company it plans: --apply finds that company.
        if "@" + match.new_domain not in planned:
            same = company_named(store, name)
            refuse = (refuse or ("no-reply address" if is_no_reply(entry.address) else "")
                      or (f"{same.name} has the same name" if same is not None else ""))
        else:
            refuse = ""
        if not refuse:
            return create_company_entry(store, entry, match.new_domain, name, planned,
                                        result, apply)
        reason = f"{reason} ({refuse}, so none created)"
    seen.add(key)
    result.review += 1
    if apply:
        item = inbox.add(entry, reason)
        store.notify(f"{kind_prefix(item.kind)}: {item.id} to review", ["inbox"])
    return f"to review: {reason}"


def create_company_entry(store: Store, entry: Entry, domain: str, name: str,
                         planned: dict, result, apply: bool) -> str:
    """Create the company for an unknown domain, then the contact, then log."""
    first, last = name_parts(entry.name, entry.address)
    result.logged += 1
    result.contacts += 1
    known = planned.get("@" + domain)
    if known:  # dry run: a second person at a company this run will create
        planned[entry.address] = known
        return f"{known} | new contact {first} {last}".rstrip() + ", log"
    result.companies += 1
    if not apply:
        planned["@" + domain] = planned[entry.address] = f"{domain} (new company)"
        return f"new company from {domain} | new contact {first} {last}".rstrip() + ", log"
    way = "to" if entry.direction == "out" else "from"
    company = store.create_company(
        name, website=f"https://{domain}",
        notes=f"Created by the BCC import from a mail {way} {entry.address} "
              f"({entry.date:%Y-%m-%d}).")
    contact = store.create_contact(company.slug, first, last, email=entry.address)
    log_entry(store, company.slug, contact.slug, entry)
    return f"{company.slug}/{contact.slug} | new company, new contact, log"


def assign(store: Store, inbox: Inbox, item_id: str, company: str,
           first_name: str = "", last_name: str = ""):
    """Log an inbox item at a company; returns (company slug, interaction).

    The company is found by slug or name (ignoring legal suffixes), else by the
    mail's domain; a name that finds nothing becomes a new company, with the
    mail's domain as its website unless that is a personal mailbox."""
    item = inbox.get(item_id)
    if item is None:
        raise ValidationError({"item": f"unknown inbox item {item_id!r}"})
    name = (company or "").strip()
    if not name:
        raise ValidationError({"company": "pick a company"})
    try:
        slug = resolve_company(store, name)
    except ValidationError:
        same = company_named(store, name)
        slug = same.slug if same is not None else match_address(store, item.address).company
    first_name, last_name = (first_name or "").strip(), (last_name or "").strip()
    if not first_name and not last_name:
        first_name, last_name = item.first_name, item.last_name
    prefix = kind_prefix(item.kind)
    new = not slug
    with store.batch(f"{prefix}: {item.id} assigned") as batch:
        if new:
            slug = store.create_company(name, website=website_for_address(item.address)).slug
        target = store.companies[slug]
        contact = existing_contact(target, item.address, first_name, last_name)
        if contact is None:
            contact = store.create_contact(slug, first_name, last_name, email=item.address)
        elif not contact.email:
            store.update_contact(slug, contact.slug, email=item.address)
        interaction = log_entry(store, slug, contact.slug, item.entry())
        inbox.remove(item.id)
        # The inbox is outside companies/ and the Inbox writes its own files, so
        # name the path here: a commit only covers what the store was told about,
        # and the removal would stay behind as a deleted-but-uncommitted file.
        store.notify(f"{prefix}: {item.id} assigned", ["inbox"])
        batch["message"] = (f"{prefix}: {item.id} assigned to {slug}/{contact.slug}"
                            + (" (new company)" if new else ""))
    return slug, interaction


def discard(store: Store, inbox: Inbox, item_id: str) -> InboxItem:
    item = inbox.get(item_id)
    if item is None:
        raise ValidationError({"item": f"unknown inbox item {item_id!r}"})
    inbox.discard(item)
    store.notify(f"{kind_prefix(item.kind)}: {item.id} discarded", ["inbox"])
    return item


# ---------------------------------------------------------------------- imap


def keychain_password(settings: Settings, data_dir: Path | str | None = None,
                      runner=subprocess.run, env: dict | None = None,
                      platform: str | None = None) -> str:
    """The Gmail app password: $HERMITCRM_BCC_PASSWORD (or $CRM_BCC_PASSWORD),
    .secrets.toml, then the macOS Keychain (service bcc_keychain_service,
    account = the IMAP user). See hermitcrm/secrets.py."""
    service, account = settings.keychain_service, settings.imap_user
    password = secrets.get("bcc_password", data_dir,
                           {"bcc_keychain_service": service}, account=account,
                           env=env, runner=runner, platform=platform)
    if not password:
        raise BccError(
            "no Gmail app password found. Set HERMITCRM_BCC_PASSWORD, add "
            "bcc_password to .secrets.toml (chmod 600), or on macOS: "
            f"security add-generic-password -s {service} -a {account} -w")
    return password.replace(" ", "")  # Gmail shows it in groups of 4


_LIST_LINE = re.compile(rb'^\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$')


def all_mail_folder(list_lines) -> str:
    """Gmail's All Mail folder by its \\All flag (the name depends on UI language)."""
    for line in list_lines or []:
        if isinstance(line, tuple):
            line = line[0]
        m = _LIST_LINE.match(line or b"")
        if m and b"\\All" in m.group("flags").split():
            name = m.group("name").decode("utf-8", "replace").strip()
            return name[1:-1] if name.startswith('"') and name.endswith('"') else name
    return "[Gmail]/All Mail"


def _imap_text(exc: Exception) -> str:
    arg = exc.args[0] if exc.args else exc
    return arg.decode("utf-8", "replace") if isinstance(arg, bytes) else str(arg)


class GmailMailbox:
    """Reads the tracking address's mail over IMAP; a context manager."""

    def __init__(self, settings: Settings, password: str, imap_factory=None,
                 timeout: float = 30.0):
        self.settings = settings
        self.password = password
        self.imap_factory = imap_factory or imaplib.IMAP4_SSL
        self.timeout = timeout
        self.conn = None
        self.folder = ""

    def __enter__(self) -> "GmailMailbox":
        host, user = self.settings.imap_host, self.settings.imap_user
        try:
            self.conn = self.imap_factory(host, 993, timeout=self.timeout)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise BccError(f"could not reach {host}: {exc}") from exc
        try:
            self.conn.login(user, self.password)
            _, lines = self.conn.list()
            self.folder = all_mail_folder(lines)
            quoted = '"' + self.folder.replace('"', '\\"') + '"'
            typ, data = self.conn.select(quoted)
        except imaplib.IMAP4.error as exc:
            self.close()
            raise BccError(f"Gmail refused the login for {user}: {_imap_text(exc)}. "
                           f"Check the app password in the Keychain (service "
                           f"{self.settings.keychain_service!r}).") from exc
        except OSError as exc:
            self.close()
            raise BccError(f"connection to {host} failed: {exc}") from exc
        if typ != "OK":
            self.close()
            raise BccError(f"could not open {self.folder}: {data!r}")
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.logout()
            except Exception:  # logout on a broken connection is not worth a failure
                pass
            self.conn = None

    def query(self) -> str:
        return (f'"deliveredto:{self.settings.address} '
                f'newer_than:{self.settings.lookback_days}d"')

    def fetch(self) -> list[tuple[bytes, bytes]]:
        try:
            typ, data = self.conn.uid("SEARCH", "X-GM-RAW", self.query())
            if typ != "OK":
                raise BccError(f"Gmail search failed: {data!r}")
            uids = data[0].split() if data and data[0] else []
            out = []
            for uid in uids:
                typ, parts = self.conn.uid("FETCH", uid, "(BODY.PEEK[])")
                raw = next((p[1] for p in parts or []
                            if isinstance(p, tuple) and len(p) > 1), None)
                if typ == "OK" and raw:
                    out.append((uid, raw))
            return out
        except (imaplib.IMAP4.error, OSError) as exc:
            raise BccError(f"reading mail failed: {_imap_text(exc)}") from exc

    def mark_read(self, uids: list[bytes]) -> None:
        if not uids:
            return
        try:
            self.conn.uid("STORE", b",".join(uids), "+FLAGS", "(\\Seen)")
        except (imaplib.IMAP4.error, OSError) as exc:
            raise BccError(f"marking mail read failed: {_imap_text(exc)}") from exc


NOT_SET_UP = ("BCC import is not set up: set bcc_address (and my_addresses) in "
              "config.toml, then store the app password (see README, BCC import).")


def open_gmail(settings: Settings, data_dir: Path | str | None = None,
               runner=subprocess.run) -> GmailMailbox:
    if not settings.address:
        raise BccError(NOT_SET_UP)
    password = keychain_password(settings, data_dir, runner)
    return GmailMailbox(settings, password)


def run_bcc(store: Store, inbox: Inbox, settings: Settings, apply: bool,
            open_mailbox: Callable[[], GmailMailbox]) -> RunResult:
    """Fetch, import and (with apply) mark read; records the run for the Inbox page."""
    try:
        with open_mailbox() as box:
            fetched = box.fetch()
            result = import_mails(store, inbox, [raw for _, raw in fetched], settings,
                                  apply)
            if apply:
                box.mark_read([uid for uid, _ in fetched])
    except Exception as exc:
        if apply:
            message = str(exc) if isinstance(exc, BccError) else f"{type(exc).__name__}: {exc}"
            inbox.record_run(False, store.now(), error=message)
        raise
    if apply:
        inbox.record_run(True, store.now(), summary=result.summary())
    return result
