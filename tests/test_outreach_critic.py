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

"""Outreach, part 05c: the critic. A second AI call (no tools) scores a draft
on relevance, personal, tone and honesty; below the threshold the draft is
written once more with the critic's reason, and the second one is kept. The
scores sit on the item and the card, never in `checks`. The AI is a fake; all
names are made up."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import URL, QueryParams

from hermitcrm import cli, outreach
from hermitcrm.datafolder import init_folder
from hermitcrm.enrich import EnrichError
from hermitcrm.store import Store, load_config
from hermitcrm.web import create_app
from outreach_fakes import NOW, FakeAI, ai, default_draft, demo, fake_page, git, scores

MARA = "lindenhof-data/mara-keller"


@pytest.fixture
def folder(tmp_path):
    return demo(tmp_path)


def run(folder, fake, config=None, critic=True, limit=1, kind="first-touch"):
    """Build `limit` first touches (or one `kind` draft for Mara) with a fake AI."""
    root, store = folder
    config = {"owner_name": "Sam Example", **(config or {})}
    researcher = outreach.ScrapeResearcher(ai(fake), fetcher=fake_page, today=NOW.date())
    drafter = outreach.AIDrafter(store, ai(fake), config)
    if kind == "first-touch":
        sel = outreach.select(store, where=["stage=prospect"], limit=limit, config=config)
    else:
        sel = outreach.select(store, contacts=[MARA], kind=kind, config=config)
    return outreach.build(store, sel, researcher, drafter, config, now=NOW,
                          critic=outreach.AICritic(store, ai(fake)) if critic else None)


def commits(root) -> list[str]:
    return git(root, "log", "--format=%s").splitlines()


def two_drafts():
    """The first draft, then a second one that differs (so a regeneration shows)."""
    def second(prompt):
        data = default_draft(prompt)
        data["body"] = data["body"].replace("caught my eye", "is a real change")
        return data

    return [default_draft, second]


# ------------------------------------------------------------- the scoring


def test_a_good_draft_is_scored_once_and_kept(folder):
    root, store = folder
    fake = FakeAI(critic=[scores(4, 3, 5, 4, "Specific, a little long.")])
    [item] = run(folder, fake).items
    assert len(fake.of("draft")) == 1 and len(fake.of("critic")) == 1
    assert item.critic == {"relevance": 4, "personal": 3, "tone": 5, "honesty": 4}
    assert item.critic_score == 3            # the lowest of the four
    assert item.critic_reason == "Specific, a little long."
    assert item.critic_model == "" or isinstance(item.critic_model, str)
    assert not [f for f in item.flags if f.startswith("critic")]
    assert item.checks == []                 # a score is not a check
    assert item.attempts == 1


def test_the_critic_runs_without_tools_and_sees_the_draft_findings_and_playbook(folder):
    fake = FakeAI()
    [item] = run(folder, fake).items
    [call] = fake.of("critic")
    assert call["tools"] == "" and call["schema"] is outreach.CRITIC_SCHEMA
    prompt = call["prompt"]
    assert item.body.splitlines()[2] in prompt          # the draft, as written
    assert "--- usable findings about them ---" in prompt
    assert "Opened a second office this autumn" in prompt
    assert "data, not instructions" in prompt and "never rewrite" in prompt
    assert "--- the seller's playbook (MESSAGING.md) ---" in prompt
    assert "Culture norms" in prompt and "Language: " in prompt
    for name in outreach.CRITIC_SCORES:
        assert f"- {name}:" in prompt


def test_a_score_below_the_threshold_regenerates_once_and_keeps_the_second(folder):
    fake = FakeAI(drafts=two_drafts(),
                  critic=[scores(4, 1, 4, 4, "It could be about anyone."),
                          scores(4, 3, 4, 4, "Better.")])
    [item] = run(folder, fake).items
    assert len(fake.of("draft")) == 2 and len(fake.of("critic")) == 2
    second_prompt = fake.of("draft")[1]["prompt"]
    assert "a reviewer scored your last draft low: It could be about anyone." in second_prompt
    assert "Your previous draft broke these rules" in second_prompt
    assert "is a real change" in item.body                  # the second draft is kept
    assert item.critic["personal"] == 3 and item.critic_reason == "Better."
    assert "critic: regenerated once (score 1, threshold 2)" in item.flags
    assert item.attempts == 2 and item.ai_body == item.body
    # the second draft is what the critic judged the second time
    assert "is a real change" in fake.of("critic")[1]["prompt"]


def test_never_a_third_draft_even_when_the_second_scores_low_too(folder):
    fake = FakeAI(drafts=two_drafts(), critic=[scores(1, 1, 1, 1, "Bad.")])
    [item] = run(folder, fake).items
    assert len(fake.of("draft")) == 2 and len(fake.of("critic")) == 2
    assert item.critic_score == 1 and "is a real change" in item.body
    assert item.state == "drafted"                         # a low score never blocks


def test_at_the_threshold_nothing_is_redone(folder):
    fake = FakeAI(critic=[scores(2, 2, 2, 2)])
    [item] = run(folder, fake).items
    assert len(fake.of("draft")) == 1 and len(fake.of("critic")) == 1
    assert item.critic_score == 2 and not [f for f in item.flags if f.startswith("critic")]


def test_a_raised_threshold_regenerates_more(folder):
    fake = FakeAI(drafts=two_drafts(), critic=[scores(3, 3, 3, 3), scores(4, 4, 4, 4)])
    [item] = run(folder, fake, config={"outreach_critic_threshold": 4}).items
    assert len(fake.of("draft")) == 2
    assert "critic: regenerated once (score 3, threshold 4)" in item.flags


def test_threshold_zero_turns_the_critic_off(folder):
    fake = FakeAI()
    [item] = run(folder, fake, config={"outreach_critic_threshold": 0}).items
    assert fake.of("critic") == [] and item.critic == {} and item.critic_reason == ""
    assert not [f for f in item.flags if f.startswith("critic")]


def test_no_critic_object_means_no_critic_call(folder):
    fake = FakeAI()
    [item] = run(folder, fake, critic=False).items
    assert fake.of("critic") == [] and item.critic == {}


@pytest.mark.parametrize("value,expected", [
    (None, 2), ("", 2), (0, 0), ("0", 0), (3, 3), ("4", 4), (9, 5), (-2, 0), ("lots", 2),
    (True, 2), (2.0, 2)])
def test_the_threshold_setting_is_read_leniently(value, expected):
    config = {} if value is None else {"outreach_critic_threshold": value}
    assert outreach.critic_threshold(config) == expected


# ------------------------------------------------------- the critic fails


@pytest.mark.parametrize("answer,why", [
    (EnrichError("the AI CLI timed out"), "the AI CLI timed out"),
    ("not json", "the critic returned no JSON object"),
    ({"relevance": 4, "personal": 4, "tone": 4, "reason": "x"}, "the critic's honesty score is None, not 1 to 5"),
    (scores(honesty=7), "the critic's honesty score is 7, not 1 to 5"),
    (scores(tone=True), "the critic's tone score is True, not 1 to 5"),
    (scores(tone="high"), "the critic's tone score is 'high', not 1 to 5"),
])
def test_a_failing_critic_leaves_the_draft_and_says_so(folder, answer, why):
    fake = FakeAI(critic=[answer])
    result = run(folder, fake)
    [item] = result.items
    assert item.state == "drafted" and item.critic == {} and item.critic_reason == ""
    assert len(fake.of("draft")) == 1 and len(fake.of("critic")) == 1   # asked once, no retry
    assert f"critic did not run: {why}" in item.flags
    assert result.lines[0].startswith("drafted: ") and "critic" not in result.lines[0]


def test_a_critic_that_fails_on_the_second_draft_keeps_that_draft(folder):
    fake = FakeAI(drafts=two_drafts(),
                  critic=[scores(1, 4, 4, 4, "Invented familiarity."), EnrichError("timed out")])
    [item] = run(folder, fake).items
    assert "is a real change" in item.body and item.critic == {}
    assert "critic: regenerated once (score 1, threshold 2)" in item.flags
    assert "critic did not run on the new draft: timed out" in item.flags


def test_when_the_second_draft_fails_the_first_stays_with_its_scores(folder):
    def nothing(prompt):
        return "no json at all"

    fake = FakeAI(drafts=[default_draft, nothing],
                  critic=[scores(4, 4, 4, 1, "Claims it saw a post.")])
    [item] = run(folder, fake).items
    assert item.state == "drafted" and "caught my eye" in item.body
    assert item.critic["honesty"] == 1
    assert any(f.startswith("critic: asked for a new draft (score 1, threshold 2) but the AI "
                            "gave none") for f in item.flags)


def test_a_failed_draft_is_not_scored(folder):
    def nothing(prompt):
        return "no json at all"

    fake = FakeAI(drafts=[nothing])
    [item] = run(folder, fake).items
    assert item.state == "skipped" and fake.of("critic") == []


def test_a_fallback_draft_with_gaps_is_not_scored():
    draft = outreach.Draft(subject="Hello", body="Hi Sam,\n\n[their trigger]\n")
    asked = []

    class Critic:
        def critique(self, *args, **kwargs):
            asked.append(args)
            return outreach.CriticResult({n: 5 for n in outreach.CRITIC_SCORES})

    brief = outreach.Brief(who="Sam")
    args = (Critic(), {}, draft, lambda reason: draft, "first-touch", "email", brief, None, [],
            None)
    assert outreach._review(*args, True) is None and asked == []
    assert outreach._review(*args, False) is not None and len(asked) == 1


# --------------------------------------------------- commits and the files


def test_the_critic_adds_no_commit(folder):
    root, store = folder
    before = len(commits(root))
    fake = FakeAI(drafts=two_drafts(), critic=[scores(1, 1, 1, 1), scores(4, 4, 4, 4)])
    [item] = run(folder, fake).items
    log = commits(root)[:len(commits(root)) - before]
    assert len(log) == 2                                   # research, then the draft
    assert log[0].startswith("outreach: draft ") and log[1].startswith("outreach: research ")
    assert git(root, "status", "--porcelain") == ""
    assert outreach.get_item(root, item.id).critic == item.critic


def test_the_scores_are_written_after_checks_and_read_back(folder):
    root, store = folder
    fake = FakeAI(critic=[scores(5, 4, 3, 2, "Fine.")])
    [item] = run(folder, fake).items
    text = (root / item.path).read_text()
    head = text.split("---")[1]
    assert head.index("checks:") < head.index("critic:") < head.index("critic_reason:") \
        < head.index("critic_model:") < head.index("flags:")
    back = outreach.get_item(root, item.id)
    assert back.critic == {"relevance": 5, "personal": 4, "tone": 3, "honesty": 2}
    assert back.critic_reason == "Fine." and back.critic_score == 2
    again = outreach.item_text(back)
    assert again == text                                   # byte for byte


def test_an_item_without_the_keys_reads_as_not_scored(folder):
    root, store = folder
    [item] = run(folder, FakeAI(), critic=False).items
    path = root / item.path
    text = path.read_text()
    for key in ("critic", "critic_reason", "critic_model"):
        text = "\n".join(line for line in text.splitlines()
                         if not line.startswith(f"{key}:")) + "\n"
    path.write_text(text)
    back = outreach.get_item(root, item.id)
    assert back.critic == {} and back.critic_score == 0 and back.critic_reason == ""


def test_malformed_scores_are_ignored_when_reading(folder):
    root, store = folder
    [item] = run(folder, FakeAI(), critic=False).items
    path = root / item.path
    path.write_text(path.read_text().replace(
        "critic: {}", "critic: {relevance: 4, personal: 9, tone: x, honesty: 2, other: 5}"))
    assert outreach.get_item(root, item.id).critic == {"relevance": 4, "honesty": 2}


# ----------------------------------------------- replies and follow-ups


def test_a_follow_up_is_judged_against_the_message_it_follows(folder):
    root, store = folder
    store.create_interaction("lindenhof-data", "email", "out", subject="Your second office",
                             contact="mara-keller", date=NOW - timedelta(days=6),
                             body="Hi Mara,\n\nA first message about hiring.\n\nSam\n")
    fake = FakeAI(critic=[scores(4, 4, 4, 4)])
    [item] = run(folder, fake, kind="follow-up").items
    assert item.kind == "follow-up" and item.critic_score == 4
    prompt = fake.of("critic")[0]["prompt"]
    assert "--- your earlier message (2026-10-10, email out) ---" in prompt
    assert "A first message about hiring." in prompt
    assert "--- usable findings about them ---" not in prompt
    assert "A follow-up needs no finding: do not mark it down for having none." in prompt


def test_a_reply_to_interest_is_judged_on_their_words_not_on_a_finding():
    brief = outreach.Brief(who="Mara")
    reply = type("Reply", (), {"body": "Sounds interesting, how does it work?", "label":
                               "email in", "date": NOW})()
    prompt = outreach.critic_prompt("reply-to-interest", brief, "email", "Re: hello",
                                    "Hi Mara,\n\nHere is how.\n", "", [], None, "", reply)
    assert "--- their reply (2026-10-16, email in) ---" in prompt
    assert "Sounds interesting, how does it work?" in prompt
    assert "do not mark it down for having none" in prompt
    assert "usable findings" not in prompt


def test_a_first_touch_prompt_lists_only_usable_findings_with_their_numbers():
    brief = outreach.Brief(who="Mara")
    findings = [outreach.Finding("Opened an office", "https://a.example.com", "trigger", "high"),
                outreach.Finding("Maybe hiring", "https://a.example.com", "trigger", "low"),
                outreach.Finding("Founded in 2019", "https://b.example.com", "company",
                                 "medium")]
    prompt = outreach.critic_prompt("first-touch", brief, "email", "Hello", "Hi.\n", "",
                                    findings, None, "")
    assert "1. [trigger, high; source https://a.example.com] Opened an office" in prompt
    assert "Maybe hiring" not in prompt
    assert "3. [company, medium; source https://b.example.com] Founded in 2019" in prompt


# ------------------------------------------------------- check again


def drafted_item(folder, fake):
    [item] = run(folder, fake, critic=False).items
    return item


def test_check_again_asks_the_critic_about_the_edited_text(folder):
    root, store = folder
    item = drafted_item(folder, FakeAI())
    fake = FakeAI(critic=[scores(3, 5, 4, 4, "Warmer now.")])
    before = len(commits(root))
    edited = item.body.replace("caught my eye", "was a nice surprise")
    item, found = outreach.save_text(store, item.id, body=edited,
                                     critic=outreach.AICritic(store, ai(fake)))
    assert found == [] and item.critic["personal"] == 5 and item.critic_reason == "Warmer now."
    assert "was a nice surprise" in fake.of("critic")[0]["prompt"]
    assert fake.of("critic")[0]["tools"] == "" and fake.of("draft") == []   # no regeneration
    assert len(commits(root)) == before + 1                                # one commit


def test_check_again_with_a_low_score_does_not_regenerate_the_edit(folder):
    root, store = folder
    item = drafted_item(folder, FakeAI())
    fake = FakeAI(critic=[scores(1, 1, 1, 1, "Hmm.")])
    item, found = outreach.save_text(store, item.id, body=item.body,
                                     critic=outreach.AICritic(store, ai(fake)))
    assert item.critic_score == 1 and len(fake.of("critic")) == 1 and fake.of("draft") == []
    assert found == []                       # the score is not a check
    assert item.body == item.ai_body


def test_check_again_without_an_ai_runs_the_checks_and_says_the_critic_did_not_run(folder):
    root, store = folder
    item = drafted_item(folder, FakeAI())
    item.critic, item.critic_reason = {n: 4 for n in outreach.CRITIC_SCORES}, "Old."
    outreach.write_item(root, item)
    bad = item.body.replace("?", ".")
    item, found = outreach.save_text(store, item.id, body=bad, why_not="The AI CLI is not "
                                                                     "available: no CLI")
    assert any("questions" in p for p in found)             # the hard checks still run
    assert item.critic == {} and item.critic_reason == ""   # the old scores described other words
    assert "critic did not run: The AI CLI is not available: no CLI" in item.flags


def test_check_again_with_the_critic_off_says_nothing_and_drops_old_scores(folder):
    root, store = folder
    item = drafted_item(folder, FakeAI())
    item.critic = {n: 4 for n in outreach.CRITIC_SCORES}
    item, _ = outreach.save_text(store, item.id, body=item.body,
                                 config={"outreach_critic_threshold": 0})
    assert item.critic == {} and not [f for f in item.flags if f.startswith("critic")]


def test_check_again_replaces_an_old_critic_flag(folder):
    root, store = folder
    item = drafted_item(folder, FakeAI())
    outreach.save_text(store, item.id, body=item.body)
    assert outreach.get_item(root, item.id).flags.count("critic did not run: no AI available") == 1
    item, _ = outreach.save_text(store, item.id, body=item.body)
    assert item.flags.count("critic did not run: no AI available") == 1   # not twice
    fake = FakeAI()
    item, _ = outreach.save_text(store, item.id, body=item.body,
                                 critic=outreach.AICritic(store, ai(fake)))
    assert not [f for f in item.flags if f.startswith("critic")] and item.critic


def test_a_high_score_does_not_hide_a_failing_hard_check(folder):
    root, store = folder
    item = drafted_item(folder, FakeAI())
    fake = FakeAI(critic=[scores(5, 5, 5, 5, "Perfect.")])
    bad = item.body.replace("?", ".")
    item, found = outreach.save_text(store, item.id, body=bad,
                                     critic=outreach.AICritic(store, ai(fake)))
    assert item.critic_score == 5 and found and item.checks == found


def test_mark_ready_does_not_ask_the_critic_and_keeps_the_scores(folder):
    root, store = folder
    fake = FakeAI(critic=[scores(4, 4, 4, 4, "Good.")])
    [item] = run(folder, fake).items
    calls = len(fake.calls)
    ready, _ = outreach.mark_ready(store, item.id)
    assert len(fake.calls) == calls
    assert ready.critic_score == 4 and ready.critic_reason == "Good."


# ------------------------------------------------------------ regenerate


def test_regenerate_scores_the_new_draft_and_drops_the_old_scores_and_flags(folder):
    root, store = folder
    first = FakeAI(drafts=two_drafts(), critic=[scores(1, 1, 1, 1, "Bad."), scores(5, 5, 5, 5)])
    [item] = run(folder, first).items
    assert "critic: regenerated once (score 1, threshold 2)" in item.flags
    fake = FakeAI(drafts=two_drafts(), critic=[scores(4, 4, 4, 3, "Fine now.")])
    again = outreach.redraft(store, item.id, outreach.AIDrafter(store, ai(fake), {}),
                             critic=outreach.AICritic(store, ai(fake)))
    assert again.critic_reason == "Fine now." and again.critic_score == 3
    assert not [f for f in again.flags if f.startswith("critic")]
    assert len(fake.of("draft")) == 1 and len(fake.of("critic")) == 1


def test_regenerate_regenerates_once_more_on_a_low_score_and_counts_the_calls(folder):
    root, store = folder
    [item] = run(folder, FakeAI(), critic=False).items
    fake = FakeAI(drafts=two_drafts(), critic=[scores(1, 4, 4, 4, "Invented."), scores()])
    again = outreach.redraft(store, item.id, outreach.AIDrafter(store, ai(fake), {}),
                             critic=outreach.AICritic(store, ai(fake)))
    assert len(fake.of("draft")) == 2 and again.attempts == 2
    assert "critic: regenerated once (score 1, threshold 2)" in again.flags
    assert commits(root)[0].startswith("outreach: regenerate ")


def test_regenerate_without_a_critic_clears_the_scores_of_the_old_text(folder):
    root, store = folder
    [item] = run(folder, FakeAI()).items
    assert item.critic
    again = outreach.redraft(store, item.id, outreach.AIDrafter(store, ai(FakeAI()), {}))
    assert again.critic == {} and again.critic_reason == ""


# ------------------------------------------------------------ the CLI


def test_the_command_line_shows_the_scores_in_the_build_line_and_on_show(tmp_path, monkeypatch,
                                                                         capsys):
    root = init_folder(tmp_path / "x", demo=True, now=NOW)
    fake = FakeAI(critic=[scores(5, 4, 3, 4, "Plain and honest.")])
    monkeypatch.setattr(outreach, "default_enricher", lambda config, tier="medium": ai(fake))
    from hermitcrm import scrape
    monkeypatch.setattr(scrape, "fetch", lambda url, timeout=10: fake_page(url))
    code = cli.main(["outreach", "build", "--contact", MARA], root=root)
    out = capsys.readouterr().out
    assert code == 0, out
    assert "| checks passed | critic 3/5 |" in out
    [item] = outreach.items(root)
    assert cli.main(["outreach", "show", item.id], root=root) == 0
    card = capsys.readouterr().out
    assert ("Critic: 3/5 lowest (relevance 5, personal 4, tone 3, honesty 4): "
            "Plain and honest.") in card
    assert len(fake.of("critic")) == 1


def test_the_command_line_with_the_critic_off_does_not_ask(tmp_path, monkeypatch, capsys):
    root = init_folder(tmp_path / "x", demo=True, now=NOW)
    (root / "config.toml").write_text(
        (root / "config.toml").read_text() + "\noutreach_critic_threshold = 0\n")
    fake = FakeAI()
    monkeypatch.setattr(outreach, "default_enricher", lambda config, tier="medium": ai(fake))
    from hermitcrm import scrape
    monkeypatch.setattr(scrape, "fetch", lambda url, timeout=10: fake_page(url))
    assert cli.main(["outreach", "build", "--contact", MARA], root=root) == 0
    out = capsys.readouterr().out
    assert fake.of("critic") == [] and "critic" not in out.split("item(s)")[0]


# ------------------------------------------------------------- the page


@pytest.fixture
def root(tmp_path):
    return init_folder(tmp_path / "crm", demo=True, now=NOW)


@pytest.fixture
def fake():
    return FakeAI(critic=[scores(4, 2, 5, 4, "The opener is generic.")])


@pytest.fixture
def client(root, fake):
    app = create_app(root, {**load_config(root), "push_enabled": False,
                            "owner_name": "Sam Example"})
    app.state.setup_redirected = True
    app.state.enricher = ai(fake)
    app.state.outreach_fetcher = fake_page
    app.state.store.clock = lambda: NOW
    return TestClient(app, follow_redirects=False)


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.app.state.csrf_token, **data})


def query(response) -> dict:
    return dict(QueryParams(URL(response.headers["location"]).query))


def web_item(client, root) -> outreach.Item:
    response = post(client, "/outreach/build", contact=MARA, back="/outreach")
    assert response.status_code == 303, response.text
    return next(i for i in outreach.items(root) if i.record == MARA)


def test_the_card_shows_the_scores_and_the_reason_next_to_the_checks(client, root, fake):
    item = web_item(client, root)
    assert item.critic_score == 2 and len(fake.of("critic")) == 1
    page = client.get("/outreach").text
    assert "Critic 2/5" in page
    assert "relevance 4, personal 2, tone 5, honesty 4" in page
    assert "The opener is generic." in page
    assert "Checks passed." not in page
    assert '<details class="small outreach-critic"' in page
    assert "asks the AI critic to score it again" in page


def test_a_card_without_scores_shows_no_critic_line(client, root):
    client.app.state.config["outreach_critic_threshold"] = 0
    web_item(client, root)
    assert "Critic " not in client.get("/outreach").text


def test_save_and_check_again_on_the_page_scores_the_edit(client, root, fake):
    item = web_item(client, root)
    fake.critic = [scores(5, 5, 5, 5, "Now it is personal.")]
    response = post(client, f"/outreach/{item.id}/check", subject=item.subject,
                    body=item.body.replace("caught my eye", "was a nice surprise"))
    assert response.status_code == 303 and "Saved." in query(response)["flash"]
    back = outreach.get_item(root, item.id)
    assert back.critic_score == 5 and back.critic_reason == "Now it is personal."
    assert "Critic 5/5" in client.get("/outreach").text


def test_save_and_check_again_without_an_ai_says_the_critic_did_not_run(client, root):
    item = web_item(client, root)
    client.app.state.enricher = outreach.default_enricher({"enrich_provider": "none"})
    response = post(client, f"/outreach/{item.id}/check", subject=item.subject, body=item.body)
    assert response.status_code == 303
    back = outreach.get_item(root, item.id)
    assert back.critic == {} and any(f.startswith("critic did not run: The AI CLI is not "
                                                  "available") for f in back.flags)
    assert "critic did not run" in client.get("/outreach").text


def test_regenerate_on_the_page_runs_the_critic(client, root, fake):
    item = web_item(client, root)
    fake.critic = [scores(3, 3, 3, 3, "Okay.")]
    response = post(client, f"/outreach/{item.id}/regenerate")
    assert response.status_code == 303
    assert outreach.get_item(root, item.id).critic_reason == "Okay."


def test_the_setting_is_described_and_defaults_to_two(root):
    from hermitcrm import datafolder, store as store_module

    assert store_module.DEFAULT_CONFIG["outreach_critic_threshold"] == 2
    assert "outreach_critic_threshold" in datafolder.CONFIG_DOCS
    assert load_config(root)["outreach_critic_threshold"] == 2
