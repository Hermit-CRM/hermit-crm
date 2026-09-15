from datetime import date, datetime

import pytest
import yaml

from owncrm.models import (
    CLOSED_STAGES,
    OPEN_STAGES,
    Channel,
    Company,
    Contact,
    Country,
    Direction,
    Interaction,
    InteractionSource,
    Role,
    Source,
    Stage,
    ValidationError,
    company_from_dict,
    company_to_frontmatter,
    contact_from_dict,
    contact_to_frontmatter,
    dump_frontmatter,
    fmt_date,
    fmt_datetime,
    interaction_from_dict,
    interaction_to_frontmatter,
    normalise_email,
    normalise_website,
    parse_date,
    parse_datetime,
    parse_tags,
    slugify,
    unique_slug,
)

# ------------------------------------------------------------------ enums


def test_enum_values_are_hyphenated_strings():
    assert [e.value for e in Source] == [
        "linkedin-search", "referral", "inbound", "event", "list", "network", "other",
    ]
    assert [e.value for e in Stage] == [
        "prospect", "reached-out", "discovery", "offer", "won", "lost",
        "disqualified", "temp-disqualified",
    ]
    assert len(Country) == 249 and "GB" in [e.value for e in Country] and "UK" not in [e.value for e in Country]
    assert [e.value for e in Role] == [
        "champion", "decision-maker", "influencer", "gatekeeper",
    ]
    assert [e.value for e in Channel] == ["email", "linkedin", "call", "meeting"]
    assert [e.value for e in Direction] == ["out", "in"]
    assert [e.value for e in InteractionSource] == ["manual", "bcc-import", "calendar-import"]
    assert OPEN_STAGES == ["offer", "discovery", "reached-out", "prospect"]
    assert CLOSED_STAGES == ["won", "lost", "disqualified"]


# ------------------------------------------------------------------ slugify


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Müller & Söhne", "mueller-soehne"),
        ("Straße 12", "strasse-12"),
        ("Société Générale", "societe-generale"),
        ("Ærø Håndværk", "aeroe-haandvaerk"),
        ("Jörg Öztürk", "joerg-oeztuerk"),
        ("Añejo Ñandú", "anejo-nandu"),
        ("  spaced   out  ", "spaced-out"),
        ("---weird---", "weird"),
        ("Ελλάδα", "company"),
        ("", "company"),
    ],
)
def test_slugify_transliteration(text, expected):
    assert slugify(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Müller & Söhne GmbH", "mueller-soehne"),
        ("Acme Inc.", "acme"),
        ("Widgets Co. KG", "widgets"),
        ("Stichting Foo B.V.", "stichting-foo"),
        ("Beta Holding AG", "beta-holding"),
        ("Gamma SE", "gamma"),
        ("Delta Ltd", "delta"),
        ("Epsilon SARL", "epsilon"),
        ("Zeta SAS", "zeta"),
        ("Eta UG", "eta"),
        ("Theta BV", "theta"),
        ("GmbH", "company"),
    ],
)
def test_slugify_strips_legal_suffixes(text, expected):
    assert slugify(text, strip_legal=True) == expected


def test_slugify_does_not_strip_legal_by_default():
    assert slugify("Acme Inc.") == "acme-inc"


def test_slugify_length_cap():
    s = slugify("Ratatatatat " * 20)
    assert len(s) <= 60
    assert not s.endswith("-")


def test_slugify_default_kwarg():
    assert slugify("???", default="contact") == "contact"


def test_unique_slug_suffixes():
    assert unique_slug("acme", []) == "acme"
    assert unique_slug("acme", ["acme"]) == "acme-2"
    assert unique_slug("acme", ["acme", "acme-2"]) == "acme-3"
    assert unique_slug("acme", ["acme", "acme-2", "acme-3"]) == "acme-4"


# ------------------------------------------------------------------ helpers


