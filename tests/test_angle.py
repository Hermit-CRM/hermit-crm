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

"""The optional `angle` (and `approach`) on interactions, and migration 9."""

from __future__ import annotations

import subprocess

import pytest

from hermitcrm import migrations
from hermitcrm.models import ValidationError
from hermitcrm.store import Store, split_file

BODY = "Hi Dee,\n\nangle: scale in a body is not front matter.  \n\n-- \nSam\n"


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout


def interaction_file(extra: str = "") -> str:
    return ("---\ndate: 2026-09-10T09:00\nchannel: email\ndirection: out\ncontact: dee-fox\n"
            f"subject: Hello\n{extra}outcome:\nsource: manual\n---\n{BODY}")


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "crm"
    (root / "companies/delta/interactions").mkdir(parents=True)
    (root / "companies/delta/company.md").write_text(
        "---\nname: Delta\nslug: delta\n---\n", encoding="utf-8")
    files = {
        "plain": interaction_file(),
        "upper": interaction_file("angle: ' Scale '\n"),
        "empty": interaction_file("angle:\n"),
        "fine": interaction_file("angle: hook\n"),
        "odd": interaction_file("angle: Our own thing\n"),
    }
    for name, text in files.items():
        (root / f"companies/delta/interactions/{name}.md").write_text(text, encoding="utf-8")
    migrations.write_format(root, 8)
    git(root, "init", "-q", "-b", "main")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "old")
    return root


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
