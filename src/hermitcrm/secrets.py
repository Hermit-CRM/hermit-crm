"""Secrets (the Gmail app password, the calendar ICS URL) never live in config.toml.

``get(name, data_dir, config)`` looks in this order and returns '' if nothing is set:

1. the environment: ``HERMITCRM_<NAME>`` (and a legacy alias, see LEGACY_ENV);
2. ``<data>/.secrets.toml`` (``name = "value"``); a warning is logged when the
   file is readable by anyone but you (mode broader than 600);
3. on macOS, the Keychain: service from config ``<name>_keychain_service`` (or
   the older ``bcc_keychain_service`` / ``calendar_keychain_service``), account
   from config ``<name>_keychain_account`` (or the caller, e.g. the IMAP user).

``set(name, value, data_dir)`` writes ``.secrets.toml`` with mode 600.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

logger = logging.getLogger("hermitcrm.secrets")

SECRETS_FILE = ".secrets.toml"
NAMES = ("bcc_password", "calendar_ics_url")
LEGACY_ENV = {"bcc_password": "CRM_BCC_PASSWORD", "calendar_ics_url": "CRM_CALENDAR_URL"}
# The config prefix older data folders use for the Keychain service/account.
CONFIG_PREFIX = {"bcc_password": "bcc", "calendar_ics_url": "calendar"}


def env_name(name: str) -> str:
    return f"HERMITCRM_{name.upper()}"


def _check_name(name: str) -> None:
    if name not in NAMES:
        raise ValueError(f"unknown secret {name!r} (known: {', '.join(NAMES)})")


def _read_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            logger.warning("%s has mode %o; run: chmod 600 %s", path, mode, path)
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("unreadable %s: %s", path, exc)
        return {}


def _config_value(config: dict, name: str, suffix: str) -> str:
    for key in (f"{name}_{suffix}", f"{CONFIG_PREFIX.get(name, name)}_{suffix}"):
        value = str(config.get(key) or "").strip()
        if value:
            return value
    return ""


def keychain_lookup(service: str, account: str, runner=subprocess.run) -> str:
    try:
        proc = runner(["security", "find-generic-password", "-s", service, "-a", account,
                       "-w"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.info("Keychain lookup for %s failed: %s", service, exc)
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def get(name: str, data_dir: Path | str | None, config: dict | None = None, *,
        account: str = "", env: dict | None = None, runner=subprocess.run,
        platform: str | None = None) -> str:
    """The secret's value, or '' when it is not set anywhere."""
    _check_name(name)
    env = os.environ if env is None else env
    config = config or {}
    for var in (env_name(name), LEGACY_ENV.get(name, "")):
        value = str(env.get(var, "") if var else "").strip()
        if value:
            return value
    if data_dir is not None:
        value = str(_read_file(Path(data_dir) / SECRETS_FILE).get(name, "")).strip()
        if value:
            return value
    if (platform or sys.platform) == "darwin":
        service = _config_value(config, name, "keychain_service")
        account = account or _config_value(config, name, "keychain_account")
        if service and account:
            return keychain_lookup(service, account, runner)
    return ""


def set(name: str, value: str, data_dir: Path | str) -> Path:  # noqa: A001
    """Store a secret in ``<data>/.secrets.toml`` (mode 600), keeping other keys."""
    _check_name(name)
    path = Path(data_dir) / SECRETS_FILE
    values = _read_file(path)
    values[name] = str(value)
    text = "".join(f"{k} = {json.dumps(str(v), ensure_ascii=False)}\n"
                   for k, v in sorted(values.items()))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)
    return path
