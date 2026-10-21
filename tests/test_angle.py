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

"""The optional `angle` (and `approach`) on interactions, and migration 9; the optional
`framework` beside them, and migration 16."""

from __future__ import annotations

import re
import subprocess

import pytest

from hermitcrm import migrations
from hermitcrm.models import ValidationError, normalise_framework
from hermitcrm.store import Store, split_file

BODY = "Hi Dee,\n\nangle: scale in a body is not front matter.  \n\n-- \nSam\n"


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout


def interaction_file(extra: str = "") -> str:
    return ("---\ndate: 2026-09-10T09:00\nchannel: email\ndirection: out\ncontact: dee-fox\n"
            f"subject: Hello\n{extra}outcome:\nsource: manual\n---\n{BODY}")


def old_folder(tmp_path, files, version):
    """A committed data folder at format `version` holding these interaction files."""
    root = tmp_path / "crm"
    (root / "companies/delta/interactions").mkdir(parents=True)
    (root / "companies/delta/company.md").write_text(
        "---\nname: Delta\nslug: delta\n---\n", encoding="utf-8")
    for name, text in files.items():
        (root / f"companies/delta/interactions/{name}.md").write_text(text, encoding="utf-8")
    migrations.write_format(root, version)
    git(root, "init", "-q", "-b", "main")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "old")
    return root


@pytest.fixture
def folder(tmp_path):
    return old_folder(tmp_path, {
        "plain": interaction_file(),
        "upper": interaction_file("angle: ' Scale '\n"),
        "empty": interaction_file("angle:\n"),
        "fine": interaction_file("angle: hook\n"),
        "odd": interaction_file("angle: Our own thing\n"),
    }, 8)


@pytest.fixture
def framework_folder(tmp_path):
    """A folder at format 15, the one before `framework` reached interactions."""
    return old_folder(tmp_path, {
        "plain": interaction_file("angle: hook\napproach: Team build\n"),
        "upper": interaction_file("angle: hook\nframework: ' Trigger-Tension-Trust '\n"
                                  "approach: Team build\n"),
        "empty": interaction_file("angle: hook\nframework:\napproach: Team build\n"),
        "fine": interaction_file("angle: hook\nframework: house\napproach: Team build\n"),
        "odd": interaction_file("framework: Our own thing\n"),
    }, 15)


def test_m9_normalises_angle_and_touches_nothing_else(folder):
    inter = folder / "companies/delta/interactions"
    before = {p.name: p.read_bytes() for p in inter.glob("*.md")}
    text = migrations.dry_run(folder)
    assert "9. interactions get an optional angle: 3 file(s)" in text
    migrations.ensure_current(folder)
    after = {p.name: p.read_bytes() for p in inter.glob("*.md")}
    # files without angle, or with a clean one, are byte for byte the same
    assert after["plain.md"] == before["plain.md"]
    assert after["fine.md"] == before["fine.md"]
    upper, body = split_file(after["upper.md"].decode())
    assert upper["angle"] == "scale" and body == BODY
    assert list(upper) == ["date", "channel", "direction", "contact", "subject", "angle",
                           "outcome", "source"]
    empty, body = split_file(after["empty.md"].decode())
    assert "angle" not in empty and body == BODY
    assert after["empty.md"] == before["plain.md"]
    odd, body = split_file(after["odd.md"].decode())
    assert odd["angle"] == "our own thing" and body == BODY  # kept, only folded
    assert git(folder, "status", "--porcelain") == ""


def test_m9_is_idempotent(folder):
    migrations.ensure_current(folder)
    snapshot = {p: p.read_bytes() for p in folder.rglob("*.md")}
    for path in snapshot:
        meta, _ = split_file(path.read_text())
        assert migrations.m9_angle(meta) is meta
    migrations.write_format(folder, 8)
    assert migrations.ensure_current(folder).endswith(": 0 file(s) changed")
    assert {p: p.read_bytes() for p in snapshot} == snapshot


