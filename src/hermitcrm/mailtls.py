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
the certificate, so anyone on the path could read the app password. These two
factories (same call shape as the test fakes: host, port, timeout=) always pass
`ssl.create_default_context()`, which requires a valid certificate for the host."""

from __future__ import annotations

import imaplib
import smtplib
import ssl


def smtp_ssl(host: str, port: int, timeout: float | None = None) -> smtplib.SMTP_SSL:
    return smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())


def imap_ssl(host: str, port: int = 993, timeout: float | None = None) -> imaplib.IMAP4_SSL:
    return imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(),
                             timeout=timeout)
