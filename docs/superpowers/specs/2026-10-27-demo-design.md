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

## Gijs's idea: use the existing onboarding flow

Added the same day, after Gijs asked whether the onboarding could carry the demo.
"Onboarding" is two different things in the app, and they behave differently:

- **"Show me around"** (`/?tour=1`, `static/tour.js`, 129 lines). A bubble that points
  at each part of the real screen, 15 stops: Home, Pipeline, Calendar, Tasks,
  Companies, Contacts, Messages, Outreach, Learning, Extension, Reports, Search,
  Ask, Make it yours, Settings. It runs in the visitor's browser only, has no
  dependencies and needs no server. It anchors to `data-tour` marks on the page and
  skips a stop whose anchor is gone, so it keeps up with the app by itself.
  **This is a ready-made guided overlay. It fits option C almost exactly.**
- **"Getting started"** (`/welcome`, 13 steps). A checklist of jobs: say who you are,
  add a company, log what happened, move a deal, draft a message. Each step ticks
  itself by looking at your own data. It is not a demonstration: it needs a live
  app and a real folder to do anything, so it cannot be frozen into a tour.
  (A "Load a sample account" button already exists: one made-up company, Northwind
  Robotics, with people, messages, a deal, tasks, a dashboard and a routine.)

What this changes:

1. **Screenshots from the tour are a good source.** Its 15 stops are the app's own
   list of what matters, kept current by the app. The step list for the website
   tour (Stage 1) should come from it, not from my list above. Taking one
   screenshot per stop of a demo folder is simple.
2. **C gets cheaper.** In a read-only trial I ran (nothing changed in the repo), the
   app's own test client opened 80 pages of a fresh demo folder in-process, all
   without errors (only `/` redirects, to the welcome page on a new folder). The
   pages carry the 18 tour marks. So the crawl works, and `tour.js`
   can be saved with the pages and start with `?tour=1`: the real app, clickable,
   with the app's own guide on top and no server. I have not built it; links,
   forms and the header rules still need the work described under Stage 2.
3. **The 13-step checklist stays out of the demo.** It is about your own data, so in
   a frozen copy it would only show ticks that cannot happen.
4. **Limits of the overlay as it is:** the stops are one short sentence each and only
   point at the sidebar. A demo for HN wants a bit more story per stop (what a
   freelancer does here), so Stage 2 adds text; it does not replace the overlay.

Net effect on the scores: C improves (build effort 3 to 4, time to first version 3 to
4, total 32 to 34). B2 stays ahead by one point because it needs nothing from the
app and can ship on day 1 from screenshots that already exist.

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
| **1. Effort to build** | **2**. Read-only mode must be built across 100+ routes, plus reset, plus a second Fly app: ~4 sessions | **1**. A1 plus sandboxing and cleanup per visitor: ~6+ sessions | **5**. A few hours of recording by Gijs | **4**. ~2 sessions; the first page can reuse the 14 existing screenshots in one | **4**. ~3 sessions, and the guide overlay (`tour.js`) already exists: crawl the page types, fix links, switch buttons off |
| **2. Effort to maintain** (regenerates from code?) | **3**. Always the current code, but every new risky feature needs a new switch | **3**. Same as A1, more to watch | **2**. Re-record by hand after UI changes; ~190 commits in 8 days will date it fast | **4**. One command retakes every screenshot; the step text still needs a human when a screen changes | **5**. Whole demo is rebuilt from code on every build; a broken link fails the build |
| **3. Potential to grow** | **4**. Real clicking; canned "Ask" answers must be faked | **5**. Anything the app does | **3**. Guided steps and branching are built in; try-your-own-CSV and canned answers are not possible | **4**. Segments (freelancer, consultant) are just other step lists; own-CSV not possible | **4**. Segments = different demo folders; canned "Ask" answers are easy to put in; own-CSV not possible (a later, browser-side idea at best) |
| **4. Security and abuse risk** | **1**. Public server that can mail, read mail, run AI programs, hold keys, commit to git (list below) | **1**. Same list, times many visitors; people will try it | **5**. Nothing of ours is exposed | **5**. Images and links only | **4**. No server; the one risk is putting real data in the demo folder, and the app's own scripts run on our domain, so the demo section needs its own header rules |
| **5. Running cost on Fly** | **4**. Small machine that sleeps when idle: a few dollars a month (Fly prices not rechecked today) | **2**. A machine or a volume per visitor; one spike from HN costs real money | **5**. $0 on a free plan, $38-50/month if the watermark must go | **5**. Static files in the image we already pay for | **5**. Same |
| **6. Fit with the product promise** | **2**. A cloud copy of a product that says "no cloud"; first party, but a server | **1**. Same, and visitor-entered data sits on our server | **1**. Third-party script or frame, the vendor's cookies and analytics, and the site's header would have to be loosened. Directly breaks "no widget scripts" | **5**. The site stays what it says it is | **4**. First-party, no server, but real app code runs on the site |
| **7. Measurability** (`?ref=demo`, no app telemetry) | **4**. Arrival and pages are in the existing log; a click inside the app is not counted unless we log it, which we should not | **3**. Same, more noise | **2**. Their dashboard has the numbers, not ours; our log sees only the arrival | **4**. Each step is its own page, so our log shows how far people got (below) | **4**. Same, each page is a log line |
| **8. Time to first usable version** | **1**. Weeks of careful work | **1**. Weeks | **5**. 1 day, but only a free-plan demo | **4**. A first version in 1 day, a good one in ~3 | **4**. ~3-4 days |
| **Total (of 40)** | **21** | **17** | **27** | **35** | **34** |

