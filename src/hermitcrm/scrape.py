"""Free enrichment: read a company's website or LinkedIn page and propose
fields from what the page itself says. Standard library only, no AI, no API
key. Like ``enrich.py`` it only proposes; a person applies.

What a page can give us:
- website  <title>, meta description / og:description  -> product_oneliner
           links to linkedin.com/company/...            -> linkedin
           JSON-LD Organization (sameAs, address, numberOfEmployees)
           the domain's country TLD (.de, .ch, ...)      -> country
- LinkedIn company page (when LinkedIn serves the public version; it often
  answers an anonymous request with HTTP 999 or a login wall)
           og:description "Name | 1,234 followers on LinkedIn. tagline..."
           JSON-LD numberOfEmployees                     -> fte_estimate
           the website link                              -> website
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

from .enrich import Proposal
from .models import Company, Country, normalise_website

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MAX_BYTES = 2_000_000

TLD_COUNTRY = {"de": "DE", "ch": "CH", "nl": "NL", "se": "SE", "dk": "DK", "no": "NO",
               "uk": "GB", "us": "US", "at": "AT", "fr": "FR",
               "be": "BE", "lu": "LU", "li": "LI", "es": "ES", "it": "IT", "ie": "IE",
               "pl": "PL", "fi": "FI", "pt": "PT"}
NAME_COUNTRY = {
    "germany": "DE", "deutschland": "DE", "switzerland": "CH", "schweiz": "CH",
    "suisse": "CH", "netherlands": "NL", "nederland": "NL", "the netherlands": "NL",
    "sweden": "SE", "sverige": "SE", "denmark": "DK", "danmark": "DK", "norway": "NO",
    "norge": "NO", "united kingdom": "GB", "great britain": "GB", "uk": "GB",
    "united states": "US", "usa": "US", "austria": "AT", "österreich": "AT",
    "france": "FR",
}
NAME_COUNTRY.update({c.value.lower(): c.value for c in Country})


class ScrapeError(Exception):
    """The page could not be fetched or is not something we can read."""


@dataclass
class PageFacts:
    url: str
    title: str = ""
    description: str = ""
    site_name: str = ""
    lang: str = ""
    links: list[str] = field(default_factory=list)
    jsonld: list[dict] = field(default_factory=list)
    text_hints: list[str] = field(default_factory=list)  # "11-50 employees" etc.


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.facts = PageFacts(url="")
        self._in_title = False
        self._script_type = ""
        self._script_buf: list[str] = []
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "html" and a.get("lang"):
            self.facts.lang = a["lang"].strip().lower()[:2]
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            content = (a.get("content") or "").strip()
            if not content:
                return
            if key in ("description", "og:description", "twitter:description"):
                if not self.facts.description or key == "description":
                    self.facts.description = content
            elif key in ("og:site_name",):
                self.facts.site_name = content
            elif key == "og:title" and not self.facts.title:
                self.facts.title = content
        elif tag == "a" and a.get("href"):
            self.facts.links.append(a["href"].strip())
        elif tag == "script":
            self._script_type = (a.get("type") or "").lower()
            self._script_buf = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            if "ld+json" in self._script_type:
                raw = "".join(self._script_buf).strip()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = None
                for item in _flatten_jsonld(data):
                    self.facts.jsonld.append(item)
            self._script_type = ""
            self._script_buf = []

    def handle_data(self, data):
        if self._in_title:
            self.facts.title = (self.facts.title + " " + data).strip() if not self.facts.title else self.facts.title + data
        elif self._script_type:
            self._script_buf.append(data)
        elif data.strip():
            self._text.append(data.strip())

    def hints(self) -> list[str]:
        text = " ".join(self._text)
        return re.findall(r"\b\d[\d,.]*\s*[-–]\s*\d[\d,.]*\s+employees\b", text)


def _flatten_jsonld(data) -> list[dict]:
    if isinstance(data, list):
        out = []
        for item in data:
            out += _flatten_jsonld(item)
        return out
    if isinstance(data, dict):
        out = [data]
        for key in ("@graph", "mainEntity"):
            if key in data:
                out += _flatten_jsonld(data[key])
        return out
    return []


def parse_page(url: str, text: str) -> PageFacts:
    parser = _Parser()
    parser.feed(text)
    parser.close()
    facts = parser.facts
    facts.url = url
    # LinkedIn encodes some entities twice ("I&amp;#39;ve"): one more pass.
    facts.title = " ".join(html.unescape(facts.title).split())
    facts.description = " ".join(html.unescape(facts.description).split())
    facts.text_hints = parser.hints()
    return facts


# ----------------------------------------------------------------- fetching


def fetch(url: str, timeout: float = 10) -> str:
    """GET one page as text. Raises ScrapeError with a plain-language reason."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ScrapeError(f"not a web address: {url!r}")
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en,de;q=0.8,nl;q=0.7",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype and "xml" not in ctype and ctype:
                raise ScrapeError(f"{url} is not an HTML page ({ctype.split(';')[0]})")
            raw = resp.read(MAX_BYTES)
            charset = resp.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as exc:
        if "linkedin.com" in parsed.netloc and exc.code in (999, 403, 429):
            raise ScrapeError("LinkedIn refused the anonymous request "
                              f"(HTTP {exc.code}); use the company website instead")
        raise ScrapeError(f"{url} answered HTTP {exc.code}")
    except urllib.error.URLError as exc:
        raise ScrapeError(f"could not reach {url}: {exc.reason}")
    except TimeoutError:
        raise ScrapeError(f"{url} did not answer within {int(timeout)} s")
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- proposing


