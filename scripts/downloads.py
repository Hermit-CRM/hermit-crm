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

"""Count Hermit CRM downloads on all three channels and keep the numbers.

    downloads.py collect             fetch PyPI, GitHub and the website log, save them
    downloads.py report              print the totals from what has been saved
    downloads.py report --installs   ...and list every real pip/uv install

Maintainer tool, not part of the installed package. Standard library only, plus
the `gh` and `flyctl` command line tools, both logged in.

Where the numbers come from:
  PyPI     pypistats.org (daily totals) and ClickPy, the public copy of PyPI's
           download log, which says which client downloaded (pip, uv, a browser,
           a mirror...), from which country, with which Python, and whether CI.
  GitHub   release asset download counts, and the 14-day clone and view traffic.
  Website  the tarball log nginx keeps on the Fly volume (website/nginx.conf).

Everything is saved as plain CSV / JSON lines in DATA_DIR, merged by key, so
running `collect` twice, or after a gap, loses nothing. The sources keep only a
window (pypistats 180 days, GitHub traffic 14 days), which is why this runs on a
schedule. `collect` exits 1 when any source failed, so launchd shows the failure.
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs

REPO = "Hermit-CRM/hermit-crm"
FLY_APP = "hermitcrm"
PROJECT = "hermitcrm"
DATA_DIR = Path(os.environ.get("HERMITCRM_DOWNLOADS_DIR", "~/.local/share/hermitcrm-downloads")).expanduser()

PYPISTATS = f"https://pypistats.org/api/packages/{PROJECT}/overall"
CLICKPY = "https://sql-clickhouse.clickhouse.com/?user=demo"
CLICKPY_SQL = f"""
SELECT toString(date) AS day, version, type, installer, country_code AS country,
       python_minor AS python, system, toString(ci) AS ci, count() AS downloads
