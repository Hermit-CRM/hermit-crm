# Hermit CRM website

A static site in the "Quiet cabin" style (design direction A): the home page and
the comparison pages under `/compare/`.

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

## Other things you might change

| What | Where |
| --- | --- |
| Download, SHA-256, GitHub and install-by-hand links | `[links]` in `content.toml` |
| Version, file name, size | `[release]` in `content.toml` |
| App screenshot instead of the drawn placeholder | put the image in `site/img/`, set `[file].screenshot` |
| Colours, sizes, spacing | `site/style.css` (tokens at the top, light and dark) |
| Brand green, font stacks, the drawn app's colours | `src/hermitcrm/static/tokens.css` (shared with the app; see `DESIGN.md`) |
| Page structure | `render()` in `build.py` |
| Share image (`site/img/og.png`) | `python3 build.py --share` (needs Playwright) |

## Publish

Upload the `site/` folder as-is to any static host (GitHub Pages, Netlify,
Cloudflare Pages), including the generated `app-tokens.css`. It makes no requests to other servers: no web fonts, no
analytics, no cookies, no trackers. Set `[page].site_url` first so
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
   `--release` refuses to finish. Then `flyctl deploy --remote-only`.

Keep older files in `site/download/` if people may still link to them.

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
