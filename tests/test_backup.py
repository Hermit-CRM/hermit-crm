"""hermitcrm/backup.py against real git: every way a folder's history can be damaged,
and that the backup survives it, stays small and never touches the folder's own
branch, index or working tree.

Nothing here touches the real HOME: the backup goes under tmp_path/home.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hermitcrm import backup, cli, doctor, schedule
from hermitcrm.datafolder import init_folder

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
ID = ["-c", "user.name=t", "-c", "user.email=t@example.com"]


def git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *ID, *args], cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout.strip()


def refs(dest: Path) -> dict[str, str]:
    out = git(dest, "for-each-ref", "--format=%(refname) %(objectname)")
    pairs = (line.split(" ", 1) for line in out.splitlines())
    return {name: sha for name, sha in pairs} if out else {}


def commit_file(folder: Path, rel: str, text: str, message: str) -> str:
    path = folder / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", message)
    return git(folder, "rev-parse", "HEAD")


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


@pytest.fixture
def folder(tmp_path):
    path = init_folder(tmp_path / "crm", demo=True)
    assert git(path, "status", "--porcelain") == ""
    return path


def run(folder, home, minutes=0, config=None, **kw):
    return backup.run(folder, config or {}, home=home, now=NOW + timedelta(minutes=minutes), **kw)


def dest_of(folder, home):
    return backup.default_path(folder, home)


# ------------------------------------------------------------- the basics


def test_default_path_is_outside_and_distinct(tmp_path, home):
    a = backup.default_path(tmp_path / "one" / "crm", home)
    b = backup.default_path(tmp_path / "two" / "crm", home)
    assert a != b and a.name.startswith("crm-") and a.suffix == ".git"
    assert a.parent == home / ".hermitcrm" / "backups"


def test_first_run_creates_a_protected_bare_repo_and_pushes_main(folder, home):
    out = run(folder, home)
    dest = dest_of(folder, home)
    assert out.code == 0 and out.changed
    assert git(dest, "rev-parse", "--is-bare-repository") == "true"
    for key, value in backup.BARE_CONFIG.items():
        assert git(dest, "config", key) == value
    assert refs(dest)["refs/heads/main"] == git(folder, "rev-parse", "HEAD")
    assert "Do not delete" in (dest / "description").read_text()


def test_a_run_with_nothing_new_writes_nothing(folder, home):
    run(folder, home)
    dest = dest_of(folder, home)
    before = refs(dest)
    out = run(folder, home, minutes=5)
    assert out.code == 0 and not out.changed
    assert out.lines == [f"nothing new; backup at {dest}"]
    assert refs(dest) == before


def test_a_new_commit_fast_forwards_the_backup(folder, home):
    run(folder, home)
    sha = commit_file(folder, "companies/acme/company.md", "---\nname: Acme\n---\n", "add")
    out = run(folder, home, minutes=5)
    assert out.changed and refs(dest_of(folder, home))["refs/heads/main"] == sha


# ------------------------------------------------ uncommitted edits (snapshots)


def test_uncommitted_edits_are_snapshotted_without_touching_the_folder(folder, home):
    run(folder, home)
    (folder / "MESSAGING.md").write_text("half-finished playbook\n", encoding="utf-8")
    (folder / "notes.md").write_text("new, never added\n", encoding="utf-8")
    (folder / ".secrets.toml").write_text('bcc_password = "hunter2"\n', encoding="utf-8")
    head = git(folder, "rev-parse", "HEAD")
    index = (folder / ".git" / "index").read_bytes()
    status = git(folder, "status", "--porcelain")

    out = run(folder, home, minutes=5)

    dest = dest_of(folder, home)
    snaps = [r for r in refs(dest) if r.startswith("refs/snapshots/")]
    assert len(snaps) == 1 and snaps[0] == "refs/snapshots/20260918-120500Z"
    assert out.code == 0
    # the folder is exactly as it was: branch, index and working tree
    assert git(folder, "rev-parse", "HEAD") == head
    assert (folder / ".git" / "index").read_bytes() == index
    assert git(folder, "status", "--porcelain") == status
    # the snapshot has the edits, on top of HEAD, and never the secrets
    assert git(dest, "show", f"{snaps[0]}:MESSAGING.md") == "half-finished playbook"
    assert git(dest, "show", f"{snaps[0]}:notes.md") == "new, never added"
    assert git(dest, "rev-parse", f"{snaps[0]}^") == head
    assert subprocess.run(["git", "cat-file", "-e", f"{snaps[0]}:.secrets.toml"], cwd=dest,
                          capture_output=True).returncode != 0


def test_the_same_uncommitted_state_is_snapshotted_once(folder, home):
    run(folder, home)
    (folder / "MESSAGING.md").write_text("draft\n", encoding="utf-8")
    run(folder, home, minutes=5)
    run(folder, home, minutes=10)
    run(folder, home, minutes=15)
    snaps = [r for r in refs(dest_of(folder, home)) if r.startswith("refs/snapshots/")]
    assert len(snaps) == 1
    (folder / "MESSAGING.md").write_text("draft, longer\n", encoding="utf-8")
    run(folder, home, minutes=20)
    snaps = [r for r in refs(dest_of(folder, home)) if r.startswith("refs/snapshots/")]
    assert len(snaps) == 2


def test_committing_the_edit_needs_no_snapshot(folder, home):
    run(folder, home)
    commit_file(folder, "MESSAGING.md", "final\n", "playbook")
    run(folder, home, minutes=5)
    assert not [r for r in refs(dest_of(folder, home)) if r.startswith("refs/snapshots/")]


def test_a_held_index_lock_does_not_stop_a_backup(folder, home):
    """The web app may be mid-commit; the backup never takes the folder's lock."""
    run(folder, home)
    (folder / "MESSAGING.md").write_text("edit\n", encoding="utf-8")
    lock = folder / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    try:
        out = run(folder, home, minutes=5)
    finally:
        lock.unlink()
    assert out.code == 0
    assert [r for r in refs(dest_of(folder, home)) if r.startswith("refs/snapshots/")]


