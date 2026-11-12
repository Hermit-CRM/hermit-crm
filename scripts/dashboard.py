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

"""A local dashboard for the numbers scripts/downloads.py collects.

    dashboard.py serve            http://127.0.0.1:8777, with a Refresh button that runs `collect`
                                  and a Live section that updates every 10 minutes while the page is in front
    dashboard.py serve --open     ...and open it in the browser
    dashboard.py build            write dashboard.html into the data folder (no Refresh button)

Maintainer tool, not part of the installed package. Standard library only; the
charts are inline SVG drawn by a few lines of JavaScript in the page itself, so
nothing is downloaded and no third party is asked. The server listens on
127.0.0.1 only.

It adds no counting rules of its own: what is a real install, a bot, or yours is
decided in downloads.py (pypi_bucket, website_events), so the report and the
dashboard cannot disagree.
"""
import argparse
import html
import json
import sys
import threading
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import downloads as dl

TOKENS_CSS = Path(__file__).resolve().parent.parent / "src" / "hermitcrm" / "static" / "tokens.css"
# Not 8765: that is the Hermit CRM app's own port, and the app is usually running.
PORT = 8777


def day_range(first: str, last: str) -> list[str]:
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    return [(a + timedelta(days=n)).isoformat() for n in range((b - a).days + 1)]


def page_name(path: str) -> str:
    """/index.html is how nginx logs the home page and every folder's page."""
    return path.removesuffix("index.html") or "/"


def campaign(row: dict) -> str:
    """The tag on a link you posted: https://hermitcrm.io/?ref=hn (or utm_source=hn)."""
    q = parse_qs(row.get("q", ""))
    return (q.get("ref") or q.get("utm_source") or [""])[0][:40]


def count_by(rows: list[dict], key, weight=lambda r: 1) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[key(r)] = out.get(key(r), 0) + weight(r)
    return out


LIVE_MINUTES = 10      # one column of the live chart, and how often the open page asks for new data
LIVE_SLOTS = 144       # 24 hours of those
LIVE_RECENT = 12       # rows in "latest page views"
LIVE_SERIES = ("Arrivals", "Other page views", "AI crawlers and assistants")


def utc_time(row: dict) -> datetime:
    return datetime.fromisoformat(row["t"]).astimezone(timezone.utc)


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def live_summary(visits: dict[str, list[dict]], now: datetime, collected: str | None = None) -> dict:
    """The last 24 hours in 10-minute columns, from the rows downloads.visit_events sorted.

    `now` is passed in (not read here) so the same rows give the same answer in a test. The last
    column is the slot still filling, so it grows until the next one begins. Times go out as
    UTC strings; the page shows them in the viewer's own time zone. Same rules as everywhere
    else: bots, scripts and your own hits are not in it, and an arrival is a person who came from outside."""
    now = now.astimezone(timezone.utc)
    current = now.replace(minute=now.minute - now.minute % LIVE_MINUTES, second=0, microsecond=0)
    starts = [current - timedelta(minutes=LIVE_MINUTES * n) for n in range(LIVE_SLOTS - 1, -1, -1)]
    where = {s: i for i, s in enumerate(starts)}
    series = {name: [0] * LIVE_SLOTS for name in LIVE_SERIES}

    def add(rows, name):
        for r in rows:
            t = utc_time(r)
            i = where.get(t.replace(minute=t.minute - t.minute % LIVE_MINUTES, second=0, microsecond=0))
            if i is not None and t <= now:
                series[name][i] += 1

    people = visits["people"]
    arrivals = [r for r in people if dl.is_arrival(r)]
    add(arrivals, "Arrivals")
    add([r for r in people if not dl.is_arrival(r)], "Other page views")
    add(visits["ai"], "AI crawlers and assistants")

    def since(rows, minutes):
        edge = now - timedelta(minutes=minutes)
        return sum(1 for r in rows if edge < utc_time(r) <= now)

    newest = sorted(people, key=lambda r: (r["t"], r["id"]), reverse=True)
    return {
        "now": stamp(now),
        "slots": [stamp(s) for s in starts],
        "series": series,
        "tiles": {"arrivals_10m": since(arrivals, 10), "arrivals_1h": since(arrivals, 60),
                  "arrivals_24h": since(arrivals, 24 * 60), "views_1h": since(people, 60)},
        "last_arrival": stamp(max(map(utc_time, arrivals))) if arrivals else None,
        "recent": [{"t": stamp(utc_time(r)), "page": page_name(r["path"]),
                    "arrival": dl.is_arrival(r), "from": r.get("ref") or "direct", "tag": campaign(r)}
                   for r in newest[:LIVE_RECENT]],
        "collected": collected,
    }


