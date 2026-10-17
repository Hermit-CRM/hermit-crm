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

"""The Outreach page: the outreach bot's review flow in the browser.

    /outreach            filter bar, Preview, Build queue; tabs Replies to
                         interest, Follow-ups, First touches, Ready, Skipped
    /outreach/job        the background build's progress (JSON, for the page)
    /outreach/card/<id>  one card (HTML), added to the page as it is built

Every button is one call into outreach.py, which writes one commit; nothing
here decides what a draft says or who gets one. The bot never sends and never
logs: Mark ready changes the state (and adds the findings to the contact's
notes), Mark sent changes the state only.

The queue builds in a background thread, one at a time; the page polls
/outreach/job and inserts each card as it is done, so what someone is typing
in another card is never reloaded away. Tests swap app.state.run_background
for a plain call.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from . import outreach, playbook, routines
from . import setup as setup_steps
from .enrich import EnrichError
from .models import INTERESTED, ValidationError

logger = logging.getLogger(__name__)

TABS = (  # (key, label): replies first, that is where deals leak
    ("replies", "Replies to interest"),
    ("followups", "Follow-ups"),
    ("first", "First touches"),
    ("ready", "Ready"),
    ("skipped", "Skipped"),
)
TAB_OF_KIND = {"reply-to-interest": "replies", "follow-up": "followups",
               "first-touch": "first"}
KIND_LABELS = {"first-touch": "First touch", "reply-to-interest": "Reply to interest",
               "follow-up": "Follow-up"}
SKIP_LABELS = {
    "bad-fit": "Bad fit (keeps the company out)", "wrong-person": "Wrong person",
    "bad-timing": "Bad timing", "bad-draft": "Bad draft", "already-in-contact":
    "Already in contact", "other": "Other",
}


def tab_of(item) -> str:
    if item.state == "ready":
        return "ready"
    if item.state in ("skipped", "sent", "logged"):
        return "skipped" if item.state == "skipped" else "ready"
    return TAB_OF_KIND.get(item.kind, "first")


def split_where(text: str) -> list[str]:
    """The filter box: conditions separated by `;` or new lines (a comma
    belongs to a value: `country=DE,NL`)."""
    return [part.strip() for line in (text or "").splitlines() for part in line.split(";")
            if part.strip()]


@dataclass
class Job:
    """The one background build: what it does and how far it got."""

    label: str
    total: int
    tab: str = "first"
    done: int = 0
    ids: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    error: str = ""
    running: bool = True

    def to_dict(self) -> dict:
        return {"label": self.label, "total": self.total, "done": self.done,
                "ids": list(self.ids), "lines": list(self.lines), "error": self.error,
                "running": self.running, "tab": self.tab}


def register(app, *, store, root: Path, config: dict, render, check_csrf, flashed,
             safe_back, config_saved) -> None:
    """Add the Outreach routes to the app (called from web.create_app)."""
    jobs_lock = threading.Lock()
    app.state.outreach_job = None

    def run_background(fn) -> None:
        threading.Thread(target=fn, name="outreach-build", daemon=True).start()

    app.state.run_background = run_background

    # ------------------------------------------------------------- helpers

    def ai_ready() -> str:
        """Why the AI cannot draft now, or ""."""
        enricher = app.state.enricher
        if not enricher.available:
            return enricher.unavailable_reason()
        return routines.ai_problem(enricher)

    def drafter_for(kind: str, tier: str = "medium"):
        problem = ai_ready()
        if not problem:
            return outreach.AIDrafter(store, app.state.enricher.with_tier(tier), config)
        if kind == "reply-to-interest":
            return outreach.TemplateDrafter(store, config)
        raise outreach.OutreachError(f"No AI to draft with: {problem}. A reply to interest "
                                     "works without one (from the wording template).")

    def researcher():
        return outreach.ScrapeResearcher(app.state.enricher.with_tier("medium"),
                                         fetcher=app.state.fetcher, today=store.today())

    def card(item) -> dict:
        company = store.get(item.company)
        contact = company.contacts.get(item.contact) if company else None
        fit = outreach.fit_value(company, str(outreach._config(config, "outreach_fit_field"))) \
            if company else None
        reply = outreach.find_interaction(store, item.reply_to) if item.reply_to else None
        return {"item": item, "company": company, "contact": contact, "fit": fit,
                "reply": reply, "tab": tab_of(item),
                "copy": ((f"{item.subject}\n\n" if item.subject else "") + item.body).strip()}

    def start_job(label: str, selection, kind: str) -> None:
        """Build the selection in the background; refuses a second one."""
        drafter = drafter_for(kind)
        research = researcher() if kind != "reply-to-interest" else None
        with jobs_lock:
            current = app.state.outreach_job
            if current is not None and current.running:
                raise outreach.OutreachError("A queue is already being built; wait until "
                                             "it is done.")
            job = Job(label=label, total=len(selection.picked), tab=TAB_OF_KIND[kind])
            app.state.outreach_job = job

        def progress(item) -> None:
            job.done += 1
            job.ids.append(item.id)

        def work() -> None:
            try:
                result = outreach.build(store, selection, research, drafter, config,
                                        progress=progress)
                job.lines = result.lines
            except (outreach.OutreachError, EnrichError) as exc:
                job.error = str(exc)
            except Exception as exc:  # the page must say it stopped, not spin forever
                logger.exception("outreach build failed")
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                job.running = False

        app.state.run_background(work)

    def form_where(where: str) -> list[str]:
        return split_where(where)

    def selection_for(where: str, kind: str, channel: str, limit: str, approach: str):
        try:
            size = int(limit) if str(limit).strip() else None
        except ValueError:
            raise outreach.OutreachError("the batch size must be a whole number") from None
        return outreach.select(store, where=form_where(where), channel=channel, kind=kind,
                               limit=size, approach=approach, config=config)

    def page(request: Request, tab: str = "", status_code: int = 200, **extra):
        every = outreach.items(root)
        open_items = [i for i in every if i.is_open]
        rows = outreach.replies(store)
        counts = {key: 0 for key, _ in TABS}
        for i in every:
            if i.state != "sent":
                counts[tab_of(i)] += 1
        counts["replies"] += sum(1 for r in rows if not r.item and r.status != "no")
        tab = tab if tab in counts else ""
        if not tab:
            tab = "replies" if counts["replies"] else "first"
        shown = [i for i in every if tab_of(i) == tab and i.state != "sent"]
        if tab == "ready":
            shown.sort(key=lambda i: i.ready or i.created)
        pb = playbook.load(root)
        gate = ""
        try:
            ready_approaches = playbook.require_ready(root)
        except playbook.NotReady as exc:
            gate, ready_approaches = str(exc), []
        job = app.state.outreach_job
        values = {"where": "stage=prospect", "kind": "first-touch", "channel": "",
                  "research": str(outreach._config(config, "outreach_research")),
                  "limit": str(outreach._config(config, "outreach_batch_size")),
                  "approach": ""}
        values.update(extra.pop("values", {}) or {})
        return render(request, "outreach.html", {
            "tabs": TABS, "tab": tab, "counts": counts,
            "cards": [card(i) for i in shown],
            "replies": [r for r in rows if not r.item] if tab == "replies" else [],
            "hidden_no": sum(1 for r in rows if r.status == "no" and not r.item),
            "show_no": request.query_params.get("all") == "1",
            "waiting": outreach_waiting() if tab == "followups" else [],
            "sent": [i for i in every if i.state == "sent"][:20] if tab == "ready" else [],
            "values": values, "kinds": outreach.KINDS, "kind_labels": KIND_LABELS,
            "channels": outreach.CHANNELS, "levels": outreach.LEVELS,
            "built_levels": outreach.BUILT_LEVELS,
            "approaches": [a.name for a in ready_approaches] or [a.name for a in pb.approaches],
            "gate": gate, "ai_problem": ai_ready(),
            "skip_reasons": outreach.SKIP_REASONS, "skip_labels": SKIP_LABELS,
            "job": job.to_dict() if job else None,
            "interested_missing": INTERESTED not in store.outcomes,
            "outcomes": list(store.outcomes), "open_count": len(open_items),
            "preview": None, "build_error": "",
            **extra,
        }, status_code=status_code)

    def outreach_waiting():
        """Waiting on them (you wrote last, nothing came back): the follow-up radar
        per contact, for the Follow-ups tab until the bot drafts follow-ups."""
        from . import followups

        out = []
        for company in store.all():
            if company.is_sample or not company.is_active:
                continue
            for cslug in company.contacts:
                row = followups.for_contact(company, cslug, store.today(), reply_after=10**6,
                                            nudge_after=int(config.get("followup_nudge_days",
                                                                       5)))
                if row is not None and row.kind == followups.NUDGE:
                    out.append(row)
        return sorted(out, key=lambda r: -r.days)

    def need_item(item_id: str):
        item = outreach.get_item(root, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"unknown outreach item {item_id!r}")
        return item

    def back_to(item, message: str):
        return flashed(f"/outreach?tab={tab_of(item)}", message, anchor=f"item-{item.id}")

    def who(item) -> str:
        company = store.get(item.company)
        contact = company.contacts.get(item.contact) if company else None
        return contact.name if contact else item.record

    # -------------------------------------------------------------- the page

    @app.get("/outreach", response_class=HTMLResponse)
    def outreach_page(request: Request, tab: str = ""):
        return page(request, tab)

    @app.post("/outreach/preview", response_class=HTMLResponse)
    def outreach_preview(request: Request, csrf_token: str = Form(""), where: str = Form(""),
                         kind: str = Form("first-touch"), channel: str = Form(""),
                         research: str = Form(""), limit: str = Form(""),
                         approach: str = Form("")):
        """Who a batch would go to and why not the others: no AI, nothing written."""
        check_csrf(csrf_token)
        values = {"where": where, "kind": kind, "channel": channel, "research": research,
                  "limit": limit, "approach": approach}
        tab = TAB_OF_KIND.get(kind, "first")
        try:
            sel = selection_for(where, kind, channel, limit, approach)
        except outreach.OutreachError as exc:
            return page(request, tab, status_code=400, values=values, build_error=str(exc))
        return page(request, tab, values=values, preview=sel)

    @app.post("/outreach/build")
    def outreach_build(request: Request, csrf_token: str = Form(""), where: str = Form(""),
                       kind: str = Form("first-touch"), channel: str = Form(""),
                       research: str = Form(""), limit: str = Form(""),
                       approach: str = Form("")):
        """Start building the queue in the background; cards appear as they finish."""
        check_csrf(csrf_token)
        values = {"where": where, "kind": kind, "channel": channel, "research": research,
                  "limit": limit, "approach": approach}
        tab = TAB_OF_KIND.get(kind, "first")
        try:
            if kind != "reply-to-interest":
                outreach.research_level(config, research)
            sel = selection_for(where, kind, channel, limit, approach)
            if sel.gate:
                raise outreach.OutreachError(sel.gate)
            if kind not in outreach.BUILT_KINDS:
                raise outreach.OutreachError(f"{KIND_LABELS.get(kind, kind)} drafts come in "
                                             "a later version.")
            if not sel.picked:
                return page(request, tab, values=values, preview=sel,
                            build_error="Nobody to build for: see why below.")
            start_job(f"{len(sel.picked)} {KIND_LABELS[kind].lower()} draft"
                      f"{'s' if len(sel.picked) != 1 else ''} by {channel}", sel, kind)
        except outreach.OutreachError as exc:
            return page(request, tab, status_code=400, values=values, build_error=str(exc))
        return flashed(f"/outreach?tab={tab}",
                       "Building in the background: the cards appear here as they are "
                       "done. Nothing is sent.")

    @app.get("/outreach/job")
    def outreach_job():
        job = app.state.outreach_job
        return JSONResponse(job.to_dict() if job else {"running": False, "ids": []})

    @app.get("/outreach/card/{item_id}", response_class=HTMLResponse)
    def outreach_card(request: Request, item_id: str):
        item = need_item(item_id)
        return render(request, "outreach_card.html", {
            "c": card(item), "skip_reasons": outreach.SKIP_REASONS,
            "skip_labels": SKIP_LABELS, "kind_labels": KIND_LABELS})

    # --------------------------------------------------- replies to interest
    # (before the cards' routes: /outreach/replies/check is not an item's check)

    @app.post("/outreach/replies/check")
    def outreach_check_replies(request: Request, csrf_token: str = Form("")):
        """Ask the AI about each reply not checked yet (once per reply)."""
        check_csrf(csrf_token)
        problem = ai_ready()
        if problem:
            return flashed("/outreach?tab=replies", f"No AI to check replies with: {problem}. "
                           "Mark a reply as interest yourself, or log it with outcome "
                           f"{INTERESTED}.")
        rows = [r for r in outreach.replies(store) if r.status == "unchecked"]
        if not rows:
            return flashed("/outreach?tab=replies", "Every reply is checked already.")
        with jobs_lock:
            current = app.state.outreach_job
            if current is not None and current.running:
                return flashed("/outreach?tab=replies", "A queue is being built; check the "
                               "replies when it is done.")
            job = Job(label=f"checking {len(rows)} repl{'y' if len(rows) == 1 else 'ies'}",
                      total=len(rows), tab="replies")
            app.state.outreach_job = job
        enricher = app.state.enricher.with_tier("medium")

        def work() -> None:
            try:
                job.lines = outreach.check_replies(store, enricher, rows)
                job.done = job.total
            except Exception as exc:
                logger.exception("checking replies failed")
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                job.running = False

        app.state.run_background(work)
        return flashed("/outreach?tab=replies", "Checking the replies in the background; "
                       "the list updates when it is done.")

    @app.post("/outreach/replies/confirm")
    def outreach_confirm_reply(request: Request, csrf_token: str = Form(""),
                               key: str = Form(""), answer: str = Form("")):
        check_csrf(csrf_token)
        try:
            outreach.confirm_reply(store, key, answer == "yes")
        except (outreach.OutreachError, ValidationError) as exc:
            return flashed("/outreach?tab=replies", str(exc))
        return flashed("/outreach?tab=replies",
                       "Marked as interest." if answer == "yes" else "Marked as not interest.",
                       anchor="replies")

    @app.post("/outreach/replies/draft")
    def outreach_draft_reply(request: Request, csrf_token: str = Form(""),
                             key: str = Form(""), channel: str = Form("email")):
        """Draft a reply to one reply that shows interest (in the background)."""
        check_csrf(csrf_token)
        it = outreach.find_interaction(store, key)
        if it is None or not it.contact:
            return flashed("/outreach?tab=replies", f"No reply {key!r} with a contact.")
        cslug = key.partition("/")[0]
        return start_for_contact(f"{cslug}/{it.contact}", "reply-to-interest", channel,
                                 fail_to="/outreach?tab=replies")

    @app.post("/outreach/outcomes/interested")
    def outreach_add_interested(request: Request, csrf_token: str = Form("")):
        """Offer, never add silently: the `interested` outcome, on this click."""
        check_csrf(csrf_token)
        names = list(store.outcomes)
        if INTERESTED not in names:
            names = names[:-1] + [INTERESTED] + names[-1:] if len(names) > 1 else \
                names + [INTERESTED]
        result = setup_steps.save_outcomes(
            root, names, str(config.get("message_window_days", 14)),
            str(config.get("silent_days", 14)))
        if not result.ok:
            return flashed("/outreach?tab=replies", "Not saved: " + "; ".join(
                result.errors.values()))
        config_saved()
        return flashed("/outreach?tab=replies", f"Added the outcome {INTERESTED}: "
                       + ", ".join(names) + ". Change the list in Settings, Outcomes.")

    # ------------------------------------------------------------ the cards

    @app.post("/outreach/{item_id}/check")
    def outreach_check(request: Request, item_id: str, csrf_token: str = Form(""),
                       subject: str | None = Form(None), body: str | None = Form(None),
                       pitch: str | None = Form(None)):
        """Save the edited text and run the hard checks on it again."""
        check_csrf(csrf_token)
        item = need_item(item_id)
        try:
            item = outreach.save_text(store, item_id, subject, body, pitch, recheck=True)
        except outreach.OutreachError as exc:
            return back_to(item, str(exc))
        n = len(item.checks)
        return back_to(item, "Checks passed." if not n else
                       f"{n} check{'s still fail' if n > 1 else ' still fails'}; you can "
                       "still mark it ready.")

    @app.post("/outreach/{item_id}/ready")
    def outreach_ready(request: Request, item_id: str, csrf_token: str = Form(""),
                       subject: str | None = Form(None), body: str | None = Form(None),
                       pitch: str | None = Form(None)):
        """Save the text, then Mark ready: the state, and the findings to the
        contact's notes, in one commit. Allowed with a failed check (warned)."""
        check_csrf(csrf_token)
        item = need_item(item_id)
        try:
            outreach.save_text(store, item_id, subject, body, pitch)
            item, found = outreach.mark_ready(store, item_id)
        except (outreach.OutreachError, ValidationError) as exc:
            return back_to(item, f"Not marked ready: {exc}")
        text = f"Ready: {who(item)}. Send it yourself, then log it as usual."
        if found:
            text += (f" Warning: {len(found)} check"
                     f"{'s still fail' if len(found) > 1 else ' still fails'}: "
                     + "; ".join(found))
        return flashed("/outreach?tab=ready", text, anchor=f"item-{item.id}")

    @app.post("/outreach/{item_id}/regenerate")
    async def outreach_regenerate(request: Request, item_id: str, csrf_token: str = Form(""),
                                  strong: str = Form("")):
        check_csrf(csrf_token)
        item = need_item(item_id)
        try:
            drafter = drafter_for(item.kind, "strong" if strong else "medium")
            item = await run_in_threadpool(outreach.regenerate, store, item_id, drafter)
        except (outreach.OutreachError, EnrichError) as exc:
            return back_to(item, f"Not regenerated: {exc}")
        return back_to(item, f"New draft for {who(item)}"
                       + (" (stronger model)." if strong else "."))

    @app.post("/outreach/{item_id}/skip")
    def outreach_skip(request: Request, item_id: str, csrf_token: str = Form(""),
                      reason: str = Form(""), note: str = Form("")):
        check_csrf(csrf_token)
        item = need_item(item_id)
        try:
            outreach.skip(store, item_id, reason, note)
        except outreach.OutreachError as exc:
            return back_to(item, f"Not skipped: {exc}")
        return flashed(f"/outreach?tab={TAB_OF_KIND.get(item.kind, 'first')}",
                       f"Skipped {who(item)} ({reason}).")

    @app.post("/outreach/{item_id}/sent")
    def outreach_sent(request: Request, item_id: str, csrf_token: str = Form("")):
        """You sent it: the state only, nothing is logged."""
        check_csrf(csrf_token)
        item = need_item(item_id)
        try:
            outreach.mark_sent(store, item_id)
        except outreach.OutreachError as exc:
            return back_to(item, str(exc))
        return flashed("/outreach?tab=ready", f"Marked sent: {who(item)}. Nothing was "
                       "logged; log the message as usual if you have not.")

    @app.post("/outreach/{item_id}/findings/add")
    def outreach_finding_add(request: Request, item_id: str, csrf_token: str = Form(""),
                             text: str = Form(""), source: str = Form("")):
        check_csrf(csrf_token)
        item = need_item(item_id)
        try:
            outreach.add_finding(store, item_id, text, source)
        except outreach.OutreachError as exc:
            return back_to(item, str(exc))
        return back_to(item, "Finding added.")

    @app.post("/outreach/{item_id}/findings/{number}/remove")
    def outreach_finding_remove(request: Request, item_id: str, number: int,
                                csrf_token: str = Form("")):
        check_csrf(csrf_token)
        item = need_item(item_id)
        try:
            outreach.remove_finding(store, item_id, number)
        except outreach.OutreachError as exc:
            return back_to(item, str(exc))
        return back_to(item, "Finding removed.")

    @app.post("/outreach/{item_id}/proposals/{key}")
    def outreach_proposal(request: Request, item_id: str, key: str,
                          csrf_token: str = Form("")):
        check_csrf(csrf_token)
        item = need_item(item_id)
        try:
            outreach.accept_proposal(store, item_id, key)
        except (outreach.OutreachError, ValidationError) as exc:
            return back_to(item, f"Not saved: {exc}")
        return back_to(item, f"Saved the {key} to the record.")

    # -------------------------------------------- the contact page's button

    def start_for_contact(record: str, kind: str, channel: str, fail_to: str):
        if kind not in outreach.KINDS:
            return flashed(fail_to, f"Unknown draft type {kind!r}.")
        if kind not in outreach.BUILT_KINDS:
            return flashed(fail_to, f"{KIND_LABELS[kind]} drafts come in a later version; "
                           "pick another type or write it yourself.")
        try:
            sel = outreach.select(store, contacts=[record], channel=channel, kind=kind,
                                  limit=1, config=config)
            if sel.gate:
                raise outreach.OutreachError(sel.gate)
            if not sel.picked:
                why = sel.excluded[0].reason if sel.excluded else "nobody to draft for"
                raise outreach.OutreachError(f"No draft: {why}.")
            if kind == "first-touch":
                outreach.research_level(config)
            start_job(f"{KIND_LABELS[kind].lower()} for {sel.picked[0].contact.name} by "
                      f"{channel}", sel, kind)
        except outreach.OutreachError as exc:
            return flashed(fail_to, str(exc))
        doing = ("Drafting a reply" if kind == "reply-to-interest" else
                 "Researching and drafting")
        return flashed(f"/outreach?tab={TAB_OF_KIND[kind]}",
                       f"{doing} for {sel.picked[0].contact.name} in the background; the "
                       "card appears here when it is done.")

    @app.post("/companies/{slug}/contacts/{cslug}/outreach")
    def contact_outreach(request: Request, slug: str, cslug: str, csrf_token: str = Form(""),
                         kind: str = Form(""), channel: str = Form("email")):
        """"Research & draft" on a contact's page."""
        check_csrf(csrf_token)
        company = store.get(slug)
        if company is None or cslug not in company.contacts:
            raise HTTPException(status_code=404, detail="unknown contact")
        kind = kind or outreach.suggested_kind(company, cslug)
        return start_for_contact(f"{slug}/{cslug}", kind, channel,
                                 fail_to=f"/companies/{slug}/contacts/{cslug}")


def contact_context(root: Path, company, contact) -> dict:
    """What contact.html shows in its Outreach box: the open item for this
    person (if any), and the button's suggested draft type and channel."""
    open_item = next((i for i in outreach.items(root) if i.is_open
                      and i.company == company.slug and i.contact == contact.slug), None)
    channel = "email" if contact.email or not contact.linkedin else "linkedin"
    return {"outreach_item": open_item, "outreach_tab": tab_of(open_item) if open_item else "",
            "outreach_kind": outreach.suggested_kind(company, contact.slug),
            "outreach_channel": channel, "outreach_kinds": outreach.KINDS,
            "outreach_kind_labels": KIND_LABELS,
            "outreach_built": outreach.BUILT_KINDS}
