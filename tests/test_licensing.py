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

"""Licensing: the files Apache 2.0 asks for, and the header on every source file.

A relicence is easy to do and easy to half-undo -- a new module lands without a
header, or LICENSE gets "tidied" and stops matching what licence scanners look
for. These are the cheap guards against that.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# sha256 of the canonical text at https://www.apache.org/licenses/LICENSE-2.0.txt.
# Apache 2.0 must be included verbatim; GitHub and licence scanners match on the
# text, so a reflowed line is a real problem, not a cosmetic one.
APACHE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"

HEADER_MARKER = "Licensed under the Apache License, Version 2.0"


def tracked(*globs: str) -> list[Path]:
    out = subprocess.run(["git", "ls-files", *globs], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout.split()
    return [ROOT / p for p in out]


def test_license_is_apache_2_0_verbatim():
    digest = hashlib.sha256((ROOT / "LICENSE").read_bytes()).hexdigest()
    assert digest == APACHE_SHA256, "LICENSE is not the canonical Apache 2.0 text"


def test_notice_names_the_copyright_holder_and_the_trademark():
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert notice.startswith("Hermit CRM\nCopyright 2026 Gijs Bos")
    assert "bundles no third-party source code" in notice
    assert "not licensed under the Apache License" in notice


def test_pyproject_declares_apache_and_ships_the_licence_files():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license = "Apache-2.0"' in text
    assert 'license-files = ["LICENSE", "NOTICE"]' in text
    # PEP 639: an SPDX expression and a License :: classifier cannot both be set.
    assert "License :: OSI Approved" not in text
    assert "MIT" not in text


def test_every_source_file_carries_the_header():
    files = tracked("src/hermitcrm/*.py", "src/hermitcrm/**/*.py", "tests/*.py",
                    "website/build.py", "scripts/*.sh", "src/hermitcrm/static/*.js")
    assert len(files) > 50, "the file list looks wrong, not the headers"
    missing = [p.relative_to(ROOT).as_posix() for p in files
               if HEADER_MARKER not in p.read_text(encoding="utf-8")]
    assert not missing, f"no Apache header: {missing}"


def test_a_header_never_displaces_a_shebang():
    for path in tracked("src/hermitcrm/cli.py", "website/build.py", "scripts/*.sh"):
        assert path.read_text(encoding="utf-8").startswith("#!"), path


def test_the_risk_documents_are_there_and_link_up():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Alpha software" in readme
    assert "no warranty of" in readme
    assert "(DISCLAIMER.md)" in readme and "(LICENSE)" in readme
    assert "(SECURITY.md)" in readme
    assert "MIT licensed" not in readme

    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "@" in security, "SECURITY.md has no reporting address"
    assert "no guarantee of a fix" in security

    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "git commit -s" in contributing
    assert "developercertificate.org" in contributing
