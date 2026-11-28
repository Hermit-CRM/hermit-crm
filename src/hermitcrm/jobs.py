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

"""Background jobs: AI work that no longer holds a page request.

One `JobRunner` per app (`app.state.jobs`) runs job functions on a two-worker
thread pool (`Pool`). A job function takes one argument, `report(progress, done=None,
total=None)`, calls the same code a route used to call inline, and returns a small
dict (the result). Raising fails the job; the error text is what the page shows.

Jobs live in memory. Every job that starts or finishes is also written to
``.git/hermitcrm-jobs.json`` (the newest ``KEEP``), so an answer survives the
upgrade restart. A job that was running when the server stopped is read back as
``interrupted``. The file is a convenience, not data: a missing or damaged one
reads as empty, and nothing here may stop a job from running.

Progress is polled (``GET /jobs/{id}.json``, pages/jobs.py), never pushed.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import queue
import uuid
from concurrent.futures import Future
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import send

logger = logging.getLogger("hermitcrm.jobs")

STATE_FILE = "hermitcrm-jobs.json"
KEEP = 50
WORKERS = 2

QUEUED, RUNNING, DONE, FAILED, INTERRUPTED = (
    "queued", "running", "done", "failed", "interrupted")
ACTIVE = (QUEUED, RUNNING)
FINISHED = (DONE, FAILED, INTERRUPTED)

INTERRUPTED_TEXT = ("Hermit CRM stopped while this was running (a restart or an "
                    "upgrade). Nothing after the last step was done: start it again.")

Report = Callable[..., None]


@dataclass
class Job:
    id: str
    kind: str                      # "ask", "outreach-batch", "enrich", ...
    label: str                     # what the badge and the page call it
    back: str = "/"                # the page to return to
    params: dict = field(default_factory=dict)   # what it was started with (the question)
    state: str = QUEUED
    progress: str = ""             # one line: what it is doing now
    done: int | None = None        # steps done, with total: "3 of 20"
    total: int | None = None
    created: str = ""
    started: str = ""
    ended: str = ""
    result: dict = field(default_factory=dict)
    error: str = ""
    seen: bool = False             # a finished job someone opened leaves the badge

    @property
    def active(self) -> bool:
        return self.state in ACTIVE

    @property
    def finished(self) -> bool:
        return self.state in FINISHED

    @property
    def steps(self) -> str:
        """ "3 of 20", or "" when the job does not count steps."""
        if self.total is None:
            return ""
        return f"{self.done or 0} of {self.total}"

    def as_json(self) -> dict:
        """What the page script polls. Everything except the result body, which can be
        long (an answer): the script only needs to know the job finished, then reloads."""
        data = asdict(self)
        data.pop("result")
        data["steps"] = self.steps
        data["url"] = f"/jobs/{self.id}"
        return data

    @classmethod
    def from_json(cls, data: dict) -> "Job | None":
        known = {f.name for f in fields(cls)}
        try:
            job = cls(**{k: v for k, v in data.items() if k in known})
        except TypeError:
            return None
        if not isinstance(job.id, str) or not job.id or not isinstance(job.result, dict) \
                or not isinstance(job.params, dict):
            return None
        return job


class Inline:
    """An executor that runs the job inside `submit`: tests use it, so a route test
    sees the finished job without a thread or a sleep."""

    def submit(self, fn, *args, **kwargs) -> Future:
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # the job wrapper catches; this is belt and braces
            future.set_exception(exc)
        return future

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        pass


class Pool:
    """Two worker threads, like `ThreadPoolExecutor(max_workers=2)`, but daemon ones.
    The standard pool makes the interpreter wait at exit for a running job, so a
    Ctrl-C or a supervisor's stop would hang for as long as an AI call takes (up to
    `ask_timeout`). A daemon worker just ends with the process; the job's line in
    the file still says running and reads back as interrupted. Threads start on
    the first job, so an app that never runs one starts none."""

    def __init__(self, workers: int = WORKERS):
        self.workers = workers
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._closed = False

    def submit(self, fn, *args, **kwargs) -> Future:
        future: Future = Future()
        with self._lock:
            if self._closed:
                raise RuntimeError("the job pool is shut down")
            self._queue.put((future, fn, args, kwargs))
            if len(self._threads) < self.workers:
                thread = threading.Thread(target=self._work, daemon=True,
                                          name=f"hermitcrm-job-{len(self._threads) + 1}")
                self._threads.append(thread)
                thread.start()
        return future

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            future, fn, args, kwargs = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        with self._lock:
            self._closed = True
            threads = list(self._threads)
        for _ in threads:
            self._queue.put(None)
        if wait:
            for thread in threads:
                thread.join()


def make_executor():
    """The pool every app gets. tests/conftest.py swaps this for `Inline`."""
    return Pool()


def path(root) -> Path:
    return send.runtime_dir(root) / STATE_FILE


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class JobRunner:
    """Starts jobs, keeps them, and answers what a page asks about them."""

    def __init__(self, root, executor=None, clock: Callable[[], str] = _now):
        self.root = Path(root)
        self.clock = clock
        self.executor = executor if executor is not None else make_executor()
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        # kind -> view(request, job): what /jobs/{id} shows for a job of that kind (the
        # route that starts such jobs registers it, next to itself in web.py). A view
        # that returns None leaves the generic job page.
        self.views: dict[str, Callable] = {}
        self._load()

    # ------------------------------------------------------------ the file

    def _load(self) -> None:
        try:
            raw = json.loads(path(self.root).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        stopped = False
        for entry in raw.get("jobs", []) if isinstance(raw, dict) else []:
            job = Job.from_json(entry) if isinstance(entry, dict) else None
            if job is None:
                continue
            if job.active:   # this process did not start it: the server stopped under it
                job.state, job.error = INTERRUPTED, INTERRUPTED_TEXT
                job.ended = job.ended or self.clock()
                stopped = True
            self._jobs[job.id] = job
        if stopped:
            self._save()

    def _save(self) -> None:
        """Write the newest KEEP jobs. Never raises: a job must not fail on its log."""
        with self._lock:
            keep = sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)[:KEEP]
            text = json.dumps({"jobs": [asdict(j) for j in keep]}, indent=1,
                              ensure_ascii=False)
        target = path(self.root)
        tmp = target.with_name(target.name + ".tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, target)
        except OSError:
            logger.exception("could not write %s", target)

    # ------------------------------------------------------------- running

    def start(self, kind: str, label: str, fn: Callable[[Report], dict | None],
              back: str = "/", params: dict | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, label=label, back=back,
                  params=dict(params or {}), created=self.clock())
        with self._lock:
            self._jobs[job.id] = job
            # Memory holds the newest KEEP too, and never drops a job still running.
            done = sorted((j for j in self._jobs.values() if j.finished),
                          key=lambda j: j.created)
            for old in done[:max(0, len(self._jobs) - KEEP)]:
                del self._jobs[old.id]
        self.executor.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: Callable[[Report], dict | None]) -> None:
        def report(progress: str, done: int | None = None, total: int | None = None):
            job.progress = str(progress)
            if total is not None:
                job.total = total
            if done is not None:
                job.done = done

        job.state, job.started = RUNNING, self.clock()
        self._save()
        try:
            result = fn(report)
        except Exception as exc:   # every failure is the job's, never the pool's
            if not _expected(exc):
                logger.exception("job %s (%s) failed", job.id, job.kind)
            job.error = str(exc) or type(exc).__name__
            job.state = FAILED
        else:
            job.result = dict(result or {})
            job.state = DONE
        job.ended = self.clock()
        self._save()

    # ------------------------------------------------------------- reading

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active(self) -> list[Job]:
        """Running and queued jobs, and finished ones nobody has opened yet (the badge
        says "ready" for those), oldest first."""
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.active or not j.seen]
        return sorted(jobs, key=lambda j: j.created)

    def recent(self) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        return sorted(jobs, key=lambda j: j.created, reverse=True)

    def mark_seen(self, job: Job) -> None:
        if job.finished and not job.seen:
            job.seen = True
            self._save()

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False)


def _expected(exc: Exception) -> bool:
    """An AI or outreach error is a message for the page, not a crash for the log."""
    from .enrich import EnrichError
    from .outreach import OutreachError
    return isinstance(exc, (EnrichError, OutreachError))
