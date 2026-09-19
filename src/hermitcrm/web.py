"""FastAPI application: server-rendered HTML over the Markdown file store.

Every mutation goes through ``Store``; the store's ``on_write`` hook
regenerates PIPELINE.md and commits, so the files on disk and git history stay
the single source of truth.
"""

from __future__ import annotations

import calendar
import hashlib
import hmac
import ipaddress
import json
import logging
import platform as platform_info
import socket
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import quote, urlencode, urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import __version__, updates
from fastapi.templating import Jinja2Templates

from . import (bcc, brief, calendar_sync, capture, feedback, fields as custom, filters,
               followups, messaging, migrations, pipeline, reports, welcome)
from . import schedule, scrape, usertheme
from . import help as helpdocs
from . import setup as setup_steps
from .filters import Column
from .enrich import Enricher, EnrichError, model_label
from . import ask as asking
from .scrape import ScrapeError
from .importer import (
    CONTACT_COLUMNS,
    CONTACT_PREFIXES,
    MODES,
    alias_help,
    apply_import,
    decode_upload,
    parse_table,
    plan_import,
)
from .gitops import GitOps
from .models import (
    Channel,
    Company,
    DEFAULT_OUTCOMES,
    Direction,
    Role,
    Country,
    Source,
    Stage,
    TaskStatus,
    ValidationError,
    fmt_date,
    fmt_datetime,
    normalise_email,
    normalise_website,
    safe_href,
    parse_date,
    slugify,
    split_name,
)
from .store import (
    COMPANY_MERGE_FIELDS, CONTACT_MERGE_FIELDS, DEFAULT_CONFIG, Store, load_config,
    normalise_body,
)

logger = logging.getLogger("crm.web")

HERE = Path(__file__).resolve().parent
BASE_URL = "http://127.0.0.1:8765"

BOARD_STAGES = ["prospect", "engaged", "discovery", "offer"]
BOARD_CLOSED = ["won", "lost", "disqualified", "temp-disqualified"]
STAGES = [s.value for s in Stage]
SOURCES = [s.value for s in Source]
COUNTRIES = [c.value for c in Country]
TASK_STATUSES = [t.value for t in TaskStatus]
ROLES = [r.value for r in Role]
CHANNELS = [c.value for c in Channel]
DIRECTIONS = [d.value for d in Direction]


def message_statuses(outcomes: list[str]) -> list[str]:
    """Every value the Messages tab can show: the config outcomes plus "unknown"."""
    return [o for o in outcomes if o] + ["unknown"]


def asset_version(folder: Path = HERE / "static") -> str:
    """The ?v= on static URLs: a hash of the files, not the version number, so an
    update within one version (a rebuilt tarball) never shows yesterday's
    stylesheet from the browser's cache."""
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()[:10]


# --------------------------------------------------------------------- filters


def custom_columns(defs: list, view: str) -> list[Column]:
    """Filterable columns for the user's own fields.

    `Column` already takes a getter, so a custom field needs no change to the
    filter engine at all: it reads out of `extra` and the whole operator
    syntax (`!foo`, `>5`, `-`, `*`) works on it unmodified.
    """
    kinds = {"number": "number", "date": "date", "select": "enum", "text": "text"}
    return [
        Column(d.key, d.label, kinds.get(d.type, "text"),
               options=list(d.options),
               getter=(lambda key: lambda obj: (getattr(obj, "extra", None) or {}).get(key))(d.key))
        for d in defs if d.shows_in(view)
    ]


def company_columns(defs: list | None = None) -> list[Column]:
    return [
        Column("name", "name"),
        Column("country", "country", "enum", COUNTRIES),
        Column("stage", "stage", "enum", STAGES),
        Column("source", "source", "enum", SOURCES),
        *custom_columns(defs or [], "companies"),
        Column("tags", "tags"),
        Column("last_touch", "last touch", "date"),
        Column("next_step", "next step"),
        Column("next_step_due", "due", "date"),
    ]


def board_columns(defs: list | None = None) -> list[Column]:
    return [
        Column("stage", "columns", "enum", BOARD_STAGES),
        Column("name", "name"),
        Column("country", "country", "enum", COUNTRIES),
        Column("source", "source", "enum", SOURCES),
        *custom_columns(defs or [], "board"),
        Column("tags", "tags"),
        Column("next_step_due", "due", "date"),
    ]


class ContactRow:
    """One row of the Contacts tab: a contact with its company attached."""

    def __init__(self, company: Company, contact):
        self.company = company
        self.contact = contact
        self.slug = contact.slug
        self.name = contact.name
        self.title = contact.title
        self.role = contact.role
        self.email = contact.email
        self.linkedin = contact.linkedin
        self.company_name = company.name
        self.company_slug = company.slug
        self.extra = contact.extra  # custom fields read from here
        self.last_touch = company.contact_last_touch(contact.slug)
        self.interaction_count = sum(
            1 for i in company.interactions if i.contact == contact.slug)


def contact_columns(defs: list | None = None) -> list[Column]:
    return [
        Column("name", "name"),
        Column("company_name", "company"),
        Column("title", "title"),
        Column("email", "email"),
        Column("linkedin", "linkedin"),
        Column("last_touch", "last touch", "date"),
        Column("interaction_count", "interactions", "number"),
        *custom_columns(defs or [], "contacts"),
    ]


class MessageRow:
    """One outbound message on the Messages tab, with its derived outcome."""

    def __init__(self, company: Company, it, status: str, uses: int):
        self.company = company
        self.it = it
        self.id = it.id
        self.date = it.date
        self.company_name = company.name
        self.company_slug = company.slug
        self.contact = contact_label(company, it.contact)
        self.contact_slug = it.contact
        self.channel = it.channel
        self.subject = it.subject
        self.body = it.body
        self.preview = " ".join(it.body.split())
        self.status = status
        self.explicit = it.outcome  # "" when the status was derived
        self.uses = uses
        self.country = company.country
        self.language = company.language
        self.stage = company.stage
        self.extra = it.extra  # custom fields read from here


def message_columns(statuses: list[str], defs: list | None = None) -> list[Column]:
    return [
        Column("date", "sent", "date"),
        Column("company_name", "company"),
        Column("contact", "contact"),
        Column("channel", "channel", "enum", CHANNELS),
        Column("country", "country", "enum", COUNTRIES),
        Column("stage", "stage", "enum", STAGES),
        Column("status", "outcome", "enum", statuses),
        Column("uses", "uses", "number"),
        *custom_columns(defs or [], "messages"),
        Column("body", "message"),
    ]


def normalised_body(text: str) -> str:
    return " ".join((text or "").split()).lower()


def sort_url_for(request: Request):
    """Builder for header links: keeps every filter, swaps sort/dir."""
    path = request.url.path

    def build(key: str, direction: str = "asc") -> str:
        params = [(k, v) for k, v in request.query_params.multi_items()
                  if k not in ("sort", "dir", "flash")]
        if key:
            params += [("sort", key), ("dir", direction)]
        return path + ("?" + urlencode(params) if params else "")
    return build


def merge_rows(keep, drop, fields, labels: dict | None = None,
               defs: list | None = None) -> list[dict]:
    """Side-by-side rows for the merge page with the default choice filled in.

    Custom fields get a row like any other: a merge that silently kept one
    side's user-defined values would lose work without saying so.
    """
    labels = dict(labels or {})
    fields = list(fields)
    custom_keys = set()
    for d in (defs or []):
        fields.append(d.key)
        labels[d.key] = d.label
        custom_keys.add(d.key)
    rows = []
    for key in fields:
        if key in custom_keys:
            a, b = (keep.extra or {}).get(key), (drop.extra or {}).get(key)
        else:
            a, b = getattr(keep, key), getattr(drop, key)
        empty_a = a in ("", None, [])
        rows.append({
            "key": key,
            "label": labels.get(key, key.replace("_", " ")),
            "keep": a, "drop": b,
            "default": "drop" if empty_a and b not in ("", None, []) else "keep",
            "both": key in ("tags", "notes"),
        })
    return rows


# --------------------------------------------------------------------- helpers


def company_matches(store: Store, name: str, website: str = "") -> list[Company]:
    """Existing companies a new one with this name or website would double:
    the same name ignoring case and legal suffixes (GmbH, BV, Ltd...), or the
    website's host among the company's domains (bcc.company_domains)."""
    key = slugify(name, strip_legal=True, default="")
    host = bcc._host(website) if website else ""
    hits = [c for c in store.companies.values()
            if (key and slugify(c.name, strip_legal=True, default="") == key)
            or (host and host in bcc.company_domains(c))]
    return sorted(hits, key=lambda c: c.name.lower())


def contact_matches(store: Store, name: str, email: str, company_slug: str = ""):
    """(company, contact) pairs a new contact would double: the same email
    anywhere, or the same name (ignoring case and accents) at `company_slug`."""
    email = normalise_email(email)
    key = slugify(name, default="")
    return [(c, ct) for c in store.companies.values() for ct in c.contacts.values()
            if (email and ct.email == email)
            or (key and c.slug == company_slug and slugify(ct.name, default="") == key)]


def duplicate_links(store: Store, name: str, email: str, company_slug: str,
                    company_name: str = "", website: str = "") -> list[dict]:
    """What the duplicate warning lists: contacts first, then (when a company
    would be created) the companies it is close to."""
    links = [{"label": f"{ct.name} at {c.name}" + (f" ({ct.email})" if ct.email else ""),
              "url": f"/companies/{c.slug}/contacts/{ct.slug}"}
             for c, ct in contact_matches(store, name, email, company_slug)]
    if not company_slug:
        links += [{"label": f"company {c.name}" + (f" ({c.website})" if c.website else ""),
                   "url": f"/companies/{c.slug}"}
                  for c in company_matches(store, company_name, website)]
    return links


def resolve_contact_company(store: Store, text: str, email: str) -> tuple[str, str]:
    """(slug, how) for a contact's company: an existing one by slug or name
    ("name"), else the one whose domain the email has ("domain", via
    bcc.match_address), else "" and "new"."""
    try:
        return bcc.resolve_company(store, text), "name"
    except ValidationError:
        pass
    email = normalise_email(email)
    if "@" in email:
        match = bcc.match_address(store, email)
        if match.company:
            return match.company, "domain"
    return "", "new"


def website_for_new_company(website: str, email: str) -> str:
    """The given website, else https://<email domain> unless that is freemail."""
    if website.strip():
        return normalise_website(website)
    domain = normalise_email(email).rpartition("@")[2]
    return f"https://{domain}" if domain and domain not in bcc.FREEMAIL else ""


def board_sort_key(c: Company):
    """PIPELINE.md order: next_step_due asc (empty last), then last_touch desc."""
    lt = c.last_touch
    return (
        c.next_step_due is None,
        c.next_step_due or date.min,
        -(lt.timestamp() if lt else 0.0),
        c.name.lower(),
    )


def calendar_link(c: Company) -> str:
    """All-day Google Calendar event on next_step_due (§8.1). '' when no due date."""
    if not c.next_step_due:
        return ""
    start = c.next_step_due
    end = start + timedelta(days=1)
    text = f"{c.name}: {c.next_step}" if c.next_step else c.name
    details = f"{c.next_step}\n\n{BASE_URL}/companies/{c.slug}"
    return (
        "https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={quote(text, safe='')}"
        f"&dates={start:%Y%m%d}/{end:%Y%m%d}"
        f"&details={quote(details, safe='')}"
    )


def company_values(c: Company) -> dict:
    return {
        "name": c.name,
        "website": c.website,
        "linkedin": c.linkedin,
        "country": c.country,
        "source": c.source,
        "stage": c.stage,
        "lost_reason": c.lost_reason,
        "requalify_on": fmt_date(c.requalify_on),
        "value_eur_month": "" if c.value_eur_month is None else str(c.value_eur_month),
        "product_oneliner": c.product_oneliner,
        "next_step": c.next_step,
        "next_step_due": fmt_date(c.next_step_due),
        "next_step_status": c.next_step_status,
        "tags": ", ".join(c.tags),
        "notes": c.notes,
    }


def contact_values(c) -> dict:
    return {
        "first_name": c.first_name,
        "last_name": c.last_name,
        "title": c.title,
        "linkedin": c.linkedin,
        "email": c.email,
        "phone": c.phone,
        "role": c.role,
        "notes": c.notes,
    }


def contact_label(company: Company, slug: str) -> str:
    if not slug:
        return "company"
    contact = company.contacts.get(slug)
    return contact.name if contact else slug


