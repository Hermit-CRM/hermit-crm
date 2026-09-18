"""Dataclasses, enums, validation and (de)serialisation for Hermit CRM.

The Markdown files under companies/ are the source of truth; everything here
exists to turn those files into objects and back again, byte-deterministically.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Iterable

import yaml

# --------------------------------------------------------------------------- enums


class Source(str, Enum):
    LINKEDIN_SEARCH = "linkedin-search"
    REFERRAL = "referral"
    INBOUND = "inbound"
    EVENT = "event"
    LIST = "list"
    NETWORK = "network"
    OTHER = "other"


class Stage(str, Enum):
    PROSPECT = "prospect"
    ENGAGED = "engaged"
    DISCOVERY = "discovery"
    OFFER = "offer"
    WON = "won"
    LOST = "lost"
    DISQUALIFIED = "disqualified"
    TEMP_DISQUALIFIED = "temp-disqualified"


# ISO 3166-1 alpha-2, all 249 officially assigned codes.
ISO_3166_ALPHA2 = (
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT", "AU", "AW", "AX", "AZ",
    "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI", "BJ", "BL", "BM", "BN", "BO", "BQ", "BR", "BS",
    "BT", "BV", "BW", "BY", "BZ", "CA", "CC", "CD", "CF", "CG", "CH", "CI", "CK", "CL", "CM", "CN",
    "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM", "DO", "DZ", "EC", "EE",
    "EG", "EH", "ER", "ES", "ET", "FI", "FJ", "FK", "FM", "FO", "FR", "GA", "GB", "GD", "GE", "GF",
    "GG", "GH", "GI", "GL", "GM", "GN", "GP", "GQ", "GR", "GS", "GT", "GU", "GW", "GY", "HK", "HM",
    "HN", "HR", "HT", "HU", "ID", "IE", "IL", "IM", "IN", "IO", "IQ", "IR", "IS", "IT", "JE", "JM",
    "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN", "KP", "KR", "KW", "KY", "KZ", "LA", "LB", "LC",
    "LI", "LK", "LR", "LS", "LT", "LU", "LV", "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH", "MK",
    "ML", "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU", "MV", "MW", "MX", "MY", "MZ", "NA",
    "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP", "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG",
    "PH", "PK", "PL", "PM", "PN", "PR", "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW",
    "SA", "SB", "SC", "SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM", "SN", "SO", "SR", "SS",
    "ST", "SV", "SX", "SY", "SZ", "TC", "TD", "TF", "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO",
    "TR", "TT", "TV", "TW", "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE", "VG", "VI",
    "VN", "VU", "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW",
)

# Any ISO code is valid; country is stored upper case.
Country = Enum("Country", {c: c for c in ISO_3166_ALPHA2}, type=str)

# Common non-ISO spellings accepted on input and stored as the ISO code.
COUNTRY_CODE_ALIASES = {"UK": "GB", "USA": "US"}


def normalise_country(value) -> str:
    """Upper-case a country code and map UK/USA to GB/US; '' stays ''."""
    code = str(value.value if isinstance(value, Enum) else (value or "")).strip().upper()
    return COUNTRY_CODE_ALIASES.get(code, code)


class TaskStatus(str, Enum):
    OPEN = "open"
    DONE = "done"


# Outcome choices for an interaction when config.toml sets none: the first is
# what a detected reply counts as, the last what silence past the message
# window counts as; an empty outcome means "not yet known".
DEFAULT_OUTCOMES = ("successful", "unsuccessful")
# What message_status reports for callers that pass no outcomes list.
LEGACY_OUTCOMES = ("success", "unsuccessful")


# Language of outreach by HQ country; anything else is English. Belgium stays
# English on purpose: Dutch or French depends on the region, so check by hand.
LANGUAGE_BY_COUNTRY = {
    "DE": "de", "AT": "de", "CH": "de", "LI": "de",
    "NL": "nl",
    "FR": "fr", "LU": "fr", "MC": "fr",
}


def language_for(country: str) -> str:
    return LANGUAGE_BY_COUNTRY.get(normalise_country(country), "en")


class Role(str, Enum):
    CHAMPION = "champion"
    DECISION_MAKER = "decision-maker"
    INFLUENCER = "influencer"
    GATEKEEPER = "gatekeeper"


class Channel(str, Enum):
    EMAIL = "email"
    LINKEDIN = "linkedin"
    CALL = "call"
    MEETING = "meeting"


class Direction(str, Enum):
    OUT = "out"
    IN = "in"


class InteractionSource(str, Enum):
    MANUAL = "manual"
    BCC_IMPORT = "bcc-import"
    CALENDAR_IMPORT = "calendar-import"


OPEN_STAGES = ["offer", "discovery", "engaged", "prospect"]
# Old stage names still accepted as input (imports, CLI); files are migrated.
STAGE_ALIASES = {"reached-out": "engaged"}
# Early stages carry no monthly value in PIPELINE.md headings.
UNVALUED_STAGES = ["engaged", "prospect"]
CLOSED_STAGES = ["won", "lost", "disqualified"]
# Parked: out of the pipeline for now, but a next step (revisit) still shows up.
PARKED_STAGES = ["temp-disqualified"]
# Stages whose reason is kept in `lost_reason`.
REASON_STAGES = ["lost", "disqualified", "temp-disqualified"]


class ValidationError(Exception):
    """User-facing form/file errors. ``errors`` maps field name -> message."""

    def __init__(self, errors: dict[str, str] | str, message: str = ""):
        if isinstance(errors, str):
            errors = {errors: message or errors}
        self.errors: dict[str, str] = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


# ------------------------------------------------------------------ date helpers


def fmt_date(d: date | None) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    return f"{d:%Y-%m-%d}"


def fmt_datetime(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return f"{dt:%Y-%m-%dT%H:%M}"


def parse_date(s) -> date | None:
    if s is None or s == "":
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    s = str(s).strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError({"date": f"not a YYYY-MM-DD date: {s!r}"})


def parse_datetime(s) -> datetime | None:
    """Accepts ``YYYY-MM-DDTHH:MM``, ``YYYY-MM-DD HH:MM``, optional seconds,
    and a bare ``YYYY-MM-DD`` (midnight). Naive local time, no timezone."""
    if s is None or s == "":
        return None
    if isinstance(s, datetime):
        return s.replace(second=0, microsecond=0, tzinfo=None)
    if isinstance(s, date):
        return datetime(s.year, s.month, s.day)
    s = str(s).strip()
    if not s:
        return None
    txt = s.replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt, fmt).replace(second=0, microsecond=0)
        except ValueError:
            continue
    raise ValidationError({"date": f"not a YYYY-MM-DDTHH:MM datetime: {s!r}"})


# ------------------------------------------------------------------ normalisers


_WEB_URL = re.compile(r"^https?://", re.IGNORECASE)
_OTHER_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def normalise_website(s: str | None) -> str:
    """An http(s) URL, whatever was typed: `example.com` gets https://.

    Any other scheme is dropped (`ftp://x` becomes `https://x`), so a stored
    link can never be `javascript:` or `data:`. A bare `javascript:alert(1)`
    becomes `https://javascript:alert(1)`: nonsense, but inert.
    """
    s = (s or "").strip()
    if not s:
        return ""
    if not _WEB_URL.match(s):
        s = "https://" + _OTHER_SCHEME.sub("", s)
    return s


def normalise_linkedin(value: str | None) -> str:
    """A LinkedIn URL as https://www.linkedin.com/..., without a trailing slash."""
    value = (value or "").strip()
    if not value:
        return ""
    if not _WEB_URL.match(value):
        value = "https://" + _OTHER_SCHEME.sub("", value).removeprefix("www.")
    value = re.sub(r"^https?://(www\.)?linkedin\.com", "https://www.linkedin.com", value,
                   flags=re.IGNORECASE)
    return value.rstrip("/")


