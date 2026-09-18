from datetime import date, datetime

import pytest

from hermitcrm.models import StageChange, ValidationError
from hermitcrm.store import Store, build_file, load_config, normalise_body, split_file
from conftest import FIXED_NOW


def read(path):
    return path.read_text(encoding="utf-8")


def fresh(store):
    """A second Store over the same root, loaded from disk."""
    s = Store(store.root, clock=lambda: FIXED_NOW)
    s.load()
    return s


# ------------------------------------------------------------------ config


def test_load_config_defaults(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg == {"port": 8765, "host": "127.0.0.1", "silent_days": 14,
                   "followup_reply_days": 1, "followup_nudge_days": 5,
                   "push_enabled": True,
                   "remote": "origin", "enrich_provider": "auto", "enrich_account": "subscription", "enrich_command": "", "enrich_model": "", "enrich_timeout": 180,
                   "enrich_model_strong": "", "ai_tier": "medium", "ask_timeout": 300,
                   "theme": "light",
                   "message_window_days": 14, "fetch_timeout": 10,
                   "outcomes": ["successful", "unsuccessful"],
                   "owner_name": "", "owner_email": "",
                   "bcc_address": "", "bcc_imap_host": "imap.gmail.com",
                   "bcc_keychain_service": "crm-bcc", "bcc_lookback_days": 30,
                   "my_addresses": [],
                   "bcc_ignore_domains": [],
                   "calendar_keychain_service": "crm-calendar",
                   "calendar_keychain_account": "ics", "calendar_lookback_days": 30,
                   "calendar_ignore_titles": [], "calendar_min_attendees": 2,
                   "update_check": True, "update_url": "", "feedback_email": ""}


def test_load_config_reads_toml(tmp_path):
    (tmp_path / "config.toml").write_text(
        "port = 9000\nsilent_days = 7\npush_enabled = false\nremote = \"upstream\"\n"
    )
    assert load_config(tmp_path) == {"port": 9000, "host": "127.0.0.1", "silent_days": 7,
                                     "followup_reply_days": 1, "followup_nudge_days": 5,
                                     "push_enabled": False, "remote": "upstream",
                                     "enrich_provider": "auto", "enrich_account": "subscription", "enrich_command": "", "enrich_model": "", "enrich_timeout": 180,
                   "enrich_model_strong": "", "ai_tier": "medium", "ask_timeout": 300,
                   "theme": "light",
                   "message_window_days": 14, "fetch_timeout": 10,
                   "outcomes": ["successful", "unsuccessful"],
                   "owner_name": "", "owner_email": "",
                   "bcc_address": "", "bcc_imap_host": "imap.gmail.com",
                   "bcc_keychain_service": "crm-bcc", "bcc_lookback_days": 30,
                   "my_addresses": [],
                   "bcc_ignore_domains": [],
                   "calendar_keychain_service": "crm-calendar",
                   "calendar_keychain_account": "ics", "calendar_lookback_days": 30,
                   "calendar_ignore_titles": [], "calendar_min_attendees": 2,
                   "update_check": True, "update_url": "", "feedback_email": ""}


# ------------------------------------------------------------------ clock


def test_now_is_truncated_to_minutes(tmp_path):
    s = Store(tmp_path, clock=lambda: datetime(2026, 9, 14, 10, 30, 59, 999))
    assert s.now() == datetime(2026, 9, 14, 10, 30)
    assert s.today() == date(2026, 9, 14)


# ------------------------------------------------------------ split / build


def test_split_file_keeps_body_byte_for_byte():
    text = "---\nname: Acme\n---\nbody line\n\n\n"
    meta, body = split_file(text)
    assert meta == {"name": "Acme"}
    assert body == "body line\n\n\n"
    assert build_file(meta, body) == text


def test_split_file_empty_body():
    meta, body = split_file("---\nname: Acme\n---\n")
    assert meta == {"name": "Acme"} and body == ""


def test_split_file_body_containing_a_dash_rule():
    meta, body = split_file("---\nname: Acme\n---\ntext\n---\nmore\n")
    assert meta == {"name": "Acme"}
    assert body == "text\n---\nmore\n"


def test_normalise_body():
    assert normalise_body("a\r\nb\r\n") == "a\nb\n"
    assert normalise_body("a\n\n\n") == "a\n"
    assert normalise_body("") == ""
    assert normalise_body(None) == ""
    assert normalise_body("no newline") == "no newline\n"


# ------------------------------------------------------------- create company


def test_create_company_slug_and_files(store, messages):
    c = store.create_company("Müller & Söhne GmbH", source="referral",
                             website="mueller.de")
    assert c.slug == "mueller-soehne"
    assert c.name == "Müller & Söhne GmbH"
    assert c.website == "https://mueller.de"
    assert c.stage == "prospect"
    assert c.stage_changed == store.today()
    assert c.created == c.updated == FIXED_NOW
    path = store.root / "companies" / "mueller-soehne" / "company.md"
    assert path.exists()
    assert messages == ["company: mueller-soehne created"]


def test_create_company_file_bytes(store):
    store.create_company("Acme", tags="dora, bank")
    text = read(store.root / "companies" / "acme" / "company.md")
    assert text == (
        "---\n"
        "name: Acme\n"
        "slug: acme\n"
        "website:\n"
        "linkedin:\n"
        "country:\n"
        "source: other\n"
        "stage: prospect\n"
        "stage_changed: 2026-09-14\n"
        "lost_reason:\n"
        "requalify_on:\n"
        "value_eur_month:\n"
        "my_score:\n"
        "fit_score:\n"
        "fte_estimate:\n"
        "ae_count:\n"
        "product_oneliner:\n"
        "next_step:\n"
        "next_step_due:\n"
        "next_step_status: open\n"
        "tags: [dora, bank]\n"
        "created: 2026-09-14T10:30\n"
        "updated: 2026-09-14T10:30\n"
        "---\n"
    )


def test_create_company_slug_uniqueness(store):
    assert store.create_company("Acme").slug == "acme"
    assert store.create_company("Acme").slug == "acme-2"
    assert store.create_company("Acme Inc.").slug == "acme-3"


def test_create_company_lost_requires_reason(store, messages):
    with pytest.raises(ValidationError) as e:
        store.create_company("Acme", stage="lost")
    assert "lost_reason" in e.value.errors
    assert not (store.root / "companies" / "acme").exists()
    assert messages == []


def test_create_company_coerces_form_strings(store):
    c = store.create_company("Acme", value_eur_month="3000",
                             next_step_due="2026-09-20", tags="a,b")
    assert c.value_eur_month == 3000
    assert c.next_step_due == date(2026, 9, 20)
    assert c.tags == ["a", "b"]
    c2 = store.create_company("Beta", value_eur_month="")
    assert c2.value_eur_month is None
    with pytest.raises(ValidationError) as e:
        store.create_company("Gamma", value_eur_month="lots")
    assert "value_eur_month" in e.value.errors


def test_create_company_bad_enum(store):
    with pytest.raises(ValidationError) as e:
        store.create_company("Acme", stage="negotiating")
    assert "stage" in e.value.errors


# ------------------------------------------------------------- update company


def test_update_company_stage_change(store, messages):
    store.create_company("Acme")
    messages.clear()
    c = store.update_company("acme", stage="discovery")
    assert c.stage == "discovery"
    assert c.stage_changed == store.today()
    assert messages == ["company: acme stage prospect -> discovery"]


def test_update_company_without_stage_change(store, messages):
    store.create_company("Acme")
    messages.clear()
    c = store.update_company("acme", next_step="Send proposal")
    assert c.next_step == "Send proposal"
    assert messages == ["company: acme updated"]


def test_update_company_lost_requires_reason_and_writes_nothing(store, messages):
    store.create_company("Acme")
    before = read(store.root / "companies" / "acme" / "company.md")
    messages.clear()
    with pytest.raises(ValidationError) as e:
        store.update_company("acme", stage="lost")
    assert "lost_reason" in e.value.errors
    assert read(store.root / "companies" / "acme" / "company.md") == before
    assert messages == []
    assert store.get("acme").stage == "prospect"

    c = store.update_company("acme", stage="lost", lost_reason="no budget")
    assert c.stage == "lost" and c.lost_reason == "no budget"
    assert messages == ["company: acme stage prospect -> lost"]


def test_leaving_lost_clears_reason(store):
    store.create_company("Acme")
    store.update_company("acme", stage="lost", lost_reason="no budget")
    c = store.update_company("acme", stage="discovery")
    assert c.lost_reason == ""
    assert fresh(store).get("acme").lost_reason == ""


def test_update_company_unknown_slug(store):
    with pytest.raises(ValidationError):
        store.update_company("nope", stage="won")


# ------------------------------------------------------------------ contacts


def test_create_contact(store, messages):
    store.create_company("Müller & Söhne GmbH")
    messages.clear()
    c = store.create_contact("mueller-soehne", "Anna", "Müller", title="CEO",
                             email="Anna@Mueller.DE", role="decision-maker")
    assert c.slug == "anna-mueller"
    assert c.email == "anna@mueller.de"
    path = store.root / "companies" / "mueller-soehne" / "contacts" / "anna-mueller.md"
    assert path.exists()
    assert messages == ["contact: mueller-soehne/anna-mueller created"]
    assert store.get("mueller-soehne").contacts["anna-mueller"] == c


def test_create_contact_slug_unique_within_company(store):
    store.create_company("Acme")
    store.create_company("Beta")
    assert store.create_contact("acme", "Anna", "Müller").slug == "anna-mueller"
    assert store.create_contact("acme", "Anna", "Mueller").slug == "anna-mueller-2"
    assert store.create_contact("beta", "Anna", "Müller").slug == "anna-mueller"


def test_update_contact(store, messages):
    store.create_company("Acme")
    store.create_contact("acme", "Anna", "Müller")
    messages.clear()
    c = store.update_contact("acme", "anna-mueller", title="CTO",
                             email="A@B.COM", notes="hi\r\n")
    assert (c.title, c.email, c.notes) == ("CTO", "a@b.com", "hi\n")
    assert c.slug == "anna-mueller"
    assert messages == ["contact: acme/anna-mueller updated"]


def test_contact_bad_role(store):
    store.create_company("Acme")
    with pytest.raises(ValidationError):
        store.create_contact("acme", "Anna", role="boss")


# -------------------------------------------------------------- interactions


def test_create_interaction_id_and_message(store, messages):
    store.create_company("Müller & Söhne GmbH")
    store.create_contact("mueller-soehne", "Anna", "Müller")
    messages.clear()
    it = store.create_interaction("mueller-soehne", subject="Intro",
                                  channel="linkedin", direction="out",
                                  contact="anna-mueller",
                                  date="2026-09-08T09:12")
    assert it.id == "2026-09-08T0912-linkedin-out-anna-mueller"
    assert it.source == "manual"
    assert (store.root / "companies" / "mueller-soehne" / "interactions"
            / f"{it.id}.md").exists()
    # One commit: the prospect became engaged with the first interaction.
    assert messages == [
        "interaction: mueller-soehne linkedin out anna-mueller 2026-09-08T09:12; "
        "stage prospect -> engaged"
    ]


def test_create_interaction_company_level_id(store):
    store.create_company("Acme")
    it = store.create_interaction("acme", subject="Call", channel="call",
                                  direction="in", date="2026-09-14 10:30")
    assert it.id == "2026-09-14T1030-call-in-company"
    assert it.contact_label == "company"


def test_create_interaction_defaults_to_now(store):
    store.create_company("Acme")
    it = store.create_interaction("acme", subject="s", channel="email",
                                  direction="out")
    assert it.date == FIXED_NOW
    assert it.id == "2026-09-14T1030-email-out-company"


def test_create_interaction_collision_suffix(store):
    store.create_company("Acme")
    kw = dict(channel="email", direction="out", date="2026-09-14T10:30")
    a = store.create_interaction("acme", subject="one", **kw)
    b = store.create_interaction("acme", subject="two", **kw)
    c = store.create_interaction("acme", subject="three", **kw)
    assert a.id == "2026-09-14T1030-email-out-company"
    assert b.id == "2026-09-14T1030-email-out-company-2"
    assert c.id == "2026-09-14T1030-email-out-company-3"
    assert len(list((store.root / "companies" / "acme" / "interactions")
                    .glob("*.md"))) == 3


def test_create_interaction_unknown_contact(store):
    store.create_company("Acme")
    with pytest.raises(ValidationError) as e:
        store.create_interaction("acme", subject="s", channel="email",
                                 direction="out", contact="ghost")
    assert "contact" in e.value.errors


def test_create_interaction_validates_enums_and_subject(store):
    store.create_company("Acme")
    # Subject is optional: an empty one is written as an empty key.
    it = store.create_interaction("acme", subject="", channel="email", direction="out")
    assert it.subject == ""
    assert "subject:\n" in read(store.company_dir("acme") / "interactions" / f"{it.id}.md")
    with pytest.raises(ValidationError) as e:
        store.create_interaction("acme", subject="s", channel="fax", direction="out")
    assert "channel" in e.value.errors
    with pytest.raises(ValidationError) as e:
        store.create_interaction("acme", subject="s", channel="email", direction="")
    assert "direction" in e.value.errors


def test_update_interaction_date_renames_and_deletes_old(store, messages):
    store.create_company("Acme")
    old = store.create_interaction("acme", subject="s", channel="email",
                                   direction="out", date="2026-09-14T10:30")
    folder = store.root / "companies" / "acme" / "interactions"
    messages.clear()
    new = store.update_interaction("acme", old.id, date="2026-09-15T11:45")
    assert new.id == "2026-09-15T1145-email-out-company"
    assert (folder / f"{new.id}.md").exists()
    assert not (folder / f"{old.id}.md").exists()
    assert [p.name for p in folder.glob("*.md")] == [f"{new.id}.md"]
    assert messages == [f"interaction: acme {new.id} updated"]
    assert [i.id for i in store.get("acme").interactions] == [new.id]


def test_update_interaction_keeps_id_when_base_unchanged(store):
    store.create_company("Acme")
    it = store.create_interaction("acme", subject="s", channel="email",
                                  direction="out", date="2026-09-14T10:30")
    same = store.update_interaction("acme", it.id, subject="new subject",
                                    outcome="successful")
    assert same.id == it.id
    assert same.subject == "new subject" and same.outcome == "successful"


def test_update_interaction_keeps_collision_suffix(store):
    store.create_company("Acme")
    kw = dict(channel="email", direction="out", date="2026-09-14T10:30")
    store.create_interaction("acme", subject="one", **kw)
    second = store.create_interaction("acme", subject="two", **kw)
    assert second.id.endswith("-2")
    same = store.update_interaction("acme", second.id, outcome="unsuccessful")
    assert same.id == second.id


def test_update_interaction_body_and_contact(store):
    store.create_company("Acme")
    store.create_contact("acme", "Anna", "Müller")
    it = store.create_interaction("acme", subject="s", channel="email",
                                  direction="out", date="2026-09-14T10:30")
    new = store.update_interaction("acme", it.id, contact="anna-mueller",
                                   body="line\r\nline2")
    assert new.id == "2026-09-14T1030-email-out-anna-mueller"
    assert new.body == "line\nline2\n"
    with pytest.raises(ValidationError):
        store.update_interaction("acme", new.id, contact="ghost")


# ------------------------------------------------------------------ round trip


def make_full_company(store):
    store.create_company(
        "Müller & Söhne GmbH", website="mueller.de",
        linkedin="https://linkedin.com/company/mueller", source="referral",
        value_eur_month="3000", next_step="Send proposal: outline",
        next_step_due="2026-09-20", tags="dora, bank de",
        notes="Notes with: colon and #hash\n",
    )
    store.create_contact("mueller-soehne", "Anna", "Müller", title="CEO",
                         email="Anna@Mueller.DE", role="decision-maker",
                         phone="+49 30 1234", linkedin="https://li/anna",
                         notes="likes detail\n")
    store.create_contact("mueller-soehne", "Jonas", "Berg")
    store.create_interaction("mueller-soehne", subject="Intro on LinkedIn",
                             channel="linkedin", direction="out",
                             contact="anna-mueller", date="2026-09-08T09:12",
                             body="Hallo Anna,\n\nkurz zu uns.\n")
    store.create_interaction("mueller-soehne", subject="Re: Intro", channel="email",
                             direction="in", contact="anna-mueller",
                             date="2026-09-11T16:40", outcome="successful",
                             body="Danke!\n")
    store.create_interaction("mueller-soehne", subject="Discovery call",
                             channel="call", direction="out",
                             date="2026-09-14T10:30", body="Notes.\n")


def test_full_round_trip(store):
    make_full_company(store)
    reloaded = fresh(store)
    assert reloaded.problems == []
    assert reloaded.get("mueller-soehne") == store.get("mueller-soehne")


def test_round_trip_preserves_every_field(store):
    make_full_company(store)
    c = fresh(store).get("mueller-soehne")
    assert c.name == "Müller & Söhne GmbH"
    assert c.slug == "mueller-soehne"
    assert c.website == "https://mueller.de"
    assert c.source == "referral"
    assert c.stage == "engaged"  # it has interactions
    assert c.stage_changed == date(2026, 9, 14)
    assert c.value_eur_month == 3000
    assert c.next_step == "Send proposal: outline"
    assert c.next_step_due == date(2026, 9, 20)
    assert c.tags == ["dora", "bank de"]
    assert c.created == FIXED_NOW and c.updated == FIXED_NOW
    assert c.notes == "Notes with: colon and #hash\n"
    anna = c.contacts["anna-mueller"]
    assert (anna.name, anna.title, anna.email, anna.role, anna.phone) == (
        "Anna Müller", "CEO", "anna@mueller.de", "decision-maker", "+49 30 1234")
    assert anna.notes == "likes detail\n"
    assert set(c.contacts) == {"anna-mueller", "jonas-berg"}


def test_interactions_sorted_newest_first(store):
    make_full_company(store)
    c = fresh(store).get("mueller-soehne")
    assert [i.date for i in c.interactions] == [
        datetime(2026, 9, 14, 10, 30),
        datetime(2026, 9, 11, 16, 40),
        datetime(2026, 9, 8, 9, 12),
    ]
    assert [i.contact_label for i in c.interactions] == [
        "company", "anna-mueller", "anna-mueller"]
    assert c.last_touch_summary == "call out 2026-09-14 (company)"
    assert c.latest_contact_slug == "anna-mueller"
    assert c.interaction_count == 3


def test_rewriting_unchanged_records_is_byte_identical(store):
    make_full_company(store)
    files = sorted((store.root / "companies").rglob("*.md"))
    before = {p: read(p) for p in files}
    s2 = fresh(store)
    c = s2.get("mueller-soehne")
    s2.write_company(c)
    for contact in c.contacts.values():
        s2.write_contact(c.slug, contact)
    for it in c.interactions:
        s2.write_interaction(c.slug, it)
    assert sorted((store.root / "companies").rglob("*.md")) == files
    for p in files:
        assert read(p) == before[p], p


def test_body_preserved_byte_for_byte_including_trailing_blanks(store):
    store.create_company("Acme")
    path = store.root / "companies" / "acme" / "interactions" / "hand-written.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "Line one\n\nLine  two   \n\n\n"
    path.write_text(
        "---\n"
        "date: 2026-09-10T08:00\n"
        "channel: email\n"
        "direction: in\n"
        "contact:\n"
        "subject: Hand written\n"
        "outcome:\n"
        "source: manual\n"
        "---\n" + body,
        encoding="utf-8",
    )
    s2 = fresh(store)
    it = s2.get("acme").interactions[0]
    assert it.id == "hand-written"
    assert it.body == body
    s2.write_interaction("acme", it)
    assert read(path).endswith("---\n" + body)
    assert read(path).split("---\n", 2)[2] == body


def test_empty_keys_written_without_trailing_space(store):
    store.create_company("Acme")
    text = read(store.root / "companies" / "acme" / "company.md")
    assert "website:\n" in text
    assert "website: \n" not in text
    assert all(not line.endswith(" ") for line in text.splitlines())


def test_datetimes_written_without_seconds(store):
    store.create_company("Acme")
    store.create_interaction("acme", subject="s", channel="call", direction="out",
                             date="2026-09-14T10:30:45")
    company_text = read(store.root / "companies" / "acme" / "company.md")
    assert "created: 2026-09-14T10:30\n" in company_text
    it_text = read(store.root / "companies" / "acme" / "interactions"
                   / "2026-09-14T1030-call-out-company.md")
    assert "date: 2026-09-14T10:30\n" in it_text


# ------------------------------------------------------------------ problems


def write_company_file(root, slug, lines, body=""):
    path = root / "companies" / slug / "company.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + lines + "---\n" + body, encoding="utf-8")
    return path


GOOD = ("name: Good\nslug: good\nstage: prospect\nstage_changed: 2026-09-01\n"
        "created: 2026-09-01T09:00\nupdated: 2026-09-01T09:00\n")


def test_bad_enum_is_a_problem_and_other_files_still_load(tmp_path):
    write_company_file(tmp_path, "good", GOOD)
    write_company_file(tmp_path, "bad", "name: Bad\nslug: bad\nstage: negotiating\n")
    s = Store(tmp_path)
    problems = s.load()
    assert set(s.companies) == {"good"}
    assert len(problems) == 1
    assert problems[0].path == "companies/bad/company.md"
    assert "stage" in problems[0].message
    assert s.problems is problems


def test_missing_required_key_is_a_problem(tmp_path):
    write_company_file(tmp_path, "bad", "slug: bad\nstage: prospect\n")
    s = Store(tmp_path)
    s.load()
    assert s.companies == {}
    assert "name" in s.problems[0].message


def test_missing_company_md_is_a_problem(tmp_path):
    (tmp_path / "companies" / "empty" / "contacts").mkdir(parents=True)
    s = Store(tmp_path)
    s.load()
    assert s.companies == {}
    assert s.problems[0].path == "companies/empty/company.md"


def test_slug_mismatch_is_a_problem_but_folder_wins(tmp_path):
    write_company_file(tmp_path, "acme", "name: Acme\nslug: not-acme\n")
    s = Store(tmp_path)
    s.load()
    assert set(s.companies) == {"acme"}
    assert s.companies["acme"].slug == "acme"
    assert "does not match folder" in s.problems[0].message


def test_unknown_interaction_contact_is_a_problem_but_still_loads(tmp_path):
    write_company_file(tmp_path, "acme", "name: Acme\n")
    path = tmp_path / "companies" / "acme" / "interactions" / "x.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\ndate: 2026-09-14T10:30\nchannel: email\ndirection: out\n"
        "contact: ghost\nsubject: s\noutcome:\nsource: manual\n---\n",
        encoding="utf-8")
    s = Store(tmp_path)
    s.load()
    assert [i.id for i in s.get("acme").interactions] == ["x"]
    assert len(s.problems) == 1
    assert s.problems[0].path == "companies/acme/interactions/x.md"
    assert "ghost" in s.problems[0].message