def _is_linkedin(url: str) -> bool:
    return "linkedin.com" in urlparse(url).netloc.lower()


def _company_linkedin(links: list[str], base: str) -> str:
    for href in links:
        full = urljoin(base, href)
        m = re.match(r"https?://(?:[a-z]+\.)?linkedin\.com/company/[^/?#]+", full, re.I)
        if m:
            return m.group(0).replace("http://", "https://")
    return ""


def _country_from(facts: PageFacts) -> str:
    for item in facts.jsonld:
        addr = item.get("address")
        if isinstance(addr, list):
            addr = addr[0] if addr else None
        if isinstance(addr, dict):
            name = str(addr.get("addressCountry") or "").strip().lower()
            if name in NAME_COUNTRY:
                return NAME_COUNTRY[name]
    host = urlparse(facts.url).netloc.lower().split(":")[0]
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    if host.endswith(".co.uk") or host.endswith(".org.uk"):
        return "GB"
    return TLD_COUNTRY.get(tld, "")


def _employees_from(facts: PageFacts) -> str:
    for item in facts.jsonld:
        n = item.get("numberOfEmployees")
        if isinstance(n, dict):
            n = n.get("value") or n.get("minValue")
        if n not in (None, ""):
            try:
                return f"~{int(float(str(n).replace(',', '')))}"
            except ValueError:
                continue
    m = re.search(r"([\d,.]+)\s*[-–]\s*([\d,.]+)\s+employees", facts.description, re.I)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    if facts.text_hints:
        return re.sub(r"\s+employees$", "", facts.text_hints[0], flags=re.I).replace(" ", "")
    return ""


def _website_from(facts: PageFacts) -> str:
    for item in facts.jsonld:
        same = item.get("sameAs") or item.get("url")
        for candidate in (same if isinstance(same, list) else [same]):
            if isinstance(candidate, str) and candidate.startswith("http") \
                    and not _is_linkedin(candidate):
                return candidate
    for href in facts.links:
        m = re.search(r"[?&]url=(https?[^&]+)", href)
        if m:
            from urllib.parse import unquote
            return unquote(m.group(1))
    return ""


# A person's page, not a company's. Nothing in Hermit CRM recognised these
# until now, so a LinkedIn profile was read as if it were a company.
PERSON_URL = re.compile(r"linkedin\.com/in/|xing\.com/profile/", re.I)

# What LinkedIn appends to a person's own headline in og:description:
#   "<headline> · Experience: <employer> · Education: ... · Location: ...
#    · 500+ connections on LinkedIn. View X's profile on LinkedIn, ..."
PROFILE_TAIL = re.compile(
    r"\s*·\s*(Experience|Education|Location|Erfahrung|Ausbildung|Standort|"
    r"Expérience|Formation|Localisation|Ervaring|Opleiding|Locatie)\s*:|"
    r"\s*·\s*\d[\d,.+]*\s*(connections|followers|Kontakte|relations|connecties)\b|"
    r"\s*View\s+[^·]{1,60}?'s?\s+profile\s+on\s+LinkedIn", re.I)

