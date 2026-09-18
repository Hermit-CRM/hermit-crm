"""Deterministic outreach drafts: three angles, right language, no AI, TOML-driven."""

from hermitcrm import messaging
from hermitcrm.messaging import deep_merge, drafts, load_messages, next_hurdle
from hermitcrm.models import Company, Contact, language_for


def company(**kw):
    """A company whose team-size fields are user-defined fields, as they now are.

    `fte_estimate` and `ae_count` were attributes until custom fields arrived.
    The playbook still reads them by name, out of `extra`.
    """
    extra = {"fte_estimate": "~12", "ae_count": 2}
    for key in ("fte_estimate", "ae_count"):
        if key in kw:
            value = kw.pop(key)
            if value in (None, ""):
                extra.pop(key, None)
            else:
                extra[key] = value
    base = dict(name="Acme", slug="acme", country="DE",
                website="https://acme.example.com")
    base.update(kw)
    return Company(extra=extra, **base)


def test_language_follows_country():
    codes = ("DE", "AT", "CH", "LI", "NL", "FR", "LU", "MC", "BE", "SE", "", "USA", "gb")
    assert [language_for(c) for c in codes] == \
        ["de", "de", "de", "de", "nl", "fr", "fr", "fr", "en", "en", "en", "en", "en"]


def test_next_hurdle():
    assert next_hurdle("~12") == 20 and next_hurdle("21") == 50
    assert next_hurdle("11-50") == 20 and next_hurdle("") is None


def test_default_languages_and_labels_come_from_toml():
    assert messaging.language_names() == {"en": "English", "de": "German", "nl": "Dutch",
                                          "fr": "French"}
    assert set(messaging.signal_labels()) == set(messaging.SIGNALS)
    for lang in load_messages()["languages"].values():
        assert set(lang["size"]) == {"known", "unknown"} == set(lang["team"])
        assert set(lang["growth"]) == {"growing", "stalled", "declining", ""}


def test_three_distinct_drafts_in_german_with_signal():
    jo = Contact(first_name="Johannes", last_name="W", slug="jw")
    out = drafts(company(), jo, signal="stalled", observation="", owner_name="Sam Owner")
    assert [d.key for d in out] == ["scale", "unblock", "hook"]
    assert all(d.language == "de" and d.body.startswith("Hallo Johannes,") for d in out)
    assert len({d.body for d in out}) == 3
    assert "Wachstum scheint etwas zu stocken" in out[0].body
    assert "20-Mitarbeiter-Marke" in out[1].body and "~12 Leute" in out[1].body
    assert "[Was dir auf acme.example.com aufgefallen ist" in out[2].body
    assert "schon 2 Leute im Vertrieb" in out[2].body
    assert all(d.body.endswith("\n\nSam\n") for d in out)


def test_hiring_signal_swaps_scale_for_bridge_and_observation_is_used():
    out = drafts(company(country="SE", ae_count=None), Contact("Johan", "B", "jb"),
                 signal="hiring", observation="Loved the declarative approach.")
    assert [d.key for d in out] == ["bridge", "unblock", "hook"]
    assert "Acme is hiring for [the role]" in out[0].body
    assert out[2].body.splitlines()[1] == "Loved the declarative approach."
    assert "[One thing you noticed about the team.]" in out[2].body
    assert out[0].body.endswith("[your name]\n")


def test_messages_without_decline_fall_back_to_scale():
    messages = messaging.default_messages()
    for t in messages["languages"].values():
        del t["decline"]
    out = drafts(company(country="NL"), None, signal="declining", messages=messages)
    assert [d.key for d in out] == ["scale", "unblock", "hook"]


def test_unknown_signal_and_missing_data_leave_brackets():
    out = drafts(company(country="NL", fte_estimate="", ae_count=None), None, signal="nope")
    assert out[0].body.startswith("Hoi [first name],")
    assert "[groeit hard / is ver gekomen]" in out[0].body
    assert "[N]" in out[1].body
    fr = drafts(company(country="FR"), Contact("Marie", "D", "md"))
    assert fr[0].body.startswith("Bonjour Marie,") and fr[0].language == "fr"


def test_deep_merge_keeps_untouched_keys():
    base = {"a": {"b": 1, "c": {"d": 2, "e": 3}}, "f": 4}
    assert deep_merge(base, {"a": {"c": {"d": 9}}, "g": 5}) == \
        {"a": {"b": 1, "c": {"d": 9, "e": 3}}, "f": 4, "g": 5}
    assert base["a"]["c"]["d"] == 2  # not mutated


