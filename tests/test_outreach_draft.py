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

"""Outreach, part 03: the first-touch draft, clean_answer's hard checks (one
retry), the outreach/ files and their commits, the manual sender, the CLI."""

from __future__ import annotations

import socket

import pytest

from hermitcrm import cli, outreach, scrape
from hermitcrm.enrich import EnrichError
from hermitcrm.store import Store, split_file
from outreach_fakes import NOW, FakeAI, ai, default_draft, demo, fake_page, git

GOOD = ("Hi Mara,\n\nThe second office this autumn caught my eye.\nWe help founders build "
        "a sales team that sells without them.\nWhere does it hurt most right now: "
        "pipeline, conversion or deal size?\n\nSam")
FINDINGS = [outreach.Finding("Opened a second office", "https://a.example.com", "trigger",
                             "high"),
            outreach.Finding("Maybe hiring", "https://a.example.com", "trigger", "low")]
PROOF = ["Took a five-person team from 2 to 9 deals a quarter."]


def ctx(**kw):
    channel = kw.pop("channel", "email")
    base = dict(kind="first-touch", channel=channel, rules=outreach.channel_rules(channel),
                findings=FINDINGS, proof=PROOF,
                offer_lines=["We build your first sales team."])
    base.update(kw)
    return outreach.CheckContext(**base)


def answer(body=GOOD, subject="Your second office", angle="hook", findings_used=(1,),
           proof_used=(), pitch=""):
    return {"subject": subject, "body": body, "pitch": pitch, "angle": angle,
            "findings_used": list(findings_used), "proof_used": list(proof_used)}


def problems(data, **kw):
    return outreach.clean_answer(data, ctx(**kw)).problems


# ---------------------------------------------------------------- clean_answer


def test_a_good_draft_passes():
    draft = outreach.clean_answer(answer(proof_used=PROOF), ctx())
    assert draft.problems == [] and draft.angle == "hook"
    assert draft.findings_used == [1] and draft.proof_used == PROOF
    assert draft.body.endswith("Sam\n")


@pytest.mark.parametrize("body,count", [
    (GOOD.replace("deal size?", "deal size."), 0),
    (GOOD.replace("right now:", "right now? Or:"), 2),
])
def test_exactly_one_question(body, count):
    found = problems(answer(body))
    assert f"the message asks {count} questions; it must ask exactly one" in found


def test_a_question_inside_quotes_does_not_count():
    body = GOOD.replace("The second office", 'Your line "who sells when you don\'t?" and '
                        "the second office")
    assert problems(answer(body)) == []
    french = GOOD.replace("deal size?", "deal size ?")
    assert problems(answer(french)) == []


@pytest.mark.parametrize("opening", ["I saw your second office.", "Ich habe gesehen, dass.",
                                     "Ik zag jullie kantoor.", "Je vois que.",
                                     "I'm writing because."])
def test_an_opening_i_is_refused(opening):
    body = GOOD.replace("The second office this autumn caught my eye.", opening)
    assert any(p.startswith("it opens with") for p in problems(answer(body)))
    # "In" or "Ideas" are not "I"
    body = GOOD.replace("The second office this autumn caught my eye.",
                        "In autumn you opened a second office.")
    assert problems(answer(body)) == []


def test_a_reply_to_interest_needs_the_offer_line():
    found = problems(answer(), kind="reply-to-interest")
    assert "a reply to interest must say the offer line from the playbook" in found
    body = GOOD.replace("We help founders build a sales team that sells without them.",
                        "We build  your first\nsales team.")
    assert "a reply to interest must say the offer line from the playbook" not in problems(
        answer(body), kind="reply-to-interest")


@pytest.mark.parametrize("link", ["https://calendly.com/sam/30min",
                                  "https://meetings.hubspot.com/sam",
                                  "https://outlook.office.com/bookwithme/user/abc"])
def test_a_calendar_link_is_refused(link):
    body = GOOD.replace("\n\nSam", f"\nBook here: {link}\n\nSam")
    assert any("calendar link" in p for p in problems(answer(body)))


def test_any_link_in_a_first_touch_is_refused():
    body = GOOD.replace("\n\nSam", "\nSee https://www.example.com/case\n\nSam")
    assert any(p.startswith("it contains a link") for p in problems(answer(body)))


@pytest.mark.parametrize("slot", ["Free on Tuesday at 3pm.", "Dienstag um 14 Uhr passt.",
                                  "Mardi à 14h30 ?", "How about 10:30 on the 21st.",
                                  "Could we speak this week at your convenience.",
                                  "Dinsdag om 14:00."])
def test_a_proposed_time_slot_is_refused(slot):
    body = GOOD.replace("\n\nSam", f"\n{slot}\n\nSam")
    assert any(p.startswith("it proposes a time") for p in problems(answer(body)))