def safe_href(url) -> str:
    """The URL if it is http(s), else "": the last check before a value becomes a link.

    Files are edited by hand and by other tools, so a stored website or LinkedIn
    field is not trusted to have gone through the normalisers above.
    """
    url = str(url or "").strip()
    if _WEB_URL.match(url) and not any(ord(ch) < 32 for ch in url):
        return url
    return ""


def normalise_email(s: str | None) -> str:
    return (s or "").strip().lower()


def parse_tags(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple)):
        parts = [str(p) for p in value]
    else:
        raise ValidationError({"tags": f"cannot read tags from {value!r}"})
    return [p.strip() for p in parts if p.strip()]


# ----------------------------------------------------------------------- slugs

TRANSLITERATE = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "á": "a", "à": "a", "â": "a", "ã": "a", "å": "aa",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ó": "o", "ò": "o", "ô": "o", "õ": "o", "ø": "oe",
    "ú": "u", "ù": "u", "û": "u",
    "ç": "c", "ñ": "n", "ý": "y",
    "æ": "ae", "œ": "oe",
}

LEGAL_SUFFIXES = {
    "gmbh", "ag", "se", "bv", "b.v.", "ltd", "inc", "sas", "sarl", "kg", "ug", "co",
}


def slugify(text: str, strip_legal: bool = False, default: str = "company") -> str:
    s = (text or "").strip().lower()
    s = "".join(TRANSLITERATE.get(ch, ch) for ch in s)
    if strip_legal:
        # tokens are separated by whitespace; "b.v." keeps its dots at this point
        tokens = [t for t in re.split(r"\s+", s) if t]
        kept = [t for t in tokens
                if t not in LEGAL_SUFFIXES and t.strip(".,") not in LEGAL_SUFFIXES]
        s = " ".join(kept) if kept else ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    s = s[:60].strip("-")
    return s or default


