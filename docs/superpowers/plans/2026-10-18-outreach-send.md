# Outreach send (scheduled email, paced LinkedIn) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An approved outreach email goes out from the app (now or on a spaced schedule) and is logged once; LinkedIn runs as a paced session where the person clicks Send.

**Architecture:** `outreach.py` keeps the item states (`queued`, `failed` are new). Four new modules: `sendplan.py` (pure planner and caps), `send.py` (settings, message, SMTP, guards, worker), `suppress.py` (suppression list, bounce parsing), `linkedin.py` (session caps and countdown). A launchd/systemd job runs `hermitcrm send due` every 3 minutes. Web, CLI, doctor and schedule are wired to those.

**Tech Stack:** Python 3.11+ standard library only (`smtplib`, `imaplib`, `email`, `fcntl`), FastAPI/Jinja templates, pytest. No network in any test (SMTP/IMAP are test doubles).

**Spec:** `docs/superpowers/specs/2026-10-16-outreach-bot/08-send.md` (decisions of 18 Oct 2026 appended there).

## Decisions (the person's answers, 18 Oct 2026)

1. LinkedIn: **A**, a paced session where the person clicks Send. M5 is not built.
2. Country guard: **no**. `send_email_block_countries` stays `[]`; the guard code exists but is off.
3. A **separate sending mailbox**, about **100 emails a day**. The daily cap is a setting (`send_daily_cap`, default 100). Above 150 a day is strongly discouraged for more than 1-2 days in a row: Settings warns above 100 and above 150, and the planner and worker **hold a day at 150 once the two previous send-days both went over 150** (`SOFT_CEILING = 150`, `MAX_DAYS_OVER = 2`).

**Changed 19 Oct:** the plan is 50 a day (`send_daily_cap` 50, ramp `[10, 20, 30, 40]`, Settings warns above 50 and above 150), and the playbook's opt-out line is optional. The numbers below are the first decision.

Assumptions (called out so they can be changed): the ramp for a fresh mailbox is `[20, 40, 60, 80]` then 100; a re-plan keeps the times the page already showed and only places new, overdue or moved items (so "goes out at the time the page showed" holds); `failed` counts as an open state (no second draft for the contact, and it can be skipped); runtime state (lock, auto-pause) lives in `.git/` so it is never committed and needs no `.gitignore` migration.

## Global Constraints

- Commit messages start with `ai:`; `.venv/bin/pytest` passes before every commit.
- No new runtime dependency. No real people or addresses in code, tests, docs (use example.com).
- Item front-matter changes = numbered migration (idempotent) + tests; writes deterministic; interaction bodies byte for byte.
- Plain text mail, UTF-8; From `owner_name <send_from>`; no BCC, no HTML, no tracking, no `List-Unsubscribe`.
- `Message-ID` from `email.utils.make_msgid(domain=<sending domain>)`, written on the item and committed **before** the SMTP call.
- Every new POST route takes the form token. No MCP tool schedules or sends.
- `send_enabled = false` by default; Send now / Schedule are hidden while off.
- Max one send per worker tick (`send_max_per_tick = 1`); tick every 3 minutes.

## Review Focus

- A contact with no email address, or an address with odd case/whitespace: held back with a reason, never a crash.
- A hand edit to an approved file after scheduling: the hash guard returns it to `ready`.
- The clock jumping (Mac asleep for hours): overdue items re-plan, never burst.
- Two ticks at once (launchd overlap) and a `send now` during a tick: the lock refuses the second.
- Daily cap and the 150 rule across midnight and across non-send days (weekends).
- Unreadable `suppressed.toml` / `.send-state.json`: sending stops safely (fail closed) and says why.

---

### Task 1: Foundations (states, keys, migrations, source, secret, config)

**Files:** Modify `models.py` (`InteractionSource.OUTREACH = "outreach"`), `outreach.py` (STATES + `queued`, `failed`; OPEN_STATES + both; ITEM_KEYS; `Item`; `item_from_text`; `sent_by_interaction` also takes `queued` items), `migrations.py` (m12 item keys, m13 no-op source), `secrets.py` (`send_password`), `store.py` (DEFAULT_CONFIG `send_*`, `linkedin_*`), `learning.py`/`exemplars.py` (`queued`, `failed` count as reviewed). Test: `tests/test_send_foundations.py`.