def test_fmt_and_parse_dates():
    assert fmt_date(date(2026, 9, 14)) == "2026-09-14"
    assert fmt_date(None) == ""
    assert fmt_datetime(datetime(2026, 9, 14, 10, 30)) == "2026-09-14T10:30"
    assert fmt_datetime(None) == ""
    assert parse_date("") is None
    assert parse_date("2026-09-14") == date(2026, 9, 14)
    assert parse_date(date(2026, 9, 14)) == date(2026, 9, 14)
    with pytest.raises(ValidationError):
        parse_date("14/09/2026")


def test_parse_datetime_variants():
    want = datetime(2026, 9, 14, 10, 30)
    assert parse_datetime("2026-09-14T10:30") == want
    assert parse_datetime("2026-09-14 10:30") == want
    assert parse_datetime("2026-09-14T10:30:59") == want.replace(second=0)
    assert parse_datetime(datetime(2026, 9, 14, 10, 30, 45, 123)) == want
    assert parse_datetime(date(2026, 9, 14)) == datetime(2026, 9, 14, 0, 0)
    assert parse_datetime("") is None
    with pytest.raises(ValidationError):
        parse_datetime("yesterday")


def test_normalisers():
    assert normalise_website("") == ""
    assert normalise_website(" acme.com ") == "https://acme.com"
    assert normalise_website("http://acme.com") == "http://acme.com"
    assert normalise_email("  Anna@Mueller.DE ") == "anna@mueller.de"
    assert parse_tags("a, b ,,c") == ["a", "b", "c"]
    assert parse_tags("") == []
    assert parse_tags(["x", " y "]) == ["x", "y"]


# ------------------------------------------------- dump_frontmatter / round trip


def reparse(text: str):
    return yaml.safe_load(text)


def test_dump_frontmatter_basic_types_and_empties():
    out = dump_frontmatter({
        "name": "Acme",
        "website": "",
        "value_eur_month": 3000,
        "missing": None,
        "stage_changed": date(2026, 9, 14),
        "created": datetime(2026, 9, 14, 10, 30),
        "tags": [],
    })
    assert out == (
        "name: Acme\n"
        "website:\n"
        "value_eur_month: 3000\n"
        "missing:\n"
        "stage_changed: 2026-09-14\n"
        "created: 2026-09-14T10:30\n"
        "tags: []\n"
    )
    assert "website: \n" not in out  # no trailing space on empty keys
    back = reparse(out)
    assert back["website"] is None and back["missing"] is None
    assert back["value_eur_month"] == 3000
    assert back["stage_changed"] == date(2026, 9, 14)


def test_dump_frontmatter_is_deterministic_and_ordered():
    meta = {"b": "2", "a": "1", "c": [1, 2]}
    assert dump_frontmatter(meta) == dump_frontmatter(meta)
    assert list(reparse(dump_frontmatter(meta))) == ["b", "a", "c"]


def test_dump_frontmatter_tags_flow_style():
    out = dump_frontmatter({"tags": ["dora", "bank de"]})
    assert out == "tags: [dora, bank de]\n"
    assert reparse(out)["tags"] == ["dora", "bank de"]


@pytest.mark.parametrize(
    "value",
    [
        "plain",
        "colon: inside",
        "hash # inside",
        "#leading hash",
        "it's quoted",
        'double "quotes"',
        "  leading spaces",
        "trailing spaces  ",
        "Müller & Söhne GmbH",
        "yes",
        "no",
        "true",
        "null",
        "2026",
        "2026-09-14",
        "3000",
        "- dash start",
        "[bracket]",
        "{brace}",
        "*star",
        "&anchor",
        "line one\nline two",
        "tab\there",
        "100%",
        "@at",
    ],
)
def test_dump_frontmatter_tricky_strings_round_trip(value):
    out = dump_frontmatter({"subject": value})
    assert out.count("\n") == 1
    assert reparse(out)["subject"] == value


def test_dump_frontmatter_tricky_strings_in_tags():
    tags = ["yes", "a: b", "#x", "2026"]
    out = dump_frontmatter({"tags": tags})
    assert reparse(out)["tags"] == tags


