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

"""Plain text from a website, a PDF, a Word file or a text file, for
"Draft it from my website" on Settings > Playbook. Nothing here runs an AI:
it only turns what you point at into text the AI then reads.

A website is its home page plus a few pages of the same site whose address
looks like it describes the business (about, services, pricing, customers,
in a few languages). Word files are read with the standard library (a .docx
is a zip of XML); PDFs with pypdf.
"""

from __future__ import annotations

import io
import re
import zipfile
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from hermitcrm import scrape

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_XML_BYTES = 20 * 1024 * 1024  # a .docx unpacked: a small zip can hold gigabytes
MAX_PAGES = 5            # the home page and up to four more
MAX_CHARS = 30000        # what the playbook prompt takes at most

# Path words of pages worth reading, in the languages the app drafts in.
PAGE_WORDS = (
    "about", "service", "offer", "product", "pricing", "price", "solution", "customer",
    "case", "client", "work", "team", "why", "how",
    "ueber", "uber", "leistung", "angebot", "preise", "kunden", "loesung",
    "over-ons", "diensten", "aanbod", "prijzen", "klanten", "oplossing",
    "a-propos", "propos", "offre", "tarif", "clients", "solution",
)


class SourceError(Exception):
    """The website or file could not be read, in words a person can act on."""


class _Text(HTMLParser):
    """The visible text of a page: no scripts, styles, navigation chrome."""

    SKIP = {"script", "style", "noscript", "svg", "template", "head"}
    BLOCK = {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "br", "tr",
             "header", "footer", "main", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href.strip())
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(" ".join(data.split()) + " ")


def _tidy(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out, seen = [], set()
    for line in lines:
        # Menus and footers repeat on every page: keep a line once.
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return "\n".join(out)


def page_text(html: str) -> tuple[str, list[str]]:
    parser = _Text()
    parser.feed(html)
    parser.close()
    return _tidy("".join(parser.parts)), parser.links


def _same_site(base: str, href: str) -> str:
    url = urljoin(base, href).split("#", 1)[0]
    a, b = urlparse(base), urlparse(url)
    if b.scheme not in ("http", "https"):
        return ""
    if b.netloc.lower().removeprefix("www.") != a.netloc.lower().removeprefix("www."):
        return ""
    if re.search(r"\.(pdf|jpe?g|png|gif|svg|zip|docx?|xlsx?|mp4|webp)$", b.path, re.I):
        return ""
    return url


def _wanted(url: str) -> bool:
    path = urlparse(url).path.lower()
    return bool(path.strip("/")) and any(word in path for word in PAGE_WORDS)


def read_website(url: str, fetcher=scrape.fetch) -> str:
    """The text of a site: the page given and up to four pages of the same site
    that describe the business. Raises SourceError when the first page fails."""
    url = (url or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    try:
        html = fetcher(url)
    except scrape.ScrapeError as exc:
        raise SourceError(str(exc)) from None
    text, links = page_text(html)
    pages = [f"--- {url} ---\n{text}"]
    seen = {url.rstrip("/")}
    for href in links:
        if len(pages) >= MAX_PAGES or sum(map(len, pages)) >= MAX_CHARS:
            break
        link = _same_site(url, href)
        if not link or link.rstrip("/") in seen or not _wanted(link):
            continue
        seen.add(link.rstrip("/"))
        try:
            more, _ = page_text(fetcher(link))
        except scrape.ScrapeError:
            continue  # one page that fails does not spoil the rest
        if more:
            pages.append(f"--- {link} ---\n{more}")
    return "\n\n".join(pages)[:MAX_CHARS]


def _docx_text(data: bytes) -> str:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    unreadable = SourceError("this is not a Word file Hermit CRM can read (.docx); "
                             "save it as .docx or PDF, or paste the text")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.getinfo("word/document.xml").file_size > MAX_XML_BYTES:
                raise SourceError("this Word file is too large to read; save it as PDF, "
                                  "or paste the text")
            with z.open("word/document.xml") as f:
                xml = f.read(MAX_XML_BYTES + 1)
        if len(xml) > MAX_XML_BYTES:  # the size in the zip lied
            raise SourceError("this Word file is too large to read; save it as PDF, "
                              "or paste the text")
        root = ElementTree.fromstring(xml)
    except SourceError:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, RuntimeError,
            NotImplementedError, EOFError, OSError, ValueError, zipfile.LargeZipFile):
        # Not a zip, no document in it, broken XML, encrypted or packed in a
        # way zipfile does not know.
        raise unreadable from None
    paragraphs = []
    for p in root.iter(f"{ns}p"):
        text = "".join(t.text or "" for t in p.iter(f"{ns}t"))
        if text.strip():
            paragraphs.append(text)
    return "\n".join(paragraphs)


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:  # an install from before pypdf was a dependency
        raise SourceError("reading PDFs needs the pypdf package: update Hermit CRM "
                          "(or pip install pypdf), or paste the text") from None
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise SourceError("this PDF is password-protected; paste its text instead")
        pages = [(page.extract_text() or "").strip() for page in reader.pages[:60]]
    except SourceError:
        raise
    except PdfReadError as exc:
        raise SourceError(f"this PDF cannot be read ({exc}); paste its text instead") from None
    except Exception as exc:  # noqa: BLE001 -- pypdf raises many kinds on a broken file
        raise SourceError(f"this PDF cannot be read ({type(exc).__name__}); "
                          "paste its text instead") from None
    text = "\n\n".join(p for p in pages if p)
    if not text.strip():
        raise SourceError("this PDF has no text in it (a scan or only images); "
                          "paste its text instead")
    return text


def read_file(filename: str, data: bytes) -> str:
    """The text of an uploaded .pdf, .docx, .txt or .md file."""
    if len(data) > MAX_FILE_BYTES:
        raise SourceError(f"the file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    if not data:
        raise SourceError("the file is empty")
    suffix = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if suffix == "pdf" or data[:5] == b"%PDF-":
        text = _pdf_text(data)
    elif suffix == "docx":
        text = _docx_text(data)
    elif suffix in ("txt", "md", "markdown", "text", ""):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
    elif suffix == "doc":
        raise SourceError("old Word files (.doc) cannot be read; save it as .docx or PDF")
    else:
        raise SourceError(f"a .{suffix} file cannot be read; use PDF, Word (.docx) or .txt")
    return _tidy(text)[:MAX_CHARS]
