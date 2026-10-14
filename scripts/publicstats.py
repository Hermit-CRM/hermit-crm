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

"""Publish the site's own numbers on https://hermitcrm.io/stats/ ("build in public").

    publicstats.py build   [--today YYYY-MM-DD] [--out DIR]   write numbers.html and stats.json (default DIR: <data>/public)
    publicstats.py publish [--today YYYY-MM-DD] [--force]     build, then upload to the site when changed

Maintainer tool, not part of the installed package. Standard library only, plus
`flyctl` (logged in) for `publish`. Runs once a day from launchd, after
`downloads.py collect` (website/io.hermitcrm.publicstats.plist).

It adds no counting rules: the numbers come from dashboard.summarize(), which
uses downloads.py, so the public page, the private dashboard and `report`
cannot disagree. What it does add is what is left out of public view:
  - anything seen fewer than K times in a list (a referrer host, a page, a tag,
    a country) goes into "Other", because one hit can point at one person;
  - public-hide.txt in the data folder (one host, page or tag per line, `#`
    comments) removes names from every list, whatever their count;
  - no user agents (only AI product names), request ids, times finer than a
    day, single install rows, or anything counted as yours.

The output is deterministic: the same files and the same --today give the same
bytes, so `publish` uploads only when a number changed. The page shell is
website/build.py's /stats/ page; nginx includes numbers.html into it.
"""
import argparse
import hashlib
import html
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import dashboard as db
import downloads as dl

K = 3            # smallest count shown under its own name
TOP = 10         # longest list
WINDOW = 90      # days in the charts and the visitor lists
REMOTE = "/data/public"
SECTION_SOURCES = {"visitors": ("visits",), "downloads": ("pypi", "website"), "github": ("github",),
                   "ai": ("visits",)}
SOURCE_NAMES = {"visits": "visitor", "pypi": "PyPI", "website": "website download", "github": "GitHub"}


def read_hidden(data_dir: Path) -> set[str]:
    path = data_dir / "public-hide.txt"
    if not path.exists():
        return set()
    lines = (line.split("#")[0].strip() for line in path.read_text().splitlines())
    return {line for line in lines if line}


def fold(counts: dict[str, int], k: int = K, hide: set[str] | frozenset[str] = frozenset(),
         top: int = TOP) -> list[list]:
    """[[name, count], ...] biggest first (ties by name), with hidden names dropped and
    small or overflowing ones summed into a last "Other" row."""
    kept = sorted(((n, c) for n, c in counts.items() if n not in hide and c >= k), key=lambda nc: (-nc[1], nc[0]))
    other = sum(c for n, c in counts.items() if n not in hide and c < k) + sum(c for _, c in kept[top:])
    return [[n, c] for n, c in kept[:top]] + ([["Other", other]] if other else [])


def window(today: str) -> list[str]:
    last = date.fromisoformat(today)
    return [(last - timedelta(days=n)).isoformat() for n in range(WINDOW - 1, -1, -1)]


def cut(series: dict[str, list[int]], days: list[str], window_days: list[str]) -> dict[str, list[int]]:
    """The same series on the last WINDOW days; days before the data starts are zeros."""
    out = {}
    for name, values in series.items():
        by_day = dict(zip(days, values))
        out[name] = [by_day.get(d, 0) for d in window_days]
    return out


def visitor_lists(data_dir: Path, first: str, hide: set[str]) -> dict:
    """Pages, sources, tags and AI names over the window. The dashboard's lists are all
    time and already cut to ten; this sorts the same rows with the same rules."""
    vpath = data_dir / "visits.jsonl"
    visits = dl.visit_events(dl.parse_log(vpath.read_text()), dl.read_ignored(data_dir))
    recent = {kind: [r for r in rows if r["t"][:10] >= first] for kind, rows in visits.items()}
    arrivals = [r for r in recent["people"] if dl.is_arrival(r)]
    return {
        "pages": fold(db.count_by(recent["people"], lambda r: db.page_name(r["path"])), hide=hide),
        "sources": fold(dl.count_hosts(arrivals), hide=hide),
        "tags": fold(db.count_by([r for r in arrivals if db.campaign(r)], db.campaign), hide=hide),
        # Product names only (ClaudeBot, GPTBot); never the user agent itself.
        "ai_names": fold(db.count_by(recent["ai"], lambda r: dl.ai_name(r["ua"])), k=1, hide=hide),
    }