def live_for(data_dir: Path, now: datetime | None = None) -> dict | None:
    """live_summary from the saved page log; None before there is one."""
    vpath = data_dir / "visits.jsonl"
    if not vpath.exists():
        return None
    visits = dl.visit_events(dl.parse_log(vpath.read_text()), dl.read_ignored(data_dir))
    spath = data_dir / "status.json"
    status = json.loads(spath.read_text()) if spath.exists() else {}
    return live_summary(visits, now or datetime.now(timezone.utc), status.get("visits", {}).get("last_ok"))


def summarize(data_dir: Path, today: str | None = None, now: datetime | None = None) -> dict:
    """Everything the page shows, as plain data, from the files `collect` saved."""
    now = now or datetime.now(timezone.utc)
    today = today or now.strftime("%Y-%m-%d")

    pypi = dl.read_csv(data_dir / "pypi-downloads.csv")
    buckets = {b: 0 for b in ("installs", "ci", "browser", "scripts", "unknown", "mirrors", "other")}
    for r in pypi:
        buckets[dl.pypi_bucket(r)] += int(r["downloads"])
    installs = [r for r in pypi if dl.pypi_bucket(r) == "installs"]
    pypi_per_day = count_by(installs, lambda r: r["day"], lambda r: int(r["downloads"]))

    assets = dl.read_csv(data_dir / "github-assets.csv")
    latest = max((r["day"] for r in assets), default=None)
    current = [r for r in assets if r["day"] == latest]
    github_total = sum(int(r["downloads"]) for r in current)
    traffic = {r["day"]: r for r in dl.read_csv(data_dir / "github-traffic.csv")}

    repo_rows = sorted(dl.read_csv(data_dir / "github-repo.csv"), key=lambda r: r["day"])
    repo = repo_rows[-1] if repo_rows else None
    stars = {r["day"]: int(r["stars"]) for r in dl.read_csv(data_dir / "github-stars.csv")}
    referrers = {r["referrer"]: int(r["uniques"]) for r in dl.latest_snapshot(dl.read_csv(data_dir / "github-referrers.csv"), "uniques")}
    gh_paths = {r["path"]: int(r["uniques"]) for r in dl.latest_snapshot(dl.read_csv(data_dir / "github-paths.csv"), "uniques")}

    path = data_dir / "website.jsonl"
    site = (dl.website_events(dl.parse_log(path.read_text()), dl.read_ignored(data_dir)) if path.exists()
            else dict.fromkeys(("downloads", "aborted", "bots", "mine"), []))
    site_per_day = count_by(site["downloads"], lambda r: r["t"][:10])

    vpath = data_dir / "visits.jsonl"
    visits = (dl.visit_events(dl.parse_log(vpath.read_text()), dl.read_ignored(data_dir)) if vpath.exists()
              else None)
    people = visits["people"] if visits else []
    arrivals = [r for r in people if dl.is_arrival(r)]
    arrivals_per_day = count_by(arrivals, lambda r: r["t"][:10])
    ai_per_day = count_by(visits["ai"], lambda r: r["t"][:10]) if visits else {}

    known = [d for d in (*pypi_per_day, *site_per_day, *traffic, *stars, *arrivals_per_day, *ai_per_day) if d]
    first = min(known, default=today)
    days = day_range(first, max(today, *known)) if known else [today]

    def versions(r: dict) -> str:
        return r["version"]

    site_version = lambda r: r["path"].removeprefix("/download/hermitcrm-").removesuffix(".tar.gz")
    version_rows = {}
    for label, counts in (("pypi", count_by(installs, versions, lambda r: int(r["downloads"]))),
                          ("website", count_by(site["downloads"], site_version)),
                          ("github", count_by(current, lambda r: r["tag"].lstrip("v"), lambda r: int(r["downloads"])))):
        for v, n in counts.items():
            version_rows.setdefault(v, {"pypi": 0, "website": 0, "github": 0})[label] = n

    best = buckets["installs"] + github_total + len(site["downloads"])
    status_path = data_dir / "status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    return {
        "today": today,
        "live": None if visits is None else live_summary(visits, now, status.get("visits", {}).get("last_ok")),
        "tiles": {"best": best, "pypi": buckets["installs"], "github": github_total,
                  "website": len(site["downloads"])},
        "days": days,
        "downloads_per_day": {"PyPI installs": [pypi_per_day.get(d, 0) for d in days],
                              "Website downloads": [site_per_day.get(d, 0) for d in days]},
        "github": None if repo is None else {
            "stars": int(repo["stars"]), "forks": int(repo["forks"]), "watchers": int(repo["watchers"]),
            "as_of": repo["day"], "referrers": referrers, "paths": gh_paths},
        "stars_per_day": {"New stars": [stars.get(d, 0) for d in days]},
        "github_traffic": {"Unique visitors": [int(traffic.get(d, {}).get("views_unique", 0)) for d in days],
                           "Unique cloners": [int(traffic.get(d, {}).get("clones_unique", 0)) for d in days]},
        "has_traffic": bool(traffic),
        "visits": None if visits is None else {
            "arrivals": len(arrivals), "page_views": len(people), "ai": len(visits["ai"]),
            "per_day": {"Arrivals": [arrivals_per_day.get(d, 0) for d in days]},
            "ai_per_day": {"AI crawlers and assistants": [ai_per_day.get(d, 0) for d in days]},
            "pages": dict(sorted(count_by(people, lambda r: page_name(r["path"])).items(), key=lambda kv: -kv[1])[:10]),
            "sources": dict(sorted(dl.count_hosts(arrivals).items(), key=lambda kv: -kv[1])[:10]),
            "campaigns": dict(sorted(count_by(
                [r for r in arrivals if campaign(r)], campaign).items(), key=lambda kv: -kv[1])),
            "ai_names": dict(sorted(count_by(visits["ai"], lambda r: dl.ai_name(r["ua"])).items(), key=lambda kv: -kv[1])),
            "left_out": [("Bots and link previews", len(visits["bots"])),
                         ("Scripts (curl, python...)", len(visits["scripts"])),
                         ("Yours (?own, ignore.txt, other host)", len(visits["mine"]))],
        },
        "versions": dict(sorted(version_rows.items(), key=lambda kv: kv[0], reverse=True)),
        "countries": dict(sorted(count_by(installs, lambda r: r["country"] or "unknown",
                                          lambda r: int(r["downloads"])).items(), key=lambda kv: -kv[1])),
        "installers": count_by(installs, lambda r: r["installer"], lambda r: int(r["downloads"])),
        "pythons": count_by(installs, lambda r: r["python"] or "unknown", lambda r: int(r["downloads"])),
        "filtered": [
            ("PyPI: pip/uv in CI", buckets["ci"]),
            ("PyPI: browser downloads", buckets["browser"]),
            ("PyPI: Python scripts (requests)", buckets["scripts"]),
            ("PyPI: unknown clients (curl, scanners)", buckets["unknown"]),
            ("PyPI: mirrors", buckets["mirrors"]),
            ("PyPI: other clients", buckets["other"]),
            ("Website: aborted before the end", len(site["aborted"])),
            ("Website: bots and crawlers", len(site["bots"])),
            ("Website: yours (?own, selftest, ignore.txt)", len(site["mine"])),
        ],
        "status": status,
    }