def test_bad_contact_file_is_a_problem_and_siblings_load(tmp_path):
    write_company_file(tmp_path, "acme", "name: Acme\n")
    cdir = tmp_path / "companies" / "acme" / "contacts"
    cdir.mkdir(parents=True)
    (cdir / "anna.md").write_text("---\nname: Anna\nslug: anna\n---\n",
                                  encoding="utf-8")
    (cdir / "broken.md").write_text("---\nname: Broken\nrole: boss\n---\n",
                                    encoding="utf-8")
    s = Store(tmp_path)
    s.load()
    assert set(s.get("acme").contacts) == {"anna"}
    assert s.problems[0].path == "companies/acme/contacts/broken.md"


def test_load_never_raises_on_invalid_yaml(tmp_path):
    write_company_file(tmp_path, "bad", "name: [unclosed\n")
    s = Store(tmp_path)
    s.load()
    assert s.companies == {}
    assert len(s.problems) == 1


def test_load_on_empty_root(tmp_path):
    s = Store(tmp_path)
    assert s.load() == []
    assert s.all() == []


# ------------------------------------------------------------------ reload


def test_reload_company_sees_hand_edit(store):
    store.create_company("Acme")
    path = store.root / "companies" / "acme" / "company.md"
    path.write_text(read(path).replace("stage: prospect", "stage: discovery"),
                    encoding="utf-8")
    assert store.get("acme").stage == "prospect"  # index is stale
    assert store.get("acme", refresh=True).stage == "discovery"
    assert store.companies["acme"].stage == "discovery"


