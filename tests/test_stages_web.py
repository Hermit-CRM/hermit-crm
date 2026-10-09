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

"""Deal stages in the web app: Settings, the board, the company page, hot reload."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import cli
from hermitcrm import stages as st
from hermitcrm.datafolder import init_folder
from hermitcrm.store import load_config
from hermitcrm.web import create_app

DEFAULT_ROWS = st.to_config(st.DEFAULT_STAGES)


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "demo", demo=True)


def make_client(folder: Path, tmp_path: Path):
    config = load_config(folder)
    config["push_enabled"] = False
    config["owner_email"] = config.get("owner_email") or "me@example.com"
    app = create_app(folder, config)
    app.state.setup_platform = "linux"
    app.state.schedule_home = tmp_path / "home"
    app.state.calendar_url = lambda refresh=False: ""
    return app, TestClient(app, follow_redirects=False)


def token(client) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get("/settings").text).group(1)


def git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True,
                          check=True).stdout


def subjects(folder: Path, n: int = 8) -> list[str]:
    return git(folder, "log", f"-{n}", "--format=%s").splitlines()


def files_of(folder: Path, rev: str = "HEAD") -> set[str]:
    return set(git(folder, "show", "--name-only", "--format=", rev).split())


def cfg(folder: Path) -> dict:
    return tomllib.loads((folder / "config.toml").read_text(encoding="utf-8"))


def form(rows, **extra):
    """The Settings form for `rows` [(name, role, old, valued)], plus a blank add row."""
    rows = list(rows) + [("", "open", "", False)]
    data = {"name": [r[0] for r in rows], "role": [r[1] for r in rows],
            "old": [r[2] for r in rows],
            "valued": [str(i) for i, r in enumerate(rows) if r[3]]}
    data.update(extra)
    return data


def default_rows():
    return [(c["name"], c["role"], c["name"], bool(c.get("valued"))) for c in DEFAULT_ROWS]


def column_order(html: str) -> list[str]:
    return re.findall(r'<section class="column[^"]*" id="col-([^"]+)"', html)


# ----------------------------------------------------------------- the Settings section


def test_settings_shows_the_stages_with_roles_and_counts(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    page = client.get("/settings").text
    assert '<section class="setup-step" id="stages">' in page
    assert 'action="/settings/stages"' in page
    for name in st.DEFAULT_STAGES.names:
        assert f'name="old" value="{name}"' in page
    assert '<option value="parked" selected>parked</option>' in page
    # It sits in the "Your CRM" tab, after task types.
    assert page.index('id="tab-crm"') < page.index('id="task-types"') < page.index(
        'id="stages"') < page.index('id="outcomes"') < page.index('id="tab-backup"')


def test_unchanged_form_saves_without_touching_any_company(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    t = token(client)
    r = client.post("/settings/stages", data=form(default_rows(), csrf_token=t))
    assert r.status_code == 303 and r.headers["location"] == "/settings?flash=Stages%20saved#stages"
    assert app.state.store.stages == st.DEFAULT_STAGES
    assert not [s for s in subjects(demo, 3) if "renamed" in s or "removed" in s
                or "written out" in s]
    assert cfg(demo)["stages"] == DEFAULT_ROWS      # the defaults, written down


def test_rename_insert_and_drop_in_one_save(demo, tmp_path):
    """The brief's scenario: engaged to contacted, a new qualified stage after it,
    and temp-disqualified dropped (its company moves to prospect)."""
    app, client = make_client(demo, tmp_path)
    store = app.state.store
    t = token(client)
    rows = default_rows()
    rows[1] = ("contacted", "open", "engaged", False)
    rows.insert(2, ("qualified", "open", "", False))
    drop = len(rows) - 1                                    # temp-disqualified

    # A stage that still has companies asks where they go.
    r = client.post("/settings/stages", data=form(rows, csrf_token=t, delete=str(drop)))
    assert r.status_code == 400
    assert "still in temp-disqualified" in r.text and 'name="move_to"' in r.text
    assert store.stages == st.DEFAULT_STAGES               # nothing was saved
    assert "stages" not in cfg(demo)

    r = client.post("/settings/stages", data=form(
        rows, csrf_token=t, delete=str(drop), move_to="prospect"))
    assert r.status_code == 303, r.text
    assert store.stages.names == ["prospect", "contacted", "qualified", "discovery", "offer",
                                  "won", "lost", "disqualified"]
    assert [s["name"] for s in cfg(demo)["stages"]][:3] == ["prospect", "contacted", "qualified"]

    # Companies and their histories were rewritten, in commits of their own.
    copperleaf = store.companies["copperleaf-studio"]
    assert copperleaf.stage == "contacted"
    assert all("engaged" not in (e.from_stage, e.to_stage) for e in copperleaf.stage_history)
    assert store.companies["glasshouse-health"].stage == "prospect"
    # One commit takes it all: the config line, the companies and PIPELINE.md.
    before = subjects(demo, 2)[1]
    assert subjects(demo, 1) == [
        'settings: stages: renamed "engaged" to "contacted", removed "temp-disqualified" '
        "(6 companies rewritten, 1 moved)"]
    assert {"config.toml", "PIPELINE.md", "companies/copperleaf-studio/company.md",
            "companies/glasshouse-health/company.md"} <= files_of(demo)
    assert "temp-disqualified" not in before          # the commit before is not part of it
    assert "from: engaged" not in (demo / "companies" / "copperleaf-studio"
                                   / "company.md").read_text()

    # The board, PIPELINE.md and `check` agree.
    assert column_order(client.get("/pipeline").text) == [
        "prospect", "contacted", "qualified", "discovery", "offer"]
    pipeline_md = (demo / "PIPELINE.md").read_text()
    assert "## contacted (1)" in pipeline_md and "## qualified (0)" in pipeline_md
    assert "## Temp disqualified" not in pipeline_md
    # The demo dashboard still filters on "engaged": Hermit does not rewrite your
    # TOML, so `check` names it (and the Settings flash did too).
    text, code = cli.cmd_check(cli.build_store(demo))
    assert code == 1 and "monday-review.toml" in text and "unknown value 'engaged'" in text
    assert all(line.startswith("dashboards/monday-review.toml") for line in text.splitlines())
    assert "monday-review.toml" in r.headers["location"]
    dash = demo / "dashboards" / "monday-review.toml"
    dash.write_text(dash.read_text().replace("engaged", "contacted"), encoding="utf-8")
    text, code = cli.cmd_check(cli.build_store(demo))
    assert code == 0 and text.startswith("OK:"), text


def test_a_new_first_stage_writes_the_implied_history_first(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    store = app.state.store
    assert store.companies["tallpine-software"].stage_history == []   # implied start
    t = token(client)
    rows = [("inbox", "open", "", False)] + default_rows()
    r = client.post("/settings/stages", data=form(rows, csrf_token=t))
    assert r.status_code == 303
    assert store.stages.entry == "inbox"
    tall = store.companies["tallpine-software"]
    assert [(e.from_stage, e.to_stage) for e in tall.stage_history] == [("", "prospect")]
    # The start of the old history went into the same commit as the new stage list.
    assert subjects(demo, 1) == ["settings: stages changed"]
    assert {"config.toml", "companies/tallpine-software/company.md"} <= files_of(demo)
    assert [(e.from_stage, e.to_stage) for e in tall.stage_entries()] == [("", "prospect")]


def test_reorder_with_up_and_down(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    t = token(client)
    r = client.post("/settings/stages", data=form(default_rows(), csrf_token=t, move="3-up"))
    assert r.status_code == 303
    assert app.state.store.stages.open == ["prospect", "engaged", "offer", "discovery"]
    assert column_order(client.get("/pipeline").text) == [
        "prospect", "engaged", "offer", "discovery"]


def test_deleting_an_empty_stage_needs_no_move(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    t = token(client)
    rows = default_rows() + [("watching", "open", "", False)]
    assert client.post("/settings/stages", data=form(rows, csrf_token=t)).status_code == 303
    assert "watching" in app.state.store.stages
    idx = len(rows) - 1
    r = client.post("/settings/stages", data=form(rows, csrf_token=t, delete=str(idx)))
    assert r.status_code == 303 and "watching" not in app.state.store.stages


def test_moving_companies_into_a_lost_stage_asks_for_a_reason(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    t = token(client)
    rows = default_rows()
    drop = [r[0] for r in rows].index("engaged")
    r = client.post("/settings/stages", data=form(
        rows, csrf_token=t, delete=str(drop), move_to="lost"))
    assert r.status_code == 400 and "needs a reason" in r.text
    assert app.state.store.companies["copperleaf-studio"].stage == "engaged"
    r = client.post("/settings/stages", data=form(
        rows, csrf_token=t, delete=str(drop), move_to="lost", move_reason="stage retired"))
    assert r.status_code == 303
    assert app.state.store.companies["copperleaf-studio"].stage == "lost"
    assert app.state.store.companies["copperleaf-studio"].lost_reason == "stage retired"


def test_a_stage_cannot_become_lost_while_its_companies_have_no_reason(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    t = token(client)
    rows = default_rows()
    rows[1] = ("engaged", "lost", "engaged", False)
    r = client.post("/settings/stages", data=form(rows, csrf_token=t))
    assert r.status_code == 400 and "have no reason" in r.text
    assert app.state.store.stages == st.DEFAULT_STAGES


def test_bad_stage_forms_are_refused_and_nothing_changes(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    t = token(client)
    before = (demo / "config.toml").read_text()
    for rows, needle in (
        (default_rows() + [("prospect", "open", "", False)], "Duplicate stage"),
        (default_rows() + [("yes", "open", "", False)], "reserved"),
        ([(n, "won", o, False) for n, _, o, _ in default_rows()], "At least one stage"),
    ):
        r = client.post("/settings/stages", data=form(rows, csrf_token=t))
        assert r.status_code == 400 and needle in r.text, needle
    assert (demo / "config.toml").read_text() == before
    assert client.post("/settings/stages", data={"name": ["x"]}).status_code == 403


def test_flash_names_the_dashboards_and_routines_that_still_use_an_old_name(demo, tmp_path):
    (demo / "routines.toml").write_text(
        '[[routine]]\nname = "x"\nfilters = { stage = "engaged" }\n', encoding="utf-8")
    app, client = make_client(demo, tmp_path)
    t = token(client)
    rows = default_rows()
    rows[1] = ("contacted", "open", "engaged", False)
    r = client.post("/settings/stages", data=form(rows, csrf_token=t))
    assert r.status_code == 303
    assert "routines.toml" in r.headers["location"].replace("%2E", ".")


# --------------------------------------------------------------- the board and the pages


def custom_folder(tmp_path, line: str) -> Path:
    folder = init_folder(tmp_path / "f", demo=False)
    with open(folder / "config.toml", "a", encoding="utf-8") as fh:
        fh.write("\n" + line + "\n")
    return folder


FIVE_LINE = ('stages = [{name = "lead", role = "open"}, {name = "contacted", role = "open"}, '
             '{name = "qualified", role = "open"}, {name = "proposal", role = "open", '
             'valued = true}, {name = "negotiation", role = "open", valued = true}, '
             '{name = "closed-won", role = "won"}, {name = "closed-lost", role = "lost"}, '
             '{name = "dead", role = "closed"}, {name = "snoozed", role = "parked"}]')


def test_the_board_has_a_column_per_open_stage_and_lists_per_other_stage(tmp_path):
    folder = custom_folder(tmp_path, FIVE_LINE)
    app, client = make_client(folder, tmp_path)
    app.state.store.create_company("Acme", stage="negotiation")
    html = client.get("/pipeline").text
    assert column_order(html) == ["lead", "contacted", "qualified", "proposal", "negotiation"]
    assert re.findall(r'<details class="closed" id="closed-([^"]+)"', html) == [
        "closed-won", "closed-lost", "dead", "snoozed"]
    # The card's own stage menu offers the configured names.
    assert '<option value="qualified"' in html and '<option value="engaged"' not in html


def test_new_company_form_starts_in_the_entry_stage(tmp_path):
    folder = custom_folder(tmp_path, FIVE_LINE)
    app, client = make_client(folder, tmp_path)
    html = client.get("/companies/new").text
    assert '<option value="lead" selected>lead</option>' in html
    r = client.post("/companies", data={"name": "Acme"})
    assert r.status_code == 303
    assert app.state.store.companies["acme"].stage == "lead"


def test_company_page_offers_the_closed_and_parked_stages_and_requalifies_to_entry(tmp_path):
    folder = custom_folder(tmp_path, FIVE_LINE)
    app, client = make_client(folder, tmp_path)
    store = app.state.store
    store.create_company("Acme", stage="qualified")
    page = client.get("/companies/acme").text
    assert 'summary class="button">Close or park' in page
    assert 'value="dead"' in page and ">Dead</button>" in page
    assert 'value="snoozed"' in page and ">Snoozed</button>" in page
    assert "goes back to lead on this date" in page
    assert 'value="closed-lost"' not in page.split("stage-menu")[1].split("</details>")[0]

    r = client.post("/companies/acme/disqualify", data={
        "stage": "snoozed", "reason": "after summer", "requalify_on": "2026-12-01"})
    assert r.status_code == 303
    assert r.headers["location"] == "/companies/acme?flash=Snoozed%20until%202026-12-01"
    assert store.companies["acme"].stage == "snoozed"
    assert store.companies["acme"].requalify_on.isoformat() == "2026-12-01"
    page = client.get("/companies/acme").text
    assert ">Requalify</button>" in page and 'name="stage" value="lead"' in page

    r = client.post("/companies/acme/disqualify", data={"stage": "lead"})
    assert store.companies["acme"].stage == "lead"
    assert "Requalified" in r.headers["location"]
    # Won and lost are not exits of this menu.
    r = client.post("/companies/acme/disqualify", data={"stage": "closed-won"})
    assert "unknown" in r.headers["location"] and store.companies["acme"].stage == "lead"


def test_default_names_keep_the_familiar_buttons(demo, tmp_path):
    app, client = make_client(demo, tmp_path)
    page = client.get("/companies/tallpine-software").text
    assert page.count('summary class="button">Disqualify') == 1
    assert ">Temp disqualify</button>" in page and ">Disqualify</button>" in page


def test_a_lost_stage_other_than_the_first_names_itself_in_the_reason_redirect(tmp_path):
    folder = custom_folder(
        tmp_path, 'stages = [{name = "lead", role = "open"}, {name = "lost-price", role = '
                  '"lost"}, {name = "lost-fit", role = "lost"}]')
    app, client = make_client(folder, tmp_path)
    app.state.store.create_company("Acme")
    r = client.post("/companies/acme/stage", data={"stage": "lost-price"})
    assert r.headers["location"] == "/companies/acme?focus=lost_reason"
    r = client.post("/companies/acme/stage", data={"stage": "lost-fit"})
    assert r.headers["location"] == "/companies/acme?focus=lost_reason&stage=lost-fit"
    html = client.get(r.headers["location"]).text
    assert 'stage.value = "lost-fit"' in html
    # Without a reason the store still refuses; with one it goes through.
    r = client.post("/companies/acme", data={"name": "Acme", "stage": "lost-fit",
                                              "lost_reason": "too small"})
    assert app.state.store.companies["acme"].stage == "lost-fit"


def test_companies_list_toggle_names_the_parked_stage(tmp_path):
    folder = custom_folder(tmp_path, FIVE_LINE)
    app, client = make_client(folder, tmp_path)
    app.state.store.create_company("Acme", stage="snoozed")
    html = client.get("/companies").text
    assert "Show snoozed (1)" in html and ">Acme</a>" not in html     # hidden by default
    shown = client.get("/companies?parked=1").text
    assert "Hide snoozed" in shown and ">Acme</a>" in shown


def test_no_parked_stage_means_no_toggle(tmp_path):
    folder = custom_folder(tmp_path, 'stages = [{name = "a", role = "open"}, '
                                      '{name = "b", role = "won"}]')
    app, client = make_client(folder, tmp_path)
    assert "toggle-parked" not in client.get("/companies").text


# ------------------------------------------------------------- hot reload / hand edits


def test_editing_config_toml_by_hand_changes_the_app_without_a_restart(tmp_path):
    folder = custom_folder(tmp_path, 'stages = [{name = "a", role = "open"}, '
                                      '{name = "b", role = "open"}]')
    app, client = make_client(folder, tmp_path)
    assert column_order(client.get("/pipeline").text) == ["a", "b"]
    text = (folder / "config.toml").read_text().replace(
        '{name = "b", role = "open"}]', '{name = "b", role = "open"}, '
        '{name = "c", role = "open"}, {name = "done", role = "won"}]')
    (folder / "config.toml").write_text(text, encoding="utf-8")
    assert column_order(client.get("/pipeline").text) == ["a", "b", "c"]
    assert app.state.store.stages.names == ["a", "b", "c", "done"]
    assert '<option value="c"' in client.get("/companies/new").text   # the macro's list too


def test_a_broken_stages_line_keeps_the_old_stages_and_says_why(tmp_path):
    folder = custom_folder(tmp_path, 'stages = [{name = "a", role = "open"}]')
    app, client = make_client(folder, tmp_path)
    text = (folder / "config.toml").read_text().replace(
        '[{name = "a", role = "open"}]', '[{name = "a", role = "won"}]')
    (folder / "config.toml").write_text(text, encoding="utf-8")
    html = client.get("/pipeline").text
    assert app.state.store.stages.names == ["a"] and column_order(html) == ["a"]
    assert "at least one stage with role open" in html


def test_a_company_in_a_removed_stage_stays_visible_and_the_app_says_so(tmp_path):
    folder = custom_folder(tmp_path, 'stages = [{name = "a", role = "open"}, '
                                      '{name = "b", role = "open"}]')
    app, client = make_client(folder, tmp_path)
    app.state.store.create_company("Acme", stage="b")
    text = (folder / "config.toml").read_text().replace(
        ', {name = "b", role = "open"}', "")
    (folder / "config.toml").write_text(text, encoding="utf-8")
    html = client.get("/companies").text
    assert "1 company is in a stage that is not in Settings:</strong>" in html
    assert "b (1)" in html
    assert 'class="off-board"' in html and "Acme" in html
    # Editing the company keeps its stage until someone picks a configured one.
    page = client.get("/companies/acme").text
    assert 'value="b" selected>b (not in Settings)' in page
    assert column_order(client.get("/pipeline").text) == ["a"]


def test_one_undo_takes_a_whole_stage_change_back(demo, tmp_path):
    """The config line and the rewritten companies are one commit, so undoing it
    cannot leave config.toml and the company files disagreeing."""
    app, client = make_client(demo, tmp_path)
    t = token(client)
    rows = default_rows()
    rows[1] = ("contacted", "open", "engaged", False)
    assert client.post("/settings/stages", data=form(rows, csrf_token=t)).status_code == 303
    sha = git(demo, "rev-parse", "HEAD").strip()
    assert app.state.store.companies["copperleaf-studio"].stage == "contacted"

    code = cli.main(["undo", sha], root=demo)
    assert code == 0
    assert "stages" not in cfg(demo)
    text = (demo / "companies" / "copperleaf-studio" / "company.md").read_text()
    assert "stage: engaged" in text and "contacted" not in text
    assert client.get("/pipeline").status_code == 200       # the app re-reads the file
    assert app.state.store.stages == st.DEFAULT_STAGES
    store = cli.build_store(demo)
    assert cli.cmd_check(store)[1] == 0 and store.off_board() == []