# --- the page ----------------------------------------------------------------

CSS = """
:root{--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--chart-grid:var(--line);--chart-axis:var(--muted)}
@media (prefers-color-scheme:dark){:root[data-theme="system"]{--s1:#3987e5;--s2:#d95926;--s3:#199e70}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 var(--sans)}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
h1{font:500 24px/1.2 var(--title-font);margin:0}
h2{font:600 11px/1 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:32px 0 12px}
header{display:flex;flex-wrap:wrap;gap:12px 16px;align-items:center;justify-content:space-between}
.sub{color:var(--muted);margin:4px 0 0}
button{font:inherit;color:var(--text);background:var(--surface);border:1px solid var(--line-strong);
  border-radius:6px;padding:6px 12px;cursor:pointer}
button:hover{background:var(--subtle)}
button[aria-pressed="true"]{background:var(--subtle);border-color:var(--text);font-weight:600}
button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button[disabled]{opacity:.6;cursor:wait}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.tile .label{color:var(--muted)}
.tile .value{font:600 32px/1.1 var(--sans);margin-top:4px}
.tile.hero .value{font-size:48px}
.tile .note{color:var(--faint);font-size:12px;margin-top:4px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:16px;margin-bottom:12px}
.card h3{font:600 14px/1.2 var(--sans);margin:0 0 2px}
.card .sub{margin-bottom:10px}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:8px 0 0;color:var(--muted)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.filters .label{color:var(--muted);margin-right:4px}
.chart{position:relative}
.chart svg{display:block;width:100%;height:auto;overflow:visible}
.chart text{fill:var(--chart-axis);font:11px var(--sans)}
.chart .grid{stroke:var(--chart-grid);stroke-width:1}
.chart .col{fill:transparent;outline:none}
.chart .col:hover,.chart .col:focus{fill:color-mix(in srgb,var(--text) 6%,transparent)}
.tip{position:absolute;pointer-events:none;background:var(--surface);color:var(--text);border:1px solid var(--line-strong);
  border-radius:6px;padding:8px 10px;box-shadow:var(--shadow);font-size:12px;white-space:nowrap;z-index:2}
.tip[hidden]{display:none}
.tip b{font-size:14px}
.tip .k{display:inline-block;width:10px;height:2px;margin-right:6px;vertical-align:middle}
.tip .d{color:var(--muted);margin-bottom:4px}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
table{border-collapse:collapse;width:100%}
th{font:600 11px var(--sans);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);text-align:left}
th,td{padding:6px 8px;border-bottom:1px solid var(--line)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}
.zero{color:var(--faint)}
details{margin-top:8px}summary{cursor:pointer;color:var(--muted)}
.ok{color:var(--ok)}.bad{color:var(--danger)}
.empty{color:var(--muted);padding:24px 0}
.hint{color:var(--muted);font-size:12px}
.kind{display:inline-block;border:1px solid var(--line-strong);border-radius:999px;padding:0 8px;font-size:11px;color:var(--muted)}
.kind.arrival{border-color:var(--s1);color:var(--s1)}
td.when{white-space:nowrap}
.scroll{overflow-x:auto}
@media (max-width:520px){.tile.hero .value{font-size:40px}}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const COLOR = {'PyPI installs': 'var(--s1)', 'Website downloads': 'var(--s2)',
  'Unique visitors': 'var(--s1)', 'Unique cloners': 'var(--s2)',
  'Arrivals': 'var(--s1)', 'Other page views': 'var(--s2)', 'New stars': 'var(--s1)', 'AI crawlers and assistants': 'var(--s3)'};
let range = 30;
const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };
const fmtDay = d => new Date(d + 'T00:00:00Z').toLocaleDateString(undefined, {day: 'numeric', month: 'short', timeZone: 'UTC'});
// Four whole-number gridlines: the step is 1, 2, 5 or 10 times a power of ten, the top is four steps up.
const niceMax = m => { const raw = Math.max(m, 4) / 4, p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const s of [1, 2, 5, 10]) if (raw <= s * p) return 4 * s * p; return 40 * p; };

function topRounded(x, y, w, h, r) {
  r = Math.min(r, h, w / 2);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

// Stacked daily columns. Segments touch with a 2px surface gap; only the top one is rounded.
function columns(host, days, series, names, fmt = {axis: fmtDay, full: fmtDay}) {
  host.querySelectorAll('svg').forEach(s => s.remove());
  const W = Math.max(280, host.clientWidth), H = 220, L = 36, B = 22, T = 8, R = 4;
  const n = days.length, totals = days.map((_, i) => names.reduce((a, k) => a + series[k][i], 0));
  const max = niceMax(Math.max(0, ...totals));
  const svg = el('svg', {viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': host.dataset.label}, host);
  const y = v => T + (H - T - B) * (1 - v / max);
  for (let t = 0; t <= 4; t++) { const v = max * t / 4;
    el('line', {x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'grid'}, svg);
    el('text', {x: L - 6, y: y(v) + 4, 'text-anchor': 'end'}, svg).textContent = Math.round(v).toLocaleString(); }
  const slot = (W - L - R) / n, bw = Math.min(24, slot * 0.7);
  const every = Math.ceil(n / Math.max(2, Math.floor((W - L) / 70)));  // a label needs about 70px
  days.forEach((d, i) => {
    const cx = L + slot * (i + 0.5);
    if (i % every === 0 || i === n - 1) el('text', {x: cx, y: H - 6, 'text-anchor': 'middle'}, svg).textContent = fmt.axis(d);
    let base = H - B;
    const live = names.filter(k => series[k][i] > 0);
    live.forEach((k, j) => {
      const hh = Math.max((H - T - B) * series[k][i] / max, 1), top = j === live.length - 1;
      const yy = base - hh;
      if (top) el('path', {d: topRounded(cx - bw / 2, yy, bw, hh, 4), fill: COLOR[k]}, svg);
      else el('rect', {x: cx - bw / 2, y: yy, width: bw, height: hh, fill: COLOR[k]}, svg);
      base = yy - 2;
    });
    const hit = el('rect', {x: cx - slot / 2, y: T, width: slot, height: H - T - B, class: 'col', tabindex: 0,
      'aria-label': `${fmt.full(d)}: ` + names.map(k => `${k} ${series[k][i]}`).join(', ')}, svg);
    const show = () => tip(host, hit, d, series, names, i, fmt);
    hit.addEventListener('pointermove', show); hit.addEventListener('focus', show);
    hit.addEventListener('pointerleave', () => host.querySelector('.tip').hidden = true);
    hit.addEventListener('blur', () => host.querySelector('.tip').hidden = true);
  });
}

function tip(host, hit, d, series, names, i, fmt) {
  const t = host.querySelector('.tip'); t.replaceChildren();
  const head = document.createElement('div'); head.className = 'd'; head.textContent = fmt.full(d); t.appendChild(head);
  names.forEach(k => { const row = document.createElement('div');
    const key = document.createElement('span'); key.className = 'k'; key.style.background = COLOR[k];
    const v = document.createElement('b'); v.textContent = series[k][i].toLocaleString();
    row.append(key, v, ' ' + k); t.appendChild(row); });
  t.hidden = false;
  const r = hit.getBoundingClientRect(), h = host.getBoundingClientRect();
  const left = r.left - h.left + r.width / 2 - t.offsetWidth / 2;
  t.style.left = Math.max(0, Math.min(left, h.width - t.offsetWidth)) + 'px';
  t.style.top = '0px';
}

function slice(series, n) { const out = {}; for (const k in series) out[k] = n ? series[k].slice(-n) : series[k]; return out; }

function draw() {
  const n = range || D.days.length, days = D.days.slice(-n);
  document.querySelectorAll('[data-chart]').forEach(host => {
    const src = D.series[host.dataset.chart];
    const sel = host.dataset.series ? [host.dataset.series] : Object.keys(src);
    columns(host, days, slice(src, n), sel);
  });
  document.querySelectorAll('[data-range]').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.range === range)));
}
document.querySelectorAll('[data-range]').forEach(b => b.addEventListener('click', () => { range = +b.dataset.range; draw(); }));
draw();

// Live: the last 24 hours in 10-minute columns. While this page is the one in front it asks the server for
// the newest page requests every 10 minutes (POST /live/refresh); a hidden tab asks for nothing, so a
// dashboard left open overnight does not keep the site's machine awake.
const LIVE_MS = 10 * 60 * 1000;
const clock = t => new Date(t).toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit'});
const SLOT = {axis: clock, full: t => { const a = new Date(t);
  return a.toLocaleDateString(undefined, {weekday: 'short'}) + ' ' + clock(a) + '–' + clock(a.getTime() + LIVE_MS); }};
const ago = t => { const m = Math.floor((Date.now() - new Date(t)) / 60000);
  return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.floor(m / 60) + ' h ago' : Math.floor(m / 1440) + ' d ago'; };
const say = (id, value) => { document.getElementById(id).textContent = value; };
let nextAt = 0, busy = false, updated = 0, problem = '';

function drawLive() {
  const L = D.live; if (!L) return;
  say('live-10m', L.tiles.arrivals_10m.toLocaleString());
  say('live-1h', L.tiles.arrivals_1h.toLocaleString());
  say('live-24h', L.tiles.arrivals_24h.toLocaleString());
  say('live-last', L.last_arrival ? 'last one ' + ago(L.last_arrival) : 'none in the log yet');
  columns(document.querySelector('[data-live-chart]'), L.slots, L.series, Object.keys(L.series), SLOT);
  const body = document.getElementById('live-recent'); body.replaceChildren();
  const cell = (tr, text, cls) => { const td = document.createElement('td'); td.textContent = text; if (cls) td.className = cls; tr.appendChild(td); return td; };
  L.recent.forEach(r => { const tr = document.createElement('tr');
    cell(tr, clock(r.t) + ', ' + ago(r.t), 'when');
    const kind = document.createElement('span'); kind.className = 'kind' + (r.arrival ? ' arrival' : '');
    kind.textContent = r.arrival ? 'arrival' : 'view'; cell(tr, '').appendChild(kind);
    cell(tr, r.page); cell(tr, r.arrival ? r.from : '–'); cell(tr, r.tag || '');
    body.appendChild(tr); });
  if (!L.recent.length) { const tr = document.createElement('tr'); cell(tr, 'No page views by people yet.').colSpan = 5; body.appendChild(tr); }
}

function tick() {
  if (!D.live) return;
  const secs = Math.max(0, Math.round((nextAt - Date.now()) / 1000));
  const next = Math.floor(secs / 60) + ':' + String(secs % 60).padStart(2, '0');
  say('live-status', busy ? 'Updating…' : problem
    ? 'Could not update (' + problem + '). Showing what is saved' + (D.live.collected ? ', from ' + clock(D.live.collected) : '') + '. Trying again in ' + next + '.'
    : 'Updated ' + clock(updated) + '. Next update in ' + next + '.');
  if (!busy && !document.hidden && Date.now() >= nextAt) liveRefresh();
}

async function liveRefresh() {
  busy = true; tick();
  try {
    const r = await fetch('/live/refresh', {method: 'POST'}), j = await r.json();
    if (j.live) { D.live = j.live; drawLive(); }
    problem = j.ok ? '' : (j.error || 'the page log could not be fetched');
    if (j.ok) updated = Date.now();
  } catch (e) { problem = String(e); }
  busy = false; nextAt = Date.now() + LIVE_MS; tick();
}

let resizing; addEventListener('resize', () => { clearTimeout(resizing); resizing = setTimeout(() => { draw(); drawLive(); }, 100); });
drawLive();
if (D.live && document.body.dataset.live === 'on') setInterval(tick, 1000), tick();
else if (D.live) say('live-status', 'Static copy, as of when the page was built. Run dashboard.py serve for live updates.');

const refresh = document.getElementById('refresh');
if (refresh) refresh.addEventListener('click', async () => {
  refresh.disabled = true; refresh.textContent = 'Collecting…';
  try { const r = await fetch('/refresh', {method: 'POST'}); const j = await r.json();
    if (!j.ok) alert('Some sources failed: ' + j.failed.join(', ') + '. The dashboard shows what is saved.'); }
  catch (e) { alert('Refresh failed: ' + e); }
  location.reload();
});
"""


