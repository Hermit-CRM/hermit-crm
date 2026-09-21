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

"""Secret lookup order: env, .secrets.toml, the OS store (macOS Keychain, Linux
Secret Service); set() writes mode 600."""

import logging
import stat
import subprocess

import pytest

from hermitcrm import bcc, calendar_sync as cal, secrets


def keychain(value, calls=None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0 if value else 44, stdout=value + "\n")
    return run


CONFIG = {"bcc_keychain_service": "crm-bcc"}


def test_env_beats_file_beats_keychain(tmp_path):
    secrets.set("bcc_password", "from-file", tmp_path)
    kc = keychain("from-keychain")
    env = {"HERMITCRM_BCC_PASSWORD": "from-env", "CRM_BCC_PASSWORD": "legacy"}
    get = lambda env: secrets.get("bcc_password", tmp_path, CONFIG, account="me@example.com",
                                  env=env, runner=kc, platform="darwin")
    assert get(env) == "from-env"
    assert get({"CRM_BCC_PASSWORD": "legacy"}) == "legacy"
    assert get({}) == "from-file"
    (tmp_path / ".secrets.toml").unlink()
    assert get({}) == "from-keychain"


def test_keychain_uses_config_service_and_account(tmp_path):
    calls = []
    got = secrets.get("calendar_ics_url", tmp_path,
                      {"calendar_keychain_service": "crm-calendar",
                       "calendar_keychain_account": "ics"},
                      env={}, runner=keychain("webcal://x.example/a.ics", calls),
                      platform="darwin")
    assert got == "webcal://x.example/a.ics"
    assert calls == [["security", "find-generic-password", "-s", "crm-calendar", "-a", "ics", "-w"]]
    calls.clear()
    # The new-style key wins over the old prefix.
    secrets.get("calendar_ics_url", tmp_path,
                {"calendar_ics_url_keychain_service": "svc", "calendar_keychain_service": "old",
                 "calendar_ics_url_keychain_account": "acct"},
                env={}, runner=keychain("u", calls), platform="darwin")
    assert calls[0][3:6] == ["svc", "-a", "acct"]


def test_keychain_skipped_off_macos_and_on_errors(tmp_path):
    calls = []
    assert secrets.get("bcc_password", tmp_path, CONFIG, account="me@example.com", env={},
                       runner=keychain("pw", calls), platform="linux") == ""
    assert calls == []

    def broken(cmd, **kw):
        raise OSError("no security binary")

    assert secrets.get("bcc_password", tmp_path, CONFIG, account="me@example.com", env={},
                       runner=broken, platform="darwin") == ""
    with pytest.raises(ValueError):
        secrets.get("nope", tmp_path)


def test_set_writes_mode_600_and_keeps_other_keys(tmp_path):
    secrets.set("calendar_ics_url", 'https://x.example/a "b".ics', tmp_path)
    path = secrets.set("bcc_password", "pw", tmp_path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert secrets.get("calendar_ics_url", tmp_path, env={}, platform="linux") == \
        'https://x.example/a "b".ics'
    assert secrets.get("bcc_password", tmp_path, env={}, platform="linux") == "pw"


def test_broad_file_mode_warns(tmp_path, caplog):
    path = secrets.set("bcc_password", "pw", tmp_path)
    path.chmod(0o644)
    with caplog.at_level(logging.WARNING, logger="hermitcrm.secrets"):
        assert secrets.get("bcc_password", tmp_path, env={}, platform="linux") == "pw"
    assert "chmod 600" in caplog.text


def test_bcc_and_calendar_use_secrets(tmp_path):
    settings = bcc.Settings(address="me+bcc@example.com")
    calls = []
    assert bcc.keychain_password(settings, tmp_path, runner=keychain("abcd efgh", calls),
                                 env={}, platform="darwin") == "abcdefgh"
    assert calls[0] == ["security", "find-generic-password", "-s", "crm-bcc",
                        "-a", "me@example.com", "-w"]
    with pytest.raises(bcc.BccError, match="security add-generic-password -s crm-bcc"):
        bcc.keychain_password(settings, tmp_path, runner=keychain(""), env={}, platform="darwin")
    with pytest.raises(bcc.BccError, match="not set up"):
        bcc.open_gmail(bcc.Settings())
    cal_settings = cal.settings_from_config({})
    assert cal.resolve_url(cal_settings, tmp_path, env={"CRM_CALENDAR_URL": "u1"}) == "u1"
    assert "not set up" in cal.setup_hint(cal_settings)
    assert "security add-generic-password -s crm-calendar" in cal.setup_hint(
        cal_settings, platform="darwin")
    linux = cal.setup_hint(cal_settings, platform="linux")
    assert "calendar_ics_url to .secrets.toml" in linux
    assert "Keychain" not in linux and "security " not in linux


# ------------------------------------------------ Linux: the Secret Service

BUS = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
HAS_TOOL = lambda name: "/usr/bin/secret-tool" if name == "secret-tool" else None  # noqa: E731


def secret_tool(stored=None, calls=None, stderr=""):
    """A fake secret-tool: lookup prints the stored value (exit 1 when absent),
    store reads stdin. stderr simulates an unreachable service."""
    stored = {} if stored is None else stored

    def run(cmd, **kw):
        if calls is not None:
            calls.append((cmd, kw.get("input")))
        assert cmd[0] == "secret-tool"
        if stderr:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=stderr)
        key = (cmd[-3], cmd[-1])  # service, account
        if cmd[1] == "lookup":
            value = stored.get(key)
            return subprocess.CompletedProcess(cmd, 0 if value else 1,
                                               stdout=value or "", stderr="")
        stored[key] = kw["input"]
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return run


