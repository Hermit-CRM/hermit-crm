#!/usr/bin/env python3
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

"""Build the Hermit CRM website from content.toml.

    python3 build.py            build site/index.html, site/compare/, site/about/ and site/app-tokens.css once
    python3 build.py --watch    rebuild whenever content.toml, about.toml, style.css or the app's tokens change
    python3 build.py --share    also render site/img/og.png and .github/social-preview.png (needs Playwright)
    python3 build.py --release  build, then fail if any [TBC], "#" link or brief problem is left,
                                or if /docs/ was not built from the release's own download

Only the Python standard library is needed (3.11 or newer) for the page.
All words come from content.toml, compare/*.toml (the comparison pages) and
about.toml (the About page); the look is in site/style.css. Colours and
fonts shared with the app come from src/hermitcrm/static/tokens.css, copied into
site/app-tokens.css on every build. The build fails if the site uses a token
that neither file defines, so the site cannot drift from the app unnoticed.

/docs/ and llms-full.txt are the app's Help pages (src/hermitcrm/help/*.md),
taken from the download named in [links].download so they match the released
version; see README, "Docs".
"""
from __future__ import annotations

import html
import importlib.util
import json
import re
import struct
import sys
import tarfile
import tempfile
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content.toml"
SITE = ROOT / "site"
OUT = SITE / "index.html"
STYLE = SITE / "style.css"
TOKENS = ROOT.parent / "src" / "hermitcrm" / "static" / "tokens.css"
APP_TOKENS = SITE / "app-tokens.css"
COMPARE = ROOT / "compare"
FEATURES = ROOT / "features"
ABOUT = ROOT / "about.toml"
LLMS = SITE / "llms.txt"
LLMS_FULL = SITE / "llms-full.txt"
HELP = ROOT.parent / "src" / "hermitcrm" / "help"

# Tokens from tokens.css that mean the same on the site as in the app. They are
# defined for the whole page; the rest (the app's palette) only inside the
# drawn app, so names like --muted cannot clash with the site's own.
SHARED = ("--brand", "--ink", "--sans", "--mono", "--serif")

BANNED = ["revolutionary", "supercharge", "seamless", "unlock", "powerful",
          "effortless", "game-changing", "next-generation", "ai-powered"]

# The Hermit CRM mark, cropped to the frame (from hermitcrm-mark.svg). The ink
# parts follow the text colour, so the mark works on light and dark paper.
MARK = ('<svg viewBox="4.5 10.5 55 43" aria-hidden="true" focusable="false">'
        '<rect x="7" y="13" width="50" height="38" rx="7" fill="none" stroke="currentColor" stroke-width="5"/>'
        '<circle cx="24" cy="27" r="5.5" fill="#1E8A60"/>'
        '<path d="M16 43 a8 8 0 0 1 16 0 z" fill="#1E8A60"/>'
        '<rect x="38" y="25" width="12" height="4" rx="2" fill="currentColor"/>'
        '<rect x="38" y="34" width="8" height="4" rx="2" fill="currentColor"/></svg>')


# Meta tags every page carries. max-snippet:-1 lets search and AI answer engines
# quote as much of the text as they need; the share image is og.png.
def common_meta(c: dict) -> str:
    site = c["page"]["site_url"].rstrip("/")
    lines = ['<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">',
             f'<meta property="og:site_name" content="{attr(c["header"]["name"])}">',
             '<meta property="og:locale" content="en_GB">']
    if site:
        # For AI tools and crawlers: where the manual is, as a page and as text.
        lines += [f'<link rel="help" href="{attr(site)}/docs/">',
                  f'<link rel="alternate" type="text/plain" title="Hermit CRM docs as text" '
                  f'href="{attr(site)}/llms-full.txt">']
        lines += ['<meta property="og:image:width" content="1200">',
                  '<meta property="og:image:height" content="630">',
                  f'<meta property="og:image:alt" content="{attr(c["share"]["image_alt"])}">']
    return "\n".join(lines) + "\n"


class BuildError(Exception):
    """Something the page cannot be built with; the message says what."""