def test_angle_sits_after_subject_and_is_omitted_when_empty(store, tmp_path):
    store.create_company("Delta")
    store.create_contact("delta", "Dee", "Fox")
    plain = store.create_interaction("delta", "email", "out", subject="Hi",
                                     contact="dee-fox", body="Hello.\n")
    meta, _ = split_file(store.interaction_path("delta", plain.id).read_text()
                         if hasattr(store, "interaction_path") else
                         (tmp_path / f"companies/delta/interactions/{plain.id}.md").read_text())
    assert "angle" not in meta and "approach" not in meta
    it = store.create_interaction("delta", "email", "out", subject="Again", contact="dee-fox",
                                  body="Hello again.\n", angle="Hook", approach="Team build")
    meta, _ = split_file((tmp_path / f"companies/delta/interactions/{it.id}.md").read_text())
    keys = list(meta)
    assert keys[keys.index("subject") + 1:keys.index("subject") + 3] == ["angle", "approach"]
    assert meta["angle"] == "hook" and meta["approach"] == "Team build"
    fresh = Store(tmp_path)
    fresh.load()
    again = next(i for i in fresh.get("delta").interactions if i.id == it.id)
    assert (again.angle, again.approach) == ("hook", "Team build")


def test_store_refuses_an_unknown_angle(store):
    store.create_company("Delta")
    store.create_contact("delta", "Dee", "Fox")
    with pytest.raises(ValidationError, match="unknown angle"):
        store.create_interaction("delta", "email", "out", contact="dee-fox", angle="loud")
    it = store.create_interaction("delta", "email", "out", contact="dee-fox", body="x\n")
    assert store.update_interaction("delta", it.id, angle="bridge").angle == "bridge"
    assert store.update_interaction("delta", it.id, angle="").angle == ""
    with pytest.raises(ValidationError, match="unknown angle"):
        store.update_interaction("delta", it.id, angle="loud")


def test_hermitcrm_set_sets_angle_in_bulk(tmp_path):
    from hermitcrm import bulk
    from hermitcrm.datafolder import init_folder
    from hermitcrm.bulk import BulkError, Ops

    root = init_folder(tmp_path / "crm", demo=True)
    store = Store(root)
    store.load()
    plan = bulk.plan(store, "interactions", ["channel=email"], Ops(set={"angle": "scale"}))
    bulk.apply(store, plan)
    fresh = Store(root)
    fresh.load()
    messages = [i for c in fresh.all() for i in c.interactions
                if i.channel == "email" and i.is_message]
    assert messages and {i.angle for i in messages} == {"scale"}
    with pytest.raises(BulkError, match="angle"):
        bulk.plan(store, "interactions", ["channel=email"], Ops(set={"angle": "loud"}))


def test_messages_tab_shows_and_filters_angle(tmp_path):
    from fastapi.testclient import TestClient

    from hermitcrm.datafolder import init_folder
    from hermitcrm.web import create_app

    root = init_folder(tmp_path / "crm", demo=True)
    store = Store(root)
    store.load()
    company = next(c for c in store.all() if any(i.is_message for i in c.interactions))
    it = next(i for i in company.interactions if i.is_message)
    store.update_interaction(company.slug, it.id, angle="unblock")
    client = TestClient(create_app(root))
    page = client.get("/messages?f_angle=unblock").text
    assert f"/interactions/{it.id}/edit" in page
    assert page.count("/edit\">edit</a>") == 1
    form = client.get(f"/companies/{company.slug}/interactions/{it.id}/edit").text
    assert '<option value="unblock" selected>' in form


# ------------------------------------------------------------------ framework

FRAMEWORK_BAD = {"framework": "a framework id: lower case letters, digits and hyphens"}


def test_normalise_framework_trims_and_lower_cases():
    assert normalise_framework(" Trigger-Tension-Trust ") == "trigger-tension-trust"
    assert normalise_framework(None) == "" and normalise_framework("  ") == ""


def test_framework_sits_between_angle_and_approach_and_is_omitted_when_empty(store, tmp_path):
    store.create_company("Delta")
    store.create_contact("delta", "Dee", "Fox")
    plain = store.create_interaction("delta", "email", "out", subject="Hi",
                                     contact="dee-fox", body="Hello.\n", angle="hook")
    path = tmp_path / f"companies/delta/interactions/{plain.id}.md"
    assert "framework" not in split_file(path.read_text())[0]
    it = store.create_interaction("delta", "email", "out", subject="Again", contact="dee-fox",
                                  body="Hello again.\n", angle="Hook", approach="Team build",
                                  framework="Trigger-Tension-Trust")
    meta, _ = split_file((tmp_path / f"companies/delta/interactions/{it.id}.md").read_text())
    keys = list(meta)
    assert keys[keys.index("subject") + 1:keys.index("subject") + 4] == [
        "angle", "framework", "approach"]
    assert meta["framework"] == "trigger-tension-trust"
    fresh = Store(tmp_path)
    fresh.load()
    again = next(i for i in fresh.get("delta").interactions if i.id == it.id)
    assert again.framework == "trigger-tension-trust" and again.extra == {}