def test_reload_company_sees_new_hand_written_contact(store):
    store.create_company("Acme")
    path = store.root / "companies" / "acme" / "contacts" / "hand.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nname: Hand Written\nslug: hand\n---\n", encoding="utf-8")
    assert store.get("acme").contacts == {}
    assert set(store.reload_company("acme").contacts) == {"hand"}


def test_reload_company_refreshes_problems(store):
    store.create_company("Acme")
    path = store.root / "companies" / "acme" / "company.md"
    good = read(path)
    path.write_text(good.replace("stage: prospect", "stage: negotiating"),
                    encoding="utf-8")
    assert store.reload_company("acme") is None
    assert len(store.problems) == 1
    assert "acme" not in store.companies
    path.write_text(good, encoding="utf-8")
    assert store.reload_company("acme").stage == "prospect"
    assert store.problems == []


def test_reload_company_missing_folder(store):
    store.create_company("Acme")
    import shutil
    shutil.rmtree(store.root / "companies" / "acme")
    assert store.reload_company("acme") is None
    assert store.get("acme") is None


# ------------------------------------------------------------------ queries


def test_all_sorted_by_name(store):
    store.create_company("zeta")
    store.create_company("Alpha")
    store.create_company("mid")
    assert [c.name for c in store.all()] == ["Alpha", "mid", "zeta"]


