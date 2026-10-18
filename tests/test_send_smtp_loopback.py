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

"""The real smtplib against a tiny SMTP server on 127.0.0.1 (STARTTLS, AUTH, DATA):
the in-memory doubles prove the logic, this proves send.py calls smtplib correctly.
Loopback only: nothing leaves the machine. Skipped where openssl is not installed."""

from __future__ import annotations

import base64
import shutil
import socket
import ssl
import subprocess
import threading
from email import message_from_bytes, policy

import pytest

from hermitcrm import outreach, send

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")


@pytest.fixture
def server(tmp_path, monkeypatch):
    key, cert = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                    "-out", str(cert), "-days", "1", "-subj", "/CN=localhost"], check=True,
                   capture_output=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    box = {"mail": [], "auth": [], "port": listener.getsockname()[1], "password": "right"}

    def read_line(f):
        return f.readline().decode("utf-8", "replace").rstrip("\r\n")

    def serve(conn):
        f, tls = conn.makefile("rwb"), False
        def say(text):
            f.write(text.encode() + b"\r\n")
            f.flush()
        say("220 loopback ESMTP")
        try:
            while True:
                line = read_line(f)
                verb = line.split(" ", 1)[0].upper()
                if verb == "EHLO":
                    say("250-loopback")
                    say("250 AUTH PLAIN LOGIN" if tls else "250 STARTTLS")
                elif verb == "STARTTLS":
                    say("220 go ahead")
                    conn = context.wrap_socket(conn, server_side=True)
                    f, tls = conn.makefile("rwb"), True
                elif verb == "AUTH":
                    _, user, password = base64.b64decode(line.split()[-1]).decode().split("\0")
                    box["auth"].append((user, password))
                    say("235 2.7.0 Accepted" if password == box["password"] else
                        "535 5.7.8 Username and Password not accepted. For more information, "
                        "go to https://support.example.com/BadCredentials")
                elif verb in ("MAIL", "RCPT"):
                    say("250 2.1.0 OK")
                elif verb == "DATA":
                    say("354 go on")
                    data = b""
                    while not data.endswith(b"\r\n.\r\n"):
                        data += f.readline()
                    box["mail"].append(data[:-5])
                    say("250 2.0.0 OK queued")
                elif verb == "QUIT":
                    say("221 bye")
                    break
                elif verb == "":
                    break
                else:
                    say("250 OK")
        finally:
            conn.close()

    def accept():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            threading.Thread(target=serve, args=(conn,), daemon=True).start()

    threading.Thread(target=accept, daemon=True).start()
    loose = ssl.create_default_context()
    loose.check_hostname, loose.verify_mode = False, ssl.CERT_NONE
    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: loose)
    yield box
    listener.close()


def settings(port):
    return send.settings_from_config({
        "send_from": "cold@mail.example.net", "owner_name": "Sam Example",
        "send_smtp_host": "127.0.0.1", "send_smtp_port": port, "send_imap_host": "",
        "my_addresses": ["cold@mail.example.net"]})


def test_the_real_smtplib_logs_in_over_starttls_and_delivers_the_message(server):
    s = settings(server["port"])
    item = outreach.Item(id="x", company="c", contact="p", subject="Your second office",
                         body="Hi Mara,\n\nOne question: where does it hurt most?\n\nSam\n")
    msg = send.build_message(item, "mara@example.org", s, message_id="<l.1@mail.example.net>")
    conn = send.connect(s, "right")
    conn.send_message(msg)
    send._quit(conn)
    assert server["auth"] == [("cold@mail.example.net", "right")]
    (raw,) = server["mail"]
    got = message_from_bytes(raw, policy=policy.default)
    assert got["From"] == "Sam Example <cold@mail.example.net>" and got["To"] == "mara@example.org"
    assert got["Message-ID"] == "<l.1@mail.example.net>" and got["Subject"] == "Your second office"
    assert got.get_content().replace("\r\n", "\n").rstrip("\n") == item.body.rstrip("\n")


def test_a_wrong_password_comes_back_as_the_servers_own_words(server):
    s = settings(server["port"])
    with pytest.raises(send.SendError) as caught:
        send.connect(s, "wrong")
    assert caught.value.kind == send.AUTH
    assert len(server["auth"]) == 1                 # one failed login, not PLAIN and then LOGIN
    assert caught.value.text.startswith("535 5.7.8 Username and Password not accepted")
    assert "BadCredentials" in caught.value.text


def test_the_test_mail_goes_through_the_real_smtplib(server, tmp_path):
    from hermitcrm.datafolder import init_folder
    from hermitcrm.setup import set_config_values
    root = init_folder(tmp_path / "crm")
    s = settings(server["port"])
    set_config_values(root / "config.toml", {
        "send_from": "cold@mail.example.net", "owner_email": "sam@example.com",
        "my_addresses": ["cold@mail.example.net"], "send_smtp_host": "127.0.0.1",
        "send_smtp_port": s.smtp_port, "send_imap_host": ""})
    result = send.send_test(root, password="right")
    assert result.ok and "Test mail sent to sam@example.com" in result.text()
    got = message_from_bytes(server["mail"][0], policy=policy.default)
    assert got["To"] == "sam@example.com" and got["Subject"] == "Hermit CRM: sending works"
    bad = send.send_test(root, password="nope")
    assert not bad.ok and "The test failed: 535 5.7.8" in bad.text()
