# A way to see Hermit CRM without installing it: hosted demo or click-through tour

Status: PROPOSAL, waiting for Gijs's decision. Nothing here is built.
Written 2026-10-27. No code, no deploy, no sign-ups were done for this plan.

## The problem in plain words

Hermit CRM needs Python and an AI coding agent to install. People who arrive from
Hacker News or Product Hunt will not do that just to look. The stats page shows
about 120 arrivals a month, so each arrival that leaves without seeing the product
is a real loss. We need a way to see the app in two minutes, with no install, that
fits a product whose promise is "local, no cloud, no telemetry".

## What I looked at

- The site: a static nginx image on Fly, built by `website/build.py`, text in
  `website/content.toml`. It makes no requests to other servers. Its security
  header (`nginx.conf`) allows only its own CSS and images, and forbids framing.
- `/stats/`: the page shell is in the image, the numbers are a file on the Fly
  volume, pulled in with SSI, refreshed once a day. A page can change without a
  deploy this way.
- The visit log: nginx already logs every HTML page with its query string (`q`),
  no IP, no cookie. `?ref=hn` or `?utm_source=` links are counted as "Tagged links".
  The download log also keeps the query string.
- The app (`web.py`): 46 pages you can only look at (GET) and more than 100
  routes that change something (POST). It is built to run on `127.0.0.1` for one
  person with no login. I searched `web.py` for a read-only switch
  (`read_only`, `readonly`) and found none. It would have to be built.
- `hermitcrm init <dir> --demo` makes a folder of fictional companies, people,
  tasks, a pipeline, a dashboard and a paused routine.
- The site already has about 14 real screenshots of the app, taken with Playwright
  from a demo folder of the released version (`website/README.md`, "Feature pages").
  `build.py --share` already uses Playwright, so it is a dev-only tool already.
- Hosted tour tools: pricing pages read on 2026-10-27.

## The options

- **A1. One shared live demo.** The real app on Fly with demo data. Everyone sees
  the same copy. It needs a read-only mode, plus a reset on a timer.
- **A2. A fresh copy per visitor.** Each visitor gets their own throwaway app
  and folder. Full freedom to click, full freedom to break things.
- **B1. A hosted tour tool** (Arcade, Supademo, Storylane, Navattic).
- **B2. A tour we build ourselves.** Plain HTML pages on the existing site, one
  page per step, using screenshots that a script regenerates from the demo folder.
  No script is needed in the visitor's browser: "next" and "back" are ordinary links.
- **C. A static copy of the real app.** At build time a script opens every page of
  the app against the demo folder and saves the HTML. The visitor clicks through
  real pages, with no server behind them. Buttons that would change something show
  "this is a demo, here is how to install". A small guide strip can sit on top.

One better option than any single one of these: **do B2 first and C second, on one
shared capture script** (staged path below). B2 is the quick win. C reuses the same
demo folder and the same headless browser, and replaces screenshots by real pages.

## Facts about the hosted tour tools (read 2026-10-27)

| Tool | Free plan, as the pricing page says | Paid start |
| --- | --- | --- |
| Supademo | 5 guided interactive demos, unlimited views, 1 creator, share by link, embed, video and PDF. Watermark not stated. | Scale: $50/month ($38 billed yearly) |
| Navattic | 1 demo, unlimited views, 1 seat, basic analytics | Prices not shown on the page |
| Storylane | 1 published demo, unlimited views, 1 seat. "Remove the Storylane logo" is a paid feature, so the free one carries the logo. Embedding on the free plan is not clear from the page. | Starter: $50/month ($40 yearly) |
| Arcade | The pricing page I could read is for its AI video product (free: 30 second videos, watermark). Its interactive demo plans sit on a separate page that I did not read. Treat as unknown. | Pro video plan: $49/month yearly |

Free plans exist and show unlimited views, but all four run the demo from their own
servers, usually as an embedded frame or script on our page. Details can change; they
need a look again before anyone signs up.

## Scored matrix

Higher is better for the maintainer. For every row, 5 means easy, safe, cheap or
fast; 1 means hard, risky, expensive or slow.