def public_numbers(data_dir: Path, today: str) -> dict:
    """What the public page shows, as plain data. Reads the data folder, writes nothing."""
    s = db.summarize(data_dir, today)
    hide = read_hidden(data_dir)
    days = window(today)

    out: dict = {"schema": 1, "generated": f"{today}T00:00:00Z", "today": today, "days": days}

    v = s["visits"]
    if v is None:
        out["visitors"] = out["ai"] = None
    else:
        lists = visitor_lists(data_dir, days[0], hide)
        per_day = cut(v["per_day"], s["days"], days)
        ai_per_day = cut(v["ai_per_day"], s["days"], days)
        out["visitors"] = {"per_day": per_day, "arrivals_30d": sum(per_day["Arrivals"][-30:]),
                           "pages": lists["pages"], "sources": lists["sources"], "tags": lists["tags"]}
        out["ai"] = {"per_day": ai_per_day, "fetches_30d": sum(next(iter(ai_per_day.values()))[-30:]),
                     "names": lists["ai_names"]}

    t = s["tiles"]
    out["downloads"] = {
        "total": t["best"], "pypi": t["pypi"], "github": t["github"], "website": t["website"],
        "per_day": cut(s["downloads_per_day"], s["days"], days),
        "versions": [[ver, n["pypi"], n["website"], n["github"]] for ver, n in s["versions"].items()],
        "countries": fold(s["countries"], hide=hide),
        "installers": fold(s["installers"], hide=hide),
    }

    g = s["github"]
    out["github"] = None if g is None else {
        "stars": g["stars"], "forks": g["forks"], "watchers": g["watchers"], "as_of": g["as_of"],
        "stars_per_day": cut(s["stars_per_day"], s["days"], days),
        "traffic": cut(s["github_traffic"], s["days"], days) if s["has_traffic"] else None,
    }

    # Every count set aside, as totals; what was counted as yours stays private.
    left_out = list(s["filtered"]) + (list(v["left_out"]) if v else [])
    out["left_out"] = [[label, n] for label, n in left_out if "yours" not in label.lower()]

    out["sources"] = {name: {"ok": bool(st.get("ok")), "last_ok": (st.get("last_ok") or "")[:10] or None}
                      for name, st in sorted(s["status"].items()) if name in dl.SOURCES}
    out["tiles"] = {"arrivals_30d": out["visitors"]["arrivals_30d"] if out["visitors"] else None,
                    "downloads": t["best"], "stars": g["stars"] if g else None,
                    "ai_30d": out["ai"]["fetches_30d"] if out["ai"] else None}
    return out


# --- the HTML fragment --------------------------------------------------------

def esc(value) -> str:
    return html.escape(str(value))


def num(n) -> str:
    return "n/a" if n is None else f"{n:,}"


def long_date(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d.day} {d:%B %Y}"


def bars(series: dict[str, list[int]], days: list[str], label: str, unit: str) -> str:
    """Stacked daily bars as inline SVG: classes for colour, no style attributes (the
    site's CSP blocks them), a <title> per bar for hover and screen readers."""
    W, H, T, B = 900, 200, 30, 30   # B leaves room for the dates, T for the top value
    n = len(days)
    totals = [sum(vals[i] for vals in series.values()) for i in range(n)]
    top = max(totals, default=0) or 1
    slot = W / n
    bw = slot * 0.7
    scale = (H - T - B) / top
    parts = []
    for i, d in enumerate(days):
        x = i * slot + (slot - bw) / 2
        y = H - B
        rects = []
        for k, vals in enumerate(series.values(), start=1):
            if vals[i]:
                h = vals[i] * scale
                y -= h
                rects.append(f'<rect class="s{k}" x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}"/>')
        if rects:
            what = ", ".join(f"{vals[i]:,} {name.lower()}" for name, vals in series.items() if vals[i])
            parts.append(f'<g><title>{esc(d)}: {esc(what)}</title>{"".join(rects)}</g>')
    total = sum(totals)
    aria = f"{label}, last {n} days, {total:,} {unit} in total"
    legend = "".join(f'<span class="key s{k}">{esc(name)}</span>' for k, name in enumerate(series, start=1))
    return (f'<figure class="chart"><svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(aria)}">'
            f'<line class="base" x1="0" x2="{W}" y1="{H - B}" y2="{H - B}"/>'
            f'<text x="0" y="{T - 8}">{max(totals, default=0):,}</text>'
            f'<text x="0" y="{H - 4}">{esc(days[0])}</text>'
            f'<text x="{W}" y="{H - 4}" text-anchor="end">{esc(days[-1])}</text>'
            f'{"".join(parts)}</svg>'
            f'<figcaption>{legend}</figcaption></figure>')


