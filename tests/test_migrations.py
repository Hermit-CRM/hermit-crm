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

import re
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from hermitcrm import fields, migrations
from hermitcrm.models import Company, company_to_frontmatter
from hermitcrm.store import Store, build_file
from hermitcrm.updates import UPGRADE_HINT

BODY = "Notes stay byte for byte.  \n\ngijs_score: 3 in a body is not front matter\n"


def front_matter(text: str) -> str:
    """A file's text up to and including the closing `---` line."""
    return text[:text.index("---\n", 4) + 4]


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
    assert "Data format 0 → 20" in text
    assert "1. rename gijs_score to my_score: 3 file(s)" in text  # bolt has an empty key
    assert "2. country UK→GB, USA→US: 2 file(s)" in text
    assert "3. interaction result folded into outcome: 0 file(s)" in text
    assert "5. scores and team size become fields you define: 1 file(s)" in text
    assert "fields.toml" in text
    assert not (old_folder / "fields.toml").exists()          # a dry run writes nothing
    assert "companies/acme/company.md" in text and "companies/cygne/company.md" not in \
        text.split("2. country")[1].split("3. interaction")[0]
    assert "19. company notes become note interactions: 6 file(s)" in text  # 3 notes + 3 files
    assert {p: p.read_bytes() for p in old_folder.rglob("company.md")} == before
    assert not (old_folder / ".hermitcrm-format").exists()


def test_migrate_before_after_in_one_commit(old_folder):
    acme = old_folder / "companies/acme/company.md"
    expected = acme.read_text().replace("gijs_score: 7", "my_score: 7").replace(
        "country: UK", "country: GB")
    commits_before = int(git(["rev-list", "--count", "HEAD"], old_folder))

    summary = migrations.ensure_current(old_folder)

    assert summary.startswith("migrate: data format 0 → 20 (rename gijs_score to my_score; "
                              "country UK→GB, USA→US; interaction result folded into "
                              "outcome; stage reached-out renamed to engaged; scores and "
                              "team size become fields you define; agents may not rewrite "
                              "history (.claude/settings.json); contact notes become "
                              "note interactions; agents learn to adjust Hermit "
                              "(/hermit skill); interactions get an optional angle; "
                              "outreach drafts record the lessons they used and your reason chips; "
                              "outreach drafts record the examples they were shown; "
                              "outreach items get the keys for scheduling, sending and LinkedIn sessions; "
                              "interactions may have the source outreach (nothing to change in a file); "
                              "agents never schedule or send mail unasked (CLAUDE.md, AGENTS.md); "
                              "outreach drafts record their framework; "
                              "interactions get an optional framework; "
                              "outreach items lose the retired angle; "
                              "interactions lose the retired angle; "
                              "company notes become note interactions; interactions may have "
                              "attachments (nothing to change in a file)")
    # The body moved to a company-level note; the front matter is the same file.
    assert acme.read_text() == expected[:expected.index("---\n", 4) + 4]
    note = old_folder / "companies/acme/interactions/2026-09-01T1000-note-company.md"
    assert note.read_text().endswith("---\n" + BODY)
    bolt = (old_folder / "companies/bolt/company.md").read_text()
    assert "country: US\n" in bolt and "my_score:\n" in bolt and "gijs_score" not in bolt.split("---")[1]
    assert (old_folder / ".hermitcrm-format").read_text() == f"{migrations.LATEST}\n"
    assert int(git(["rev-list", "--count", "HEAD"], old_folder)) == commits_before + 1
    assert git(["log", "-1", "--format=%s|%an"], old_folder).startswith("migrate: data format 0 → 20")
    assert "hermitcrm" in git(["log", "-1", "--format=%an"], old_folder)
    changed = git(["show", "--name-only", "--format=", "HEAD"], old_folder).split()
    assert sorted(changed) == [".claude/settings.json", ".claude/skills/hermit/SKILL.md",
                               ".gitignore", ".hermitcrm-format",
                               "companies/acme/company.md",
                               "companies/acme/interactions/2026-09-01T1000-note-company.md",
                               "companies/bolt/company.md",
                               "companies/bolt/interactions/2026-09-01T1000-note-company.md",
                               "companies/cygne/company.md",
                               "companies/cygne/interactions/2026-09-01T1000-note-company.md",
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
    with pytest.raises(migrations.FormatTooNew, match=re.escape(UPGRADE_HINT)):
        migrations.ensure_current(old_folder)
    with pytest.raises(migrations.FormatTooNew):
        migrations.dry_run(old_folder)


def test_works_without_git(tmp_path):
    path = tmp_path / "companies/acme/company.md"
    path.parent.mkdir(parents=True)
    path.write_text(old_company_file("Acme", "acme", "UK", 1))
    # the company file, plus the fields.toml describing the score it carries
    # + .claude/settings.json, the /hermit skill and .gitignore
    assert "6 file(s) changed" in migrations.ensure_current(tmp_path)  # + its note
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

    # Byte for byte, bar the body m19 moves to a company note.
    assert path.read_bytes() == before[:before.index(b"---\n", 4) + 4]
    # fields.toml, .claude/settings.json, the /hermit skill, .gitignore, + company.md
    # (its body) and the note that body became
    assert "6 file(s) changed" in summary
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
    # + .claude/settings.json, the /hermit skill, .gitignore
    assert "5 file(s) changed" in migrations.ensure_current(tmp_path)  # + the body's note
    store = Store(tmp_path)
    assert store.load() == []
    c = store.get("acme")
    assert c.stage == "engaged"
    assert [(e.from_stage, e.to_stage) for e in c.stage_history] == [
        ("prospect", "engaged"), ("engaged", "lost")]
    assert path.read_text().endswith("---\n") and "reached-out" not in path.read_text()
    assert c.interactions[0].body == BODY
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
        old_company_file("Acme", "acme", "GB", 1).removesuffix(BODY)  # no company body:
        .replace("gijs_score", "my_score"))                         # m19 has nothing to port
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