| | A1 Shared live demo | A2 Copy per visitor | B1 Hosted tool | B2 Own tour | C Static export |
| --- | --- | --- | --- | --- | --- |
| **1. Effort to build** | **2**. Read-only mode must be built across 100+ routes, plus reset, plus a second Fly app: ~4 sessions | **1**. A1 plus sandboxing and cleanup per visitor: ~6+ sessions | **5**. A few hours of recording by Gijs | **4**. ~2 sessions; the first page can reuse the 14 existing screenshots in one | **3**. ~3 sessions: crawl the 46 page types, fix links, switch buttons off |
| **2. Effort to maintain** (regenerates from code?) | **3**. Always the current code, but every new risky feature needs a new switch | **3**. Same as A1, more to watch | **2**. Re-record by hand after UI changes; ~190 commits in 8 days will date it fast | **4**. One command retakes every screenshot; the step text still needs a human when a screen changes | **5**. Whole demo is rebuilt from code on every build; a broken link fails the build |
| **3. Potential to grow** | **4**. Real clicking; canned "Ask" answers must be faked | **5**. Anything the app does | **3**. Guided steps and branching are built in; try-your-own-CSV and canned answers are not possible | **4**. Segments (freelancer, consultant) are just other step lists; own-CSV not possible | **4**. Segments = different demo folders; canned "Ask" answers are easy to put in; own-CSV not possible (a later, browser-side idea at best) |
| **4. Security and abuse risk** | **1**. Public server that can mail, read mail, run AI programs, hold keys, commit to git (list below) | **1**. Same list, times many visitors; people will try it | **5**. Nothing of ours is exposed | **5**. Images and links only | **4**. No server; the one risk is putting real data in the demo folder, and the app's own scripts run on our domain, so the demo section needs its own header rules |
| **5. Running cost on Fly** | **4**. Small machine that sleeps when idle: a few dollars a month (Fly prices not rechecked today) | **2**. A machine or a volume per visitor; one spike from HN costs real money | **5**. $0 on a free plan, $38-50/month if the watermark must go | **5**. Static files in the image we already pay for | **5**. Same |
| **6. Fit with the product promise** | **2**. A cloud copy of a product that says "no cloud"; first party, but a server | **1**. Same, and visitor-entered data sits on our server | **1**. Third-party script or frame, the vendor's cookies and analytics, and the site's header would have to be loosened. Directly breaks "no widget scripts" | **5**. The site stays what it says it is | **4**. First-party, no server, but real app code runs on the site |
| **7. Measurability** (`?ref=demo`, no app telemetry) | **4**. Arrival and pages are in the existing log; a click inside the app is not counted unless we log it, which we should not | **3**. Same, more noise | **2**. Their dashboard has the numbers, not ours; our log sees only the arrival | **4**. Each step is its own page, so our log shows how far people got (below) | **4**. Same, each page is a log line |
| **8. Time to first usable version** | **1**. Weeks of careful work | **1**. Weeks | **5**. 1 day, but only a free-plan demo | **4**. A first version in 1 day, a good one in ~3 | **3**. ~4-5 days |
| **Total (of 40)** | **21** | **17** | **27** | **35** | **32** |

Why B1 scores 27 and not lower: it is the fastest and the safest. It loses on the
promise, on staying up to date, and on measurement, and those are the three that
matter most for this product.

## Recommendation

**Build the tour yourself, in two stages. Stage 1 is the plain-HTML tour (B2),
shipped before Show HN. Stage 2 is the static copy of the real app (C), built on
the same script and reached from the same page. Do not build a hosted live demo
(A) and do not use a hosted tool (B1) for launch.**

Why:

1. **It keeps the promise.** The site stays plain HTML with no widget scripts, and
   no visitor data leaves it. A tour that needs a vendor's script or a live server
   would be the first thing HN comments pick at for a "local, no cloud" product.
2. **It is the only route that stays fresh on its own.** Both stages are produced
   by a script from the demo folder, so a big redesign means one command, not a
   re-recording session.