@pytest.fixture
def tool_installed(monkeypatch):
    monkeypatch.setattr(secrets, "_which", HAS_TOOL)


def test_linux_reads_the_secret_service(tmp_path, tool_installed):
    calls = []
    run = secret_tool({("crm-bcc", "me@example.com"): "from-keyring"}, calls)
    get = lambda: secrets.get("bcc_password", tmp_path, CONFIG,  # noqa: E731
                              account="me@example.com", env=BUS, runner=run,
                              platform="linux")
    assert get() == "from-keyring"
    assert calls == [(["secret-tool", "lookup", "service", "crm-bcc",
                       "account", "me@example.com"], None)]
    secrets.set("bcc_password", "from-file", tmp_path)
    assert get() == "from-file"  # the file still comes first
    # The calendar URL goes the same way, through its own service/account keys.
    run = secret_tool({("crm-calendar", "ics"): "https://x.example/a.ics"})
    assert secrets.get("calendar_ics_url", tmp_path,
                       {"calendar_keychain_service": "crm-calendar",
                        "calendar_keychain_account": "ics"},
                       env=BUS, runner=run, platform="linux") == "https://x.example/a.ics"


def test_linux_without_secret_tool_or_bus_never_runs_it(tmp_path, monkeypatch):
    calls = []
    run = secret_tool({("crm-bcc", "me@example.com"): "x"}, calls)
    get = lambda env: secrets.get("bcc_password", tmp_path, CONFIG,  # noqa: E731
                                  account="me@example.com", env=env, runner=run,
                                  platform="linux")
    assert get(BUS) == ""  # conftest: secret-tool is not installed
    monkeypatch.setattr(secrets, "_which", HAS_TOOL)
    assert get({}) == ""  # installed, but no session bus (headless, cron)
    assert calls == []
    # The systemd per-user socket counts as a bus even without the variable.
    (tmp_path / "bus").touch()
    assert get({"XDG_RUNTIME_DIR": str(tmp_path)}) == "x"


def test_linux_lookup_failures_read_as_unset(tmp_path, tool_installed):
    def raises(exc):
        def run(cmd, **kw):
            raise exc
        return run

    for run in (secret_tool(stderr="Cannot autolaunch D-Bus without X11 $DISPLAY"),
                raises(OSError("gone")),
                raises(subprocess.TimeoutExpired("secret-tool", 10))):
        assert secrets.get("bcc_password", tmp_path, CONFIG, account="me@example.com",
                           env=BUS, runner=run, platform="linux") == ""


def test_os_store_probe_per_platform(tool_installed):
    ok = secret_tool()  # nothing stored: exit 1, silent stderr = reachable
    assert secrets.os_store("darwin") == secrets.KEYCHAIN
    assert secrets.os_store("linux", runner=ok, env=BUS) == secrets.SECRET_SERVICE
    assert secrets.os_store("freebsd13", runner=ok, env=BUS) == secrets.SECRET_SERVICE
    assert secrets.os_store("win32", runner=ok, env=BUS) is None
    assert secrets.os_store("linux", runner=ok, env={}) is None
    dead = secret_tool(stderr="GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown")
    assert secrets.os_store("linux", runner=dead, env=BUS) is None
    usable, detail = secrets.secret_service_status(dead, BUS)
    assert not usable and "ServiceUnknown" in detail

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 5)

    assert "did not answer" in secrets.secret_service_status(slow, BUS)[1]
    assert "not installed" in secrets.secret_service_status(ok, BUS, lambda n: None)[1]
    assert "D-Bus" in secrets.secret_service_status(ok, {})[1]


def test_os_store_save_sends_the_secret_on_stdin(tool_installed):
    calls, stored = [], {}
    assert secrets.os_store_save(secrets.SECRET_SERVICE, "crm-bcc", "me@example.com",
                                 "s3cret", label="Hermit CRM app password",
                                 runner=secret_tool(stored, calls))
    argv, stdin = calls[0]
    assert argv == ["secret-tool", "store", "--label=Hermit CRM app password",
                    "service", "crm-bcc", "account", "me@example.com"]
    assert stdin == "s3cret" and "s3cret" not in " ".join(argv)
    assert stored == {("crm-bcc", "me@example.com"): "s3cret"}
    failing = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "dismissed")  # noqa: E731
    assert not secrets.os_store_save(secrets.SECRET_SERVICE, "s", "a", "v", runner=failing)
    assert not secrets.os_store_save("nothing", "s", "a", "v", runner=failing)


def test_unset_removes_one_key(tmp_path):
    assert not secrets.unset("bcc_password", tmp_path)  # no file yet
    secrets.set("bcc_password", "pw", tmp_path)
    path = secrets.set("calendar_ics_url", "https://x.example/a.ics", tmp_path)
    assert secrets.unset("bcc_password", tmp_path)
    assert not secrets.unset("bcc_password", tmp_path)
    assert "bcc_password" not in path.read_text()
    assert secrets.get("calendar_ics_url", tmp_path, env={}, platform="linux")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_hints_name_the_store_of_each_platform():
    settings = bcc.Settings(address="me+bcc@example.com")
    linux = bcc.password_hint(settings, "linux")
    assert "secret-tool store" in linux and "service crm-bcc account me@example.com" in linux
    assert "security" not in linux
    assert "security add-generic-password" in bcc.password_hint(settings, "darwin")
    windows = bcc.password_hint(settings, "win32")
    assert "secret-tool" not in windows and "security" not in windows
    cal_settings = cal.settings_from_config({})
    linux = cal.setup_hint(cal_settings, platform="linux")
    assert "secret-tool store" in linux and "service crm-calendar account ics" in linux
    assert "secret-tool" not in cal.setup_hint(cal_settings, platform="win32")
