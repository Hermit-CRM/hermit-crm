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

"""`hermitcrm set` (hermitcrm/bulk.py): a dry run first, then one commit.

The folder is a real git repository (init_folder), so the tests can say what the
commit contains and that a failed change leaves the tree byte for byte as it was.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from hermitcrm import bulk
from hermitcrm import cli as crm
from hermitcrm import pipeline
from hermitcrm.bulk import ApplyError, BulkError, Ops
from hermitcrm.datafolder import init_folder
from hermitcrm.gitops import GitOps
from hermitcrm.models import StageChange
from hermitcrm.store import Store, load_config, split_file
from hermitcrm.web import create_app
from conftest import FIXED_NOW

FIELDS = """\
[[field]]
key = "my_score"
type = "number"
show_in = ["detail", "companies"]

[[field]]
key = "fte_estimate"
type = "text"
show_in = ["detail"]

[[field]]
key = "tier"
type = "select"
options = ["a", "b", "c"]
show_in = ["detail", "companies"]

[[field]]
key = "seniority"
type = "select"
options = ["junior", "senior"]
applies_to = "contact"
show_in = ["detail", "contacts"]

[[field]]
key = "template"
type = "text"
applies_to = "interaction"
show_in = ["detail", "messages"]
"""


# ------------------------------------------------------------------- fixtures


def git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    assert done.returncode == 0, (args, done.stderr)
    return done.stdout


def commit_all(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-qm", message)


def tree(root: Path) -> dict:
    """Every file outside .git, by path, with its bytes."""
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts}


def commit_count(root: Path) -> int:
    return int(git(root, "rev-list", "--count", "HEAD"))


def head_files(root: Path) -> set:
    return set(git(root, "show", "--name-only", "--format=", "HEAD").split())


def subject(root: Path) -> str:
    return git(root, "log", "-1", "--format=%s").strip()


def seed(store: Store) -> None:
    """Six companies, four people, three messages, on the suite's fixed day."""
    s = store
    s.create_company("Acme GmbH", country="DE", source="referral", tags="saas",
                     website="acme.example.com",
                     custom={"my_score": 80, "fte_estimate": "~45", "tier": "a"})
    s.create_company("Beta AG", country="DE", tags="fintech", custom={"my_score": 40})
    s.create_company("Gamma BV", country="NL", custom={"my_score": 90, "tier": "b"})
    s.create_company("Delta SAS", country="FR", tags="priority, saas", stage="discovery",
                     custom={"my_score": 55})
    s.create_company("Epsilon Ltd", country="GB")
    s.create_company("Zeta Inc", country="FI")
    s.update_company("zeta", stage="temp-disqualified", lost_reason="later",
                     requalify_on="2026-12-01")
    s.create_contact("acme", "Jane", "Doe", title="CEO", email="jane@acme.example.com",
                     phone="+31 20 555 0100", custom={"seniority": "senior"})
    s.create_contact("acme", "Joe", "Roe", title="CTO")
    s.create_contact("beta", "Kim", "Lee")
    s.create_contact("gamma", "Lou", "Ray", title="CFO")
    s.create_contact("delta", "Dee", "Fox", title="COO")
    s.add_task("acme", "Send the deck", due="2026-09-20", contact="jane-doe")
    for slug, who, channel, when, body in [
        ("acme", "jane-doe", "linkedin", "2026-09-12T09:00", "Hi Jane,\n\nWorth a call?\n"),
        ("acme", "joe-roe", "email", "2026-08-20T09:00", "Hi Joe,\n\nA short note.\n"),
        ("beta", "kim-lee", "linkedin", "2026-08-20T10:00", "Hi Kim,\n\nHello.\n"),
        ("delta", "dee-fox", "linkedin", "2026-09-13T11:00", "Hi Dee,\n\nHello.\n"),
    ]:
        s.create_interaction(slug, channel, "out", contact=who, date=when, body=body,
                             subject="Intro")
    s.create_interaction("acme", "linkedin", "in", contact="jane-doe", date="2026-09-13T08:00",
                         body="Sure, Thursday.\n")
    # Keys Hermit does not know are the user's (or another tool's), and must survive.
    path = tmp_company(s, "epsilon")
    path.write_text(path.read_text().replace("---\n", "---\nzz_tool: 1\naa_owner: me\n", 1))


def tmp_company(store: Store, slug: str) -> Path:
    return store.company_dir(slug) / "company.md"