def unique_slug(base: str, existing: Iterable[str]) -> str:
    taken = set(existing)
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


# ------------------------------------------------------------------ dataclasses


@dataclass
class Contact:
    first_name: str
    last_name: str
    slug: str
    title: str = ""
    linkedin: str = ""
    email: str = ""
    phone: str = ""
    role: str = ""
    tasks: list["Task"] = field(default_factory=list)
    created: datetime | None = None
    updated: datetime | None = None
    notes: str = ""
    extra: dict = field(default_factory=dict)  # unknown front-matter keys, round-tripped

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


def split_name(full: str) -> tuple[str, str]:
    """'Jane van Doe' -> ('Jane', 'van Doe'); a single word is a first name."""
    parts = (full or "").split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


@dataclass
class Interaction:
    id: str
    date: datetime | None = None
    channel: str = ""
    direction: str = ""
    contact: str = ""
    subject: str = ""
    outcome: str = ""  # one of config outcomes, or "" (not yet known)
    source: str = "manual"
    message_id: str = ""  # dedup key of a BCC (Message-ID) or calendar (ical:…) import
    body: str = ""
    extra: dict = field(default_factory=dict)  # unknown front-matter keys, round-tripped

    @property
    def is_message(self) -> bool:
        """An outbound interaction with a body is a message you sent (a meeting is not)."""
        return (self.direction == Direction.OUT.value and bool(self.body.strip())
                and self.channel != Channel.MEETING.value)

    def base_id(self) -> str:
        return (
            f"{self.date:%Y-%m-%dT%H%M}-{self.channel}-{self.direction}-"
            f"{self.contact or 'company'}"
        )

    @property
    def contact_label(self) -> str:
        return self.contact or "company"


@dataclass
class Task:
    """One thing you owe an account or a person.

    The company's `next_step` is the single task that decides where the deal
    stands; these are everything else. Keeping them apart is deliberate: the
    pipeline stays one line per company, and a to-do list does not quietly
    become a second pipeline.
    """

    text: str
    due: date | None = None
    done: bool = False

    def overdue(self, today: date | None = None) -> bool:
        return bool(self.due and not self.done and self.due < (today or date.today()))


@dataclass
class StageChange:
    """One entry of a company's append-only stage history. `from_stage` is
    empty for the entry that records the stage a company was created in."""
    date: date
    from_stage: str
    to_stage: str
    reason: str = ""


