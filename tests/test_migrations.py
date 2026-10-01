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

"""Data format migrations: fixtures before/after, dry run, idempotence, one commit."""

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from hermitcrm import fields, migrations
from hermitcrm.models import Company, company_to_frontmatter
from hermitcrm.store import Store, build_file

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
    assert "Data format 0 → 7" in text
    assert "1. rename gijs_score to my_score: 3 file(s)" in text  # bolt has an empty key
    assert "2. country UK→GB, USA→US: 2 file(s)" in text
    assert "3. interaction result folded into outcome: 0 file(s)" in text
    assert "5. scores and team size become fields you define: 1 file(s)" in text
    assert "fields.toml" in text
    assert not (old_folder / "fields.toml").exists()          # a dry run writes nothing
    assert "companies/acme/company.md" in text and "companies/cygne/company.md" not in \
        text.split("2. country")[1]
    assert {p: p.read_bytes() for p in old_folder.rglob("company.md")} == before
    assert not (old_folder / ".hermitcrm-format").exists()


def test_migrate_before_after_in_one_commit(old_folder):
    acme = old_folder / "companies/acme/company.md"
    expected = acme.read_text().replace("gijs_score: 7", "my_score: 7").replace(
        "country: UK", "country: GB")
    commits_before = int(git(["rev-list", "--count", "HEAD"], old_folder))

    summary = migrations.ensure_current(old_folder)

    assert summary.startswith("migrate: data format 0 → 7 (rename gijs_score to my_score; "
                              "country UK→GB, USA→US; interaction result folded into "
                              "outcome; stage reached-out renamed to engaged; scores and "
                              "team size become fields you define; agents may not rewrite "
                              "history (.claude/settings.json); contact notes become "
                              "note interactions)")
    assert acme.read_text() == expected and acme.read_text().endswith(BODY)
    bolt = (old_folder / "companies/bolt/company.md").read_text()
    assert "country: US\n" in bolt and "my_score:\n" in bolt and "gijs_score" not in bolt.split("---")[1]
    assert (old_folder / ".hermitcrm-format").read_text() == "7\n"
    assert int(git(["rev-list", "--count", "HEAD"], old_folder)) == commits_before + 1
    assert git(["log", "-1", "--format=%s|%an"], old_folder).startswith("migrate: data format 0 → 7")
    assert "hermitcrm" in git(["log", "-1", "--format=%an"], old_folder)
    changed = git(["show", "--name-only", "--format=", "HEAD"], old_folder).split()
    assert sorted(changed) == [".claude/settings.json", ".hermitcrm-format",
                               "companies/acme/company.md",
                               "companies/bolt/company.md", "companies/cygne/company.md",
                               "fields.toml"]
    assert git(["status", "--porcelain"], old_folder) == ""
    store = Store(old_folder)
    assert store.load() == []
    # my_score is a user-defined field now, so it round-trips through `extra`
    assert store.get("acme").extra["my_score"] == 7 and store.get("acme").country == "GB"


def test_migrations_are_idempotent(old_folder):
    migrations.ensure_current(old_folder)
    snapshot = {p: p.read_bytes() for p in old_folder.rglob("*.md")}
    head = git(["rev-parse", "HEAD"], old_folder)
    assert migrations.ensure_current(old_folder) == ""
    assert git(["rev-parse", "HEAD"], old_folder) == head
    # Re-running the functions themselves on migrated data changes nothing either.
    (old_folder / ".hermitcrm-format").write_text("0\n")
    assert migrations.ensure_current(old_folder).endswith(": 0 file(s) changed")
    assert {p: p.read_bytes() for p in old_folder.rglob("*.md")} == snapshot
    assert migrations.m1_my_score({"gijs_score": 1, "my_score": 5}) == {"my_score": 5}


def test_refuses_data_newer_than_code(old_folder):
    migrations.write_format(old_folder, migrations.LATEST + 1)
    with pytest.raises(migrations.FormatTooNew, match="pipx upgrade hermitcrm"):
        migrations.ensure_current(old_folder)
    with pytest.raises(migrations.FormatTooNew):
        migrations.dry_run(old_folder)


def test_works_without_git(tmp_path):
    path = tmp_path / "companies/acme/company.md"
    path.parent.mkdir(parents=True)
    path.write_text(old_company_file("Acme", "acme", "UK", 1))
    # the company file, plus the fields.toml describing the score it carries
    assert "3 file(s) changed" in migrations.ensure_current(tmp_path)  # + .claude/settings.json
    assert "country: GB" in path.read_text()
    assert 'key = "my_score"' in (tmp_path / "fields.toml").read_text()


def test_m5_describes_the_old_fields_without_touching_a_company_file(tmp_path):
    """The riskiest migration here, so this asserts the bytes.

    my_score and friends were plain YAML before and are plain YAML now. All
    that changes is that the folder gains a description of them.
    """
    path = tmp_path / "companies/acme/company.md"
    path.parent.mkdir(parents=True)
    path.write_text(old_company_file("Acme", "acme", "GB", 7).replace("gijs_score", "my_score"))
    migrations.write_format(tmp_path, 4)
    before = path.read_bytes()

    summary = migrations.ensure_current(tmp_path)

    assert path.read_bytes() == before          # byte for byte
    assert "2 file(s) changed" in summary  # fields.toml, .claude/settings.json
    defs = fields.load(tmp_path)
    assert [d.key for d in defs] == ["my_score"]     # only what the folder used
    assert defs[0].type == "number" and "companies" in defs[0].show_in
    store = Store(tmp_path)
    assert store.load() == []
    assert store.get("acme").extra["my_score"] == 7


