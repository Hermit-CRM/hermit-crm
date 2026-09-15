"""File store: reads and writes companies/<slug>/ and keeps an in-memory index.

Nothing here touches git or PIPELINE.md; ``on_write`` is the hook the caller
uses to commit with the message this module produces.
"""

from __future__ import annotations

import shutil
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import frontmatter
import yaml

from .models import (
    Channel,
    Company,
    Contact,
    Country,
    DEFAULT_OUTCOMES,
    Direction,
    Interaction,
    InteractionSource,
    REASON_STAGES,
    Role,
    Source,
    Stage,
    StageChange,
    TaskStatus,
    ValidationError,
    company_from_dict,
    company_to_frontmatter,
    contact_from_dict,
    contact_to_frontmatter,
    dump_frontmatter,
    interaction_from_dict,
    interaction_to_frontmatter,
    normalise_country,
    normalise_email,
    normalise_website,
    parse_date,
    parse_datetime,
    parse_tags,
    slugify,
    unique_slug,
)

DEFAULT_CONFIG = {
    # You: the name signs outreach drafts ({owner_first_name}).
    "owner_name": "",
    "owner_email": "",
    "port": 8765,
    "silent_days": 14,
    "push_enabled": True,
    "remote": "origin",
    # Enrichment shells out to an AI CLI; see owncrm/enrich.py. "auto" picks the
    # first of claude, codex, gemini, grok on PATH. Empty command/model mean
    # the provider's own binary and default model.
    "enrich_provider": "auto",
    "enrich_command": "",
    "enrich_model": "",
    "enrich_timeout": 180,
    # A message with no reply and no explicit outcome counts as the last
    # outcome after this many days (Messages tab).
    "message_window_days": 14,
    # Outcome choices for an interaction (Messages tab and the interaction form).
    # The first is what a detected reply counts as, the last what silence past
    # message_window_days counts as; empty outcome means "not yet known".
    "outcomes": list(DEFAULT_OUTCOMES),
    # Seconds to wait when the free "Fetch from URL" enrichment reads a page.
    "fetch_timeout": 10,
    # BCC import (owncrm/bcc.py): mails BCC'd or forwarded to bcc_address.
    "bcc_address": "",
    "bcc_imap_host": "imap.gmail.com",
    "bcc_keychain_service": "crm-bcc",
    "bcc_lookback_days": 30,
    # Mail from these addresses is yours (outbound); recipients at these
    # domains (colleagues) are never logged.
    "my_addresses": [],
    "bcc_ignore_domains": [],
    # Calendar import (owncrm/calendar_sync.py). The ICS URL itself is a secret
    # (owncrm/secrets.py), never this file.
    "calendar_keychain_service": "crm-calendar",
    "calendar_keychain_account": "ics",
    "calendar_lookback_days": 30,
    "calendar_ignore_titles": [],
    "calendar_min_attendees": 2,
    # Check PyPI for a newer version at most once a day (owncrm/updates.py).
    "update_check": True,
}


@dataclass
class Problem:
    path: str
    message: str


def load_config(root: Path) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = Path(root) / "config.toml"
    if path.exists():
        with open(path, "rb") as fh:
            cfg.update(tomllib.load(fh))
    return cfg


# ------------------------------------------------------------------ raw file io


def split_file(text: str) -> tuple[dict, str]:
    """Split raw file text into (front matter dict, body preserved byte for byte)."""
    nl = text.find("\n")
    if nl == -1 or text[:nl].rstrip("\r") != "---":
        return {}, text
    rest = text[nl + 1:]
    meta_text, body, start = rest, "", 0
    while True:
        eol = rest.find("\n", start)
        line = (rest[start:eol] if eol != -1 else rest[start:]).rstrip("\r")
        if line == "---":
            meta_text = rest[:start]
            body = rest[eol + 1:] if eol != -1 else ""
            break
        if eol == -1:
            break
        start = eol + 1
    # Metadata goes through python-frontmatter; the body is taken from the raw
    # text above because frontmatter strips trailing whitespace from content.
    try:
        meta = frontmatter.loads(f"---\n{meta_text}---\n").metadata if meta_text.strip() else {}
    except yaml.YAMLError as exc:
        raise ValidationError({"file": f"invalid YAML front matter: {exc}"})
    return meta or {}, body


def build_file(meta: dict, body: str) -> str:
    return "---\n" + dump_frontmatter(meta) + "---\n" + body


