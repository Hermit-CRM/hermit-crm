# Security policy

## Reporting a vulnerability

Mail **gcjbos@gmail.com** with `hermitcrm security` in the subject.

Useful things to include: the version (`hermitcrm --version`), what an attacker
would gain, and the smallest set of steps that shows it. A patch is welcome and
not expected.

Please do not open a public issue for something exploitable. Give it a little
time in private first — a week or two is plenty for a project this size.

## What you will get back

An acknowledgement when the report is read, and an honest answer about whether
it will be fixed.

**There is no guarantee of a fix.** There is no response time, no service level
and no obligation to act at all. Hermit CRM is free, unpaid alpha software
maintained by one person in their own time. A report may be fixed the same day,
fixed in six months, documented as a known limitation, or declined. Assume
nothing; the answer will be honest either way.

If a report is not acted on and you think it should be public, say so and
publish it. That is a fair thing to do.

## Supported versions

Only the latest release. There are no backports and no security branches.

## What is in scope

The code in this repository: the CLI, the local web app, the MCP server, the
importers, and the file handling. Especially worth reporting:

- A way to read or write files outside the data folder.
- A way for a web page in another tab to make the local app change your data
  (the app has a host allowlist, a CSRF token, a cross-site check and a strict
  Content-Security-Policy; a way past any of them is a real finding).
- A secret leaking into the git history, a log, a commit message, a report, or
  the Feedback form.
- A crafted mail, calendar entry or scraped page that causes code to run.

## What is out of scope

- Anything that needs an attacker to already have your shell or your disk. If
  they are inside the machine, the CRM is not the problem.
- Running `hermitcrm serve --host 0.0.0.0` on an untrusted network. That flag
  is documented as putting the app on your LAN with no authentication. It is a
  choice, not a bug.
- Vulnerabilities in dependencies, upstream. Report those upstream. Tell us if
  Hermit CRM's own use of one makes it exploitable here.
- Anything in an AI tool, mail provider or other third-party service you have
  connected. See [DISCLAIMER.md](DISCLAIMER.md).
- Missing hardening that costs a dependency. The project is standard library
  where it can be, on purpose.

## No warranty

Reporting a bug, and the author reading it, creates no obligation and no
warranty. See [DISCLAIMER.md](DISCLAIMER.md) and sections 7 and 8 of
[LICENSE](LICENSE).
