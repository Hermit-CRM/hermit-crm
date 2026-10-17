# Directories, lists and newsletters

The launch plan in `TODO.md` names the sites; this file says how and when to
use each one. Rules were checked on 15 Oct 2026; check again before you submit.
These are free listings only, with no paid fast tracks.

The repo goes public on Mon 19 Oct 2026 as a new repo with new history, so any
list that counts stars or the age of the first commit starts counting then.

## Copy to reuse

- One line (no pitch, no emoji): "A local CRM for one person: Markdown files
  in git, a web app, a CLI and an MCP server."
- Registry description (at most 100 characters): the `description` in
  `server.json`.
- Media: `docs/img/demo.gif`, `pipeline.png`, `company.png`, `calendar.png`;
  the social preview is `.github/social-preview.png`.
- Tags: crm, open-source, local-first, markdown, git, mcp, solopreneur, python.
- Alternative to: HubSpot CRM, Pipedrive, Attio, Monica, Twenty.

## A. Before 19 Oct: in the repo

- [x] `server.json` for the MCP Registry, valid against the 2025-12-11 schema.
      The name is `io.github.Hermit-CRM/hermit-crm`, with the case of the
      GitHub login, because the registry matches it exactly.
- [x] `<!-- mcp-name: io.github.Hermit-CRM/hermit-crm -->` at the top of
      README.md. The registry looks for it in the README on PyPI, so it only
      counts from the next release on. `tests/test_mcp.py` keeps the marker,
      the name and both versions in `server.json` in line with `__version__`.
      Bump them together.
- [ ] Tag the next release so the marker reaches PyPI.

## B. 19-21 Oct: public, before Show HN

- [ ] **MCP Registry.** Install `mcp-publisher` (Homebrew or the release
      binary), then `mcp-publisher login github`. It needs an Owner of the
      Hermit-CRM org, because ordinary members do not get the org namespace.
      Then `mcp-publisher validate` and `mcp-publisher publish`. Check with
      `curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=hermit"`.
      Do it again after each release, or later move it into `release.yml`.
- [ ] **Glama.** Wait for it to index the public repo or add it there, then
      claim it. You need the listing and its score badge for the next step.
- [ ] **awesome-mcp-servers (punkpeye).** One pull request with one line, in
      alphabetical order, under the category that fits best (there is no CRM
      category). Put the Glama score badge right after the repo link, because
      their CI checks for it. A PR from an agent ends its title with 🤖🤖🤖.
- [ ] **PulseMCP, mcp.so, Smithery.** Submission forms that work from the
      GitHub URL.
- [ ] **AlternativeTo.** List it as an alternative to HubSpot CRM, Pipedrive
      and Monica, with screenshots and the "Free, Open Source, Self-Hosted"
      tags.
- [ ] **OpenAlternative.** Use the free queue. It shows stars, so expect
      traffic only after Product Hunt; submit early so the queue time passes.

## C. 22 Oct - 3 Nov: around Product Hunt

- [ ] **SaaSHub.** Alternative to the same five.
- [ ] **LibHunt.** It picks up public Python repos; claim the page and set
      the description.
- [ ] **european-alternatives.eu.** The angle: made in the EU, local, no
      cloud.
- [ ] **awesome-claude-code.** From about 2 Nov (14 days after the first
      commit, with commits after it; or earlier at 100 stars). Fill in the
      web form by hand: no PR, no `gh`, a person has to do it, one resource,
      the one-line description.
- [ ] **Other awesome lists** (awesome-crm, AI-agent lists). Look at the date
      of the last merged PR first; skip lists that have gone quiet.

## D. After Show HN: newsletter pitches

One short email each, with the GIF, the repo link and one result from Show HN
(a star count, or a line from the thread). Send them once Show HN has given
you that result.

- [ ] selfh.st Weekly (self-hosted): the best fit.
- [ ] Changelog News: through its submission form.
- [ ] PyCoder's Weekly and Python Weekly: pure Python, FastAPI, an MCP server
      with no dependency.
- [ ] Hacker Newsletter: picks from HN itself, so it only matters if Show HN
      does well.
- [ ] Indie and solo-founder newsletters: "a CRM your AI agent can run".
- Skipped: Console.dev (developer tools only) and TLDR (mostly paid).

## E. February 2027 or later

- [ ] **awesome-selfhosted.** Software has to be first released more than
      4 months before (PyPI 0.5.0 was 2 Oct 2026). Their rules forbid
      entries written or submitted by AI agents, so write the YAML entry
      yourself.
