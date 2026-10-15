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

"""The "no telemetry" promise (README, DISCLAIMER, website), kept checkable.

FastAPI 0.143 pulls in `opentelemetry-api` as a hard dependency. The API alone
records into no-op proxies and sends nothing; data could only leave the machine
if an OpenTelemetry SDK and an exporter were installed and switched on (FastAPI
does that at lifespan startup when FASTAPI_OTEL_AUTO_CONFIGURE=true and an OTLP
endpoint is set). These tests fail as soon as any of that creeps in.
"""

from __future__ import annotations

import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm.web import create_app

CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "owner_email": "me@example.com",
          "welcome_dismissed": True, "disclaimer_accepted": "2026-09-01T09:00:00"}

# Module prefixes that mean something could record or ship data somewhere.
FORBIDDEN_MODULES = ("opentelemetry.sdk", "opentelemetry.exporter",
                     "opentelemetry.instrumentation", "opentelemetry.distro")


def _forbidden_distribution(name: str) -> bool:
    name = name.lower().replace("_", "-")
    return (name in ("opentelemetry-sdk", "opentelemetry-distro")
            or name.startswith(("opentelemetry-exporter", "opentelemetry-instrumentation")))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for args in (["init", "-b", "main"], ["config", "user.name", "CRM Test"],
                 ["config", "user.email", "crm@test.local"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    return tmp_path


def test_a_request_loads_no_sdk_and_configures_no_provider(repo: Path, monkeypatch) -> None:
    # Test what a user gets by default, whatever the developer's shell exports.
    for key in list(os.environ):
        if key.startswith(("OTEL_", "FASTAPI_OTEL_")):
            monkeypatch.delenv(key)

    app = create_app(repo, config=CONFIG)
    app.state.setup_redirected = True
    # The context manager runs lifespan startup, where FastAPI would set up export.
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/").status_code < 500

    loaded = sorted(m for m in sys.modules if m.startswith(FORBIDDEN_MODULES))
    assert loaded == []

    try:
        from opentelemetry import _logs, metrics, trace
    except ImportError:  # an older FastAPI without OpenTelemetry: nothing to check
        return
    # Still the API's no-op proxies: nobody installed a real provider.
    assert type(trace.get_tracer_provider()).__name__ == "ProxyTracerProvider"
    assert type(metrics.get_meter_provider()).__name__ == "_ProxyMeterProvider"
    assert type(_logs.get_logger_provider()).__name__ == "ProxyLoggerProvider"


def test_no_sdk_or_exporter_is_installed() -> None:
    installed = sorted({d.metadata["Name"] for d in metadata.distributions()
                        if d.metadata["Name"] and _forbidden_distribution(d.metadata["Name"])})
    assert installed == [], (
        f"{installed} would let telemetry leave the machine; Hermit CRM promises none")