# ------------------------------------- 19: company notes -> notes interactions


def company_folder(tmp_path, bodies: dict) -> Path:
    """Companies at format 18, each with the given company.md body."""
    for slug, body in bodies.items():
        path = tmp_path / f"companies/{slug}/company.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = old_company_file(slug.title(), slug, "GB", 1).removesuffix(BODY)
        path.write_text(text.replace("gijs_score", "my_score") + body)
    migrations.write_format(tmp_path, 18)
    return tmp_path


def test_m19_ports_company_notes_to_company_level_notes(tmp_path):
    root = company_folder(tmp_path, {
        "acme": "Founder-led, 12 people.\n\n21/10/2026: asked for a pricing sheet\n"
                "Second line of the same note.\n03/09/2026: met at a fair\n"
                "Left over at the end.\n",
        "bolt": "Only undated text.\nOn two lines.\n",
        "cygne": "",
    })
    before = {slug: (root / f"companies/{slug}/company.md").read_text()
              for slug in ("acme", "bolt", "cygne")}

    dry = migrations.dry_run(root)
    assert "19. company notes become note interactions: 6 file(s)" in dry
    assert not (root / "companies/acme/interactions").exists()  # a dry run writes nothing
    assert {s: (root / f"companies/{s}/company.md").read_text() for s in before} == before

    migrations.ensure_current(root)
    # Front matter byte for byte, `updated` included; only the body goes.
    for slug, text in before.items():
        assert (root / f"companies/{slug}/company.md").read_text() == front_matter(text)

    store = Store(root)
    assert store.load() == []
    acme = store.get("acme")
    assert acme.notes == ""
    # A dated line opens a note on its day and keeps the lines under it; the text
    # before the first one is dated by the company's `created`.
    assert sorted(i.id for i in acme.interactions) == [
        "2026-09-01T1000-note-company",
        "2026-09-03T0000-note-company",
        "2026-10-21T0000-note-company",
    ]
    by_id = {i.id: i for i in acme.interactions}
    for it in acme.interactions:
        assert (it.channel, it.direction, it.contact, it.source) == (
            "note", "", "", "migration")
    assert by_id["2026-09-01T1000-note-company"].body == "Founder-led, 12 people.\n"
    assert by_id["2026-10-21T0000-note-company"].body == (
        "21/10/2026: asked for a pricing sheet\nSecond line of the same note.\n")
    assert by_id["2026-09-03T0000-note-company"].body == (
        "03/09/2026: met at a fair\nLeft over at the end.\n")
    assert acme.last_touch is None  # notes are memos, not contact made

    bolt, = store.get("bolt").interactions
    assert (bolt.id, bolt.body) == ("2026-09-01T1000-note-company",
                                    "Only undated text.\nOn two lines.\n")
    assert store.get("cygne").interactions == []
    assert not (root / "companies/cygne/interactions").exists()  # empty body: untouched


