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

"""search.py: matching, grouping, ranking, snippets and palette actions, on
records built in memory (no folder, no git)."""

from datetime import date, datetime
from types import SimpleNamespace

from hermitcrm import search as finder
from hermitcrm.models import Company, Contact, Interaction, Task


def company(name, slug, **kw) -> Company:
    return Company(name=name, slug=slug, **kw)


def person(first, last, slug, **kw) -> Contact:
    return Contact(first_name=first, last_name=last, slug=slug, **kw)


def message(id, when, subject="", body="", contact="", channel="email", direction="out"):
    return Interaction(id=id, date=when, channel=channel, direction=direction,
                       contact=contact, subject=subject, body=body)


def folder(*companies) -> SimpleNamespace:
    return SimpleNamespace(companies={c.slug: c for c in companies})


def titles(results, kind):
    return [h.title for h in results.group(kind).hits]


def acme() -> Company:
    c = company("Acme GmbH", "acme", website="https://acme.example.com",
                tags=["saas", "berlin"], product_oneliner="Payroll for bakeries",
                updated=datetime(2026, 9, 1))
    c.contacts["jane-doe"] = person("Jane", "Doe", "jane-doe", title="CTO",
                                    email="jane@acme.example.com")
    c.interactions.append(message(
        "2026-09-10T0900-email-out-jane-doe", datetime(2026, 9, 10, 9), "Pricing follow-up",
        "Hi Jane,\n\nAs promised, the quarterly invoice for the flamingo project is "
        "attached. Let me know if the numbers look right.", contact="jane-doe"))
    c.tasks.append(Task("Send the pricing page", due=date(2026, 9, 20)))
    return c


def test_a_word_only_in_a_message_body_finds_that_message():
    r = finder.search(folder(acme()), "flamingo")
    hits = r.group("interactions").hits
    assert [h.title for h in hits] == ["Pricing follow-up"]
    hit = hits[0]
    assert hit.url == "/companies/acme/contacts/jane-doe#i-2026-09-10T0900-email-out-jane-doe"
    assert "Jane Doe" in hit.detail and "Acme GmbH" in hit.detail
    assert ("flamingo", True) in hit.snippet
    assert r.total == 1   # nothing else says flamingo


def test_every_word_must_match_in_any_field_and_case_does_not_matter():
    data = folder(acme(), company("Berlin Bakers", "berlin-bakers"))
    assert titles(finder.search(data, "BERLIN"), "companies") == ["Berlin Bakers", "Acme GmbH"]
    # "saas" is a tag of Acme, "payroll" its one-liner: both words, two fields
    assert titles(finder.search(data, "saas payroll"), "companies") == ["Acme GmbH"]
    assert titles(finder.search(data, "saas bakers"), "companies") == []
    assert titles(finder.search(data, "acme.example"), "companies") == ["Acme GmbH"]
    assert titles(finder.search(data, "jane cto"), "contacts") == ["Jane Doe"]
    assert titles(finder.search(data, "jane@acme"), "contacts") == ["Jane Doe"]


def test_part_of_a_word_is_enough():
    r = finder.search(folder(acme()), "flam invo")
    assert titles(r, "interactions") == ["Pricing follow-up"]


def test_a_name_that_starts_with_the_query_comes_first_then_the_most_recent():
    old = company("Old Northwind", "old", updated=datetime(2025, 1, 1))
    new = company("New Northwind", "new", updated=datetime(2026, 9, 1))
    first = company("Northwind Labs", "labs", updated=datetime(2020, 1, 1))
    r = finder.search(folder(old, new, first), "northwind")
    assert titles(r, "companies") == ["Northwind Labs", "New Northwind", "Old Northwind"]


def test_a_company_is_as_recent_as_its_last_interaction():
    quiet = company("Quiet Harbour", "quiet", updated=datetime(2026, 1, 1))
    busy = company("Busy Harbour", "busy", updated=datetime(2025, 1, 1))
    busy.interactions.append(message("i1", datetime(2026, 9, 1), "hello"))
    assert titles(finder.search(folder(quiet, busy), "harbour"), "companies") == \
        ["Busy Harbour", "Quiet Harbour"]


def test_interactions_newest_first():
    c = company("Acme", "acme")
    c.interactions += [message("a", datetime(2026, 1, 1), "renewal one"),
                       message("b", datetime(2026, 6, 1), "renewal two"),
                       message("c", None, "a renewal without a date")]
    r = finder.search(folder(c), "renewal")
    assert titles(r, "interactions")[:2] == ["renewal two", "renewal one"]
    assert titles(r, "interactions")[2] == "a renewal without a date"


def test_at_most_eight_per_group_and_the_rest_counted():
    many = [company(f"Harbour {n:02}", f"h{n}") for n in range(12)]
    r = finder.search(folder(*many), "harbour")
    g = r.group("companies")
    assert len(g.hits) == 8 and g.total == 12 and g.more == 4
    assert len(finder.search(folder(*many), "harbour", limit=50).group("companies").hits) == 12


def test_kinds_keeps_only_those_groups():
    r = finder.search(folder(acme()), "pricing", kinds=("tasks",))
    assert [g.kind for g in r.groups] == ["tasks"]
    assert titles(r, "tasks") == ["Send the pricing page"]


