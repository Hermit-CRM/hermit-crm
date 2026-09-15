"""Outreach drafts without AI: three distinct angles per contact, written in
the language of the company's country, from what the CRM already knows plus
two things you check by hand on LinkedIn insights and the website.

The wording lives in TOML, not in code. The package ships
``owncrm/default_messages.toml`` with neutral B2B angles; a ``messages.toml``
in the data folder is deep-merged over it, so you only override what you
want to change. The three angles:

1. scale   they are growing (or levelling off): offer help to keep the pace
2. unblock "you are at N people": get past the next headcount hurdle
3. hook    one concrete observation about their product, then an open question

A ``hiring`` signal swaps angle 1 for ``bridge`` (help while the role is open).
Square brackets mark what only you can fill in.

Slots: {first} {company} {growth} {size} {hurdle} {team} {observation} {fte}
{ae} {site}, plus {owner_first_name} (from ``owner_name`` in config.toml).
The ``size`` and ``team`` tables have ``known`` / ``unknown`` variants.
"""

from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path

from .models import Company, Contact, language_for, normalise_country

SIGNALS = ["", "growing", "stalled", "hiring"]
HURDLES = [10, 20, 50, 100, 250, 500]
MESSAGES_FILE = "messages.toml"
DRAFT_KEYS = ("scale", "bridge", "unblock", "hook")


@dataclass
class Draft:
    key: str      # scale | bridge | unblock | hook
    label: str
    language: str
    body: str


def fte_number(fte_estimate: str) -> int | None:
    digits = "".join(ch for ch in (fte_estimate or "") if ch.isdigit() or ch == "-")
    first = digits.split("-")[0]
    return int(first) if first.isdigit() else None


def next_hurdle(fte_estimate: str) -> int | None:
    n = fte_number(fte_estimate)
    if n is None:
        return None
    return next((h for h in HURDLES if h > n), None)


# -------------------------------------------------------------- templates


@lru_cache(maxsize=1)
def _default_text() -> str:
    return resources.files("owncrm").joinpath("default_messages.toml").read_text(
        encoding="utf-8")


def default_messages() -> dict:
    return tomllib.loads(_default_text())


def deep_merge(base: dict, override: dict) -> dict:
    """A new dict: override's tables merged key by key into base's."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_messages(data_dir: Path | str | None = None) -> dict:
    """The shipped defaults with ``<data>/messages.toml`` merged over them."""
    messages = default_messages()
    if data_dir is not None:
        path = Path(data_dir) / MESSAGES_FILE
        if path.exists():
            with open(path, "rb") as fh:
                messages = deep_merge(messages, tomllib.load(fh))
    return messages


def language_names(messages: dict | None = None) -> dict[str, str]:
    messages = messages if messages is not None else default_messages()
    return {code: str(t.get("name", code)) for code, t in messages["languages"].items()}


def signal_labels(messages: dict | None = None) -> dict[str, str]:
    messages = messages if messages is not None else default_messages()
    return {s: str(messages.get("signals", {}).get(s, s)) for s in SIGNALS}


LANGUAGE_NAMES = language_names()
SIGNAL_LABELS = signal_labels()


def owner_first_name(owner_name: str) -> str:
    parts = (owner_name or "").split()
    return parts[0] if parts else "[your name]"


def belgian_language(company: Company) -> str:
    """Draft language for a Belgian company: "nl" (Flanders), "fr" (Wallonia) or "en".

    Belgium has no single business language, so the country code alone is not
    enough. Signals on the record: company.website (a /nl/ or /fr/ path, or
    nl./fr. subdomain), company.product_oneliner and company.notes (written in
    the company's own language when fetched from its site), and contact names.
    Return "en" whenever the signals disagree or are missing.
    """
    # TODO(human): infer Flemish vs Walloon from the record
    return "en"


def drafts(company: Company, contact: Contact | None = None, signal: str = "",
           observation: str = "", messages: dict | None = None,
           owner_name: str = "") -> list[Draft]:
    """Three distinct drafts for one contact (company-level when None)."""
    messages = messages if messages is not None else default_messages()
    languages = messages["languages"]
    lang = (belgian_language(company) if normalise_country(company.country) == "BE"
            else language_for(company.country))
    if lang not in languages:
        lang = "en"
    t = languages[lang]
    labels = messages.get("labels", {})
    signal = signal if signal in SIGNALS else ""
    fte = fte_number(company.fte_estimate)
    hurdle = next_hurdle(company.fte_estimate)
    site = (company.website or company.linkedin or "their site").replace(
        "https://", "").replace("http://", "").rstrip("/")
    first = (contact.first_name if contact else "") or "[first name]"
    observation = " ".join((observation or "").split())
    slots = {
        "first": first,
        "company": company.name,
        "fte": fte if fte is not None else "N",
        "hurdle": hurdle if hurdle is not None else "[N]",
        "ae": company.ae_count or 0,
        "site": site,
        "owner_first_name": owner_first_name(owner_name),
    }
    slots["growth"] = t["growth"][signal if signal in ("growing", "stalled") else ""].format_map(slots)
    slots["size"] = t["size"]["known" if fte is not None else "unknown"].format_map(slots)
    slots["team"] = t["team"]["known" if company.ae_count else "unknown"].format_map(slots)
    slots["observation"] = observation or t["observation"].format_map(slots)

    keys = ["bridge" if signal == "hiring" else "scale", "unblock", "hook"]
    out = []
    for key in keys:
        body = "\n".join([
            t["greeting"].format_map(slots),
            t[key].format_map(slots),
            "",
            t["signoff"].format_map(slots),
        ])
        out.append(Draft(key=key, label=str(labels.get(key, key)), language=lang,
                         body=body + "\n"))
    return out
