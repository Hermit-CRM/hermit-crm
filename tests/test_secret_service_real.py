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

"""The real secret-tool against a real Secret Service, for the CI keyring job
(.github/workflows/test.yml). Skipped everywhere else: it would touch the
developer's own keyring. HERMITCRM_KEYRING_CI says what the job set up:

- "no-daemon": secret-tool and a D-Bus session, but nothing serving secrets;
- "running": gnome-keyring-daemon with an unlocked login keyring.
"""

import os
import subprocess
import uuid

import pytest

from hermitcrm import secrets

MODE = os.environ.get("HERMITCRM_KEYRING_CI", "")
pytestmark = [pytest.mark.real_secret_service,
              pytest.mark.skipif(not MODE, reason="needs the CI keyring job")]


@pytest.mark.skipif(MODE != "no-daemon", reason="for the no-daemon step")
def test_no_secret_service_reads_as_unavailable(tmp_path):
    usable, detail = secrets.secret_service_status()
    assert not usable, detail
    assert secrets.os_store("linux") is None
    assert secrets.get("bcc_password", tmp_path, {"bcc_keychain_service": "crm-bcc"},
                       account="me@example.com", env=dict(os.environ),
                       platform="linux") == ""


@pytest.mark.skipif(MODE != "running", reason="for the running-keyring step")
def test_store_and_read_through_the_real_secret_service(tmp_path):
    assert secrets.secret_service_status() == (True, "Secret Service reachable (secret-tool)")
    assert secrets.os_store("linux") == secrets.SECRET_SERVICE
    service, value = f"hermitcrm-ci-{uuid.uuid4().hex[:8]}", "abcd efgh ijkl mnop"
    assert secrets.os_store_save(secrets.SECRET_SERVICE, service, "me@example.com", value,
                                 label="Hermit CRM CI")
    try:
        assert secrets.get("bcc_password", tmp_path, {"bcc_keychain_service": service},
                           account="me@example.com", platform="linux") == value
        assert secrets.get("bcc_password", tmp_path, {"bcc_keychain_service": service},
                           account="someone-else@example.com", platform="linux") == ""
    finally:
        subprocess.run(["secret-tool", "clear", "service", service,
                        "account", "me@example.com"], check=False)