# ---------------------------------------------------- damage to the history


def test_reset_hard_keeps_both_lines_and_warns_once(folder, home):
    first = git(folder, "rev-parse", "HEAD")
    commit_file(folder, "companies/acme/company.md", "---\nname: Acme\n---\n", "one")
    lost = commit_file(folder, "companies/acme/company.md", "---\nname: Acme 2\n---\n", "two")
    run(folder, home)
    dest = dest_of(folder, home)

    git(folder, "reset", "-q", "--hard", first)  # what a careless agent does
    git(folder, "reflog", "expire", "--expire=now", "--all")
    git(folder, "gc", "-q", "--prune=now")
    assert subprocess.run(["git", "cat-file", "-e", lost], cwd=folder).returncode != 0
    new = commit_file(folder, "companies/other/company.md", "---\nname: Other\n---\n", "new")

    out = run(folder, home, minutes=5)
    assert out.code == 1 and len(out.warnings) == 1
    assert "rewritten" in out.warnings[0]
    r = refs(dest)
    assert r["refs/heads/main"] == lost  # the old line, untouched
    rewritten = [k for k in r if k.startswith("refs/rewritten/")]
    assert rewritten == ["refs/rewritten/20260918-120500Z/main"] and r[rewritten[0]] == new

    # later runs follow the new line and do not warn again
    newer = commit_file(folder, "companies/other/company.md", "---\nname: Other 2\n---\n", "n2")
    out = run(folder, home, minutes=10)
    assert out.code == 0 and not out.warnings
    assert refs(dest)[rewritten[0]] == newer
    assert refs(dest)["refs/heads/main"] == lost


def test_amend_counts_as_a_rewrite(folder, home):
    run(folder, home)
    head = git(folder, "rev-parse", "HEAD")
    git(folder, "commit", "-q", "--amend", "-m", "changed message")
    out = run(folder, home, minutes=5)
    assert out.code == 1
    assert refs(dest_of(folder, home))["refs/heads/main"] == head


def test_the_backup_refuses_force_pushes_and_deletes(folder, home):
    commit_file(folder, "a.md", "a\n", "a")
    run(folder, home)
    dest = dest_of(folder, home)
    head = refs(dest)["refs/heads/main"]
    forced = subprocess.run(["git", "push", "--force", str(dest), "HEAD~1:refs/heads/main"],
                            cwd=folder, capture_output=True, text=True)
    deleted = subprocess.run(["git", "push", str(dest), ":refs/heads/main"],
                             cwd=folder, capture_output=True, text=True)
    assert forced.returncode != 0 and deleted.returncode != 0
    assert refs(dest)["refs/heads/main"] == head