def test_search(store):
    store.create_company("Müller & Söhne GmbH", tags="dora, bank de")
    store.create_contact("mueller-soehne", "Anna", "Müller", email="Anna@Mueller.DE")
    store.create_company("Acme", tags="iso")
    store.create_contact("acme", "Bob", "Jones", email="bob@acme.com")

    assert [c.slug for c in store.search("")] == ["acme", "mueller-soehne"]
    assert [c.slug for c in store.search("MÜLLER")] == ["mueller-soehne"]
    assert [c.slug for c in store.search("dora")] == ["mueller-soehne"]
    assert [c.slug for c in store.search("anna")] == ["mueller-soehne"]
    assert [c.slug for c in store.search("bob@acme")] == ["acme"]
    assert [c.slug for c in store.search("e")] == ["acme", "mueller-soehne"]
    assert store.search("nothing here") == []


def test_get_unknown_returns_none(store):
    assert store.get("nope") is None


def test_company_country_is_optional_enum(store, messages):
    c = store.create_company("Acme", country="DE")
    assert c.country == "DE"
    assert "country: DE\n" in read(store.company_dir("acme") / "company.md")
    with pytest.raises(ValidationError) as e:
        store.create_company("Beta", country="XX")
    assert "country" in e.value.errors
    store.update_company("acme", country="")
    assert store.get("acme").country == ""
    assert "country:\n" in read(store.company_dir("acme") / "company.md")
    with pytest.raises(ValidationError):
        store.update_company("acme", country="xx")
    assert messages == ["company: acme created", "company: acme updated"]


