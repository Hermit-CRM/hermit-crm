"""The date format the person reads and types (Settings > Appearance).

Files, exports and anything an AI tool reads stay ISO (YYYY-MM-DD); this module
is only for what the web pages show and what a form field accepts. ISO is
always accepted as input, whichever style is chosen, so a pasted
`2026-12-01` or an old bookmark never breaks.

The chosen style is process-wide state, set by the web app when it starts and
whenever config.toml is re-read (`set_style`). Nothing here imports models, so
models.parse_date can use it.
"""

from __future__ import annotations

import re
from datetime import date, datetime

# key -> (label shown in Settings, strftime pattern, typing hint)
STYLES: dict[str, tuple[str, str, str]] = {
    "iso": ("2026-12-31", "%Y-%m-%d", "YYYY-MM-DD"),
    "dmy-dash": ("31-12-2026", "%d-%m-%Y", "DD-MM-YYYY"),
    "dmy": ("31/12/2026", "%d/%m/%Y", "DD/MM/YYYY"),
    "mdy": ("12/31/2026", "%m/%d/%Y", "MM/DD/YYYY"),
}
DEFAULT = "iso"

_style = DEFAULT


def normalise(value) -> str:
    """A known style key, else the default (a hand-edited config.toml)."""
    key = str(value or "").strip().lower()
    return key if key in STYLES else DEFAULT


def set_style(value) -> str:
    global _style
    _style = normalise(value)
    return _style


def style() -> str:
    return _style


def pattern() -> str:
    return STYLES[_style][1]


def hint() -> str:
    """How to type a date in the chosen style: "DD/MM/YYYY"."""
    return STYLES[_style][2]


def hint_datetime() -> str:
    return hint() + " HH:MM"


def fmt(d: date | None) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime(pattern())


def fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return f"{fmt(dt)} {dt:%H:%M}"


_TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?$")


def parse(text: str) -> date | None:
    """`text` in the chosen style (not ISO: the caller tries that first), or
    None when it does not read as a date in that style."""
    try:
        return datetime.strptime(text.strip(), pattern()).date()
    except ValueError:
        return None


def parse_dt(text: str) -> datetime | None:
    """`text` as "<date in the chosen style>[ HH:MM[:SS]]", else None."""
    parts = text.strip().replace("T", " ").split()
    if not 1 <= len(parts) <= 2:
        return None
    day = parse(parts[0])
    if day is None:
        return None
    hour = minute = 0
    if len(parts) == 2:
        found = _TIME.match(parts[1])
        if not found:
            return None
        hour, minute = int(found.group(1)), int(found.group(2))
        if hour > 23 or minute > 59:
            return None
    return datetime(day.year, day.month, day.day, hour, minute)
