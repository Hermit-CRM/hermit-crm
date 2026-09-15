"""Unknown front-matter keys survive every write, after the known keys, sorted."""

from owncrm.models import (Contact, company_from_dict, company_to_frontmatter,
                           contact_from_dict, contact_to_frontmatter, dump_frontmatter)
from owncrm.store import Store, split_file
from conftest import FIXED_NOW


def test_models_round_trip_extra_keys():
    meta = {"name": "Acme", "zeta": "last", "alpha": {"b": 2, "a": 1}, "custom": ["x", "y"]}
    c = company_from_dict(meta, "", "acme")
    assert c.extra == {"zeta": "last", "alpha": {"b": 2, "a": 1}, "custom": ["x", "y"]}
    out = company_to_frontmatter(c)
    assert list(out)[-3:] == ["alpha", "custom", "zeta"]
    assert list(out)[:2] == ["name", "slug"]
    text = dump_frontmatter(out)
    assert text.endswith("alpha: {a: 1, b: 2}\ncustom: [x, y]\nzeta: last\n")
    ct = contact_from_dict({"first_name": "Jo", "pronouns": "they", "name": "Jo X"}, "", "jo")
    assert ct.extra == {"pronouns": "they"}  # legacy `name` is a known key
    assert list(contact_to_frontmatter(ct))[-1] == "pronouns"
    assert contact_to_frontmatter(Contact("A", "B", "ab"))  # no extra, no crash


def test_store_writes_preserve_extra_keys(tmp_path):
    store = Store(tmp_path, clock=lambda: FIXED_NOW)
    store.load()
    store.create_company("Acme", country="DE")
    store.create_contact("acme", "Jane", "Doe", email="jane@acme.example.com")
    it = store.create_interaction("acme", channel="email", direction="out",
                                  contact="jane-doe", date="2026-09-10T09:00", body="Hi\n")
    folder = tmp_path / "companies/acme"
    paths = {"company": folder / "company.md",
             "contact": folder / "contacts/jane-doe.md",
             "interaction": folder / f"interactions/{it.id}.md"}
    for path in paths.values():  # a user or another tool adds its own keys
        text = path.read_text()
        path.write_text(text.replace("---\n", "---\nzz_tool: 1\naa_owner: me\n", 1))
    store.load()

    store.update_company("acme", stage="reached-out", next_step="Call")
    store.update_contact("acme", "jane-doe", title="CEO")
    store.update_interaction("acme", it.id, outcome="replied")

    for kind, path in paths.items():
        meta, body = split_file(path.read_text())
        assert meta["aa_owner"] == "me" and meta["zz_tool"] == 1, kind
        assert list(meta)[-2:] == ["aa_owner", "zz_tool"], kind
    first = paths["company"].read_text()
    store.load()
    store.update_company("acme", next_step="Call")  # no-op write is deterministic
    assert paths["company"].read_text().split("updated:")[0] == first.split("updated:")[0]
    assert store.get("acme").stage == "reached-out"
