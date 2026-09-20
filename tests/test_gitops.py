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

import logging
import subprocess
import sys
import time
from pathlib import Path


from hermitcrm.gitops import GitOps


def run(args, cwd):
    result = subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run(["init", "-b", "main"], cwd=path)
    run(["-c", "user.name=crm", "-c", "user.email=crm@localhost", "commit",
         "--allow-empty", "-m", "init"], cwd=path)
    return path


def test_commit_creates_commit_and_returns_sha(tmp_path):
    repo = init_repo(tmp_path / "repo")
    (repo / "file.txt").write_text("hello\n")

    gitops = GitOps(root=repo)
    sha = gitops.commit("company: acme created")

    assert sha is not None
    assert len(sha) >= 7

    log = run(["log", "-1", "--pretty=%s"], cwd=repo)
    assert log.strip() == "company: acme created"


def test_commit_with_no_change_returns_none(tmp_path):
    repo = init_repo(tmp_path / "repo")
    (repo / "file.txt").write_text("hello\n")

    gitops = GitOps(root=repo)
    first_sha = gitops.commit("company: acme created")
    assert first_sha is not None

    log_count_before = run(["rev-list", "--count", "HEAD"], cwd=repo).strip()

    second_sha = gitops.commit("company: acme updated")
    assert second_sha is None

    log_count_after = run(["rev-list", "--count", "HEAD"], cwd=repo).strip()
    assert log_count_before == log_count_after


def test_push_with_bogus_remote_fails_gracefully(tmp_path):
    repo = init_repo(tmp_path / "repo")
    run(["remote", "add", "origin", "https://127.0.0.1:9/none.git"], cwd=repo)

    gitops = GitOps(root=repo, remote="origin", branch="main", push_timeout=5.0)
    ok = gitops.push_sync()

    assert ok is False
    assert gitops.last_push is not None
    assert gitops.last_push["ok"] is False
    assert gitops.last_push["error"]


def test_push_async_disabled_starts_nothing(tmp_path):
    repo = init_repo(tmp_path / "repo")
    run(["remote", "add", "origin", "https://127.0.0.1:9/none.git"], cwd=repo)

    gitops = GitOps(root=repo, push_enabled=False)
    gitops.push_async()

    time.sleep(0.2)
    assert gitops.last_push is None


def test_push_async_with_failing_remote_completes_without_raising(tmp_path):
    repo = init_repo(tmp_path / "repo")
    run(["remote", "add", "origin", "https://127.0.0.1:9/none.git"], cwd=repo)

    gitops = GitOps(root=repo, push_enabled=True, push_timeout=5.0)
    gitops.push_async()

    deadline = time.monotonic() + 10
    while gitops.last_push is None and time.monotonic() < deadline:
        time.sleep(0.05)

    assert gitops.last_push is not None
    assert gitops.last_push["ok"] is False


def test_push_warning_throttled_to_once_per_minute(tmp_path, caplog):
    repo = init_repo(tmp_path / "repo")
    run(["remote", "add", "origin", "https://127.0.0.1:9/none.git"], cwd=repo)

    fake_time = [1000.0]

    def clock():
        return fake_time[0]

    gitops = GitOps(root=repo, push_timeout=5.0, clock=clock)

    with caplog.at_level(logging.WARNING, logger="crm.gitops"):
        gitops.push_sync()
        fake_time[0] += 10  # well within the 60s throttle window
        gitops.push_sync()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    # both failures still recorded in last_push despite the suppressed log
    assert gitops.last_push["ok"] is False


def test_push_warning_logs_again_after_throttle_window(tmp_path, caplog):
    repo = init_repo(tmp_path / "repo")
    run(["remote", "add", "origin", "https://127.0.0.1:9/none.git"], cwd=repo)

    fake_time = [1000.0]

    def clock():
        return fake_time[0]

    gitops = GitOps(root=repo, push_timeout=5.0, clock=clock)

    with caplog.at_level(logging.WARNING, logger="crm.gitops"):
        gitops.push_sync()
        fake_time[0] += 61  # past the 60s throttle window
        gitops.push_sync()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2


def test_push_success_to_local_bare_remote(tmp_path):
    bare = tmp_path / "bare.git"
    run(["init", "--bare", "-b", "main", str(bare)], cwd=tmp_path)

    repo = init_repo(tmp_path / "repo")
    run(["remote", "add", "origin", str(bare)], cwd=repo)

    gitops = GitOps(root=repo, remote="origin", branch="main", push_timeout=5.0)
    ok = gitops.push_sync()

    assert ok is True
    assert gitops.last_push["ok"] is True
    assert gitops.last_push["error"] == ""


def test_last_commit_sha_none_before_any_commit(tmp_path):
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    run(["init", "-b", "main"], cwd=repo)

    gitops = GitOps(root=repo)
    assert gitops.last_commit_sha() is None


def test_status_shape(tmp_path):
    repo = init_repo(tmp_path / "repo")
    gitops = GitOps(root=repo, push_enabled=True)

    status = gitops.status()
    assert set(status.keys()) == {"last_commit", "last_push", "push_enabled"}
    assert status["last_commit"] is not None
    assert status["last_push"] is None
    assert status["push_enabled"] is True


def test_commit_stages_only_the_given_paths(tmp_path):
    """A write commits its own record, not whatever else is in the folder."""
    repo = init_repo(tmp_path / "repo")
    (repo / "wanted.txt").write_text("x\n")
    (repo / "stray.txt").write_text("not mine to commit\n")

    sha = GitOps(root=repo).commit("company: acme created", ["wanted.txt"])

    assert sha is not None
    assert run(["show", "--name-only", "--pretty="], cwd=repo).split() == ["wanted.txt"]
    assert run(["ls-files", "stray.txt"], cwd=repo) == ""  # still untracked


def test_commit_records_a_deletion_in_the_given_paths(tmp_path):
    repo = init_repo(tmp_path / "repo")
    (repo / "gone.txt").write_text("x\n")
    GitOps(root=repo).commit("company: acme created", ["gone.txt"])
    (repo / "gone.txt").unlink()

    sha = GitOps(root=repo).commit("company: acme deleted", ["gone.txt"])

    assert sha is not None
    assert run(["ls-files", "gone.txt"], cwd=repo) == ""


def test_commit_with_paths_and_nothing_staged_returns_none(tmp_path):
    repo = init_repo(tmp_path / "repo")
    (repo / "stray.txt").write_text("not mine\n")

    assert GitOps(root=repo).commit("company: acme created", ["absent.txt"]) is None
    assert run(["ls-files", "stray.txt"], cwd=repo) == ""