Why B1 scores 27 and not lower: it is the fastest and the safest. It loses on the
promise, on staying up to date, and on measurement, and those are the three that
matter most for this product.

## Gijs's goal, stated later: show the breadth, not a demo

Added the same day. Gijs said: no video, no need to teach CRM basics. The goal is to
show on hermitcrm.io that the tool is **feature rich**, as a **high-level overview of
what it contains**. That is a smaller job than "a demo", and it changes the plan.

**What the site already has.** `/features/` is an overview of 11 pages (Home, Pipeline,
Calendar, Tasks, Companies, Contacts, Messages, Extension, Reports, Make it yours,
Settings), each with real screenshots from a demo folder, and the home page has a
"What you get" list. So a visitor can already see the basics.

**What is missing, and it is the part that makes the tool look rich.** As far as I can
see from `website/features/` and `content.toml`, these have no screenshot or page of
their own: the **Outreach bot** (researched, checked first messages for you to
approve), **Learning** (lessons from your edits and replies), **Ask the Hermit**
(questions in plain words), **Adjust** (change the tool by describing it), the
**Inbox** and mail capture, the **CLI and MCP server** (your AI agent works in the
same data), and **plain files in git** with backups and one-click upgrade. These are
what separates Hermit from "a CRM in a spreadsheet", and today they are mentioned in
text only.

**What a visitor needs for this goal:** one page they can scan in a minute. A grid of
labelled screenshots grouped by area, one plain line each, each linking to the longer
page. Nothing to click through, nothing to wait for.

**Consequence for the recommendation.** A guided tour with steps (B2 as I wrote it) is
more than this needs, and the static copy of the real app (C) is much more than this
needs. Neither is wrong, but neither is the cheapest way to the goal. See the updated
Recommendation, which replaces the staging described further down. The scored
matrix is still correct as a comparison of the options. For this smaller goal, the
overview page is the B2 idea cut down to one page with no steps.

## Recommendation

**Updated after Gijs's goal above. Build one overview page, `hermitcrm.io/tour/`
(name to be chosen), made of real screenshots grouped by area, covering everything the
tool contains, including the parts that have no page today. Ship it before Show HN.
Do not build a hosted live demo (A) or use a hosted tool (B1). The guided steps (the
original Stage 1) and the frozen real app (C, Stage 2) become optional later work,
only if people ask for more.**

Concretely: about 1 session to build the page from the screenshots that exist, plus
about 1 session for the 5-7 new screenshots of what is missing (Outreach, Learning,
Ask, Adjust, Inbox, the CLI and an agent working in the folder, the files and git
log). The new screenshots come from a demo folder of the released version, as the
site's rule says. Some, like Learning and Outreach, may need demo data the demo folder
does not have yet; if so that is a small change to the demo folder, not to the site.

The reasons below were written for the tour, and they still hold for this page.

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

## Stage 1 (original plan, now optional): the guided tour (B2)

**What the visitor sees.** `hermitcrm.io/tour/` is a plain page: one real
screenshot, two or three sentences, "Back" and "Next" links, and a step list. Each
step is its own page (`/tour/pipeline/`, `/tour/company/`, ...). The last page says
"Install it" with the download and the agent install line.

**Steps for a first version.** Start from the 15 stops of the app's own "Show me
around" tour (see "Gijs's idea" above) and keep the ones a solopreneur needs first.
My own shortlist, about 8, the daily job of a solopreneur:
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

## Stage 2 (original plan, now optional): the real app, frozen (C)

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
- The app's own "Show me around" overlay (`tour.js`, started with `?tour=1`) as the guide. Extra story text per stop for the segments goes beside it.
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

- Say yes to the one-page overview (the guided tour and the frozen app are optional later).
- Read the overview page's grouping and text once (about 15 minutes); he is the judge of
  what should come first.
- Say whether the new screenshots may show the made-up demo data as it is.
- Run the deploy himself (`flyctl deploy` for the site, as today); I do not deploy.
- Put `?ref=demo` on the links in the posts.

## Accounts and money

- **The overview page, and the optional Stage 1: no new accounts, no new money.** It uses the existing Fly site and
  the existing deploy. Playwright is already used by `--share` and needs no sign-up.
- **Optional Stage 2: no new accounts, no new money.** Same site, static files.
- **Not needed now:** a second Fly app (only for option A, a few dollars a month),
  and any hosted tour tool (free plan, or from about $38-50 a month if the
  watermark must go).

## Questions

None that change the recommendation. Assumptions I made, which he can correct:

1. The overview should show the released version's look, not main's, and use `?ref=demo` links for measuring (arrivals and downloads, as in Stage 1 below).
2. The Show HN / Product Hunt date is about 3 Nov (from the brief), not the
   dates in `TODO.md`.
3. One thing I could not read: Arcade's interactive-demo plan page. It does not
   change the decision, since a hosted tool is not recommended.