def test_protection_is_put_back_if_someone_loosens_it(folder, home):
    run(folder, home)
    dest = dest_of(folder, home)
    git(dest, "config", "receive.denyNonFastForwards", "false")
    run(folder, home, minutes=5)
    assert git(dest, "config", "receive.denyNonFastForwards") == "true"


def test_a_deleted_git_folder_comes_back_from_the_backup(folder, home, tmp_path):
    commit_file(folder, "companies/acme/company.md", "---\nname: Acme\n---\n", "acme")
    (folder / "draft.md").write_text("uncommitted\n", encoding="utf-8")
    run(folder, home)
    files = {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*")
             if p.is_file() and ".git" not in p.parts and p.name != "draft.md"}
    shutil.rmtree(folder / ".git")
    shutil.rmtree(folder / "companies")

    again = tmp_path / "restored"
    subprocess.run(["git", "clone", "-q", str(dest_of(folder, home)), str(again)], check=True)
    for rel, data in files.items():
        if rel.parts[0] == "companies" or rel.name in ("config.toml", "CLAUDE.md"):
            assert (again / rel).read_bytes() == data, rel
    snap = [r for r in refs(dest_of(folder, home)) if r.startswith("refs/snapshots/")][0]
    assert git(dest_of(folder, home), "show", f"{snap}:draft.md") == "uncommitted"


def test_a_missing_backup_is_recreated_loudly(folder, home):
    run(folder, home)
    shutil.rmtree(dest_of(folder, home))
    out = run(folder, home, minutes=5)
    assert out.code == 1
    assert "was missing" in out.warnings[0] and "2026-09-18T12:00:00+00:00" in out.warnings[0]
    assert refs(dest_of(folder, home))["refs/heads/main"] == git(folder, "rev-parse", "HEAD")


def test_backup_dir_inside_the_folder_is_refused(folder, home):
    out = run(folder, home, config={"backup_dir": str(folder / "bk.git")})
    assert out.code == 2 and "inside the data folder" in out.lines[0]
    assert not (folder / "bk.git").exists()


def test_backup_dir_setting_is_used(folder, home, tmp_path):
    out = run(folder, home, config={"backup_dir": str(tmp_path / "elsewhere.git")})
    assert out.code == 0 and (tmp_path / "elsewhere.git" / "HEAD").exists()
    assert not dest_of(folder, home).exists()


def test_a_non_repository_at_the_backup_path_is_an_error(folder, home):
    dest = dest_of(folder, home)
    dest.mkdir(parents=True)
    (dest / "photo.jpg").write_bytes(b"x")
    out = run(folder, home)
    assert out.code == 2 and "not a bare git repository" in out.lines[0]
    assert (dest / "photo.jpg").exists()


# ------------------------------------------------------------------- size


def test_size_grows_with_edits_not_with_runs(folder, home):
    run(folder, home)
    dest = dest_of(folder, home)
    git(dest, "gc", "-q")
    before = backup._size(dest)
    for i in range(1, 60):  # five hours of an idle folder
        assert not run(folder, home, minutes=5 * i).changed
    assert backup._size(dest) == before
    assert len(refs(dest)) == 1


# ---------------------------------------------------------- the remote too


def test_pushes_to_the_folders_remote_when_enabled(folder, home, tmp_path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(folder, "remote", "add", "origin", str(origin))
    commit_file(folder, "a.md", "a\n", "a")
    out = run(folder, home, config={"push_enabled": False, "remote": "origin"})
    assert git(origin, "for-each-ref") == ""
    out = run(folder, home, minutes=5, config={"push_enabled": True, "remote": "origin"})
    assert "pushed main to origin" in out.lines
    assert git(origin, "rev-parse", "main") == git(folder, "rev-parse", "HEAD")


def test_a_failing_remote_is_a_warning_and_the_local_backup_still_happens(folder, home):
    git(folder, "remote", "add", "origin", "/nonexistent/origin.git")
    out = run(folder, home, config={"push_enabled": True, "remote": "origin"})
    assert out.code == 1 and "push to origin failed" in out.warnings[0]
    assert refs(dest_of(folder, home))["refs/heads/main"] == git(folder, "rev-parse", "HEAD")


# -------------------------------------------------------------- restoring


def damage(folder):
    """What a bad agent run looks like: one company rewritten, one deleted."""
    companies = sorted(p for p in (folder / "companies").iterdir() if p.is_dir())
    victim, gone = companies[0], companies[1]
    original = (victim / "company.md").read_bytes()
    gone_files = {p.relative_to(folder): p.read_bytes() for p in gone.rglob("*") if p.is_file()}
    (victim / "company.md").write_text("---\nname: WRONG\n---\n", encoding="utf-8")
    shutil.rmtree(gone)
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "ai: tidy up")
    return victim, original, gone, gone_files


