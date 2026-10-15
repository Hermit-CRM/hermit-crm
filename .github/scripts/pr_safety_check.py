"""PR safety check: flags changes in a pull request that need a careful human look.

It compares a pull request with the branch it wants to merge into and prints one
plain-English line per finding. It exits with status 1 when anything was found,
which makes the "pr-safety-check" check fail on GitHub.

It only reads git history. It never runs, imports or installs anything from the
pull request. Standard library only.

Run it yourself:  python3 .github/scripts/pr_safety_check.py <base> <head>
e.g.              python3 .github/scripts/pr_safety_check.py origin/main HEAD
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import sys
from collections import Counter

# --- What counts as a sensitive file ------------------------------------------

# (pattern on the file path, reason shown to the maintainer)
SENSITIVE_PATHS = [
    (r"(^|/)install[^/]*$", "it is an install file; users' AI agents follow install instructions on their Mac"),
    (r"(^|/)(setup|bootstrap)[^/]*$", "it is an install or setup script"),
    (r"(^|/)(CLAUDE|AGENTS|GEMINI|COPILOT)\.md$", "it tells AI agents what to do"),
    (r"(^|/)\.claude/", "it configures or instructs Claude Code"),
    (r"(^|/)\.(cursor|codex|windsurf|aider)[^/]*", "it configures or instructs an AI coding agent"),
    (r"(^|/)\.cursorrules$", "it instructs an AI coding agent"),
    (r"(^|/)[^/]*prompt[^/]*$|(^|/)prompts?/", "it looks like a prompt for an AI agent"),
    (r"(^|/)\.github/", "it controls GitHub automation (workflows, owners, Dependabot)"),
    (r"(^|/)CODEOWNERS$", "it decides who must review changes"),
    (r"(^|/)(pyproject\.toml|uv\.lock|poetry\.lock|Pipfile(\.lock)?|requirements[^/]*\.txt|setup\.cfg|MANIFEST\.in)$",
     "it changes which outside packages get installed"),
    (r"(^|/)(package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|Podfile(\.lock)?|Package\.swift|Package\.resolved|Gemfile(\.lock)?|Cargo\.(toml|lock)|go\.(mod|sum))$",
     "it changes which outside packages get installed"),
    (r"(^|/)(Makefile|Dockerfile|fly\.toml|nginx\.conf|build\.py)$", "it is a build or deploy file"),
    (r"^scripts/", "it is a build or release script"),
    (r"\.(sh|bash|zsh|command|tool)$", "it is a shell script"),
    (r"(^|/)\.gitattributes$", "it decides which files end up in the release download"),
]

# README sections whose headings contain one of these words count as install sections.
INSTALL_HEADING = re.compile(r"install|set ?up|setup|getting started|quick ?start|upgrad|updat|requirement", re.I)

# --- Content patterns ----------------------------------------------------------

NETWORK = [
    (r"\burllib\b|\burlopen\b|\bhttp\.client\b|\bhttp\.server\b|\bhttplib\b", "Python web request code (urllib/http)"),
    (r"\brequests\.|\bimport requests\b|\bhttpx\b|\baiohttp\b|\burllib3\b|\bpycurl\b", "a Python web request library"),
    (r"\bsocket\b|\bsocketserver\b|\bssl\.wrap|\bsmtplib\b|\bftplib\b|\bimaplib\b|\bpoplib\b|\btelnetlib\b|\bparamiko\b",
     "network socket or mail/FTP code"),
    (r"\bfetch\s*\(|XMLHttpRequest|\bWebSocket\b|\bEventSource\b|sendBeacon|\baxios\b|\$\.(ajax|get|post)\s*\(",
     "browser code that talks to a server"),
    (r"\bcurl\b|\bwget\b|\bnc\s+-|\bnetcat\b|\bscp\b|\brsync\b|\bssh\s", "a command that downloads or uploads over the network"),
    (r"<(script|iframe|link|img)[^>]+(src|href)\s*=\s*['\"]?(https?:)?//", "a web page element that loads something from another site"),
    (r"\bURLSession\b|\bNSURLConnection\b|\bnet\.(connect|createConnection)|\bhttps?\.(get|request)\s*\(",
     "network request code"),
]

EXECUTION = [
    (r"\bsubprocess\b|\bos\.(system|popen|exec\w*|spawn\w*|fork|posix_spawn\w*)\b|\bpty\.spawn\b|\bcommands\.getoutput\b",
     "code that runs other programs or shell commands"),
    (r"shell\s*=\s*True", "a shell command built from text (shell=True)"),
    (r"(?<![\w.])(eval|exec|execfile|compile)\s*\(", "code that runs text as code (eval/exec)"),
    (r"__import__\s*\(|\bimportlib\b|\bctypes\b|\bcffi\b|\bmarshal\.loads|\bpickle\.loads?\b|\bdill\b",
     "code that loads code in an unusual way"),
    (r"\bnew\s+Function\s*\(|\bFunction\s*\(\s*['\"]|\bchild_process\b|\bsetTimeout\s*\(\s*['\"]",
     "JavaScript that runs text as code or starts programs"),
    (r"\bosascript\b|\bAppleScript\b|\bsudo\b|\bchmod\b|\bchown\b|\bxattr\b|\bspctl\b|\bcodesign\b|\bcsrutil\b",
     "a Mac system or permission command"),
    (r"\blaunchctl\b|LaunchAgents|LaunchDaemons|\bcrontab\b|\blogin ?items?\b|\.plist\b|\bsystemctl\b",
     "something that makes a program start automatically"),
    (r"\|\s*(ba|z)?sh\b|\bbash\s+-c\b|\bsh\s+-c\b|\bzsh\s+-c\b", "a command piped into a shell"),
]

OBFUSCATION = [
    (r"[A-Za-z0-9+/]{200,}={0,2}", "a long block of encoded text (looks like base64)"),
    (r"(?:[0-9a-fA-F]{2}){100,}", "a long block of hex-encoded data"),
    (r"(?:\\x[0-9a-fA-F]{2}){20,}|(?:\\u[0-9a-fA-F]{4}){20,}|(?:%[0-9a-fA-F]{2}){30,}", "a long run of escaped characters"),
    (r"\b(atob|btoa|b64decode|b64encode|a85decode|b85decode|fromCharCode|codecs\.decode|zlib\.decompress|bz2\.decompress|lzma\.decompress)\b",
     "code that decodes hidden text"),
    (r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]", "invisible or text-direction characters that can hide what code really does"),
]

BINARY_EXT = re.compile(
    r"\.(dylib|so|dll|exe|bin|o|a|app|pkg|dmg|zip|tar|gz|tgz|bz2|xz|7z|rar|jar|war|class|pyc|pyo|whl|egg|wasm|"
    r"msi|deb|rpm|iso|img|node|elf|out|scpt|scptd|workflow)$", re.I)
MINIFIED = re.compile(r"\.min\.(js|css|mjs)$|[-.]bundle\.js$", re.I)

URL = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"<>()\[\]{}`]+")
IPV4 = re.compile(r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\w.])")
TLDS = ("com|org|net|io|dev|app|co|ai|xyz|ru|cn|info|biz|me|sh|gg|top|site|online|cloud|tk|link|eu|nl|de|fr|"
        "uk|us|be|ch|at|pw|cc|ws|to|ly|so|club|space|tech|store|live|pro|run|page|zip|mov")
DOMAIN = re.compile(r"(?<![\w@/.-])(?:[a-zA-Z0-9-]+\.)+(?:" + TLDS + r")(?![\w-])", re.I)
QUOTED = re.compile(r"(['\"])(.*?)\1")
# Reserved for documentation and testing, or this machine: never a real destination.
HARMLESS_HOST = re.compile(r"(^|\.)(example\.(com|org|net)|localhost|invalid|test)$|^127\.|^0\.0\.0\.0$|^::1$", re.I)
CODE_FILE = re.compile(r"\.(py|js|mjs|ts|swift|rb|go|rs|java|kt)$")
PROSE_FILE = re.compile(r"\.(md|markdown|txt|rst|html?)$", re.I)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def in_base(base: str, needle: str) -> bool:
    """True if the base branch already contains this exact text somewhere."""
    r = subprocess.run(["git", "grep", "-q", "-F", "-i", "-e", needle, base, "--"],
                       capture_output=True)
    return r.returncode == 0


def entropy(s: str) -> float:
    counts = Counter(s)
    return -sum(c / len(s) * math.log2(c / len(s)) for c in counts.values())


def host_of(url: str) -> str:
    rest = url.split("://", 1)[1]
    return rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0].rsplit("@", 1)[-1].split(":", 1)[0]


def added_lines(base: str, head: str) -> dict[str, list[tuple[int, str]]]:
    """Map each changed file to the lines the PR adds, with their new line numbers."""
    out: dict[str, list[tuple[int, str]]] = {}
    path, lineno = None, 0
    for line in git("diff", "-U0", "--no-color", "--no-ext-diff", f"{base}...{head}").splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            if path is not None:
                out.setdefault(path, [])
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and path is not None:
            out[path].append((lineno, line[1:]))
            lineno += 1
    return out


def removed_line_numbers(base: str, head: str, path: str) -> list[int]:
    nums, lineno = [], 0
    for line in git("diff", "-U0", "--no-color", f"{base}...{head}", "--", path).splitlines():
        if line.startswith("@@"):
            m = re.search(r"-(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("-") and not line.startswith("---"):
            nums.append(lineno)
            lineno += 1
    return nums


def heading_at(text: str, lineno: int) -> str:
    heading = ""
    for i, line in enumerate(text.splitlines(), 1):
        if i > lineno:
            break
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
    return heading


def check(base: str, head: str) -> list[str]:
    # (file, reason) -> line numbers, so a reason that repeats is reported once per file.
    found: dict[tuple[str, str], list[int]] = {}

    def flag(path: str, line: int | None, why: str) -> None:
        lines = found.setdefault((path, why), [])
        if line and line not in lines:
            lines.append(line)

    # File-level checks: what was added, changed, deleted, and with which permissions.
    merge_base = git("merge-base", base, head).strip()
    for raw in git("diff", "--raw", "--no-renames", f"{base}...{head}").splitlines():
        meta, _, path = raw.partition("\t")
        old_mode, new_mode, *_rest, status = meta.lstrip(":").split()
        if new_mode == "120000":
            flag(path, None, "adds a shortcut (symlink) that could point anywhere on the computer.")
        if new_mode == "100755" and old_mode != "100755":
            flag(path, None, "is marked as a program that can be run directly (executable).")
        if BINARY_EXT.search(path):
            flag(path, None, "is a compiled, packaged or compressed file that a person cannot read.")
        if MINIFIED.search(path):
            flag(path, None, "is minified (squashed) code that a person cannot read.")
        for pattern, reason in SENSITIVE_PATHS:
            if re.search(pattern, path, re.I):
                verb = "deletes" if status == "D" else "changes"
                flag(path, None, f"this PR {verb} a sensitive file: {reason}.")
                break

    for line in git("diff", "--numstat", f"{base}...{head}").splitlines():
        added, removed, path = line.split("\t", 2)
        if added == "-" and removed == "-":
            flag(path, None, "is a binary (non-text) file that a person cannot read.")

    # README install sections, judged by the heading above each changed line.
    for path in git("diff", "--name-only", f"{base}...{head}").splitlines():
        if not re.search(r"(^|/)README[^/]*$", path, re.I):
            continue
        sections = set()
        try:
            new_text = git("show", f"{head}:{path}")
            sections |= {heading_at(new_text, n) for n, _ in added_lines(base, head).get(path, [])}
        except subprocess.CalledProcessError:
            pass
        try:
            old_text = git("show", f"{merge_base}:{path}")
            sections |= {heading_at(old_text, n) for n in removed_line_numbers(base, head, path)}
        except subprocess.CalledProcessError:
            pass
        for s in sorted(x for x in sections if INSTALL_HEADING.search(x)):
            flag(path, None, f"changes the install part of the README (section \"{s}\").")

    # Line-level checks on everything the PR adds.
    seen_hosts: set[tuple[str, str]] = set()
    for path, lines in added_lines(base, head).items():
        if BINARY_EXT.search(path):
            continue
        blob = "".join(text for _, text in lines)
        if len(blob) >= 400 and entropy(blob) > 5.3:
            flag(path, None, "the added text looks scrambled or encrypted (unusually random characters).")
        for n, text in lines:
            # A Markdown or HTML paragraph is one long line; only flag it if it is not prose.
            prose = PROSE_FILE.search(path) and text.count(" ") / max(len(text), 1) > 0.08
            if len(text) > 500 and not prose:
                flag(path, n, "has very long lines (over 500 characters), which can hide code.")
            for token in re.findall(r"\S{120,}", text):
                if entropy(token) > 4.8 and not URL.fullmatch(token):
                    flag(path, n, "contains a long run of random-looking characters (possibly hidden data).")
                    break

            # New web addresses, domains and IP addresses.
            candidates = [(m.group(0).rstrip(".,;:"), host_of(m.group(0))) for m in URL.finditer(text)]
            candidates += [(m.group(0), m.group(0)) for m in IPV4.finditer(text)]
            domain_source = text if not CODE_FILE.search(path) else " ".join(q[1] for q in QUOTED.findall(text))
            candidates += [(m.group(0), m.group(0)) for m in DOMAIN.finditer(domain_source)]
            for shown, host in candidates:
                host = host.lower()
                if not host or HARMLESS_HOST.search(host) or (path, host) in seen_hosts:
                    continue
                seen_hosts.add((path, host))
                if not in_base(base, host):
                    flag(path, n, f"adds a web address or server that was not in the project before: {shown}. "
                                  "New addresses can send data to, or fetch code from, somewhere new.")

            for group, label in ((NETWORK, "talks to the internet"), (EXECUTION, "runs other programs or code"),
                                 (OBFUSCATION, "hides what it does")):
                for pattern, reason in group:
                    if re.search(pattern, text):
                        flag(path, n, f"adds code that {label}: {reason}.")
                        break
    findings = []
    for (path, why), lines in found.items():
        if not lines:
            where = path
        elif len(lines) == 1:
            where = f"{path} (line {lines[0]})"
        else:
            shown = ", ".join(map(str, lines[:5]))
            more = f" and {len(lines) - 5} more" if len(lines) > 5 else ""
            where = f"{path} (lines {shown}{more})"
        findings.append(f"{where}: {why}")
    return findings


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    base, head = sys.argv[1], sys.argv[2]
    findings = check(base, head)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not findings:
        msg = "PR safety check: nothing suspicious found. A human review is still needed before merging."
        print(msg)
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        return 0
    header = (f"PR safety check: {len(findings)} thing(s) need a careful human look before this can be merged.\n"
              "This does not mean the change is bad, only that a person must check these parts.\n")
    print(header)
    for item in findings:
        print("  - " + item)
        if os.environ.get("GITHUB_ACTIONS"):
            # Also show each finding as an annotation on the PR's "Files changed" tab.
            print("::warning title=PR safety check::" + item.replace("%", "%25").replace("\n", " "))
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## " + header + "\n" + "".join(f"- {i}\n" for i in findings))
    return 1


if __name__ == "__main__":
    sys.exit(main())
