# One-click upgrade

Status: being built the day it was written, 20 Oct 2026. The review gate was
waived by Gijs's standing "don't block on questions" instruction, so every
decision below that he did not state is marked **call** and listed again at the
end for a veto. Decisions marked **yours** are his words.

## Why

New versions ship often and will keep shipping. Today an upgrade is three steps
by hand: run the command the nav notice names, restart the server, reload the
browser. Skipping the second one is not harmless. On 20 Oct an assistant
reinstalled the tool while `io.hermitcrm.serve` was still running 0.7.5 in
memory. Jinja read the new `settings.html` from disk, which asked for a
`playbook_status` value the old Python never supplied, and every page broke. A
forced reload could not help; the browser was fine.

Two gaps stand behind that:

1. **The check runs once, at process start.** `UpdateNotice.start()` is called
   from `create_app`. A server that has been up since Friday never asks again,
   so it never learns of a release.
2. **Nothing notices that the files on disk are newer than the program in
   memory.** That is the state that broke.

## Goals

- **yours:** users can tell they are on an old version, and are prompted to
  upgrade.
- **yours:** the upgrade is one click and covers downloading and installing the
  new version, restarting the server, and prompting the user to reload the
  browser.
- **call:** a long-running server keeps checking (still at most one network
  request a day, same cache, same promise to the user).
- **call:** when the version on disk is newer than the running one, say so and
  offer one-click restart. This covers an upgrade made from a terminal or by an
  assistant.
- **call:** when a page errors while the server is in that state, the error page
  says why and offers the restart, in place of a bare "Internal Server Error".
- **call:** every other open tab is told to reload after a restart.

## Non-goals and anti-goals

- No upgrade without a click. No automatic install, ever.
- No new telemetry and no new network destination. The only new network traffic
  is the installer the user's own tool (uv, pipx, pip) runs against PyPI.
- No rollback in this version. A failed install leaves the old files in place
  (uv and pipx replace atomically enough for that); a failed self-check says so
  and names the command that pins the previous version.
- Not for servers reachable from the network, Windows, installs whose
  `update_url` is not PyPI, or a system Python (`pip` outside a virtualenv).
  There the notice keeps showing the command, as it does today.
- No "check now" button. No change to the 24-hour interval.
- The first upgrade *to* this version is still by hand: the running server does
  not have the button yet.

## How it works

**Detecting.** `updates.DiskWatch` reads the installed version off the
`hermitcrm-*.dist-info/METADATA` file on `sys.path` (not `importlib`, which the
PR safety check flags; `test_no_telemetry.py` does the same), memoised for a few
seconds. If that version is newer than `hermitcrm.__version__` the process is
*stale*. `UpdateNotice.tick()` runs on each page load and starts a background
re-check when the last one is more than an hour old; `look()` still decides
whether the network is touched, so the cache and the 24 h promise stand.

**Upgrading.** `upgrade.py` holds one `Upgrader`. `POST /upgrade` starts a
thread:

1. *install* — the fixed command from `updates.upgrade_argv()` (`uv tool
   install hermitcrm@latest`, `pipx install --force hermitcrm`, or `pip install
   --upgrade hermitcrm`), run without a shell, 10 minute limit. uv and pipx are
   found on the PATH launchd gives jobs plus `~/.local/bin`, `~/.cargo/bin` and
   Homebrew.
2. *verify* — `python -I -m hermitcrm.cli --version` in a child process: the new
   files must start and must be newer than what is running. If not, the server
   keeps running and the page says what to do. This is what stops a bad release
   from putting launchd's `KeepAlive` into a crash loop.
3. *restart* — uvicorn is asked to shut down gracefully (in-flight requests
   finish, 10 s cap), `cmd_serve` sees the flag and `os.execv`s the same
   command line. Same PID, so launchd, systemd and a terminal all see one
   unbroken process, and a `hermitcrm serve` nobody supervises comes back too.

`POST /upgrade/restart` is steps 2 and 3 alone, for the stale-process case.

**While it runs** a middleware answers every page with a small 503 that
reloads itself, so the half-replaced templates are never served. Only
`/upgrade`, `/upgrade/status` and `/static/` stay open.

**The browser.** `upgrade.js` is loaded on every page. A form marked
`data-upgrade` is submitted with `fetch`; an overlay shows the step, polls
`/upgrade/status` once a second, and when the server comes back with a different
`boot` id says "Upgraded to vX" with a **Reload** button (it does not reload by
itself). Each page also asks `/upgrade/status` when its tab becomes visible; a
different `boot` id gives that tab the same Reload prompt. Without JavaScript the
form posts normally and lands on `/upgrade`, a plain status page that refreshes
itself.

**Pages that cannot depend on templates.** The 503 page, `/upgrade` and the
stale-process 500 page are built from Python strings. The failure being fixed is
"templates and code disagree"; a page that extends `base.html` could break the
same way.

**Who may click.** The button appears only when the server is bound to a
loopback address (Hermit CRM has no password, so on a network anyone could click
it). It needs the per-process CSRF token on top of the existing cross-site
guard. The command is fixed text; nothing from the network or the request is
interpolated into it.

## Left to the builder

CSS for the banner and overlay, in the app's existing tokens; the wording of the
steps; where in Settings → About the buttons sit.

## Calls, for a veto

1. Loopback-only for the one-click path.
2. `@latest` / `--force` / `--upgrade`, not a pinned version: the version string
   comes from PyPI's answer and is for display only.
3. exec in place rather than exit-and-let-the-supervisor-restart.
4. Verify before restarting, no rollback.
5. The Reload button is a prompt, not an automatic reload (as asked); the
   overlay does not close itself.
6. Restart is allowed even when nothing is stale (harmless, useful for support).
7. Website docs (`website/site/docs`) not touched here; Help, README, INSTALL
   and the changelog are.
