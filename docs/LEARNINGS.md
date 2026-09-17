# Learnings

What building Hermit CRM taught us, kept so the next change does not relearn it.
Newest first within each section.

## Product

- **One concept, one field.** An interaction had `outcome` (free text) and
  `result` (success/unsuccessful, set only from the Messages tab). Two fields
  for one idea meant two places to look and values that disagreed. Since 0.2
  there is one `outcome`, its choices come from `config.toml` (`outcomes`), and
  every page writes the same front-matter key, so nothing needs "syncing".
- **A number without its rows is a claim.** Reports counts link to the rows
  behind them (`/reports/rows?key=…`). It doubles as the test: the row lists
  must sum to the count.
- **Stage history beats a deals entity for one person.** An append-only
  `stage_history` on the company gives funnel and velocity reports without a
  second object to keep consistent. Deals become worth it only with several
  parallel opportunities per account.
- **Setup is a page you keep, not a wizard you pass.** "Setup" became
  "Settings" once it held things you come back to (review queue, calendar,
  enrichment, outcomes).
- **Help that an AI can read is the same help a person reads.** Plain Markdown
  in the package, served at `/help/<topic>` and printed by `hermitcrm help
  <topic>`; the data folder's `CLAUDE.md` points agents at it.
- **Check the name before you print it.** "OwnCRM" collided with two existing
  businesses. Check PyPI, GitHub, DNS and a web search before choosing.

## Engineering

- **Separate code from data.** When the app lived in the data folder, the
  server's `git add -A` swept code into data commits. Code is now a package,
  the data folder is a git repo of its own, and `--data DIR` joins them.
- **Clean files, leaky history.** Removing names from files does not remove
  them from git history. Going public needed a squash, `reflog expire`,
  `gc --prune=now`, then a scan of every reachable and unreachable object for
  every name, domain and email in the private data; plant a known name first
  to prove the scanner catches it.
- **Daemons have a different environment.** launchd and systemd start jobs
  with a bare `PATH`, so `shutil.which("claude")` failed and the Enrich button
  silently vanished. `enrich.find_executable` searches the usual install dirs
  and runs the CLI by full path; `schedule install` writes `PATH` into the job.
  Test the real job (`launchctl kickstart`), not a shell approximation.
- **`plutil -extract … FILE` rewrites the file unless you pass `-o -`.** Every
  plist read in `schedule.py` uses `-o -`.
- **Migrations touch front matter only.** Interaction bodies are the record
  and are never rewritten; `.hermitcrm-format` records the level, unknown keys
  round-trip through `extra`, and one migration run is one commit.
- **Derive lists from the enum.** Reports hard-coded the channels and missed
  meetings the day `Channel.MEETING` appeared. Iterate the enum.
- **Verify by comparison.** After the package split, drafts, `PIPELINE.md`
  and the report were compared byte for byte between old and new code on the
  real data. That found the channel bug above.
- **Parallel agents need file ownership and a shared contract first.** Merge
  conflicts came from two agents editing the same import line. Now the shared
  change (a config key, a method signature) is committed before the fan-out,
  each agent owns named files and route regions, and new tests go in new files.
- **Editable installs and worktrees.** `pip install -e` points at the main
  tree; in a worktree run tests with `PYTHONPATH=src` and check
  `hermitcrm.__file__` first.
- **Never put a liveness-critical step on an LLM run.** Scheduled agent runs
  get torn down mid-task; heartbeats and syncs are deterministic code.