@pytest.fixture(scope="module")
def template(tmp_path_factory) -> Path:
    """One seeded folder, built once and copied for every test."""
    root = init_folder(tmp_path_factory.mktemp("bulk") / "crm")
    (root / "fields.toml").write_text(FIELDS, encoding="utf-8")
    with open(root / "config.toml", "a", encoding="utf-8") as fh:
        fh.write("\npush_enabled = false\n")
    config = load_config(root)
    store = Store(root, clock=lambda: FIXED_NOW, outcomes=config["outcomes"])
    store.load()
    seed(store)
    pipeline.write(store)
    commit_all(root, "seed")
    return root


@pytest.fixture
def root(template, tmp_path) -> Path:
    target = tmp_path / "crm"
    shutil.copytree(template, target)
    assert git(target, "status", "--porcelain") == ""
    return target


def make_store(root: Path) -> Store:
    store = Store(root, clock=lambda: FIXED_NOW, outcomes=load_config(root)["outcomes"])
    store.load()
    return store


@pytest.fixture
def store(root) -> Store:
    return make_store(root)


def run_plan(store, scope, where=(), **ops) -> bulk.Plan:
    return bulk.plan(store, scope, list(where), Ops(**ops))


def labels(plan: bulk.Plan) -> set:
    return {c.label for c in plan.changes}


def fresh(root: Path) -> Store:
    """A second store, read from disk: what the next process would see."""
    return make_store(root)


# ---------------------------------------------------------------- every operation


def test_companies_set_a_built_in_field(store, root):
    p = run_plan(store, "companies", ["country=DE"], set={"product_oneliner": "Big and shiny"})
    assert labels(p) == {"acme", "beta"}
    bulk.apply(store, p)
    again = fresh(root)
    assert again.get("acme").product_oneliner == "Big and shiny"
    assert again.get("beta").product_oneliner == "Big and shiny"
    assert again.get("gamma").product_oneliner == ""


def test_companies_set_is_coerced_the_way_the_forms_do(store, root):
    p = run_plan(store, "companies", ["name=beta"],
                 set={"website": "beta.example.com", "country": "uk", "value_eur_month": "1500",
                      "next_step_due": "2026-10-01", "next_step": "Call"})
    bulk.apply(store, p)
    beta = fresh(root).get("beta")
    assert beta.website == "https://beta.example.com"      # normalised
    assert beta.country == "GB"                            # alias and upper case
    assert beta.value_eur_month == 1500
    assert beta.next_due == date(2026, 10, 1)


def test_companies_unset(store, root):
    p = run_plan(store, "companies", ["name=acme"], unset=["website", "my_score"])
    assert {f.field for f in p.changes[0].fields} == {"website", "my_score"}
    bulk.apply(store, p)
    acme = fresh(root).get("acme")
    assert acme.website == "" and "my_score" not in acme.extra
    assert acme.extra["fte_estimate"] == "~45"             # the others stay


def test_companies_add_and_remove_tags(store, root):
    p = run_plan(store, "companies", ["country=DE"], add_tags=["priority", "Q4"])
    bulk.apply(store, p)
    again = fresh(root)
    assert again.get("acme").tags == ["saas", "priority", "Q4"]
    assert again.get("beta").tags == ["fintech", "priority", "Q4"]
    p = run_plan(store, "companies", ["tags=priority"], remove_tags=["PRIORITY", "saas"])
    bulk.apply(store, p)
    again = fresh(root)
    assert again.get("acme").tags == ["Q4"]                # case-insensitive
    assert again.get("delta").tags == []


def test_companies_stage_goes_through_the_stage_change_path(store, root):
    p = run_plan(store, "companies", ["name=gamma"], stage="discovery")
    bulk.apply(store, p)
    gamma = fresh(root).get("gamma")
    assert gamma.stage == "discovery"
    assert gamma.stage_changed == FIXED_NOW.date()
    assert gamma.stage_history[-1] == StageChange(FIXED_NOW.date(), "prospect", "discovery", "")
    # the same call the web app makes gives the same record
    store.update_company("epsilon", stage="discovery")
    web_way = fresh(root).get("epsilon")
    assert web_way.stage_history[-1] == StageChange(FIXED_NOW.date(), "prospect", "discovery", "")


def test_stage_rules_apply_lost_needs_a_reason_and_parking_clears_dates(store, root):
    with pytest.raises(BulkError) as exc:
        run_plan(store, "companies", ["name=gamma"], stage="lost")
    assert "lost_reason is required" in str(exc.value) and exc.value.code == 2
    p = run_plan(store, "companies", ["name=gamma"], stage="lost",
                 set={"lost_reason": "no budget"})
    bulk.apply(store, p)
    gamma = fresh(root).get("gamma")
    assert gamma.stage == "lost" and gamma.lost_reason == "no budget"
    assert gamma.stage_history[-1].reason == "no budget"
    # requalifying a parked company clears what only parking needs; the dry run says so
    p = run_plan(store, "companies", ["name=zeta"], stage="prospect")
    shown = {f.field: (f.before, f.after) for f in p.changes[0].fields}
    assert shown["stage"] == ("temp-disqualified", "prospect")
    assert shown["lost_reason"] == ("later", "(empty)")
    assert shown["requalify_on"] == ("2026-12-01", "(empty)")


