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

"""The LinkedIn conversation import, Hermit side: payload -> Thread -> Match -> Plan."""

import re
from datetime import date, datetime

import pytest

from hermitcrm import conversation
from hermitcrm.conversation import ConversationError

# A Sunday. The browser's clock in the payload wins when it is there; the tests
# that leave it out are resolved against this.
NOW = datetime(2026, 11, 1, 14, 55)


def item(text="Hi Sam", *, is_other=True, who="Alex Voorbeeld", day="Today",
         time="9:15 AM", urn=None, inherited=False, sent_title="",
         who_href="/in/ACoAAAexample"):
    return {"urn": urn, "is_other": is_other, "who": who, "who_href": who_href,
            "day": day, "time": time, "inherited": inherited,
            "sent_title": sent_title, "text": text}


def payload(*items, lang="en", other=None, **extra):
    base = {"v": 1, "url": "https://www.linkedin.com/messaging/thread/2-abc/",
            "layout": "page",
            "other": {"name": "Alex Voorbeeld", "href": "/in/ACoAAAexample"}
            if other is None else other,
            "lang": lang, "tz_min": -60, "items": list(items)}
    base.update(extra)
    return base


def parse_one(day, *, lang="en", time="9:15 AM", now=NOW):
    thread = conversation.parse(payload(item(day=day, time=time), lang=lang), now)
    return thread, thread.messages[0]


# ------------------------------------------------------------ a normal thread


def test_a_one_to_one_thread_becomes_messages_in_page_order():
    thread = conversation.parse(payload(
        item("Hi Sam", is_other=True, time="9:15 AM", urn="urn:li:msg_message:(a,1)"),
        item("Hello Alex", is_other=False, who="Sam Voorbeeld", time="9:20 AM",
             urn="urn:li:msg_message:(a,2)"),
    ), NOW)
    assert thread.name == "Alex Voorbeeld"
    assert thread.needs_date == []
    assert [(m.direction, m.text, m.urn) for m in thread.messages] == [
        ("in", "Hi Sam\n", "urn:li:msg_message:(a,1)"),
        ("out", "Hello Alex\n", "urn:li:msg_message:(a,2)"),
    ]
    assert [m.when for m in thread.messages] == [
        datetime(2026, 11, 1, 9, 15), datetime(2026, 11, 1, 9, 20)]


def test_the_header_link_and_the_page_address_are_both_profile_addresses():
    thread = conversation.parse(payload(
        item(), url="https://www.linkedin.com/in/alex-voorbeeld/"), NOW)
    assert thread.profile_urls == ["https://www.linkedin.com/in/ACoAAAexample",
                                   "https://www.linkedin.com/in/alex-voorbeeld"]
    assert thread.profile_url == "https://www.linkedin.com/in/ACoAAAexample"


def test_an_address_that_is_not_a_linkedin_profile_is_dropped():
    thread = conversation.parse(payload(
        item(), url="https://evil.example.com/in/alex",
        other={"name": "Alex Voorbeeld", "href": "javascript:alert(1)"}), NOW)
    assert thread.profile_urls == []
    assert thread.profile_url == ""


def test_an_empty_thread_is_a_thread_without_messages():
    thread = conversation.parse(payload(), NOW)
    assert thread.messages == [] and thread.needs_date == []


def test_the_message_text_is_kept_with_its_line_breaks_and_one_trailing_newline():
    thread = conversation.parse(payload(item("Hello\r\n\r\nWorld  \r\n")), NOW)
    assert thread.messages[0].text == "Hello\n\nWorld  \n"


def test_a_message_without_text_is_left_out():
    thread = conversation.parse(payload(item("   \n"), item("Real")), NOW)
    assert [m.text for m in thread.messages] == ["Real\n"]


# ------------------------------------------------------------- day headings


@pytest.mark.parametrize("lang, heading, expected", [
    ("en", "Today", date(2026, 11, 1)),
    ("en", "Yesterday", date(2026, 10, 31)),
    ("en", "Wednesday", date(2026, 10, 28)),
    ("en", "Oct 28", date(2026, 10, 28)),
    ("en", "Oct 28, 2025", date(2025, 10, 28)),
    ("nl", "Vandaag", date(2026, 11, 1)),
    ("nl", "Gisteren", date(2026, 10, 31)),
    ("nl", "woensdag", date(2026, 10, 28)),
    ("nl", "28 okt", date(2026, 10, 28)),
    ("de", "Heute", date(2026, 11, 1)),
    ("de", "Gestern", date(2026, 10, 31)),
    ("de", "Mittwoch", date(2026, 10, 28)),
    ("de", "28. Oktober", date(2026, 10, 28)),
    ("fr", "Aujourd’hui", date(2026, 11, 1)),
    ("fr", "Hier", date(2026, 10, 31)),
    ("fr", "mercredi", date(2026, 10, 28)),
    ("fr", "28 oct.", date(2026, 10, 28)),
    ("es", "Hoy", date(2026, 11, 1)),
    ("es", "Ayer", date(2026, 10, 31)),
    ("es", "miércoles", date(2026, 10, 28)),
    ("es", "28 de octubre", date(2026, 10, 28)),
])
def test_a_day_heading_in_each_language_resolves_to_its_date(lang, heading, expected):
    thread, message = parse_one(heading, lang=lang, time="18:24")
    assert thread.needs_date == []
    assert message.when == datetime.combine(expected, datetime.min.time()).replace(
        hour=18, minute=24)


