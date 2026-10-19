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

"""Sending approved outreach email from the app (spec part 08).

    ready ──> Schedule ──> queued ──> worker tick ──> guards ──> SMTP ──> log ──> sent
              (planner)    send_at    `send due`       hold or    message_id   interaction,
                                                       pause      first        source: outreach

Nothing here uses an AI: it is plain Python on a schedule, so it keeps going
when the web app is closed and can be run from the CLI with `--dry-run`. The
person still approves every message; this module only sends what they approved,
exactly as approved, once.

The order inside one send is what makes a crash recoverable:

  1. the guards run (nothing is written if one holds the item);
  2. `message_id` and `send_tries` are written on the item and committed;
  3. the message goes out over SMTP;
  4. the interaction is logged and the item becomes `sent`, in one commit.

If the process dies between 3 and 4, the next tick finds a queued item that
already has a `message_id`, looks for that Message-ID in the Sent folder, and
logs it when it is there; only when it is not does it send again, with the same
Message-ID. Standard library only (`smtplib`, `imaplib`, `email`, `fcntl`).
"""

from __future__ import annotations

import hashlib
import imaplib
import json
import re
import smtplib
import socket
import ssl
import subprocess
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, make_msgid
from pathlib import Path

from . import messaging, outreach, playbook, secrets, sendplan, suppress
from .models import do_not_contact, normalise_email, valid_email
from .store import Store, load_config

try:                      # not on Windows: the lock is then a plain exclusive file
    import fcntl
except ImportError:       # pragma: no cover
    fcntl = None

AUTH, QUOTA, TEMPORARY, RECIPIENT, REFUSED = "auth", "quota", "temporary", "recipient", "refused"
RETRY_MINUTES = 15       # a temporary error moves send_at this far
MAX_TRIES = 3            # then the item is failed
TIMEOUT = 30.0
SEND_NOW_WAIT = 10.0     # seconds Send now waits for a tick that holds the lock
STATE_FILE = "hermitcrm-send.json"
LOCK_FILE = "hermitcrm-send.lock"

# What each common provider needs. Only Gmail and Google Workspace are tested;
# Microsoft has switched off password sign-in, as on the BCC page.
PROVIDERS = {
    "gmail": {"label": "Gmail / Google Workspace", "smtp_host": "smtp.gmail.com",
              "smtp_port": 587, "imap_host": "imap.gmail.com", "tested": True, "works": True,
              "password_url": "https://myaccount.google.com/apppasswords",
              "note": "Needs 2-Step Verification, then an app password named \"Hermit CRM\". "
                      "A Workspace admin can switch app passwords off, and changing the "
                      "account password revokes them."},
    "icloud": {"label": "iCloud Mail (untested)", "smtp_host": "smtp.mail.me.com",
               "smtp_port": 587, "imap_host": "imap.mail.me.com", "tested": False,
               "works": True, "password_url": "https://account.apple.com",
               "note": "An app-specific password. Not tested end to end."},
    "fastmail": {"label": "Fastmail (untested)", "smtp_host": "smtp.fastmail.com",
                 "smtp_port": 587, "imap_host": "imap.fastmail.com", "tested": False,
                 "works": True, "password_url": "",
                 "note": "An app password with SMTP and IMAP access. Not tested end to end."},
    "outlook": {"label": "Outlook.com / Microsoft 365", "smtp_host": "smtp.office365.com",
                "smtp_port": 587, "imap_host": "outlook.office365.com", "tested": False,
                "works": False, "password_url": "",
                "note": "Microsoft has switched off password sign-in for most accounts, so "
                        "this usually fails. Use a Gmail or Fastmail mailbox for sending."},
}


# ----------------------------------------------------------------- settings


@dataclass(frozen=True)
class SendSettings:
    enabled: bool = False
    paused: bool = False
    owner_name: str = ""
    from_addr: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    imap_host: str = "imap.gmail.com"
    keychain_service: str = "hermitcrm-send"
    window: tuple = (8 * 60 + 30, 17 * 60 + 30)
    days: tuple = (0, 1, 2, 3, 4)
    ramp: tuple = (10, 20, 30, 40)
    daily_cap: int = 50
    min_gap: int = 3
    company_gap_hours: int = 24
    grace: int = 10
    overdue: int = 20
    block_countries: tuple = ()
    my_addresses: tuple = ()
    problems: tuple = ()         # config values that could not be read (defaults were used)

    @property
    def domain(self) -> str:
        return self.from_addr.rpartition("@")[2]

    @property
    def plan(self) -> sendplan.PlanConfig:
        return sendplan.PlanConfig(days=self.days, window=self.window, ramp=self.ramp,
                                   daily_cap=self.daily_cap, min_gap=self.min_gap,
                                   company_gap_hours=self.company_gap_hours,
                                   grace=self.grace, overdue=self.overdue)

    @property
    def missing(self) -> str:
        """'' when it can send, else what is missing (for Settings and doctor)."""
        if not self.from_addr or not valid_email(self.from_addr):
            return "no sending address: set send_from (or owner_email) in Settings > Sending"
        if self.from_addr not in self.my_addresses:
            return (f"{self.from_addr} is not one of my_addresses; add it, so mail you send "
                    "from it is recognised as yours")
        return ""


def _int(config: dict, key: str, default: int, problems: list, low: int = 0) -> int:
    raw = config.get(key)
    try:
        value = default if raw is None or raw == "" else int(raw)
    except (TypeError, ValueError):
        problems.append(f"{key}: {raw!r} is not a number; using {default}")
        return default
    if value < low:
        problems.append(f"{key}: {value} is too low; using {default}")
        return default
    return value


