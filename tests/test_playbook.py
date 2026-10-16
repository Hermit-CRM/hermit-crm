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


"""The playbook (MESSAGING.md: offers in the front matter, an offer block per
offer in the body): validation, the readiness gate, persona matching, picking
the offer for a company, offers added, copied and deleted, and the
byte-for-byte upgrade. All names are made up."""

import subprocess

import pytest

from hermitcrm import cli, playbook
from hermitcrm.datafolder import MESSAGING, NEW_MESSAGING, init_folder
from hermitcrm.enrich import EnrichError
from hermitcrm.models import Company, Contact

FILLED = """---
offers:
  - name: Clinic software
    offer_line: "We build booking software for clinics."
    icp:
      industries: [healthcare]
      fte: [5, 200]
      countries: [NL, BE]
    disqualifiers:
      - title_present: ["IT Director"]
      - tag_present: [competitor]
    personas:
      owner: {titles: ["Owner", "Practice Manager"]}
---
# Messaging playbook

General notes.

# Offer: Clinic software

## Proof

- A made-up clinic cut no-shows by a third.

## Lessons

### Worked

- Short mails.
"""

TWO = """---
offers:
  - name: Founder coaching
    offer_line: I coach founders.
    icp: {salespeople: [0, 0], countries: [DE, NL]}
    personas: {founder: {titles: [CEO]}}
  - name: Team build-out
    offer_line: I build your sales team.
    icp: {salespeople: [1, 10], countries: [DE, NL]}
    disqualifiers:
      - title_present: [Head of Sales]
    personas: {founder: {titles: [CEO]}}
---
# Offer: Founder coaching

## Proof

- A made-up founder got a day a week back.

# Offer: Team build-out

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
    offer, = pb.offers
    assert playbook.offer_gaps(offer) == []
    assert offer.proof == ["A made-up clinic cut no-shows by a third."]
    assert offer.lessons() == {"worked": "- Short mails.", "failed": "", "open": ""}


def test_a_list_of_offer_lines_is_refused():
    text = FILLED.replace('offer_line: "We build booking software for clinics."',
                          "offer_line:\n      - one line\n      - another line")
    pb = playbook.parse(text)
    assert any(playbook.ONE_LINE in p for p in playbook.validate_front(pb.front))
    assert any("offer line" in g for g in playbook.offer_gaps(pb.offers[0]))


@pytest.mark.parametrize("item, says", [
    ("- title_present: CEO", "title_present takes a list"),
    ("- fte_over: 100", "fte_over is not a hard disqualifier"),
    ("- no_salespeople: true", "write it in the Disqualifiers section as text"),
    ("- {title_present: [a], tag_present: [b]}", "must be one `key: [...]`"),
])
def test_disqualifier_vocabulary(item, says):
    text = FILLED.replace('- title_present: ["IT Director"]', item)
    problems = playbook.validate_front(playbook.parse(text).front)
    assert any(says in p for p in problems), problems


@pytest.mark.parametrize("old, new, says", [
    ("fte: [5, 200]", "fte: [200, 5]", "icp.fte: must be [min, max]"),
    ("countries: [NL, BE]", "countries: [NL, Narnia]", "not a two-letter country code"),
    ("industries: [healthcare]", "industries: healthcare", "icp.industries: must be a list"),
    ("    offer_line:", "    offer_lines: x\n    offer_line:", "offer_lines: not an offer key"),
    ('owner: {titles: ["Owner", "Practice Manager"]}', "owner: {pains: [time]}",
     "personas.owner: has no titles"),
    ("  - name: Clinic software", "  - name: ''", "has no name"),
    ("offers:", "offer_line: x\noffers:", "offer_line: not a playbook key"),
])
def test_front_matter_problems_are_named(old, new, says):
    problems = playbook.validate_front(playbook.parse(FILLED.replace(old, new)).front)
    assert any(says in p for p in problems), problems


def test_two_offers_cannot_share_a_name():
    text = TWO.replace("name: Team build-out", "name: founder  COACHING")
    assert any("two offers are called" in p
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
    (folder / "MESSAGING.md").write_text("---\noffers: [unclosed\n---\n", encoding="utf-8")
    text, code = cli.cmd_check(cli.build_store(folder))
    assert code == 1 and "not valid YAML" in text


# ----------------------------------------------------------------- readiness


def test_gate_blocks_an_empty_playbook(folder):
    with pytest.raises(playbook.NotReady) as exc:
        playbook.require_ready(folder)
    assert len(exc.value.gaps[playbook.DEFAULT_OFFER]) == 4
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
    ("      industries: [healthcare]\n      fte: [5, 200]\n      countries: [NL, BE]\n",
     "      industries: []\n", "ideal customer"),
])
def test_gate_names_each_gap(tmp_path, old, new, gap):
    (tmp_path / "MESSAGING.md").write_text(FILLED.replace(old, new), encoding="utf-8")
    pb = playbook.load(tmp_path)
    gaps = [g for g in playbook.offer_gaps(pb.offers[0]) if "front matter" not in g]
    assert len(gaps) == 1 and gap in gaps[0]
    with pytest.raises(playbook.NotReady):
        playbook.require_ready(tmp_path)


def test_gate_passes_with_one_ready_offer_and_names_the_other(tmp_path):
    text = TWO.replace("- A made-up team hit quota.", "")
    (tmp_path / "MESSAGING.md").write_text(text, encoding="utf-8")
    assert [o.name for o in playbook.require_ready(tmp_path)] == ["Founder coaching"]
    with pytest.raises(playbook.NotReady, match="Team build-out: one proof line"):
        playbook.require_ready(tmp_path, offer="team build-out")
    with pytest.raises(playbook.NotReady, match="an offer called"):
        playbook.require_ready(tmp_path, offer="Nope")


def test_the_demo_folder_has_two_ready_offers(tmp_path):
    folder = init_folder(tmp_path / "demo", demo=True)
    ready = playbook.require_ready(folder)
    assert [o.name for o in ready] == ["Founder coaching", "Scaling the sales team"]
    assert all(all(ok for _, ok in playbook.completeness(o)) for o in ready)
    pb = playbook.load(folder)
    assert playbook.validate_front(pb.front) == []
    assert all(line in pb.text.splitlines() for line in NEW_MESSAGING.splitlines())
    assert "## What worked" not in pb.text  # Lessons, per offer, instead


def test_a_new_folder_has_one_empty_offer_and_no_what_worked(folder):
    pb = playbook.load(folder)
    assert [o.name for o in pb.offers] == [playbook.DEFAULT_OFFER]
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


# ---------------------------------------- disqualifiers and picking the offer


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


def test_hard_disqualifiers():
    offer = playbook.parse(FILLED).offers[0]
    assert not playbook.disqualify(company(titles=["CEO"]), offer).excluded
    assert playbook.disqualify(company(titles=["IT Director, EMEA"]), offer).reasons == [
        "already has a IT Director"]
    assert playbook.disqualify(company(tags=["Competitor"]), offer).reasons == [
        "tagged competitor"]
    assert playbook.disqualify(company(), offer).unchecked == [
        "not checked: no contact titles"]


@pytest.mark.parametrize("co, offer", [
    (company(ae=0), "Founder coaching"),
    (company(ae=3), "Team build-out"),
    (company(ae=3, titles=["Head of Sales"]), ""),   # disqualified for the one it fits
    (company(ae=3, country="FR"), ""),                # outside every ICP
])
def test_pick_offer_by_fit(co, offer):
    pick = playbook.pick_offer(co, playbook.parse(TWO).offers)
    assert pick.offer == offer and not pick.unclear


def test_pick_offer_asks_when_an_empty_field_cannot_decide():
    pick = playbook.pick_offer(company(), playbook.parse(TWO).offers)
    assert pick.offer == "" and pick.unclear == ["Founder coaching", "Team build-out"]
    assert "no number of salespeople" in pick.why


def test_pick_offer_says_why_an_offer_was_left_out():
    pick = playbook.pick_offer(company(ae=3, titles=["Head of Sales"]),
                               playbook.parse(TWO).offers)
    assert pick.left_out == {"Founder coaching": ["3 salespeople, wants 0 salespeople"],
                             "Team build-out": ["already has a Head of Sales"]}


# ------------------------------------------------------------------- upgrade


OLD_FILES = [
    MESSAGING,
    "# My notes\r\n\r\nNo trailing newline, Windows line ends",
    "",
    "## Proof\n\n- something we already wrote\n",
    "---\noffers:\n  - name: Kept\n    offer_line: as written\n---\n# Offer: Kept\n\n"
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
        assert playbook.parse(new).offers[0].proof == ["mine"]
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
    assert "no offer is ready" in capsys.readouterr().out
    (folder / "MESSAGING.md").write_text(TWO.replace("- A made-up team hit quota.", ""),
                                         encoding="utf-8")
    assert cli.main(["playbook"], root=folder) == 0
    out = capsys.readouterr().out
    assert "Ready for the outreach bot: Founder coaching." in out
    assert "Team build-out: " in out and "not ready, missing one proof line" in out


# --------------------------------------------------------- offers, the form


def test_form_round_trip_keeps_the_rest_of_the_file():
    text = playbook.upgrade_text(MESSAGING)
    values = {"name": "Brand design", "offer_line": "  We  design   brands. ",
              "icp_industries": "food, Food, retail", "icp_countries": "fr, be",
              "icp_fte_min": "2", "icp_fte_max": "40", "dq_tag_present": "customer",
              "personas": "Brand Owner: CMO, Founder\n\nbuyer: Head of Marketing",
              "section_proof": "- A made-up launch sold out in a week.",
              "section_voice": "Warm and short.", "section_disqualifiers": "- Agencies",
              "lessons_failed": "- Long mails."}
    new, errors = playbook.save_form(text, playbook.DEFAULT_OFFER, values)
    assert errors == {}
    offer, = playbook.parse(new).offers
    assert offer.name == "Brand design" and offer.offer_line == "We design brands."
    assert offer.icp["industries"] == ["food", "retail"] and offer.icp["countries"] == ["FR", "BE"]
    assert offer.icp["fte"] == [2, 40] and offer.icp["salespeople"] == []
    assert offer.disqualifiers == [{"tag_present": ["customer"]}]
    assert offer.personas == {"brand-owner": {"titles": ["CMO", "Founder"]},
                              "buyer": {"titles": ["Head of Marketing"]}}
    assert offer.section("voice") == "Warm and short."
    assert offer.section("disqualifiers") == "- Agencies"
    assert offer.lessons()["failed"] == "- Long mails."
    assert "# Offer: Brand design" in new and "# Offer: My offer" not in new
    assert MESSAGING in new
    # Saving the same values again writes the same bytes.
    again, _ = playbook.save_form(new, "Brand design", playbook.form_values(offer))
    assert again == new


def test_form_errors_and_kept_keys():
    old = {"name": "X", "personas": {"buyer": {"titles": ["CEO"], "pains": ["time"]}}}
    front, _, errors = playbook.from_form(
        {"name": "X", "icp_fte_min": "50", "icp_fte_max": "5",
         "personas": "buyer: CEO, COO\njust a line"}, old)
    assert set(errors) == {"icp_fte", "personas"}
    assert front["personas"]["buyer"] == {"titles": ["CEO", "COO"], "pains": ["time"]}
    assert "name" in playbook.from_form({"name": "a: b"})[2]


def test_save_refuses_a_name_another_offer_has():
    new, errors = playbook.save_form(TWO, "Team build-out", {
        **playbook.form_values(playbook.parse(TWO).offer("Team build-out")),
        "name": "Founder Coaching"})
    assert new == TWO and "already an offer called" in errors["name"]


def test_add_copy_and_delete_offers():
    text = playbook.add_offer(TWO, "Workshops")
    pb = playbook.parse(text)
    assert [o.name for o in pb.offers] == ["Founder coaching", "Team build-out", "Workshops"]
    assert playbook.offer_gaps(pb.offer("Workshops"))  # empty
    copied = playbook.add_offer(text, "Team build-out (UK)", copy_from="Team build-out")
    twin, source = (playbook.parse(copied).offer(n)
                    for n in ("Team build-out (UK)", "Team build-out"))
    assert twin.icp == source.icp and twin.proof == source.proof == ["A made-up team hit quota."]
    assert {k: v for k, v in twin.front.items() if k != "name"} == {
        k: v for k, v in source.front.items() if k != "name"}
    assert playbook.copy_name(playbook.parse(copied), "Team build-out") == "Copy of Team build-out"
    gone = playbook.delete_offer(copied, "Team build-out")
    pb = playbook.parse(gone)
    assert [o.name for o in pb.offers] == ["Founder coaching", "Workshops", "Team build-out (UK)"]
    assert pb.offer("Team build-out (UK)").proof == ["A made-up team hit quota."]
    assert "# Offer: Team build-out\n" not in gone
    assert playbook.validate_front(pb.front) == []
    with pytest.raises(playbook.PlaybookError, match="already an offer"):
        playbook.add_offer(TWO, "founder coaching")
    with pytest.raises(playbook.PlaybookError, match="at least one offer"):
        playbook.delete_offer(FILLED, "Clinic software")


def test_the_ai_reads_the_body_and_only_its_offer():
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
    assert 'offer called "Roof repair"' in prompt
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


def test_setup_step_saves_the_offer(folder):
    saved = playbook.save_basics(folder, "We clean offices.", "property, retail",
                                 "Office Manager, COO", "A made-up client saved 10 hours a week.",
                                 commit=cli.GitOps(folder, push_enabled=False).commit)
    assert saved == ["offer line", "industries", "buyer titles", "a customer result"]
    assert [o.name for o in playbook.require_ready(folder)] == [playbook.DEFAULT_OFFER]
    assert git(folder, "log", "-1", "--format=%s").strip() == "playbook: your offer"
    assert playbook.save_basics(folder) == []