def test_pyyaml_treats_second_less_datetime_as_string():
    # The emitter relies on this: 2026-09-14T10:30 is NOT a YAML timestamp.
    assert reparse("created: 2026-09-14T10:30")["created"] == "2026-09-14T10:30"
    # ...but with seconds it is, and parse_datetime must cope with both.
    assert reparse("created: 2026-09-14T10:30:00")["created"] == datetime(
        2026, 9, 14, 10, 30
    )
    assert parse_datetime(reparse("created: 2026-09-14T10:30")["created"]) == (
        parse_datetime(reparse("created: 2026-09-14T10:30:00")["created"])
    )


# ------------------------------------------------------------ frontmatter order


def test_company_frontmatter_key_order():
    c = Company(name="Acme", slug="acme")
    assert list(company_to_frontmatter(c)) == [
        "name", "slug", "website", "linkedin", "country", "source", "stage", "stage_changed",
        "lost_reason", "requalify_on", "value_eur_month", "my_score", "fit_score",
        "fte_estimate", "ae_count", "product_oneliner", "next_step", "next_step_due",
        "next_step_status", "tags", "created", "updated",
    ]


def test_contact_frontmatter_key_order():
    assert list(contact_to_frontmatter(Contact(first_name="A", last_name="B", slug="a"))) == [
        "first_name", "last_name", "slug", "title", "linkedin", "email", "phone", "role",
        "created", "updated",
    ]


def test_interaction_frontmatter_key_order():
    it = Interaction(id="x", date=datetime(2026, 9, 14, 10, 30), channel="call",
                     direction="out", subject="s")
    assert list(interaction_to_frontmatter(it)) == [
        "date", "channel", "direction", "contact", "subject", "outcome", "source",
    ]


# ------------------------------------------------------------------ from_dict


def test_company_from_dict_accepts_strings_and_objects():
    a = company_from_dict(
        {"name": "Acme", "stage": "offer", "stage_changed": "2026-09-01",
         "created": "2026-09-01T09:00", "updated": "2026-09-02T09:00",
         "value_eur_month": "3000", "tags": ["a", "b"]},
        "body\n", "acme",
    )
    b = company_from_dict(
        {"name": "Acme", "stage": "offer", "stage_changed": date(2026, 9, 1),
         "created": datetime(2026, 9, 1, 9, 0), "updated": datetime(2026, 9, 2, 9, 0),
         "value_eur_month": 3000, "tags": ["a", "b"]},
        "body\n", "acme",
    )
    assert a == b
    assert a.stage_changed == date(2026, 9, 1)
    assert a.created == datetime(2026, 9, 1, 9, 0)
    assert a.value_eur_month == 3000
    assert a.notes == "body\n"


def test_company_from_dict_defaults():
    c = company_from_dict({"name": "Acme"}, "", "acme")
    assert (c.source, c.stage, c.tags, c.value_eur_month) == (
        "other", "prospect", [], None)


def test_company_from_dict_missing_name():
    with pytest.raises(ValidationError) as e:
        company_from_dict({"stage": "prospect"}, "", "acme")
    assert "name" in e.value.errors


def test_company_from_dict_bad_enum():
    with pytest.raises(ValidationError) as e:
        company_from_dict({"name": "Acme", "stage": "negotiating"}, "", "acme")
    assert "stage" in e.value.errors
    assert "negotiating" in e.value.errors["stage"]


def test_company_from_dict_lost_needs_reason():
    with pytest.raises(ValidationError) as e:
        company_from_dict({"name": "Acme", "stage": "lost"}, "", "acme")
    assert "lost_reason" in e.value.errors
    ok = company_from_dict(
        {"name": "Acme", "stage": "lost", "lost_reason": "no budget"}, "", "acme")
    assert ok.lost_reason == "no budget"