def normalise_body(body: str | None) -> str:
    """For bodies coming from forms: LF line endings, exactly one trailing \\n."""
    body = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    body = body.rstrip("\n")
    return body + "\n" if body else ""


# ----------------------------------------------------------------------- store


COMPANY_COPY_FIELDS = (
    "name", "slug", "website", "linkedin", "country", "source", "stage",
    "stage_changed", "lost_reason", "requalify_on", "value_eur_month", "my_score",
    "fit_score", "fte_estimate", "ae_count", "product_oneliner", "next_step",
    "next_step_due", "next_step_status", "tags", "stage_history", "created", "updated",
    "notes",
)
# Fields a merge lets you choose per side (everything but slug, timestamps and
# the stage history, which is always combined).
COMPANY_MERGE_FIELDS = tuple(
    f for f in COMPANY_COPY_FIELDS
    if f not in ("slug", "created", "updated", "stage_history"))
CONTACT_COPY_FIELDS = (
    "first_name", "last_name", "slug", "title", "linkedin", "email", "phone",
    "role", "created", "updated", "notes",
)
CONTACT_MERGE_FIELDS = tuple(
    f for f in CONTACT_COPY_FIELDS if f not in ("slug", "created", "updated"))
INTERACTION_COPY_FIELDS = (
    "id", "date", "channel", "direction", "contact", "subject", "outcome",
    "source", "message_id", "body",
)


