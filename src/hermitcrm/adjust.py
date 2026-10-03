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

"""Make it yours: hand a change to the user's own AI agent, and the page around it.

Hermit does not build the change. It shows what is possible (the starters),
hands the request to the agent the user already has in one click (a deep link,
or a command or prompt to copy), and makes the result visible afterwards (what
you've built, `hermitcrm check`). The agent follows the recipes in
`hermitcrm help adjust`.

The handoff is built twice: `handoff()` here is the reference, and
static/adjust.js builds the same prompt, link and command in the browser while
the user types, from data attributes the server renders. Change one, change
the other; tests/test_adjust.py runs both on the same inputs when node is there.

The dashboards, layout and routines modules each own a file; BUILT_PROVIDERS
and VALIDATORS call their built_items() and validate(), importing them late so
loading this module imports none of them.
"""

from __future__ import annotations

import difflib
import importlib
import logging
import re
import shlex
import subprocess
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import quantiles
from typing import Callable
from urllib.parse import quote

from . import fields as custom
from . import messaging, task_types, usertheme

logger = logging.getLogger("crm.adjust")

# ------------------------------------------------------------------ the agent

# Which agent a request goes to, and how. A link agent gets a deep link that
# opens it with the request typed in; a command agent gets a shell command to
# paste; "copy" gets only the prompt.
AGENTS = {
    "claude": {"label": "Claude Code", "how": "link", "button": "Open in Claude Code"},
    "cursor": {"label": "Cursor", "how": "link", "button": "Open in Cursor"},
    "codex": {"label": "Codex", "how": "command", "button": "Copy command"},
    "gemini": {"label": "Gemini CLI", "how": "command", "button": "Copy command"},
    "copy": {"label": "", "how": "copy", "button": ""},
}
AGENT_KEY = "adjust_agent"

# On macOS a deep link over about 1,024 bytes fails without a word (Claude Code
# issue 81485), and the link percent-encodes the prompt, so a prompt over this
# many UTF-8 bytes is copied instead of linked.
LINK_LIMIT = 500

# The whitespace JavaScript's \s matches, spelled out so Python and adjust.js
# collapse exactly the same characters.
_SPACE = re.compile("[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f"
                    "\u3000\ufeff]+")
# What encodeURIComponent leaves alone; quote() always keeps A-Z a-z 0-9 _ . - ~.
_URI_SAFE = "!'()*"


def agent_for(config: dict) -> str:
    """The agent requests go to: `adjust_agent`, else the AI CLI Enrich uses
    when it is one of ours (`enrich_provider`, then the name `enrich_command`
    starts with, the way enrich.resolve_provider reads it), else "copy"."""
    chosen = str(config.get(AGENT_KEY) or "").strip().lower()
    if chosen in AGENTS:
        return chosen
    provider = str(config.get("enrich_provider") or "").strip().lower()
    if provider in ("claude", "codex", "gemini"):
        return provider
    command = str(config.get("enrich_command") or "").strip()
    if command:
        try:
            base = Path(shlex.split(command)[0]).name.lower()
        except (ValueError, IndexError):
            base = ""
        for name in ("claude", "codex", "gemini"):
            if base.startswith(name):
                return name
    return "copy"


def one_line(text: str) -> str:
    """Runs of whitespace (newlines too) as one space, trimmed."""
    return _SPACE.sub(" ", str(text or "")).strip(" ")


def prompt_for(agent: str, request: str, page_title: str = "", path: str = "") -> str:
    """What the agent receives. With no path (the hub) there is no "Asked on"."""
    request, page_title = one_line(request), one_line(page_title)
    asked = ""
    if path:
        asked = f"Asked on {page_title} ({path}): " if page_title else f"Asked on {path}: "
    if agent == "claude":
        return f"/hermit {asked}{request}"
    return f'Run "hermitcrm help adjust" first and follow it. {asked}{request}'


def byte_size(text: str) -> int:
    return len(text.encode("utf-8"))


def uri_component(text: str) -> str:
    """encodeURIComponent, in Python."""
    return quote(text, safe=_URI_SAFE)


