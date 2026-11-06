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

"""Disqualifying a company and skipping outreach as one idea, in the browser: the
Disqualify form asks about open drafts, a batch lists the companies it left out
and takes them back on request, one Generate click drafts for a closed company
with a warning, and Skip as bad-fit offers to disqualify. The AI is a fake; all
names are made up."""

from __future__ import annotations

import re

from hermitcrm import outreach
from outreach_client import MARA, client, commits, drafted, post, query, root, fake  # noqa: F401
from outreach_fakes import NOW

KESTREL = "kestrel-metrics/daan-visser"


def store_of(client):
    return client.app.state.store


def company_page(client, slug="lindenhof-data") -> str:
    return client.get(f"/companies/{slug}").text


def open_item(root, company, contact, state="drafted"):
    item = outreach.Item(id=f"2026-10-15T0900-email-{company}-{contact}", state=state,
                         company=company, contact=contact, created=NOW, body="Hi.\n")
    outreach.write_item(root, item)
    return item


# ------------------------------------------------------ the Disqualify form


def test_the_form_asks_about_open_drafts_and_ticks_the_box(client, root):
    drafted(client, root)
    page = company_page(client)
    box = re.search(r'<label class="inline skip-drafts">.*?</label>', page, re.S).group(0)
    assert "1 open outreach draft" in box and "checked" in box and 'name="skip_drafts"' in box
    assert 'name="asked_drafts" value="1"' in page
    assert "skip_drafts" not in company_page(client, "kestrel-metrics")     # nothing to ask


def test_ticked_the_drafts_are_skipped_and_the_flash_says_how_many(client, root):
    item = drafted(client, root)
    response = post(client, "/companies/lindenhof-data/disqualify", stage="disqualified",
                    reason="no fit", asked_drafts="1", skip_drafts="1")
    assert response.status_code == 303
    assert "1 open outreach draft skipped" in query(response)["flash"]
    again = outreach.get_item(root, item.id)
    assert again.state == "skipped" and again.skip_reason == "company-closed"
    assert store_of(client).get("lindenhof-data").stage == "disqualified"


def test_unticked_the_drafts_stay(client, root):
    item = drafted(client, root)
    post(client, "/companies/lindenhof-data/disqualify", stage="temp-disqualified",
         reason="later", requalify_on="2027-03-01", asked_drafts="1")
    assert outreach.get_item(root, item.id).state == "drafted"
    assert store_of(client).get("lindenhof-data").stage == "temp-disqualified"


def test_a_post_without_the_question_skips_by_default(client, root):
    item = drafted(client, root)
    post(client, "/companies/lindenhof-data/disqualify", stage="disqualified", reason="no")
    assert outreach.get_item(root, item.id).state == "skipped"


def test_requalifying_asks_nothing_and_revives_nothing(client, root):
    item = drafted(client, root)
    post(client, "/companies/lindenhof-data/disqualify", stage="disqualified", reason="no",
         asked_drafts="1", skip_drafts="1")
    assert "skip_drafts" not in company_page(client)
    post(client, "/companies/lindenhof-data/disqualify", stage="prospect")
    assert outreach.get_item(root, item.id).state == "skipped"


# --------------------------------- a batch leaves them out; one click does not


def close_kestrel(client):
    store_of(client).update_company("kestrel-metrics", stage="disqualified")


def test_the_preview_lists_the_left_out_with_a_box_each_off_by_default(client, root):
    close_kestrel(client)
    page = client.get("/outreach", params={"preview": "1", "where": "stage=disqualified"}).text
    assert "Left out: their company is not open (1)" in page
    box = re.search(r'<input type="checkbox"[^>]*name="include_closed"[^>]*>', page).group(0)
    assert f'value="{KESTREL}"' in box and "checked" not in box
    assert 'form="outreach-build"' in box and "disqualified" in page


def test_a_build_without_the_box_builds_nothing_and_says_why(client, root, fake):
    close_kestrel(client)
    response = post(client, "/outreach/build", where="stage=disqualified", limit="3")
    assert "left out because their company is not open" in query(response)["flash"]
    assert outreach.items(root) == [] and fake.calls == []


