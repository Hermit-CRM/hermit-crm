"""Help: short Markdown pages, read by people (``/help``, ``hermitcrm help``) and by
AI agents (``hermitcrm help <topic>`` from the data folder's CLAUDE.md).

The pages live next to this file as ``<topic>.md`` and ship as package data.
``render`` is a small converter (headings, paragraphs, lists, fenced code,
tables, inline code, bold, links) with no dependency; everything is HTML
escaped. ``topic_for`` maps a request path to the topic its Help link opens.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Fixed order: the index first, then the nav order, then the reference pages.
TOPICS = [
    "index", "pipeline", "calendar", "companies", "contacts", "interactions",
    "messages", "reports", "settings", "import", "extension", "enrich", "ask", "merge", "cli",
    "backups", "data-format", "ai-agents", "feedback",
]


def topics() -> list[str]:
    return list(TOPICS)


def path_for(topic: str) -> Path:
    return HERE / f"{topic}.md"


def read(topic: str) -> str | None:
    """The Markdown of a topic, or None when there is no such topic."""
    if topic not in TOPICS:
        return None
    try:
        return path_for(topic).read_text(encoding="utf-8")
    except OSError:
        return None


def title_of(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def summary_of(text: str) -> str:
    """The one-line summary: the first paragraph after the title."""
    lines = text.splitlines()
    seen_title = False
    for line in lines:
        if line.startswith("# "):
            seen_title = True
            continue
        if seen_title and line.strip() and not line.startswith("#"):
            return line.strip()
    return ""


def titles() -> list[tuple[str, str]]:
    """(topic, title) for every topic that has a page."""
    out = []
    for topic in TOPICS:
        text = read(topic)
        if text is not None:
            out.append((topic, title_of(text) or topic))
    return out


# ------------------------------------------------------------- topic mapping


def topic_for(path: str) -> str:
    """The help topic for a request path (the nav's Help link)."""
    path = (path or "/").split("?", 1)[0].rstrip("/") or "/"
    parts = path.strip("/").split("/")
    if path == "/":
        return "index"
    if path in ("/pipeline", "/today"):
        return "pipeline"
    head = parts[0]
    if head == "help":
        return "index"
    if head == "ask":
        return "ask"
    if head in ("settings", "setup", "inbox", "bcc"):
        return "settings"
    if head == "capture":  # the old path; the page is /extension now
        return "extension"
    if head in ("calendar", "messages", "reports", "import", "extension", "contacts"):
        return head
    if head == "companies":
        tail = parts[-1]
        if tail == "merge":
            return "merge"
        if tail in ("enrich", "fetch") or (len(parts) > 1 and parts[-2] == "enrich"):
            return "enrich"
        if "interactions" in parts:
            return "interactions"
        if "contacts" in parts:
            return "contacts"
        return "companies"
    return "index"


# ------------------------------------------------------------ the converter

_FENCE = re.compile(r"^```")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_UL = re.compile(r"^[-*]\s+(.*)$")
_OL = re.compile(r"^\d+\.\s+(.*)$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_CODE_SPAN = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _safe_href(url: str) -> str:
    """Only http(s), site-relative and fragment links become hrefs."""
    if url.startswith(("http://", "https://", "/", "#")):
        return url
    return ""


def inline(text: str) -> str:
    """Escape, then code spans, bold and links (code spans stay literal)."""
    out = []
    for i, part in enumerate(_CODE_SPAN.split(text)):
        if i % 2:  # inside backticks
            out.append(f"<code>{html.escape(part)}</code>")
            continue
        part = html.escape(part, quote=True)
        part = _BOLD.sub(r"<strong>\1</strong>", part)

        def link(m: re.Match) -> str:
            href = _safe_href(html.unescape(m.group(2)))
            if not href:
                return m.group(0)
            return f'<a href="{html.escape(href, quote=True)}">{m.group(1)}</a>'

        out.append(_LINK.sub(link, part))
    return "".join(out)


def _table_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def render(text: str) -> str:
    """Markdown to HTML. Unknown constructs render as paragraphs."""
    lines = text.splitlines()
    out: list[str] = []
    para: list[str] = []
    list_tag = ""
    items: list[str] = []
    i = 0

    def flush_para() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(s.strip() for s in para))}</p>")
            para.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"<{list_tag}>" + "".join(f"<li>{inline(it)}</li>" for it in items)
                       + f"</{list_tag}>")
            items.clear()
            list_tag = ""

    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            flush_para()
            flush_list()
            code: list[str] = []
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i]):
                code.append(lines[i])
                i += 1
            out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
            i += 1
            continue
        if not line.strip():
            flush_para()
            flush_list()
            i += 1
            continue
        m = _HEADING.match(line)
        if m:
            flush_para()
            flush_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2).strip())}</h{level}>")
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush_para()
            flush_list()
            head = _table_row(line)
            rows = []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(_table_row(lines[i]))
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head)
                       + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
                                 for row in rows)
                       + "</tbody></table>")
            continue
        m = _UL.match(line) or _OL.match(line)
        if m and not line.startswith(" "):
            flush_para()
            tag = "ul" if _UL.match(line) else "ol"
            if list_tag != tag:
                flush_list()
                list_tag = tag
            items.append(m.group(1))
            i += 1
            continue
        if list_tag and line.startswith("  "):
            items[-1] += " " + line.strip()  # continuation of the last item
            i += 1
            continue
        flush_list()
        para.append(line)
        i += 1
    flush_para()
    flush_list()
    return "\n".join(out)