def test_companies_custom_field_values_are_checked_like_the_form(store):
    with pytest.raises(BulkError, match="my_score|score"):
        run_plan(store, "companies", ["name=acme"], set={"my_score": "lots"})
    with pytest.raises(BulkError, match="tier"):
        run_plan(store, "companies", ["name=acme"], set={"tier": "z"})
    p = run_plan(store, "companies", ["name=acme"], set={"my_score": "7.5", "tier": "c"})
    assert {f.field: f.after for f in p.changes[0].fields} == {"my_score": "7.5", "tier": "c"}


def test_contacts_every_kind_of_change(store, root):
    p = run_plan(store, "contacts", ["company=acme"],
                 set={"role": "champion", "language": "nl", "seniority": "junior"},
                 unset=["phone"])
    assert labels(p) == {"acme/jane-doe", "acme/joe-roe"}
    bulk.apply(store, p)
    again = fresh(root).get("acme")
    jane, joe = again.contacts["jane-doe"], again.contacts["joe-roe"]
    assert (jane.role, jane.language, jane.extra["seniority"]) == ("champion", "nl", "junior")
    assert jane.phone == "" and joe.role == "champion"
    assert jane.title == "CEO"                              # untouched fields stay


def test_a_contacts_tasks_survive_a_change(store, root):
    """The Store used to drop a contact's tasks when it rewrote the contact."""
    before = fresh(root).get("acme").contacts["jane-doe"].tasks
    assert [t.text for t in before] == ["Send the deck"]
    bulk.apply(store, run_plan(store, "contacts", ["name=jane"], set={"title": "Chair"}))
    after = fresh(root).get("acme").contacts["jane-doe"]
    assert after.title == "Chair" and after.tasks == before


def test_a_change_that_would_lose_data_is_refused_not_run(store, monkeypatch):
    """Whatever a write forgets to carry over shows as a change nobody asked for."""
    real = Store.write_contact

    def forgetful(self, company_slug, contact):
        contact.tasks = []
        return real(self, company_slug, contact)

    monkeypatch.setattr(Store, "write_contact", forgetful)
    with pytest.raises(BulkError) as exc:
        run_plan(store, "contacts", ["name=jane"], set={"title": "Chair"})
    assert "tasks" in str(exc.value) and "without being asked" in str(exc.value)


def test_interactions_front_matter_only(store, root):
    bodies = {p.name: p.read_bytes() for p in (root / "companies").glob("*/interactions/*.md")}
    p = run_plan(store, "interactions", ["channel=linkedin", "status=unknown"],
                 set={"outcome": "successful", "template": "intro-v2"})
    assert labels(p) == {"delta/2026-09-13T1100-linkedin-out-dee-fox"}   # no reply, still young
    bulk.apply(store, p)
    again = fresh(root)
    it = next(i for i in again.get("delta").interactions if i.channel == "linkedin")
    assert it.outcome == "successful" and it.extra["template"] == "intro-v2"
    assert it.body == "Hi Dee,\n\nHello.\n"
    # bodies are the record: every other interaction file is byte-for-byte the same
    for path in (root / "companies").glob("*/interactions/*.md"):
        meta, body = split_file(path.read_text())
        old = bodies[path.name]
        assert body.encode() == split_file(old.decode())[1].encode()
    # a subject change does not move the file (its name is date, channel, person)
    p = run_plan(store, "interactions", ["channel=linkedin"], set={"subject": "Hello"})
    bulk.apply(store, p)
    assert {i.subject for c in fresh(root).all() for i in c.interactions
            if i.channel == "linkedin" and i.direction == "out"} == {"Hello"}
    assert git(root, "show", "--name-status", "--format=", "HEAD").count("\nR") == 0


def test_interaction_outcome_is_checked_against_the_configured_outcomes(store):
    with pytest.raises(BulkError, match="unknown outcome"):
        run_plan(store, "interactions", ["channel=linkedin"], set={"outcome": "great"})


def test_unknown_front_matter_keys_survive(store, root):
    p = run_plan(store, "companies", ["name=epsilon"], add_tags=["x"], set={"country": "IE"})
    bulk.apply(store, p)
    meta, _ = split_file((root / "companies/epsilon/company.md").read_text())
    assert meta["zz_tool"] == 1 and meta["aa_owner"] == "me"
    assert list(meta)[-2:] == ["aa_owner", "zz_tool"]
    assert meta["tags"] == ["x"] and meta["country"] == "IE"


