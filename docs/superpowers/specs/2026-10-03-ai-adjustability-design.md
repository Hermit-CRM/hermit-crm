# Make it yours: adjusting and automating Hermit CRM with your own AI agent

Status: design proposal, 2026-10-03. Nothing is built. Mockups are in
[`2026-10-03-ai-adjustability/`](2026-10-03-ai-adjustability/) (`hub.html`, `adjust-panel.html`; open them
directly, the CSS is inlined).

## 0. Decisions already taken (Gijs, 2026-10-03)

| # | Question | Decision |
|---|---|---|
| D1 | `TODO.md` lists "workflow/agent builders" as a deliberate non-goal | **Reversed.** Adjusting and automating Hermit is a goal. |
| D2 | Who builds the change | **The user's own agent** (Claude Code, Codex, Cursor, Gemini CLI, ...). Hermit does not write the change itself. |
| D3 | Rules for bulk changes and automation | **Agreed:** dry run with count and sample, one commit per run, one-click undo, `hermitcrm check` afterwards, interaction bodies are never rewritten, messages are drafts and are never sent. |
| D4 | Prominence | **Prominent**: visible everywhere, not tucked into Settings (Settings shows it too). |
| D5 | Timing | **Deploy before the public launch** (19 Oct). Otherwise timing is not a constraint for the design. |

The "code or data" question was left to this proposal (section 5.7).

## 1. The idea in one paragraph

Hermit is a folder of files, and the user already has an AI agent. **Hermit's job is to make
the possibilities visible, hand the request to that agent in one click, and make the result safe
and visible afterwards**: picked up without a restart, validated, listed, and undoable with one
click. The agent's job is to do the building, guided by recipes that ship with Hermit. That
keeps the old principle ("a folder you point your own agent at") while dropping the old
conclusion ("so we build nothing for it"). We build everything around the agent, not the agent.

```
 user ──describes──▶ Hermit (hub / Adjust tab / Settings / Help)
                        │ one click: claude-cli:// deep link, Cursor link, or copy
                        ▼
                  user's own agent ──reads──▶ `hermitcrm help adjust-*` (recipes)
                        │ writes allowlisted files, runs `hermitcrm check`, commits "ai: adjust: …"
                        ▼
                  data folder (git) ──▶ Hermit picks it up (no restart), shows it under
                                        "What you've built" / "Recent changes" with Undo
```

---

## 2. Inventory: what exists today (step 1)

Read from `origin/main` c6d2504. "Bucket": **a** = possible today through a file, the CLI or MCP,
but nobody would find it; **b** = possible with a small new declarative file the app reads;
**c** = needs code in Hermit.

| Wished-for capability | Possible today? | How | Discoverable? | Gap | Bucket |
|---|---|---|---|---|---|
| Add / remove fields | Yes, for your own fields on companies, contacts and interactions (text, number, date, select) | `fields.toml`; Settings > Your CRM > Fields | Settings only | none | a |
| Hide built-in fields | No | (templates are fixed) | n/a | `layout.toml` | b |
| Change the data structure | Partly: fields yes; new record types (deals, projects, partners) no | `fields.toml` | Settings only | record types need store, UI and a data format change | a / **c** |
| Change page layout | Only where your own fields appear (`show_in`: detail, board, companies, contacts, messages) | `fields.toml` | Settings field form | section order and visibility, list columns | b |
| Dashboards from a prompt | No. Reports has fixed sections (activity, funnel, outcomes, messages) with drill-down rows; list filters are `f_<key>` URL params, so a bookmark is the only saved view | `reports.py`, `filters.py` | n/a | `dashboards/*.toml` | b |
| Mass changes | Only by an agent hand-editing files or writing a script. `hermitcrm add` creates records; nothing updates in bulk and nothing does a dry run | (none) | no | `hermitcrm set` with dry run, `hermitcrm undo` | b (CLI) |
| Automate messaging | Templates and playbook yes (`messages.toml`, `MESSAGING.md`, per-contact language); the To file queue exists; nothing drafts on a schedule | `messaging.py` | Messages, Settings | routines | a / b |
| Routines | No; a design exists (memory `hermitcrm-routines-proposal`, approach C) | (none) | n/a | `routines.toml` and engine | b |
| Integrations | MCP server (10 tools: 7 read incl. `brief`, 3 `add_*`), CLI, CSV/TSV/xlsx importer with preview, BCC and calendar sync, bookmarklet | `mcp.py`, `cli.py`, `importer.py` | Settings > Advanced, Help | scheduled scripts; MCP write tools | a now, b later |
| Look | Yes: `theme.css` overrides tokens; meant to be written by the user's AI tool | `usertheme.py` | Settings > Appearance, Help | none | a |
| New features | No | n/a | n/a | n/a | **c** |