@dataclass
class Company:
    name: str
    slug: str
    website: str = ""
    linkedin: str = ""
    country: str = ""
    source: str = "other"
    stage: str = "prospect"
    stage_changed: date | None = None
    lost_reason: str = ""
    requalify_on: date | None = None  # temp-disqualified until this date
    value_eur_month: int | None = None
    product_oneliner: str = ""
    next_step: str = ""
    next_step_due: date | None = None
    next_step_status: str = "open"
    tags: list[str] = field(default_factory=list)
    stage_history: list[StageChange] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    created: datetime | None = None
    updated: datetime | None = None
    notes: str = ""
    contacts: dict[str, Contact] = field(default_factory=dict)
    interactions: list[Interaction] = field(default_factory=list)
    extra: dict = field(default_factory=dict)  # unknown front-matter keys, round-tripped

    # --- derived, never written to file
    @property
    def last_touch(self) -> datetime | None:
        dates = [i.date for i in self.interactions if i.date]
        return max(dates) if dates else None

    @property
    def last_touch_summary(self) -> str:
        if not self.interactions:
            return "none"
        it = max(
            (i for i in self.interactions if i.date),
            key=lambda i: i.date,
            default=None,
        )
        if it is None:
            return "none"
        return (
            f"{it.channel} {it.direction} {fmt_date(it.date)} ({it.contact_label})"
        )

    @property
    def interaction_count(self) -> int:
        return len(self.interactions)

    def days_in_stage(self, today: date | None = None) -> int:
        if self.stage_changed is None:
            return 0
        return ((today or date.today()) - self.stage_changed).days

    def stage_entries(self) -> list[StageChange]:
        """The history oldest first, with the start filled in when it is not
        recorded: an implicit `"" -> <first from_stage>` entry dated `created`.
        Without any history (files written before it existed and not yet
        backfilled) that is `"" -> prospect` at `created`, plus
        `prospect -> <stage>` at `stage_changed` when the stage moved on."""
        entries = sorted(self.stage_history, key=lambda e: e.date)
        if not entries:
            if self.created:
                entries.append(StageChange(self.created.date(), "", "prospect"))
            if self.stage != "prospect" and self.stage_changed:
                entries.append(StageChange(self.stage_changed,
                                           "prospect" if entries else "", self.stage))
            return entries
        if entries[0].from_stage and self.created:
            entries.insert(0, StageChange(min(self.created.date(), entries[0].date), "",
                                          entries[0].from_stage))
        return entries

    @property
    def closed_on(self) -> date | None:
        """Date of the last transition into a closed stage, if any."""
        dates = [e.date for e in self.stage_history if e.to_stage in CLOSED_STAGES]
        return max(dates) if dates else None

    def entered_stage_on(self, stage: str) -> date | None:
        """Date this company last entered `stage` (implicit start included)."""
        dates = [e.date for e in self.stage_entries() if e.to_stage == stage]
        return max(dates) if dates else None

    def stage_durations(self, today: date | None = None) -> dict[str, int]:
        """Days spent per stage visited up to `today`, repeat visits summed.
        The current stage runs until today; entries after today are ignored.
        Without any history this is just the current stage and days in stage."""
        today = today or date.today()
        entries = [e for e in self.stage_entries() if e.date <= today]
        if not entries:
            return {self.stage: self.days_in_stage(today)} if self.stage_changed else {}
        durations: dict[str, int] = {}
        for cur, nxt in zip(entries, entries[1:] + [None]):
            end = nxt.date if nxt else today
            durations[cur.to_stage] = durations.get(cur.to_stage, 0) + (end - cur.date).days
        return durations

    @property
    def has_next_step(self) -> bool:
        return bool(self.next_step) or self.next_step_due is not None

    @property
    def next_step_done(self) -> bool:
        return self.has_next_step and self.next_step_status == TaskStatus.DONE.value

    @property
    def next_step_open(self) -> bool:
        return self.has_next_step and not self.next_step_done

    def next_step_overdue(self, today: date | None = None) -> bool:
        if self.next_step_due is None or self.next_step_done:
            return False
        return self.next_step_due < (today or date.today())

    def silent_days(self, today: date | None = None) -> int:
        today = today or date.today()
        ref = self.last_touch
        ref_date = ref.date() if ref else (self.created.date() if self.created else today)
        return (today - ref_date).days

    @property
    def is_closed(self) -> bool:
        return self.stage in CLOSED_STAGES

    @property
    def is_parked(self) -> bool:
        return self.stage in PARKED_STAGES

    @property
    def is_active(self) -> bool:
        """In the pipeline: neither closed nor parked."""
        return not self.is_closed and not self.is_parked

    def requalify_due(self, today: date | None = None) -> bool:
        """Parked with a requalify date that has arrived."""
        return (self.is_parked and self.requalify_on is not None
                and self.requalify_on <= (today or date.today()))

    @property
    def language(self) -> str:
        return language_for(self.country)

    def message_status(self, it: Interaction, today: date | None = None,
                       window_days: int = 14, outcomes=None) -> str:
        """The outcome of one outbound message, or "unknown".

        An explicit `it.outcome` wins; otherwise a later inbound interaction
        from the same contact (or a company-level one) counts as `outcomes[0]`;
        otherwise a message older than `window_days` counts as `outcomes[-1]`;
        otherwise "unknown". `outcomes` is the config's `outcomes` list; a
        caller that passes none gets the legacy success/unsuccessful names."""
        if it.outcome:
            return it.outcome
        positive, negative = (outcomes or LEGACY_OUTCOMES)[0], (outcomes or LEGACY_OUTCOMES)[-1]
        if it.date:
            for other in self.interactions:
                if (other.direction == Direction.IN.value and other.date
                        and other.date > it.date
                        and (other.contact == it.contact or not other.contact)):
                    return positive
            age = (today or date.today()) - it.date.date()
            if age.days >= window_days:
                return negative
        return "unknown"

    @property
    def website_url(self) -> str:
        return self.website

    def contact_last_touch(self, cslug: str) -> datetime | None:
        dates = [i.date for i in self.interactions if i.date and i.contact == cslug]
        return max(dates) if dates else None

    @property
    def latest_contact_slug(self) -> str:
        for it in sorted(
            (i for i in self.interactions if i.date),
            key=lambda i: i.date,
            reverse=True,
        ):
            if it.contact:
                return it.contact
        return ""