def handoff(agent: str, folder: str, request: str, page_title: str = "",
            path: str = "") -> dict:
    """Everything the buttons need for one request.

    `link` is the deep link (empty when the agent has none or the prompt is
    over LINK_LIMIT bytes, `too_long` says which), `command` the shell line a
    command agent pastes, `prompt` what Copy prompt copies.
    """
    agent = agent if agent in AGENTS else "copy"
    prompt = prompt_for(agent, request, page_title, path)
    size = byte_size(prompt)
    out = {"agent": agent, "prompt": prompt, "bytes": size, "link": "", "command": "",
           "too_long": False}
    if AGENTS[agent]["how"] == "link":
        if size > LINK_LIMIT:
            out["too_long"] = True
        elif agent == "claude":
            out["link"] = (f"claude-cli://open?cwd={uri_component(folder)}"
                           f"&q={uri_component(prompt)}")
        else:
            out["link"] = ("cursor://anysphere.cursor-deeplink/prompt?text="
                           + uri_component(prompt))
    elif agent == "codex":
        out["command"] = f"cd {shlex.quote(folder)} && codex {shlex.quote(prompt)}"
    elif agent == "gemini":
        out["command"] = f"cd {shlex.quote(folder)} && gemini -i {shlex.quote(prompt)}"
    return out


def agent_info(config: dict, root: Path, home: Path | None = None) -> dict:
    """What the pages say about the agent: which, its button, the folder."""
    agent = agent_for(config)
    folder = str(Path(root).resolve())
    home = str((home or Path.home()).resolve())
    shown = "~" + folder[len(home):] if folder == home or folder.startswith(home + "/") \
        else folder
    return {"agent": agent, **AGENTS[agent], "folder": folder, "folder_shown": shown,
            "chosen": str(config.get(AGENT_KEY) or "").strip().lower(),
            "limit": LINK_LIMIT}


# ------------------------------------------------------------------ page kinds

PAGE_KINDS = ("company", "contact", "companies", "contacts", "pipeline", "home", "tasks",
              "messages", "reports", "calendar", "settings", "other")


def page_kind(path: str) -> str:
    """Which kind of page a path is, for the starters that fit it."""
    path = (path or "/").split("?", 1)[0].rstrip("/") or "/"
    parts = path.strip("/").split("/")
    if path in ("/", "/welcome"):
        return "home"
    head = parts[0]
    if head == "companies":
        if len(parts) >= 4 and parts[2] == "contacts" and parts[3] != "new":
            return "contact"
        if len(parts) >= 2 and parts[1] != "new":
            return "company"
        return "companies"
    if head in ("contacts", "pipeline", "tasks", "messages", "reports", "calendar",
                "settings"):
        return head
    return "other"


def page_path(path: str, query: str = "") -> str:
    """The page as the agent should hear of it: path and query, minus the
    one-time bits (a flash message, the tour)."""
    pairs = [p for p in (query or "").split("&")
             if p and p.split("=", 1)[0] not in ("flash", "tour")]
    return path + ("?" + "&".join(pairs) if pairs else "")


# ---------------------------------------------------------------- the starters

FAMILIES = ("Dashboards", "Fields", "Pages", "Bulk changes", "Routines", "Messages", "Look",
            "Connect")
RECIPES = {"Dashboards": "adjust-dashboards", "Fields": "adjust-fields",
           "Pages": "adjust-layout", "Bulk changes": "adjust-bulk",
           "Routines": "adjust-routines", "Messages": "adjust-messages",
           "Look": "adjust-look", "Connect": "adjust-connect", "Feature": "adjust-feature"}
UNDO = "undo in one click"
DRY_RUN = "dry run first"
PAUSED = "starts paused"
PREVIEW = "preview first"


@dataclass(frozen=True)
class Starter:
    """One idea: `text` is the request, with [placeholders] the user edits and
    {slots} filled from their own data (see prefill)."""

    id: str
    family: str
    title: str
    text: str
    changes: str
    safety: str
    kinds: tuple[str, ...]



