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

"""The default mail connections verify the server certificate and host name."""

from __future__ import annotations

import imaplib
import smtplib
import ssl

import pytest

from hermitcrm import bcc, mailtls, send


class Recorder:
    def __init__(self):
        self.args, self.kwargs = None, None

    def __call__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        return "connection"


def assert_verifying(ctx):
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_imap_ssl_passes_a_verifying_context(monkeypatch):
    recorded = Recorder()
    monkeypatch.setattr(imaplib, "IMAP4_SSL", recorded)
    assert mailtls.imap_ssl("imap.example.com", 993, timeout=12) == "connection"
    assert recorded.args == ("imap.example.com", 993)
    assert recorded.kwargs["timeout"] == 12
    assert_verifying(recorded.kwargs["ssl_context"])


def test_smtp_ssl_passes_a_verifying_context(monkeypatch):
    recorded = Recorder()
    monkeypatch.setattr(smtplib, "SMTP_SSL", recorded)
    assert mailtls.smtp_ssl("smtp.example.com", 465, timeout=12) == "connection"
    assert recorded.args == ("smtp.example.com", 465)
    assert recorded.kwargs["timeout"] == 12
    assert_verifying(recorded.kwargs["context"])


def test_the_defaults_are_the_verifying_factories(monkeypatch):
    settings = send.SendSettings(smtp_host="smtp.example.com", smtp_port=465,
                                 smtp_user="me@example.com", imap_host="imap.example.com")
    assert send.Mailbox(settings, "pw").factory is mailtls.imap_ssl
    assert bcc.GmailMailbox(bcc.Settings(address="me+bcc@example.com"), "pw").imap_factory \
        is mailtls.imap_ssl
    called = []

    def sentinel(host, port, timeout=None):
        called.append((host, port))
        raise RuntimeError("sentinel")

    monkeypatch.setattr(mailtls, "smtp_ssl", sentinel)
    with pytest.raises(send.SendError):
        send.connect(settings, "pw")
    assert called == [("smtp.example.com", 465)]
