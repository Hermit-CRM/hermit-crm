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

"""Bulk import of companies and contacts from a pasted TSV/CSV table or .xlsx.

The first row is a header. Two modes:

- "companies": one company per row, plus an optional contact from columns
  prefixed `founder_`, `contact_` or `person_`. Existing companies (matched by
  the slug of the name) only get empty fields filled; existing contacts are
  left alone.
- "contacts": one person per row (HubSpot, Apollo, LinkedIn, Pipedrive, Attio
  exports). The company comes from a company column, else from a non-freemail
  email domain. Companies match by slug or website domain, contacts by email,
  else by name; only empty fields are filled.

Headers map to fields through alias tables; an explicit mapping
{header: field | "ignore" | "notes"} overrides them. Every column mapped to
"notes" is kept as a `column: value` line so nothing from the sheet is lost.
"""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .models import (
    Country,
    normalise_country,
    Role,
    Source,
    Stage,
    ValidationError,
    normalise_email,
    normalise_linkedin,
    normalise_website,
    parse_tags,
    slugify,
    split_name,
)
from .bcc import FREEMAIL

# Header aliases (normalised: lower case, non-alphanumerics collapsed to "_").
COMPANY_COLUMNS = {
    "name": "name", "company": "name", "company_name": "name",
    "organization": "name", "organisation": "name", "organization_name": "name",
    "account": "name", "account_name": "name",
    "website": "website", "url": "website", "domain": "website",
    "website_url": "website", "company_website": "website", "company_domain": "website",
    "linkedin": "linkedin", "company_linkedin": "linkedin", "linkedin_url": "linkedin",
    "company_linkedin_url": "linkedin", "linkedin_company_page": "linkedin",
    "country": "country", "hq_country": "country", "country_region": "country",
    "company_country": "country",
    "source": "source", "stage": "stage",
    "product_oneliner": "product_oneliner",
    "oneliner": "product_oneliner", "description": "product_oneliner",
    "value_eur_month": "value_eur_month",
    "next_step": "next_step", "next_step_due": "next_step_due",
    "tags": "tags", "opportunity_type": "tags",
    "comments": "notes_text", "notes": "notes_text",
}
CONTACT_PREFIXES = ("founder_", "contact_", "person_")
CONTACT_COLUMNS = {
    "name": "name", "full_name": "name", "first_name": "first_name",
    "last_name": "last_name", "title": "title", "job_title": "title",
    "linkedin": "linkedin", "linkedin_url": "linkedin", "email": "email",
    "phone": "phone", "role": "role",
}
# Contacts mode: one person per row.
PERSON_COLUMNS = {
    "first_name": "first_name", "firstname": "first_name", "given_name": "first_name",
    "last_name": "last_name", "lastname": "last_name", "surname": "last_name",
    "family_name": "last_name",
    "name": "name", "full_name": "name", "person_name": "name", "contact_name": "name",
    "email": "email", "email_address": "email", "e_mail": "email", "work_email": "email",
    "person_email": "email", "contact_email": "email", "primary_email": "email",
    "email_addresses": "email",
    "title": "title", "job_title": "title", "position": "title", "person_title": "title",
    "person_job_title": "title",
    "linkedin": "linkedin", "linkedin_url": "linkedin", "url": "linkedin",
    "person_linkedin_url": "linkedin", "linkedin_profile": "linkedin",
    "profile_url": "linkedin",
    "phone": "phone", "phone_number": "phone", "phone_numbers": "phone",
    "mobile_phone": "phone", "mobile": "phone", "work_phone": "phone",
    "person_phone": "phone", "corporate_phone": "phone",
    "role": "role",
    "company": "company", "company_name": "company", "organization": "company",
    "organisation": "company", "account": "company", "account_name": "company",
    "organization_name": "company", "person_organization": "company",
    "website": "website", "domain": "website", "company_website": "website",
    "website_url": "website", "company_domain": "website",
    "organization_website": "website",
    "company_linkedin_url": "company_linkedin", "company_linkedin": "company_linkedin",
    "country": "country", "country_region": "country", "company_country": "country",
    "tags": "tags",
}
MODES = ("companies", "contacts")
COMPANY_TARGETS = {
    "name": "company name", "website": "website", "linkedin": "company LinkedIn",
    "country": "country", "source": "source", "stage": "stage",
    "product_oneliner": "product oneliner",
    "value_eur_month": "value EUR/month", "next_step": "next step",
    "next_step_due": "next step due", "tags": "tags", "notes_text": "notes (as text)",
    "contact_name": "contact: full name", "contact_first_name": "contact: first name",
    "contact_last_name": "contact: last name", "contact_title": "contact: title",
    "contact_linkedin": "contact: LinkedIn", "contact_email": "contact: email",
    "contact_phone": "contact: phone", "contact_role": "contact: role",
    "contact_notes": "contact: notes line",
}
CONTACT_TARGETS = {
    "first_name": "first name", "last_name": "last name", "name": "full name",
    "email": "email", "title": "title", "linkedin": "LinkedIn", "phone": "phone",
    "role": "role", "company": "company name", "website": "company website",
    "company_linkedin": "company LinkedIn", "country": "company country",
    "tags": "company tags",
}
SPECIAL_TARGETS = {"notes": "keep as notes line", "ignore": "ignore"}
COMPANY_ONLY = {"source", "stage",
                "product_oneliner", "value_eur_month", "next_step", "next_step_due",
                "notes_text"}