# The eight use cases of the design (section 4) first, then a few per page
# kind. The panel shows the first four that fit the page, in this order.
STARTERS = [
    Starter("dashboard-monday", "Dashboards", "A Monday dashboard",
            "Make a dashboard called [Monday review] with: prospects with [{score}] above "
            "[{score_cut}] that I have not contacted yet, the replies I owe, and the deals "
            "by stage with their value. Pin it to the sidebar.",
            "dashboards/monday-review.toml", UNDO, ("home", "pipeline", "other")),
    Starter("look", "Look", "Change the look",
            "Make Hermit [cooler and more compact]: a [blue] accent and tighter table rows.",
            "theme.css", UNDO, ("home", "settings", "calendar", "reports", "other")),
    Starter("field-new", "Fields", "Track something new",
            "Add a [date] field [contract renewal] to [companies], shown on the company "
            "page and in the companies list.",
            "fields.toml", UNDO, ("company", "settings", "other")),
    Starter("bulk-tag", "Bulk changes", "Clean up in bulk",
            "Tag every prospect in [{country}] with more than [50] FTE as [priority]. Show "
            "me the dry run first.",
            "company files, one commit", DRY_RUN, ("companies",)),
    Starter("routine-nudge", "Routines", "Nudge quiet threads",
            "Every [morning], for people I messaged on [{channel}] [{nudge_days}] days ago "
            "without a reply, draft a short follow-up into To file. Never send anything.",
            "routines.toml; drafts land in To file", PAUSED,
            ("messages", "contact", "contacts", "home")),
    Starter("layout-company", "Pages", "Rearrange a page",
            "On company pages, show the [timeline] first and hide the [Merge] section. "
            "Hide the [value per month] field everywhere.",
            "layout.toml", UNDO, ("company",)),
    Starter("messages-template", "Messages", "Templates in my voice",
            "Write a [{channel} connection note] template for [finance leads at payment "
            "companies], in [English, Dutch and German]. Use my playbook.",
            "messages.toml", UNDO, ("messages", "contact", "settings")),
    Starter("import", "Connect", "Bring data in",
            "Import [~/Downloads/leads.csv] (an export from [my outreach tool]). Match "
            "existing companies by website; show me what would be created first.",
            "new company and contact files, one commit", PREVIEW,
            ("companies", "contacts")),
    # ---- more per page kind
    Starter("bulk-lookalike", "Bulk changes", "Tag lookalikes",
            "Tag companies like this one ([{company_tag}], [{company_country}]) as "
            "[lookalike]. Show me the dry run first.",
            "company files, one commit", DRY_RUN, ("company",)),
    Starter("pipeline-cards", "Fields", "Show more on the cards",
            "Show [{score}] and [{field2}] on the pipeline cards.",
            "fields.toml", UNDO, ("pipeline", "company")),
    Starter("dashboard-ranking", "Dashboards", "Rank your prospects",
            "Make a dashboard that ranks [prospects] by [{score}], highest first, with their "
            "[country] and [next step]. Pin it to the sidebar.",
            "dashboards/ranking.toml", UNDO, ("companies", "pipeline")),
    Starter("columns-companies", "Pages", "Choose the columns",
            "In the companies list, show only [name, stage, {score}, country, next step].",
            "layout.toml", UNDO, ("companies",)),
    Starter("field-contact", "Fields", "A field on people",
            "Add a [select] field [seniority] to [contacts] with the options [junior, "
            "senior, executive], shown in the contacts list.",
            "fields.toml", UNDO, ("contact", "contacts")),
    Starter("layout-contact", "Pages", "Rearrange contact pages",
            "On contact pages, show the [timeline] first and hide the [message drafts].",
            "layout.toml", UNDO, ("contact",)),
    Starter("columns-contacts", "Pages", "Choose the columns",
            "In the contacts list, show only [name, company, title, email].",
            "layout.toml", UNDO, ("contacts",)),
    Starter("bulk-roles", "Bulk changes", "Set roles in bulk",
            "Set the role of every contact whose title contains [CEO] to [decision-maker]. "
            "Show me the dry run first.",
            "contact files, one commit", DRY_RUN, ("contacts",)),
    Starter("bulk-quiet", "Bulk changes", "Close what went quiet",
            "Move every [prospect] I have not touched in [90] days to [lost] with the reason "
            "[no response]. Show me the dry run first.",
            "company files, one commit", DRY_RUN, ("pipeline",)),
    Starter("routine-brief", "Routines", "A morning brief",
            "Every [morning], put a short brief of [today's meetings and overdue tasks] in "
            "To file.",
            "routines.toml; the brief lands in To file", PAUSED,
            ("home", "calendar", "tasks")),
    Starter("dashboard-week", "Dashboards", "This week at a glance",
            "Make a dashboard called [This week] with my [overdue tasks], the tasks due "
            "[this week] by type, and the companies with no next step.",
            "dashboards/this-week.toml", UNDO, ("tasks", "calendar")),
    Starter("bulk-next-step", "Bulk changes", "Give everyone a next step",
            "Give every [engaged] company without a next step the task [follow up] due "
            "[next Monday]. Show me the dry run first.",
            "company files, one commit", DRY_RUN, ("tasks",)),
    Starter("task-types", "Fields", "Your own task types",
            "Add the task types [demo] and [proposal], in [blue] and [amber].",
            "config.toml (task_types)", UNDO, ("tasks", "settings")),
    Starter("dashboard-messages", "Dashboards", "How your messages land",
            "Make a dashboard of my [{channel}] messages from the last [30] days by outcome, "
            "with the ones still [unknown] first.",
            "dashboards/messages.toml", UNDO, ("messages",)),
    Starter("outcomes", "Fields", "Your own outcomes",
            "Change my message outcomes to [replied, meeting booked, no reply].",
            "config.toml (outcomes)", UNDO, ("messages", "settings")),
    Starter("routine-outcomes", "Routines", "A weekly outcome check",
            "Every [Friday], list my messages from the last [{window}] days that still have "
            "no outcome, and put that list in To file.",
            "routines.toml; the list lands in To file", PAUSED, ("messages", "reports")),
    Starter("dashboard-report", "Dashboards", "Your own report",
            "Make a dashboard called [Pipeline health] with the [funnel] for the last [30] "
            "days, the deals by [stage] and the [overdue next steps]. Pin it to the sidebar.",
            "dashboards/pipeline-health.toml", UNDO, ("reports",)),
    Starter("hide-field", "Pages", "Hide what you never use",
            "Hide the [{unused_field}] field everywhere; I never use it.",
            "layout.toml", UNDO, ()),
    Starter("field-describe", "Fields", "Describe a field you already have",
            "Describe [{stray_key}] in fields.toml as a field, so I can see, filter and sort "
            "it.",
            "fields.toml", UNDO, ()),
]
# The bucket-c path: not a card, the box at the bottom of the hub.
FEATURE = Starter("feature", "Feature", "Something Hermit can't do yet",
                  "I want [a quote generator]. Check first whether a field, page layout, "
                  "dashboard or routine covers it.",
                  "nothing in your data folder", "", ())