def split_company(body, fallback=datetime(2026, 9, 1, 10, 0)):
    return [(f"{when:%Y-%m-%d %H:%M}", text)
            for when, text in migrations._split_company_notes(body, fallback)]


@pytest.mark.parametrize("body, expected", [
    # `08/10/2026: text` -- slashes, a colon, text on the same line
    ("08/10/2026: sent the deck\n", [("2026-10-08 00:00", "08/10/2026: sent the deck\n")]),
    # `21-10-2026` alone on its line, the text on the lines below it
    ("21-10-2026\nProposition: a pilot.\nMore text.\n",
     [("2026-10-21 00:00", "21-10-2026\nProposition: a pilot.\nMore text.\n")]),
    # ISO date, text on the same line
    ("2026-10-05 call booked\n", [("2026-10-05 00:00", "2026-10-05 call booked\n")]),
    ("21.10.2026 - dots and a dash\n", [("2026-10-21 00:00", "21.10.2026 - dots and a dash\n")]),
    ("1-2-2026 short day and month\n", [("2026-02-01 00:00", "1-2-2026 short day and month\n")]),
    ("  21-10-2026\n  indented\n", [("2026-10-21 00:00", "  21-10-2026\n  indented\n")]),
    # two dates in one body: each keeps its own lines, in file order
    ("21-10-2026\nFirst.\n\n05/11/2026: second\nStill second.\n",
     [("2026-10-21 00:00", "21-10-2026\nFirst.\n"),
      ("2026-11-05 00:00", "05/11/2026: second\nStill second.\n")]),
    # an undated lead is a note at the fallback date; blank lines at the ends go
    ("\n\nMet at a fair.\n\n21-10-2026\nFollow-up.\n\n",
     [("2026-09-01 10:00", "Met at a fair.\n"), ("2026-10-21 00:00", "21-10-2026\nFollow-up.\n")]),
    # the machine-imported block is its own note, apart from the hand-written text
    ("Likes short mails.\n\nImported fields (2026-09-14):\n- hq_city: Utrecht\n- category: saas\n",
     [("2026-09-01 10:00", "Likes short mails.\n"),
      ("2026-09-14 00:00",
       "Imported fields (2026-09-14):\n- hq_city: Utrecht\n- category: saas\n")]),
    ("Imported fields (2026-09-14):\n- hq_city: Utrecht\n",
     [("2026-09-14 00:00", "Imported fields (2026-09-14):\n- hq_city: Utrecht\n")]),
    # an impossible date is an ordinary line; so is a date inside a line, or a mixed separator
    ("31-04-2026 not a date\nmonth 13: 05/13/2026\n21-10/2026 mixed\nsee 2026-10-05\n",
     [("2026-09-01 10:00",
       "31-04-2026 not a date\nmonth 13: 05/13/2026\n21-10/2026 mixed\nsee 2026-10-05\n")]),
    ("12345678 an id, not a date\n2026-10-051 no\n",
     [("2026-09-01 10:00", "12345678 an id, not a date\n2026-10-051 no\n")]),
    ("\n  \n\n", []),
    ("", []),
    ("Windows lines\r\n21-10-2026\r\nunder it\r\n",
     [("2026-09-01 10:00", "Windows lines\n"), ("2026-10-21 00:00", "21-10-2026\nunder it\n")]),
])
def test_split_company_notes(body, expected):
    assert split_company(body) == expected


def test_m7_keeps_its_own_splitter():
    """Contacts still split on `dd/mm/yyyy:` only, and lines under it stay separate."""
    notes = migrations._split_notes("21-10-2026\ntext\n01/10/2026: a\nb\n", datetime(2026, 9, 1))
    assert [(f"{w:%Y-%m-%d}", t) for w, t in notes] == [
        ("2026-09-01", "21-10-2026\ntext\n"), ("2026-10-01", "01/10/2026: a\n"),
        ("2026-09-01", "b\n")]