def goto(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def flashed(path: str, message: str, anchor: str = "") -> RedirectResponse:
    url = f"{path}?flash={quote(message, safe='')}"
    if anchor:
        url += f"#{anchor}"
    return goto(url)


# ----------------------------------------------------------------- app factory


def build_enricher(config: dict) -> Enricher:
    """The AI CLI wrapper used by Enrich and Ask the Hermit, from config.toml."""
    return Enricher(
        provider=str(config.get("enrich_provider", "auto")),
        account=str(config.get("enrich_account", "subscription")),
        command=str(config.get("enrich_command", "")),
        model=str(config.get("enrich_model", "")),
        model_strong=str(config.get("enrich_model_strong", "")),
        tier=str(config.get("ai_tier") or "medium"),
        timeout=float(config.get("enrich_timeout", 180)),
    )


CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")


def safe_page(page: str) -> str:
    """A local path to answer questions about; anything else becomes /."""
    page = (page or "").strip()
    if not page.startswith("/") or page.startswith("//") or "\\" in page \
            or page.startswith("/ask") or page.startswith("/static"):
        return "/"
    return page


# ---------------------------------------------------------------- request guards
#
# Hermit CRM has no login, so the browser is the only thing between a web page
# you happen to have open and your CRM. Two checks close that gap:
#
# * Host: a page on attacker.example whose DNS answer flips to 127.0.0.1 (DNS
#   rebinding) talks to this app as if it were its own site, and could read
#   every page. Its requests carry `Host: attacker.example`. An IP address can
#   never be rebound, so IP literals always pass; names must be known.
# * Cross-site POST: any page can submit a form to 127.0.0.1:8765. Browsers
#   say where a request came from (Sec-Fetch-Site, else Origin, else Referer);
#   a write that another site started is refused. Requests with none of these
#   headers are not from a browser page (curl, scripts, tests) and pass.

# Host names accepted besides IP literals, `localhost` and config
# `allowed_hosts`. Tests add their client's "testserver" here.
EXTRA_HOST_NAMES: set[str] = set()
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def host_name(value: str) -> str:
    """The name in a Host header or URL netloc: lower case, no port, no brackets."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def is_ip(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def allowed_host_names(config: dict) -> set[str]:
    """Every host name (not IP) this app answers to."""
    names = {"localhost", *EXTRA_HOST_NAMES}
    names |= {str(h).strip().lower() for h in (config.get("allowed_hosts") or [])
              if str(h).strip()}
    bind = str(config.get("host") or "127.0.0.1").strip().lower()
    if bind and not is_ip(bind):
        names.add(bind)
    if bind in ("0.0.0.0", "::"):
        # On the network, your phone may use this machine's own name.
        machine = socket.gethostname().strip().lower()
        if machine:
            short = machine.split(".")[0]
            names |= {machine, short, f"{short}.local"}
    return names


def host_allowed(host_header: str, names: set[str]) -> bool:
    name = host_name(host_header)
    # No Host at all is not a browser, and so not a rebinding page.
    return not name or is_ip(name) or name in names


def cross_site(request: Request) -> bool:
    """True when the browser says another site's page sent this request."""
    site = request.headers.get("sec-fetch-site")
    if site:
        return site not in ("same-origin", "none")
    host = (request.headers.get("host") or "").strip().lower()
    origin = request.headers.get("origin")
    if origin is not None:
        return origin.strip() == "null" or urlparse(origin).netloc.lower() != host
    referer = request.headers.get("referer")
    if referer:
        return urlparse(referer).netloc.lower() != host
    return False


def record_version(root: Path, slug: str, cslug: str = "") -> str:
    """A short hash of a company's file (or a contact's), as a page showed it.

    The edit forms send it back, so a save made from a page opened before
    another process changed the record is caught instead of reverting it.
    """
    folder = Path(root) / "companies" / slug
    path = folder / "contacts" / f"{cslug}.md" if cslug else folder / "company.md"
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def changed_fields(submitted: dict, current: dict) -> list[str]:
    """Form fields whose submitted value is not what the record now holds."""
    def norm(value) -> str:
        return normalise_body(str(value or "")).strip()
    return [k for k in submitted if k in current and norm(submitted[k]) != norm(current[k])]


def stale_form_text(what: str, differ: list[str]) -> str:
    fields = f" It now differs from what you typed in: {', '.join(differ)}." if differ else ""
    return (f"Not saved: this {what} changed after you opened the page (another tab, "
            f"the daily import or a git pull).{fields} The form keeps what you typed; "
            "check it against the record and save again.")


def create_app(root: Path, config: dict | None = None) -> FastAPI:
    root = Path(root)
    config = dict(config) if config is not None else load_config(root)

    gitops = GitOps(
        root,
        push_enabled=bool(config.get("push_enabled", True)),
        remote=str(config.get("remote", "origin")),
    )

    def on_write(message: str) -> None:
        paths = store.take_touched()
        try:
            pipeline.write(store)
        except Exception:
            logger.exception("could not regenerate PIPELINE.md for %r", message)
        try:
            gitops.commit(message, [*paths, "PIPELINE.md"])
            gitops.push_async()
        except Exception:  # GitOps never raises, but a write must never fail here
            logger.exception("git commit/push failed for %r", message)

    # Thresholds for the follow-up radar on the home page, as radar() names them.
    followup_days = {
        "reply_after": int(config.get("followup_reply_days",
                                      DEFAULT_CONFIG["followup_reply_days"])),
        "nudge_after": int(config.get("followup_nudge_days",
                                      DEFAULT_CONFIG["followup_nudge_days"])),
    }
    outcomes = [str(o) for o in (config.get("outcomes") or DEFAULT_OUTCOMES)]
    store = Store(root, silent_days=int(config.get("silent_days", 14)),
                  on_write=on_write, outcomes=outcomes)
    store.load()

    def load_custom_fields() -> list:
        """Field definitions, or none at all when fields.toml cannot be read.

        A broken fields.toml must not stop the app: the values it describes are
        in the files either way, and `hermitcrm check` is where the reason
        belongs.
        """
        try:
            return custom.load(root)
        except custom.FieldError:
            return []

    messages = messaging.load_messages(root)
    app = FastAPI(title="Hermit CRM")
    app.state.messages = messages
    app.state.update_notice = updates.UpdateNotice()
    if config.get("start_update_check"):  # set by `hermitcrm serve`; tests stay offline
        app.state.update_notice.start(config)
    app.state.store = store
    app.state.custom_fields = load_custom_fields()
    app.state.gitops = gitops
    app.state.config = config
    app.state.enricher = build_enricher(config)
    fetch_timeout = float(config.get("fetch_timeout", 10))
    app.state.fetcher = lambda url: scrape.fetch(url, timeout=fetch_timeout)
    message_window = int(config.get("message_window_days", 14))
    bcc_settings = bcc.settings_from_config(config)
    inbox = bcc.Inbox(root)
    app.state.bcc_settings = bcc_settings
    app.state.inbox = inbox
    app.state.open_mailbox = lambda: bcc.open_gmail(app.state.bcc_settings, root)
    cal_settings = calendar_sync.settings_from_config(config)
    app.state.calendar_settings = cal_settings
    # Settings page: a per-process CSRF token, redirect-once state and test seams.
    app.state.csrf_token = token_urlsafe(32)
    app.state.setup_redirected = False
    app.state.setup_runner = subprocess.run
    app.state.setup_platform = sys.platform
    app.state.setup_push = None
    app.state.setup_state = None
    app.state.schedule_home = None  # Path.home() unless a test points elsewhere
    cal_url_cache: dict[str, str] = {}

    def calendar_url(refresh: bool = False) -> str:
        """The secret ICS URL, looked up once (Keychain) and again on Import now."""
        if refresh or "url" not in cal_url_cache:
            cal_url_cache["url"] = calendar_sync.resolve_url(app.state.calendar_settings, root)
        return cal_url_cache["url"]

    app.state.calendar_url = calendar_url
    app.state.fetch_calendar = lambda url: calendar_sync.fetch_ics(url)

    def current_setup_state(refresh: bool = False) -> dict:
        if refresh or app.state.setup_state is None:
            try:
                app.state.setup_state = setup_steps.setup_state(
                    root, config, runner=app.state.setup_runner,
                    platform=app.state.setup_platform)
            except Exception:
                logger.exception("setup state failed")
                app.state.setup_state = {"you": True, "bcc": True, "backup": True,
                                         "calendar": True}
        return app.state.setup_state

    def refresh_config() -> None:
        """Re-read config.toml after a settings save and rebuild derived settings."""
        nonlocal message_window
        fresh = load_config(root)
        keep = {k: config[k] for k in ("start_update_check",) if k in config}
        config.clear()
        config.update(fresh, **keep)
        app.state.bcc_settings = bcc.settings_from_config(config)
        app.state.calendar_settings = calendar_sync.settings_from_config(config)
        gitops.push_enabled = bool(config.get("push_enabled", True))
        gitops.remote = str(config.get("remote", "origin"))
        store.silent_days = int(config.get("silent_days", 14))
        message_window = int(config.get("message_window_days", 14))
        app.state.enricher = build_enricher(config)
        app.state.custom_fields = load_custom_fields()
        cal_url_cache.clear()
        current_setup_state(refresh=True)

    def calendar_alert() -> str:
        last = inbox.last_run(calendar_sync.LAST_RUN_FILE)
        if not last or not app.state.calendar_url():
            return ""
        return bcc.run_alert(last, store.now(), "calendar import")

    app.state.index_head = gitops.last_commit_sha()

    def refresh_if_moved() -> None:
        """Reload the index when git HEAD moved since it was loaded.

        Every write by any Hermit CRM process (the daily sync, the CLI, the MCP
        server, another `serve`) is a commit, and so is a git pull; this app's
        own writes are too, which costs one reload (~0.1 s for 350 companies)
        on the page after a save. Writes re-read their record either way (see
        Store._current); this keeps the lists and the pipeline current.
        """
        head = gitops.last_commit_sha()
        if head and head != app.state.index_head:
            store.load()
            app.state.custom_fields = load_custom_fields()
            app.state.index_head = head

    @app.middleware("http")
    async def requalify_sweep(request: Request, call_next):
        # Parked companies whose "requalify on" date has arrived go back to
        # prospect the next time any page is opened (idempotent, one commit).
        if request.method == "GET" and not request.url.path.startswith("/static") \
                and request.url.path != "/theme.css":
            try:
                refresh_if_moved()
            except Exception:
                logger.exception("index refresh failed")
            try:
                store.requalify_due()
            except Exception:
                logger.exception("requalify sweep failed")
        return await call_next(request)

    @app.middleware("http")
    async def content_security_policy(request: Request, call_next):
        # Pages may only use this app's own files. That is what makes a user's
        # theme.css safe: it cannot load, or send anything to, another host.
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        return response

    host_names = allowed_host_names(config)

    @app.middleware("http")  # registered last, so it runs first
    async def request_guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if not host_allowed(host, host_names):
            logger.warning("refused request for unknown host %r", host)
            return PlainTextResponse(
                f"Hermit CRM does not answer to the host name {host_name(host)!r}. "
                "If that name is yours, add it to allowed_hosts in config.toml and "
                "restart.", status_code=400)
        if request.method in UNSAFE_METHODS and cross_site(request):
            logger.warning("refused cross-site %s %s", request.method, request.url.path)
            return PlainTextResponse(
                "Refused: this change was sent from another website's page. Make it "
                "from Hermit CRM itself.", status_code=403)
        return await call_next(request)

    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @app.get("/theme.css", include_in_schema=False)
    def user_theme_css() -> Response:
        """<data folder>/theme.css as written: the user's own look (Help > Settings)."""
        found = usertheme.path(root)
        if found is None:
            raise HTTPException(status_code=404, detail="no theme.css in the data folder")
        return Response(found.read_bytes(), media_type="text/css",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon_ico() -> RedirectResponse:
        """Browsers ask for /favicon.ico regardless of the <link> tags; point them at ours."""
        return RedirectResponse("/static/favicon.svg", status_code=301)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.globals.update(
        fmt_date=fmt_date,
        fmt_datetime=fmt_datetime,
        preview=followups.first_line,
        stages=STAGES,
        sources=SOURCES,
        countries=COUNTRIES,
        task_statuses=TASK_STATUSES,
        roles=ROLES,
        channels=CHANNELS,
        directions=DIRECTIONS,
        contact_label=contact_label,
        calendar_link=calendar_link,
        signals=messaging.SIGNALS,
        signal_labels=messaging.signal_labels(messages),
        language_names=messaging.language_names(messages),
        outcomes=outcomes,
        message_statuses=message_statuses(outcomes),
        hermitcrm_version=__version__,
        asset_version=asset_version(),
        update_notice=app.state.update_notice,
        render_markdown=helpdocs.render,
        record_version=lambda slug, cslug="": record_version(root, slug, cslug),
        custom_fields_for=lambda scope: custom.for_scope(app.state.custom_fields, scope),
    )

    templates.env.filters["slug"] = slugify  # CSS class names from outcome values
    templates.env.filters["href"] = safe_href  # stored URLs: http(s) or nothing

    def render(request: Request, name: str, ctx: dict, status_code: int = 200):
        context = {
            "flash": request.query_params.get("flash", ""),
            "q": request.query_params.get("q", ""),
            "errors": {},
            "today": store.today(),
            "sort": "", "dir": "asc", "sort_url": sort_url_for(request),
            "inbox_count": inbox.count(),
            "inbox_alert": (bcc.run_alert(inbox.last_run(), store.now())
                            or calendar_alert()),
            "enricher": app.state.enricher,
            "setup_pending": setup_steps.pending(current_setup_state()),
            "csrf_token": app.state.csrf_token,
            "help_topic": helpdocs.topic_for(request.url.path),
            "theme": str(config.get("theme") or "light"),
            "user_theme": usertheme.path(root) is not None,
            "ask_page": safe_page(request.url.path + (f"?{request.url.query}"
                                                      if request.url.query else "")),
            "model_label": model_label,
        }
        context.update(ctx)
        return templates.TemplateResponse(request, name, context,
                                          status_code=status_code)

    def need_company(slug: str, refresh: bool = False) -> Company:
        company = store.get(slug, refresh=refresh)
        if company is None:
            raise HTTPException(status_code=404, detail=f"unknown company {slug!r}")
        return company

    def custom_defs(scope: str) -> list:
        return custom.for_scope(app.state.custom_fields, scope)

    def _task_back(request: Request, slug: str, contact: str) -> str:
        """Back to the page the task was ticked on, not always the company."""
        referer = urlparse(request.headers.get("referer", "")).path
        if referer:
            return referer
        return (f"/companies/{slug}/contacts/{contact}" if contact
                else f"/companies/{slug}")

    def with_custom(values: dict, record, scope: str) -> dict:
        """Form values plus this record's custom fields, named as the form names
        them (`custom_<key>`), so one dict drives the whole form."""
        extra = getattr(record, "extra", None) or {}
        out = dict(values)
        for d in custom_defs(scope):
            out.setdefault(f"custom_{d.key}", d.display(extra.get(d.key)))
        return out

    async def custom_submitted(request: Request, scope: str) -> tuple[dict, dict, dict]:
        """(values for the store, values to re-render, errors) from a submitted form."""
        defs = custom_defs(scope)
        if not defs:
            return {}, {}, {}
        form = await request.form()
        raw = {d.key: form.get(f"custom_{d.key}", "") for d in defs}
        values, errors = custom.coerce_all(defs, raw)
        return (values,
                {f"custom_{k}": v for k, v in raw.items()},
                {f"custom_{k}": v for k, v in errors.items()})

    def interaction_values(company: Company, contact: str | None = None,
                           form: dict | None = None, channel: str = "",
                           body: str = "") -> dict:
        if form is not None:
            return form
        if contact is None:
            contact = company.latest_contact_slug
        if contact and contact not in company.contacts:
            contact = ""
        return {
            "channel": channel if channel in CHANNELS else "linkedin",
            "direction": "out",
            "contact": contact or "",
            "date": fmt_datetime(store.now()),
            "subject": "",
            "outcome": "",
            "body": body or "",
        }

    def draft_context(request: Request, company: Company, contact=None) -> dict:
        """Message drafts for a page, driven by two hand-checked signals."""
        signal = request.query_params.get("signal", "")
        observation = request.query_params.get("observation", "")
        return {
            "drafts": messaging.drafts(
                company, contact, signal, observation,
                messages=app.state.messages,
                owner_name=str(config.get("owner_name", "")),
                defs=custom_defs("company"),
                size_field=str(config.get("messaging_size_field",
                                          messaging.DEFAULT_SIZE_FIELD)),
                team_field=str(config.get("messaging_team_field",
                                          messaging.DEFAULT_TEAM_FIELD))),
            "signal": signal if signal in messaging.SIGNALS else "",
            "observation": observation,
            "draft_contact": contact,
        }

    # ------------------------------------------------------------------- home

    # What each part of the app is for, in one line, for someone who has just
    # opened it. Kept here rather than in the template because the home page
    # and the help index should not drift apart.
    AREAS = [
        ("/pipeline", "Pipeline", "pipeline",
         "Every open deal as a card, in the stage it has reached."),
        ("/calendar", "Calendar", "calendar",
         "What is due when, and your task list."),
        ("/companies", "Companies", "companies",
         "Every account as a table you can filter and sort."),
        ("/contacts", "Contacts", "contacts",
         "Every person, with the company they belong to."),
        ("/messages", "Messages", "messages",
         "What you sent, and whether it was answered."),
        ("/extension", "Extension", "capture",
         "Save the page you are looking at as a company or a contact."),
        ("/reports", "Reports", "reports",
         "Activity, funnel and outcomes over a period you choose."),
        ("/ask", "Ask the Hermit", "ask",
         "A question about the page you are on, or the whole CRM."),
    ]

    def welcome_steps() -> list:
        return welcome.steps(store, config, current_setup_state(),
                             app.state.enricher.available)

    @app.get("/welcome", response_class=HTMLResponse)
    def welcome_page(request: Request):
        app.state.setup_redirected = True
        all_steps = welcome_steps()
        done, total = welcome.progress(all_steps)
        return render(request, "welcome.html", {
            "steps": all_steps, "done": done, "total": total,
            "dismissed": bool(config.get("welcome_dismissed")),
        })

    @app.post("/welcome/tick")
    def welcome_tick(request: Request, csrf_token: str = Form(""), key: str = Form(""),
                     done: str = Form("1")):
        """Tick (or untick) a step the app cannot see happen."""
        check_csrf(csrf_token)
        if key not in welcome.MANUAL:
            return flashed("/welcome", "That step ticks itself when it is done")
        ticked = [k for k in (config.get("welcome_done") or []) if k != key]
        if done:
            ticked.append(key)
        setup_steps.set_config_values(root / "config.toml", {"welcome_done": ticked})
        refresh_config()
        return goto("/welcome#" + key)

    @app.post("/welcome/dismiss")
    def welcome_dismiss(request: Request, csrf_token: str = Form(""),
                        dismissed: str = Form("1")):
        check_csrf(csrf_token)
        setup_steps.set_config_values(root / "config.toml",
                                      {"welcome_dismissed": bool(dismissed)})
        refresh_config()
        return flashed("/" if dismissed else "/welcome",
                       "The walkthrough stays under Help" if dismissed
                       else "The walkthrough opens at start again")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        # Once per server start, a folder that has not finished the walkthrough
        # lands on it; "Skip for now" there works for the rest of the session.
        if not app.state.setup_redirected:
            app.state.setup_redirected = True
            if welcome.should_show(config, welcome_steps()):
                return goto("/welcome")
        today = store.today()
        week = today + timedelta(days=7)
        due_soon = sorted(
            (c for c in store.companies.values()
             if not c.is_closed and c.next_step_open and c.next_step_due
             and c.next_step_due <= week),
            key=lambda c: (c.next_step_due, c.name.lower()))
        tasks = sorted(
            ({"company": company, "contact": None if record is company else record,
              "index": index, "task": task}
             for company, record, index, task in store.open_tasks(today)
             if task.due and task.due <= week),
            key=lambda r: (r["task"].due, r["company"].name.lower()))
        report = build_report(reports.period_for("30d", today), today)
        return render(request, "home.html", {
            "today": today,
            "due_soon": due_soon,
            "tasks": tasks,
            "followups": followups.radar(store, today, **followup_days),
            "totals": report["activity"]["totals"],
            "previous": report["activity"]["previous"],
            "funnel": report["funnel"],
            "delta": reports.delta,
            "areas": AREAS,
            "counts": {
                "companies": len(store.companies),
                "contacts": sum(len(c.contacts) for c in store.companies.values()),
                "interactions": sum(len(c.interactions) for c in store.companies.values()),
            },
            "no_companies": not store.companies,
        })

    # ------------------------------------------------------------------ board

    @app.get("/pipeline", response_class=HTMLResponse)
    def board(request: Request):
        today = store.today()
        cols = board_columns(app.state.custom_fields)
        active = filters.parse(request.query_params, cols)
        sort_key, sort_dir = filters.parse_sort(request.query_params, cols)
        shown_stages = active.get("stage") or BOARD_STAGES
        card_filters = {k: v for k, v in active.items() if k != "stage"}
        companies = filters.apply(store.companies.values(), cols, card_filters)

        def ordered(cards):
            cards = sorted(cards, key=board_sort_key)
            return filters.sort_rows(cards, cols, sort_key, sort_dir)

        columns = [
            {"stage": stage, "companies": ordered(c for c in companies if c.stage == stage)}
            for stage in BOARD_STAGES if stage in shown_stages
        ]
        closed = {
            stage: ordered(c for c in companies if c.stage == stage)
            for stage in BOARD_CLOSED
        }
        return render(request, "board.html", {
            "columns": columns, "closed": closed, "today": today,
            "followups": followups.radar(store, today, **followup_days),
            "filter_columns": cols, "active": active,
            "sort": sort_key, "dir": sort_dir,
            "no_companies": not store.companies,
        })

    # ------------------------------------------------------------------ today

    @app.get("/today")
    def today_view(request: Request):
        """The Today lists live at the top of the Calendar page now."""
        return goto("/calendar#top-priority")

    # --------------------------------------------------------------- calendar

    @app.get("/calendar", response_class=HTMLResponse)
    def calendar_view(request: Request, month: str = ""):
        today = store.today()
        try:
            first = datetime.strptime(month, "%Y-%m").date() if month else today.replace(day=1)
        except ValueError:
            first = today.replace(day=1)
        first = first.replace(day=1)
        prev_month = (first - timedelta(days=1)).replace(day=1)
        next_month = (first + timedelta(days=32)).replace(day=1)
        open_tasks = sorted(
            (c for c in store.companies.values() if not c.is_closed and c.next_step_open),
            key=lambda c: (c.next_step_due is None, c.next_step_due or date.min,
                           c.name.lower()),
        )
        priority = [c for c in open_tasks if c.next_step_due and c.next_step_due <= today]
        future = [c for c in open_tasks if c not in priority]
        silent = sorted(
            (c for c in store.companies.values()
             if c.is_active and c.silent_days(today) >= store.silent_days),
            key=lambda c: (-c.silent_days(today), c.name.lower()),
        )
        by_day: dict[date, list[Company]] = {}
        for c in open_tasks:
            if c.next_step_due:
                by_day.setdefault(c.next_step_due, []).append(c)
        # The other tasks: a company's own list and its contacts', on their day.
        listed = [
            {"company": company, "contact": None if record is company else record,
             "index": index, "task": task}
            for company, record, index, task in store.open_tasks(today)
        ]
        tasks_by_day: dict[date, list[dict]] = {}
        for row in listed:
            if row["task"].due:
                tasks_by_day.setdefault(row["task"].due, []).append(row)
        weeks = [
            [{"date": d, "tasks": by_day.get(d, []), "listed": tasks_by_day.get(d, [])}
             for d in week]
            for week in calendar.Calendar(firstweekday=0).monthdatescalendar(
                first.year, first.month)
        ]
        listed_due = sorted((r for r in listed if r["task"].due),
                            key=lambda r: (r["task"].due, r["company"].name.lower()))
        listed_undated = [r for r in listed if not r["task"].due]
        return render(request, "calendar.html", {
            "today": today,
            "first": first,
            "prev_month": prev_month,
            "next_month": next_month,
            "weeks": weeks,
            "open_tasks": open_tasks,
            "listed_overdue": [r for r in listed_due if r["task"].due <= today],
            "listed_future": [r for r in listed_due if r["task"].due > today],
            "listed_undated": listed_undated,
            "companies": store.all(),
            "priority": priority,
            "future": future,
            "silent": silent,
            "silent_threshold": store.silent_days,
            "upcoming": brief.briefs(store, inbox, store.now()),
            "calendar_last_run": inbox.last_run(calendar_sync.LAST_RUN_FILE),
        })

    @app.post("/calendar/task")
    def calendar_task(request: Request, text: str = Form(""), company: str = Form(""),
                      contact: str = Form(""), due: str = Form("")):
        """Create a task from the calendar: pick the company, optionally the person."""
        try:
            slug = bcc.resolve_company(store, company)
        except ValidationError:
            return flashed("/calendar", f"No company called {company!r}", "task-list")
        try:
            store.add_task(slug, text, due=due, contact=contact.strip())
        except ValidationError as exc:
            return flashed("/calendar", "; ".join(exc.errors.values()), "task-list")
        return flashed("/calendar", "Task created", "task-list")

    @app.post("/calendar/import")
    def calendar_import(request: Request, back: str = Form("/calendar")):
        # "/inbox" is the old name of the review queue, now on the Settings page.
        back = "/settings" if back in ("/inbox", "/settings") else "/calendar"
        anchor = "inbox" if back == "/settings" else ""
        url = app.state.calendar_url(refresh=True)
        if not url:
            return flashed(back, "Calendar import failed: "
                           + calendar_sync.setup_hint(app.state.calendar_settings), anchor)
        fetch = app.state.fetch_calendar
        try:
            result = calendar_sync.run_calendar(store, inbox, app.state.calendar_settings, True,
                                                lambda: fetch(url))
        except calendar_sync.CalendarError as exc:
            logger.warning("calendar import failed: %s", exc)
            return flashed(back, f"Calendar import failed: {exc}", anchor)
        except Exception as exc:
            logger.exception("calendar import crashed")
            return flashed(back, f"Calendar import failed: {type(exc).__name__}: {exc}", anchor)
        return flashed(back, "Calendar import: " + result.summary(), anchor)

    # ---------------------------------------------------------------- import

    def _import_page(request: Request, text: str, mode: str = "", errors=None,
                     status_code: int = 200):
        return render(request, "import.html", {
            "text": text, "mode": mode, "modes": MODES, "errors": errors or {},
            "company_aliases": alias_help("companies"),
            "contact_aliases": alias_help("contacts"),
            "prefixes": CONTACT_PREFIXES,
            "prefixed_columns": sorted(set(CONTACT_COLUMNS)),
        }, status_code=status_code)

    @app.get("/import", response_class=HTMLResponse)
    def import_form(request: Request, mode: str = ""):
        return _import_page(request, "", mode if mode in MODES else "")

    def _import_text(text: str, upload) -> str:
        if upload is not None and getattr(upload, "filename", ""):
            return decode_upload(upload.file.read())
        return text

    def _form_mapping(form, text: str) -> dict | None:
        """Per-column choices posted as map_<index>; dropped when the mode changed."""
        if form.get("prev_mode") and form.get("prev_mode") != form.get("mode"):
            return None
        headers, _ = parse_table(text)
        mapping = {h: str(form[f"map_{i}"]) for i, h in enumerate(headers)
                   if h and f"map_{i}" in form}
        return mapping or None

    @app.post("/import/preview", response_class=HTMLResponse)
    async def import_preview(request: Request):
        form = await request.form()
        text = str(form.get("text") or "")
        mode = str(form.get("mode") or "")
        try:
            text = _import_text(text, form.get("file"))
            plan = plan_import(store, text, mode=mode or None,
                               mapping=_form_mapping(form, text),
                               defs=app.state.custom_fields)
        except ValidationError as exc:
            return _import_page(request, text, mode, exc.errors, status_code=400)
        return render(request, "import_preview.html",
                      {"plan": plan, "text": text, "modes": MODES})

    @app.post("/import")
    async def import_apply(request: Request):
        form = await request.form()
        text = str(form.get("text") or "")
        mode = str(form.get("mode") or "")
        try:
            plan = plan_import(store, text, mode=mode or None,
                               mapping=_form_mapping(form, text),
                               defs=app.state.custom_fields)
        except ValidationError as exc:
            return _import_page(request, text, mode, exc.errors, status_code=400)
        counts = apply_import(store, plan)
        if plan.mode == "contacts":
            message = (f"Imported: {counts['contacts']} contacts created, "
                       f"{counts['contacts_updated']} updated, {counts['created']} "
                       f"companies created, {counts['updated']} updated, "
                       f"{counts['skipped']} rows skipped")
        else:
            message = (f"Imported: {counts['created']} companies created, "
                       f"{counts['updated']} updated, {counts['contacts']} contacts created, "
                       f"{counts['skipped']} rows skipped")
        if counts["failed"]:
            message += f", {counts['failed']} rows failed"
        return flashed("/companies", message)

    # ---------------------------------------------------------------- enrich

    def _proposal_page(request: Request, company: Company, proposal, action: str,
                       title: str, back: str, retry: str = "", enricher=None):
        return render(request, "enrich_preview.html", {
            "company": company, "proposal": proposal, "action": action,
            "title": title, "back": back, "retry": retry, "ran": enricher,
        })

    def tiered(request: Request) -> Enricher:
        tier = request.query_params.get("tier", "")
        enricher = app.state.enricher
        return enricher.with_tier(tier) if tier else enricher

    @app.post("/companies/{slug}/enrich", response_class=HTMLResponse)
    def company_enrich(request: Request, slug: str):
        company = need_company(slug, refresh=True)
        try:
            enricher = tiered(request)
            proposal = enricher.propose_company(company, custom_defs('company'))
        except EnrichError as exc:
            return flashed(f"/companies/{slug}", str(exc))
        if not proposal.missing:
            return flashed(f"/companies/{slug}", "Nothing to enrich: every field is set")
        if not proposal.fields:
            return flashed(f"/companies/{slug}",
                           "Enrichment found nothing it could verify" +
                           (f": {proposal.notes}" if proposal.notes else ""))
        return _proposal_page(request, company, proposal,
                              f"/companies/{slug}/enrich/apply",
                              f"Enrich {company.name}", f"/companies/{slug}",
                              retry=f"/companies/{slug}/enrich", enricher=enricher)

    @app.post("/companies/{slug}/enrich/apply")
    async def company_enrich_apply(request: Request, slug: str):
        need_company(slug)
        form = await request.form()
        chosen = {key: form.get(key, "") for key in form.getlist("apply")}
        if not chosen:
            return flashed(f"/companies/{slug}", "Nothing applied")
        try:
            store.update_company(slug, message=f"ai: company {slug} enriched", **chosen)
        except ValidationError as exc:
            return flashed(f"/companies/{slug}", "; ".join(exc.errors.values()))
        return flashed(f"/companies/{slug}", "Enriched: " + ", ".join(sorted(chosen)))

    @app.post("/companies/{slug}/fetch", response_class=HTMLResponse)
    def company_fetch(request: Request, slug: str, url: str = Form("")):
        """Free enrichment: read the website or LinkedIn page itself."""
        company = need_company(slug, refresh=True)
        url = (url or "").strip() or company.website or company.linkedin
        if not url:
            return flashed(f"/companies/{slug}", "Give a website or LinkedIn URL to fetch")
        try:
            proposal = scrape.propose_from_url(
                company, url, fetcher=app.state.fetcher,
                custom_keys={d.key for d in custom_defs('company')})
        except ScrapeError as exc:
            return flashed(f"/companies/{slug}", str(exc))
        if not proposal.missing:
            return flashed(f"/companies/{slug}", "Nothing to enrich: every field is set")
        if not proposal.fields:
            return flashed(f"/companies/{slug}", "The page gave nothing for the empty fields"
                           + (f" ({proposal.notes})" if proposal.notes else ""))
        return _proposal_page(request, company, proposal,
                              f"/companies/{slug}/enrich/apply",
                              f"Fetched from {url}", f"/companies/{slug}")

    @app.post("/companies/{slug}/contacts/{cslug}/enrich", response_class=HTMLResponse)
    def contact_enrich(request: Request, slug: str, cslug: str):
        company = need_company(slug, refresh=True)
        contact = company.contacts.get(cslug)
        if contact is None:
            raise HTTPException(status_code=404, detail=f"unknown contact {cslug!r}")
        back = f"/companies/{slug}/contacts/{cslug}"
        try:
            enricher = tiered(request)
            proposal = enricher.propose_contact(company, contact,
                                                custom_defs('contact'))
        except EnrichError as exc:
            return flashed(back, str(exc))
        if not proposal.missing:
            return flashed(back, "Nothing to enrich: every field is set")
        if not proposal.fields and not proposal.sources:
            return flashed(back, "Enrichment found nothing it could verify" +
                           (f": {proposal.notes}" if proposal.notes else ""))
        # Nothing verified but sources found (say, a profile at another
        # company): show the page, so the notes and links can be checked by hand.
        return _proposal_page(request, company, proposal, f"{back}/enrich/apply",
                              f"Enrich {contact.name}", back, retry=f"{back}/enrich",
                              enricher=enricher)

    @app.post("/companies/{slug}/contacts/{cslug}/enrich/apply")
    async def contact_enrich_apply(request: Request, slug: str, cslug: str):
        company = need_company(slug)
        back = f"/companies/{slug}/contacts/{cslug}"
        if cslug not in company.contacts:
            raise HTTPException(status_code=404, detail=f"unknown contact {cslug!r}")
        form = await request.form()
        chosen = {key: form.get(key, "") for key in form.getlist("apply")}
        if not chosen:
            return flashed(back, "Nothing applied")
        try:
            store.update_contact(slug, cslug,
                                 message=f"ai: contact {slug}/{cslug} enriched", **chosen)
        except ValidationError as exc:
            return flashed(back, "; ".join(exc.errors.values()))
        return flashed(back, "Enriched: " + ", ".join(sorted(chosen)))

    # -------------------------------------------------------------- companies

    @app.get("/companies", response_class=HTMLResponse)
    def companies_list(request: Request, q: str = ""):
        cols = company_columns(app.state.custom_fields)
        active = filters.parse(request.query_params, cols)
        sort_key, sort_dir = filters.parse_sort(request.query_params, cols)
        companies = filters.apply(store.search(q), cols, active)
        show_parked = (request.query_params.get("parked") == "1"
                       or "temp-disqualified" in active.get("stage", []))
        hidden = 0
        if not show_parked:
            hidden = sum(1 for c in companies if c.is_parked)
            companies = [c for c in companies if not c.is_parked]
        companies = filters.sort_rows(companies, cols, sort_key, sort_dir)
        toggle = [(k, v) for k, v in request.query_params.multi_items()
                  if k not in ("parked", "flash")]
        if not show_parked:
            toggle.append(("parked", "1"))
        return render(request, "companies.html", {
            "companies": companies, "q": q, "filter_columns": cols, "active": active,
            "sort": sort_key, "dir": sort_dir, "show_parked": show_parked,
            "hidden_parked": hidden,
            "toggle_url": "/companies" + ("?" + urlencode(toggle) if toggle else ""),
        })

    @app.get("/contacts", response_class=HTMLResponse)
    def contacts_list(request: Request, q: str = ""):
        cols = contact_columns(app.state.custom_fields)
        active = filters.parse(request.query_params, cols)
        sort_key, sort_dir = filters.parse_sort(request.query_params, cols)
        needle = (q or "").strip().lower()
        rows = []
        for company in store.companies.values():
            for contact in company.contacts.values():
                row = ContactRow(company, contact)
                haystack = (row.name, row.email, row.title, row.company_name)
                if needle and not any(needle in (h or "").lower() for h in haystack):
                    continue
                rows.append(row)
        rows = filters.apply(rows, cols, active)
        rows.sort(key=lambda r: (r.name.lower(), r.company_name.lower()))
        rows = filters.sort_rows(rows, cols, sort_key, sort_dir)
        return render(request, "contacts.html", {
            "rows": rows, "q": q, "filter_columns": cols, "active": active,
            "sort": sort_key, "dir": sort_dir,
        })

    # --------------------------------------------------------------- messages

    @app.get("/messages", response_class=HTMLResponse)
    def messages_list(request: Request, q: str = ""):
        today = store.today()
        cols = message_columns(message_statuses(outcomes), app.state.custom_fields)
        active = filters.parse(request.query_params, cols)
        sort_key, sort_dir = filters.parse_sort(request.query_params, cols)
        needle = (q or "").strip().lower()
        uses = Counter(
            normalised_body(i.body) for c in store.companies.values()
            for i in c.interactions if i.is_message)
        rows = []
        for company in store.companies.values():
            for it in company.interactions:
                if not it.is_message:
                    continue
                status = company.message_status(it, today, message_window, outcomes)
                rows.append(MessageRow(company, it, status, uses[normalised_body(it.body)]))
        counts = Counter(r.status for r in rows)
        if needle:
            rows = [r for r in rows if needle in r.preview.lower()
                    or needle in r.company_name.lower() or needle in r.contact.lower()]
        rows = filters.apply(rows, cols, active)
        rows.sort(key=lambda r: (r.date or datetime.min), reverse=True)
        rows = filters.sort_rows(rows, cols, sort_key, sort_dir)
        return render(request, "messages.html", {
            "rows": rows, "q": q, "filter_columns": cols, "active": active,
            "sort": sort_key, "dir": sort_dir, "counts": counts,
            "window": message_window,
        })

    def report_span(period: str, params, today) -> reports.Period:
        """The period of a /reports query (custom reads from/to); raises
        ValueError or ValidationError for a bad name or dates."""
        start = parse_date(params.get("from", "")) if period == "custom" else None
        end = parse_date(params.get("to", "")) if period == "custom" else None
        return reports.period_for(period, today, start, end)

    def report_error(exc: Exception) -> str:
        return "; ".join(exc.errors.values()) if isinstance(exc, ValidationError) else str(exc)

    def build_report(span: reports.Period, today) -> dict:
        return reports.build(store, span, today, message_window, config.get("outcomes"))

    @app.get("/reports", response_class=HTMLResponse)
    def reports_page(request: Request, period: str = "30d"):
        today = store.today()
        params = request.query_params
        error = ""
        try:
            span = report_span(period, params, today)
        except (ValueError, ValidationError) as exc:
            error = report_error(exc)
            period, span = "30d", reports.period_for("30d", today)
        from_value = params.get("from", "") or fmt_date(span.start)
        to_value = params.get("to", "") or fmt_date(span.end)
        return render(request, "reports.html", {
            "report": build_report(span, today),
            "period": period, "periods": reports.PERIODS, "error": error,
            "from_value": from_value, "to_value": to_value,
            "delta": reports.delta,
            # Query string the number links carry so the rows page shows the same period.
            "rows_query": reports.period_query(period, from_value, to_value),
        })

    @app.get("/reports/rows", response_class=HTMLResponse)
    def report_rows_page(request: Request, key: str = "", period: str = "30d"):
        """The rows behind one number of the report: `key` as registered by
        reports.Rows for the same period."""
        today = store.today()
        params = request.query_params
        try:
            span = report_span(period, params, today)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail=report_error(exc))
        report = build_report(span, today)
        registry = report["rows"]
        if key not in registry:
            raise HTTPException(status_code=404, detail=f"unknown report key {key!r}")
        rows = registry.get(key)
        return render(request, "report_rows.html", {
            "key": key, "title": registry.label(key), "rows": rows,
            "columns": reports.row_columns(rows), "report": report, "period": period,
            "back": "/reports?" + reports.period_query(period, params.get("from", ""),
                                                      params.get("to", "")),
        })

    @app.post("/companies/{slug}/interactions/{id}/outcome")
    def interaction_outcome(request: Request, slug: str, id: str,
                            outcome: str = Form("")):
        """Set the outcome of a sent message from the Messages tab buttons
        (one of the config outcomes, or empty for not yet known)."""
        company = need_company(slug)
        if not any(i.id == id for i in company.interactions):
            raise HTTPException(status_code=404, detail=f"unknown interaction {id!r}")
        try:
            store.update_interaction(slug, id, outcome=outcome)
        except ValidationError as exc:
            return flashed("/messages", "; ".join(exc.errors.values()))
        back = urlparse(request.headers.get("referer", "")).path or "/messages"
        return flashed(back, f"Message marked {outcome or 'unknown'}")

    # --------------------------------------------------------------- extension

    def bookmarklet_for(request: Request) -> str:
        """The bookmarklet, pointed at whatever address this app is answering on.

        Built from the request rather than from config, so a `serve --host`
        session hands out a bookmarklet that works from the phone that asked.
        """
        return capture.bookmarklet(str(request.base_url).rstrip("/"))

    @app.get("/extension", response_class=HTMLResponse)
    def extension_page(request: Request):
        return render(request, "extension.html", {
            "bookmarklet": bookmarklet_for(request),
            "base": str(request.base_url).rstrip("/"),
        })

    @app.get("/capture", include_in_schema=False)
    def capture_moved():
        """Bookmarklets already sitting in someone's bar point here."""
        return goto("/extension")

    @app.get("/capture/new", include_in_schema=False)
    def capture_new_moved(url: str = ""):
        return goto(("/extension/new?url=" + quote(url, safe="")) if url else "/extension")

    @app.get("/extension/new", response_class=HTMLResponse)
    def extension_new(request: Request, url: str = ""):
        """Read a page and open the new-company form with it filled in.

        A GET, because that is what a bookmarklet can open in a tab; it only
        reads the page and renders a form, and writes nothing.
        """
        if not (url or "").strip():
            return goto("/extension")
        page = dict(request.query_params)
        try:
            if page.get("v") and scrape.PERSON_URL.search(url):
                # read in your own logged-in tab by the bookmarklet: no fetch
                found = capture.from_page(store, url, page)
            else:
                found = capture.from_url(
                    store, url, fetcher=app.state.fetcher,
                    custom_keys={d.key for d in custom_defs('company')})
        except ScrapeError as exc:
            return flashed("/extension", f"Could not read that page: {exc}")
        if found.kind == "person":
            if found.existing is not None:
                cslug = capture.contact_slug_in(found.existing, found.url)
                where = (f"/companies/{found.existing.slug}/contacts/{cslug}" if cslug
                         else f"/companies/{found.existing.slug}")
                return flashed(where, f"{found.name or 'That profile'} is already "
                                      "in the CRM")
            return _global_contact_page(request, found.contact_values, capture=found)
        if found.existing is not None:
            return flashed(f"/companies/{found.existing.slug}",
                           f"{found.existing.name} is already in the CRM")
        return render(request, "company_new.html",
                      {"values": with_custom(found.values, None, "company"),
                       "capture": found})

    @app.get("/companies/new", response_class=HTMLResponse)
    def company_new(request: Request):
        values = {
            "name": "", "website": "", "linkedin": "", "country": "", "source": "other",
            "stage": "prospect", "lost_reason": "", "requalify_on": "", "value_eur_month": "",
            "product_oneliner": "",
            "next_step": "", "next_step_due": "", "next_step_status": "open",
            "tags": "", "notes": "",
        }
        return render(request, "company_new.html",
                      {"values": with_custom(values, None, "company")})

    @app.post("/companies")
    async def company_create(
        request: Request,
        name: str = Form(""),
        website: str = Form(""),
        linkedin: str = Form(""),
        country: str = Form(""),
        source: str = Form("other"),
        stage: str = Form("prospect"),
        lost_reason: str = Form(""),
        requalify_on: str = Form(""),
        value_eur_month: str = Form(""),
        product_oneliner: str = Form(""),
        next_step: str = Form(""),
        next_step_due: str = Form(""),
        next_step_status: str = Form("open"),
        tags: str = Form(""),
        notes: str = Form(""),
    ):
        values = {
            "name": name, "website": website, "linkedin": linkedin,
            "country": country, "source": source, "stage": stage,
            "lost_reason": lost_reason, "requalify_on": requalify_on,
            "value_eur_month": value_eur_month, "product_oneliner": product_oneliner,
            "next_step": next_step,
            "next_step_due": next_step_due, "next_step_status": next_step_status,
            "tags": tags, "notes": notes,
        }
        extra, shown, custom_errors = await custom_submitted(request, "company")
        if custom_errors:
            return render(request, "company_new.html",
                          {"values": {**values, **shown}, "errors": custom_errors},
                          status_code=400)
        try:
            company = store.create_company(custom=extra, **values)
        except ValidationError as exc:
            return render(request, "company_new.html",
                          {"values": {**values, **shown}, "errors": exc.errors},
                          status_code=400)
        return flashed(f"/companies/{company.slug}", "Company created")

    @app.get("/companies/{slug}", response_class=HTMLResponse)
    def company_page(request: Request, slug: str):
        company = need_company(slug, refresh=True)
        interaction = interaction_values(company)
        draft_contact = company.contacts.get(interaction["contact"]) or next(
            iter(company.contacts.values()), None)
        return render(request, "company.html", {
            "company": company,
            "values": with_custom(company_values(company), company, "company"),
            "interaction": interaction,
            "focus": request.query_params.get("focus", ""),
            "others": sorted((c for c in store.companies.values() if c.slug != slug),
                             key=lambda c: c.name.lower()),
            **draft_context(request, company, draft_contact),
        })

    @app.post("/companies/{slug}")
    async def company_update(
        request: Request,
        slug: str,
        name: str = Form(""),
        website: str = Form(""),
        linkedin: str = Form(""),
        country: str = Form(""),
        source: str = Form("other"),
        stage: str = Form("prospect"),
        lost_reason: str = Form(""),
        requalify_on: str = Form(""),
        value_eur_month: str = Form(""),
        product_oneliner: str = Form(""),
        next_step: str = Form(""),
        next_step_due: str = Form(""),
        next_step_status: str = Form("open"),
        tags: str = Form(""),
        notes: str = Form(""),
        version: str = Form(""),
    ):
        company = need_company(slug)
        values = {
            "name": name, "website": website, "linkedin": linkedin,
            "country": country, "source": source, "stage": stage,
            "lost_reason": lost_reason, "requalify_on": requalify_on,
            "value_eur_month": value_eur_month, "product_oneliner": product_oneliner,
            "next_step": next_step,
            "next_step_due": next_step_due, "next_step_status": next_step_status,
            "tags": tags, "notes": notes,
        }
        extra, shown, custom_errors = await custom_submitted(request, "company")
        if version and version != record_version(root, slug):
            current = need_company(slug, refresh=True)
            return render(request, "company.html", {
                "company": current,
                "values": {**values, **shown},
                "flash": stale_form_text("company",
                                         changed_fields(values, company_values(current))),
                "interaction": interaction_values(current),
                "focus": "",
                "others": [],
                **draft_context(request, current,
                                next(iter(current.contacts.values()), None)),
            }, status_code=409)
        try:
            if custom_errors:
                raise ValidationError(custom_errors)
            store.update_company(slug, custom=extra, **values)
        except ValidationError as exc:
            return render(request, "company.html", {
                "company": company,
                "values": {**values, **shown},
                "errors": exc.errors,
                "interaction": interaction_values(company),
                "focus": "lost_reason" if "lost_reason" in exc.errors else "",
                "others": [],
                **draft_context(request, company,
                                next(iter(company.contacts.values()), None)),
            }, status_code=400)
        return flashed(f"/companies/{slug}", "Saved")

    @app.post("/companies/{slug}/next-step")
    def company_next_step_status(request: Request, slug: str,
                                 status: str = Form("open")):
        """Mark the next step done, or reopen it, from a one-click button."""
        need_company(slug)
        try:
            store.update_company(slug, next_step_status=status)
        except ValidationError as exc:
            return flashed(f"/companies/{slug}", "; ".join(exc.errors.values()))
        back = urlparse(request.headers.get("referer", "")).path or f"/companies/{slug}"
        word = "done" if status == TaskStatus.DONE.value else "reopened"
        return flashed(back, f"Next step {word}", "tasks" if back.startswith("/companies/") else "")

    @app.post("/companies/{slug}/task")
    def company_task(request: Request, slug: str, next_step: str = Form(""),
                     next_step_due: str = Form("")):
        """Set the next step and its due date from the Tasks section; it starts open."""
        need_company(slug)
        back = urlparse(request.headers.get("referer", "")).path or f"/companies/{slug}"
        try:
            store.update_company(slug, next_step=next_step, next_step_due=next_step_due,
                                 next_step_status="open",
                                 message=f"company: {slug} next step set")
        except ValidationError as exc:
            return flashed(back, "; ".join(exc.errors.values()), "tasks")
        return flashed(back, "Task saved", "tasks")

    @app.post("/companies/{slug}/tasks")
    def task_add(request: Request, slug: str, text: str = Form(""),
                 due: str = Form(""), contact: str = Form("")):
        back = _task_back(request, slug, contact)
        try:
            store.add_task(slug, text, due=due, contact=contact)
        except ValidationError as exc:
            return flashed(back, "; ".join(exc.errors.values()), "tasks")
        return flashed(back, "Task added", "tasks")

    @app.post("/companies/{slug}/tasks/{index}/done")
    def task_done(request: Request, slug: str, index: int, done: str = Form(""),
                  contact: str = Form(""), text: str = Form("")):
        back = _task_back(request, slug, contact)
        try:
            store.set_task_done(slug, index, bool(done), contact=contact, text=text)
        except ValidationError as exc:
            return flashed(back, "; ".join(exc.errors.values()), "tasks")
        return flashed(back, "Task done" if done else "Task reopened", "tasks")

    @app.post("/companies/{slug}/tasks/{index}/delete")
    def task_delete(request: Request, slug: str, index: int, contact: str = Form(""),
                    text: str = Form("")):
        back = _task_back(request, slug, contact)
        try:
            store.delete_task(slug, index, contact=contact, text=text)
        except ValidationError as exc:
            return flashed(back, "; ".join(exc.errors.values()), "tasks")
        return flashed(back, "Task deleted", "tasks")

    @app.post("/companies/{slug}/disqualify")
    def company_disqualify(request: Request, slug: str, stage: str = Form(""),
                           reason: str = Form(""), requalify_on: str = Form("")):
        """Disqualify, temp disqualify (until a date), or requalify."""
        need_company(slug)
        if stage not in (Stage.DISQUALIFIED.value, Stage.TEMP_DISQUALIFIED.value,
                         Stage.PROSPECT.value):
            return flashed(f"/companies/{slug}", f"unknown stage {stage!r}")
        try:
            store.update_company(slug, stage=stage, lost_reason=reason,
                                 requalify_on=requalify_on)
        except ValidationError as exc:
            return flashed(f"/companies/{slug}", "; ".join(exc.errors.values()))
        word = "Requalified" if stage == Stage.PROSPECT.value else stage.replace("-", " ").capitalize()
        if stage == Stage.TEMP_DISQUALIFIED.value and requalify_on:
            word += f" until {requalify_on}"
        return flashed(f"/companies/{slug}", word)

    @app.get("/companies/{slug}/merge", response_class=HTMLResponse)
    def company_merge_form(request: Request, slug: str, drop: str = ""):
        keep = need_company(slug, refresh=True)
        other = store.get(drop) if drop else None
        if drop and other is None:  # the picker also takes a company name
            try:
                other = store.get(bcc.resolve_company(store, drop))
                drop = other.slug
            except ValidationError:
                other = None
        if drop and (other is None or drop == slug):
            return flashed(f"/companies/{slug}", f"cannot merge {drop!r} into {slug}")
        if other is None:
            return flashed(f"/companies/{slug}", "Pick a company to merge in first")
        return render(request, "merge.html", {
            "title": f"Merge {other.name} into {keep.name}",
            "action": f"/companies/{slug}/merge",
            "keep_label": f"{keep.name} ({keep.slug}, kept)",
            "drop_label": f"{other.name} ({other.slug}, removed)",
            "rows": merge_rows(keep, other, COMPANY_MERGE_FIELDS,
                               defs=custom_defs("company")),
            "drop": drop,
            "back": f"/companies/{slug}",
            "note": (f"{len(other.contacts)} contacts and {len(other.interactions)} "
                     f"interactions of {other.name} move to {keep.name}; the folder "
                     f"companies/{other.slug} is deleted (history stays in git)."),
        })

    @app.post("/companies/{slug}/merge")
    async def company_merge(request: Request, slug: str):
        need_company(slug)
        form = await request.form()
        drop = form.get("drop", "")
        choices = {k[7:]: v for k, v in form.items() if k.startswith("choice_")}
        try:
            store.merge_companies(slug, drop, choices)
        except ValidationError as exc:
            return flashed(f"/companies/{slug}", "; ".join(exc.errors.values()))
        return flashed(f"/companies/{slug}", f"Merged {drop} into {slug}")

    @app.get("/companies/{slug}/contacts/{cslug}/merge", response_class=HTMLResponse)
    def contact_merge_form(request: Request, slug: str, cslug: str, drop: str = ""):
        company = need_company(slug, refresh=True)
        keep = company.contacts.get(cslug)
        if keep is None:
            raise HTTPException(status_code=404, detail=f"unknown contact {cslug!r}")
        back = f"/companies/{slug}/contacts/{cslug}"
        other = company.contacts.get(drop) if drop else None
        if drop and other is None:  # the picker also takes a contact name
            other = next((c for c in company.contacts.values()
                          if c.name.lower() == drop.strip().lower()), None)
            drop = other.slug if other else drop
        if other is None or drop == cslug:
            return flashed(back, "Pick another contact of this company to merge in")
        return render(request, "merge.html", {
            "title": f"Merge {other.name} into {keep.name}",
            "action": f"{back}/merge",
            "keep_label": f"{keep.name} ({keep.slug}, kept)",
            "drop_label": f"{other.name} ({other.slug}, removed)",
            "rows": merge_rows(keep, other, CONTACT_MERGE_FIELDS,
                               defs=custom_defs("contact")),
            "drop": drop,
            "back": back,
            "note": f"Interactions logged for {other.name} are re-pointed to {keep.name}.",
        })

    @app.post("/companies/{slug}/contacts/{cslug}/merge")
    async def contact_merge(request: Request, slug: str, cslug: str):
        need_company(slug)
        back = f"/companies/{slug}/contacts/{cslug}"
        form = await request.form()
        drop = form.get("drop", "")
        choices = {k[7:]: v for k, v in form.items() if k.startswith("choice_")}
        try:
            store.merge_contacts(slug, cslug, drop, choices)
        except ValidationError as exc:
            return flashed(back, "; ".join(exc.errors.values()))
        return flashed(back, f"Merged {drop} into {cslug}")

    @app.post("/companies/{slug}/stage")
    def company_stage(request: Request, slug: str, stage: str = Form("")):
        company = need_company(slug)
        if stage == Stage.LOST.value and company.stage != Stage.LOST.value:
            # A lost stage needs a reason: send the user to the form instead.
            return goto(f"/companies/{slug}?focus=lost_reason")
        try:
            store.update_company(slug, stage=stage)
        except ValidationError as exc:
            return flashed(f"/companies/{slug}", "; ".join(exc.errors.values()))
        return goto("/")

    # --------------------------------------------------------------- contacts

    GLOBAL_CONTACT_BLANK = {"name": "", "email": "", "title": "", "linkedin": "",
                            "company": "", "website": "", "company_linkedin": ""}

    def _global_contact_page(request: Request, values: dict, errors=None,
                             duplicates=None, status_code: int = 200, capture=None):
        return render(request, "contact_new.html", {
            "company": None, "values": values, "errors": errors or {},
            "duplicates": duplicates or [], "companies": store.all(),
            "capture": capture,
        }, status_code=status_code)

    @app.get("/contacts/new", response_class=HTMLResponse)
    def global_contact_new(request: Request):
        return _global_contact_page(request, dict(GLOBAL_CONTACT_BLANK))

    @app.post("/contacts")
    def global_contact_create(
        request: Request,
        name: str = Form(""),
        email: str = Form(""),
        title: str = Form(""),
        linkedin: str = Form(""),
        company: str = Form(""),
        website: str = Form(""),
        company_linkedin: str = Form(""),
        force: str = Form(""),
    ):
        """New contact anywhere: the company is found by name or slug, else by
        the email's domain, else created (default stage). Possible duplicates
        stop the write once; "Create anyway" (force=1) goes through.

        `company_linkedin` comes from a captured profile and only ever goes on
        a company created here, cleaned by scrape.company_page_url: it never
        rewrites a company you already have."""
        values = {"name": name, "email": email, "title": title, "linkedin": linkedin,
                  "company": company, "website": website,
                  "company_linkedin": company_linkedin}
        errors = {}
        if not name.strip():
            errors["name"] = "name is required"
        if not company.strip():
            errors["company"] = "company is required"
        if errors:
            return _global_contact_page(request, values, errors, status_code=400)
        slug, how = resolve_contact_company(store, company, email)
        new_site = website_for_new_company(website, email) if not slug else ""
        duplicates = duplicate_links(store, name, email, slug, company, new_site)
        if duplicates and not force:
            return _global_contact_page(request, values, duplicates=duplicates)
        first_name, last_name = split_name(name)
        try:
            with store.batch("") as ctx:
                if not slug:
                    slug = store.create_company(
                        company, website=new_site,
                        linkedin=scrape.company_page_url(company_linkedin)).slug
                contact = store.create_contact(slug, first_name, last_name, title=title,
                                               linkedin=linkedin, email=email)
                ctx["message"] = f"contact: {slug}/{contact.slug} created" + (
                    f" with company {slug}" if how == "new" else "")
        except ValidationError as exc:
            return _global_contact_page(request, values, exc.errors, status_code=400)
        note = {"name": "", "domain": " (company matched by email domain)",
                "new": f" with company {store.get(slug).name}"}[how]
        return flashed(f"/companies/{slug}/contacts/{contact.slug}", "Contact created" + note)

    @app.get("/companies/{slug}/contacts/new", response_class=HTMLResponse)
    def contact_new(request: Request, slug: str):
        company = need_company(slug)
        values = {"first_name": "", "last_name": "", "title": "", "linkedin": "",
                  "email": "", "phone": "", "role": "", "notes": ""}
        return render(request, "contact_new.html",
                      {"company": company, "values": values})

    @app.post("/companies/{slug}/contacts")
    async def contact_create(
        request: Request,
        slug: str,
        first_name: str = Form(""),
        last_name: str = Form(""),
        title: str = Form(""),
        linkedin: str = Form(""),
        email: str = Form(""),
        phone: str = Form(""),
        role: str = Form(""),
        notes: str = Form(""),
        force: str = Form(""),
    ):
        company = need_company(slug)
        values = {"first_name": first_name, "last_name": last_name, "title": title,
                  "linkedin": linkedin, "email": email, "phone": phone, "role": role,
                  "notes": notes}
        extra, shown, custom_errors = await custom_submitted(request, "contact")
        values.update(shown)
        duplicates = duplicate_links(store, f"{first_name} {last_name}", email, slug)
        if duplicates and not force:
            return render(request, "contact_new.html",
                          {"company": company, "values": values, "duplicates": duplicates})
        try:
            if custom_errors:
                raise ValidationError(custom_errors)
            contact = store.create_contact(slug, custom=extra,
                                           **{k: v for k, v in values.items()
                                              if not k.startswith("custom_")})
        except ValidationError as exc:
            return render(request, "contact_new.html",
                          {"company": company, "values": values,
                           "errors": exc.errors}, status_code=400)
        return flashed(f"/companies/{slug}/contacts/{contact.slug}",
                       "Contact created")

    @app.get("/companies/{slug}/contacts/{cslug}", response_class=HTMLResponse)
    def contact_page(request: Request, slug: str, cslug: str):
        company = need_company(slug, refresh=True)
        contact = company.contacts.get(cslug)
        if contact is None:
            raise HTTPException(status_code=404, detail=f"unknown contact {cslug!r}")
        return render(request, "contact.html", {
            "company": company,
            "contact": contact,
            "values": contact_values(contact),
            "interactions": [i for i in company.interactions if i.contact == cslug],
            "interaction": interaction_values(company, contact=cslug),
            **draft_context(request, company, contact),
        })

    @app.post("/companies/{slug}/contacts/{cslug}")
    async def contact_update(
        request: Request,
        slug: str,
        cslug: str,
        first_name: str = Form(""),
        last_name: str = Form(""),
        title: str = Form(""),
        linkedin: str = Form(""),
        email: str = Form(""),
        phone: str = Form(""),
        role: str = Form(""),
        notes: str = Form(""),
        version: str = Form(""),
    ):
        company = need_company(slug)
        contact = company.contacts.get(cslug)
        if contact is None:
            raise HTTPException(status_code=404, detail=f"unknown contact {cslug!r}")
        values = {"first_name": first_name, "last_name": last_name, "title": title,
                  "linkedin": linkedin, "email": email, "phone": phone, "role": role,
                  "notes": notes}
        extra, shown, custom_errors = await custom_submitted(request, "contact")
        if version and version != record_version(root, slug, cslug):
            current = need_company(slug, refresh=True)
            person = current.contacts.get(cslug)
            if person is None:
                raise HTTPException(status_code=404, detail=f"unknown contact {cslug!r}")
            return render(request, "contact.html", {
                "company": current,
                "contact": person,
                "values": {**values, **shown},
                "flash": stale_form_text("contact",
                                         changed_fields(values, contact_values(person))),
                "interactions": [i for i in current.interactions if i.contact == cslug],
                "interaction": interaction_values(current, contact=cslug),
                **draft_context(request, current, person),
            }, status_code=409)
        try:
            if custom_errors:
                raise ValidationError(custom_errors)
            store.update_contact(slug, cslug, custom=extra, **values)
        except ValidationError as exc:
            values.update(shown)
            return render(request, "contact.html", {
                "company": company,
                "contact": contact,
                "values": values,
                "errors": exc.errors,
                "interactions": [i for i in company.interactions
                                 if i.contact == cslug],
                "interaction": interaction_values(company, contact=cslug),
                **draft_context(request, company, contact),
            }, status_code=400)
        return flashed(f"/companies/{slug}/contacts/{cslug}", "Saved")

    @app.post("/companies/{slug}/contacts/{cslug}/delete")
    def contact_delete(request: Request, slug: str, cslug: str):
        """Delete one contact (the browser asked for confirmation); its
        interactions stay on the company without a contact."""
        company = need_company(slug)
        contact = company.contacts.get(cslug)
        if contact is None:
            raise HTTPException(status_code=404, detail=f"unknown contact {cslug!r}")
        kept = sum(1 for i in company.interactions if i.contact == cslug)
        store.delete_contact(slug, cslug)
        note = f"; {kept} interaction(s) kept on {company.name}" if kept else ""
        return flashed(f"/companies/{slug}", f"Contact {contact.name} deleted{note}")

    # ----------------------------------------------------------- interactions

    @app.get("/companies/{slug}/interactions/new", response_class=HTMLResponse)
    def interaction_new(request: Request, slug: str, contact: str = "",
                        channel: str = "", body: str = ""):
        company = need_company(slug, refresh=True)
        return render(request, "interaction_new.html", {
            "company": company,
            "interaction": interaction_values(company, contact=contact or None,
                                              channel=channel, body=body),
        })

    @app.post("/companies/{slug}/interactions")
    async def interaction_create(
        request: Request,
        slug: str,
        channel: str = Form(""),
        direction: str = Form("out"),
        contact: str = Form(""),
        date: str = Form(""),
        subject: str = Form(""),
        outcome: str = Form(""),
        body: str = Form(""),
    ):
        company = need_company(slug)
        values = {"channel": channel, "direction": direction, "contact": contact,
                  "date": date, "subject": subject, "outcome": outcome,
                  "body": body}
        extra, shown, custom_errors = await custom_submitted(request, "interaction")
        try:
            if custom_errors:
                raise ValidationError(custom_errors)
            created = store.create_interaction(slug, custom=extra, **values)
        except ValidationError as exc:
            values.update(shown)
            return render(request, "interaction_new.html", {
                "company": company,
                "interaction": values,
                "errors": exc.errors,
            }, status_code=400)
        return flashed(f"/companies/{slug}", "Interaction logged",
                       anchor=f"i-{created.id}")

    @app.get("/companies/{slug}/interactions/{id}/edit", response_class=HTMLResponse)
    def interaction_edit(request: Request, slug: str, id: str):
        company = need_company(slug, refresh=True)
        it = next((i for i in company.interactions if i.id == id), None)
        if it is None:
            raise HTTPException(status_code=404, detail=f"unknown interaction {id!r}")
        values = {
            "channel": it.channel, "direction": it.direction, "contact": it.contact,
            "date": fmt_datetime(it.date), "subject": it.subject,
            "outcome": it.outcome, "body": it.body,
        }
        return render(request, "interaction_edit.html",
                      {"company": company, "id": id, "interaction": values})

    @app.post("/companies/{slug}/interactions/{id}/edit")
    async def interaction_save(
        request: Request,
        slug: str,
        id: str,
        channel: str = Form(""),
        direction: str = Form("out"),
        contact: str = Form(""),
        date: str = Form(""),
        subject: str = Form(""),
        outcome: str = Form(""),
        body: str = Form(""),
    ):
        company = need_company(slug)
        if not any(i.id == id for i in company.interactions):
            raise HTTPException(status_code=404, detail=f"unknown interaction {id!r}")
        values = {"channel": channel, "direction": direction, "contact": contact,
                  "date": date, "subject": subject, "outcome": outcome,
                  "body": body}
        extra, shown, custom_errors = await custom_submitted(request, "interaction")
        try:
            if custom_errors:
                raise ValidationError(custom_errors)
            saved = store.update_interaction(slug, id, custom=extra, **values)
        except ValidationError as exc:
            return render(request, "interaction_edit.html", {
                "company": company, "id": id, "interaction": values,
                "errors": exc.errors,
            }, status_code=400)
        return flashed(f"/companies/{slug}", "Interaction updated",
                       anchor=f"i-{saved.id}")

    @app.post("/companies/{slug}/interactions/{id}/delete")
    def interaction_delete(request: Request, slug: str, id: str):
        """Delete one interaction (the browser asked for confirmation). Back to
        the page it was on, unless that page was the interaction itself."""
        company = need_company(slug)
        if not any(i.id == id for i in company.interactions):
            raise HTTPException(status_code=404, detail=f"unknown interaction {id!r}")
        store.delete_interaction(slug, id)
        back = urlparse(request.headers.get("referer", "")).path
        if not back or back.startswith(f"/companies/{slug}/interactions/"):
            back = f"/companies/{slug}"
        return flashed(back, "Interaction deleted")

    # --------------------------------------------------- settings (+ inbox)

    def inbox_context(**extra) -> dict:
        ctx = {
            "items": inbox.items(),
            "last_run": inbox.last_run(),
            "calendar_last_run": inbox.last_run(calendar_sync.LAST_RUN_FILE),
            "bcc_address": app.state.bcc_settings.address,
            "companies": sorted(store.all(), key=lambda c: c.name.lower()),
        }
        ctx.update(extra)
        return ctx

    def schedule_status() -> dict:
        """The daily job's status; never raises (the page must always render)."""
        try:
            ctx = schedule.Context(data_dir=root, home=app.state.schedule_home or Path.home(),
                                   platform=app.state.setup_platform,
                                   runner=app.state.setup_runner)
            state = schedule.status(ctx)
        except Exception as exc:  # launchctl/systemctl missing, unreadable plist, ...
            logger.warning("schedule status failed: %s", exc)
            state = {"installed": False, "lines": [f"could not check: {exc}"]}
        state["install_command"] = f"hermitcrm --data {root} schedule install --serve"
        return state

    def local_backup_status() -> dict:
        """`hermitcrm backup status` for the Backup section; never raises."""
        from . import backup

        try:
            return backup.status(root, config, home=app.state.schedule_home)
        except Exception as exc:
            logger.warning("backup status failed: %s", exc)
            return {"level": "warn", "summary": f"could not check: {exc}", "lines": []}

    def access_facts() -> dict:
        """The two front doors the Settings page cannot switch on for you.

        A phone needs the app bound to something other than loopback, and an MCP
        client needs a command to spawn; both are terminal-side. The page can
        only tell you what to type, but Settings is where you look for it.
        """
        from .cli import reachable_address  # cli imports web, so import it late

        host = str(config.get("host") or DEFAULT_CONFIG["host"])
        port = str(config.get("port") or DEFAULT_CONFIG["port"])
        binary = Path(sys.executable).with_name("hermitcrm")
        command = str(binary) if binary.exists() else "hermitcrm"
        return {
            "host": host,
            "port": port,
            "on_network": host not in ("127.0.0.1", "localhost", "::1"),
            "lan_url": "http://%s:%s" % (reachable_address("0.0.0.0"), port),
            "serve_command": "%s --data %s serve --host 0.0.0.0" % (command, root),
            "mcp_command": "%s --data %s mcp" % (command, root),
            "mcp_config": json.dumps(
                {"mcpServers": {"hermitcrm": {"command": command,
                                              "args": ["--data", str(root), "mcp"]}}},
                indent=2),
        }

    def settings_context(**extra) -> dict:
        state = current_setup_state()
        owner = str(config.get("owner_email") or "")
        bcc_address = str(config.get("bcc_address") or "")
        enricher = app.state.enricher
        try:
            data_format = migrations.current_format(root)
        except Exception:
            data_format = None
        ctx = {
            "state": state,
            "you": {"name": str(config.get("owner_name") or ""),
                    "addresses": ", ".join(config.get("my_addresses") or [])
                    or owner},
            "bcc_form": {"address": bcc_address or setup_steps.suggest_bcc_address(owner),
                         "imap_host": (str(config.get("bcc_imap_host") or "")
                                       if bcc_address else "")
                         or setup_steps.imap_host_for(bcc_address or owner)},
            "gmail_filter": (setup_steps.gmail_filter_text(bcc_address)
                             if bcc_address else ""),
            "is_mac": app.state.setup_platform == "darwin",
            "remote_url": setup_steps.remote_url(root, str(config.get("remote") or "origin"),
                                                 app.state.setup_runner),
            "remote_warning": "",
            "form_errors": {},
            "enrich_form": {"provider": str(config.get("enrich_provider") or "auto"),
                            "account": str(config.get("enrich_account") or "subscription"),
                            "command": str(config.get("enrich_command") or ""),
                            "model": str(config.get("enrich_model") or ""),
                            "model_strong": str(config.get("enrich_model_strong") or ""),
                            "tier": str(config.get("ai_tier") or "medium"),
                            "timeout": str(config.get("enrich_timeout") or 180)},
            "tier_models": {t: enricher.model_for(t) for t in setup_steps.AI_TIERS},
            "themes": setup_steps.THEMES,
            "theme_file": usertheme.status(root),
            "theme_example": usertheme.EXAMPLE,
            "fields_form": {"toml": (root / custom.FILENAME).read_text(encoding="utf-8")
                            if (root / custom.FILENAME).exists() else ""},
            "custom_field_defs": app.state.custom_fields,
            "messaging_form": {
                "size_field": str(config.get("messaging_size_field") or ""),
                "team_field": str(config.get("messaging_team_field") or "")},
            "company_field_keys": [d.key for d in app.state.custom_fields
                                   if d.applies_to == "company"],
            "field_types": custom.TYPES,
            "field_scopes": custom.SCOPES,
            "field_views": custom.VIEWS_FOR_SCOPE,
            "mail_providers": bcc.MAIL_PROVIDERS,
            "enrich_providers": setup_steps.ENRICH_PROVIDERS,
            "enrich_accounts": setup_steps.ENRICH_ACCOUNTS,
            "enrich_status": {"available": enricher.available,
                              "provider": enricher.provider_name,
                              "reason": "" if enricher.available
                              else enricher.unavailable_reason()},
            "outcomes_form": {"outcomes": "\n".join(
                                  setup_steps.parse_outcomes(config.get("outcomes") or [])),
                              "message_window_days": str(config.get("message_window_days")
                                                         or 14),
                              "silent_days": str(config.get("silent_days") or 14)},
            "schedule": schedule_status(),
            "local_backup": local_backup_status(),
            "access": access_facts(),
            "about": {"version": __version__, "data_dir": str(root),
                      "data_format": data_format, "latest_format": migrations.LATEST,
                      "update_check": bool(config.get("update_check", True)),
                      "update_note": updates.note(app.state.update_notice.result)},
        }
        if ctx["remote_url"]:
            ctx["remote_warning"] = setup_steps.private_warning(ctx["remote_url"])
        ctx.update(inbox_context())
        ctx.update(extra)
        return ctx

    def settings_page(request: Request, status_code: int = 200, **extra):
        return render(request, "settings.html", settings_context(**extra),
                      status_code=status_code)

    def check_csrf(token: str) -> None:
        if not hmac.compare_digest(str(token or ""), app.state.csrf_token):
            raise HTTPException(status_code=403, detail="invalid or missing CSRF token; "
                                "reload the settings page and try again")

    def setup_done(result, anchor: str) -> RedirectResponse:
        refresh_config()
        return flashed("/settings", result.text() or "Saved", anchor=anchor)

    def setup_invalid(request: Request, result, step: str, **extra):
        return settings_page(request, status_code=400,
                             form_errors={step: result.errors}, **extra)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_view(request: Request):
        app.state.setup_redirected = True
        return settings_page(request)

    @app.get("/setup")
    def setup_redirect(request: Request):
        """The old Setup page is the Settings page now."""
        return RedirectResponse("/settings", status_code=301)

    @app.get("/inbox")
    def inbox_redirect(request: Request):
        """The old Inbox page is the review queue on the Settings page now."""
        return RedirectResponse("/settings#inbox", status_code=301)

    # The POST paths keep their /setup/... names and also answer under /settings/...

    @app.post("/settings/you")
    @app.post("/setup/you")
    def setup_you(request: Request, csrf_token: str = Form(""), name: str = Form(""),
                  addresses: str = Form("")):
        check_csrf(csrf_token)
        result = setup_steps.save_you(root, name, addresses)
        if not result.ok:
            return setup_invalid(request, result, "you",
                                 you={"name": name, "addresses": addresses})
        return setup_done(result, "you")

    @app.post("/settings/bcc")
    @app.post("/setup/bcc")
    def setup_bcc(request: Request, csrf_token: str = Form(""), address: str = Form(""),
                  imap_host: str = Form(""), password: str = Form(""),
                  keychain: str = Form("")):
        check_csrf(csrf_token)
        result = setup_steps.save_bcc(root, address, imap_host, password,
                                      use_keychain=bool(keychain),
                                      runner=app.state.setup_runner,
                                      platform=app.state.setup_platform)
        if not result.ok:
            return setup_invalid(request, result, "bcc",
                                 bcc_form={"address": address, "imap_host": imap_host})
        return setup_done(result, "bcc")

    @app.post("/settings/bcc/test")
    @app.post("/setup/bcc/test")
    def setup_bcc_test(request: Request, csrf_token: str = Form("")):
        check_csrf(csrf_token)
        result = setup_steps.test_bcc(root, config, open_mailbox=app.state.open_mailbox,
                                      store=store)
        return flashed("/settings", result.text(), anchor="bcc")

    @app.post("/settings/backup")
    @app.post("/setup/backup")
    def setup_backup(request: Request, csrf_token: str = Form(""), url: str = Form("")):
        check_csrf(csrf_token)
        result = setup_steps.save_backup(root, url, config, runner=app.state.setup_runner,
                                         push=app.state.setup_push)
        if result.errors.get("url"):
            return setup_invalid(request, result, "backup")
        return setup_done(result, "backup")

    @app.post("/settings/calendar")
    @app.post("/setup/calendar")
    def setup_calendar(request: Request, csrf_token: str = Form(""), url: str = Form("")):
        check_csrf(csrf_token)
        result = setup_steps.save_calendar(root, url, config,
                                           fetch=app.state.fetch_calendar, store=store)
        if result.errors.get("url"):
            return setup_invalid(request, result, "calendar")
        return setup_done(result, "calendar")

    @app.post("/settings/fields")
    async def settings_fields(request: Request, csrf_token: str = Form(""),
                              fields_toml: str = Form("")):
        check_csrf(csrf_token)
        result = setup_steps.save_fields(root, fields_toml)
        if not result.ok:
            return setup_invalid(request, result, "fields",
                                 fields_form={"toml": fields_toml})
        app.state.custom_fields = load_custom_fields()
        return flashed("/settings", result.text(), anchor="fields")

    @app.post("/settings/fields/add")
    async def settings_fields_add(request: Request, csrf_token: str = Form(""),
                                  key: str = Form(""), label: str = Form(""),
                                  type: str = Form("text"),
                                  applies_to: str = Form("company"),
                                  options: str = Form(""), help: str = Form(""),
                                  messaging: str = Form("on")):
        check_csrf(csrf_token)
        form = await request.form()
        result = setup_steps.add_field(root, key, label, type, applies_to, options,
                                       show_in=form.getlist("show_in") or ["detail"],
                                       help=help, messaging=bool(messaging))
        if not result.ok:
            return setup_invalid(request, result, "fields")
        app.state.custom_fields = load_custom_fields()
        return flashed("/settings", result.text(), anchor="fields")

    @app.post("/settings/messaging")
    def settings_messaging(request: Request, csrf_token: str = Form(""),
                           size_field: str = Form(""), team_field: str = Form("")):
        check_csrf(csrf_token)
        result = setup_steps.save_messaging_fields(root, size_field, team_field)
        if not result.ok:
            return setup_invalid(request, result, "messaging")
        refresh_config()
        return flashed("/settings", result.text(), anchor="messaging")

    @app.post("/settings/enrichment")
    def settings_enrichment(request: Request, csrf_token: str = Form(""),
                            provider: str = Form("auto"), command: str = Form(""),
                            model: str = Form(""), timeout: str = Form("180"),
                            model_strong: str = Form(""), tier: str = Form("medium"),
                            account: str = Form("subscription")):
        check_csrf(csrf_token)
        result = setup_steps.save_enrichment(root, provider, command, model, timeout,
                                             model_strong=model_strong, tier=tier,
                                             account=account)
        if not result.ok:
            return setup_invalid(request, result, "enrichment",
                                 enrich_form={"provider": provider, "command": command,
                                              "model": model, "timeout": timeout,
                                              "model_strong": model_strong, "tier": tier,
                                              "account": account})
        refresh_config()
        enricher = app.state.enricher
        note = (f" In use: {enricher.provider_name}." if enricher.available
                else f" Unavailable: {enricher.unavailable_reason()}")
        return flashed("/settings", result.text() + note, anchor="enrichment")

    @app.post("/settings/appearance")
    def settings_appearance(request: Request, csrf_token: str = Form(""),
                            theme: str = Form("")):
        check_csrf(csrf_token)
        result = setup_steps.save_theme(root, theme)
        if not result.ok:
            return setup_invalid(request, result, "appearance")
        return setup_done(result, "appearance")

    # ------------------------------------------------------------ ask hermit

    async def page_html(page: str) -> str:
        """Render a local GET page in-process, exactly as the browser saw it."""
        path, _, query = page.partition("?")
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
                 "query_string": query.encode(), "root_path": "",
                 "headers": [(b"host", b"127.0.0.1")], "client": ("127.0.0.1", 0),
                 "server": ("127.0.0.1", 80)}
        chunks: list[bytes] = []
        status = {"code": 500}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        await app(scope, receive, send)
        if status["code"] >= 400:
            return ""
        return b"".join(chunks).decode("utf-8", "replace")

    def ask_page_view(request: Request, page: str, status_code: int = 200, **extra):
        enricher = app.state.enricher
        ctx = {"ask_page": page, "question": "", "answer": None, "error": "", "tried": "",
               "ai": {"available": enricher.available, "provider": enricher.provider_name,
                      "reason": "" if enricher.available else enricher.unavailable_reason(),
                      "medium": enricher.model_for("medium"),
                      "strong": enricher.model_for("strong"), "tier": enricher.tier}}
        ctx.update(extra)
        return render(request, "ask.html", ctx, status_code=status_code)

    @app.get("/ask", response_class=HTMLResponse)
    def ask_form(request: Request, page: str = "/"):
        return ask_page_view(request, safe_page(page))

    @app.post("/ask", response_class=HTMLResponse)
    async def ask_post(request: Request, csrf_token: str = Form(""), question: str = Form(""),
                       page: str = Form("/"), scope: str = Form("auto"),
                       tier: str = Form("")):
        check_csrf(csrf_token)
        page = safe_page(page)
        enricher = app.state.enricher.with_tier(tier) if tier else app.state.enricher
        enricher = enricher.with_tier(enricher.tier)  # a copy: the timeout changes below
        html = await page_html(page)
        try:
            answer = await run_in_threadpool(
                asking.ask, enricher, question, page, html, root,
                "crm" if scope == "crm" else "auto",
                float(config.get("ask_timeout") or 300))
        except EnrichError as exc:
            return ask_page_view(request, page, question=question, error=str(exc),
                                 tried=enricher.model,
                                 status_code=400 if not question.strip() else 502)
        return ask_page_view(request, page, question=question, answer=answer)

    @app.post("/settings/outcomes")
    def settings_outcomes(request: Request, csrf_token: str = Form(""),
                          outcomes: str = Form(""), message_window_days: str = Form("14"),
                          silent_days: str = Form("14")):
        check_csrf(csrf_token)
        result = setup_steps.save_outcomes(root, outcomes, message_window_days, silent_days)
        if not result.ok:
            return setup_invalid(request, result, "outcomes",
                                 outcomes_form={"outcomes": outcomes,
                                                "message_window_days": message_window_days,
                                                "silent_days": silent_days})
        return setup_done(result, "outcomes")

    # Review queue (the former /inbox): BCC and calendar items waiting for a company.

    @app.post("/bcc/import")
    def bcc_import(request: Request):
        try:
            result = bcc.run_bcc(store, inbox, app.state.bcc_settings, True,
                                 app.state.open_mailbox)
        except bcc.BccError as exc:
            logger.warning("BCC import failed: %s", exc)
            return flashed("/settings", f"BCC import failed: {exc}", anchor="inbox")
        except Exception as exc:
            logger.exception("BCC import crashed")
            return flashed("/settings", f"BCC import failed: {type(exc).__name__}: {exc}",
                           anchor="inbox")
        return flashed("/settings", "BCC import: " + result.summary(), anchor="inbox")

    @app.post("/inbox/{item_id}/assign")
    def inbox_assign(request: Request, item_id: str, company: str = Form(""),
                     first_name: str = Form(""), last_name: str = Form("")):
        if inbox.get(item_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown inbox item {item_id!r}")
        try:
            slug, it = bcc.assign(store, inbox, item_id, company, first_name, last_name)
        except ValidationError as exc:
            return settings_page(request, status_code=400, errors=exc.errors)
        return flashed("/settings", f"Logged at {slug}/{it.contact}", anchor="inbox")

    @app.post("/inbox/{item_id}/discard")
    def inbox_discard(request: Request, item_id: str):
        try:
            item = bcc.discard(store, inbox, item_id)
        except ValidationError:
            raise HTTPException(status_code=404, detail=f"unknown inbox item {item_id!r}")
        return flashed("/settings", f"Discarded {item.address}", anchor="inbox")

    # ------------------------------------------------------------------- help

    def help_page(request: Request, topic: str, **extra):
        text = helpdocs.read(topic)
        if text is None:
            raise HTTPException(status_code=404, detail=f"unknown help topic {topic!r}")
        ctx = {
            "topic": topic,
            "title": helpdocs.title_of(text) or topic,
            "body": helpdocs.render(text),
            "topics": helpdocs.titles(),
        }
        # Feedback is the one topic that is also a form, so it renders a template that
        # extends help.html: same sidebar, same prose, a form above it.
        if topic == "feedback":
            ctx.update(feedback_context(**extra))
            return render(request, "feedback.html", ctx,
                          status_code=422 if ctx.get("errors") else 200)
        return render(request, "help.html", ctx)

    def feedback_facts() -> list[str]:
        """Numbers and flags only; see hermitcrm/feedback.py for why."""
        companies = store.all()
        try:
            data_format = migrations.current_format(root)
        except Exception:
            data_format = None
        state = current_setup_state()
        return feedback.diagnostics(
            version=__version__,
            python=platform_info.python_version(),
            platform=f"{platform_info.system()} {platform_info.release()} "
                     f"({platform_info.machine()})",
            counts={"companies": len(companies),
                    "contacts": sum(len(c.contacts) for c in companies),
                    "interactions": sum(len(c.interactions) for c in companies)},
            data_format=data_format,
            features={
                "BCC import": "on" if state.get("bcc") else "off",
                "Calendar import": "on" if state.get("calendar") else "off",
                "Git remote": "yes" if state.get("backup") else "no",
                "Enrichment": (app.state.enricher.provider_name
                               if app.state.enricher.available else "unavailable"),
                "Daily schedule": ("installed" if schedule_status().get("installed")
                                   else "not installed"),
            })

    def feedback_context(saved=None, errors=None, form=None) -> dict:
        return {
            "kinds": feedback.KINDS,
            "facts": feedback_facts(),
            "errors": errors or {},
            "saved": saved,
            "form": form or {"kind": feedback.KIND_VALUES[0], "summary": "", "detail": "",
                             "reporter": " ".join(x for x in
                                                  (str(config.get("owner_name") or ""),
                                                   f"<{config.get('owner_email')}>"
                                                   if config.get("owner_email") else "")
                                                  if x)},
        }

    @app.get("/help", response_class=HTMLResponse)
    def help_index(request: Request):
        return help_page(request, "index")

    @app.get("/help/{topic}", response_class=HTMLResponse)
    def help_topic(request: Request, topic: str):
        return help_page(request, topic)

    @app.post("/help/feedback", response_class=HTMLResponse)
    def help_feedback(request: Request, csrf_token: str = Form(""), kind: str = Form(""),
                      summary: str = Form(""), detail: str = Form(""),
                      reporter: str = Form("")):
        check_csrf(csrf_token)
        form = {"kind": kind, "summary": summary, "detail": detail, "reporter": reporter}
        errors = {}
        if not summary.strip():
            errors["summary"] = "Give it a one-line summary."
        if not detail.strip():
            errors["detail"] = "Say what happened; an empty report cannot be acted on."
        if errors:
            return help_page(request, "feedback", errors=errors, form=form)

        text = feedback.report(kind, summary, detail, reporter, facts=feedback_facts(),
                               now=store.now(), version=__version__)
        name = feedback.filename(summary, now=store.now())
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        try:
            gitops.commit(f"feedback: {' '.join(summary.split())}", [name])
            gitops.push_async()
        except Exception:  # a report is still a report if git is unhappy
            logger.exception("could not commit feedback %r", name)
        return help_page(request, "feedback", saved={
            "path": name, "text": text,
            "mailto": feedback.mailto(str(config.get("feedback_email") or ""),
                                      " ".join(summary.split()), text)})

    # ------------------------------------------------------------ housekeeping

    @app.post("/reload")
    def reload_index(request: Request):
        """Re-read the data folder: the records and the fields that describe them."""
        store.load()
        app.state.custom_fields = load_custom_fields()
        return goto(request.headers.get("referer") or "/")

    @app.get("/health")
    def health():
        status = gitops.status()
        return JSONResponse({
            "companies": len(store.companies),
            "contacts": sum(len(c.contacts) for c in store.companies.values()),
            "interactions": sum(len(c.interactions)
                                for c in store.companies.values()),
            "last_commit": status.get("last_commit"),
            "last_push": status.get("last_push"),
            "problems": [{"path": p.path, "message": p.message}
                         for p in store.problems],
        })

    return app
