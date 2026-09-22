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

"""Secrets (the Gmail app password, the calendar ICS URL) never live in config.toml.

``get(name, data_dir, config)`` looks in this order and returns '' if nothing is set:

1. the environment: ``HERMITCRM_<NAME>`` (and a legacy alias, see LEGACY_ENV);
2. ``<data>/.secrets.toml`` (``name = "value"``); a warning is logged when the
   file is readable by anyone but you (mode broader than 600);
3. the operating system's secret store: the Keychain on macOS (``security``),
   the freedesktop Secret Service on Linux and other Unixes (``secret-tool``
   from libsecret; GNOME Keyring, KWallet, KeePassXC). The service comes from
   config ``<name>_keychain_service`` (or the older ``bcc_keychain_service`` /
   ``calendar_keychain_service``), the account from config
   ``<name>_keychain_account`` (or the caller, e.g. the IMAP user). The config
   keys say "keychain" on every platform so config.toml keeps one shape.

``set(name, value, data_dir)`` writes ``.secrets.toml`` with mode 600;
``unset(name, data_dir)`` removes a key from it. ``os_store()`` says which OS
store is usable here and ``os_store_save()`` writes to it.

The Secret Service is reached over the D-Bus session bus. Without one (a
headless server, a cron job outside a login session) secret-tool is not run at
all: it would try to autolaunch D-Bus and fail or hang. Every failure reads as
"not set", so a missing or broken store never crashes anything.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
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

KEYCHAIN = "keychain"
SECRET_SERVICE = "secret-service"
STORE_LABELS = {KEYCHAIN: "the macOS Keychain",
                SECRET_SERVICE: "the system keyring (Secret Service)"}
SECRET_TOOL = "secret-tool"
# Looked up through this name so tests can make secret-tool "missing" everywhere.
_which = shutil.which


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


def _uses_secret_service(platform: str) -> bool:
    """Linux and the BSDs; not macOS (Keychain) and not Windows (no store)."""
    return not platform.startswith(("darwin", "win", "cygwin", "msys"))


def session_bus(env: dict | None = None) -> bool:
    """Whether a D-Bus session bus is reachable without autolaunching one: the
    address is in the environment, or the systemd per-user socket exists."""
    env = os.environ if env is None else env
    if str(env.get("DBUS_SESSION_BUS_ADDRESS") or "").strip():
        return True
    runtime = str(env.get("XDG_RUNTIME_DIR") or "").strip()
    return bool(runtime) and Path(runtime, "bus").exists()


def _secret_tool_ready(env: dict | None, which) -> str:
    """'' when secret-tool can be run, else why not (for doctor and Settings)."""
    if not (which or _which)(SECRET_TOOL):
        return "secret-tool is not installed; its package is libsecret-tools or libsecret"
    if not session_bus(env):
        return "no D-Bus session bus (headless or outside a login session)"
    return ""


def secret_service_lookup(service: str, account: str, runner=subprocess.run,
                          env: dict | None = None, which=None) -> str:
    """The stored value, or '' when none, or when the Secret Service is
    unreachable (logged, never raised)."""
    if _secret_tool_ready(env, which):
        return ""
    try:
        proc = runner([SECRET_TOOL, "lookup", "service", service, "account", account],
                      capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.info("Secret Service lookup for %s failed: %s", service, exc)
        return ""
    if proc.returncode != 0:
        if (proc.stderr or "").strip():
            logger.info("Secret Service lookup for %s failed: %s", service,
                        proc.stderr.strip()[:200])
        return ""
    return (proc.stdout or "").strip()


def secret_service_status(runner=subprocess.run, env: dict | None = None,
                          which=None) -> tuple[bool, str]:
    """(usable, detail). A lookup of an entry that does not exist tells the two
    failure modes apart: "not found" is exit 1 with nothing on stderr, while an
    unreachable service (no daemon, D-Bus error) complains on stderr."""
    reason = _secret_tool_ready(env, which)
    if reason:
        return False, reason
    try:
        proc = runner([SECRET_TOOL, "lookup", "service", "hermitcrm-probe",
                       "account", "probe"], capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return False, "the Secret Service did not answer within 5 seconds"
    except OSError as exc:
        return False, f"secret-tool could not run: {exc}"
    err = (proc.stderr or "").strip()
    if proc.returncode in (0, 1) and not err:
        return True, "Secret Service reachable (secret-tool)"
    return False, "the Secret Service is not reachable: " + (
        err.splitlines()[0][:200] if err else f"secret-tool exited {proc.returncode}")


def os_store(platform: str | None = None, runner=subprocess.run, env: dict | None = None,
             which=None) -> str | None:
    """KEYCHAIN on macOS, SECRET_SERVICE where secret-tool works, else None."""
    platform = platform or sys.platform
    if platform == "darwin":
        return KEYCHAIN
    if _uses_secret_service(platform) and secret_service_status(runner, env, which)[0]:
        return SECRET_SERVICE
    return None


def os_store_save(store: str, service: str, account: str, value: str, label: str = "",
                  runner=subprocess.run) -> bool:
    """Write one secret to the OS store; True when it worked. On Linux the value
    goes over stdin, never on the command line (where ps would show it)."""
    if store == KEYCHAIN:
        args, stdin = ["security", "add-generic-password", "-U", "-s", service,
                       "-a", account, "-w", value], None
    elif store == SECRET_SERVICE:
        args = [SECRET_TOOL, "store", f"--label={label or f'Hermit CRM {service}'}",
                "service", service, "account", account]
        stdin = value
    else:
        return False
    try:
        proc = runner(args, input=stdin, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.info("saving %s in %s failed: %s", service, store, exc)
        return False
    if proc.returncode != 0:
        logger.info("saving %s in %s failed: %s", service, store,
                    (proc.stderr or "").strip()[:200])
    return proc.returncode == 0


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
    platform = platform or sys.platform
    service = _config_value(config, name, "keychain_service")
    account = account or _config_value(config, name, "keychain_account")
    if not (service and account):
        return ""
    if platform == "darwin":
        return keychain_lookup(service, account, runner)
    if _uses_secret_service(platform):
        return secret_service_lookup(service, account, runner, env)
    return ""


def _write_file(path: Path, values: dict) -> None:
    text = "".join(f"{k} = {json.dumps(str(v), ensure_ascii=False)}\n"
                   for k, v in sorted(values.items()))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def set(name: str, value: str, data_dir: Path | str) -> Path:  # noqa: A001
    """Store a secret in ``<data>/.secrets.toml`` (mode 600), keeping other keys."""
    _check_name(name)
    path = Path(data_dir) / SECRETS_FILE
    values = _read_file(path)
    values[name] = str(value)
    _write_file(path, values)
    return path


def unset(name: str, data_dir: Path | str) -> bool:
    """Remove a secret from ``.secrets.toml`` (after it moved to the OS store,
    where the file would otherwise keep winning). True when a key was removed."""
    _check_name(name)
    path = Path(data_dir) / SECRETS_FILE
    values = _read_file(path)
    if name not in values:
        return False
    del values[name]
    _write_file(path, values)
    return True