# --------------------------------------------------------- --where means the list's


def slugs_on_page(html: str) -> set:
    return {s for s in re.findall(r'href="/companies/([a-z0-9-]+)"', html) if s != "new"}


def contacts_on_page(html: str) -> set:
    return {f"{c}/{k}" for c, k in re.findall(r'href="/companies/([^/"]+)/contacts/([^/"]+)"', html)}


def messages_on_page(html: str) -> set:
    return {f"{c}/{i}" for c, i in
            re.findall(r'href="/companies/([^/"]+)/interactions/([^/"]+)/edit"', html)}


@pytest.fixture
def client(root):
    config = {**load_config(root), "push_enabled": False, "welcome_dismissed": True,
              "disclaimer_accepted": "2026-09-01T09:00:00"}
    app = create_app(root, config=config, clock=lambda: FIXED_NOW)
    return TestClient(app, follow_redirects=False)


def page(client, path: str, params) -> str:
    response = client.get(path + "?" + urlencode(params))
    assert response.status_code == 200, (path, params)
    return response.text


COMPANY_FILTERS = [
    (["name=acme"], [("f_name", "acme")]),
    (["name=!a"], [("f_name", "!a")]),
    (["name==Beta AG"], [("f_name", "=Beta AG")]),
    (["my_score=>50"], [("f_my_score", ">50")]),
    (["my_score=<50"], [("f_my_score", "<50")]),
    (["my_score=-"], [("f_my_score", "-")]),
    (["tags=-"], [("f_tags", "-")]),
    (["tags=*"], [("f_tags", "*")]),
    (["tags=saas"], [("f_tags", "saas")]),
    (["country=DE"], [("f_country", "DE")]),
    (["stage=engaged,prospect"], [("f_stage", "engaged"), ("f_stage", "prospect")]),
    (["tier=a"], [("f_tier", "a")]),
    (["last_touch=>2026-09-01"], [("f_last_touch", ">2026-09-01")]),
    (["country=DE", "my_score=>50"], [("f_country", "DE"), ("f_my_score", ">50")]),
]


@pytest.mark.parametrize("where,query", COMPANY_FILTERS)
def test_where_on_companies_is_the_companies_page_filter(store, client, where, query):
    on_page = slugs_on_page(page(client, "/companies", [*query, ("parked", "1")]))
    plan = run_plan(store, "companies", where, add_tags=["zz-marker"])
    assert labels(plan) == on_page
    assert plan.matched == len(on_page)


def test_where_matches_parked_companies_unlike_the_page_default(store, client):
    shown = slugs_on_page(page(client, "/companies", []))
    assert "zeta" not in shown                                # the page hides parked ones
    plan = run_plan(store, "companies", ["country=FI"], add_tags=["x"])
    assert labels(plan) == {"zeta"}                           # a filter you typed finds it


@pytest.mark.parametrize("where,query", [
    (["title=c"], [("f_title", "c")]),
    (["title=-"], [("f_title", "-")]),
    (["company=acme"], [("f_company_name", "acme")]),
    (["email=*"], [("f_email", "*")]),
    (["interaction_count=>0"], [("f_interaction_count", ">0")]),
    (["seniority=senior"], [("f_seniority", "senior")]),
    (["last_touch=>2026-09-01"], [("f_last_touch", ">2026-09-01")]),
])
def test_where_on_contacts_is_the_contacts_page_filter(store, client, where, query):
    on_page = contacts_on_page(page(client, "/contacts", query))
    plan = run_plan(store, "contacts", where, set={"phone": "zz"})
    assert labels(plan) == on_page and on_page


@pytest.mark.parametrize("where,query", [
    (["channel=linkedin"], [("f_channel", "linkedin")]),
    (["status=unknown"], [("f_status", "unknown")]),
    (["outcome=unsuccessful"], [("f_status", "unsuccessful")]),
    (["company=acme", "channel=email"], [("f_company_name", "acme"), ("f_channel", "email")]),
    (["date=<2026-09-01"], [("f_date", "<2026-09-01")]),
    (["uses=>0"], [("f_uses", ">0")]),
    (["message=short"], [("f_body", "short")]),
])
def test_where_on_interactions_is_the_messages_page_filter(store, client, where, query):
    on_page = messages_on_page(page(client, "/messages", query))
    plan = run_plan(store, "interactions", where, set={"subject": "ZZ"})
    assert labels(plan) == on_page and on_page


