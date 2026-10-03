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

"""The sample account: one fictional company a new user can load, look at and remove."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import adjust, cli, dashboards, routines, sample, welcome
from hermitcrm.datafolder import init_folder
from hermitcrm.models import ValidationError
from hermitcrm.store import Store, load_config
from hermitcrm.web import create_app

NOW = datetime(2026, 9, 14, 10, 30)


def git(args, cwd) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


def log(folder: Path) -> list[str]:
    return git(["log", "--format=%s"], folder).splitlines()


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "crm")


def make_client(folder: Path):
    config = load_config(folder)
    config["push_enabled"] = False
    app = create_app(folder, config)
    app.state.setup_platform = "linux"
    app.state.setup_redirected = True
    app.state.calendar_url = lambda refresh=False: ""
    return app, TestClient(app, follow_redirects=False)


def token(client) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get("/settings").text).group(1)


def cli_add(folder: Path) -> None:
    assert cli.main(["--data", str(folder), "sample", "add"]) == 0


# ------------------------------------------------------------------ content


def test_the_sample_has_one_of_everything(folder):
    cli_add(folder)
    store = Store(folder)
    assert store.load() == []
    [company] = store.all()
    assert company.is_sample and "sample" in company.tags
    assert company.stage == "offer" and company.value_eur_month
    assert [e.to_stage for e in company.stage_entries()] == \
        ["prospect", "engaged", "discovery", "offer"]
    assert len(company.contacts) == 2
    assert {c.role for c in company.contacts.values()} == {"decision-maker", "champion"}
    its = company.interactions
    assert any(i.is_message for i in its) and any(i.direction == "in" for i in its)
    assert any(i.channel == "meeting" for i in its)
    assert company.next_step and company.next_step_due > NOW.date()
    person_tasks = [t for c in company.contacts.values() for t in c.tasks]
    assert any(not t.done and t.due for t in person_tasks)
    assert any(t.done for t in company.tasks + person_tasks)
    assert "made up" in company.notes and "Remove" in company.notes
    text = (folder / "companies" / company.slug / "company.md").read_text()
    assert "\nsample: true\n" in text


def test_loading_is_one_commit_and_check_stays_clean(folder, capsys):
    cli_add(folder)
    assert log(folder)[0] == "sample: added" and len(log(folder)) == 2
    assert git(["status", "--porcelain"], folder) == ""
    capsys.readouterr()
    assert cli.main(["--data", str(folder), "check"]) == 0


def test_loading_twice_is_refused(folder, capsys):
    cli_add(folder)
    capsys.readouterr()
    assert cli.main(["--data", str(folder), "sample", "add"]) == 1
    assert "already" in capsys.readouterr().err
    store = Store(folder)
    store.load()
    assert len(store.all()) == 1 and len(log(folder)) == 2


def test_pipeline_marks_the_sample_line(folder):
    cli_add(folder)
    pipeline = (folder / "PIPELINE.md").read_text()
    [line] = [ln for ln in pipeline.splitlines() if "Northwind" in ln]
    assert line.endswith("| sample (fictional)")


def test_new_folders_tell_agents_to_leave_samples_out(folder):
    for name in ("CLAUDE.md", "AGENTS.md"):
        assert "sample: true" in (folder / name).read_text()


# ------------------------------------------------------------------ removal


def test_remove_takes_only_the_sample(folder, capsys):
    cli_add(folder)
    assert cli.main(["--data", str(folder), "add", "company", "Real Customer BV"]) == 0
    capsys.readouterr()
    assert cli.main(["--data", str(folder), "sample", "remove"]) == 0
    out = capsys.readouterr().out
    assert "Northwind Robotics" in out
    store = Store(folder)
    store.load()
    assert [c.name for c in store.all()] == ["Real Customer BV"]
    assert log(folder)[0] == "sample: removed"
    assert git(["status", "--porcelain"], folder) == ""
    assert "Northwind" not in (folder / "PIPELINE.md").read_text()


def test_remove_with_nothing_there_says_so(folder, capsys):
    assert cli.main(["--data", str(folder), "sample", "remove"]) == 0
    assert "no sample" in capsys.readouterr().out.lower()
    assert len(log(folder)) == 1


def test_delete_sample_refuses_a_company_without_the_marker(folder):
    store = Store(folder)
    store.load()
    real = store.create_company("Real Customer BV")
    with pytest.raises(ValidationError):
        store.delete_sample(real.slug)
    assert (folder / "companies" / real.slug / "company.md").exists()


def test_removing_the_marker_by_hand_makes_it_yours(folder, capsys):
    cli_add(folder)
    path = next((folder / "companies").glob("*/company.md"))
    path.write_text(path.read_text().replace("sample: true\n", ""))
    capsys.readouterr()
    assert cli.main(["--data", str(folder), "sample", "remove"]) == 0
    assert path.exists()


# ------------------------------------------------------------------ walkthrough


def test_the_walkthrough_ignores_the_sample(folder):
    cli_add(folder)
    store = Store(folder)
    store.load()
    steps = welcome.steps(store, {}, {}, False)
    done = {s.key for s in steps if s.done}
    assert not done & {"company", "contact", "interaction", "move", "plan"}


# ------------------------------------------------------------------ web


def test_first_start_offers_the_sample_on_welcome_and_home(folder):
    _, client = make_client(folder)
    for page in (client.get("/welcome").text, client.get("/").text):
        assert 'action="/sample"' in page
    assert "sample-bar" not in client.get("/").text


def test_load_and_remove_from_the_web(folder):
    app, client = make_client(folder)
    csrf = token(client)
    assert client.post("/sample", data={}).status_code == 403
    r = client.post("/sample", data={"csrf_token": csrf})
    assert r.status_code == 303 and r.headers["location"].startswith("/companies/northwind-robotics")
    assert log(folder)[0] == "sample: added"

    for url in ("/", "/pipeline", "/companies", "/calendar", "/messages", "/reports",
                "/welcome", "/companies/northwind-robotics"):
        page = client.get(url)
        assert page.status_code == 200, url
        assert "sample-bar" in page.text and 'href="/sample/remove"' in page.text, url
    assert "0 of 11" in client.get("/welcome").text   # the sample ticks nothing
    # a second load is refused with a message, not a second company
    r = client.post("/sample", data={"csrf_token": csrf})
    assert "already" in r.headers["location"].lower()
    assert len(app.state.store.companies) == 1

    confirm = client.get("/sample/remove").text
    assert "Northwind Robotics" in confirm and "Lena Vogt" in confirm
    assert client.post("/sample/remove", data={}).status_code == 403
    r = client.post("/sample/remove", data={"csrf_token": csrf})
    assert r.status_code == 303
    assert app.state.store.companies == {}
    assert log(folder)[0] == "sample: removed"
    home = client.get("/").text
    assert "sample-bar" not in home and 'action="/sample"' in home


# ------------------------------------------------- the dashboard and the routine
# Show before you ask (design 7.2): the sample comes with a pinned dashboard and
# a paused routine, and takes back only what is still exactly as it wrote it.

USER_DASHBOARD = 'title = "My own Monday"\n\n[[widget]]\ntype = "count"\nscope = "companies"\n'
USER_ROUTINES = '''# my own routines
[[routine]]
name = "morning-brief"
title = "Morning brief"
action = "brief"
'''


def commit_all(folder: Path, message: str = "ai: adjust: by hand") -> None:
    git(["add", "-A"], folder)
    git(["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", message],
        folder)


def dashboard_page(folder: Path) -> str:
    _, client = make_client(folder)
    page = client.get(sample.DASHBOARD_URL)
    assert page.status_code == 200
    return page.text


def assert_every_widget_has_rows(page: str) -> None:
    assert page.count('<section class="widget') == 5
    assert 'class="empty"' not in page
    counts = re.findall(r'<p class="widget-count"><a [^>]*>(\d+)</a>', page)
    assert len(counts) == 2 and all(int(n) > 0 for n in counts)


def test_add_writes_a_pinned_dashboard_and_a_paused_routine(folder, capsys):
    cli_add(folder)
    out = capsys.readouterr().out
    assert "Monday review" in out and "Nudge quiet threads, paused" in out
    assert (folder / sample.DASHBOARD).read_text() == sample.DASHBOARD_TEXT
    assert (folder / sample.ROUTINES).read_text() == sample.ROUTINE_BLOCK
    assert dashboards.pins(folder) == [{"title": "Monday review", "url": "/d/monday-review"}]
    routine = routines.load(folder).get(sample.ROUTINE)
    assert routine.paused and routine.title == "Nudge quiet threads"
    assert dashboards.validate(folder) == [] and routines.validate(folder) == []
    # one commit for the company and both files, nothing left over
    assert log(folder)[0] == "sample: added" and len(log(folder)) == 2
    changed = git(["show", "--name-only", "--format=", "HEAD"], folder).split()
    assert {sample.DASHBOARD, sample.ROUTINES} <= set(changed)
    assert git(["status", "--porcelain"], folder) == ""


def test_every_widget_shows_rows_with_the_sample_alone(folder):
    cli_add(folder)
    assert_every_widget_has_rows(dashboard_page(folder))


def test_add_overwrites_nothing(folder, capsys):
    (folder / "dashboards").mkdir()
    (folder / sample.DASHBOARD).write_text(USER_DASHBOARD)
    mine = USER_ROUTINES.replace("morning-brief", sample.ROUTINE)
    (folder / sample.ROUTINES).write_text(mine)
    commit_all(folder)
    cli_add(folder)
    out = capsys.readouterr().out
    assert "already exists" in out and f"already has a routine called {sample.ROUTINE}" in out
    assert (folder / sample.DASHBOARD).read_text() == USER_DASHBOARD
    assert (folder / sample.ROUTINES).read_text() == mine
    # and remove leaves them alone too: they were never the sample's
    assert cli.main(["--data", str(folder), "sample", "remove"]) == 0
    out = capsys.readouterr().out
    assert "Removed the sample: Northwind Robotics." in out and "Kept" not in out
    assert (folder / sample.DASHBOARD).read_text() == USER_DASHBOARD
    assert (folder / sample.ROUTINES).read_text() == mine


def test_the_routine_joins_routines_already_there_and_leaves_them(folder, capsys):
    (folder / sample.ROUTINES).write_text(USER_ROUTINES)
    commit_all(folder)
    cli_add(folder)
    names = routines.load(folder).names
    assert names == ["morning-brief", sample.ROUTINE]
    assert routines.validate(folder) == []
    capsys.readouterr()
    assert cli.main(["--data", str(folder), "sample", "remove"]) == 0
    out = capsys.readouterr().out
    assert "the routine Nudge quiet threads" in out
    assert "Kept your other routine in routines.toml: morning-brief." in out
    assert (folder / sample.ROUTINES).read_text() == USER_ROUTINES  # byte for byte
    assert not (folder / sample.DASHBOARD).exists()
    assert git(["status", "--porcelain"], folder) == ""


def test_a_routines_file_that_does_not_parse_gets_nothing_added(folder, capsys):
    (folder / sample.ROUTINES).write_text("[[routine]\nname = 'x'\n")
    commit_all(folder)
    cli_add(folder)
    assert "has a problem" in capsys.readouterr().out
    assert (folder / sample.ROUTINES).read_text() == "[[routine]\nname = 'x'\n"
    assert (folder / sample.DASHBOARD).exists()


def test_remove_keeps_a_dashboard_you_changed(folder, capsys):
    cli_add(folder)
    path = folder / sample.DASHBOARD
    path.write_text(path.read_text().replace('period = "30d"', 'period = "90d"'))
    commit_all(folder, "ai: adjust: dashboard Monday review, 90 days")
    capsys.readouterr()
    assert cli.main(["--data", str(folder), "sample", "remove"]) == 0
    out = capsys.readouterr().out
    assert "Kept dashboards/monday-review.toml" in out
    assert "the routine Nudge quiet threads" in out and "the dashboard" not in out
    assert path.exists() and not (folder / sample.ROUTINES).exists()
    assert log(folder)[0] == "sample: removed"
    assert git(["status", "--porcelain"], folder) == ""


def test_a_routine_turned_on_is_yours_and_off_again_is_the_samples(folder, capsys):
    cli_add(folder)
    store = Store(folder)
    store.load()
    assert routines.set_paused(store, sample.ROUTINE, False)
    assert sample.plan_removal(folder).files == [sample.DASHBOARD]
    kept = sample.plan_removal(folder).kept
    assert any("changed since the sample wrote it" in k for k in kept)
    assert routines.set_paused(store, sample.ROUTINE, True)
    assert (folder / sample.ROUTINES).read_text() == sample.ROUTINE_BLOCK
    assert sample.plan_removal(folder).files == [sample.DASHBOARD, sample.ROUTINES]


def test_remove_leaves_a_routine_you_changed(folder, capsys):
    cli_add(folder)
    path = folder / sample.ROUTINES
    path.write_text(path.read_text().replace("days = 7", "days = 10"))
    commit_all(folder)
    capsys.readouterr()
    assert cli.main(["--data", str(folder), "sample", "remove"]) == 0
    out = capsys.readouterr().out
    assert f"Kept the routine {sample.ROUTINE}" in out
    assert "days = 10" in path.read_text()
    assert not (folder / "dashboards").exists()


def test_the_walkthrough_does_not_count_the_samples_files(folder):
    cli_add(folder)
    assert not adjust.has_adjusted_files(folder)
    path = folder / sample.DASHBOARD
    path.write_text(path.read_text().replace("pin = true", "pin = false"))
    assert adjust.has_adjusted_files(folder)


# ------------------------------------------------------------------ the demo folder


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "demo", demo=True)


def test_the_demo_folder_has_both_and_checks_clean(demo, capsys):
    assert (demo / sample.DASHBOARD).read_text() == sample.DASHBOARD_TEXT
    assert (demo / sample.ROUTINES).read_text() == sample.ROUTINE_BLOCK
    assert cli.main(["--data", str(demo), "check"]) == 0
    assert git(["status", "--porcelain"], demo) == ""
    # the routine has someone to pick in the demo, so its preview is not empty
    store = Store(demo)
    store.load()
    picks = routines.select(store, routines.load(demo).get(sample.ROUTINE))
    assert [p for p in picks if not p.status]


def test_the_demo_hub_sidebar_and_pages_show_them(demo):
    _, client = make_client(demo)
    hub = client.get("/yours").text
    built = hub.split('id="built"', 1)[1].split('id="changes"', 1)[0]
    assert 'href="/d/monday-review">Monday review</a>' in built
    assert 'href="/yours/routines/nudge-quiet-threads">Nudge quiet threads</a>' in built
    assert built.count("· sample") == 2 and "paused" in built
    home = client.get("/").text
    assert 'href="/d/monday-review"' in home  # pinned in the sidebar
    assert_every_widget_has_rows(dashboard_page(demo))
    page = client.get(sample.ROUTINE_URL)
    assert page.status_code == 200 and "paused" in page.text and "Turn on" in page.text


def test_sample_remove_in_the_demo_takes_the_two_files(demo, capsys):
    assert cli.main(["--data", str(demo), "sample", "remove"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Removed the sample: the dashboard Monday review and the routine "
                          "Nudge quiet threads.")
    assert not (demo / "dashboards").exists() and not (demo / sample.ROUTINES).exists()
    assert log(demo)[0] == "sample: removed"
    assert git(["status", "--porcelain"], demo) == ""
    assert cli.main(["--data", str(demo), "sample", "remove"]) == 0
    assert "No sample account" in capsys.readouterr().out


# ------------------------------------------------------------------ web


def test_the_web_remove_page_lists_and_keeps(folder):
    _, client = make_client(folder)
    csrf = token(client)
    r = client.post("/sample", data={"csrf_token": csrf})
    assert "Monday review" in r.headers["location"].replace("%20", " ")
    path = folder / sample.DASHBOARD
    path.write_text(path.read_text().replace("pin = true", "pin = false"))
    commit_all(folder)
    page = client.get("/sample/remove").text
    assert "Northwind Robotics" in page and "Nudge quiet threads" in page
    assert 'href="/yours/routines/nudge-quiet-threads"' in page
    assert "Kept dashboards/monday-review.toml" in page
    made = page.split("Made with it", 1)[1].split("</div>", 1)[0]
    assert "Nudge quiet threads" in made and "Monday review" not in made
    r = client.post("/sample/remove", data={"csrf_token": csrf})
    assert "Kept" in r.headers["location"].replace("%20", " ")
    assert path.exists() and not (folder / sample.ROUTINES).exists()
