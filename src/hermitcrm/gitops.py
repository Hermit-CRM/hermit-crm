"""Git operations wrapper: commit and push the file-backed data store.

Never raises. Failures are logged (ERROR for commit, WARNING throttled for
push) and surfaced via return values / status() instead of exceptions.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("crm.gitops")

_PUSH_WARNING_INTERVAL = 60.0  # seconds


class GitOps:
    def __init__(
        self,
        root: Path,
        push_enabled: bool = True,
        remote: str = "origin",
        branch: str = "main",
        push_timeout: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root = Path(root)
        self.push_enabled = push_enabled
        self.remote = remote
        self.branch = branch
        self.push_timeout = push_timeout
        self._clock = clock
        self.last_push: Optional[dict] = None
        self._last_warning_time: Optional[float] = None
        self._lock = threading.Lock()

    def commit(self, message: str) -> Optional[str]:
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.root,
                capture_output=True,
                text=True,
            )
            if status.returncode != 0:
                logger.error(
                    "git status failed: %s", status.stderr.strip()
                )
                return None
            if not status.stdout.strip():
                return None  # nothing to commit

            add = subprocess.run(
                ["git", "add", "-A"],
                cwd=self.root,
                capture_output=True,
                text=True,
            )
            if add.returncode != 0:
                logger.error("git add failed: %s", add.stderr.strip())
                return None

            commit = subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=hermitcrm",
                    "-c",
                    "user.email=hermitcrm@localhost",
                    "commit",
                    "-m",
                    message,
                ],
                cwd=self.root,
                capture_output=True,
                text=True,
            )
            if commit.returncode != 0:
                logger.error(
                    "git commit failed: %s", commit.stderr.strip()
                )
                return None

            return self.last_commit_sha()
        except Exception:
            logger.error("git commit raised an exception", exc_info=True)
            return None

    def push_async(self) -> None:
        if not self.push_enabled:
            return
        try:
            thread = threading.Thread(target=self.push_sync, daemon=True)
            thread.start()
        except Exception:
            logger.error("failed to start push thread", exc_info=True)

    def push_sync(self) -> bool:
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")
        try:
            env = dict(os.environ)
            env["GIT_TERMINAL_PROMPT"] = "0"
            result = subprocess.run(
                ["git", "push", self.remote, self.branch],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=self.push_timeout,
                env=env,
            )
            if result.returncode == 0:
                self.last_push = {"ok": True, "time": now_str, "error": ""}
                logger.info("git push succeeded (%s/%s)", self.remote, self.branch)
                return True
            else:
                error = result.stderr.strip() or "git push failed"
                self._record_failure(now_str, error)
                return False
        except subprocess.TimeoutExpired:
            self._record_failure(now_str, f"push timed out after {self.push_timeout}s")
            return False
        except Exception as exc:
            self._record_failure(now_str, str(exc))
            return False

    def _record_failure(self, now_str: str, error: str) -> None:
        self.last_push = {"ok": False, "time": now_str, "error": error}
        with self._lock:
            now = self._clock()
            should_warn = (
                self._last_warning_time is None
                or (now - self._last_warning_time) >= _PUSH_WARNING_INTERVAL
            )
            if should_warn:
                self._last_warning_time = now
        if should_warn:
            logger.warning("git push failed: %s", error)

    def last_commit_sha(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short=10", "HEAD"],
                cwd=self.root,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return None
            sha = result.stdout.strip()
            return sha if sha else None
        except Exception:
            logger.error("git rev-parse raised an exception", exc_info=True)
            return None

    def status(self) -> dict:
        return {
            "last_commit": self.last_commit_sha(),
            "last_push": self.last_push,
            "push_enabled": self.push_enabled,
        }