def test_a_weekday_is_the_most_recent_such_day_and_never_today():
    # Today is a Sunday and LinkedIn would say "Today", so "Sunday" is last week's.
    assert parse_one("Sunday")[1].when.date() == date(2026, 10, 25)
    assert parse_one("Monday")[1].when.date() == date(2026, 10, 26)
    assert parse_one("Saturday")[1].when.date() == date(2026, 10, 31)


def test_a_heading_without_a_year_that_would_be_in_the_future_is_last_year():
    january = datetime(2027, 1, 5, 9, 0)
    assert parse_one("Oct 28", now=january)[1].when.date() == date(2026, 10, 28)
    assert parse_one("Jan 4", now=january)[1].when.date() == date(2027, 1, 4)
    assert parse_one("Jan 6", now=january)[1].when.date() == date(2026, 1, 6)


def test_the_browsers_clock_in_the_payload_wins_over_the_servers():
    thread = conversation.parse(
        payload(item(day="Today"), now_local="2026-11-02T01:30"), NOW)
    assert thread.messages[0].when.date() == date(2026, 11, 2)


@pytest.mark.parametrize("stamp", [
    "0001-01-01T00:00", "9999-12-31T23:59", "2026-12-24T08:00", "nonsense", "", 5, None,
    "2026-11-01T14:55:00Z", "2026-11-01T14:55:00+01:00"])
def test_a_clock_that_is_absurd_or_not_a_plain_local_time_never_crashes_or_wins(stamp):
    for heading in ("Today", "Yesterday", "Monday", "Oct 28"):
        thread = conversation.parse(
            payload(item(day=heading), now_local=stamp), NOW)
        assert abs(thread.messages[0].when - NOW) < conversation.timedelta(days=10)


def test_an_unknown_heading_asks_for_the_date_and_dates_nothing():
    thread, message = parse_one("Sol 3")
    assert thread.needs_date == ["Sol 3"]
    assert message.when is None and message.heading == "Sol 3"


def test_a_heading_in_another_language_than_the_page_is_not_guessed():
    # A Dutch page says "Vandaag"; "Hoy" there is a sign something is off.
    thread, message = parse_one("Hoy", lang="nl")
    assert thread.needs_date == ["Hoy"] and message.when is None


def test_without_a_known_language_every_language_is_tried():
    assert parse_one("Gisteren", lang="")[1].when.date() == date(2026, 10, 31)
    assert parse_one("Gisteren", lang="pt")[1].when.date() == date(2026, 10, 31)
    # French and Spanish both abbreviate Tuesday to "mar": they agree, so it is read.
    assert parse_one("mar", lang="")[1].when.date() == date(2026, 10, 27)


def test_languages_that_read_a_heading_differently_make_it_a_question(monkeypatch):
    def invented(monday_word):
        names = [monday_word] + [f"{monday_word}{n}" for n in range(1, 7)]
        months = [f"{monday_word}m{n}" for n in range(12)]
        return conversation._language("t", "y", names, months)
    monkeypatch.setattr(conversation, "LANGUAGES",
                        {"aa": invented("foo"), "bb": invented("bar")})
    monkeypatch.setitem(conversation.LANGUAGES["bb"].weekdays, "foo", 1)  # Tuesday there
    assert conversation.parse_day("foo", date(2026, 11, 1), "") is None
    assert conversation.parse_day("foo", date(2026, 11, 1), "aa") == date(2026, 10, 26)
    assert conversation.parse_day("bar", date(2026, 11, 1), "") == date(2026, 10, 26)


def test_the_language_is_read_from_a_locale_tag():
    assert parse_one("Gisteren", lang="nl-NL")[1].when.date() == date(2026, 10, 31)
    assert parse_one("Gisteren", lang="NL_be")[1].when.date() == date(2026, 10, 31)


def test_the_same_unknown_heading_is_asked_once():
    thread = conversation.parse(payload(
        item(day="Sol 3"), item(day="Sol 3"), item(day="Sol 4")), NOW)
    assert thread.needs_date == ["Sol 3", "Sol 4"]


