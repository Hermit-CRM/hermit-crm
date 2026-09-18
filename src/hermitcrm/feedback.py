"""The Feedback form (Help -> Feedback): turn what a tester typed into a file they can send.

Hermit CRM has no server to post to, and adding one would undo the whole point, so
this module never touches the network. It builds a Markdown report, the web app writes
it into the data folder like any other record, and the tester sends it themselves -- by
mail link if ``feedback_email`` is configured, otherwise by copying the text.

What goes in the report is deliberately narrow. Diagnostics are the facts that make a
bug reproducible (version, Python, platform, how much data, which optional features
are switched on) and nothing that identifies anybody: no names, no company names, no
mail addresses, and no filesystem paths -- a data folder path is usually
/Users/<their name>/..., which is exactly the kind of leak nobody expects from a
"send diagnostics" checkbox. The tester sees the whole report before anything is sent.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime

from .models import slugify

# (value, what the tester sees). The first is the default.
KINDS = [
    ("bug", "Something is broken"),
    ("confusing", "Something confused me"),
    ("missing", "Something is missing"),
    ("praise", "Something worked well"),
]
KIND_VALUES = [value for value, _ in KINDS]

# mailto: has no standard length limit and clients differ; Outlook has historically
# truncated around 2 000 characters. The file on disk always holds the whole thing.
MAILTO_LIMIT = 1800


def diagnostics(version: str, python: str, platform: str, counts: dict,
                data_format=None, features: dict | None = None) -> list[str]:
    """The automatic facts, as lines. Every value here is a number, a flag or a version."""
    lines = [
        f"Hermit CRM {version} on Python {python} ({platform})",
        "Data folder: %d companies, %d contacts, %d interactions%s" % (
            int(counts.get("companies", 0)), int(counts.get("contacts", 0)),
            int(counts.get("interactions", 0)),
            f", format {data_format}" if data_format is not None else ""),
    ]
    for name, value in (features or {}).items():
        lines.append(f"{name}: {value}")
    return lines


def report(kind: str, summary: str, detail: str, reporter: str = "",
           facts: list[str] | None = None, now: datetime | None = None,
           version: str = "") -> str:
    """The Markdown a tester sends. Front matter so a reader can sort a pile of them."""
    now = now or datetime.now()
    kind = kind if kind in KIND_VALUES else KIND_VALUES[0]
    summary = " ".join(str(summary or "").split()) or "(no summary)"
    head = [
        "---",
        "kind: feedback",
        f"about: {kind}",
        f"version: {version}",
        f"date: {now.strftime('%Y-%m-%dT%H:%M:%S')}",
        "---",
        "",
        f"# {summary}",
        "",
        str(detail or "").strip() or "(nothing else written)",
    ]
    if reporter.strip():
        head += ["", "## From", "", reporter.strip()]
    if facts:
        head += ["", "## About this install (filled in automatically)", ""]
        head += [f"- {line}" for line in facts]
    return "\n".join(head).rstrip() + "\n"


def filename(summary: str, now: datetime | None = None) -> str:
    """feedback/2026-09-18-1432-sorting-puts-empty-rows-first.md"""
    now = now or datetime.now()
    slug = slugify(summary or "feedback", default="feedback")[:60].strip("-") or "feedback"
    return f"feedback/{now.strftime('%Y-%m-%d-%H%M')}-{slug}.md"


def mailto(address: str, summary: str, body: str, limit: int = MAILTO_LIMIT) -> str:
    """A prefilled mail link, or '' when there is no address to send to."""
    if not str(address or "").strip():
        return ""
    if len(body) > limit:
        body = body[:limit].rstrip() + "\n\n[...] the full report is in the file named above."
    query = urllib.parse.urlencode({"subject": f"Hermit CRM feedback: {summary}",
                                    "body": body}, quote_via=urllib.parse.quote)
    return f"mailto:{urllib.parse.quote(str(address).strip())}?{query}"
