# Hermit CRM: rules for AI sessions working on this repo (the code, not a data folder)

Layout: the package is `src/hermitcrm/` (`cli.py` entry point, `store.py` file
store, `models.py`, `web.py` + `templates/` + `static/`, `migrations.py`,
`secrets.py`, `updates.py`, `datafolder.py` for `init`). Tests are in `tests/`.
The spec is `docs/ARCHITECTURE.md`.

- Set up with `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`.
- `.venv/bin/pytest` must pass before any commit.
- Commit messages for AI-made changes start with "ai:".
- No new runtime dependencies without discussion.
- Never put real people, companies or email addresses in code, tests or docs;
  use fictional names and example.com / example.org.
- Changing front-matter keys or values means a new numbered migration in
  `migrations.py` (idempotent, front matter only) plus tests.
- Keep writes deterministic and interaction bodies byte for byte.
- Try changes against a demo folder: `.venv/bin/hermitcrm init /tmp/x --demo`.