def test_list_shows_versions_touching_a_path(folder, home):
    good = git(folder, "rev-parse", "--short", "HEAD")
    run(folder, home)
    victim, *_ = damage(folder)
    run(folder, home, minutes=5)
    text, code = backup.list_versions(folder, {}, path=str(victim.relative_to(folder)),
                                      home=home)
    assert code == 0
    lines = [l for l in text.splitlines() if l[:1].isalnum() and "  " in l]
    assert "ai: tidy up" in lines[0] and any(l.startswith(good[:7]) for l in lines)


def test_restore_dry_run_changes_nothing(folder, home):
    good = git(folder, "rev-parse", "HEAD")
    run(folder, home)
    victim, *_ = damage(folder)
    head = git(folder, "rev-parse", "HEAD")
    out, commit = backup.restore(folder, good[:10], [str(victim.relative_to(folder))],
                                 home=home, now=NOW)
    assert commit is None and out.code == 0
    assert any("would change" in l for l in out.lines)
    assert git(folder, "rev-parse", "HEAD") == head
    assert "WRONG" in (victim / "company.md").read_text()


def test_restore_one_company_and_a_deleted_one(folder, home):
    good = git(folder, "rev-parse", "HEAD")
    run(folder, home)
    victim, original, gone, gone_files = damage(folder)
    bad = git(folder, "rev-parse", "HEAD")
    paths = [str(victim.relative_to(folder)), str(gone.relative_to(folder))]

    out, commit = backup.restore(folder, good[:10], paths, apply=True, home=home, now=NOW)

    assert out.code == 0 and commit
    assert (victim / "company.md").read_bytes() == original
    for rel, data in gone_files.items():
        assert (folder / rel).read_bytes() == data
    # a new commit on top: the bad one stays in the history, and the folder is clean
    assert git(folder, "rev-parse", "HEAD~1") == bad
    assert git(folder, "log", "-1", "--format=%s").startswith("backup: restore companies/")
    assert git(folder, "status", "--porcelain") == ""
    # the damaged state was backed up before being replaced
    assert refs(dest_of(folder, home))["refs/heads/main"] == bad


def test_restore_everything_removes_files_added_since(folder, home):
    good = git(folder, "rev-parse", "HEAD")
    run(folder, home)
    commit_file(folder, "companies/junk/company.md", "---\nname: Junk\n---\n", "junk")
    (folder / "companies" / "untracked.md").write_text("stray\n", encoding="utf-8")
    out, commit = backup.restore(folder, good, [], apply=True, home=home, now=NOW)
    assert out.code == 0 and commit
    assert not (folder / "companies" / "junk").exists()
    assert not (folder / "companies" / "untracked.md").exists()
    assert git(folder, "diff", "--stat", good, "HEAD") == ""
    # the stray file is not lost: it went into a snapshot first
    snap = [r for r in refs(dest_of(folder, home)) if r.startswith("refs/snapshots/")][0]
    assert git(dest_of(folder, home), "show", f"{snap}:companies/untracked.md") == "stray"


def test_restore_a_version_only_the_backup_still_has(folder, home):
    base = git(folder, "rev-parse", "HEAD")
    lost = commit_file(folder, "companies/acme/company.md", "---\nname: Acme\n---\n", "acme")
    run(folder, home)
    git(folder, "reset", "-q", "--hard", base)
    git(folder, "reflog", "expire", "--expire=now", "--all")
    git(folder, "gc", "-q", "--prune=now")
    out, commit = backup.restore(folder, lost[:8], ["companies/acme"], apply=True,
                                 home=home, now=NOW)
    assert out.code == 0, out.lines
    assert "name: Acme" in (folder / "companies/acme/company.md").read_text()


def test_restore_a_snapshot_by_its_name(folder, home):
    run(folder, home)
    (folder / "MESSAGING.md").write_text("the good draft\n", encoding="utf-8")
    run(folder, home, minutes=5)
    (folder / "MESSAGING.md").write_text("ruined\n", encoding="utf-8")
    out, commit = backup.restore(folder, "snapshots/20260918-120500Z", ["MESSAGING.md"],
                                 apply=True, home=home, now=NOW + timedelta(minutes=10))
    assert out.code == 0, out.lines
    assert (folder / "MESSAGING.md").read_text() == "the good draft\n"


