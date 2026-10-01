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

"""Route tests for app/web.py, including the §10 acceptance flow end to end."""

from __future__ import annotations

import html as htmllib
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from fastapi.testclient import TestClient

from hermitcrm import usertheme
from hermitcrm.models import fmt_date
from hermitcrm.web import asset_version, company_values, create_app
from conftest import FIXED_NOW
from test_tokens import effective  # the CSS reader the token tests use

CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "owner_email": "me@example.com",
          # an established user: these tests are not about the first launch
          "welcome_dismissed": True, "disclaimer_accepted": "2026-09-01T09:00:00"}

# The day these tests are about. It has to be the day the app believes in too,
# or every date below becomes a bet on when the suite is run: see the app fixture.
TODAY = FIXED_NOW.date()
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
    app = create_app(repo, config=CONFIG)
    # Every page under test asks the store what day it is, while the tests write
    # dates of their own -- TODAY, and literals in September 2026. Leave the store
    # on the real clock and the gap between the two changes every day: a task due
    # "2026-09-24" sits in Future tasks, then moves to Top priority when that date
    # arrives, and once the month rolls over the calendar grid stops drawing it at
    # all. Fixing the store's day makes the tests mean what they say.
    app.state.store.clock = lambda: FIXED_NOW
    return app


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
                 "phone": "", "role": ""}
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
    assert "Call Jane" in page and "send the deck" in page   # both kinds of work
    assert 'href="/pipeline"' in page
    # this folder has put the walkthrough away, so the beginner block is gone too
    assert "What this thing does" not in page and "Getting started" not in page

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
    r = client.post("/welcome/tick", data={"csrf_token": token, "key": "extension",
                                           "done": "1"})
    assert r.status_code == 303
    assert "extension" in app.state.config.get("welcome_done", []) or \
        '"extension"' in (repo / "config.toml").read_text()
    page = client.get("/welcome").text
    assert "Untick" in page.split('id="extension"')[1].split("</li>")[0]

    # and the Untick button gives it back: the form sends an empty value for off
    client.post("/welcome/tick", data={"csrf_token": token, "key": "extension",
                                       "done": ""})
    assert "extension" not in (app.state.config.get("welcome_done") or [])

    # a step that ticks itself cannot be ticked by hand
    r = client.post("/welcome/tick", data={"csrf_token": token, "key": "company",
                                           "done": "1"})
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
    assert r.status_code == 303 and r.headers["location"] == "/tasks?when=overdue&when=today"
    table = lambda url: client.get(url).text.split("</nav>", 1)[1].split('id="task-list"')[0]
    priority = table("/tasks?when=overdue&when=today")
    future = table("/tasks?when=later")
    assert "Due Now GmbH" in priority
    assert "Future GmbH" not in priority and "Future GmbH" in future
    assert "Closed GmbH" not in future
    assert "Closed GmbH" in table("/tasks")          # closed companies are listed too
    assert "/interactions/new" not in priority        # no "log interaction" here
    page = client.get("/calendar").text
    silent_part = page[page.index('id="silent"'):]
    assert "Quiet GmbH" in silent_part
    assert "Due Now GmbH" not in silent_part
    assert "1 due today or earlier" in page
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
                          contact="jane-doe", subject="", body="kept body")
    assert ok.status_code == 303
    assert "(no subject)" in client.get("/companies/acme").text

    # An interaction is always with a person: no contact, no interaction.
    nobody = post_interaction(client, "acme", channel="call", direction="in",
                              subject="", body="kept body")
    assert nobody.status_code == 400 and "pick a contact" in nobody.text

    bad = post_interaction(client, "acme", channel="", direction="in",
                           contact="jane-doe", subject="", body="kept body")
    assert bad.status_code == 400
    assert "channel is required" in bad.text
    assert "kept body" in bad.text