def table(rows: list[list], head: tuple[str, ...]) -> str:
    if not rows:
        return '<p class="stats-empty">No data yet.</p>'
    num_class = ' class="n"'
    th = "".join(f'<th scope="col"{num_class if i else ""}>{esc(h)}</th>' for i, h in enumerate(head))
    body = "".join(
        "<tr>" + f'<th scope="row">{esc(r[0])}</th>' + "".join(f'<td class="n">{num(c)}</td>' for c in r[1:]) + "</tr>"
        for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def tile(label: str, value, note: str) -> str:
    return (f'<div class="stats-tile"><p class="stats-label">{esc(label)}</p>'
            f'<p class="stats-value">{num(value)}</p><p class="stats-note">{esc(note)}</p></div>')


def stale(numbers: dict, section: str) -> str:
    notes = []
    for name in SECTION_SOURCES[section]:
        st = numbers["sources"].get(name)
        if st and not st["ok"]:
            since = f"since {long_date(st['last_ok'])}" if st["last_ok"] else "yet"
            notes.append(f'<p class="stats-stale">The {SOURCE_NAMES[name]} numbers have not been updated {since}.</p>')
    return "".join(notes)


def render_fragment(numbers: dict) -> str:
    """The numbers as an HTML fragment for the /stats/ page shell (no <html>, <head> or <body>)."""
    days = numbers["days"]
    t = numbers["tiles"]
    v, ai, dls, g = numbers["visitors"], numbers["ai"], numbers["downloads"], numbers["github"]
    parts = ['<section class="stats">',
             f'<p class="stats-fresh">Numbers up to {long_date(numbers["today"])}. Updated every day.</p>',
             '<div class="stats-tiles">',
             tile("Arrivals", t["arrivals_30d"], "last 30 days"),
             tile("Downloads", t["downloads"], "all time, PyPI, GitHub and this site"),
             tile("GitHub stars", t["stars"], "now"),
             tile("AI fetches", t["ai_30d"], "last 30 days"),
             "</div>"]

    parts.append('<h2 id="visitors">Visitors</h2>' + stale(numbers, "visitors"))
    if v is None:
        parts.append('<p class="stats-empty">No data yet.</p>')
    else:
        parts.append(bars(v["per_day"], days, "Arrivals per day", "arrivals"))
        parts.append('<div class="stats-two">'
                     f'<div><h3>Pages</h3>{table(v["pages"], ("Page", "Views"))}</div>'
                     f'<div><h3>Where arrivals came from</h3>{table(v["sources"], ("Source", "Arrivals"))}</div>'
                     "</div>")
        parts.append(f'<h3>Tagged links</h3>{table(v["tags"], ("Tag", "Arrivals"))}')

    parts.append('<h2 id="downloads">Downloads</h2>' + stale(numbers, "downloads"))
    parts.append(f'<p>{num(dls["total"])} in total: {num(dls["pypi"])} installs from PyPI, '
                 f'{num(dls["github"])} from GitHub releases, {num(dls["website"])} from this site.</p>')
    parts.append(bars(dls["per_day"], days, "Downloads per day", "downloads"))
    parts.append(f'<h3>By version</h3>{table(dls["versions"], ("Version", "PyPI", "Website", "GitHub"))}')

    parts.append('<h2 id="github">GitHub</h2>' + stale(numbers, "github"))
    if g is None:
        parts.append('<p class="stats-empty">No data yet.</p>')
    else:
        parts.append(f'<p>{num(g["stars"])} stars, {num(g["forks"])} forks, {num(g["watchers"])} watching '
                     f'on {long_date(g["as_of"])}.</p>')
        parts.append(bars(g["stars_per_day"], days, "New stars per day", "new stars"))
        if g["traffic"]:
            parts.append(bars(g["traffic"], days, "GitHub visitors and cloners per day", "unique visitors and cloners"))

    parts.append('<h2 id="ai">AI crawlers and assistants</h2>' + stale(numbers, "ai"))
    if ai is None:
        parts.append('<p class="stats-empty">No data yet.</p>')
    else:
        parts.append(bars(ai["per_day"], days, "AI fetches per day", "fetches"))
        parts.append(f'<h3>Which AI</h3>{table(ai["names"], ("Name", "Fetches"))}')

    parts.append('<h2 id="installs">Who installs</h2>')
    parts.append('<div class="stats-two">'
                 f'<div><h3>By country</h3>{table(dls["countries"], ("Country", "Installs"))}</div>'
                 f'<div><h3>By installer</h3>{table(dls["installers"], ("Installer", "Installs"))}</div>'
                 "</div>")

    parts.append('<h2 id="left-out">Left out</h2><p>Counted, but not in the totals above.</p>')
    parts.append(table(numbers["left_out"], ("Kind", "Count")))
    parts.append("</section>")
    return "\n".join(parts) + "\n"


# --- build and publish ------------------------------------------------------------

def build(data_dir: Path, today: str, out: Path) -> dict[str, bytes]:
    numbers = public_numbers(data_dir, today)
    files = {"numbers.html": render_fragment(numbers).encode(),
             "stats.json": (json.dumps(numbers, indent=2, sort_keys=True) + "\n").encode()}
    for name, data in files.items():
        dl.write_atomic(out / name, data.decode())
    return files


def digest(files: dict[str, bytes]) -> str:
    return hashlib.sha256(b"".join(hashlib.sha256(files[n]).digest() for n in sorted(files))).hexdigest()


def record(data_dir: Path, **entry) -> None:
    """The publish result in status.json, next to collect's sources, for the dashboard."""
    path = data_dir / "status.json"
    status = json.loads(path.read_text()) if path.exists() else {}
    current = status.setdefault("publish", {})
    current.update(entry)
    if entry.get("ok"):
        current.pop("error", None)
    dl.write_atomic(path, json.dumps(status, indent=2) + "\n")


def publish(data_dir: Path, today: str, force: bool = False) -> int:
    out = data_dir / "public"
    files = build(data_dir, today, out)
    stamp = out / ".published.sha256"
    new = digest(files)
    if not force and stamp.exists() and stamp.read_text().strip() == new:
        dl.log("publish: unchanged, nothing uploaded")
        return 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        dl.fly_ssh(f"mkdir -p {REMOTE}")
        for name in ("numbers.html", "stats.json"):
            dl.fly_put(f"{REMOTE}/{name}", files[name])
    except Exception as e:
        record(data_dir, ok=False, error=str(e)[:300], tried=now)
        dl.log(f"publish FAILED: {e}", err=True)
        return 1
    dl.write_atomic(stamp, new + "\n")
    record(data_dir, ok=True, last_ok=now, tried=now, detail=f"numbers up to {today}")
    dl.log(f"publish: ok, numbers up to {today}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", type=Path, default=dl.DATA_DIR, help=f"default {dl.DATA_DIR}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write numbers.html and stats.json")
    b.add_argument("--out", type=Path, help="default <data>/public")
    p = sub.add_parser("publish", help="build, then upload to the site when changed")
    p.add_argument("--force", action="store_true", help="upload even when nothing changed")
    for cmd in (b, p):
        cmd.add_argument("--today", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                         help="the last day shown, YYYY-MM-DD (default: today, UTC)")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        out = args.out or args.data_dir / "public"
        build(args.data_dir, args.today, out)
        print(out)
        return 0
    return publish(args.data_dir, args.today, args.force)


if __name__ == "__main__":
    sys.exit(main())