def test_m5_leaves_a_folder_that_never_used_them_alone(tmp_path):
    path = tmp_path / "companies/acme/company.md"
    path.parent.mkdir(parents=True)
    text = old_company_file("Acme", "acme", "GB", 1)
    path.write_text("\n".join(l for l in text.split("\n") if "gijs_score" not in l))
    migrations.write_format(tmp_path, 4)
    migrations.ensure_current(tmp_path)
    assert not (tmp_path / "fields.toml").exists()


def test_m4_renames_reached_out_in_stage_and_history(tmp_path):
    path = tmp_path / "companies/acme/company.md"
    path.parent.mkdir(parents=True)
    text = old_company_file("Acme", "acme", "GB", 1).replace("stage: prospect", "stage: reached-out")
    text = text.replace("created:", "stage_history:\n"
                        "  - {date: 2026-09-10, from: prospect, to: reached-out}\n"
                        "  - {date: 2026-09-12, from: reached-out, to: lost, reason: later}\n"
                        "created:", 1)
    path.write_text(text)
    migrations.write_format(tmp_path, 3)
    assert "2 file(s) changed" in migrations.ensure_current(tmp_path)  # + .claude/settings.json
    store = Store(tmp_path)
    assert store.load() == []
    c = store.get("acme")
    assert c.stage == "engaged"
    assert [(e.from_stage, e.to_stage) for e in c.stage_history] == [
        ("prospect", "engaged"), ("engaged", "lost")]
    assert path.read_text().endswith(BODY) and "reached-out" not in path.read_text()
    meta = {"stage": "offer"}
    assert migrations.m4_stage_engaged(meta) is meta


# ------------------------------------------------- 7: contact notes -> notes


CONTACT_FM = ("---\nfirst_name: Jan\nlast_name: Jansen\nslug: jan\ntitle: CEO\n"
              "created: 2026-09-14T17:02\nupdated: 2026-09-15T21:36\n---\n")


def contact_folder(tmp_path, bodies: dict) -> Path:
    for slug, body in bodies.items():
        path = tmp_path / f"companies/acme/contacts/{slug}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CONTACT_FM.replace("slug: jan", f"slug: {slug}") + body)
    (tmp_path / "companies/acme/company.md").write_text(
        old_company_file("Acme", "acme", "GB", 1).replace("gijs_score", "my_score"))
    migrations.write_format(tmp_path, 6)
    return tmp_path


def test_m7_ports_contact_notes_to_note_interactions(tmp_path):
    root = contact_folder(tmp_path, {
        "jan": "01/10/2026: didn't accept invite\n"
                 "founder_sales_nav_url: https://www.linkedin.com/sales/lead/X\n",
        "anna": "founder_sales_nav_url: https://www.linkedin.com/sales/lead/Y\n",
        "jo": "Met at a fair.\nLikes detail.\n\n31/02/2026: not a date, an ordinary line\n",
        "empty": "",
    })
    before = {slug: (root / f"companies/acme/contacts/{slug}.md").read_text()
              for slug in ("jan", "anna", "jo", "empty")}

    dry = migrations.dry_run(root)
    assert "7. contact notes become note interactions: 7 file(s)" in dry
    assert not (root / "companies/acme/interactions").exists()  # a dry run writes nothing

    migrations.ensure_current(root)
    folder = root / "companies/acme/interactions"
    assert sorted(p.name for p in folder.glob("*.md")) == [
        "2026-09-14T1702-note-anna.md",
        "2026-09-14T1702-note-jan.md",
        "2026-09-14T1702-note-jo.md",
        "2026-10-01T0000-note-jan.md",
    ]
    # Each contact keeps its front matter byte for byte and loses only the body.
    for slug in ("jan", "anna", "jo", "empty"):
        text = (root / f"companies/acme/contacts/{slug}.md").read_text()
        assert text == before[slug][:before[slug].index("---\n", 4) + 4]

    store = Store(root)
    assert store.load() == []
    acme = store.get("acme")
    by_id = {i.id: i for i in acme.interactions}
    dated = by_id["2026-10-01T0000-note-jan"]
    assert (dated.channel, dated.direction, dated.contact, dated.source) == (
        "note", "", "jan", "migration")
    assert dated.body == "01/10/2026: didn't accept invite\n"
    assert by_id["2026-09-14T1702-note-jan"].body.startswith("founder_sales_nav_url:")
    assert by_id["2026-09-14T1702-note-jo"].body == (
        "Met at a fair.\nLikes detail.\n\n31/02/2026: not a date, an ordinary line\n")
    assert acme.last_touch is None  # notes are memos, not contact made

    # Idempotent: the bodies are gone, so a second run has nothing to port.
    assert migrations.current_format(root) == migrations.LATEST
    assert migrations.m7_contact_notes(root, {"companies/acme/contacts/jan.md": {}},
                                       write=True) == []


def test_m7_does_not_overwrite_an_existing_interaction(tmp_path):
    root = contact_folder(tmp_path, {"jan": "01/10/2026: one\n"})
    folder = root / "companies/acme/interactions"
    folder.mkdir()
    (folder / "2026-10-01T0000-note-jan.md").write_text("---\nchannel: note\n---\nmine\n")
    migrations.ensure_current(root)
    assert (folder / "2026-10-01T0000-note-jan.md").read_text().endswith("mine\n")
    assert (folder / "2026-10-01T0000-note-jan-2.md").read_text().endswith("01/10/2026: one\n")