def test_an_interaction_without_framework_keeps_its_bytes(store, tmp_path):
    store.create_company("Delta")
    store.create_contact("delta", "Dee", "Fox")
    it = store.create_interaction("delta", "email", "out", subject="Hi", contact="dee-fox",
                                  body=BODY, angle="hook", approach="Team build")
    path = tmp_path / f"companies/delta/interactions/{it.id}.md"
    before = path.read_bytes()
    assert b"framework" not in before.split(b"\n---\n")[0]
    fresh = Store(tmp_path)
    fresh.load()
    again = fresh.get("delta").interactions[0]
    assert again.framework == ""
    fresh.update_interaction("delta", it.id, subject="Hi")     # read, then written again
    assert path.read_bytes() == before


def test_other_edits_carry_the_framework_along(store):
    store.create_company("Delta")
    store.create_contact("delta", "Dee", "Fox")
    it = store.create_interaction("delta", "email", "out", subject="Hi", contact="dee-fox",
                                  body="Hello.\n", framework="house")
    assert store.update_interaction("delta", it.id, subject="Hi again").framework == "house"
    assert store.update_interaction("delta", it.id, angle="scale").framework == "house"


def test_store_refuses_a_framework_that_is_no_id(store):
    store.create_company("Delta")
    store.create_contact("delta", "Dee", "Fox")
    with pytest.raises(ValidationError) as err:
        store.create_interaction("delta", "email", "out", contact="dee-fox",
                                 framework="Trigger tension")
    assert err.value.errors == FRAMEWORK_BAD
    it = store.create_interaction("delta", "email", "out", contact="dee-fox", body="x\n")
    assert store.update_interaction("delta", it.id, framework=" House ").framework == "house"
    for bad in ("-house", "house!", "two words"):
        with pytest.raises(ValidationError) as err:
            store.update_interaction("delta", it.id, framework=bad)
        assert err.value.errors == FRAMEWORK_BAD
    assert store.update_interaction("delta", it.id, framework="").framework == ""
    # the library is not consulted: an id that was removed later still reads back
    gone = store.create_interaction("delta", "email", "out", contact="dee-fox", body="y\n",
                                    framework="removed-later")
    assert gone.framework == "removed-later"


def test_m16_normalises_framework_and_touches_nothing_else(framework_folder):
    folder = framework_folder
    inter = folder / "companies/delta/interactions"
    before = {p.name: p.read_bytes() for p in inter.glob("*.md")}
    text = migrations.dry_run(folder)
    assert "16. interactions get an optional framework: 3 file(s)" in text
    migrations.ensure_current(folder)
    after = {p.name: p.read_bytes() for p in inter.glob("*.md")}
    # a file without framework, or with a clean one, is byte for byte the same
    assert after["plain.md"] == before["plain.md"]
    assert after["fine.md"] == before["fine.md"]
    upper, body = split_file(after["upper.md"].decode())
    assert upper["framework"] == "trigger-tension-trust" and body == BODY
    assert list(upper) == ["date", "channel", "direction", "contact", "subject", "angle",
                           "framework", "approach", "outcome", "source"]
    empty, body = split_file(after["empty.md"].decode())
    assert "framework" not in empty and body == BODY
    assert after["empty.md"] == before["plain.md"]
    odd, body = split_file(after["odd.md"].decode())
    assert odd["framework"] == "our own thing" and body == BODY  # kept, only folded
    assert migrations.current_format(folder) == migrations.LATEST
    assert git(folder, "status", "--porcelain") == ""
    fresh = Store(folder)
    fresh.load()
    assert {i.id: i.framework for i in fresh.get("delta").interactions} == {
        "plain": "", "upper": "trigger-tension-trust", "empty": "", "fine": "house",
        "odd": "our own thing"}


def test_m16_is_idempotent(framework_folder):
    folder = framework_folder
    migrations.ensure_current(folder)
    snapshot = {p: p.read_bytes() for p in folder.rglob("*.md")}
    for path in snapshot:
        meta, _ = split_file(path.read_text())
        assert migrations.MIGRATIONS[-1].apply(meta) is meta
    migrations.write_format(folder, 15)
    assert migrations.ensure_current(folder).endswith(": 0 file(s) changed")
    assert {p: p.read_bytes() for p in snapshot} == snapshot


def test_migrations_15_and_16_cover_items_and_interactions():
    by_version = {m.version: m for m in migrations.MIGRATIONS}
    assert by_version[15].glob == "outreach/*.md"
    assert by_version[16].glob == "companies/*/interactions/*.md"
    assert by_version[16].apply is by_version[15].apply is migrations.m15_framework
    assert by_version[16].title == "interactions get an optional framework"


