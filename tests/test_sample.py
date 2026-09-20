"""The sample account: one fictional company a new user can load, look at and remove."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import cli, welcome
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
    assert "0 of 10" in client.get("/welcome").text   # the sample ticks nothing
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
