"""theme.css in the data folder: your own look for the app, on top of the defaults.

The defaults live in static/tokens.css and are shared with the website. A user
changes their own app by writing a :root { ... } block of token overrides to
<data folder>/theme.css (usually through their AI tool); the app links it last,
so it wins. Nothing here ever changes the shipped defaults.

The file is served from one fixed path and only when it is a regular file inside
the data folder, so a symlink cannot expose anything else. The app's
Content-Security-Policy stops the file loading anything from elsewhere; `lint`
names the lines that try, for `hermitcrm doctor` and Settings > Appearance.
"""

from __future__ import annotations

import re
from pathlib import Path

FILENAME = "theme.css"

# The hint in Settings > Appearance: one line that visibly changes the default
# (Help > Settings has the full template).
EXAMPLE = """\
/* My look for Hermit CRM. Delete this file to go back to the default. */
:root {
  --accent: light-dark(#1a4fd6, #7ea6ff);  /* blue links and buttons */
}
"""

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_IMPORT = re.compile(r"@import\b", re.I)
_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)


def path(root: Path) -> Path | None:
    """The theme file when it exists as a regular file inside the data folder, else None."""
    root = Path(root)
    candidate = root / FILENAME
    try:
        resolved = candidate.resolve(strict=True)
        inside = resolved.is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return None
    return resolved if inside and resolved.is_file() else None


def lint(text: str) -> list[tuple[int, str]]:
    """(line number, problem) for each thing the app will block: @import and url()
    pointing anywhere but a data: URL. Comments are ignored."""
    # Blank out comments but keep their newlines, so line numbers stay right.
    code = _COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    line_of = lambda pos: code.count("\n", 0, pos) + 1  # noqa: E731
    problems = [(line_of(m.start()), "@import loads another file; the app blocks it")
                for m in _IMPORT.finditer(code)]
    for m in _URL.finditer(code):
        target = m.group(2).strip()
        if re.search(r"@import\s*$", code[:m.start()], re.I):
            continue  # already named as the @import it belongs to
        if not target.lower().startswith("data:"):
            problems.append((line_of(m.start()),
                             f"url({target}) loads a file; the app blocks it (only data: URLs work)"))
    return sorted(problems)


def status(root: Path) -> dict:
    """What Settings > Appearance shows: where the file goes, whether it is in use,
    and what in it will not work."""
    found = path(root)
    problems: list[tuple[int, str]] = []
    if found is not None:
        text = found.read_bytes().decode("utf-8", errors="replace")
        problems = lint(text)
    return {"path": str(Path(root) / FILENAME), "active": found is not None,
            "problems": problems}
