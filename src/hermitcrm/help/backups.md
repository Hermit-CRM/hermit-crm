# Backups and undo

A second copy of the folder's history, outside the folder, that can only grow; every few minutes, and any version can be put back. Claude Code is blocked from the git commands that destroy history.

Every change in Hermit CRM is already a git commit, so a bad edit is undone
from the history. What the history cannot protect is *itself*: a
`git reset --hard`, an amended or rebased commit, a deleted `.git` folder or a
force-push loses it. Anything with a shell in the folder can do that -- you, a
script, or an AI agent that meant well. The backup covers that case.

## Dangerous git commands are blocked

Every data folder has a `.claude/settings.json` that stops Claude Code from
running the commands that destroy history, in every permission mode (bypass
included). An agent that tries one gets a refusal instead of a result:

| Blocked | Why |
|---|---|
| `git reset --hard`, `git commit --amend`, `git rebase` | move `main` back or replace commits |
| `git push --force` / `-f` / `--force-with-lease` | overwrite the copy on your remote |
| `git filter-branch`, `git filter-repo` | rewrite every commit |
| `git update-ref -d`, `git reflog expire`, `git gc --prune` | delete refs, or the objects a reset left behind |
| `git clean -f` / `-fd` / `-fdx` | delete files git does not track |
| the same with `git -C <dir> ...` | `git -C` would slip past a plain prefix match |
| `rm -rf .git`, `rm -rf companies`, `rm -rf ~/.hermitcrm` | delete the history, the data or the backup |
| editing `~/.hermitcrm/**` or `.claude/settings.json` | the backup, and this list itself |

New folders get it from `hermitcrm init`; existing folders get it with the
upgrade (data format 6), merged into any settings file already there. Your
own rules in that file are kept. `hermitcrm doctor` warns when a rule is
missing and `hermitcrm backup guard` puts them back.

Two limits, stated plainly:

- **It is Claude Code only.** Codex, Gemini and other agents have no such file;
  they get the same rules as text in `AGENTS.md`.
- **It matches command patterns; it is a seat belt, not a lock.** A script,
  `bash -c "..."` or a command spelled differently still gets through. That is
  what the backup below is for: whatever gets through, the versions it
  destroyed are still in the backup.

You are not blocked: these rules apply to Claude Code, not to your own
terminal. To let an agent run one of them anyway, remove that line from the
file for the moment (`doctor` will remind you to put it back).

## What it is

A bare git repository at `~/.hermitcrm/backups/<folder>-<hash>.git` (or
`backup_dir` in `config.toml`; it has to be outside the data folder). It is
set up so that nothing in it is ever lost:

- a push can add commits and refs, but never move a ref backwards or delete one
  (`receive.denyNonFastForwards`, `receive.denyDeletes`);
- old versions are never cleaned up (reflogs and unreachable objects never expire);
- Hermit CRM puts those settings back on every run, should anything change them.

## What each run does

To start it, click **Start local backups** in Settings, Backup, or run
`hermitcrm schedule install`.

`hermitcrm backup` (the scheduled job runs it every 5 minutes):

1. **Uncommitted edits.** If a file differs from the last commit -- a hand edit,
   an agent that forgot to commit -- that state is saved as
   `refs/snapshots/<time>`. Your folder is not touched: no commit, no staging,
   your branch stays where it is. The same state is saved once, not every run.
2. **The branch.** New commits are added to the backup's `main`.
3. **Rewritten history.** If `main` in the folder no longer contains what the
   backup has (a reset, an amend, a rebase), the backup keeps its old `main`
   as it was and stores the new line as `refs/rewritten/<time>/main`. The run
   warns once (exit 1, a `WARNING:` line in the log, a warning in
   `hermitcrm doctor`); later runs follow the new line.
4. **Your git remote.** If you set one up under Settings, Backup, commits it
   does not have yet are pushed there too, never forced. A failing push is a
   warning; the local backup has already happened.