def test_where_ranges_and_repeated_keys(store):
    both = run_plan(store, "companies", ["my_score=>50", "my_score=<90"], add_tags=["x"])
    assert labels(both) == {"acme", "delta"}                   # every pair has to hold
    either = run_plan(store, "companies", ["country=DE", "country=NL"], add_tags=["x"])
    assert labels(either) == {"acme", "beta", "gamma"}         # choices are "any of"


def test_where_is_checked(store):
    with pytest.raises(BulkError) as exc:
        run_plan(store, "companies", ["contry=DE"], add_tags=["x"])
    assert "Did you mean country?" in str(exc.value) and "Keys:" in str(exc.value)
    with pytest.raises(BulkError, match="not a number"):
        run_plan(store, "companies", ["my_score=>lots"], add_tags=["x"])
    with pytest.raises(BulkError, match="not one of the choices"):
        run_plan(store, "companies", ["stage=prosect"], add_tags=["x"])
    with pytest.raises(BulkError, match="has no value"):
        run_plan(store, "companies", ["tags="], add_tags=["x"])
    with pytest.raises(BulkError, match="key=value"):
        run_plan(store, "companies", ["acme"], add_tags=["x"])


# ---------------------------------------------------------------------- dry run


def test_a_dry_run_writes_nothing_and_commits_nothing(store, root):
    before, count, rev = tree(root), commit_count(root), git(root, "rev-parse", "HEAD")
    p = run_plan(store, "companies", ["country=DE"], add_tags=["priority"], stage="engaged")
    text = p.render()
    assert p.changed == 2
    assert tree(root) == before
    assert commit_count(root) == count and git(root, "rev-parse", "HEAD") == rev
    assert git(root, "status", "--porcelain") == ""
    assert not [x for x in root.iterdir() if x.name.startswith("hermitcrm-bulk")]
    assert "Dry run: add tag priority, stage engaged on companies where country=DE" in text
    assert "2 companies match. 2 would change." in text
    assert "  acme: tags: saas → saas, priority" in text
    assert text.endswith("Nothing changed. Run again with --apply to change 2 companies "
                         "in one commit.")


def test_the_dry_run_shows_five_samples_and_counts_the_rest(store):
    p = bulk.plan(store, "companies", [], Ops(add_tags=["zz"]), everything=True)
    text = p.render()
    assert p.changed == 6
    assert len(re.findall(r"^  \w+: tags:", text, re.M)) == 5
    assert "  and 1 more." in text
    assert "to change 6 companies in one commit" in text


def test_zero_matches_and_no_change_are_not_errors(store, root, monkeypatch, capsys):
    monkeypatch.setattr(crm, "_reload_server", lambda config: None)
    assert crm.main(["set", "companies", "--where", "country=SE", "--add-tag", "x"],
                    root=root) == 0
    assert "No companies match country=SE. Nothing to change." in capsys.readouterr().out
    assert crm.main(["set", "companies", "--where", "tags=priority", "--add-tag", "priority"],
                    root=root) == 0
    assert "already looks like this. Nothing to change." in capsys.readouterr().out
    assert git(root, "status", "--porcelain") == ""


# ------------------------------------------------------------------------ apply


def test_apply_is_one_commit_with_only_the_changed_files(store, root):
    count = commit_count(root)
    p = run_plan(store, "companies", ["country=DE"], add_tags=["priority"])
    sha = bulk.apply(store, p)
    assert commit_count(root) == count + 1
    assert sha and git(root, "rev-parse", "--short=10", "HEAD").strip() == sha
    assert head_files(root) == {"companies/acme/company.md", "companies/beta/company.md"}
    assert subject(root) == "bulk: add tag priority on 2 companies (country=DE)"
    assert git(root, "status", "--porcelain") == ""
    body = git(root, "log", "-1", "--format=%b")
    assert "where: country=DE" in body and "changed: 2 companies" in body


def test_the_subject_is_short_and_a_message_replaces_the_summary(store, root):
    p = bulk.plan(store, "companies", ["name=acme", "country=DE", "my_score=>1", "tags=*",
                                       "tier=a"],
                  Ops(set={"product_oneliner": "x" * 40}, add_tags=["priority"]))
    assert len(p.subject()) <= 72 and p.subject().startswith("bulk: ")
    bulk.apply(store, p, message="Tag the German accounts")
    assert subject(root) == "bulk: Tag the German accounts"
    p = run_plan(store, "companies", ["name=beta"], add_tags=["x"])
    bulk.apply(store, p, message="bulk: already prefixed")
    assert subject(root) == "bulk: already prefixed"
    p = run_plan(store, "companies", ["name=gamma"], add_tags=["x"])
    with pytest.raises(BulkError, match="--message is empty"):
        bulk.apply(store, p, message="   ")


