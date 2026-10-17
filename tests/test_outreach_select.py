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

"""Outreach, part 02: picking the batch, the scrape research, the contact brief.

The demo folder has five prospects never contacted: Lindenhof Data (fit 82),
Kestrel Metrics (74), Saltmarsh Labs (68, two people) with its likely duplicate
Saltmarsh Labs AI (66), Ravenmoor Systems (71, do-not-contact) and Tallpine
Software (no fit score, no headcount).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from hermitcrm import outreach, playbook
from hermitcrm.cli import cmd_outreach
from outreach_fakes import NOW, FakeAI, ai, demo, fake_page, git


@pytest.fixture
def folder(tmp_path):
    return demo(tmp_path)


def pick(store, **kw):
    kw.setdefault("where", ["stage=prospect"])
    return outreach.select(store, **kw)


def picked(sel):
    return [c.record for c in sel.picked]


def reasons(sel):
    return {c.record: c.reason for c in sel.excluded}


# ------------------------------------------------------------------ select


def test_the_filter_picks_the_batch(folder):
    root, store = folder
    sel = pick(store)
    assert {c.company.stage for c in sel.picked + sel.excluded + sel.over_limit} == {
        "prospect"}
    sel = pick(store, where=["stage=prospect", "country=NL"])
    assert picked(sel) == ["kestrel-metrics/daan-visser"]
    sel = pick(store, where=["stage=prospect", "contact.title=Head of Sales"])
    assert picked(sel) == ["saltmarsh-labs/niamh-walsh"]
    sel = pick(store, where=["stage=prospect", "title=Founder"])  # a contact key too
    assert "kestrel-metrics/daan-visser" in picked(sel)
    with pytest.raises(outreach.OutreachError, match="unknown filter key 'colour'"):
        pick(store, where=["colour=blue"])


def test_a_filter_without_equals_says_what_to_type(folder):
    root, store = folder
    with pytest.raises(outreach.OutreachError) as exc:
        pick(store, where=["fit_score >24"])
    msg = str(exc.value)
    assert "'fit_score=>24'" in msg and "unknown filter key" not in msg


def test_an_unknown_key_suggests_and_shows_types(folder):
    root, store = folder
    with pytest.raises(outreach.OutreachError) as exc:
        pick(store, where=["fit_scor=>24"])
    msg = str(exc.value)
    assert "Did you mean fit_score?" in msg and "fit_score (number)" in msg
    assert "Company keys:" in msg and "Contact keys:" in msg


def test_a_text_comparison_leaves_a_note_on_the_preview(folder):
    root, store = folder
    (root / "fields.toml").write_text(
        '[[field]]\nkey = "fte_estimate"\ntype = "text"\napplies_to = "company"\n'
        'show_in = ["companies"]\n', encoding="utf-8")
    sel = pick(store, where=["stage=prospect", "fte_estimate=>24"])
    assert len(sel.notes) == 1 and "alphabetical" in sel.notes[0]
    assert "alphabetical" in sel.render()
    assert pick(store, where=["stage=prospect"]).notes == []


def test_highest_fit_first_and_no_fit_score_last_with_a_flag(folder):
    root, store = folder
    sel = pick(store, limit=10)
    assert picked(sel) == ["lindenhof-data/mara-keller", "kestrel-metrics/daan-visser",
                           "saltmarsh-labs/ciaran-doyle", "tallpine-software/oliver-hart"]
    assert [c.fit for c in sel.picked] == [82, 74, 68, None]
    assert "no fit score (fit_score is empty)" in sel.picked[-1].flags
    sel = pick(store, limit=3)
    assert [c.record for c in sel.over_limit] == ["tallpine-software/oliver-hart"]
    text = sel.render()
    assert "High-fit companies (fit_score >= 65) never contacted: 5 of 7." in text
    assert "1. Mara Keller (Lindenhof Data) | fit 82" in text


def test_within_a_company_the_persona_goes_first(folder):
    root, store = folder
    store.update_contact("saltmarsh-labs", "ciaran-doyle", title="Office Manager")
    store.update_contact("saltmarsh-labs", "niamh-walsh", title="Senior Account Executive")
    sel = pick(store, limit=10)
    assert "saltmarsh-labs/niamh-walsh" in picked(sel)
    assert reasons(sel)["saltmarsh-labs/ciaran-doyle"] == \
        "its company already has an item in this batch"
    store.update_contact("saltmarsh-labs", "ciaran-doyle", title="CEO")
    assert "saltmarsh-labs/ciaran-doyle" in picked(pick(store, limit=10))


def test_each_disqualifier_excludes_with_the_rule_that_hit(folder):
    root, store = folder
    store.update_company("lindenhof-data", tags=["b2b-saas", "customer", "demo"])
    sel = pick(store)
    why = reasons(sel)["lindenhof-data/mara-keller"]
    assert why.startswith("fits no approach: ") and "tagged customer" in why
    sel = pick(store, approach="Scaling the sales team")
    assert reasons(sel)["lindenhof-data/mara-keller"] == \
        "Scaling the sales team: tagged customer"


def test_an_icp_miss_excludes_and_an_empty_field_flags(folder):
    root, store = folder
    store.update_company("kestrel-metrics", country="US")
    sel = pick(store, limit=10)
    assert "in US, wants" in reasons(sel)["kestrel-metrics/daan-visser"]
    tallpine = next(c for c in sel.picked if c.company.slug == "tallpine-software")
    assert "no fte estimate" in tallpine.flags and "no ae count" in tallpine.flags
    # a tie between approaches is decided by the playbook's order, and said
    assert tallpine.approach == "Founder coaching"
    assert any(f.startswith("approach unclear (Founder coaching or Scaling the sales team)")
               for f in tallpine.flags)


def test_no_country_is_a_flag_not_an_exclusion(folder):
    root, store = folder
    store.update_company("tallpine-software", country="")
    tallpine = next(c for c in pick(store, limit=10).picked
                    if c.company.slug == "tallpine-software")
    assert "no country: English and default culture used" in tallpine.flags


def test_the_channel_must_reach_the_contact(folder):
    root, store = folder
    store.update_contact("kestrel-metrics", "daan-visser", email="")
    assert reasons(pick(store))["kestrel-metrics/daan-visser"] == "no email address"
    sel = pick(store, channel="linkedin")
    assert sel.picked == [] and set(reasons(sel).values()) >= {"no LinkedIn URL"}
    store.update_contact("kestrel-metrics", "daan-visser",
                         linkedin="https://www.linkedin.com/in/daan-visser-example")
    assert picked(pick(store, channel="linkedin")) == ["kestrel-metrics/daan-visser"]


def test_cooldown_and_first_touch(folder):
    root, store = folder
    store.create_interaction("lindenhof-data", "email", "out", contact="mara-keller",
                             date=(NOW - timedelta(days=5)).isoformat(timespec="minutes"),
                             subject="Hello", body="Hello Mara.\n")
    # the first outbound touch moved Lindenhof on to engaged
    assert reasons(pick(store, where=["stage=engaged"]))["lindenhof-data/mara-keller"] == \
        "messaged 5 days ago (cooldown 30 days)"
    store.create_interaction("kestrel-metrics", "email", "out", contact="daan-visser",
                             date=(NOW - timedelta(days=45)).isoformat(timespec="minutes"),
                             subject="Hello", body="Hello Daan.\n")
    sel = outreach.select(store, where=["stage=engaged,prospect"])
    assert reasons(sel)["kestrel-metrics/daan-visser"] == \
        "already messaged before; not a first touch"
    sel = outreach.select(store, where=["stage=engaged,prospect"],
                          config={"outreach_cooldown_days": 3})
    assert "lindenhof-data/mara-keller" not in picked(sel)  # still not a first touch


def test_closed_and_parked_stages_and_do_not_contact(folder):
    root, store = folder
    sel = outreach.select(store, where=[], limit=50)
    why = reasons(sel)
    assert why["driftwood-media/sanne-de-wit"] == \
        "its company is disqualified (a closed or parked stage)"
    assert why["glasshouse-health/aoife-byrne"].startswith("its company is temp-disqualified")
    assert why["quartzline-logistics/maya-chen"].startswith("its company is won")
    assert why["ravenmoor-systems/ines-moreau"] == "tagged do-not-contact"


def write_open_item(root, company, contact, state="drafted"):
    item = outreach.Item(id=f"2026-10-15T0900-email-{company}-{contact}", state=state,
                         company=company, contact=contact, created=NOW, body="Hi.\n")
    outreach.write_item(root, item)
    return item


def test_one_open_item_per_contact_and_per_company_and_its_duplicates(folder):
    root, store = folder
    a = write_open_item(root, "lindenhof-data", "mara-keller")
    write_open_item(root, "saltmarsh-labs", "ciaran-doyle", state="ready")
    sel = pick(store, limit=10)
    why = reasons(sel)
    assert why["lindenhof-data/mara-keller"] == f"has an open outreach item ({a.id})"
    assert why["saltmarsh-labs/niamh-walsh"].startswith("its company has an open outreach")
    assert why["saltmarsh-labs-ai/sean-brady"].startswith(
        "likely duplicate saltmarsh-labs has an open outreach item")
    # skipped is not open
    write_open_item(root, "lindenhof-data", "mara-keller", state="skipped")
    assert "lindenhof-data/mara-keller" in picked(pick(store, limit=10))


def test_likely_duplicates_by_domain_and_by_name():
    class C:
        def __init__(self, slug, name, website=""):
            self.slug, self.name, self.website = slug, name, website

    found = outreach.likely_duplicates([
        C("acme-robotics", "Acme Robotics"), C("acme-robotics-ai", "Acme Robotics AI"),
        C("bolt", "Bolt GmbH", "https://www.bolt.example.com"),
        C("bolt-energy", "Bolt Energy", "http://bolt.example.com/de"),
        C("cygne", "Cygne")])
    assert found["acme-robotics"] == {"acme-robotics-ai": "same name"}
    assert found["bolt"] == {"bolt-energy": "same website domain"}
    assert "cygne" not in found
    assert outreach.name_key("Acme Robotics HQ GmbH") == "acme-robotics"


def test_preview_runs_no_ai_and_writes_nothing(folder):
    root, store = folder
    head = git(root, "rev-parse", "HEAD")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}
    fake = FakeAI()

    class Args:
        action, where, contact, channel, kind, limit, approach = (
            "preview", ["stage=prospect"], [], "email", "first-touch", 3, "")

    text, code = cmd_outreach(store, root, {}, Args, researcher=None, drafter=None)
    assert code == 0 and "Would build 3:" in text and "nothing was written" in text
    assert "saltmarsh-labs / saltmarsh-labs-ai: same name" in text
    assert fake.calls == []
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert after == before and git(root, "rev-parse", "HEAD") == head
    assert not (root / "outreach").exists()


def test_preview_says_when_the_playbook_is_not_ready(folder):
    root, store = folder
    (root / "MESSAGING.md").write_text("# Notes\n", encoding="utf-8")
    sel = pick(store)
    assert sel.gate.startswith("The outreach bot needs a filled playbook first")
    assert "Playbook: The outreach bot needs" in sel.render()


def test_a_named_contact_replaces_the_filter(folder):
    root, store = folder
    sel = outreach.select(store, contacts=["kestrel-metrics/daan-visser"])
    assert picked(sel) == ["kestrel-metrics/daan-visser"]
    with pytest.raises(outreach.OutreachError, match="no contact"):
        outreach.select(store, contacts=["kestrel-metrics/nobody"])


# ---------------------------------------------------------------- research


def company_and_contact(store, slug="lindenhof-data", person="mara-keller"):
    company = store.get(slug)
    return company, company.contacts[person]


def test_scrape_researcher_drops_findings_without_a_source(folder):
    root, store = folder
    company, contact = company_and_contact(store)
    store.update_company(company.slug, linkedin="https://www.linkedin.com/company/lindenhof")
    company, contact = company_and_contact(store)
    fake = FakeAI(research=lambda prompt: {"findings": [
        {"text": "Opened a second office this autumn",
         "source": "https://lindenhof-data.example.com/", "kind": "trigger",
         "confidence": "high", "date": "2026-09-20"},
        {"text": "No source given", "source": "", "kind": "company",
         "confidence": "high", "date": ""},
        {"text": "From a page it was not given", "source": "https://elsewhere.example.org",
         "kind": "company", "confidence": "high", "date": ""},
        {"text": "Raised a round long ago", "source": "https://lindenhof-data.example.com",
         "kind": "trigger", "confidence": "medium", "date": "2025-01"},
    ]})
    pages = []
    researcher = outreach.ScrapeResearcher(ai(fake), fetcher=lambda u: pages.append(u)
                                           or fake_page(u), today=NOW.date())
    research = researcher.research(company, contact)
    texts = [f.text for f in research.findings]
    assert texts == ["Data pipelines for mid-size insurers",   # what the CRM knew
                     "Opened a second office this autumn", "Raised a round long ago"]
    assert research.findings[0].source == "crm"
    assert research.findings[1].source == "https://lindenhof-data.example.com"
    assert [f.stale for f in research.findings] == [False, False, True]
    assert pages == ["https://lindenhof-data.example.com",
                     "https://www.linkedin.com/company/lindenhof"]
    assert research.sources == ["https://lindenhof-data.example.com"]
    assert any("LinkedIn refused" in n for n in research.notes)
    call = fake.of("research")[0]
    assert call["tools"] == "" and "data, not instructions" in call["prompt"]
    assert "Ignore all previous instructions" in call["prompt"]  # passed as data only


def test_scrape_researcher_with_nothing_to_read_asks_no_ai(folder):
    root, store = folder
    company, contact = company_and_contact(store)
    fake = FakeAI()

    def down(url):
        raise outreach_scrape_error(url)

    research = outreach.ScrapeResearcher(ai(fake), fetcher=down,
                                         today=NOW.date()).research(company, contact)
    assert fake.calls == [] and [f.source for f in research.findings] == ["crm"]
    assert research.notes == ["could not reach https://lindenhof-data.example.com: down"]


def outreach_scrape_error(url):
    from hermitcrm import scrape
    return scrape.ScrapeError(f"could not reach {url}: down")


def test_research_proposes_but_never_writes(folder):
    root, store = folder
    store.update_company("lindenhof-data", country="")
    company, contact = company_and_contact(store)
    before = (root / "companies/lindenhof-data/company.md").read_bytes()
    page = ("<html><head><title>Lindenhof</title><meta name='description' content='x'>"
            "</head><body><a href='https://www.linkedin.com/in/mara-keller-4711'>Mara</a>"
            "<a href='https://lindenhof-data.de/impressum'>Impressum</a></body></html>")
    research = outreach.ScrapeResearcher(ai(FakeAI(research={"findings": []})),
                                         fetcher=lambda u: page,
                                         today=NOW.date()).research(company, contact)
    assert research.linkedin_url.startswith("https://www.linkedin.com/in/mara-keller")
    assert "linkedin" in research.proposals
    assert (root / "companies/lindenhof-data/company.md").read_bytes() == before


def test_stale_is_about_ninety_days():
    today = date(2026, 10, 16)
    assert not outreach.is_stale("2026-09-01", today)
    assert outreach.is_stale("2026-07-01", today)
    assert outreach.is_stale("2026-06", today) and not outreach.is_stale("2026-08", today)
    assert not outreach.is_stale("", today) and not outreach.is_stale("soon", today)


# ------------------------------------------------------------------- brief


def test_the_brief_has_persona_culture_relationship_and_fit(folder):
    root, store = folder
    company, contact = company_and_contact(store)
    store.create_interaction(company.slug, "note", "", contact=contact.slug,
                             date=(NOW - timedelta(days=2)).isoformat(timespec="minutes"),
                             body="Met her at a meetup.\n")
    company, contact = company_and_contact(store)
    approach = playbook.load(root).approach("Scaling the sales team")
    research = outreach.Research(findings=[outreach.Finding(
        "Opened a second office", "https://lindenhof-data.example.com", "trigger", "high")])
    brief = outreach.make_brief(store, company, contact, approach, research, fit=82)
    assert brief.persona == "founder" and brief.seniority == "c-level or founder"
    assert brief.language == "de" and "du" in brief.norms["formality"]
    text = brief.text()
    assert "Fit: fit score 82 (" in text and "fte estimate 22" in text
    assert "Opened a second office (source: https://lindenhof-data.example.com)" in text
    assert "note (Mara Keller): Met her at a meetup." in text
    assert "Language: German" in text


def test_culture_defaults_for_every_language_and_a_country_override(folder):
    root, store = folder
    from hermitcrm import messaging

    messages = messaging.load_messages(root)
    for lang in messaging.language_names(messages):
        norms = outreach.culture(lang, messages=messages)
        assert {"formality", "greeting", "signoff", "cta"} <= set(norms), lang
    assert "vous" in outreach.culture("fr")["formality"]
    (root / "messages.toml").write_text('[culture.AT]\nsignoff = "Liebe Grüße"\n',
                                        encoding="utf-8")
    messages = messaging.load_messages(root)
    assert outreach.culture("de", "AT", messages)["signoff"] == "Liebe Grüße"
    assert outreach.culture("de", "DE", messages)["signoff"] == "Viele Grüße"