def settings_from_config(config: dict) -> SendSettings:
    """Everything send_* in config.toml, parsed once. A value that cannot be
    read falls back to its default and is listed in `problems`."""
    c = config or {}
    problems: list[str] = []
    d = SendSettings()
    from_addr = normalise_email(str(c.get("send_from") or c.get("owner_email") or ""))
    try:
        window = sendplan.parse_window(c.get("send_window") or "08:30-17:30")
    except ValueError as exc:
        problems.append(f"send_window: {exc}; using 08:30-17:30")
        window = d.window
    try:
        days = sendplan.parse_days(c.get("send_days") or ["mon", "tue", "wed", "thu", "fri"])
    except ValueError as exc:
        problems.append(f"send_days: {exc}; using Monday to Friday")
        days = d.days
    ramp_raw = c.get("send_ramp")
    ramp: list[int] = []
    for value in ramp_raw if isinstance(ramp_raw, list) else list(d.ramp):
        try:
            ramp.append(max(0, int(value)))
        except (TypeError, ValueError):
            problems.append(f"send_ramp: {value!r} is not a number; the ramp is ignored")
            ramp = []
            break
    countries = tuple(sorted({str(x).strip().upper() for x in
                              (c.get("send_email_block_countries") or []) if str(x).strip()}))
    port = _int(c, "send_smtp_port", d.smtp_port, problems, 1)
    return SendSettings(
        enabled=bool(c.get("send_enabled")), paused=bool(c.get("send_paused")),
        owner_name=" ".join(str(c.get("owner_name") or "").split()), from_addr=from_addr,
        smtp_host=str(c.get("send_smtp_host") or d.smtp_host).strip(), smtp_port=port,
        smtp_user=str(c.get("send_smtp_user") or from_addr).strip(),
        imap_host=str(c.get("send_imap_host") if c.get("send_imap_host") is not None
                      else d.imap_host).strip(),
        keychain_service=str(c.get("send_keychain_service") or d.keychain_service).strip(),
        window=window, days=days, ramp=tuple(ramp),
        daily_cap=_int(c, "send_daily_cap", d.daily_cap, problems),
        min_gap=_int(c, "send_min_gap_minutes", d.min_gap, problems, 1),
        company_gap_hours=_int(c, "send_company_gap_hours", d.company_gap_hours, problems),
        grace=_int(c, "send_grace_minutes", d.grace, problems),
        overdue=_int(c, "send_overdue_minutes", d.overdue, problems, 1),
        block_countries=countries,
        my_addresses=tuple(sorted({normalise_email(a) for a in c.get("my_addresses") or []}
                                  | ({normalise_email(c.get("owner_email"))}
                                     if c.get("owner_email") else set()))),
        problems=tuple(problems))


PLAN_CAP = 50   # the daily cap the plan starts from; Settings warns above it


def cap_warning(cap: int) -> str:
    """What Settings says about a daily cap: nothing up to PLAN_CAP."""
    if cap > sendplan.SOFT_CEILING:
        return (f"{cap} a day is more than {sendplan.SOFT_CEILING}. That is allowed for at "
                f"most {sendplan.MAX_DAYS_OVER} send-days in a row; the third is held at "
                f"{sendplan.SOFT_CEILING}. A mailbox that sends this much for long ends up "
                "in spam.")
    if cap > PLAN_CAP:
        return (f"{cap} a day is above the plan of {PLAN_CAP}. Raise it in steps and watch "
                "bounces and replies; if either gets worse, go back down.")
    return ""


def password_stored(settings: SendSettings, root, *, env=None, runner=subprocess.run,
                    platform=None) -> bool:
    """Whether an app password is saved for the sending mailbox (never raises, never
    returns the password): what Settings uses to say "stored" only when it is."""
    try:
        return bool(get_password(settings, root, env=env, runner=runner, platform=platform))
    except SendError:
        return False


def get_password(settings: SendSettings, root, *, env=None, runner=subprocess.run,
                 platform=None) -> str:
    """The sending mailbox's app password (environment, .secrets.toml, then the OS
    store; account = the SMTP user), without the spaces Google shows in it."""
    password = secrets.get("send_password", root,
                           {"send_keychain_service": settings.keychain_service},
                           account=settings.smtp_user, env=env, runner=runner,
                           platform=platform)
    if not password:
        who = settings.smtp_user or "the sending mailbox"
        raise SendError(AUTH, f"no app password found for {who}: save it in Settings > "
                        "Sending (or set HERMITCRM_SEND_PASSWORD)")
    return password.replace(" ", "")


# ------------------------------------------------------------------- errors


class SendError(Exception):
    """A send or a mailbox check failed. `kind` decides what happens next
    (AUTH/REFUSED/QUOTA pause, TEMPORARY retries, RECIPIENT fails the item) and
    `text` is the server's own words, shown as they are."""

    def __init__(self, kind: str, text: str, code: int | None = None):
        super().__init__(text)
        self.kind, self.text, self.code = kind, text, code

    def __str__(self) -> str:
        return self.text