def test_messages_toml_in_data_folder_is_merged_over_defaults(tmp_path):
    (tmp_path / "messages.toml").write_text(
        '[labels]\nhook = "3. my hook"\n\n'
        '[languages.en]\nsignoff = "Cheers,\\n{owner_first_name}"\n\n'
        '[languages.en.team]\nunknown = "Small team, big plans."\n\n'
        '[languages.xx]\nname = "Pirate"\n', encoding="utf-8")
    messages = load_messages(tmp_path)
    assert messages["languages"]["en"]["greeting"] == "Hi {first},"  # default kept
    assert messaging.language_names(messages)["xx"] == "Pirate"
    out = drafts(company(country="SE", ae_count=None), Contact("Ann", "B", "ab"),
                 messages=messages, owner_name="Robin Roe")
    assert out[2].label == "3. my hook" and out[0].label.startswith("1. scale")
    assert "Small team, big plans." in out[2].body
    assert out[0].body.endswith("Cheers,\nRobin\n")
    assert load_messages(tmp_path / "missing")["languages"]["en"]["signoff"] == \
        "{owner_first_name}"


# ---------------------------------------------------------------- Belgium


def _it(body, direction="in", day=1):
    from datetime import datetime
    from hermitcrm.models import Interaction
    return Interaction(id=f"i{day}", date=datetime(2026, 9, day, 10), channel="email",
                       direction=direction, body=body)


def test_text_language_and_postcodes():
    assert messaging.text_language("Bedankt voor uw bericht, wij hebben graag een gesprek") == "nl"
    assert messaging.text_language("Merci pour votre message, nous sommes intéressés par une démo") == "fr"
    assert messaging.text_language("Thanks for the note, happy to talk next week") == ""
    assert messaging.belgian_postcode_language("Kerkstraat 1, 9000 Gent") == "nl"
    assert messaging.belgian_postcode_language("Rue de Namur 5, B-5000 Namur") == "fr"
    assert messaging.belgian_postcode_language("Avenue Louise 54, 1050 Bruxelles") == ""
    assert messaging.belgian_postcode_language("founded 2019, 25 staff") == ""


def test_belgian_language_signals():
    be = lambda **kw: company(country="BE", website="https://acme.be", **kw)  # noqa: E731
    assert messaging.belgian_language(be()) == "en"
    assert messaging.belgian_language(company(country="BE", website="https://acme.be/nl/")) == "nl"
    assert messaging.belgian_language(company(country="BE", website="https://fr.acme.be")) == "fr"
    assert messaging.belgian_language(be(notes="HQ: 4000 Liège")) == "fr"
    # their own reply outweighs a Dutch website path
    c = company(country="BE", website="https://acme.be/nl/")
    c.interactions.append(_it("Bonjour, merci pour votre message. Nous sommes intéressés, pouvons-nous parler la semaine prochaine?"))
    assert messaging.belgian_language(c) == "fr"
    # equal evidence on both sides stays English
    c = company(country="BE", website="https://acme.be/nl/", notes="bureau: 7000 Mons")
    assert messaging.belgian_language(c) == "en"
    # a contact title is weak but enough on its own
    c = be()
    c.contacts["jan"] = Contact(first_name="Jan", last_name="Peeters", slug="jan",
                                title="Zaakvoerder en oprichter van het bedrijf")
    assert messaging.belgian_language(c) == "nl"
    evidence = messaging.belgian_language_scores(c)
    assert evidence["nl"] and not evidence["fr"]


def test_belgian_drafts_use_the_inferred_language():
    c = company(country="BE", website="https://acme.be/fr/")
    fr = drafts(c, messages=load_messages())
    en = drafts(company(country="BE"), messages=load_messages())
    assert fr[0].body != en[0].body


def test_declining_signal_has_its_own_growth_sentence():
    out = drafts(company(country="NL"), None, signal="declining")
    assert "het team is de laatste tijd kleiner geworden" in out[0].body
    assert [d.key for d in out] == ["decline", "unblock", "hook"]
    assert "[jouw aanbod]" in out[0].body
    assert messaging.signal_labels()["declining"] == "headcount decline"


def test_messages_without_a_declining_sentence_fall_back_to_unchecked():
    messages = messaging.default_messages()
    for t in messages["languages"].values():
        del t["growth"]["declining"]
    out = drafts(company(country="NL"), None, signal="declining", messages=messages)
    assert out[0].body.splitlines()[1] == messages["languages"]["nl"]["growth"][""].format(
        company=company().name)