@pytest.mark.parametrize("ref,paths,expect", [
    ("HEAD", ["../outside"], "outside the data folder"),
    ("HEAD", [".git/config"], "not on .git"),
    ("nosuchversion", [], "not a version"),
    ("HEAD", ["companies/does-not-exist"], "not in that version"),
])
def test_restore_refuses(folder, home, ref, paths, expect):
    run(folder, home)
    out, commit = backup.restore(folder, ref, paths, apply=True, home=home, now=NOW)
    assert out.code == 2 and commit is None
    assert any(expect in l for l in out.lines), out.lines


def test_restore_of_the_current_state_is_a_no_op(folder, home):
    run(folder, home)
    out, commit = backup.restore(folder, "HEAD", [], apply=True, home=home, now=NOW)
    assert commit is None and "nothing to restore" in out.lines[-1]


# ----------------------------------------------------------------- status


def test_status_levels(folder, home):
    assert backup.status(folder, {}, home=home, now=NOW)["level"] == "warn"
    run(folder, home)
    st = backup.status(folder, {}, home=home, now=NOW + timedelta(minutes=3))
    assert st["level"] == "ok" and "3 min ago" in st["summary"]
    stale = backup.status(folder, {}, home=home, now=NOW + timedelta(hours=2))
    assert stale["level"] == "warn" and "over an hour" in stale["summary"]
    shutil.rmtree(dest_of(folder, home))
    gone = backup.status(folder, {}, home=home, now=NOW)
    assert gone["level"] == "warn" and "missing" in gone["summary"]


def test_status_reports_a_rewrite(folder, home):
    run(folder, home)
    git(folder, "commit", "-q", "--amend", "-m", "x")
    run(folder, home, minutes=5)
    st = backup.status(folder, {}, home=home, now=NOW + timedelta(minutes=6))
    assert st["level"] == "warn" and "rewritten" in st["summary"]
    run(folder, home, minutes=10)  # the next clean run clears the warning
    assert backup.status(folder, {}, home=home,
                         now=NOW + timedelta(minutes=11))["level"] == "ok"


# -------------------------------------------------------------------- CLI


@pytest.fixture
def cli_home(home, monkeypatch):
    monkeypatch.setenv("HOME", str(home))
    return home


def test_cli_backup_run_list_status_restore(folder, cli_home, capsys):
    good = git(folder, "rev-parse", "HEAD")
    assert cli.main(["--data", str(folder), "backup"]) == 0
    assert "main at" in capsys.readouterr().out
    assert cli.main(["--data", str(folder), "backup", "run", "--quiet"]) == 0
    assert capsys.readouterr().out == ""  # the job's log stays empty when idle
    victim, original, *_ = damage(folder)
    rel = str(victim.relative_to(folder))
    assert cli.main(["--data", str(folder), "backup", "list", rel]) == 0
    assert "ai: tidy up" in capsys.readouterr().out
    assert cli.main(["--data", str(folder), "backup", "restore", good[:10], rel]) == 0
    assert "would change" in capsys.readouterr().out
    assert cli.main(["--data", str(folder), "backup", "restore", good[:10], rel,
                     "--apply"]) == 0
    printed = capsys.readouterr().out
    assert "restored companies/" in printed
    assert (victim / "company.md").read_bytes() == original
    assert "backed up the restored state" in printed
    assert refs(backup.default_path(folder, cli_home))["refs/heads/main"] == \
        git(folder, "rev-parse", "HEAD")  # the restore and its rebuild are in the backup
    assert cli.main(["--data", str(folder), "backup", "status"]) == 0
    assert "last good run" in capsys.readouterr().out


def test_cli_backup_runs_even_when_the_data_format_is_too_new(folder, cli_home, capsys):
    (folder / ".hermitcrm-format").write_text("999\n", encoding="utf-8")
    git(folder, "commit", "-qam", "future")
    assert cli.main(["--data", str(folder), "backup"]) == 0
    assert (folder / ".hermitcrm-format").read_text() == "999\n"


def test_cli_backup_failure_exits_2(folder, cli_home, capsys, tmp_path):
    (folder / "config.toml").write_text(
        (folder / "config.toml").read_text() + f'\nbackup_dir = "{folder / "b.git"}"\n')
    assert cli.main(["--data", str(folder), "backup"]) == 2
    assert "inside the data folder" in capsys.readouterr().err