**Interfaces — Produces:** new `Item` fields `queued: datetime|None, send_at: datetime|None, send_hash: str, message_id: str, send_tries: int, send_error: str, send_note: str, invite_sent: datetime|None, accepted: datetime|None, pitch_sent: datetime|None`, written in ITEM_KEYS right after `skipped`.

Tests (write first): old file round-trips through m12 to the exact bytes `write_item` produces; m12 and m13 idempotent; `LATEST == 13`; an `outreach` interaction loads/writes; `secrets.get("send_password")` reads env `HERMITCRM_SEND_PASSWORD`; a `queued` item is marked sent by an outbound email interaction and keeps `message_id`; `queued`/`failed` are open.

### Task 2: Sending one email (M1)

**Files:** Create `send.py`, `tests/test_send_email.py`. Modify `outreach.py` (`send_now`-facing helpers: `schedule`, `unschedule` state transitions live here), `web.py` + `templates/settings.html` + `outreach.html` (Settings → Sending, Send test, Send now), `cli.py` (`send test`, `outreach send-now`).

**Interfaces — Produces (in `send.py`):**
```python
@dataclass class SendSettings            # all send_* config, parsed once
def settings_from_config(config: dict) -> SendSettings
class SendError(Exception): kind: str; code: int | None; text: str   # kind in auth|quota|temporary|recipient|config
def classify_smtp(exc: Exception) -> SendError
def build_message(item, to: str, settings, *, message_id: str, in_reply_to: str = "", references: str = "") -> EmailMessage
class SmtpSender:                          # satisfies outreach.Sender
    def __init__(self, store, settings, password, smtp_factory=None)
    def send(self, item) -> outreach.SendResult
class OutreachLogger:                      # satisfies outreach.Logger
    def log(self, item, result) -> None    # create_interaction(source="outreach", message_id=item.message_id), flips item to sent
def send_test(root, config, smtp_factory=None) -> str          # mail to myself; the server's exact text on failure
def send_now(store, item_id, *, sender, logger, now, settings) -> outreach.Item
```
Tests: headers/plain text/Message-ID domain/opt-out line only under a cold first touch; `In-Reply-To`/`References` from `follows`/`reply_to` interaction `message_id`; 535 shows Google's text; the logged interaction has the Message-ID and a later BCC import of the same mail logs nothing; `ManualSender` stays default; no test touches the network.

### Task 3: Planner and caps (M2, pure)

**Files:** Create `sendplan.py`, `tests/test_sendplan.py`.
```python
@dataclass(frozen=True) class PlanConfig        # days, window, ramp, daily_cap, min_gap, company_gap_hours, grace, overdue
@dataclass(frozen=True) class Slot              # id, company, domain, follow_up: bool, queued: datetime, send_at: datetime | None
@dataclass(frozen=True) class Sent              # when, company, domain
def day_cap(day: date, first_send: date | None, sent_by_day: dict[date, int], cfg) -> int   # ramp, daily_cap, 150 rule
def plan(queue: list[Slot], sent: list[Sent], now: datetime, cfg) -> dict[str, datetime]
def jitter(item_id: str) -> float               # sha256-seeded, 0.6..1.4
```
Algorithm: items with a `send_at` that is in a send window and not overdue by more than `overdue` stay fixed; the rest are placed in order (follow-ups first, then queued order) by first fit: earliest `t >= now+grace` inside the window, day under `day_cap`, gap from the previous placed time that day (the window start counts as one) of `max(min_gap, window/cap * jitter(id))`, at least `min_gap` before the next placed time, `company_gap_hours` from any same company/domain. Terminates within 60 days.

Tests: window/days, ramp weeks, cap, 150 rule (two over-150 send-days then 150; weekend skipped), jitter bounds and seed stability, gap floor, company spread, grace, order, fixed items untouched, overdue moved without bursts, same input = same output.

### Task 4: Queue operations and the worker (M2)