def test_tasks_open_first_with_where_they_live():
    c = acme()
    c.tasks.append(Task("Pricing call done", done=True))
    c.contacts["jane-doe"].tasks.append(Task("Ask Jane about pricing"))
    c.next_step = "Pricing review"
    r = finder.search(folder(c), "pricing")
    hits = r.group("tasks").hits
    assert [h.title for h in hits][-1] == "Pricing call done"
    jane = next(h for h in hits if h.title == "Ask Jane about pricing")
    assert jane.url == "/companies/acme/contacts/jane-doe#tasks"
    review = next(h for h in hits if h.title == "Pricing review")
    assert review.url == "/companies/acme#tasks"
    assert "done" in hits[-1].detail


def test_a_message_to_the_company_links_to_the_company_page():
    c = company("Acme", "acme")
    c.interactions.append(message("n1", datetime(2026, 9, 1), "", "a note on budgets",
                                  channel="note", direction=""))
    hit = finder.search(folder(c), "budgets").group("interactions").hits[0]
    assert hit.url == "/companies/acme#i-n1"
    assert hit.title == "note with Acme"   # no subject: what it was, and with whom


def test_attachment_names_are_searched():
    from hermitcrm.attachments import Attachment
    c = company("Acme", "acme")
    it = message("m1", datetime(2026, 9, 1), "Contract")
    it.attachments.append(Attachment(file="abc-service-agreement.pdf",
                                     name="service-agreement.pdf", size=10,
                                     type="application/pdf"))
    c.interactions.append(it)
    assert titles(finder.search(folder(c), "agreement"), "interactions") == ["Contract"]


def test_pages_and_help_topics():
    r = finder.search(folder(), "pipe")
    assert ("Pipeline", "/pipeline") in [(h.title, h.url) for h in r.group("pages").hits]
    r = finder.search(folder(), "data format")
    assert [(h.title, h.url) for h in r.group("help").hits] == [("Data format", "/help/data-format")]
    # a page is found by another word for it too
    assert "Tasks" in titles(finder.search(folder(), "todo"), "pages")


def test_an_empty_or_blank_query_finds_nothing():
    for q in ("", "   ", None):
        r = finder.search(folder(acme()), q)
        assert r.total == 0 and all(not g.hits for g in r.groups)


def test_a_long_query_is_cut_not_refused():
    assert len(finder.words_of("word " * 100)) == 1
    assert len(finder.words_of(" ".join(f"w{n}" for n in range(30)))) == finder.MAX_WORDS
    assert len(finder.search(folder(), "x" * 5000).q) == finder.MAX_QUERY


def test_snippet_marks_every_match_and_trims_to_words():
    text = ("word " * 30) + "the Flamingo project and the flamingo invoice " + ("tail " * 40)
    parts = finder.snippet(text, ["flamingo", "invoice"])
    joined = "".join(t for t, _ in parts)
    assert joined.startswith("…") and joined.endswith("…")
    assert [t for t, hit in parts if hit] == ["Flamingo", "flamingo", "invoice"]
    assert " wor…" not in joined and not joined[1:].startswith("ord")
    assert finder.snippet("nothing here", ["flamingo"]) == ()
    whole = finder.snippet("short flamingo", ["flamingo"])
    assert whole == (("short ", False), ("flamingo", True))


def test_json_has_groups_with_hits_and_actions():
    data = finder.search(folder(acme()), "jane").to_json()
    assert data["q"] == "jane"
    assert [g["kind"] for g in data["groups"]] == ["contacts", "interactions"]
    labels = [a["label"] for a in data["actions"]]
    assert "Log a call with Jane Doe" in labels
    log = next(a for a in data["actions"] if a["label"].startswith("Log a call"))
    assert log["url"] == "/companies/acme/interactions/new?contact=jane-doe&channel=call"
    assert labels[-1] == "Ask Hermit: jane"
    ask = data["actions"][-1]
    assert ask["kind"] == "ask" and ask["question"] == "jane" and ask["url"] == ""
    hit = data["groups"][1]["hits"][0]
    assert isinstance(hit["snippet"], list) and ["Jane", True] in hit["snippet"]


def test_actions_for_an_empty_query_are_the_fixed_commands():
    labels = [a["label"] for a in finder.actions(finder.search(folder(acme()), ""))]
    assert labels == [label for label, _, _ in finder.COMMANDS]
    r = finder.search(folder(acme()), "acme")
    labels = [a["label"] for a in finder.actions(r)]
    assert "Add a task for Acme GmbH" in labels
    task = next(a for a in finder.actions(r) if a["label"].startswith("Add a task"))
    assert task["url"] == "/companies/acme#tasks"
    assert [a["label"] for a in finder.actions(finder.search(folder(), "new comp"))][:1] == \
        ["New company"]


def test_actions_only_go_to_get_pages():
    """No action posts anything: each is a link (or fills the Ask box)."""
    r = finder.search(folder(acme()), "a")
    for a in finder.actions(r):
        assert a["kind"] in ("go", "ask")
        assert a["kind"] == "ask" or a["url"].startswith("/")
