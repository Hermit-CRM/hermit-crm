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

"""Default mail connections that verify the server's certificate and host name.

`imaplib.IMAP4_SSL` and `smtplib.SMTP_SSL` called without a context do not check
the certificate, so anyone on the path could read the app password. These
factories (same call shape as the test fakes: host, port, timeout=) always pass
`ssl.create_default_context()`, which requires a valid certificate for the host.
(`smtp`, for port 587, connects in the clear; `send.connect` then upgrades it
with STARTTLS and that same verifying context before it logs in.)

The SMTP factories also name the client themselves. Left to itself, smtplib
asks DNS for this computer's full name (`socket.getfqdn`) on every connection,
for its EHLO greeting; on a network that cannot answer, that lookup hangs for
about 30 seconds before every send. Instead the connection says the address it
connected from, as an address literal (`[192.0.2.10]`), which RFC 5321 allows
when there is no domain name and which is what smtplib itself falls back to
when the computer's name has no dot. No lookup, and the computer's name is
not sent."""

from __future__ import annotations

import imaplib
import smtplib
import ssl


# Given to smtplib so it does not look the name up; replaced by the address
# literal as soon as the connection is open (see `_named`).
_UNNAMED = "localhost"


def address_literal(address: str) -> str:
    """This end's IP address as an EHLO name: `[192.0.2.10]`, `[IPv6:2001:db8::1]`."""
    address = address.split("%", 1)[0]  # an IPv6 scope (fe80::1%en0) is local only
    return f"[IPv6:{address}]" if ":" in address else f"[{address}]"


def _named(conn):
    """Name the client by the address it connected from (a real connection has a
    socket; a test double may not, and is returned as it is)."""
    sock = getattr(conn, "sock", None)
    if sock is not None:
        conn.local_hostname = address_literal(sock.getsockname()[0])
    return conn


def smtp(host: str, port: int, timeout: float | None = None) -> smtplib.SMTP:
    return _named(smtplib.SMTP(host, port, timeout=timeout, local_hostname=_UNNAMED))


def smtp_ssl(host: str, port: int, timeout: float | None = None) -> smtplib.SMTP_SSL:
    return _named(smtplib.SMTP_SSL(host, port, timeout=timeout, local_hostname=_UNNAMED,
                                   context=ssl.create_default_context()))


def imap_ssl(host: str, port: int = 993, timeout: float | None = None) -> imaplib.IMAP4_SSL:
    return imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(),
                             timeout=timeout)