FROM pypi.pypi WHERE project = '{PROJECT}'
GROUP BY day, version, type, installer, country, python, system, ci
ORDER BY day FORMAT JSONEachRow"""

PYPI_FIELDS = ["day", "version", "type", "installer", "country", "python", "system", "ci", "downloads"]
STATS_FIELDS = ["day", "category", "downloads"]
ASSET_FIELDS = ["day", "tag", "asset", "downloads"]
TRAFFIC_FIELDS = ["day", "clones", "clones_unique", "views", "views_unique"]
STARS_FIELDS = ["day", "stars"]
REPO_FIELDS = ["day", "stars", "forks", "watchers"]
REFERRER_FIELDS = ["day", "referrer", "count", "uniques"]
PATH_FIELDS = ["day", "path", "count", "uniques"]

# What pip, uv and friends report as `installer`. Anything else that downloads
# is a browser, a script, a mirror or a scanner.
INSTALLERS = {"pip", "uv", "poetry", "pdm", "pipenv", "pixi"}
MIRRORS = {"bandersnatch", "devpi", "Artifactory", "Nexus", "z3c.pypimirror"}
# curl and wget are deliberately not here: people do fetch the tarball with them.
BOT_UA = re.compile(r"bot|crawl|spider|preview|scan|slurp|headless|facebookexternalhit|uptime|monitor", re.I)
# A completed download sent (nearly) the whole file.
COMPLETE = 0.9

# Website page views (website/nginx.conf, /data/visits.log). The crawlers of AI
# services, and the assistants that fetch a page because a person asked, are
# counted on their own: for this site they matter, but they are not visitors.
SITE_HOST = "hermitcrm.io"
AI_BOT = re.compile(r"GPTBot|ChatGPT-User|OAI-SearchBot|ClaudeBot|Claude-User|Claude-SearchBot|anthropic-ai|"
                    r"PerplexityBot|Perplexity-User|Google-Extended|Applebot-Extended|Bytespider|CCBot|Amazonbot|"
                    r"meta-externalagent|cohere-ai|DuckAssistBot|MistralAI-User", re.I)


def log(msg: str, err: bool = False) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print(f"{stamp} {msg}", file=sys.stderr if err else sys.stdout, flush=True)


def run(cmd: list[str], timeout: int = 180) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if done.returncode:
        raise RuntimeError(f"{cmd[0]} exited {done.returncode}: {done.stderr.strip()[:300]}")
    return done.stdout


def fetch(url: str, body: str | None = None) -> str:
    req = urllib.request.Request(url, data=body.encode() if body else None,
                                 headers={"User-Agent": "hermitcrm-downloads/1 (+https://hermitcrm.io)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode()


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def merge_csv(path: Path, fields: list[str], key: list[str], rows: list[dict]) -> int:
    """Add rows to a CSV, replacing saved rows with the same key. Returns the row count."""
    merged = {tuple(r[k] for k in key): r for r in read_csv(path)}
    for r in rows:
        r = {k: str(r[k]) for k in fields}
        merged[tuple(r[k] for k in key)] = r
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(merged[k] for k in sorted(merged))
    write_atomic(path, buf.getvalue())
    return len(merged)


def parse_log(text: str) -> list[dict]:
    """The JSON lines in `text`. ssh prints a 'Connecting to...' line too; skip anything else."""
    rows = []
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("id") and row.get("path"):
            rows.append(row)
    return rows


# --- collect ---------------------------------------------------------------

def collect_pypi(data_dir: Path) -> str:
    stats = json.loads(fetch(PYPISTATS))["data"]
    merge_csv(data_dir / "pypi-pypistats.csv", STATS_FIELDS, ["day", "category"],
              [{"day": r["date"], "category": r["category"], "downloads": r["downloads"]} for r in stats])
    rows = [json.loads(line) for line in fetch(CLICKPY, CLICKPY_SQL).splitlines() if line.strip()]
    total = merge_csv(data_dir / "pypi-downloads.csv", PYPI_FIELDS, PYPI_FIELDS[:-1], rows)
    return f"{len(stats)} pypistats rows, {total} ClickPy rows"


def latest_snapshot(rows: list[dict], sort_key: str) -> list[dict]:
    """The rows saved on the most recent day, biggest first. Referrers and popular pages are
    rolling 14-day totals saved once per collect, so only the newest day is the current picture."""
    latest = max((r["day"] for r in rows), default=None)
    return sorted((r for r in rows if r["day"] == latest), key=lambda r: -int(r[sort_key]))


def stars_per_day(timestamps: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in timestamps:
        out[t[:10]] = out.get(t[:10], 0) + 1
    return out


def collect_github(data_dir: Path) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # One page of 100 is plenty: the project has a handful of releases.
    releases = json.loads(run(["gh", "api", f"repos/{REPO}/releases?per_page=100"]))
    assets = [{"day": today, "tag": rel["tag_name"], "asset": a["name"], "downloads": a["download_count"]}
              for rel in releases for a in rel["assets"]]
    merge_csv(data_dir / "github-assets.csv", ASSET_FIELDS, ["day", "tag", "asset"], assets)
    traffic: dict[str, dict] = {}
    for kind in ("clones", "views"):
        for e in json.loads(run(["gh", "api", f"repos/{REPO}/traffic/{kind}"]))[kind]:
            row = traffic.setdefault(e["timestamp"][:10], {"day": e["timestamp"][:10]})
            row[kind], row[f"{kind}_unique"] = e["count"], e["uniques"]
    merge_csv(data_dir / "github-traffic.csv", TRAFFIC_FIELDS, ["day"],
              [{f: r.get(f, 0) for f in TRAFFIC_FIELDS} for r in traffic.values()])
    # The repo's own numbers, and who sent the traffic. Referrers and popular pages are
    # rolling 14-day totals, so each collect saves them under today's date.
    repo = json.loads(run(["gh", "api", f"repos/{REPO}"]))
    merge_csv(data_dir / "github-repo.csv", REPO_FIELDS, ["day"],
              [{"day": today, "stars": repo["stargazers_count"], "forks": repo["forks_count"],
                "watchers": repo["subscribers_count"]}])
    referrers = json.loads(run(["gh", "api", f"repos/{REPO}/traffic/popular/referrers"]))
    merge_csv(data_dir / "github-referrers.csv", REFERRER_FIELDS, ["day", "referrer"],
              [{"day": today, "referrer": r["referrer"], "count": r["count"], "uniques": r["uniques"]} for r in referrers])
    paths = json.loads(run(["gh", "api", f"repos/{REPO}/traffic/popular/paths"]))
    merge_csv(data_dir / "github-paths.csv", PATH_FIELDS, ["day", "path"],
              [{"day": today, "path": r["path"], "count": r["count"], "uniques": r["uniques"]} for r in paths])
    # Stars have a date, so their history can be rebuilt on every run (an unstar drops out).
    starred = run(["gh", "api", f"repos/{REPO}/stargazers", "--paginate", "-H", "Accept: application/vnd.github.star+json",
                   "--jq", ".[].starred_at"]).split()
    merge_csv(data_dir / "github-stars.csv", STARS_FIELDS, ["day"],
              [{"day": d, "stars": n} for d, n in sorted(stars_per_day(starred).items())])
    return f"{len(assets)} assets, {len(traffic)} traffic days, {repo['stargazers_count']} stars"


def ssh_cat(path: str) -> str:
    """Read a file on the site's machine.

    The machine is stopped whenever nobody is looking at the site, and `flyctl ssh`
    does not start it ("app has no started VMs"), so start it first and retry while
    it boots. Fly stops it again on its own once it is idle."""
    for attempt in range(6):
        try:
            for m in json.loads(run(["flyctl", "machines", "list", "-a", FLY_APP, "--json"])):
                if m["state"] in ("stopped", "suspended", "created"):
                    subprocess.run(["flyctl", "machine", "start", m["id"], "-a", FLY_APP],
                                   capture_output=True, timeout=120)
            return run(["flyctl", "ssh", "console", "-a", FLY_APP, "-C", f"cat {path}"])
        except RuntimeError:
            if attempt == 5:
                raise
            time.sleep(5)


def collect_website(data_dir: Path) -> str:
    # The volume keeps the file between boots.
    text = ssh_cat("/data/downloads.log")
    path = data_dir / "website.jsonl"
    merged = {r["id"]: r for r in parse_log(path.read_text())} if path.exists() else {}
    fresh = parse_log(text)
    merged.update({r["id"]: r for r in fresh})
    ordered = sorted(merged.values(), key=lambda r: (r["t"], r["id"]))
    write_atomic(path, "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in ordered))
    return f"{len(fresh)} lines on the volume, {len(ordered)} saved"


def collect_visits(data_dir: Path) -> str:
    try:
        text = ssh_cat("/data/visits.log")
    except RuntimeError as e:
        if "No such file" not in str(e):  # the site has not been deployed with the page log yet
            raise
        return "no page log on the site yet (deploy website/ first)"
    path = data_dir / "visits.jsonl"
    merged = {r["id"]: r for r in parse_log(path.read_text())} if path.exists() else {}
    fresh = parse_log(text)
    merged.update({r["id"]: r for r in fresh})
    ordered = sorted(merged.values(), key=lambda r: (r["t"], r["id"]))
    write_atomic(path, "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in ordered))
    return f"{len(fresh)} lines on the volume, {len(ordered)} saved"


SOURCES = {"pypi": collect_pypi, "github": collect_github, "website": collect_website, "visits": collect_visits}


def collect(data_dir: Path) -> int:
    data_dir.mkdir(parents=True, exist_ok=True)
    status_path = data_dir / "status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    failed = []
    for name, fn in SOURCES.items():
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        entry = status.setdefault(name, {})
        try:
            detail = fn(data_dir)
        except Exception as e:  # one broken source must not stop the other two
            failed.append(name)
            entry.update(ok=False, error=str(e)[:300], tried=now)
            log(f"{name}: FAILED: {e}", err=True)
        else:
            entry.update(ok=True, last_ok=now, tried=now, detail=detail)
            entry.pop("error", None)
            log(f"{name}: ok, {detail}")
    write_atomic(status_path, json.dumps(status, indent=2) + "\n")
    if failed:
        log("collect FAILED: " + ", ".join(failed), err=True)
        return 1
    log("collect ok")
    return 0


# --- report ----------------------------------------------------------------

def pypi_bucket(row: dict) -> str:
    installer = row["installer"]
    if installer in INSTALLERS:
        return "ci" if row["ci"] == "true" else "installs"
    if installer in MIRRORS:
        return "mirrors"
    return {"Browser": "browser", "requests": "scripts", "": "unknown"}.get(installer, "other")


def looks_like_a_bot(row: dict) -> bool:
    ua = row["ua"]
    if not ua or BOT_UA.search(ua):
        return True
    # A person's browser sends Sec-Fetch-Site; a scanner that borrows a browser's
    # name usually does not. curl and wget never send it and are not judged on it,
    # and log lines from before the field existed have no "sf" key at all.
    return "sf" in row and ua.startswith("Mozilla/") and not row["sf"]


def read_ignored(data_dir: Path) -> set[str]:
    """Request ids in ignore.txt (one per line, `#` starts a comment): downloads that were not real,
    such as a verification curl. Nothing is deleted from the log; the report just counts them as yours."""
    path = data_dir / "ignore.txt"
    if not path.exists():
        return set()
    lines = (line.split("#")[0].strip() for line in path.read_text().splitlines())
    return {line for line in lines if line}


def website_events(rows: list[dict], ignore: frozenset[str] | set[str] = frozenset()) -> dict[str, list[dict]]:
    """Sort tarball GETs into mine / bots / aborted / downloads. Other requests are ignored."""
    gets = [r for r in rows if r["method"] == "GET" and r["status"] == 200]
    biggest: dict[str, int] = {}
    for r in gets:
        biggest[r["path"]] = max(biggest.get(r["path"], 0), r["bytes"])
    out: dict[str, list[dict]] = {"downloads": [], "aborted": [], "bots": [], "mine": []}
    for r in gets:
        if (r["id"] in ignore or "own" in parse_qs(r.get("q", ""), keep_blank_values=True)
                or "selftest" in r["ua"].lower()):
            out["mine"].append(r)
        elif looks_like_a_bot(r):
            out["bots"].append(r)
        elif r["bytes"] < COMPLETE * biggest[r["path"]]:
            out["aborted"].append(r)
        else:
            out["downloads"].append(r)
    return out


def ai_name(ua: str) -> str:
    m = AI_BOT.search(ua)
    return m.group(0) if m else ""


def visit_events(rows: list[dict], ignore: frozenset[str] | set[str] = frozenset()) -> dict[str, list[dict]]:
    """Sort page requests into people, AI crawlers, bots, scripts and yours.

    parse_log wants "path", which a page row has. A person is a browser that says it is
    navigating to a document (Sec-Fetch-Dest) and that is not a named bot; curl and
    scripts send neither, and are kept apart rather than called visitors. `arrivals`
    are the people who came from outside the site (a link, a bookmark, the address bar,
    Sec-Fetch-Site cross-site or none); a click from one page of the site to another is
    same-origin and counts as a page view only. No IP address or cookie is kept, so this
    is the closest thing to a unique visit the log allows."""
    out: dict[str, list[dict]] = {"people": [], "ai": [], "bots": [], "scripts": [], "mine": []}
    for r in rows:
        if r.get("method", "GET") != "GET" or r.get("status") not in (200, 304):
            continue
        ua = r.get("ua", "")
        if (r["id"] in ignore or "own" in parse_qs(r.get("q", ""), keep_blank_values=True)
                or "selftest" in ua.lower() or r.get("h", SITE_HOST) != SITE_HOST):
            out["mine"].append(r)
        elif AI_BOT.search(ua):
            out["ai"].append(r)
        elif not ua or BOT_UA.search(ua):
            out["bots"].append(r)
        elif not ua.startswith("Mozilla/"):
            out["scripts"].append(r)
        elif r.get("sd") != "document":
            out["bots"].append(r)
        else:
            out["people"].append(r)
    return out


def count_hosts(rows) -> dict[str, int]:
    """Where arrivals came from; an empty referrer (typed, bookmarked, an app) is "direct"."""
    out: dict[str, int] = {}
    for r in rows:
        host = r.get("ref") or "direct"
        out[host] = out.get(host, 0) + 1
    return out


def is_arrival(row: dict) -> bool:
    return row.get("sf") in ("cross-site", "none")


def report(data_dir: Path, installs: bool = False) -> None:
    lines = []
    out = lines.append

    pypi = read_csv(data_dir / "pypi-downloads.csv")
    stats = read_csv(data_dir / "pypi-pypistats.csv")
    buckets = {b: 0 for b in ("installs", "ci", "browser", "scripts", "unknown", "mirrors", "other")}
    for r in pypi:
        buckets[pypi_bucket(r)] += int(r["downloads"])
    pypi_all = sum(buckets.values())
    days = sorted({r["day"] for r in pypi})
    out(f"PyPI     {pypi_all} downloads in total" + (f", {days[0]} to {days[-1]}" if days else ""))
    for label, key in (("pip/uv installs", "installs"), ("pip/uv in CI", "ci"), ("browser downloads", "browser"),
                       ("Python scripts (requests)", "scripts"), ("unknown clients (curl, scanners)", "unknown"),
                       ("mirrors", "mirrors"), ("other clients", "other")):
        if buckets[key]:
            out(f"           {buckets[key]:>5}  {label}")
    without = sum(int(r["downloads"]) for r in stats if r["category"] == "without_mirrors")
    if stats:
        out(f"         pypistats headline, without mirrors: {without} (this still counts browsers and scripts)")
    if installs:
        for r in sorted((r for r in pypi if pypi_bucket(r) in ("installs", "ci")), key=lambda r: r["day"]):
            out(f"           {r['day']}  {r['country'] or '--'}  {r['installer']:<4} py{r['python'] or '?':<5} "
                f"{r['system'] or '?':<7} {r['type']:<11} x{r['downloads']}  v{r['version']}  ci={r['ci']}")

    assets = read_csv(data_dir / "github-assets.csv")
    traffic = read_csv(data_dir / "github-traffic.csv")
    latest = max((r["day"] for r in assets), default=None)
    current = [r for r in assets if r["day"] == latest]
    gh_total = sum(int(r["downloads"]) for r in current)
    out("")
    out(f"GitHub   {gh_total} release downloads" + (f" (counts as of {latest})" if latest else ""))
    for r in current:
        out(f"           {int(r['downloads']):>5}  {r['asset']}")
    if traffic:
        out(f"         clones {sum(int(r['clones']) for r in traffic)}, views {sum(int(r['views']) for r in traffic)} "
            f"over {len(traffic)} saved days (activity, not people: it includes your own checkouts)")

    repo_rows = sorted(read_csv(data_dir / "github-repo.csv"), key=lambda r: r["day"])
    if repo_rows:
        r = repo_rows[-1]
        out(f"         {r['stars']} stars, {r['forks']} forks, {r['watchers']} watching (as of {r['day']})")
    for r in latest_snapshot(read_csv(data_dir / "github-referrers.csv"), "uniques")[:5]:
        out(f"         {r['uniques']:>5}  unique visitors from {r['referrer']} in the last 14 days")

    path = data_dir / "website.jsonl"
    site = (website_events(parse_log(path.read_text()), read_ignored(data_dir)) if path.exists()
            else dict.fromkeys(("downloads", "aborted", "bots", "mine"), []))
    out("")
    out(f"Website  {len(site['downloads'])} completed downloads")
    for label, key in (("aborted before the end", "aborted"), ("bots and crawlers", "bots"),
                       ("yours (?own, selftest or ignore.txt)", "mine")):
        if site[key]:
            out(f"           {len(site[key]):>5}  {label}")
    per_file: dict[str, int] = {}
    for r in site["downloads"]:
        per_file[r["path"]] = per_file.get(r["path"], 0) + 1
    for p in sorted(per_file):
        out(f"           {per_file[p]:>5}  {p}")

    vpath = data_dir / "visits.jsonl"
    visits = (visit_events(parse_log(vpath.read_text()), read_ignored(data_dir)) if vpath.exists()
              else dict.fromkeys(("people", "ai", "bots", "scripts", "mine"), []))
    people = visits["people"]
    out("")
    if vpath.exists():
        out(f"Visitors {sum(1 for r in people if is_arrival(r))} arrivals, {len(people)} page views by people "
            "(an arrival is a visit that began outside the site; no IP or cookie is kept)")
        for label, key in (("AI crawlers and assistants", "ai"), ("bots and link previews", "bots"),
                           ("scripts (curl, python...)", "scripts"), ("yours (?own, ignore.txt, other host)", "mine")):
            if visits[key]:
                out(f"           {len(visits[key]):>5}  {label}")
        for host, n in sorted(count_hosts(r for r in people if is_arrival(r)).items(), key=lambda kv: -kv[1])[:5]:
            out(f"           {n:>5}  from {host}")
    else:
        out("Visitors no page log saved yet: deploy website/, then run `downloads.py collect`")

    best = buckets["installs"] + gh_total + len(site["downloads"])
    site_all = sum(len(v) for v in site.values())
    out("")
    out(f"Best estimate of real downloads: {buckets['installs']} + {gh_total} + {len(site['downloads'])} = {best}")
    out(f"Everything counted, bots and mirrors included: {pypi_all} + {gh_total} + {site_all} = {pypi_all + gh_total + site_all}")

    status_path = data_dir / "status.json"
    if status_path.exists():
        status = json.loads(status_path.read_text())
        out("")
        for name, s in status.items():
            note = f"ok, last {s.get('last_ok', '?')}" if s.get("ok") else f"FAILING since {s.get('last_ok', 'never')}: {s.get('error', '')}"
            out(f"collect {name}: {note}")
    else:
        out("")
        out("No data saved yet: run `downloads.py collect` first.")
    print("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR, help=f"default {DATA_DIR}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect", help="fetch all three sources and save them")
    rep = sub.add_parser("report", help="print the totals from what is saved")
    rep.add_argument("--installs", action="store_true", help="list each real pip/uv install")
    args = ap.parse_args(argv)
    if args.cmd == "collect":
        return collect(args.data_dir)
    report(args.data_dir, args.installs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
