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

Two steps, cheapest first. The page the question was asked on is rendered to
plain text and the model answers from that text alone, without tools. Only
when it says the page is not enough does a second run start inside the data
folder with read-only tools (files plus `hermitcrm show/digest/report`), where
the folder's CLAUDE.md tells an agent how to read the CRM cheaply. The model
tier (medium by default, strong for "Retry with ...") comes from the Enricher.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from .enrich import EnrichError, Enricher, model_label

PAGE_LIMIT = 40_000  # characters of page text sent with the first step

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


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.select = ""        # name of the <select> we are in, if any
        self.selected = False   # inside its selected <option>: that value is page data

    def handle_starttag(self, tag, attrs):
        if tag == "select":
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
        if tag == "select":
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


def page_text(html: str, limit: int = PAGE_LIMIT) -> str:
    """The visible content of a rendered page as compact text, capped at limit."""
    parser = _TextExtractor()
    parser.feed(html or "")
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    text = "\n".join(line for line in lines if line.strip(" |"))
    if len(text) > limit:
        text = text[:limit] + "\n[page text cut off here]"
    return text


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


def crm_prompt(question: str, page: str, text: str) -> str:
    context = text[:4000]
    return (
        "You are Hermit, the assistant inside Hermit CRM. The current directory is "
        "the CRM data folder; CLAUDE.md in it explains the layout and the cheapest "
        "way to read it (PIPELINE.md first, `hermitcrm show <slug>`, `hermitcrm "
        "digest`, `hermitcrm report --md`). Answer the question from that data. "
        "Read only: do not create, edit or delete anything. If the data does not "
        "answer the question, say so plainly. Be concise and concrete.\n\n"
        f"The user asked this while on the page {page} (start of that page below, "
        "for context).\n\n"
        f"Question: {question}\n\n--- page ---\n{context}\n--- end ---\n"
    )


@dataclass
class Answer:
    question: str
    text: str
    scope: str                       # "page" or "crm"
    model: str
    tier: str
    sources: list[str] = field(default_factory=list)

    @property
    def model_label(self) -> str:
        return model_label(self.model)


def ask(enricher: Enricher, question: str, page: str, html: str, data_dir: Path | str,
        scope: str = "auto", timeout: float | None = None) -> Answer:
    """Answer from the page first (scope auto), or go straight to the CRM (scope crm).

    Raises EnrichError when no AI CLI is available or a run fails.
    """
    question = " ".join((question or "").split())
    if not question:
        raise EnrichError("Type a question first.")
    if not enricher.available:
        raise EnrichError(enricher.unavailable_reason())
    if timeout:
        enricher.timeout = float(timeout)
    text = page_text(html)
    if scope != "crm":
        data = enricher.runner(page_prompt(question, page, text), PAGE_SCHEMA, tools="")
        answer = str(data.get("answer") or "").strip()
        if data.get("answerable") and answer:
            return Answer(question, answer, "page", enricher.model, enricher.tier)
    data = enricher.runner(crm_prompt(question, page, text), CRM_SCHEMA, tools=CRM_TOOLS,
                           cwd=str(data_dir), extra_path=str(Path(sys.executable).parent))
    answer = str(data.get("answer") or "").strip()
    if not answer:
        raise EnrichError("The AI returned an empty answer.")
    sources = [str(s) for s in (data.get("sources") or []) if s]
    return Answer(question, answer, "crm", enricher.model, enricher.tier, sources)