def test_length_rules_per_channel():
    long_subject = "x" * 61
    assert "the subject is 61 characters; at most 60" in problems(answer(subject=long_subject))
    long_body = GOOD.replace("Sam", "word " * 120 + "Sam")
    assert any(p.startswith("the email is") for p in problems(answer(long_body)))
    note = "Hi Mara, the second office caught my eye. Where does it hurt most?" + " x" * 150
    pitch = "Hi Mara, thanks for connecting. We build sales teams. Where does it hurt?"
    found = problems(answer(note, subject="", pitch=pitch), channel="linkedin")
    assert any(p.startswith("the connection note is") for p in found)
    found = problems(answer("Hi Mara, the office caught my eye. Where does it hurt?",
                            pitch=pitch * 10), channel="linkedin")
    assert any(p.startswith("the pitch message is") for p in found)


def test_unknown_findings_or_proof_are_refused():
    found = problems(answer(findings_used=(1, 2, 7), proof_used=["Doubled revenue."]))
    assert "it cites finding 2, which is not a usable finding given" in found  # low
    assert "it cites finding 7, which is not a usable finding given" in found
    assert any(p.startswith("it cites proof that is not in the playbook") for p in found)


def test_a_leftover_gap_is_refused_only_when_research_could_fill_it():
    body = GOOD.replace("The second office this autumn caught my eye.",
                        "[One thing you noticed.]")
    assert any(p.startswith("it leaves a gap to fill") for p in problems(answer(body)))
    assert problems(answer(body, findings_used=()), findings=[]) == []


def test_the_opt_out_line_is_added_for_cold_email_and_not_counted():
    line = outreach.culture("en")["opt_out"]
    draft = outreach.clean_answer(answer(), ctx(opt_out=line))
    assert draft.body.rstrip("\n").endswith(line) and draft.problems == []


def test_not_a_draft_at_all_is_rejected():
    for data in (None, "text", answer(body=""), answer(body="```\ncode\n```")):
        with pytest.raises(outreach.Rejected):
            outreach.clean_answer(data, ctx())


# ------------------------------------------------------------ retry and drafter


@pytest.fixture
def folder(tmp_path):
    return demo(tmp_path)


def drafter_for(store, *drafts):
    fake = FakeAI(drafts=list(drafts))
    return outreach.AIDrafter(store, ai(fake), {"owner_name": "Sam Example"}), fake


def draft_once(store, drafter):
    company = store.get("lindenhof-data")
    research = outreach.Research(findings=list(FINDINGS))
    approach = outreach.playbook.load(store.root).approach("Scaling the sales team")
    return drafter.draft("first-touch", company, company.contacts["mara-keller"], research,
                         "email", approach=approach)


def test_one_retry_fixes_a_broken_draft(folder):
    root, store = folder
    bad = answer(GOOD.replace("The second office", "I saw the second office"))
    drafter, fake = drafter_for(store, bad, answer())
    draft = draft_once(store, drafter)
    assert draft.problems == [] and draft.attempts == 2
    prompts = [c["prompt"] for c in fake.of("draft")]
    assert "Your previous draft broke these rules" not in prompts[0]
    assert "Your previous draft broke these rules" in prompts[1]
    assert "it opens with \"I\"" in prompts[1]
    assert all(c["tools"] == "" for c in fake.calls)
    # German contact: the culture norms and the language are in the prompt
    assert "Language: German" in prompts[0] and "du" in prompts[0]
    assert "Sign as: Sam." in prompts[0]


def test_after_one_retry_the_draft_is_shown_with_the_problem_marked(folder):
    root, store = folder
    bad = answer(GOOD.replace("deal size?", "deal size."))
    drafter, fake = drafter_for(store, bad, bad, answer())
    draft = draft_once(store, drafter)
    assert len(fake.of("draft")) == 2 and draft.attempts == 2
    assert draft.problems == ["the message asks 0 questions; it must ask exactly one"]
    assert draft.body.startswith("Hi Mara,")


def test_no_usable_answer_twice_fails(folder):
    root, store = folder
    drafter, fake = drafter_for(store, EnrichError("the CLI timed out"), "not json")
    draft = draft_once(store, drafter)
    assert draft.failed == "the AI returned no JSON object" and draft.attempts == 2


# --------------------------------------------------------------- files, commits


def built(folder, limit=3, drafts=None, research=None):
    root, store = folder
    fake = FakeAI(research=research, drafts=drafts)
    researcher = outreach.ScrapeResearcher(ai(fake), fetcher=fake_page, today=NOW.date())
    drafter = outreach.AIDrafter(store, ai(fake), {"owner_name": "Sam Example"})
    sel = outreach.select(store, where=["stage=prospect"], limit=limit)
    return outreach.build(store, sel, researcher, drafter, now=NOW), fake


