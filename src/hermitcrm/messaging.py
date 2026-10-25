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

"""The wording the outreach bot works from, kept in TOML rather than code: the
languages (names, culture norms, the reply and follow-up templates) and the
signal labels the pages show.

The package ships ``hermitcrm/default_messages.toml``; a ``messages.toml`` in
the data folder is deep-merged over it, so you only override what you want to
change. Draft language comes from the contact, else the company's country
(Belgium by its evidence).

Slots: {first} {company} {growth} {size} {hurdle} {team} {observation} {fte}
{ae} {site}, plus {owner_first_name} (from ``owner_name`` in config.toml), plus
one slot per field the folder defined itself, named by its key. ``field_slots``
and the ``messaging_size_field`` / ``messaging_team_field`` settings are what
is left of the retired no-AI template drafts.
"""

from __future__ import annotations

import copy
import re
import tomllib
from functools import lru_cache
from importlib import resources
from pathlib import Path

from .models import Company, Contact, language_for, normalise_country, normalise_language

SIGNALS = ["", "growing", "stalled", "declining", "hiring"]
# Slot names the templates already use. A field of your own cannot take one of
# these, or a field keyed `company` would quietly replace the company's name.
RESERVED_SLOTS = frozenset({
    "first", "company", "growth", "size", "hurdle", "team", "observation",
    "fte", "ae", "site", "owner_first_name",
})
# The two roles the shipped playbook understands, named by the keys a folder
# migrated from an older Hermit CRM already has. A folder without those fields
# simply has neither, and the size and team lines use their "unknown" wording.
DEFAULT_SIZE_FIELD = "fte_estimate"
DEFAULT_TEAM_FIELD = "ae_count"
# Signals with their own `growth` sentence; the others use the "" one.
GROWTH_SIGNALS = ("growing", "stalled", "declining")
HURDLES = [10, 20, 50, 100, 250, 500]
MESSAGES_FILE = "messages.toml"


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
    return resources.files("hermitcrm").joinpath("default_messages.toml").read_text(
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


class MessagesShapeError(ValueError):
    """messages.toml replaced `languages` with something that is not a table of
    languages; every draft would fail on it."""


def load_messages(data_dir: Path | str | None = None) -> dict:
    """The shipped defaults with ``<data>/messages.toml`` merged over them."""
    messages = default_messages()
    if data_dir is not None:
        path = Path(data_dir) / MESSAGES_FILE
        if path.exists():
            with open(path, "rb") as fh:
                messages = deep_merge(messages, tomllib.load(fh))
            languages = messages.get("languages")
            if not isinstance(languages, dict) or not all(
                    isinstance(v, dict) for v in languages.values()):
                raise MessagesShapeError("must be a table of languages, each a table "
                                         "of wording, as in the shipped messages")
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


# Belgium has no single business language, so the country code alone is not
# enough: the draft language comes from what the record says.
_NL_WORDS = frozenset("""het een van voor met niet zijn wij onze jullie bij ook maar dat
    dit naar uw graag bedankt dank groeten hallo beste vriendelijke hebben wordt
    kunnen zaakvoerder zaakvoerster bestuurder oprichter medeoprichter verkoop
    klanten oplossingen bedrijf""".split())
_FR_WORDS = frozenset("""le la les des une et pour avec pas sont nous notre vous votre
    chez aussi mais que ce cette merci bonjour cordialement salutations avoir est
    pouvons gérant gérante administrateur fondateur cofondateur directeur commercial
    ventes clients solutions entreprise""".split())
# Weights: what they wrote to you beats what you wrote beats their website and
# address beats the language of free text (titles, notes, product line).
_W_INBOUND, _W_OUTBOUND, _W_SITE, _W_POSTCODE, _W_TEXT = 4, 3, 2, 2, 1
_LOCATION_KEYS = ("postcode", "postal_code", "zip", "city", "address", "location", "hq")


def text_language(text: str) -> str:
    """"nl", "fr" or "" from function words; "" when neither clearly dominates."""
    words = [w.strip(".,;:!?()\"'«»“”") for w in (text or "").lower().split()]
    nl = sum(w in _NL_WORDS for w in words)
    fr = sum(w in _FR_WORDS for w in words)
    if max(nl, fr) < 3 or nl == fr or min(nl, fr) * 2 > max(nl, fr):
        return ""
    return "nl" if nl > fr else "fr"


def belgian_postcode_language(text: str) -> str:
    """Language region of the first Belgian postcode in text; Brussels (1000-1299)
    is bilingual and gives ""."""
    for match in re.finditer(r"(?<![\d-])(?:B-?\s?)?([1-9]\d{3})\s+[A-ZÀ-Ý]", text or ""):
        code = int(match.group(1))
        if 1000 <= code <= 1299:
            continue
        if 1300 <= code <= 1499 or 4000 <= code <= 7999:
            return "fr"   # Walloon Brabant, Liège, Namur, Hainaut, Luxembourg
        return "nl"       # Flemish Brabant, Antwerp, Limburg, West and East Flanders
    return ""


def _site_language(url: str) -> str:
    url = (url or "").lower()
    host_path = url.split("://", 1)[-1]
    host, _, path = host_path.partition("/")
    first = path.split("/", 1)[0].split("?", 1)[0]
    for lang in ("nl", "fr"):
        if host.startswith(f"{lang}.") or first in (lang, f"{lang}-be", f"be-{lang}",
                                                    f"{lang}_be"):
            return lang
    return ""


def belgian_language_scores(company: Company) -> dict[str, list[str]]:
    """The evidence per language: {"nl": [reasons], "fr": [reasons]}, weighted by
    repetition (a reason appears once per weight point)."""
    evidence: dict[str, list[str]] = {"nl": [], "fr": []}

    def add(lang: str, weight: int, reason: str) -> None:
        if lang in evidence:
            evidence[lang] += [reason] * weight

    for it in company.interactions:
        if it.is_note:  # your own memo, not a message in their language
            continue
        lang = text_language(f"{it.subject}\n{it.body}")
        if lang:
            inbound = it.direction == "in"
            add(lang, _W_INBOUND if inbound else _W_OUTBOUND,
                f"{'their' if inbound else 'your'} {it.channel or 'message'} of "
                f"{it.date:%Y-%m-%d}" if it.date else "a message")
    for url in [company.website] + [c.linkedin for c in company.contacts.values()]:
        lang = _site_language(url)
        if lang:
            add(lang, _W_SITE, f"{url}")
    places = [str(company.extra.get(k) or "") for k in _LOCATION_KEYS] + [company.notes]
    lang = belgian_postcode_language(" ".join(places))
    if lang:
        add(lang, _W_POSTCODE, "postcode")
    free_text = " ".join([company.product_oneliner, company.notes]
                         + [f"{c.title} {c.notes}" for c in company.contacts.values()])
    lang = text_language(free_text)
    if lang:
        add(lang, _W_TEXT, "language of the record's text")
    return evidence


def belgian_language(company: Company) -> str:
    """Draft language for a Belgian company: "nl" (Flanders), "fr" (Wallonia) or "en".

    Evidence, strongest first: previous correspondence (their messages, then
    yours), a /nl/ or /fr/ website, a postcode outside Brussels, then the
    language of titles and notes. The heavier side wins when it has at least
    twice the weight of the other (so one reply from them beats a website path); otherwise, or with no evidence, "en". A
    LinkedIn profile's language is not read: that needs fetching the profile.
    """
    evidence = belgian_language_scores(company)
    nl, fr = len(evidence["nl"]), len(evidence["fr"])
    if max(nl, fr) == 0 or min(nl, fr) * 2 > max(nl, fr):
        return "en"
    return "nl" if nl > fr else "fr"


def field_slots(company: Company, defs: list | None) -> dict:
    """One slot per field of your own: `{segment}`, `{fit_score}`, and so on.

    An empty field renders as its label in square brackets, the same mark the
    templates already use for "only you can fill this in", so a draft written
    against a field you have not filled says so instead of going blank.
    """
    slots = {}
    for d in (defs or []):
        if d.applies_to != "company" or not d.messaging or d.key in RESERVED_SLOTS:
            continue
        shown = d.display((company.extra or {}).get(d.key))
        slots[d.key] = shown if shown else f"[{d.label}]"
    return slots


def draft_language(company: Company, contact: Contact | None = None,
                   override: str = "", messages: dict | None = None) -> str:
    """The language drafts are written in, first match wins: the page's own
    choice (`override`), the contact's language, then the company's country
    (Belgium by its evidence). A code without templates is skipped, so a
    hand-typed "sv" falls through until messages.toml has a [languages.sv]."""
    languages = (messages if messages is not None else default_messages())["languages"]
    for code in (override, contact.language if contact else ""):
        code = normalise_language(code)
        if code in languages:
            return code
    lang = (belgian_language(company) if normalise_country(company.country) == "BE"
            else language_for(company.country))
    return lang if lang in languages else "en"