Files in `.gitignore` are never backed up, so `.secrets.toml` stays on this
machine only.

## Size

Git stores each version of a file once and compresses the differences between
versions. A run that finds nothing new writes nothing: an idle folder costs
nothing, however often the job runs. The backup grows with your real edits,
typically a few MB for years of a CRM. `hermitcrm backup status` prints its
size.

## Turning it on

```bash
hermitcrm schedule install              # daily sync + backup every 5 minutes
hermitcrm schedule install --backup-every 1
hermitcrm schedule install --no-backup  # sync only
hermitcrm backup status                 # where, how big, last run
hermitcrm doctor                        # includes a backup line
```

On macOS the job is `io.hermitcrm.backup` (log `~/Library/Logs/hermitcrm-backup.log`,
one line per run that did something); on Linux the `hermitcrm-backup.timer`
user unit; on Windows a `schtasks` line to run yourself.

## Finding a version

```bash
hermitcrm backup list                       # the last 20 versions, all lines
hermitcrm backup list companies/acme        # only those that touched Acme
hermitcrm backup list MESSAGING.md -n 50
```

Each line is `<id>  <date>  <message>`, with the ref names next to the ones
that are the tip of a line (`main`, `snapshots/...`, `rewritten/...`).
`list` runs a backup first, so what happened since the last scheduled run --
usually the very thing you are looking into -- is in the list and saved.

## Rolling back

```bash
hermitcrm backup restore <id> companies/acme            # dry run: what would change
hermitcrm backup restore <id> companies/acme --apply    # one company
hermitcrm backup restore <id> companies/acme companies/globex --apply
hermitcrm backup restore <id> --apply                   # the whole folder
hermitcrm backup restore snapshots/20260918-140500Z MESSAGING.md --apply
```

- `<id>` is any id from `backup list`, a ref name printed there, or anything
  git understands (`HEAD~3`). A version that only the backup still has (it was
  reset away in the folder) is fetched from the backup.
- Without `--apply` nothing changes; it prints which files would change.
- With `--apply` it first runs a backup, so the state being replaced is saved
  too; then it puts the files back, removes files that did not exist in that
  version (within the paths given), commits
  `backup: restore <paths> to <id> (<date>)` and rebuilds the index and
  `PIPELINE.md`.
- A restore is a new commit on top. Nothing is taken out of the history, so a
  restore is undone the same way.

## When the folder itself is gone

If `.git`, or the whole folder, has been deleted, clone the backup back to the
same path (the backup's name comes from the path, so the job then carries on
with the same backup):

```bash
ls ~/.hermitcrm/backups/
mv ~/crm ~/crm-damaged                     # if anything is left of it
git clone ~/.hermitcrm/backups/<folder>-<hash>.git ~/crm
cd ~/crm
git remote set-url origin <your private remote>   # or: git remote remove origin
```

That gives the backup's `main`. Two things may be newer than it: uncommitted
edits (the newest `snapshots/<time>`) and, if the history was rewritten
before the folder went, the newest `rewritten/<time>/main` (`hermitcrm backup
status` lists them). Put back whichever you want:

```bash
hermitcrm backup list -n 5
hermitcrm backup restore snapshots/<time> --apply
```

## What it does not cover

- **The backup and the folder on the same disk.** A dead disk or a stolen
  laptop takes both. Set a private git remote (Settings, Backup) and/or use
  Time Machine or another machine-level backup; `backup_dir` can also point at
  a folder another disk or a sync service holds.
- **Someone going after the backup itself.** Anything running as you can
  delete `~/.hermitcrm/backups`. Hermit CRM notices (the next run says the
  backup "was missing" and `doctor` warns) but cannot bring it back. Claude
  Code is denied that path (above); other agents only have the written rule.

Related: [Settings](/help/settings), [CLI](/help/cli), [AI agents](/help/ai-agents)
