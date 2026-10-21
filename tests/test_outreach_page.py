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

"""Outreach, part 05d: "Add to research". The bookmarklet reads a LinkedIn
profile in your own tab; for someone already saved whose card is drafted, the
app offers the page to the card: trim it, add it, the AI (no tools) turns it
into findings sourced to the profile. The bookmarklet is run in node against
a stub page. The AI is a fake; all names are made up."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from urllib.parse import parse_qsl, quote, urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import URL, QueryParams

from hermitcrm import capture, notes, outreach
from hermitcrm.datafolder import init_folder
from hermitcrm.store import load_config
from hermitcrm.web import create_app
from outreach_fakes import NOW, FakeAI, ai, default_draft, default_research, fake_page, git

MARA = "lindenhof-data/mara-keller"
PROFILE = "https://www.linkedin.com/in/mara-keller-x"
ABOUT = "We build data tools for small teams. I started Lindenhof to fix reporting."
ACTIVITY = "Mara Keller posted\nWe just hired our first account executive in Hamburg."
TOP = "Mara Keller\nCEO at Lindenhof Data\nBerlin, Germany"


def profile_answer(prompt):
    """The AI's answer for the profile page: findings sourced to the address in
    the prompt, one not about the page at all."""
    if "--- page " not in prompt or "linkedin.com/in/" not in prompt:
        return default_research(prompt)
    return {"findings": [
        {"text": "Hired a first account executive in Hamburg", "source": PROFILE,
         "kind": "trigger", "confidence": "high", "date": "2026-10-08"},
        {"text": "Started the company to fix reporting", "source": PROFILE,
         "kind": "company", "confidence": "medium", "date": ""},
        {"text": "Is an investor", "source": "https://other.example.net/mara",
         "kind": "person", "confidence": "high", "date": ""},
        {"text": "Likes sailing", "source": "", "kind": "person", "confidence": "high",
         "date": ""},
    ]}


@pytest.fixture
def root(tmp_path):
    return init_folder(tmp_path / "crm", demo=True, now=NOW)


@pytest.fixture
def fake():
    return FakeAI(research=profile_answer)


@pytest.fixture
def client(root, fake):
    app = create_app(root, {**load_config(root), "push_enabled": False,
                            "owner_name": "Sam Example"})
    app.state.setup_redirected = True
    app.state.enricher = ai(fake)
    app.state.outreach_fetcher = fake_page
    app.state.store.clock = lambda: NOW
    app.state.store.update_contact("lindenhof-data", "mara-keller", linkedin=PROFILE)
    return TestClient(app, follow_redirects=False)


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.app.state.csrf_token, **data})


def query(response) -> dict:
    return dict(QueryParams(URL(response.headers["location"]).query))


def commits(root) -> list[str]:
    return git(root, "log", "--format=%s").splitlines()


def drafted(client, root) -> outreach.Item:
    response = post(client, "/outreach/build", contact=MARA, back="/outreach")
    assert response.status_code == 303, response.text
    return next(i for i in outreach.items(root) if i.record == MARA)


READ = {"url": PROFILE + "/", "v": "3", "h1": "Mara Keller", "top": TOP, "about": ABOUT,
        "act": ACTIVITY}


# ------------------------------------------------------- the page that offers


def test_a_saved_profile_with_a_drafted_card_offers_add_to_research(client, root):
    item = drafted(client, root)
    before = commits(root)
    status = git(root, "status", "--porcelain")
    page = client.get("/extension/new", params=READ)
    assert page.status_code == 200
    assert "Add to research" in page.text and "Mara Keller" in page.text
    assert f'action="/outreach/{item.id}/page"' in page.text
    for piece in (TOP, ABOUT, "hired our first account executive"):
        assert piece in page.text
    assert 'name="about"' in page.text and 'name="act"' in page.text and 'name="top"' in page.text
    assert 'name="csrf_token"' in page.text and f'value="{PROFILE}"' in page.text
    assert commits(root) == before and git(root, "status", "--porcelain") == status  # a GET


def test_the_page_lists_what_was_not_read(client, root):
    drafted(client, root)
    page = client.get("/extension/new", params={**READ, "about": "", "act": ""})
    assert page.text.count("nothing read") == 2


def test_an_old_v2_query_still_opens_the_page_with_the_top_card(client, root):
    drafted(client, root)
    old = {"url": PROFILE, "v": "2", "h1": "Mara Keller", "top": TOP, "exp": "x"}
    page = client.get("/extension/new", params=old)
    assert page.status_code == 200 and "Add to research" in page.text and TOP in page.text


def test_without_an_open_card_it_goes_to_the_contact_as_before(client, root):
    response = client.get("/extension/new", params=READ)
    assert response.status_code == 303
    assert response.headers["location"].startswith(
        "/companies/lindenhof-data/contacts/mara-keller")


def test_a_skipped_or_sent_card_is_not_open(client, root):
    item = drafted(client, root)
    post(client, f"/outreach/{item.id}/skip", reason="bad-timing")
    assert client.get("/extension/new", params=READ).status_code == 303


def test_a_ready_card_says_why_it_cannot_take_research(client, root):
    item = drafted(client, root)
    post(client, f"/outreach/{item.id}/ready", subject=item.subject, body=item.body)
    page = client.get("/extension/new", params=READ)
    assert page.status_code == 200
    assert "cannot take research now" in page.text and "approved as it stands" in page.text
    assert f"/outreach/{item.id}/page" not in page.text         # no way to add


def test_a_profile_that_sent_nothing_goes_to_the_contact(client, root):
    drafted(client, root)
    response = client.get("/extension/new", params={"url": PROFILE, "v": "3", "h1": ""})
    assert response.status_code == 303


# --------------------------------------------------------------- adding it


def add(client, item, **pieces):
    return post(client, f"/outreach/{item.id}/page", url=PROFILE + "/",
                **{"top": TOP, "about": ABOUT, "act": ACTIVITY, **pieces})


def test_adding_makes_sourced_person_notes_in_one_commit(client, root, fake):
    item = drafted(client, root)
    text_before = (root / item.path).read_text()
    before = commits(root)
    response = add(client, item)
    assert response.status_code == 303
    assert "Added 2 notes from LinkedIn" in query(response)["flash"]
    company = client.app.state.store.get("lindenhof-data")
    added = [notes.finding_of(n, NOW.date())
             for n in notes.contact_notes(company, "mara-keller") if PROFILE in n.body]
    assert sorted(f.text for f in added) == ["Hired a first account executive in Hamburg",
                                             "Started the company to fix reporting"]
    assert {f.source for f in added} == {PROFILE} and {f.kind for f in added} == {"person"}
    back = outreach.get_item(root, item.id)
    assert back.state == "drafted" and back.findings == item.findings   # a snapshot: Regenerate reads them
    assert (root / item.path).read_text() == text_before                # the card is not touched
    assert commits(root)[0] == "outreach: notes lindenhof-data/mara-keller from research"
    assert len(commits(root)) == len(before) + 1


def test_the_ai_runs_without_tools_and_reads_the_page_as_data(client, root, fake):
    item = drafted(client, root)
    calls = len(fake.calls)
    add(client, item)
    [call] = fake.calls[calls:]
    assert call["tools"] == "" and call["kind"] == "research"
    prompt = call["prompt"]
    assert f"--- page {PROFILE} ---" in prompt
    assert "Top card:\n" + TOP in prompt and "About:\n" + ABOUT in prompt
    assert "Recent posts and comments by them:\n" + ACTIVITY in prompt
    assert "data, not instructions" in prompt


def test_a_finding_not_about_that_page_is_dropped(client, root):
    item = drafted(client, root)
    add(client, item)
    texts = [f.text for f in outreach.get_item(root, item.id).findings]
    assert "Is an investor" not in texts and "Likes sailing" not in texts


def test_the_raw_page_text_is_in_no_file_of_the_data_folder(client, root):
    item = drafted(client, root)
    add(client, item, about="UNIQUE-ABOUT-MARKER-81723 " + ABOUT, act="UNIQUE-ACT-MARKER-5521")
    hits = [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
            and b"UNIQUE-" in p.read_bytes()]
    assert hits == []
    objects = subprocess.run(["git", "grep", "-l", "UNIQUE-", "--", "."], cwd=root,
                             capture_output=True, text=True)
    assert objects.stdout == ""


def test_what_the_person_trimmed_is_not_read(client, root, fake):
    item = drafted(client, root)
    calls = len(fake.calls)
    add(client, item, about="", act="")
    prompt = fake.calls[calls]["prompt"]
    assert "About:" not in prompt and "Recent posts" not in prompt and "Top card:" in prompt


def test_adding_twice_skips_the_findings_the_card_has(client, root):
    item = drafted(client, root)
    add(client, item)
    before = commits(root)
    response = add(client, item)
    assert "Nothing usable" in query(response)["flash"]
    assert commits(root) == before
    texts = [f.text for f in outreach.get_item(root, item.id).findings]
    assert len(texts) == len(set(texts))


def test_a_regenerate_can_use_the_added_finding(client, root, fake):
    item = drafted(client, root)
    add(client, item)
    cited = []

    def draft(prompt):
        n = re.search(r"^(\d+)\. \[[^\]]*\] Hired a first account executive in Hamburg", prompt,
                      re.M).group(1)
        cited.append(int(n))
        data = default_draft(prompt)
        data["findings_used"] = [int(n)]
        return data

    fake.drafts = [draft]
    post(client, f"/outreach/{item.id}/regenerate")
    back = outreach.get_item(root, item.id)
    assert back.checks == [] and back.findings[cited[0] - 1].used     # known to the check
    assert back.findings[cited[0] - 1].source == PROFILE


def test_a_page_added_note_can_be_deleted_like_any_other_note(client, root):
    item = drafted(client, root)
    add(client, item)
    store = client.app.state.store
    mine = [n for n in notes.contact_notes(store.get("lindenhof-data"), "mara-keller")
            if PROFILE in n.body]
    store.delete_interaction("lindenhof-data", mine[0].id)
    post(client, f"/outreach/{item.id}/regenerate")
    after = outreach.get_item(root, item.id).findings
    assert sum(f.source == PROFILE for f in after) == len(mine) - 1


# ------------------------------------------------------------------ refusals


def test_post_without_the_csrf_token_is_refused(client, root):
    item = drafted(client, root)
    response = client.post(f"/outreach/{item.id}/page",
                           data={"url": PROFILE, "about": ABOUT})
    assert response.status_code == 403
    assert outreach.get_item(root, item.id).findings == item.findings


def test_a_cross_site_post_is_refused(client, root, fake):
    item = drafted(client, root)
    calls = len(fake.calls)
    response = client.post(f"/outreach/{item.id}/page", headers={
        "Origin": "https://www.linkedin.com", "Sec-Fetch-Site": "cross-site"},
        data={"csrf_token": client.app.state.csrf_token, "url": PROFILE, "about": ABOUT})
    assert response.status_code == 403 and len(fake.calls) == calls
    assert outreach.get_item(root, item.id).findings == item.findings


def test_a_page_that_is_not_this_contacts_profile_is_refused(client, root, fake):
    item = drafted(client, root)
    calls = len(fake.calls)
    response = post(client, f"/outreach/{item.id}/page",
                    url="https://www.linkedin.com/in/someone-else", about=ABOUT)
    assert "not this contact's LinkedIn profile" in query(response)["flash"]
    assert len(fake.calls) == calls and outreach.get_item(root, item.id).findings == item.findings


def test_without_an_ai_it_is_refused_with_the_reason_and_nothing_is_written(client, root):
    item = drafted(client, root)
    client.app.state.enricher = outreach.default_enricher({"enrich_provider": "none"})
    before = commits(root)
    response = add(client, item)
    assert "Not added: The AI CLI is not available" in query(response)["flash"]
    assert commits(root) == before
    page = client.get("/extension/new", params=READ)
    assert "The AI CLI is not available" in page.text and "disabled" in page.text


def test_a_card_that_is_not_drafted_takes_nothing(client, root):
    item = drafted(client, root)
    post(client, f"/outreach/{item.id}/ready", subject=item.subject, body=item.body)
    response = add(client, item)
    assert "only a drafted item can take more research" in query(response)["flash"]


def test_a_failing_ai_leaves_the_card_alone(client, root, fake):
    from hermitcrm.enrich import EnrichError

    item = drafted(client, root)
    fake.research = EnrichError("timed out")
    before = commits(root)
    response = add(client, item)
    assert "Not added: the AI could not read the page: timed out" in query(response)["flash"]
    assert commits(root) == before


def test_an_unknown_card_is_a_404(client):
    response = post(client, "/outreach/nope/page", url=PROFILE)
    assert response.status_code == 404


# ----------------------------------------------------------- the bookmarklet

NODE = shutil.which("node")


def run_bookmarklet(body: str, href: str = "https://www.linkedin.com/in/mara-keller-x/"):
    """The bookmarklet as the browser would run it, on a page that is only text
    (no hooks): returns the address it opens."""
    code = capture.bookmarklet("http://localhost:8000")[len("javascript:"):]
    harness = """