def test_a_follow_up_without_a_day_or_a_time_takes_the_previous_ones():
    thread = conversation.parse(payload(
        item("one", day="Wednesday", time="6:24 PM"),
        item("two", day="", time="", inherited=True),
    ), NOW)
    first, second = thread.messages
    assert second.when == first.when == datetime(2026, 10, 28, 18, 24)
    assert second.inherited and not first.inherited


# -------------------------------------------------------------------- times


@pytest.mark.parametrize("text, hour, minute", [
    ("6:24 PM", 18, 24), ("6:24 pm", 18, 24), ("6:24 p.m.", 18, 24),
    ("12:26 AM", 0, 26), ("12:30 PM", 12, 30), ("9:05 AM", 9, 5),
    ("18:24", 18, 24), ("09:05", 9, 5), ("0:00", 0, 0),
])
def test_twelve_and_twenty_four_hour_times(text, hour, minute):
    thread, message = parse_one("Today", time=text)
    assert thread.needs_date == []
    assert (message.when.hour, message.when.minute) == (hour, minute)


@pytest.mark.parametrize("text", ["", "late", "25:00", "13:00 PM", "6:75 AM"])
def test_a_time_that_cannot_be_read_asks_instead_of_guessing(text):
    thread, message = parse_one("Today", time=text)
    assert message.when is None
    assert thread.needs_date == [f"Today {text}".strip()]


def test_an_own_message_with_an_absolute_title_checks_the_heading():
    ok = conversation.parse(payload(item(
        is_other=False, day="Saturday", time="6:24 PM",
        sent_title="Sent at 10/31/2026, 6:24 PM")), NOW).messages[0]
    wrong = conversation.parse(payload(item(
        is_other=False, day="Today", time="6:24 PM",
        sent_title="Sent at 10/31/2026, 6:24 PM")), NOW).messages[0]
    assert ok.date_conflict is False
    assert wrong.date_conflict is True


def test_a_title_in_a_format_it_does_not_know_checks_nothing():
    message = conversation.parse(payload(item(
        is_other=False, day="Today", time="6:24 PM",
        sent_title="Verzonden op 31-10-2026 18:24")), NOW).messages[0]
    assert message.date_conflict is False


# ------------------------------------------------------------------- groups


def test_a_group_conversation_is_refused():
    with pytest.raises(ConversationError, match="group conversations are not supported"):
        conversation.parse(payload(
            item(who="Alex Voorbeeld", who_href="/in/ACoAAAone"),
            item(who="Robin Voorbeeld", who_href="/in/ACoAAAtwo"),
        ), NOW)


def test_a_header_without_a_person_is_refused_as_a_group():
    with pytest.raises(ConversationError, match="group conversations are not supported"):
        conversation.parse(payload(item(), other={"name": "", "href": ""}), NOW)


def test_one_person_who_writes_several_times_is_not_a_group():
    thread = conversation.parse(payload(item("a"), item("b", inherited=True)), NOW)
    assert len(thread.messages) == 2


# ---------------------------------------------------------- hostile payloads


@pytest.mark.parametrize("bad", [None, "text", [], 5, {"v": 2, "items": []},
                                 {"v": 1, "items": "no"}, {"v": 1}])
def test_a_payload_of_the_wrong_shape_is_refused(bad):
    with pytest.raises(ConversationError):
        conversation.parse(bad, NOW)


def test_items_of_the_wrong_type_are_skipped_not_crashed_on():
    thread = conversation.parse(payload(
        item("kept"), "x", 5, None, {"text": 7, "day": ["a"]}, item("also")), NOW)
    assert [m.text for m in thread.messages] == ["kept\n", "also\n"]


def test_a_header_whose_fields_are_not_text_names_nobody():
    with pytest.raises(ConversationError):
        conversation.parse(payload(item(), other={"name": 7, "href": {}}), NOW)


def test_control_characters_and_nul_are_stripped_but_tab_and_newline_stay():
    thread = conversation.parse(payload(item("a\x00b\x07c\x1b[31m\td\ne\x7f")), NOW)
    assert thread.messages[0].text == "abc[31m\td\ne\n"


def test_nothing_in_the_payload_is_executed_or_used_as_a_path():
    nasty = "__import__('os').system('true') ${HOME} ../../etc/passwd </script><img src=x>"
    thread = conversation.parse(payload(
        item(nasty, who="../../x", urn="../../etc/passwd"),
        other={"name": "../../etc", "href": "/in/../../etc/passwd"}), NOW)
    assert thread.messages[0].text == nasty + "\n"
    assert thread.messages[0].urn == "../../etc/passwd"
    assert thread.name == "../../etc"
    assert all(u.startswith("https://www.linkedin.com/in/") for u in thread.profile_urls)