BY_ID = {s.id: s for s in [*STARTERS, FEATURE]}

# Settings sections and other pages that open the hub on a matching starter.
SETTINGS_STARTERS = {"fields": "field-new", "messaging": "messages-template",
                     "task-types": "task-types", "outcomes": "outcomes"}
REPORTS_STARTER = "dashboard-report"

# Defaults when the data has nothing better (the design's own examples).
DEFAULTS = {"score": "fit", "score_cut": "70", "field2": "FTE estimate", "country": "Germany",
            "channel": "LinkedIn", "nudge_days": "7", "window": "14",
            "company_tag": "robotics", "company_country": "DE",
            "unused_field": "value per month", "stray_key": "segment"}
CHANNEL_NAMES = {"linkedin": "LinkedIn", "email": "email", "call": "phone"}
# Built-in company fields nobody has to use, with the name the pages give them.
OPTIONAL_FIELDS = {"value_eur_month": "value per month",
                   "product_oneliner": "product oneliner", "linkedin": "LinkedIn"}
# Front-matter keys Hermit writes itself that are not fields to describe.
NOT_FIELDS = {"sample"}


def _number(value):
    try:
        return float(str(value).replace(",", ".").lstrip("~"))
    except (TypeError, ValueError):
        return None


def _shown_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def score_field(defs: list):
    """The user's own score: a number field on companies, preferring one whose
    key says score or fit."""
    numbers = [d for d in defs if d.applies_to == "company" and d.type == "number"]
    for d in numbers:
        if "score" in d.key or "fit" in d.key:
            return d
    return numbers[0] if numbers else None


def prefill(store, defs: list, config: dict, company=None) -> dict:
    """Values for the starters' {slots}, from the user's own data (design 7.1):
    their real field names, most common country, most used channel."""
    out = dict(DEFAULTS)
    companies = [c for c in store.companies.values() if not getattr(c, "is_sample", False)]
    score = score_field(defs)
    if score is not None:
        out["score"] = score.label
        values = sorted(v for v in (_number((c.extra or {}).get(score.key))
                                    for c in companies) if v is not None)
        if len(values) >= 4:
            out["score_cut"] = _shown_number(quantiles(values, n=4)[2])
        elif values:
            out["score_cut"] = _shown_number(values[-1])
    others = [d for d in defs if d.applies_to == "company" and d is not score]
    if others:
        out["field2"] = others[0].label
    countries = Counter(c.country for c in companies if c.country)
    if countries:
        out["country"] = countries.most_common(1)[0][0]
    channels = Counter(i.channel for c in companies for i in c.interactions if i.is_message)
    if channels:
        top = channels.most_common(1)[0][0]
        out["channel"] = CHANNEL_NAMES.get(top, top)
    out["nudge_days"] = str(config.get("followup_nudge_days") or out["nudge_days"])
    out["window"] = str(config.get("message_window_days") or out["window"])
    if company is not None:
        out.update(company_values(company))
    unused = unused_fields(companies)
    if unused:
        out["unused_field"] = OPTIONAL_FIELDS[unused[0]]
    stray = stray_keys(companies, defs)
    if stray:
        out["stray_key"] = stray[0][0]
    return out