def test_interaction_edit_renames_file_on_date_change(client, repo):
    post_company(client, name="Acme GmbH")
    post_contact(client, "acme", first_name="Jane", last_name="Doe")
    post_interaction(client, "acme", channel="email", direction="out", contact="jane-doe",
                     date="2026-09-01T08:00", subject="Intro", body="hello")
    old_id = "2026-09-01T0800-email-out-jane-doe"
    old_path = repo / "companies/acme/interactions" / f"{old_id}.md"
    assert old_path.exists()

    form = client.get(f"/companies/acme/interactions/{old_id}/edit").text
    assert 'value="2026-09-01T08:00"' in form

    resp = client.post(f"/companies/acme/interactions/{old_id}/edit",
                       data={**INTERACTION_BLANK, "channel": "email",
                             "direction": "out", "date": "2026-09-02T09:30",
                             "contact": "jane-doe", "subject": "Intro", "body": "hello"})
    new_id = "2026-09-02T0930-email-out-jane-doe"
    assert resp.status_code == 303
    assert resp.headers["location"].endswith(f"#i-{new_id}")
    assert (repo / "companies/acme/interactions" / f"{new_id}.md").exists()
    assert not old_path.exists()
    assert last_commit(repo) == f"interaction: acme {new_id} updated"


def test_log_form_preselects_latest_contact(client):
    post_company(client, name="Acme GmbH")
    post_contact(client, "acme", first_name="Jane", last_name="Doe")
    post_contact(client, "acme", first_name="John", last_name="Roe")
    post_interaction(client, "acme", channel="email", direction="out",
                     contact="john-roe", date="2026-09-02T09:00", subject="Hi")

    # The company page has no log form any more: you log on the person's page,
    # or on the standalone form, which preselects the latest contact.
    assert 'id="quick-add"' not in client.get("/companies/acme").text
    page = client.get("/companies/acme/interactions/new").text
    assert '<option value="john-roe" selected>' in page
    assert "company only" not in page
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
                            direction="out", contact="jonas-berg", date="2026-09-14T10:30",
                            subject="Intro call", body="Spoke about DORA scope.")
    ids = [
        "2026-09-08T0912-linkedin-out-anna-mueller",
        "2026-09-11T1640-email-in-anna-mueller",
        "2026-09-14T1030-call-out-jonas-berg",
    ]
    for iid in ids:
        assert (folder / "interactions" / f"{iid}.md").exists()
    assert resp.headers["location"].endswith(f"#i-{ids[2]}")

    page = client.get("/companies/mueller-soehne").text
    positions = [page.index(f'id="i-{iid}"') for iid in ids]
    assert positions == sorted(positions, reverse=True)  # newest first
    assert "Anna Müller" in page and "Jonas Berg" in page
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
    overdue_part = client.get("/tasks?when=overdue").text.split("</nav>", 1)[1]
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
    assert ">Done<" in page and 'action="/companies/acme/next-step"' in page
    tasks_page = lambda url="/tasks": client.get(url).text.split("</nav>", 1)[1]
    assert "Call Jane" in tasks_page()

    r = client.post("/companies/acme/next-step", data={"status": "done"},
                    headers={"referer": "http://testserver/calendar?flash=x"})
    assert r.status_code == 303 and r.headers["location"].startswith("/calendar?flash=")
    acme = app.state.store.get("acme")
    assert acme.next_step_done and acme.next_step_done_on == app.state.store.today()
    assert f"next_step_done_on: {acme.next_step_done_on}" in \
        company_file(repo, "acme").read_text(encoding="utf-8")
    assert last_commit(repo) == "company: acme next step done"
    assert "Call Jane" not in tasks_page()
    done = tasks_page("/tasks?f_status=done")
    assert "Call Jane" in done and fmt_date(acme.next_step_done_on) in done
    page = client.get("/companies/acme").text
    assert "Reopen" in page and "status-done" in page and "Add to Google Calendar" not in page
    assert "(done)" in client.get("/pipeline").text and "(done)" in client.get("/companies").text

    r = client.post("/companies/acme/next-step", data={"status": "open"})
    assert r.headers["location"] == "/companies/acme?flash=Task%20reopened#tasks"
    assert last_commit(repo) == "company: acme next step reopened"
    acme = app.state.store.get("acme")
    assert acme.next_step_done_on is None
    assert "next_step_done_on" not in company_file(repo, "acme").read_text(encoding="utf-8")


