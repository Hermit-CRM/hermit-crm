"""Data format migrations: fixtures before/after, dry run, idempotence, one commit."""

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from owncrm import migrations
from owncrm.models import Company, company_to_frontmatter
from owncrm.store import Store, build_file

BODY = "Notes stay byte for byte.  \n\ngijs_score: 3 in a body is not front matter\n"


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


def old_company_file(name, slug, country="", score=None) -> str:
    """A company.md as the pre-versioning app wrote it (gijs_score, UK/USA)."""
    c = Company(name=name, slug=slug, created=datetime(2026, 9, 1, 10, 0),
                updated=datetime(2026, 9, 1, 10, 0))
    meta = company_to_frontmatter(c)
    meta = {("gijs_score" if k == "my_score" else k): v for k, v in meta.items()}
    meta["gijs_score"] = score
    meta["country"] = country
    return build_file(meta, BODY)


@pytest.fixture
def old_folder(tmp_path):
    root = tmp_path / "crm"
    for slug, name, country, score in (("acme", "Acme Ltd", "UK", 7),
                                       ("bolt", "Bolt Inc", "USA", None),
                                       ("cygne", "Cygne SA", "FR", 2)):
        path = root / "companies" / slug / "company.md"
        path.parent.mkdir(parents=True)
        path.write_text(old_company_file(name, slug, country, score), encoding="utf-8")
    git(["init", "-q", "-b", "main"], root)
    git(["-c", "user.name=t", "-c", "user.email=t@example.com", "add", "-A"], root)
    git(["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "old"], root)
    return root


def test_format_detection(tmp_path, old_folder):
    assert migrations.current_format(tmp_path / "empty") == migrations.LATEST
    assert migrations.current_format(old_folder) == 0
    migrations.write_format(tmp_path, 1)
    assert migrations.current_format(tmp_path) == 1


def test_dry_run_lists_files_and_writes_nothing(old_folder):
    before = {p: p.read_bytes() for p in old_folder.rglob("company.md")}
    text = migrations.dry_run(old_folder)
    assert "Data format 0 → 2" in text
    assert "1. rename gijs_score to my_score: 3 file(s)" in text  # bolt has an empty key
    assert "2. country UK→GB, USA→US: 2 file(s)" in text
    assert "companies/acme/company.md" in text and "companies/cygne/company.md" not in \
        text.split("2. country")[1]
    assert {p: p.read_bytes() for p in old_folder.rglob("company.md")} == before
    assert not (old_folder / ".owncrm-format").exists()


def test_migrate_before_after_in_one_commit(old_folder):
    acme = old_folder / "companies/acme/company.md"
    expected = acme.read_text().replace("gijs_score: 7", "my_score: 7").replace(
        "country: UK", "country: GB")
    commits_before = int(git(["rev-list", "--count", "HEAD"], old_folder))

    summary = migrations.ensure_current(old_folder)

    assert summary.startswith("migrate: data format 0 → 2 (rename gijs_score to my_score; "
                              "country UK→GB, USA→US)")
    assert acme.read_text() == expected and acme.read_text().endswith(BODY)
    bolt = (old_folder / "companies/bolt/company.md").read_text()
    assert "country: US\n" in bolt and "my_score:\n" in bolt and "gijs_score" not in bolt.split("---")[1]
    assert (old_folder / ".owncrm-format").read_text() == "2\n"
    assert int(git(["rev-list", "--count", "HEAD"], old_folder)) == commits_before + 1
    assert git(["log", "-1", "--format=%s|%an"], old_folder).startswith("migrate: data format 0 → 2")
    assert "owncrm" in git(["log", "-1", "--format=%an"], old_folder)
    changed = git(["show", "--name-only", "--format=", "HEAD"], old_folder).split()
    assert sorted(changed) == [".owncrm-format", "companies/acme/company.md",
                               "companies/bolt/company.md", "companies/cygne/company.md"]
    assert git(["status", "--porcelain"], old_folder) == ""
    store = Store(old_folder)
    assert store.load() == []
    assert store.get("acme").my_score == 7 and store.get("acme").country == "GB"


def test_migrations_are_idempotent(old_folder):
    migrations.ensure_current(old_folder)
    snapshot = {p: p.read_bytes() for p in old_folder.rglob("*.md")}
    head = git(["rev-parse", "HEAD"], old_folder)
    assert migrations.ensure_current(old_folder) == ""
    assert git(["rev-parse", "HEAD"], old_folder) == head
    # Re-running the functions themselves on migrated data changes nothing either.
    (old_folder / ".owncrm-format").write_text("0\n")
    assert migrations.ensure_current(old_folder).endswith(": 0 file(s) changed")
    assert {p: p.read_bytes() for p in old_folder.rglob("*.md")} == snapshot
    assert migrations.m1_my_score({"gijs_score": 1, "my_score": 5}) == {"my_score": 5}


def test_refuses_data_newer_than_code(old_folder):
    migrations.write_format(old_folder, migrations.LATEST + 1)
    with pytest.raises(migrations.FormatTooNew, match="pipx upgrade owncrm"):
        migrations.ensure_current(old_folder)
    with pytest.raises(migrations.FormatTooNew):
        migrations.dry_run(old_folder)


def test_works_without_git(tmp_path):
    path = tmp_path / "companies/acme/company.md"
    path.parent.mkdir(parents=True)
    path.write_text(old_company_file("Acme", "acme", "UK", 1))
    assert "1 file(s) changed" in migrations.ensure_current(tmp_path)
    assert "country: GB" in path.read_text()