def test_unchanged_records_are_skipped_and_not_counted(store, root):
    p = run_plan(store, "companies", ["country=DE"], add_tags=["saas"])
    assert (p.matched, p.changed, p.skipped) == (2, 1, 1)   # acme already has it
    assert labels(p) == {"beta"}
    count = commit_count(root)
    bulk.apply(store, p)
    assert commit_count(root) == count + 1
    assert head_files(root) == {"companies/beta/company.md"}
    assert "(1 company matched and already looked like this.)" in p.result("abc")
    again = run_plan(store, "companies", ["country=DE"], add_tags=["saas"])
    assert (again.matched, again.changed, again.skipped) == (2, 0, 2)
    with pytest.raises(BulkError, match="nothing to apply"):
        bulk.apply(store, again)
    assert commit_count(root) == count + 1


def test_pipeline_md_stays_in_sync(store, root):
    p = run_plan(store, "companies", ["name=gamma"], stage="discovery")
    bulk.apply(store, p)
    assert "PIPELINE.md" in head_files(root) and "companies/gamma/company.md" in head_files(root)
    text = (root / "PIPELINE.md").read_text()
    # (the first line carries the time it was generated)
    assert text.split("\n", 1)[1] == pipeline.render(make_store(root)).split("\n", 1)[1]
    discovery = text.split("## discovery")[1].split("##")[0]
    assert "- gamma |" in discovery


def test_apply_works_on_the_row_it_matched_not_on_a_stale_name(store, root):
    p = run_plan(store, "contacts", ["company=beta"], set={"title": "Buyer"})
    bulk.apply(store, p)
    assert head_files(root) == {"companies/beta/contacts/kim-lee.md"}
    assert fresh(root).get("beta").contacts["kim-lee"].title == "Buyer"


# --------------------------------------------------------------------- safety


def test_a_validation_failure_puts_everything_back_and_commits_nothing(store, root, monkeypatch):
    p = run_plan(store, "companies", ["country=DE"], add_tags=["priority"], stage="engaged")
    before, count = tree(root), commit_count(root)
    real = Store.write_company

    def breaks_beta(self, company):
        path = real(self, company)
        if company.slug == "beta":
            path.write_text(path.read_text().replace("country: DE", "country: ZZZZ"))
        return path

    monkeypatch.setattr(Store, "write_company", breaks_beta)
    with pytest.raises(ApplyError) as exc:
        bulk.apply(store, p)
    assert exc.value.code == 1 and "do not check out" in str(exc.value)
    assert "companies/beta/company.md" in str(exc.value)
    assert tree(root) == before                         # byte for byte, no partial writes
    assert commit_count(root) == count
    assert git(root, "status", "--porcelain") == ""
    assert store.get("acme").tags == ["saas"] and store.get("beta").country == "DE"
    assert fresh(root).get("beta").country == "DE"


def test_a_failed_commit_puts_everything_back(store, root, monkeypatch):
    p = run_plan(store, "companies", ["country=DE"], stage="discovery")
    before, count = tree(root), commit_count(root)
    monkeypatch.setattr(GitOps, "commit", lambda self, message, paths=None: None)
    with pytest.raises(ApplyError, match="could not make the commit"):
        bulk.apply(store, p)
    assert tree(root) == before and commit_count(root) == count
    assert git(root, "status", "--porcelain") == ""


def test_a_failed_commit_after_staging_leaves_the_index_clean(store, root, monkeypatch):
    p = run_plan(store, "companies", ["country=DE"], add_tags=["x"])
    before = tree(root)

    def stages_then_fails(self, message, paths=None):
        git(root, "add", "-A", "--", *paths)
        return None

    monkeypatch.setattr(GitOps, "commit", stages_then_fails)
    with pytest.raises(ApplyError):
        bulk.apply(store, p)
    assert tree(root) == before and git(root, "status", "--porcelain") == ""


def test_a_plan_older_than_a_write_is_refused(store, root):
    p = run_plan(store, "companies", ["country=DE"], add_tags=["priority"])
    path = root / "companies/acme/company.md"
    path.write_text(path.read_text().replace("tags: [saas]", "tags: [saas, edited]"))
    edited, before_beta = path.read_text(), (root / "companies/beta/company.md").read_bytes()
    count = commit_count(root)
    with pytest.raises(ApplyError, match="changed since the dry run"):
        bulk.apply(store, p)
    assert path.read_text() == edited                    # their edit is theirs
    assert (root / "companies/beta/company.md").read_bytes() == before_beta
    assert commit_count(root) == count


