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

"""Disqualifying a company and skipping outreach as one idea (core rules): a
company that is not open gets no batch draft, one named contact is drafted on
purpose with a warning, a stage move skips the open drafts, replies are always
allowed and the hard stops are never lifted. The demo folder's closed companies
were all written to before they closed, so a first touch to them is excluded for
that reason as well; the tests move prospects nobody has written to instead:
Kestrel Metrics (disqualified), Saltmarsh Labs (temp-disqualified), Tallpine
Software (won). All names are made up."""

from __future__ import annotations

from datetime import timedelta

import pytest

from hermitcrm import learning, migrations, outreach, send, suppress
from hermitcrm.store import split_file
from outreach_fakes import NOW, demo, git
from send_fakes import GOOD_PASSWORD, make_folder, ready_item
from test_send_email import OPT_OUT, deliver, set_opt_out

DRIFT = "kestrel-metrics/daan-visser"           # moved to disqualified by `closed`
GLASS = "saltmarsh-labs/niamh-walsh"            # moved to temp-disqualified
WON = "tallpine-software/{}"                    # moved to won (contact slug looked up)
MARA = "lindenhof-data/mara-keller"
STATES = ("researching", "drafted", "ready", "queued", "failed")


def close(store, slug, stage):
    """Move a prospect nobody has written to into a stage that is not open."""
    fields = {"stage": stage}
    if stage == "lost":
        fields["lost_reason"] = "no budget"
    if stage == "temp-disqualified":
        fields["requalify_on"] = "2027-02-01"
    store.update_company(slug, **fields)


@pytest.fixture
def folder(tmp_path):
    root, store = demo(tmp_path)
    global WON
    WON = "tallpine-software/" + next(iter(store.get("tallpine-software").contacts))
    close(store, "kestrel-metrics", "disqualified")
    close(store, "saltmarsh-labs", "temp-disqualified")
    close(store, "tallpine-software", "won")
    return root, store


def everyone(store, **kw):
    kw.setdefault("where", [])
    kw.setdefault("limit", 50)
    return outreach.select(store, **kw)


def picked(sel):
    return [c.record for c in sel.picked]


def left_out(sel):
    return {c.record: c.stage_blocked for c in sel.stage_left_out}


def excluded(sel):
    return {c.record: c.reason for c in sel.excluded}


def open_item(root, company, contact, state="drafted", **extra):
    item = outreach.Item(id=f"2026-10-15T0900-email-{company}-{contact}-{state}", state=state,
                         company=company, contact=contact, created=NOW, body="Hi.\n", **extra)
    outreach.write_item(root, item)
    return item


# ------------------------------------------------------------- 1-3: select


def test_a_batch_leaves_out_a_company_that_is_not_open_and_lists_it(folder):
    root, store = folder
    sel = everyone(store)
    assert {DRIFT: "disqualified", GLASS: "temp-disqualified", WON: "won"}.items() \
        <= left_out(sel).items()
    assert not {DRIFT, GLASS, WON} & (set(picked(sel)) | set(excluded(sel)))
    text = sel.render()
    assert "Left out because their company is not open" in text
    assert f"--include-closed {DRIFT}" in text and "disqualified" in text


def test_include_closed_brings_a_contact_in_on_purpose_with_a_warning(folder):
    root, store = folder
    sel = everyone(store, include_closed={DRIFT})
    cand = next(c for c in sel.picked if c.record == DRIFT)
    assert cand.stage_override == "disqualified"
    assert any("its company is disqualified" in w and "on purpose" in w
               for w in cand.warnings)
    assert DRIFT not in left_out(sel)
    assert GLASS in left_out(sel)      # only the confirmed one comes back


def test_one_named_contact_is_drafted_with_a_warning_and_no_prompt(folder):
    root, store = folder
    sel = outreach.select(store, contacts=[DRIFT])
    assert picked(sel) == [DRIFT] and not sel.stage_left_out
    assert sel.picked[0].stage_override == "disqualified"
    assert any("disqualified" in w for w in sel.picked[0].warnings)