COUNTRY_ALIASES = {
    "germany": "DE", "deutschland": "DE", "de": "DE",
    "switzerland": "CH", "schweiz": "CH", "suisse": "CH", "ch": "CH",
    "netherlands": "NL", "the netherlands": "NL", "nederland": "NL", "nl": "NL",
    "sweden": "SE", "sverige": "SE", "se": "SE",
    "denmark": "DK", "danmark": "DK", "dk": "DK",
    "norway": "NO", "norge": "NO", "no": "NO",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB",
    "usa": "US", "united states": "US", "united states of america": "US",
    "austria": "AT", "österreich": "AT", "france": "FR", "belgium": "BE",
    "belgië": "BE", "belgique": "BE", "luxembourg": "LU", "liechtenstein": "LI",
    "monaco": "MC", "spain": "ES", "españa": "ES", "italy": "IT", "italia": "IT",
    "ireland": "IE", "poland": "PL", "polska": "PL", "finland": "FI", "suomi": "FI",
    "portugal": "PT", "canada": "CA", "australia": "AU",
}
DECISION_MAKER_TITLES = re.compile(
    r"\b(founder|ceo|cto|coo|cfo|cro|managing director|geschäftsführer|owner)\b",
    re.IGNORECASE,
)
INT_FIELDS = ("value_eur_month",)


def normalise_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (header or "").strip().lower()).strip("_")


def map_country(value: str) -> str | None:
    """Return the enum value for a country name, or None when unmapped."""
    key = (value or "").strip().lower()
    if not key:
        return ""
    code = normalise_country(key)
    if code in {c.value for c in Country}:
        return code
    return COUNTRY_ALIASES.get(key)


# ------------------------------------------------------------------- parsing


