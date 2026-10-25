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

"""Shared test doubles for sending: an SMTP server and an IMAP server that live
in memory. No test touches the network; every address is on example.com."""

from __future__ import annotations

import imaplib
import re
import smtplib
from datetime import date, datetime
from email import message_from_bytes, policy

from hermitcrm import outreach
from hermitcrm.datafolder import init_folder
from hermitcrm.send import SendSettings, settings_from_config
from hermitcrm.store import Store, load_config

from outreach_fakes import NOW, demo  # noqa: F401  (re-exported for the tests)

MARA = ("lindenhof-data", "mara-keller")
GOOD_PASSWORD = "abcd efgh ijkl mnop"
SEND_CONFIG = {
    "send_enabled": True, "send_from": "sam@mail.example.com",
    "owner_name": "Sam Example", "owner_email": "sam@example.com",
    "my_addresses": ["sam@example.com", "sam@mail.example.com"],
}


class FakeSmtp:
    """One in-memory SMTP server. `factory` is what send.py is handed in place
    of smtplib.SMTP. Script failures with `login_error`, `send_errors` (a list
    consumed one per send; None = accept) and `connect_error`."""

    def __init__(self, login_error=None, send_errors=None, connect_error=None):
        self.login_error = login_error
        self.send_errors = list(send_errors or [])
        self.connect_error = connect_error
        self.sent = []            # EmailMessage objects accepted
        self.logins = []          # (host, port, user, password)
        self.starttls_used = False
        self.connections = 0

    def factory(self, host, port, timeout=None):
        if self.connect_error is not None:
            raise self.connect_error
        self.connections += 1
        return _SmtpConn(self, host, port)

    def to(self, address):
        return [m for m in self.sent if address in str(m["To"])]


class _SmtpConn:
    def __init__(self, server, host, port):
        self.server, self.host, self.port = server, host, port
        self.user = ""

    def ehlo(self):
        return (250, b"ok")

    def starttls(self, context=None):
        self.server.starttls_used = True
        return (220, b"ready")

    def login(self, user, password):
        self.server.logins.append((self.host, self.port, user, password))
        if self.server.login_error is not None:
            raise self.server.login_error
        self.user = user

    def send_message(self, msg, *args, **kwargs):
        if self.server.send_errors:
            err = self.server.send_errors.pop(0)
            if err is not None:
                raise err
        self.server.sent.append(msg)
        return {}

    def quit(self):
        return (221, b"bye")

    def close(self):
        return None


def auth_error(code=535, text=b"5.7.8 Username and Password not accepted. For more "
               b"information, go to https://support.google.com/mail/?p=BadCredentials x"):
    return smtplib.SMTPAuthenticationError(code, text)


def data_error(code, text):
    return smtplib.SMTPDataError(code, text)


def recipients_refused(address, code=550, text=b"5.1.1 The email account that you tried "
                       b"to reach does not exist."):
    return smtplib.SMTPRecipientsRefused({address: (code, text)})


class FakeImap:
    """An in-memory IMAP server. `folders` maps a folder name to a list of
    (raw bytes, internal date) messages; `flags` maps a name to its special-use
    flags. The default is a Gmail-shaped account."""

    def __init__(self, login_error=None, connect_error=None, search_error=None):
        self.login_error = login_error
        self.connect_error = connect_error
        self.search_error = search_error
        self.folders = {"INBOX": [], "[Gmail]/Sent Mail": [], "[Gmail]/All Mail": []}
        self.flags = {"INBOX": "", "[Gmail]/Sent Mail": r"\Sent", "[Gmail]/All Mail": r"\All"}
        self.logins = []
        self.searches = []
        self.selected = []

    def factory(self, host, port=993, timeout=None):
        if self.connect_error is not None:
            raise self.connect_error
        return _ImapConn(self)

    def deliver(self, folder, raw: bytes, when: date | datetime):
        day = when.date() if isinstance(when, datetime) else when
        self.folders[folder].append((raw, day))


class _ImapConn:
    def __init__(self, server):
        self.server = server
        self.current = None

    def login(self, user, password):
        self.server.logins.append((user, password))
        if self.server.login_error is not None:
            raise self.server.login_error
        return ("OK", [b"logged in"])

    def list(self):
        lines = []
        for name, flags in self.server.flags.items():
            lines.append(f'({flags} \\HasNoChildren) "/" "{name}"'.replace("( ", "(").encode())
        return ("OK", lines)

    def select(self, name, readonly=False):
        name = name.strip('"')
        self.server.selected.append(name)
        if name not in self.server.folders:
            return ("NO", [b"no such folder"])
        self.current = name
        return ("OK", [str(len(self.server.folders[name])).encode()])

    def search(self, charset, *criteria):
        if self.server.search_error is not None:
            raise self.server.search_error
        self.server.searches.append((self.current, criteria))
        found = []
        crit = [c.strip('"') if isinstance(c, str) else c for c in criteria]
        for number, (raw, day) in enumerate(self.server.folders.get(self.current, []), 1):
            msg = message_from_bytes(raw, policy=policy.default)
            ok = True
            for i, key in enumerate(crit):
                if key == "FROM":
                    ok = ok and crit[i + 1].lower() in str(msg.get("From", "")).lower()
                elif key == "SINCE":
                    ok = ok and day >= datetime.strptime(crit[i + 1], "%d-%b-%Y").date()
                elif key == "HEADER":
                    ok = ok and crit[i + 2] in str(msg.get(crit[i + 1], ""))
            if ok:
                found.append(str(number))
        return ("OK", [" ".join(found).encode()])

    def fetch(self, number, parts):
        raw, _ = self.server.folders[self.current][int(number) - 1]
        return ("OK", [(b"1 (RFC822 {%d}" % len(raw), raw), b")"])

    def logout(self):
        return ("BYE", [b"bye"])


def imap_error(text=b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)"):
    return imaplib.IMAP4.error(text)


def raw_mail(sender, to, subject, body="Hi\n", message_id="<r1@example.org>"):
    return (f"From: {sender}\r\nTo: {to}\r\nSubject: {subject}\r\nMessage-ID: {message_id}\r\n"
            f"Date: Mon, 19 Oct 2026 10:00:00 +0200\r\n\r\n{body}").encode()


def make_folder(tmp_path, config=None, name="crm"):
    """A demo folder with sending switched on and a Store that commits like the
    CLI does. Returns (root, store, settings)."""
    root, store = demo(tmp_path, name)
    from hermitcrm.setup import set_config_values
    cfg = {**SEND_CONFIG, **(config or {})}
    set_config_values(root / "config.toml", cfg)
    return root, store, settings_from_config(load_config(root))


def ready_item(root, store, *, item_id="2026-10-19T0800-email-lindenhof-data-mara-keller",
               subject="Your second office", body=None, state="ready", kind="first-touch",
               ready=None, company=MARA[0], contact=MARA[1], **extra):
    """Write a ready item for the demo contact and return it. The body carries
    the opt-out line the playbook's drafter would add."""
    body = body if body is not None else (
        "Hi Mara,\n\nThe second office this autumn caught my eye. Where does it hurt "
        "most right now: pipeline, conversion or deal size?\n\nSam\n\n"
        "If this is not for you, tell me and I will not write again.\n")
    item = outreach.Item(id=item_id, state=state, kind=kind, channel="email", company=company,
                         contact=contact, subject=subject, body=body, language="en",
                         ready=ready or NOW, created=NOW, drafted=NOW,
                         approach=extra.pop("approach", ""), **extra)
    outreach.write_item(root, item)
    return item