PROFILE_PART = re.compile(
    r"·\s*(?:Experience|Erfahrung|Expérience|Ervaring)\s*:\s*([^·]+)", re.I)
PROFILE_PLACE = re.compile(
    r"·\s*(?:Location|Standort|Localisation|Locatie)\s*:\s*([^·]+)", re.I)


_PROFILE_PATH = re.compile(r"^/in/([\w%.~-]+)", re.I)
_COMPANY_PATH = re.compile(r"^/company/([\w%.~-]+)", re.I)

# Tussenvoegsels and their cousins stay lower-case inside a name.
NAME_PARTICLES = {"van", "der", "den", "de", "del", "della", "di", "da", "du", "dos",
                  "das", "von", "zu", "ten", "ter", "te", "la", "le", "y"}


def _linkedin_path(url: str) -> str:
    """The path of a LinkedIn address, or "" when it is not one.

    A link read off a LinkedIn page may be relative ("/company/123/"); anything
    that is not http(s) on linkedin.com or a subdomain of it is not LinkedIn.
    """
    text = (url or "").strip()
    if text.startswith("/"):
        return text
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    host = parsed.netloc.lower().split(":")[0]
    if parsed.scheme not in ("http", "https"):
        return ""
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return ""
    return parsed.path


def profile_url(url: str) -> str:
    """The one address of a LinkedIn profile, from whichever page of it you were on.

    `/in/x/overlay/contact-info/`, `nl.linkedin.com/in/x` and `/in/x?miniProfileUrn=`
    are one person; compared raw, they were three. No trailing slash, which is
    how most profile addresses in a CRM already look. Anything that is not a
    profile comes back unchanged.
    """
    m = _PROFILE_PATH.match(_linkedin_path(url))
    return "https://www.linkedin.com/in/" + m.group(1) if m else url


def company_page_url(href: str) -> str:
    """A LinkedIn company page's address, cleaned; "" for anything else.

    It comes from a link on a page that is not ours, so it is only ever
    rebuilt from the part that names the company, never passed through.
    """
    m = _COMPANY_PATH.match(_linkedin_path(href))
    return "https://www.linkedin.com/company/" + m.group(1) if m else ""


def name_from_handle(url: str) -> str:
    """A name guessed from a profile's address, for when the page cannot be read.

    `ines-vega-8a1b2c3d` spells a name plus LinkedIn's suffix. `inesvega` or an
    internal id does not, and there a wrong guess is worse than none.
    """
    m = re.match(r"https://www\.linkedin\.com/in/(.+)$", profile_url(url))
    if not m:
        return ""
    words = [w for w in unquote(m.group(1)).split("-") if w]
    while words and any(ch.isdigit() for ch in words[-1]):
        words.pop()
    if len(words) < 2 or not all(w.isalpha() for w in words):
        return ""
    return " ".join(w.lower() if i and w.lower() in NAME_PARTICLES else w.capitalize()
                    for i, w in enumerate(words))


@dataclass
class PersonFacts:
    """What a profile page gives away: little logged out, more logged in."""

    name: str = ""
    headline: str = ""
    employer: str = ""
    location: str = ""
    position: str = ""          # the current job title, from Experience
    company_linkedin: str = ""  # the employer's LinkedIn page
    email: str = ""             # only when Contact info was open


EMAIL = re.compile(r"[^@\s:/?#<>\"']+@[^@\s:/?#<>\"']+\.[^@\s:/?#<>\"']+")


def _email(text: str) -> str:
    """A plain address from a mailto link, or ""."""
    text = (text or "").strip()
    if text.lower().startswith("mailto:"):
        text = text[7:]
    text = unquote(text.split("?")[0]).strip()
    return text if EMAIL.fullmatch(text) else ""


