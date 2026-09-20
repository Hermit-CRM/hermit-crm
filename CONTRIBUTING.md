# Contributing to Hermit CRM

Thanks for helping. Hermit CRM is deliberately small: plain files, a thin web app,
no database and no JavaScript framework. Changes that keep it that way are the
easiest to accept.

## Dev setup

```bash
git clone <your fork> hermitcrm && cd hermitcrm
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/hermitcrm init /tmp/hermitcrm-dev --demo
.venv/bin/hermitcrm --data /tmp/hermitcrm-dev serve
```

Python 3.11 is the oldest supported version; avoid syntax newer than that.

## Tests

```bash
.venv/bin/pytest
```

The suite must pass before every commit. Tests run in `tmp_path` folders and
never touch the network or your own data. Add a test with every change; for a
change to the data format, add a numbered migration in
`src/hermitcrm/migrations.py` with before/after fixtures.

## Commit style

- One logical change per commit, imperative subject line, a short body when the
  why is not obvious.
- Commits written with an AI assistant start with `ai: `.
- Update `CHANGELOG.md` for anything a user would notice.
- **Every commit must be signed off** (`git commit -s`). See below.

## Sign your work (DCO)

Hermit CRM uses the [Developer Certificate of Origin](https://developercertificate.org/)
1.1. It is not a copyright assignment and not a CLA: it is you stating that you
wrote the patch, or otherwise have the right to send it.

Add the line by committing with `-s`:

```bash
git commit -s -m "add a thing"
```

which appends

```
Signed-off-by: Your Name <your.email@example.com>
```

using your `user.name` and `user.email`. Use a real name and a real address,
the same ones each time. Forgot it on the last commit? `git commit -s --amend`
before you push. On a branch, `git rebase --signoff main` fixes the lot.

A pull request whose commits are not signed off cannot be merged.

### What you are certifying

The full text is at <https://developercertificate.org/>. In short: the
contribution is yours to give, or it came from somewhere with a compatible
licence and you are passing it on, and you understand that the contribution and
your sign-off are public and kept forever.

### Licence of contributions

Hermit CRM is licensed under the Apache License 2.0 (see [LICENSE](LICENSE)).
Anything you contribute is under the same licence, as Apache 2.0 section 5 sets
out, unless you say otherwise in writing. You keep the copyright in your own
work; nothing here transfers it.

Do not paste in code you found unless you know its licence and it is compatible
— and say where it came from in the commit body. That includes code an AI tool
produced from a prompt naming someone else's project.

## Rules

- **No new runtime dependencies without discussion.** Open an issue first; the
  standard library usually suffices.
- Never write personal or customer data into the repo, including tests and
  fixtures: use example.com / example.org addresses and fictional names.
- File output must stay deterministic (fixed key order, byte-for-byte bodies).
- The web app binds to 127.0.0.1 only.

## Cutting a release

```bash
scripts/release.sh          # or: scripts/release.sh <commit>
```

Bump `__version__` in `src/hermitcrm/__init__.py` and move the CHANGELOG heading
first; the script reads the version from there and refuses to overwrite a tarball
that already exists, so a forgotten bump fails loudly instead of quietly shipping
0.3.0 twice.

It writes `dist/hermitcrm-<version>.tar.gz`, which unpacks to
`hermitcrm-<version>/`, and `dist/hermitcrm-<version>.tar.gz.sha256` beside it.
Put **both** on the download page: the checksum is how someone tells your file
from a corrupted or substituted one, and it costs nothing.

The archive comes from `git archive`, so it holds the tracked files at that commit
and nothing else -- no `.secrets.toml`, no stray data folder, no editor backups. The
other side of that coin is that uncommitted work is not in it; the script prints a
warning when the tree is dirty, and it means what it says.