def test_company_from_dict_bad_date_and_int():
    with pytest.raises(ValidationError) as e:
        company_from_dict(
            {"name": "Acme", "next_step_due": "soon", "value_eur_month": "lots"},
            "", "acme")
    assert set(e.value.errors) == {"next_step_due", "value_eur_month"}


def test_contact_from_dict_lowercases_email_and_validates_role():
    c = contact_from_dict({"name": "Anna", "email": "Anna@Mueller.DE",
                           "role": "champion"}, "", "anna")
    assert c.email == "anna@mueller.de"
    with pytest.raises(ValidationError):
        contact_from_dict({"name": "Anna", "role": "boss"}, "", "anna")


def test_interaction_from_dict_requirements():
    it = interaction_from_dict(
        {"date": "2026-09-14T10:30", "channel": "call", "direction": "out",
         "subject": "Intro call"}, "notes\n", "the-id")
    assert it.id == "the-id" and it.source == "manual" and it.contact == ""
    with pytest.raises(ValidationError) as e:
        interaction_from_dict({"channel": "call", "direction": "out"}, "", "x")
    assert "date" in e.value.errors
    assert "subject" not in e.value.errors  # subject is optional
    with pytest.raises(ValidationError) as e:
        interaction_from_dict(
            {"date": "2026-09-14T10:30", "channel": "fax", "direction": "sideways",
             "subject": "s"}, "", "x")
    assert set(e.value.errors) == {"channel", "direction"}


# ------------------------------------------------------------------ derived


def build_company(**kw):
    base = dict(name="Acme", slug="acme", created=datetime(2026, 9, 1, 9, 0),
                updated=datetime(2026, 9, 1, 9, 0), stage_changed=date(2026, 9, 1))
    base.update(kw)
    return Company(**base)


def test_interaction_base_id_and_label():
    it = Interaction(id="", date=datetime(2026, 9, 8, 9, 12), channel="linkedin",
                     direction="out", contact="anna-mueller", subject="hi")
    assert it.base_id() == "2026-09-08T0912-linkedin-out-anna-mueller"
    assert it.contact_label == "anna-mueller"
    it.contact = ""
    assert it.base_id() == "2026-09-08T0912-linkedin-out-company"
    assert it.contact_label == "company"


def test_derived_metrics():
    c = build_company(interactions=[
        Interaction(id="a", date=datetime(2026, 9, 14, 10, 30), channel="email",
                    direction="out", contact="jane-doe", subject="s"),
        Interaction(id="b", date=datetime(2026, 9, 1, 10, 0), channel="call",
                    direction="in", contact="", subject="s"),
    ])
    today = date(2026, 9, 20)
    assert c.last_touch == datetime(2026, 9, 14, 10, 30)
    assert c.last_touch_summary == "email out 2026-09-14 (jane-doe)"
    assert c.interaction_count == 2
    assert c.days_in_stage(today) == 19
    assert c.silent_days(today) == 6
    assert c.is_closed is False
    assert c.latest_contact_slug == "jane-doe"


def test_derived_metrics_without_interactions():
    c = build_company()
    assert c.last_touch is None
    assert c.last_touch_summary == "none"
    assert c.interaction_count == 0
    assert c.silent_days(date(2026, 9, 20)) == 19  # falls back to created
    assert c.latest_contact_slug == ""
    assert c.next_step_overdue(date(2026, 9, 20)) is False


def test_last_touch_summary_company_level():
    c = build_company(interactions=[
        Interaction(id="a", date=datetime(2026, 9, 14, 10, 30), channel="call",
                    direction="in", contact="", subject="s"),
    ])
    assert c.last_touch_summary == "call in 2026-09-14 (company)"
    assert c.latest_contact_slug == ""


def test_next_step_overdue_ignores_stage():
    today = date(2026, 9, 14)
    assert build_company(next_step_due=date(2026, 9, 13)).next_step_overdue(today)
    assert not build_company(next_step_due=date(2026, 9, 14)).next_step_overdue(today)
    assert not build_company(next_step_due=date(2026, 9, 15)).next_step_overdue(today)
    closed = build_company(stage="won", next_step_due=date(2026, 9, 13))
    assert closed.next_step_overdue(today) is True
    assert closed.is_closed is True


