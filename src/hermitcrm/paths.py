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