def test_help_topic_exists():
    code = cli.cmd_help("backups")[1]
    assert code == 0
    text = cli.cmd_help("backups")[0]
    for needle in ("hermitcrm backup restore", "refs/rewritten", "schedule install",
                   "git clone"):
        assert needle in text, needle


def test_agent_rules_mention_backups():
    from hermitcrm.datafolder import AGENT_RULES
    assert "hermitcrm backup" in AGENT_RULES and ".hermitcrm/backups" in AGENT_RULES


# --------------------------------------------------------------- schedule


def sched_ctx(tmp_path, platform):
    data = tmp_path / "my crm"
    data.mkdir(parents=True, exist_ok=True)
    calls = []

    def runner(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1 if argv[0] == "plutil" else 0, "", "")
    c = schedule.Context(data_dir=data, home=tmp_path / "h", platform=platform, runner=runner,
                         env={}, exe=["/x/hermitcrm"], uid=501)
    return c, calls


def test_schedule_installs_the_backup_job_on_macos(tmp_path):
    c, calls = sched_ctx(tmp_path, "darwin")
    lines = schedule.install(c, backup_every=5)
    plist = plistlib.loads((tmp_path / "h/Library/LaunchAgents/io.hermitcrm.backup.plist")
                           .read_bytes())
    assert plist["StartInterval"] == 300 and plist["RunAtLoad"] is True
    assert plist["ProgramArguments"] == ["/x/hermitcrm", "--data", str(c.data_dir),
                                         "backup", "run", "--quiet"]
    assert "loaded io.hermitcrm.backup" in lines
    assert any("backup runs every 5 min" in l for l in lines)
    st = schedule.status(c)
    assert st["backup_installed"] is True
    assert any(l.startswith("io.hermitcrm.backup: installed every 5 min") for l in st["lines"])
    schedule.remove(c)
    assert not (tmp_path / "h/Library/LaunchAgents/io.hermitcrm.backup.plist").exists()
    assert ["launchctl", "bootout", "gui/501/io.hermitcrm.backup"] in calls


def test_schedule_no_backup(tmp_path):
    c, _ = sched_ctx(tmp_path, "darwin")
    schedule.install(c, backup=False)
    assert not (tmp_path / "h/Library/LaunchAgents/io.hermitcrm.backup.plist").exists()
    assert schedule.status(c)["backup_installed"] is False


def test_schedule_backup_on_linux_and_windows(tmp_path):
    c, _ = sched_ctx(tmp_path, "linux")
    schedule.install(c, backup_every=10)
    units = tmp_path / "h/.config/systemd/user"
    assert "OnUnitActiveSec=10min" in (units / "hermitcrm-backup.timer").read_text()
    assert "backup run --quiet" in (units / "hermitcrm-backup.service").read_text()
    assert schedule.status(c)["backup_installed"] is True
    schedule.remove(c)
    assert not (units / "hermitcrm-backup.timer").exists()
    w, _ = sched_ctx(tmp_path / "w", "win32")
    assert any("/SC MINUTE /MO 5" in l and "backup" in l for l in schedule.install(w))


@pytest.mark.parametrize("bad", [0, 1441, "x"])
def test_schedule_backup_every_bounds(tmp_path, bad):
    c, _ = sched_ctx(tmp_path, "darwin")
    with pytest.raises(schedule.ScheduleError):
        schedule.install(c, backup_every=bad)


# ----------------------------------------------------------------- doctor


def test_doctor_backup_check(folder, home, tmp_path):
    def names():
        return {c.name: c for c in doctor.run_checks(
            folder, env={}, which=lambda n: "/usr/bin/git", platform="linux", home=home,
            update_fetcher=lambda: "0.0.1", update_cache=tmp_path / "u.json")}
    assert names()["backup"].status == doctor.WARN
    backup.run(folder, {}, home=home)
    check = names()["backup"]
    assert check.status == doctor.WARN and "no job runs it" in check.detail
    c = schedule.Context(data_dir=folder, home=home, platform="linux",
                         runner=lambda a, **k: subprocess.CompletedProcess(a, 0, "", ""),
                         env={}, exe=["/x/hermitcrm"])
    schedule.install(c)
    assert names()["backup"].status == doctor.OK