def test_engaged_is_an_open_stage(store, messages):
    store.create_company("Acme")
    c = store.update_company("acme", stage="engaged")
    assert c.stage == "engaged" and not c.is_closed
    assert c.stage_changed == FIXED_NOW.date()
    assert messages[-1] == "company: acme stage prospect -> engaged"


def test_next_step_status_lifecycle(store, messages):
    store.create_company("Acme", next_step="Call Jane", next_step_due="2026-09-10")
    c = store.get("acme")
    assert c.next_step_open and c.next_step_overdue(FIXED_NOW.date())
    c = store.update_company("acme", next_step_status="done")
    assert c.next_step_done and not c.next_step_overdue(FIXED_NOW.date())
    assert messages[-1] == "company: acme next step done"
    assert "next_step_status: done\n" in read(store.company_dir("acme") / "company.md")
    c = store.update_company("acme", next_step_status="open")
    assert c.next_step_open and messages[-1] == "company: acme next step reopened"
    # A rewritten next step starts open again, even if the form still says done.
    store.update_company("acme", next_step_status="done")
    c = store.update_company("acme", next_step="Send deck", next_step_status="done")
    assert c.next_step == "Send deck" and c.next_step_open
    # Clearing the task resets the status; unknown values are rejected.
    c = store.update_company("acme", next_step="", next_step_due="", next_step_status="done")
    assert c.next_step_status == "open" and not c.has_next_step
    with pytest.raises(ValidationError):
        store.update_company("acme", next_step_status="later")


