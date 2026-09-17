# Enrich

Two ways to fill a company's or contact's empty fields: **Fetch from URL** reads a web page (no AI); **Enrich** asks an AI CLI you already have.

Both show a proposal page first: each proposed value with a checkbox and an
editable input, plus the sources. Only ticked fields are written, in one
commit (`ai: company <slug> enriched`, `ai: contact <slug>/<contact> enriched`).
Fields that already have a value are never touched.

## Fetch from URL

On the company page. Reads the given website or LinkedIn company URL
(defaults to the company's own) with the standard library: title, meta
description, links, JSON-LD and the domain's country TLD become proposals for
website, LinkedIn, country, FTE estimate and the one-liner. LinkedIn serves
its public page to some anonymous requests and refuses others (HTTP 999); the
error says so. CLI: `hermitcrm fetch <slug> [--url URL] [--apply]`.

## Enrich

On company and contact pages when a CLI is available. Company fields: website,
LinkedIn, country, FTE estimate, AE count, one-liner. Contact fields: title,
LinkedIn. The CLI is asked for a JSON answer with sources; anything it cannot
verify comes back as "not found", never guessed. A call can take a minute and
uses that CLI's credits. CLI: `hermitcrm enrich <slug> [--contact <cslug>] [--apply]`.

## Which CLI

Set on the Settings page or in `config.toml`: `enrich_provider` is `auto`
(the first of claude, codex, gemini, grok found), one of those names, or
`custom` with `enrich_command`; `enrich_model` and `enrich_timeout` (seconds,
default 180) are optional. The binary is looked up on PATH and, because
launchd and systemd start with a bare PATH, also in `/usr/local/bin`,
`/opt/homebrew/bin`, `~/.local/bin` and the usual npm, bun, pipx and cargo
folders. The Settings page shows what was resolved; `hermitcrm doctor` reports
it too.

Related: [Settings](/help/settings), [Companies](/help/companies), [Contacts](/help/contacts), [CLI](/help/cli)
