"""Route tests for app/web.py, including the §10 acceptance flow end to end."""

from __future__ import annotations

import html as htmllib
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from conftest import FIXED_NOW
from hermitcrm import usertheme
from hermitcrm.web import asset_version, company_values, create_app

CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "owner_email": "me@example.com",
          # an established user: these tests are not about the first launch
          "welcome_dismissed": True}

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


# ------------------------------------------------------------------- fixtures


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "CRM Test"], cwd=tmp_path,
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "crm@test.local"], cwd=tmp_path,
                   check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    return tmp_path


@pytest.fixture
def app(repo: Path):
    return create_app(repo, config=CONFIG)


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def frozen_app(repo: Path):
    """The app on the suite's fixed clock (2026-09-14).

    Most tests here date their records from the real `TODAY`, so they read the
    same on any day. A test that names absolute dates instead needs "today" to
    stand still: this hands `create_app` the same frozen clock the `store`
    fixture uses, so `store.today()` cannot drift into the dates it asserts on.
    """
    return create_app(repo, config=CONFIG, clock=lambda: FIXED_NOW)


@pytest.fixture
def frozen_client(frozen_app):
    return TestClient(frozen_app, follow_redirects=False)


# -------------------------------------------------------------------- helpers


COMPANY_BLANK = {
    "name": "", "website": "", "linkedin": "", "source": "other",
    "stage": "prospect", "lost_reason": "", "value_eur_month": "",
    "next_step": "", "next_step_due": "", "next_step_status": "open",
    "tags": "", "notes": "",
}
CONTACT_BLANK = {"first_name": "", "last_name": "", "title": "", "linkedin": "", "email": "",
                 "phone": "", "role": "", "notes": ""}
INTERACTION_BLANK = {"channel": "email", "direction": "out", "contact": "",
                     "date": "", "subject": "", "outcome": "", "body": ""}


def post_company(client, **fields):
    return client.post("/companies", data={**COMPANY_BLANK, **fields})


def define_fields(client, repo, toml: str):
    """Write fields.toml and make the running app pick it up."""
    (repo / "fields.toml").write_text(toml, encoding="utf-8")
    client.post("/reload")


MY_SCORE = ('[[field]]\nkey = "my_score"\nlabel = "my score"\ntype = "number"\n'
            'show_in = ["detail", "board", "companies"]\n')
FIT_AND_FTE = ('[[field]]\nkey = "fit_score"\nlabel = "fit"\ntype = "number"\n'
               'show_in = ["detail", "companies"]\n\n'
               '[[field]]\nkey = "fte_estimate"\nlabel = "FTE"\ntype = "text"\n'
               'show_in = ["detail", "companies"]\n')


def patch_company(client, app, slug, **fields):
    """POST the full edit form, changing only the given fields."""
    values = company_values(app.state.store.companies[slug])
    values.update(fields)
    return client.post(f"/companies/{slug}", data=values)


def post_contact(client, slug, **fields):
    return client.post(f"/companies/{slug}/contacts",
                       data={**CONTACT_BLANK, **fields})


def post_interaction(client, slug, **fields):
    return client.post(f"/companies/{slug}/interactions",
                       data={**INTERACTION_BLANK, **fields})


def last_commit(repo: Path) -> str:
    out = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo,
                         capture_output=True, text=True)
    return out.stdout.strip()


def company_file(repo: Path, slug: str) -> Path:
    return repo / "companies" / slug / "company.md"


def pipeline_text(repo: Path) -> str:
    return (repo / "PIPELINE.md").read_text(encoding="utf-8")


def calendar_params(page: str) -> dict:
    match = re.search(r'href="(https://calendar\.google\.com[^"]+)"', page)
    assert match, "no Google Calendar link on the page"
    url = htmllib.unescape(match.group(1))
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


# ------------------------------------------------------------- simple routes


def test_health_shape(client, repo):
    post_company(client, name="Acme GmbH")
    post_contact(client, "acme", first_name="Jane", last_name="Doe", email="jane@acme.de")
    post_interaction(client, "acme", channel="email", direction="out",
                     contact="jane-doe", date="2026-09-01T09:00", subject="Hi")

    payload = client.get("/health").json()
    assert payload["companies"] == 1
    assert payload["contacts"] == 1
    assert payload["interactions"] == 1
    assert payload["problems"] == []
    assert payload["last_commit"]  # a sha after the writes above
    assert payload["last_push"] is None  # push disabled in tests


def test_board_lists_open_and_closed(client, app, repo):
    post_company(client, name="Acme GmbH", stage="prospect")
    post_company(client, name="Beta AG", stage="discovery",
                 next_step="Call back", next_step_due=str(YESTERDAY))
    post_company(client, name="Gamma BV", stage="won")

    page = client.get("/pipeline").text
    assert 'id="col-prospect"' in page and 'id="col-discovery"' in page
    assert page.index('id="col-prospect"') < page.index('id="col-engaged"') \
        < page.index('id="col-discovery"') < page.index('id="col-offer"')
    assert "Acme GmbH" in page and "Beta AG" in page and "Gamma BV" in page
    assert "overdue" in page  # Beta AG's next step is in the past
    assert "won (1)" in page and "lost (0)" in page
    assert 'onchange="this.form.submit()"' in page
    assert "d in stage" in page


def test_the_home_page_is_not_the_board(client, app, repo):
    """Reported: the logo and the Pipeline tab went to the same place."""
    post_company(client, name="Acme", next_step="Call Jane", next_step_due=str(TODAY))
    client.post("/companies/acme/tasks", data={"text": "send the deck",
                                               "due": str(TODAY)})

    page = client.get("/").text
    assert 'class="board"' not in page                  # the board is elsewhere now
    assert "What needs doing" in page and "How it is going" in page
    assert "What this thing does" in page
    assert "Call Jane" in page and "send the deck" in page   # both kinds of work
    assert 'href="/pipeline"' in page and "Every open deal as a card" in page

    nav = page.split("</nav>")[0]
    assert 'href="/"' in nav and 'href="/pipeline"' in nav   # two entries, two places
    assert 'class="brand" href="/"' in nav

    board = client.get("/pipeline").text
    assert 'class="board"' in board and 'id="col-prospect"' in board


def test_the_home_page_only_shows_the_next_seven_days(client, app):
    post_company(client, name="Soon", next_step="this week", next_step_due=str(TODAY))
    post_company(client, name="Later", next_step="next month",
                 next_step_due=str(TODAY + timedelta(days=40)))
    page = client.get("/").text
    doing = page.split('id="doing"')[1].split("</table>")[0]
    assert "this week" in doing and "next month" not in doing
    assert 'href="/calendar"' in page          # the rest is one click away


def test_the_walkthrough_ticks_itself_from_the_data(client, app, repo):
    page = client.get("/welcome").text
    assert "of 10</strong> done" in page
    before = int(page.split("<strong>")[1].split(" of")[0])

    post_company(client, name="Acme")
    post_contact(client, "acme", first_name="Jane", last_name="Roe")
    page = client.get("/welcome").text
    after = int(page.split("<strong>")[1].split(" of")[0])
    assert after == before + 2                        # company and contact, from the files
    step = page.split('id="company"')[1].split("</li>")[0]
    assert "&#10003;" in step


def test_the_two_steps_nobody_can_see_are_ticked_by_hand(client, app, repo):
    token = app.state.csrf_token
    r = client.post("/welcome/tick", data={"csrf_token": token, "key": "extension"})
    assert r.status_code == 303
    assert "extension" in app.state.config.get("welcome_done", []) or \
        '"extension"' in (repo / "config.toml").read_text()
    page = client.get("/welcome").text
    assert "Untick" in page.split('id="extension"')[1].split("</li>")[0]

    # a step that ticks itself cannot be ticked by hand
    r = client.post("/welcome/tick", data={"csrf_token": token, "key": "company"})
    assert "ticks%20itself" in r.headers["location"]


def test_the_walkthrough_explains_filters_and_bcc(client):
    page = client.get("/welcome").text
    assert "!text for everything that does not contain it" in page
    assert "matches each message to a company" in page
    assert "app password" in page


def test_the_tour_is_anchored_to_every_part_it_names(client):
    """A stop with no anchor would be skipped; this makes sure none are."""
    page = client.get("/").text
    for key in ("home", "pipeline", "calendar", "companies", "contacts", "messages",
                "capture", "search", "ask", "settings"):
        assert f'data-tour="{key}"' in page, key
    assert "/static/tour.js" in page
    assert client.get("/static/tour.js").status_code == 200


def test_bcc_settings_offer_the_common_providers(client):
    page = client.get("/settings").text
    assert "imap.gmail.com" in page and "imap.mail.me.com" in page
    assert "Microsoft has switched off password sign-in" in page
    assert "what does !text mean?" in client.get("/companies").text


def test_logo_and_favicon(client):
    page = client.get("/").text
    assert 'class="brand-mark"' in page
    assert 'rel="icon" type="image/svg+xml"' in page
    svg = client.get("/static/favicon.svg")
    assert svg.status_code == 200 and "prefers-color-scheme: dark" in svg.text
    png = client.get("/static/favicon.png")
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")

    ico = client.get("/favicon.ico", follow_redirects=False)
    assert ico.status_code == 301 and ico.headers["location"] == "/static/favicon.svg"


def test_a_write_leaves_unrelated_files_alone(client, repo):
    """One commit per write means the write's own files, not the whole folder."""
    (repo / "MESSAGING.md").write_text("notes I am still editing\n", encoding="utf-8")

    post_company(client, name="Acme")

    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              text=True).stdout

    committed = git("show", "--name-only", "--pretty=", "HEAD").split()
    assert "companies/acme/company.md" in committed
    assert "MESSAGING.md" not in committed
    assert git("ls-files", "MESSAGING.md") == ""  # still the user's to commit


def test_delete_is_recorded_without_sweeping_the_folder(client, repo):
    post_company(client, name="Acme")
    post_contact(client, "acme", first_name="Jane", last_name="Roe")
    (repo / "scratch.md").write_text("mine\n", encoding="utf-8")

    client.post("/companies/acme/contacts/jane-roe/delete")

    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              text=True).stdout

    assert git("ls-files", "companies/acme/contacts/jane-roe.md") == ""  # deletion recorded
    assert git("ls-files", "scratch.md") == ""                           # stray untouched


def test_board_shows_the_follow_up_radar(client, app):
    """An unanswered inbound message is the first thing the home page says."""
    post_company(client, name="Acme GmbH", stage="engaged")
    post_contact(client, "acme", first_name="Jane", last_name="Roe")
    post_interaction(client, "acme", channel="email", direction="in",
                     contact="jane-roe",
                     date=str(TODAY - timedelta(days=4)) + "T09:00",
                     body="Hi there,\n\nCan you send pricing?")

    page = client.get("/pipeline").text
    assert 'id="followups"' in page and "Follow up (1)" in page
    assert "radar-reply" in page and "wrote, no reply from you" in page
    assert "Can you send pricing?" in page
    assert page.index('id="followups"') < page.index('class="board"')


