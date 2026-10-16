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


"""Text for "Draft it from my website": a website (home page plus a few pages
that describe the business), a PDF, a Word file or a text file. No network:
the fetcher is a fake. All names are made up."""

import io
import zipfile

import pytest

from hermitcrm import scrape, textsource

HOME = """<html><head><title>Example Roofing</title><style>.x{color:red}</style>
<script>var tracking = 1;</script></head><body>
<nav><a href="/">Home</a> <a href="/about-us">About</a> <a href="/services/">Services</a>
<a href="/blog/2026/news">News</a> <a href="https://other.example.org/about">Partner</a>
<a href="/brochure.pdf">Brochure</a> <a href="mailto:hi@example.com">Mail</a></nav>
<h1>We fix leaky roofs</h1><p>For offices &amp; schools.</p></body></html>"""
PAGES = {
    "https://roofing.example.com": HOME,
    "https://roofing.example.com/about-us": "<p>Founded by two roofers.</p><nav>Home</nav>",
    "https://roofing.example.com/services/": "<p>Repairs and inspections.</p>",
}


def fetcher(url):
    if url not in PAGES:
        raise AssertionError(f"fetched {url}")
    return PAGES[url]


def test_website_reads_home_and_pages_about_the_business():
    text = textsource.read_website("roofing.example.com", fetcher=fetcher)
    assert "We fix leaky roofs" in text and "For offices & schools." in text
    assert "Founded by two roofers." in text and "Repairs and inspections." in text
    assert "tracking" not in text and "color:red" not in text
    assert "other.example.org" not in text  # another site is never fetched


def test_one_failing_extra_page_does_not_spoil_the_rest():
    def flaky(url):
        if url.endswith("/services/"):
            raise scrape.ScrapeError("answered HTTP 500")
        return fetcher(url)

    text = textsource.read_website("https://roofing.example.com", fetcher=flaky)
    assert "Founded by two roofers." in text and "Repairs" not in text


def test_a_website_that_cannot_be_reached_says_so():
    def down(url):
        raise scrape.ScrapeError("could not reach https://down.example.com: refused")

    with pytest.raises(textsource.SourceError, match="could not reach"):
        textsource.read_website("down.example.com", fetcher=down)


def docx(*paragraphs):
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def zipped(name, data):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, data)
    return buf.getvalue()


def pdf(text):
    """A one-page PDF with one line of text, written by hand (no library)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    return bytes(out)


@pytest.mark.parametrize("name, data, expected", [
    ("deck.docx", docx("We fix leaky roofs.", "Offices and schools."),
     "We fix leaky roofs.\nOffices and schools."),
    ("notes.txt", "We fix roofs.\n\n\nFor schools.".encode(), "We fix roofs.\nFor schools."),
    ("notes.txt", "Über uns: Dächer".encode("latin-1"), "Über uns: Dächer"),
    ("deck.pdf", pdf("We fix leaky roofs"), "We fix leaky roofs"),
])
def test_files(name, data, expected):
    assert textsource.read_file(name, data) == expected


@pytest.mark.parametrize("name, data, says", [
    ("old.doc", b"\xd0\xcf\x11\xe0", "old Word files"),
    ("sheet.xlsx", b"PK..", "a .xlsx file cannot be read"),
    ("broken.docx", b"not a zip", "not a Word file"),
    ("empty.txt", b"", "empty"),
    ("scan.pdf", pdf(""), "no text in it"),
    ("broken.docx", zipped("word/document.xml", b"<w:document><unclosed"), "not a Word file"),
    ("other.docx", zipped("something.xml", b"<x/>"), "not a Word file"),
    ("broken.pdf", b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 9 0 R >> endobj\n"
                   b"trailer << /Root 1 0 R >>\n%%EOF", "PDF cannot be read|no text"),
])
def test_files_that_cannot_be_read_say_why(name, data, says):
    with pytest.raises(textsource.SourceError, match=says):
        textsource.read_file(name, data)


def test_a_docx_that_unpacks_to_too_much_is_refused_before_it_is_read():
    bomb = zipped("word/document.xml", b"<w:document>" + b" " * (textsource.MAX_XML_BYTES + 10)
                  + b"</w:document>")
    assert len(bomb) < 100_000  # small on disk...
    with pytest.raises(textsource.SourceError, match="too large"):
        textsource.read_file("bomb.docx", bomb)  # ...and never unpacked whole


@pytest.mark.parametrize("url", ["https://exa mple.com", "https://example.com:abc",
                                 "https://" + "a" * 70 + ".example.com", "https://[::1"])
def test_a_typo_in_the_address_is_a_scrape_error(url):
    with pytest.raises(scrape.ScrapeError):
        scrape.fetch(url, timeout=2)
