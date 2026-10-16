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


"""The playbook (MESSAGING.md front matter and seller sections): validation,
the readiness gate, persona matching, disqualifiers and the byte-for-byte
upgrade. All names are made up."""

import subprocess

import pytest

from hermitcrm import cli, playbook
from hermitcrm.datafolder import MESSAGING, init_folder
from hermitcrm.enrich import EnrichError
from hermitcrm.models import Company, Contact

FILLED = """---
offer_line: "We build booking software for clinics."
icp:
  industries: [healthcare]
  fte: [5, 200]
  countries: [NL, BE]
disqualifiers:
  - fte_over: 500
  - title_present: ["IT Director"]
  - no_salespeople: true
  - tag_present: [competitor]
personas:
  owner: {titles: ["Owner", "Practice Manager"]}
---
# Messaging playbook

## Proof

- A made-up clinic cut no-shows by a third.
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
    assert pb.has_front and not pb.error
    assert playbook.validate_front(pb.front) == []
    assert playbook.missing(pb) == []
    assert pb.proof == ["A made-up clinic cut no-shows by a third."]


def test_a_list_of_offer_lines_is_refused():
    text = FILLED.replace('offer_line: "We build booking software for clinics."',
                          "offer_line:\n  - one offer\n  - another offer")
    pb = playbook.parse(text)
    problems = playbook.validate_front(pb.front)
    assert any(playbook.ONE_OFFER in p for p in problems)
    assert any("offer line" in m for m in playbook.missing(pb))


@pytest.mark.parametrize("item, says", [
    ("- fte_over: lots", "fte_over takes a whole number"),
    ("- title_present: CEO", "title_present takes a list"),
    ("- no_salespeople: maybe", "no_salespeople takes true or false"),
    ("- revenue_under: 5", "revenue_under is not a disqualifier"),
    ("- {fte_over: 1, fte_under: 2}", "must be one `key: value`"),
])
def test_disqualifier_vocabulary(item, says):
    text = FILLED.replace("  - fte_over: 500", "  " + item)
    problems = playbook.validate_front(playbook.parse(text).front)
    assert any(says in p for p in problems), problems


@pytest.mark.parametrize("old, new, says", [
    ("fte: [5, 200]", "fte: [200, 5]", "icp.fte: must be [min, max]"),
    ("countries: [NL, BE]", "countries: [NL, Narnia]", "not a two-letter country code"),
    ("industries: [healthcare]", "industries: healthcare", "icp.industries: must be a list"),
    ("offer_line:", "offer_lines: x\noffer_line:", "offer_lines: not a playbook key"),
    ('owner: {titles: ["Owner", "Practice Manager"]}', "owner: {pains: [time]}",
     "personas.owner: has no titles"),
])
def test_front_matter_problems_are_named(old, new, says):
    problems = playbook.validate_front(playbook.parse(FILLED.replace(old, new)).front)
    assert any(says in p for p in problems), problems


def test_check_reports_problems_and_hints(folder):
    (folder / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    text, code = cli.cmd_check(cli.build_store(folder))
    assert code == 0 and "MESSAGING.md: not set up for the outreach bot" in text
    (folder / "MESSAGING.md").write_text(
        FILLED.replace('"We build booking software for clinics."', "[a, b]"),
        encoding="utf-8")
    text, code = cli.cmd_check(cli.build_store(folder))
    assert code == 1 and f"MESSAGING.md: front matter: offer_line: {playbook.ONE_OFFER}" in text
    (folder / "MESSAGING.md").write_text("---\noffer_line: [unclosed\n---\n", encoding="utf-8")
    text, code = cli.cmd_check(cli.build_store(folder))
    assert code == 1 and "not valid YAML" in text


# ----------------------------------------------------------------- readiness


def test_gate_blocks_an_empty_playbook(folder):
    with pytest.raises(playbook.NotReady) as exc:
        playbook.require_ready(folder)
    assert len(exc.value.missing) == 4
    message = str(exc.value)
    assert "offer line" in message and "persona" in message and "proof" in message
    assert "/settings/playbook" in message


def test_gate_blocks_a_missing_file_and_one_without_front_matter(tmp_path):
    with pytest.raises(playbook.NotReady):
        playbook.require_ready(tmp_path)
    (tmp_path / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    with pytest.raises(playbook.NotReady):
        playbook.require_ready(tmp_path)


@pytest.mark.parametrize("old, new, gap", [
    ('"We build booking software for clinics."', '""', "offer line"),
    ("- A made-up clinic cut no-shows by a third.", "<!-- a result -->", "proof line"),
    ('owner: {titles: ["Owner", "Practice Manager"]}', "owner: {titles: []}", "persona"),
])
def test_gate_names_each_gap(tmp_path, old, new, gap):
    (tmp_path / "MESSAGING.md").write_text(FILLED.replace(old, new), encoding="utf-8")
    gaps = [g for g in playbook.readiness(tmp_path) if "front matter" not in g]
    assert len(gaps) == 1 and gap in gaps[0]


def test_gate_needs_some_icp(tmp_path):
    text = FILLED.replace("  industries: [healthcare]\n  fte: [5, 200]\n  countries: [NL, BE]\n",
                          "  industries: []\n")
    (tmp_path / "MESSAGING.md").write_text(text, encoding="utf-8")
    assert playbook.readiness(tmp_path) == [
        "an ideal customer profile (at least one of industries, size, countries, "
        "funding or signals)"]


def test_gate_passes_the_demo_folder(tmp_path):
    folder = init_folder(tmp_path / "demo", demo=True)
    pb = playbook.require_ready(folder)
    assert pb.offer_line and all(ok for _, ok in playbook.completeness(pb))
    assert playbook.validate_front(pb.front) == []
    # Every line of the plain playbook is still there.
    assert all(line in pb.text.splitlines() for line in MESSAGING.splitlines())


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


# -------------------------------------------------------------- disqualifiers


def company(fte="", ae=None, titles=(), tags=()):
    co = Company(name="Example Ltd", slug="example-ltd", tags=list(tags))
    if fte:
        co.extra["fte_estimate"] = fte
    if ae is not None:
        co.extra["ae_count"] = ae
    for n, title in enumerate(titles):
        co.contacts[f"p{n}"] = Contact(first_name="Person", last_name=str(n), slug=f"p{n}", title=title)
    return co


def test_disqualifiers_exclude_on_known_fields():
    rules = playbook.parse(FILLED).disqualifiers
    assert not playbook.disqualify(company("~40", 2, ["CEO"]), rules).excluded
    assert playbook.disqualify(company("~900", 2, ["CEO"]), rules).reasons == [
        "more than 500 people (about 900)"]
    assert playbook.disqualify(company("~40", 0, ["CEO"]), rules).reasons == ["no salespeople"]
    assert playbook.disqualify(company("~40", 2, ["IT Director, EMEA"]), rules).reasons == [
        "already has a IT Director"]
    assert playbook.disqualify(company("~40", 2, ["CEO"], ["Competitor"]), rules).reasons == [
        "tagged competitor"]


def test_an_empty_field_cannot_decide():
    result = playbook.disqualify(company(), playbook.parse(FILLED).disqualifiers)
    assert not result.excluded
    assert "not checked: no headcount" in result.unchecked
    assert "not checked: no number of salespeople" in result.unchecked


# ------------------------------------------------------------------- upgrade


OLD_FILES = [
    MESSAGING,
    "# My notes\r\n\r\nNo trailing newline, Windows line ends",
    "",
    "## Proof\n\n- something we already wrote\n",
    "---\noffer_line: kept as written\n---\n# with front matter, no seller headings\n",
]


@pytest.mark.parametrize("old", OLD_FILES)
def test_upgrade_keeps_every_byte_and_is_idempotent(old):
    new = playbook.upgrade_text(old)
    source, body = playbook.split(new)
    assert source is not None
    old_body = playbook.split(old)[1]
    assert body.startswith(old_body)                     # byte for byte, in place
    if playbook.split(old)[0] is not None:
        assert new.startswith(old[: len(old) - len(old_body)])  # its front matter too
    assert playbook.upgrade_text(new) == new
    for _, title, _ in playbook.SECTIONS:
        assert f"## {title}\n" in new


def test_upgrade_does_not_duplicate_a_heading_already_there():
    new = playbook.upgrade_text(OLD_FILES[3])
    assert new.count("## Proof") == 1
    assert playbook.parse(new).proof == ["something we already wrote"]


def test_upgrade_command_is_one_commit_and_idempotent(folder):
    (folder / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    git(folder, "commit", "-qam", "an old playbook")
    before = git(folder, "rev-list", "--count", "HEAD")
    gitops = cli.GitOps(folder, push_enabled=False)
    text, code = cli.cmd_playbook(folder, "upgrade", commit=gitops.commit)
    assert code == 0 and "every line you had is kept" in text
    assert int(git(folder, "rev-list", "--count", "HEAD")) == int(before) + 1
    assert git(folder, "show", "--name-only", "--format=", "HEAD").split() == ["MESSAGING.md"]
    upgraded = (folder / "MESSAGING.md").read_text(encoding="utf-8")
    assert MESSAGING in upgraded
    text, code = cli.cmd_playbook(folder, "upgrade", commit=gitops.commit)
    assert "nothing changed" in text
    assert int(git(folder, "rev-list", "--count", "HEAD")) == int(before) + 1


def test_existing_folders_are_not_changed_by_other_commands(folder):
    (folder / "MESSAGING.md").write_text(MESSAGING, encoding="utf-8")
    for argv in (["check"], ["playbook"], ["playbook", "upgrade", "--dry-run"], ["rebuild"]):
        cli.main(argv, root=folder)
    assert (folder / "MESSAGING.md").read_text(encoding="utf-8") == MESSAGING


def test_status_command(folder, capsys):
    assert cli.main(["playbook", "status"], root=folder) == 1
    assert "will not run yet" in capsys.readouterr().out
    (folder / "MESSAGING.md").write_text(FILLED, encoding="utf-8")
    assert cli.main(["playbook"], root=folder) == 0
    assert "Ready for the outreach bot." in capsys.readouterr().out


# ---------------------------------------------------------------------- form


def test_form_round_trip_keeps_the_rest_of_the_body():
    text = playbook.upgrade_text(MESSAGING)
    values = {"offer_line": "  We  design   brands. ", "icp_industries": "food, Food, retail",
              "icp_countries": "fr, be", "icp_fte_min": "2", "icp_fte_max": "40",
              "dq_fte_over": "300", "dq_no_salespeople": "on",
              "personas": "Brand Owner: CMO, Founder\n\nbuyer: Head of Marketing",
              "section_proof": "- A made-up launch sold out in a week.",
              "section_voice": "Warm and short."}
    front, sections, errors = playbook.from_form(values, playbook.parse(text).front)
    assert errors == {}
    new = playbook.apply(text, front, sections)
    pb = playbook.parse(new)
    assert pb.offer_line == "We design brands."
    assert pb.icp["industries"] == ["food", "retail"] and pb.icp["countries"] == ["FR", "BE"]
    assert pb.icp["fte"] == [2, 40] and pb.icp["salespeople"] == []
    assert pb.disqualifiers == [{"fte_over": 300}, {"no_salespeople": True}]
    assert pb.personas == {"brand-owner": {"titles": ["CMO", "Founder"]},
                           "buyer": {"titles": ["Head of Marketing"]}}
    assert pb.section("voice") == "Warm and short." and playbook.validate_front(pb.front) == []
    assert "## What worked (write your own notes here)" in new
    assert playbook.form_values(pb)["personas"] == ("brand-owner: CMO, Founder\n"
                                                     "buyer: Head of Marketing")
    # Saving the same values again writes the same bytes.
    again = playbook.from_form(playbook.form_values(pb), pb.front)
    assert playbook.apply(new, again[0], again[1]) == new


def test_form_errors_and_kept_keys():
    old = {"personas": {"buyer": {"titles": ["CEO"], "pains": ["time"]}}}
    front, _, errors = playbook.from_form(
        {"icp_fte_min": "50", "icp_fte_max": "5", "dq_fte_over": "many",
         "personas": "buyer: CEO, COO\njust a line"}, old)
    assert set(errors) == {"icp_fte", "dq_fte_over", "personas"}
    assert front["personas"]["buyer"] == {"titles": ["CEO", "COO"], "pains": ["time"]}


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
              "proof": ["A made-up office stayed dry all winter."]}
    fake = FakeEnricher(answer)
    values = playbook.propose(fake, "Example Roofing fixes roofs. " * 3)
    (prompt, schema, tools), = fake.calls
    assert tools == "" and "Example Roofing" in prompt and "Never invent" in prompt
    assert values["offer_line"] == "We fix leaky roofs."
    assert values["icp_countries"] == "NL"
    assert values["personas"] == "facility-manager: Facility Manager"
    assert values["section_proof"] == "- A made-up office stayed dry all winter."
    assert not (tmp_path / "MESSAGING.md").exists()


def test_draft_refuses_a_cli_with_tools_and_empty_text():
    with pytest.raises(EnrichError, match="drafting the playbook needs"):
        playbook.propose(FakeEnricher({}, no_tools="gemini can't run without tools, so "
                                      "routines that draft need Claude Code"), "text")
    with pytest.raises(EnrichError, match="paste some text"):
        playbook.propose(FakeEnricher({}), "  ")


# --------------------------------------------------------------------- setup


def test_setup_step_saves_the_offer(folder):
    saved = playbook.save_basics(folder, "We clean offices.", "property, retail",
                                 "Office Manager, COO", "A made-up client saved 10 hours a week.",
                                 commit=cli.GitOps(folder, push_enabled=False).commit)
    assert saved == ["offer line", "industries", "buyer titles", "a customer result"]
    assert playbook.readiness(folder) == []
    assert git(folder, "log", "-1", "--format=%s").strip() == "playbook: your offer"
    assert playbook.save_basics(folder) == []


def test_routines_give_the_ai_the_body_only():
    assert playbook.body_for_ai(FILLED).startswith("# Messaging playbook")
    assert playbook.body_for_ai(MESSAGING) == MESSAGING