def test_board_radar_is_absent_when_nothing_is_waiting(client):
    post_company(client, name="Acme GmbH", stage="prospect")
    page = client.get("/pipeline").text
    assert 'id="followups"' not in page


def test_board_card_order_follows_pipeline(client):
    post_company(client, name="Later", stage="prospect",
                 next_step="x", next_step_due=str(TODAY + timedelta(days=5)))
    post_company(client, name="Sooner", stage="prospect",
                 next_step="x", next_step_due=str(TODAY))
    post_company(client, name="Undated", stage="prospect")

    page = client.get("/pipeline").text
    assert page.index(">Sooner<") < page.index(">Later<") < page.index(">Undated<")


def test_today_sections(client, app, repo):
    post_company(client, name="Due Now GmbH", stage="discovery",
                 next_step="Send deck", next_step_due=str(YESTERDAY))
    post_company(client, name="Future GmbH", stage="discovery",
                 next_step="Later", next_step_due=str(TODAY + timedelta(days=9)))
    post_company(client, name="Closed GmbH", stage="lost", lost_reason="no budget",
                 next_step="Ignore me", next_step_due=str(YESTERDAY))

    # Age one company past the silent threshold by rewriting created by hand.
    path = company_file(repo, "quiet")
    post_company(client, name="Quiet GmbH", stage="prospect")
    old = f"{TODAY - timedelta(days=40)}T09:00"
    path.write_text(path.read_text(encoding="utf-8").replace(
        f"created: {app.state.store.companies['quiet'].created:%Y-%m-%dT%H:%M}",
        f"created: {old}"), encoding="utf-8")
    client.post("/reload")

    r = client.get("/today")
    assert r.status_code == 303 and r.headers["location"] == "/calendar#top-priority"
    page = client.get("/calendar").text
    priority = page[page.index('id="top-priority"'):page.index('class="month-nav"')]
    future = page[page.index('id="future-tasks"'):page.index('id="silent"')]
    silent_part = page[page.index('id="silent"'):]
    assert "Due Now GmbH" in priority
    assert "Future GmbH" not in priority and "Future GmbH" in future
    assert "Closed GmbH" not in priority and "Closed GmbH" not in future
    assert "Quiet GmbH" in silent_part
    assert "Due Now GmbH" not in silent_part
    assert "/companies/due-now/interactions/new" in priority
    assert "Today" not in page.split("</nav>")[0]


def test_companies_table_and_search_by_contact_email(client):
    post_company(client, name="Acme GmbH", source="referral")
    post_company(client, name="Zeta AG", source="inbound")
    post_contact(client, "acme", first_name="Anna", last_name="Müller", email="Anna@Mueller.de")

    page = client.get("/companies").text
    assert "Acme GmbH" in page and "Zeta AG" in page and "referral" in page

    hit = client.get("/companies", params={"q": "anna@mueller.de"}).text
    assert "Acme GmbH" in hit
    assert "Zeta AG" not in hit


