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

"""Ask the Hermit: answer a question about the CRM with the configured AI CLI.

Two steps, cheapest first. Python builds a compact index of the whole CRM (one
row per contact, with ready-made links, stage, last touch and next task) and the
model answers from the page text plus that index in one call without tools.
Only when it says that is not enough (a question about what notes or emails say)
does a second run start inside the data folder with read-only tools (files plus
`hermitcrm show/digest/report`), where the folder's CLAUDE.md tells an agent how
to read the CRM cheaply. Every answer goes through `fix_links`, so a link the
model invented never renders as a dead one. The model tier (medium by default,
strong for "Retry with ...") comes from the Enricher.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from .enrich import EnrichError, Enricher, model_label

PAGE_LIMIT = 40_000  # characters of page text sent with the first step
INDEX_LIMIT = 60_000  # characters of the CRM index; the oldest rows go first

# Tags whose content is chrome or form plumbing, not what the page says.
SKIP_TAGS = {"script", "style", "nav", "header", "footer", "button", "svg", "template",
             "noscript"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "table", "tr", "li", "ul",
              "ol", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "details", "summary",
              "br", "form", "label", "dl", "dt", "dd", "blockquote"}
VOID_TAGS = {"br", "img", "input", "meta", "link", "hr", "col", "source", "wbr"}

# Claude Code --allowedTools for the whole-CRM step: read-only.
CRM_TOOLS = ("Read,Grep,Glob,Bash(hermitcrm show:*),Bash(hermitcrm digest:*),"
             "Bash(hermitcrm report:*),Bash(hermitcrm check:*)")

PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "boolean",
                       "description": "true only if the page text is enough to answer"},
        "answer": {"type": "string",
                   "description": "the answer in Markdown; empty when not answerable"},
    },
    "required": ["answerable", "answer"],
    "additionalProperties": False,
}
CRM_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "the answer in Markdown"},
        "sources": {"type": "array", "items": {"type": "string"},
                    "description": "files or commands the answer relies on"},
    },
    "required": ["answer", "sources"],
    "additionalProperties": False,
}


def _internal(href: str) -> bool:
    """A link into the app worth showing the model: not an anchor, asset or Ask itself."""
    return (href.startswith("/") and not href.startswith("//")
            and not href.startswith(("/static", "/ask")))


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.select = ""        # name of the <select> we are in, if any
        self.selected = False   # inside its selected <option>: that value is page data
        self.href = ""          # the internal link we are inside, if any
        self.href_at = 0        # where its text starts in parts
        self.links: set[str] = set()   # every internal href that was kept

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = (dict(attrs).get("href") or "").strip()
            self.href = href if _internal(href) else ""
            self.href_at = len(self.parts)
        elif tag == "select":
            self.select = dict(attrs).get("name") or "choice"
        elif tag == "option":
            self.selected = self.select != "" and "selected" in dict(attrs)
        elif tag in SKIP_TAGS and tag not in VOID_TAGS:
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag == "input" and not self.skip:
            values = dict(attrs)
            if values.get("type") not in ("hidden", "submit", "checkbox", "radio") \
                    and values.get("value"):
                self.parts.append(f" [{values.get('name', 'field')}: {values['value']}] ")

    def handle_endtag(self, tag):
        if tag == "a":
            if self.href and "".join(self.parts[self.href_at:]).strip():
                self.parts.append(f" ({self.href})")   # the model sees the real URL
                self.links.add(self.href)
            self.href = ""
        elif tag == "select":
            self.select, self.selected = "", False
        elif tag == "option":
            self.selected = False
        elif tag in SKIP_TAGS and tag not in VOID_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.select:  # of a dropdown only the chosen value is content
            if self.selected and data.strip():
                self.parts.append(f" [{self.select}: {data.strip()}] ")
            return
        self.parts.append(data)


def _extract(html: str, limit: int) -> tuple[str, set[str]]:
    parser = _TextExtractor()
    parser.feed(html or "")
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    text = "\n".join(line for line in lines if line.strip(" |"))
    if len(text) > limit:
        text = text[:limit] + "\n[page text cut off here]"
    return text, parser.links


def page_text(html: str, limit: int = PAGE_LIMIT) -> str:
    """The visible content of a rendered page as compact text, capped at limit.

    A link into the app is kept as `label (/path)`, so the model can link to it."""
    return _extract(html, limit)[0]


# ------------------------------------------------------------------ CRM index


def _cell(text: str, limit: int = 0) -> str:
    """Text safe inside a Markdown table cell (and inside a [label])."""
    text = " ".join(str(text).split()).replace("|", "/").replace("[", "(").replace("]", ")")
    return text[:limit].rstrip() + "…" if limit and len(text) > limit else text


def _latest(items):
    return max((i for i in items if i.date), key=lambda i: i.date, default=None)


def _stamp(it, today: date) -> str:
    if it is None:
        return "none"
    return f"{it.date:%Y-%m-%d} {it.label} ({(today - it.date.date()).days}d)"


def _next_task(company, slug: str, today: date) -> str:
    """The earliest open to-do of this person or of the company as a whole."""
    todos = [t for t in company.open_todos() if t.contact is None or t.contact.slug == slug]
    if not todos:
        return "none"
    t = todos[0]
    text = _cell(t.text, 40)
    if t.due is None:
        return f"open, no date: {text}"
    return f"{t.due:%Y-%m-%d}{' overdue' if t.due < today else ''}: {text}"


def crm_index(store, today: date | None = None) -> str:
    """One Markdown row per contact (and per company without any), newest activity first.

    Python does the lookups the model would otherwise have to do over files: the
    links are ready-made, the stage comes with its role (open, won, lost, closed,
    parked), and every date is measured against today.
    """
    today = today or store.today()
    rows: list[tuple[datetime, str]] = []
    for company in store.companies.values():
        by_contact: dict[str, list] = {}
        for it in company.interactions:
            key = it.contact if it.contact in company.contacts else ""
            by_contact.setdefault(key, []).append(it)
        company_level = by_contact.get("", [])
        # "Logged an interaction" counts a company-level one too, so it gets a column.
        company_last = _latest(i for i in company_level if i.is_touch)
        company_link = f"[{_cell(company.name)}](/companies/{company.slug})"
        stage = f"{_cell(company.stage)} ({store.stages.role_of(company.stage) or 'unknown'})"
        people = list(company.contacts.values()) or [None]
        for person in people:
            its = by_contact.get(person.slug, []) if person else []
            touch = _latest(i for i in its if i.is_touch)
            logged = _latest(its)
            if person:
                who = f"[{_cell(person.name or person.slug)}](/companies/{company.slug}/contacts/{person.slug})"
                days = str((today - touch.date.date()).days) if touch else "-"
            else:
                who, days = "(no contacts)", "-"
            dates = [i.date for i in (touch, logged, company_last) if i]
            line = " | ".join([
                who, company_link, stage, _stamp(touch, today),
                "same" if logged is touch and touch else _stamp(logged, today),
                _stamp(company_last, today),
                _next_task(company, person.slug if person else "", today), days])
            rows.append((max(dates) if dates else datetime.min, f"| {line} |"))
    rows.sort(key=lambda r: r[0], reverse=True)

    head = (
        f"Today: {today:%Y-%m-%d}\n"
        "One row per contact, newest activity first. Columns: contact, company, company "
        "stage with its role (open, won, lost, closed or parked), last touch (contact made "
        "with this person: email, call, meeting...; the age in days), last logged (the "
        "latest interaction of any kind, notes included; `same` when it is the last touch), "
        "company-level last touch (not tied to a person), next open task (soonest due; "
        "`overdue` when before today; `none` when there is no open task), days since the "
        "person's last touch.\n\n"
        "| contact | company | stage | last touch | last logged | company-level touch | "
        "next open task | days |\n|---|---|---|---|---|---|---|---|\n")
    out, size = [], len(head)
    for n, (_, line) in enumerate(rows):
        if size + len(line) + 1 > INDEX_LIMIT:
            out.append(f"[{len(rows) - n} older rows left out]")
            break
        out.append(line)
        size += len(line) + 1
    return head + "\n".join(out)


# ----------------------------------------------------------------------- links

_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_CODE = re.compile(r"(```.*?```|`[^`\n]*`)", re.DOTALL)
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def _key(href: str) -> str:
    """A link or file path reduced to the key it is looked up by."""
    path = href.split("#")[0].split("?")[0].strip().strip("/")
    path = re.sub(r"^(\./|\.\./)+", "", path)
    if path.endswith(".md"):
        path = path[:-3]
    if path.endswith("/company"):
        path = path[: -len("/company")]
    return path


def link_lookup(store) -> dict[str, str]:
    """Every way the model may name a company or person, mapped to its real URL.

    The URL itself, the file path in the data folder (`companies/acme/company.md`,
    `companies/acme/contacts/jane-doe.md`) and the bare slug when it is unambiguous."""
    known: dict[str, str] = {}
    slugs: dict[str, set[str]] = {}
    for company in store.companies.values():
        url = f"/companies/{company.slug}"
        known[_key(url)] = url
        slugs.setdefault(company.slug, set()).add(url)
        for person in company.contacts.values():
            purl = f"{url}/contacts/{person.slug}"
            known[_key(purl)] = purl
            slugs.setdefault(person.slug, set()).add(purl)
    for slug, urls in slugs.items():
        if len(urls) == 1:
            known.setdefault(slug, next(iter(urls)))
    return known


def fix_links(markdown: str, known: dict[str, str]) -> str:
    """Keep real links, repair ones that point at a file or slug, flatten the rest.

    `known` is what `link_lookup` returns. http(s) and mailto links are left
    alone; any other link that is not a known page becomes its plain label, so
    nothing renders as a link that ends in a 404. Code spans are not touched."""
    def link(m: re.Match) -> str:
        label, href = m.group(1), m.group(2)
        if href.startswith(("http://", "https://", "mailto:")):
            return m.group(0)
        if not _SCHEME.match(href) and not href.startswith(("//", "#")):
            url = known.get(_key(href))
            if url:
                return f"[{label}]({url})"
        return label

    parts = _CODE.split(markdown)
    return "".join(p if i % 2 else _LINK.sub(link, p) for i, p in enumerate(parts))


def page_prompt(question: str, page: str, text: str) -> str:
    return (
        "You are Hermit, the assistant inside Hermit CRM, a personal sales CRM. "
        f"The user is looking at the page {page} and asks a question about it. "
        "Answer using only the page content below. If the page does not contain "
        "enough to answer reliably, set answerable to false and leave answer empty; "
        "a search of the whole CRM follows. Be concise and concrete; use Markdown "
        "lists or tables when they help.\n\n"
        f"Question: {question}\n\n--- page content ---\n{text}\n--- end of page ---\n"
    )


def index_prompt(question: str, page: str, text: str, index: str) -> str:
    """The one no-tools call: the question, the page (when there is one) and the CRM index."""
    shown = (f"The user is looking at the page {page}; its content is below.\n\n"
             f"--- page content ---\n{text}\n--- end of page ---\n\n") if text else ""
    return (
        "You are Hermit, the assistant inside Hermit CRM, a personal sales CRM. "
        "Answer the question from the CRM index and the page content below; both are "
        "complete and exact. Filter on the columns of the index, do not guess, and use "
        "the days and dates as given (today is in the index). A person is `disqualified` "
        "only when the company stage's role says closed; a follow-up is the `next open "
        "task` column. Link every person and company you name with the Markdown links "
        "in the data, copied exactly; use only links that appear in the data and never "
        "link to files. If the question needs what a note or email says, or anything "
        "the data does not hold, set answerable to false and leave answer empty; a "
        "search of the data folder follows. Be concise and concrete; use a Markdown "
        "list or table when it helps.\n\n"
        f"Question: {question}\n\n{shown}--- CRM index ---\n{index}\n--- end of index ---\n"
    )


def crm_prompt(question: str, page: str, text: str) -> str:
    context = text[:4000]
    return (
        "You are Hermit, the assistant inside Hermit CRM. The current directory is "
        "the CRM data folder; CLAUDE.md in it explains the layout and the cheapest "
        "way to read it (PIPELINE.md first, `hermitcrm show <slug>`, `hermitcrm "
        "digest`, `hermitcrm report --md`). Answer the question from that data. "
        "Read only: do not create, edit or delete anything. If the data does not "
        "answer the question, say so plainly. Be concise and concrete. When you name "
        "a company or person, link it with a site path: /companies/<company-slug> "
        "and /companies/<company-slug>/contacts/<contact-slug>; never link to files.\n\n"
        f"The user asked this while on the page {page} (start of that page below, "
        "for context).\n\n"
        f"Question: {question}\n\n--- page ---\n{context}\n--- end ---\n"
    )


@dataclass
class Answer:
    question: str
    text: str
    scope: str                       # "index" (page + CRM index), "page" (page only) or "crm"
    model: str
    tier: str
    sources: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def model_label(self) -> str:
        return model_label(self.model)

    @property
    def seconds_label(self) -> str:
        return f"{self.seconds:.1f} s" if self.seconds < 10 else f"{self.seconds:.0f} s"


def ask(enricher: Enricher, question: str, page: str, html: str, data_dir: Path | str,
        scope: str = "auto", timeout: float | None = None, store=None) -> Answer:
    """Answer in one no-tools call, then (only if needed) by reading the data folder.

    scope "auto" sends the page and the CRM index, "crm" the index alone, "deep"
    goes straight to the read-only walk of the data folder. Without a store there
    is no index and the first call has the page alone.

    Raises EnrichError when no AI CLI is available or a run fails.
    """
    question = " ".join((question or "").split())
    if not question:
        raise EnrichError("Type a question first.")
    if not enricher.available:
        raise EnrichError(enricher.unavailable_reason())
    if timeout:
        enricher.timeout = float(timeout)
    started = time.monotonic()
    text, page_links = _extract(html, PAGE_LIMIT)
    known = link_lookup(store) if store is not None else {}
    for href in page_links:  # a link the page itself showed is a real one
        known.setdefault(_key(href), href)
    if scope != "deep":
        if store is not None:
            index = crm_index(store)
            prompt = index_prompt(question, page, "" if scope == "crm" else text, index)
        else:
            prompt = page_prompt(question, page, text)
        data = enricher.runner(prompt, PAGE_SCHEMA, tools="")
        answer = str(data.get("answer") or "").strip()
        if data.get("answerable") and answer:
            return Answer(question, fix_links(answer, known), "index" if store is not None else "page",
                          enricher.model, enricher.tier, seconds=time.monotonic() - started)
    data = enricher.runner(crm_prompt(question, page, text), CRM_SCHEMA, tools=CRM_TOOLS,
                           cwd=str(data_dir), extra_path=str(Path(sys.executable).parent))
    answer = str(data.get("answer") or "").strip()
    if not answer:
        raise EnrichError("The AI returned an empty answer.")
    sources = [str(s) for s in (data.get("sources") or []) if s]
    return Answer(question, fix_links(answer, known), "crm", enricher.model, enricher.tier,
                  sources, time.monotonic() - started)