def test_two_named_contacts_are_left_out_and_listed(folder):
    root, store = folder
    sel = outreach.select(store, contacts=[DRIFT, GLASS])
    assert picked(sel) == []
    assert left_out(sel) == {DRIFT: "disqualified", GLASS: "temp-disqualified"}
    both = outreach.select(store, contacts=[DRIFT, GLASS], include_closed=[DRIFT, GLASS])
    assert picked(both) == [DRIFT, GLASS] or set(picked(both)) == {DRIFT, GLASS}


def test_a_parked_company_behaves_like_a_closed_one(folder):
    root, store = folder
    assert left_out(everyone(store))[GLASS] == "temp-disqualified"
    assert picked(outreach.select(store, contacts=[GLASS])) == [GLASS]
    assert picked(everyone(store, include_closed=[GLASS])).count(GLASS) == 1


def test_a_won_company_is_left_out_the_same_way(folder):
    root, store = folder
    assert left_out(everyone(store))[WON] == "won"
    assert picked(outreach.select(store, contacts=[WON])) == [WON]


# ---------------------------------------------------- 4: hard stops stay


def test_do_not_contact_is_never_picked_even_named_or_included(folder):
    root, store = folder
    dnc = "ravenmoor-systems/ines-moreau"
    for sel in (outreach.select(store, contacts=[dnc]),
                everyone(store, include_closed=[dnc])):
        assert dnc not in picked(sel) and dnc not in left_out(sel)
        assert excluded(sel)[dnc] == "tagged do-not-contact"
    # a disqualified company that is also tagged: the tag wins, nothing to include
    store.update_company("kestrel-metrics", tags=["demo", "do-not-contact"])
    sel = outreach.select(store, contacts=[DRIFT])
    assert picked(sel) == [] and excluded(sel)[DRIFT] == "tagged do-not-contact"


def test_a_suppressed_address_is_never_picked_even_named_or_included(folder):
    root, store = folder
    address = store.get("kestrel-metrics").contacts["daan-visser"].email
    suppress.add(root, address, "opted-out", "2026-10-01")
    for sel in (outreach.select(store, contacts=[DRIFT]),
                everyone(store, include_closed=[DRIFT])):
        assert DRIFT not in picked(sel) and DRIFT not in left_out(sel)
        assert "suppression list" in excluded(sel)[DRIFT]


def test_a_playbook_tag_disqualifier_is_never_lifted_for_a_named_contact(folder):
    root, store = folder
    store.update_company("kestrel-metrics", tags=["demo", "customer"])
    for sel in (outreach.select(store, contacts=[DRIFT], approach="Scaling the sales team"),
                outreach.select(store, contacts=[DRIFT]),
                everyone(store, include_closed=[DRIFT])):
        assert DRIFT not in picked(sel) and DRIFT not in left_out(sel)
        assert "tagged customer" in excluded(sel)[DRIFT]


# ------------------------------------------------------- 5: reply, follow-up


def log_exchange(store, company, contact, *, outcome="interested", inbound=True):
    """You wrote two days ago; they answered yesterday (or did not, `inbound=False`)."""
    store.create_interaction(company, "email", "out", subject="Hello", contact=contact,
                             date=NOW - timedelta(days=9 if not inbound else 2),
                             body="Hi.\n")
    if inbound:
        store.create_interaction(company, "email", "in", subject="Re: Hello", contact=contact,
                                 date=NOW - timedelta(days=1), outcome=outcome,
                                 body="Interested, tell me more.\n")


def test_a_reply_to_interest_is_allowed_for_a_company_that_is_not_open(folder):
    root, store = folder
    for slug, contact in (("kestrel-metrics", "daan-visser"), GLASS.split("/"), WON.split("/")):
        log_exchange(store, slug, contact)
        sel = outreach.select(store, contacts=[f"{slug}/{contact}"] * 2, kind=outreach.REPLY)
        assert f"{slug}/{contact}" in picked(sel), excluded(sel)
        assert not sel.stage_left_out
        assert sel.picked[0].stage_override == ""      # no stage was lifted: none applies


def test_replies_lists_an_interested_reply_from_a_closed_company_only(folder):
    root, store = folder
    log_exchange(store, "kestrel-metrics", "daan-visser")                      # interested
    log_exchange(store, "saltmarsh-labs", "niamh-walsh", outcome="")           # unchecked
    found = {r.record for r in outreach.replies(store)}
    assert DRIFT in found and GLASS not in found


