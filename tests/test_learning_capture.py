# Hermit CRM: what the learning loop captures on an outreach item (reason
# chips on a tracked edit, the lessons a draft carried) and migration 10.

from __future__ import annotations

from hermitcrm import migrations, outreach
from hermitcrm.store import Store, split_file
from test_outreach_web import (  # noqa: F401  (fixtures)
    MARA, client, commits, drafted, fake, post, query, root,
)


def test_reason_chips_are_kept_on_the_edit_known_ones_only_in_order(client, root):
    item = drafted(client, root)
    body = item.body.replace("caught my eye", "stood out")
    outreach.save_text(Store(root), item.id, subject=item.subject, body=body,
                       note="too much", tags=["wrong-tone", "TOO-LONG", "made-up", "too-long"])
    [edit] = outreach.get_item(root, item.id).edits
    assert edit.tags == ["too-long", "wrong-tone"]
    meta, _ = split_file((root / item.path).read_text())
    assert meta["edits"][0]["tags"] == ["too-long", "wrong-tone"]


def test_an_edit_without_chips_writes_no_tags_key(client, root):
    item = drafted(client, root)
    body = item.body.replace("caught my eye", "stood out")
    outreach.save_text(Store(root), item.id, subject=item.subject, body=body)
    meta, _ = split_file((root / item.path).read_text())
    assert "tags" not in meta["edits"][0]


def test_lessons_used_round_trips_and_is_absent_when_empty():
    item = outreach.Item(id="x", state="drafted", ai_body="Hi.", body="Hi.",
                         lessons_used=["Labc123", "Labc123", " Ldef456 "])
    meta = item.to_frontmatter()
    assert meta["lessons_used"] == ["Labc123", "Labc123", " Ldef456 "]
    again = outreach.item_from_text("x", outreach.item_text(item))
    assert again.lessons_used == ["Labc123", "Ldef456"]
    assert "lessons_used" not in outreach.Item(id="y").to_frontmatter()


def test_apply_draft_copies_the_lessons_of_the_prompt():
    item = outreach.Item(id="x")
    draft = outreach.Draft(subject="S", body="B?", lessons_used=["Labc123"])
    outreach._apply_draft(item, draft, False, outreach.datetime(2026, 10, 18, 9, 0))
    assert item.lessons_used == ["Labc123"]


def test_never_write_is_a_hard_check():
    ctx = outreach.CheckContext(never_write=outreach.never_write(
        {"outreach_never_write": ["  game   changer ", "", "synergy"]}))
    assert ctx.never_write == ["game changer", "synergy"]
    found = outreach.check_text("Quick one", "This is a Game Changer for you. Open to it?",
                                "", ctx)
    assert any("game changer" in p and "never to write" in p for p in found)
    assert outreach.never_write({"outreach_never_write": [f"p{n}" for n in range(20)]}) == \
        [f"p{n}" for n in range(outreach.NEVER_WRITE_MAX)]


def test_m10_leaves_a_plain_item_as_it_is_and_cleans_hand_written_keys():
    plain = {"state": "sent", "edits": [{"at": "2026-10-01T09:00", "words": 3, "body": "x"}]}
    assert migrations.m10_learning(plain) is plain
    messy = {"state": "sent", "lessons_used": ["La", "La", ""],
             "edits": [{"at": "t", "tags": ["Cliche", "nope"], "body": "x"},
                       {"at": "u", "tags": [], "body": "y"}]}
    out = migrations.m10_learning(messy)
    assert out["lessons_used"] == ["La"]
    assert out["edits"][0]["tags"] == ["cliche"] and "tags" not in out["edits"][1]
    assert "lessons_used" not in migrations.m10_learning({"lessons_used": []})


def test_migration_10_is_registered_for_outreach_files():
    m = next(m for m in migrations.MIGRATIONS if m.version == 10)
    assert m.glob == "outreach/*.md" and m.apply is migrations.m10_learning
    assert migrations.LATEST >= 10