def company_values(company) -> dict:
    """The slots that speak of the company page the user is on."""
    out = {}
    if company.tags:
        out["company_tag"] = company.tags[0]
    if company.country:
        out["company_country"] = company.country
    return out


def unused_fields(companies: list) -> list[str]:
    """Optional built-in company fields that no company fills in (needs a few
    companies before it says so)."""
    if len(companies) < 5:
        return []
    return [k for k in OPTIONAL_FIELDS if not any(getattr(c, k, None) for c in companies)]


def stray_keys(companies: list, defs: list) -> list[tuple[str, int]]:
    """(key, companies) for front-matter keys no field describes, most used first."""
    described = {d.key for d in defs if d.applies_to == "company"} | NOT_FIELDS
    counts = Counter(k for c in companies for k in (c.extra or {}) if k not in described)
    return [(k, n) for k, n in counts.most_common() if n >= 3]


# "routines.toml; drafts land in To file" -> the file, then the rest.
_CHANGES_FILE = re.compile(r"^([\w./-]+\.(?:toml|css|md))(.*)$")


def render_starter(starter: Starter, values: dict) -> dict:
    """A starter as the templates use it: the text with its slots filled."""
    try:
        text = starter.text.format_map(values)
    except (KeyError, ValueError):
        text = starter.text.format_map(DEFAULTS)
    found = _CHANGES_FILE.match(starter.changes)
    return {"id": starter.id, "family": starter.family, "title": starter.title,
            "text": text, "changes": starter.changes, "safety": starter.safety,
            "changes_file": found.group(1) if found else "",
            "changes_note": found.group(2) if found else starter.changes,
            "safety_class": "dry" if starter.safety in (DRY_RUN, PREVIEW) else "",
            "recipe": RECIPES.get(starter.family, "adjust")}


def starters_for(kind: str, values: dict, limit: int = 4) -> list[dict]:
    """The starters the Adjust tab shows on a page of this kind."""
    fitting = [s for s in STARTERS if kind in s.kinds] or \
        [s for s in STARTERS if "other" in s.kinds]
    return [render_starter(s, values) for s in fitting[:limit]]


def gallery(values: dict) -> list[dict]:
    """Every starter for the hub's cards (the two that only suggestions open
    stay out of the grid)."""
    return [render_starter(s, values) for s in STARTERS if s.kinds]


def starter(starter_id: str, values: dict) -> dict | None:
    found = BY_ID.get(starter_id)
    return render_starter(found, values) if found else None


# ------------------------------------------------------------ suggested for you


def suggestions(store, defs: list, config: dict, values: dict, today, window: int,
                outcomes: list[str], limit: int = 3) -> list[dict]:
    """At most three plain rules about the data (design 7.3), no AI."""
    out = []
    companies = [c for c in store.companies.values() if not getattr(c, "is_sample", False)]
    root = Path(store.root)
    dashboards = [p.read_text(encoding="utf-8", errors="replace")
                  for p in sorted((root / "dashboards").glob("*.toml"))] \
        if (root / "dashboards").is_dir() else []
    score = score_field(defs)
    if score is not None:
        scored = sum(1 for c in companies if (c.extra or {}).get(score.key) not in (None, ""))
        if scored and not any(score.key in text for text in dashboards):
            out.append({"text": f"{scored} {'company has' if scored == 1 else 'companies have'}"
                                f" a **{score.label}** score, but no list ranks them.",
                        "starter": "dashboard-ranking", "action": "Make a ranking dashboard"})
    unknown = sum(1 for c in companies for i in c.interactions if i.is_message
                  and c.message_status(i, today, window, outcomes) == "unknown")
    if unknown >= 5:
        out.append({"text": f"{unknown} messages from the last {window} days still have "
                            "outcome **unknown**.",
                    "starter": "routine-outcomes", "action": "Add a weekly reminder routine"})
    unused = unused_fields(companies)
    if unused:
        out.append({"text": f"No company uses **{OPTIONAL_FIELDS[unused[0]]}**.",
                    "starter": "hide-field", "action": "Hide the field"})
    stray = stray_keys(companies, defs)
    if stray:
        key, n = stray[0]
        out.append({"text": f"{n} companies have **{key}** in their files, but no field "
                            "describes it.",
                    "starter": "field-describe", "action": "Describe it as a field"})
    if not dashboards and score is None:
        out.append({"text": "You have no dashboards yet.", "starter": "dashboard-monday",
                    "action": "Make your first dashboard"})
    return out[:limit]