def commits(root) -> list[str]:
    return git(root, "log", "--format=%s").splitlines()


def test_build_writes_checked_items_one_commit_per_step(folder):
    root, store = folder
    before = len(commits(root))
    result, fake = built(folder)
    assert [i.state for i in result.items] == ["drafted"] * 3
    assert all(i.checks == [] for i in result.items)
    log = commits(root)[:len(commits(root)) - before]
    assert len(log) == 6
    assert log[-1] == ("outreach: research lindenhof-data/mara-keller (scrape, 2 findings)")
    assert log[-2] == "outreach: draft lindenhof-data/mara-keller (email, hook): checks passed"
    for sha in git(root, "log", f"-{6}", "--format=%h").split():
        files = git(root, "show", "--name-only", "--format=", sha).split()
        assert [f for f in files if f.startswith("outreach/")] and \
            all(f.startswith("outreach/") or f == "PIPELINE.md" for f in files)
    item = result.items[0]
    assert item.id == "2026-10-16T0900-email-lindenhof-data-mara-keller"
    assert item.approach == "Scaling the sales team" and item.language == "de"
    assert [f.used for f in item.findings] == [False, True]  # the CRM's line, the trigger
    assert item.body.rstrip("\n").endswith(outreach.culture("de")["opt_out"])
    assert item.ai_body == item.body and item.model and item.seconds is not None
    assert item.norms and item.norms[0].startswith("formality: informal: du")


def test_item_files_are_deterministic_and_keep_the_body_byte_for_byte(folder):
    root, store = folder
    result, _ = built(folder, limit=1)
    item = result.items[0]
    path = root / item.path
    text = path.read_bytes()
    again = outreach.get_item(root, item.id)
    assert outreach.item_text(again).encode() == text            # read, write: same bytes
    meta, body = split_file(text.decode())
    assert list(meta) == list(outreach.ITEM_KEYS)
    # a hand edit with odd whitespace survives a step byte for byte
    odd = "Hi Mara,  \n\n\tThe second office caught my eye.\nWhere does it hurt most?\n\n\nSam\n"
    meta["checks"] = []
    path.write_text(text.decode().split("\n---\n", 1)[0] + "\n---\n" + odd, encoding="utf-8")
    item, found = outreach.mark_ready(store, item.id, anyway=True)
    assert split_file(path.read_text())[1] == odd
    assert outreach.get_item(root, item.id).body == odd


def test_ready_rechecks_the_text_and_records_the_edit(folder):
    root, store = folder
    result, _ = built(folder, limit=1)
    item = result.items[0]
    path = root / item.path
    head, body = path.read_text().split("\n---\n", 1)
    path.write_text(head + "\n---\n" + body.replace("deal size?", "deal size."),
                    encoding="utf-8")
    with pytest.raises(outreach.OutreachError, match="asks 0 questions"):
        outreach.mark_ready(store, item.id)
    path.write_text(head + "\n---\n" + body.replace("caught my eye", "stood out"),
                    encoding="utf-8")
    before = len(commits(root))
    ready, found = outreach.mark_ready(store, item.id)
    assert found == [] and ready.state == "ready" and ready.edit_distance == 3
    assert len(commits(root)) == before + 1
    assert commits(root)[0] == "outreach: ready lindenhof-data/mara-keller (email)"
    files = git(root, "show", "--name-only", "--format=", "HEAD").split()
    assert item.path in files and any("/interactions/" in f for f in files)
    fresh = Store(root)
    fresh.load()
    note = next(i for i in fresh.get("lindenhof-data").interactions if i.is_note)
    assert note.contact == "mara-keller"
    assert "- Opened a second office this autumn (https://lindenhof-data.example.com)" \
        in note.body
    assert fresh.get("lindenhof-data").stage == "prospect"  # a note is not a touch
    with pytest.raises(outreach.OutreachError, match="only a drafted item"):
        outreach.mark_ready(store, item.id)


def test_skip_is_one_commit_and_frees_the_contact(folder):
    root, store = folder
    result, _ = built(folder, limit=1)
    item = result.items[0]
    before = len(commits(root))
    with pytest.raises(outreach.OutreachError, match="say why"):
        outreach.skip(store, item.id, "  ")
    skipped = outreach.skip(store, item.id, "They just hired a sales lead")
    assert skipped.state == "skipped" and skipped.skip_reason == "They just hired a sales lead"
    assert len(commits(root)) == before + 1
    sel = outreach.select(store, where=["stage=prospect"], limit=1)
    assert [c.record for c in sel.picked] == ["lindenhof-data/mara-keller"]


