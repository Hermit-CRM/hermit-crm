# Hermit CRM website

One static page in the "Quiet cabin" style (design direction A).

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
rebuilds the page every time you save `content.toml`; just reload the browser.

Inside any text you can write `**bold**`, `` `code` `` and `[link text](https://...)`.

After each build the script lists every `[TBC]` still on the page and warns about em
dashes, exclamation marks and the banned marketing words from the brief.

## Other things you might change

| What | Where |
| --- | --- |
| Download, SHA-256, GitHub and install-by-hand links | `[links]` in `content.toml` |
| Version, file name, size | `[release]` in `content.toml` |
| App screenshot instead of the drawn placeholder | put the image in `site/img/`, set `[file].screenshot` |
| Colours, sizes, spacing | `site/style.css` (tokens at the top) |
| Page structure | `render()` in `build.py` |
| Share image (`site/img/og.png`) | `python3 build.py --share` (needs Playwright) |

## Publish

Upload the `site/` folder as-is to any static host (GitHub Pages, Netlify,
Cloudflare Pages). It makes no requests to other servers: no web fonts, no
analytics, no cookies, no trackers. Set `[page].site_url` first so
link previews find the share image.

## Fonts

None are downloaded, from Google or anywhere else. The page uses fonts that are
already on the visitor's computer:

- Serif (headings and text): New York in Safari, Iowan Old Style or Charter in
  other Mac browsers, Georgia on Windows.
- Monospace: the same stack as the app (SF Mono, then Menlo).
- The drawn app mock-up: the same system sans-serif as the app.

## Keeping it in step with the app

The app's look is in `src/hermitcrm/static/style.css`. Shared already: the logo
(`site/img/favicon.svg` matches `src/hermitcrm/static/favicon.svg`), the monospace
and sans-serif font stacks. Not shared yet: colour. The app's accent is blue
(`--accent: #1a4fd6`); the site's is the logo green (`--green: #1D8A60`).
