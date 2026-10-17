"""One place that turns a name into a file path under a folder, and refuses a
name that would climb out of it.

Slugs, ids and topics come from URLs and form fields. Most are checked
somewhere upstream (a lookup in the index, a pattern), but a path built from
them should not depend on that holding everywhere, now and after the next
change. Every such path goes through `contained`.
"""
from __future__ import annotations

import os
from pathlib import Path

from .models import ValidationError


def contained(base: Path | str, *parts: str) -> Path:
    """`base/part/part...`, or ValidationError when the result leaves `base`.

    A name with a separator or a `..` in it, or an absolute one, ends up
    outside `base` once the path is normalised. Links are not followed: a data
    folder that is itself a symlink keeps working.
    """
    if not parts:
        return Path(base)
    root = os.path.abspath(os.fspath(base))
    full = os.path.abspath(os.path.join(root, *parts))
    if "\0" in full or not full.startswith(os.path.join(root, "")):
        raise ValidationError({"path": f"{'/'.join(parts)!r} is not a name inside "
                                       f"{os.path.basename(root) or root}"})
    # Relative to `base` as it was given, so a relative base stays relative.
    return Path(base) / os.path.relpath(full, root)