def test_disqualify_stages_keep_reason_and_park(store, messages):
    c = store.create_company("Acme", stage="disqualified", lost_reason="no fit")
    assert c.is_closed and c.lost_reason == "no fit"
    c = store.update_company("acme", stage="temp-disqualified", lost_reason="freeze")
    assert c.is_parked and not c.is_closed and not c.is_active and c.lost_reason == "freeze"
    assert messages[-1] == "company: acme stage disqualified -> temp-disqualified"
    c = store.update_company("acme", stage="prospect")
    assert c.is_active and c.lost_reason == ""


def _two_companies(store):
    store.create_company("Acme", website="https://acme.de", my_score=7,
                         tags=["a"], notes="Acme notes.\n", next_step="Call")
    store.create_company("Acme Software", linkedin="https://l/acme", country="DE",
                         my_score=3, fit_score=80, tags=["b"], notes="Other notes.\n")
    store.create_contact("acme", "Jane", "Doe", email="jane@acme.de")
    store.create_contact("acme-software", "Jane", "Doe", title="CEO")
    store.create_contact("acme-software", "Bob", "King")
    store.create_interaction("acme", channel="email", direction="out", contact="jane-doe",
                             subject="A1", date="2026-09-10T09:00")
    store.create_interaction("acme-software", channel="call", direction="in",
                             contact="jane-doe", subject="B1", date="2026-09-11T09:00")
    store.create_interaction("acme-software", channel="email", direction="out",
                             contact="bob-king", subject="B2", date="2026-09-12T09:00",
                             body="body b2\n")
    store.create_interaction("acme-software", channel="email", direction="out",
                             subject="B3", date="2026-09-10T09:00")
    store.create_interaction("acme", channel="email", direction="out",
                             subject="A2", date="2026-09-10T09:00")