def test_a_bulk_set_keeps_the_framework(tmp_path):
    from hermitcrm import bulk
    from hermitcrm.bulk import Ops
    from hermitcrm.datafolder import init_folder

    root = init_folder(tmp_path / "crm", demo=True)
    store = Store(root)
    store.load()
    company = next(c for c in store.all() if any(
        i.is_message and i.channel == "email" for i in c.interactions))
    it = next(i for i in company.interactions if i.is_message and i.channel == "email")
    store.update_interaction(company.slug, it.id, framework="trigger-tension-trust")
    plan = bulk.plan(store, "interactions", ["channel=email"], Ops(set={"angle": "scale"}))
    bulk.apply(store, plan)
    fresh = Store(root)
    fresh.load()
    again = next(i for i in fresh.get(company.slug).interactions if i.id == it.id)
    assert (again.angle, again.framework) == ("scale", "trigger-tension-trust")


# ------------------------------------------------- framework: bulk set, Messages, forms


def demo_message(root):
    """(store, company, message) of an email in the demo folder."""
    store = Store(root)
    store.load()
    company = next(c for c in store.all() if any(
        i.is_message and i.channel == "email" for i in c.interactions))
    it = next(i for i in company.interactions if i.is_message and i.channel == "email")
    return store, company, it


def test_hermitcrm_set_sets_framework_in_bulk(tmp_path):
    from hermitcrm import bulk
    from hermitcrm.bulk import BulkError, Ops
    from hermitcrm.datafolder import init_folder

    root = init_folder(tmp_path / "crm", demo=True)
    store = Store(root)
    store.load()
    before = {p: p.read_bytes() for p in (root / "companies").rglob("*.md")}
    plan = bulk.plan(store, "interactions", ["channel=email"], Ops(set={"framework": "house"}))
    assert plan.changed and "framework: (empty) → house" in plan.render()
    assert {p: p.read_bytes() for p in (root / "companies").rglob("*.md")} == before  # dry run
    bulk.apply(store, plan)
    fresh = Store(root)
    fresh.load()
    messages = [i for c in fresh.all() for i in c.interactions
                if i.channel == "email" and i.is_message]
    assert messages and {i.framework for i in messages} == {"house"}
    others = [i for c in fresh.all() for i in c.interactions
              if i.channel != "email" and i.is_message]
    assert {i.framework for i in others} == {""}
    # the value is the store's to judge: the shape of an id, and a case is folded
    with pytest.raises(BulkError, match="framework"):
        bulk.plan(store, "interactions", ["channel=email"], Ops(set={"framework": "two words"}))
    cleared = bulk.plan(store, "interactions", ["channel=email"], Ops(unset=["framework"]))
    bulk.apply(store, cleared)
    fresh = Store(root)
    fresh.load()
    assert {i.framework for c in fresh.all() for i in c.interactions} == {""}


def test_messages_tab_shows_and_filters_framework(tmp_path):
    from fastapi.testclient import TestClient

    from hermitcrm.datafolder import init_folder
    from hermitcrm.web import create_app

    root = init_folder(tmp_path / "crm", demo=True)
    store, company, it = demo_message(root)
    store.update_interaction(company.slug, it.id, framework="trigger-tension-trust")
    client = TestClient(create_app(root))
    page = client.get("/messages").text
    heads = [h.strip() for h in re.findall(r"<th>\s*([a-z ]+?)\s*<span class=\"sort\"", page)]
    assert heads.index("framework") == heads.index("angle") + 1
    page = client.get("/messages?f_framework=trigger").text
    assert f"/interactions/{it.id}/edit" in page
    assert page.count("/edit\">edit</a>") == 1
    assert "<td>trigger-tension-trust</td>" in page
    assert "no messages" not in page.lower()
    assert "/edit\">edit</a>" not in client.get("/messages?f_framework=house").text