def test_an_interaction_that_would_be_renamed_is_refused(store, root):
    """An id that is not date-channel-contact is renamed by the Store on any write."""
    folder = root / "companies/acme/interactions"
    original = next(folder.glob("*linkedin-out*.md"))
    original.rename(folder / "legacy-name.md")
    store = make_store(root)
    with pytest.raises(BulkError, match="renamed"):
        run_plan(store, "interactions", ["channel=linkedin"], set={"subject": "ZZ"})


# -------------------------------------------------------------------- refusals


@pytest.mark.parametrize("scope,ops,text", [
    ("interactions", {"set": {"body": "x"}}, "never rewritten"),
    ("interactions", {"unset": ["body"]}, "never rewritten"),
    ("interactions", {"set": {"message": "x"}}, "never rewritten"),
    ("companies", {"set": {"notes": "x"}}, "never changed in bulk"),
    ("companies", {"set": {"name": "X"}}, "names the record"),
    ("companies", {"set": {"slug": "x"}}, "names the record"),
    ("contacts", {"set": {"first_name": "X"}}, "names the record"),
    ("interactions", {"set": {"date": "2026-01-01"}}, "names the record"),
    ("interactions", {"set": {"channel": "call"}}, "names the record"),
    ("companies", {"set": {"stage": "won"}}, "use --stage"),
    ("companies", {"set": {"created": "2026-01-01"}}, "kept by Hermit"),
    ("companies", {"set": {"stage_history": "x"}}, "kept by Hermit"),
    ("companies", {"unset": ["source"]}, "cannot be empty"),
    ("contacts", {"add_tags": ["x"]}, "only companies have tags"),
    ("interactions", {"stage": "won"}, "only works on companies"),
    ("contacts", {"stage": "won"}, "only works on companies"),
    ("companies", {"stage": "prosect"}, "Did you mean prospect?"),
    ("companies", {"set": {"source": "linkdin-search"}}, "Did you mean linkedin-search?"),
    ("companies", {"set": {"country": "Germany"}}, "not a country code"),
    ("companies", {"add_tags": ["x"], "remove_tags": ["X"]}, "added and removed"),
    ("companies", {"add_tags": ["x"], "set": {"tags": "y"}}, "changed twice"),
    ("companies", {"set": {"my_score": "1"}, "unset": ["my_score"]}, "changed twice"),
    ("companies", {}, "nothing to do"),
])
def test_refusals(store, root, scope, ops, text):
    before, count = tree(root), commit_count(root)
    with pytest.raises(BulkError) as exc:
        run_plan(store, scope, ["name=a"], **ops)
    assert text in str(exc.value) and exc.value.code == 2
    assert tree(root) == before and commit_count(root) == count


def test_an_unknown_field_gets_a_hint_and_the_way_to_add_it(store):
    with pytest.raises(BulkError) as exc:
        run_plan(store, "companies", ["name=a"], set={"my_scor": "5"})
    msg = str(exc.value)
    assert "unknown field 'my_scor'" in msg and "Did you mean my_score?" in msg
    assert "fields.toml first" in msg and "hermitcrm help adjust-fields" in msg
    with pytest.raises(BulkError, match="is a company field, not a contact field"):
        run_plan(store, "contacts", ["name=a"], set={"my_score": "5"})


def test_no_where_is_refused_and_all_says_you_mean_it(store, root):
    with pytest.raises(BulkError) as exc:
        bulk.plan(store, "companies", [], Ops(add_tags=["x"]))
    assert "every one of your companies" in str(exc.value) and "--all" in str(exc.value)
    with pytest.raises(BulkError, match="contradict"):
        bulk.plan(store, "companies", ["country=DE"], Ops(add_tags=["x"]), everything=True)
    p = bulk.plan(store, "companies", [], Ops(add_tags=["x"]), everything=True)
    assert p.matched == 6 and p.describe_where() == "all companies"
    with pytest.raises(BulkError, match="unknown scope 'company'"):
        bulk.plan(store, "company", ["name=a"], Ops(add_tags=["x"]))


def test_a_broken_fields_toml_is_a_refusal(store, root):
    (root / "fields.toml").write_text('[[field]]\nkey = "x"\ntype = "weird"\n')
    with pytest.raises(BulkError, match="fields.toml"):
        run_plan(store, "companies", ["name=a"], add_tags=["x"])


def test_the_hub_contract(root):
    assert bulk.validate(root) == [] and bulk.built_items(root) == []


# -------------------------------------------------------------------------- CLI


@pytest.fixture
def cli_root(root, monkeypatch):
    monkeypatch.setattr(crm, "_reload_server", lambda config: None)  # never the live app
    return root