def test_merge_companies_defaults_choices_and_moves_everything(store, messages):
    _two_companies(store)
    del messages[:]
    merged = store.merge_companies("acme", "acme-software",
                                   {"my_score": "drop", "tags": "both", "notes": "both"})
    assert messages == ["company: acme-software merged into acme"]
    assert merged.slug == "acme" and merged.name == "Acme"
    assert merged.website == "https://acme.de"           # kept (non-empty)
    assert merged.linkedin == "https://l/acme"           # filled from drop
    assert merged.country == "DE" and merged.fit_score == 80
    assert merged.my_score == 3                        # explicit drop
    assert merged.tags == ["a", "b"]
    assert merged.notes == "Acme notes.\n\n---\n\nOther notes.\n"
    assert merged.next_step == "Call"
    assert sorted(merged.contacts) == ["bob-king", "jane-doe", "jane-doe-2"]
    assert merged.contacts["jane-doe"].email == "jane@acme.de"
    assert merged.contacts["jane-doe-2"].title == "CEO"
    assert len(merged.interactions) == 5
    by_subject = {i.subject: i for i in merged.interactions}
    assert by_subject["B1"].contact == "jane-doe-2"
    assert by_subject["B2"].contact == "bob-king" and by_subject["B2"].body == "body b2\n"
    assert by_subject["B3"].contact == ""
    assert by_subject["B3"].id == "2026-09-10T0900-email-out-company-2"
    assert not store.company_dir("acme-software").exists()
    assert "acme-software" not in store.companies
    assert store.get("acme") is merged
    assert (store.company_dir("acme") / "interactions" / f"{by_subject['B2'].id}.md").exists()


def test_merge_companies_validation(store):
    _two_companies(store)
    with pytest.raises(ValidationError):
        store.merge_companies("acme", "acme")
    with pytest.raises(ValidationError):
        store.merge_companies("acme", "nope")
    with pytest.raises(ValidationError):
        store.merge_companies("nope", "acme")
    store.update_company("acme-software", stage="lost", lost_reason="x")
    with pytest.raises(ValidationError):
        store.merge_companies("acme", "acme-software", {"stage": "drop", "lost_reason": "keep"})
    assert store.get("acme-software") is not None


def test_merge_contacts_repoints_and_renames_interactions(store, messages):
    store.create_company("Acme")
    store.create_contact("acme", "Jane", "Doe", email="jane@acme.de")
    store.create_contact("acme", "J.", "Doe", title="CEO", linkedin="https://l/jd")
    store.create_interaction("acme", channel="email", direction="out", contact="j-doe",
                             subject="Hi", date="2026-09-10T09:00", body="kept\n")
    store.create_interaction("acme", channel="email", direction="out", contact="jane-doe",
                             subject="Hello", date="2026-09-10T09:00")
    del messages[:]
    merged = store.merge_contacts("acme", "jane-doe", "j-doe", {"title": "drop"})
    assert messages == ["contact: acme/j-doe merged into jane-doe"]
    assert merged.name == "Jane Doe" and merged.title == "CEO"
    assert merged.linkedin == "https://l/jd" and merged.email == "jane@acme.de"
    company = store.get("acme")
    assert list(company.contacts) == ["jane-doe"]
    assert not (store.company_dir("acme") / "contacts" / "j-doe.md").exists()
    ids = sorted(i.id for i in company.interactions)
    assert ids == ["2026-09-10T0900-email-out-jane-doe", "2026-09-10T0900-email-out-jane-doe-2"]
    assert all(i.contact == "jane-doe" for i in company.interactions)
    assert {i.body for i in company.interactions} == {"kept\n", ""}
    folder = store.company_dir("acme") / "interactions"
    assert sorted(p.stem for p in folder.glob("*.md")) == ids
    with pytest.raises(ValidationError):
        store.merge_contacts("acme", "jane-doe", "jane-doe")


# ------------------------------------------------------ requalify, results