def esc(s) -> str:
    return html.escape(str(s))


def count_table(rows: dict, head: tuple[str, str]) -> str:
    if not rows:
        return '<p class="empty">Nothing yet.</p>'
    body = "".join(f"<tr><td>{esc(k)}</td><td class='n'>{v:,}</td></tr>" for k, v in rows.items())
    return f"<table><thead><tr><th>{esc(head[0])}</th><th class='n'>{esc(head[1])}</th></tr></thead><tbody>{body}</tbody></table>"


def tile(label: str, value: int, note: str, hero: bool = False) -> str:
    return (f'<div class="tile{" hero" if hero else ""}"><div class="label">{esc(label)}</div>'
            f'<div class="value">{value:,}</div><div class="note">{esc(note)}</div></div>')


def render(summary: dict, live: bool, generated: str | None = None) -> str:
    s = summary
    generated = generated or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    tokens = TOKENS_CSS.read_text() if TOKENS_CSS.exists() else ""

    versions = "".join(
        f"<tr><td>{esc(v)}</td>" + "".join(f"<td class='n{' zero' if not c[k] else ''}'>{c[k]:,}</td>"
                                           for k in ("pypi", "website", "github")) + "</tr>"
        for v, c in s["versions"].items())
    versions = (f"<table><thead><tr><th>Version</th><th class='n'>PyPI</th><th class='n'>Website</th>"
                f"<th class='n'>GitHub</th></tr></thead><tbody>{versions}</tbody></table>"
                if versions else '<p class="empty">Nothing yet.</p>')
    filtered = "".join(f"<tr><td>{esc(k)}</td><td class='n{' zero' if not v else ''}'>{v:,}</td></tr>"
                       for k, v in s["filtered"])
    status = "".join(
        f"<tr><td>{esc(name)}</td><td class='{'ok' if st.get('ok') else 'bad'}'>"
        f"{'ok' if st.get('ok') else 'FAILING: ' + esc(st.get('error', ''))}</td>"
        f"<td>{esc(st.get('last_ok', 'never'))}</td><td>{esc(st.get('detail', ''))}</td></tr>"
        for name, st in s["status"].items())
    status = (f"<table><thead><tr><th>Source</th><th>State</th><th>Last good run</th><th>What it fetched</th></tr></thead>"
              f"<tbody>{status}</tbody></table>" if status
              else '<p class="empty">No data saved yet. Press Refresh, or run <code>downloads.py collect</code>.</p>')

    names = list(s["downloads_per_day"])
    legend = "".join(f'<span><i style="background:var(--s{i + 1})"></i>{esc(n)}</span>' for i, n in enumerate(names))
    refresh = ('<button id="refresh" type="button">Refresh</button>' if live else
               '<span class="hint">Static copy: run <code>dashboard.py serve</code> for the Refresh button.</span>')
    ranges = "".join(f'<button type="button" data-range="{n}" aria-pressed="false">{label}</button>'
                     for n, label in ((7, "7 days"), (30, "30 days"), (90, "90 days"), (0, "All")))
    traffic = ""
    if s["has_traffic"]:
        traffic = f"""
<div class="two">
  <div class="card"><h3>GitHub: unique visitors</h3><p class="sub">Per day, as GitHub reports it (14-day window, saved by each collect)</p>
    <div class="chart" data-chart="traffic" data-series="Unique visitors" data-label="Unique GitHub visitors per day"><div class="tip" hidden></div></div></div>
  <div class="card"><h3>GitHub: unique cloners</h3><p class="sub">Includes your own checkouts and CI</p>
    <div class="chart" data-chart="traffic" data-series="Unique cloners" data-label="Unique GitHub cloners per day"><div class="tip" hidden></div></div></div>
</div>"""
    t = s["tiles"]
    v = s["visits"]
    series = {"downloads": s["downloads_per_day"], "traffic": s["github_traffic"], "stars": s["stars_per_day"],
              **({"visits": v["per_day"], "ai": v["ai_per_day"]} if v else {})}
    data = json.dumps({"days": s["days"], "series": series, "live": s["live"]}).replace("</", "<\\/")
    g = s["github"]
    github = ""
    if g:
        github = f"""
<h2>GitHub</h2>
<div class="tiles">
  {tile("Stars", g["stars"], f"as of {g['as_of']}")}
  {tile("Forks", g["forks"], f"as of {g['as_of']}")}
  {tile("Watching", g["watchers"], f"as of {g['as_of']}")}
</div>
<div class="two">
  <div class="card"><h3>New stars per day</h3><p class="sub">From the stargazer list, so it has the full history</p>
    <div class="chart" data-chart="stars" data-label="New GitHub stars per day"><div class="tip" hidden></div></div></div>
  <div class="card"><h3>Where GitHub visitors came from</h3><p class="sub">Unique visitors, last 14 days</p>
    {count_table(g["referrers"], ("Referrer", "Visitors"))}</div>
  <div class="card"><h3>Pages on GitHub</h3><p class="sub">Unique visitors, last 14 days</p>
    {count_table(g["paths"], ("Path", "Visitors"))}</div>
</div>"""
    visitors = ""
    if v:
        left_out = "".join(f"<tr><td>{esc(k)}</td><td class='n{' zero' if not n else ''}'>{n:,}</td></tr>"
                           for k, n in v["left_out"])
        visitors = f"""
<h2>Visitors</h2>
<div class="tiles">
  {tile("Arrivals on the website", v["arrivals"], "people who came from outside the site", hero=True)}
  {tile("Page views by people", v["page_views"], "includes clicks between pages")}
  {tile("AI crawlers and assistants", v["ai"], "page requests, not counted as visitors")}
</div>
<p class="hint">No IP address or cookie is kept, so a person who comes back counts again. An arrival is a page view that began
  at a link, a bookmark or the address bar; a click from one page of the site to another is not one.</p>
<div class="two">
  <div class="card"><h3>Arrivals per day</h3><p class="sub">People, bots left out</p>
    <div class="chart" data-chart="visits" data-label="Website arrivals per day"><div class="tip" hidden></div></div></div>
  <div class="card"><h3>AI crawlers and assistants per day</h3><p class="sub">Page requests</p>
    <div class="chart" data-chart="ai" data-label="AI crawler requests per day"><div class="tip" hidden></div></div></div>
  <div class="card"><h3>Where arrivals came from</h3>{count_table(v["sources"], ("Referrer host", "Arrivals"))}</div>
  <div class="card"><h3>Pages people looked at</h3>{count_table(v["pages"], ("Page", "Views"))}</div>
  <div class="card"><h3>Tagged links</h3><p class="sub">Arrivals on a link with <code>?ref=</code> or <code>utm_source=</code>, e.g. a post you wrote</p>
    {count_table(v["campaigns"], ("Tag", "Arrivals"))}</div>
  <div class="card"><h3>Which AI</h3>{count_table(v["ai_names"], ("Crawler", "Requests"))}</div>
  <div class="card"><h3>Left out</h3><table><tbody>{left_out}</tbody></table></div>
</div>"""
    else:
        visitors = ('<h2>Visitors</h2><div class="card"><p class="empty">No page log saved yet. Deploy <code>website/</code>, '
                    'then Refresh.</p></div>')

    # Filled in by the page's JavaScript from the data below, on load and after every update.
    live_panel = ""
    if s["live"]:
        live_legend = "".join(f'<span><i style="background:var(--s{i + 1})"></i>{esc(n)}</span>'
                              for i, n in enumerate(LIVE_SERIES))
        live_panel = f"""
<h2>Live</h2>
<p class="hint" id="live-status" role="status"></p>
<div class="tiles">
  <div class="tile hero"><div class="label">Arrivals, last 10 minutes</div><div class="value" id="live-10m">0</div>
    <div class="note" id="live-last"></div></div>
  <div class="tile"><div class="label">Arrivals, last hour</div><div class="value" id="live-1h">0</div>
    <div class="note">people who came from outside the site</div></div>
  <div class="tile"><div class="label">Arrivals, last 24 hours</div><div class="value" id="live-24h">0</div>
    <div class="note">same rules as Visitors below</div></div>
</div>
<div class="card"><h3>Last 24 hours</h3><p class="sub">Per 10 minutes, in your time zone. The last column is still filling.</p>
  <div class="chart" data-live-chart data-label="Website visits in the last 24 hours, per 10 minutes"><div class="tip" hidden></div></div>
  <div class="legend">{live_legend}</div></div>
<div class="card"><h3>Latest page views by people</h3>
  <div class="scroll"><table><thead><tr><th>When</th><th>What</th><th>Page</th><th>From</th><th>Tag</th></tr></thead>
  <tbody id="live-recent"></tbody></table></div></div>"""

    return f"""<!doctype html>
<html lang="en" data-theme="system">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermit CRM numbers</title>
<style>{tokens}</style>
<style>{CSS}</style>
</head>
<body data-live="{'on' if live else 'off'}"><main>
<header>
  <div><h1>Hermit CRM numbers</h1>
  <p class="sub">Real downloads, bots and your own hits left out. Page built {esc(generated)}.</p></div>
  {refresh}
</header>

{live_panel}

<div class="filters"><span class="label">Show</span>{ranges}</div>

{visitors}

<h2>All time</h2>
<div class="tiles">
  {tile("Best estimate of real downloads", t["best"], "PyPI installs + GitHub + website", hero=True)}
  {tile("PyPI installs", t["pypi"], "pip and uv, CI left out")}
  {tile("GitHub release downloads", t["github"], "asset counters, GitHub's own filtering")}
  {tile("Website downloads", t["website"], "completed tarball downloads")}
</div>

<h2>Per day</h2>
<div class="card"><h3>Real downloads</h3><p class="sub">PyPI installs and website downloads, stacked</p>
  <div class="chart" data-chart="downloads" data-label="Real downloads per day"><div class="tip" hidden></div></div>
  <div class="legend">{legend}</div></div>
{traffic}

{github}

<h2>Downloads: who and what</h2>
<div class="two">
  <div class="card"><h3>By version</h3>{versions}</div>
  <div class="card"><h3>PyPI installs by country</h3>{count_table(s["countries"], ("Country", "Installs"))}</div>
  <div class="card"><h3>PyPI installs by tool</h3>{count_table(s["installers"], ("Installer", "Installs"))}</div>
  <div class="card"><h3>PyPI installs by Python</h3>{count_table(s["pythons"], ("Python", "Installs"))}</div>
</div>

<h2>Left out</h2>
<div class="card"><p class="sub">Counted by the sources but not in the totals above.</p>
  <table><thead><tr><th>Kind</th><th class="n">Count</th></tr></thead><tbody>{filtered}</tbody></table></div>

<h2>Sources</h2>
<div class="card">{status}</div>
</main>
<script id="data" type="application/json">{data}</script>
<script>{JS}</script>
</body></html>
"""


