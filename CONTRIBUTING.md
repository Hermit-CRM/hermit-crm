# Contributing to OwnCRM

Thanks for helping. OwnCRM is deliberately small: plain files, a thin web app,
no database and no JavaScript framework. Changes that keep it that way are the
easiest to accept.

## Dev setup

```bash
git clone <your fork> owncrm && cd owncrm
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/owncrm init /tmp/owncrm-dev --demo
.venv/bin/owncrm --data /tmp/owncrm-dev serve
```

Python 3.11 is the oldest supported version; avoid syntax newer than that.

## Tests

```bash
.venv/bin/pytest
```

The suite must pass before every commit. Tests run in `tmp_path` folders and
never touch the network or your own data. Add a test with every change; for a
change to the data format, add a numbered migration in
`src/owncrm/migrations.py` with before/after fixtures.

## Commit style

- One logical change per commit, imperative subject line, a short body when the
  why is not obvious.
- Commits written with an AI assistant start with `ai: `.
- Update `CHANGELOG.md` for anything a user would notice.

## Rules

- **No new runtime dependencies without discussion.** Open an issue first; the
  standard library usually suffices.
- Never write personal or customer data into the repo, including tests and
  fixtures: use example.com / example.org addresses and fictional names.
- File output must stay deterministic (fixed key order, byte-for-byte bodies).
- The web app binds to 127.0.0.1 only.