def test_m19_keeps_the_lines_under_a_date_and_lists_them_in_a_dry_run(tmp_path):
    root = company_folder(tmp_path, {
        "acme": "Hand-written remark.\n\n21-10-2026\nProposition: a pilot.\nMore text.\n",
        "bolt": "Imported fields (2026-09-14):\n- hq_city: Utrecht\n- category: saas\n",
    })
    before = {s: (root / f"companies/{s}/company.md").read_text() for s in ("acme", "bolt")}

    dry = migrations.dry_run(root)
    assert "19. company notes become note interactions: 5 file(s)" in dry
    assert "     companies/acme/interactions/2026-10-21T0000-note-company.md" in dry
    assert "     companies/bolt/interactions/2026-09-14T0000-note-company.md" in dry
    assert not (root / "companies/acme/interactions").exists()

    migrations.ensure_current(root)
    for slug, text in before.items():
        assert (root / f"companies/{slug}/company.md").read_text() == front_matter(text)
    store = Store(root)
    assert store.load() == []
    by_id = {i.id: i for i in store.get("acme").interactions}
    assert by_id["2026-10-21T0000-note-company"].body == (
        "21-10-2026\nProposition: a pilot.\nMore text.\n")
    assert by_id["2026-09-01T1000-note-company"].body == "Hand-written remark.\n"
    bolt, = store.get("bolt").interactions
    assert bolt.date == datetime(2026, 9, 14) and bolt.body.startswith("Imported fields (")


def test_m19_two_notes_on_the_same_day_get_unique_ids(tmp_path):
    root = company_folder(tmp_path, {"acme": "21-10-2026\none\n21/10/2026: two\n"})
    migrations.ensure_current(root)
    names = sorted(p.name for p in (root / "companies/acme/interactions").glob("*.md"))
    assert names == ["2026-10-21T0000-note-company-2.md", "2026-10-21T0000-note-company.md"]
    # in file order: the first note owns the plain id
    assert (root / "companies/acme/interactions/2026-10-21T0000-note-company.md"
            ).read_text().endswith("21-10-2026\none\n")


def test_m19_dates_an_undated_body_by_updated_when_there_is_no_created(tmp_path):
    root = company_folder(tmp_path, {"acme": "Plain text.\n"})
    path = root / "companies/acme/company.md"
    path.write_text("".join(l for l in path.read_text().splitlines(keepends=True)
                            if not l.startswith("created:")))
    updated = re.search(r"^updated: (\d{4}-\d\d-\d\d)T(\d\d):(\d\d)", path.read_text(),
                        re.M).groups()
    migrations.ensure_current(root)
    names = [p.name for p in (root / "companies/acme/interactions").glob("*.md")]
    assert names == [f"{updated[0]}T{updated[1]}{updated[2]}-note-company.md"]


def test_m19_second_run_changes_nothing(tmp_path):
    root = company_folder(tmp_path, {"acme": "21/10/2026: one\nTwo.\n"})
    migrations.ensure_current(root)
    snapshot = {p: p.read_bytes() for p in root.rglob("*.md")}
    assert migrations.m19_company_notes(
        root, {"companies/acme/company.md": {}}, write=True) == []
    migrations.write_format(root, 18)
    assert migrations.ensure_current(root).endswith(": 0 file(s) changed")
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == snapshot


def test_m19_does_not_overwrite_an_existing_interaction(tmp_path):
    root = company_folder(tmp_path, {"acme": "21/10/2026: one\n"})
    folder = root / "companies/acme/interactions"
    folder.mkdir()
    (folder / "2026-10-21T0000-note-company.md").write_text("---\nchannel: note\n---\nmine\n")
    migrations.ensure_current(root)
    assert (folder / "2026-10-21T0000-note-company.md").read_text().endswith("mine\n")
    assert (folder / "2026-10-21T0000-note-company-2.md").read_text().endswith(
        "21/10/2026: one\n")


def test_m19_leaves_contact_files_alone(tmp_path):
    root = company_folder(tmp_path, {"acme": ""})
    contact = root / "companies/acme/contacts/jan.md"
    contact.parent.mkdir()
    contact.write_text(CONTACT_FM + "A contact body, ported by m7 not m19.\n")
    assert migrations.m19_company_notes(
        root, {"companies/acme/contacts/jan.md": {}}, write=True) == []
    assert contact.read_text().endswith("not m19.\n")


@pytest.mark.parametrize("meta, expected", [
    ({"state": "drafted"}, {"state": "drafted"}),
    ({"state": "drafted", "framework": ""}, {"state": "drafted"}),
    ({"state": "drafted", "framework": None}, {"state": "drafted"}),
    ({"state": "drafted", "framework": " Trigger-Tension-Trust "},
     {"state": "drafted", "framework": "trigger-tension-trust"}),
])
def test_the_framework_migration_normalises_and_is_idempotent(meta, expected):
    once = migrations.m15_framework(meta)
    assert once == expected and migrations.m15_framework(once) == once