def _company_links(text: str) -> list[tuple[str, str]]:
    """(company page, name) for each "href|label" line the bookmarklet sent.

    The label is the link's text, else its logo's alt text ("Acme logo").
    """
    out = []
    for line in (text or "").splitlines():
        href, _, label = line.partition("|")
        url = company_page_url(href)
        if url:
            label = re.sub(r"\s+logo$", "", " ".join(label.split()), flags=re.I)
            out.append((url, label))
    return out


# What the interface itself says, in the languages it is most used in here.
# A line matching one of these is never a headline, a location or a job title.
# "Contact info" on its own line, or at the end of the location's line when the
# location, a separator and the link come out of one block of inline elements.
CONTACT_INFO = re.compile(r"(?:^|\s*[·•]\s*)(contact info|contactgegevens|contactinformatie|"
                          r"kontaktinfo(rmationen)?|coordonnées)$", re.I)
TOP_NOISE = re.compile(
    r"^(·|•|\(?(he|she|they|hij|zij|hen|er|sie|il|elle|iel)\s*/\s*\w+\)?"
    r"|·?\s*(1st|2nd|3rd\+?|1e|2e|3e\+?|[123]\.\+?)(\s+degree connection)?"
    r"|verified|geverifieerd|verifiziert|vérifié"
    r"|\d[\d.,]*\+?\s+(connections|followers|connecties|volgers|kontakte|follower"
    r"|relations|abonnés)"
    r"|message|bericht|nachricht|connect|connectie maken|vernetzen|se connecter"
    r"|follow|volgen|folgen|suivre|more|meer|mehr|plus)$", re.I)
EXPERIENCE = re.compile(r"^(experience|ervaring|berufserfahrung|erfahrung|expérience)$",
                        re.I)
# "Full-time · 5 yrs 2 mos", "Jan 2023 - Present · 2 yrs 9 mos": a role's
# furniture, never its title.
ROLE_FURNITURE = re.compile(
    r"\b(\d+\s*(yrs?|mos?|jr|jaar|mnd|maanden|jahre?|mon\.?|ans?|mois))\b"
    r"|^(full-time|part-time|freelance|self-employed|contract|internship|fulltime"
    r"|parttime|vollzeit|teilzeit|temps plein|temps partiel)\b", re.I)
# "Current company: Acme. Click to skip to experience card" -> the label, the name.
LABELLED = re.compile(r"^([^:]{2,40}):\s*(.+?)(?:\.?\s+(?:click|klik|klicken|cliquez)\b.*)?$",
                      re.I)
CURRENT_COMPANY = re.compile(r"^(current company|huidig bedrijf|huidige werkgever"
                             r"|aktuelles unternehmen|derzeitiges unternehmen"
                             r"|entreprise actuelle)$", re.I)


def _lines(text: str) -> list[str]:
    """Non-empty lines, with the copy LinkedIn prints for screen readers dropped."""
    out: list[str] = []
    for line in (text or "").splitlines():
        line = " ".join(line.split())
        if line and (not out or out[-1] != line):
            out.append(line)
    return out


def _same(a: str, b: str) -> bool:
    """One name, whatever its case or a trailing full stop ("Acme Inc." / "acme inc")."""
    def key(text):
        return " ".join(text.split()).rstrip(".").casefold()
    return bool(a and b) and key(a) == key(b)


# "(3) Ines Vega | LinkedIn": an unread-count, the name, the site.
TAB_TITLE = re.compile(r"^(?:\(\d+\+?\)\s*)?(.*?)\s*\|\s*LinkedIn\s*$", re.I)


def _name_from_title(title) -> str:
    """The name in a profile tab's title, for a layout with no <h1> to read."""
    m = TAB_TITLE.match(" ".join((title or "").split()))
    return m.group(1) if m else ""