# ── Tokens shared with the app ───────────────────────────────────────
def declarations(block: str) -> list[tuple[str, str]]:
    return [(m.group(1), " ".join(m.group(2).split()))
            for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", block)]


def uncomment(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def app_tokens_css(tokens: str) -> str:
    """site/app-tokens.css from the app's tokens.css: brand and type for the whole
    page, the app palette scoped to the drawn app (.mock-box)."""
    css = uncomment(tokens)
    main = re.search(r"^:root \{(.*?)^\}", css, re.S | re.M)
    fallback = re.search(r"@supports not \(color: light-dark\(#000, #fff\)\) \{\s*:root \{(.*?)\}", css, re.S)
    themes = re.findall(r'^\[data-theme="(\w+)"\]\s*\{\s*color-scheme:\s*([^;]+);\s*\}', css, re.M)
    if not main or not fallback or not themes:
        raise BuildError(f"{TOKENS} no longer has the :root block, the @supports "
                         "fallback and the [data-theme] rules this build reads")
    decls = declarations(main.group(1))
    shared = [d for d in decls if d[0] in SHARED]
    missing = set(SHARED) - {n for n, _ in shared}
    if missing:
        raise BuildError(f"tokens.css no longer defines {', '.join(sorted(missing))}")
    palette = [d for d in decls if d[0] not in SHARED]
    scheme = re.search(r"color-scheme:\s*([^;]+);", main.group(1)).group(1)
    line = lambda n, v: f"  {n}: {v};"  # noqa: E731
    out = ["/* GENERATED by website/build.py from src/hermitcrm/static/tokens.css.",
           "   Do not edit: change tokens.css (the app's defaults) and rebuild. */", "",
           "/* brand and type, the same on the site as in the app */",
           ":root {", *(line(n, v) for n, v in shared), "}", "",
           "/* the app's palette, only inside the drawn app */",
           ".mock-box {", f"  color-scheme: {scheme};", *(line(n, v) for n, v in palette), "}"]
    out += [f'.mock-box[data-theme="{name}"] {{ color-scheme: {value}; }}' for name, value in themes]
    out += ["", "@supports not (color: light-dark(#000, #fff)) {", "  .mock-box {",
            *("  " + line(n, v) for n, v in declarations(fallback.group(1))), "  }",
            "  .mock-box[data-theme] { color-scheme: light; }", "}", ""]
    return "\n".join(out)


def drift(site_css: str, app_css: str) -> list[str]:
    """Tokens the site uses but nobody defines. Inside the drawn app (.mock rules)
    a token must come from the app, not from the site's look-alike of the same name."""
    # The app's names are the ones in its main blocks; the @supports fallback
    # only repeats them for old browsers and must not keep a renamed one alive.
    site_css, app_css = uncomment(site_css), uncomment(app_css).split("@supports", 1)[0]
    defined = lambda css: {n for n, _ in declarations(css)}  # noqa: E731
    app_defined, site_defined = defined(app_css), defined(site_css)
    problems = [f"site/style.css uses {n}, which neither style.css nor tokens.css defines"
                for n in sorted(set(re.findall(r"var\((--[\w-]+)", site_css)) - app_defined - site_defined)]
    mock_rules = [body for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", site_css) if ".mock" in sel]
    mock_own = defined("".join(mock_rules))  # e.g. --u, the drawing's unit
    for n in sorted({n for body in mock_rules for n in re.findall(r"var\((--[\w-]+)", body)}
                    - app_defined - mock_own):
        problems.append(f"the drawn app uses {n}, which the app's tokens.css does not define")
    return problems


# ── Text helpers ─────────────────────────────────────────────────────
def flat(text: str) -> str:
    """Join a multi-line TOML string into one line."""
    return " ".join(text.split())


def typeset(text: str) -> str:
    """Typographic quotes in prose: ’ in don't and in plural possessives, “ ” and
    ‘ ’ around quoted words. Straight quotes stay in code, URLs and attributes."""
    text = re.sub(r"(?<=\w)'(?=\w)", "’", text)                    # don't, Hermit's
    text = re.sub(r"(?<=s)'(?=\s|[.,;:!?)]|$)", "’", text)         # vendors'
    text = re.sub(r'(^|[\s(\[])"(?=\S)', lambda m: m.group(1) + "“", text)
    text = text.replace('"', "”")
    text = re.sub(r"(^|[\s(\[])'(?=\S)", lambda m: m.group(1) + "‘", text)
    return text.replace("'", "’")


_TAGS = re.compile(r"(<pre\b.*?</pre>|<code\b.*?</code>|<[^>]+>)", re.S)


def typeset_html(markup: str) -> str:
    """typeset() on the text of finished HTML, leaving tags, <code> and <pre> alone.
    Used for the docs and the changelog, which the app's own converter renders."""
    def fix(part: str) -> str:
        if part.startswith("<"):
            return part
        plain_text = part.replace("&#x27;", "'").replace("&#39;", "'").replace("&quot;", '"')
        return typeset(plain_text)
    return "".join(fix(p) for p in _TAGS.split(markup))


def md(text: str) -> str:
    """Escape, then apply **bold**, `code` and [text](url), with typographic quotes."""
    out = html.escape(flat(text), quote=False)
    codes: list[str] = []

    def keep_code(m: re.Match) -> str:
        codes.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    out = re.sub(r"`([^`]+)`", keep_code, out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                 lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', out)
    out = "".join(p if p.startswith("<") else typeset(p) for p in re.split(r"(<[^>]+>)", out))
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], out)


def attr(text: str) -> str:
    return html.escape(flat(text), quote=True)


# ── Page parts ───────────────────────────────────────────────────────
def meta_line(c: dict) -> str:
    r = c["release"]
    return f'<p class="meta">Version {md(r["version"])} · {md(r["license"])}</p>'


def download_block(c: dict) -> str:
    return (f'<div class="download">\n'
            f'  <a class="btn" href="{attr(c["links"]["download"])}">{md(c["hero"]["download_button"])}</a>\n'
            f'  {meta_line(c)}\n</div>')


def mock() -> str:
    cols = [("Prospect", [("Acme BV", "NL · today", True), ("Globex GmbH", "DE · 3 days", False),
                          ("Initech SARL", "FR · 1 week", False)]),
            ("Engaged", [("Umbrella NV", "BE · 2 days", False), ("Hooli Ltd", "GB · 5 days", False)]),
            ("Discovery", [("Soylent AG", "CH · 4 days", False), ("Stark &amp; Co", "NL · 2 weeks", False)]),
            ("Offer", [("Wonka BV", "NL · 6 days", False)]),
            ("Won", [("Vandelay SA", "FR · 3 weeks", False)])]
    nav = ["Home", "Pipeline", "Calendar", "Companies", "Contacts", "Messages", "Extension",
           "Reports", "Settings", "Help"]  # same order as the app sidebar (templates/base.html)
    side = "".join(f'<div class="mock-nav{" on" if n == "Pipeline" else ""}">{n}</div>' for n in nav)
    board = "".join(
        f'<div class="mock-col"><div class="mock-h"><span>{h}</span><span>{len(cards)}</span></div>'
        + "".join(f'<div class="mock-card{" hi" if hi else ""}"><b>{n}</b><small>{m}</small></div>'
                  for n, m, hi in cards)
        + "</div>" for h, cards in cols)
    return (f'<div class="mock-box" data-theme="system" role="img" aria-label="Placeholder drawing of the pipeline board">'
            f'<div class="mock" aria-hidden="true">'
            f'<div class="mock-side"><div class="mock-brand">{MARK}<span>Hermit CRM</span></div>{side}</div>'
            f'<div class="mock-main"><div class="mock-top"><div class="mock-title">Pipeline</div>'
            f'<div class="mock-tag">Placeholder · real screenshot [TBC]</div></div>'
            f'<div class="mock-cols">{board}</div></div></div></div>')


def png_size(path: Path) -> tuple[int, int]:
    """Width and height of a PNG, from its header; (0, 0) when it is not one."""
    try:
        head = path.read_bytes()[:24]
    except OSError:
        return 0, 0
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return 0, 0
    return struct.unpack(">II", head[16:24])


def yours_section(c: dict) -> str:
    """Make it yours: the promise, three examples (what you type, what changes,
    a screenshot of the result) and the safety line."""
    y = c["yours"]
    items = []
    for e in y["examples"]:
        items.append(
            f'      <li class="example">\n'
            f'        <div class="example-text">\n'
            f'          <h3>{md(e["name"])}</h3>\n'
            f'          <p class="small-label">{md(y["prompt_label"])}</p>\n'
            f'          <p class="said">{md(e["prompt"])}</p>\n'
            f'          <p class="small-label">{md(y["change_label"])}</p>\n'
            f'          <p class="change">{md(e["change"])}</p>\n'
            f'        </div>\n'
            f'        {figure("", e["image"], e["alt"], e["address"])}\n'
            f'      </li>')
    examples = "\n".join(items)
    return f"""  <section class="yours wide" aria-labelledby="yours">
    <div class="narrow">
      <p class="label">{md(y["label"])}</p>
      <h2 class="big" id="yours">{md(y["heading"])}</h2>
      <p class="lead">{md(y["promise"])}</p>
    </div>
    <ol class="examples">
{examples}
    </ol>
    <p class="safety narrow">{md(y["safety"])}</p>
  </section>
"""


def site_nav(c: dict, root: str, here: str = "") -> str:
    """The top bar, the same on every page: Features, Docs, Compare, About, then
    GitHub (when the repository is public). `here` is the section the page is in,
    and its link is marked. Compare and About leave the bar on a phone; the footer
    has them."""
    h = c["header"]

    def link(section: str, label: str, more: bool = False) -> str:
        cur = ' aria-current="page"' if here == section else ""
        cls = ' class="nav-more"' if more else ""
        return f'<a href="{root}{section}/"{cls}{cur}>{md(label)}</a>'

    github = (f'<a href="{attr(c["links"]["github"])}">{md(h["github_label"])}</a>'
              if c["links"]["github"] else "")
    return ('<nav class="site-nav" aria-label="Site">'
            + link("features", h["features_label"]) + link("docs", h["docs_label"])
            + link("compare", h["compare_label"], True) + link("about", h["about_label"], True)
            + github + "</nav>")


def figure(root: str, image: str, alt: str, address: str) -> str:
    """A screenshot in its window frame. It opens full size when selected, which
    is how a phone shows the small print. The size is read from the PNG so the
    page does not jump while it loads."""
    w, h = png_size(SITE / "img" / image)
    size = f' width="{w}" height="{h}"' if w else ""
    return (f'<figure class="window">\n'
            f'          <div class="window-bar"><i></i><i></i><i></i><span>{md(address)}</span></div>\n'
            f'          <a class="zoom" href="{root}img/{attr(image)}"><img src="{root}img/{attr(image)}" '
            f'alt="{attr(alt)}"{size} loading="lazy"></a>\n'
            f'        </figure>')


def render(c: dict, ld: str = "") -> str:
    p, h, i, f = c["page"], c["hero"], c["install"], c["file"]
    description = flat(p["description"] or h["subline"])
    site_url = p["site_url"].rstrip("/")
    og = ""
    if site_url:
        og = (f'<link rel="canonical" href="{attr(site_url)}/">\n'
              f'<meta property="og:url" content="{attr(site_url)}/">\n'
              f'<meta property="og:image" content="{attr(site_url)}/img/og.png">\n')
    # An empty [links].github hides both GitHub links (header and footer), for
    # as long as the repository is private.
    github = (f'<a href="{attr(c["links"]["github"])}">{md(c["header"]["github_label"])}</a>'
              if c["links"]["github"] else "")
    nav = site_nav(c, "")

    steps = "\n".join(f"      <li><span>{md(s)}</span></li>" for s in i["steps"])
    # A row whose page exists links to it: features/<slug>/ (built from features/*.toml).
    def feature_name(x: dict) -> str:
        if not x.get("slug"):
            return md(x["name"])
        return f'<a href="features/{attr(x["slug"])}/">{md(x["name"])}</a>'

    features = "\n".join(f"      <dt>{feature_name(x)}</dt><dd>{md(x['text'])}</dd>"
                         for x in c["features"]["items"])
    all_features = (f'    <p class="all-features"><a href="features/">{md(c["features"]["all_label"])}</a></p>\n'
                    if c["features"].get("all_label") else "")
    principles = "\n".join(f"      <p><strong>{md(x['name'])}</strong> {md(x['text'])}</p>"
                           for x in c["principles"])
    faqs = "\n".join(
        f'      <details{" open" if q.get("open") else ""}><summary>{md(q["q"])}</summary>'
        f'<p>{md(q["a"])}</p></details>' for q in c["questions"]["items"])

    if f["screenshot"]:
        idea_figure = figure("", f["screenshot"], f["screenshot_alt"], f["address_bar"])
    else:
        idea_figure = (f'<figure class="window">\n'
                       f'        <div class="window-bar"><i></i><i></i><i></i><span>{md(f["address_bar"])}</span></div>\n'
                       f'        {mock()}\n      </figure>')
    file_body = html.escape(f["file_body"].strip("\n"))
    sha256 = f'<a href="{attr(c["links"]["sha256"])}">{md(h["sha256_label"])}</a>'
    footer_text = c["footer"]["text"]
    if not github:
        footer_text = footer_text.replace("{github} · ", "").replace(" · {github}", "")
    footer = (md(footer_text.replace("{github}", "\x01").replace("{sha256}", "\x02"))
              .replace("\x01", github).replace("\x02", sha256))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{attr(p["title"])}</title>
<meta name="description" content="{attr(description)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{attr(p["title"])}">
<meta property="og:description" content="{attr(description)}">
{og}{common_meta(c)}<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#F5F1E8" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#1C1B18" media="(prefers-color-scheme: dark)">
<link rel="icon" href="img/favicon.svg" type="image/svg+xml">
<link rel="icon" href="img/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="img/apple-touch-icon.png">
<link rel="stylesheet" href="app-tokens.css">
<link rel="stylesheet" href="style.css">
{ld}</head>
<body>
<!-- Built from content.toml by build.py. Edit the text there, not here. -->
<a class="skip" href="#main">Skip to content</a>

<header class="site-header wide">
  <a class="brand" href="./" aria-label="{attr(c["header"]["name"])} home">{MARK}<span>{md(c["header"]["name"])}</span></a>
  {nav}
</header>

<main id="main">
  <section class="hero col">
    <h1>{md(h["h1"])}</h1>
    <p class="subline">{md(h["subline"])}</p>
    {download_block(c)}

    <div class="install">
      <h2 class="label">{md(i["label"])}</h2>
      <ol class="steps">
{steps}
      </ol>
      <div class="card indent">
        <p class="message" id="install-message">{md(i["message"])}</p>
        <button class="copy" type="button" hidden data-copy="{attr(i["message"])}" data-done="{attr(i["copied_label"])}"
                data-failed="{attr(i["copy_failed_label"])}"
                aria-label="Copy the install message"><span aria-live="polite">{md(i["copy_button"])}</span></button>
      </div>
    </div>
  </section>

  <hr class="rule">

  <section class="idea wide" aria-labelledby="idea">
    <div class="narrow">
      <p class="label">{md(f["label"])}</p>
      <h2 class="big" id="idea">{md(f["heading"])}</h2>
    </div>
    <div class="idea-grid">
      {idea_figure}
      <div class="file">
        <p>{md(f["file_caption"])}</p>
        <pre><span class="path">{html.escape(f["file_path"])}</span>
{file_body}</pre>
      </div>
    </div>
  </section>

  <hr class="rule blank">

{yours_section(c)}
  <hr class="rule blank">

  <section class="features col" aria-labelledby="features">
    <h2 class="label" id="features">{md(c["features"]["label"])}</h2>
    <dl>
{features}
    </dl>
{all_features}    <div class="principles">
{principles}
    </div>
  </section>

  <hr class="rule blank">

  <section class="questions col" aria-labelledby="questions">
    <h2 class="label" id="questions">{md(c["questions"]["label"])}</h2>
    <div>
{faqs}
    </div>
  </section>

  <section class="closing col" aria-label="{attr(c["closing"]["label"])}">
    <p class="lead">{md(c["closing"]["text"])}</p>
    {download_block(c)}
  </section>
</main>

<footer class="site-footer col">{footer}</footer>

<script>
// Copy button: shown only when scripts run. "Copied" only when the copy
// worked; otherwise the message is selected and the button says how to copy.
document.querySelectorAll("[data-copy]").forEach(function (btn) {{
  var label = btn.querySelector("span"), idle = label.textContent, timer;
  var message = document.getElementById("install-message");
  btn.hidden = false;
  function show(text, ms) {{
    label.textContent = text;
    clearTimeout(timer);
    timer = setTimeout(function () {{ label.textContent = idle; }}, ms);
  }}
  function done() {{ show(btn.dataset.done, 2000); }}
  function failed() {{
    var range = document.createRange(), sel = window.getSelection();
    range.selectNodeContents(message); sel.removeAllRanges(); sel.addRange(range);
    show(btn.dataset.failed, 4000);
  }}
  function fallback(text) {{
    var t = document.createElement("textarea"), ok = false;
    t.value = text; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select();
    try {{ ok = document.execCommand("copy"); }} catch (e) {{}}
    document.body.removeChild(t);
    ok ? done() : failed();
  }}
  btn.addEventListener("click", function () {{
    var text = btn.dataset.copy;
    if (navigator.clipboard && window.isSecureContext) {{
      navigator.clipboard.writeText(text).then(done, function () {{ fallback(text); }});
    }} else {{ fallback(text); }}
  }});
}});
// Printing: open every answer, then put them back as they were.
var shut = [];
addEventListener("beforeprint", function () {{
  shut = [].filter.call(document.querySelectorAll("details"), function (d) {{ return !d.open; }});
  shut.forEach(function (d) {{ d.open = true; }});
}});
addEventListener("afterprint", function () {{ shut.forEach(function (d) {{ d.open = false; }}); }});
</script>
</body>
</html>
"""


# ── Structured data (JSON-LD) ────────────────────────────────────────
# Search engines and AI answer engines read these to know what the page is
# about: the product, the page's place on the site and its questions.
def plain(text: str) -> str:
    """Text without the **bold**, `code` and [link](url) marks, for JSON-LD and llms.txt."""
    out = re.sub(r"\[([^\]]+)\]\([^)\s]+\)", r"\1", flat(text))
    return out.replace("**", "").replace("`", "")


def jsonld(*nodes: dict) -> str:
    data = json.dumps({"@context": "https://schema.org", "@graph": list(nodes)},
                      ensure_ascii=False, indent=1)
    data = data.replace("</", "<\\/")  # a "</script>" inside a string must not end the block
    return f'<script type="application/ld+json">\n{data}\n</script>\n'


def software(c: dict, hub: dict) -> dict:
    site = c["page"]["site_url"].rstrip("/")
    return {"@type": "SoftwareApplication", "@id": f"{site}/#software", "name": "Hermit CRM",
            "url": f"{site}/", "description": plain(hub["hermit"]["about"]),
            "applicationCategory": "BusinessApplication", "operatingSystem": "macOS, Linux",
            "softwareVersion": c["release"]["version"],
            "license": "https://www.apache.org/licenses/LICENSE-2.0",
            "isAccessibleForFree": True,
            "softwareHelp": {"@type": "CreativeWork", "url": f"{site}/docs/"},
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"}}


def website(c: dict) -> dict:
    site = c["page"]["site_url"].rstrip("/")
    return {"@type": "WebSite", "@id": f"{site}/#website", "url": f"{site}/",
            "name": c["header"]["name"], "inLanguage": "en"}


def breadcrumbs(url: str, trail: list[tuple[str, str]]) -> dict:
    return {"@type": "BreadcrumbList", "@id": f"{url}#breadcrumb",
            "itemListElement": [{"@type": "ListItem", "position": n, "name": name, "item": link}
                                for n, (name, link) in enumerate(trail, 1)]}


# ── Comparison pages (/compare/ and /compare/<name>/) ────────────────
def load_compare() -> tuple[dict, list[dict]]:
    """compare/index.toml and one dict per other CRM, in their `order`."""
    hub = tomllib.loads((COMPARE / "index.toml").read_text(encoding="utf-8"))
    keys = [r["key"] for r in hub["rows"]]
    pages = []
    for f in sorted(COMPARE.glob("*.toml")):
        if f.name == "index.toml":
            continue
        p = tomllib.loads(f.read_text(encoding="utf-8"))
        p["slug"] = f.stem
        cells = p.get("cells", {})
        missing, extra = [k for k in keys if k not in cells], [k for k in cells if k not in keys]
        if missing or extra:
            raise BuildError(f"compare/{f.name}: [cells] must have exactly the keys of the rows "
                             f"in index.toml; missing {missing or 'none'}, unknown {extra or 'none'}")
        for need in ("name", "checked", "title", "description", "short_answer", "sources"):
            if need not in p:
                raise BuildError(f"compare/{f.name} has no {need}")
        pages.append(p)
    pages.sort(key=lambda p: (p.get("order", 99), p["name"].lower()))
    return hub, pages


def long_date(d) -> str:
    return f"{d.day} {d:%B %Y}"


def page_head(c: dict, hub: dict, *, title: str, description: str, path: str, root: str, ld: str,
              modified=None) -> str:
    """<head> of a page below the home page. `root` leads back to site/ ("../../")."""
    site = c["page"]["site_url"].rstrip("/")
    # The link of the section the page is in is marked as the current page.
    section = path.strip("/").split("/")[0]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{attr(title)}</title>
<meta name="description" content="{attr(description)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{attr(title)}">
<meta property="og:description" content="{attr(description)}">
<link rel="canonical" href="{attr(site + path)}">
<meta property="og:url" content="{attr(site + path)}">
<meta property="og:image" content="{attr(site)}/img/og.png">
{common_meta(c)}{f'<meta property="article:modified_time" content="{modified.isoformat()}">{chr(10)}' if modified else ""}<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#F5F1E8" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#1C1B18" media="(prefers-color-scheme: dark)">
<link rel="icon" href="{root}img/favicon.svg" type="image/svg+xml">
<link rel="icon" href="{root}img/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="{root}img/apple-touch-icon.png">
<link rel="stylesheet" href="{root}app-tokens.css">
<link rel="stylesheet" href="{root}style.css">
{ld}</head>
<body>
<!-- Built by build.py from compare/*.toml, about.toml and the app's Help pages. Edit the text there, not here. -->
<a class="skip" href="#main">Skip to content</a>

<header class="site-header wide">
  <a class="brand" href="{root}" aria-label="{attr(c["header"]["name"])} home">{MARK}<span>{md(c["header"]["name"])}</span></a>
  {site_nav(c, root, section)}
</header>
"""


def page_foot(hub: dict, compare_link: str, about_link: str, docs_link: str, stats_link: str,
              notice: bool = True, changelog_link: str = "../changelog/") -> str:
    """Footer of a page below the home page. The prices-and-trademarks notice is
    for the comparison pages; the About page leaves it out."""
    # The features pages sit beside the docs: ../docs/ -> ../features/, and from the docs page itself ../features/.
    features_link = "../features/" if docs_link == "./" else docs_link[:-len("docs/")] + "features/"
    text = (hub["footer"]["text"].replace("{compare}", compare_link)
            .replace("{about}", about_link).replace("{docs}", docs_link).replace("{stats}", stats_link)
            .replace("{changelog}", changelog_link).replace("{features}", features_link))
    return ('<footer class="site-footer col">\n'
            + (f'  <p class="notice">{md(hub["notice"]["text"])}</p>\n' if notice else "")
            + f'  <p>{md(text)}</p>\n</footer>\n</body>\n</html>\n')


def crumbs(hub: dict, root: str, here: str, compare_link: str | None) -> str:
    lab = hub["labels"]
    items = [f'<li><a href="{root}">{md(lab["breadcrumb_home"])}</a></li>']
    if compare_link:
        items.append(f'<li><a href="{compare_link}">{md(lab["breadcrumb_compare"])}</a></li>')
    items.append(f'<li aria-current="page">{html.escape(here)}</li>')
    return f'<nav class="crumbs" aria-label="Breadcrumb"><ol>{"".join(items)}</ol></nav>'


def features_crumbs(hub: dict, fhub: dict, root: str, here: str, features_link: str | None) -> str:
    """Hermit CRM / Features / <page>; on the overview itself the last crumb is Features."""
    items = [f'<li><a href="{root}">{md(hub["labels"]["breadcrumb_home"])}</a></li>']
    if features_link:
        items.append(f'<li><a href="{features_link}">{md(fhub["labels"]["breadcrumb_features"])}</a></li>')
    items.append(f'<li aria-current="page">{html.escape(here)}</li>')
    return f'<nav class="crumbs" aria-label="Breadcrumb"><ol>{"".join(items)}</ol></nav>'


def about_block(hub: dict, root: str) -> str:
    lab = hub["labels"]
    return (f'  <section class="about col" aria-label="About Hermit CRM">\n'
            f'    <p>{md(hub["hermit"]["about"])}</p>\n'
            f'    <div class="download"><a class="btn" href="{root}">{md(lab["download"])}</a>'
            f'<p class="meta">{md(lab["download_note"])}</p></div>\n  </section>\n')


def render_compare(c: dict, hub: dict, p: dict, pages: list[dict]) -> str:
    site, lab, name = c["page"]["site_url"].rstrip("/"), hub["labels"], p["name"]
    path, root = f"/compare/{p['slug']}/", "../../"
    url, h1 = site + path, f"Hermit CRM vs {name}"
    sub = lambda s: s.replace("{name}", name)  # noqa: E731
    checked = p["checked"]

    head_row = (f'<tr><td></td><th scope="col">Hermit CRM</th>'
                f'<th scope="col">{html.escape(name)}</th></tr>')
    rows = "\n".join(
        f'        <tr><th scope="row">{md(r["label"])}</th>'
        f'<td data-label="Hermit CRM">{md(r["hermit"])}</td>'
        f'<td data-label="{attr(name)}">{md(p["cells"][r["key"]])}</td></tr>'
        for r in hub["rows"])
    bullets = lambda items: "\n".join(f"      <li>{md(x)}</li>" for x in items)  # noqa: E731
    steps = "\n".join(f"      <li><span>{md(s)}</span></li>" for s in p.get("switch", []))
    faqs = "\n".join(f'    <h3>{md(q["q"])}</h3>\n    <p>{md(q["a"])}</p>' for q in p.get("faq", []))
    sources = "\n".join(f'      <li><a href="{attr(s["url"])}">{md(s["label"])}</a></li>'
                        for s in p["sources"])
    others = "\n".join(f'      <li><a href="../{o["slug"]}/">Hermit CRM vs {html.escape(o["name"])}</a></li>'
                       for o in pages if o is not p)

    ld = jsonld(
        {"@type": "WebPage", "@id": url, "url": url, "name": flat(p["title"]),
         "description": flat(p["description"]), "inLanguage": "en",
         "dateModified": checked.isoformat(), "isPartOf": {"@id": f"{site}/#website"},
         "about": [{"@id": f"{site}/#software"}, {"@type": "SoftwareApplication", "name": name}],
         "breadcrumb": {"@id": f"{url}#breadcrumb"}},
        breadcrumbs(url, [(lab["breadcrumb_home"], f"{site}/"),
                          (lab["breadcrumb_compare"], f"{site}/compare/"), (h1, url)]),
        {"@type": "FAQPage", "@id": f"{url}#questions",
         "mainEntity": [{"@type": "Question", "name": plain(q["q"]),
                         "acceptedAnswer": {"@type": "Answer", "text": plain(q["a"])}}
                        for q in p.get("faq", [])]},
        software(c, hub), website(c))

    section = lambda key, body, cls="": (  # noqa: E731
        f'  <section class="part col{cls}" aria-labelledby="{key}">\n'
        f'    <h2 class="label" id="{key}">{md(sub(lab[key]))}</h2>\n{body}\n  </section>\n')

    return (page_head(c, hub, title=p["title"], description=flat(p["description"]), path=path, root=root, ld=ld,
                      modified=checked)
            + f"""
<main id="main">
  <div class="page-top col">
    {crumbs(hub, root, h1, "../")}
    <h1 class="page-h1">{html.escape(h1)}</h1>
    <p class="checked">{md(lab["checked"])} <time datetime="{checked.isoformat()}">{long_date(checked)}</time>.</p>
  </div>

{section("short_answer", f'    <p class="lead">{md(p["short_answer"])}</p>')}
  <section class="part col" aria-labelledby="table">
    <h2 class="label" id="table">{md(lab["table"])}</h2>
    <table class="versus">
      <caption>Hermit CRM and {html.escape(name)} side by side, checked {long_date(checked)}</caption>
      <thead>{head_row}</thead>
      <tbody>
{rows}
      </tbody>
    </table>
  </section>

{section("choose_other", f'    <ul class="points">{chr(10)}{bullets(p["choose_other"])}{chr(10)}    </ul>')}
{section("choose_hermit", f'    <ul class="points">{chr(10)}{bullets(p["choose_hermit"])}{chr(10)}    </ul>')}
{about_block(hub, root)}
{section("switch", f'    <ol class="steps">{chr(10)}{steps}{chr(10)}    </ol>') if steps else ""}
{section("questions", faqs, " faq") if faqs else ""}
{section("sources", f'    <ul class="sources">{chr(10)}{sources}{chr(10)}    </ul>')}
{section("others", f'    <ul class="others">{chr(10)}{others}{chr(10)}    </ul>')}
</main>

""" + page_foot(hub, "../", "../../about/", "../../docs/", "../../stats/",
                          changelog_link="../../changelog/"))


def render_hub(c: dict, hub: dict, pages: list[dict]) -> str:
    site, lab, pg = c["page"]["site_url"].rstrip("/"), hub["labels"], hub["page"]
    path, root = "/compare/", "../"
    url = site + path
    checked = min(p["checked"] for p in pages)
    her = hub["hermit"]
    cells = {r["key"]: r["hermit"] for r in hub["rows"]}
    cols = [pg["col_crm"], pg["col_best_for"], pg["col_price"], pg["col_data"], pg["col_code"]]

    def row(name_html: str, name: str, best: str, price: str, data: str, code: str) -> str:
        tds = "".join(f'<td data-label="{attr(col)}">{md(v)}</td>'
                      for col, v in zip(cols[1:], (best, price, data, code)))
        return f'        <tr><th scope="row">{name_html}</th>{tds}</tr>'

    rows = [row(html.escape(her["name"]), her["name"], her["best_for"], her["price"],
                cells["data"], cells["code"])]
    rows += [row(f'<a href="{p["slug"]}/">{html.escape(p["name"])}</a>', p["name"], p["best_for"],
                 p["price"], p["cells"]["data"], p["cells"]["code"]) for p in pages]
    thead = "".join(f'<th scope="col">{md(x)}</th>' for x in cols)
    cards = "\n".join(
        f'    <li><h2><a href="{p["slug"]}/">Hermit CRM vs {html.escape(p["name"])}</a></h2>'
        f'<p>{md(p["short_answer"])}</p></li>' for p in pages)

    ld = jsonld(
        {"@type": "CollectionPage", "@id": url, "url": url, "name": flat(pg["title"]),
         "description": flat(pg["description"]), "inLanguage": "en",
         "dateModified": max(p["checked"] for p in pages).isoformat(),
         "isPartOf": {"@id": f"{site}/#website"}, "about": {"@id": f"{site}/#software"},
         "breadcrumb": {"@id": f"{url}#breadcrumb"},
         "mainEntity": {"@type": "ItemList", "itemListElement": [
             {"@type": "ListItem", "position": n, "url": f"{url}{p['slug']}/",
              "name": f"Hermit CRM vs {p['name']}"} for n, p in enumerate(pages, 1)]}},
        breadcrumbs(url, [(lab["breadcrumb_home"], f"{site}/"), (lab["breadcrumb_compare"], url)]),
        software(c, hub), website(c))

    return (page_head(c, hub, title=pg["title"], description=flat(pg["description"]), path=path, root=root, ld=ld)
            + f"""
<main id="main">
  <div class="page-top col">
    {crumbs(hub, root, lab["breadcrumb_compare"], None)}
    <h1 class="page-h1">{md(pg["h1"])}</h1>
    <p class="lead">{md(pg["intro"])}</p>
    <p class="checked">{md(lab["checked"])} <time datetime="{checked.isoformat()}">{long_date(checked)}</time>.</p>
  </div>

  <section class="part wide">
    <table class="versus overview">
      <caption>{md(pg["table_caption"])}</caption>
      <thead><tr>{thead}</tr></thead>
      <tbody>
{chr(10).join(rows)}
      </tbody>
    </table>
  </section>

  <section class="part col">
    <ul class="cards">
{cards}
    </ul>
  </section>

{about_block(hub, root)}
</main>

""" + page_foot(hub, "./", "../about/", "../docs/", "../stats/"))


# ── About page (/about/) ─────────────────────────────────────────────
def load_about() -> dict:
    """about.toml, with the story's entries checked: a paragraph or a quote with its source."""
    a = tomllib.loads(ABOUT.read_text(encoding="utf-8"))
    for need in ("page", "author", "story"):
        if need not in a:
            raise BuildError(f"about.toml has no [{need}]")
    for n, item in enumerate(a["story"], 1):
        if not ("text" in item or ("quote" in item and "by" in item)):
            raise BuildError(f"about.toml: story entry {n} needs `text`, or `quote` and `by`")
    return a


def render_about(c: dict, hub: dict, a: dict) -> str:
    site, lab, pg, au = c["page"]["site_url"].rstrip("/"), hub["labels"], a["page"], a["author"]
    path, root = "/about/", "../"
    url, published = site + path, pg["published"]

    def block(item: dict) -> str:
        if "text" in item:
            return f'    <p>{md(item["text"])}</p>'
        return (f'    <figure class="pull">\n      <blockquote><p>{md(item["quote"])}</p></blockquote>\n'
                f'      <figcaption>{md(item["by"])}</figcaption>\n    </figure>')

    story = "\n".join(block(item) for item in a["story"])
    ld = jsonld(
        {"@type": "AboutPage", "@id": url, "url": url, "name": flat(pg["title"]),
         "description": flat(pg["description"]), "inLanguage": "en",
         "datePublished": published.isoformat(), "dateModified": published.isoformat(),
         "isPartOf": {"@id": f"{site}/#website"}, "about": {"@id": f"{site}/#software"},
         "author": {"@type": "Person", "name": au["name"], "url": au["url"]},
         "breadcrumb": {"@id": f"{url}#breadcrumb"}},
        breadcrumbs(url, [(lab["breadcrumb_home"], f"{site}/"), (pg["h1"], url)]),
        software(c, hub), website(c))

    return (page_head(c, hub, title=pg["title"], description=flat(pg["description"]), path=path, root=root, ld=ld,
                      modified=published)
            + f"""
<main id="main">
  <div class="page-top col">
    {crumbs(hub, root, pg["h1"], None)}
    <h1 class="page-h1">{md(pg["h1"])}</h1>
    <p class="checked">{md(au["label"])} <a href="{attr(au["url"])}">{md(au["name"])}</a>, <time datetime="{published.isoformat()}">{long_date(published)}</time>.</p>
  </div>

  <section class="story col" aria-label="{attr(pg["h1"])}">
{story}
  </section>

  <section class="about col" aria-label="Download Hermit CRM">
    <div class="download"><a class="btn" href="{root}">{md(lab["download"])}</a><p class="meta">{md(lab["download_note"])}</p></div>
  </section>
</main>

""" + page_foot(hub, "../compare/", "./", "../docs/", "../stats/", notice=False))


# ── Feature pages (/features/ and /features/<name>/) ─────────────────
# One page for each link in the app's left navigation: what it shows, what you
# can do on it, and real screenshots. Words in features/*.toml, in the order of
# the app's sidebar (`order`).
def load_features() -> tuple[dict, list[dict]]:
    """features/index.toml and one dict per page, in their `order`."""
    fhub = tomllib.loads((FEATURES / "index.toml").read_text(encoding="utf-8"))
    pages = []
    for f in sorted(FEATURES.glob("*.toml")):
        if f.name == "index.toml":
            continue
        p = tomllib.loads(f.read_text(encoding="utf-8"))
        p["slug"] = f.stem
        for need in ("order", "name", "nav", "title", "description", "summary", "intro", "docs", "sections"):
            if need not in p:
                raise BuildError(f"features/{f.name} has no {need}")
        for n, s in enumerate(p["sections"], 1):
            if "heading" not in s or not (s.get("text") or s.get("points")):
                raise BuildError(f"features/{f.name}: section {n} needs a heading and text or points")
            if "image" in s and not all(k in s for k in ("alt", "address")):
                raise BuildError(f"features/{f.name}: section {n} has an image but no alt or address")
        pages.append(p)
    pages.sort(key=lambda p: (p["order"], p["name"].lower()))
    return fhub, pages


def feature_thumb(p: dict) -> str:
    """The overview's picture of a page: img/thumbs/<slug>.png when there is one,
    otherwise the page's first screenshot."""
    if (SITE / "img" / "thumbs" / f"{p['slug']}.png").is_file():
        return f"thumbs/{p['slug']}.png"
    return next((s["image"] for s in p["sections"] if "image" in s), "")


def render_feature(c: dict, hub: dict, fhub: dict, p: dict, pages: list[dict]) -> str:
    site, lab, fl = c["page"]["site_url"].rstrip("/"), hub["labels"], fhub["labels"]
    path, root = f"/features/{p['slug']}/", "../../"
    url, name = site + path, p["name"]
    by_slug = {q["slug"]: q for q in pages}
    at = pages.index(p)

    sections = []
    for n, s in enumerate(p["sections"], 1):
        body = [f'        <h2 id="s{n}">{md(s["heading"])}</h2>']
        if s.get("text"):
            body.append(f'        <p>{md(s["text"])}</p>')
        if s.get("points"):
            body.append('        <ul class="points">\n'
                        + "\n".join(f"          <li>{md(x)}</li>" for x in s["points"]) + "\n        </ul>")
        shot = (f'\n      <div class="wide shot">\n        {figure(root, s["image"], s["alt"], s["address"])}\n      </div>'
                if s.get("image") else "")
        sections.append(f'    <section class="part feature" aria-labelledby="s{n}">\n'
                        f'      <div class="col">\n' + "\n".join(body) + f'\n      </div>{shot}\n    </section>\n')

    related = [by_slug[r] for r in p.get("related", []) if r in by_slug]
    related_html = ""
    if related:
        items = "\n".join(f'        <li><a href="{root}features/{q["slug"]}/">{md(q["name"])}</a>: {md(q["summary"])}</li>'
                          for q in related)
        related_html = (f'      <h2 class="label">{md(fl["related"])}</h2>\n'
                        f'      <ul class="points">\n{items}\n      </ul>\n')
    prev_q = pages[at - 1] if at > 0 else None
    next_q = pages[at + 1] if at + 1 < len(pages) else None
    pager = "".join(
        f'<a class="{cls}" href="{root}features/{q["slug"]}/" rel="{rel}"><small>{md(label)}</small> {md(q["name"])}</a>'
        for q, cls, rel, label in ((prev_q, "prev", "prev", fl["previous"]), (next_q, "next", "next", fl["next"]))
        if q)
    docs_link = p.get("docs_label") or fl["docs_link"].replace("{name}", name)

    ld = jsonld(
        {"@type": "WebPage", "@id": url, "url": url, "name": flat(p["title"]),
         "description": flat(p["description"]), "inLanguage": "en",
         "isPartOf": {"@id": f"{site}/#website"}, "about": {"@id": f"{site}/#software"},
         "breadcrumb": {"@id": f"{url}#breadcrumb"}},
        breadcrumbs(url, [(lab["breadcrumb_home"], f"{site}/"),
                          (fl["breadcrumb_features"], f"{site}/features/"), (name, url)]),
        software(c, hub), website(c))
    has_shots = any("image" in s for s in p["sections"])
    note = f'\n    <p class="checked">{md(fl["screenshot_note"])}</p>' if has_shots else ""

    return (page_head(c, hub, title=p["title"], description=flat(p["description"]), path=path, root=root, ld=ld)
            + f"""
<main id="main">
  <div class="page-top col">
    {features_crumbs(hub, fhub, root, name, "../")}
    <h1 class="page-h1">{md(p.get("h1", name))}</h1>
    <p class="lead">{md(p["intro"])}</p>
    <p class="checked">{md(fl["in_nav"])} <strong>{md(p["nav"])}</strong></p>{note}
  </div>

{"".join(sections)}
  <section class="part col more" aria-label="{attr(fl["related"])}">
    <p><a href="{root}docs/#{attr(p["docs"])}">{md(docs_link)}</a></p>
{related_html}    <nav class="pager" aria-label="{attr(fl["breadcrumb_features"])}">{pager}</nav>
    <p><a href="../">{md(fl["all_features"])}</a></p>
  </section>

{about_block(hub, root)}
</main>

""" + page_foot(hub, "../../compare/", "../../about/", "../../docs/", "../../stats/", notice=False,
                changelog_link="../../changelog/"))


def render_features_hub(c: dict, hub: dict, fhub: dict, pages: list[dict]) -> str:
    site, lab, fl, pg = c["page"]["site_url"].rstrip("/"), hub["labels"], fhub["labels"], fhub["page"]
    path, root = "/features/", "../"
    url = site + path
    tiles = []
    for p in pages:
        thumb = feature_thumb(p)
        w, h = png_size(SITE / "img" / thumb) if thumb else (0, 0)
        img = (f'<img src="{root}img/{attr(thumb)}" alt="" width="{w}" height="{h}" loading="lazy">'
               if thumb else "")
        tiles.append(f'      <li><a class="tile" href="{p["slug"]}/">{img}'
                     f'<span class="tile-name">{md(p["name"])}</span>'
                     f'<span class="tile-text">{md(p["summary"])}</span></a></li>')
    hp = fhub["help"]
    ld = jsonld(
        {"@type": "CollectionPage", "@id": url, "url": url, "name": flat(pg["title"]),
         "description": flat(pg["description"]), "inLanguage": "en",
         "isPartOf": {"@id": f"{site}/#website"}, "about": {"@id": f"{site}/#software"},
         "breadcrumb": {"@id": f"{url}#breadcrumb"},
         "mainEntity": {"@type": "ItemList", "itemListElement": [
             {"@type": "ListItem", "position": n, "url": f"{url}{p['slug']}/", "name": p["name"]}
             for n, p in enumerate(pages, 1)]}},
        breadcrumbs(url, [(lab["breadcrumb_home"], f"{site}/"), (fl["breadcrumb_features"], url)]),
        software(c, hub), website(c))
    return (page_head(c, hub, title=pg["title"], description=flat(pg["description"]), path=path, root=root, ld=ld)
            + f"""
<main id="main">
  <div class="page-top col">
    {features_crumbs(hub, fhub, root, fl["breadcrumb_features"], None)}
    <h1 class="page-h1">{md(pg["h1"])}</h1>
    <p class="lead">{md(pg["intro"])}</p>
  </div>

  <section class="part wide" aria-label="{attr(pg["table_caption"])}">
    <ul class="tiles">
{chr(10).join(tiles)}
    </ul>
  </section>

  <section class="part col">
    <p><strong>{md(hp["name"])}.</strong> {md(hp["summary"])} <a href="{root}{attr(hp["link"])}">{md(c["docs"]["h1"])}</a></p>
  </section>

{about_block(hub, root)}
</main>

""" + page_foot(hub, "../compare/", "../about/", "../docs/", "../stats/", notice=False))


def build_features(c: dict, hub: dict) -> tuple[dict, list[dict]]:
    """Write site/features/. Stale pages of a removed feature are deleted."""
    fhub, pages = load_features()
    out = SITE / "features"
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(render_features_hub(c, hub, fhub, pages), encoding="utf-8")
    keep = {p["slug"] for p in pages}
    for d in out.iterdir():
        if d.is_dir() and d.name not in keep and (d / "index.html").exists():
            (d / "index.html").unlink()
            d.rmdir()
    for p in pages:
        (out / p["slug"]).mkdir(exist_ok=True)
        (out / p["slug"] / "index.html").write_text(render_feature(c, hub, fhub, p, pages), encoding="utf-8")
    print(f"built site/features/ ({len(pages)} pages)")
    return fhub, pages


# ── Stats (/stats/) ──────────────────────────────────────────────────
# Only the shell is built here. The numbers are a fragment that
# scripts/publicstats.py uploads to the Fly volume once a day; nginx includes
# it with SSI (see nginx.conf and README, "Public stats"). Opened from disk,
# the page shows the fallback text: browsers ignore SSI comments.
def render_stats(c: dict, hub: dict) -> str:
    site, lab, st = c["page"]["site_url"].rstrip("/"), hub["labels"], c["stats"]
    path, root = "/stats/", "../"
    url = site + path
    ld = jsonld(
        {"@type": "WebPage", "@id": url, "url": url, "name": flat(st["title"]),
         "description": flat(st["description"]), "inLanguage": "en",
         "isPartOf": {"@id": f"{site}/#website"}, "about": {"@id": f"{site}/#software"},
         "breadcrumb": {"@id": f"{url}#breadcrumb"}},
        breadcrumbs(url, [(lab["breadcrumb_home"], f"{site}/"), (st["h1"], url)]),
        software(c, hub), website(c))
    how = "\n".join(f"      <li>{md(item)}</li>" for item in st["how"])
    return (page_head(c, hub, title=st["title"], description=flat(st["description"]), path=path, root=root, ld=ld)
            + f"""
<main id="main">
  <div class="page-top col">
    {crumbs(hub, root, st["h1"], None)}
    <h1 class="page-h1">{md(st["h1"])}</h1>
    <p class="lead">{md(st["intro"])}</p>
  </div>

  <div class="stats-page col">
<!--# block name="nostats" --><p class="stats-fallback">{md(st["fallback"])}</p><!--# endblock -->
<!--# include virtual="/stats/_numbers" stub="nostats" -->
  </div>

  <section class="stats-how col" aria-labelledby="how">
    <h2 id="how">{md(st["how_heading"])}</h2>
    <ul>
{how}
    </ul>
    <p>{md(st["json_label"])}</p>
  </section>
</main>

""" + page_foot(hub, "../compare/", "../about/", "../docs/", "./", notice=False))


def build_stats(c: dict, hub: dict) -> None:
    """Write site/stats/index.html."""
    (SITE / "stats").mkdir(exist_ok=True)
    (SITE / "stats" / "index.html").write_text(render_stats(c, hub), encoding="utf-8")
    print("built site/stats/")


# ── Docs (/docs/ and llms-full.txt) ──────────────────────────────────
# The app's Help pages (src/hermitcrm/help/*.md) are the one source: the app's
# /help, `hermitcrm help <topic>` and these all read them, and nothing here is
# copied by hand. They are taken from the download the site offers, so the docs
# describe the version people get, not work on main that is not released yet.
# The index is left out (the contents list replaces it), and so is feedback,
# which is a form inside the app. The changelog gets a page of its own,
# /changelog/, built from the same download.
DOCS_SKIP = ("index", "feedback", "changelog")


class Docs(dict):
    """version, date (or None), source ("download" or "working tree"), path,
    topics [(topic, title, summary, markdown)], changelog (its Markdown, or None
    for a release from before it was a Help page) and render (the app's converter)."""


def load_help(folder: Path):
    """The app's help module, loaded from a folder without importing the rest of
    the package. It needs only the standard library."""
    spec = importlib.util.spec_from_file_location("hermit_help", folder / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def version_of(init_py: str) -> str:
    m = re.search(r'^__version__ = "([^"]+)"$', init_py, re.M)
    return m.group(1) if m else ""


def first_paragraph(text: str) -> str:
    """The paragraph under a topic's title, joined into one line. (The app's own
    summary_of keeps only its first line, which is enough for a terminal.)"""
    para: list[str] = []
    for line in text.splitlines():
        if line.startswith("# ") and not para:
            continue
        if line.strip():
            para.append(line.strip())
        elif para:
            break
    return " ".join(para)


def read_help(folder: Path, version: str, **info) -> Docs:
    mod = load_help(folder)
    topics = []
    for topic in mod.topics():
        text = mod.read(topic)
        if text is None or topic in DOCS_SKIP:
            continue
        topics.append((topic, mod.title_of(text) or topic, first_paragraph(text), text))
    return Docs(version=version, topics=topics, changelog=mod.read("changelog"),
                render=mod.render, **info)


def docs_from_tarball(tarball: Path, label: str = "") -> Docs:
    """The Help pages inside a release tarball (made by scripts/release.sh, so one
    top folder, hermitcrm-<version>/). Its date is the commit's: git archive
    stamps every file with it."""
    with tarfile.open(tarball, "r:gz") as tar, tempfile.TemporaryDirectory() as tmp:
        help_dir, init_py, stamp = Path(tmp), "", 0
        for m in tar.getmembers():
            parts = m.name.split("/")
            if not m.isfile() or len(parts) < 4 or parts[1:3] != ["src", "hermitcrm"]:
                continue
            if parts[3:] == ["__init__.py"]:
                init_py = tar.extractfile(m).read().decode("utf-8")
            elif len(parts) == 5 and parts[3] == "help" and re.fullmatch(r"[\w-]+\.(md|py)", parts[4]):
                (help_dir / parts[4]).write_bytes(tar.extractfile(m).read())
                stamp = max(stamp, m.mtime)
        if not (help_dir / "__init__.py").is_file():
            raise BuildError(f"{tarball.name} has no src/hermitcrm/help/")
        made = datetime.fromtimestamp(stamp, timezone.utc).date() if stamp else None
        return read_help(help_dir, version_of(init_py), date=made, source="download",
                         path=label or tarball.name)


def load_docs(c: dict) -> Docs:
    """From the download in [links].download when it is in site/, otherwise from
    this checkout (which `check` reports, and --release refuses)."""
    link = c["links"]["download"]
    tarball = SITE / link if link not in ("", "#") and "://" not in link else None
    if tarball and tarball.is_file():
        return docs_from_tarball(tarball, f"site/{link}")
    init_py = (HELP.parent / "__init__.py").read_text(encoding="utf-8")
    return read_help(HELP, version_of(init_py), date=None, source="working tree",
                     path="src/hermitcrm/help/")


_APP_LINK = re.compile(r"\[([^\]]+)\]\((/[^)\s]*)\)")


def docs_links(text: str, topics: set[str], base: str) -> str:
    """Point the Help pages' links at this page: /help/settings#bcc-capture becomes
    <base>#settings-bcc-capture. Links into the rest of the app (/welcome,
    /settings) mean nothing on the website, so they become plain text."""
    def fix(m: re.Match) -> str:
        path, _, frag = m.group(2).partition("#")
        path = path.rstrip("/")
        if path == "/help":
            return f"[{m.group(1)}]({base}#contents)"
        topic = path[len("/help/"):] if path.startswith("/help/") else ""
        if topic in topics:
            return f"[{m.group(1)}]({base}#{topic}{'-' + frag if frag else ''})"
        return m.group(1)
    return _APP_LINK.sub(fix, text)


def demote(text: str) -> str:
    """One heading level down, outside code fences: a topic's # title becomes ##
    under the page's own title."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(r"#{1,5} ", line):
            line = "#" + line
        out.append(line)
    return "\n".join(out)


def docs_section(docs: Docs, topic: str, text: str, names: set[str]) -> str:
    """One topic as HTML: the title an h2 with the topic as its id, sub-headings
    one level down with ids prefixed by the topic (so they stay unique on the
    page), and wide tables in a box that scrolls on a phone."""
    body = docs["render"](docs_links(text, names, ""))
    body = re.sub(r'<h([2-5]) id="([^"]+)">(.*?)</h\1>',
                  lambda m: f'<h{int(m.group(1)) + 1} id="{topic}-{m.group(2)}">{m.group(3)}</h{int(m.group(1)) + 1}>',
                  body)
    body = re.sub(r"<h1>(.*?)</h1>", rf'<h2 id="{topic}">\1</h2>', body, count=1)
    body = body.replace("<table>", '<div class="docs-table"><table>').replace("</table>", "</table></div>")
    return typeset_html(body)


def render_docs(c: dict, hub: dict, docs: Docs) -> str:
    site, lab, d = c["page"]["site_url"].rstrip("/"), hub["labels"], c["docs"]
    path, root = "/docs/", "../"
    url = site + path
    names = {t for t, *_ in docs["topics"]}
    version = docs["version"] or c["release"]["version"]
    article = {"@type": "TechArticle", "@id": url, "url": url, "headline": flat(d["h1"]),
               "name": flat(d["title"]), "description": flat(d["description"]), "inLanguage": "en",
               "version": version, "isPartOf": {"@id": f"{site}/#website"},
               "about": {"@id": f"{site}/#software"}, "breadcrumb": {"@id": f"{url}#breadcrumb"},
               "encoding": {"@type": "MediaObject", "encodingFormat": "text/plain",
                            "contentUrl": f"{site}/llms-full.txt"}}
    if docs["date"]:
        article["dateModified"] = docs["date"].isoformat()
    ld = jsonld(article, breadcrumbs(url, [(lab["breadcrumb_home"], f"{site}/"), (d["h1"], url)]),
                software(c, hub), website(c))

    def toc(items) -> str:
        return "".join(f'<li><a href="#{t}">{html.escape(title)}</a></li>' for t, title, *_ in items)
    use = [x for x in docs["topics"] if not x[0].startswith("adjust-")]
    recipes = [x for x in docs["topics"] if x[0].startswith("adjust-")]
    sections = "\n".join(
        f'  <section class="doc" aria-labelledby="{t}">\n{docs_section(docs, t, text, names)}\n'
        f'  <p class="doc-up"><a href="#contents">{md(d["back"])}</a></p>\n  </section>'
        for t, _, _, text in docs["topics"])
    made = (f', <time datetime="{docs["date"].isoformat()}">{long_date(docs["date"])}</time>'
            if docs["date"] else "")

    return (page_head(c, hub, title=d["title"], description=flat(d["description"]), path=path,
                      root=root, ld=ld, modified=docs["date"])
            + f"""
<main id="main">
  <div class="page-top col">
    {crumbs(hub, root, d["h1"], None)}
    <h1 class="page-h1">{md(d["h1"])}</h1>
    <p class="lead">{md(d["lead"])}</p>
    <p class="checked">{md(d["version_label"])} {html.escape(version)}{made}. {md(d["text_note"])}</p>
  </div>

  <nav class="docs-toc col" id="contents" aria-labelledby="contents-h">
    <h2 class="label" id="contents-h">{md(d["contents"])}</h2>
    <ul>{toc(use)}</ul>
    <h3 class="label">{md(d["recipes"])}</h3>
    <p class="docs-note">{md(d["recipes_note"])}</p>
    <ul>{toc(recipes)}</ul>
  </nav>

  <div class="docs col">
{sections}
  </div>
</main>

""" + page_foot(hub, "../compare/", "../about/", "./", "../stats/", notice=False))


def llms_full_txt(c: dict, docs: Docs) -> str:
    """Every docs topic as Markdown in one file, for an AI tool that wants the
    whole manual in one request (the llms-full.txt convention)."""
    site, d = c["page"]["site_url"].rstrip("/"), c["docs"]
    names = {t for t, *_ in docs["topics"]}
    version = docs["version"] or c["release"]["version"]
    head = [f"# {plain(d['h1'])}", "", f"> {plain(d['description'])}", "",
            f"{plain(d['version_label'])} {version}"
            + (f", {docs['date'].isoformat()}" if docs["date"] else "") + ". "
            f"The same text as {site}/docs/ and as `hermitcrm help <topic>` in the app.", ""]
    body = [demote(docs_links(text, names, f"{site}/docs/")).rstrip("\n") + "\n"
            for _, _, _, text in docs["topics"]]
    return "\n".join(head) + "\n" + "\n".join(body)


def build_docs(c: dict, hub: dict) -> Docs:
    """Write site/docs/index.html and site/llms-full.txt."""
    docs = load_docs(c)
    (SITE / "docs").mkdir(exist_ok=True)
    (SITE / "docs" / "index.html").write_text(render_docs(c, hub, docs), encoding="utf-8")
    LLMS_FULL.write_text(llms_full_txt(c, docs), encoding="utf-8")
    print(f"built site/docs/ and site/llms-full.txt ({len(docs['topics'])} topics, "
          f"version {docs['version']}, from {docs['path']})")
    return docs


# ── Changelog (/changelog/) ──────────────────────────────────────────
# The app's Help > Changelog, from the same download as /docs/, so it ends at
# the version people get. Its links to other Help pages go to /docs/.
def render_changelog(c: dict, hub: dict, docs: Docs) -> str:
    site, lab, ch = c["page"]["site_url"].rstrip("/"), hub["labels"], c["changelog"]
    path, root = "/changelog/", "../"
    url = site + path
    names = {t for t, *_ in docs["topics"]}
    text = docs["changelog"]
    text = text.split("\n", 1)[1] if text.startswith("# ") else text  # the page has its own h1
    # The converter only takes "#" and absolute links, so Help links become
    # anchors first and then point at /docs/ (the page has no anchors of its own).
    body = docs["render"](docs_links(text, names, "")).replace('href="#', 'href="../docs/#')
    body = body.replace("<table>", '<div class="docs-table"><table>').replace("</table>", "</table></div>")
    body = typeset_html(body)
    page = {"@type": "WebPage", "@id": url, "url": url, "name": flat(ch["title"]),
            "description": flat(ch["description"]), "inLanguage": "en",
            "isPartOf": {"@id": f"{site}/#website"}, "about": {"@id": f"{site}/#software"},
            "breadcrumb": {"@id": f"{url}#breadcrumb"}}
    if docs["date"]:
        page["dateModified"] = docs["date"].isoformat()
    ld = jsonld(page, breadcrumbs(url, [(lab["breadcrumb_home"], f"{site}/"), (ch["h1"], url)]),
                software(c, hub), website(c))
    return (page_head(c, hub, title=ch["title"], description=flat(ch["description"]), path=path,
                      root=root, ld=ld, modified=docs["date"])
            + f"""
<main id="main">
  <div class="page-top col">
    {crumbs(hub, root, ch["h1"], None)}
    <h1 class="page-h1">{md(ch["h1"])}</h1>
    <p class="lead">{md(ch["lead"])}</p>
  </div>

  <div class="docs col">
  <section class="doc">
{body}
  </section>
  </div>
</main>

""" + page_foot(hub, "../compare/", "../about/", "../docs/", "../stats/", notice=False,
                changelog_link="./"))


def build_changelog(c: dict, hub: dict, docs: Docs) -> bool:
    """Write site/changelog/index.html, or leave it out for a download from
    before the changelog was a Help page."""
    if not docs.get("changelog"):
        print("  no changelog in the download: site/changelog/ not built")
        return False
    (SITE / "changelog").mkdir(exist_ok=True)
    (SITE / "changelog" / "index.html").write_text(render_changelog(c, hub, docs), encoding="utf-8")
    print("built site/changelog/")
    return True


def llms_txt(c: dict, hub: dict, pages: list[dict], about: dict, docs: Docs,
             features: list[dict] = ()) -> str:
    """llms.txt (llmstxt.org): a plain summary with links, for AI tools that read a site.
    The docs come first: they say what Hermit CRM does, feature by feature."""
    site = c["page"]["site_url"].rstrip("/")
    y, d = c["yours"], c["docs"]
    lines = [f"# {c['header']['name']}", "", f"> {plain(c['hero']['subline'])}", "",
             plain(hub["hermit"]["about"]), "",
             "## Docs", "", plain(d["llms_intro"]), "",
             f"- [All docs in one file]({site}/llms-full.txt): every topic below as Markdown, "
             f"for version {docs['version'] or c['release']['version']}",
             f"- [Docs]({site}/docs/): the same as one web page"]
    lines += [f"- [{plain(title)}]({site}/docs/#{t}): {plain(summary)}"
              for t, title, summary, _ in docs["topics"]]
    lines += ["",
             f"## {plain(y['heading']).rstrip('.')}", "", plain(y["promise"]), ""]
    lines += [f'- {plain(e["name"])}: "{plain(e["prompt"])}" {plain(e["change"])}'
              for e in y["examples"]]
    lines += ["", plain(y["safety"]), "",
              "## Pages", "", f"- [Home]({site}/): what it is, how to install it, questions and answers",
             f"- [Docs]({site}/docs/): {plain(d['description'])}",
             *([f"- [Features]({site}/features/): every page of the app, with screenshots"] if features else []),
             *([f"- [Changelog]({site}/changelog/): {plain(c['changelog']['description'])}"]
               if docs.get("changelog") else []),
             f"- [Hermit CRM compared]({site}/compare/): {plain(hub['page']['description'])}",
             f"- [About]({site}/about/): {plain(about['page']['description'])}",
             f"- [Stats]({site}/stats/): {plain(c['stats']['llms'])}; "
             f"the same as JSON at {site}/stats/stats.json", ""]
    if features:
        lines += ["## Features", "", "One page for each link in the app's left navigation.", ""]
        lines += [f"- [{plain(p['name'])}]({site}/features/{p['slug']}/): {plain(p['summary'])}"
                  for p in features]
        lines += [""]
    lines += ["## Comparisons", ""]
    lines += [f"- [Hermit CRM vs {p['name']}]({site}/compare/{p['slug']}/): {plain(p['short_answer'])}"
              for p in pages]
    lines += ["", "## Facts", ""]
    lines += [f"- {plain(r['label'])}: {plain(r['hermit'])}" for r in hub["rows"]]
    return "\n".join(lines) + "\n"


def build_compare(c: dict) -> tuple[dict, list[dict]]:
    """Write site/compare/. Stale pages of a removed CRM are deleted."""
    hub, pages = load_compare()
    out = SITE / "compare"
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(render_hub(c, hub, pages), encoding="utf-8")
    keep = {p["slug"] for p in pages}
    for d in out.iterdir():
        if d.is_dir() and d.name not in keep and (d / "index.html").exists():
            (d / "index.html").unlink()
            d.rmdir()
    for p in pages:
        (out / p["slug"]).mkdir(exist_ok=True)
        (out / p["slug"] / "index.html").write_text(render_compare(c, hub, p, pages), encoding="utf-8")
    print(f"built site/compare/ ({len(pages)} comparisons)")
    return hub, pages


def build_about(c: dict, hub: dict, pages: list[dict]) -> dict:
    """Write site/about/index.html."""
    a = load_about()
    (SITE / "about").mkdir(exist_ok=True)
    (SITE / "about" / "index.html").write_text(render_about(c, hub, a), encoding="utf-8")
    print("built site/about/")
    return a


# ── Checks against the brief ─────────────────────────────────────────
def walk(value, path=""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(value, list):
        for n, v in enumerate(value, 1):
            yield from walk(v, f"{path}[{n}]")


def check(c: dict, pages: list[dict] | None = None, hub: dict | None = None,
          about: dict | None = None, docs: Docs | None = None, fhub: dict | None = None,
          features: list[dict] | None = None) -> tuple[list[str], list[str]]:
    problems, tbc = [], []
    texts = list(walk(c))
    if hub:
        texts += walk(hub, "compare/index")
    if about:
        texts += walk(about, "about")
    if fhub:
        texts += walk(fhub, "features/index")
    for p in pages or []:
        texts += walk({k: v for k, v in p.items() if k != "checked"}, f"compare/{p['slug']}")
    for p in features or []:
        texts += walk({k: v for k, v in p.items() if k not in ("image", "address")}, f"features/{p['slug']}")
    # Search results cut titles after about 60 characters and descriptions
    # after about 155; the page still works, but the end goes missing.
    snippets = [("page", c["page"]["title"], c["page"]["description"] or c["hero"]["subline"])]
    if hub:
        snippets.append(("compare/index", hub["page"]["title"], hub["page"]["description"]))
    snippets += [(f"compare/{p['slug']}", p["title"], p["description"]) for p in pages or []]
    if about:
        snippets.append(("about", about["page"]["title"], about["page"]["description"]))
    if fhub:
        snippets.append(("features/index", fhub["page"]["title"], fhub["page"]["description"]))
    snippets += [(f"features/{p['slug']}", p["title"], p["description"]) for p in features or []]
    snippets.append(("docs", c["docs"]["title"], c["docs"]["description"]))
    snippets.append(("changelog", c["changelog"]["title"], c["changelog"]["description"]))
    snippets.append(("stats", c["stats"]["title"], c["stats"]["description"]))
    for where, title, description in snippets:
        if len(flat(title)) > 65:
            problems.append(f"{where}: title is {len(flat(title))} characters, keep it at 65 or less")
        if len(flat(description)) > 155:
            problems.append(f"{where}: description is {len(flat(description))} characters, keep it at 155 or less")
    for path, text in texts:
        if path == "file.file_body":
            continue
        if "—" in text or "–" in text:
            problems.append(f"{path}: em or en dash")
        if "!" in text:
            problems.append(f"{path}: exclamation mark")
        low = text.lower()
        for word in BANNED:
            if re.search(rf"\b{re.escape(word)}", low):
                problems.append(f"{path}: banned word '{word}'")
        if "[TBC" in text or text.strip() == "#" and path.startswith("links."):
            tbc.append(path)
    for p in problems:
        print(f"  warning  {p}")
    if tbc:
        print(f"  {len(tbc)} values still [TBC]: " + ", ".join(tbc))
    # A download served by the site itself must be in site/ when the site is
    # built; the release files are not in git (see README, "Publishing a build").
    for key in ("download", "sha256"):
        link = c["links"][key]
        if link not in ("", "#") and "://" not in link and not (SITE / link).is_file():
            problems.append(f"links.{key}: site/{link} does not exist")
            print(f"  warning  {problems[-1]}")
    if c["file"]["screenshot"] and not (SITE / "img" / c["file"]["screenshot"]).exists():
        problems.append(f"site/img/{c['file']['screenshot']} does not exist")
        print(f"  warning  {problems[-1]}")
    for e in c["yours"]["examples"]:
        if png_size(SITE / "img" / e["image"]) == (0, 0):
            problems.append(f"yours.examples: site/img/{e['image']} is missing or not a PNG")
            print(f"  warning  {problems[-1]}")
    # Feature pages: every screenshot exists, every link they make goes somewhere,
    # and every row of "What you get" with a slug has its page.
    first = len(problems)
    slugs = {p["slug"] for p in features or []}
    topics = {t for t, *_ in docs["topics"]} if docs else set()
    for p in features or []:
        where = f"features/{p['slug']}"
        for s in p["sections"]:
            if "image" in s and png_size(SITE / "img" / s["image"]) == (0, 0):
                problems.append(f"{where}: site/img/{s['image']} is missing or not a PNG")
            if "image" in s and not s["alt"].strip():
                problems.append(f"{where}: a screenshot has no alt text")
        for r in p.get("related", []):
            if r not in slugs:
                problems.append(f"{where}: related page '{r}' does not exist")
        if topics and p["docs"] not in topics | {"contents"}:
            problems.append(f"{where}: docs topic '{p['docs']}' is not in the docs")
        if feature_thumb(p) and png_size(SITE / "img" / feature_thumb(p)) == (0, 0):
            problems.append(f"{where}: thumbnail site/img/{feature_thumb(p)} is missing or not a PNG")
    for x in c["features"]["items"]:
        if x.get("slug") and features is not None and x["slug"] not in slugs:
            problems.append(f"features.items: '{x['name']}' links to features/{x['slug']}/, which does not exist")
    for p in problems[first:]:
        print(f"  warning  {p}")
    # /docs/ must describe the version people download, so on a release it has
    # to come from that download and carry its version.
    if docs:
        if docs["source"] != "download":
            problems.append(f"docs: built from {docs['path']}, not from the download in "
                            f"[links].download, so they may describe unreleased work")
            print(f"  warning  {problems[-1]}")
        if docs["version"] != c["release"]["version"]:
            problems.append(f"docs: {docs['path']} is version {docs['version'] or '?'}, "
                            f"[release].version is {c['release']['version']}")
            print(f"  warning  {problems[-1]}")
    return problems, tbc


def build() -> tuple[dict, list[str], list[str]]:
    """Build both files; raise BuildError when the site and the app have drifted."""
    app_css = app_tokens_css(TOKENS.read_text(encoding="utf-8"))
    broken = drift(STYLE.read_text(encoding="utf-8"), app_css)
    if broken:
        raise BuildError("the site no longer matches the app's tokens:\n  " + "\n  ".join(broken))
    c = tomllib.loads(CONTENT.read_text(encoding="utf-8"))
    site_url = c["page"]["site_url"].rstrip("/")
    APP_TOKENS.write_text(app_css, encoding="utf-8")
    # The comparison pages and the About page need the site's address for their
    # canonical links, so they are only built once [page].site_url is set.
    hub, pages = build_compare(c) if site_url else (None, [])
    about = build_about(c, hub, pages) if hub else None
    fhub, features = build_features(c, hub) if hub else (None, [])
    docs = build_docs(c, hub) if hub else None
    if hub:
        build_changelog(c, hub, docs)
        build_stats(c, hub)
        LLMS.write_text(llms_txt(c, hub, pages, about, docs, features), encoding="utf-8")
        print("built site/llms.txt")
    ld = jsonld(website(c), software(c, hub)) if hub else ""
    OUT.write_text(render(c, ld), encoding="utf-8")
    print(f"built {OUT.relative_to(ROOT)} and {APP_TOKENS.relative_to(ROOT)}")
    crawl(site_url, pages, about, docs, stats=bool(hub), features=features)
    problems, tbc = check(c, pages, hub, about, docs, fhub, features)
    return c, problems, tbc


def crawl(site_url: str, pages: list[dict] = (), about: dict | None = None,
          docs: Docs | None = None, stats: bool = False, features: list[dict] = ()) -> None:
    """Write robots.txt and sitemap.xml for search engines, or drop them while
    the site has no address yet (a sitemap needs absolute URLs)."""
    robots, sitemap = SITE / "robots.txt", SITE / "sitemap.xml"
    if not site_url:
        robots.unlink(missing_ok=True)
        sitemap.unlink(missing_ok=True)
        LLMS.unlink(missing_ok=True)
        LLMS_FULL.unlink(missing_ok=True)
        return
    robots.write_text(f"User-agent: *\nAllow: /\n\nSitemap: {site_url}/sitemap.xml\n",
                      encoding="utf-8")
    urls = [f"  <url><loc>{html.escape(site_url)}/</loc></url>"]
    if pages:
        newest = max(p["checked"] for p in pages).isoformat()
        urls.append(f"  <url><loc>{html.escape(site_url)}/compare/</loc><lastmod>{newest}</lastmod></url>")
        urls += [f"  <url><loc>{html.escape(site_url)}/compare/{p['slug']}/</loc>"
                 f"<lastmod>{p['checked'].isoformat()}</lastmod></url>" for p in pages]
    if about:
        urls.append(f"  <url><loc>{html.escape(site_url)}/about/</loc>"
                    f"<lastmod>{about['page']['published'].isoformat()}</lastmod></url>")
    if docs:
        lastmod = f"<lastmod>{docs['date'].isoformat()}</lastmod>" if docs["date"] else ""
        urls.append(f"  <url><loc>{html.escape(site_url)}/docs/</loc>{lastmod}</url>")
        if docs.get("changelog"):
            urls.append(f"  <url><loc>{html.escape(site_url)}/changelog/</loc>{lastmod}</url>")
    if features:
        # The features describe the released version, so they are as new as the docs.
        lastmod = f"<lastmod>{docs['date'].isoformat()}</lastmod>" if docs and docs["date"] else ""
        urls.append(f"  <url><loc>{html.escape(site_url)}/features/</loc>{lastmod}</url>")
        urls += [f"  <url><loc>{html.escape(site_url)}/features/{p['slug']}/</loc>{lastmod}</url>"
                 for p in features]
    if stats:
        urls.append(f"  <url><loc>{html.escape(site_url)}/stats/</loc><changefreq>daily</changefreq></url>")
    sitemap.write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                       '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                       + "\n".join(urls) + "\n</urlset>\n", encoding="utf-8")
    print("built site/robots.txt and site/sitemap.xml")


# The share images: og.png for links to the site, and the repository's social
# preview, which GitHub wants at 1280 x 640 and takes only as an upload
# (Settings > General > Social preview), so it is kept in the repo to upload.
SHARE_IMAGES = [
    (SITE / "img" / "og.png", 1200, 630),
    (ROOT.parent / ".github" / "social-preview.png", 1280, 640),
]


def share(c: dict) -> None:
    """Render the share images (og.png and the GitHub social preview) with Playwright."""
    from playwright.sync_api import sync_playwright  # pip install playwright

    tmp = SITE / "_share.html"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for out, w, h in SHARE_IMAGES:
                page_html = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="app-tokens.css"><link rel="stylesheet" href="style.css"><style>
:root{{color-scheme:light}} body{{margin:0;width:{w}px;height:{h}px;overflow:hidden}}
.s{{width:{w}px;height:{h}px;box-sizing:border-box;padding:96px 120px;display:flex;flex-direction:column;justify-content:space-between}}
.s .brand svg{{width:58px;height:46px}} .s .brand span{{font-size:38px}}
.s h1{{font-size:112px;line-height:1}} .s p{{margin:0;font-size:28px;color:var(--muted)}}
</style></head><body><div class="s">
<div class="brand">{MARK}<span>{md(c["header"]["name"])}</span></div>
<div><h1>{md(c["hero"]["h1"])}</h1></div>
<p>{md(c["share"]["tagline"])}</p></div></body></html>"""
                tmp.write_text(page_html, encoding="utf-8")
                page = browser.new_page(viewport={"width": w, "height": h})
                page.goto(tmp.as_uri())
                page.evaluate("document.fonts.ready")
                page.screenshot(path=str(out))
                page.close()
                print(f"built {out.relative_to(ROOT.parent)}")
            browser.close()
    finally:
        tmp.unlink(missing_ok=True)


def main() -> None:
    try:
        c, problems, tbc = build()
    except BuildError as e:
        sys.exit(f"build failed: {e}")
    if "--release" in sys.argv and (problems or tbc):
        sys.exit(f"not ready to release: {len(tbc)} [TBC] or '#' values and "
                 f"{len(problems)} problems left (listed above)")
    if "--share" in sys.argv:
        share(c)
    if "--watch" in sys.argv:
        watched = lambda: [CONTENT, ABOUT, STYLE, TOKENS, *sorted(COMPARE.glob("*.toml")),  # noqa: E731
                           *sorted(FEATURES.glob("*.toml")), *sorted(HELP.glob("*.md"))]
        print("watching content.toml, about.toml, compare/*.toml, features/*.toml, site/style.css, the app's tokens.css "
              "and its Help pages (Ctrl+C to stop)")
        stamp = lambda: [(f, f.stat().st_mtime) for f in watched()]  # noqa: E731
        seen = stamp()
        while True:
            time.sleep(0.5)
            now = stamp()
            if now != seen:
                seen = now
                try:
                    build()
                except tomllib.TOMLDecodeError as e:
                    print(f"  content.toml has a mistake: {e}")
                except BuildError as e:
                    print(f"  build failed: {e}")


if __name__ == "__main__":
    main()