def parse_table(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Split pasted text into (headers, rows). Tab wins; otherwise sniff , or ;."""
    text = (text or "").lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return [], []
    if "\t" in lines[0]:
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(lines[0], delimiters=",;").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    headers = [h.strip() for h in next(reader)]
    rows = []
    for raw in reader:
        if not any(cell.strip() for cell in raw):
            continue
        raw = list(raw) + [""] * (len(headers) - len(raw))
        rows.append({h: raw[i].strip() for i, h in enumerate(headers) if h})
    return headers, rows


def _local(tag: str) -> str:
    return tag.rpartition("}")[2]


def _xlsx_text(node) -> str:
    """Text of a shared string or inline string: plain <t> or rich-text runs."""
    parts = []
    for child in node:
        tag = _local(child.tag)
        if tag == "t":
            parts.append(child.text or "")
        elif tag == "r":
            parts += [t.text or "" for t in child if _local(t.tag) == "t"]
    return "".join(parts)


def _column_index(letters: str) -> int:
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - 64)
    return index - 1


def _xlsx_number(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    return value


def _first_sheet(zf: zipfile.ZipFile, names: set[str]) -> str:
    try:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        first = next(e for e in workbook.iter() if _local(e.tag) == "sheet")
        rid = next(v for k, v in first.attrib.items() if _local(k) == "id")
        target = next(r.get("Target", "") for r in rels if r.get("Id") == rid)
        target = target.lstrip("/")
        path = target if target.startswith("xl/") else "xl/" + target
        if path in names:
            return path
    except (KeyError, StopIteration, ET.ParseError):
        pass
    sheets = sorted((n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                    key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    if not sheets:
        raise ValidationError({"file": "the .xlsx file has no worksheet"})
    return sheets[0]


def xlsx_to_text(data: bytes) -> str:
    """First worksheet of an .xlsx as tab-separated text (standard library only).

    Shared and inline strings are read; numbers come out as text (whole numbers
    without ".0"). Dates stay Excel serial numbers, since telling a date from a
    number needs the style table.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValidationError({"file": "could not read the file as .xlsx"})
    try:
        with zf:
            names = set(zf.namelist())
            shared = []
            if "xl/sharedStrings.xml" in names:
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                shared = [_xlsx_text(si) for si in root if _local(si.tag) == "si"]
            sheet = ET.fromstring(zf.read(_first_sheet(zf, names)))
    except (KeyError, ET.ParseError, zipfile.BadZipFile):
        raise ValidationError({"file": "could not read the file as .xlsx"})
    out = io.StringIO()
    writer = csv.writer(out, delimiter="\t", lineterminator="\n")
    for row in sheet.iter():
        if _local(row.tag) != "row":
            continue
        cells: dict[int, str] = {}
        next_col = 0
        for cell in row:
            if _local(cell.tag) != "c":
                continue
            letters = re.match(r"[A-Z]+", cell.get("r", ""))
            col = _column_index(letters.group()) if letters else next_col
            next_col = col + 1
            kind = cell.get("t", "n")
            v = next((x for x in cell if _local(x.tag) == "v"), None)
            raw = v.text if v is not None and v.text else ""
            if kind == "s":
                value = shared[int(raw)] if raw.isdigit() and int(raw) < len(shared) else ""
            elif kind == "inlineStr":
                inline = next((x for x in cell if _local(x.tag) == "is"), None)
                value = _xlsx_text(inline) if inline is not None else ""
            elif kind == "b":
                value = "TRUE" if raw == "1" else "FALSE" if raw else ""
            elif kind == "n":
                value = _xlsx_number(raw)
            else:
                value = raw
            cells[col] = " ".join(value.replace("\t", " ").splitlines())
        width = max(cells) + 1 if cells else 0
        writer.writerow([cells.get(i, "") for i in range(width)])
    return out.getvalue()


def decode_upload(raw: bytes) -> str:
    """Uploaded bytes as table text: .xlsx (zip magic) or a UTF-8/16/cp1252 text file."""
    if raw[:2] == b"PK":
        return xlsx_to_text(raw)
    # UTF-16 only with a byte-order mark: without one, any even-length cp1252
    # file "decodes" as UTF-16 garbage.
    encodings = ("utf-16",) if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ()
    for encoding in encodings + ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError({"file": "could not decode the file as UTF-8"})


# ------------------------------------------------------------------ mapping


# A mapping target for a field the folder defined itself, using the same
# prefix convention the contact columns already use.
CUSTOM_PREFIX = "custom_"


def custom_targets(defs: list | None, mode: str) -> dict[str, str]:
    """Mapping targets for the user's own fields, for this mode's main record."""
    scope = "company" if mode == "companies" else "contact"
    return {f"{CUSTOM_PREFIX}{d.key}": d.label
            for d in (defs or []) if d.applies_to == scope}


def targets(mode: str, defs: list | None = None) -> dict[str, str]:
    """Field value -> label for the mapping dropdown of a mode."""
    base = COMPANY_TARGETS if mode == "companies" else CONTACT_TARGETS
    return {**base, **custom_targets(defs, mode), **SPECIAL_TARGETS}


def default_target(header: str, mode: str, defs: list | None = None) -> str:
    key = normalise_header(header)
    custom = {d.key: d for d in (defs or [])
              if d.applies_to == ("company" if mode == "companies" else "contact")}
    # A column named exactly like one of your fields maps to it without being told.
    if key in custom:
        return f"{CUSTOM_PREFIX}{key}"
    if mode == "contacts":
        return PERSON_COLUMNS.get(key, "notes")
    prefix = next((p for p in CONTACT_PREFIXES if key.startswith(p)), None)
    if prefix:
        ckey = CONTACT_COLUMNS.get(key[len(prefix):])
        return f"contact_{ckey}" if ckey else "contact_notes"
    return COMPANY_COLUMNS.get(key, "notes")


def default_mapping(headers: list[str], mode: str, defs: list | None = None) -> dict[str, str]:
    return {h: default_target(h, mode, defs) for h in headers if h}


def detect_mode(headers: list[str], defs: list | None = None) -> str:
    """contacts when a person-name or email column and a company column are
    present and nothing company-only (stage, founder_ columns, a field you
    defined on companies...)."""
    keys = [normalise_header(h) for h in headers]
    own = {d.key for d in (defs or []) if d.applies_to == "company"}
    person = any(PERSON_COLUMNS.get(k) in ("first_name", "last_name", "email")
                 or (PERSON_COLUMNS.get(k) == "name" and k != "name") for k in keys)
    company = any(PERSON_COLUMNS.get(k) == "company" for k in keys)
    company_only = any(COMPANY_COLUMNS.get(k) in COMPANY_ONLY or k.startswith("founder_")
                       or k in own
                       for k in keys)
    return "contacts" if person and company and not company_only else "companies"


def resolve_mapping(headers: list[str], mode: str, mapping: dict | None = None,
                    defs: list | None = None) -> dict:
    allowed = targets(mode, defs)
    result = default_mapping(headers, mode, defs)
    errors = []
    for header, target in (mapping or {}).items():
        if header not in result:
            continue
        target = (target or "").strip()
        if target not in allowed:
            errors.append(f"{header}: unknown field {target!r} for {mode} mode")
        else:
            result[header] = target
    if errors:
        raise ValidationError({"mapping": "; ".join(errors)})
    return result


def alias_help(mode: str) -> list[tuple[str, list[str]]]:
    """(field label, [recognised header names]) for the Import page help."""
    table = COMPANY_COLUMNS if mode == "companies" else PERSON_COLUMNS
    labels = targets(mode)
    grouped: dict[str, list[str]] = {}
    for alias, target in table.items():
        grouped.setdefault(target, []).append(alias)
    return [(labels.get(t, t), names) for t, names in grouped.items()]


# ------------------------------------------------------------------ planning


@dataclass
class RowPlan:
    row: int
    name: str
    slug: str
    action: str  # create | update | keep (contacts mode: company unchanged) | skip
    reason: str = ""
    fields: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    contact: dict | None = None
    contact_action: str = "none"  # create | update | exists | none
    warnings: list[str] = field(default_factory=list)
    contact_slug: str = ""  # the matched contact (contacts mode)
    contact_fields: dict = field(default_factory=dict)  # empty contact fields to fill
    custom: dict = field(default_factory=dict)  # user-defined fields, stored in `extra`


@dataclass
class ImportPlan:
    headers: list[str]
    rows: list[RowPlan]
    mode: str = "companies"
    mapping: dict = field(default_factory=dict)
    samples: dict = field(default_factory=dict)
    defs: list = field(default_factory=list)  # the folder's own field definitions

    def count(self, action: str) -> int:
        return sum(1 for r in self.rows if r.action == action)

    @property
    def contacts_to_create(self) -> int:
        return sum(1 for r in self.rows if r.contact_action == "create" and r.action != "skip")

    @property
    def contacts_to_update(self) -> int:
        return sum(1 for r in self.rows if r.contact_action == "update" and r.action != "skip")

    @property
    def has_changes(self) -> bool:
        return bool(self.count("create") or self.count("update")
                    or self.contacts_to_create or self.contacts_to_update)

    @property
    def choices(self) -> list[tuple[str, str]]:
        return list(targets(self.mode, self.defs).items())

    @property
    def summary(self) -> str:
        if self.mode == "contacts":
            return (
                f"{self.contacts_to_create} contacts to create, {self.contacts_to_update} "
                f"to update, {self.count('create')} companies to create, "
                f"{self.count('update')} to update, {self.count('skip')} rows skipped"
            )
        return (
            f"{self.count('create')} companies to create, {self.count('update')} to "
            f"update, {self.count('skip')} rows skipped, "
            f"{self.contacts_to_create} contacts to create"
        )


def _int(value: str):
    value = value.strip().lstrip("~")
    return int(value) if re.fullmatch(r"-?\d+", value) else None


def _imported_block(existing: str, lines: list[str], stamp: str) -> str:
    return existing.rstrip("\n") + ("\n\n" if existing.strip() else "") + \
        f"Imported fields ({stamp}):\n" + "\n".join(f"- {line}" for line in lines) + "\n"


def _contact_role(contact: dict) -> None:
    if contact.get("role") not in {r.value for r in Role}:
        contact.pop("role", None)
        if DECISION_MAKER_TITLES.search(contact.get("title", "")):
            contact["role"] = Role.DECISION_MAKER.value


def _plan_row(store, index: int, row: dict[str, str], today, mapping=None,
              defs: list | None = None) -> RowPlan:
    if mapping is None:
        mapping = default_mapping(list(row), "companies", defs)
    by_key = {d.key: d for d in (defs or []) if d.applies_to == "company"}
    custom: dict = {}
    fields: dict = {}
    tags: list[str] = []
    notes_text = ""
    extras: list[str] = []
    contact: dict = {}
    contact_extras: list[str] = []
    warnings: list[str] = []

    for header, value in row.items():
        target = mapping.get(header, "notes")
        if not value or target == "ignore":
            continue
        if target.startswith(CUSTOM_PREFIX):
            defn = by_key.get(target[len(CUSTOM_PREFIX):])
            if defn is None:
                extras.append(f"{header}: {value}")
                continue
            try:
                custom[defn.key] = defn.coerce(value)
            except ValueError as exc:
                warnings.append(f"{exc}; kept in notes")
                extras.append(f"{header}: {value}")
            continue
        if target.startswith("contact_"):
            ckey = target[len("contact_"):]
            if ckey == "notes":
                contact_extras.append(f"{header}: {value}")
            else:
                contact.setdefault(ckey, value)
            continue
        fkey = target
        if fkey == "notes":
            extras.append(f"{header}: {value}")
        elif fkey == "tags":
            tags += parse_tags(value)
        elif fkey == "notes_text":
            notes_text = value
        elif fkey == "country":
            mapped = map_country(value)
            if mapped:
                fields["country"] = mapped
            else:
                warnings.append(f"country {value!r} is not in the list; kept in notes")
                extras.append(f"{header}: {value}")
        elif fkey in INT_FIELDS:
            number = _int(value)
            if number is None:
                warnings.append(f"{fkey} {value!r} is not a whole number; kept in notes")
                extras.append(f"{header}: {value}")
            else:
                fields[fkey] = number
        elif fkey == "source":
            if value in {s.value for s in Source}:
                fields["source"] = value
            else:
                extras.append(f"{header}: {value}")
        elif fkey == "stage":
            if value in {s.value for s in Stage}:
                fields["stage"] = value
            else:
                extras.append(f"{header}: {value}")
        elif fkey == "website":
            fields["website"] = normalise_website(value)
        elif fkey == "linkedin":
            fields["linkedin"] = normalise_linkedin(value)
        else:
            fields.setdefault(fkey, " ".join(value.split()))

    name = " ".join(fields.pop("name", "").split()).strip(" ,;")
    if not name:
        return RowPlan(row=index, name="", slug="", action="skip",
                       reason="empty name", warnings=warnings)
    slug = slugify(name, strip_legal=True, default="company")
    fields.setdefault("source", "list")

    if contact:
        first, last = contact.pop("first_name", ""), contact.pop("last_name", "")
        if not first and not last:
            first, last = split_name(contact.pop("name", ""))
        contact.pop("name", None)
        contact["first_name"], contact["last_name"] = first, last
        if "linkedin" in contact:
            contact["linkedin"] = normalise_linkedin(contact["linkedin"])
        _contact_role(contact)
        if contact_extras:
            contact["notes"] = "\n".join(contact_extras) + "\n"
        if not first and not last:
            warnings.append("contact columns present but no contact name; skipped")
            contact = {}
        else:
            contact["slug"] = slugify(f"{first} {last}", default="contact")

    stamp = today.isoformat()
    existing = store.companies.get(slug)
    if existing is None:
        notes = notes_text.strip()
        if extras:
            notes += ("\n\n" if notes else "") + f"Imported fields ({stamp}):\n" + \
                "\n".join(f"- {line}" for line in extras)
        plan = RowPlan(row=index, name=name, slug=slug, action="create",
                       fields=fields, tags=sorted(set(tags)), notes=notes + "\n" if notes else "",
                       custom=custom, warnings=warnings)
        if contact:
            plan.contact, plan.contact_action = contact, "create"
        return plan

    # Existing company: fill empty fields only, never overwrite.
    fill = {}
    for key, value in fields.items():
        if key in ("source", "stage"):
            continue
        current = getattr(existing, key)
        if current in ("", None):
            fill[key] = value
    # Custom fields obey the same rule: fill an empty one, never overwrite.
    fill_custom = {k: v for k, v in custom.items()
                   if (existing.extra or {}).get(k) in ("", None)}
    new_tags = sorted(set(existing.tags) | set(tags))
    if new_tags != sorted(existing.tags):
        fill["tags"] = new_tags
    added_notes = [line for line in ([notes_text] if notes_text else []) + extras
                   if line and line not in existing.notes]
    if added_notes:
        fill["notes"] = _imported_block(existing.notes, added_notes, stamp)
    contact_action = "none"
    if contact:
        contact_action = "exists" if contact["slug"] in existing.contacts else "create"
    if not fill and not fill_custom and contact_action != "create":
        return RowPlan(row=index, name=name, slug=slug, action="skip",
                       reason="already up to date", contact=contact or None,
                       contact_action=contact_action, warnings=warnings)
    filled = sorted(set(fill) | set(fill_custom))
    reason = "fills " + ", ".join(filled) if filled else "adds contact only"
    return RowPlan(row=index, name=name, slug=slug, action="update", reason=reason,
                   fields=fill, custom=fill_custom, contact=contact or None,
                   contact_action=contact_action, warnings=warnings)


def _host(url: str) -> str:
    host = (urlparse(normalise_website(url)).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _email_domain(email: str) -> str:
    return email.rpartition("@")[2].lower() if "@" in email else ""


def _first_email(value: str) -> str:
    return next((normalise_email(p) for p in re.split(r"[,;\s]+", value or "") if "@" in p), "")


def name_from_domain(domain: str) -> str:
    """acme-labs.de -> 'Acme-labs'; acme.co.uk -> 'Acme'."""
    labels = [label for label in domain.lower().split(".") if label]
    if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "net", "ac", "gov") \
            and len(labels[-1]) == 2:
        label = labels[-3]
    else:
        label = labels[-2] if len(labels) >= 2 else (labels[0] if labels else "")
    return label[:1].upper() + label[1:]


def _name_key(first: str, last: str) -> str:
    return " ".join(f"{first} {last}".split()).casefold()


class _ContactPlanner:
    """Plans contacts-mode rows, remembering companies and people planned earlier
    in the same import so five people at one new company create it once."""

    def __init__(self, store, today):
        self.store, self.stamp = store, today.isoformat()
        self.by_domain: dict[str, str | None] = {}
        self.by_email: dict[str, tuple[str, str]] = {}
        for slug, company in store.companies.items():
            domains = {_host(company.website)} if company.website else set()
            for cslug, contact in company.contacts.items():
                if contact.email:
                    email = normalise_email(contact.email)
                    self.by_email.setdefault(email, (slug, cslug))
                    domains.add(_email_domain(email))
            for domain in domains - FREEMAIL - {""}:
                # A domain shared by two companies is ambiguous: match neither.
                self.by_domain[domain] = slug if self.by_domain.get(domain, slug) == slug else None
        self.pending: set[str] = set()
        self.pending_domains: dict[str, str] = {}
        self.planned_people: dict[str, set[str]] = {}

    def _domain_slug(self, domain: str) -> str | None:
        return self.by_domain.get(domain) or self.pending_domains.get(domain)

    def plan(self, index: int, row: dict[str, str], mapping: dict) -> RowPlan:
        values: dict[str, tuple[str, str]] = {}
        extras: list[str] = []
        tags: list[str] = []
        warnings: list[str] = []
        for header, value in row.items():
            target = mapping.get(header, "notes")
            value = (value or "").strip()
            if not value or target == "ignore":
                continue
            if target == "notes":
                extras.append(f"{header}: {value}")
            elif target == "tags":
                tags += parse_tags(value)
            else:
                values.setdefault(target, (header, value))

        def get(key: str) -> str:
            return values.get(key, ("", ""))[1]

        first, last = get("first_name"), get("last_name")
        if not first and not last:
            first, last = split_name(get("name"))
        first, last = " ".join(first.split()), " ".join(last.split())
        email = _first_email(get("email"))
        if not first and not last:
            return RowPlan(row=index, name="", slug="", action="skip",
                           reason="no contact name", warnings=warnings)

        # --- company
        company_name = " ".join(get("company").split()).strip(" ,;")
        website = normalise_website(get("website")) if get("website") else ""
        email_domain = _email_domain(email)
        if email_domain in FREEMAIL:
            email_domain = ""
        if not website and email_domain:
            website = "https://" + email_domain
        domain = _host(website) if website else ""
        store = self.store
        hit = self.by_email.get(email) if email else None
        if hit:
            slug = hit[0]
        elif company_name:
            slug = slugify(company_name, strip_legal=True, default="company")
            if slug not in store.companies and slug not in self.pending and domain:
                slug = self._domain_slug(domain) or slug
        elif domain and self._domain_slug(domain):
            slug = self._domain_slug(domain)
        elif domain:
            company_name = name_from_domain(domain)
            slug = slugify(company_name, strip_legal=True, default="company")
            warnings.append(f"no company given; {company_name!r} derived from {domain}")
        else:
            return RowPlan(row=index, name="", slug="", action="skip",
                           reason="no company",
                           warnings=["no company column and no company email domain; skipped"])

        company_fields: dict = {}
        if website:
            company_fields["website"] = website
        if get("company_linkedin"):
            company_fields["linkedin"] = normalise_linkedin(get("company_linkedin"))
        if get("country"):
            mapped = map_country(get("country"))
            if mapped:
                company_fields["country"] = mapped
            else:
                warnings.append(f"country {get('country')!r} is not in the list; kept in notes")
                extras.append(f"{values['country'][0]}: {get('country')}")


        existing = store.companies.get(slug)
        if existing is not None:
            name = existing.name
            fill = {k: v for k, v in company_fields.items()
                    if getattr(existing, k) in ("", None)}
            new_tags = sorted(set(existing.tags) | set(tags))
            if new_tags != sorted(existing.tags):
                fill["tags"] = new_tags
            action = "update" if fill else "keep"
            reason = ("fills " + ", ".join(sorted(fill))) if fill else "existing company"
            plan = RowPlan(row=index, name=name, slug=slug, action=action, reason=reason,
                           fields=fill, warnings=warnings)
        elif slug in self.pending:
            plan = RowPlan(row=index, name=company_name or slug, slug=slug, action="keep",
                           reason="company created by an earlier row", warnings=warnings)
        else:
            company_fields["source"] = "list"
            plan = RowPlan(row=index, name=company_name, slug=slug, action="create",
                           fields=company_fields, tags=sorted(set(tags)), warnings=warnings)
            self.pending.add(slug)
            if domain:
                self.pending_domains.setdefault(domain, slug)

        # --- contact
        contact = {"first_name": first, "last_name": last}
        for key in ("title", "phone", "role"):
            if get(key):
                contact[key] = " ".join(get(key).split())
        if get("linkedin"):
            contact["linkedin"] = normalise_linkedin(get("linkedin"))
        if email:
            contact["email"] = email
        _contact_role(contact)
        contact["slug"] = slugify(f"{first} {last}", default="contact")
        plan.contact = contact

        keys = {f"n:{_name_key(first, last)}"} | ({f"e:{email}"} if email else set())
        seen = self.planned_people.setdefault(slug, set())
        if keys & seen:
            plan.contact_action = "exists"
            warnings.append("same person as an earlier row; skipped")
        elif existing is not None:
            match = hit[1] if hit and hit[0] == slug else ""
            if not match:
                target = _name_key(first, last)
                match = next((cs for cs, c in existing.contacts.items()
                              if _name_key(c.first_name, c.last_name) == target), "")
                if match and email and existing.contacts[match].email and \
                        normalise_email(existing.contacts[match].email) != email:
                    warnings.append(f"matched {match} by name, but the email differs; "
                                    "email not changed")
            if match:
                current = existing.contacts[match]
                fill = {k: v for k, v in contact.items()
                        if k in ("title", "linkedin", "email", "phone", "role")
                        and getattr(current, k) in ("", None)}
                new_lines = [line for line in extras if line not in current.notes]
                if new_lines:
                    fill["notes"] = _imported_block(current.notes, new_lines, self.stamp)
                plan.contact_slug = match
                plan.contact_fields = fill
                plan.contact_action = "update" if fill else "exists"
            else:
                plan.contact_action = "create"
        else:
            plan.contact_action = "create"
        if plan.contact_action == "create" and extras:
            contact["notes"] = _imported_block("", extras, self.stamp)
        seen |= keys

        if plan.action == "keep" and plan.contact_action == "exists":
            plan.action, plan.reason = "skip", "already up to date"
        return plan


def plan_import(store, text: str, mode: str | None = None,
                mapping: dict | None = None, defs: list | None = None) -> ImportPlan:
    headers, rows = parse_table(text)
    if not headers:
        raise ValidationError({"text": "nothing to import: paste a table with a header row"})
    mode = (mode or "").strip().lower() or detect_mode(headers, defs)
    if mode not in MODES:
        raise ValidationError({"mode": f"unknown mode {mode!r}; use companies or contacts"})
    resolved = resolve_mapping(headers, mode, mapping, defs)
    used = set(resolved.values())
    today = store.today()
    if mode == "companies":
        if "name" not in used:
            raise ValidationError({"text": "the header row needs a 'name' column"})
        plans = [_plan_row(store, i + 2, row, today, resolved, defs)
                 for i, row in enumerate(rows)]
    else:
        if not used & {"name", "first_name", "last_name"}:
            raise ValidationError({"text": "contacts mode needs a name, first name or "
                                           "last name column"})
        planner = _ContactPlanner(store, today)
        plans = [planner.plan(i + 2, row, resolved) for i, row in enumerate(rows)]
    samples = {h: (rows[0].get(h, "") if rows else "") for h in headers if h}
    return ImportPlan(headers=headers, rows=plans, mode=mode, mapping=resolved,
                      samples=samples, defs=list(defs or []))


# ------------------------------------------------------------------ applying


def apply_import(store, plan: ImportPlan) -> dict[str, int]:
    """Write every planned row inside one batch (one commit). Returns counts."""
    counts = {"created": 0, "updated": 0, "contacts": 0, "skipped": 0, "failed": 0}
    if plan.mode == "contacts":
        counts["contacts_updated"] = 0
        message = (f"import: {plan.contacts_to_create} contacts created, "
                   f"{plan.contacts_to_update} updated, "
                   f"{plan.count('create')} companies created")
    else:
        message = (f"import: {plan.count('create')} companies created, "
                   f"{plan.count('update')} updated, {plan.contacts_to_create} contacts created")
    created_slugs: dict[str, str] = {}
    with store.batch(message):
        for row in plan.rows:
            try:
                if row.action == "create":
                    company = store.create_company(
                        name=row.name, tags=row.tags, notes=row.notes,
                        custom=row.custom, **row.fields)
                    created_slugs[row.slug] = company.slug
                    counts["created"] += 1
                elif row.action == "update":
                    if row.fields or row.custom:
                        store.update_company(row.slug, custom=row.custom, **row.fields)
                    counts["updated"] += 1
                elif row.action != "keep":
                    counts["skipped"] += 1
                    continue
                slug = created_slugs.get(row.slug, row.slug)
                if row.contact_action == "create" and row.contact:
                    contact = {k: v for k, v in row.contact.items() if k != "slug"}
                    store.create_contact(slug, **contact)
                    counts["contacts"] += 1
                elif row.contact_action == "update" and row.contact_fields:
                    store.update_contact(slug, row.contact_slug, **row.contact_fields)
                    counts["contacts_updated"] += 1
            except ValidationError as exc:
                counts["failed"] += 1
                row.warnings.append("; ".join(f"{k}: {v}" for k, v in exc.errors.items()))
    return counts
