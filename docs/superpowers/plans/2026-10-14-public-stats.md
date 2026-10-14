# Public Stats Page Implementation Plan ("build in public")

> **For agentic workers:** execute task by task, in order. Steps use checkbox
> (`- [ ]`) syntax for tracking. Read `CLAUDE.md` and `website/README.md`
> ("Counting downloads and visitors", "The dashboard", "Publish") first; their
> rules win over anything here.

**Goal:** a public page, **https://hermitcrm.io/stats/**, that shows Hermit CRM's
own numbers (website visitors, downloads, GitHub stars, AI crawlers, where people
come from) and refreshes **every day** without anyone touching it. Plus
`/stats/stats.json`, the same numbers as data, so anyone (or any AI tool) can
check or quote them.

**Frequency: daily.** Decided because it costs **zero AI tokens**: the numbers
are already collected every 6 hours by `scripts/downloads.py collect` (launchd
job `io.hermitcrm.downloads` on the maintainer's Mac). Publishing them is a
deterministic Python script plus one upload; no Claude session is involved in
the daily run. Claude only spends tokens once, to build this. An optional
weekly written note (Task 8) is the only part that would cost tokens, and it is
off unless the maintainer turns it on.

**Architecture:**

```
 Mac (launchd, daily)                              Fly machine "hermitcrm"
 ───────────────────                               ───────────────────────
 downloads.py collect  (already every 6 h)
        │ CSV / JSONL in ~/.local/share/hermitcrm-downloads/
        ▼
 publicstats.py build  ──► public/numbers.html      nginx: /stats/  (page shell, in the image,
                           public/stats.json  ──upload──► /data/public/  built by build.py)
 publicstats.py publish ─── flyctl ssh ────────────►     │ SSI include of /data/public/numbers.html
                                                          ▼
                                                   https://hermitcrm.io/stats/
```

- **The page shell is part of the normal site build** (`website/build.py`
  renders `site/stats/index.html` with the site's header, footer, `style.css`,
  intro text and "how we count" notes). It changes only when the site is
  deployed.
- **The numbers live on the Fly volume** (`/data/public/numbers.html` and
  `/data/public/stats.json`), which already exists (`downloads`, mounted at
  `/data`). nginx pulls the fragment into the shell with **SSI**
  (`ssi on` + `<!--# include virtual=... -->`), so a daily refresh is a file
  upload, **not** a `flyctl deploy`.
- **Counting rules are not duplicated:** `publicstats.py` calls
  `dashboard.summarize()` (which calls `downloads.py`), so the public page, the
  private dashboard and `report` can never disagree.

**Tech stack:** Python 3.13 standard library only (no new dependencies),
nginx 1.27 SSI, `flyctl`, launchd, pytest.

## Decisions (already made; do not reopen)

- **Daily, deterministic, no LLM in the loop.** See above.
- **Runs on the maintainer's Mac, not GitHub Actions.** Reasons: (1) the history
  lives only in the Mac's data folder (GitHub traffic and the Fly logs keep short
  windows, so CI could not rebuild it); (2) `site/download/` (the tarballs) is
  not in git, so a CI `flyctl deploy` would ship a site without downloads;
  (3) reading GitHub traffic needs a token with push access, which Actions'
  `GITHUB_TOKEN` cannot do. If the Mac is asleep, launchd runs the job on wake;
  the page says how old its numbers are (below).
- **No redeploy per refresh.** Upload to the volume, nginx includes it.
- **Plain HTML, no JavaScript.** The site's CSP is `script-src 'unsafe-inline'`
  only for the copy button and `style-src 'self'`. Charts are **inline SVG drawn
  in Python**, styled with classes from `style.css` and SVG presentation
  attributes (`fill=`, `stroke=`). **No `style="..."` attributes anywhere**: the
  CSP blocks them.
- **Aggregates only. Never published:** request ids, user agents (except the
  names of AI crawlers/assistants, which `downloads.ai_name()` already reduces to
  a product name), timestamps finer than a day, single PyPI install rows, Python
  version × system × country combinations, the `ignore.txt` contents, the
  "yours" rows, GitHub stargazer names.
