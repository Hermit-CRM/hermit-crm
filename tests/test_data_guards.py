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

"""The three medium findings of the 2026-09 audit, kept fixed.

* Links: a website or LinkedIn field never becomes a `javascript:` link.
* Front matter: keys Hermit CRM does not know read back as what was written.
* Concurrency: writes from threads and from other processes do not interleave.
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm.models import dump_frontmatter, normalise_linkedin, normalise_website, safe_href
from hermitcrm.store import Store, WriteLock, split_file
from hermitcrm.web import create_app

CONFIG = {"port": 8765, "silent_days": 14, "push_enabled": False, "remote": "origin",
          "welcome_dismissed": True}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for args in (["init", "-b", "main"], ["config", "user.name", "CRM Test"],
                 ["config", "user.email", "crm@test.local"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "companies").mkdir()
    return tmp_path


@pytest.fixture
def client(repo: Path) -> TestClient:
    app = create_app(repo, config=dict(CONFIG))
    app.state.setup_redirected = True
    return TestClient(app, follow_redirects=False)


# -------------------------------------------------------------------- links


BAD = ["javascript:alert(1)", "JavaScript:alert(1)", "javascript://x.example/%0aalert(1)",
       "data:text/html,<script>alert(1)</script>", " javascript:alert(1)",
       "vbscript:msgbox(1)"]


@pytest.mark.parametrize("value", BAD)
def test_normalisers_only_make_web_links(value):
    for normalise in (normalise_website, normalise_linkedin):
        assert normalise(value).startswith("https://")


def test_normalisers_keep_ordinary_links():
    assert normalise_website("example.com") == "https://example.com"
    assert normalise_website("http://example.com/a") == "http://example.com/a"
    assert normalise_website("ftp://example.com") == "https://example.com"
    assert normalise_linkedin("linkedin.com/in/jane/") == "https://www.linkedin.com/in/jane"
    assert normalise_linkedin("www.linkedin.com/company/acme") == \
        "https://www.linkedin.com/company/acme"


@pytest.mark.parametrize("value", BAD + ["https://x.example/\nb", "/companies", "#top", ""])
def test_safe_href_refuses_anything_but_http(value):
    assert safe_href(value) == ""


def test_safe_href_keeps_http():
    assert safe_href("https://example.com/a?b=1") == "https://example.com/a?b=1"
    assert safe_href("HTTP://example.com") == "HTTP://example.com"


def hrefs(page: str) -> list[str]:
    return re.findall(r'href="([^"]*)"', page)


def assert_no_script_links(page: str) -> None:
    for href in hrefs(page):
        assert not re.match(r"\s*(javascript|data|vbscript):", href, re.I), href


def test_link_fields_from_a_form_are_never_script_links(client, repo):
    resp = client.post("/companies", data={"name": "Linky BV",
                                           "website": "javascript://x.example/%0aalert(1)",
                                           "linkedin": "javascript:alert(document.domain)"})
    assert resp.status_code == 303
    text = (repo / "companies/linky/company.md").read_text(encoding="utf-8")
    assert "website: https://x.example/%0aalert(1)" in text
    for path in ("/companies/linky", "/companies"):
        assert_no_script_links(client.get(path).text)


def test_a_hand_edited_file_does_not_become_a_script_link(client, repo):
    client.post("/companies", data={"name": "Acme BV"})
    store = Store(repo)
    store.load()
    store.create_contact("acme", "Jane", "Doe")
    # Someone edits the files by hand, past every normaliser.
    for rel in ("companies/acme/company.md", "companies/acme/contacts/jane-doe.md"):
        path = repo / rel
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"^linkedin:.*$", "linkedin: javascript:alert(1)", text, flags=re.M)
        text = re.sub(r"^website:.*$", "website: 'javascript:alert(2)'", text, flags=re.M)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "hand edit"], cwd=repo, check=True,
                   capture_output=True)
    for path in ("/companies/acme", "/companies", "/contacts",
                 "/companies/acme/contacts/jane-doe"):
        page = client.get(path)
        assert page.status_code == 200, path
        assert_no_script_links(page.text)


# ------------------------------------------------------------- front matter


def round_trip(meta: dict) -> dict:
    back, _ = split_file("---\n" + dump_frontmatter(meta) + "---\n")
    return back


@pytest.mark.parametrize("value", [
    [True, 1.5, None], [[1, 2], {"a": "b"}], ["a", 1], [1, 2, 3], {"a": [1, {"b": True}]},
    1e20, -0.5, 2.0, "123", "yes", "a: b", "---", "# not a comment", "multi\nline",
    ["plain", "a: b", "yes"], [{"a": 1}, {"b": [2]}],
])
def test_an_unknown_value_reads_back_as_written(value):
    assert round_trip({"x_extra": value}) == {"x_extra": value}


def test_infinity_reads_back():
    assert math.isinf(round_trip({"x": float("inf")})["x"])


@pytest.mark.parametrize("key", ["weird key: yes", "123", "a b", "#hash", "yes", "- dash"])
def test_an_odd_key_keeps_the_file_readable(key):
    meta = {"name": "X", key: "v", "after": 1}
    assert round_trip(meta) == meta


def test_known_fields_keep_their_layout():
    text = dump_frontmatter({"name": "Acme", "tags": ["a", "b"], "value_eur_month": 1500,
                             "score": 2.5, "next_step": "", "empty": []})
    assert text == ("name: Acme\ntags: [a, b]\nvalue_eur_month: 1500\nscore: 2.5\n"
                    "next_step:\nempty: []\n")


def test_a_company_with_odd_extra_keys_survives_an_update(repo):
    store = Store(repo)
    store.load()
    store.create_company("Acme BV")
    path = repo / "companies/acme/company.md"
    text = path.read_text(encoding="utf-8")
    head, body = text.split("\n---\n", 1)
    path.write_text(head + "\n'crm id: legacy': 7\nx_flags: [true, 1.5]\n"
                    "x_nested: [[1, 2], {a: b}]\n---\n" + body, encoding="utf-8")
    store = Store(repo)
    assert store.load() == []
    store.update_company("acme", next_step="call")
    fresh = Store(repo)
    assert fresh.load() == []
    meta, _ = split_file(path.read_text(encoding="utf-8"))
    assert meta["crm id: legacy"] == 7
    assert meta["x_flags"] == [True, 1.5]
    assert meta["x_nested"] == [[1, 2], {"a": "b"}]
    assert meta["next_step"] == "call"


# -------------------------------------------------------------- concurrency


def test_concurrent_writes_commit_only_their_own_files(tmp_path):
    (tmp_path / "companies").mkdir()
    commits: list[tuple[str, list[str]]] = []
    store = Store(tmp_path)

    def on_write(message: str) -> None:
        time.sleep(0.005)  # PIPELINE.md takes a while; another thread may write meanwhile
        commits.append((message, store.take_touched()))

    store.on_write = on_write
    store.load()
    barrier = threading.Barrier(8)

    def make(i: int) -> None:
        barrier.wait()
        store.create_company(f"Company {i}")

    threads = [threading.Thread(target=make, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(commits) == 8
    for message, paths in commits:
        slug = re.search(r"company-\d", message).group(0)
        assert paths == [f"companies/{slug}/company.md"], (message, paths)


def test_a_batch_does_not_take_in_another_threads_write(tmp_path):
    (tmp_path / "companies").mkdir()
    commits: list[tuple[str, list[str]]] = []
    store = Store(tmp_path)
    store.on_write = lambda message: commits.append((message, store.take_touched()))
    store.load()
    inside = threading.Event()

    def other() -> None:
        inside.wait()
        store.create_company("Other BV")

    t = threading.Thread(target=other)
    t.start()
    with store.batch("import"):
        store.create_company("Mine BV")
        inside.set()
        time.sleep(0.1)  # the other thread is now waiting, not writing into the batch
    t.join()
    assert commits == [("import", ["companies/mine/company.md"]),
                       ("company: other created", ["companies/other/company.md"])]


def test_concurrent_interactions_get_their_own_ids(tmp_path):
    (tmp_path / "companies").mkdir()
    store = Store(tmp_path, clock=lambda: __import__("datetime").datetime(2026, 9, 18, 10, 0))
    store.load()
    store.create_company("Acme BV")
    barrier = threading.Barrier(6)
    ids: list[str] = []

    def log() -> None:
        barrier.wait()
        ids.append(store.create_interaction("acme", channel="email", direction="in",
                                            body="hi").id)

    threads = [threading.Thread(target=log) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(ids)) == 6
    assert len(list((tmp_path / "companies/acme/interactions").glob("*.md"))) == 6


def test_another_process_holding_the_lock_makes_a_write_wait(repo):
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time\nfrom hermitcrm.store import WriteLock\n"
         f"with WriteLock({str(repo)!r}):\n"
         "    print('held', flush=True)\n    time.sleep(0.6)\n"],
        stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        start = time.monotonic()
        store = Store(repo)
        store.load()  # reading waits too: the holder may be half way through a file
        store.create_company("Acme BV")
        assert time.monotonic() - start > 0.3
    finally:
        holder.wait(timeout=10)
    assert (repo / "companies/acme/company.md").exists()


def test_the_lock_file_lives_inside_git(repo):
    with WriteLock(repo):
        pass
    assert (repo / ".git/hermitcrm.lock").exists()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, text=True,
                            capture_output=True, check=True).stdout
    assert "hermitcrm.lock" not in status


def test_a_folder_without_git_still_writes(tmp_path):
    (tmp_path / "companies").mkdir()
    store = Store(tmp_path)
    store.load()
    store.create_company("Acme BV")
    assert not (tmp_path / ".git").exists()