# ------------------------------------------------------------- YAML front matter


def _scalar(value: str) -> str:
    """Emit a string as a single-line YAML scalar, quoted only when needed."""
    if "\n" in value or "\r" in value:
        dumped = yaml.safe_dump(
            value, allow_unicode=True, default_style='"', width=10**9
        )
    else:
        dumped = yaml.safe_dump(
            value, allow_unicode=True, default_flow_style=True, width=10**9
        )
    if dumped.endswith("\n...\n"):
        dumped = dumped[:-5]
    return dumped.rstrip("\n")


_PLAIN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
# Words YAML 1.1 reads as a boolean or null, not as the key they spell.
_YAML_WORDS = {"y", "n", "yes", "no", "on", "off", "true", "false", "null"}


def _flow(value) -> str:
    """Any YAML-safe value (nested lists, maps, numbers) as one flow-style line."""
    dumped = yaml.safe_dump(value, default_flow_style=True, sort_keys=False,
                            allow_unicode=True, width=10**9)
    if dumped.endswith("\n...\n"):
        dumped = dumped[:-5]
    return dumped.strip()


def dump_frontmatter(meta: dict) -> str:
    """Front matter lines, in the order of `meta`.

    The fields Hermit CRM knows keep their hand-editable layout. Anything else
    (a key another tool or the user added) must read back as the same value, so
    what does not fit the simple forms is written as YAML flow style. The one
    exception is "": it is written as an empty value, as for every known field,
    and reads back as null.
    """
    lines = []
    for key, value in meta.items():
        if (not isinstance(key, str) or not _PLAIN_KEY.match(key)
                or key.lower() in _YAML_WORDS):
            # `weird key: yes` unquoted would make the whole file unreadable.
            key = _flow(key) if not isinstance(key, str) else _scalar(key)
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            # A list of maps (stage_history): one flow mapping per line.
            lines.append(f"{key}:")
            for item in value:
                dumped = yaml.safe_dump(item, default_flow_style=True, sort_keys=False,
                                        allow_unicode=True, width=10**9)
                lines.append(f"  - {dumped.strip()}")
            continue
        if isinstance(value, dict):
            dumped = yaml.safe_dump(value, default_flow_style=True, sort_keys=True,
                                    allow_unicode=True, width=10**9)
            lines.append(f"{key}: {dumped.strip()}")
            continue
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            elif all(isinstance(v, str) for v in value):
                lines.append(f"{key}: [{', '.join(_scalar(v) for v in value)}]")
            else:  # numbers, booleans, nested lists: str() would lose them
                lines.append(f"{key}: {_flow(value)}")
            continue
        if value is None or value == "":
            lines.append(f"{key}:")
            continue
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key}: {value}")
        elif isinstance(value, float):
            lines.append(f"{key}: {_flow(value)}")  # 1e+20 and inf need YAML's spelling
        elif isinstance(value, datetime):
            lines.append(f"{key}: {fmt_datetime(value)}")
        elif isinstance(value, date):
            lines.append(f"{key}: {fmt_date(value)}")
        else:
            lines.append(f"{key}: {_scalar(str(value))}")
    return "".join(line + "\n" for line in lines)