def person_from_page(page: dict) -> PersonFacts:
    """A person from what the bookmarklet read on a profile you are logged in to.

    `page` is the bookmarklet's query: h1 (the name), top (the top card's
    text), exp (the Experience section's text), co ("href|label" per company
    link), lab (the top card's aria-labels), mail (a mailto from Contact info).
    Nothing here fetches anything.

    It leans on what a layout change leaves alone -- the order of lines around
    the name, the "Current company: X" label a screen reader gets, the Contact
    info link -- and never on class names, which LinkedIn scrambles. What it
    cannot place stays empty: a wrong employer would create a wrong company.
    """
    person = PersonFacts(name=" ".join((page.get("h1") or "").split())
                         or _name_from_title(page.get("title")),
                         email=_email(page.get("mail")))
    links = _company_links(page.get("co"))
    exp = _lines(page.get("exp"))
    if not exp:
        # The whole page's text came instead: Experience is where its heading is.
        whole = _lines(page.get("top"))
        exp = next((whole[i:] for i, line in enumerate(whole) if EXPERIENCE.match(line)), [])
    if exp and EXPERIENCE.match(exp[0]):
        exp = exp[1:]

    # The employer: the label the page gives the current company, else the
    # first company in Experience (it lists the current role first).
    labelled = {}
    for label in (page.get("lab") or "").splitlines():
        m = LABELLED.match(" ".join(label.split()))
        if m:
            labelled[m.group(2).strip()] = bool(CURRENT_COMPANY.match(m.group(1).strip()))
    person.employer = next((name for name, current in labelled.items() if current), "")
    if not person.employer and links:
        person.employer = links[0][1]
    person.company_linkedin = next(
        (url for url, label in links if _same(label, person.employer)), "")

    # The top card: the headline is the first line under the name that is not
    # pronouns, the connection degree or a name the labels already gave (the
    # company and the school sit in the same block); the location is the line
    # before "Contact info". The name may share its line with the pronouns
    # and the degree, and without it nothing marks where the headline starts.
    def known(line):
        return any(_same(line, name) for name in labelled)

    top = [line for line in _lines(page.get("top")) if not TOP_NOISE.match(line)]
    anchor = next((i for i, line in enumerate(top) if person.name
                   and line.casefold().startswith(person.name.casefold())), None)
    for i, line in enumerate(top):
        marker = CONTACT_INFO.search(line)
        if marker:
            before = line[:marker.start()].strip(" ·•")
            at, place = (i, before) if before else (i - 1, top[i - 1] if i else "")
            if place and at != anchor and not known(place) \
                    and not _same(place, person.headline):
                person.location = place
            break
        if anchor is not None and i > anchor and not person.headline and not known(line):
            person.headline = line

    # The position: the first role in Experience. On its own it reads "title,
    # company · Full-time, dates"; several roles at one company read "company,
    # Full-time · 5 yrs, title, dates".
    if exp and person.employer:
        if len(exp) > 1 and _same(exp[1].split(" · ")[0].strip(), person.employer):
            person.position = exp[0]
        elif _same(exp[0], person.employer):
            person.position = next(
                (line for line in exp[1:4] if not ROLE_FURNITURE.search(line)), "")
    return person


def is_person_page(facts: PageFacts) -> bool:
    if PERSON_URL.search(facts.url or ""):
        return True
    for item in facts.jsonld:
        if str(item.get("@type", "")).strip().lower() == "person":
            return True
    return False


MASKED = re.compile(r"[\s*·•]+")


def _jsonld_text(value) -> str:
    """The first readable text in a JSON-LD value.

    schema.org lets any value be a list, and LinkedIn sends job titles as one;
    str() of it put "['Co-chair', 'Founder']" in a title field. Logged out,
    an ordinary member's titles also come masked, "********** *** ***", which
    says only that LinkedIn is hiding them: skipped, never written.
    """
    for item in value if isinstance(value, list) else [value]:
        if isinstance(item, dict):
            item = item.get("name")
        text = " ".join(str(item or "").split())
        if text and not MASKED.fullmatch(text):
            return text
    return ""


