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

"""The company form: fields in labelled groups on a grid, the closing details
shown only for a stage that keeps them (templates/macros.html company_fields)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm.datafolder import init_folder
from hermitcrm.store import load_config
from hermitcrm.web import create_app


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return init_folder(tmp_path / "f", demo=False)


def make_client(folder: Path, tmp_path: Path):
    config = load_config(folder)
    config["push_enabled"] = False
    config["owner_email"] = config.get("owner_email") or "me@example.com"
    app = create_app(folder, config)
    app.state.setup_platform = "linux"
    app.state.schedule_home = tmp_path / "home"
    app.state.calendar_url = lambda refresh=False: ""
    return app, TestClient(app, follow_redirects=False)


def form_of(html: str) -> str:
    match = re.search(r'<form method="post" action="/companies/[^"]+" class="record-form">.*?</form>',
                      html, re.S)
    assert match, "no company form on the page"
    return match.group(0)


def closing_tag(form: str) -> str:
    """The opening tag of the closing-details group, so `hidden` can be read."""
    return re.search(r'<fieldset class="form-group" id="closing-fields"[^>]*>', form).group(0)


def label_tag(form: str, field: str) -> str:
    return re.search(rf'<label [^>]*id="{field}-label"[^>]*>', form).group(0)


def legends(form: str) -> list[str]:
    return re.findall(r"<legend>([^<]+)</legend>", form)


def test_the_fields_come_in_labelled_groups_on_a_grid(folder, tmp_path):
    app, client = make_client(folder, tmp_path)
    app.state.store.create_company("Acme", stage="engaged")
    form = form_of(client.get("/companies/acme").text)
    assert legends(form) == ["Closing details", "Profile", "Next step", "Tags and notes"]
    assert "form-grid" in form and 'class="span-6"' in form
    # No long rows of the old layout are left in this form.
    assert 'class="row"' not in form


def test_closing_details_are_hidden_for_an_open_stage_but_still_in_the_form(folder, tmp_path):
    app, client = make_client(folder, tmp_path)
    app.state.store.create_company("Acme", stage="engaged")
    form = form_of(client.get("/companies/acme").text)
    assert " hidden" in closing_tag(form)
    # Hidden, not removed: the inputs still submit what they hold.
    assert 'name="lost_reason"' in form and 'name="requalify_on"' in form


def test_closing_details_show_for_a_closed_stage_without_the_date(folder, tmp_path):
    app, client = make_client(folder, tmp_path)
    app.state.store.create_company("Acme", stage="disqualified", lost_reason="no budget")
    form = form_of(client.get("/companies/acme").text)
    assert " hidden" not in closing_tag(form)
    assert " hidden" not in label_tag(form, "lost_reason")
    assert " hidden" in label_tag(form, "requalify_on")


def test_closing_details_show_the_date_for_a_parked_stage(folder, tmp_path):
    app, client = make_client(folder, tmp_path)
    app.state.store.create_company("Acme", stage="temp-disqualified")
    form = form_of(client.get("/companies/acme").text)
    assert " hidden" not in closing_tag(form)
    assert " hidden" not in label_tag(form, "lost_reason")
    assert " hidden" not in label_tag(form, "requalify_on")


def post_company(client, slug: str, **fields):
    page = client.get(f"/companies/{slug}").text
    data = {"version": re.search(r'name="version" value="([^"]*)"', page).group(1),
            "name": "Acme", "source": "other", **fields}
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page)
    if csrf:
        data["csrf_token"] = csrf.group(1)
    return client.post(f"/companies/{slug}", data=data)


def test_a_typed_reason_stays_visible_when_the_save_comes_back_with_an_error(folder, tmp_path):
    # The store drops a reason on a stage that keeps none, so the only way a
    # reason sits in the form on an open stage is a form sent back for a fix.
    app, client = make_client(folder, tmp_path)
    app.state.store.create_company("Acme", stage="engaged")
    r = post_company(client, "acme", stage="engaged", lost_reason="typed before switching",
                     next_step_due="not-a-date")
    assert r.status_code != 303
    form = form_of(r.text)
    assert " hidden" not in closing_tag(form)
    assert " hidden" not in label_tag(form, "lost_reason")
    assert "typed before switching" in form
    assert " hidden" in label_tag(form, "requalify_on")


def test_the_stage_select_says_which_stages_keep_what(folder, tmp_path):
    app, client = make_client(folder, tmp_path)
    app.state.store.create_company("Acme", stage="engaged")
    form = form_of(client.get("/companies/acme").text)
    raw = re.search(r"""<select name="stage" id="stage" data-keeps='([^']*)'""", form).group(1)
    assert json.loads(raw.replace("&#34;", '"')) == {
        "lost": "reason", "disqualified": "reason",
        "temp-disqualified": "reason requalify"}
    # The options themselves are as before.
    assert '<option value="engaged" selected>engaged</option>' in form


def test_the_name_field_asks_password_managers_to_keep_out(folder, tmp_path):
    app, client = make_client(folder, tmp_path)
    app.state.store.create_company("Acme")
    form = form_of(client.get("/companies/acme").text)
    name = re.search(r'<input name="name"[^>]*>', form).group(0)
    assert 'autocomplete="off"' in name and "data-lpignore" in name and "data-1p-ignore" in name


def test_hidden_fields_leave_their_group_and_an_empty_group_leaves_with_them(folder, tmp_path):
    (folder / "layout.toml").write_text(
        '[company]\nhide_fields = ["lost_reason", "requalify_on", "value_eur_month", '
        '"product_oneliner", "next_step", "next_step_due", "next_step_status", '
        '"next_step_type", "tags"]\n', encoding="utf-8")
    app, client = make_client(folder, tmp_path)
    app.state.store.create_company("Acme", stage="disqualified")
    form = form_of(client.get("/companies/acme").text)
    # Closing details, Profile (nothing left) and Next step are gone; notes stay.
    assert legends(form) == ["Tags and notes"]
    assert 'id="closing-fields"' not in form and 'name="notes"' in form
    assert 'name="lost_reason"' not in form and 'name="next_step"' not in form


def test_the_new_company_form_has_the_same_groups(folder, tmp_path):
    _, client = make_client(folder, tmp_path)
    html = client.get("/companies/new").text
    assert "form-grid" in html and "<legend>Profile</legend>" in html
    assert " hidden" in closing_tag(html)
    assert 'data-lpignore="true"' in html


def test_a_closed_company_still_saves_its_reason(folder, tmp_path):
    app, client = make_client(folder, tmp_path)
    store = app.state.store
    store.create_company("Acme", stage="engaged")
    r = post_company(client, "acme", stage="disqualified", lost_reason="no budget")
    assert r.status_code == 303, r.text[:300]
    assert store.get("acme").lost_reason == "no budget"
    assert store.get("acme").stage == "disqualified"
