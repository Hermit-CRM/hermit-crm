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


"""website/build.py: the SHA-256 printed under the download button.

The hash comes from the .sha256 file beside the download, never from a value typed
into content.toml, and a file that does not hold a checksum prints nothing rather
than something wrong. Nothing here writes into website/site/.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("website_build", ROOT / "website" / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

DIGEST = "ab" * 32  # 64 hex characters


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A site folder with download/x.tar.gz.sha256 under it, plus a minimal config."""
    monkeypatch.setattr(build, "SITE", tmp_path)
    (tmp_path / "download").mkdir()
    c = {"links": {"download": "download/x.tar.gz", "sha256": "download/x.tar.gz.sha256"},
         "hero": {"download_button": "Download", "sha256_label": "SHA-256"},
         "release": {"version": "1.0.0", "license": "Apache 2.0"}}
    return tmp_path, c


def test_hash_is_read_from_the_checksum_file(site):
    path, c = site
    (path / "download" / "x.tar.gz.sha256").write_text(f"{DIGEST.upper()}  x.tar.gz\n")
    assert build.sha256_of(c) == DIGEST  # lower-cased, filename dropped
    line = build.sha256_line(c)
    assert f"<code>{DIGEST}</code>" in line and 'href="download/x.tar.gz.sha256"' in line


@pytest.mark.parametrize("content", ["", "not a checksum  x.tar.gz\n", "abc123  x.tar.gz\n",
                                     DIGEST[:-1] + "g  x.tar.gz\n"])
def test_a_file_that_is_not_a_checksum_prints_nothing(site, content):
    path, c = site
    (path / "download" / "x.tar.gz.sha256").write_text(content)
    assert build.sha256_of(c) == ""
    assert build.sha256_line(c) == ""


def test_missing_file_and_external_links_print_nothing(site):
    _, c = site
    assert build.sha256_of(c) == ""  # no file written
    c["links"]["sha256"] = "https://example.com/x.sha256"
    assert build.sha256_of(c) == ""
    c["links"]["sha256"] = "#"
    assert build.sha256_of(c) == ""


def test_hash_shows_only_where_asked(site):
    path, c = site
    (path / "download" / "x.tar.gz.sha256").write_text(f"{DIGEST}  x.tar.gz\n")
    assert DIGEST in build.download_block(c, with_hash=True)
    assert DIGEST not in build.download_block(c)


def test_home_page_shows_the_hash_of_the_real_download():
    """On the built site the hash on the page is the one in the shipped checksum file."""
    import re
    import tomllib
    c = tomllib.loads(build.CONTENT.read_text(encoding="utf-8"))
    sha_file = build.SITE / c["links"]["sha256"]
    if not sha_file.is_file():  # the release files are not in git; a plain checkout lacks them
        pytest.skip("release files are not in site/download/")
    build.use_shots(c, build.load_shots())
    page = build.render(c)
    assert len(re.findall(r"<code>[0-9a-f]{64}</code>", page)) == 1
    assert build.sha256_of(c) in page
