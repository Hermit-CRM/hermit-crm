#!/usr/bin/env python3
"""Build the Hermit CRM website from content.toml.

    python3 build.py            build site/index.html once
    python3 build.py --watch    rebuild whenever content.toml changes
    python3 build.py --share    also render site/img/og.png (needs Playwright)

Only the Python standard library is needed (3.11 or newer) for the page.
All words come from content.toml; the look is in site/style.css.
"""
from __future__ import annotations

import html
import re
import sys
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content.toml"
SITE = ROOT / "site"
OUT = SITE / "index.html"

BANNED = ["revolutionary", "supercharge", "seamless", "unlock", "powerful",
          "effortless", "game-changing", "next-generation", "ai-powered"]

# The Hermit CRM mark, cropped to the frame (from hermitcrm-mark.svg).
MARK = ('<svg viewBox="4.5 10.5 55 43" aria-hidden="true" focusable="false">'
        '<rect x="7" y="13" width="50" height="38" rx="7" fill="none" stroke="#17181A" stroke-width="5"/>'
        '<circle cx="24" cy="27" r="5.5" fill="#1E8A60"/>'
        '<path d="M16 43 a8 8 0 0 1 16 0 z" fill="#1E8A60"/>'
        '<rect x="38" y="25" width="12" height="4" rx="2" fill="#17181A"/>'
        '<rect x="38" y="34" width="8" height="4" rx="2" fill="#17181A"/></svg>')


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
    r, l = c["release"], c["links"]
    return (f'<p class="meta">Version {md(r["version"])} · <code>{html.escape(r["file"])}</code>'
            f' · {md(r["size"])} · <a href="{attr(l["sha256"])}">{md(c["hero"]["sha256_label"])}</a>'
            f' · {md(r["license"])}</p>')


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
    return (f'<div class="mock-box" role="img" aria-label="Placeholder drawing of the pipeline board">'
            f'<div class="mock" aria-hidden="true">'
            f'<div class="mock-side"><div class="mock-brand">{MARK}<span>Hermit CRM</span></div>{side}</div>'
            f'<div class="mock-main"><div class="mock-top"><div class="mock-title">Pipeline</div>'
            f'<div class="mock-tag">Placeholder · real screenshot [TBC]</div></div>'
            f'<div class="mock-cols">{board}</div></div></div></div>')


