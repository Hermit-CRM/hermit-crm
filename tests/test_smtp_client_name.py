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

"""The name Hermit gives itself in EHLO costs no DNS lookup (mailtls.py).

smtplib, left to itself, asks DNS for this computer's full name on every
connection (socket.getfqdn). On a network that cannot answer, that lookup hangs
for about 30 seconds before every send and every test mail. Hermit names the
connection by its own address instead, the address literal RFC 5321 allows when
there is no domain name: no lookup, and the computer's name stays private."""

from __future__ import annotations

import smtplib
import socket
import threading

import pytest

from hermitcrm import mailtls, send


@pytest.fixture
def no_dns_for_my_name(monkeypatch):
    def getfqdn(name=""):
        raise AssertionError("looked up this computer's name in DNS")

    monkeypatch.setattr(socket, "getfqdn", getfqdn)


@pytest.fixture
def ehlo_server():
    """A loopback SMTP server that answers EHLO and records what it was told."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    heard: list[str] = []

    def serve():
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        with conn, conn.makefile("rwb") as f:
            f.write(b"220 loopback ESMTP\r\n")
            f.flush()
            for raw in f:
                line = raw.decode().rstrip("\r\n")
                heard.append(line)
                if line.upper().startswith("QUIT"):
                    f.write(b"221 bye\r\n")
                    f.flush()
                    return
                f.write(b"250 loopback\r\n")
                f.flush()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield listener.getsockname()[1], heard
    listener.close()
    thread.join(timeout=5)


@pytest.mark.parametrize("address, literal", [
    ("192.0.2.10", "[192.0.2.10]"),
    ("2001:db8::1", "[IPv6:2001:db8::1]"),
    ("fe80::1%en0", "[IPv6:fe80::1]"),  # a link-local scope is not part of the address
])
def test_the_address_literal(address, literal):
    assert mailtls.address_literal(address) == literal


def test_the_starttls_connection_names_itself_by_its_address(ehlo_server, no_dns_for_my_name):
    port, heard = ehlo_server
    conn = mailtls.smtp("127.0.0.1", port, timeout=5)
    try:
        conn.ehlo()
    finally:
        conn.quit()
    assert heard[0] == "ehlo [127.0.0.1]"  # smtplib writes the verb in lower case


def test_the_ssl_factory_gives_smtplib_a_name_so_it_asks_no_dns(monkeypatch):
    recorded = {}

    def fake_ssl(*args, **kwargs):
        recorded.update(kwargs, args=args)
        return "connection"

    monkeypatch.setattr(smtplib, "SMTP_SSL", fake_ssl)
    assert mailtls.smtp_ssl("smtp.example.com", 465, timeout=12) == "connection"
    assert recorded["args"] == ("smtp.example.com", 465)
    assert recorded["local_hostname"]  # given, so smtplib never calls getfqdn


def test_the_starttls_factory_gives_smtplib_a_name_so_it_asks_no_dns(monkeypatch):
    recorded = {}

    def fake_smtp(*args, **kwargs):
        recorded.update(kwargs, args=args)
        return "connection"

    monkeypatch.setattr(smtplib, "SMTP", fake_smtp)
    assert mailtls.smtp("smtp.example.com", 587, timeout=12) == "connection"
    assert recorded["args"] == ("smtp.example.com", 587)
    assert recorded["timeout"] == 12
    assert recorded["local_hostname"]


def test_sending_on_587_uses_the_named_factory(monkeypatch):
    settings = send.SendSettings(smtp_host="smtp.example.com", smtp_port=587,
                                 smtp_user="me@example.com", imap_host="imap.example.com")
    called = []

    def sentinel(host, port, timeout=None):
        called.append((host, port))
        raise RuntimeError("sentinel")

    monkeypatch.setattr(mailtls, "smtp", sentinel)
    with pytest.raises(send.SendError):
        send.connect(settings, "pw")
    assert called == [("smtp.example.com", 587)]