def test_a_confirmed_contact_is_built_and_stays_confirmed_through_the_loop(client, root):
    close_kestrel(client)
    response = post(client, "/outreach/build", where="stage=disqualified", limit="3",
                    include_closed=[KESTREL])
    assert response.status_code == 303
    item, = outreach.items(root)
    assert item.record == KESTREL and item.stage_override == "disqualified"
    assert any("its company is disqualified" in f for f in item.flags)
    assert "include_closed=kestrel-metrics%2Fdaan-visser" in response.headers["location"]
    # the loop asks again for the next one with the same confirmation: nobody else is there
    assert query(response)["left"] == "2"


def test_a_stale_confirmation_for_someone_else_changes_nothing(client, root):
    close_kestrel(client)
    response = post(client, "/outreach/build", where="stage=disqualified", limit="3",
                    include_closed=["lindenhof-data/mara-keller", "not a record"])
    assert outreach.items(root) == []
    assert "Nothing to build" in query(response)["flash"] or "left out" in query(response)["flash"]


def test_one_generate_click_drafts_for_a_closed_company_with_a_warning(client, root, fake):
    close_kestrel(client)
    panel = re.search(r'<section id="generate".*?</section>',
                      client.get(f"/outreach?contact={KESTREL}").text, re.S).group(0)
    assert "Kestrel Metrics is disqualified" in panel and "drafted on purpose" in panel
    response = post(client, "/outreach/build", contact=KESTREL, back="/outreach")
    assert response.status_code == 303
    item, = outreach.items(root)
    assert item.state == "drafted" and item.stage_override == "disqualified"
    assert any("disqualified" in f for f in item.flags)
    assert "its company is disqualified" in client.get("/outreach?tab=drafts").text


def test_a_company_that_is_open_gets_no_generate_warning(client):
    panel = re.search(r'<section id="generate".*?</section>',
                      client.get(f"/outreach?contact={MARA}").text, re.S).group(0)
    assert "generate-stage-note" not in panel


# ---------------------------------------------------------- Skip offers it


def test_bad_fit_with_the_box_disqualifies_and_skips_the_rest(client, root):
    item = drafted(client, root)
    other = open_item(root, "lindenhof-data", "someone-else", state="ready")
    page = client.get("/outreach?tab=drafts").text
    box = re.search(r'<label class="check small outreach-skip-disqualify">.*?</label>', page,
                    re.S).group(0)
    assert "Also disqualify Lindenhof Data" in box and "disqualified" in box
    assert "checked" not in box                                         # default off
    response = post(client, f"/outreach/{item.id}/skip", reason="bad-fit", note="sells b2c",
                    disqualify="1")
    flash = query(response)["flash"]
    assert "Skipped: bad-fit" in flash and "now disqualified" in flash
    company = store_of(client).get("lindenhof-data")
    assert company.stage == "disqualified" and company.lost_reason == "sells b2c"
    assert outreach.get_item(root, item.id).skip_reason == "bad-fit"
    cascaded = outreach.get_item(root, other.id)
    assert cascaded.state == "skipped" and cascaded.skip_reason == "company-closed"
    assert "1 open outreach draft skipped" in flash


def test_the_box_off_leaves_the_stage_alone(client, root):
    item = drafted(client, root)
    post(client, f"/outreach/{item.id}/skip", reason="bad-fit")
    assert store_of(client).get("lindenhof-data").stage == "prospect"


def test_only_bad_fit_acts_on_the_box(client, root):
    item = drafted(client, root)
    post(client, f"/outreach/{item.id}/skip", reason="bad-timing", disqualify="1")
    assert store_of(client).get("lindenhof-data").stage == "prospect"


def test_the_box_is_not_offered_for_a_company_that_is_not_open(client, root):
    close_kestrel(client)
    post(client, "/outreach/build", contact=KESTREL, back="/outreach")
    page = client.get("/outreach?tab=drafts").text
    assert "outreach-skip-disqualify" not in page


def test_the_box_is_hidden_when_the_folder_has_no_closed_stage(client, root):
    drafted(client, root)
    store = store_of(client)
    from hermitcrm import stages as st
    store.set_stages(st.from_config([{"name": "prospect", "role": "open"},
                                     {"name": "won", "role": "won"},
                                     {"name": "snoozed", "role": "parked"}]))
    assert outreach.disqualify_stage(store, "lindenhof-data") == ""