const [code, body, href] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
let opened = '';
const doc = {title: 'Mara Keller | LinkedIn',
  body: {innerText: body, querySelector: () => null, querySelectorAll: () => [],
         closest: () => null},
  querySelector: () => null, getElementById: () => null,
  createTreeWalker: () => ({nextNode: () => false})};
new Function('document', 'location', 'encodeURIComponent', 'window', 'Node', 'NodeFilter',
  code)(doc, {href}, encodeURIComponent, {open: (u) => { opened = u; }},
  {DOCUMENT_POSITION_FOLLOWING: 4}, {SHOW_TEXT: 4});
process.stdout.write(opened);
"""
    out = subprocess.run([NODE, "-e", harness], input=json.dumps([code, body, href]),
                         capture_output=True, text=True, check=True).stdout
    return out, dict(parse_qsl(urlsplit(out).query, keep_blank_values=True))


PROFILE_TEXT = (
    "Mara Keller\nCEO at Lindenhof Data\nBerlin, Germany\n\nAbout\n" + ABOUT + "\n\n"
    "Activity\nMara Keller posted\nWe just hired our first account executive in Hamburg.\n\n"
    "Jan Example likes this\nA post by somebody else about conferences.\n\n"
    "Mara Keller commented\nGood point about onboarding.\n\n"
    "Mara Keller reposted this\nSomebody else's announcement.\n\n"
    "Experience\nCEO\nLindenhof Data · Full-time\nLed the team.\n")


def test_the_bookmarklet_stays_one_line_without_a_percent_sign():
    js = capture.bookmarklet("http://localhost:8000")
    assert js.startswith("javascript:") and "%" not in js and "\n" not in js
    assert "&v=3" in js and "&about=" in js and "&act=" in js


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_bookmarklet_sends_about_and_the_persons_own_posts_and_comments():
    url, got = run_bookmarklet(PROFILE_TEXT)
    assert got["v"] == "3" and got["url"].startswith("https://www.linkedin.com/in/mara-keller-x")
    assert got["about"] == ABOUT
    assert "hired our first account executive" in got["act"]
    assert "Good point about onboarding." in got["act"]
    assert "somebody else about conferences" not in got["act"]    # a reaction
    assert "announcement" not in got["act"]                        # a repost
    assert got["top"].startswith("Mara Keller") and "Led the team." in got["exp"]
    assert url.startswith("http://localhost:8000/extension/new?")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_pieces_fit_the_request_budget_on_a_long_profile():
    long = ("Mara Keller\nCEO at Lindenhof Data\nBerlin\n" + "a top card line é ü ñ\n" * 500
            + "\nAbout\n" + "About words ü. " * 500 + "\n\nActivity\n"
            + "".join(f"Mara Keller posted\nPost {i} é " + "y" * 400 + "\n\n" for i in range(9))
            + "Experience\nCEO\nLindenhof Data · Full-time\n" + "Led the team é. " * 500)
    url, got = run_bookmarklet(long)
    assert len(url.encode()) < 13000                               # 16 KB head with headers
    assert got["about"] and got["act"] and got["exp"] and got["top"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_over_budget_the_activity_shrinks_first_then_about_then_experience():
    # Everything long: the old pieces alone use most of the room.
    heavy = ("Mara Keller\nCEO\n" + "é" * 40 + "\n" + ("top ü\n" * 800)
             + "\nAbout\n" + "ü" * 4000 + "\n\nActivity\nMara Keller posted\n" + "ü" * 6000
             + "\n\nExperience\nCEO\nLindenhof Data · Full-time\n" + "ü" * 6000)
    url, got = run_bookmarklet(heavy)
    sizes = {k: len(quote(v, safe="")) for k, v in got.items()}
    assert len(url) < 13000
    assert sizes["act"] < 3000                                     # act gave way
    assert sizes["exp"] > 2000                                     # exp is the last to shrink


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_profile_without_about_or_activity_sends_them_empty():
    _, got = run_bookmarklet("Mara Keller\nCEO at Lindenhof Data\n\nExperience\nCEO\nLindenhof\n")
    assert got["about"] == "" and got["act"] == ""


def test_page_pieces_and_text_keep_the_order_and_skip_empty_ones():
    pieces = capture.page_pieces({"top": " Top ", "act": "Posts"})
    assert pieces == [("top", "Top card", "Top"), ("about", "About", ""),
                      ("act", "Recent posts and comments by them", "Posts")]
    assert capture.page_text({"top": "Top", "about": "  ", "act": "Posts"}) == (
        "Top card:\nTop\n\nRecent posts and comments by them:\nPosts")
    assert capture.page_text({}) == ""


# ------------------------------------------------- the contact on the card


def test_a_card_shows_the_contacts_email_next_to_linkedin(client, root):
    client.app.state.store.update_contact("lindenhof-data", "mara-keller",
                                          email="mara@example.com")
    item = drafted(client, root)
    page = client.get("/outreach", params={"tab": "drafts"}).text
    card = page[page.index(f'id="item-{item.id}"'):]
    head = card[:card.index("</p>")]
    assert 'href="mailto:mara@example.com"' in head and "mara@example.com</a>" in head
    assert head.index("LinkedIn") < head.index("mara@example.com")


def test_a_card_without_an_email_shows_no_mailto(client, root):
    item = drafted(client, root)
    client.app.state.store.update_contact("lindenhof-data", "mara-keller", email="")
    page = client.get("/outreach", params={"tab": "drafts"}).text
    card = page[page.index(f'id="item-{item.id}"'):]
    assert "mailto:" not in card[:card.index("</p>")]


# ------------------------------------------------- about you, about them


def worded(root, item, body, **fields):
    """The saved item with this text and language, as the page reads it back."""
    item.body, item.language = body, fields.pop("language", "en")
    for key, value in fields.items():
        setattr(item, key, value)
    outreach.write_item(root, item)
    return item


def card_text(client, item, tab="drafts"):
    page = client.get("/outreach", params={"tab": tab}).text
    start = page.index(f'id="item-{item.id}"')
    return page[start:page.index("</article>", start)]


def test_a_card_that_leans_to_you_says_so(client, root):
    item = worded(root, drafted(client, root),
                  "Hi Alex,\n\nWe help teams. Our clients grow. I can show you?\n\nSam")
    card = card_text(client, item)
    assert '<p class="small warning">About you 3, about them 1: more about you than about ' \
           'them</p>' in card


def test_a_card_that_leans_to_them_shows_the_count_without_a_warning(client, root):
    item = worded(root, drafted(client, root),
                  "Hi Alex,\n\nYour team grew. We see you hiring. Is your pipeline "
                  "ready?\n\nSam")
    line = '<p class="small">About you 1, about them 3</p>'
    assert line in card_text(client, item)
    assert "more about you" not in card_text(client, item)
    # the ready card shows it too
    post(client, f"/outreach/{item.id}/ready", subject=item.subject, body=item.body)
    ready = card_text(client, item, tab="ready")
    assert line in ready and "Mark ready" not in ready


def test_the_count_is_worked_out_only_for_the_cards_that_show_it(client, root, monkeypatch):
    item = worded(root, drafted(client, root), "Hi Alex,\n\nWe help teams.\n\nSam")
    asked, real = [], outreach.about_for_item
    monkeypatch.setattr(outreach, "about_for_item",
                        lambda folder, shown: asked.append(shown.id) or real(folder, shown))
    client.get("/outreach", params={"tab": "drafts"})
    assert asked == [item.id]
    asked.clear()
    worded(root, item, item.body, state="sent", sent=NOW)
    page = client.get("/outreach", params={"tab": "sent"}).text
    assert f'id="item-{item.id}"' in page and asked == []


def test_a_language_without_word_lists_shows_no_count(client, root):
    item = worded(root, drafted(client, root), "Hola Alex,\n\nTe ayudamos. ¿Te interesa?\n\nSam",
                  language="es")
    assert "About you" not in card_text(client, item)
