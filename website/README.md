# Hermit CRM website

A static site in the "Quiet cabin" style (design direction A): the home page,
the comparison pages under `/compare/`, the About page and the docs under `/docs/`.

This folder is for the maintainer only. `.gitattributes` marks it `export-ignore`,
so `scripts/release.sh` (which uses `git archive`) leaves it out of the download,
and it is outside `src/`, so it is not in the installed package either. It is
still in the git repository: if the GitHub repo goes public, so does this folder.

## Change the text

All words on the page are in **`content.toml`**. Edit them there, then run:

```sh
python3 build.py
```

and open `site/index.html` in a browser. While you edit, `python3 build.py --watch`
rebuilds the page every time you save `content.toml`, `site/style.css` or the app's
`tokens.css`; just reload the browser.

Inside any text you can write `**bold**`, `` `code` `` and `[link text](https://...)`.

After each build the script lists every `[TBC]` still on the page and warns about em
dashes, exclamation marks and the banned marketing words from the brief.
`python3 build.py --release` does the same and exits with an error while any of
them are left, so run that one before you publish.

## Comparison pages

`/compare/` and one page per other CRM (`/compare/hubspot/`, `/compare/attio/`, ...)
come from the files in **`compare/`**:

- `compare/index.toml`: the overview text, the rows of every comparison table with
  Hermit CRM's side, the paragraph about Hermit CRM that every page repeats, and
  the headings.
- `compare/<name>.toml`: one per other CRM. The file name is the address, so
  `compare/salesforce.toml` becomes `/compare/salesforce/` and shows up on the
  overview, in "Other comparisons", in `sitemap.xml` and in `llms.txt` by itself.
  Copy an existing file to start one. Its `[cells]` must fill every row of
  `index.toml`, or the build stops and names what is missing.

Every claim about another product has a source in its file and a `checked` date,
shown on the page and used as the sitemap's `lastmod`. Prices change often:
check them all again before you change the date. Keep the tone fair (each page
says when the other CRM is the better choice); it is what makes the pages
trusted by readers and quoted by AI search engines.

Made for search engines and AI answer engines:

- Plain HTML, no scripts needed to read it, one `h1`, and the short answer first.
- A real `<table>` for the comparison, which stacks into labelled blocks on phones.
- JSON-LD on every page: `WebPage`, `BreadcrumbList`, `FAQPage` (from the
  questions) and `SoftwareApplication` for Hermit CRM; the home page gets
  `WebSite` and `SoftwareApplication`.