def test_temp_disqualify_keeps_date_only_while_parked(store, messages):
    store.create_company("Acme", stage="prospect", requalify_on="2026-10-01")
    assert store.get("acme").requalify_on is None  # only meaningful when parked
    store.update_company("acme", stage="temp-disqualified", lost_reason="freeze",
                         requalify_on="2026-10-01")
    text = read(store.company_dir("acme") / "company.md")
    assert "requalify_on: 2026-10-01\n" in text
    store.update_company("acme", stage="prospect")
    assert store.get("acme").requalify_on is None
    assert "requalify_on:\n" in read(store.company_dir("acme") / "company.md")
    with pytest.raises(ValidationError):
        store.update_company("acme", stage="temp-disqualified", requalify_on="soon")


def test_requalify_due_sweep_is_idempotent_and_one_commit(store, messages):
    store.create_company("Later", stage="temp-disqualified", requalify_on="2026-09-20")
    store.create_company("Now", stage="temp-disqualified", requalify_on="2026-09-14")
    store.create_company("Past", stage="temp-disqualified", requalify_on="2026-09-01")
    messages.clear()
    assert store.requalify_due() == ["now", "past"]
    assert messages == ["company: requalified now, past (parked until today)"]
    assert store.get("now").stage == "prospect" and store.get("now").requalify_on is None
    assert store.get("later").stage == "temp-disqualified"
    assert store.requalify_due() == [] and len(messages) == 1
    assert store.requalify_due(date(2026, 9, 20)) == ["later"]
    assert messages[-1] == "company: later requalified (parked until 2026-09-20)"


def test_interaction_outcome_field_and_commit_message(store, messages):
    store.create_company("Acme")
    it = store.create_interaction("acme", channel="linkedin", direction="out",
                                  body="Hi", outcome="")
    path = store.company_dir("acme") / "interactions" / f"{it.id}.md"
    assert it.outcome == "" and "outcome:\n" in read(path) and "result" not in read(path)
    messages.clear()
    store.update_interaction("acme", it.id, outcome="successful")
    assert messages == [f"interaction: acme {it.id} outcome successful"]
    assert "outcome: successful\n" in read(path)
    store.update_interaction("acme", it.id, outcome="")
    assert messages[-1] == f"interaction: acme {it.id} outcome unknown"
    with pytest.raises(ValidationError):
        store.update_interaction("acme", it.id, outcome="meh")
    with pytest.raises(ValidationError):
        store.create_interaction("acme", channel="call", direction="out", outcome="meh")


def test_country_aliases_on_create_and_edit(store):
    store.create_company("Acme", country="uk")
    assert store.get("acme").country == "GB"
    store.update_company("acme", country="USA")
    assert store.get("acme").country == "US"
    store.update_company("acme", country="jp")
    assert store.get("acme").country == "JP"
    with pytest.raises(ValidationError):
        store.update_company("acme", country="Narnia")


def test_interaction_moves_only_a_prospect_to_engaged(store, messages):
    store.create_company("Acme")
    store.create_company("Beta", stage="discovery")
    store.create_interaction("acme", channel="email", direction="in", date="2026-09-10T09:00")
    acme = store.get("acme")
    assert acme.stage == "engaged" and acme.stage_changed == FIXED_NOW.date()
    assert [(e.from_stage, e.to_stage) for e in acme.stage_history] == [("prospect", "engaged")]
    assert len(acme.interactions) == 1
    messages.clear()
    store.create_interaction("acme", channel="call", direction="out")
    assert messages == ["interaction: acme call out company 2026-09-14T10:30"]
    store.create_interaction("beta", channel="linkedin", direction="out")
    assert store.get("beta").stage == "discovery" and store.get("beta").stage_history == [
        StageChange(FIXED_NOW.date(), "", "discovery")]


def test_old_stage_name_is_accepted_as_input(store):
    store.create_company("Acme", stage="reached-out")
    assert store.get("acme").stage == "engaged"
    assert store.update_company("acme", stage="reached-out").stage == "engaged"


def test_delete_contact_keeps_interactions_without_contact(store, messages):
    store.create_company("Acme")
    store.create_contact("acme", "Jane", "Doe")
    store.create_contact("acme", "Tom", "Typo")
    it = store.create_interaction("acme", channel="linkedin", direction="out",
                                  contact="jane-doe", date="2026-09-10T09:00", body="Hi Jane\n")
    messages.clear()
    store.delete_contact("acme", "tom-typo")
    assert messages == ["contact: acme/tom-typo deleted"]
    store.delete_contact("acme", "jane-doe")
    assert messages[-1] == "contact: acme/jane-doe deleted (1 interaction(s) kept without a contact)"
    assert len(messages) == 2
    folder = store.root / "companies" / "acme"
    assert not (folder / "contacts" / "jane-doe.md").exists()
    assert not (folder / "interactions" / f"{it.id}.md").exists()
    c = fresh(store).get("acme")
    assert c.contacts == {} and len(c.interactions) == 1
    kept = c.interactions[0]
    assert kept.contact == "" and kept.body == "Hi Jane\n"
    assert kept.id == "2026-09-10T0900-linkedin-out-company"
    with pytest.raises(ValidationError):
        store.delete_contact("acme", "jane-doe")