**Gaps that the agent-builds model hits immediately** (found while reading the code):

- **G1, no pickup without a restart.** `POST /reload` re-reads records and `fields.toml` only
  (`web.py`, `reload_index`). `config.toml` is re-read only after a Settings save
  (`config_saved()`), and `messages.toml` is loaded once at startup (`web.py`,
  `messaging.load_messages(root)`). An agent that edits task types, outcomes or templates sees
  nothing change until the app restarts.
- **G2, Ask is read-only by design.** `ask.py` gives the AI read-only tools only
  (`CRM_TOOLS`) and nothing hands work to an agent.
- **G3, no history or undo in the UI.** Git has every change; the app shows none of it.
- **G4, the agent rules teach reading and creating, not adjusting.** The data folder's
  `CLAUDE.md`/`AGENTS.md` (`datafolder.AGENT_RULES`) cover reading cheaply and `hermitcrm add`;
  they say nothing about fields, theme, layouts or automation.

**How the author actually uses it (last 30 days, a real data folder):**
- a few hundred companies, almost all prospects, imported from a list;
- a few dozen interactions, mostly LinkedIn outbound;
- four scoring fields of their own (a score, a fit score, a headcount estimate, a count of sales people);
- a few dozen messages sent with a low success rate, and about ten still at outcome "unknown".

The most useful cases are ranking and working that prospect list, bulk tagging or scoring it,
and nudging quiet LinkedIn threads.

---

## 3. How others do it (step 2)