- `site/llms.txt` ([llmstxt.org](https://llmstxt.org)): a plain-text summary of
  Hermit CRM with a link and the short answer for every comparison.
- A canonical URL per page and every page in `sitemap.xml`.

Links between pages end in a slash (`compare/hubspot/`), which a web server
turns into `index.html` but a browser opening files from disk does not. To click
through the pages locally, serve the folder: `python3 -m http.server -d site 8000`.

## Docs

`/docs/` is the app's Help, all on one page, and `llms-full.txt` is the same text
as one Markdown file for AI tools. Neither has text of its own to edit: both are
built from `src/hermitcrm/help/*.md`, the pages the app shows under Help and
`hermitcrm help <topic>` prints. Change a topic there and the app, the CLI and
the website all follow. Only the words around them (title, intro, labels) are in
`[docs]` in `content.toml`.

The build takes the Help pages from the download in `[links].download` (the
tarball in `site/download/`), not from this checkout, so the docs describe the
version people get and not work on main that is not released yet. Publishing a
new version (below) therefore updates the docs with no extra step. Without the
tarball the build falls back to `src/hermitcrm/help/` and warns; `--release`
refuses that, and refuses docs whose version is not `[release].version`.

What changes on the way: links between Help pages become anchors on the page
(`/help/settings#bcc-capture` becomes `#settings-bcc-capture`), links into the
rest of the app (`/welcome`, `/settings`) become plain text, and two topics are
left out: the Help index (the contents list replaces it) and Feedback (a form in
the app). The topics are in the app's own order, with the Make it yours recipes
listed separately in the contents.

For AI tools: `llms.txt` lists every topic with its first paragraph before
anything else, every page's `<head>` links to `/docs/` (`rel="help"`) and to
`llms-full.txt`, the `SoftwareApplication` data names `/docs/` as its
`softwareHelp`, and `/docs/` is in `sitemap.xml` with the release's date. People
see one "Docs" link in the header and the footer.

## Other things you might change

| What | Where |
| --- | --- |
| Download, SHA-256, GitHub and install-by-hand links | `[links]` in `content.toml` |
| Version, file name, size | `[release]` in `content.toml` |
| Any screenshot: its file, alt text and window address | `shots.toml`, one table per shot; pages name it with `shot = "key"` (below) |
| Retake the screenshots | `python3 screenshots.py` (below) |
| The "Make it yours" examples (what you type, what changes, the screenshot) | `[yours]` in `content.toml`; the pictures are shots in `shots.toml` |
| The tiles under the first screen of the home page | the pages in `features/*.toml` (name, `summary`, screenshot): the same tiles as `/features/` |
| Colours, sizes, spacing | `site/style.css` (tokens at the top, light and dark) |
| Brand green, font stacks, the drawn app's colours | `src/hermitcrm/static/tokens.css` (shared with the app; see `DESIGN.md`) |
| Page structure | `render()` in `build.py` |
| Share image (`site/img/og.png`) | `python3 build.py --share` (needs Playwright) |

## Feature pages

`/features/` and one page per link in the app's left navigation
(`/features/pipeline/`, `/features/calendar/`, ...) come from the files in
**`features/`**, built the same way as the comparison pages:

- `features/index.toml`: the overview text and the labels every page shares.
- `features/<name>.toml`: one per page. The file name is the address. `order`
  puts it in the same order as the app's sidebar, `summary` is the line shown on
  the overview and in "What you get" on the home page, `docs` is the topic its
  "Read the full page in the docs" link goes to (`contents` for the top), and
  each `[[sections]]` has a `heading`, `text` and/or `points`, and optionally an
  `image` with its `alt` text and the `address` shown in the window frame.
- A row of "What you get" in `content.toml` links to its page by `slug`.

A page's screenshots come from `shots.toml`, the one list of every picture on
the site. Each table is a **shot**: `file` (in `site/img/`), `alt` and `address`
(shown in its window frame) are what the build reads, and the rest says how to take
it (see "Retaking the screenshots"). A section of a feature page, `[file]` and each
`[[yours.examples]]` in `content.toml` ask for one with `shot = "pipeline-board"`.
A section can still write its own `alt` or `address`, which wins. Because the home
page and `/features/` name the same keys, they always show the same files with the
same words, and a picture is changed in one place. `site/img/thumbs/<slug>.png` are
the pictures on the tiles, on `/features/` and on the home page: the top of each
page's first screenshot at 3:2, 720 px wide, made by the same script (`thumb =
"<slug>"` on that shot). The build checks that every image, related page and docs
topic exists, and refuses a screenshot over 200 KB. Selecting a screenshot opens it
full size, which is how a phone shows the small print.

The home page shows every feature page as a tile directly under the first screen,
and each section that has a page ends with a link to it (`more` and `more_link` in
`[file]`, `[yours]` and `[outreach]`). The header has **Features** as the one button.

## Retaking the screenshots

```sh
python3 screenshots.py                    # all of them, from the release in [links].download
python3 screenshots.py --only outreach-card ask-panel
python3 screenshots.py --source ~/Code/HermitCRM     # a checkout: what main looks like
python3 screenshots.py --list
```

It is a maintainer tool, outside the package (`website/` is export-ignored), and needs
Playwright and Pillow for this Python, the same Playwright `build.py --share` uses.
Each run starts from nothing: it unpacks the version (the release tarball by default,
or a checkout's `src/`, whichever version you give it), makes a new demo folder with
`hermitcrm init --demo` in a temp folder, serves it on a spare port and takes each shot at
2x, cropped, quantised to 256 colours, so a shot weighs about 100 KB. It never touches
`~/crm` or a server you have running. It clicks through the real pages as a person
would; what the AI and the web would say is scripted in `screenshots_app.py` (made-up
companies and words, the app's own cards, checks and critic). Without that the
screenshots would call a real AI CLI.

The default is the released version, because the site shows what people can download.
Retake after every release (`[release].version` and the tarball in `site/download/` first),
and look at the pages before you deploy. To see unreleased work, pass `--source` with a
checkout; do not deploy those images until it is released.

Some shots need the demo in a state of its own and get a fresh copy of it (`scene` in
`shots.toml`): the Make it yours field (the `contract_renewal` field from `hermitcrm help
adjust-fields`, filled in with `hermitcrm set`), the routine (turned on and run once)
and the Upgrade button (a made-up newer version, 1.0.1, so the button shows). The
Outreach cards are made through the Generate panel with the scripted AI, and the data
folder shows as `~/crm`. Windows are 1200 px wide (900 for Make it yours, 1500 for Messages).

## Publish

Upload the `site/` folder as-is to any static host (GitHub Pages, Netlify,
Cloudflare Pages), including the generated `app-tokens.css`. It makes no requests to other servers: no web fonts, no
analytics, no cookies, no trackers. (The site's own numbers are public at
`/stats/`, counted from nginx's logs on the server; see "Public stats".) Set `[page].site_url` first so
link previews find the share image.

### Publishing a build

The download is served by the site itself, from `site/download/`. The files
are not in git (`site/download/` is ignored), so copy them in before you
deploy:

1. Build the release from a clean worktree of the release commit
   (`./scripts/release.sh` in the repo root; it writes `dist/`).
2. Copy `dist/hermitcrm-<version>.tar.gz` and its `.sha256` to `site/download/`.
3. Point `[links].download` and `[links].sha256` at them and set
   `[release].version`.
4. `python3 build.py` warns when a linked file is missing, and
   `--release` refuses to finish. The same build rebuilds `/docs/` and
   `llms-full.txt` from the new tarball (see "Docs"). Then
   `flyctl deploy --remote-only`.

Keep older files in `site/download/` if people may still link to them.

## Counting downloads and visitors

`scripts/downloads.py` counts downloads on all three channels, website visitors
and GitHub's own numbers, and keeps them (`collect` fetches and saves, `report`
prints). `scripts/dashboard.py` shows the same numbers as one page (see
"The dashboard" below). Both are maintainer tooling: `.gitattributes` keeps them
out of the download.

| Channel | Where the count comes from |
| --- | --- |
| Website | the tarball log nginx writes to the Fly volume |
| GitHub | release asset counts, clone and view traffic, referrers and popular pages (14-day windows, so they must be saved), stars with their dates, forks and watchers |
| PyPI | pypistats.org for daily totals, and ClickPy (the public copy of PyPI's download log) for who downloaded |
| Website visitors | the page log nginx writes next to the tarball log (below) |

**The website log.** `nginx.conf` logs only `GET /download/hermitcrm-<version>.tar.gz`
requests, one JSON line each, to `/data/downloads.log` on the Fly volume
`downloads` (1 GB, created once with the command in `fly.toml`). No IP address
and no referer are kept; the `.sha256` files and the `www` redirect log nothing
(the pages go to a second log, next section). The volume survives deploys and machine stops. Do not delete it:
the log goes with it (Fly keeps 5 daily snapshots). stdout is no use for this:
`flyctl logs` keeps only the last 100 lines.

**The page log.** `nginx.conf` also logs every HTML page, `llms.txt` and `llms-full.txt`, one JSON
line each, to `/data/visits.log` on the same volume. Still no IP address and no
cookie, and of the referer only the host (`news.example.com`, never the path or
query). Images, CSS, `robots.txt` and the Fly health check (which is why it asks
for `/robots.txt` and not `/`) are not logged. The log keeps the browser's
`Sec-Fetch-Site`, `-Dest` and `-Mode` headers, and `report` uses them like this:

| Counted as | What it is |
| --- | --- |
| People | a browser that says it is opening a document, whose name is not a known bot |
| Arrivals | the people whose first page came from a link, a bookmark or the address bar (`cross-site` or `none`). A click from one page of the site to another is `same-origin` and only a page view. This is the closest thing to "visitors" the log allows, because no IP or cookie means nobody can be recognised on a second visit |
| AI crawlers and assistants | GPTBot, ClaudeBot, PerplexityBot and the like, and assistants fetching a page because someone asked (ChatGPT-User, Claude-User...). Listed by name, never counted as visitors |
| Bots, scripts, yours | link previews and anything else that is not a browser; curl and scripts; `?own`, `ignore.txt` ids and the `hermitcrm.fly.dev` copy |

Put `?ref=hn` (or `?utm_source=hn`) on a link you post and the dashboard lists the
arrivals under "Tagged links": that is how Reddit, Hacker News, a newsletter or a
mail count without any of them having an API. The log is never trimmed; at a few
hundred bytes a view, 1 GB is years. Deploy `website/` once before `collect` can
fetch it; until then the source says so and the dashboard shows an empty Visitors
section.

**Your own downloads.** Add `?own` to the link (nginx ignores the query string)
or use `curl -A selftest`, and `report` lists the request under "yours". For a
request that is already in the log, put its `id` in `ignore.txt` in the data folder
(one per line, `#` for comments); nothing is deleted from the log.

**Link scanners.** Anything that publishes the download link (a PR, a post, a
mail) gets it fetched within seconds by scanners, some with a browser's name in the
user agent. The log keeps the browser's `Sec-Fetch-Site` / `Sec-Fetch-User`
headers, and `report` calls a browser-named request without them a bot. That is a
heuristic: the website number is an upper bound, most trustworthy once the first
burst after a launch has passed.

**What a PyPI number means.** A new release gets a few hundred downloads in its
first days from mirrors, scanners and crawlers. pypistats' "without mirrors" still
includes browser downloads and Python scripts. The number for people who ran
`pip install` or `uv` is "pip/uv installs" in the report; `report --installs`
lists each one with its country, Python and system. None of the three counts
unique people, and a person who uses two channels is counted twice.

**Running it.**

```sh
uv run --no-project --python 3.13 scripts/downloads.py collect
uv run --no-project --python 3.13 scripts/downloads.py report --installs
```

The data is in `~/.local/share/hermitcrm-downloads/` (set `HERMITCRM_DOWNLOADS_DIR`
to move it; keep it out of the repository). A launchd job, `io.hermitcrm.downloads`,
runs `collect` every 6 hours. It runs a *copy* of the script in that folder, not
the checkout, so a branch in progress never runs unattended; after changing the
script, copy it over again:

```sh
cp scripts/downloads.py ~/.local/share/hermitcrm-downloads/downloads.py
```

`collect` exits 1 when a source fails, which launchd shows as a failed job.

## The dashboard

```sh
uv run --no-project --python 3.13 scripts/dashboard.py serve --open
```

serves one page on `http://127.0.0.1:8777` (this computer only; `--port` changes it) from the files
`collect` saved. **Refresh** runs `collect` and reloads, so you do not need the
launchd job to look at it; the job is for not losing the 14-day windows. A failing
source does not blank the page: it shows what is saved and the Sources table at the
bottom says which source failed and since when. `dashboard.py build` writes
`dashboard.html` into the data folder instead, a static copy without the button.

The page shows the Visitors section first (who came to the website, and from where),
then real downloads per day (PyPI installs and website downloads), GitHub's numbers, who downloads, and a "Left out" table with every
count that was set aside (CI, mirrors, browsers on PyPI, bots, your own), so a
total that looks low can be checked. It makes no counting rules of its own: it calls
`downloads.py`, so the page and `report` always agree. Run the dashboard from the
checkout, not the launchd copy: it imports `downloads.py` from the same folder.
(The data folder has a copy of `dashboard.py` too, for `publicstats.py`; see below.)

## Public stats

Hermit CRM is built in public: https://hermitcrm.io/stats/ shows the site's own
numbers, and https://hermitcrm.io/stats/stats.json has the same numbers as data.
They are updated once a day, with no AI and no redeploy in the loop.

**How it fits together.** `build.py` writes the page shell, `site/stats/index.html`,
with the text from `[stats]` in `content.toml`. The numbers are a fragment,
`numbers.html`, that `scripts/publicstats.py` builds from the data folder and
uploads to the Fly volume (`/data/public/`). nginx includes it into the shell with
SSI (`nginx.conf`, `location /stats/`), so a new day's numbers are an upload, not a
`flyctl deploy`. Until the fragment exists the page says "not published yet";
opened from disk it always says that, because browsers ignore SSI.

**What is on it.** Arrivals per day and where they came from, pages, tagged links,
downloads per day and per version, GitHub stars, forks, visitors and cloners, AI
crawlers and assistants by name, installs by country and installer, and the "Left
out" totals. Charts cover the last 90 days. The counting is `dashboard.summarize()`,
so the page, the dashboard and `report` agree.

**What is never on it.** User agents (only AI product names such as ClaudeBot),
request ids, times finer than a day, single PyPI install rows, Python versions,
GitHub stargazers, the source error messages, and anything counted as yours
(`?own`, `ignore.txt`). In every list, a name seen fewer than 3 times (a referrer
host, a page, a tag, a country) is counted under "Other": one visit from
`mail.someones-company.example` can point at one person. To hide a name whatever
its count, put it in `public-hide.txt` in the data folder (one host, page or tag per
line, `#` for comments). That file stays out of git: it names what it hides.

**Running it.**

```sh
uv run --no-project --python 3.13 scripts/publicstats.py build --out /tmp/stats-preview   # look first
uv run --no-project --python 3.13 scripts/publicstats.py publish                          # build and upload
```

`build` writes `numbers.html` and `stats.json` (to `<data>/public/` by default).
`publish` builds, then uploads only when the files changed (`--force` uploads anyway).
The same data and the same `--today` give the same bytes. A failed upload exits 1
and shows as `publish` in the dashboard's Sources table. When a source's `collect`
failed, the page says how old that section's numbers are.

**The daily job.** `io.hermitcrm.publicstats.plist` (in this folder) runs
`collect`, then `publish`, every day at 06:20, or on wake if the Mac was asleep.
Like `collect`, it runs copies in the data folder, and `publicstats.py` needs all
three:

```sh
cp scripts/downloads.py scripts/dashboard.py scripts/publicstats.py ~/.local/share/hermitcrm-downloads/
cp website/io.hermitcrm.publicstats.plist ~/Library/LaunchAgents/   # then replace YOU in it
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.hermitcrm.publicstats.plist
launchctl kickstart gui/$(id -u)/io.hermitcrm.publicstats            # run it once now
```

Pause it with `launchctl bootout gui/$(id -u)/io.hermitcrm.publicstats`. Its
output is in `publicstats.log` in the data folder.

**Taking the numbers offline at once:**

```sh
flyctl ssh console -a hermitcrm -C "rm /data/public/numbers.html /data/public/stats.json"
```

The page then shows the "not published yet" text and `stats.json` is a 404, until
the next `publish` (pause the job first).

## Fonts

None are downloaded, from Google or anywhere else. The page uses fonts that are
already on the visitor's computer:

- Serif (headings and text): New York in Safari, Iowan Old Style or Charter in
  other Mac browsers, Georgia on Windows.
- Monospace: the same stack as the app (SF Mono, then Menlo).
- The drawn app mock-up: the same system sans-serif as the app.

## Keeping it in step with the app

`DESIGN.md` at the root of the repository has the whole picture. In short: the
app's defaults live in `src/hermitcrm/static/tokens.css`. Every build copies them
into `site/app-tokens.css` (generated; do not edit): the brand green and the font
stacks for the whole page, the app's palette only inside the drawn app, which
therefore always looks like the real app in light and dark. If the site uses a
token that the app no longer defines, the build stops and names it.

The accents differ on purpose: the app's is blue (`--accent`), the site's is the
logo green (`--green`, which is the shared `--brand`).