def render(c: dict) -> str:
    p, h, i, f = c["page"], c["hero"], c["install"], c["file"]
    description = flat(p["description"] or h["subline"])
    site_url = p["site_url"].rstrip("/")
    og = ""
    if site_url:
        og = (f'<meta property="og:url" content="{attr(site_url)}/">\n'
              f'<meta property="og:image" content="{attr(site_url)}/img/og.png">\n')
    github = f'<a href="{attr(c["links"]["github"])}">{md(c["header"]["github_label"])}</a>'

    steps = "\n".join(f"      <li><span>{md(s)}</span></li>" for s in i["steps"])
    features = "\n".join(f"      <dt>{md(x['name'])}</dt><dd>{md(x['text'])}</dd>"
                         for x in c["features"]["items"])
    principles = "\n".join(f"      <p><strong>{md(x['name'])}</strong> {md(x['text'])}</p>"
                           for x in c["principles"])
    reqs = "\n".join(f"      <li>{md(x)}</li>" for x in c["requirements"]["items"])
    faqs = "\n".join(
        f'      <details{" open" if q.get("open") else ""}><summary>{md(q["q"])}</summary>'
        f'<p>{md(q["a"])}</p></details>' for q in c["questions"]["items"])

    if f["screenshot"]:
        visual = (f'<img src="img/{attr(f["screenshot"])}" alt="{attr(f["screenshot_alt"])}" '
                  f'width="1600" height="1000" loading="lazy">')
    else:
        visual = mock()
    file_body = html.escape(f["file_body"].strip("\n"))
    footer = md(c["footer"]["text"].replace("{github}", "\x01")).replace("\x01", github)

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
{og}<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#F5F1E8">
<link rel="icon" href="img/favicon.svg" type="image/svg+xml">
<link rel="icon" href="img/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="img/apple-touch-icon.png">
<link rel="stylesheet" href="style.css">
</head>
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
        <button class="copy" type="button" data-copy="{attr(i["message"])}" data-done="{attr(i["copied_label"])}"
                aria-label="Copy the install message"><span aria-live="polite">{md(i["copy_button"])}</span></button>
      </div>
      <p class="note indent">{md(i["note"])}</p>
      <p class="manual indent"><a href="{attr(c["links"]["install_manual"])}">{md(i["manual_link"])}</a></p>
    </div>
  </section>

  <hr class="rule">

  <section class="features col" aria-labelledby="features">
    <h2 class="label" id="features">{md(c["features"]["label"])}</h2>
    <dl>
{features}
    </dl>
    <div class="principles">
{principles}
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
    <p class="after narrow">{md(f["after"])}</p>
  </section>

  <hr class="rule">

  <section class="requirements col" aria-labelledby="requirements">
    <h2 class="label" id="requirements">{md(c["requirements"]["label"])}</h2>
    <ul>
{reqs}
    </ul>
  </section>

  <hr class="rule">

  <section class="questions col" aria-labelledby="questions">
    <h2 class="label" id="questions">{md(c["questions"]["label"])}</h2>
    <div>
{faqs}
    </div>
  </section>

  <hr class="rule">

  <section class="col" aria-label="Download">
    {download_block(c)}
  </section>
</main>

<footer class="site-footer col">{footer}</footer>

<script>
// Copy button: copies the install message and says "Copied" for 2 seconds.
document.querySelectorAll("[data-copy]").forEach(function (btn) {{
  var label = btn.querySelector("span"), idle = label.textContent, timer;
  function fallback(text) {{
    var t = document.createElement("textarea");
    t.value = text; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select();
    try {{ document.execCommand("copy"); }} catch (e) {{}}
    document.body.removeChild(t);
  }}
  btn.addEventListener("click", function () {{
    var text = btn.dataset.copy;
    if (navigator.clipboard && window.isSecureContext) {{
      navigator.clipboard.writeText(text).catch(function () {{ fallback(text); }});
    }} else {{ fallback(text); }}
    label.textContent = btn.dataset.done;
    clearTimeout(timer);
    timer = setTimeout(function () {{ label.textContent = idle; }}, 2000);
  }});
}});
</script>
</body>
</html>
"""


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


def check(c: dict) -> None:
    problems, tbc = [], []
    for path, text in walk(c):
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
    if c["file"]["screenshot"] and not (SITE / "img" / c["file"]["screenshot"]).exists():
        print(f"  warning  site/img/{c['file']['screenshot']} does not exist")


def build() -> dict:
    c = tomllib.loads(CONTENT.read_text(encoding="utf-8"))
    OUT.write_text(render(c), encoding="utf-8")
    print(f"built {OUT.relative_to(ROOT)}")
    check(c)
    return c


def share(c: dict) -> None:
    """Render the 1200 x 630 share image with Playwright."""
    from playwright.sync_api import sync_playwright  # pip install playwright

    page_html = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="style.css"><style>
body{{margin:0;width:1200px;height:630px;overflow:hidden}}
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
    c = build()
    if "--share" in sys.argv:
        share(c)
    if "--watch" in sys.argv:
        print("watching content.toml (Ctrl+C to stop); style.css changes need only a reload")
        seen = CONTENT.stat().st_mtime
        while True:
            time.sleep(0.5)
            now = CONTENT.stat().st_mtime
            if now != seen:
                seen = now
                try:
                    build()
                except tomllib.TOMLDecodeError as e:
                    print(f"  content.toml has a mistake: {e}")


if __name__ == "__main__":
    main()