class Store:
    def __init__(
        self,
        root: Path,
        silent_days: int = 14,
        on_write: Callable[[str], None] | None = None,
        clock: Callable[[], datetime] | None = None,
        outcomes: list[str] | None = None,
    ):
        self.root = Path(root)
        self.companies_dir = self.root / "companies"
        self.companies: dict[str, Company] = {}
        self.problems: list[Problem] = []
        self.silent_days = silent_days
        # Allowed interaction outcomes (config `outcomes`); "" is always allowed.
        self.outcomes = [str(o) for o in (outcomes or DEFAULT_OUTCOMES)]
        self.on_write = on_write
        self._batch: list[str] | None = None
        self.clock = clock

    # --- clock

    def now(self) -> datetime:
        dt = self.clock() if self.clock else datetime.now()
        return dt.replace(second=0, microsecond=0)

    def today(self) -> date:
        return self.now().date()

    # --- helpers

    def _rel(self, path: Path) -> str:
        try:
            return str(Path(path).relative_to(self.root))
        except ValueError:
            return str(path)

    def _problem(self, path: Path, message: str) -> None:
        self.problems.append(Problem(path=self._rel(path), message=message))

    def company_dir(self, slug: str) -> Path:
        return self.companies_dir / slug

    def _notify(self, message: str) -> None:
        if self._batch is not None:
            self._batch.append(message)
            return
        if self.on_write:
            self.on_write(message)

    @contextmanager
    def batch(self, message: str):
        """Group several writes into one on_write call (one commit)."""
        ctx = {"message": message}  # callers may set ctx["message"] once counts are known
        if self._batch is not None:
            yield ctx
            return
        self._batch = []
        try:
            yield ctx
        finally:
            written = self._batch
            self._batch = None
        if written and self.on_write:
            self.on_write(ctx["message"])

    def notify(self, message: str) -> None:
        """Commit a write made outside companies/ (the BCC inbox)."""
        self._notify(message)

    # --- loading

    def load(self) -> list[Problem]:
        self.companies = {}
        self.problems = []
        if not self.companies_dir.exists():
            return self.problems
        for folder in sorted(p for p in self.companies_dir.iterdir() if p.is_dir()):
            company = self._parse_company_folder(folder)
            if company:
                self.companies[company.slug] = company
        return self.problems

    def _parse_company_folder(self, folder: Path) -> Company | None:
        slug = folder.name
        company_file = folder / "company.md"
        if not company_file.exists():
            self._problem(company_file, "company.md is missing")
            return None
        try:
            meta, body = split_file(company_file.read_text(encoding="utf-8"))
            company = company_from_dict(meta, body, slug)
        except ValidationError as exc:
            self._problem(company_file, exc.args[0])
            return None
        if meta.get("slug") and str(meta["slug"]) != slug:
            self._problem(
                company_file,
                f"slug {meta['slug']!r} does not match folder {slug!r}; folder wins",
            )

        contacts_dir = folder / "contacts"
        if contacts_dir.is_dir():
            for path in sorted(contacts_dir.glob("*.md")):
                try:
                    cmeta, cbody = split_file(path.read_text(encoding="utf-8"))
                    contact = contact_from_dict(cmeta, cbody, path.stem)
                except ValidationError as exc:
                    self._problem(path, exc.args[0])
                    continue
                if cmeta.get("slug") and str(cmeta["slug"]) != path.stem:
                    self._problem(
                        path,
                        f"slug {cmeta['slug']!r} does not match file {path.stem!r}; "
                        "file name wins",
                    )
                company.contacts[contact.slug] = contact

        interactions_dir = folder / "interactions"
        if interactions_dir.is_dir():
            for path in sorted(interactions_dir.glob("*.md")):
                try:
                    imeta, ibody = split_file(path.read_text(encoding="utf-8"))
                    interaction = interaction_from_dict(imeta, ibody, path.stem)
                except ValidationError as exc:
                    self._problem(path, exc.args[0])
                    continue
                if interaction.contact and interaction.contact not in company.contacts:
                    self._problem(
                        path,
                        f"contact {interaction.contact!r} is not a contact of {slug!r}",
                    )
                company.interactions.append(interaction)
        company.interactions.sort(key=lambda i: (i.date or datetime.min, i.id),
                                  reverse=True)
        return company

    def reload_company(self, slug: str) -> Company | None:
        prefix = self._rel(self.company_dir(slug))
        self.problems = [
            p for p in self.problems
            if not (p.path == prefix or p.path.startswith(prefix + "/"))
        ]
        folder = self.company_dir(slug)
        if not folder.is_dir():
            self.companies.pop(slug, None)
            return None
        company = self._parse_company_folder(folder)
        if company is None:
            self.companies.pop(slug, None)
            return None
        self.companies[slug] = company
        return company

    # --- reading

    def get(self, slug: str, refresh: bool = False) -> Company | None:
        if refresh:
            return self.reload_company(slug)
        return self.companies.get(slug)

    def all(self) -> list[Company]:
        return sorted(self.companies.values(), key=lambda c: c.name.lower())

    def search(self, q: str) -> list[Company]:
        q = (q or "").strip().lower()
        if not q:
            return self.all()
        hits = []
        for c in self.companies.values():
            haystack = [c.name] + list(c.tags)
            for contact in c.contacts.values():
                haystack.append(contact.name)
                haystack.append(contact.email)
            if any(q in (h or "").lower() for h in haystack):
                hits.append(c)
        return sorted(hits, key=lambda c: c.name.lower())

    # --- writing (low level, deterministic)

    def write_company(self, c: Company) -> Path:
        path = self.company_dir(c.slug) / "company.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_file(company_to_frontmatter(c), c.notes),
                        encoding="utf-8")
        return path

    def write_contact(self, company_slug: str, contact: Contact) -> Path:
        path = self.company_dir(company_slug) / "contacts" / f"{contact.slug}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_file(contact_to_frontmatter(contact), contact.notes),
                        encoding="utf-8")
        return path

    def write_interaction(self, company_slug: str, it: Interaction) -> Path:
        path = self.company_dir(company_slug) / "interactions" / f"{it.id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_file(interaction_to_frontmatter(it), it.body),
                        encoding="utf-8")
        return path

    # --- coercion for form input

    @staticmethod
    def _coerce_int(value, field_name: str) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            raise ValidationError(
                {field_name: f"{field_name} must be a whole number, got {value!r}"}
            )

    @staticmethod
    def _coerce_date(value, field_name: str) -> date | None:
        try:
            return parse_date(value)
        except ValidationError:
            raise ValidationError(
                {field_name: f"{field_name} must be YYYY-MM-DD, got {value!r}"}
            )

    @staticmethod
    def _coerce_datetime(value, field_name: str) -> datetime | None:
        try:
            return parse_datetime(value)
        except ValidationError:
            raise ValidationError(
                {field_name: f"{field_name} must be YYYY-MM-DDTHH:MM, got {value!r}"}
            )

    @staticmethod
    def _coerce_enum(value, enum, field_name: str, allow_empty: bool,
                     default: str = "") -> str:
        value = (value or "").strip() if isinstance(value, str) else (
            value.value if isinstance(value, enum) else str(value or "").strip()
        )
        if not value:
            if allow_empty:
                return default
            raise ValidationError({field_name: f"{field_name} is required"})
        allowed = [e.value for e in enum]
        if value not in allowed:
            raise ValidationError(
                {field_name: f"unknown {field_name} {value!r} "
                             f"(allowed: {', '.join(allowed)})"}
            )
        return value

    def _coerce_outcome(self, value, current: str = "") -> str:
        """Empty, one of the configured outcomes, or unchanged (a legacy value
        already in the file must not block saving the rest of the form)."""
        value = (value or "").strip()
        if value and value != current and value not in self.outcomes:
            raise ValidationError(
                {"outcome": f"unknown outcome {value!r} "
                            f"(allowed: {', '.join(self.outcomes)})"}
            )
        return value

    # --- mutations: company

    def create_company(
        self,
        name,
        website="",
        linkedin="",
        country="",
        source="other",
        stage="prospect",
        lost_reason="",
        requalify_on=None,
        value_eur_month=None,
        my_score=None,
        fit_score=None,
        fte_estimate="",
        ae_count=None,
        product_oneliner="",
        next_step="",
        next_step_due=None,
        next_step_status="open",
        tags=None,
        notes="",
    ) -> Company:
        name = (name or "").strip()
        if not name:
            raise ValidationError({"name": "name is required"})
        country = self._coerce_enum(normalise_country(country), Country, "country", True, "")
        source = self._coerce_enum(source, Source, "source", True, "other")
        stage = self._coerce_enum(stage, Stage, "stage", True, "prospect")
        lost_reason = (lost_reason or "").strip()
        if stage == Stage.LOST.value and not lost_reason:
            raise ValidationError(
                {"lost_reason": "lost_reason is required when stage is lost"}
            )
        if stage not in REASON_STAGES:
            lost_reason = ""
        requalify_on = self._coerce_date(requalify_on, "requalify_on")
        if stage != Stage.TEMP_DISQUALIFIED.value:
            requalify_on = None
        now = self.now()
        taken = set(self.companies)
        if self.companies_dir.exists():
            taken |= {p.name for p in self.companies_dir.iterdir() if p.is_dir()}
        slug = unique_slug(slugify(name, strip_legal=True, default="company"), taken)
        company = Company(
            name=name,
            slug=slug,
            website=normalise_website(website),
            linkedin=(linkedin or "").strip(),
            country=country,
            source=source,
            stage=stage,
            stage_changed=now.date(),
            lost_reason=lost_reason,
            requalify_on=requalify_on,
            value_eur_month=self._coerce_int(value_eur_month, "value_eur_month"),
            my_score=self._coerce_int(my_score, "my_score"),
            fit_score=self._coerce_int(fit_score, "fit_score"),
            fte_estimate=(fte_estimate or "").strip(),
            ae_count=self._coerce_int(ae_count, "ae_count"),
            product_oneliner=" ".join((product_oneliner or "").split()),
            next_step=(next_step or "").strip(),
            next_step_due=self._coerce_date(next_step_due, "next_step_due"),
            next_step_status=self._coerce_enum(next_step_status, TaskStatus,
                                               "next_step_status", True, "open"),
            tags=parse_tags(tags),
            created=now,
            updated=now,
            notes=normalise_body(notes),
        )
        if not company.has_next_step:
            company.next_step_status = TaskStatus.OPEN.value
        if stage != Stage.PROSPECT.value:
            # Prospect is the implicit start; any other start is recorded.
            company.stage_history = [StageChange(now.date(), "", stage, lost_reason)]
        self.write_company(company)
        self.companies[slug] = company
        self._notify(f"company: {slug} created")
        return company

    def update_company(self, slug: str, message: str | None = None, **fields) -> Company:
        """Update fields; `message` overrides the default commit message."""
        company = self.companies.get(slug)
        if company is None:
            raise ValidationError({"slug": f"unknown company {slug!r}"})
        old_stage = company.stage
        new = Company(**{k: getattr(company, k) for k in COMPANY_COPY_FIELDS})
        new.extra = dict(company.extra)
        new.contacts = company.contacts
        new.interactions = company.interactions

        if "name" in fields:
            name = (fields["name"] or "").strip()
            if not name:
                raise ValidationError({"name": "name is required"})
            new.name = name
        if "website" in fields:
            new.website = normalise_website(fields["website"])
        if "linkedin" in fields:
            new.linkedin = (fields["linkedin"] or "").strip()
        if "country" in fields:
            new.country = self._coerce_enum(normalise_country(fields["country"]), Country, "country",
                                            True, "")
        if "source" in fields:
            new.source = self._coerce_enum(fields["source"], Source, "source", True,
                                           "other")
        if "stage" in fields:
            new.stage = self._coerce_enum(fields["stage"], Stage, "stage", True,
                                          "prospect")
        if "lost_reason" in fields:
            new.lost_reason = (fields["lost_reason"] or "").strip()
        if "requalify_on" in fields:
            new.requalify_on = self._coerce_date(fields["requalify_on"], "requalify_on")
        if "value_eur_month" in fields:
            new.value_eur_month = self._coerce_int(fields["value_eur_month"],
                                                   "value_eur_month")
        if "my_score" in fields:
            new.my_score = self._coerce_int(fields["my_score"], "my_score")
        if "fit_score" in fields:
            new.fit_score = self._coerce_int(fields["fit_score"], "fit_score")
        if "fte_estimate" in fields:
            new.fte_estimate = (fields["fte_estimate"] or "").strip()
        if "ae_count" in fields:
            new.ae_count = self._coerce_int(fields["ae_count"], "ae_count")
        if "product_oneliner" in fields:
            new.product_oneliner = " ".join((fields["product_oneliner"] or "").split())
        if "next_step" in fields:
            new.next_step = (fields["next_step"] or "").strip()
        if "next_step_due" in fields:
            new.next_step_due = self._coerce_date(fields["next_step_due"],
                                                  "next_step_due")
        status_explicit = False
        if "next_step_status" in fields:
            status = self._coerce_enum(fields["next_step_status"], TaskStatus,
                                       "next_step_status", True, "open")
            status_explicit = status != company.next_step_status
            new.next_step_status = status
        # A rewritten next step is a new task: it starts open unless the caller
        # changed the status in the same write.
        if new.next_step != company.next_step and not status_explicit:
            new.next_step_status = TaskStatus.OPEN.value
        if not new.has_next_step:
            new.next_step_status = TaskStatus.OPEN.value
        if "tags" in fields:
            new.tags = parse_tags(fields["tags"])
        if "notes" in fields:
            new.notes = normalise_body(fields["notes"])

        if new.stage == Stage.LOST.value and not new.lost_reason:
            raise ValidationError(
                {"lost_reason": "lost_reason is required when stage is lost"}
            )
        if new.stage not in REASON_STAGES:
            new.lost_reason = ""
        if new.stage != Stage.TEMP_DISQUALIFIED.value:
            new.requalify_on = None

        now = self.now()
        new.updated = now
        stage_changed = new.stage != old_stage
        if stage_changed:
            new.stage_changed = now.date()
            # Append-only: a new list so the old Company object stays untouched.
            new.stage_history = list(company.stage_history) + [
                StageChange(now.date(), old_stage, new.stage, new.lost_reason)]

        self.write_company(new)
        self.companies[slug] = new
        if message:
            self._notify(message)
        elif stage_changed:
            self._notify(f"company: {slug} stage {old_stage} -> {new.stage}")
        elif set(fields) == {"next_step_status"} and status_explicit:
            word = "done" if new.next_step_done else "reopened"
            self._notify(f"company: {slug} next step {word}")
        else:
            self._notify(f"company: {slug} updated")
        return new

    def requalify_due(self, today: date | None = None) -> list[str]:
        """Put every temp-disqualified company whose requalify date has arrived
        back into prospect. Idempotent; one commit for all of them."""
        today = today or self.today()
        due = sorted(c.slug for c in self.companies.values() if c.requalify_due(today))
        if not due:
            return []
        if len(due) == 1:
            until = self.companies[due[0]].requalify_on
            message = f"company: {due[0]} requalified (parked until {until:%Y-%m-%d})"
        else:
            message = f"company: requalified {', '.join(due)} (parked until today)"
        with self.batch(message):
            for slug in due:
                self.update_company(slug, stage=Stage.PROSPECT.value)
        return due

    def backfill_stage_history(self, slug: str, history: list[StageChange]) -> Company:
        """Write a reconstructed history (owncrm backfill-history) for a company
        that has none yet. Existing entries are never rewritten."""
        company = self.companies.get(slug)
        if company is None:
            raise ValidationError({"slug": f"unknown company {slug!r}"})
        if company.stage_history:
            raise ValidationError({"stage_history": f"{slug} already has a stage history"})
        new = Company(**{k: getattr(company, k) for k in COMPANY_COPY_FIELDS})
        new.extra = dict(company.extra)
        new.contacts = company.contacts
        new.interactions = company.interactions
        new.stage_history = sorted(history, key=lambda e: e.date)
        new.updated = self.now()
        self.write_company(new)
        self.companies[slug] = new
        self._notify(f"company: {slug} stage history backfilled")
        return new

    # --- merging

    @staticmethod
    def _merge_value(field_name: str, keep_value, drop_value, choice: str | None):
        if choice == "drop":
            return drop_value
        if choice == "both":
            if field_name == "tags":
                return sorted(set(keep_value) | set(drop_value))
            if field_name == "notes":
                parts = [p.strip("\n") for p in (keep_value, drop_value) if p.strip()]
                return "\n\n---\n\n".join(parts) + "\n" if parts else ""
        if choice == "keep":
            return keep_value
        return drop_value if keep_value in ("", None, []) else keep_value

    def merge_companies(self, keep: str, drop: str,
                        choices: dict[str, str] | None = None) -> Company:
        """Fold company `drop` into `keep`: fields per `choices` (keep | drop |
        both; default keeps the non-empty one), contacts and interactions moved,
        the dropped folder deleted. One commit."""
        choices = choices or {}
        a = self.companies.get(keep)
        b = self.companies.get(drop)
        if a is None:
            raise ValidationError({"keep": f"unknown company {keep!r}"})
        if b is None:
            raise ValidationError({"drop": f"unknown company {drop!r}"})
        if keep == drop:
            raise ValidationError({"drop": "a company cannot be merged into itself"})
        merged = Company(**{k: getattr(a, k) for k in COMPANY_COPY_FIELDS})
        for field_name in COMPANY_MERGE_FIELDS:
            setattr(merged, field_name, self._merge_value(
                field_name, getattr(a, field_name), getattr(b, field_name),
                choices.get(field_name)))
        if merged.stage == Stage.LOST.value and not merged.lost_reason:
            raise ValidationError(
                {"lost_reason": "lost_reason is required when stage is lost"})
        if merged.stage not in REASON_STAGES:
            merged.lost_reason = ""
        if merged.stage != Stage.TEMP_DISQUALIFIED.value:
            merged.requalify_on = None
        if not merged.has_next_step:
            merged.next_step_status = "open"
        created = [c for c in (a.created, b.created) if c]
        merged.created = min(created) if created else a.created
        merged.updated = self.now()
        # Both histories survive, oldest first (stable for same-day entries).
        # When the merged stage is not where the combined history ends (e.g. a
        # stage picked by hand, or no history yet), record the move from ours.
        merged.stage_history = sorted(a.stage_history + b.stage_history,
                                      key=lambda e: e.date)
        last = merged.stage_history[-1].to_stage if merged.stage_history else a.stage
        if merged.stage != last:
            merged.stage_history.append(StageChange(
                merged.updated.date(), last, merged.stage, merged.lost_reason))

        merged.contacts = dict(a.contacts)
        slug_map: dict[str, str] = {}
        for cslug, contact in b.contacts.items():
            new_slug = unique_slug(cslug, set(merged.contacts))
            moved = Contact(**{k: getattr(contact, k) for k in CONTACT_COPY_FIELDS})
            moved.slug = new_slug
            self.write_contact(keep, moved)
            merged.contacts[new_slug] = moved
            slug_map[cslug] = new_slug
        for it in b.interactions:
            moved = Interaction(**{k: getattr(it, k) for k in INTERACTION_COPY_FIELDS})
            moved.contact = slug_map.get(it.contact, it.contact) if it.contact else ""
            moved.id = self._interaction_id(keep, moved)
            self.write_interaction(keep, moved)
        self.write_company(merged)
        shutil.rmtree(self.company_dir(drop))
        self.companies.pop(drop, None)
        self.reload_company(keep)
        self._notify(f"company: {drop} merged into {keep}")
        return self.companies[keep]

    def merge_contacts(self, company_slug: str, keep: str, drop: str,
                       choices: dict[str, str] | None = None) -> Contact:
        """Fold contact `drop` into `keep` within one company; interactions of
        `drop` are re-pointed (and renamed) to `keep`. One commit."""
        choices = choices or {}
        company = self.companies.get(company_slug)
        if company is None:
            raise ValidationError({"company": f"unknown company {company_slug!r}"})
        a = company.contacts.get(keep)
        b = company.contacts.get(drop)
        if a is None:
            raise ValidationError({"keep": f"unknown contact {keep!r}"})
        if b is None:
            raise ValidationError({"drop": f"unknown contact {drop!r}"})
        if keep == drop:
            raise ValidationError({"drop": "a contact cannot be merged into itself"})
        merged = Contact(**{k: getattr(a, k) for k in CONTACT_COPY_FIELDS})
        for field_name in CONTACT_MERGE_FIELDS:
            setattr(merged, field_name, self._merge_value(
                field_name, getattr(a, field_name), getattr(b, field_name),
                choices.get(field_name)))
        if not merged.first_name and not merged.last_name:
            raise ValidationError({"first_name": "first name is required"})
        created = [c for c in (a.created, b.created) if c]
        merged.created = min(created) if created else a.created
        merged.updated = self.now()
        self.write_contact(company_slug, merged)
        folder = self.company_dir(company_slug) / "interactions"
        for it in company.interactions:
            if it.contact != drop:
                continue
            moved = Interaction(**{k: getattr(it, k) for k in INTERACTION_COPY_FIELDS})
            moved.contact = keep
            old_path = folder / f"{it.id}.md"
            moved.id = self._interaction_id(company_slug, moved, exclude=it.id)
            self.write_interaction(company_slug, moved)
            if moved.id != it.id and old_path.exists():
                old_path.unlink()
        (self.company_dir(company_slug) / "contacts" / f"{drop}.md").unlink(missing_ok=True)
        self.reload_company(company_slug)
        self._notify(f"contact: {company_slug}/{drop} merged into {keep}")
        return self.companies[company_slug].contacts[keep]

    # --- mutations: contact

    def create_contact(self, company_slug: str, first_name, last_name="", title="",
                       linkedin="", email="", phone="", role="", notes="") -> Contact:
        company = self.companies.get(company_slug)
        if company is None:
            raise ValidationError({"company": f"unknown company {company_slug!r}"})
        first_name = " ".join((first_name or "").split())
        last_name = " ".join((last_name or "").split())
        if not first_name and not last_name:
            raise ValidationError({"first_name": "first name is required"})
        name = f"{first_name} {last_name}".strip()
        now = self.now()
        existing = set(company.contacts)
        contacts_dir = self.company_dir(company_slug) / "contacts"
        if contacts_dir.is_dir():
            existing |= {p.stem for p in contacts_dir.glob("*.md")}
        contact = Contact(
            first_name=first_name,
            last_name=last_name,
            slug=unique_slug(slugify(name, default="contact"), existing),
            title=(title or "").strip(),
            linkedin=(linkedin or "").strip(),
            email=normalise_email(email),
            phone=(phone or "").strip(),
            role=self._coerce_enum(role, Role, "role", True, ""),
            created=now,
            updated=now,
            notes=normalise_body(notes),
        )
        self.write_contact(company_slug, contact)
        company.contacts[contact.slug] = contact
        self._notify(f"contact: {company_slug}/{contact.slug} created")
        return contact

    def update_contact(self, company_slug: str, cslug: str, message: str | None = None,
                       **fields) -> Contact:
        company = self.companies.get(company_slug)
        if company is None:
            raise ValidationError({"company": f"unknown company {company_slug!r}"})
        contact = company.contacts.get(cslug)
        if contact is None:
            raise ValidationError({"contact": f"unknown contact {cslug!r}"})
        new = Contact(**{k: getattr(contact, k) for k in (
            "first_name", "last_name", "slug", "title", "linkedin", "email", "phone",
            "role", "created", "updated", "notes")})
        new.extra = dict(contact.extra)
        if "first_name" in fields:
            new.first_name = " ".join((fields["first_name"] or "").split())
        if "last_name" in fields:
            new.last_name = " ".join((fields["last_name"] or "").split())
        if not new.first_name and not new.last_name:
            raise ValidationError({"first_name": "first name is required"})
        if "title" in fields:
            new.title = (fields["title"] or "").strip()
        if "linkedin" in fields:
            new.linkedin = (fields["linkedin"] or "").strip()
        if "email" in fields:
            new.email = normalise_email(fields["email"])
        if "phone" in fields:
            new.phone = (fields["phone"] or "").strip()
        if "role" in fields:
            new.role = self._coerce_enum(fields["role"], Role, "role", True, "")
        if "notes" in fields:
            new.notes = normalise_body(fields["notes"])
        new.updated = self.now()
        self.write_contact(company_slug, new)
        company.contacts[new.slug] = new
        self._notify(message or f"contact: {company_slug}/{new.slug} updated")
        return new

    # --- mutations: interaction

    def _interaction_id(self, company_slug: str, it: Interaction,
                        exclude: str | None = None) -> str:
        base = it.base_id()
        folder = self.company_dir(company_slug) / "interactions"
        candidate, n = base, 1
        while True:
            if candidate == exclude or not (folder / f"{candidate}.md").exists():
                return candidate
            n += 1
            candidate = f"{base}-{n}"

    def create_interaction(self, company_slug: str, channel, direction, subject="",
                           contact="", date=None, outcome="", body="",
                           source="manual", message_id="") -> Interaction:
        company = self.companies.get(company_slug)
        if company is None:
            raise ValidationError({"company": f"unknown company {company_slug!r}"})
        subject = (subject or "").strip()
        channel = self._coerce_enum(channel, Channel, "channel", False)
        direction = self._coerce_enum(direction, Direction, "direction", False)
        contact = (contact or "").strip()
        if contact and contact not in company.contacts:
            raise ValidationError(
                {"contact": f"unknown contact {contact!r} for {company_slug!r}"}
            )
        when = self._coerce_datetime(date, "date") or self.now()
        it = Interaction(
            id="",
            date=when,
            channel=channel,
            direction=direction,
            contact=contact,
            subject=subject,
            outcome=self._coerce_outcome(outcome),
            source=self._coerce_enum(source, InteractionSource, "source", False),
            message_id=(message_id or "").strip(),
            body=normalise_body(body),
        )
        it.id = self._interaction_id(company_slug, it)
        self.write_interaction(company_slug, it)
        company.interactions.append(it)
        company.interactions.sort(key=lambda i: (i.date or datetime.min, i.id),
                                  reverse=True)
        self._notify(
            f"interaction: {company_slug} {channel} {direction} "
            f"{it.contact_label} {when:%Y-%m-%dT%H:%M}"
        )
        return it

    def update_interaction(self, company_slug: str, id: str, **fields) -> Interaction:
        company = self.companies.get(company_slug)
        if company is None:
            raise ValidationError({"company": f"unknown company {company_slug!r}"})
        old = next((i for i in company.interactions if i.id == id), None)
        if old is None:
            raise ValidationError({"id": f"unknown interaction {id!r}"})
        new = Interaction(**{k: getattr(old, k) for k in INTERACTION_COPY_FIELDS})
        new.extra = dict(old.extra)
        if "date" in fields:
            when = self._coerce_datetime(fields["date"], "date")
            if when is None:
                raise ValidationError({"date": "date is required"})
            new.date = when
        if "channel" in fields:
            new.channel = self._coerce_enum(fields["channel"], Channel, "channel", False)
        if "direction" in fields:
            new.direction = self._coerce_enum(fields["direction"], Direction,
                                              "direction", False)
        if "contact" in fields:
            contact = (fields["contact"] or "").strip()
            if contact and contact not in company.contacts:
                raise ValidationError(
                    {"contact": f"unknown contact {contact!r} for {company_slug!r}"}
                )
            new.contact = contact
        if "subject" in fields:
            new.subject = (fields["subject"] or "").strip()
        if "outcome" in fields:
            new.outcome = self._coerce_outcome(fields["outcome"], old.outcome)
        if "body" in fields:
            new.body = normalise_body(fields["body"])

        folder = self.company_dir(company_slug) / "interactions"
        old_path = folder / f"{old.id}.md"
        desired = new.base_id()
        suffix = old.id[len(desired) + 1:]
        keeps_id = old.id == desired or (
            old.id.startswith(desired + "-") and suffix.isdigit()
        )
        if not keeps_id:
            new.id = self._interaction_id(company_slug, new, exclude=old.id)
        self.write_interaction(company_slug, new)
        if new.id != old.id and old_path.exists():
            old_path.unlink()
        company.interactions = [i for i in company.interactions if i.id != old.id]
        company.interactions.append(new)
        company.interactions.sort(key=lambda i: (i.date or datetime.min, i.id),
                                  reverse=True)
        if set(fields) == {"outcome"}:
            self._notify(f"interaction: {company_slug} {new.id} outcome "
                         f"{new.outcome or 'unknown'}")
        else:
            self._notify(f"interaction: {company_slug} {new.id} updated")
        return new
