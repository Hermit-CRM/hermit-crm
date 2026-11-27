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

"""Compiled page templates, kept once per process and shared by every app.

Jinja turns each template into Python code the first time a page needs it, and
keeps that code in its environment. Every ``create_app`` builds a new
environment, so every new app compiled every template again: about a quarter
of a second for the first page an app shows. A server builds one app, so it
never noticed; the test suite builds thousands.

``SHARED`` is a Jinja bytecode cache in memory. Jinja looks a template up in it
by name and by a checksum of its source, so a template whose text changed is
compiled afresh, never served stale. Only the compiled code is shared: each
app still renders with its own globals and filters, looked up when the page is
drawn. The code does depend on how the environment is set up (autoescaping,
and which filters take the context): every app sets its environment up the
same way in ``create_app``, so that is the same for all. Nothing is written to
disk.
"""

from __future__ import annotations

import threading

from jinja2 import BytecodeCache
from jinja2.bccache import Bucket


class MemoryBytecodeCache(BytecodeCache):
    """A Jinja bytecode cache that lives in this process's memory only."""

    def __init__(self) -> None:
        self._code: dict[str, bytes] = {}
        self._lock = threading.Lock()  # pages render on worker threads

    def load_bytecode(self, bucket: Bucket) -> None:
        with self._lock:
            code = self._code.get(bucket.key)
        if code is not None:
            bucket.bytecode_from_string(code)

    def dump_bytecode(self, bucket: Bucket) -> None:
        code = bucket.bytecode_to_string()
        with self._lock:
            self._code[bucket.key] = code

    def clear(self) -> None:
        with self._lock:
            self._code.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._code)


SHARED = MemoryBytecodeCache()
