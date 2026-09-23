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

    python3 build.py            build site/index.html, site/compare/ and site/app-tokens.css once
    python3 build.py --watch    rebuild whenever content.toml, style.css or the app's tokens change
    python3 build.py --share    also render site/img/og.png (needs Playwright)
    python3 build.py --release  build, then fail if any [TBC], "#" link or brief problem is left

Only the Python standard library is needed (3.11 or newer) for the page.
All words come from content.toml and compare/*.toml (the comparison pages);
the look is in site/style.css. Colours and
fonts shared with the app come from src/hermitcrm/static/tokens.css, copied into
site/app-tokens.css on every build. The build fails if the site uses a token
that neither file defines, so the site cannot drift from the app unnoticed.
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content.toml"
SITE = ROOT / "site"
OUT = SITE / "index.html"
STYLE = SITE / "style.css"
TOKENS = ROOT.parent / "src" / "hermitcrm" / "static" / "tokens.css"
APP_TOKENS = SITE / "app-tokens.css"
COMPARE = ROOT / "compare"
LLMS = SITE / "llms.txt"

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


def md(text: str) -> str:
    """Escape, then apply **bold**, `code` and [text](url)."""
    out = html.escape(flat(text), quote=False)
    codes: list[str] = []

    def keep_code(m: re.Match) -> str:
        codes.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    out = re.sub(r"`([^`]+)`", keep_code, out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                 lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', out)
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

    steps = "\n".join(f"      <li><span>{md(s)}</span></li>" for s in i["steps"])
    features = "\n".join(f"      <dt>{md(x['name'])}</dt><dd>{md(x['text'])}</dd>"
                         for x in c["features"]["items"])
    principles = "\n".join(f"      <p><strong>{md(x['name'])}</strong> {md(x['text'])}</p>"
                           for x in c["principles"])
    faqs = "\n".join(
        f'      <details{" open" if q.get("open") else ""}><summary>{md(q["q"])}</summary>'
        f'<p>{md(q["a"])}</p></details>' for q in c["questions"]["items"])

    if f["screenshot"]:
        visual = (f'<img src="img/{attr(f["screenshot"])}" alt="{attr(f["screenshot_alt"])}" '
                  f'width="1600" height="800" loading="lazy">')
    else:
        visual = mock()
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
  {github}
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
      <figure class="window">
        <div class="window-bar"><i></i><i></i><i></i><span>{md(f["address_bar"])}</span></div>
        {visual}
      </figure>
      <div class="file">
        <p>{md(f["file_caption"])}</p>
        <pre><span class="path">{html.escape(f["file_path"])}</span>
{file_body}</pre>
      </div>
    </div>
  </section>

  <hr class="rule blank">

  <section class="features col" aria-labelledby="features">
    <h2 class="label" id="features">{md(c["features"]["label"])}</h2>
    <dl>
{features}
    </dl>
    <div class="principles">
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
<!-- Built from compare/*.toml by build.py. Edit the text there, not here. -->
<a class="skip" href="#main">Skip to content</a>

<header class="site-header wide">
  <a class="brand" href="{root}" aria-label="{attr(c["header"]["name"])} home">{MARK}<span>{md(c["header"]["name"])}</span></a>
  <a href="{root}">{md(hub["labels"]["header_link"])}</a>
</header>
"""


def page_foot(hub: dict, compare_link: str) -> str:
    return (f'<footer class="site-footer col">\n  <p class="notice">{md(hub["notice"]["text"])}</p>\n'
            f'  <p>{md(hub["footer"]["text"].replace("{compare}", compare_link))}</p>\n</footer>\n'
            "</body>\n</html>\n")


def crumbs(hub: dict, root: str, here: str, compare_link: str | None) -> str:
    lab = hub["labels"]
    items = [f'<li><a href="{root}">{md(lab["breadcrumb_home"])}</a></li>']
    if compare_link:
        items.append(f'<li><a href="{compare_link}">{md(lab["breadcrumb_compare"])}</a></li>')
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

""" + page_foot(hub, "../"))


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

""" + page_foot(hub, "./"))


def llms_txt(c: dict, hub: dict, pages: list[dict]) -> str:
    """llms.txt (llmstxt.org): a plain summary with links, for AI tools that read a site."""
    site = c["page"]["site_url"].rstrip("/")
    lines = [f"# {c['header']['name']}", "", f"> {plain(c['hero']['subline'])}", "",
             plain(hub["hermit"]["about"]), "",
             "## Pages", "", f"- [Home]({site}/): what it is, how to install it, questions and answers",
             f"- [Hermit CRM compared]({site}/compare/): {plain(hub['page']['description'])}", "",
             "## Comparisons", ""]
    lines += [f"- [Hermit CRM vs {p['name']}]({site}/compare/{p['slug']}/): {plain(p['short_answer'])}"
              for p in pages]
    lines += ["", "## Facts", ""]
    lines += [f"- {plain(r['label'])}: {plain(r['hermit'])}" for r in hub["rows"]]
    return "\n".join(lines) + "\n"


def build_compare(c: dict) -> tuple[dict, list[dict]]:
    """Write site/compare/ and site/llms.txt. Stale pages of a removed CRM are deleted."""
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
    if c["page"]["site_url"]:
        LLMS.write_text(llms_txt(c, hub, pages), encoding="utf-8")
    print(f"built site/compare/ ({len(pages)} comparisons) and site/llms.txt")
    return hub, pages


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


def check(c: dict, pages: list[dict] | None = None, hub: dict | None = None) -> tuple[list[str], list[str]]:
    problems, tbc = [], []
    texts = list(walk(c))
    if hub:
        texts += walk(hub, "compare/index")
    for p in pages or []:
        texts += walk({k: v for k, v in p.items() if k != "checked"}, f"compare/{p['slug']}")
    # Search results cut titles after about 60 characters and descriptions
    # after about 155; the page still works, but the end goes missing.
    snippets = [("page", c["page"]["title"], c["page"]["description"] or c["hero"]["subline"])]
    if hub:
        snippets.append(("compare/index", hub["page"]["title"], hub["page"]["description"]))
    snippets += [(f"compare/{p['slug']}", p["title"], p["description"]) for p in pages or []]
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
    # The comparison pages need the site's address for their canonical links,
    # so they are only built once [page].site_url is set.
    hub, pages = build_compare(c) if site_url else (None, [])
    ld = jsonld(website(c), software(c, hub)) if hub else ""
    OUT.write_text(render(c, ld), encoding="utf-8")
    print(f"built {OUT.relative_to(ROOT)} and {APP_TOKENS.relative_to(ROOT)}")
    crawl(site_url, pages)
    problems, tbc = check(c, pages, hub)
    return c, problems, tbc


def crawl(site_url: str, pages: list[dict] = ()) -> None:
    """Write robots.txt and sitemap.xml for search engines, or drop them while
    the site has no address yet (a sitemap needs absolute URLs)."""
    robots, sitemap = SITE / "robots.txt", SITE / "sitemap.xml"
    if not site_url:
        robots.unlink(missing_ok=True)
        sitemap.unlink(missing_ok=True)
        LLMS.unlink(missing_ok=True)
        return
    robots.write_text(f"User-agent: *\nAllow: /\n\nSitemap: {site_url}/sitemap.xml\n",
                      encoding="utf-8")
    urls = [f"  <url><loc>{html.escape(site_url)}/</loc></url>"]
    if pages:
        newest = max(p["checked"] for p in pages).isoformat()
        urls.append(f"  <url><loc>{html.escape(site_url)}/compare/</loc><lastmod>{newest}</lastmod></url>")
        urls += [f"  <url><loc>{html.escape(site_url)}/compare/{p['slug']}/</loc>"
                 f"<lastmod>{p['checked'].isoformat()}</lastmod></url>" for p in pages]
    sitemap.write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                       '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                       + "\n".join(urls) + "\n</urlset>\n", encoding="utf-8")
    print("built site/robots.txt and site/sitemap.xml")


def share(c: dict) -> None:
    """Render the 1200 x 630 share image with Playwright."""
    from playwright.sync_api import sync_playwright  # pip install playwright

    page_html = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="app-tokens.css"><link rel="stylesheet" href="style.css"><style>
:root{{color-scheme:light}} body{{margin:0;width:1200px;height:630px;overflow:hidden}}
.s{{width:1200px;height:630px;box-sizing:border-box;padding:96px 120px;display:flex;flex-direction:column;justify-content:space-between}}
.s .brand svg{{width:58px;height:46px}} .s .brand span{{font-size:38px}}
.s h1{{font-size:112px;line-height:1}} .s p{{margin:0;font-size:28px;color:var(--muted)}}
</style></head><body><div class="s">
<div class="brand">{MARK}<span>{md(c["header"]["name"])}</span></div>
<div><h1>{md(c["hero"]["h1"])}</h1></div>
<p>{md(c["share"]["tagline"])}</p></div></body></html>"""
    tmp = SITE / "_share.html"
    tmp.write_text(page_html, encoding="utf-8")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1200, "height": 630})
            page.goto(tmp.as_uri())
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(SITE / "img" / "og.png"))
            browser.close()
    finally:
        tmp.unlink(missing_ok=True)
    print("built site/img/og.png")


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
        watched = lambda: [CONTENT, STYLE, TOKENS, *sorted(COMPARE.glob("*.toml"))]  # noqa: E731
        print("watching content.toml, compare/*.toml, site/style.css and the app's tokens.css (Ctrl+C to stop)")
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