def test_the_next_step_is_the_task_due_first(client, app, repo):
    """No picking: the company's open task due first is its next step, for the
    company or one of its people, and adding a task never replaces one."""
    post_company(client, name="Acme", next_step="Call Jane",
                 next_step_due=str(TODAY + timedelta(days=5)))
    post_contact(client, "acme", first_name="Jane", last_name="Roe")

    page = client.get("/companies/acme").text
    assert 'id="tasks"' in page
    assert 'action="/companies/acme/task"' not in page      # no "Save next step" form
    assert 'action="/companies/acme/tasks"' in page         # one "Add task" form
    assert '<option value="jane-roe">Jane Roe</option>' in page
    # "This company on the Tasks page" filters to this company only
    post_company(client, name="Acme Two", next_step="Other", next_step_due=str(TODAY))
    link = re.search(r'href="(/tasks\?f_company_name=[^"]+)"', page).group(1)
    listed = client.get(htmllib.unescape(link)).text.split("</nav>", 1)[1].split('id="task-list"')[0]
    assert "Call Jane" in listed and "Other" not in listed

    contact_page = client.get("/companies/acme/contacts/jane-roe").text
    assert "Tasks for Jane Roe" in contact_page
    assert 'href="/companies/acme#tasks"' in contact_page

    # an earlier task for Jane becomes the next step; the old one stays a task
    client.post("/companies/acme/tasks", data={
        "text": "send her the deck", "contact": "jane-roe",
        "due": str(TODAY + timedelta(days=2))})
    company = app.state.store.get("acme")
    assert company.next_step == "Call Jane" and company.next_step_open   # untouched
    assert company.next_text == "send her the deck"
    assert company.next_due == TODAY + timedelta(days=2)
    assert "next: send her the deck (Jane Roe), due" in pipeline_text(repo)
    page = client.get("/companies/acme").text
    rows = page.split('id="tasks"')[1].split("</table>")[0]
    assert rows.index("send her the deck") < rows.index('next step</span>') < rows.index("Call Jane")
    assert "(Jane Roe), due" in page.split('class="small next-step-line')[1][:600]

    # tick it off and "Call Jane" is next again
    client.post("/companies/acme/tasks/0/done",
                data={"contact": "jane-roe", "text": "send her the deck", "done": "1"})
    company = app.state.store.get("acme")
    assert company.next_text == "Call Jane"
    assert company.contacts["jane-roe"].tasks[0].done_on == app.state.store.today()

    # the old "Save next step" form, from a tab left open, now adds a task
    r = client.post("/companies/acme/task",
                    data={"next_step": "Book the demo", "next_step_due": ""},
                    headers={"referer": "http://testserver/companies/acme"})
    assert r.status_code == 303 and r.headers["location"].endswith("#tasks")
    company = app.state.store.get("acme")
    assert company.next_step == "Call Jane"
    assert [t.text for t in company.tasks] == ["Book the demo"]
    assert company.next_text == "Call Jane"       # dated beats undated


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
    listing = client.get("/tasks").text.split("</nav>", 1)[1]
    assert "send the pricing page" in listing and "book the intro call" in listing
    assert "Ines Vega" in listing and "no date" in listing

    # /tasks takes the same form, a person by name, and returns to the view
    r = client.post("/tasks", data={"text": "ask about budget",
                                    "company": "Harbour Light Labs",
                                    "contact": "ines vega",
                                    "back": "/tasks?when=none&flash=old"})
    assert r.headers["location"] == "/tasks?when=none&flash=Task%20created#task-list"
    assert [t.text for t in app.state.store.get("harbour-light-labs")
            .contacts["ines-vega"].tasks] == ["book the intro call", "ask about budget"]
    # a first name alone is enough; an unknown one says who is there
    client.post("/tasks", data={"text": "first name only", "company": "Harbour Light Labs",
                                "contact": "Ines"})
    assert app.state.store.get("harbour-light-labs").contacts["ines-vega"].tasks[-1].text \
        == "first name only"
    r = client.post("/tasks", data={"text": "call about pricing",
                                    "company": "Harbour Light Labs", "contact": "jane",
                                    "due": "2026-09-30", "back": "/tasks?when=none"})
    assert r.status_code == 400
    form = r.text.split('id="task-list"')[1]          # the message sits by the form
    assert "nobody at Harbour Light Labs is called &#39;jane&#39;" in form
    assert "Ines Vega" in form and 'class="flash"' not in r.text
    assert 'value="call about pricing"' in form and 'value="jane"' in form
    assert 'value="2026-09-30"' in form and 'value="/tasks?when=none"' in form
    r = client.post("/tasks", data={"text": "x", "company": "Harbour Light Labs",
                                    "back": "https://evil.example/"})
    assert r.headers["location"].startswith("/tasks?flash=")

    # a company nobody has is refused rather than invented
    r = client.post("/calendar/task", data={"text": "x", "company": "Nobody"})
    assert r.status_code == 400 and "No company called &#39;Nobody&#39;" in r.text
    r = client.post("/calendar/task", data={"text": "x", "company": "Nobody",
                                            "back": "/calendar"})
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
    # a done next step is off the calendar
    assert "Finished" not in page
    # the old task tables moved to /tasks; one line points there
    assert 'id="future-tasks"' not in page and 'id="task-list"' not in page
    assert "2 due today or earlier" in page and 'href="/tasks?when=overdue&amp;when=today"' in page

    main = lambda url: frozen_client.get(url).text.split("</nav>", 1)[1].split('id="task-list"')[0]
    priority = main("/tasks?when=overdue&when=today")
    assert priority.index("Delta") < priority.index("Acme")
    assert "Beta" not in priority and "Gamma" not in priority
    later = main("/tasks?when=week&when=none")
    assert later.index("Beta") < later.index("Gamma")
    assert "Acme" not in later and "Delta" not in later
    assert "no date" in later and ">Done<" in later
    assert 'href="/calendar?month=2026-08"' in page and 'href="/calendar?month=2026-10"' in page

    august = frozen_client.get("/calendar?month=2026-08").text
    assert "August 2026" in august and "Delta" in august.split('id="day-2026-08-03"')[1].split("</td>")[0]
    assert frozen_client.get("/calendar?month=garbage").status_code == 200