def test_a_first_touch_and_a_follow_up_stay_blocked(folder):
    root, store = folder
    # a first touch: only the stage is in the way, so the batch lists it
    assert DRIFT in left_out(everyone(store, kind=outreach.FIRST_TOUCH))
    # a follow-up: your message went unanswered. Due while the company is open ...
    store.update_company("kestrel-metrics", stage="prospect")
    log_exchange(store, "kestrel-metrics", "daan-visser", inbound=False)
    assert "kestrel-metrics" in {d.company.slug for d in outreach.due_followups(store, NOW.date())}
    # ... and not once it is closed, named or in a batch
    store.update_company("kestrel-metrics", stage="disqualified")
    assert "kestrel-metrics" not in {d.company.slug
                                     for d in outreach.due_followups(store, NOW.date())}
    for sel in (outreach.select(store, contacts=[DRIFT], kind=outreach.FOLLOW_UP),
                everyone(store, kind=outreach.FOLLOW_UP, include_closed=[DRIFT])):
        assert DRIFT not in picked(sel)
    assert DRIFT not in {f.company.slug + "/" + f.contact.slug
                         for f in outreach.due_followups(store, NOW.date())}


# ---------------------------------------------------- 6: the store cascade


@pytest.mark.parametrize("target", ["disqualified", "temp-disqualified", "won", "lost"])
def test_leaving_an_open_stage_skips_open_items_in_one_commit(folder, target):
    root, store = folder
    ids = []
    for n, state in enumerate(STATES):
        item = open_item(root, "lindenhof-data", f"person-{n}", state=state)
        if state == "queued":
            item.queued = item.send_at = NOW
            item.send_hash = "abc"
            outreach.write_item(root, item)
        ids.append(item.id)
    other = open_item(root, "kestrel-metrics", "daan-visser")
    sent = open_item(root, "lindenhof-data", "someone", state="sent")
    before = len(git(root, "log", "--format=%s").splitlines())
    fields = {"stage": target}
    if target == "lost":
        fields["lost_reason"] = "no budget"
    if target == "temp-disqualified":
        fields["requalify_on"] = "2027-02-01"
    store.update_company("lindenhof-data", **fields)
    for item_id in ids:
        item = outreach.get_item(root, item_id)
        assert item.state == "skipped" and item.skip_reason == "company-closed"
        assert item.queued is None and item.send_at is None
        assert item.skip_note == f"company moved to {target}"
    assert outreach.get_item(root, other.id).state == "drafted"      # another company
    assert outreach.get_item(root, sent.id).state == "sent"          # not open
    log = git(root, "log", "--format=%s").splitlines()
    assert len(log) == before + 1 and log[0] == f"company: lindenhof-data stage prospect -> {target}"
    dirty = git(root, "status", "--porcelain")
    assert not any(item_id in dirty for item_id in ids)       # all in the one commit
    assert any("5 open outreach drafts skipped" in n for n in store.take_notices())


def test_keep_drafts_leaves_the_items_alone(folder):
    root, store = folder
    item = open_item(root, "lindenhof-data", "mara-keller", state="ready")
    store.update_company("lindenhof-data", stage="disqualified", keep_drafts=True)
    assert outreach.get_item(root, item.id).state == "ready"
    assert store.take_notices() == []


def test_moving_back_revives_nothing_and_moves_between_closed_stages_do_nothing(folder):
    root, store = folder
    item = open_item(root, "lindenhof-data", "mara-keller")
    store.update_company("lindenhof-data", stage="disqualified")
    again = outreach.get_item(root, item.id)
    skipped_at = again.skipped
    store.update_company("lindenhof-data", stage="lost", lost_reason="no budget")
    assert outreach.get_item(root, item.id).skipped == skipped_at
    store.update_company("lindenhof-data", stage="prospect")
    assert outreach.get_item(root, item.id).state == "skipped"
    # a move that is not leaving an open stage never skips: a new draft is safe
    fresh = open_item(root, "lindenhof-data", "mara-keller", state="ready")
    store.update_company("lindenhof-data", stage="engaged")
    assert outreach.get_item(root, fresh.id).state == "ready"