- **Small-number threshold `K = 3`:** a referrer host, country, page or tagged
  link with fewer than 3 in the window is folded into "Other". Reason: a host
  like `mail.someones-company.example` seen once can point at one person.
- **Hide list:** `public-hide.txt` in the data folder (one host / path / tag per
  line, `#` comments) removes items from every public list even above `K`. Not
  in git (it may name the hidden things).
- **What is shown** (all from `summarize()`; names as on the private dashboard):

  | Section | Shown | Window |
  | --- | --- | --- |
  | Headline tiles | Arrivals (30 d), real downloads total (all time: PyPI installs + GitHub assets + website), GitHub stars, AI fetches (30 d) | as stated |
  | Visitors | Arrivals per day (bar chart); top pages; top sources (referrer hosts); tagged links (`?ref=`) | last 90 days |
  | Downloads | PyPI installs + website downloads per day (stacked bars); per version table (PyPI / website / GitHub) | last 90 days / all time |
  | GitHub | stars, forks, watchers; new stars per day; unique visitors and cloners per day | last 90 days |
  | AI | AI crawlers and assistants per day; by name | last 90 days |
  | Who installs | PyPI installs by country (top 10 + Other) and by installer (pip / uv / ...) | all time |
  | Left out | every count set aside (CI, mirrors, bots, yours...), as totals | all time |
  | Freshness | "Numbers from <date>, updated daily", and per source the last good fetch from `status.json` | |

- **Staleness:** the fragment carries its own "updated" date. If `collect` failed
  for a source, that source's section says "not updated since <date>" (from
  `status.json`). The shell (Task 5) has a fallback text when no fragment exists
  yet.
- **`stats.json`** mirrors the public numbers exactly (same thresholds, same
  hide list), with `"generated"` (UTC ISO time) and `"schema": 1`.
- **Deterministic output:** same input files + same `--today` → byte-identical
  `numbers.html` and `stats.json` (sorted keys, fixed float formatting, ties
  broken alphabetically). Only then does `publish` skip uploads when nothing
  changed.
- **Upload is atomic:** write to `/data/public/.numbers.html.tmp`, then `mv`.
  A visitor never gets a half file.
- **Words:** the shell's text goes in a new `[stats]` table in
  `website/content.toml` (the rule for all site text). Follow the site's tone
  rules: `build.py` warns about em dashes, exclamation marks and banned
  marketing words, and `--release` refuses them.
- **Name in the nav/footer:** "Stats", next to "Docs" in the footer text.
  Not in the top bar (keep it quiet).

## Global constraints

- `.venv/bin/pytest` must pass before every commit (`python3 -m venv .venv &&
  .venv/bin/pip install -e '.[dev]'` first).
- Commit messages start with `ai:`.
- No new runtime dependencies. Standard library only, like `downloads.py`.
- Fictional data in tests (hosts like `news.example.com`, `blog.example.org`).
- New maintainer files stay out of the download: add them to `.gitattributes`
  as `export-ignore` (like `scripts/downloads.py`).
- Tests use fixed dates (`--today 2026-10-14` style), never "now".
- Do not run `flyctl deploy` or the upload from a cloud session: there is no
  `flyctl` login there, and the deploy is the maintainer's step (Task 7).

## File map

| File | Change |
| --- | --- |
| `scripts/publicstats.py` | **new**: `build` and `publish` commands |
| `tests/test_publicstats_script.py` | **new** |
| `scripts/downloads.py` | factor the "start the stopped machine, retry" loop out of `ssh_cat` into `fly_ssh(cmd, stdin=None)` so `publish` reuses it |
| `website/nginx.conf` | `/stats/` with SSI, internal locations for the volume files, `/stats/stats.json` |
| `website/build.py` | `render_stats()`, sitemap entry, llms.txt line |
| `website/content.toml` | `[stats]` text; footer link |
| `website/site/style.css` | small classes for the SVG charts and the tables (reuse tokens) |
| `tests/test_website_stats.py` | **new**: the shell renders, has the SSI include, no inline styles |
| `website/README.md` | new section "Public stats" |
| `.gitattributes` | `export-ignore` the two new test/script files |
| `website/io.hermitcrm.publicstats.plist` | **new** (example launchd job, committed for reference) |