def test_more_than_500_messages_keeps_the_newest_500():
    items = [item(f"m{n}", urn=f"u{n}") for n in range(600)]
    thread = conversation.parse(payload(*items), NOW)
    assert len(thread.messages) == 500 and thread.dropped == 100
    assert thread.messages[0].urn == "u100" and thread.messages[-1].urn == "u599"


def test_a_message_over_20000_characters_is_cut():
    thread = conversation.parse(payload(item("a" * 25000)), NOW)
    assert thread.messages[0].text == "a" * 20000 + "\n"


def test_a_payload_over_a_megabyte_of_text_keeps_the_newest_messages():
    items = [item("é" * 10000, urn=f"u{n}") for n in range(100)]
    thread = conversation.parse(payload(*items), NOW)
    assert sum(len(m.text.encode()) for m in thread.messages) <= 1_000_000
    assert 10 < len(thread.messages) < 100
    assert thread.messages[-1].urn == "u99"
    assert thread.dropped == 100 - len(thread.messages)


# ================================================================ Task 1.2
# Direction: whose message is it. Matching: whose thread is it.


def thread_of(*messages, name="Alex Voorbeeld", urls=()):
    return conversation.Thread(name=name, profile_urls=list(urls), messages=list(messages))


def msg(marker, who="", text="x\n"):
    return conversation.Message(direction=marker, when=NOW, text=text, who=who)


@pytest.mark.parametrize("marker, who, owner, expected", [
    # the page's own marker is the primary signal
    ("in", "", "Sam Voorbeeld", "in"),
    ("out", "", "Sam Voorbeeld", "out"),
    # the sender's name agrees with it
    ("in", "Alex Voorbeeld", "Sam Voorbeeld", "in"),
    ("out", "Sam Voorbeeld", "Sam Voorbeeld", "out"),
    ("in", "ALEX voorbeeld", "Sam Voorbeeld", "in"),
    ("in", "Alex Voorbeeld", "", "in"),
    # it disagrees: ask, never guess
    ("out", "Alex Voorbeeld", "Sam Voorbeeld", "ask"),
    ("in", "Sam Voorbeeld", "Sam Voorbeeld", "ask"),
    ("out", "Alex Voorbeeld", "", "ask"),
    # a third name is neither of the two people
    ("in", "Robin Derde", "Sam Voorbeeld", "ask"),
    ("out", "Robin Derde", "Sam Voorbeeld", "ask"),
    ("in", "Robin Derde", "", "ask"),
    # without a configured name an own message cannot be checked: the marker stands
    ("out", "Sam Voorbeeld", "", "out"),
    # no marker, no direction
    ("ask", "Alex Voorbeeld", "Sam Voorbeeld", "ask"),
])
def test_direction_is_the_pages_marker_cross_checked_against_the_names(
        marker, who, owner, expected):
    assert conversation.direction_for(marker, who, "Alex Voorbeeld", owner) == expected


def test_names_are_compared_without_case_accents_or_pronouns():
    assert conversation.same_name("Åsa  Müller", "asa muller")
    assert conversation.same_name("Alex Voorbeeld (He/Him)", "Alex Voorbeeld")
    assert not conversation.same_name("Alex", "Alex Voorbeeld")
    assert not conversation.same_name("", "")


def test_a_thread_gets_its_directions_checked_message_by_message():
    thread = thread_of(msg("in", "Alex Voorbeeld"), msg("out", "Sam Voorbeeld"),
                       msg("out", "Alex Voorbeeld"))
    checked = conversation.check_directions(thread, "Sam Voorbeeld")
    assert [m.direction for m in checked.messages] == ["in", "out", "ask"]
    assert [m.direction for m in thread.messages] == ["in", "out", "out"]  # not changed


def people(store):
    assert store.create_company("Voorbeeld", country="NL").slug == "voorbeeld"
    assert store.create_company("Tweede", country="NL").slug == "tweede"
    return store


def test_a_contact_is_found_by_the_pages_vanity_address(store):
    people(store)
    store.create_contact("voorbeeld", "Alex", "Voorbeeld",
                         linkedin="https://nl.linkedin.com/in/alex-voorbeeld/")
    thread = thread_of(urls=["https://www.linkedin.com/in/ACoAAAunknown",
                             "https://www.linkedin.com/in/alex-voorbeeld"], name="A. V.")
    found = conversation.match(store, thread)
    assert (found.kind, found.company, found.contact) == (
        "profile", "voorbeeld", "alex-voorbeeld")


def test_a_contact_who_was_saved_with_the_member_address_is_found_by_it(store):
    people(store)
    store.create_contact("voorbeeld", "Alex", "Voorbeeld",
                         linkedin="https://www.linkedin.com/in/ACoAAAexample/")
    thread = thread_of(urls=["https://www.linkedin.com/in/ACoAAAexample"], name="Someone Else")
    assert conversation.match(store, thread).kind == "profile"