def test_the_tasks_page_filters_every_task_in_one_table(frozen_client):
    """Date buttons, a filter per column, done dates, closed companies."""
    c = frozen_client
    post_company(c, name="Acme", stage="discovery", next_step="Call Jane",
                 next_step_due="2026-09-10")
    post_contact(c, "acme", first_name="Jane", last_name="Roe")
    c.post("/companies/acme/tasks", data={"text": "send the deck", "contact": "jane-roe",
                                          "due": "2026-09-30"})
    c.post("/companies/acme/tasks", data={"text": "check the audit"})
    post_company(c, name="Beta", next_step="Book the demo", next_step_due="2026-09-14")
    post_company(c, name="Lost Co", stage="lost", lost_reason="budget",
                 next_step="Ask again", next_step_due="2026-09-15")
    main = lambda url: c.get(url).text.split("</nav>", 1)[1]
    table = lambda url: main(url).split('class="filters"')[1].split("</table>")[0]

    page = main("/tasks")
    assert "Tasks (5)" in page                    # open ones, closed companies too
    assert "Ask again" in page and "Show closed companies" not in page
    # one chip per date range, with a count
    for label, n in (("Overdue", 1), ("Today", 1), ("Next 7 days", 2), ("Later", 1),
                     ("No date", 1)):
        assert f'{label} <span class="count">{n}</span>' in page
    # the next step is each company's open task due first
    rows = table("/tasks")
    assert rows.index("Call Jane") < rows.index("Book the demo") \
        < rows.index("send the deck") < rows.index("check the audit")
    assert rows.count('class="tag next-step"') == 3
    assert 'Next steps only <span class="count">3</span>' in page

    assert "Book the demo" in table("/tasks?when=today") and "Call Jane" not in table("/tasks?when=today")
    both = table("/tasks?when=overdue&when=today")
    assert "Call Jane" in both and "Book the demo" in both and "send the deck" not in both
    assert "Ask again" not in table("/tasks?f_stage=discovery")

    nexts = table("/tasks?next=1")
    assert "Call Jane" in nexts and "send the deck" not in nexts
    assert "Jane Roe" in table("/tasks?f_who=jane") and "Beta" not in table("/tasks?f_who=jane")
    assert "Book the demo" not in table("/tasks?f_stage=discovery")
    assert "check the audit" in table("/tasks?f_due=-") and "Call Jane" not in table("/tasks?f_due=-")
    by_text = table("/tasks?sort=text&dir=asc")
    assert by_text.index("Book the demo") < by_text.index("Call Jane") < by_text.index("check the audit")

    # Done from the filtered view comes back to it and records the day
    r = c.post("/companies/acme/tasks/0/done",
               data={"text": "check the audit", "done": "1", "back": "/tasks?next=1&f_who=acme"})
    assert r.headers["location"] == "/tasks?next=1&f_who=acme&flash=Task%20done#tasks"
    assert "check the audit" not in table("/tasks")
    done = table("/tasks?f_status=done")
    assert "check the audit" in done and "2026-09-14" in done
    assert "check the audit" in table("/tasks?f_status=done&f_done_on=>2026-09-13")
    assert "check the audit" in table("/tasks?f_status=open&f_status=done")