---

## Task 1: Share the Fly ssh helper

**Files:** `scripts/downloads.py`, `tests/test_downloads_script.py`

- [ ] Read `ssh_cat()` in `scripts/downloads.py`. Extract its loop into
  `fly_ssh(command: str, stdin: bytes | None = None) -> str` that starts
  stopped machines, retries 6 × 5 s, and runs
  `flyctl ssh console -a hermitcrm -C <command>`. `ssh_cat(path)` becomes
  `return fly_ssh(f"cat {path}")`.
- [ ] Find out (run `flyctl ssh console --help` and `flyctl ssh sftp --help`
  on the Mac, or read the current flyctl docs) **whether `ssh console -C`
  forwards stdin**. Pick the upload method in this order and note the choice in
  a comment:
  1. `flyctl ssh sftp put <local> <remote>` if it exists non-interactively;
  2. `ssh console -C "sh -c 'cat > tmp && mv tmp final'"` with stdin piped;
  3. fallback: base64 the file into the command
     (`sh -c 'echo <b64> | base64 -d > tmp && mv tmp final'`); only if the
     fragment stays under ~60 KB (assert it; it should be ~20–40 KB).
  If the cloud session cannot run flyctl, implement option 3 (works with any
  flyctl) behind the same `fly_put(remote_path, data: bytes)` function and
  leave a `TODO(maintainer)` comment to try option 1.
- [ ] Existing tests for `ssh_cat` keep passing (patch `run`/`subprocess.run`
  as they already do). Add one test that `fly_put` builds the expected command
  and does `mv` after writing the tmp file.
- [ ] Commit: `ai: downloads: fly_ssh and fly_put helpers, shared with the public stats`

## Task 2: `publicstats.py build`: the numbers as data

**Files:** `scripts/publicstats.py`, `tests/test_publicstats_script.py`

- [ ] Module header like `dashboard.py` (license, docstring with usage):

  ```
  publicstats.py build   [--today YYYY-MM-DD] [--out DIR]   write numbers.html and stats.json (default DIR: <data>/public)
  publicstats.py publish [--today YYYY-MM-DD] [--force]     build, then upload to the site when changed
  ```

  It imports `dashboard as db` and `downloads as dl` from its own folder (same
  pattern as `dashboard.py`).
- [ ] `public_numbers(data_dir, today) -> dict`: call `db.summarize(data_dir, today)`
  and reduce it to the public shape. Pure function, no I/O except reading
  `public-hide.txt`. Rules:
  - cut every per-day series to the last 90 days ending `today` (zeros kept);
  - 30-day sums for the "Arrivals" and "AI fetches" tiles;
  - `fold(counts: dict, k=3, hide=set, top=10)`: drop hidden keys, move keys
    with `< k` into `"Other"`, keep the top 10 by count then name, everything
    else into `"Other"`; drop `"Other"` when 0;
  - drop from `summarize()` output: `status` details except per-source
    `ok` / `last_ok` dates, `pythons`, any field not in the table above;
  - `"generated"`: `today` + `T00:00:00Z` (not the wall clock: determinism);
    `"schema": 1`.