def test_without_an_address_the_full_name_finds_the_contact(store):
    people(store)
    contact = store.create_contact("voorbeeld", "Åsa", "Müller")
    found = conversation.match(store, thread_of(name="asa  MULLER"))
    assert (found.kind, found.company, found.contact) == ("name", "voorbeeld", contact.slug)


def test_the_address_beats_the_name(store):
    people(store)
    store.create_contact("voorbeeld", "Alex", "Voorbeeld")
    store.create_contact("tweede", "Robin", "Anders",
                         linkedin="https://www.linkedin.com/in/ACoAAAexample")
    found = conversation.match(
        store, thread_of(urls=["https://www.linkedin.com/in/ACoAAAexample"]))
    assert (found.kind, found.company, found.contact) == ("profile", "tweede", "robin-anders")


def test_two_contacts_with_one_name_are_candidates_never_a_guess(store):
    people(store)
    store.create_contact("voorbeeld", "Alex", "Voorbeeld")
    store.create_contact("tweede", "Alex", "Voorbeeld")
    found = conversation.match(store, thread_of())
    assert found.kind == "ambiguous" and found.company == "" and found.contact == ""
    assert found.candidates == [("tweede", "alex-voorbeeld"),
                                ("voorbeeld", "alex-voorbeeld")]


def test_two_contacts_with_one_name_in_one_company_are_candidates_too(store):
    people(store)
    store.create_contact("voorbeeld", "Alex", "Voorbeeld")
    store.create_contact("voorbeeld", "Alex", "Voorbeeld")
    assert conversation.match(store, thread_of()).kind == "ambiguous"


def test_two_contacts_sharing_an_address_are_candidates_never_a_guess(store):
    people(store)
    url = "https://www.linkedin.com/in/alex-voorbeeld"
    store.create_contact("voorbeeld", "Alex", "Voorbeeld", linkedin=url)
    store.create_contact("tweede", "Alexander", "Voorbeeld", linkedin=url)
    found = conversation.match(store, thread_of(urls=[url]))
    assert found.kind == "ambiguous" and len(found.candidates) == 2


def test_nobody_known_is_none_and_an_empty_name_matches_nobody(store):
    people(store)
    store.create_contact("voorbeeld", "Alex", "Voorbeeld")
    found = conversation.match(store, thread_of(name="Robin Anders"))
    assert (found.kind, found.company, found.contact, found.candidates) == ("none", "", "", [])
    assert conversation.match(store, thread_of(name="")).kind == "none"


# ================================================================ Task 1.3
# Plan, de-duplicate, apply.

from hermitcrm import migrations, outreach  # noqa: E402
from hermitcrm.models import InteractionSource  # noqa: E402
from hermitcrm.store import Store  # noqa: E402

OWNER = "Sam Voorbeeld"
COMPANY, CONTACT = "voorbeeld", "alex-voorbeeld"


def world(store, stage=None):
    store.create_company("Voorbeeld", country="NL")
    store.create_contact(COMPANY, "Alex", "Voorbeeld",
                         linkedin="https://www.linkedin.com/in/alex-voorbeeld")
    if stage:
        store.update_company(COMPANY, stage=stage)
    return store


def theirs(text, day, time, urn, **kw):
    return item(text, is_other=True, who="Alex Voorbeeld", day=day, time=time, urn=urn, **kw)


def mine(text, day, time, urn, **kw):
    return item(text, is_other=False, who=OWNER, day=day, time=time, urn=urn, **kw)


def thread3(*extra):
    return conversation.parse(payload(
        theirs("Hi Sam", "Wednesday", "6:24 PM", "u1"),
        mine("Hello Alex", "Wednesday", "6:30 PM", "u2"),
        theirs("Great, call Friday?", "Thursday", "9:05 AM", "u3"),
        *extra), NOW)


def planned(store, thread, **kw):
    kw.setdefault("owner_name", OWNER)
    return conversation.plan(store, COMPANY, CONTACT, thread, NOW, **kw)


def interactions(store):
    return sorted(store.get(COMPANY, refresh=True).interactions, key=lambda i: (i.date, i.id))


def test_a_fresh_thread_is_all_new_and_ticked_by_default(store):
    world(store)
    p = planned(store, thread3())
    assert [r.status for r in p.rows] == ["new", "new", "new"]
    assert p.default_selection == [0, 1, 2]
    assert [r.message.direction for r in p.rows] == ["in", "out", "in"]