def person_from(facts: PageFacts) -> PersonFacts:
    """A name, a headline and an employer, from a page built to hide them.

    Logged out, LinkedIn gives a title and one description string; everything
    below is squeezed out of those two. What cannot be found stays empty rather
    than being guessed, because a wrong employer creates a wrong company.
    """
    person = PersonFacts()
    for item in facts.jsonld:
        if str(item.get("@type", "")).strip().lower() != "person":
            continue
        person.name = _jsonld_text(item.get("name"))
        person.headline = _jsonld_text(item.get("jobTitle"))
        person.employer = _jsonld_text(item.get("worksFor"))

    title = " ".join((facts.title or "").split())
    # "Ines Vega - Harbour Light Labs | LinkedIn"
    title = re.sub(r"\s*[|\-–—]\s*LinkedIn\s*$", "", title, flags=re.I).strip()
    if not person.name and title:
        person.name = re.split(r"\s+[-–—|]\s+", title)[0].strip()

    text = " ".join((facts.description or "").split())
    if not person.headline and text:
        head = PROFILE_TAIL.split(text)[0].strip(" .·")
        person.headline = head
    if not person.employer:
        m = PROFILE_PART.search(text)
        if m:
            person.employer = m.group(1).strip(" .·")
    if not person.employer and " - " in title:
        person.employer = title.split(" - ", 1)[1].strip()
    m = PROFILE_PLACE.search(text)
    if m:
        person.location = m.group(1).strip(" .·")
    return person


def _oneliner_from(facts: PageFacts) -> str:
    """One sentence about the product. Never about a person.

    A profile's og:description is that person's headline with their experience,
    education and connection count stapled on. Read as a company one-liner it
    produced the worst field Hermit CRM has ever written, so a person's page
    now yields nothing here and `enrich` is the way to fill it.
    """
    if is_person_page(facts):
        return ""
    text = facts.description
    if _is_linkedin(facts.url):
        # "Acme | 1,234 followers on LinkedIn. Tagline. | Long description"
        text = re.sub(r"^.*?followers on LinkedIn\.\s*", "", text, flags=re.I)
        text = text.split(" | ")[0]
    text = PROFILE_TAIL.split(text)[0] if text else text
    if not text:
        text = facts.title
        for sep in (" | ", " – ", " - ", " — "):
            if sep in text:
                parts = [p for p in text.split(sep) if p.strip()]
                text = max(parts, key=len)
                break
    return " ".join(text.split())[:300]


def propose_from_url(company: Company, url: str, fetcher=fetch,
                     custom_keys=()) -> Proposal:
    """Fetch `url` (a website or LinkedIn company page) and propose values for
    the company's empty fields. Never overwrites anything."""
    url = normalise_website(url)
    return propose_from_facts(company, parse_page(url, fetcher(url)),
                              custom_keys=custom_keys)


def propose_from_facts(company: Company, facts: PageFacts,
                       custom_keys=()) -> Proposal:
    """The proposing half of propose_from_url, for a page already fetched.

    Capture needs the parsed page for the company's *name* as well as its
    fields, and fetching the same URL twice to get both would be silly.
    """
    url = facts.url
    found = {}
    if _is_linkedin(url):
        found["linkedin"] = url.split("?")[0].rstrip("/")
        found["website"] = _website_from(facts)
    else:
        found["website"] = url
        found["linkedin"] = _company_linkedin(facts.links, url)
        for item in facts.jsonld:
            same = item.get("sameAs")
            for candidate in (same if isinstance(same, list) else [same]):
                if isinstance(candidate, str) and "linkedin.com/company/" in candidate:
                    found["linkedin"] = candidate.split("?")[0].rstrip("/")
    found["country"] = _country_from(facts)
    found["product_oneliner"] = _oneliner_from(facts)

    wanted = ["website", "linkedin", "country", "product_oneliner"]
    # A headcount is only worth reading off the page when the folder has a
    # field to put it in; `custom_keys` is whatever the user defined.
    if "fte_estimate" in (custom_keys or ()):
        found["fte_estimate"] = _employees_from(facts)
        wanted.insert(3, "fte_estimate")

    proposal = Proposal(sources=[url])
    proposal.missing = [k for k in wanted
                        if (getattr(company, k, None) if k not in (custom_keys or ())
                            else company.extra.get(k)) in ("", None)]
    for key in proposal.missing:
        value = found.get(key) or ""
        if value:
            proposal.fields[key] = value
    notes = []
    if facts.title:
        notes.append(f"page title: {facts.title}")
    if not facts.description and not facts.jsonld:
        notes.append("the page has no description or structured data; "
                     "only the title and links were usable")
    proposal.notes = "; ".join(notes)
    return proposal