# --- serve --------------------------------------------------------------------

def make_handler(data_dir: Path):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?")[0] != "/":
                return self.send(404, b"not found", "text/plain")
            self.send(200, render(summarize(data_dir), live=True).encode(), "text/html; charset=utf-8")

        def do_POST(self):
            if self.path == "/live/refresh":
                # The open page asks for this every 10 minutes: only the newest page requests, not the whole collect.
                with lock:
                    code = dl.collect(data_dir, dl.LIVE_SOURCES)
                status = json.loads((data_dir / "status.json").read_text())
                reply = {"ok": code == 0, "error": status.get("visits", {}).get("error", ""), "live": live_for(data_dir)}
                return self.send(200, json.dumps(reply).encode(), "application/json")
            if self.path != "/refresh":
                return self.send(404, b"not found", "text/plain")
            with lock:  # one collect at a time
                code = dl.collect(data_dir)
            status = json.loads((data_dir / "status.json").read_text())
            failed = [k for k, v in status.items() if not v.get("ok")]
            self.send(200, json.dumps({"ok": code == 0, "failed": failed}).encode(), "application/json")

    return Handler


def serve(data_dir: Path, port: int, open_browser: bool) -> int:
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(data_dir))
    except OSError as e:
        print(f"Cannot listen on 127.0.0.1:{port} ({e.strerror}). Something else is using it; "
              f"pick another with --port, for example --port {port + 1}.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{port}/"
    print(f"Dashboard on {url} (data in {data_dir}); Ctrl-C to stop")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", type=Path, default=dl.DATA_DIR, help=f"default {dl.DATA_DIR}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve", help="serve the dashboard locally, with a Refresh button")
    sv.add_argument("--port", type=int, default=PORT)
    sv.add_argument("--open", action="store_true", help="open it in the browser")
    sub.add_parser("build", help="write dashboard.html into the data folder")
    args = ap.parse_args(argv)
    if args.cmd == "serve":
        return serve(args.data_dir, args.port, args.open)
    out = args.data_dir / "dashboard.html"
    dl.write_atomic(out, render(summarize(args.data_dir), live=False))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
