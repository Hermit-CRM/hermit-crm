"""The ten-step walkthrough at /welcome.

Each step knows whether it is done by asking the data, not by remembering that
you clicked something: "your first company" is done when a company exists,
"BCC capture" when the mail settings are saved with a password. Two steps
cannot be detected that way -- nothing tells a web page that a bookmarklet was
dragged to a bookmarks bar -- so those are ticked by hand and remembered in
config.toml as `welcome_done`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Steps you tick yourself, because the app has no way to see them happen.
MANUAL = ("extension", "find")


@dataclass
class Step:
    key: str
    title: str
    why: str
    action: str
    href: str
    done: bool = False
    manual: bool = False


def steps(store, config: dict, setup_state: dict, ai_available: bool) -> list[Step]:
    # The sample account is there to look at; the steps count your own records.
    companies = [c for c in store.companies.values() if not c.is_sample]
    contacts = [c for co in companies for c in co.contacts.values()]
    interactions = [i for co in companies for i in co.interactions]
    moved = any(co.stage != "prospect" or any(e.from_stage for e in co.stage_history)
                for co in companies)
    planned = any(co.has_next_step or co.tasks for co in companies) or \
        any(c.tasks for c in contacts)
    ticked = set(config.get("welcome_done") or [])

    return [
        Step("you", "Say who you are",
             "Your name signs the drafts, and your addresses are how Hermit CRM "
             "tells mail you sent from mail you received.",
             "Open Settings", "/settings#you", bool(setup_state.get("you"))),
        Step("company", "Add your first company",
             "A company is a folder with a file in it. Everything else hangs off one.",
             "Add a company", "/companies/new", bool(companies)),
        Step("contact", "Add a person at it",
             "Contacts live inside their company. Drafts address them by first name "
             "and the timeline says who you spoke to.",
             "Add a contact", "/contacts/new", bool(contacts)),
        Step("interaction", "Log what happened",
             "A call, a mail, a meeting. The first one moves a prospect to engaged "
             "on its own, and every one of them is what the reports count.",
             "Open a company", "/companies", bool(interactions)),
        Step("move", "Move a deal along",
             "Change a stage on the pipeline. The history is kept, so the reports "
             "can say how long deals spend where.",
             "Open the pipeline", "/pipeline", moved),
        Step("plan", "Write down what comes next",
             "Each company has one next step -- the thing that decides where the "
             "deal stands -- and a list of other tasks beside it. Both show on the "
             "calendar on their due date.",
             "Open the calendar", "/calendar", planned),
        Step("bcc", "Capture your mail without typing it",
             "Put a tracking address in BCC when you write to a prospect, or forward "
             "a thread to it. Hermit CRM reads that mailbox, matches each message to "
             "a company by the other person's address or domain, and logs it. Mail "
             "it cannot match waits in a review queue under Settings. Pick your mail "
             "provider there and it fills in the server; you need an app password, "
             "not your normal one.",
             "Set up BCC capture", "/settings#bcc", bool(setup_state.get("bcc"))),
        Step("calendar", "Import your meetings",
             "Give Hermit CRM your calendar's secret address and meetings with people "
             "it knows are logged as interactions. Nothing is written to your calendar.",
             "Connect a calendar", "/settings#calendar",
             bool(setup_state.get("calendar"))),
        Step("extension", "Save pages as you browse",
             "Drag the bookmarklet to your bookmarks bar. On a company's website it "
             "opens a new company; on someone's LinkedIn profile it opens a new "
             "contact with their employer filled in.",
             "Get the bookmarklet", "/extension", "extension" in ticked, manual=True),
        Step("find", "Find anything again",
             "The box at the top searches names, tags and people. Every table has a "
             "filter per column: type text to match it, !text for everything that "
             "does not contain it, =text for an exact match, >5 or <5 for numbers "
             "and dates, - for empty and * for not empty. The ? next to Filter has "
             "the list. And Ask the Hermit answers a question in plain words"
             + ("" if ai_available else ", once an AI CLI is set up under Settings")
             + ".",
             "Try a filter", "/companies", "find" in ticked, manual=True),
    ]


def progress(all_steps: list[Step]) -> tuple[int, int]:
    return sum(1 for s in all_steps if s.done), len(all_steps)


def should_show(config: dict, all_steps: list[Step]) -> bool:
    """Whether a fresh start lands on /welcome instead of the home page."""
    if config.get("welcome_dismissed"):
        return False
    done, total = progress(all_steps)
    return done < total
