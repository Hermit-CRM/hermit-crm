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


"""Compiled page templates are shared by every app in one process (templatecache.py)."""

from __future__ import annotations

import jinja2
from fastapi.testclient import TestClient

from hermitcrm import templatecache
from hermitcrm.templatecache import MemoryBytecodeCache
from hermitcrm.web import create_app
from conftest import CONFIG


def env(cache, source: str) -> jinja2.Environment:
    return jinja2.Environment(loader=jinja2.DictLoader({"page.html": source}),
                              bytecode_cache=cache)


def counting_compiles(monkeypatch) -> list:
    """Every template Jinja compiles from source, by name, from here on."""
    compiled: list = []
    real = jinja2.Environment.compile

    def compile(self, source, name=None, filename=None, raw=False, defer_init=False):
        compiled.append(name)
        return real(self, source, name, filename, raw, defer_init)

    monkeypatch.setattr(jinja2.Environment, "compile", compile)
    return compiled


def test_a_second_environment_reuses_the_compiled_template(monkeypatch):
    cache = MemoryBytecodeCache()
    compiled = counting_compiles(monkeypatch)
    assert env(cache, "Hello {{ name }}").get_template("page.html").render(name="Jane") == "Hello Jane"
    assert compiled == ["page.html"]
    # A new environment (a new app) on the same cache: rendered, not compiled again.
    assert env(cache, "Hello {{ name }}").get_template("page.html").render(name="Max") == "Hello Max"
    assert compiled == ["page.html"]


def test_a_changed_template_is_compiled_again_not_served_stale(monkeypatch):
    cache = MemoryBytecodeCache()
    compiled = counting_compiles(monkeypatch)
    assert env(cache, "old {{ x }}").get_template("page.html").render(x=1) == "old 1"
    assert env(cache, "new {{ x }}").get_template("page.html").render(x=2) == "new 2"
    assert compiled == ["page.html", "page.html"]


def test_an_empty_cache_loads_nothing_and_clear_empties_it():
    cache = MemoryBytecodeCache()
    bucket = cache.get_bucket(jinja2.Environment(), "page.html", None, "x")
    assert bucket.code is None
    env(cache, "x").get_template("page.html")
    assert len(cache) == 1
    cache.clear()
    assert len(cache) == 0


def test_every_app_uses_the_one_shared_cache(repo, tmp_path, monkeypatch):
    first = create_app(repo, config=dict(CONFIG))
    second = create_app(repo, config=dict(CONFIG))
    assert first.state.templates.env.bytecode_cache is templatecache.SHARED
    assert second.state.templates.env.bytecode_cache is templatecache.SHARED

    assert TestClient(first).get("/companies").status_code == 200  # compiles the page once
    compiled = counting_compiles(monkeypatch)
    page = TestClient(second).get("/companies")
    assert page.status_code == 200
    assert compiled == []
    # Rendered by the second app with its own globals, from code compiled for the first.
    assert second.state.csrf_token in page.text
    assert first.state.csrf_token not in page.text