def test_the_framework_migration_returns_an_unchanged_value_as_it_is():
    meta = {"state": "drafted", "framework": "house"}
    assert migrations.m15_framework(meta) is meta
    assert next(m for m in migrations.MIGRATIONS if m.version == 15).glob == "outreach/*.md"


def test_a_folder_at_format_14_gets_the_framework_normalised_in_one_run(tmp_path):
    from hermitcrm import outreach
    from hermitcrm.datafolder import init_folder

    root = init_folder(tmp_path / "crm", demo=True)

    def write(item_id, framework):
        item = outreach.Item(id=item_id, state="drafted", company="lindenhof-data",
                             contact="mara-keller", framework=framework,
                             body="Hi Mara,\n\nA first message.\n\nSam\n")
        path = root / item.path
        path.parent.mkdir(exist_ok=True)
        return path, item

    messy, item = write("2026-10-16T0900-email-lindenhof-data-mara-keller", "house")
    messy.write_text(outreach.item_text(item).replace("framework: house\n",
                                                      'framework: " House"\n'), encoding="utf-8")
    plain, old = write("2026-10-16T0901-email-kestrel-metrics-daan-visser", "")
    plain.write_text(outreach.item_text(old), encoding="utf-8")
    before = plain.read_bytes()
    assert b"framework" not in before and b'framework: " House"' in messy.read_bytes()

    migrations.write_format(root, 14)
    migrations.ensure_current(root)

    assert migrations.current_format(root) == migrations.LATEST
    assert messy.read_text(encoding="utf-8") == outreach.item_text(item)
    assert outreach.get_item(root, item.id).framework == "house"
    assert plain.read_bytes() == before


@pytest.mark.parametrize("meta, expected", [
    ({"state": "drafted"}, {"state": "drafted"}),
    ({"state": "drafted", "angle": "hook"}, {"state": "drafted"}),
    ({"state": "drafted", "angle": " Hook "}, {"state": "drafted"}),     # a hand-edited value
    ({"state": "drafted", "angle": ""}, {"state": "drafted"}),
    ({"state": "drafted", "angle": "hook", "critic_reason": "wrong angle"},
     {"state": "drafted", "critic_reason": "wrong angle"}),              # free text stays
])
def test_the_drop_angle_migration_removes_only_the_key_and_is_idempotent(meta, expected):
    once = migrations.m17_drop_angle(meta)
    assert once == expected and migrations.m17_drop_angle(once) == once


def test_the_drop_angle_migration_returns_a_file_without_angle_as_it_is():
    meta = {"state": "drafted", "framework": "house"}
    assert migrations.m17_drop_angle(meta) is meta
    by_version = {m.version: m for m in migrations.MIGRATIONS}
    assert by_version[17].glob == "outreach/*.md"
    assert by_version[18].glob == "companies/*/interactions/*.md"
    assert by_version[19].glob == "companies/*/company.md"
    assert migrations.LATEST == 20


def test_a_folder_at_format_16_loses_angle_from_items_and_interactions(tmp_path):
    from hermitcrm.datafolder import init_folder

    root = init_folder(tmp_path / "crm", demo=True)
    body = "Hi Mara,\n\nBody mentioning the word angle stays.\n\nSam\n"
    files = {
        root / "outreach/2026-10-16T0900-email-lindenhof-data-mara-keller.md":
            f"---\nstate: drafted\nkind: first\nangle: hook\nframework: house\n---\n{body}",
        root / "companies/lindenhof-data/interactions/2026-10-16T0900-email-mara.md":
            f"---\nchannel: email\nangle: Bridge\nframework: house\n---\n{body}",
    }
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    migrations.write_format(root, 16)
    migrations.ensure_current(root)
    assert migrations.current_format(root) == migrations.LATEST
    for path in files:
        text = path.read_text(encoding="utf-8")
        head, _, rest = text.partition("\n---\n")
        assert "angle" not in head and "framework: house" in head
        assert rest == body
    migrations.ensure_current(root)     # a second run is a no-op
    assert all("angle:" not in p.read_text(encoding="utf-8") for p in files)