def test_apply_logs_each_message_as_a_linkedin_interaction_in_one_commit(store, messages):
    world(store, stage="engaged")
    before = len(messages)
    result = conversation.apply(store, planned(store, thread3()), [0, 1, 2])
    assert len(result.ids) == 3 and result.skipped == 0
    assert len(messages) == before + 1
    assert messages[-1] == "interaction: voorbeeld linkedin import alex-voorbeeld (3 messages)"
    first, second, third = interactions(store)
    assert (first.channel, first.direction, first.contact) == ("linkedin", "in", CONTACT)
    assert (second.direction, third.direction) == ("out", "in")
    assert first.date == datetime(2026, 10, 28, 18, 24)
    assert third.date == datetime(2026, 10, 29, 9, 5)
    assert [i.source for i in (first, second, third)] == ["linkedin-import"] * 3
    assert [i.message_id for i in (first, second, third)] == [
        "linkedin:u1", "linkedin:u2", "linkedin:u3"]
    assert first.body == "Hi Sam\n" and second.body == "Hello Alex\n"


def test_the_commit_of_one_message_says_message(store, messages):
    world(store, stage="engaged")
    t = conversation.parse(payload(theirs("Hi", "Wednesday", "6:24 PM", "u1")), NOW)
    conversation.apply(store, planned(store, t), [0])
    assert messages[-1] == "interaction: voorbeeld linkedin import alex-voorbeeld (1 message)"


def test_the_message_text_is_stored_byte_for_byte(store):
    world(store, stage="engaged")
    text = "Hej  \tmed mellanrum  \n\n\u00c5sa \u2713 <b>&amp;</b> --- \n"
    t = conversation.parse(payload(theirs(text, "Wednesday", "6:24 PM", "u1")), NOW)
    conversation.apply(store, planned(store, t), [0])
    stored = interactions(store)[0]
    assert stored.body == text
    assert store.interaction_file(COMPANY, stored.id).read_text(encoding="utf-8").endswith(
        "\n" + text)


def test_importing_the_same_thread_twice_adds_nothing_and_commits_nothing(store, messages):
    world(store, stage="engaged")
    conversation.apply(store, planned(store, thread3()), [0, 1, 2])
    before, files = len(messages), sorted(p.name for p in store.root.rglob("*.md"))
    again = planned(store, thread3())
    assert [r.status for r in again.rows] == ["logged"] * 3
    assert again.default_selection == []
    result = conversation.apply(store, again, [0, 1, 2])
    assert result.ids == [] and result.skipped == 3
    assert len(messages) == before
    assert sorted(p.name for p in store.root.rglob("*.md")) == files


def test_what_was_imported_is_still_logged_after_the_folder_is_read_again(store):
    world(store, stage="engaged")
    conversation.apply(store, planned(store, thread3()), [0, 1, 2])
    fresh = Store(store.root)
    assert fresh.load() == []  # linkedin-import and the message ids are valid front matter
    assert [r.status for r in planned(fresh, thread3()).rows] == ["logged"] * 3


def test_a_thread_that_grew_by_two_messages_adds_exactly_those_two(store):
    world(store, stage="engaged")
    conversation.apply(store, planned(store, thread3()), [0, 1, 2])
    grown = thread3(mine("Friday works", "Thursday", "9:30 AM", "u4"),
                    theirs("Great", "Thursday", "9:41 AM", "u5"))
    p = planned(store, grown)
    assert [r.status for r in p.rows] == ["logged"] * 3 + ["new"] * 2
    result = conversation.apply(store, p, p.default_selection)
    assert len(result.ids) == 2 and len(interactions(store)) == 5


def test_a_message_without_an_id_is_keyed_by_contact_direction_minute_and_text(store):
    world(store, stage="engaged")
    def thread(text="Hi Sam", time="6:24 PM"):
        return conversation.parse(payload(theirs(text, "Wednesday", time, None)), NOW)
    a = planned(store, thread()).rows[0].message_id
    assert a == planned(store, thread()).rows[0].message_id
    assert re.fullmatch(r"linkedin:alex-voorbeeld:[0-9a-f]{16}", a)
    assert a != planned(store, thread(text="Hi Sam!")).rows[0].message_id
    assert a != planned(store, thread(time="6:25 PM")).rows[0].message_id
    conversation.apply(store, planned(store, thread()), [0])
    assert planned(store, thread()).rows[0].status == "logged"


def test_a_hand_logged_copy_that_differs_in_bytes_is_maybe_not_new(store):
    world(store, stage="engaged")
    store.create_interaction(COMPANY, "linkedin", "out", contact=CONTACT,
                             date=datetime(2026, 10, 28, 18, 40),
                             body="Hello   Alex \r\n\r\n")
    p = planned(store, thread3())
    assert [r.status for r in p.rows] == ["new", "maybe", "new"]
    assert p.rows[1].existing  # which interaction it looks like
    assert p.default_selection == [0, 2]
    result = conversation.apply(store, p, [0, 1, 2])  # ticking a maybe imports it
    assert len(result.ids) == 3


