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


"""The playbook (MESSAGING.md: approaches in the front matter, an approach block per
approach in the body): validation, the readiness gate, persona matching, picking
the approach for a company, approaches added, copied and deleted, and the
byte-for-byte upgrade. All names are made up."""

import subprocess

import pytest

from hermitcrm import cli, playbook
from hermitcrm.datafolder import MESSAGING, NEW_MESSAGING, init_folder
from hermitcrm.enrich import EnrichError
from hermitcrm.models import Company, Contact

FILLED = """---
approaches:
  - name: Clinic software
    offer_line: "We build booking software for clinics."
    icp:
      industries: [healthcare]
      countries: [NL, BE]
      ranges: {employees: [5, 200]}
    disqualifiers:
      - tag_present: [competitor]
    personas:
      owner: {titles: ["Owner", "Practice Manager"]}
---
# Messaging playbook

General notes.

# Approach: Clinic software

## Proof

- A made-up clinic cut no-shows by a third.

## Lessons

### Worked

- Short mails.
"""

TWO = """---
approaches:
  - name: Founder coaching
    offer_line: I coach founders.
    icp: {countries: [DE, NL], ranges: {ae_count: [0, 0]}}
    personas: {founder: {titles: [CEO]}}
  - name: Team build-out
    offer_line: I build your sales team.
    icp: {countries: [DE, NL], ranges: {ae_count: [1, 10]}}
    disqualifiers:
      - tag_present: [has-sales-leader]
    personas: {founder: {titles: [CEO]}}
---
# Approach: Founder coaching

## Proof

- A made-up founder got a day a week back.

# Approach: Team build-out

## Proof

- A made-up team hit quota.
"""


def git(folder, *args):
    return subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True,
                          check=True).stdout


@pytest.fixture
def folder(tmp_path):
    return init_folder(tmp_path / "crm")


# ---------------------------------------------------------------- validation


def test_filled_front_matter_is_valid_and_ready():
    pb = playbook.parse(FILLED)
    assert pb.set_up and not pb.error
    assert playbook.validate_front(pb.front) == []
    approach, = pb.approaches
    assert playbook.approach_gaps(approach) == []
    assert approach.proof == ["A made-up clinic cut no-shows by a third."]
    assert approach.lessons() == {"worked": "- Short mails.", "failed": "", "open": ""}


def test_a_list_of_offer_lines_is_refused():
    text = FILLED.replace('offer_line: "We build booking software for clinics."',
                          "offer_line:\n      - one line\n      - another line")
    pb = playbook.parse(text)
    assert any(playbook.ONE_LINE in p for p in playbook.validate_front(pb.front))
    assert any("offer line" in g for g in playbook.approach_gaps(pb.approaches[0]))


@pytest.mark.parametrize("item, says", [
    ("- tag_present: customer", "tag_present takes a list"),
    ("- title_present: [CEO]", "title_present is not a hard disqualifier"),
    ("- no_salespeople: true", "write it in the Disqualifiers section as text"),
    ("- {tag_present: [a], fte_over: [b]}", "must be one `key: [...]`"),
])
def test_disqualifier_vocabulary(item, says):
    text = FILLED.replace("- tag_present: [competitor]", item)
    problems = playbook.validate_front(playbook.parse(text).front)
    assert any(says in p for p in problems), problems


@pytest.mark.parametrize("old, new, says", [
    ("employees: [5, 200]", "employees: [200, 5]", "icp.ranges.employees: must be [min, max]"),
    ("ranges: {employees: [5, 200]}", "fte: [5, 200]", "icp.fte: not an ICP key"),
    ("ranges: {employees: [5, 200]}", "ranges: [5, 200]", "icp.ranges: must be field"),
    ("countries: [NL, BE]", "countries: [NL, Narnia]", "not a two-letter country code"),
    ("industries: [healthcare]", "industries: healthcare", "icp.industries: must be a list"),
    ("    offer_line:", "    offer_lines: x\n    offer_line:", "offer_lines: not an approach key"),
    ('owner: {titles: ["Owner", "Practice Manager"]}', "owner: {pains: [time]}",
     "personas.owner: has no titles"),
    ("  - name: Clinic software", "  - name: ''", "has no name"),
    ("approaches:", "offer_line: x\napproaches:", "offer_line: not a playbook key"),
])
def test_front_matter_problems_are_named(old, new, says):
    problems = playbook.validate_front(playbook.parse(FILLED.replace(old, new)).front)
    assert any(says in p for p in problems), problems