def _text(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return " ".join(str(value or "").split())


_QUOTA = re.compile(r"5\.4\.5|sending (quota|limit)|quota exceeded|too many (messages|recipients)",
                    re.I)
_RECIPIENT = re.compile(r"5\.1\.\d|user unknown|does not exist|no such user|unknown user|"
                        r"mailbox unavailable|address rejected|invalid recipient|"
                        r"recipient (address )?rejected", re.I)


def classify_smtp(exc: BaseException) -> SendError:
    """Turn what smtplib raised into a SendError, keeping the server's text."""
    if isinstance(exc, SendError):
        return exc
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return SendError(AUTH, f"{exc.smtp_code} {_text(exc.smtp_error)}", exc.smtp_code)
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        who, (code, text) = next(iter(exc.recipients.items()))
        return _by_code(int(code), f"{who}: {_text(text)}", recipient=True)
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return _by_code(int(exc.smtp_code), _text(exc.smtp_error), recipient=False)
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return SendError(REFUSED, _text(exc))
    if isinstance(exc, smtplib.SMTPResponseException):
        return _by_code(int(exc.smtp_code), _text(exc.smtp_error), recipient=False)
    if isinstance(exc, (smtplib.SMTPServerDisconnected, socket.timeout, ssl.SSLError, OSError)):
        return SendError(TEMPORARY, _text(exc) or type(exc).__name__)
    return SendError(TEMPORARY, f"{type(exc).__name__}: {_text(exc)}")


def _by_code(code: int, text: str, recipient: bool) -> SendError:
    shown = f"{code} {text}"
    if 400 <= code < 500:
        return SendError(TEMPORARY, shown, code)
    if _QUOTA.search(text):
        return SendError(QUOTA, shown, code)
    if code in (530, 534, 535) or "authentication" in text.lower():
        return SendError(AUTH, shown, code)
    if recipient or _RECIPIENT.search(text):
        return SendError(RECIPIENT, shown, code)
    return SendError(REFUSED, shown, code)


# ------------------------------------------------------------------ message


def text_hash(subject: str, body: str) -> str:
    """The hash kept at Schedule time: an edit to the subject or body changes it."""
    return hashlib.sha256(f"{subject}\n{body}".encode("utf-8")).hexdigest()[:20]


def new_message_id(domain: str) -> str:
    return make_msgid(domain=domain or "localhost")


def thread_refs(company, item) -> tuple[str, str]:
    """(In-Reply-To, References) for an answer or follow-up: the Message-ID of the
    interaction it follows (your unanswered mail) or answers (their reply), when
    that mail has one."""
    key = item.follows or item.reply_to
    found = next((i for i in company.interactions if i.id == key), None) if key else None
    mid = (found.message_id if found is not None else "").strip()
    return (mid, mid) if mid.startswith("<") and mid.endswith(">") else ("", "")


_ADDRESS = re.compile(r"^[^@\s,;<>\"]+@[^@\s,;<>\"]+$")


def build_message(item, to: str, settings: SendSettings, *, message_id: str,
                  in_reply_to: str = "", references: str = "",
                  when: datetime | None = None) -> EmailMessage:
    """The mail exactly as approved: plain text, UTF-8, the item's subject and body.
    No BCC, no HTML, no tracking, no List-Unsubscribe (a one-to-one mail that
    looks like a newsletter is what filters punish)."""
    if not _ADDRESS.match(to or ""):
        raise SendError(RECIPIENT, f"{to!r} is not an email address")
    msg = EmailMessage()
    msg["From"] = formataddr((settings.owner_name, settings.from_addr)) \
        if settings.owner_name else settings.from_addr
    msg["To"] = to
    msg["Subject"] = " ".join((item.subject or "").split())
    msg["Date"] = format_datetime((when or datetime.now()).astimezone())
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to
    body = item.body
    plain = body.isascii() and max((len(line) for line in body.split("\n")), default=0) < 900
    msg.set_content(body, cte="7bit" if plain else "quoted-printable")
    return msg


# ---------------------------------------------------------------- transport


def connect(settings: SendSettings, password: str, factory=None, timeout: float = TIMEOUT):
    """An authenticated SMTP connection: STARTTLS on 587, SSL on 465."""
    ssl_port = settings.smtp_port == 465
    factory = factory or (smtplib.SMTP_SSL if ssl_port else smtplib.SMTP)
    conn = None
    try:
        conn = factory(settings.smtp_host, settings.smtp_port, timeout=timeout)
        conn.ehlo()
        if not ssl_port:
            conn.starttls(context=ssl.create_default_context())
            conn.ehlo()
        # smtplib's login tries every mechanism the server lists: a wrong password then
        # costs two failed logins (PLAIN, then LOGIN), and a server that drops the line
        # after the first would look like a temporary error that is retried. One attempt.
        features = getattr(conn, "esmtp_features", None)
        if isinstance(features, dict) and "PLAIN" in features.get("auth", "").upper().split():
            features["auth"] = "PLAIN"
        conn.login(settings.smtp_user, password)
        return conn
    except BaseException as exc:
        _quit(conn)
        raise classify_smtp(exc) from exc


def _quit(conn) -> None:
    if conn is None:
        return
    try:
        conn.quit()
    except Exception:       # a broken connection is not worth a failure
        try:
            conn.close()
        except Exception:
            pass


class SmtpSender:
    """Sends one approved item over SMTP; satisfies outreach.Sender. The item's
    `message_id` must already be written (see deliver)."""

    def __init__(self, store: Store, settings: SendSettings, password: str,
                 smtp_factory=None, timeout: float = TIMEOUT):
        self.store, self.settings, self.password = store, settings, password
        self.smtp_factory, self.timeout = smtp_factory, timeout

    def message_for(self, item) -> EmailMessage:
        company = self.store.get(item.company)
        contact = company.contacts.get(item.contact) if company is not None else None
        if contact is None:
            raise SendError(RECIPIENT, f"{item.record} is not in the CRM any more")
        to = normalise_email(contact.email)
        if not valid_email(to):
            raise SendError(RECIPIENT, f"{contact.name} has no email address")
        reply_to, refs = thread_refs(company, item)
        return build_message(item, to, self.settings, message_id=item.message_id,
                             in_reply_to=reply_to, references=refs, when=self.store.now())

    def send(self, item) -> outreach.SendResult:
        if not item.message_id:
            raise SendError(REFUSED, f"{item.id} has no Message-ID yet (internal error)")
        msg = self.message_for(item)
        conn = connect(self.settings, self.password, self.smtp_factory, self.timeout)
        try:
            conn.send_message(msg)
        except BaseException as exc:
            raise classify_smtp(exc) from exc
        finally:
            _quit(conn)
        return outreach.SendResult(sent=True, detail=f"sent to {msg['To']} as {item.message_id}")


class OutreachLogger:
    """Logs a sent mail as an outbound interaction (source `outreach`), the body
    byte for byte as it went out, with the angle and approach of the item. The
    store flips the item to `sent` in the same commit (sent_by_interaction)."""

    def __init__(self, store: Store, when: datetime | None = None):
        self.store, self.when = store, when

    def log(self, item, result) -> None:
        self.store.create_interaction(
            item.company, "email", "out", subject=" ".join((item.subject or "").split()),
            contact=item.contact, date=self.when or self.store.now(), body=item.body,
            source="outreach",
            message_id=item.message_id, angle=item.angle, approach=item.approach)


# ------------------------------------------------------------------ mailbox

_LIST_LINE = re.compile(rb'^\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$')


def special_folders(lines) -> dict[str, str]:
    """{'sent': name, 'all': name} found by their special-use flags, never by
    their (localised) names; INBOX is the one name IMAP fixes."""
    found: dict[str, str] = {"inbox": "INBOX"}
    for line in lines or []:
        if isinstance(line, tuple):
            line = line[0]
        m = _LIST_LINE.match(line if isinstance(line, bytes) else str(line).encode())
        if not m:
            continue
        flags = {f.lower() for f in m.group("flags").decode("utf-8", "replace").split()}
        name = m.group("name").decode("utf-8", "replace").strip()
        name = name[1:-1] if name.startswith('"') and name.endswith('"') else name
        if "\\sent" in flags:
            found.setdefault("sent", name)
        if "\\all" in flags:
            found.setdefault("all", name)
    return found


def imap_date(day: date) -> str:
    return f"{day.day:02d}-{day.strftime('%b')}-{day.year}"


def _imap_text(exc: BaseException) -> str:
    arg = exc.args[0] if exc.args else exc
    return _text(arg)


class Mailbox:
    """The sending mailbox over IMAP, read-only: has anyone written since an item
    was approved, is a Message-ID in Sent, which delivery reports came in. It uses
    the same user and app password as SMTP (one app password covers both at
    Google). A context manager; every failure is a SendError."""

    def __init__(self, settings: SendSettings, password: str, factory=None,
                 timeout: float = TIMEOUT):
        self.settings, self.password = settings, password
        self.factory = factory or imaplib.IMAP4_SSL
        self.timeout = timeout
        self.conn = None
        self.folders: dict[str, str] = {}

    def __enter__(self) -> "Mailbox":
        host, user = self.settings.imap_host, self.settings.smtp_user
        try:
            self.conn = self.factory(host, 993, timeout=self.timeout)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise SendError(TEMPORARY, f"could not reach {host}: {_text(exc)}") from exc
        try:
            self.conn.login(user, self.password)
            _, lines = self.conn.list()
            self.folders = special_folders(lines)
        except imaplib.IMAP4.error as exc:
            self.close()
            raise SendError(AUTH, f"{host} refused the login for {user}: "
                            f"{_imap_text(exc)}") from exc
        except OSError as exc:
            self.close()
            raise SendError(TEMPORARY, f"connection to {host} failed: {_text(exc)}") from exc
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.logout()
            except Exception:
                pass
            self.conn = None

    def _search(self, folder: str, *criteria) -> list[bytes]:
        quoted = '"' + folder.replace('"', '\\"') + '"'
        try:
            typ, data = self.conn.select(quoted, readonly=True)
            if typ != "OK":
                raise SendError(TEMPORARY, f"could not open {folder}: {data!r}")
            typ, data = self.conn.search(None, *criteria)
            if typ != "OK":
                raise SendError(TEMPORARY, f"search in {folder} failed: {data!r}")
        except (imaplib.IMAP4.error, OSError) as exc:
            raise SendError(TEMPORARY, f"reading {folder} failed: {_imap_text(exc)}") from exc
        return data[0].split() if data and data[0] else []

    def replied_since(self, address: str, since: date) -> bool:
        """Is there mail from `address` in the mailbox on or after `since`? All
        Mail where the provider has one (it holds archived and filtered mail),
        else the inbox."""
        folder = self.folders.get("all") or self.folders["inbox"]
        found = self._search(folder, "FROM", f'"{address}"', "SINCE", imap_date(since))
        return bool(found)

    def has_sent(self, message_id: str) -> bool:
        """Is this Message-ID in the Sent folder (found by its \\Sent flag)?"""
        folder = self.folders.get("sent")
        if not folder:
            raise SendError(TEMPORARY, "the mailbox has no folder flagged \\Sent, so a send "
                            "that may have gone out cannot be checked")
        bare = message_id.strip().strip("<>")
        return bool(self._search(folder, "HEADER", "Message-ID", f'"{bare}"'))

    def fetch(self, folder: str, numbers: list[bytes]) -> list[bytes]:
        out = []
        try:
            for number in numbers:
                typ, parts = self.conn.fetch(number, "(BODY.PEEK[])")
                raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and len(p) > 1),
                           None)
                if typ == "OK" and raw:
                    out.append(raw)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise SendError(TEMPORARY, f"reading mail failed: {_imap_text(exc)}") from exc
        return out

    def reports_since(self, since: date) -> list[bytes]:
        """Raw delivery reports (from mailer-daemon or postmaster) since `since`."""
        folder = self.folders.get("all") or self.folders["inbox"]
        numbers: list[bytes] = []
        for sender in ("mailer-daemon", "postmaster"):
            numbers += self._search(folder, "FROM", f'"{sender}"', "SINCE", imap_date(since))
        seen, unique = set(), []
        for n in numbers:
            if n not in seen:
                seen.add(n)
                unique.append(n)
        return self.fetch(folder, unique)


