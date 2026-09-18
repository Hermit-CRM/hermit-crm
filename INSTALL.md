# Installing Hermit CRM

You have unpacked Hermit CRM into a folder. Open that folder in an AI coding
tool (Claude Code, Codex, Cursor, Gemini CLI, or any other) and send it one
message:

> Read INSTALL.md and set up Hermit CRM for me.

It will do the rest and ask you what it needs to know. You need Python 3.11 or
newer and git; the assistant checks both. **On a Mac that has never been used
for programming, neither is really there** and one dialog has to be clicked by
you: the assistant will say so and wait.

Prefer to do it by hand? [README.md](README.md) has the same steps as commands.

---

## For the assistant

You are installing Hermit CRM for the person you are talking to, on their
machine. Assume they are not a developer: say what you are doing in plain
words, run the commands yourself, and do not hand them a terminal unless a step
below says to.

Hermit CRM is a CRM that is a folder of Markdown files in git. Nothing leaves
their machine. Work through these in order and stop at the first failure, with
the error and what it means.

### 1. Check the machine

```bash
git --version
python3 --version
```

`git` must print a version, and Python must be **3.11 or newer**. If both are
fine, go to step 2.

**On a Mac, expect both to fail, and not in the way they look like they fail.**
`/usr/bin/python3` and `/usr/bin/git` always exist, so `which` finds them, but
they are stubs. Until Apple's Command Line Tools are installed they do nothing
except ask for those tools:

```
xcode-select: note: No developer tools were found, requesting install.
```

That is not "git is missing". It is "git is a placeholder for git". Check it
directly rather than guessing:

```bash
xcode-select -p          # prints a path when the tools are installed; errors when not
```

There are two separate problems on such a Mac, and fixing the first does not fix
the second:

**Git.** Work down this list and stop at the first one that prints a version.

*It may already be on the disk.* If full Xcode is installed, it carries its own
git and nothing needs installing:

```bash
ls /Applications/Xcode.app/Contents/Developer/usr/bin/git
```

If that file exists, put it on PATH and go to Python:

```bash
export PATH="/Applications/Xcode.app/Contents/Developer/usr/bin:$PATH"
```

*Someone is sitting at the Mac.* Run it yourself:

```bash
xcode-select --install
```

It returns immediately and opens a dialog **they** have to click Install in;
nothing you can type dismisses it. Tell them plainly: a window has opened, press
Install, it takes a few minutes, tell me when it finishes. Then re-run
`git --version`. (If it says the tools are already installed but git still fails,
their install is broken: `sudo rm -rf /Library/Developer/CommandLineTools` and
`xcode-select --install` again. Say so; do not run it yourself.)

*Nobody is sitting at the Mac.* If that install fails with something about no
active GUI session, then no one is logged in at the screen: you are on SSH, or in
a background session. Apple's installer is a window, so it cannot open, and
waiting will not change that. Say so rather than retrying, and take one of the
two ways around it.

With a password, install the same tools with no dialog. This is Apple's own
unattended path, the one build servers use:

```bash
sudo touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
label=$(softwareupdate -l | grep -o 'Command Line Tools for Xcode.*' | tail -1)
sudo softwareupdate -i "$label" --verbose
sudo rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
```

`sudo` will ask for a password. If you were not given one, ask for it or ask them
to run those four lines; never guess at it.

Without a password, skip Apple's tools altogether. Hermit CRM wants *a* git, not
Apple's git, and conda-forge publishes a ready-built one that unpacks into the
home folder:

```bash
curl -Ls https://micro.mamba.pm/api/micromamba/osx-arm64/latest | tar -xj bin/micromamba
./bin/micromamba create -y -p "$HOME/.hermit-tools" -c conda-forge git
export PATH="$HOME/.hermit-tools/bin:$PATH"
git --version
```

Use `osx-64` instead of `osx-arm64` on an Intel Mac; `uname -m` says which
(`arm64` or `x86_64`). It takes about ten seconds, writes only inside the home
folder, compiles nothing and asks for no password. Add that `export PATH` line to
`~/.zshrc` so tomorrow's shell still has git. Homebrew is not the answer here: it
requires the same Command Line Tools you are working around.

**Python.** Command Line Tools ship **Python 3.9.6**, which is too old for Hermit
CRM, so `xcode-select --install` will not fix this and neither will waiting. Do
not send them to python.org and do not use Homebrew, which needs the same
Command Line Tools and takes far longer. Install `uv`, which brings its own
Python and needs no compiler:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then use `uv` for step 2. It downloads a suitable Python by itself when the
system one is too old, so there is nothing else to install. If you would rather
be explicit, `uv python install 3.12` first.

Stop only if every one of those git routes fails, or the `uv` install fails; say
which ones you tried and what each said.