def test_a_look_alike_must_be_the_same_contact_direction_text_and_within_a_day(store):
    world(store, stage="engaged")
    store.create_contact(COMPANY, "Robin", "Anders")
    other = dict(channel="linkedin", body="Hello Alex\n")
    day = datetime(2026, 10, 28, 18, 30)
    store.create_interaction(COMPANY, direction="out", contact="robin-anders", date=day, **other)
    store.create_interaction(COMPANY, direction="in", contact=CONTACT, date=day, **other)
    store.create_interaction(COMPANY, direction="out", contact=CONTACT,
                             date=datetime(2026, 10, 26, 18, 30), **other)  # two days off
    store.create_interaction(COMPANY, "email", "out", contact=CONTACT, date=day,
                             subject="x", body="Hello Alex\n")
    assert planned(store, thread3()).rows[1].status == "new"


def test_an_outreach_message_you_sent_through_hermit_is_a_look_alike_too(store):
    world(store, stage="engaged")
    store.create_interaction(COMPANY, "linkedin", "out", contact=CONTACT,
                             date=datetime(2026, 10, 28, 18, 29), body="Hello Alex\n",
                             source="outreach")
    assert planned(store, thread3()).rows[1].status == "maybe"


def test_an_earlier_import_with_another_id_is_not_a_hand_logged_look_alike(store):
    world(store, stage="engaged")
    store.create_interaction(COMPANY, "linkedin", "out", contact=CONTACT,
                             date=datetime(2026, 10, 28, 18, 30), body="Hello Alex\n",
                             source="linkedin-import", message_id="linkedin:another")
    assert planned(store, thread3()).rows[1].status == "new"


def test_two_messages_in_one_minute_get_their_own_ids(store):
    world(store, stage="engaged")
    t = conversation.parse(payload(
        theirs("One", "Wednesday", "6:24 PM", "u1"),
        theirs("Two", "Wednesday", "6:24 PM", "u2")), NOW)
    result = conversation.apply(store, planned(store, t), [0, 1])
    assert len(set(result.ids)) == 2 and len(interactions(store)) == 2


def test_the_first_touch_advances_a_prospect_once_in_the_same_commit(store, messages):
    world(store)
    entry, target = store.stages.entry, store.stages.advance_target
    assert store.get(COMPANY).stage == entry
    p = planned(store, thread3())
    assert p.stage_change == f"{entry} -> {target}"
    before = len(messages)
    conversation.apply(store, p, [0, 1, 2])
    assert store.get(COMPANY).stage == target
    assert len(messages) == before + 1
    assert messages[-1].endswith(f"(3 messages); stage {entry} -> {target}")
    assert planned(store, thread3()).stage_change == ""


def _ready_item(store, ready):
    item_ = outreach.Item(
        id="li-1", state="ready", kind="first-touch", channel="linkedin", company=COMPANY,
        contact=CONTACT, body="Hi Alex", language="en", ready=ready,
        created=ready, drafted=ready)
    outreach.write_item(store.root, item_)
    return item_.id


def test_an_outbound_message_after_ready_marks_the_outreach_item_sent(store):
    world(store, stage="engaged")
    item_id = _ready_item(store, datetime(2026, 10, 28, 18, 27))
    p = planned(store, thread3())
    assert p.outreach_sent == [item_id]
    conversation.apply(store, p, [0, 1, 2])
    assert outreach.get_item(store.root, item_id).state == "sent"


def test_an_outbound_message_before_ready_does_not(store):
    world(store, stage="engaged")
    item_id = _ready_item(store, datetime(2026, 10, 30, 12, 0))
    p = planned(store, thread3())
    assert p.outreach_sent == []
    conversation.apply(store, p, [0, 1, 2])
    assert outreach.get_item(store.root, item_id).state == "ready"


def test_a_block_with_an_unknown_heading_is_refused_until_the_person_gives_a_date(store):
    world(store, stage="engaged")
    t = conversation.parse(payload(
        theirs("Hi Sam", "Sol 3", "6:24 PM", "u1"),
        mine("Hello", "Sol 3", "6:30 PM", "u2")), NOW)
    assert t.needs_date == ["Sol 3"]
    p = planned(store, t)
    assert [r.status for r in p.rows] == ["undated", "undated"]
    assert p.default_selection == []
    with pytest.raises(ConversationError, match="date"):
        conversation.apply(store, p, [0, 1])
    assert interactions(store) == []
    answered = planned(store, t, dates={"Sol 3": date(2026, 10, 20)})
    assert [r.status for r in answered.rows] == ["new", "new"]
    conversation.apply(store, answered, [0, 1])
    assert [i.date for i in interactions(store)] == [
        datetime(2026, 10, 20, 18, 24), datetime(2026, 10, 20, 18, 30)]