def test_board_unused_columns_are_marked(client):
    post_company(client, name="Acme")
    page = client.get("/pipeline").text
    assert 'class="column" id="col-prospect"' in page
    assert 'class="column unused" id="col-offer"' in page


SHEET = (
    "name\thq_country\twebsite\tfounder_name\tfounder_title\tfit_score\n"
    "Skarvik\tSweden\t\tNils Ekdahl\tFounder / CEO\t82\n"
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
    assert "Nils Ekdahl (Founder / CEO) &middot; create" in preview.text

    bad = client.post("/import/preview", data={"text": "foo\tbar\n1\t2\n"})
    assert bad.status_code == 400 and "needs a &#39;name&#39; column" in bad.text

    upload = client.post("/import/preview", files={"file": ("x.tsv", SHEET.encode(), "text/tab-separated-values")})
    assert upload.status_code == 200 and "Skarvik" in upload.text

    r = client.post("/import", data={"text": SHEET})
    assert r.status_code == 303
    assert "1%20companies%20created%2C%201%20updated%2C%202%20contacts%20created" in r.headers["location"]
    assert last_commit(repo) == "import: 1 companies created, 1 updated, 2 contacts created"
    store = app.state.store
    assert store.get("skarvik").country == "SE"
    assert store.get("acme").extra["fit_score"] == 70  # mapped to a custom field
    assert "nils-ekdahl" in store.get("skarvik").contacts
    assert store.get("acme").contacts["jane-doe"].title == "CEO"
    assert "skarvik" in (repo / "PIPELINE.md").read_text()


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
    assert "Revisit" in client.get("/tasks?when=overdue").text.split("</nav>", 1)[1]
    today = client.get("/calendar").text
    assert "1 due today or earlier" in today
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
    post_contact(client, "acme", first_name="Henrik", last_name="Lund")
    post_interaction(client, "acme", contact="henrik-lund", channel="linkedin", date=fresh,
                     body="Hi Henrik, growing nicely.")
    post_interaction(client, "acme", contact="jane-doe", channel="linkedin", date=fresh,
                     body="Hi Jane, fractional?")
    post_interaction(client, "acme", contact="jane-doe", channel="email", direction="in",
                     date=f"{TODAY}T10:00", body="Sure, let's talk")
    post_interaction(client, "acme", contact="jane-doe", channel="call", direction="out",
                     date=fresh, subject="no body")  # not a message

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
    henrik = next(i for i in ids if "henrik" in i)
    r = client.post(f"/companies/acme/interactions/{henrik}/outcome",
                    data={"outcome": "unsuccessful"},
                    headers={"referer": "http://testserver/messages?f_channel=linkedin"})
    assert r.status_code == 303 and r.headers["location"].startswith("/messages?flash=")
    assert last_commit(repo) == f"interaction: acme {henrik} outcome unsuccessful"
    page = client.get("/messages").text
    assert '<td class="outcome-unsuccessful">unsuccessful</td>' in page
    assert "Messages (1)" in client.get("/messages?f_status=unsuccessful").text
    assert "Messages (2)" in client.get("/messages?q=jane").text
    assert "Messages (1)" in client.get("/messages?f_contact=henrik").text

    # age: a message with no reply and no verdict flips to unsuccessful after 14 days
    post_company(client, name="Beta")
    post_contact(client, "beta", first_name="Bo", last_name="Beta")
    post_interaction(client, "beta", contact="bo-beta", channel="email", date=old,
                     body="Hello Beta")
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
    post_contact(client, "acme", first_name="Jane", last_name="Doe")
    # A note is not contact made: the prospect stays a prospect.
    post_interaction(client, "acme", channel="note", direction="", contact="jane-doe",
                     date="2026-09-09T09:00", body="met at a fair")
    assert app.state.store.get("acme").stage == "prospect"
    post_interaction(client, "acme", channel="linkedin", direction="out",
                     contact="jane-doe", date="2026-09-10T09:00")
    assert app.state.store.get("acme").stage == "engaged"
    assert last_commit(repo) == ("interaction: acme linkedin out jane-doe 2026-09-10T09:00; "
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
    ids = ['id="details"', 'id="timeline"', 'id="quick-add"', 'id="tasks"', 'id="drafts"',
           'id="delete"']
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
                      "email": "", "phone": "", "role": ""})
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