3. **The live demo is the most expensive route and the least safe.** The app was
   built for one person on their own machine, with no login and no read-only mode.
   A public copy can send mail, run AI programs and write to git unless every
   route is shut. That is a real security project, not a launch task.
4. **It is measurable without telemetry.** Each step is a page, and the existing
   visit log already keeps each page and its `?ref=`.
5. **It is quick.** Stage 1 can start with the 14 screenshots that already exist.

When to look at A again: if people write "I want to try it with my own data", build
the one thing that answers it, which is the install itself, made easier. A hosted
copy would not be "your own data" either.

## What a public live instance would have to switch off (why A is risky)

Only for the record; this is not planned. A public instance would need all of this
closed, with a read-only switch that does not exist today:

- **Every route that changes something**: more than 100 POST routes (companies,
  contacts, interactions, tasks, stages, settings, outreach, learning, routines).
  Needs one switch that refuses every POST, tested against the route list so a new
  route cannot slip by.
- **Sending email over SMTP**: Settings > Send, the test button, the send job,
  and the Outreach send, schedule and resume buttons.
- **Reading email over IMAP**: the reply check, BCC capture and its test.
- **Starting AI programs**: Ask the Hermit (`/ask`), Enrich (company and contact),
  the adjust agent, playbook drafting, Learning runs, and "try" on routines. These
  start a command on the machine (`subprocess` in `enrich.py`, `ask.py`).
- **Secrets**: `secrets.py` (environment, `.secrets.toml`, macOS Keychain) and the
  settings pages that write them. A public copy must hold none and show none.
- **Writing git commits and pushing**: `gitops.py`, backup (`/settings/backup`),
  undo (`/yours/undo`).
- **Importing and exporting files**: `/import`, `/bcc/import`, `/learning/import`,
  and `/export.zip`, which downloads the whole folder.
- **Upgrading and restarting the server**: `/upgrade`, `/reload`.
- **The MCP server**: it speaks over stdio on the same machine, not over the
  network, so a web instance does not expose it. It still must not be started there.
- **The login-less design**: the app trusts whoever reaches it and checks only the
  host name and that a change did not come from another website. Public use is
  outside what it was built for.

## Stage 1: the tour (B2), shippable in days

**What the visitor sees.** `hermitcrm.io/tour/` is a plain page: one real
screenshot, two or three sentences, "Back" and "Next" links, and a step list. Each
step is its own page (`/tour/pipeline/`, `/tour/company/`, ...). The last page says
"Install it" with the download and the agent install line.

**Steps for a first version** (about 8, the daily job of a solopreneur):
Home and today's tasks, the pipeline, a company page with its history, a contact
with a drafted message, Outreach (review, approve), the calendar, reports and
dashboards, then "It is your files" (a file in an editor and `git log`).

**How it is built** (no new runtime dependency):
- A new `[tour]` section and steps in `website/content.toml`, plus a page template
  in `build.py`, in the style of the feature pages. No browser script is needed.
- Day 1 (1 session): the page, built from the existing feature screenshots.
  Shippable on its own.