- [ ] Tests (fixtures built like `test_dashboard_script.py` does: write small
  CSV/JSONL files into `tmp_path`):
  - a referrer host seen twice goes to "Other", one seen 3 times is listed;
  - a host in `public-hide.txt` disappears even with 50 hits;
  - no user agent string, request id or `"yours"` row appears anywhere in
    `json.dumps(result)` (search for the fixture's UA and ids);
  - AI names appear only as product names (`ClaudeBot`, `GPTBot`);
  - series are exactly 90 entries, last one is `today`;
  - same input twice → identical `json.dumps(..., sort_keys=True)`.
- [ ] Commit: `ai: publicstats: public numbers from the dashboard summary, with a small-number threshold and a hide list`

## Task 3: `publicstats.py build`: the HTML fragment

**Files:** `scripts/publicstats.py`, `tests/test_publicstats_script.py`

- [ ] `render_fragment(numbers: dict) -> str`: a `<section class="stats">`
  fragment (no `<html>`, `<head>` or `<body>`; the shell provides those). Use
  `html.escape` for every value that came from data (hosts, pages, tags, names).
- [ ] Inline SVG bar charts, written in Python: `bars(series: dict[str, list[int]], days: list[str]) -> str`.
  `viewBox` only (scales to width via CSS), one `<rect>` per day per series
  stacked, class per series (`s1`, `s2`), a baseline, the max value as a label,
  first/last date as labels, and a `<title>` per bar ("2026-10-12: 4 arrivals")
  for hover and screen readers. Each chart gets `role="img"` and an
  `aria-label` summarising it ("Arrivals per day, last 90 days, 212 in total").
  **No `style=` attributes.**
- [ ] Tables for the top lists and the per-version and left-out numbers: real
  `<table>` with `<th scope>`; numbers right-aligned via a class.
- [ ] Freshness line at the top: "Numbers up to 14 October 2026. Updated every
  day." (use `build.py`'s date style: `long_date`); per-section "not updated
  since …" when `status[source].ok` is false.
- [ ] `build` writes `numbers.html` and `stats.json` (`json.dumps(indent=2,
  sort_keys=True)` + newline) with `dl.write_atomic`.
- [ ] Tests: the fragment contains no `style=`, no `<script`; a host named
  `<b>x</b>.example.com` is escaped; output is byte-identical across two runs;
  the empty data folder (no files at all) still renders, with "no data yet".
- [ ] Run against real-looking data: `HERMITCRM_DOWNLOADS_DIR=<tmp with the
  test fixtures> python3 scripts/publicstats.py build --today 2026-10-14`, then
  open the fragment inside the shell from Task 5 (Task 5 step "preview").
- [ ] Commit: `ai: publicstats: the numbers as an HTML fragment with inline SVG charts`

## Task 4: `publicstats.py publish`

**Files:** `scripts/publicstats.py`, `tests/test_publicstats_script.py`

- [ ] `publish`: run `build`; compare the new files with
  `<data>/public/.published.sha256` (sha256 of both files); if unchanged and no
  `--force`, log "unchanged, nothing uploaded" and exit 0. Otherwise
  `dl.fly_ssh("mkdir -p /data/public")`, `dl.fly_put("/data/public/numbers.html", ...)`,
  `dl.fly_put("/data/public/stats.json", ...)`, then write the new hash.
- [ ] Exit 1 on an upload failure (launchd shows the job as failed), and record
  `{"publish": {"ok": false, "error": ..., "tried": ...}}` in `status.json` like
  `collect` does, so the private dashboard's Sources table shows it. Exit 0 on
  success and record `last_ok`.
- [ ] Do **not** run `collect` inside `publish`; the launchd plist chains them
  (Task 6). Keeps each command single-purpose and testable.
- [ ] Tests: patch `dl.fly_put`/`dl.fly_ssh`; unchanged data → no calls;
  changed data → two puts in order; a raising `fly_put` → exit 1 and
  `status.json` has `publish.ok == false`.
- [ ] Commit: `ai: publicstats: publish uploads to the site's volume only when the numbers changed`

## Task 5: The `/stats/` page on the site

**Files:** `website/build.py`, `website/content.toml`, `website/site/style.css`,
`website/nginx.conf`, `tests/test_website_stats.py`

- [ ] `content.toml`: add `[stats]` with `title` ("Hermit CRM in numbers"),
  `description` (meta), `intro` (2–3 sentences: we build in public; these are
  the site's and the package's own numbers, updated every day; no cookies, no
  IP addresses, see "how we count"), `how` (a short list explaining Arrivals,
  real downloads, AI fetches, the threshold of 3 and what is left out, linking
  to nothing private), `fallback` ("The numbers are not published yet."),
  `json_label` ("The same numbers as JSON").
  Add `· [Stats](stats/)` to `[footer].text` after `[Docs](docs/)`.
- [ ] `build.py`: `render_stats(c, hub)` using `page_head` / `page_foot` /
  `crumbs` like `render_about`. Body: `h1`, intro, then exactly

  ```html
  <!--# block name="nostats" --><p class="stats-fallback">{fallback}</p><!--# endblock -->
  <!--# include virtual="/stats/_numbers" stub="nostats" -->
  ```

  then the "how we count" block and a link to `stats.json`. Write it to
  `site/stats/index.html` in `build()`; add `/stats/` to `sitemap.xml`
  (`lastmod` = build date is fine: the page says "updated daily", use
  `<changefreq>daily</changefreq>`), add one line to `llms.txt` pointing at
  `/stats/` and `/stats/stats.json`. JSON-LD: `WebPage` + `BreadcrumbList`
  (same helpers as the About page).
  Opening `site/stats/index.html` from disk shows the fallback text only
  (browsers ignore SSI comments); that is expected.
- [ ] `nginx.conf` (inside the existing `server` for hermitcrm.io):

  ```nginx
  location = /stats/ {
      ssi on;
      ssi_silent_errors on;
      try_files /stats/index.html =404;
      access_log /data/visits.log visits;
  }
  location = /stats/_numbers {
      internal;                       # only reachable through the SSI include
      default_type text/html;
      alias /data/public/numbers.html;
  }
  location = /stats/stats.json {
      default_type application/json;
      alias /data/public/stats.json;
      add_header Cache-Control "public, max-age=3600";
      # add_header here drops the server-level headers: repeat them.
      add_header X-Robots-Tag $robots_tag always;
      add_header X-Content-Type-Options "nosniff" always;
      add_header Referrer-Policy "no-referrer" always;
  }
  ```

  Check the details against nginx 1.27 docs: whether `try_files` inside an
  exact location serves with SSI (if not, use `index index.html;` with
  `location /stats/`), whether `alias` works in `location =`, and that the
  server-level CSP/security headers still reach `/stats/` (an `add_header` in a
  location replaces them; the `/stats/` block above has none on purpose).
  Add `/stats/stats.json` to the `$is_page` map so its fetches are counted.
  `nginx -t` runs in the Dockerfile, so a broken config fails the image build.
- [ ] `style.css`: classes for `.stats` tiles, `.chart` (`width:100%;height:auto`),
  `.s1`/`.s2` fills using existing tokens (`--green` and one neutral), table
  number alignment, light and dark. Reuse the site's tokens; the build's
  `drift()` check fails on tokens the app does not define.
- [ ] `tests/test_website_stats.py` (pattern: `test_website_docs.py`, render to
  strings, write nothing into `website/site/`): the page has one `h1`, the SSI
  `include` with `stub="nostats"`, no `style=` attribute, the footer link;
  sitemap and `llms.txt` list `/stats/`.
- [ ] **Preview locally with real SSI:**
  `docker build -t hermit-site website && docker run --rm -p 8080:80 -v <dir with public/numbers.html and stats.json>:/data hermit-site`
  (mount a dir that has `public/` inside), open `http://localhost:8080/stats/`,
  check light and dark, a 375 px wide window, and the browser console for CSP
  errors. If Docker is not available in the session, say so in the PR and
  leave this to the maintainer (Task 7).
- [ ] `python3 website/build.py --release` reports no new problems from the
  stats text.
- [ ] Commit: `ai: website: /stats/ page shell, served with the daily numbers from the volume`

## Task 6: The daily schedule

**Files:** `website/io.hermitcrm.publicstats.plist` (new, example), `website/README.md`, `.gitattributes`

- [ ] Example launchd plist, label `io.hermitcrm.publicstats`, runs once a day
  at **06:20 local** (`StartCalendarInterval` Hour 6 Minute 20; launchd runs a
  missed job on wake), command:

  ```sh
  /bin/sh -c 'cd ~/.local/share/hermitcrm-downloads && uv run --no-project --python 3.13 downloads.py collect; uv run --no-project --python 3.13 publicstats.py publish'
  ```

  `collect` first so the page is fresh; `;` not `&&`, so one failing source
  still publishes the rest (the page then shows that source as stale).
  `StandardOutPath`/`StandardErrorPath` to `publicstats.log` in the data folder.
  Paths in the plist use `$HOME`-free absolute placeholders
  (`/Users/YOU/...`) with a comment to replace them.
- [ ] The job runs **copies** in the data folder (same rule as `collect`):
  `publicstats.py` imports `dashboard.py` and `downloads.py`, so all three are
  copied. `dashboard.py`'s `TOKENS_CSS` path is only read by `serve`/`build`,
  not by `summarize()`; confirm `publicstats.py build` runs from the copy
  folder with no checkout around (a test that imports from a `tmp_path` copy
  of the three scripts is enough).
- [ ] `website/README.md`: new section **"Public stats"** after "The dashboard":
  what is on `/stats/`, what is never published, the threshold and
  `public-hide.txt`, the commands, the copy step

  ```sh
  cp scripts/downloads.py scripts/dashboard.py scripts/publicstats.py ~/.local/share/hermitcrm-downloads/
  ```

  installing the plist (`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.hermitcrm.publicstats.plist`),
  how to pause it (`launchctl bootout ...`), and how to take the numbers offline
  at once (`flyctl ssh console -a hermitcrm -C "rm /data/public/numbers.html /data/public/stats.json"`;
  the page then shows the fallback text). Update the "Publish" section's
  "no analytics" sentence: still true (no third party, nothing in the browser),
  but mention the stats page.
- [ ] `.gitattributes`: `export-ignore` for `scripts/publicstats.py`,
  `tests/test_publicstats_script.py`, `tests/test_website_stats.py`.
  (`website/` is already ignored as a whole.)
- [ ] `.venv/bin/pytest` passes. Commit:
  `ai: publicstats: daily launchd job, README section`

## Task 7: Maintainer steps (not for the AI session; put this list in the PR body)

1. Review what `/stats/` would show on the real data before anything goes live:
   `uv run --no-project --python 3.13 scripts/publicstats.py build --out /tmp/stats-preview`
   and read `stats.json`. Add anything private to `public-hide.txt`.
2. `cd website && python3 build.py --release && flyctl deploy --remote-only`
   (with the release tarball in `site/download/` as usual).
3. Copy the three scripts to the data folder, install and load the plist, then
   run it once by hand: `launchctl kickstart gui/$(id -u)/io.hermitcrm.publicstats`.
4. Open https://hermitcrm.io/stats/ and https://hermitcrm.io/stats/stats.json.
5. Optional: post the link with `?ref=` tags so the page's own "Tagged links"
   shows the effect.

## Task 8 (optional, off by default): a weekly note written by Claude

Only if the maintainer wants words next to the numbers. This is the only part
that spends tokens (one short run a week, roughly a few thousand tokens:
it reads `stats.json`, not the raw logs).

- Scheduled task, **Mondays 07:10** (maintainer's time zone), fresh session,
  prompt: read `https://hermitcrm.io/stats/stats.json`, compare the last 7 days
  with the 7 before, write at most 80 words in the site's tone (no em dashes,
  no exclamation marks, no marketing words, no guesses about why), save as
  `website/notes/YYYY-MM-DD.md`, open a draft PR. The maintainer merges it and
  the next deploy shows the latest note above the numbers.
- Needs: a `[stats].note` slot in `render_stats` that shows the newest file in
  `website/notes/` (if any). Build this only when asked.

## Done when

- `.venv/bin/pytest` passes; `python3 website/build.py --release` has no new
  warnings.
- `publicstats.py build` on the test fixtures produces byte-identical output
  twice and contains no user agent, request id or sub-threshold host.
- `/stats/` renders (with Docker preview) in light and dark, at phone width,
  with no CSP errors; without the volume files it shows the fallback text.
- README section "Public stats" explains publish, pause and take-down.
- A draft PR lists Task 7 for the maintainer.