def task_to_dict(t: Task) -> dict:
    item: dict = {"text": t.text}
    if t.due:
        item["due"] = t.due
    if t.done:
        item["done"] = True
    return item


def _tasks(value, errors: dict[str, str]) -> list[Task]:
    if value in (None, "", []):
        return []
    if not isinstance(value, list):
        errors["tasks"] = "tasks must be a list"
        return []
    out = []
    for n, item in enumerate(value, 1):
        if not isinstance(item, dict):
            errors["tasks"] = f"task {n} is not a mapping"
            return []
        text = " ".join(str(item.get("text") or "").split())
        if not text:
            errors["tasks"] = f"task {n} has no text"
            return []
        try:
            due = parse_date(item.get("due")) if item.get("due") else None
        except ValidationError:
            errors["tasks"] = f"task {n} has an unreadable due date"
            return []
        out.append(Task(text=text, due=due, done=bool(item.get("done"))))
    return out


def stage_change_to_dict(e: StageChange) -> dict:
    item = {"date": e.date, "from": e.from_stage, "to": e.to_stage}
    if e.reason:
        item["reason"] = e.reason
    return item


def company_to_frontmatter(c: Company) -> dict:
    meta = {
        "name": c.name,
        "slug": c.slug,
        "website": c.website,
        "linkedin": c.linkedin,
        "country": c.country,
        "source": c.source,
        "stage": c.stage,
        "stage_changed": c.stage_changed,
        "lost_reason": c.lost_reason,
        "requalify_on": c.requalify_on,
        "value_eur_month": c.value_eur_month,
        "product_oneliner": c.product_oneliner,
        "next_step": c.next_step,
        "next_step_due": c.next_step_due,
        "next_step_status": c.next_step_status,
        "tags": list(c.tags),
    }
    if c.stage_history:  # absent until the first recorded change
        meta["stage_history"] = [stage_change_to_dict(e) for e in c.stage_history]
    if c.tasks:          # absent until there is one
        meta["tasks"] = [task_to_dict(t) for t in c.tasks]
    meta["created"] = c.created
    meta["updated"] = c.updated
    return _with_extra(meta, c.extra, COMPANY_KEYS)


def _with_extra(meta: dict, extra: dict, known: frozenset) -> dict:
    """Append unknown keys after the known ones, sorted, so output is deterministic."""
    for key in sorted(extra or {}, key=str):
        if key not in known:
            meta[key] = extra[key]
    return meta


def _extra(meta: dict, known: frozenset) -> dict:
    return {k: v for k, v in meta.items() if k not in known}


