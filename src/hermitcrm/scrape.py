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

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

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
    facts.title = " ".join(facts.title.split())
    facts.description = " ".join(facts.description.split())
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


def _oneliner_from(facts: PageFacts) -> str:
    text = facts.description
    if _is_linkedin(facts.url):
        # "Acme | 1,234 followers on LinkedIn. Tagline. | Long description"
        text = re.sub(r"^.*?followers on LinkedIn\.\s*", "", text, flags=re.I)
        text = text.split(" | ")[0]
    if not text:
        text = facts.title
        for sep in (" | ", " – ", " - ", " — "):
            if sep in text:
                parts = [p for p in text.split(sep) if p.strip()]
                text = max(parts, key=len)
                break
    return " ".join(text.split())[:300]


def propose_from_url(company: Company, url: str, fetcher=fetch) -> Proposal:
    """Fetch `url` (a website or LinkedIn company page) and propose values for
    the company's empty fields. Never overwrites anything."""
    url = normalise_website(url)
    return propose_from_facts(company, parse_page(url, fetcher(url)))


def propose_from_facts(company: Company, facts: PageFacts) -> Proposal:
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
    found["fte_estimate"] = _employees_from(facts)
    found["product_oneliner"] = _oneliner_from(facts)

    proposal = Proposal(sources=[url])
    proposal.missing = [k for k in ("website", "linkedin", "country", "fte_estimate",
                                    "product_oneliner")
                        if getattr(company, k) in ("", None)]
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
