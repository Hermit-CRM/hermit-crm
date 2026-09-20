# Copyright 2026 Gijs Bos
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Look up missing company and contact fields with an AI command-line tool.

Any of the supported CLIs (Claude Code, OpenAI Codex, Gemini CLI, Grok CLI) or
a custom command runs non-interactively and returns JSON. The app only
proposes values; a person confirms them before anything is written. Configure
with `enrich_provider` ("auto" picks the first CLI on PATH), `enrich_command`
(binary override, or the full command line for "custom"), `enrich_model` and
`enrich_timeout` in config.toml. Nothing here imports the store: callers pass
records in and apply the returned fields themselves.
"""

from __future__ import annotations

import copy
import json
import re
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .models import Company, Contact, Country, normalise_country

COMPANY_FIELDS = {
    "website": ("string", "official website URL"),
    "linkedin": ("string", "LinkedIn company page URL"),
    "country": ("string", "HQ country as an ISO 3166-1 alpha-2 code "
                          "(DE, GB, US, ...); null if unknown"),
    "product_oneliner": ("string", "one sentence saying what the product does and "
                                   "for whom"),
}
CONTACT_FIELDS = {
    "title": ("string", "current job title at the company"),
    "linkedin": ("string", "personal LinkedIn profile URL"),
}

# JSON-schema types for a user-defined field that asked to be enriched.
CUSTOM_TYPES = {"number": "number", "text": "string", "date": "string",
                "select": "string"}


def fields_with_custom(base: dict, defs: list, scope: str) -> dict:
    """The fixed schema plus any custom field that set `enrich = true`.

    A user who defines their own field and says what it means gets the model
    filling it, which is strictly more than the two hard-coded fields this
    replaced.
    """
    out = dict(base)
    for d in defs:
        if d.applies_to != scope or not d.enrich:
            continue
        description = d.description or d.help or d.label
        if d.type == "select" and d.options:
            description += " (one of: " + ", ".join(d.options) + ")"
        out[d.key] = (CUSTOM_TYPES.get(d.type, "string"), description)
    return out


class EnrichError(Exception):
    """The CLI could not be run or returned nothing usable."""


@dataclass
class Proposal:
    fields: dict = field(default_factory=dict)   # field -> proposed value
    missing: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    notes: str = ""


def _schema(fields: dict[str, tuple[str, str]]) -> dict:
    props = {
        key: {"type": [kind, "null"], "description": desc}
        for key, (kind, desc) in fields.items()
    }
    props["sources"] = {"type": "array", "items": {"type": "string"},
                        "description": "URLs you relied on"}
    props["notes"] = {"type": "string",
                      "description": "one short line on confidence or caveats"}
    return {"type": "object", "properties": props,
            "required": list(fields) + ["sources", "notes"],
            "additionalProperties": False}


def _known(pairs: list[tuple[str, object]]) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in pairs if v not in ("", None, []))


def company_prompt(company: Company, missing: list[str]) -> str:
    known = _known([
        ("name", company.name), ("website", company.website),
        ("linkedin", company.linkedin), ("country", company.country),
        ("product", company.product_oneliner), ("tags", ", ".join(company.tags)),
    ])
    wanted = "\n".join(f"- {k}: {COMPANY_FIELDS[k][1]}" for k in missing)
    return (
        "You are filling gaps in a B2B sales CRM record. Use web search to find "
        "the missing facts about this company; prefer the company's own site and "
        "LinkedIn page. Return null for anything you cannot verify. Do not guess.\n\n"
        f"Known:\n{known}\n\nFind:\n{wanted}\n"
    )


def contact_prompt(company: Company, contact: Contact, missing: list[str]) -> str:
    known = _known([
        ("name", contact.name), ("company", company.name),
        ("company website", company.website), ("title", contact.title),
        ("linkedin", contact.linkedin),
    ])
    wanted = "\n".join(f"- {k}: {CONTACT_FIELDS[k][1]}" for k in missing)
    return (
        "You are filling gaps in a B2B sales CRM record for one person. Use web "
        "search; prefer LinkedIn and the company's own site. Only return facts "
        "about this exact person at this company. Return null for anything you "
        "cannot verify. Do not guess.\n\n"
        f"Known:\n{known}\n\nFind:\n{wanted}\n"
    )


def extract_json(text: str) -> dict:
    """Return the first balanced top-level {...} object in text.

    Tolerates code fences and chatter before or after the object; braces inside
    JSON strings are skipped. Raises EnrichError when there is no object.
    """
    text = text or ""
    start = text.find("{")
    while start != -1:
        depth, in_string, escaped = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(value, dict):
                        return value
                    break
        start = text.find("{", start + 1)
    snippet = " ".join(text.split())[:120]
    raise EnrichError("enrichment returned no JSON object"
                      + (f" (output began: {snippet!r})" if snippet else " (empty output)"))


def _schema_instruction(prompt: str, schema: dict) -> str:
    return (f"{prompt}\nReturn ONLY a JSON object matching this JSON schema, with no "
            f"other text:\n{json.dumps(schema)}\n")


# Two model tiers per provider: "medium" is the default for Enrich and Ask
# Hermit, "strong" is what "Retry with ..." uses. Overridable in config.toml
# (enrich_model, enrich_model_strong). Only the claude IDs are verified against
# the installed CLI; the others follow each vendor's naming and may need a
# Settings override.
TIERS = ("medium", "strong")
DEFAULT_MODELS = {
    "claude": {"medium": "claude-opus-5", "strong": "claude-fable-5-1"},
    "codex": {"medium": "gpt-5-mini", "strong": "gpt-5"},
    "gemini": {"medium": "gemini-2.5-flash", "strong": "gemini-2.5-pro"},
    "grok": {"medium": "grok-4-fast", "strong": "grok-4"},
}

# How the CLI is signed in. A subscription (a ChatGPT, Claude or Gemini plan)
# is not entitled to the same model ids as an API key, and asking for one it
# does not have is a hard error rather than a downgrade.
ACCOUNTS = ("subscription", "api")

# What a subscription gets instead, per provider. Only what is actually known
# belongs here: a ChatGPT account refuses `gpt-5-mini` outright, so codex is
# given no model flag at all and uses whatever that account gets. Claude's
# tiers work on a subscription, so claude is absent and keeps its defaults.
# An empty string means "pass no model flag".
SUBSCRIPTION_MODELS = {
    "codex": {"medium": "", "strong": ""},
}

# Every provider says "you cannot have that model" in its own words, and every
# one of them names the model when it does. Recognising it turns a wall of
# repeated JSON into one sentence naming the setting to change.
UNSUPPORTED_MODEL = re.compile(
    r"model[^\n]{0,80}?\bnot (supported|available|found)\b"
    r"|\bunknown model\b|\bmodel[_ ]not[_ ]found\b|\binvalid[_ ]model\b", re.I)


def error_lines(text: str, limit: int = 3) -> list[str]:
    """The last few distinct lines of a failure.

    A CLI that fails during startup and again during the run prints the same
    message several times; without the de-duplication the reader sees one fact
    three times and has to work out that it is one fact.
    """
    seen: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line and line not in seen:
            seen.append(line)
    return seen[-limit:]
MODEL_LABELS = {"claude-opus-5": "Opus", "claude-fable-5-1": "Fable",
                "claude-sonnet-5": "Sonnet", "claude-haiku-4-5": "Haiku"}


def model_label(model: str) -> str:
    """A short display name: Opus, Fable, or the model id itself."""
    return MODEL_LABELS.get(model, model) if model else "the default model"


class Provider:
    """One CLI: how to call it, what environment it gets, how to read its output."""

    name = ""
    default_binary = ""
    prompt_on_stdin = True

    def __init__(self, binary: str = ""):
        self.binary = binary or self.default_binary

    # Tools for a run: None = the enrich default (web search); a string is
    # provider-specific (Claude: an --allowedTools value). Set per call.
    tools: str | None = None

    def build_argv(self, schema_path: str, model: str, out_path: str = "",
                   prompt: str = "", schema: dict | None = None) -> list[str]:
        raise NotImplementedError

    def stdin(self, prompt: str, schema: dict) -> str | None:
        return prompt

    def parse(self, stdout: str, out_file_text: str = "") -> dict:
        return extract_json(stdout)

    def env(self, environ) -> dict:
        return dict(environ)

    @property
    def executable(self) -> str:
        return self.binary


class ClaudeProvider(Provider):
    """Claude Code: `claude -p` with web search and a JSON schema (verified 2.1.211)."""

    name, default_binary = "claude", "claude"

    def build_argv(self, schema_path, model, out_path="", prompt="", schema=None):
        argv = [self.binary, "-p", "--output-format", "json",
                "--json-schema", json.dumps(schema or {}),
                "--allowedTools", self.tools if self.tools is not None
                else "WebSearch,WebFetch"]
        if model:
            argv += ["--model", model]
        return argv

    def env(self, environ):
        # A nested session inherits CLAUDECODE; an API key would bypass the login.
        return {k: v for k, v in environ.items()
                if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY")}

    def parse(self, stdout, out_file_text=""):
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            raise EnrichError("enrichment returned no JSON")
        if not isinstance(payload, dict):
            raise EnrichError("enrichment returned no structured output")
        if payload.get("is_error"):
            raise EnrichError(f"enrichment failed: {payload.get('result', '')}")
        data = payload.get("structured_output")
        if data is None:
            try:
                data = json.loads(payload.get("result", ""))
            except (TypeError, json.JSONDecodeError):
                raise EnrichError("enrichment returned no structured output")
        return data


class CodexProvider(Provider):
    """OpenAI Codex: `codex exec` with --output-schema; the answer lands in a file.

    Not installed when this was written: flags follow the Codex CLI docs. Web
    search is not switched on here (see README).
    """

    name, default_binary = "codex", "codex"

    def build_argv(self, schema_path, model, out_path="", prompt="", schema=None):
        argv = [self.binary, "exec", "--skip-git-repo-check",
                "--output-schema", schema_path, "--output-last-message", out_path]
        if model:
            argv += ["-m", model]
        return argv + ["-"]

    def parse(self, stdout, out_file_text=""):
        text = out_file_text.strip() or stdout
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        return extract_json(text)


class GeminiProvider(Provider):
    """Gemini CLI: prompt on stdin, `-p` appends the instruction, JSON envelope."""

    name, default_binary = "gemini", "gemini"
    instruction = "Answer the request above. Output only the JSON object."

    def build_argv(self, schema_path, model, out_path="", prompt="", schema=None):
        argv = [self.binary, "-p", self.instruction, "--output-format", "json"]
        if model:
            argv += ["-m", model]
        return argv

    def stdin(self, prompt, schema):
        return _schema_instruction(prompt, schema)

    def parse(self, stdout, out_file_text=""):
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return extract_json(stdout)
        if isinstance(payload, dict):
            if payload.get("error"):
                error = payload["error"]
                message = error.get("message") if isinstance(error, dict) else error
                raise EnrichError(f"enrichment failed: {message}")
            if isinstance(payload.get("response"), str):
                return extract_json(payload["response"])
            return payload
        raise EnrichError("enrichment returned no JSON object")


class GrokProvider(Provider):
    """Grok CLI: headless `grok -p <prompt>`; the whole prompt goes in argv.

    Not installed when this was written: the output may be a JSON envelope or
    plain text, so both are read.
    """

    name, default_binary = "grok", "grok"
    prompt_on_stdin = False

    def build_argv(self, schema_path, model, out_path="", prompt="", schema=None):
        argv = [self.binary, "-p", _schema_instruction(prompt, schema or {}),
                "--output-format", "json"]
        if model:
            argv += ["-m", model]
        return argv

    def stdin(self, prompt, schema):
        return None

    def parse(self, stdout, out_file_text=""):
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return extract_json(stdout)
        if isinstance(payload, list):  # a message list: the last one is the answer
            texts = [m.get("content") for m in payload
                     if isinstance(m, dict) and isinstance(m.get("content"), str)]
            return extract_json(texts[-1] if texts else "")
        if isinstance(payload, dict):
            for key in ("response", "result", "content", "text", "output"):
                if isinstance(payload.get(key), str):
                    return extract_json(payload[key])
            return payload
        raise EnrichError("enrichment returned no JSON object")


class CustomProvider(Provider):
    """Any command line: `{schema_file}` and `{model}` are substituted; prompt on stdin."""

    name = "custom"

    def build_argv(self, schema_path, model, out_path="", prompt="", schema=None):
        return [part.replace("{schema_file}", schema_path).replace("{model}", model or "")
                for part in shlex.split(self.binary)]

    @property
    def executable(self) -> str:
        try:
            parts = shlex.split(self.binary)
        except ValueError:
            return ""
        return parts[0] if parts else ""


PROVIDERS = {cls.name: cls for cls in
             (ClaudeProvider, CodexProvider, GeminiProvider, GrokProvider, CustomProvider)}
AUTO_ORDER = ("claude", "codex", "gemini", "grok")


# Where AI CLIs live when the process runs with a bare PATH (launchd, systemd,
# cron): Homebrew, npm/bun globals, pipx. Searched after PATH itself.
EXTRA_BIN_DIRS = ("/usr/local/bin", "/opt/homebrew/bin", "~/.local/bin",
                  "~/.npm-global/bin", "~/.bun/bin", "~/.cargo/bin", "~/bin")


def find_executable(name: str) -> str | None:
    """`shutil.which` that also looks in EXTRA_BIN_DIRS; returns the full path."""
    found = shutil.which(name)
    if found or not name or "/" in name:
        return found
    for d in EXTRA_BIN_DIRS:
        candidate = Path(d).expanduser() / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _located(candidate: "Provider", which) -> "Provider | None":
    """The candidate with its binary replaced by the path `which` found, so a
    CLI found outside PATH is still runnable."""
    found = which(candidate.executable)
    if not found:
        return None
    if isinstance(found, str) and os.path.isabs(found) and found != candidate.executable:
        candidate.binary = candidate.binary.replace(candidate.executable, found, 1)
    return candidate


def resolve_provider(provider: str = "auto", command: str = "",
                     which=find_executable) -> Provider | None:
    """Pick the provider for a config. None means no usable CLI was found.

    "auto" with an `enrich_command` set uses the provider whose name starts the
    command's file name (so `claude` or `/opt/bin/codex` keep working), and
    treats anything else as a custom command line.
    """
    provider = (provider or "auto").strip().lower()
    command = (command or "").strip()
    if provider == "auto":
        if command:
            try:
                base = Path(shlex.split(command)[0]).name.lower()
            except (ValueError, IndexError):
                base = ""
            name = next((n for n in AUTO_ORDER if base.startswith(n)), "custom")
            return _located(PROVIDERS[name](command), which)
        for name in AUTO_ORDER:
            candidate = _located(PROVIDERS[name](), which)
            if candidate:
                return candidate
        return None
    if provider not in PROVIDERS:
        raise EnrichError(f"unknown enrich_provider {provider!r}; use auto, "
                          + ", ".join(PROVIDERS))
    candidate = PROVIDERS[provider](command)
    if not candidate.binary:
        return None
    return _located(candidate, which)


def _with_path(env: dict, extra_path: str) -> dict:
    if extra_path:
        env["PATH"] = os.pathsep.join(p for p in (extra_path, env.get("PATH", "")) if p)
    return env


class Enricher:
    def __init__(self, provider: str = "auto", command: str = "", model: str = "",
                 timeout: float = 180, runner=None, which=find_executable,
                 model_strong: str = "", tier: str = "medium",
                 account: str = "subscription"):
        self.requested = (provider or "auto").strip().lower()
        self.command = command or ""
        self.overrides = {"medium": model or "", "strong": model_strong or ""}
        self.tier = tier if tier in TIERS else "medium"
        self.account = account if account in ACCOUNTS else "subscription"
        self.timeout = float(timeout)
        self.error = ""
        try:
            self.provider = resolve_provider(self.requested, self.command, which=which)
        except EnrichError as exc:  # a bad config must not stop the web app
            self.provider, self.error = None, str(exc)
        self.runner = runner or self._run_cli

    def model_for(self, tier: str) -> str:
        """The model id for a tier: an explicit override first, then the default
        for this account type. An empty string means no model flag at all, so
        the CLI answers on whatever the signed-in account gets."""
        tier = tier if tier in TIERS else "medium"
        if self.overrides.get(tier):
            return self.overrides[tier]
        name = self.provider_name
        if self.account == "subscription" and name in SUBSCRIPTION_MODELS:
            return SUBSCRIPTION_MODELS[name].get(tier, "")
        return DEFAULT_MODELS.get(name, {}).get(tier, "")

    @property
    def model(self) -> str:
        return self.model_for(self.tier)

    @property
    def strong_model(self) -> str:
        return self.model_for("strong")

    def with_tier(self, tier: str) -> "Enricher":
        """A copy that runs on the given tier (for "Retry with ...")."""
        clone = copy.copy(self)
        clone.tier = tier if tier in TIERS else "medium"
        if self.runner == self._run_cli:  # rebind: the bound method points at self
            clone.runner = clone._run_cli
        return clone

    @property
    def available(self) -> bool:
        return self.provider is not None

    @property
    def provider_name(self) -> str:
        return self.provider.name if self.provider else ""

    def unavailable_reason(self) -> str:
        if self.error:
            return self.error
        wanted = self.command or (self.requested if self.requested not in ("auto", "custom")
                                  else "")
        if wanted:
            return (f"{wanted!r} not found; install it or set enrich_provider / "
                    "enrich_command in config.toml")
        if self.requested == "custom":
            return "enrich_provider is custom but enrich_command is empty"
        return ("no AI CLI found (looked for " + ", ".join(AUTO_ORDER) + "); install "
                "one or set enrich_provider / enrich_command in config.toml")

    # --- transport

    def _run_cli(self, prompt: str, schema: dict, tools: str | None = None,
                 cwd: str | None = None, extra_path: str = "") -> dict:
        provider = self.provider
        if provider is None:
            raise EnrichError(self.unavailable_reason())
        provider = copy.copy(provider)
        provider.tools = tools
        with tempfile.TemporaryDirectory(prefix="crm-enrich-") as tmp:
            schema_path = str(Path(tmp) / "schema.json")
            out_path = str(Path(tmp) / "output.txt")
            Path(schema_path).write_text(json.dumps(schema), encoding="utf-8")
            argv = provider.build_argv(schema_path, self.model, out_path=out_path,
                                       prompt=prompt, schema=schema)
            try:
                proc = subprocess.run(argv, input=provider.stdin(prompt, schema),
                                      capture_output=True, text=True,
                                      timeout=self.timeout, cwd=cwd,
                                      env=_with_path(provider.env(os.environ), extra_path))
            except FileNotFoundError:
                raise EnrichError(f"{argv[0]!r} not found; set enrich_provider / "
                                  "enrich_command in config.toml")
            except subprocess.TimeoutExpired:
                raise EnrichError(f"enrichment timed out after {int(self.timeout)} s")
            if proc.returncode != 0:
                tail = ((proc.stderr or "").strip() or (proc.stdout or "").strip())
                try:  # a JSON envelope (claude -p) carries the readable message
                    envelope = json.loads(proc.stdout or "")
                    if isinstance(envelope, dict) and isinstance(envelope.get("result"), str):
                        tail = envelope["result"].strip() or tail
                except json.JSONDecodeError:
                    pass
                if self.model and UNSUPPORTED_MODEL.search(tail):
                    raise EnrichError(
                        f"{provider.name} has no model {self.model!r} on this account. "
                        "If you signed in with a subscription rather than an API key, "
                        "say so under Account in Settings \u2192 AI; otherwise set a "
                        "model id your account has.")
                raise EnrichError(f"{provider.name} ({self.model or 'default model'}) failed: "
                                  + " | ".join(error_lines(tail)))
            out = Path(out_path)
            out_text = out.read_text(encoding="utf-8") if out.exists() else ""
            data = provider.parse(proc.stdout or "", out_text)
        if not isinstance(data, dict):
            raise EnrichError("enrichment returned no JSON object")
        return data

    # --- proposals

    @staticmethod
    def _clean(data: dict, fields: dict[str, tuple[str, str]]) -> Proposal:
        proposal = Proposal()
        for key, (kind, _) in fields.items():
            value = data.get(key)
            if value in (None, "", []):
                continue
            if kind == "integer":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            else:
                value = " ".join(str(value).split())
                if key == "country":
                    value = normalise_country(value)
                    if value not in {c.value for c in Country}:
                        continue
            proposal.fields[key] = value
        sources = data.get("sources") or []
        proposal.sources = [str(s) for s in sources if s]
        proposal.notes = " ".join(str(data.get("notes") or "").split())
        return proposal

    @staticmethod
    def _empty(record, key: str, custom_keys: set) -> bool:
        """A built-in field reads off the object; a custom one out of `extra`."""
        if key in custom_keys:
            return (record.extra or {}).get(key) in ("", None)
        return getattr(record, key, None) in ("", None)

    def propose_company(self, company: Company, defs: list | None = None) -> Proposal:
        wanted = fields_with_custom(COMPANY_FIELDS, defs or [], "company")
        custom_keys = set(wanted) - set(COMPANY_FIELDS)
        missing = [k for k in wanted if self._empty(company, k, custom_keys)]
        if not missing:
            return Proposal(missing=[])
        data = self.runner(company_prompt(company, missing), _schema(
            {k: wanted[k] for k in missing}))
        proposal = self._clean(data, {k: wanted[k] for k in missing})
        proposal.missing = missing
        return proposal

    def propose_contact(self, company: Company, contact: Contact,
                        defs: list | None = None) -> Proposal:
        wanted = fields_with_custom(CONTACT_FIELDS, defs or [], "contact")
        custom_keys = set(wanted) - set(CONTACT_FIELDS)
        missing = [k for k in wanted if self._empty(contact, k, custom_keys)]
        if not missing:
            return Proposal(missing=[])
        data = self.runner(contact_prompt(company, contact, missing), _schema(
            {k: wanted[k] for k in missing}))
        proposal = self._clean(data, {k: wanted[k] for k in missing})
        proposal.missing = missing
        return proposal