# ------------------------------------------------------------- what you've built

Provider = Callable[[Path], list]


def built_items(root: Path) -> list[dict]:
    """What the core knows the user made: their fields, their look, their
    draft wording. Layouts, dashboards and routines list themselves."""
    root = Path(root)
    items = []
    try:
        defs = custom.load(root)
    except (custom.FieldError, tomllib.TOMLDecodeError, OSError):
        defs = None
    if defs is None:
        items.append({"kind": "fields", "title": "Your fields", "url": "/settings#fields",
                      "detail": "fields.toml has a problem; hermitcrm check says which",
                      "adjust": "Fix fields.toml: hermitcrm check reports a problem."})
    elif defs:
        per_scope = Counter(d.applies_to for d in defs)
        items.append({"kind": "fields", "title": ", ".join(d.label for d in defs),
                      "url": "/settings#fields",
                      "detail": ", ".join(f"{n} {scope} field{'s' if n != 1 else ''}"
                                          for scope, n in per_scope.items()),
                      "adjust": "Change my fields: [what to change]."})
    theme = usertheme.status(root)
    if theme["active"]:
        problems = len(theme["problems"])
        items.append({"kind": "look", "title": "Your own look", "url": "/settings#appearance",
                      "detail": "theme.css" + (f", {problems} line{'s' if problems != 1 else ''}"
                                               " the app blocks" if problems else ""),
                      "adjust": "Change my look in theme.css: [what to change]."})
    if (root / messaging.MESSAGES_FILE).is_file():
        try:
            with open(root / messaging.MESSAGES_FILE, "rb") as fh:
                languages = sorted((tomllib.load(fh).get("languages") or {}).keys())
        except (tomllib.TOMLDecodeError, OSError):
            languages = []
        items.append({"kind": "messages", "title": "Your own draft wording",
                      "url": "/help/messages",
                      "detail": "messages.toml" + (f": {', '.join(languages)}"
                                                   if languages else ""),
                      "adjust": "Change my draft templates in messages.toml: "
                                "[what to change]."})
    return items


def _late(module: str, name: str) -> Provider:
    """`hermitcrm.<module>.<name>(root)`, imported on the first call."""
    def call(root: Path) -> list:
        return getattr(importlib.import_module(f"{__package__}.{module}"), name)(root)
    call.__qualname__ = f"{module}.{name}"
    return call


# Every module that builds something lists it here.
BUILT_PROVIDERS: list[Provider] = [built_items, _late("dashboards", "built_items"),
                                   _late("layout", "built_items"),
                                   _late("routines", "built_items")]


def all_built(root: Path) -> list[dict]:
    """Every provider's items; a provider that fails costs its own rows only.
    The sample account's dashboard and routine say so while they are unchanged."""
    from . import sample

    items = []
    for provider in BUILT_PROVIDERS:
        try:
            items.extend(provider(Path(root)) or [])
        except Exception:
            logger.exception("built items failed in %r", provider)
    marked = sample.untouched_urls(root)
    for item in items:
        if item.get("url") in marked:
            item["detail"] = f"{item.get('detail') or ''} · sample".lstrip(" ·")
    return items


# Files whose presence, or an "ai: adjust:" commit, means the user made Hermit
# their own (the welcome step).
ADJUSTED_FILES = ("theme.css", "layout.toml", "routines.toml")


def has_adjusted(root: Path) -> bool:
    return has_adjusted_files(root) or has_adjust_commit(root)


def has_adjusted_files(root: Path) -> bool:
    """A few stats: a theme.css, layout.toml, routines.toml or a dashboard,
    not counting the sample account's while they are as it wrote them."""
    from . import sample

    root = Path(root)
    sample_files = sample.untouched(root)
    if any((root / name).is_file() and name not in sample_files for name in ADJUSTED_FILES):
        return True
    folder = root / "dashboards"
    return folder.is_dir() and any(f"dashboards/{p.name}" not in sample_files
                                   for p in folder.glob("*.toml"))