| Product | Entry point | How a first try is seeded | Safety | Take / leave |
|---|---|---|---|---|
| **Attio** ([AI](https://attio.com/platform/ai), [Workflows](https://attio.com/blog/orchestrate-revenue-agents)) | "Ask Attio" from the workspace home; you describe the goal and blocks appear on a canvas (2026: Ask Attio Feb, Actions Apr, agent Workflows Jun) | templates, example prompt | run history ("what each agent read, decided, did"); agents scoped to user permissions; editable blocks | **Take:** describe it, watch it assemble, edit the result. **Leave:** canvas builder, credits. |
| **Twenty** (open-source CRM) | custom objects and fields in the UI; MCP server; `npx create-twenty-app` SDK; "AI skills" | none found | none found | Closest open-source rival, already marketed as "built for AI". **Take:** positioning pressure; our answer is "no SDK, your agent edits files". **Leave:** TypeScript apps framework. |
| **Airtable Omni** ([app building](https://www.airtable.com/platform/app-building)) | on the home screen ("Build an app with Omni") and inside each base | one prompt builds tables, interfaces, automations | credit meter | **Take:** the entry point is on the first screen, not in settings. |
| **Notion Custom Agents** ([intro](https://www.notion.com/blog/introducing-custom-agents)) | Library > Agents directory; "Agent Hall of Fame" gallery | write a job description and the agent writes its own instructions; templates show the prompt, trigger and instructions and can be copied and remixed | none found | **Take:** a gallery of recipes whose prompt is visible and editable. 1M+ agents built since Feb 2026. |
| **folk** ([Follow-up Assistant](https://help.folk.app/en/articles/10304768-follow-up-assistant)) | pre-built, named assistants (Follow-up, Research, Recap) | none needed: they work on synced mail out of the box | drafts to review | **Take:** named, ready-made automations, which become our starter routines. |
| **Raycast** ([Prompt Explorer](https://ray.so/prompts)) | a public web gallery with "Add to Raycast" | browse, one-click import, placeholders | none found | **Take:** a public recipe gallery on hermitcrm.io (later). |
| **Customermates** (researched 2026-10-03) | Routines page | demo prompts of 400-650 words of tool-call engineering | auto-pause, approvals declined | **Leave:** long prompts. Our know-how lives in help topics, so prompts stay one sentence. |
| **Agent deep links** | [`claude-cli://open?cwd=…&q=…`](https://code.claude.com/docs/en/deep-links): opens a terminal in that folder with the prompt typed in and **never runs it** (shows "Prompt from an external link"). [`cursor://anysphere.cursor-deeplink/prompt?text=…`](https://cursor.com/docs/reference/deeplinks) (≤8,000 chars, opens in the current Cursor window). `codex://new?…` exists but is thinly documented | n/a | the user presses Enter | **Take:** one-click handoff. **Constraint:** `q` is documented to 5,000 chars, but on macOS a launch over ~1,024 bytes fails silently ([#81485](https://github.com/anthropics/claude-code/issues/81485), open). That leaves about 500 bytes of prompt. Claude Code's docs suggest naming a skill in `q` instead. |

**The pattern across all of them:** (1) the entry point sits on the first screen, never only in
settings; (2) starting points are templates whose prompt is visible and editable; (3) a history
of what ran or changed; (4) a few named, ready-made automations. None of them lets you see a diff
and undo one change with one click; Hermit gets that for free from git.

---

## 4. Use cases, ranked (step 3)

Ranked for someone selling alone. "Wow" is how much a first try impresses (1-5). Effort is for
Hermit's side, in PRs (S/M/L). ★ marks what Gijs would use this month.

| # | Job | Starter prompt (placeholders editable) | Changes | Bucket | Risk | Effort | Wow |
|---|---|---|---|---|---|---|---|
| 1 ★ | See what to work on | "Make a dashboard called [Monday review] with: prospects with [fit] above [70] that I have not contacted yet, the replies I owe, and the deals by stage with their value. Pin it to the sidebar." | `dashboards/monday-review.toml` | b | low | M | 5 |
| 2 | Make it look like mine | "Make Hermit [cooler and more compact]: a [blue] accent and tighter table rows." | `theme.css` | a | none | S | 4 |
| 3 | Track something new | "Add a [date] field [contract renewal] to [companies], shown on the company page and in the companies list." | `fields.toml` | a | low | S | 3 |
| 4 ★ | Clean up or score in bulk | "Tag every prospect in [Germany] with more than [50] FTE as [priority]. Show me the dry run first." | company files, one commit | b | **high** → dry run | M | 4 |
| 5 ★ | Never let a thread go quiet | "Every [morning], for people I messaged on [LinkedIn] [7] days ago without a reply, draft a short follow-up into To file. Never send anything." | `routines.toml`; drafts in To file | b | medium (drafts only) | L | 5 |
| 6 | Rearrange a page | "On company pages, show the [timeline] first and hide the [Merge] section. Hide the [value per month] field everywhere." | `layout.toml` | b | low | M | 3 |
| 7 | Templates in my voice | "Write a [LinkedIn connection note] template for [finance leads at payment companies], in [English, Dutch and German]. Use my playbook." | `messages.toml` | a | low | S | 3 |
| 8 | Bring data in | "Import [~/Downloads/leads.csv] (an export from [my outreach tool]). Match existing companies by website; show me what would be created first." | new records, one commit | a | medium → preview | S | 3 |
| (c) | Something Hermit can't do | "I want [a quote generator]." The agent first checks whether a field, layout, dashboard or routine covers it; if not, it writes the feature request, or builds it in a fork for a developer. | nothing in the data folder | c | none | S | 2 |

**Best first try:** #2 (look) or #1 (dashboard): visible at once and zero risk. The hub and the
welcome step lead with these two. The other families are covered: one-off shape changes (#3, #6),
views (#1), bulk (#4), recurring (#5), messaging (#7), connect (#8).

**What stays honest:** new record types ("a separate Deals list") are bucket c. The recipe for
"change the structure" answers with fields plus a dashboard (for example, partners as companies
with `type = partner` and a pinned "Partners" dashboard) and says so plainly.

---

## 5. Placement and UX (step 4)

**Recommendation: all five entry points, one vocabulary.** The place is called **Make it yours**;
the action is **Adjust**.

| Entry | What | Mockup |
|---|---|---|
| **A. Sidebar hub** | A **Yours** group just above Settings: *Make it yours* (bold, accent icon), then any dashboards the user pinned, then a rule before Settings. As people pin dashboards, the sidebar itself becomes theirs, which is the strongest "it's mine" signal there is. | `hub.html` |
| **B. Every page** | The existing *Ask the Hermit* button becomes **Ask · Adjust**: one button, one panel, two tabs. The Adjust tab shows 3-4 starters that fit the page type, a request box, **Open in Claude Code** (or the configured agent) and **Copy prompt**. The page path goes along. The last-used tab is remembered. | `adjust-panel.html` |
| **C. Settings** | General tab: a first card "Make it yours with your AI" linking to the hub. Your CRM tab: each section (Fields, Messaging, Task types, Outcomes) gets an "or describe it" link that opens Adjust with a matching starter. | (none) |
| **D. Help** | A *Make it yours* topic near the top of the index, plus the recipe topics. These are **the same text the agent reads**, so docs and behaviour never drift apart. | (none) |
| **E. Nudges** | A welcome-walkthrough step "Make it yours" ("change one thing: try the look"). The sample account ships a pinned demo dashboard and a paused routine, so the hub is never empty. "Suggested for you" on the hub (below). Empty states, e.g. the bottom of Reports: "Want a different view? Describe it." | in `hub.html` |

**Why merge Ask and Adjust instead of adding a second button:** the button is already on every
page, already top right and already in the accent colour, so prominence costs no new chrome.
"Ask" (read) and "Adjust" (change) are the two things you want from AI about a page. Two buttons
would compete and add noise; Settings was just cut by about 50% for having too much.

**The hub page (mockup `hub.html`), top to bottom:**
1. A one-line promise, plus which agent links open ("Your agent: Claude Code, opens in `~/crm`", Change).
2. **Describe a change**: a free text box with Open in agent / Copy.
3. **Start from an idea**: recipe cards with family chips (Dashboards, Fields, Pages, Bulk changes,
   Routines, Messages, Look, Connect). Each card shows its prompt with editable `[placeholders]`,
   the file it changes, and a safety badge ("undo in one click", "dry run first", "starts paused").
4. **Suggested for you**: at most three, worked out from the data with plain rules, no AI (section 7).
5. **What you've built**: dashboards, routines (state, Preview, Turn on), your fields, your look;
   each with an *Adjust* link that pre-fills a starter.
6. **Recent changes**: commits that touched an extension file, plus `bulk:` commits, each with
   **Undo** (a new revert commit; history is never rewritten).
7. **Something Hermit can't do yet?**: the bucket-c path.

**Name candidates:** *Make it yours* (recommended: Gijs's own words, an invitation, and it covers
both shaping and automating); *Adjust* (good verb, cold as a place); *Customize* (sounds like
Settings); *Workshop* / *Studio* (vague); *Automate* (too narrow).

---

## 6. Engine and extension surface (step 5)

### 6.1 Handoff: how a request reaches the user's agent

Hermit already knows the user's AI CLI (`enrich_command`, used by Enrich and Ask). The handoff
follows it:

| Configured agent | Primary button | Always also |
|---|---|---|
| Claude Code | **Open in Claude Code**: `claude-cli://open?cwd=<data folder>&q=<request>` | Copy prompt |
| Cursor | **Open in Cursor**: `cursor://anysphere.cursor-deeplink/prompt?text=<request>` (the data folder must be open in Cursor) | Copy prompt |
| Codex | **Copy command**: `cd <data folder> && codex "<request>"` | Copy prompt |
| Gemini CLI | **Copy command**: `cd <data folder> && gemini -i "<request>"` | Copy prompt |
| MCP-only (Claude Desktop, ChatGPT) | Copy prompt (works once the MCP write tools exist, 6.8) | (none) |

**The prompt stays short (≤500 UTF-8 bytes in the link).** For Claude Code it is
`/hermit Asked on <page title> (<path>): <request>`, where `/hermit` is a skill in the data folder
(6.2). For other agents it is `Run "hermitcrm help adjust" first and follow it. Asked on … : <request>`.
If a request is over the limit, the Open button turns into Copy, with one line saying why
(the macOS deep-link bug above).

**First click:** Claude Code registers its `claude-cli://` handler the first time you send a
prompt in an interactive session. Under the button: "Nothing opened? Run `claude` once in a
terminal and try again", with Copy always there as the fallback.

### 6.2 Agent know-how: recipes that ship with Hermit

- **Recipes are help topics in the package**, so they always match the installed version:
  `adjust` (the rules plus which recipe to use), `adjust-fields`, `adjust-layout`,
  `adjust-dashboards`, `adjust-bulk`, `adjust-routines`, `adjust-messages`, `adjust-look`,
  `adjust-connect`, `adjust-feature`. Each states which files it may write, gives an example,
  says how to validate it, and gives the commit message.
- **The data folder gets a thin Claude Code skill** at `.claude/skills/hermit/SKILL.md`. Its
  content is only: name, description, "run `hermitcrm help adjust` and follow it". That keeps the
  deep link tiny, and the skill never goes stale, because the substance lives in the package.
- **`CLAUDE.md` and `AGENTS.md` get an "Adjusting Hermit" paragraph**: it points at
  `hermitcrm help adjust`, lists the allowed files and the rules in 6.3.
- **Existing data folders** get these through **data format 8**, a migration that touches agent
  files only. This is the house convention: format 6 did the same for the backup rules. No
  record changes, one revertible commit.

### 6.3 Rules every recipe enforces (D3)

1. **Writable without asking:** `fields.toml`, `layout.toml`, `dashboards/*.toml`, `routines.toml`,
   `theme.css`, `messages.toml`, `MESSAGING.md`, and the `task_types`/`outcomes`/`silent_days`
   keys of `config.toml`.
2. **Records only through the CLI:** `hermitcrm add` creates them; `hermitcrm set` changes them,
   always with a dry run first.
3. **Never:** interaction bodies, `.hermitcrm-format`, `PIPELINE.md`, `.secrets.toml`,
   `.claude/settings.json`, git history, or sending anything.
4. **After every change:** run `hermitcrm check`, fix what it reports, then make one commit per
   change, `ai: adjust: <what>` or `ai: bulk: <what>`.
5. **Enforcement:** the rules are written down for every agent. Claude Code's deny rules
   (`guard.py`) are the seat belt. The backup makes any mistake survivable.

### 6.4 New declarative files (all optional; absent = today's behaviour)

**`dashboards/<slug>.toml`**: one file per dashboard. Widgets reuse the `filters.py` syntax and
`reports.py` sections, so an agent writes nothing new to learn:

```toml
title = "Monday review"
pin = true                                    # show it in the sidebar's Yours group

[[widget]]
type = "list"                                 # list | count | group | report
title = "High-fit prospects, never contacted"
scope = "companies"                           # companies | contacts | messages | tasks
filters = { stage = "prospect", fit_score = ">70", last_touch = "-" }
columns = ["name", "fit_score", "country", "next_step"]
sort = "-fit_score"
limit = 20

[[widget]]
type = "report"
section = "funnel"                            # any reports.py section
period = "30d"

[[widget]]
type = "group"                                # count per value, drawn as bars
scope = "companies"
by = "stage"
```

The page lives at `/d/<slug>`. Every row and number links to its records, the way Reports does today.

**`layout.toml`**: section order and visibility, hidden built-in fields, and list columns:

```toml
[company]
sections = ["timeline", "details", "contacts"]   # order; omitted sections are hidden
hide_fields = ["value_eur_month", "requalify_on"]

[companies]                                      # the list page
columns = ["name", "stage", "fit_score", "country", "next_step"]
```

**`routines.toml`**: as in the routines proposal (approach C). Python selects the records
(filter syntax), and the AI only drafts JSON for one record at a time, with no write tools.
Output goes to To file and is never sent. Each pass is one commit, it runs after the 07:00 sync,
and new routines start paused with Preview. Starter routines: *Morning brief* (no AI), *Nudge
quiet threads*, *Reply drafts*. Running them in plain code after the sync, not as an agent run,
follows the lesson that liveness never belongs on an LLM run.

### 6.5 App side: making the agent's work visible and safe

- **Pickup without a restart (fixes G1):** before each request, stat the extension files
  (`config.toml`, `messages.toml`, `fields.toml`, `layout.toml`, `dashboards/`, `routines.toml`)
  and re-load whatever changed. *Reload* re-reads all of them too.
- **Validation:** `hermitcrm check` and `doctor` validate every extension file with line-level
  messages, e.g. "dashboards/monday.toml: widget 2: unknown column fitscore (did you mean
  fit_score?)". The hub shows the same message as a banner, so the user can paste it back to
  the agent.
- **History and undo (fixes G3):** `hermitcrm undo <sha>` runs `git revert --no-edit` (a new
  commit; allowed under the backup rules), and the hub's Recent changes calls it. A revert that
  conflicts says so and offers "Ask your agent to undo this" (a prefilled prompt).
- **Rendering:** dashboards at `/d/<slug>`; `layout.toml` applied in the company, contact, Home
  and list templates; pinned dashboards in the sidebar.

### 6.6 `hermitcrm set`: bulk changes with a dry run (D3)

```
hermitcrm set companies --where stage=prospect --where country=DE --where fte_estimate=">50" \
    --add-tag priority                 # dry run by default: count, 5 samples, before → after
hermitcrm set companies ... --add-tag priority --apply
# → "23 companies changed in one commit a1b2c3d. Undo: hermitcrm undo a1b2c3d"
```

- Operations: `--set field=value`, `--add-tag`, `--remove-tag`, `--stage`.
- Filters use the `filters.py` syntax.
- It refuses interaction bodies and runs `check` before committing.
- Scopes are companies and contacts; interactions get front-matter fields only, never bodies.

### 6.7 Code or data (my call): what Hermit deliberately does not do

| Not doing | Why |
|---|---|
| Template overrides from the data folder | They break silently on upgrade; a Jinja template is code with access to everything; and every user ends up on an unsupportable variant. `layout.toml` covers the common wishes. |
| Python plugins in the data folder | A cloned or shared data folder would run code, and upgrades would break plugins. Revisit after launch if people really hit the wall. |
| An in-app AI that writes (option i) | D2. It would also need write tools on four CLIs, and only Claude Code's tool use is verified. |
| Sending messages automatically | D3. Drafts only. "Send from the app" stays a separate roadmap question. |
| New record types | Store, UI and data format work far beyond the rest. Fields plus dashboards cover most of it; the recipe says so honestly. |
| Running scripts from the web UI | The app has no authentication on 127.0.0.1. Scripts run in the agent or a terminal. |

**Bucket c, honestly:** the `adjust-feature` recipe makes the agent (1) check whether a field,
layout, dashboard or routine already does it (usually yes), (2) otherwise write a
feature request the user can paste into GitHub, or (3) for a developer, build it in their own
clone of the Apache-2.0 repo and open a PR (DCO sign-off, per `CONTRIBUTING.md`).

### 6.8 Later, not part of the launch set

- **MCP write tools** for Claude Desktop and ChatGPT, which have no shell: `adjust_file`
  (allowlisted paths, validated, one commit), `bulk_preview`/`bulk_apply`, `undo`.
- **Scheduled scripts for integrations**, with a one-time local approval kept outside git (like
  `direnv allow`), so a cloned folder never runs code by itself.
- **A public recipe gallery** on hermitcrm.io (Raycast-style) with copy and deep-link buttons.
  GitHub strips `claude-cli://` links, so the website is the place for them.

---

## 7. Making it their own (step 6)

1. **Starter prompts: yes, as editable recipes, not a prompt library.** Placeholders are inline
   fields, pre-filled from the user's own data wherever possible:
   - their real field names (`fit`, not "score");
   - their most common country;
   - their most used channel.

   A starter that already speaks your data is the strongest hook. No persona packs in v1:
   with one user, the data is the persona.
2. **Show before you ask.** The sample account ships a pinned "Monday review" dashboard and a
   paused "Nudge quiet threads" routine. A new user sees a customised Hermit before writing a
   prompt, and removing the sample removes them too.
3. **Suggested for you** (at most three, plain rules, no AI, no cost):
   - a score field exists but no dashboard ranks by it;
   - many messages still have outcome `unknown`;
   - a built-in field is used on 0 records ("hide it?");
   - front-matter keys without a field definition ("describe them as fields?");
   - no dashboards yet.

   Each one opens the matching recipe.
4. **Ownership made visible.** Pinned dashboards in the sidebar's **Yours** group; "What you've
   built"; "Recent changes" as the CRM's own changelog, with undo.
5. **The first five minutes.** The welcome step "Make it yours" leads with the zero-risk wins
   (look, dashboard). The Adjust tab is one click from every page.
6. **Sharing (after launch).** A recipe is just a prompt, so sharing is copy/paste: a "Recipes"
   category in GitHub Discussions, and later the gallery on hermitcrm.io.
7. **Launch story.** The website benefit "Built for your AI" becomes **"Make it yours, with your
   own AI"**, with three before/after clips: a dashboard from one sentence, a new field, a
   routine that drafts follow-ups. A possible Show HN line: *"Hermit CRM: a CRM your coding agent
   can reshape. It's a folder of Markdown files; your agent is the admin."*

---

## 8. Build list (to deploy before 19 Oct)

Each PR stands alone and is tested by Gijs in the app (about 2 minutes) before merge. The list is
ordered so a slip at the end blocks nothing before it.

| PR | Contents | Size | Changes what's live / data / public? | What Gijs clicks |
|---|---|---|---|---|
| 1 | Handoff (deep links, copy, 500-byte guard); **Ask · Adjust** panel with page-aware starters; **Make it yours** hub (describe, recipe cards, built, recent changes with Undo); `hermitcrm undo`; recipes as help topics; the Settings, Welcome and Help entry points; pickup without a restart (G1) | L | live UI; no data | Adjust on a company page, *Open in Claude Code*, ask for a field, see it appear, Undo it on the hub |
| 2 | Data format 8: the `/hermit` skill and the "Adjusting Hermit" paragraph in `CLAUDE.md`/`AGENTS.md` | S | **data** (agent files, one revertible commit) | `migrate --dry-run`, then the same flow as PR 1 |
| 3 | `dashboards/*.toml`, `/d/<slug>`, pinning, `check` validation | M | live UI; optional new files | ask for "Monday review", see it pinned in the sidebar |
| 4 | `hermitcrm set` (dry run, apply, check, one commit) | M | CLI; data only on `--apply` | ask the agent to tag prospects, read the dry run, apply, Undo |
| 5 | `layout.toml` (sections, hidden fields, list columns) | M | live UI | "timeline first on company pages" |
| 6 | Routines v1 per the routines proposal (engine without AI, then AI drafts) | L | live; drafts into To file | Preview, turn on, see drafts after the sync |
| 7 | Sample account items, welcome step, website section, launch copy | S | **public** (website) | open /welcome, open hermitcrm.io |

`TODO.md`'s non-goal line changes with this spec (D1).

---

## 9. Open decisions (recommended option first)

1. **Name:** *Make it yours* / *Adjust* / *Customize*.
2. **Per-page control:** merge into **Ask · Adjust** / a separate *Adjust* button.
3. **Routines before launch:** yes, as the last PR (6), so it can slip alone / move to after launch.
4. **Dashboard format:** TOML widgets reusing `filters.py` / Markdown with query blocks (nicer
   prose, but a new mini-language).
5. **New record types:** out of scope, answered with fields plus dashboards / design custom objects now.
6. **Agent files for existing folders:** data format 8 (house convention) / write them at startup
   without a format bump.
7. **Website:** rewrite "Built for your AI" as "Make it yours, with your own AI" and add before/after
   clips / leave it as is.
8. **MCP write tools (Claude Desktop, ChatGPT):** after launch / in the launch set.