def test_cli_dry_run_then_apply(cli_root, capsys):
    root = cli_root
    argv = ["set", "companies", "--where", "country=DE", "--where", "my_score=>50",
            "--add-tag", "priority"]
    assert crm.main(argv, root=root) == 0
    out = capsys.readouterr().out
    assert "acme: tags: saas → saas, priority" in out
    assert out.strip().endswith("Nothing changed. Run again with --apply to change 1 company "
                                "in one commit.")
    assert git(root, "status", "--porcelain") == ""
    count = commit_count(root)

    assert crm.main([*argv, "--apply"], root=root) == 0
    out = capsys.readouterr().out.strip()
    sha = git(root, "rev-parse", "--short=10", "HEAD").strip()
    assert out == f"1 company changed in one commit {sha}. Undo: hermitcrm undo {sha}"
    assert commit_count(root) == count + 1 and subject(root).startswith("bulk: add tag priority")
    assert crm.main(["check"], root=root) == 0


def test_cli_every_operation_and_message(cli_root, capsys):
    root = cli_root
    assert crm.main(["set", "companies", "--where", "name=gamma", "--set", "my-score=3",
                     "--unset", "tier", "--add-tag", "a, b", "--stage", "engaged",
                     "--message", "Gamma, after the call", "--apply"], root=root) == 0
    capsys.readouterr()
    gamma = make_store(root).get("gamma")
    assert gamma.extra["my_score"] == 3 and "tier" not in gamma.extra
    assert gamma.tags == ["a", "b"] and gamma.stage == "engaged"
    assert subject(root) == "bulk: Gamma, after the call"
    assert crm.main(["set", "contacts", "--where", "company=acme", "--set", "role=champion",
                     "--apply"], root=root) == 0
    assert crm.main(["set", "interactions", "--where", "channel=email", "--set",
                     "outcome=unsuccessful", "--apply"], root=root) == 0
    capsys.readouterr()
    again = make_store(root)
    assert again.get("acme").contacts["joe-roe"].role == "champion"
    assert [i.outcome for i in again.get("acme").interactions if i.channel == "email"] \
        == ["unsuccessful"]


def test_cli_refusals_exit_2_with_nothing_written(cli_root, capsys):
    root = cli_root
    before, count = tree(root), commit_count(root)
    for argv, text in [
        (["set", "companies", "--add-tag", "x"], "every one of your companies"),
        (["set", "interactions", "--where", "channel=email", "--set", "body=x", "--apply"],
         "never rewritten"),
        (["set", "companies", "--where", "name=a", "--set", "mystery=1", "--apply"],
         "unknown field 'mystery'"),
        (["set", "companies", "--where", "name=a", "--apply"], "nothing to do"),
        (["set", "companies", "--where", "name=a", "--set", "oops", "--apply"],
         "--set wants field=value"),
        (["set", "companies", "--where", "name=a", "--set", "my_score=1",
          "--set", "my-score=2"], "given twice"),
    ]:
        assert crm.main(argv, root=root) == 2, argv
        captured = capsys.readouterr()
        assert text in captured.err and captured.out == ""
    assert tree(root) == before and commit_count(root) == count


def test_cli_a_rolled_back_write_exits_1(cli_root, capsys, monkeypatch):
    root = cli_root
    before, count = tree(root), commit_count(root)
    monkeypatch.setattr(GitOps, "commit", lambda self, message, paths=None: None)
    assert crm.main(["set", "companies", "--where", "country=DE", "--stage", "discovery",
                     "--apply"], root=root) == 1
    assert "rolled back" in capsys.readouterr().err
    assert tree(root) == before and commit_count(root) == count


def test_cli_a_bad_scope_is_an_argparse_error(cli_root):
    with pytest.raises(SystemExit) as exc:
        crm.main(["set", "deals", "--all", "--add-tag", "x"], root=cli_root)
    assert exc.value.code == 2


def test_cli_apply_asks_a_running_app_to_reload(cli_root, monkeypatch):
    asked = []
    monkeypatch.setattr(crm, "_reload_server", lambda config: asked.append(config["port"]))
    assert crm.main(["set", "companies", "--where", "name=beta", "--add-tag", "x"],
                    root=cli_root) == 0
    assert asked == []                                   # a dry run reloads nothing
    assert crm.main(["set", "companies", "--where", "name=beta", "--add-tag", "x", "--apply"],
                    root=cli_root) == 0
    assert len(asked) == 1


def test_help_topic_for_agents_is_there(capsys):
    assert crm.main(["help", "adjust-bulk"]) == 0
    out = capsys.readouterr().out
    assert "hermitcrm set" in out and "--apply" in out