# ----------------------------------------------------------- state and lock


def runtime_dir(root: Path | str) -> Path:
    """Inside .git when there is one: runtime state is never a file in the data,
    so it is never committed and needs no .gitignore line."""
    git = Path(root) / ".git"
    return git if git.is_dir() else Path(root)


@dataclass
class SendState:
    """Why sending is paused beyond the Pause button (which is config
    `send_paused`): a login that fails, a daily quota, a bounce spike. Kept in
    `.git/hermitcrm-send.json`. A damaged file reads as paused: fail closed."""

    root: Path
    paused: bool = False
    kind: str = ""
    message: str = ""
    since: str = ""
    until: str = ""          # a quota pause ends by itself at the next window
    bounce_scan: str = ""    # when delivery reports were last read
    damaged: bool = False

    @property
    def path(self) -> Path:
        return runtime_dir(self.root) / STATE_FILE

    @classmethod
    def load(cls, root: Path | str) -> "SendState":
        state = cls(root=Path(root))
        try:
            data = json.loads(state.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except FileNotFoundError:
            return state
        except (OSError, ValueError) as exc:
            state.damaged, state.paused, state.kind = True, True, "state"
            state.message = (f"{state.path} cannot be read ({exc}); press Resume once you have "
                             "checked the Sent folder")
            return state
        state.paused = bool(data.get("paused"))
        for key in ("kind", "message", "since", "until", "bounce_scan"):
            setattr(state, key, str(data.get(key) or ""))
        return state

    def save(self) -> None:
        data = {"paused": self.paused, "kind": self.kind, "message": self.message,
                "since": self.since, "until": self.until, "bounce_scan": self.bounce_scan}
        self.path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")
        self.damaged = False

    def pause(self, kind: str, message: str, now: datetime, until: datetime | None = None):
        self.paused, self.kind, self.message = True, kind, message
        self.since = now.strftime("%Y-%m-%dT%H:%M")
        self.until = until.strftime("%Y-%m-%dT%H:%M") if until else ""
        self.save()

    def resume(self) -> bool:
        """Clear the pause; True when there was one."""
        was = self.paused
        self.paused, self.kind, self.message, self.since, self.until = False, "", "", "", ""
        self.save()
        return was

    def is_paused(self, now: datetime) -> bool:
        if self.paused and self.kind == QUOTA and self.until and not self.damaged:
            if now.strftime("%Y-%m-%dT%H:%M") >= self.until:
                self.resume()
        return self.paused

    def mark_scan(self, now: datetime) -> None:
        self.bounce_scan = now.strftime("%Y-%m-%dT%H:%M")
        self.save()


class SendLock:
    """At most one send at a time across processes: a non-blocking flock on a file
    in .git (a plain exclusive file where there is no fcntl). `wait` seconds of
    patience for Send now; the worker passes 0 and simply stops when another
    tick holds it."""

    def __init__(self, root: Path | str, wait: float = 0.0):
        self.path = runtime_dir(root) / LOCK_FILE
        self.wait = wait
        self._file = None

    def __enter__(self) -> "SendLock":
        deadline = time.monotonic() + self.wait
        while True:
            if self._try():
                return self
            if time.monotonic() >= deadline:
                raise SendBusy("another send is running; try again in a moment")
            time.sleep(0.2)

    def _try(self) -> bool:
        if fcntl is None:        # pragma: no cover
            try:
                self._file = open(self.path, "x")
                return True
            except FileExistsError:
                if time.time() - self.path.stat().st_mtime > 600:
                    self.path.unlink(missing_ok=True)
                return False
        handle = open(self.path, "a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._file = handle
        return True

    def __exit__(self, *exc) -> None:
        if self._file is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(self._file, fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None
                if fcntl is None:    # pragma: no cover
                    self.path.unlink(missing_ok=True)


class SendBusy(Exception):
    """Another send holds the lock."""


# ------------------------------------------------------------- caps, history


def sent_history(store: Store) -> list[sendplan.Sent]:
    """Every email the app has sent (interactions with source outreach), for the
    caps and the company spread. Mail you send from Gmail yourself is not here."""
    out = []
    for company in store.companies.values():
        for it in company.interactions:
            if it.source == "outreach" and it.channel == "email" and it.direction == "out" \
                    and it.date is not None:
                contact = company.contacts.get(it.contact)
                out.append(sendplan.Sent(when=it.date, company=company.slug,
                                         domain=_domain(contact.email if contact else "")))
    return sorted(out, key=lambda s: s.when)


def _domain(address: str) -> str:
    return normalise_email(address).rpartition("@")[2]


def cap_status(store: Store, settings: SendSettings, now: datetime,
               history: list | None = None) -> tuple[int, int]:
    """(sent today, today's cap)."""
    history = history if history is not None else sent_history(store)
    counts = sendplan.count_by_day(history)
    cap = sendplan.day_cap(now.date(), sendplan.first_send_day(history), counts, settings.plan)
    return counts.get(now.date(), 0), cap


def next_window_start(now: datetime, settings: SendSettings) -> datetime:
    """The next time the window opens after `now` (tomorrow's, or the next send day's)."""
    start = settings.window[0]
    day = now.date()
    for _ in range(8):
        day += timedelta(days=1)
        if day.weekday() in settings.days:
            return datetime(day.year, day.month, day.day) + timedelta(minutes=start)
    return now + timedelta(days=1)


# ------------------------------------------------------------------- guards


def opt_out_problem(store: Store, item) -> str:
    """'' unless a cold first email lost the opt-out line. The line is optional: a
    playbook without `opt_out` adds none and nothing is checked. When it has one,
    the drafter adds it to the body and here we check it is still there."""
    if item.channel != "email" or item.kind != outreach.FIRST_TOUCH:
        return ""
    rules = outreach.channel_rules(item.channel, messaging.load_messages(store.root))
    if not rules.get("opt_out", True):
        return ""
    line = outreach.opt_out_line(store.root, item.kind, item.channel, item.language or "en",
                                 rules)
    if not line:
        return ""
    if outreach._norm_space(line) not in outreach._norm_space(item.body):
        return "the opt-out line from the playbook is missing from the text"
    return ""


def local_hold(store: Store, item, settings: SendSettings, *, scheduled: bool,
               config: dict | None = None) -> str:
    """The guards that need no mailbox. '' = nothing holds it, else the reason in
    plain words (it becomes the item's `send_note`)."""
    if item.channel != "email":
        return "only email is sent from the app (LinkedIn is a session)"
    if scheduled and item.send_hash and item.send_hash != text_hash(item.subject, item.body):
        return "the text changed after it was scheduled"
    company = store.get(item.company)
    contact = company.contacts.get(item.contact) if company is not None else None
    if company is None or contact is None:
        return "the contact is not in the CRM any more"
    if not valid_email(contact.email):
        return f"{contact.name} has no email address"
    try:
        listed = suppress.lookup(store.root, contact.email)
    except suppress.SuppressError as exc:
        raise SendError(REFUSED, str(exc)) from exc
    if listed is not None:
        return f"{contact.email} is on the suppression list ({listed.reason}, {listed.date})"
    if company.is_sample:
        return "it is the made-up sample account"
    if not store.stages.is_open(company.stage):
        return f"the company is {company.stage} now"
    if do_not_contact(company, contact):
        return f"tagged {outreach.DO_NOT_CONTACT}"
    if item.approach:
        approach = playbook.load(store.root).approach(item.approach)
        if approach is not None:
            dq = playbook.disqualify(company, approach)
            if dq.reasons:
                return "disqualified: " + "; ".join(dq.reasons)
    country = (company.country or "").upper()
    if country and country in settings.block_countries:
        return (f"email to {country} is switched off in Settings > Sending; "
                "use LinkedIn for this one")
    if item.ready is not None:
        wrote = [i for i in company.interactions if i.direction == "in" and i.date is not None
                 and i.date > item.ready]
        if wrote:
            latest = max(i.date for i in wrote)
            return f"they wrote to you on {latest:%d %b}"
    now_problems = [p for p in outreach.check_item(store, item, config)
                    if p not in item.checks]
    if now_problems:
        return "a check fails now that did not when it was approved: " + now_problems[0]
    if scheduled:
        problem = opt_out_problem(store, item)
        if problem:
            return problem
    return ""


def mailbox_hold(item, address: str, box: Mailbox) -> str:
    """The reply guard against the sending mailbox itself: mail from the contact
    since the day the item was approved."""
    if item.ready is not None and box.replied_since(address, item.ready.date()):
        return (f"they wrote to you since {item.ready:%d %b} (found in the sending "
                "mailbox)")
    return ""


def hold(store: Store, item, reason: str, now: datetime) -> outreach.Item:
    """Put a queued item back to `ready` with the reason; nothing is dropped
    silently, the person decides. One commit."""
    fresh = outreach._refresh(store, item.id)
    fresh.state, fresh.send_note = "ready", reason
    fresh.queued = fresh.send_at = None
    fresh.send_hash = ""
    message = f"outreach: hold {fresh.record}: {reason}"
    with store.lock:
        outreach.write_item(store.root, fresh)
        store.notify(message, [fresh.path])
    return fresh


# ----------------------------------------------------------------- delivery


@dataclass
class Outcome:
    kind: str                      # sent | recovered | held | paused | retry | failed
    item: outreach.Item
    detail: str = ""
    warnings: list = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.kind in ("sent", "recovered")


def deliver(store: Store, item_id: str, *, settings: SendSettings, now: datetime | None = None,
            scheduled: bool = True, smtp_factory=None, imap_factory=None,
            password: str | None = None, config: dict | None = None,
            state: SendState | None = None, new_id=new_message_id) -> Outcome:
    """Send one approved item: guards, Message-ID first, SMTP, log. `scheduled`
    False is Send now (a ready or failed item; the text hash is not checked and a
    missing opt-out line is a warning). Never raises for a send problem: the
    Outcome says what happened and the item is left in the right state."""
    root = store.root
    now = now or store.now()
    item = outreach._refresh(store, item_id)
    allowed = ("queued",) if scheduled else ("ready", "queued", "failed")
    if item.state not in allowed:
        raise outreach.OutreachError(f"{item.id} is {item.state}; only a "
                                     f"{' or '.join(allowed)} item can be sent")
    state = state or SendState.load(root)
    config = config if config is not None else load_config(root)
    warnings: list[str] = []
    attempted = bool(item.message_id)       # written before SMTP: it may have gone out
    wrote = False                           # this run counted its try (see _write_attempt)
    try:
        # A new send checks the cheap guards first. One that was attempted before asks
        # Sent first: if it went out, log it, whatever the guards would say now.
        why = "" if attempted else local_hold(store, item, settings, scheduled=scheduled,
                                              config=config)
        if why:
            return _held(store, item, why, now, scheduled)
        pw = password or get_password(settings, root)
        if settings.imap_host:
            with Mailbox(settings, pw, imap_factory) as box:
                if attempted and box.has_sent(item.message_id):
                    OutreachLogger(store, now).log(item, outreach.SendResult(True, "in Sent"))
                    return Outcome("recovered", outreach._refresh(store, item.id),
                                   "it had gone out before the last run stopped; logged now")
                if attempted:
                    why = local_hold(store, item, settings, scheduled=scheduled, config=config)
                why = why or mailbox_hold(item, _address(store, item), box)
        elif attempted:
            why = local_hold(store, item, settings, scheduled=scheduled, config=config)
        if why:
            return _held(store, item, why, now, scheduled)
        if not scheduled:
            warnings += [w for w in (opt_out_problem(store, item),) if w]
        _write_attempt(store, item, settings, new_id)
        wrote = True
        sent = SmtpSender(store, settings, pw, smtp_factory).send(item)
        OutreachLogger(store, now).log(item, sent)
    except SendError as err:
        return _failed_send(store, outreach._refresh(store, item.id), err, settings, now,
                            state, counted=wrote)
    return Outcome("sent", outreach._refresh(store, item.id), sent.detail, warnings)


def _address(store: Store, item) -> str:
    company = store.get(item.company)
    contact = company.contacts.get(item.contact) if company is not None else None
    return normalise_email(contact.email) if contact is not None else ""


def _write_attempt(store: Store, item, settings: SendSettings, new_id) -> None:
    """Step 2: the Message-ID and the try, on disk and committed, before SMTP."""
    item.message_id = item.message_id or new_id(settings.domain)
    item.send_tries += 1
    with store.lock:
        outreach.write_item(store.root, item)
        store.notify(f"outreach: sending {item.record} ({item.id})", [item.path])


def _held(store: Store, item, reason: str, now: datetime, scheduled: bool) -> Outcome:
    if scheduled:
        return Outcome("held", hold(store, item, reason, now), reason)
    return Outcome("held", item, reason)       # Send now: say why, change nothing


def _failed_send(store: Store, item, err: SendError, settings: SendSettings, now: datetime,
                 state: SendState, counted: bool = True) -> Outcome:
    """Step 8: what each kind of error does (the table in the spec). `counted` is
    whether this run already counted its try; one that failed before the SMTP call
    (the mailbox could not be reached) still counts, or it would be retried forever."""
    if err.kind in (AUTH, REFUSED):
        state.pause(err.kind, err.text, now)
        return Outcome("paused", item, f"sending is paused: {err.text}")
    if err.kind == QUOTA:
        state.pause(QUOTA, err.text, now, until=next_window_start(now, settings))
        return Outcome("paused", item, f"the daily quota is reached ({err.text}); sending "
                       "resumes at the next window")
    if err.kind == RECIPIENT:
        return _fail_item(store, item, err, now, suppressed=True)
    if not counted:
        item.send_tries += 1
    if item.send_tries >= MAX_TRIES:
        return _fail_item(store, item, err, now, suppressed=False,
                          prefix=f"gave up after {item.send_tries} tries: ")
    item.state, item.send_error = "queued", err.text
    item.queued = item.queued or now
    item.send_hash = item.send_hash or text_hash(item.subject, item.body)
    item.send_at = (now + timedelta(minutes=RETRY_MINUTES)).replace(second=0, microsecond=0)
    with store.lock:
        outreach.write_item(store.root, item)
        store.notify(f"outreach: retry {item.record} at {item.send_at:%H:%M}: {err.text}",
                     [item.path])
    return Outcome("retry", item, f"not sent ({err.text}); it will try again at "
                   f"{item.send_at:%H:%M}")


def _fail_item(store: Store, item, err: SendError, now: datetime, suppressed: bool,
               prefix: str = "") -> Outcome:
    item.state, item.send_error = "failed", prefix + err.text
    item.queued = item.send_at = None
    item.send_hash = ""
    paths = [item.path]
    if suppressed:
        company = store.get(item.company)
        contact = company.contacts.get(item.contact) if company is not None else None
        if contact is not None and valid_email(contact.email):
            try:
                suppress.add(store.root, contact.email, "bounced", now.strftime("%Y-%m-%d"),
                             item.id)
                paths.append(suppress.FILE)
            except suppress.SuppressError:
                pass
    with store.lock:
        outreach.write_item(store.root, item)
        store.notify(f"outreach: failed {item.record}: {err.text}", paths)
    return Outcome("failed", item, item.send_error)


# ------------------------------------------------------------ send now, test


def send_now(store: Store, item_id: str, *, settings: SendSettings | None = None,
             now: datetime | None = None, smtp_factory=None, imap_factory=None,
             password: str | None = None, new_id=new_message_id) -> Outcome:
    """Send a ready item now: no window, no gap (a reply to interest should not wait
    for a slot), but it counts toward today's cap, and it is refused while sending
    is off or paused. It runs the same guards and the same send-and-log steps as
    the worker."""
    config = load_config(store.root)
    settings = settings or settings_from_config(config)
    now = now or store.now()
    if not settings.enabled:
        raise outreach.OutreachError("sending is off: turn it on in Settings > Sending")
    if settings.missing:
        raise outreach.OutreachError(settings.missing)
    state = SendState.load(store.root)
    if settings.paused:
        raise outreach.OutreachError("sending is paused (the Pause button); resume it first")
    if state.is_paused(now):
        raise outreach.OutreachError(f"sending is paused: {state.message}")
    count, cap = cap_status(store, settings, now)
    if count >= cap:
        raise outreach.OutreachError(f"today's cap of {cap} is reached ({count} sent); it "
                                     "can go out tomorrow, or raise the cap in Settings")
    try:
        with SendLock(store.root, wait=SEND_NOW_WAIT):
            return deliver(store, item_id, settings=settings, now=now, scheduled=False,
                           smtp_factory=smtp_factory, imap_factory=imap_factory,
                           password=password, config=config, state=state, new_id=new_id)
    except SendBusy as exc:
        raise outreach.OutreachError(str(exc)) from exc


@dataclass
class ProbeResult:
    ok: bool
    lines: list

    def text(self) -> str:
        return " ".join(self.lines)


def send_test(root: Path | str, config: dict | None = None, *, smtp_factory=None,
              imap_factory=None, password: str | None = None, now: datetime | None = None,
              to: str = "") -> ProbeResult:
    """Settings > Sending > Send a test to myself: log in to SMTP and IMAP and mail
    one line to the owner. A failure shows the server's exact reply. A passing
    test is what ends an auth pause."""
    config = config if config is not None else load_config(root)
    settings = settings_from_config(config)
    now = now or datetime.now()
    lines: list[str] = []
    if settings.missing:
        return ProbeResult(False, [settings.missing])
    target = normalise_email(to or config.get("owner_email") or settings.from_addr)
    try:
        pw = password or get_password(settings, root)
        msg = EmailMessage()
        msg["From"] = formataddr((settings.owner_name, settings.from_addr)) \
            if settings.owner_name else settings.from_addr
        msg["To"] = target
        msg["Subject"] = "Hermit CRM: sending works"
        msg["Date"] = format_datetime(now.astimezone())
        msg["Message-ID"] = new_message_id(settings.domain)
        msg.set_content("This is the test from Settings > Sending in Hermit CRM. If you can "
                        "read it, the app password and the SMTP settings are right.\n")
        conn = connect(settings, pw, smtp_factory)
        try:
            conn.send_message(msg)
        except BaseException as exc:
            raise classify_smtp(exc) from exc
        finally:
            _quit(conn)
        lines.append(f"Test mail sent to {target} through {settings.smtp_host}.")
    except SendError as err:
        return ProbeResult(False, [f"The test failed: {err.text}"])
    if settings.imap_host:
        try:
            with Mailbox(settings, pw, imap_factory) as box:
                note = "" if box.folders.get("sent") else (
                    " (no folder flagged \\Sent: a send that may have gone out cannot be "
                    "double-checked)")
                lines.append(f"IMAP login to {settings.imap_host} works{note}.")
        except SendError as err:
            return ProbeResult(False, [*lines, f"IMAP failed, so the reply guard cannot "
                                      f"run: {err.text}"])
    state = SendState.load(root)
    if state.paused and state.kind in (AUTH, REFUSED, "state"):
        state.resume()
        lines.append("Sending was paused by a login problem; it can run again.")
    return ProbeResult(True, lines)


def login_check(root: Path | str, config: dict | None = None, *, smtp_factory=None,
                imap_factory=None, password: str | None = None) -> list[tuple[str, str, str]]:
    """For doctor: log in to SMTP and IMAP without sending anything. Rows of
    (name, status, detail) with status ok/warn/fail."""
    config = config if config is not None else load_config(root)
    settings = settings_from_config(config)
    if settings.missing:
        return [("smtp login", "fail", settings.missing)]
    rows = []
    try:
        pw = password or get_password(settings, root)
        _quit(connect(settings, pw, smtp_factory))
        rows.append(("smtp login", "ok", f"{settings.smtp_user} on {settings.smtp_host}"))
    except SendError as err:
        return [("smtp login", "fail", err.text)]
    if settings.imap_host:
        try:
            with Mailbox(settings, pw, imap_factory):
                pass
            rows.append(("send imap login", "ok", f"{settings.smtp_user} on {settings.imap_host}"))
        except SendError as err:
            rows.append(("send imap login", "fail", err.text))
    return rows
