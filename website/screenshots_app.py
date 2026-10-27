"""Serve a demo data folder for the website's screenshots (dev only).

Run by `screenshots.py` with the interpreter that has the app's dependencies,
never by hand and never against your own data. It starts the real web app on a
spare port, with two things swapped in so a screenshot needs no AI and no web:

* the AI CLI: a scripted answer for each kind of call (research, draft, critic,
  reply check). The words are made up, the rest is the app's own: who it picks,
  the checks, the critic's scores, the card and the page.
* the page fetcher: a short made-up page for every company's website.

It can also fake a newer release, to show the Upgrade notice (`--newer`), and turn
a routine on and run it once, with the same scripted AI (`--routine`).

    python screenshots_app.py SRC DATA PORT [--newer VERSION] [--routine NAME]

SRC is the `src/` folder of the version to show (a checkout or an unpacked
release); it goes first on the import path, so the pages are that version's.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

src, data, port = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
newer = sys.argv[sys.argv.index("--newer") + 1] if "--newer" in sys.argv else ""
routine = sys.argv[sys.argv.index("--routine") + 1] if "--routine" in sys.argv else ""
sys.path.insert(0, src)

import uvicorn  # noqa: E402

from hermitcrm import outreach, routines, upgrade  # noqa: E402
from hermitcrm import web  # noqa: E402
from hermitcrm.enrich import Enricher  # noqa: E402
from hermitcrm.store import load_config  # noqa: E402

# What the made-up research finds, by company name. Every finding is made up
# for a made-up company (example.com and example.org).
FINDINGS = {
    "Lindenhof Data": [
        ("Opened a second office in Leipzig this autumn", "trigger", "high", "2026-09-20"),
        ("Hiring its first Account Executive", "trigger", "high", "2026-10"),
        ("Sells data pipelines to mid-size manufacturers", "company", "high", ""),
    ],
    "Kestrel Metrics": [
        ("Published a customer story on faster reporting for retailers", "trigger", "medium", "2026-10"),
        ("Two founders, no sales leader on the team page", "company", "high", ""),
    ],
    "Tallpine Software": [
        ("Launched a free tier for small teams in October", "trigger", "high", "2026-10"),
        ("Pricing page lists three plans, no sales contact", "company", "medium", ""),
    ],
}

# The drafts, written in each contact's language: subject, then the message
# without its greeting and signature. The app's checks run on them as on any
# draft: one question, no link, under 120 words, not opening with "I".
DRAFTS = {
    "Lindenhof Data": ("Hallo", "Euer zweites Büro", "viele Grüße",
                       "die zweite Niederlassung in Leipzig ist mir aufgefallen, und danach folgt oft die erste "
                       "Vertriebsstelle.\nIch arbeite als dein Fractional Head of Sales: Teilzeit, ohne "
                       "Mindestlaufzeit.\nWer schließt bei euch heute die Verträge ab: du oder schon jemand im Team?"),
    "Kestrel Metrics": ("Hoi", "Jullie klantverhaal", "groet",
                        "jullie verhaal over sneller rapporteren voor retailers leest als een echt klantverhaal.\n"
                        "Ik werk als fractioneel Head of Sales: deeltijd, zonder minimale looptijd.\n"
                        "Wie voert de verkoopgesprekken bij jullie op dit moment?"),
    "Tallpine Software": ("Hi", "Your free tier", "best",
                          "launching a free tier in October usually brings a wave of small teams to talk to.\n"
                          "I work as a fractional Head of Sales: part-time, no minimum term.\n"
                          "Who picks up those conversations when they come in?"),
}


FIRST_NAMES = {"Mara": "Lindenhof Data", "Daan": "Kestrel Metrics", "Oliver": "Tallpine Software"}


def company_of(prompt: str) -> str:
    for name in FINDINGS:
        if name in prompt:
            return name
    found = re.search(r"Person: (\S+)", prompt)
    return FIRST_NAMES.get(found.group(1) if found else "", "Lindenhof Data")


def first_name(prompt: str) -> str:
    found = re.search(r"^Person: (\S+)", prompt, re.M)
    return found.group(1) if found else "there"


def research(prompt: str) -> dict:
    url = re.search(r"--- page (\S+) ---", prompt).group(1)
    return {"findings": [{"text": text, "source": url, "kind": kind, "confidence": confidence,
                          "date": date} for text, kind, confidence, date in FINDINGS[company_of(prompt)]]}


def draft(prompt: str) -> dict:
    first, company = first_name(prompt), company_of(prompt)
    hello, subject, goodbye, text = DRAFTS[company]
    if "This is a follow-up" in prompt:
        return {"subject": f"Re: {subject}", "pitch": "", "findings_used": [], "proof_used": [],
                "body": f"{hello} {first},\n\nA quick follow-up, with no calendar invite: is this a priority "
                        "for you right now, or not really? A short 'not now' is fine, then I'll close the "
                        f"loop.\n\n{goodbye[0].upper() + goodbye[1:]},\nAlex"}
    used = re.search(r"^(\d+)\. \[\w+, (?:high|medium), usable; source (?!crm)", prompt, re.M)
    return {"subject": subject, "pitch": "", "findings_used": [int(used.group(1))] if used else [],
            "proof_used": [], "body": f"{hello} {first},\n\n{text}\n\n{goodbye[0].upper() + goodbye[1:]},\nAlex"}


def routine_draft(prompt: str) -> dict:
    """What a routine that drafts follow-ups gets back: a short note to one contact."""
    first = next((n for n in ("Joris", "Jonas", "Camille") if n in prompt), "there")
    return {"channel": "email", "subject": "Re: Our call", "skip": "",
            "body": f"Hi {first},\n\nYou said the budget decision comes next quarter. Is that still the plan, "
                    "or has something changed on your side?\n\nAlex"}


def scores(prompt: str) -> dict:
    return {"relevance": 4, "personal": 4, "tone": 5, "honesty": 5,
            "reason": "Built on a real finding, one question, no claim it cannot back."}


def classify(prompt: str) -> dict:
    return {"verdict": "interested", "why": "They ask for the case study before deciding."}


class ScriptedAI:
    """Stands in for the AI CLI: one scripted answer per kind of call."""

    def __call__(self, prompt, schema, **kwargs):
        if schema in (outreach.RESEARCH_SCHEMA, getattr(outreach, "AI_WEB_SCHEMA", None)):
            return research(prompt)
        if schema is outreach.CLASSIFY_SCHEMA:
            return classify(prompt)
        if schema is outreach.CRITIC_SCHEMA:
            return scores(prompt)
        if schema is routines.DRAFT_SCHEMA:
            return routine_draft(prompt)
        return draft(prompt)


def page(url: str) -> str:
    return (f"<html lang='en'><head><title>Home | {url}</title><meta name='description' "
            "content='Software for teams that sell.'></head><body></body></html>")


def bookmarked_page(url: str) -> str:
    """The page the extension reads: a made-up company's home page."""
    return ("<html lang='en'><head><title>Harbor Robotics | Warehouse picking robots</title>"
            "<meta name='description' content='Warehouse picking robots for mid-size retailers.'>"
            "<meta property='og:site_name' content='Harbor Robotics'></head><body></body></html>")


def scripted(config: dict) -> Enricher:
    return Enricher(provider="claude", which=lambda binary: f"/usr/local/bin/{binary}", runner=ScriptedAI())


# The app builds its AI again whenever the settings change (accepting the
# disclaimer does), so replace the builder, not only the first AI. Without this
# a screenshot would call the real AI CLI.
web.build_enricher = scripted
config = load_config(data)
config.update(push_enabled=False, owner_name="Alex Example")
app = web.create_app(data, config)
app.state.setup_redirected = True
app.state.outreach_fetcher = page
app.state.fetcher = bookmarked_page

if newer:
    # Say that a newer release exists and that one click may install it.
    app.state.update_notice.available = newer
    upgrade.install_plan = lambda *a, **k: upgrade.Plan(argv=("uv", "tool", "install", "hermitcrm@latest"))

if routine:
    # Turned on and run once, as a person would the first morning.
    loaded = routines.load(data, config)
    routines.set_paused(app.state.store, routine, False, config)
    routines.run(app.state.store, routines.load(data, config).get(routine), apply=True,
                 enricher=app.state.enricher.with_tier("medium"), config=config)

uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
