# Installing Hermit CRM

You have unpacked Hermit CRM into a folder. Open that folder in an AI coding
tool (Claude Code, Codex, Cursor, Gemini CLI, or any other) and send it one
message:

> Read INSTALL.md and set up Hermit CRM for me.

It will do the rest and ask you what it needs to know. You need Python 3.11 or
newer and git; the assistant checks both.

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

`python3 --version` must report 3.11 or newer, and `git --version` must work.
If Python is older or missing, stop: tell them to install Python 3.11+ from
python.org (or `brew install python` on a Mac) and say you will continue after
that. Do not try to install Python for them.

### 2. Install the `hermitcrm` command

From this folder, try these in order and stop at the first that works:

```bash
uv tool install .
pipx install .
```

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

    feedback_email:

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