def phone_and_wide_css() -> tuple[str, str]:
    """style.css split into the @media (max-width: 760px) blocks and the rest."""
    css = (Path(create_app.__code__.co_filename).parent / "static" / "style.css").read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    phone, wide, pos = [], [], 0
    for m in re.finditer(r"@media \(max-width: 760px\) \{", css):
        depth, end = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[end], 0)
            end += 1
        wide.append(css[pos:m.start()])
        phone.append(css[m.end():end - 1])
        pos = end
    return "".join(phone), "".join(wide) + css[pos:]


def test_every_table_on_the_company_page_scrolls_in_a_box_of_its_own(client, app):
    """On a 390px phone the contacts table (two e-mail addresses) was 476px wide and
    the whole page scrolled sideways. Each table now sits in a box that scrolls."""
    post_company(client, name="Acme", next_step="call back", next_step_due=str(TODAY))
    post_contact(client, "acme", first_name="Jane", last_name="Roe",
                 email="jane.roe@a-rather-long-company-name.example.com")
    client.post("/companies/acme/tasks", data={"text": "send the deck"})
    patch_company(client, app, "acme", stage="engaged")
    page = client.get("/companies/acme").text
    assert "Stage history (1)" in page
    tables = page.count("<table")
    assert tables >= 3  # stage history, contacts, tasks (one list since the merge)
    assert page.count('<div class="table-scroll"><table') == tables


def test_the_phone_rules_that_keep_the_company_page_on_the_screen():
    """They all sit in @media (max-width: 760px): above that the page is as it was."""
    phone, wide = phone_and_wide_css()
    assert effective(phone, ".table-scroll") == {"overflow-x": "auto"}
    assert effective(wide, ".table-scroll") == {}
    # The Disqualify menu hung from its button's right edge and ran off the left
    # of the screen; on a phone it spans the header row instead.
    assert effective(phone, ".record-meta")["position"] == "relative"
    assert effective(phone, "details.stage-menu")["position"] == "static"
    assert effective(phone, "details.stage-menu .menu-panel")["left"] == "0"
    assert effective(phone, "details.stage-menu .menu-panel form.inline-form")["flex-wrap"] == "wrap"
    # "Fetch from URL" was a 320px field; open, it takes a row and the field fills it.
    assert effective(wide, ".record-actions input.url")["width"] == "320px"
    assert effective(phone, ".record-actions input.url")["width"] == "auto"
    assert effective(phone, ".record-actions details.inline-edit[open]")["flex-basis"] == "100%"
    # The 260px merge field pushed Compare off a 375px screen; now Compare wraps.
    assert effective(phone, "#merge form.inline-row")["flex-wrap"] == "wrap"
    # The add-task row gained a 260px type dropdown; every inline row wraps on a phone.
    assert effective(phone, "form.inline-row")["flex-wrap"] == "wrap"
    assert "flex-wrap" not in effective(wide, "form.inline-row")


def test_the_companies_and_settings_tables_scroll_in_a_box_of_their_own(client, repo):
    """At 390px the companies table made the page ~1250px wide and the Settings
    fields table 413px. Like the company page's tables, each now scrolls in its box."""
    define_fields(client, repo, MY_SCORE)
    post_company(client, name="Acme", country="NL", stage="prospect")
    companies = client.get("/companies").text
    assert '<div class="table-scroll"><table class="filterable">' in companies
    assert companies.count('<table class="filterable">') == 1
    settings = client.get("/settings").text
    assert '<div class="table-scroll"><table class="fields-list small">' in settings