**Files:** Modify `outreach.py` (`schedule_items`, `unschedule`, `retry`, `move_to_front`), `send.py` (guards, `due`, state file, lock, mailbox), `schedule.py` (`SEND_LABEL = "io.hermitcrm.send"`, plist/unit/timer, `install(send=...)`, `remove`, `status`), `doctor.py`, `cli.py` (`send status|due [--dry-run]|pause|resume`, `outreach schedule|unschedule`, `schedule install --send`), `datafolder.py` (AGENTS rule). Tests: `tests/test_send_worker.py`, extend `tests/test_schedule.py`, `tests/test_doctor.py`.
```python
def due(root, *, now=None, dry_run=False, smtp_factory=None, imap_factory=None) -> list[str]   # report lines
class SendState                                  # .git/hermitcrm-send.json: paused, reason, message, since
class Mailbox                                    # IMAP: reply_since(addr, since), sent_has(message_id); Sent/All by special-use flags
```
Tick order: off/paused → lock → re-plan if overdue → first `send_at <= now` → guards → write `message_id`+`send_tries` and commit → SMTP → log+flip in one commit → classify errors. Error table from the spec; crash recovery searches Sent for the Message-ID.

Tests: every guard; every error class; crash between SMTP and log (found / not found in Sent); one send per tick; lock held; edit/hash mismatch returns to `ready`; Pause stops within one tick; a 2-hour sleep resumes spaced; job files under `HERMITCRM_DRY_SCHEDULE=1`.

### Task 5: Scheduled tab, status strip, banner (M2 UI)

**Files:** Modify `web.py` (tab `scheduled`, actions `schedule`, `unschedule`, `send-now`, `front`, `retry`; `/outreach/schedule-all` preview+confirm; `/outreach/send/pause|resume`; `/settings/send`, `/settings/send/test`, `/settings/send/job`), `templates/outreach.html`, `settings.html`, `base.html` (red banner), `static/` CSS following `DESIGN.md`. Test: `tests/test_send_web.py`.

### Task 6: Bounces, opt-outs, suppression (M3)

**Files:** Create `suppress.py`, `tests/test_suppress.py`. Modify `send.py` (bounce scan at most every 30 min, rate pause), `outreach.py` (`opt_out`), `web.py`/templates (Opted out button on a reply and the contact page).
```python
def load(root) -> list[Entry]; def add(root, address, reason, item="") -> None   # outreach/suppressed.toml, deterministic
def is_suppressed(root, address) -> bool
def parse_dsn(raw: bytes) -> Bounce | None        # Final-Recipient, original Message-ID
def bounce_pause(sent_ids: list[str], bounced: list[str]) -> bool  # >3 in last 50, or >5% with at least 20 sends
```

### Task 7: LinkedIn session (M4)

**Files:** Create `linkedin.py`, `templates/outreach_linkedin.html`, `tests/test_linkedin.py`. Modify `web.py`.
```python
def counters(items, now, cfg) -> Counters          # invites today / rolling 7 days, messages today, this session
def next_card(items, now, cfg, session) -> Card | None
def countdown(item_id: str, cfg) -> int            # seeded 45..120 s
def record_sent / already_connected / couldnt_send / accepted(...)
def pending_reminders(items, now) -> list[Item]    # invites older than 21 days
```
No network call anywhere on the path. Caps: 20 invites a day, 80 per rolling 7 days, 40 messages a day, 10 cards per session, 120 minutes between sessions.

### Task 8: Help, docs, spec update, final verification

`help/sending.md` (+ `TOPICS`), `CHANGELOG.md`, `docs`/`TODO.md` notes, spec status line and decisions; full suite green; demo-folder run against a fake SMTP/IMAP server to verify the real `smtplib` path.

## Self-review

Spec coverage: Goals 1-4 → Tasks 2-6; LinkedIn → Task 7; Pages/CLI/MCP/doctor/help → Tasks 4, 5, 8; Config keys → Task 1; Rollout/Risks → Task 8 (help) and the summary. Gap closed: the spec's per-week ramp default (15..50) is replaced by the person's 100/day decision; everything else follows the spec.