def test_a_draft_that_fails_twice_is_skipped_by_the_bot(folder):
    root, store = folder
    result, _ = built(folder, limit=1, drafts=["no", "no"])
    item = result.items[0]
    assert item.state == "skipped"
    assert item.skip_reason == "no usable draft from the AI: the AI returned no JSON object"
    assert commits(root)[0] == "outreach: skip lindenhof-data/mara-keller (no usable draft)"


def test_nothing_usable_found_falls_back_with_gaps_allowed(folder):
    root, store = folder

    def gappy(prompt):
        data = default_draft(prompt)
        data["body"] = data["body"].replace("Teams at your stage often hit the same wall.",
                                            "[One thing you noticed about the team.]")
        return data

    store.update_company("lindenhof-data", product_oneliner="")
    result, _ = built(folder, limit=1, research={"findings": []}, drafts=[gappy])
    item = result.items[0]
    assert item.checks == [] and "[One thing you noticed" in item.body
    assert any(f.startswith("nothing usable found") for f in item.flags)


def test_manual_sender_never_touches_the_network(folder, monkeypatch):
    root, store = folder

    def no_network(*a, **kw):
        raise AssertionError("the network was touched")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    result = outreach.ManualSender().send(outreach.Item())
    assert result.sent is False and result.detail.startswith("not sent")
    assert outreach.ManualLogger().log(outreach.Item(), result) is None


# ---------------------------------------------------------------------- CLI


@pytest.fixture
def fake_cli(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(outreach, "default_enricher", lambda config: ai(fake))
    monkeypatch.setattr(scrape, "fetch", lambda url, timeout=10: fake_page(url))
    return fake


def test_done_when_build_writes_three_checked_items(tmp_path, fake_cli, capsys):
    from hermitcrm.datafolder import init_folder

    root = init_folder(tmp_path / "x", demo=True)
    code = cli.main(["outreach", "build", "--where", "stage=prospect", "--channel", "email",
                     "--limit", "3"], root=root)
    out = capsys.readouterr().out
    assert code == 0, out
    found = outreach.items(root)
    assert len(found) == 3 and all(i.state == "drafted" and i.checks == [] for i in found)
    assert out.count("drafted: ") == 3 and "Nothing was sent." in out
    assert {i.record for i in found} == {"lindenhof-data/mara-keller",
                                         "kestrel-metrics/daan-visser",
                                         "saltmarsh-labs/ciaran-doyle"}
    assert git(root, "status", "--porcelain") == ""
    # list, show, ready, skip
    assert cli.main(["outreach", "list"], root=root) == 0
    listing = capsys.readouterr().out
    assert listing.count(" | drafted | ") == 3
    first = sorted(i.id for i in found)[0]
    assert cli.main(["outreach", "show", first], root=root) == 0
    card = capsys.readouterr().out
    assert "Findings:" in card and "Checks: passed" in card and "Subject:" in card
    assert cli.main(["outreach", "ready", first], root=root) == 0
    assert "Not sent." in capsys.readouterr().out
    second = sorted(i.id for i in found)[1]
    assert cli.main(["outreach", "skip", second, "--reason", "wrong person"], root=root) == 0
    assert cli.main(["outreach", "list", "--state", "ready"], root=root) == 0
    assert capsys.readouterr().out.count(" | ready | ") == 1


def test_build_refuses_when_the_playbook_is_not_ready(tmp_path, fake_cli, capsys):
    from hermitcrm.datafolder import init_folder

    root = init_folder(tmp_path / "x", demo=True)
    (root / "MESSAGING.md").write_text("# Just notes\n", encoding="utf-8")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam", "x")
    head = git(root, "rev-parse", "HEAD")
    code = cli.main(["outreach", "build", "--where", "stage=prospect"], root=root)
    assert code == 1
    assert "needs a filled playbook first" in capsys.readouterr().err
    assert fake_cli.calls == [] and not (root / "outreach").exists()
    assert git(root, "rev-parse", "HEAD") == head


def test_build_refuses_a_level_or_kind_not_built_yet(tmp_path, fake_cli, capsys):
    from hermitcrm.datafolder import init_folder

    root = init_folder(tmp_path / "x", demo=True)
    assert cli.main(["outreach", "build", "--where", "stage=prospect", "--research",
                     "ai-web"], root=root) == 1
    assert "ai-web research comes in a later version" in capsys.readouterr().err
    assert cli.main(["outreach", "build", "--where", "stage=prospect", "--kind",
                     "follow-up"], root=root) == 1
    assert "later version" in capsys.readouterr().err
    assert fake_cli.calls == []


def test_no_owner_name_means_no_name_is_made_up(folder):
    root, store = folder
    fake = FakeAI()
    drafter = outreach.AIDrafter(store, ai(fake), {"owner_name": ""})
    draft_once(store, drafter)
    assert "Sign with the sign-off only: no name" in fake.of("draft")[0]["prompt"]