def contact_to_frontmatter(c: Contact) -> dict:
    meta = {
        "first_name": c.first_name,
        "last_name": c.last_name,
        "slug": c.slug,
        "title": c.title,
        "linkedin": c.linkedin,
        "email": c.email,
        "phone": c.phone,
        "role": c.role,
    }
    if c.tasks:      # absent until there is one
        meta["tasks"] = [task_to_dict(t) for t in c.tasks]
    meta["created"] = c.created
    meta["updated"] = c.updated
    return _with_extra(meta, c.extra, CONTACT_KEYS)


def interaction_to_frontmatter(i: Interaction) -> dict:
    meta = {
        "date": i.date,
        "channel": i.channel,
        "direction": i.direction,
        "contact": i.contact,
        "subject": i.subject,
        "outcome": i.outcome,
        "source": i.source,
    }
    if i.message_id:  # only BCC imports carry one
        meta["message_id"] = i.message_id
    return _with_extra(meta, i.extra, INTERACTION_KEYS)


# Every key the app reads or writes; anything else is kept in `extra`.
COMPANY_KEYS = frozenset({
    "name", "slug", "website", "linkedin", "country", "source", "stage", "stage_changed",
    "lost_reason", "requalify_on", "value_eur_month", "product_oneliner",
    "next_step", "next_step_due",
    "next_step_status", "tags", "stage_history", "tasks", "created", "updated",
})
CONTACT_KEYS = frozenset({
    "first_name", "last_name", "name", "slug", "title", "linkedin", "email", "phone",
    "role", "tasks", "created", "updated",
})
INTERACTION_KEYS = frozenset({
    "date", "channel", "direction", "contact", "subject", "outcome", "source",
    "message_id",
})


# ------------------------------------------------------------------ from-dict


def _str(meta: dict, key: str) -> str:
    value = meta.get(key)
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return fmt_date(value) if not isinstance(value, datetime) else fmt_datetime(value)
    return str(value)


def _enum(value: str, enum: type[Enum], field_name: str, allow_empty: bool,
          errors: dict[str, str], default: str = "") -> str:
    value = (value or "").strip()
    if not value:
        if allow_empty:
            return default
        errors[field_name] = f"{field_name} is required"
        return default
    allowed = [e.value for e in enum]
    if value not in allowed:
        errors[field_name] = f"unknown {field_name} {value!r} (allowed: {', '.join(allowed)})"
        return default
    return value


def _int_or_none(value, field_name: str, errors: dict[str, str]) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        errors[field_name] = f"{field_name} must be a whole number, got {value!r}"
        return None


def _date_or_none(value, field_name: str, errors: dict[str, str]) -> date | None:
    try:
        return parse_date(value)
    except ValidationError:
        errors[field_name] = f"{field_name} must be YYYY-MM-DD, got {value!r}"
        return None


def _datetime_or_none(value, field_name: str, errors: dict[str, str]) -> datetime | None:
    try:
        return parse_datetime(value)
    except ValidationError:
        errors[field_name] = f"{field_name} must be YYYY-MM-DDTHH:MM, got {value!r}"
        return None


def _stage_history(value, errors: dict[str, str]) -> list[StageChange]:
    if value in (None, "", []):
        return []
    if not isinstance(value, list):
        errors["stage_history"] = "stage_history must be a list"
        return []
    allowed = [s.value for s in Stage]
    history = []
    for n, item in enumerate(value, 1):
        if not isinstance(item, dict):
            errors["stage_history"] = f"stage_history entry {n} is not a mapping"
            return []
        try:
            when = parse_date(item.get("date"))
        except ValidationError:
            when = None
        from_stage = str(item.get("from") or "").strip()
        to_stage = str(item.get("to") or "").strip()
        if when is None or to_stage not in allowed or (from_stage and from_stage not in allowed):
            errors["stage_history"] = (f"stage_history entry {n} needs a date and "
                                       f"known from/to stages")
            return []
        history.append(StageChange(when, from_stage, to_stage,
                                   str(item.get("reason") or "").strip()))
    return history