### 2. Install the `hermitcrm` command

From this folder, try these in order and stop at the first that works:

```bash
uv tool install .
pipx install .
```

`uv tool install .` is the one to want: it fetches a Python matching Hermit CRM's
requirement when the system Python is too old, so it works on a machine where
`python3 --version` still says 3.9.6.

If neither tool exists, fall back to a virtualenv and put the command on their
PATH:

```bash
python3 -m venv ~/.hermitcrm-venv
~/.hermitcrm-venv/bin/pip install .
mkdir -p ~/.local/bin && ln -sf ~/.hermitcrm-venv/bin/hermitcrm ~/.local/bin/hermitcrm
```

Confirm with `hermitcrm --version`. If that is not found, `~/.local/bin` is not
on their PATH: tell them the one line to add to `~/.zshrc` or `~/.bashrc`, and
use the full path for the rest of these steps.

Do **not** use `pip install .` into a bare virtualenv without the symlink. It
works today and stops working the moment they close the terminal, which they
will not connect to anything you did.

### 3. Create their data folder

Ask where it should live; suggest `~/crm`. Then:

```bash
hermitcrm init ~/crm
```

This makes a git repository. It is their data, on their disk.

### 4. Ask who they are, and write it down yourself

**Do not run `hermitcrm setup`.** It asks its questions on a terminal you do
not control; with no one typing it stops without collecting anything. Ask in
the conversation instead:

- their name (its first word signs outreach drafts);
- the email addresses they send from, comma-separated. Mail from these counts
  as outbound, and their work domains stop colleagues being logged as contacts.

Then edit `~/crm/config.toml`: uncomment `owner_name`, `owner_email` and
`my_addresses` and set them. Every key in that file is already there, commented
out, with a line explaining it. Keep the comments. Run `hermitcrm --data ~/crm
check` afterwards.

If the line below has an address on it, set `feedback_email` to it in the same
file. It is where the Feedback form offers to send a report, and it is the only
way whoever packaged this hears whether it worked.

    feedback_email: gcjbos@gmail.com

### 5. Start the app and show them

```bash
hermitcrm --data ~/crm serve
```

Run it in the background and give them the link: http://127.0.0.1:8765. Let
them look around before you continue.

### 6. Secrets are theirs to type, and never yours to see

Hermit CRM can read mail you BCC to it and log past meetings from a calendar
feed. Both need a secret: a mail app password, and a private calendar URL.

**Never ask for one, never accept one if they offer, and never type one into a
command or a file.** They go through the form at
http://127.0.0.1:8765/settings, which writes them to `.secrets.toml` (mode 600)
or the macOS Keychain, on their machine only. A secret pasted into this
conversation leaves their machine and reaches a model provider.

So: tell them those two sections exist, what each one buys them, and that they
fill them in themselves on that page. Offer to wait, and to read the result of
**Test connection** with them. Both are optional; the CRM works without either.

### 7. Check the installation

```bash
hermitcrm --data ~/crm doctor
```

Walk through anything it reports as `warn` or `fail`. Missing BCC or calendar
settings are expected if they skipped step 6.

### 8. Offer the daily job

```bash
hermitcrm --data ~/crm schedule install --serve
```

This runs the mail and calendar import once a day and keeps the web app
running, through launchd on a Mac or a systemd user unit on Linux. On Windows
it prints `schtasks` commands for them to run. Only do this if they say yes,
and only if they set up step 6.

### 9. Offer to connect it to the AI tool they are already in

`hermitcrm mcp` serves the folder over MCP, so the assistant they use every day
can read the pipeline and log interactions without a terminal. The Settings
page has an **Access** section with the exact JSON for their machine, paths
filled in. Point them there, or paste it into their client's MCP config for
them if they ask.

### 10. Tell them what they can do now

Show them, briefly and in their words: add a company, log an interaction, what
the follow-up radar on the home page is for. `hermitcrm help` lists the topics,
and every page in the app has a Help link. Do not dump the whole manual.

Point out **Help -> Feedback**. Hermit CRM is early, and the small annoyances --
a label read twice, a button looked for and not found -- are the ones that never
get reported, because reporting them means leaving what you were doing. The form
writes a file into their folder and hands it back to them to send; it posts
nothing anywhere.

### What not to do

- Do not modify the Hermit CRM source you just unpacked. They are installing
  it, not developing it. `CLAUDE.md` and `AGENTS.md` in this folder are rules
  for changing the code; they do not apply to an install.
- Do not create companies, contacts or interactions to "test" it. The demo data
  is `hermitcrm init <path> --demo` in a throwaway folder if you need one.
- Do not push their data anywhere. The backup section in Settings sets up a
  git remote, and they choose it; it must be a **private** repository.
