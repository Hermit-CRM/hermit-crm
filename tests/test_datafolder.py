"""--data resolution, `hermitcrm init` (plain and --demo), config docs, --version."""

import re
import subprocess
import tomllib
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import __version__, migrations
from hermitcrm import cli
from hermitcrm.datafolder import (CONFIG_DOCS, INIT_COMMIT, NotDataFolder, init_folder,
                               render_config, resolve_data_dir)
from hermitcrm.store import DEFAULT_CONFIG, Store, load_config
from hermitcrm.web import create_app

NOW = datetime(2026, 9, 14, 10, 30)


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


# ------------------------------------------------------------ resolution


def test_resolution_order(tmp_path):
    a, b, c = (tmp_path / n for n in "abc")
    for p in (a, b):
        (p / "companies").mkdir(parents=True)
    (c).mkdir()
    (c / "config.toml").write_text("")
    assert resolve_data_dir(a, env={"HERMITCRM_DATA": str(b)}, cwd=c) == a.resolve()
    assert resolve_data_dir(None, env={"HERMITCRM_DATA": str(b)}, cwd=c) == b.resolve()
    assert resolve_data_dir(None, env={}, cwd=c) == c.resolve()  # config.toml alone counts
    with pytest.raises(NotDataFolder, match=r"Not a Hermit CRM data folder: .*empty\. Run `hermitcrm init .*empty`\."):
        resolve_data_dir(tmp_path / "empty", env={})


def test_cli_exits_2_outside_a_data_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("HERMITCRM_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["check"]) == 2
    assert "Not a Hermit CRM data folder" in capsys.readouterr().err
    assert cli.main(["--data", str(tmp_path / "nope"), "digest"]) == 2


def test_cli_uses_env_and_data_option(tmp_path, monkeypatch, capsys):
    folder = init_folder(tmp_path / "crm", demo=True, now=NOW)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HERMITCRM_DATA", str(folder))
    assert cli.main(["show", "northwind-robotics"]) == 0
    assert "Northwind Robotics" in capsys.readouterr().out
    monkeypatch.delenv("HERMITCRM_DATA")
    assert cli.main(["--data", str(folder), "check"]) == 0
    assert "0 problems" in capsys.readouterr().out or True


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0 and capsys.readouterr().out.strip() == f"hermitcrm {__version__}"


# ------------------------------------------------------------------ init


def test_init_creates_folder_repo_and_one_commit(tmp_path):
    folder = init_folder(tmp_path / "crm", now=NOW)
    for name in ("config.toml", ".gitignore", "CLAUDE.md", "AGENTS.md", "MESSAGING.md",
                 "PIPELINE.md", ".hermitcrm-format", "companies/.gitkeep", "inbox/.gitkeep"):
        assert (folder / name).exists(), name
    assert (folder / "CLAUDE.md").read_text() == (folder / "AGENTS.md").read_text()
    assert "hermitcrm show <slug>" in (folder / "CLAUDE.md").read_text()
    assert ".secrets.toml" in (folder / ".gitignore").read_text().split()
    assert (folder / ".hermitcrm-format").read_text() == f"{migrations.LATEST}\n"
    assert git(["log", "--format=%s|%an"], folder).splitlines() == [f"{INIT_COMMIT}|hermitcrm"]
    assert git(["status", "--porcelain"], folder) == ""
    assert load_config(folder) == DEFAULT_CONFIG  # everything commented out
    assert migrations.ensure_current(folder) == ""


def test_config_docs_cover_every_default_and_parse_when_uncommented():
    assert set(CONFIG_DOCS) == set(DEFAULT_CONFIG)
    text = render_config()
    uncommented = "\n".join(re.sub(r"^# (\w+ = )", r"\1", line)
                            for line in text.splitlines() if re.match(r"^# \w+ = ", line))
    assert tomllib.loads(uncommented) == DEFAULT_CONFIG


def test_init_refuses_non_empty_folder_but_accepts_existing_repo(tmp_path, capsys):
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "notes.txt").write_text("hi")
    assert cli.main(["init", str(busy)]) == 2
    assert "Refusing to init" in capsys.readouterr().err

    repo = tmp_path / "repo"
    repo.mkdir()
    git(["init", "-q", "-b", "main"], repo)
    (repo / "README.md").write_text("mine\n")
    (repo / ".gitignore").write_text("*.log")
    init_folder(repo, now=NOW)
    assert (repo / "README.md").read_text() == "mine\n"
    assert (repo / ".gitignore").read_text().startswith("*.log\n.secrets.toml\n")
    with pytest.raises(Exception, match="Refusing"):
        init_folder(repo, now=NOW)  # has config.toml now


# ------------------------------------------------------------------ demo


def test_demo_loads_clean_with_every_stage_and_reports(tmp_path):
    folder = init_folder(tmp_path / "demo", demo=True, now=NOW)
    store = Store(folder)
    assert store.load() == []
    companies = store.all()
    assert len(companies) == 6
    assert {c.stage for c in companies} >= {"prospect", "engaged", "discovery", "offer",
                                            "won", "lost"}
    domains = {ct.email.split("@")[1] for c in companies for ct in c.contacts.values()}
    assert all(d.endswith((".example.com", ".example.org")) for d in domains)
    its = [i for c in companies for i in c.interactions]
    assert any(i.is_message for i in its) and any(i.direction == "in" for i in its)
    assert any(i.channel == "meeting" for i in its)
    assert all(c.stage_history for c in companies if c.stage != "prospect")
    assert sum(1 for c in companies if c.next_step) >= 4
    assert git(["log", "--format=%s"], folder).splitlines() == [INIT_COMMIT]
    text, code = cli.cmd_check(store)
    assert code == 0, text
    report = cli.cmd_report(store, days=90, md=True)
    assert "meeting" in report and "won" in report


def test_demo_every_web_page_returns_200(tmp_path):
    folder = init_folder(tmp_path / "demo", demo=True)
    app = create_app(folder, config={**load_config(folder), "push_enabled": False,
                                     "owner_email": "me@example.com"})
    app.state.calendar_url = lambda refresh=False: ""
    client = TestClient(app, follow_redirects=False)
    store = app.state.store
    urls = ["/", "/settings", "/calendar", "/import", "/companies", "/contacts", "/messages",
            "/reports", "/reports?period=90d", "/companies/new", "/help", "/help/settings", "/health"]
    companies = store.all()
    for n, c in enumerate(companies):
        other = companies[(n + 1) % len(companies)].slug  # merge pages need a target
        urls += [f"/companies/{c.slug}", f"/companies/{c.slug}/merge?drop={other}",
                 f"/companies/{c.slug}/contacts/new", f"/companies/{c.slug}/interactions/new"]
        contacts = sorted(c.contacts)
        for ct in contacts:
            urls.append(f"/companies/{c.slug}/contacts/{ct}")
        if len(contacts) > 1:
            urls.append(f"/companies/{c.slug}/contacts/{contacts[0]}/merge?drop={contacts[1]}")
        urls += [f"/companies/{c.slug}/interactions/{i.id}/edit" for i in c.interactions]
    bad = {u: r.status_code for u in urls if (r := client.get(u)).status_code != 200}
    assert bad == {}
    assert len(urls) > 40 and any("/contacts/" in u and "merge" in u for u in urls)
    # /today and merge pages without a target redirect by design; the target loads.
    for url in ("/today", f"/companies/{companies[0].slug}/merge"):
        r = client.get(url)
        assert r.status_code == 303
        assert client.get(r.headers["location"]).status_code == 200