def company_from_dict(meta: dict, body: str, slug: str) -> Company:
    errors: dict[str, str] = {}
    if not isinstance(meta, dict):
        raise ValidationError({"file": "front matter is not a mapping"})
    name = _str(meta, "name").strip()
    if not name:
        errors["name"] = "name is required"
    country = _enum(normalise_country(_str(meta, "country")), Country, "country", True, errors)
    source = _enum(_str(meta, "source"), Source, "source", True, errors, "other")
    stage = _enum(_str(meta, "stage"), Stage, "stage", True, errors, "prospect")
    lost_reason = _str(meta, "lost_reason").strip()
    if stage == Stage.LOST.value and not lost_reason:
        errors["lost_reason"] = "lost_reason is required when stage is lost"
    c = Company(
        name=name,
        slug=slug,
        website=_str(meta, "website").strip(),
        linkedin=_str(meta, "linkedin").strip(),
        country=country,
        source=source,
        stage=stage,
        stage_changed=_date_or_none(meta.get("stage_changed"), "stage_changed", errors),
        lost_reason=lost_reason,
        requalify_on=_date_or_none(meta.get("requalify_on"), "requalify_on", errors),
        value_eur_month=_int_or_none(meta.get("value_eur_month"), "value_eur_month", errors),
        product_oneliner=_str(meta, "product_oneliner").strip(),
        next_step=_str(meta, "next_step").strip(),
        next_step_due=_date_or_none(meta.get("next_step_due"), "next_step_due", errors),
        next_step_status=_enum(_str(meta, "next_step_status"), TaskStatus,
                               "next_step_status", True, errors, "open"),
        tags=parse_tags(meta.get("tags")),
        stage_history=_stage_history(meta.get("stage_history"), errors),
        tasks=_tasks(meta.get("tasks"), errors),
        created=_datetime_or_none(meta.get("created"), "created", errors),
        updated=_datetime_or_none(meta.get("updated"), "updated", errors),
        notes=body,
        extra=_extra(meta, COMPANY_KEYS),
    )
    if errors:
        raise ValidationError(errors)
    return c


def contact_from_dict(meta: dict, body: str, slug: str) -> Contact:
    errors: dict[str, str] = {}
    if not isinstance(meta, dict):
        raise ValidationError({"file": "front matter is not a mapping"})
    first_name = _str(meta, "first_name").strip()
    last_name = _str(meta, "last_name").strip()
    if not first_name and not last_name:
        # Files written before the split carry a single name key.
        first_name, last_name = split_name(_str(meta, "name"))
    if not first_name and not last_name:
        errors["first_name"] = "first name is required"
    c = Contact(
        first_name=first_name,
        last_name=last_name,
        slug=slug,
        title=_str(meta, "title").strip(),
        linkedin=_str(meta, "linkedin").strip(),
        email=normalise_email(_str(meta, "email")),
        phone=_str(meta, "phone").strip(),
        role=_enum(_str(meta, "role"), Role, "role", True, errors, ""),
        tasks=_tasks(meta.get("tasks"), errors),
        created=_datetime_or_none(meta.get("created"), "created", errors),
        updated=_datetime_or_none(meta.get("updated"), "updated", errors),
        notes=body,
        extra=_extra(meta, CONTACT_KEYS),
    )
    if errors:
        raise ValidationError(errors)
    return c


def interaction_from_dict(meta: dict, body: str, id: str) -> Interaction:
    errors: dict[str, str] = {}
    if not isinstance(meta, dict):
        raise ValidationError({"file": "front matter is not a mapping"})
    when = _datetime_or_none(meta.get("date"), "date", errors)
    if when is None and "date" not in errors:
        errors["date"] = "date is required"
    i = Interaction(
        id=id,
        date=when,
        channel=_enum(_str(meta, "channel"), Channel, "channel", False, errors),
        direction=_enum(_str(meta, "direction"), Direction, "direction", False, errors),
        contact=_str(meta, "contact").strip(),
        subject=_str(meta, "subject").strip(),
        outcome=_str(meta, "outcome").strip(),
        source=_enum(_str(meta, "source"), InteractionSource, "source", True, errors,
                     "manual"),
        message_id=_str(meta, "message_id").strip(),
        body=body,
        extra=_extra(meta, INTERACTION_KEYS),
    )
    if errors:
        raise ValidationError(errors)
    return i