def test_the_log_form_sets_the_framework_and_the_edit_form_shows_it(tmp_path):
    from fastapi.testclient import TestClient

    from hermitcrm import frameworks
    from hermitcrm.datafolder import init_folder
    from hermitcrm.web import create_app

    root = init_folder(tmp_path / "crm", demo=True)
    store, company, message = demo_message(root)
    contact = message.contact
    client = TestClient(create_app(root), follow_redirects=False)
    new = client.get(f"/companies/{company.slug}/interactions/new").text
    for fid in frameworks.load(root).ids:
        assert f'<option value="{fid}"' in new
    assert '<option value="" selected>not known</option>' in new
    # a framework added to the folder's frameworks.toml shows without a restart
    (root / "frameworks.toml").write_text(
        '[frameworks.open-gap-question]\nname = "Open, gap, question"\n'
        'steps = ["Open", "Gap", "Question"]\ninstructions = "Open. Name the gap. Ask."\n',
        encoding="utf-8")
    assert '<option value="open-gap-question"' in client.get(
        f"/companies/{company.slug}/interactions/new").text
    form = {"channel": "email", "direction": "out", "contact": contact,
            "date": "2026-09-10T09:00", "subject": "Hello", "angle": "hook",
            "framework": "trigger-tension-trust", "outcome": "", "body": "Hi there.\n"}
    posted = client.post(f"/companies/{company.slug}/interactions", data=form)
    assert posted.status_code == 303
    fresh = Store(root)
    fresh.load()
    made = next(i for i in fresh.get(company.slug).interactions if i.subject == "Hello")
    assert (made.angle, made.framework) == ("hook", "trigger-tension-trust")
    edit = client.get(f"/companies/{company.slug}/interactions/{made.id}/edit").text
    assert '<option value="trigger-tension-trust" selected>' in edit
    assert '<option value="house" selected>' not in edit
    # saving the form changes it, and a bad value is answered on the field
    saved = client.post(f"/companies/{company.slug}/interactions/{made.id}/edit",
                        data={**form, "framework": "house"})
    assert saved.status_code == 303
    fresh.load()
    assert next(i for i in fresh.get(company.slug).interactions
                if i.id == made.id).framework == "house"
    bad = client.post(f"/companies/{company.slug}/interactions/{made.id}/edit",
                      data={**form, "framework": "two words"})
    assert bad.status_code == 400
    assert FRAMEWORK_BAD["framework"] in bad.text


def test_a_framework_outside_the_library_stays_selectable_and_saves(tmp_path):
    from fastapi.testclient import TestClient

    from hermitcrm.datafolder import init_folder
    from hermitcrm.web import create_app

    root = init_folder(tmp_path / "crm", demo=True)
    store, company, message = demo_message(root)
    store.update_interaction(company.slug, message.id, framework="removed-later")
    client = TestClient(create_app(root), follow_redirects=False)
    edit = client.get(f"/companies/{company.slug}/interactions/{message.id}/edit").text
    assert '<option value="removed-later" selected>removed-later</option>' in edit
    form = {"channel": message.channel, "direction": message.direction,
            "contact": message.contact, "date": message.date.strftime("%Y-%m-%dT%H:%M"),
            "subject": "Changed", "angle": "", "framework": "removed-later",
            "outcome": "", "body": message.body}
    saved = client.post(f"/companies/{company.slug}/interactions/{message.id}/edit", data=form)
    assert saved.status_code == 303
    fresh = Store(root)
    fresh.load()
    again = next(i for i in fresh.get(company.slug).interactions if i.subject == "Changed")
    assert again.framework == "removed-later"


def test_update_interaction_takes_the_stored_framework_unchanged(store, tmp_path):
    """A hand-written `Our own thing` reads as `our own thing`, which is no id. The
    edit form posts it back, so it must save; a new value still has to be an id."""
    store.create_company("Delta")
    store.create_contact("delta", "Dee", "Fox")
    it = store.create_interaction("delta", "email", "out", subject="Hi", contact="dee-fox",
                                  body="Hello.\n")
    path = tmp_path / f"companies/delta/interactions/{it.id}.md"
    path.write_text(path.read_text().replace("subject: Hi\n",
                                             "subject: Hi\nframework: Our own thing\n"))
    fresh = Store(tmp_path)
    fresh.load()
    assert fresh.get("delta").interactions[0].framework == "our own thing"
    kept = fresh.update_interaction("delta", it.id, framework="our own thing",
                                    subject="Hi again")
    assert (kept.framework, kept.subject) == ("our own thing", "Hi again")
    assert fresh.update_interaction("delta", it.id, framework=" Our Own Thing ").framework == (
        "our own thing")
    with pytest.raises(ValidationError) as err:
        fresh.update_interaction("delta", it.id, framework="another thing")
    assert err.value.errors == FRAMEWORK_BAD
    assert fresh.update_interaction("delta", it.id, framework="house").framework == "house"
    with pytest.raises(ValidationError):           # the old value is no longer the stored one
        fresh.update_interaction("delta", it.id, framework="our own thing")