def test_reload_picks_up_a_hand_edit(client, repo):
    post_company(client, name="Acme GmbH")
    client.get("/pipeline")  # the index catches up with the app's own commit
    path = company_file(repo, "acme")
    path.write_text(path.read_text(encoding="utf-8")
                    .replace("stage: prospect", "stage: offer"), encoding="utf-8")

    before = client.get("/pipeline").text.split('id="col-offer"')[1].split("</section>")[0]
    assert "Acme GmbH" not in before
    resp = client.post("/reload", headers={"referer": "http://testserver/"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "http://testserver/"

    offer_column = client.get("/pipeline").text.split('id="col-offer"')[1]
    assert "Acme GmbH" in offer_column.split("</section>")[0]


# ---------------------------------------------------------- company create


def test_company_create_form_renders(client):
    page = client.get("/companies/new").text
    assert 'action="/companies"' in page
    assert 'name="next_step_due"' in page and 'type="date"' in page


def test_company_create_validation_keeps_values(client):
    resp = post_company(client, name="", next_step="Keep this", tags="a, b",
                        notes="some notes")
    assert resp.status_code == 400
    assert "name is required" in resp.text
    assert 'value="Keep this"' in resp.text
    assert 'value="a, b"' in resp.text
    assert "some notes" in resp.text


# ------------------------------------------------------------------ contacts


def test_contact_routes(client, repo):
    post_company(client, name="Acme GmbH")
    assert 'action="/companies/acme/contacts"' in \
        client.get("/companies/acme/contacts/new").text

    resp = post_contact(client, "acme", first_name="Jane", last_name="Doe", title="CTO",
                        email="Jane@Acme.de", role="champion")
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/companies/acme/contacts/jane-doe")

    page = client.get("/companies/acme/contacts/jane-doe").text
    assert "Jane Doe" in page and "jane@acme.de" in page
    assert 'action="/companies/acme/interactions"' in page  # quick-add form

    resp = client.post("/companies/acme/contacts/jane-doe",
                       data={**CONTACT_BLANK, "first_name": "Jane", "last_name": "Doe",
                             "title": "CEO", "email": "jane@acme.de"})
    assert resp.status_code == 303
    assert "title: CEO" in (repo / "companies/acme/contacts/jane-doe.md") \
        .read_text(encoding="utf-8")
    assert last_commit(repo) == "contact: acme/jane-doe updated"

    bad = client.post("/companies/acme/contacts/jane-doe",
                      data={**CONTACT_BLANK, "first_name": "", "last_name": ""})
    assert bad.status_code == 400
    assert "name is required" in bad.text


# -------------------------------------------------------------- interactions


def test_interaction_standalone_form_and_validation(client):
    post_company(client, name="Acme GmbH")
    post_contact(client, "acme", first_name="Jane", last_name="Doe")

    page = client.get("/companies/acme/interactions/new",
                      params={"contact": "jane-doe"}).text
    assert '<option value="jane-doe" selected>' in page
    assert 'type="datetime-local"' in page

    # Subject is optional; the timeline shows a placeholder instead.
    ok = post_interaction(client, "acme", channel="call", direction="in",
                          subject="", body="kept body")
    assert ok.status_code == 303
    assert "(no subject)" in client.get("/companies/acme").text

    bad = post_interaction(client, "acme", channel="", direction="in",
                           subject="", body="kept body")
    assert bad.status_code == 400
    assert "channel is required" in bad.text
    assert "kept body" in bad.text


def test_interaction_edit_renames_file_on_date_change(client, repo):
    post_company(client, name="Acme GmbH")
    post_interaction(client, "acme", channel="email", direction="out",
                     date="2026-09-01T08:00", subject="Intro", body="hello")
    old_id = "2026-09-01T0800-email-out-company"
    old_path = repo / "companies/acme/interactions" / f"{old_id}.md"
    assert old_path.exists()

    form = client.get(f"/companies/acme/interactions/{old_id}/edit").text
    assert 'value="2026-09-01T08:00"' in form

    resp = client.post(f"/companies/acme/interactions/{old_id}/edit",
                       data={**INTERACTION_BLANK, "channel": "email",
                             "direction": "out", "date": "2026-09-02T09:30",
                             "subject": "Intro", "body": "hello"})
    new_id = "2026-09-02T0930-email-out-company"
    assert resp.status_code == 303
    assert resp.headers["location"].endswith(f"#i-{new_id}")
    assert (repo / "companies/acme/interactions" / f"{new_id}.md").exists()
    assert not old_path.exists()
    assert last_commit(repo) == f"interaction: acme {new_id} updated"


def test_company_page_quick_add_preselects_latest_contact(client):
    post_company(client, name="Acme GmbH")
    post_contact(client, "acme", first_name="Jane", last_name="Doe")
    post_contact(client, "acme", first_name="John", last_name="Roe")
    post_interaction(client, "acme", channel="email", direction="out",
                     contact="john-roe", date="2026-09-02T09:00", subject="Hi")

    page = client.get("/companies/acme").text
    assert '<option value="john-roe" selected>' in page
    assert '<option value="out" checked>' not in page  # direction is a radio
    assert 'name="direction" value="out" checked' in page


def test_stage_dropdown_moves_company_and_redirects_to_board(client, repo):
    post_company(client, name="Acme GmbH")
    resp = client.post("/companies/acme/stage", data={"stage": "offer"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert last_commit(repo) == "company: acme stage prospect -> offer"


def test_unknown_company_is_404(client):
    assert client.get("/companies/nope").status_code == 404
    assert client.get("/companies/nope/contacts/new").status_code == 404


# ------------------------------------------------------- §10 acceptance flow


def test_acceptance_flow(client, app, repo):
    # 1. create the company
    resp = post_company(client, name="Müller & Söhne GmbH", source="referral",
                        stage="prospect")
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/companies/mueller-soehne?flash=")
    folder = repo / "companies" / "mueller-soehne"
    assert folder.is_dir()
    text = company_file(repo, "mueller-soehne").read_text(encoding="utf-8")
    assert f"stage_changed: {TODAY}" in text
    assert last_commit(repo) == "company: mueller-soehne created"

    # 2. + 3. contacts
    post_contact(client, "mueller-soehne", first_name="Anna", last_name="Müller", title="CEO",
                 email="Anna@Mueller.de")
    anna = folder / "contacts" / "anna-mueller.md"
    assert anna.exists()
    assert "email: anna@mueller.de" in anna.read_text(encoding="utf-8")
    post_contact(client, "mueller-soehne", first_name="Jonas", last_name="Berg")
    assert (folder / "contacts" / "jonas-berg.md").exists()

    # 4. three interactions
    post_interaction(client, "mueller-soehne", channel="linkedin", direction="out",
                     contact="anna-mueller", date="2026-09-08T09:12",
                     subject="Connection note")
    post_interaction(client, "mueller-soehne", channel="email", direction="in",
                     contact="anna-mueller", date="2026-09-11T16:40",
                     subject="Re: intro")
    resp = post_interaction(client, "mueller-soehne", channel="call",
                            direction="out", contact="", date="2026-09-14T10:30",
                            subject="Intro call", body="Spoke about DORA scope.")
    ids = [
        "2026-09-08T0912-linkedin-out-anna-mueller",
        "2026-09-11T1640-email-in-anna-mueller",
        "2026-09-14T1030-call-out-company",
    ]
    for iid in ids:
        assert (folder / "interactions" / f"{iid}.md").exists()
    assert resp.headers["location"].endswith(f"#i-{ids[2]}")

    page = client.get("/companies/mueller-soehne").text
    positions = [page.index(f'id="i-{iid}"') for iid in ids]
    assert positions == sorted(positions, reverse=True)  # newest first
    assert "Anna Müller" in page and ">company<" in page
    assert "Spoke about DORA scope." in page

    # 5. stage change from the board dropdown
    resp = client.post("/companies/mueller-soehne/stage", data={"stage": "discovery"})
    assert resp.status_code == 303 and resp.headers["location"] == "/"
    assert last_commit(repo) == "company: mueller-soehne stage engaged -> discovery"
    text = company_file(repo, "mueller-soehne").read_text(encoding="utf-8")
    assert "stage: discovery" in text and f"stage_changed: {TODAY}" in text

    # 6. overdue next step + calendar link
    resp = patch_company(client, app, "mueller-soehne",
                         next_step="Send proposal outline",
                         next_step_due=str(YESTERDAY))
    assert resp.status_code == 303
    today_page = client.get("/calendar").text
    overdue_part = today_page[today_page.index('id="top-priority"'):
                              today_page.index('class="month-nav"')]
    assert "Müller &amp; Söhne GmbH" in overdue_part or \
           "Müller & Söhne GmbH" in overdue_part
    pipeline = pipeline_text(repo)
    overdue_block = pipeline.split("## Overdue next steps")[1]
    assert "mueller-soehne" in overdue_block.split("##")[0]

    params = calendar_params(client.get("/companies/mueller-soehne").text)
    assert params["dates"] == f"{YESTERDAY:%Y%m%d}/{TODAY:%Y%m%d}"
    assert "Müller & Söhne GmbH" in params["text"]
    assert "Send proposal outline" in params["text"]

    # 7. lost via the board dropdown does not save
    before = company_file(repo, "mueller-soehne").read_bytes()
    resp = client.post("/companies/mueller-soehne/stage", data={"stage": "lost"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/companies/mueller-soehne?focus=lost_reason"
    assert company_file(repo, "mueller-soehne").read_bytes() == before

    focused = client.get("/companies/mueller-soehne",
                         params={"focus": "lost_reason"}).text
    assert 'id="lost_reason"' in focused
    assert "getElementById('lost_reason')" in focused

    # lost without a reason: validation error, still no file change
    resp = patch_company(client, app, "mueller-soehne", stage="lost")
    assert resp.status_code == 400
    assert "lost_reason is required" in resp.text
    assert company_file(repo, "mueller-soehne").read_bytes() == before

    # lost with a reason
    resp = patch_company(client, app, "mueller-soehne", stage="lost",
                         lost_reason="no budget")
    assert resp.status_code == 303
    board = client.get("/pipeline").text
    lost_block = board[board.index('id="closed-lost"'):]
    assert "Müller &amp; Söhne GmbH" in lost_block or \
           "Müller & Söhne GmbH" in lost_block
    assert "lost (1)" in board
    closed_block = pipeline_text(repo).split("## Closed last 90 days")[1]
    assert "no budget" in closed_block


def test_country_stays_on_the_record_but_leaves_the_company_header(client, app, repo):
    """The header lost its country line; the field itself did not go anywhere.

    Country still decides which language a draft is written in, so it has to
    survive. It lives in the edit form, the board and the table now.
    """
    post_company(client, name="Acme", country="NL")
    page = client.get("/companies/acme").text
    assert "country: NL" not in page and "Change country" not in page
    assert 'action="/companies/acme/country"' not in page

    assert 'name="country" value="NL" list="country-codes"' in page  # the edit form
    assert app.state.store.get("acme").country == "NL"
    assert "NL" in client.get("/pipeline").text.split('id="col-prospect"')[1].split("</section>")[0]
    assert "<th>country" in client.get("/companies").text


def test_board_stage_dropdown_offers_engaged(client, app):
    post_company(client, name="Acme")
    assert '<option value="engaged">' in client.get("/pipeline").text
    r = client.post("/companies/acme/stage", data={"stage": "engaged"})
    assert r.status_code == 303
    column = client.get("/pipeline").text.split('id="col-engaged"')[1].split("</section>")[0]
    assert "Acme" in column


def test_next_step_done_button_and_views(client, app, repo):
    post_company(client, name="Acme", next_step="Call Jane", next_step_due="2026-09-10")
    post_company(client, name="Beta", next_step="Send deck", next_step_due="2026-09-20")
    post_company(client, name="Gamma", next_step="Find intro")
    page = client.get("/companies/acme").text
    assert "Mark done" in page and 'action="/companies/acme/next-step"' in page
    assert "Acme" in client.get("/calendar").text.split('class="month-nav"')[0]

    r = client.post("/companies/acme/next-step", data={"status": "done"},
                    headers={"referer": "http://testserver/calendar?flash=x"})
    assert r.status_code == 303 and r.headers["location"].startswith("/calendar?flash=")
    assert app.state.store.get("acme").next_step_done
    assert last_commit(repo) == "company: acme next step done"
    assert "Acme" not in client.get("/calendar").text.split('class="month-nav"')[0]
    page = client.get("/companies/acme").text
    assert "Reopen" in page and "status-done" in page and "Add to Google Calendar" not in page
    assert "(done)" in client.get("/pipeline").text and "(done)" in client.get("/companies").text

    r = client.post("/companies/acme/next-step", data={"status": "open"})
    assert r.headers["location"] == "/companies/acme?flash=Next%20step%20reopened#tasks"
    assert last_commit(repo) == "company: acme next step reopened"


def test_the_next_step_lives_on_the_company_and_tasks_live_where_they_belong(
        client, app, repo):
    """One next step decides the deal; everything else is a list beside it."""
    post_company(client, name="Acme")
    post_contact(client, "acme", first_name="Jane", last_name="Roe")

    page = client.get("/companies/acme").text
    assert 'id="tasks"' in page and "No open task." in page
    assert 'action="/companies/acme/task"' in page          # the next step
    assert 'action="/companies/acme/tasks"' in page         # everything else

    contact_page = client.get("/companies/acme/contacts/jane-roe").text
    assert "Tasks for Jane Roe" in contact_page
    assert 'href="/companies/acme#tasks"' in contact_page   # points at the next step
    assert 'action="/companies/acme/task"' not in contact_page

    r = client.post("/companies/acme/task",
                    data={"next_step": "Call Jane", "next_step_due": "2026-09-20"},
                    headers={"referer": "http://testserver/companies/acme"})
    assert r.status_code == 303 and r.headers["location"].endswith("#tasks")
    assert last_commit(repo) == "company: acme next step set"
    company = app.state.store.get("acme")
    assert company.next_step == "Call Jane" and company.next_step_open


def test_a_company_keeps_a_list_of_tasks_beside_its_next_step(client, app, repo):
    post_company(client, name="Acme", next_step="Call Jane", next_step_due="2026-09-20")

    r = client.post("/companies/acme/tasks",
                    data={"text": "  send the  pricing page ", "due": "2026-09-24"},
                    headers={"referer": "http://testserver/companies/acme"})
    assert r.status_code == 303 and "Task%20added" in r.headers["location"]
    assert last_commit(repo) == "task: acme added"
    company = app.state.store.get("acme")
    assert [(t.text, str(t.due), t.done) for t in company.tasks] == \
        [("send the pricing page", "2026-09-24", False)]
    assert company.next_step == "Call Jane"          # untouched

    client.post("/companies/acme/tasks", data={"text": "check the audit"})
    assert len(app.state.store.get("acme").tasks) == 2   # a second one, not a replacement

    page = client.get("/companies/acme").text
    assert "send the pricing page" in page and "check the audit" in page

    r = client.post("/companies/acme/tasks/0/done",
                    data={"done": "1", "text": "send the pricing page"})
    assert r.status_code == 303 and last_commit(repo) == "task: acme done"
    assert app.state.store.get("acme").tasks[0].done is True

    r = client.post("/companies/acme/tasks/1/delete", data={"text": "check the audit"})
    assert r.status_code == 303 and last_commit(repo) == "task: acme deleted"
    assert [t.text for t in app.state.store.get("acme").tasks] == ["send the pricing page"]


def test_a_stale_page_cannot_tick_off_the_wrong_task(client, app):
    """Index alone would silently hit whatever moved into that slot."""
    post_company(client, name="Acme")
    client.post("/companies/acme/tasks", data={"text": "first"})
    client.post("/companies/acme/tasks", data={"text": "second"})

    r = client.post("/companies/acme/tasks/0/delete", data={"text": "second"})
    assert "has%20changed%20since" in r.headers["location"]
    assert [t.text for t in app.state.store.get("acme").tasks] == ["first", "second"]

    r = client.post("/companies/acme/tasks/9/done", data={"done": "1"})
    assert "no%20longer%20there" in r.headers["location"]


def test_a_contact_keeps_their_own_tasks(client, app, repo):
    post_company(client, name="Acme")
    post_contact(client, "acme", first_name="Jane", last_name="Roe")

    r = client.post("/companies/acme/tasks", data={"text": "send her the deck",
                                                   "contact": "jane-roe"})
    assert r.status_code == 303 and last_commit(repo) == "task: acme/jane-roe added"
    company = app.state.store.get("acme")
    assert company.tasks == []                                    # not on the company
    assert [t.text for t in company.contacts["jane-roe"].tasks] == ["send her the deck"]
    assert "send her the deck" in (
        repo / "companies/acme/contacts/jane-roe.md").read_text()

    # it shows on the contact's page and, grouped under their name, on the company's
    assert "send her the deck" in client.get("/companies/acme/contacts/jane-roe").text
    page = client.get("/companies/acme").text
    assert "send her the deck" in page and "Jane Roe" in page


def test_a_task_can_be_created_from_the_calendar(client, app, repo):
    post_company(client, name="Harbour Light Labs")
    post_contact(client, "harbour-light-labs", first_name="Ines", last_name="Vega")

    r = client.post("/calendar/task", data={"text": "send the pricing page",
                                            "company": "Harbour Light Labs",
                                            "contact": "", "due": "2026-09-24"})
    assert r.status_code == 303 and "Task%20created" in r.headers["location"]
    assert r.headers["location"].endswith("#task-list")
    assert last_commit(repo) == "task: harbour-light-labs added"

    r = client.post("/calendar/task", data={"text": "book the intro call",
                                            "company": "harbour-light-labs",
                                            "contact": "ines-vega", "due": ""})
    assert r.status_code == 303
    company = app.state.store.get("harbour-light-labs")
    assert [t.text for t in company.tasks] == ["send the pricing page"]
    assert [t.text for t in company.contacts["ines-vega"].tasks] == ["book the intro call"]

    page = client.get("/calendar").text
    assert "send the pricing page" in page.split('id="day-2026-09-24"')[1].split("</td>")[0]
    listing = page.split('id="task-list"')[1].split('id="future-tasks"')[0]
    assert "send the pricing page" in listing and "book the intro call" in listing
    assert "Ines Vega" in listing and "no date" in listing

    # a company nobody has is refused rather than invented
    r = client.post("/calendar/task", data={"text": "x", "company": "Nobody"})
    assert "No%20company%20called" in r.headers["location"]

    # ticking one off from the calendar works on the right record
    r = client.post("/companies/harbour-light-labs/tasks/0/done",
                    data={"contact": "ines-vega", "text": "book the intro call",
                          "done": "1"})
    assert r.status_code == 303
    assert app.state.store.get("harbour-light-labs").contacts["ines-vega"].tasks[0].done


def test_calendar_view_shows_open_tasks(frozen_client):
    # absolute dates below are read against the frozen clock, not the real day
    post_company(frozen_client, name="Acme", next_step="Call Jane", next_step_due="2026-09-10")
    post_company(frozen_client, name="Beta", next_step="Send deck", next_step_due="2026-09-20")
    post_company(frozen_client, name="Gamma", next_step="Find intro")
    post_company(frozen_client, name="Delta", next_step="Old", next_step_due="2026-08-03")
    post_company(frozen_client, name="Done Co", next_step="Finished", next_step_due="2026-09-22",
                 next_step_status="done")
    page = frozen_client.get("/calendar").text
    assert "September 2026" in page and 'id="day-2026-09-14"' in page
    cell = page.split('id="day-2026-09-10"')[1].split("</td>")[0]
    assert "Acme" in cell and 'class="task overdue"' in cell
    assert "Beta" in page.split('id="day-2026-09-20"')[1].split("</td>")[0]
    # a done next step is off the calendar; the company still appears in the
    # new-task picker, because a task on a won customer is an ordinary thing
    grid = page.split('id="month-grid"')[1].split("</table>")[0] \
        if 'id="month-grid"' in page else page.split("<h2 id=\"task-list\"")[0]
    assert "Done Co" not in grid and "Finished" not in page
    priority = page.split('id="top-priority"')[1].split('class="month-nav"')[0]
    assert priority.index("Delta") < priority.index("Acme")
    assert "Beta" not in priority and "Gamma" not in priority
    tasks = page.split('id="future-tasks"')[1].split('id="silent"')[0]
    assert tasks.index("Beta") < tasks.index("Gamma")
    assert "Acme" not in tasks and "Delta" not in tasks
    assert "no date" in tasks
    assert "Mark done" in tasks and "Mark done" in priority
    assert 'href="/calendar?month=2026-08"' in page and 'href="/calendar?month=2026-10"' in page

    august = frozen_client.get("/calendar?month=2026-08").text
    assert "August 2026" in august and "Delta" in august.split('id="day-2026-08-03"')[1].split("</td>")[0]
    assert frozen_client.get("/calendar?month=garbage").status_code == 200


def test_board_unused_columns_are_marked(client):
    post_company(client, name="Acme")
    page = client.get("/pipeline").text
    assert 'class="column" id="col-prospect"' in page
    assert 'class="column unused" id="col-offer"' in page


SHEET = (
    "name\thq_country\twebsite\tfounder_name\tfounder_title\tfit_score\n"
    "Fjellmark\tSweden\t\tAndreas Lindqvist\tFounder / CEO\t82\n"
    "\t\t\t\t\t\n"
    "Acme\tGermany\thttps://acme.de\tJane Doe\tCEO\t70\n"
)


def test_import_preview_and_apply(client, app, repo):
    # fit_score is one of the sheet's columns and one of this folder's own fields
    define_fields(client, repo,
                  '[[field]]\nkey = "fit_score"\nlabel = "fit"\ntype = "number"\n'
                  'show_in = ["detail", "companies"]\n')
    post_company(client, name="Acme")
    assert "Import companies" in client.get("/import").text

    preview = client.post("/import/preview", data={"text": SHEET})
    assert preview.status_code == 200
    assert "1 companies to create, 1 to update, 0 rows skipped, 2 contacts to create" in preview.text
    assert "fills country, fit_score, website" in preview.text
    assert "Andreas Lindqvist (Founder / CEO) &middot; create" in preview.text

    bad = client.post("/import/preview", data={"text": "foo\tbar\n1\t2\n"})
    assert bad.status_code == 400 and "needs a &#39;name&#39; column" in bad.text

    upload = client.post("/import/preview", files={"file": ("x.tsv", SHEET.encode(), "text/tab-separated-values")})
    assert upload.status_code == 200 and "Fjellmark" in upload.text

    r = client.post("/import", data={"text": SHEET})
    assert r.status_code == 303
    assert "1%20companies%20created%2C%201%20updated%2C%202%20contacts%20created" in r.headers["location"]
    assert last_commit(repo) == "import: 1 companies created, 1 updated, 2 contacts created"
    store = app.state.store
    assert store.get("fjellmark").country == "SE"
    assert store.get("acme").extra["fit_score"] == 70  # mapped to a custom field
    assert "andreas-lindqvist" in store.get("fjellmark").contacts
    assert store.get("acme").contacts["jane-doe"].title == "CEO"
    assert "fjellmark" in (repo / "PIPELINE.md").read_text()


def _preview_mapping(page: str) -> dict:
    """The Re-preview form's selected option per map_<i> select."""
    form = page.split('action="/import/preview"', 1)[1].split("</form>", 1)[0]
    chosen = {}
    for name, body in re.findall(r'<select name="(map_\d+)">(.*?)</select>', form, re.S):
        chosen[name] = re.search(r'<option value="([^"]+)" selected>', body).group(1)
    return chosen


CONTACT_SHEET = (
    "First Name,Last Name,Email,Company Name,Lifecycle Stage\n"
    "Jane,Doe,jane@acme.de,Acme,Lead\n"
    "Tom,Berg,tom@beta.io,,Customer\n"
)


def test_import_contacts_preview_repreview_and_apply(client, app, repo):
    post_company(client, name="Acme")
    page = client.get("/import").text
    assert "company_linkedin_url" in page and "person_linkedin_url" in page

    preview = client.post("/import/preview", data={"text": CONTACT_SHEET})
    assert preview.status_code == 200
    assert "2 contacts to create, 0 to update, 1 companies to create" in preview.text
    chosen = _preview_mapping(preview.text)
    assert chosen == {"map_0": "first_name", "map_1": "last_name", "map_2": "email",
                      "map_3": "company", "map_4": "notes"}
    assert '<td class="small">jane@acme.de</td>' in preview.text

    # Re-preview with Lifecycle Stage ignored and the company column ignored too.
    form = {"text": CONTACT_SHEET, "mode": "contacts", "prev_mode": "contacts",
            **chosen, "map_4": "ignore", "map_3": "ignore"}
    again = client.post("/import/preview", data=form)
    assert again.status_code == 200
    assert _preview_mapping(again.text)["map_4"] == "ignore"
    # Without the company column Acme comes from the email domain and matches by slug.
    assert "derived from acme.de" in again.text
    assert "1 contacts to create" not in again.text and "0 companies to create" not in again.text
    assert 'name="map_4" value="ignore"' in again.text  # Import now carries it

    # Switching mode drops the old mapping and starts from that mode's defaults.
    switched = client.post("/import/preview", data={**form, "mode": "companies"})
    assert switched.status_code == 200 and "Columns: companies mode" in switched.text
    assert _preview_mapping(switched.text)["map_3"] == "name"

    r = client.post("/import", data={"text": CONTACT_SHEET, "mode": "contacts",
                                     "map_0": "first_name", "map_1": "last_name",
                                     "map_2": "email", "map_3": "company", "map_4": "ignore"})
    assert r.status_code == 303 and "2%20contacts%20created" in r.headers["location"]
    assert last_commit(repo) == "import: 2 contacts created, 0 updated, 1 companies created"
    store = app.state.store
    assert store.get("acme").contacts["jane-doe"].email == "jane@acme.de"
    assert store.get("acme").contacts["jane-doe"].notes == ""
    assert "tom-berg" in store.get("beta").contacts

    bad = client.post("/import", data={"text": CONTACT_SHEET, "mode": "contacts",
                                       "map_0": "my_score"})
    assert bad.status_code == 400 and "unknown field" in bad.text


class StubEnricher:
    available, provider_name = True, "stub"

    def __init__(self, fields, missing=None, error=None):
        self.fields, self.missing, self.error = fields, missing, error

    def _proposal(self):
        from hermitcrm.enrich import Proposal
        if self.error:
            from hermitcrm.enrich import EnrichError
            raise EnrichError(self.error)
        return Proposal(fields=dict(self.fields),
                        missing=self.missing if self.missing is not None else list(self.fields),
                        sources=["https://example.com/about"], notes="ok")

    def propose_company(self, company, defs=None):
        return self._proposal()

    def propose_contact(self, company, contact, defs=None):
        return self._proposal()


def test_enrich_company_preview_and_apply(client, app, repo):
    post_company(client, name="Acme")
    app.state.enricher = StubEnricher({})
    page = client.get("/companies/acme").text
    assert 'action="/companies/acme/enrich"' in page and "via the stub CLI" in page

    app.state.enricher = StubEnricher({"website": "https://acme.de", "country": "DE"},
                                      missing=["website", "country", "ae_count"])
    page = client.post("/companies/acme/enrich")
    assert page.status_code == 200
    assert 'name="website" value="https://acme.de"' in page.text
    assert "not found: ae_count" in page.text and "https://example.com/about" in page.text

    r = client.post("/companies/acme/enrich/apply",
                    data={"apply": ["website"], "website": "https://acme.com", "country": "DE"})
    assert r.status_code == 303 and "Enriched%3A%20website" in r.headers["location"]
    company = app.state.store.get("acme")
    assert company.website == "https://acme.com" and company.country == ""
    assert last_commit(repo) == "ai: company acme enriched"

    app.state.enricher = StubEnricher({}, missing=["linkedin"])
    r = client.post("/companies/acme/enrich")
    assert r.status_code == 303 and "found%20nothing" in r.headers["location"]

    app.state.enricher = StubEnricher({}, error="'claude' not found")
    r = client.post("/companies/acme/enrich")
    assert r.status_code == 303 and "not%20found" in r.headers["location"]

    app.state.enricher = StubEnricher({}, missing=[])
    r = client.post("/companies/acme/enrich")
    assert "every%20field%20is%20set" in r.headers["location"]


def test_enrich_buttons_hidden_when_no_cli_is_available(client, app):
    from hermitcrm.enrich import Enricher
    post_company(client, name="Acme")
    post_contact(client, "acme", first_name="Jane", last_name="Doe")
    app.state.enricher = Enricher(which=lambda binary: None)
    assert not app.state.enricher.available
    assert "/companies/acme/enrich\"" not in client.get("/companies/acme").text
    assert "/contacts/jane-doe/enrich\"" not in \
        client.get("/companies/acme/contacts/jane-doe").text
    app.state.enricher = Enricher(provider="gemini", which=lambda b: f"/usr/bin/{b}")
    assert "via the gemini CLI" in client.get("/companies/acme").text


def test_enrich_contact_preview_and_apply(client, app, repo):
    post_company(client, name="Acme")
    post_contact(client, "acme", first_name="Jane", last_name="Doe")
    app.state.enricher = StubEnricher({})
    assert 'action="/companies/acme/contacts/jane-doe/enrich"' in \
        client.get("/companies/acme/contacts/jane-doe").text
    app.state.enricher = StubEnricher({"title": "CEO",
                                       "linkedin": "https://www.linkedin.com/in/jd"})
    page = client.post("/companies/acme/contacts/jane-doe/enrich")
    assert page.status_code == 200 and 'value="CEO"' in page.text
    r = client.post("/companies/acme/contacts/jane-doe/enrich/apply",
                    data={"apply": ["title", "linkedin"], "title": "CEO",
                          "linkedin": "https://www.linkedin.com/in/jd"})
    assert r.status_code == 303
    contact = app.state.store.get("acme").contacts["jane-doe"]
    assert contact.title == "CEO" and contact.linkedin == "https://www.linkedin.com/in/jd"
    assert last_commit(repo) == "ai: contact acme/jane-doe enriched"
    assert client.post("/companies/acme/contacts/nobody/enrich").status_code == 404


def test_contact_split_reads_legacy_name_key(client, app, repo):
    post_company(client, name="Acme")
    path = repo / "companies" / "acme" / "contacts" / "old-timer.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nname: Old van Timer\nslug: old-timer\n---\n")
    client.post("/reload")
    contact = app.state.store.get("acme").contacts["old-timer"]
    assert (contact.first_name, contact.last_name) == ("Old", "van Timer")
    page = client.get("/companies/acme/contacts/old-timer").text
    assert 'name="first_name" value="Old"' in page and 'name="last_name" value="van Timer"' in page
    client.post("/companies/acme/contacts/old-timer",
                data={**CONTACT_BLANK, "first_name": "Old", "last_name": "Timer"})
    text = path.read_text()
    assert text.startswith("---\nfirst_name: Old\nlast_name: Timer\nslug: old-timer\n")
    assert "\nname:" not in text


def test_disqualify_buttons_and_routes(client, app, repo):
    post_company(client, name="Acme")
    page = client.get("/companies/acme").text
    assert 'name="stage" value="disqualified"' in page and 'value="temp-disqualified"' in page
    r = client.post("/companies/acme/disqualify",
                    data={"stage": "temp-disqualified", "reason": "hiring freeze"})
    assert r.status_code == 303 and "Temp%20disqualified" in r.headers["location"]
    c = app.state.store.get("acme")
    assert c.stage == "temp-disqualified" and c.lost_reason == "hiring freeze"
    assert last_commit(repo) == "company: acme stage prospect -> temp-disqualified"
    page = client.get("/companies/acme").text
    assert "Requalify" in page and "(hiring freeze)" in page
    board = client.get("/pipeline").text
    assert 'id="closed-temp-disqualified"' in board and "hiring freeze" in board
    assert "Acme" not in board.split('id="col-prospect"')[1].split("</section>")[0]
    r = client.post("/companies/acme/disqualify", data={"stage": "prospect"})
    assert "Requalified" in r.headers["location"]
    assert app.state.store.get("acme").stage == "prospect"
    assert app.state.store.get("acme").lost_reason == ""
    r = client.post("/companies/acme/disqualify", data={"stage": "won"})
    assert "unknown%20stage" in r.headers["location"]


def test_parked_company_keeps_its_revisit_task_but_leaves_silent_list(client, app):
    post_company(client, name="Acme", stage="temp-disqualified", next_step="Revisit",
                 next_step_due=YESTERDAY.isoformat())
    today = client.get("/calendar").text
    assert "Acme" in today.split('class="month-nav"')[0]
    assert "Acme" not in today.split('id="silent"')[1]


def test_clickable_urls(client):
    post_company(client, name="Acme", website="https://acme.de", linkedin="https://www.linkedin.com/company/acme")
    post_contact(client, "acme", first_name="Jane", last_name="Doe", email="jane@acme.de",
                 linkedin="https://www.linkedin.com/in/jd")
    page = client.get("/companies/acme").text
    assert '<a href="https://acme.de" target="_blank" rel="noopener">acme.de</a>' in page
    assert '<a href="https://www.linkedin.com/company/acme" target="_blank" rel="noopener">linkedin</a>' in page
    assert '<a href="mailto:jane@acme.de">jane@acme.de</a>' in page
    assert '<a href="https://www.linkedin.com/in/jd" target="_blank" rel="noopener">profile</a>' in page
    table = client.get("/companies").text
    assert '<a href="https://acme.de" target="_blank" rel="noopener">web</a>' in table
    contact = client.get("/companies/acme/contacts/jane-doe").text
    assert 'href="mailto:jane@acme.de"' in contact


def test_contacts_tab_lists_search_and_filters(client):
    post_company(client, name="Acme")
    post_company(client, name="Beta")
    post_contact(client, "acme", first_name="Jane", last_name="Doe", title="CEO",
                 role="decision-maker", email="jane@acme.de")
    post_contact(client, "beta", first_name="Bob", last_name="King", title="CTO")
    post_interaction(client, "acme", contact="jane-doe", subject="x")
    page = client.get("/contacts").text
    assert "Contacts (2)" in page and "Jane Doe" in page and "Bob King" in page
    assert '<a href="/companies/acme">Acme</a>' in page
    assert 'href="mailto:jane@acme.de"' in page
    assert "Contacts (1)" in client.get("/contacts?q=bob").text
    assert "<th>role" not in page and "decision-maker" not in page  # role left the overview
    only_touched = client.get("/contacts?f_interaction_count=>0").text
    assert "Jane Doe" in only_touched and "Bob King" not in only_touched
    assert "Jane Doe" not in client.get("/contacts?f_title=!ceo").text
    assert 'name="f_title" form="contact-filters"' in page
    assert "Contacts" in client.get("/").text.split("</nav>")[0]


def test_companies_filters(client, repo):
    """The filter operators work on a user-defined field with no change to them."""
    define_fields(client, repo, MY_SCORE)
    post_company(client, name="Acme", stage="offer", country="DE", custom_my_score="8",
                 tags="x, y")
    post_company(client, name="Beta", stage="prospect", country="NL", custom_my_score="3")
    post_company(client, name="Gamma", stage="offer", country="SE")
    page = client.get("/companies").text
    assert '<tr class="filters">' in page and 'name="f_stage" form="company-filters"' in page
    r = client.get("/companies?f_stage=offer&f_stage=prospect").text
    assert "Companies (3)" in r
    r = client.get("/companies?f_stage=offer").text
    assert "Companies (2)" in r and "Beta" not in r
    r = client.get("/companies?f_stage=offer&f_my_score=>5").text
    assert "Companies (1)" in r and "Acme" in r
    r = client.get("/companies?f_my_score=-").text
    assert "Companies (1)" in r and "Gamma" in r
    r = client.get("/companies?f_tags=y&f_name=!beta").text
    assert "Companies (1)" in r and "Acme" in r
    r = client.get("/companies?q=acme&f_country=NL").text
    assert "Companies (0)" in r and "clear filters" in r
    assert 'value="NL" selected' in r


def test_board_filters_choose_columns_and_cards(client):
    post_company(client, name="Acme", stage="offer", country="DE")
    post_company(client, name="Beta", stage="prospect", country="NL")
    page = client.get("/pipeline?f_stage=offer").text
    assert 'id="col-offer"' in page and 'id="col-prospect"' not in page
    page = client.get("/pipeline?f_country=NL").text
    assert "Beta" in page and 'id="col-offer"' in page
    assert "Acme" not in page.split('id="col-offer"')[1].split("</section>")[0]
    assert 'name="f_name" form="board-filters"' in page


def test_merge_companies_pages(client, app, repo):
    define_fields(client, repo, MY_SCORE)
    post_company(client, name="Acme", website="https://acme.de")
    post_company(client, name="Acme Software", linkedin="https://l/acme",
                 custom_my_score="4")
    post_contact(client, "acme-software", first_name="Jane", last_name="Doe")
    page = client.get("/companies/acme").text
    assert 'action="/companies/acme/merge"' in page and 'value="acme-software"' in page
    r = client.get("/companies/acme/merge")
    assert r.status_code == 303 and "Pick%20a%20company" in r.headers["location"]
    form = client.get("/companies/acme/merge?drop=acme-software").text
    assert "Merge Acme Software into Acme" in form
    assert 'name="choice_linkedin" value="drop" checked' in form
    assert 'name="choice_website" value="keep" checked' in form
    assert 'name="choice_notes" value="both"' in form
    assert "1 contacts and 0 interactions" in form
    r = client.post("/companies/acme/merge",
                    data={"drop": "acme-software", "choice_my_score": "drop",
                          "choice_linkedin": "drop", "choice_website": "keep"})
    assert r.status_code == 303 and "Merged%20acme-software%20into%20acme" in r.headers["location"]
    c = app.state.store.get("acme")
    assert c.linkedin == "https://l/acme" and c.website == "https://acme.de"
    assert c.extra["my_score"] == 4  # a custom field is choosable like any other
    assert "jane-doe" in c.contacts and app.state.store.get("acme-software") is None
    assert last_commit(repo) == "company: acme-software merged into acme"
    assert not (repo / "companies" / "acme-software").exists()
    assert "acme-software" not in (repo / "PIPELINE.md").read_text()
    assert client.get("/companies/acme-software").status_code == 404
    r = client.get("/companies/acme/merge?drop=acme")
    assert r.status_code == 303 and "cannot%20merge" in r.headers["location"]


def test_merge_contacts_pages(client, app, repo):
    post_company(client, name="Acme")
    post_contact(client, "acme", first_name="Jane", last_name="Doe", email="jane@acme.de")
    post_contact(client, "acme", first_name="J.", last_name="Doe", title="CEO")
    post_interaction(client, "acme", contact="j-doe", subject="Hi")
    page = client.get("/companies/acme/contacts/jane-doe").text
    assert 'action="/companies/acme/contacts/jane-doe/merge"' in page and 'value="j-doe"' in page
    form = client.get("/companies/acme/contacts/jane-doe/merge?drop=j-doe").text
    assert "Merge J. Doe into Jane Doe" in form
    assert 'name="choice_title" value="drop" checked' in form
    r = client.post("/companies/acme/contacts/jane-doe/merge", data={"drop": "j-doe"})
    assert r.status_code == 303
    company = app.state.store.get("acme")
    assert list(company.contacts) == ["jane-doe"] and company.contacts["jane-doe"].title == "CEO"
    assert all(i.contact == "jane-doe" for i in company.interactions)
    assert last_commit(repo) == "contact: acme/j-doe merged into jane-doe"
    assert client.get("/companies/acme/contacts/j-doe").status_code == 404
    r = client.get("/companies/acme/contacts/jane-doe/merge?drop=ghost")
    assert r.status_code == 303 and "Pick%20another" in r.headers["location"]


# ------------------------------------------------ batch 5: parking, sorting


def test_temp_disqualify_until_date_and_automatic_requalify(client, app, repo):
    post_company(client, name="Acme")
    r = client.post("/companies/acme/disqualify",
                    data={"stage": "temp-disqualified", "reason": "freeze",
                          "requalify_on": str(TODAY + timedelta(days=30))})
    assert r.status_code == 303 and "until" in r.headers["location"]
    c = app.state.store.get("acme")
    assert c.stage == "temp-disqualified" and c.requalify_on == TODAY + timedelta(days=30)
    page = client.get("/companies/acme").text
    assert f"requalifies on {TODAY + timedelta(days=30)}" in page
    assert f"until {TODAY + timedelta(days=30)}" in client.get("/pipeline").text
    assert f"until {TODAY + timedelta(days=30)}" in pipeline_text(repo)
    # requalify manually: date cleared
    client.post("/companies/acme/disqualify", data={"stage": "prospect"})
    assert app.state.store.get("acme").requalify_on is None

    # the date arrives: the next page view puts the company back in prospect
    client.post("/companies/acme/disqualify",
                data={"stage": "temp-disqualified", "requalify_on": str(YESTERDAY)})
    assert app.state.store.get("acme").stage == "temp-disqualified"
    assert client.get("/health").status_code == 200
    c = app.state.store.get("acme")
    assert c.stage == "prospect" and c.requalify_on is None and c.lost_reason == ""
    assert last_commit(repo) == f"company: acme requalified (parked until {YESTERDAY})"


def test_companies_hide_and_show_temp_disqualified(client, app):
    post_company(client, name="Acme")
    post_company(client, name="Parked", stage="temp-disqualified")
    page = client.get("/companies").text
    assert "Acme" in page and "Parked" not in page
    assert "Show temp disqualified (1)" in page and 'href="/companies?parked=1"' in page
    shown = client.get("/companies?parked=1").text
    assert "Parked" in shown and "Hide temp disqualified" in shown
    assert 'href="/companies"' in shown
    # an explicit stage filter shows them without the toggle
    assert "Parked" in client.get("/companies?f_stage=temp-disqualified").text
    assert "Parked" in client.get("/companies?parked=1&f_name=park").text


def test_sorting_on_companies_contacts_and_board(client, repo):
    define_fields(client, repo, FIT_AND_FTE)
    post_company(client, name="Beta", custom_fit_score="70", custom_fte_estimate="~30")
    post_company(client, name="Alpha", custom_fit_score="90", custom_fte_estimate="12")
    post_company(client, name="Gamma")
    post_contact(client, "beta", first_name="Zoe", last_name="Z")
    post_contact(client, "alpha", first_name="Adam", last_name="A")

    page = client.get("/companies").text
    assert "<th>FTE" in page and "~30" in page
    assert 'href="/companies?sort=name&amp;dir=asc"' in page
    assert 'href="/companies?sort=fte_estimate&amp;dir=desc"' in page

    def order(html, *names):
        return [html.index(n) for n in names]

    asc = client.get("/companies?sort=name&dir=asc").text.split("<tr class=\"filters\">")[1]
    assert order(asc, "Alpha", "Beta", "Gamma") == sorted(order(asc, "Alpha", "Beta", "Gamma"))
    full = client.get("/companies?sort=name&dir=desc").text
    desc = full.split("<tr class=\"filters\">")[1]
    assert desc.index("Gamma") < desc.index("Beta") < desc.index("Alpha")
    assert 'class="on"' in full and "clear filters and sorting" in full
    by_fit = client.get("/companies?sort=fit_score&dir=desc").text.split("<tr class=\"filters\">")[1]
    assert by_fit.index("Alpha") < by_fit.index("Beta") < by_fit.index("Gamma")  # empty last
    by_fte = client.get("/companies?sort=fte_estimate&dir=asc").text.split("<tr class=\"filters\">")[1]
    assert by_fte.index("Alpha") < by_fte.index("Beta")
    # sorting survives a filter submit (hidden inputs) and combines with filters
    combined = client.get("/companies?f_name=a&sort=name&dir=desc").text
    assert 'name="sort" value="name"' in combined and 'name="dir" value="desc"' in combined
    rows = combined.split("<tr class=\"filters\">")[1]
    assert rows.index("Gamma") < rows.index("Beta") < rows.index("Alpha")

    contacts = client.get("/contacts?sort=name&dir=desc").text.split("<tr class=\"filters\">")[1]
    assert contacts.index("Zoe") < contacts.index("Adam")
    board = client.get("/pipeline?sort=name&dir=desc").text.split('id="col-prospect"')[1]
    assert board.index("Gamma") < board.index("Beta") < board.index("Alpha")
    board = client.get("/pipeline?sort=name&dir=asc").text.split('id="col-prospect"')[1]
    assert board.index("Alpha") < board.index("Beta") < board.index("Gamma")


def test_filter_help_tooltip_sits_above_each_table(client):
    for path in ("/pipeline", "/companies", "/contacts", "/messages"):
        page = client.get(path).text
        head = (page.split('<div class="board">')[0] if path == "/pipeline"
                else page.split('<table class="filterable')[0])
        assert 'class="help"' in head and "does not contain" in head and "Z to A" in head
        assert 'title="contains: text' not in page  # the long per-input title is gone


# ----------------------------------------------- batch 5: fetch, messages


def test_fetch_from_url_proposes_and_applies_without_ai(client, app, repo):
    post_company(client, name="Acme", website="https://acme.de")
    page = client.get("/companies/acme").text
    assert 'action="/companies/acme/fetch"' in page and 'value="https://acme.de"' in page

    html = ('<html><head><title>Acme</title><meta name="description" content="Acme sells X.">'
            '</head><body><a href="https://www.linkedin.com/company/acme">li</a></body></html>')
    seen = []

    def fetcher(url):
        seen.append(url)
        return html

    app.state.fetcher = fetcher
    r = client.post("/companies/acme/fetch", data={"url": ""})
    assert r.status_code == 200 and seen == ["https://acme.de"]
    assert 'name="product_oneliner" value="Acme sells X."' in r.text
    assert 'name="linkedin" value="https://www.linkedin.com/company/acme"' in r.text
    assert 'name="country" value="DE"' in r.text
    assert 'action="/companies/acme/enrich/apply"' in r.text
    r = client.post("/companies/acme/enrich/apply",
                    data={"apply": ["product_oneliner", "country"],
                          "product_oneliner": "Acme sells X.", "country": "DE",
                          "linkedin": "x"})
    assert r.status_code == 303
    c = app.state.store.get("acme")
    assert c.product_oneliner == "Acme sells X." and c.country == "DE" and c.linkedin == ""

    def refuse(url):
        from hermitcrm.scrape import ScrapeError
        raise ScrapeError("LinkedIn refused the anonymous request (HTTP 999)")

    app.state.fetcher = refuse
    r = client.post("/companies/acme/fetch", data={"url": "https://www.linkedin.com/company/acme"})
    assert r.status_code == 303 and "LinkedIn%20refused" in r.headers["location"]
    post_company(client, name="Blank")
    r = client.post("/companies/blank/fetch", data={"url": ""})
    assert "Give%20a%20website" in r.headers["location"]


def test_messages_tab_lists_results_and_marking(client, app, repo):
    post_company(client, name="Acme", country="DE")
    post_contact(client, "acme", first_name="Jane", last_name="Doe")
    old = f"{TODAY - timedelta(days=20)}T09:00"
    fresh = f"{TODAY - timedelta(days=2)}T09:00"
    post_interaction(client, "acme", contact="jane-doe", channel="linkedin",
                     date=old, body="Hi Jane, fractional?")
    post_interaction(client, "acme", contact="", channel="linkedin", date=fresh,
                     body="Hi Henrik, growing nicely.")
    post_interaction(client, "acme", contact="jane-doe", channel="linkedin", date=fresh,
                     body="Hi Jane, fractional?")
    post_interaction(client, "acme", contact="jane-doe", channel="email", direction="in",
                     date=f"{TODAY}T10:00", body="Sure, let's talk")
    post_interaction(client, "acme", channel="call", direction="out", date=fresh,
                     subject="no body")  # not a message

    page = client.get("/messages").text
    assert "Messages (3)" in page and "no body" not in page
    assert "Messages" in page.split("</nav>")[0]
    assert page.count("Hi Jane, fractional?") >= 2 and "Hi Henrik" in page
    rows = page.split("<tr class=\"filters\">")[1]
    # newest first; Jane's messages got a reply -> successful; Henrik's is fresh -> unknown
    assert rows.count('class="outcome-successful"') == 2
    assert rows.count('class="outcome-unknown"') == 1
    assert "<td>2</td>" in rows  # the same text was used twice
    assert "2 successful" in page and "1 unknown" in page

    ids = re.findall(r'action="/companies/acme/interactions/([^/"]+)/outcome"', page)
    henrik = next(i for i in ids if "company" in i)
    r = client.post(f"/companies/acme/interactions/{henrik}/outcome",
                    data={"outcome": "unsuccessful"},
                    headers={"referer": "http://testserver/messages?f_channel=linkedin"})
    assert r.status_code == 303 and r.headers["location"].startswith("/messages?flash=")
    assert last_commit(repo) == f"interaction: acme {henrik} outcome unsuccessful"
    page = client.get("/messages").text
    assert '<td class="outcome-unsuccessful">unsuccessful</td>' in page
    assert "Messages (1)" in client.get("/messages?f_status=unsuccessful").text
    assert "Messages (2)" in client.get("/messages?q=jane").text
    assert "Messages (1)" in client.get("/messages?f_contact=company").text

    # age: a message with no reply and no verdict flips to unsuccessful after 14 days
    post_company(client, name="Beta")
    post_interaction(client, "beta", channel="email", date=old, body="Hello Beta")
    beta = client.get("/messages?f_company_name=beta").text
    assert "outcome-unsuccessful" in beta and "(auto)" in beta


def test_drafts_on_contact_and_company_pages(client, app):
    post_company(client, name="Brightnook", country="DE", fte_estimate="12", ae_count="2",
                 website="https://brightnook.de")
    post_contact(client, "brightnook", first_name="Johannes", last_name="W")
    page = client.get("/companies/brightnook/contacts/johannes-w").text
    assert 'id="drafts"' in page and "(German)" in page
    assert page.count("Hallo Johannes,") == 3
    assert "linkedin.com/company/brightnook/insights/" in page
    assert "[Was dir auf brightnook.de aufgefallen ist" in page
    tuned = client.get("/companies/brightnook/contacts/johannes-w?signal=hiring"
                       "&observation=Tolle+Demo.").text
    assert "dass Brightnook [die Rolle] sucht" in tuned and "Tolle Demo." in tuned
    assert '<option value="hiring" selected>' in tuned
    assert "log as sent" in tuned
    link = re.search(r'href="(/companies/brightnook/interactions/new\?contact=johannes-w'
                     r'&channel=linkedin&body=[^"]+)"', tuned).group(1)
    form = client.get(htmllib.unescape(link)).text
    assert 'value="linkedin" checked' in form and "Hallo Johannes," in form
    assert '<option value="johannes-w" selected>' in form

    company_page = client.get("/companies/brightnook").text
    assert 'id="drafts"' in company_page and "for Johannes" in company_page
    assert 'href="/companies/brightnook/contacts/johannes-w#drafts"' in company_page
    post_company(client, name="Lonely", country="SE")
    lonely = client.get("/companies/lonely").text
    assert "Hi [first name]," in lonely and "(English)" in lonely


def test_contact_enrich_shows_sources_when_nothing_verified(client, app):
    post_company(client, name="Acme")
    post_contact(client, "acme", first_name="Jane", last_name="Doe")
    app.state.enricher = StubEnricher({}, missing=["title", "linkedin"])
    page = client.post("/companies/acme/contacts/jane-doe/enrich")
    assert page.status_code == 200
    assert "Nothing verified to apply" in page.text
    assert 'href="https://example.com/about"' in page.text
    assert "Apply selected" not in page.text


def test_log_interaction_defaults_to_linkedin_out(client, app):
    post_company(client, name="Acme")
    page = client.get("/companies/acme/interactions/new").text
    assert 'name="channel" value="linkedin" checked' in page
    assert 'name="channel" value="email" checked' not in page
    assert 'name="direction" value="out" checked' in page
    assert 'value="email" checked' in client.get(
        "/companies/acme/interactions/new?channel=email").text


def test_logging_an_interaction_makes_a_prospect_engaged(client, app, repo):
    post_company(client, name="Acme")
    post_interaction(client, "acme", channel="linkedin", direction="out",
                     date="2026-09-10T09:00")
    assert app.state.store.get("acme").stage == "engaged"
    assert last_commit(repo) == ("interaction: acme linkedin out company 2026-09-10T09:00; "
                                 "stage prospect -> engaged")
    assert "stage: engaged" in company_file(repo, "acme").read_text(encoding="utf-8")


def test_delete_contact_route(client, app, repo):
    post_company(client, name="Acme")
    post_contact(client, "acme", first_name="Jane", last_name="Doe")
    post_interaction(client, "acme", channel="linkedin", direction="out",
                     contact="jane-doe", date="2026-09-10T09:00")
    page = client.get("/companies/acme/contacts/jane-doe").text
    assert 'action="/companies/acme/contacts/jane-doe/delete"' in page
    assert "1 interaction(s) stay on Acme" in page
    r = client.post("/companies/acme/contacts/jane-doe/delete")
    assert r.status_code == 303 and r.headers["location"].startswith("/companies/acme?flash=")
    assert "jane-doe" not in app.state.store.get("acme").contacts
    assert last_commit(repo) == "contact: acme/jane-doe deleted (1 interaction(s) kept without a contact)"
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True,
                          text=True).stdout.strip() == ""
    assert client.post("/companies/acme/contacts/jane-doe/delete").status_code == 404


def test_contact_page_sections_in_order_and_nav_marks_contacts(client, app):
    post_company(client, name="Acme")
    post_contact(client, "acme", first_name="Jane", last_name="Doe")
    page = client.get("/companies/acme/contacts/jane-doe").text
    ids = ['id="details"', 'id="timeline"', 'id="drafts"', 'id="quick-add"', 'id="delete"']
    positions = [page.index(i) for i in ids]
    assert positions == sorted(positions)
    active = re.findall(r'<a href="([^"]+)"[^>]*class="active"', page)
    assert active == ["/contacts"]
    assert re.findall(r'<a href="([^"]+)"[^>]*class="active"', client.get("/companies/acme").text) == ["/companies"]
    assert '<option value="declining">headcount decline</option>' in page


PROFILE_PAGE = (
    "<html><head><title>Ines Vega - Harbour Light Labs | LinkedIn</title>"
    '<meta property="og:description" content="Execution, not leads &middot; '
    'Experience: Harbour Light Labs &middot; Location: Rotterdam &middot; '
    '500+ connections on LinkedIn.">'
    "</head><body></body></html>")


def test_capturing_a_profile_opens_the_contact_form(client, app):
    """Reported: a LinkedIn profile URL opened a form to create a company."""
    app.state.fetcher = lambda url: PROFILE_PAGE
    page = client.get("/extension/new",
                      params={"url": "https://www.linkedin.com/in/ines-vega/"}).text
    assert "<h1>New contact</h1>" in page
    assert 'name="name" value="Ines Vega"' in page
    assert 'name="company" value="Harbour Light Labs"' in page
    assert 'value="Execution, not leads"' in page          # the headline, as the title
    assert "connections on LinkedIn" not in page
    assert "No company called <strong>Harbour Light Labs</strong> yet" in page
    # and it creates both when submitted
    r = client.post("/contacts", data={"name": "Ines Vega", "email": "", "title": "X",
                                       "linkedin": "https://www.linkedin.com/in/ines-vega/",
                                       "company": "Harbour Light Labs", "website": ""})
    assert r.status_code == 303
    company = app.state.store.get("harbour-light-labs")
    assert "ines-vega" in company.contacts


def test_capturing_a_profile_whose_company_you_have_says_so(client, app):
    app.state.fetcher = lambda url: PROFILE_PAGE
    post_company(client, name="Harbour Light Labs")
    page = client.get("/extension/new",
                      params={"url": "https://www.linkedin.com/in/ines-vega/"}).text
    assert "is already in the CRM and the contact will go there" in page


def test_capturing_a_profile_you_already_saved_goes_to_the_contact(client, app):
    app.state.fetcher = lambda url: PROFILE_PAGE
    post_company(client, name="Harbour Light Labs")
    client.post("/companies/harbour-light-labs/contacts",
                data={"first_name": "Ines", "last_name": "Vega", "title": "",
                      "linkedin": "https://www.linkedin.com/in/ines-vega/",
                      "email": "", "phone": "", "role": "", "notes": ""})
    r = client.get("/extension/new",
                   params={"url": "https://www.linkedin.com/in/ines-vega/"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith(
        "/companies/harbour-light-labs/contacts/ines-vega")


def test_a_profile_linkedin_refuses_still_opens_the_contact_form(client, app):
    """HTTP 999 on a profile used to end on the extension page with an error."""
    def refuse(url):
        from hermitcrm.scrape import ScrapeError
        raise ScrapeError("LinkedIn refused the anonymous request (HTTP 999)")

    app.state.fetcher = refuse
    r = client.get("/extension/new",
                   params={"url": "https://www.linkedin.com/in/ines-vega-8a1b2c3d/"})
    assert r.status_code == 200
    assert "<h1>New contact</h1>" in r.text
    assert 'name="name" value="Ines Vega"' in r.text
    assert 'name="linkedin" value="https://www.linkedin.com/in/ines-vega-8a1b2c3d"' in r.text
    note = re.search(r'<div class="flash capture-note">(.*?)</div>', r.text, re.S).group(1)
    assert "HTTP 999" in note                   # why the fields are thin
    assert 'href="/extension"' in note          # and where the bookmarklet that reads it is
    assert app.state.store.companies == {}


CONTACT_FORM = {"name": "Ines Vega", "email": "", "title": "",
                "linkedin": "https://www.linkedin.com/in/ines-vega", "website": ""}


def test_a_company_made_from_a_profile_keeps_its_linkedin_page(client, app):
    r = client.post("/contacts", data={
        **CONTACT_FORM, "company": "Harbour Light Labs",
        "company_linkedin": "https://www.linkedin.com/company/1234567/"})
    assert r.status_code == 303
    company = app.state.store.get("harbour-light-labs")
    assert company.linkedin == "https://www.linkedin.com/company/1234567"


def test_a_profile_never_changes_the_linkedin_of_a_company_you_have(client, app):
    post_company(client, name="Harbour Light Labs",
                 linkedin="https://www.linkedin.com/company/harbour-light-labs")
    client.post("/contacts", data={
        **CONTACT_FORM, "company": "Harbour Light Labs",
        "company_linkedin": "https://www.linkedin.com/company/1234567/"})
    company = app.state.store.get("harbour-light-labs")
    assert company.linkedin == "https://www.linkedin.com/company/harbour-light-labs"
    assert "ines-vega" in company.contacts


@pytest.mark.parametrize("junk", ["javascript:alert(1)",
                                  "https://evil.example.com/company/acme",
                                  "https://www.linkedin.com/in/someone-else"])
def test_only_a_linkedin_company_page_is_taken_for_a_new_company(client, app, junk):
    client.post("/contacts", data={**CONTACT_FORM, "company": "Harbour Light Labs",
                                   "company_linkedin": junk})
    assert app.state.store.get("harbour-light-labs").linkedin == ""


def test_the_company_linkedin_survives_a_form_that_comes_back(client, app):
    r = client.post("/contacts", data={
        **CONTACT_FORM, "name": "", "company": "Harbour Light Labs",
        "company_linkedin": "https://www.linkedin.com/company/1234567"})
    assert r.status_code == 400
    assert 'name="company_linkedin" value="https://www.linkedin.com/company/1234567"' in r.text


def never_fetch(url):
    raise AssertionError(f"asked LinkedIn for {url}")


BOOKMARKLET_READ = {
    "url": "https://www.linkedin.com/in/ines-vega/overlay/contact-info/", "v": "2",
    "h1": "Ines Vega",
    "co": "https://www.linkedin.com/company/1234567/|Harbour Light Labs logo",
    "mail": "ines@harbourlight.example"}


def test_what_the_bookmarklet_read_opens_the_contact_form_without_a_fetch(client, app):
    app.state.fetcher = never_fetch
    r = client.get("/extension/new", params=BOOKMARKLET_READ)
    assert r.status_code == 200
    assert "<h1>New contact</h1>" in r.text
    assert 'name="name" value="Ines Vega"' in r.text
    assert 'name="email" value="ines@harbourlight.example"' in r.text
    assert 'name="linkedin" value="https://www.linkedin.com/in/ines-vega"' in r.text
    assert 'name="company" value="Harbour Light Labs"' in r.text
    assert 'name="company_linkedin" value="https://www.linkedin.com/company/1234567"' in r.text
    assert app.state.store.companies == {}


def test_what_the_bookmarklet_read_saves_a_contact_and_its_company(client, app):
    """The whole round trip, as a click on Create contact would send it."""
    app.state.fetcher = never_fetch
    page = client.get("/extension/new", params=BOOKMARKLET_READ).text
    form = dict(re.findall(r'<input[^>]*name="([a-z_]+)"[^>]*value="([^"]*)"', page))
    r = client.post("/contacts", data={k: htmllib.unescape(v) for k, v in form.items()})
    assert r.status_code == 303
    company = app.state.store.get("harbour-light-labs")
    assert company.linkedin == "https://www.linkedin.com/company/1234567"
    contact = company.contacts["ines-vega"]
    assert contact.email == "ines@harbourlight.example"
    assert contact.linkedin == "https://www.linkedin.com/in/ines-vega"


def test_the_bookmarklet_on_someone_you_have_goes_to_them(client, app):
    app.state.fetcher = never_fetch
    post_company(client, name="Harbour Light Labs")
    post_contact(client, "harbour-light-labs", first_name="Ines", last_name="Vega",
                 linkedin="https://www.linkedin.com/in/ines-vega")
    r = client.get("/extension/new", params=BOOKMARKLET_READ, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/companies/harbour-light-labs/contacts/ines-vega")


def test_a_bookmarklet_that_read_nothing_says_to_try_again(client, app):
    app.state.fetcher = never_fetch
    r = client.get("/extension/new", params={
        "url": "https://www.linkedin.com/in/ines-vega-8a1b2c3d/", "v": "2", "h1": ""})
    assert r.status_code == 200
    assert 'name="name" value="Ines Vega"' in r.text
    note = re.search(r'<div class="flash capture-note">(.*?)</div>', r.text, re.S).group(1)
    assert "again" in note and "loaded" in note


def test_the_bookmarklet_is_one_line_a_bookmark_can_hold(client):
    """A bookmark's javascript: address is percent-decoded and loses its line
    breaks before it runs: a stray % or a newline would break the code."""
    page = client.get("/extension").text
    code = htmllib.unescape(re.search(r'class="bookmarklet" href="([^"]+)"', page).group(1))
    assert code.startswith("javascript:")
    assert "'http://testserver'" in code and "'/extension/new?'" in code
    assert "%" not in code and "\n" not in code


def test_the_old_capture_paths_still_work(client, app):
    """A bookmarklet already sitting in someone's bookmarks bar points here."""
    r = client.get("/capture", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/extension"
    r = client.get("/capture/new", params={"url": "https://northwind.example.com"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/extension/new?url=https%3A%2F%2Fnorthwind.example.com"
    r = client.get("/capture/new", follow_redirects=False)
    assert r.headers["location"] == "/extension"


def test_the_nav_and_the_ask_button_carry_the_new_names(client):
    page = client.get("/").text
    assert ">Extension<" in page and ">Capture<" not in page
    assert "Ask the Hermit" in page and ">Ask Hermit" not in page


def test_the_company_header_lost_four_of_its_six_rows(client, app):
    """The country line is gone and the two disqualify panels became one menu."""
    post_company(client, name="Acme", country="NL", stage="prospect")
    page = client.get("/companies/acme").text
    assert "country-line" not in page and "stage-line" not in page
    assert page.count("record-meta") == 1 and page.count("record-actions") == 1
    # one summary to open, not two always-open panels
    assert page.count('summary class="button">Disqualify') == 1
    assert "Temp disqualify" in page  # still there, inside the menu
    assert 'action="/companies/acme/fetch"' in page  # the actions survived the move


def test_a_custom_field_goes_all_the_way_through_the_app(client, app, repo):
    """Define it, fill it in the form, read it back off the page and the file."""
    define_fields(client, repo,
                  '[[field]]\nkey = "segment"\nlabel = "segment"\ntype = "select"\n'
                  'options = ["smb", "enterprise"]\nshow_in = ["detail", "companies"]\n')
    page = client.get("/companies/new").text
    assert 'name="custom_segment"' in page and '<option value="enterprise"' in page

    post_company(client, name="Acme", custom_segment="enterprise")
    company = app.state.store.get("acme")
    assert company.extra["segment"] == "enterprise"
    assert "segment: enterprise" in (repo / "companies/acme/company.md").read_text()

    detail = client.get("/companies/acme").text
    assert "segment enterprise" in detail                       # the header line
    assert 'value="enterprise" selected' in detail              # the edit form
    assert "<th>segment" in client.get("/companies").text

    # a value outside the options is refused, and nothing is written
    values = company_values(app.state.store.companies["acme"])
    values["custom_segment"] = "galactic"
    r = client.post("/companies/acme", data=values)
    assert r.status_code == 400 and "must be one of smb, enterprise" in r.text
    assert app.state.store.get("acme").extra["segment"] == "enterprise"

    # clearing it removes the key rather than storing an empty one
    values["custom_segment"] = ""
    assert client.post("/companies/acme", data=values).status_code == 303
    assert "segment" not in app.state.store.get("acme").extra
    assert "segment:" not in (repo / "companies/acme/company.md").read_text()


def test_a_field_on_a_contact_and_on_an_interaction(client, app, repo):
    define_fields(client, repo,
                  '[[field]]\nkey = "seniority"\ntype = "text"\napplies_to = "contact"\n'
                  'show_in = ["detail", "contacts"]\n\n'
                  '[[field]]\nkey = "sentiment"\ntype = "text"\n'
                  'applies_to = "interaction"\nshow_in = ["detail", "messages"]\n')
    post_company(client, name="Acme")
    r = client.post("/companies/acme/contacts",
                    data={"first_name": "Ines", "last_name": "Vega", "title": "",
                          "linkedin": "", "email": "", "phone": "", "role": "",
                          "notes": "", "custom_seniority": "VP"})
    assert r.status_code == 303
    assert app.state.store.get("acme").contacts["ines-vega"].extra["seniority"] == "VP"
    assert "<th>seniority" in client.get("/contacts").text

    r = client.post("/companies/acme/interactions",
                    data={"channel": "email", "direction": "out", "contact": "ines-vega",
                          "date": "2026-09-18T10:00", "subject": "Hello",
                          "outcome": "", "body": "The body is the record.",
                          "custom_sentiment": "warm"})
    assert r.status_code == 303
    it = app.state.store.get("acme").interactions[0]
    assert it.extra["sentiment"] == "warm"
    assert it.body == "The body is the record.\n"   # untouched by the custom field


# ----------------------------------------------------------------- extension


CAPTURE_PAGE = (
    '<html><head><title>Northwind Robotics | Warehouse automation</title>'
    '<meta property="og:site_name" content="Northwind Robotics">'
    '<meta name="description" content="Robots that pick and pack.">'
    '</head><body><a href="https://www.linkedin.com/company/northwind-robotics">li</a>'
    '</body></html>')


def test_extension_page_hands_out_a_bookmarklet_for_this_address(client):
    page = htmllib.unescape(client.get("/extension").text)
    # built from the request, so a serve --host session hands out a working one
    assert "var B = 'http://testserver'" in page


def test_extension_new_opens_a_prefilled_company_form(client, app):
    app.state.fetcher = lambda url: CAPTURE_PAGE

    r = client.get("/extension/new", params={"url": "northwind.example.com"})
    assert r.status_code == 200
    assert 'name="name" value="Northwind Robotics"' in r.text
    assert 'name="website" value="https://northwind.example.com"' in r.text
    assert 'name="linkedin" value="https://www.linkedin.com/company/northwind-robotics"' in r.text
    assert 'action="/companies"' in r.text
    assert "Read from" in r.text
    assert app.state.store.companies == {}  # a read, not a write


def test_extension_of_a_company_you_already_have_goes_to_it(client, app):
    post_company(client, name="Northwind Robotics", website="northwind.example.com")
    app.state.fetcher = lambda url: CAPTURE_PAGE

    r = client.get("/extension/new", params={"url": "https://northwind.example.com/pricing"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/companies/northwind-robotics")
    assert "already%20in%20the%20CRM" in r.headers["location"]


def test_extension_says_why_a_page_could_not_be_read(client, app):
    def refuse(url):
        from hermitcrm.scrape import ScrapeError
        raise ScrapeError("LinkedIn refused the anonymous request (HTTP 999)")

    app.state.fetcher = refuse
    r = client.get("/extension/new", params={"url": "https://www.linkedin.com/company/x"},
                   follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/extension?flash=")
    assert "LinkedIn%20refused" in r.headers["location"]


def test_extension_new_without_a_url_goes_back_to_the_capture_page(client):
    r = client.get("/extension/new", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/extension"


# ------------------------------------------------------ theme.css and the CSP


def test_stylesheets_load_tokens_then_style_then_theme(client, repo):
    page = client.get("/").text
    links = re.findall(r'<link rel="stylesheet" href="([^"?]+)', page)
    assert links == ["/static/tokens.css", "/static/style.css"]
    (repo / "theme.css").write_text(":root { --accent: red; }")
    links = re.findall(r'<link rel="stylesheet" href="([^"?]+)', client.get("/").text)
    assert links == ["/static/tokens.css", "/static/style.css", "/theme.css"]


def test_static_urls_change_when_the_files_do(client, tmp_path):
    """An update within one version number (a rebuilt 0.3.0) must not leave the old
    stylesheet in the browser's cache, so ?v= is a hash of the files, not the version."""
    page = client.get("/").text
    assert f'href="/static/style.css?v={asset_version()}"' in page
    folder = tmp_path / "static"
    folder.mkdir()
    (folder / "style.css").write_text("a {}")
    before = asset_version(folder)
    (folder / "style.css").write_text("a { color: red; }")
    assert asset_version(folder) != before


def test_theme_css_served_as_written(client, repo):
    assert client.get("/theme.css").status_code == 404
    body = b"/* mine */\n:root { --accent: light-dark(#1E8A60, #6BC49A); }\n"
    (repo / "theme.css").write_bytes(body)
    r = client.get("/theme.css")
    assert r.status_code == 200 and r.content == body
    assert r.headers["content-type"].startswith("text/css")
    assert r.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("body", [b"", b"\xff\xfe not utf-8"])
def test_theme_css_odd_bytes_do_not_crash(client, repo, body):
    (repo / "theme.css").write_bytes(body)
    r = client.get("/theme.css")
    assert r.status_code == 200 and r.content == body
    assert client.get("/").status_code == 200
    assert client.get("/settings").status_code == 200


def test_theme_css_never_escapes_the_data_folder(client, repo, tmp_path_factory):
    (repo / "theme.css").mkdir()
    assert client.get("/theme.css").status_code == 404
    (repo / "theme.css").rmdir()
    outside = tmp_path_factory.mktemp("elsewhere") / "id_rsa"
    outside.write_text("PRIVATE")
    (repo / "theme.css").symlink_to(outside)
    r = client.get("/theme.css")
    assert r.status_code == 404 and "PRIVATE" not in r.text
    assert "/theme.css" not in client.get("/").text


def test_theme_css_skips_the_requalify_sweep(client, app, repo, monkeypatch):
    calls = []
    monkeypatch.setattr(app.state.store, "requalify_due", lambda: calls.append(1))
    (repo / "theme.css").write_text(":root{}")
    client.get("/theme.css")
    client.get("/static/tokens.css")
    assert calls == []
    client.get("/")
    assert calls == [1]


def test_pages_carry_a_content_security_policy(client):
    for path in ("/", "/settings", "/pipeline"):
        csp = client.get(path).headers["content-security-policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert "form-action 'self'" in csp
    assert "content-security-policy" not in client.get("/static/tokens.css").headers


def test_settings_appearance_shows_the_theme_file(client, repo):
    page = client.get("/settings").text
    assert "Not in use." in page and str(repo / "theme.css") in page
    assert usertheme.EXAMPLE.strip() in page
    (repo / "theme.css").write_text(":root { --accent: red; }\n@import url(https://example.com/x.css);\n")
    page = htmllib.unescape(client.get("/settings").text)
    assert "In use:" in page
    assert "Line 2: @import loads another file" in page