def test_an_answer_with_a_time_names_the_moment_of_a_message_whose_time_was_unreadable(store):
    world(store, stage="engaged")
    t = conversation.parse(payload(theirs("Hi", "Wednesday", "late", "u1")), NOW)
    assert t.needs_date == ["Wednesday late"]
    assert planned(store, t, dates={"Wednesday late": date(2026, 10, 28)}).rows[0].status \
        == "undated"  # a day is not a moment: there is no time to borrow
    p = planned(store, t, dates={"Wednesday late": datetime(2026, 10, 28, 18, 24)})
    assert p.rows[0].status == "new" and p.rows[0].message.when == datetime(2026, 10, 28, 18, 24)


def test_a_date_that_is_probably_wrong_is_flagged_but_not_blocked(store):
    world(store, stage="engaged")
    ahead = conversation.parse(payload(theirs("Hi", "Today", "6:24 PM", "u1"),
                                       now_local="2026-11-03T08:00"), NOW)  # NOW is 1 Nov
    ancient = conversation.parse(payload(theirs("Hi", "1 Jan 1999", "6:24 PM", "u3")), NOW)
    clash = conversation.parse(payload(mine(
        "Hello", "Today", "6:24 PM", "u2", sent_title="Sent at 10/31/2026, 6:24 PM")), NOW)
    fine = thread3()
    assert [r.suspect for r in planned(store, ahead).rows] == [True]
    assert [r.suspect for r in planned(store, clash).rows] == [True]
    assert [r.suspect for r in planned(store, ancient).rows] == [True]  # before LinkedIn
    assert [r.suspect for r in planned(store, fine).rows] == [False] * 3
    assert planned(store, ahead).rows[0].status == "new"


def test_a_sender_who_does_not_fit_is_asked_about_until_a_direction_is_picked(store):
    world(store, stage="engaged")
    t = conversation.parse(payload(
        item("Hello", is_other=False, who="Robin Derde", day="Wednesday", time="6:24 PM",
             urn="u1")), NOW)
    p = planned(store, t)
    assert p.rows[0].status == "ask" and p.rows[0].message.direction == "ask"
    with pytest.raises(ConversationError, match="direction"):
        conversation.apply(store, p, [0])
    picked = planned(store, t, directions={0: "in"})
    assert picked.rows[0].status == "new" and picked.rows[0].message.direction == "in"
    conversation.apply(store, picked, [0])
    assert interactions(store)[0].direction == "in"


def test_a_flipped_direction_is_what_is_stored(store):
    world(store, stage="engaged")
    p = planned(store, thread3(), directions={0: "out", 7: "in", 1: "sideways"})
    assert [r.message.direction for r in p.rows] == ["out", "out", "in"]
    conversation.apply(store, p, [0])
    assert interactions(store)[0].direction == "out"


def test_the_owner_name_cross_check_runs_in_the_plan(store):
    world(store, stage="engaged")
    p = planned(store, thread3(), owner_name="Someone Else")
    assert [r.status for r in p.rows] == ["new", "ask", "new"]


def test_an_unknown_contact_is_refused(store):
    world(store)
    with pytest.raises(ConversationError, match="contact"):
        conversation.plan(store, COMPANY, "nobody", thread3(), NOW)
    with pytest.raises(ConversationError, match="company"):
        conversation.plan(store, "nowhere", CONTACT, thread3(), NOW)


def test_submitting_the_same_plan_twice_writes_once(store, messages):
    world(store, stage="engaged")
    p = planned(store, thread3())
    conversation.apply(store, p, [0, 1, 2])
    before = len(messages)
    again = conversation.apply(store, p, [0, 1, 2])
    assert again.ids == [] and again.skipped == 3 and len(messages) == before
    assert len(interactions(store)) == 3


def test_a_row_number_that_is_not_in_the_plan_is_refused(store):
    world(store, stage="engaged")
    with pytest.raises(ConversationError, match="row"):
        conversation.apply(store, planned(store, thread3()), [0, 9])
    assert interactions(store) == []


def test_only_the_ticked_rows_are_written(store):
    world(store, stage="engaged")
    result = conversation.apply(store, planned(store, thread3()), [2, 0])
    assert len(result.ids) == 2
    assert [i.message_id for i in interactions(store)] == ["linkedin:u1", "linkedin:u3"]


def test_migration_21_reserves_the_source_and_changes_nothing():
    migration = next(m for m in migrations.MIGRATIONS if m.version == 21)
    meta = {"date": "2026-09-14T10:30", "channel": "linkedin", "source": "linkedin-import"}
    assert migration.apply(dict(meta)) == meta
    assert migration.apply(migration.apply(dict(meta))) == meta
    assert migration.glob == "companies/*/interactions/*.md"
    assert InteractionSource.LINKEDIN_IMPORT.value == "linkedin-import"
    assert migrations.LATEST == 21