- Days 2-3 (1-2 sessions): a script, `website/tour_shots.py`, dev only like
  `--share`, that makes a demo folder with `hermitcrm init --demo` from the
  **released tarball** (the site's existing rule), serves it on a spare port, and
  takes the step screenshots with Playwright at the same size as today. It checks
  that no screenshot is missing and fails the build if a step's picture is older
  than the release.
- Keep each image under ~200 KB (the existing rule).
- A short "Not installed yet? This is what it looks like. Nothing is stored." note.

**Measuring** (no telemetry in the app):
- Links you post carry `?ref=demo` (or `?ref=hn-demo` for a Hacker News post that
  points at the tour). The existing "Tagged links" list on `/stats/` counts these
  arrivals.
- Steps are pages, so `/stats/` already shows how many people reached `/tour/`
  and each step after it.
- The "Install" button on the last page links to the download with
  `?ref=demo-tour`. The download log keeps the query string, so downloads that came
  through the tour can be counted. A person who downloads later is not counted;
  say so on the stats page.
- Needs one small decision: whether `scripts/publicstats.py` should list `/tour/`
  steps on their own line. That is a script change, not an app change, and is part
  of the stats job.

## Stage 2: the real app, frozen (C), a week or two later

**What the visitor sees.** The real interface at `hermitcrm.io/demo/`, filled with
the demo data. They can click from the pipeline to a company to a contact, open a
draft, sort and filter. Pages that would change something show "This is a demo.
Install Hermit CRM to do this" and the install line.

**How it is built:**
- A build step opens every GET page of the app in-process (the app's own test
  client, no network) against a fresh demo folder, saves the HTML under
  `site/demo/`, rewrites links to point inside it, and swaps forms and POST buttons
  for the install note. 46 page types, a company and contact page per demo record.
- The same step writes the "Ask the Hermit" answers: a handful of canned
  questions with saved answers, clearly labelled as examples.
- A guide strip (plain HTML, links only) on top: "Step 3 of 6: open a company".
  Segments by use case are different demo folders and different step lists
  (freelancer, consultant, small agency).
- A small nginx block for `/demo/` with its own header rules. The app's pages use
  inline style and script, which the site's strict header forbids today, so this
  needs one reviewed change to `nginx.conf` limited to that folder.
- A check in the build that the demo folder holds only fictional data (the
  repo's rule) and that no saved page mentions a real address, path or version
  not in the release.

**Try-your-own-CSV** needs a server or a script that parses the file in the
browser. Neither fits the promise cheaply. Leave it out; the install is the answer.

## Risks

- **A stale tour.** The app changes daily. Mitigation: screenshots and pages are
  regenerated from the released version, the build refuses if one is missing, and
  the tour steps name features, not buttons.
- **Tour and release out of step.** The site rule is "show what people can
  download". Taking screenshots from the release tarball keeps the tour in step,
  which also means a new feature appears in the tour only after its release.
- **Real data leaking into a screenshot.** The demo folder is fictional, and
  screenshots are taken only from a fresh demo folder, never from a working folder.
  CLAUDE.md's rule on real names applies to the tour text as well. One person
  must look at the finished pages once.
- **Page weight.** 8-14 screenshots at ~200 KB is fine on a 256 MB machine; the
  static copy adds a few MB of HTML.
- **Stage 2 slipping.** The tour must be good enough alone. Stage 2 is added value.
- **Dates.** The brief says Show HN and Product Hunt come around 3 Nov, but
  `TODO.md` still lists 21 and 27 Oct. I used the brief's date. Stage 1 fits
  either way if started now.
- **A hosted tool's free plan could look fine next to this.** It is the fastest
  route, but it drops the promise on the very page where people are deciding. If
  Stage 1 slips past launch, a fallback is one free Supademo or Navattic demo on a
  separate page, clearly marked as hosted by them. That is an escape hatch, not
  the plan.

## What is left to the maintainer

- Say yes to the staged path (B2 now, C after launch).
- Read the step list and the text once (about 15 minutes); he is the judge of what a
  solopreneur wants to see first.
- Run the deploy himself (`flyctl deploy` for the site, as today); I do not deploy.
- Decide the segment names for Stage 2 (freelancer, consultant, other).
- Put `?ref=demo` on the links in the posts.

## Accounts and money

- **Stage 1: no new accounts, no new money.** It uses the existing Fly site and
  the existing deploy. Playwright is already used by `--share` and needs no sign-up.
- **Stage 2: no new accounts, no new money.** Same site, static files.
- **Not needed now:** a second Fly app (only for option A, a few dollars a month),
  and any hosted tour tool (free plan, or from about $38-50 a month if the
  watermark must go).

## Questions

None that change the recommendation. Assumptions I made, which he can correct:

1. The tour should use the released version's look, not main's.
2. The Show HN / Product Hunt date is about 3 Nov (from the brief), not the
   dates in `TODO.md`.
3. One thing I could not read: Arcade's interactive-demo plan page. It does not
   change the decision, since a hosted tool is not recommended.
