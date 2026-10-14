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

"""website/build.py: /docs/ and llms-full.txt, built from the app's Help pages
(maintainer tooling, not part of the package or the download).

Nothing here writes into website/site/: the pages are rendered to strings.
"""

from __future__ import annotations

import importlib.util
import io
import re
import tarfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("website_build", ROOT / "website" / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

HELP = ROOT / "src" / "hermitcrm" / "help"


def content() -> dict:
    return tomllib.loads(build.CONTENT.read_text(encoding="utf-8"))


def tree_docs() -> dict:
    return build.read_help(HELP, "0.7.0", date=None, source="working tree", path="src/hermitcrm/help/")


def make_tarball(tmp_path: Path, version: str, changes: dict[str, str] | None = None) -> Path:
    """A tarball shaped like scripts/release.sh's: one top folder, the package
    under src/, every file stamped with the commit time."""
    out = tmp_path / f"hermitcrm-{version}.tar.gz"
    stamp = 1_791_000_000  # 2026-10-03 UTC
    files = {f"src/hermitcrm/help/{f.name}": f.read_bytes()
             for f in sorted(HELP.iterdir()) if f.suffix in (".md", ".py")}
    files["src/hermitcrm/__init__.py"] = f'"""Hermit CRM."""\n\n__version__ = "{version}"\n'.encode()
    files["README.md"] = b"# Hermit CRM\n"
    for name, text in (changes or {}).items():
        files[name] = text.encode()
    with tarfile.open(out, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(f"hermitcrm-{version}/{name}")
            info.size, info.mtime = len(data), stamp
            tar.addfile(info, io.BytesIO(data))
    return out


def test_help_links_become_anchors_and_app_links_plain_text():
    names = {"settings", "adjust", "cli"}
    text = ("See [Settings](/help/settings#bcc-capture), [Make it yours](/help/adjust), "
            "[all topics](/help), [Getting started](/welcome), [Feedback](/help/feedback) "
            "and [the site](https://example.com/x).")
    assert build.docs_links(text, names, "") == (
        "See [Settings](#settings-bcc-capture), [Make it yours](#adjust), "
        "[all topics](#contents), Getting started, Feedback "
        "and [the site](https://example.com/x).")
    assert build.docs_links("[CLI](/help/cli)", names, "https://example.org/docs/") == \
        "[CLI](https://example.org/docs/#cli)"


def test_demote_leaves_code_fences_alone():
    text = "# Title\n\n## Part\n\n```toml\n# a comment\n```\n"
    assert build.demote(text) == "## Title\n\n### Part\n\n```toml\n# a comment\n```"


def test_first_paragraph_joins_its_lines():
    assert build.first_paragraph("# T\n\nOne line\nand the next.\n\nLater.\n") == "One line and the next."


def test_docs_page_has_every_topic_and_no_links_into_the_app():
    c, docs = content(), tree_docs()
    hub, _ = build.load_compare()
    page = build.render_docs(c, hub, docs)
    topics = [t for t, *_ in docs["topics"]]
    assert "index" not in topics and "feedback" not in topics
    assert "ai-agents" in topics and "settings" in topics and "adjust-fields" in topics
    ids = re.findall(r' id="([^"]+)"', page)
    assert len(ids) == len(set(ids)), "an id is used twice"
    for t in topics:
        assert f'<h2 id="{t}">' in page
    missing = set(re.findall(r'href="#([^"]+)"', page)) - set(ids)
    assert not missing, f"links to anchors that do not exist: {sorted(missing)}"
    assert not re.findall(r'href="/(?!/)', page), "a link into the app was left on the page"
    assert page.count("<h1") == 1
    assert "For version 0.7.0" in page
    assert '"@type": "TechArticle"' in page and '"softwareHelp"' in page


def test_docs_come_from_the_release_tarball(tmp_path):
    tarball = make_tarball(tmp_path, "9.9.0", {
        "src/hermitcrm/help/pipeline.md": "# Pipeline as released\n\nThe released text.\n"})
    docs = build.docs_from_tarball(tarball)
    assert docs["source"] == "download" and docs["version"] == "9.9.0"
    assert docs["date"].isoformat() == "2026-10-03"
    titles = dict((t, title) for t, title, *_ in docs["topics"])
    assert titles["pipeline"] == "Pipeline as released"
    c = content()
    assert "For version 9.9.0" in build.render_docs(c, build.load_compare()[0], docs)
    full = build.llms_full_txt(c, docs)
    assert "## Pipeline as released" in full and "9.9.0, 2026-10-03" in full


def test_check_refuses_docs_that_are_not_the_released_ones(tmp_path):
    c = content()
    c["release"]["version"] = "9.9.0"

    def docs_problems(docs):
        problems, _ = build.check(c, docs=docs)
        return [p for p in problems if p.startswith("docs:")]

    assert docs_problems(build.docs_from_tarball(make_tarball(tmp_path, "9.9.0"))) == []
    unreleased = docs_problems(tree_docs())
    assert any("not from the download" in p for p in unreleased)
    assert any("[release].version is 9.9.0" in p for p in unreleased)
    old = docs_problems(build.docs_from_tarball(make_tarball(tmp_path, "9.8.0")))
    assert old == ["docs: hermitcrm-9.8.0.tar.gz is version 9.8.0, [release].version is 9.9.0"]


def test_llms_txt_lists_every_topic_and_llms_full_has_them_all():
    c, docs = content(), tree_docs()
    hub, pages = build.load_compare()
    site = c["page"]["site_url"].rstrip("/")
    llms = build.llms_txt(c, hub, pages, build.load_about(), docs)
    full = build.llms_full_txt(c, docs)
    assert llms.index("## Docs") < llms.index("## Pages")
    assert f"({site}/llms-full.txt)" in llms
    for t, title, summary, _ in docs["topics"]:
        assert f"- [{title}]({site}/docs/#{t}): " in llms
        assert f"\n## {title}\n" in full
    assert full.startswith("# Hermit CRM docs\n")
    assert "](/" not in full, "a site-relative link was left in llms-full.txt"