def test_requalifying_a_parked_company_skips_nothing(folder):
    root, store = folder
    item = open_item(root, "saltmarsh-labs", "niamh-walsh", state="ready")   # kept
    store.requalify_due(NOW.date() + timedelta(days=3650))
    assert store.get("saltmarsh-labs").stage == "prospect"
    assert outreach.get_item(root, item.id).state == "ready"


# --------------------------------------- 7-8: no cooldown, no signal


def test_a_company_closed_skip_sets_no_cooldown_and_is_not_bad_fit(folder):
    root, store = folder
    open_item(root, "lindenhof-data", "mara-keller", state="ready")
    store.update_company("lindenhof-data", stage="temp-disqualified",
                         requalify_on="2026-10-20")
    store.update_company("lindenhof-data", stage="prospect")      # requalified
    sel = outreach.select(store, where=["stage=prospect"], limit=50)
    assert MARA in picked(sel)
    assert MARA not in excluded(sel)


def test_a_bad_fit_skip_still_keeps_the_company_out_and_a_manual_skip_has_a_cooldown(folder):
    root, store = folder
    item = open_item(root, "lindenhof-data", "mara-keller", state="ready")
    outreach.skip(store, item.id, "bad-fit")
    assert "skipped as bad-fit" in excluded(everyone(store, where=["stage=prospect"]))[MARA]
    item2 = open_item(root, "saltmarsh-labs-ai", "sean-brady", state="ready")
    outreach.skip(store, item2.id, "bad-timing")
    assert "skipped 0 days ago (bad-timing)" in excluded(
        everyone(store, where=["stage=prospect"]))["saltmarsh-labs-ai/sean-brady"]


def test_company_closed_is_not_a_choice_in_the_skip_form_but_skip_accepts_it(folder):
    root, store = folder
    assert outreach.COMPANY_CLOSED not in outreach.MANUAL_SKIP_REASONS
    assert outreach.COMPANY_CLOSED in outreach.SKIP_REASONS
    assert set(outreach.MANUAL_SKIP_REASONS) < set(outreach.SKIP_REASONS)


def test_the_quality_and_learning_reports_ignore_company_closed(folder):
    root, store = folder
    item = open_item(root, "lindenhof-data", "mara-keller", state="drafted")
    store.update_company("lindenhof-data", stage="disqualified")
    skipped = outreach.get_item(root, item.id)
    assert skipped.skip_reason == "company-closed"
    assert not learning.reviewed(skipped)
    assert [s for s in learning.signals(store) if s.item_id == item.id] == []
    # a person's own skip is still a review
    other = open_item(root, "kestrel-metrics", "daan-visser", state="drafted")
    outreach.skip(store, other.id, "bad-timing")
    assert [s.item_id for s in learning.signals(store)] == [other.id]


# --------------------------------------------------- 9: the send step


@pytest.fixture
def sending(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMITCRM_SEND_PASSWORD", GOOD_PASSWORD)
    root, store, settings = make_folder(tmp_path)
    set_opt_out(root, OPT_OUT)
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "setup")
    return root, store, settings


def test_an_ordinary_item_is_still_refused_when_its_company_is_closed_after_drafting(sending):
    root, store, settings = sending
    item = ready_item(root, store)
    store.update_company("lindenhof-data", stage="won", keep_drafts=True)
    out, smtp, _ = deliver(store, settings, item.id)
    assert out.kind == "held" and "company is won" in out.detail and not smtp.sent


def test_an_item_drafted_on_purpose_is_not_refused_on_the_stage(sending):
    root, store, settings = sending
    item = ready_item(root, store, stage_override="won")
    store.update_company("lindenhof-data", stage="won", keep_drafts=True)
    out, smtp, _ = deliver(store, settings, item.id)
    assert out.kind == "sent" and len(smtp.sent) == 1


@pytest.mark.parametrize("case", ["suppressed", "dnc", "disqualified"])
def test_the_override_lifts_the_stage_check_only(sending, case):
    root, store, settings = sending
    item = ready_item(root, store, stage_override="won",
                      **({"approach": "Founder coaching"} if case == "disqualified" else {}))
    store.update_company("lindenhof-data", stage="won", keep_drafts=True)
    if case == "suppressed":
        suppress.add(root, "mara@lindenhof-data.example.com", "opted-out", "2026-10-01")
    elif case == "dnc":
        store.update_company("lindenhof-data", tags=["demo", "do-not-contact"])
    else:
        store.update_company("lindenhof-data", tags=["demo", "customer"])
    out, smtp, _ = deliver(store, settings, item.id)
    assert out.kind == "held" and not smtp.sent
    assert "company is" not in out.detail


