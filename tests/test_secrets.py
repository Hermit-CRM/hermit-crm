"""Secret lookup order: env, .secrets.toml, macOS Keychain; set() writes mode 600."""

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