def test_the_phone_rules_that_keep_companies_settings_and_the_disqualify_menu_on_the_screen():
    """At 390px: a closed Disqualify menu still gave its reason and date fields a box
    past the right edge, a long data-folder path pushed Settings sideways, and the
    filter help, tapped, ran 53px past the right edge of Companies."""
    phone, wide = phone_and_wide_css()
    assert effective(phone, ".filter-form") == {"position": "relative"}
    assert effective(phone, ".filter-form .help") == {"position": "static"}
    assert effective(phone, ".filter-form .help .tip")["max-width"] == "calc(100vw - 48px)"
    assert effective(wide, ".help .tip")["left"] == "0"  # above 760px it hangs from the "?"
    assert effective(wide, ".filter-form .help .tip") == {}
    assert effective(phone, "details.stage-menu:not([open]) .menu-panel") == {"display": "none"}
    assert effective(wide, "details.stage-menu:not([open]) .menu-panel") == {}
    assert effective(phone, "table.about td") == {"overflow-wrap": "anywhere"}
    assert effective(wide, "table.about td") == {}


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


# --- task types ------------------------------------------------------------

TYPES = [{"name": "prospecting", "colour": "blue"}, {"name": "lost deals", "colour": "amber"}]


@pytest.fixture
def typed_client(repo: Path):
    app = create_app(repo, config=dict(CONFIG, task_types=TYPES))
    app.state.store.clock = lambda: FIXED_NOW
    return TestClient(app, follow_redirects=False)


def test_a_task_gets_a_type_when_made_and_can_be_retyped(typed_client):
    c = typed_client
    post_company(c, name="Acme", next_step="Call Jane", next_step_due="2026-09-10",
                 next_step_type="lost deals")
    post_contact(c, "acme", first_name="Jane", last_name="Roe")
    c.post("/companies/acme/tasks", data={"text": "send deck", "type": "prospecting"})
    c.post("/tasks", data={"text": "ask Jane", "company": "Acme", "contact": "Jane",
                           "type": "prospecting", "back": "/tasks"})
    store = c.app.state.store
    acme = store.companies["acme"]
    assert acme.next_step_type == "lost deals" and acme.tasks[0].type == "prospecting"
    assert acme.contacts["jane-roe"].tasks[0].type == "prospecting"
    page = c.get("/companies/acme").text
    assert 'name="type"' in page and 'name="next_step_type"' in page
    assert c.get("/companies/acme/contacts/jane-roe").text.count('name="type"') >= 2

    r = c.post("/companies/acme/todo-type", data={"index": "0", "text": "send deck",
                                                  "type": "lost deals"})
    assert r.status_code == 303 and store.companies["acme"].tasks[0].type == "lost deals"
    c.post("/companies/acme/todo-type", data={"index": "", "type": ""})
    assert store.companies["acme"].next_step_type == ""
    c.post("/companies/acme/todo-type", data={"index": "0", "contact": "jane-roe",
                                              "text": "ask Jane", "type": ""})
    assert store.companies["acme"].contacts["jane-roe"].tasks[0].type == ""
    r = c.post("/companies/acme/todo-type", data={"index": "0", "text": "send deck",
                                                  "type": "nope"})
    assert "unknown task type" in unquote(r.headers["location"])
    r = c.post("/companies/acme/todo-type", data={"index": "0", "text": "changed",
                                                  "type": "prospecting"})
    assert "reload" in unquote(r.headers["location"])


def test_saving_the_company_form_without_a_type_field_keeps_the_type(typed_client):
    c = typed_client
    post_company(c, name="Acme", next_step="Call Jane", next_step_type="prospecting")
    c.post("/companies/acme", data={**COMPANY_BLANK, "name": "Acme", "next_step": "Call Jane"})
    assert c.app.state.store.companies["acme"].next_step_type == "prospecting"
    c.post("/companies/acme", data={**COMPANY_BLANK, "name": "Acme", "next_step": "Call Jane",
                                    "next_step_type": ""})
    assert c.app.state.store.companies["acme"].next_step_type == ""


def test_without_task_types_there_is_no_type_field(client):
    post_company(client, name="Plain", next_step="call")
    client.post("/companies/plain/tasks", data={"text": "send deck"})
    page = client.get("/companies/plain").text
    assert 'name="type"' not in page and 'name="next_step_type"' not in page
    assert 'name="type"' not in client.get("/tasks").text
    assert "next type" not in client.get("/companies").text