def test_a_reply_to_interest_is_not_refused_on_the_stage(sending):
    root, store, settings = sending
    item = ready_item(root, store, kind=outreach.REPLY)
    store.update_company("lindenhof-data", stage="won", keep_drafts=True)
    out, smtp, _ = deliver(store, settings, item.id)
    assert out.kind == "sent", out.detail


# ------------------------------------------------- 12: the key and migration


def test_stage_override_is_written_only_when_set_and_round_trips(folder):
    root, store = folder
    plain = outreach.Item(id="a", state="drafted", company="c", contact="p", body="Hi.\n")
    assert "stage_override" not in plain.to_frontmatter()
    marked = outreach.Item(id="b", state="drafted", company="c", contact="p", body="Hi.\n",
                           stage_override="disqualified")
    meta = marked.to_frontmatter()
    assert list(meta) == [k for k in outreach.ITEM_KEYS
                          if k in meta or k not in ("stage_override", "framework",
                                                    "lead_rule", "lessons_used", "exemplars_used",
                                                    "language_pick", "notes_linked",
                                                    "attachments")]
    again = outreach.item_from_text("b", outreach.item_text(marked))
    assert again.stage_override == "disqualified"
    assert outreach.item_text(again) == outreach.item_text(marked)      # deterministic


def test_migration_22_reserves_the_key_and_changes_nothing():
    migration = next(m for m in migrations.MIGRATIONS if m.version == 22)
    meta = {"state": "drafted", "kind": "first-touch", "stage_override": "disqualified"}
    assert migration.apply(dict(meta)) == meta
    assert migration.apply(migration.apply(dict(meta))) == meta
    assert migration.apply({"state": "drafted"}) == {"state": "drafted"}
    assert migration.glob == "outreach/*.md"
    assert migrations.LATEST >= 22


def test_the_migration_leaves_an_item_file_byte_for_byte(folder, tmp_path):
    root, store = folder
    item = open_item(root, "lindenhof-data", "mara-keller", state="drafted",
                     stage_override="disqualified")
    path = root / item.path
    before = path.read_bytes()
    meta, body = split_file(path.read_text(encoding="utf-8"))
    migration = next(m for m in migrations.MIGRATIONS if m.version == 22)
    assert migration.apply(dict(meta)) == meta
    assert path.read_bytes() == before and body == "Hi.\n"


# ------------------------------------------------- the other callers: bulk, CLI


def _bulk_apply(store, keep=False):
    from hermitcrm import bulk
    plan = bulk.plan(store, "companies", ["name=Lindenhof Data"],
                     bulk.Ops(stage="disqualified", keep_drafts=keep))
    return plan, bulk.apply(store, plan)


def test_a_bulk_stage_move_shows_the_skip_in_its_dry_run_and_does_it_in_one_commit(folder):
    from hermitcrm import bulk
    root, store = folder
    item = open_item(root, "lindenhof-data", "mara-keller", state="ready")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "item")
    plan = bulk.plan(store, "companies", ["name=Lindenhof Data"], bulk.Ops(stage="disqualified"))
    assert any("1 open outreach draft skipped" in w for w in plan.warnings)
    assert "1 open outreach draft skipped" in plan.render()
    assert outreach.get_item(root, item.id).state == "ready"              # a dry run writes nothing
    before = len(git(root, "log", "--format=%s").splitlines())
    bulk.apply(store, plan)
    assert outreach.get_item(root, item.id).skip_reason == "company-closed"
    assert len(git(root, "log", "--format=%s").splitlines()) == before + 1
    assert item.path in git(root, "show", "--name-only", "--format=", "HEAD")


def test_a_bulk_stage_move_with_keep_drafts_leaves_them(folder):
    root, store = folder
    item = open_item(root, "lindenhof-data", "mara-keller", state="ready")
    plan, _ = _bulk_apply(store, keep=True)
    assert not plan.warnings
    assert outreach.get_item(root, item.id).state == "ready"