def has_adjust_commit(root: Path) -> bool:
    """One git log: any commit named "ai: adjust: ..."."""
    root = Path(root)
    try:
        proc = subprocess.run(["git", "log", "-1", "--format=%h", "--grep=^ai: adjust:"],
                              cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


# ------------------------------------------------------------------ validation


def near(name: str, choices, cutoff: float = 0.6) -> str:
    """" (did you mean X?)" for a near miss, else ""."""
    match = difflib.get_close_matches(str(name), list(choices), n=1, cutoff=cutoff)
    return f" (did you mean {match[0]}?)" if match else ""


def _toml_problem(name: str, exc: tomllib.TOMLDecodeError) -> str:
    """"<file>: line N: <what>". Python 3.14 gives the line as an attribute;
    before that it is only at the end of the message."""
    text = str(exc)
    line = getattr(exc, "lineno", None)
    found = re.search(r"\s*\(at (?:line (\d+), column \d+|end of document)\)$", text)
    if found:
        line = line or (int(found.group(1)) if found.group(1) else None)
        text = text[:found.start()]
    message = getattr(exc, "msg", None) or text
    return f"{name}: line {line}: {message}" if line else f"{name}: end of file: {message}"


def _load_toml(path: Path, problems: list[str]) -> dict | None:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        problems.append(_toml_problem(path.name, exc))
    except OSError as exc:
        problems.append(f"{path.name}: file: cannot be read ({exc.strerror or exc})")
    return None


# config.toml keys an agent may write (design 6.3), plus the agent choice.
EXTENSION_KEYS = ("task_types", "outcomes", "silent_days", "message_window_days",
                  AGENT_KEY)


def validate_config(root: Path) -> list[str]:
    path = Path(root) / "config.toml"
    if not path.is_file():
        return []
    problems: list[str] = []
    data = _load_toml(path, problems)
    if data is None:
        return problems
    from .store import DEFAULT_CONFIG

    known = set(DEFAULT_CONFIG) | set(EXTENSION_KEYS)
    for key in data:
        if key not in known:
            hint = near(key, EXTENSION_KEYS)
            if hint:
                problems.append(f"config.toml: {key}: not a setting Hermit reads{hint}")
    if AGENT_KEY in data:
        value = str(data[AGENT_KEY]).strip().lower()
        if value and value not in AGENTS:
            problems.append(f"config.toml: {AGENT_KEY}: {data[AGENT_KEY]!r} is not one of "
                            f"{', '.join(AGENTS)}{near(value, AGENTS)}")
    if "task_types" in data:
        raw = data["task_types"]
        if not isinstance(raw, list):
            problems.append("config.toml: task_types: must be a list of names or "
                            "{ name = ..., colour = ... } tables")
        else:
            seen = set()
            for i, entry in enumerate(raw, 1):
                entry = {"name": entry} if isinstance(entry, str) else entry
                if not isinstance(entry, dict) or not task_types.clean(entry.get("name")):
                    problems.append(f"config.toml: task_types entry {i}: needs a name")
                    continue
                name = task_types.clean(entry.get("name"))
                if name.lower() in seen:
                    problems.append(f"config.toml: task_types entry {i}: {name} is there twice")
                seen.add(name.lower())
                colour = str(entry.get("colour") or "").strip().lower()
                if colour and colour not in task_types.PALETTE:
                    problems.append(f"config.toml: task_types entry {i}: colour {colour!r} "
                                    f"is not one of {', '.join(task_types.PALETTE)}"
                                    f"{near(colour, task_types.PALETTE)}")
    if "outcomes" in data:
        raw = data["outcomes"]
        items = [str(o).strip() for o in raw] if isinstance(raw, list) else None
        if not items or not all(items):
            problems.append("config.toml: outcomes: must be a list of at least one "
                            "non-empty name")
        elif len({o.lower() for o in items}) != len(items):
            problems.append("config.toml: outcomes: an outcome is there twice")
    for key in ("silent_days", "message_window_days"):
        if key in data and (not isinstance(data[key], int) or isinstance(data[key], bool)
                            or data[key] < 1):
            problems.append(f"config.toml: {key}: must be a whole number of days, 1 or more")
    return problems


def validate_fields(root: Path) -> list[str]:
    path = Path(root) / custom.FILENAME
    if not path.is_file():
        return []
    problems: list[str] = []
    data = _load_toml(path, problems)
    if data is None:
        return problems
    try:
        custom.parse(data)
    except custom.FieldError as exc:
        problems += [f"{custom.FILENAME}: {where}: {what}" for where, what in exc.errors.items()]
    return problems


_TOKEN_DECL = re.compile(r"(--[A-Za-z0-9_-]+)\s*:")


def shipped_tokens() -> set[str]:
    text = (Path(__file__).resolve().parent / "static" / "tokens.css").read_text(
        encoding="utf-8")
    return set(_TOKEN_DECL.findall(text))


def validate_theme(root: Path) -> list[str]:
    found = usertheme.path(root)
    if found is None:
        return []
    text = found.read_bytes().decode("utf-8", errors="replace")
    problems = [f"{usertheme.FILENAME}: line {line}: {what}"
                for line, what in usertheme.lint(text)]
    # A token that is almost a real one is a typo that changes nothing.
    tokens = shipped_tokens()
    code = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    for m in _TOKEN_DECL.finditer(code):
        name = m.group(1)
        if name not in tokens:
            # Compared without the "--" every token shares, and strictly: a
            # variable of the user's own is fine, a typo of a token is not.
            match = difflib.get_close_matches(name[2:], [t[2:] for t in tokens], n=1,
                                              cutoff=0.8)
            hint = f" (did you mean --{match[0]}?)" if match else ""
            if hint:
                line = code.count("\n", 0, m.start()) + 1
                problems.append(f"{usertheme.FILENAME}: line {line}: {name} is not a token "
                                f"the app uses{hint}")
    return problems


def validate_messages(root: Path) -> list[str]:
    """messages.toml reads, and every language in it renders a draft."""
    path = Path(root) / messaging.MESSAGES_FILE
    if not path.is_file():
        return []
    problems: list[str] = []
    if _load_toml(path, problems) is None:
        return problems
    try:
        messages = messaging.load_messages(root)
    except Exception as exc:  # deep_merge on a value of the wrong shape
        return [f"{messaging.MESSAGES_FILE}: file: {exc}"]
    try:
        defs = custom.load(root)
    except Exception:
        defs = []
    from .models import Company, Contact

    sample_company = Company(name="Example Ltd", slug="example", website="example.com")
    person = Contact(slug="jane-roe", first_name="Jane", last_name="Roe")
    languages = messages.get("languages")
    if not isinstance(languages, dict):
        return [f"{messaging.MESSAGES_FILE}: languages: must be a table of languages"]
    for code in languages:
        for signal in messaging.SIGNALS:
            try:
                messaging.drafts(sample_company, person, signal, messages=messages,
                                 defs=defs, language=code)
            except KeyError as exc:
                name = str(exc).strip("'\"")
                slots = sorted(messaging.RESERVED_SLOTS | {d.key for d in defs})
                problems.append(f"{messaging.MESSAGES_FILE}: languages.{code}: "
                                f"{{{name}}} is not a slot or a missing key{near(name, slots)}")
                break
            except Exception as exc:
                problems.append(f"{messaging.MESSAGES_FILE}: languages.{code}: "
                                f"cannot write a draft ({type(exc).__name__}: {exc})")
                break
    return problems


def validate(root: Path) -> list[str]:
    """Problems in the files an agent may write that the core owns:
    config.toml's keys, fields.toml, theme.css and messages.toml. Each line is
    "<file>: <where>: <what>", for `hermitcrm check` and the hub's banner."""
    out: list[str] = []
    for check in (validate_config, validate_fields, validate_theme, validate_messages):
        try:
            out += check(Path(root))
        except Exception as exc:  # a validator must never stop `check`
            logger.exception("validator %s failed", check.__name__)
            out.append(f"{check.__name__}: internal error: {exc}")
    return out


# Every module with files of its own lists its validate() here; the hub shows
# what they find. `hermitcrm check` calls each module's validate itself.
VALIDATORS: list[Callable[[Path], list]] = [validate, _late("layout", "validate"),
                                            _late("dashboards", "validate"),
                                            _late("routines", "validate")]


def all_problems(root: Path) -> list[str]:
    out: list[str] = []
    for check in VALIDATORS:
        try:
            out += check(Path(root)) or []
        except Exception as exc:  # a crashing check must not read as "no problems"
            logger.exception("validator %r failed", check)
            out.append(f"{getattr(check, '__qualname__', check)}: the check itself failed "
                       f"({type(exc).__name__}: {exc})")
    return out
