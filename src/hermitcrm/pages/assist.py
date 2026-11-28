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

"""Routes for the assistant features: autopilot (autopilot.py) and, next to it,
the after-contact assistant. Registered by pages.register."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import autopilot
from ..models import ValidationError
from ._ctx import ctx

router = APIRouter()


def _flashed(path: str, message: str, anchor: str = ""):
    from ..web import flashed  # web imports this package

    return flashed(path, message, anchor=anchor)


@router.post("/settings/autopilot")
def settings_autopilot(request: Request, csrf_token: str = Form(""),
                       on: list[str] = Form([]), daily_cap: str = Form("")):
    """Settings, Autopilot: the switches and the daily limit, in config.toml.
    Turning a switch on is the consent: nothing runs before the next sync."""
    c = ctx(request)
    c.check_csrf(csrf_token)
    errors = autopilot.save_settings(c.root, on, daily_cap)
    if errors:
        return _flashed("/settings", "Not saved: " + " ".join(errors.values()),
                        anchor="autopilot")
    from ..setup import commit_config

    commit_config(c.root, c.store.notify)   # the next page reads config.toml again
    chosen = [autopilot.LABELS[s][0].lower() for s in autopilot.SWITCHES if s in on]
    message = ("Autopilot saved: " + ", ".join(chosen) + " after each daily sync"
               if chosen else "Autopilot saved: everything off")
    return _flashed("/settings", message, anchor="autopilot")


# ------------------------------------------------------------ proposals
# Today's "Prepared for you" rows: Approve writes with the normal store call,
# Edit opens this page, Discard drops it. Nothing here sends anything.


def _back(back: str) -> str:
    from ..web import safe_back  # web imports this package

    return safe_back(back, "/today")


def _proposal_or_404(c, proposal_id: str):
    proposal = autopilot.get_proposal(c.root, proposal_id)
    kind = autopilot.KINDS.get(proposal.kind) if proposal is not None else None
    company = c.store.companies.get(proposal.company) if proposal is not None else None
    if proposal is None or kind is None or company is None:
        raise HTTPException(status_code=404, detail="That proposal is gone: approved, "
                            "discarded, or its company was deleted.")
    return proposal, kind, company


@router.get("/autopilot/proposals/{proposal_id}", response_class=HTMLResponse)
def proposal_page(request: Request, proposal_id: str, back: str = "/today"):
    c = ctx(request)
    proposal, kind, company = _proposal_or_404(c, proposal_id)
    return c.render(request, "autopilot_proposal.html",
                    {"proposal": proposal, "kind": kind, "company": company,
                     "back": _back(back), "text_limit": autopilot.NEXT_STEP_TEXT_LIMIT})


@router.post("/autopilot/proposals/{proposal_id}/approve")
def proposal_approve(request: Request, proposal_id: str, csrf_token: str = Form(""),
                     back: str = Form(""), text: str | None = Form(None),
                     due: str | None = Form(None)):
    """Approve as proposed (Today's button) or as edited (the Edit page's form)."""
    c = ctx(request)
    c.check_csrf(csrf_token)
    proposal, kind, company = _proposal_or_404(c, proposal_id)
    back = _back(back)
    if text is not None or due is not None:
        text = " ".join((text if text is not None else proposal.text).split())
        due = (due if due is not None else proposal.due).strip()
        if not text or len(text) > autopilot.NEXT_STEP_TEXT_LIMIT:
            return _flashed(f"/autopilot/proposals/{proposal_id}",
                            f"Not approved: write what to do, in at most "
                            f"{autopilot.NEXT_STEP_TEXT_LIMIT} characters.")
        autopilot.update_proposal(c.store, proposal_id, text, due)
    try:
        message = autopilot.approve_proposal(c.store, proposal_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="That proposal is gone.") from None
    except ValidationError as exc:
        return _flashed(f"/autopilot/proposals/{proposal_id}",
                        "Not approved: " + "; ".join(exc.errors.values()))
    return _flashed(back, message)


@router.post("/autopilot/proposals/{proposal_id}/discard")
def proposal_discard(request: Request, proposal_id: str, csrf_token: str = Form(""),
                     back: str = Form("")):
    c = ctx(request)
    c.check_csrf(csrf_token)
    proposal, kind, company = _proposal_or_404(c, proposal_id)
    autopilot.remove_proposal(c.store, proposal_id, discarded=True)
    return _flashed(_back(back), f"{kind.label} for {company.name} discarded")