def test_the_set_command_takes_keep_drafts():
    from hermitcrm import cli
    parser_args = cli._build_parser().parse_args(
        ["set", "companies", "--where", "stage=prospect", "--stage", "lost", "--keep-drafts"])
    assert parser_args.keep_drafts is True


def test_the_cli_preview_names_the_flag_that_brings_a_closed_company_back(folder):
    from hermitcrm.cli import cmd_outreach
    root, store = folder

    class Args:
        action, where, contact, channel, kind, limit, approach = (
            "preview", ["stage=disqualified"], [], "email", "first-touch", 3, "")
        include_closed = []

    text, code = cmd_outreach(store, root, {}, Args, researcher=None, drafter=None)
    assert code == 0 and "Would build nothing now." in text
    assert f"--include-closed {DRIFT}" in text
    Args.include_closed = [DRIFT]
    text, _ = cmd_outreach(store, root, {}, Args, researcher=None, drafter=None)
    assert "Would build 1:" in text and "on purpose" not in text.split("Would build 1:")[0]


def test_the_cli_skip_can_also_disqualify(folder):
    from hermitcrm.cli import cmd_outreach
    root, store = folder
    one = open_item(root, "lindenhof-data", "mara-keller", state="drafted")
    two = open_item(root, "lindenhof-data", "someone-else", state="ready")

    class Wrong:
        action, id, reason, note, disqualify = "skip", one.id, "bad-timing", "", True

    text, code = cmd_outreach(store, root, {}, Wrong)
    assert code == 2 and "--reason bad-fit" in text
    assert store.get("lindenhof-data").stage == "prospect"

    class Right:
        action, id, reason, note, disqualify = "skip", one.id, "bad-fit", "sells b2c", True

    text, code = cmd_outreach(store, root, {}, Right)
    assert code == 0 and "moved to disqualified" in text and "1 open outreach draft skipped" in text
    assert store.get("lindenhof-data").stage == "disqualified"
    assert outreach.get_item(root, two.id).skip_reason == "company-closed"


# ------------------------------------------------------------- --override (CLI)

KESTREL = "kestrel-metrics/daan-visser"   # ae count 0: misses "Scaling the sales team" (1-8)


def override_args(**kw):
    from types import SimpleNamespace
    base = dict(action="preview", where=[], contact=[KESTREL], channel="email",
                kind="first-touch", limit=3, approach="Scaling the sales team",
                include_closed=[], override=False)
    return SimpleNamespace(**{**base, **kw})


def test_the_cli_preview_names_the_override_for_an_overridable_refusal(folder):
    from hermitcrm.cli import cmd_outreach
    root, store = folder
    text, code = cmd_outreach(store, root, {}, override_args(), researcher=None, drafter=None)
    assert code == 0 and "Would build nothing now." in text
    assert "ae count 0, wants 1-8 | --override lifts it" in text


def test_the_cli_override_previews_the_draft_with_its_warning(folder):
    from hermitcrm.cli import cmd_outreach
    root, store = folder
    text, code = cmd_outreach(store, root, {}, override_args(override=True),
                              researcher=None, drafter=None)
    assert code == 0 and "Would build 1:" in text
    # this fixture's Kestrel is also in a closed stage: both lifts show, stage first
    assert "outside Scaling the sales team's ideal customer (ae count 0, wants 1-8)" in text


@pytest.mark.parametrize("contact", [[], [KESTREL, "lindenhof-data/mara-keller"]])
@pytest.mark.parametrize("action", ["preview", "build"])
def test_the_cli_override_needs_exactly_one_contact(folder, action, contact):
    from hermitcrm.cli import cmd_outreach
    root, store = folder
    head = git(root, "rev-parse", "HEAD")
    text, code = cmd_outreach(store, root, {}, override_args(action=action, contact=contact,
                                                             where=["stage=prospect"],
                                                             override=True))
    assert code == 2 and "--override needs exactly one --contact" in text
    assert git(root, "rev-parse", "HEAD") == head and not (root / "outreach").exists()


def test_the_cli_override_flag_is_parsed(folder):
    from hermitcrm import cli
    parsed = cli._build_parser().parse_args(
        ["outreach", "build", "--contact", KESTREL, "--override"])
    assert parsed.override is True
    parsed = cli._build_parser().parse_args(["outreach", "build", "--contact", KESTREL])
    assert parsed.override is False
