# Website design review, 17 October 2026: findings and fix proposals

Status: **implemented and deployed on 17 October 2026** (commit `5a10196` on branch `website-design-review`, live at
https://hermitcrm.io; the branch is not pushed yet). Done: proposals 1 to 6 and 8 (P-1, P-2), plus the new feature pages.
Not done on purpose: **M-4** (the hero copy is yours to decide), **P-5** (WebP; the screenshots were instead quantised to
under 200 KB) and **P-6** (scale to zero, a cost choice). Not committed: this file is untracked, like the app review next to it
(`design-review-2026-10-17.md`).

**Correction.** Finding H-1 was partly wrong. The docs page already had a "Back to contents" link after every topic (31 of them);
my check searched for "back to top" and missed it. What was true: the page is one very long page on a phone and its contents
and back links were only 24 px tall. H-1 is therefore a Medium finding, the fix was tap targets only (44 px now), and the
Responsive grade moves from 2.5 to 3.0 and the Design Score from B+ (3.4) to B+ (3.5). I also retracted two earlier
findings (button contrast and `transition: all`); see section 2.

Scope: the public site, https://hermitcrm.io (static, `website/`). Pages audited: Home, Docs, Changelog,
About, Compare (overview), Compare/HubSpot, Stats. The live site and the local build
(`python3 -m http.server` on `website/site/`) are byte-identical on every page except `/stats/` (live has real
numbers). Light and dark, 1440 and 375 px, Chrome engine. Screenshots are in the session scratchpad.

Rules these proposals follow (from `website/README.md`, `DESIGN.md`, `CLAUDE.md`): words live in
`content.toml`, structure in `build.py`, style in `site/style.css`; CSS uses tokens only; no web fonts and no
new runtime dependencies; run `python3 website/build.py --release` after every change and commit the
regenerated `site/*.html`; commit messages start with `ai:`; one fix per commit.

## 1. First impression

The site communicates **a person with a point of view who built a tool for themselves and tells you its
limits.** I notice the serif headline "A CRM for one." at 72px on warm paper, with one green button and
nothing else competing. The first three things my eye goes to are the headline, the green Download button,
and the grey install box with its Copy button. That is the intended order. In one word: **quiet**.

Page-area test: Home has six areas I can name in two seconds (header, hero, install steps, the idea, adjust,
what you get, questions). All pass.

**AI slop: A.** None of the ten patterns. No gradient, no icon-in-circle feature grid, not everything
centered, one radius family, real serif stack (Charter / Iowan / Georgia), real monospace, no emoji, no
generic hero copy. The design reads as chosen, not generated.

## 2. What to keep (checked, working)

- Copy button gives real feedback ("Copied", `aria-live`), falls back to "Press ⌘C" if the clipboard is denied.
- Dark mode is a real design: off-white text, desaturated mint links (`--green-ink` 8.19:1), same layout.
- Focus ring (`:focus-visible`, 2px green), skip link, one `h1` per page, alt text that describes what the
  screenshot proves, `width`/`height` on every image (no layout shift), `loading="lazy"`.
- No horizontal scroll on any page at 375 px. The compare table turns into labelled blocks on phones.
- 4 ms load locally, 75 ms TTFB live. Works without JavaScript.
- Compare pages say when the other product is the better choice. That is the strongest trust signal on the site.

**Checked and dropped (not findings):**
- Download button contrast measures 4.32:1. It is 19px at weight 700, which WCAG counts as large text (3:1).
  `style.css:23` already says so. Fine.
- `transition: all`: the CSS declares no transitions at all. Hover and press are instant by design.

## 3. Findings

| ID | Impact | Category | Finding |
|---|---|---|---|
| H-1 | Medium | Responsive | Docs is **one page, 144,501 px tall on a phone** (about 180 screens), with 24 px tall contents links. (Corrected: a "Back to contents" link after every topic already existed.) |
| H-2 | High | Visual hierarchy | The pipeline screenshot, the first proof of the product, is **unreadable**: a 3200×1600 image shown at 618 px puts UI text at about 4 px (desktop) and about 3 px at 375 px. The other three screenshots work (8 px and up). |
| M-1 | Medium | Hierarchy / conversion | Home has **one** Download button, at the top. After three screenshots and nine FAQ answers the page ends at the footer with no next step. |
| M-2 | Medium | Navigation (trunk test: PARTIAL) | The header is **different on the home page and every other page**: Home shows Docs · About · GitHub, all other pages show Docs · About · Download. Compare, Changelog and Stats are only in the footer, although Compare is the page search engines send people to. |
| M-3 | Medium | Typography | **Straight apostrophes everywhere** (`company's`, `didn't`): 1 on Home, 10 on About, 10 on Compare/HubSpot, 139 on Docs, 0 curly. On a serif site set at 19px they show. |
| M-4 | Medium | Content | Hero copy is 51 words in three sentences, and the third is a fragment ("With a pipeline, a calendar, dashboards and enrichment from a company's website.") that **"What you get" repeats three screens later**. Five lines before the button. |
| M-5 | Medium | Responsive | Tap targets on phones: footer links are 21 px tall (Docs, Changelog, Stats, Compare, About), Docs contents links 24 px. Target is 44 px. |
| P-1 | Polish | Content | Compare overview: the Hermit CRM row looks exactly like the competitors' rows. |
| P-2 | Polish | Typography | Stats chart labels use `--sans` (system sans) on an otherwise all-serif site; `DESIGN.md` says the website's text is serif. |
| P-3 | Polish | Layout | Stats: four equal cards with about 60 px of dead space under the figures. |
| P-4 | Polish | Layout | "What you get": `text-wrap: pretty` ends one row at 380 px while its neighbours run to 458 px. |
| P-5 | Polish | Performance feel | `pipeline.png` is 303 KB (PNG). A WebP of the same image is typically 60 to 70% smaller. |
| P-6 | Decision | Performance feel | `min_machines_running = 0` (scale to zero). The first visitor after idle waits about a second (the comment in `fly.toml` says so). At 77 arrivals in 30 days most visits probably hit a cold machine. A deliberate cost choice; flagging it, not recommending a change. |

**Goodwill reservoir: 80/100.** Starts at 70; +10 top task is obvious, +5 upfront about limits ("alpha, no
warranty", "Windows: no"), +5 saves a step (copy button), +5 honest compare pages, then -10 for the unreadable
hero screenshot and -5 for the dead end at the bottom of Home.

## 4. Score

| Category | Weight | Grade (GPA) | Drivers | After fixes |
|---|---|---|---|---|
| Visual hierarchy | 15% | 2.5 | H-2, M-1 | 4.0 |
| Typography | 15% | 3.5 | M-3 | 4.0 |
| Spacing and layout | 15% | 4.0 | polish only | 4.0 |
| Color and contrast | 10% | 4.0 | none | 4.0 |
| Interaction states | 10% | 3.5 | M-2 | 4.0 |
| Responsive | 10% | 3.0 | H-1 (corrected), M-5 | 3.7 |
| Content | 10% | 3.5 | M-4 | 4.0 |
| AI slop | 5% | 4.0 | none | 4.0 |
| Motion | 5% | 4.0 | none (by design) | 4.0 |
| Performance feel | 5% | 3.7 | P-5 | 4.0 |

**Design Score: B+ (3.5). After the proposals below: A (about 3.9).** Scored with the same formula as the app
review: high = one letter, medium = half a letter, polish and decisions do not count.

## 5. Proposals, in order of work

| # | Fix | Files | Effort | Risk |
|---|---|---|---|---|
| 1 | H-1 Docs: 44 px contents and back links on phones (done; the back links themselves already existed) | `style.css` | 10 min | None |
| 2 | H-2 Pipeline screenshot: recapture cropped, link every screenshot to its full size | `site/img/pipeline.png`, `build.py`, `content.toml` | 45 min | Low |
| 3 | M-3 Typographic quotes in the build | `build.py` (`md()` l.168 and the docs renderer), tests | 45 min | Medium (must skip code) |
| 4 | M-2 One header on every page | `build.py` (l.285 and l.555), `content.toml`, `compare/index.toml` | 30 min | Low |
| 5 | M-5 Footer tap targets on phones | `style.css` | 10 min | None |
| 6 | M-1 Closing call to action on Home | `content.toml`, `build.py`, `style.css` | 30 min | Low |
| 7 | M-4 Shorter hero | `content.toml` | 5 min | Needs your OK (customer-facing copy) |
| 8 | P-1, P-2, P-5 | `style.css`, `compare/index.toml`, `site/img` | 30 min | None |

Steps 1, 4 and 5 are independent and safe in one PR. Step 3 deserves its own PR and a diff of every built page.

### 1. H-1: bigger tap targets in Docs (done)

The back links exist already (`.doc-up`, 31 of them). What changed is that, on a phone, the contents links and the
"Back to contents" links are now inline blocks with padding, 47 to 48 px tall. One page per topic (22 pages) is still an
option for later: better for search and AI crawlers, but it changes URLs and `llms-full.txt`.

### 2. H-2: a pipeline screenshot you can read

- Recapture the demo pipeline in a window about **760 px wide** at 2x, cropped to the "Follow up" strip plus
  the Discovery and Offer columns. Shown at 618 px that is a scale of about 0.8, so the 11 px UI text lands
  near 9 px, like the dashboard image that already works. Same demo data (Northwind Robotics), so the
  "file behind this card" box next to it still matches.
- Wrap all four screenshots in `<a href="img/…png">` with the same `alt`, so a tap opens the full image and
  phones can pinch-zoom. Keep the full board as that link target.
- Check: at 375 px the text should be at least 7 px. Today it is about 3 px.

### 3. M-3: typographic quotes, in the build only

In `md()` and the docs renderer, after Markdown has been turned into text nodes and **outside** `<code>`,
`<pre>`, attributes and the JSON-LD block: `(\w)'(\w)` and `(\w)'(\s)` become `’`, and paired `"` become
`“ ”`. Things that must not change:

- The install message and every `data-copy` value (`Read INSTALL.md and set up Hermit CRM for me.`), the
  YAML sample (its `...` is code, not an ellipsis), TOML snippets in the docs.
- `llms.txt` and `llms-full.txt` stay plain ASCII.

Test: build before and after, diff the HTML, and the only changes should be inside prose. Add one
`tests/` assertion for a `<code>` span containing `'`. Apostrophes in the app's own help text are not
touched: this is a render-time change on the site only.

### 4. M-2: one header, same on every page

Recommendation: **Docs · Compare · About · GitHub** on every page, in that order, with the current page
dark and unlinked (as Docs and About already are). The inner pages lose "Download" in the header; they
already carry an in-page "Download Hermit CRM" link, and the brand mark leads home. Below 440 px hide
"About" (it stays in the footer) so four links and the brand still fit in 335 px; there is already a
`max-width: 439px` block in `style.css:429`. If you would rather keep About in the header on phones, the
alternative is to drop "GitHub" there, which is in the footer too.

### 5. M-5: footer links on phones

```css
@media (max-width: 720px) {
  .site-footer a { display: inline-block; padding: 12px 4px; }
}
```

(`.site-footer` is the real class, `style.css:334`.) Done when each link measures
at least 44 px tall in the browser and the footer still wraps into two or three lines, not five.

### 6. M-1: a last call to action on Home

After the FAQ, one block in the site's own voice: one sentence ("Free, Apache 2.0, and your data stays in a
folder on your computer.") and the same `.btn` pointing at the same tarball. No new section heading, no
cards, no second button. Words go in `content.toml` so the `--release` check covers them. If you think a
repeat button breaks the quiet, the minimum is the line "Download for Mac and Linux" as a text link
above the footer.

### 7. M-4: hero (customer-facing copy, your decision)

Current (51 words): "A free, open-source CRM for founders, freelancers and anyone doing their own sales.
It keeps your companies, contacts and conversations as plain text files on your laptop, and your own AI
agent can reshape it to fit how you work. With a pipeline, a calendar, dashboards and enrichment from a
company's website."

Proposal (40 words): "A free, open-source CRM for founders, freelancers and anyone doing their own sales.
It keeps your companies, contacts and conversations as plain text files on your laptop, and your own AI
agent can reshape it to fit how you work."

The cut sentence is the feature list, which "What you get" already gives in a scannable table. The
hero then fits in four lines at 640 px. This is your wording and your positioning, so I have not touched
`content.toml`.

### 8. Polish

- **P-1:** give the Hermit CRM row on `/compare/` and the "Hermit CRM" column on each page `font-weight: 600`
  (no color, no tint: the site has no highlight color and does not need one).
- **P-2:** `.chart text { font: 22px var(--serif); }` (`style.css:319`), or `--mono` for the axis figures.
  Either is a token, so `test_tokens`-style checks still pass.
- **P-5:** export `pipeline.png` (and the three others) as WebP with the PNG as `<picture>` fallback. With
  proposal 2 you recapture it anyway.

## 6. Not covered

Safari and Firefox (the `light-dark()` fallback in `style.css:42` is untested here), a screen reader pass,
and a cold-start measurement of the live Fly machine. The `/stats/` page was reviewed live only; the local
build has placeholder numbers.