# --------------------------------------------------------- messages, parking


def test_message_status_explicit_reply_window_unknown():
    from datetime import date, datetime
    from owncrm.models import Company, Interaction
    sent = datetime(2026, 9, 1, 9, 0)
    c = Company(name="A", slug="a")
    msg = Interaction(id="m", date=sent, channel="linkedin", direction="out",
                      contact="jane", body="Hi Jane")
    c.interactions = [msg]
    assert not Interaction(id="x", date=sent, direction="in", body="x").is_message
    assert not Interaction(id="x", date=sent, direction="out", body="").is_message
    assert msg.is_message
    assert not Interaction(id="x", date=sent, channel="meeting", direction="out",
                           body="agenda").is_message
    assert c.message_status(msg, date(2026, 9, 10)) == "unknown"
    assert c.message_status(msg, date(2026, 9, 15)) == "unsuccessful"
    assert c.message_status(msg, date(2026, 9, 10), window_days=5) == "unsuccessful"
    c.interactions.append(Interaction(id="r", date=datetime(2026, 9, 3), channel="email",
                                      direction="in", contact="bob"))
    assert c.message_status(msg, date(2026, 9, 30)) == "unsuccessful"  # other contact
    c.interactions.append(Interaction(id="r2", date=datetime(2026, 9, 4), channel="email",
                                      direction="in", contact="jane"))
    assert c.message_status(msg, date(2026, 9, 30)) == "success"  # legacy name, no list
    outcomes = ["successful", "no answer"]
    assert c.message_status(msg, date(2026, 9, 30), outcomes=outcomes) == "successful"
    c.interactions.pop()
    assert c.message_status(msg, date(2026, 9, 30), outcomes=outcomes) == "no answer"
    msg.outcome = "unsuccessful"
    assert c.message_status(msg, date(2026, 9, 30), outcomes=outcomes) == "unsuccessful"


def test_requalify_due_and_outcome_roundtrip():
    from datetime import date
    from owncrm.models import (Company, company_from_dict, company_to_frontmatter,
                            interaction_from_dict, interaction_to_frontmatter)
    c = Company(name="A", slug="a", stage="temp-disqualified", requalify_on=date(2026, 9, 14))
    assert c.requalify_due(date(2026, 9, 14)) and not c.requalify_due(date(2026, 9, 13))
    c.stage = "prospect"
    assert not c.requalify_due(date(2026, 9, 30))
    meta = company_to_frontmatter(c)
    assert meta["requalify_on"] == date(2026, 9, 14)
    back = company_from_dict({"name": "A", "requalify_on": "2026-09-14"}, "", "a")
    assert back.requalify_on == date(2026, 9, 14)
    # Any text loads (files are never rejected for their outcome); a leftover
    # `result` key from before migration 3 is an unknown key and round-trips.
    it = interaction_from_dict({"date": "2026-09-01T09:00", "channel": "email",
                                "direction": "out", "outcome": "successful",
                                "result": "success"}, "", "x")
    assert it.outcome == "successful" and it.extra == {"result": "success"}
    assert interaction_to_frontmatter(it)["outcome"] == "successful"
    assert "result" in interaction_to_frontmatter(it)


def test_iso_countries_and_aliases():
    from owncrm.models import ISO_3166_ALPHA2, normalise_country
    assert len(ISO_3166_ALPHA2) == 249 == len(set(ISO_3166_ALPHA2))
    assert normalise_country("uk") == "GB" and normalise_country(" USA ") == "US"
    assert normalise_country("pt") == "PT" and normalise_country(None) == ""
    c = company_from_dict({"name": "Acme", "country": "UK"}, "", "acme")
    assert c.country == "GB"
    with pytest.raises(ValidationError):
        company_from_dict({"name": "Acme", "country": "XX"}, "", "acme")