def test_two_approaches_cannot_share_a_name():
    text = TWO.replace("name: Team build-out", "name: founder  COACHING")
    assert any("two approaches are called" in p
               for p in playbook.validate_front(playbook.parse(text).front))


def test_check_reports_problems_and_hints(folder):
    (folder / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    text, code = cli.cmd_check(cli.build_store(folder))
    assert code == 0 and "MESSAGING.md: not set up for the outreach bot" in text
    (folder / "MESSAGING.md").write_text(
        FILLED.replace('"We build booking software for clinics."', "[a, b]"),
        encoding="utf-8")
    text, code = cli.cmd_check(cli.build_store(folder))
    assert code == 1 and playbook.ONE_LINE in text and "MESSAGING.md: front matter: " in text
    (folder / "MESSAGING.md").write_text("---\napproaches: [unclosed\n---\n", encoding="utf-8")
    text, code = cli.cmd_check(cli.build_store(folder))
    assert code == 1 and "not valid YAML" in text


# ----------------------------------------------------------------- readiness


def test_gate_blocks_an_empty_playbook(folder):
    with pytest.raises(playbook.NotReady) as exc:
        playbook.require_ready(folder)
    assert len(exc.value.gaps[playbook.DEFAULT_APPROACH]) == 4
    message = str(exc.value)
    assert "offer line" in message and "persona" in message and "proof" in message
    assert "/settings/playbook" in message


def test_gate_blocks_a_missing_file_and_one_without_front_matter(tmp_path):
    with pytest.raises(playbook.NotReady):
        playbook.require_ready(tmp_path)
    (tmp_path / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    with pytest.raises(playbook.NotReady, match="not set up"):
        playbook.require_ready(tmp_path)


@pytest.mark.parametrize("old, new, gap", [
    ('"We build booking software for clinics."', '""', "offer line"),
    ("- A made-up clinic cut no-shows by a third.", "<!-- a result -->", "proof line"),
    ('owner: {titles: ["Owner", "Practice Manager"]}', "owner: {titles: []}", "persona"),
    ("      industries: [healthcare]\n      countries: [NL, BE]\n"
     "      ranges: {employees: [5, 200]}\n", "      industries: []\n", "ideal customer"),
])
def test_gate_names_each_gap(tmp_path, old, new, gap):
    (tmp_path / "MESSAGING.md").write_text(FILLED.replace(old, new), encoding="utf-8")
    pb = playbook.load(tmp_path)
    gaps = [g for g in playbook.approach_gaps(pb.approaches[0]) if "front matter" not in g]
    assert len(gaps) == 1 and gap in gaps[0]
    with pytest.raises(playbook.NotReady):
        playbook.require_ready(tmp_path)


def test_gate_passes_with_one_ready_approach_and_names_the_other(tmp_path):
    text = TWO.replace("- A made-up team hit quota.", "")
    (tmp_path / "MESSAGING.md").write_text(text, encoding="utf-8")
    assert [o.name for o in playbook.require_ready(tmp_path)] == ["Founder coaching"]
    with pytest.raises(playbook.NotReady, match="Team build-out: one proof line"):
        playbook.require_ready(tmp_path, approach="team build-out")
    with pytest.raises(playbook.NotReady, match="an approach called"):
        playbook.require_ready(tmp_path, approach="Nope")


def test_the_demo_folder_has_two_ready_approaches(tmp_path):
    folder = init_folder(tmp_path / "demo", demo=True)
    ready = playbook.require_ready(folder)
    assert [o.name for o in ready] == ["Founder coaching", "Scaling the sales team"]
    assert all(all(ok for _, ok in playbook.completeness(o)) for o in ready)
    pb = playbook.load(folder)
    assert playbook.validate_front(pb.front) == []
    assert all(line in pb.text.splitlines() for line in NEW_MESSAGING.splitlines())
    assert "## What worked" not in pb.text  # Lessons, per approach, instead


def test_a_new_folder_has_one_empty_approach_and_no_what_worked(folder):
    pb = playbook.load(folder)
    assert [o.name for o in pb.approaches] == [playbook.DEFAULT_APPROACH]
    assert pb.text == playbook.upgrade_text(NEW_MESSAGING)
    assert "## What worked" not in pb.text


# ------------------------------------------------------------------ personas


PERSONAS = {"founder": {"titles": ["CEO", "Founder", "Co-Founder"]},
            "sales": {"titles": ["Head of Sales", "Account Executive"]},
            "ops": {"titles": ["Head of Sales Operations"]}}


@pytest.mark.parametrize("title, persona", [
    ("CEO", "founder"),
    ("ceo & co-founder", "founder"),
    ("  Senior   Account Executive ", "sales"),
    ("Head of Sales Operations", "ops"),   # the longest title wins
    ("Head of Sales, DACH", "sales"),
    ("CEOs' assistant", ""),               # whole words only
    ("Marketing Manager", ""),
    ("", ""),
])
def test_persona_matching_by_title(title, persona):
    assert playbook.match_persona(title, PERSONAS) == persona


# ---------------------------------------- disqualifiers and picking the approach


def company(fte="", ae=None, titles=(), tags=(), country="DE"):
    co = Company(name="Example Ltd", slug="example-ltd", country=country, tags=list(tags))
    if fte:
        co.extra["fte_estimate"] = fte
    if ae is not None:
        co.extra["ae_count"] = ae
    for n, title in enumerate(titles):
        co.contacts[f"p{n}"] = Contact(first_name="Person", last_name=str(n),
                                       slug=f"p{n}", title=title)
    return co


def test_hard_disqualifiers_are_tags_only():
    approach = playbook.parse(FILLED).approaches[0]
    assert not playbook.disqualify(company(titles=["IT Director"]), approach).excluded
    assert playbook.disqualify(company(tags=["Competitor"]), approach).reasons == [
        "tagged competitor"]


def test_ranges_use_the_folders_own_fields():
    approach = playbook.parse(FILLED).approaches[0]
    co = company()
    co.extra["employees"] = "~40"          # a text field counts by its first number
    assert playbook.fit(co, approach)[0][0] == "employees 40 (wants 5-200)"
    co.extra["employees"] = 900
    assert playbook.fit(co, approach)[1][0] == "employees 900, wants 5-200"
    assert playbook.fit(company(country="NL"), approach)[2] == ["no employees"]


@pytest.mark.parametrize("co, approach", [
    (company(ae=0), "Founder coaching"),
    (company(ae=3), "Team build-out"),
    (company(ae=3, tags=["has-sales-leader"]), ""),   # disqualified for the one it fits
    (company(ae=3, country="FR"), ""),                # outside every ICP
])
def test_pick_approach_by_fit(co, approach):
    pick = playbook.pick_approach(co, playbook.parse(TWO).approaches)
    assert pick.approach == approach and not pick.unclear


def test_pick_approach_asks_when_an_empty_field_cannot_decide():
    pick = playbook.pick_approach(company(), playbook.parse(TWO).approaches)
    assert pick.approach == "" and pick.unclear == ["Founder coaching", "Team build-out"]
    assert "no ae count" in pick.why


def test_pick_approach_says_why_an_approach_was_left_out():
    pick = playbook.pick_approach(company(ae=3, tags=["has-sales-leader"]),
                                  playbook.parse(TWO).approaches)
    assert pick.left_out == {"Founder coaching": ["ae count 3, wants 0"],
                             "Team build-out": ["tagged has-sales-leader"]}


# ------------------------------------------------------------------- upgrade


OLD_FILES = [
    MESSAGING,
    "# My notes\r\n\r\nNo trailing newline, Windows line ends",
    "",
    "## Proof\n\n- something we already wrote\n",
    "---\napproaches:\n  - name: Kept\n    offer_line: as written\n---\n# Approach: Kept\n\n"
    "## Proof\n\n- mine\n",
]


@pytest.mark.parametrize("old", OLD_FILES)
def test_upgrade_keeps_every_byte_and_is_idempotent(old):
    new = playbook.upgrade_text(old)
    assert playbook.parse(new).set_up
    old_source, old_body = playbook.split(old)
    if old_source is None:
        assert playbook.split(new)[1].startswith(old)       # byte for byte, in place
    else:
        assert new.startswith(old.rstrip("\n"))             # its front matter too
        assert playbook.parse(new).approaches[0].proof == ["mine"]
    assert playbook.upgrade_text(new) == new
    for _, title, _ in playbook.SECTIONS:
        assert f"## {title}\n" in new


def test_upgrade_leaves_a_front_matter_of_someone_else_alone():
    text = "---\ntitle: my notes\n---\nbody\n"
    assert playbook.upgrade_text(text) == text


def test_upgrade_command_is_one_commit_and_idempotent(folder):
    (folder / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    git(folder, "commit", "-qam", "an old playbook")
    before = int(git(folder, "rev-list", "--count", "HEAD"))
    gitops = cli.GitOps(folder, push_enabled=False)
    text, code = cli.cmd_playbook(folder, "upgrade", commit=gitops.commit)
    assert code == 0 and "every line you had is kept" in text
    assert int(git(folder, "rev-list", "--count", "HEAD")) == before + 1
    assert git(folder, "show", "--name-only", "--format=", "HEAD").split() == ["MESSAGING.md"]
    assert MESSAGING in (folder / "MESSAGING.md").read_text(encoding="utf-8")
    text, code = cli.cmd_playbook(folder, "upgrade", commit=gitops.commit)
    assert "nothing changed" in text
    assert int(git(folder, "rev-list", "--count", "HEAD")) == before + 1


def test_existing_folders_are_not_changed_by_other_commands(folder):
    (folder / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    for argv in (["check"], ["playbook"], ["playbook", "upgrade", "--dry-run"], ["rebuild"]):
        cli.main(argv, root=folder)
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == MESSAGING


def test_status_command(folder, capsys):
    assert cli.main(["playbook", "status"], root=folder) == 1
    assert "no approach is ready" in capsys.readouterr().out
    (folder / "MESSAGING.md").write_text(TWO.replace("- A made-up team hit quota.", ""),
                                         encoding="utf-8")
    assert cli.main(["playbook"], root=folder) == 0
    out = capsys.readouterr().out
    assert "Ready for the outreach bot: Founder coaching." in out
    assert "Team build-out: " in out and "not ready, missing one proof line" in out


# --------------------------------------------------------- approaches, the form


def test_form_round_trip_keeps_the_rest_of_the_file():
    text = playbook.upgrade_text(MESSAGING)
    values = {"name": "Brand design", "offer_line": "  We  design   brands. ",
              "icp_industries": "food, Food, retail", "icp_countries": "fr, be",
              "range_0_field": "employees", "range_0_min": "2", "range_0_max": "40",
              "range_1_field": "", "range_1_min": "", "range_1_max": "",
              "dq_tag_present": "customer",
              "personas": "Brand Owner: CMO, Founder\n\nbuyer: Head of Marketing",
              "section_proof": "- A made-up launch sold out in a week.",
              "section_voice": "Warm and short.", "section_disqualifiers": "- Agencies",
              "lessons_failed": "- Long mails."}
    new, errors = playbook.save_form(text, playbook.DEFAULT_APPROACH, values)
    assert errors == {}
    approach, = playbook.parse(new).approaches
    assert approach.name == "Brand design" and approach.offer_line == "We design brands."
    assert approach.icp["industries"] == ["food", "retail"] and approach.icp["countries"] == ["FR", "BE"]
    assert approach.icp["ranges"] == {"employees": [2, 40]}
    assert approach.disqualifiers == [{"tag_present": ["customer"]}]
    assert approach.personas == {"brand-owner": {"titles": ["CMO", "Founder"]},
                              "buyer": {"titles": ["Head of Marketing"]}}
    assert approach.section("voice") == "Warm and short."
    assert approach.section("disqualifiers") == "- Agencies"
    assert approach.lessons()["failed"] == "- Long mails."
    assert "# Approach: Brand design" in new and "# Approach: My approach" not in new
    assert MESSAGING in new
    # Saving the same values again writes the same bytes.
    again, _ = playbook.save_form(new, "Brand design", playbook.form_values(approach))
    assert again == new


def test_form_errors_and_kept_keys():
    old = {"name": "X", "personas": {"buyer": {"titles": ["CEO"], "pains": ["time"]}}}
    front, _, errors = playbook.from_form(
        {"name": "X", "range_0_field": "employees", "range_0_min": "50", "range_0_max": "5",
         "personas": "buyer: CEO, COO\njust a line"}, old)
    assert set(errors) == {"ranges", "personas"}
    assert "ranges" in playbook.from_form({"name": "X", "range_0_min": "3"})[2]
    assert front["personas"]["buyer"] == {"titles": ["CEO", "COO"], "pains": ["time"]}
    assert "name" in playbook.from_form({"name": "a: b"})[2]


def test_save_refuses_a_name_another_approach_has():
    new, errors = playbook.save_form(TWO, "Team build-out", {
        **playbook.form_values(playbook.parse(TWO).approach("Team build-out")),
        "name": "Founder Coaching"})
    assert new == TWO and "already an approach called" in errors["name"]


def test_add_copy_and_delete_approaches():
    text = playbook.add_approach(TWO, "Workshops")
    pb = playbook.parse(text)
    assert [o.name for o in pb.approaches] == ["Founder coaching", "Team build-out", "Workshops"]
    assert playbook.approach_gaps(pb.approach("Workshops"))  # empty
    copied = playbook.add_approach(text, "Team build-out (UK)", copy_from="Team build-out")
    twin, source = (playbook.parse(copied).approach(n)
                    for n in ("Team build-out (UK)", "Team build-out"))
    assert twin.icp == source.icp and twin.proof == source.proof == ["A made-up team hit quota."]
    assert {k: v for k, v in twin.front.items() if k != "name"} == {
        k: v for k, v in source.front.items() if k != "name"}
    assert playbook.copy_name(playbook.parse(copied), "Team build-out") == "Copy of Team build-out"
    gone = playbook.delete_approach(copied, "Team build-out")
    pb = playbook.parse(gone)
    assert [o.name for o in pb.approaches] == ["Founder coaching", "Workshops", "Team build-out (UK)"]
    assert pb.approach("Team build-out (UK)").proof == ["A made-up team hit quota."]
    assert "# Approach: Team build-out\n" not in gone
    assert playbook.validate_front(pb.front) == []
    with pytest.raises(playbook.PlaybookError, match="already an approach"):
        playbook.add_approach(TWO, "founder coaching")
    with pytest.raises(playbook.PlaybookError, match="at least one approach"):
        playbook.delete_approach(FILLED, "Clinic software")


def test_the_ai_reads_the_body_and_only_its_approach():
    whole = playbook.body_for_ai(FILLED)
    assert whole.startswith("# Messaging playbook") and "offer_line" not in whole
    one = playbook.body_for_ai(TWO, "Team build-out")
    assert "A made-up team hit quota." in one and "got a day a week back" not in one
    assert playbook.body_for_ai(MESSAGING) == MESSAGING


# ------------------------------------------------------------ draft (the AI)


class FakeEnricher:
    available = True

    def __init__(self, answer, no_tools=""):
        self.answer, self.no_tools, self.calls = answer, no_tools, []

    def unavailable_reason(self):
        return "no AI CLI"

    def no_tools_problem(self):
        return self.no_tools

    def runner(self, prompt, schema, tools=None):
        self.calls.append((prompt, schema, tools))
        return self.answer


def test_draft_proposes_without_tools_and_writes_nothing(tmp_path):
    answer = {"offer_line": "We fix  leaky roofs.", "industries": ["property"],
              "countries": ["nl", "Netherlands"],
              "personas": [{"name": "Facility Manager", "titles": ["Facility Manager"]},
                           {"name": "nobody", "titles": []}],
              "proof": ["A made-up office stayed dry all winter."], "why": ""}
    fake = FakeEnricher(answer)
    values = playbook.propose(fake, "Example Roofing fixes roofs. " * 3, "Roof repair")
    (prompt, schema, tools), = fake.calls
    assert tools == "" and "Example Roofing" in prompt and "Never invent" in prompt
    assert 'approach called "Roof repair"' in prompt
    assert values["offer_line"] == "We fix leaky roofs."
    assert values["icp_countries"] == "NL"
    assert values["personas"] == "facility-manager: Facility Manager"
    assert values["section_proof"] == "- A made-up office stayed dry all winter."
    assert "section_why" not in values  # an empty answer leaves the box alone
    assert not (tmp_path / "MESSAGING.md").exists()


def test_draft_refuses_a_cli_with_tools_and_empty_text():
    with pytest.raises(EnrichError, match="drafting the playbook needs"):
        playbook.propose(FakeEnricher({}, no_tools="gemini can't run without tools, so "
                                      "routines that draft need Claude Code"), "text")
    with pytest.raises(EnrichError, match="give a website address"):
        playbook.propose(FakeEnricher({}), "  ")


# ------------------------------------------------------- voice from sent mail


def test_voice_from_sent_emails(folder):
    store = cli.build_store(folder)
    co = store.create_company(name="Example Bakery", website="https://bakery.example.com")
    store.create_interaction(co.slug, channel="email", direction="out",
                             body="Hi Sam,\n\nShort question: who bakes on Sundays?\n\nCheers\n"
                                  "\nOn Mon, Sam wrote:\n> an old quoted line")
    store.create_interaction(co.slug, channel="email", direction="in", body="Their reply")
    store.create_interaction(co.slug, channel="linkedin", direction="out", body="Not a mail")
    emails = playbook.sent_emails(cli.build_store(folder))
    assert emails == ["Hi Sam,\n\nShort question: who bakes on Sundays?\n\nCheers"]
    fake = FakeEnricher({"voice": "- Short questions.\n- Signs off with Cheers."})
    assert playbook.propose_voice(fake, emails) == {
        "section_voice": "- Short questions.\n- Signs off with Cheers."}
    (prompt, _, tools), = fake.calls
    assert tools == "" and "who bakes on Sundays" in prompt and "old quoted line" not in prompt
    with pytest.raises(EnrichError, match="no sent emails"):
        playbook.propose_voice(fake, [])


# --------------------------------------------------------------------- setup


def test_setup_step_saves_the_approach(folder):
    saved = playbook.save_basics(folder, "We clean offices.", "property, retail",
                                 "Office Manager, COO", "A made-up client saved 10 hours a week.",
                                 commit=cli.GitOps(folder, push_enabled=False).commit)
    assert saved == ["offer line", "industries", "buyer titles", "a customer result"]
    assert [o.name for o in playbook.require_ready(folder)] == [playbook.DEFAULT_APPROACH]
    assert git(folder, "log", "-1", "--format=%s").strip() == "playbook: your offer"
    assert playbook.save_basics(folder) == []


def test_check_hints_at_a_range_on_a_field_the_folder_does_not_have(tmp_path):
    (tmp_path / "MESSAGING.md").write_text(FILLED, encoding="utf-8")
    problems, hints = playbook.check_lines(tmp_path)
    assert problems == [] and len(hints) == 1 and "'employees'" in hints[0]
    (tmp_path / "fields.toml").write_text(
        '[[field]]\nkey = "employees"\ntype = "number"\n', encoding="utf-8")
    assert playbook.check_lines(tmp_path) == ([], [])
    assert playbook.range_fields(tmp_path) == [("employees", "employees")]


# ------------------------------------------------- saving keeps what you wrote

HANDWRITTEN = """---
approaches:
  - name: Clinic software
    offer_line: We build booking software for clinics.
    icp: {industries: [healthcare]}
    disqualifiers:
      - tag_present: [competitor]
      - country_in: [US]
    personas:
      Practice Lead: {titles: [Practice Manager], pains: [no-shows]}
    examples: [{who: a made-up clinic, url: "https://clinic.example.com"}]
---
# Approach: Clinic software

## Proof

<!-- private: ask Dr. Example before naming them -->

- A made-up clinic cut no-shows by a third.

## Lessons

My own intro line about what we learnt.

### Worked

- Short mails.

### Notes from last year

- Phone calls on Fridays.
"""


def test_saving_the_form_unchanged_keeps_every_byte():
    """Comments, text under Lessons outside its three parts and an extra ###
    part are not in the boxes, so an unchanged box must not rewrite them."""
    text = playbook.upgrade_text(HANDWRITTEN)
    approach = playbook.parse(text).approach("Clinic software")
    new, errors = playbook.save_form(text, "Clinic software", playbook.form_values(approach))
    assert errors == {} and new == text


def test_saving_one_box_keeps_the_comments_and_the_rest_of_lessons():
    text = playbook.upgrade_text(HANDWRITTEN)
    approach = playbook.parse(text).approach("Clinic software")
    values = {**playbook.form_values(approach),
              "section_proof": "- Two made-up clinics cut no-shows.",
              "lessons_worked": "- Short mails on Tuesdays."}
    new, errors = playbook.save_form(text, "Clinic software", values)
    assert errors == {}
    for kept in ("<!-- private: ask Dr. Example before naming them -->",
                 "My own intro line about what we learnt.",
                 "### Notes from last year\n\n- Phone calls on Fridays.\n"):
        assert kept in new, kept
    saved = playbook.parse(new).approach("Clinic software")
    assert saved.section("proof") == "- Two made-up clinics cut no-shows."
    assert saved.lessons()["worked"] == "- Short mails on Tuesdays."
    assert "- A made-up clinic cut no-shows by a third." not in new


def test_saving_keeps_personas_disqualifiers_and_keys_the_form_does_not_show():
    text = playbook.upgrade_text(HANDWRITTEN)
    approach = playbook.parse(text).approach("Clinic software")
    values = {**playbook.form_values(approach), "offer_line": "We build clinic booking."}
    new, errors = playbook.save_form(text, "Clinic software", values)
    assert errors == {}
    saved = playbook.parse(new)
    assert saved.error == ""
    front = saved.approach("Clinic software").front
    assert front["personas"] == {"Practice Lead": {"titles": ["Practice Manager"],
                                                   "pains": ["no-shows"]}}
    assert {"country_in": ["US"]} in front["disqualifiers"]
    assert front["examples"] == [{"who": "a made-up clinic", "url": "https://clinic.example.com"}]


def test_the_front_matter_always_reads_back_as_written():
    front = {"approaches": [{"name": "X", "disqualifiers": [{"tag_present": ["a", "b"]}],
                             "examples": [{"who": "x", "url": "y"}], "one": [{"k": "v, w: z"}]}]}
    text = playbook.dump_front(front)
    assert "- tag_present: [a, b]" in text
    assert playbook.parse_front(text) == front


def test_a_persona_name_in_any_script_can_be_saved():
    front, _, errors = playbook.from_form({"name": "X", "personas": "営業: 部長"})
    assert errors == {} and front["personas"] == {"営業": {"titles": ["部長"]}}


def test_a_name_with_a_hash_in_it_works_and_a_closing_hash_is_refused():
    text = playbook.add_approach(FILLED, "Training C#")
    assert playbook.upgrade_text(text) == text  # the block is found: nothing added twice
    pb = playbook.parse(text)
    assert pb.approach("Training C#").block.startswith("# Approach: Training C#")
    values = {**playbook.form_values(pb.approach("Training C#")), "offer_line": "We teach C#."}
    new, errors = playbook.save_form(text, "Training C#", values)
    assert errors == {} and playbook.parse(new).approach("Training C#").offer_line == "We teach C#."
    assert "Clinic software" in [a.name for a in playbook.parse(
        playbook.delete_approach(new, "Training C#")).approaches]
    with pytest.raises(playbook.PlaybookError):
        playbook.add_approach(FILLED, "Training #")


def test_a_missing_block_is_an_error_not_a_crash():
    text = FILLED.replace("# Approach: Clinic software", "# Something else")
    # upgrade adds the block again, so a save still works...
    assert playbook.parse(playbook.upgrade_text(text)).approach("Clinic software").block
    # ...and a body edited between reading and writing fails with a reason.
    with pytest.raises(playbook.PlaybookError, match="heading was not found"):
        playbook._block_span("", "Clinic software")


def test_check_and_upgrade_on_a_front_matter_that_is_not_ours(tmp_path):
    folder = init_folder(tmp_path / "crm")
    (folder / "MESSAGING.md").write_text("---\ntitle: my notes\n---\nbody\n", encoding="utf-8")
    problems, hints = playbook.check_lines(folder)
    assert problems == [] and "without `approaches:`" in hints[0]
    (folder / "MESSAGING.md").write_text("---\nSome notes\n\n---\n\nmore: [\n", encoding="utf-8")
    assert playbook.check_lines(folder)[0] == []
    (folder / "MESSAGING.md").write_text("---\napproaches: [\n---\nbody\n", encoding="utf-8")
    assert playbook.check_lines(folder)[0], "a broken playbook front matter is a problem"
    assert "cannot be read" in playbook.upgrade(folder)


# ------------------------------------------------- first step offer (optional)


def test_first_step_offer_is_optional_and_one_sentence():
    assert playbook.validate_front(playbook.parse(FILLED).front) == []
    assert playbook.parse(FILLED).approaches[0].first_step_offer == ""
    with_step = FILLED.replace(
        '    offer_line: "We build booking software for clinics."\n',
        '    offer_line: "We build booking software for clinics."\n'
        '    first_step_offer: "The first call is free, without a  pitch."\n')
    pb = playbook.parse(with_step)
    assert playbook.validate_front(pb.front) == []
    assert pb.approaches[0].first_step_offer == "The first call is free, without a pitch."
    for bad in ("[one, two]", "|\n      one\n      two", "5"):
        text = with_step.replace('"The first call is free, without a  pitch."', bad)
        problems = playbook.validate_front(playbook.parse(text).front)
        assert any("first_step_offer: one sentence" in p for p in problems), (bad, problems)


def test_first_step_offer_on_the_form():
    text = playbook.upgrade_text(MESSAGING)
    name = playbook.DEFAULT_APPROACH
    values = {"name": name, "offer_line": "We design brands.",
              "first_step_offer": "  The first call   is free. "}
    text, errors = playbook.save_form(text, name, values)
    assert errors == {}
    approach = playbook.parse(text).approach(name)
    assert approach.first_step_offer == "The first call is free."
    assert playbook.form_values(approach)["first_step_offer"] == "The first call is free."
    # Key order: right after offer_line.
    front = text.split("---")[1]
    assert front.index("offer_line:") < front.index("first_step_offer:") < front.index("icp:")
    # A form without the box keeps it; an emptied box removes it (left out when empty).
    kept, _ = playbook.save_form(text, name, {"name": name, "offer_line": "We design brands."})
    assert playbook.parse(kept).approach(name).first_step_offer == "The first call is free."
    gone, _ = playbook.save_form(text, name, {**values, "first_step_offer": ""})
    assert "first_step_offer" not in gone