def test_the_tasks_page_filters_by_type(typed_client):
    c = typed_client
    post_company(c, name="Acme", next_step="Call Jane", next_step_due="2026-09-10")
    c.post("/companies/acme/tasks", data={"text": "send deck", "type": "prospecting"})
    c.post("/companies/acme/tasks", data={"text": "untyped one"})
    table = lambda url: c.get(url).text.split('class="filters"')[1].split("</table>")[0]
    assert "send deck" in table("/tasks?f_type=prospecting")
    assert "untyped one" not in table("/tasks?f_type=prospecting")
    assert "untyped one" in table("/tasks?f_type=(none)")
    assert "send deck" not in table("/tasks?f_type=(none)")
    assert 'class="type-chip type-blue"' in table("/tasks")
    assert "Call Jane" in table("/tasks?next=1&f_type=(none)")
    assert c.get("/tasks?f_kind=task").status_code == 200     # old links still load


def test_the_tasks_page_has_no_type_column_without_types(client):
    post_company(client, name="Plain", next_step="call")
    head = client.get("/tasks").text.split('class="filters"')[0]
    assert "f_type" not in head and ">type " not in head


def test_the_next_step_type_shows_on_companies_and_board(typed_client):
    c = typed_client
    post_company(c, name="Acme", next_step="Call Jane", next_step_due="2026-09-10")
    post_company(c, name="Beta", next_step="Book demo")
    c.post("/companies/acme/todo-type", data={"index": "", "type": "prospecting"})
    body = lambda url: c.get(url).text.split('class="filters"')[1].split("</table>")[0]
    companies = c.get("/companies").text
    assert ">next type " in companies and 'class="type-chip type-blue"' in companies
    assert "Acme" in body("/companies?f_next_type=prospecting")
    assert "Beta" not in body("/companies?f_next_type=prospecting")
    assert "Beta" in body("/companies?f_next_type=(none)")
    assert 'class="type-chip type-blue"' in c.get("/pipeline").text


# ------------------------------------------------------- notes as interactions


def test_contact_page_logs_notes_and_has_no_notes_field(client, app, repo):
    post_company(client, name="Acme")
    post_contact(client, "acme", first_name="Jane", last_name="Doe")
    page = client.get("/companies/acme/contacts/jane-doe").text
    form = page.split('<section id="quick-add">')[1].split("</section>")[0]
    assert '<input type="hidden" name="contact" value="jane-doe">' in form
    assert 'name="channel" value="note"' in form and "<select name=\"contact\">" not in form
    details = page.split('<section id="details">')[1].split("</section>")[0]
    assert 'name="notes"' not in details
    assert 'name="notes"' not in client.get("/companies/acme/contacts/new").text

    r = post_interaction(client, "acme", channel="note", direction="", contact="jane-doe",
                         date="2026-09-12T08:00", body="Prefers email.")
    assert r.status_code == 303
    assert r.headers["location"].startswith("/companies/acme/contacts/jane-doe?flash=")
    assert r.headers["location"].endswith("#i-2026-09-12T0800-note-jane-doe")
    page = client.get("/companies/acme/contacts/jane-doe").text
    item = page.split('id="i-2026-09-12T0800-note-jane-doe"')[1].split("</li>")[0]
    assert "Prefers email." in item and "(no subject)" not in item
    assert app.state.store.get("acme").stage == "prospect"  # a note is not contact made

    # Saving the contact form (which has no notes field) keeps a legacy body.
    path = repo / "companies/acme/contacts/jane-doe.md"
    path.write_text(path.read_text() + "old note\n")
    app.state.store.load()
    r = client.post("/companies/acme/contacts/jane-doe",
                    data={**CONTACT_BLANK, "first_name": "Jane", "last_name": "Doe",
                          "title": "CEO"})
    assert r.status_code == 303
    assert path.read_text().endswith("old note\n") and "title: CEO" in path.read_text()


def test_company_page_has_no_log_form_and_drafts_follow_tasks(client):
    post_company(client, name="Acme")
    post_contact(client, "acme", first_name="Jane", last_name="Doe")
    page = client.get("/companies/acme").text
    assert 'id="quick-add"' not in page and 'class="interaction-form' not in page
    assert '/companies/acme/contacts/jane-doe#quick-add">log</a>' in page
    assert page.index('id="tasks"') < page.index('id="drafts"')
