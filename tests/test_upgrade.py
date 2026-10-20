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

"""One-click upgrade (upgrade.py, the /upgrade routes, the gate, the stale page).

Nothing here installs anything or restarts a process: the installer runs through a
fake, and the restart is a recorded call. What is checked is the decisions: when a
click may run, that a failed install or a release that does not start never reaches
the restart, that pages are held back while files are being replaced, and that the
page that explains a stale server does not need a template.
"""

import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermitcrm import __version__, updates, upgrade
from hermitcrm.web import create_app

NEWER = "99.0.0"
JSON = {"accept": "application/json"}


# ---------------------------------------------------------------- helpers


class Runner:
    """Stands in for subprocess.run: answers from a queue, remembers what it was asked."""

    def __init__(self, *answers):
        self.calls, self.answers = [], list(answers)

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        code, out, err = answer
        return subprocess.CompletedProcess(argv, code, out, err)


OK = (0, "", "")
NEW_VERSION = (0, f"hermitcrm {NEWER}\n", "")


def finish(thread):
    assert thread is not None
    thread.join(5)
    assert not thread.is_alive()


def plan(*argv):
    return upgrade.Plan(tuple(argv or ("installer", "go")))


@pytest.fixture
def app(tmp_path):
    (tmp_path / "companies").mkdir()
    app = create_app(tmp_path, config={"push_enabled": False, "update_check": True})
    app.state.setup_redirected = True
    return app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------- may a click run here?


def test_blocked_names_the_reason_or_says_nothing():
    assert upgrade.blocked({}, True, platform="darwin") == ""
    assert "Windows" in upgrade.blocked({}, True, platform="win32")
    assert "hermitcrm serve" in upgrade.blocked({}, False, platform="darwin")
    for host in ("0.0.0.0", "::", "crm.local"):
        assert "no password" in upgrade.blocked({"host": host}, True, platform="darwin")
    for host in ("127.0.0.1", "localhost", "::1", ""):
        assert upgrade.blocked({"host": host}, True, platform="darwin") == ""


def test_the_plan_runs_the_tool_that_installed_hermit_by_its_full_path(tmp_path):
    uv, pipx, venv = tmp_path / "uv", tmp_path / "pipx", tmp_path / "venv"
    for env in (uv, pipx, venv):
        env.mkdir()
    (uv / "uv-receipt.toml").write_text("", encoding="utf-8")
    (pipx / "pipx_metadata.json").write_text("{}", encoding="utf-8")
    found = {"uv": "/opt/bin/uv", "pipx": "/opt/bin/pipx"}.get

    def which(name, path=None):
        return found(name)

    run = upgrade.install_plan({}, True, prefix=uv, platform="darwin", which=which)
    assert run.argv == ("/opt/bin/uv", "tool", "install", "hermitcrm@latest")
    run = upgrade.install_plan({}, True, prefix=pipx, platform="darwin", which=which)
    assert run.argv == ("/opt/bin/pipx", "install", "--force", "hermitcrm")
    run = upgrade.install_plan({}, True, prefix=venv, platform="darwin", which=which,
                               in_venv=True)
    assert run.argv == (sys.executable, "-m", "pip", "install", "--upgrade", "hermitcrm")


def test_the_plan_says_why_not_instead_of_guessing(tmp_path):
    (tmp_path / "uv-receipt.toml").write_text("", encoding="utf-8")
    missing = upgrade.install_plan({}, True, prefix=tmp_path, platform="darwin",
                                   which=lambda name, path=None: None)
    assert not missing.ok and "`uv` was not found" in missing.why_not
    assert "uv tool install hermitcrm@latest" in missing.why_not

    # Never rewrite the system Python from a web page.
    system = upgrade.install_plan({}, True, prefix=tmp_path / "none", platform="darwin",
                                  in_venv=False)
    assert not system.ok and "system Python" in system.why_not

    # The command installs from PyPI; another source is the user's to download from.
    elsewhere = upgrade.install_plan({"update_url": "https://downloads.example.com/v.json"},
                                     True, platform="darwin", in_venv=True)
    assert not elsewhere.ok and "downloads.example.com" in elsewhere.why_not

    exposed = upgrade.install_plan({"host": "0.0.0.0"}, True, platform="darwin", in_venv=True)
    assert not exposed.ok and "no password" in exposed.why_not


def test_a_launchd_job_finds_uv_in_the_usual_places():
    path = upgrade.search_path({"PATH": "/usr/bin:/bin"})
    assert path.startswith("/usr/bin:/bin")
    assert str(Path("~/.local/bin").expanduser()) in path and "/opt/homebrew/bin" in path
    assert upgrade.search_path({"PATH": "/usr/local/bin"}).count("/usr/local/bin") == 1


def test_the_restart_re_executes_this_exact_command_line():
    argv = upgrade.restart_argv(["python", "/tools/bin/hermitcrm", "--data", "/d", "serve"],
                                executable="/tools/bin/python")
    assert argv == ["/tools/bin/python", "/tools/bin/hermitcrm", "--data", "/d", "serve"]
    seen = []
    upgrade.exec_restart(execv=lambda path, args: seen.append((path, args)), argv=argv)
    assert seen == [("/tools/bin/python", argv)]
    assert upgrade.restart_argv()[0] == sys.executable


def test_the_way_back_pins_the_running_version(tmp_path):
    (tmp_path / "uv-receipt.toml").write_text("", encoding="utf-8")
    assert upgrade.previous_version_command("0.8.0", tmp_path) == \
        "uv tool install hermitcrm==0.8.0"


# ---------------------------------------------------------------- the upgrade itself


def test_install_then_verify_then_restart(tmp_path):
    runner, restarted = Runner(OK, NEW_VERSION), []
    up = upgrade.Upgrader(run=runner, version="0.8.0", python="/venv/bin/python")
    finish(up.start(plan("/bin/uv", "tool", "install", "hermitcrm@latest"),
                    lambda: restarted.append(1) or True, target=NEWER))
    assert up.state == upgrade.RESTARTING and up.target == NEWER and restarted == [1]
    install, verify = runner.calls
    assert install[0] == ["/bin/uv", "tool", "install", "hermitcrm@latest"]
    # The new files are asked in isolated mode, from a neutral folder, with no shell.
    assert verify[0] == ["/venv/bin/python", "-I", "-m", "hermitcrm.cli", "--version"]
    for _, kw in runner.calls:
        assert kw["cwd"] == tempfile.gettempdir() and kw["stdin"] == subprocess.DEVNULL
        assert not kw.get("shell") and ".local/bin" in kw["env"]["PATH"]


def test_a_failed_install_stops_before_anything_is_replaced_or_restarted():
    runner, restarted = Runner((2, "", "No solution found for hermitcrm")), []
    up = upgrade.Upgrader(run=runner, version="0.8.0")
    finish(up.start(plan(), lambda: restarted.append(1) or True))
    assert up.state == upgrade.FAILED and restarted == [] and len(runner.calls) == 1
    assert "No solution found" in up.error and "still running v0.8.0" in up.error


def test_a_release_that_does_not_start_is_never_restarted_into():
    """launchd's KeepAlive would restart a server that dies on start, for ever."""
    runner, restarted = Runner(OK, (1, "", "ImportError: no module named x")), []
    up = upgrade.Upgrader(run=runner, version="0.8.0", prefix=None)
    finish(up.start(plan(), lambda: restarted.append(1) or True))
    assert up.state == upgrade.FAILED and restarted == []
    assert "does not start" in up.error and "ImportError" in up.error
    assert f"hermitcrm==0.8.0" in up.error  # the way back is in the message


def test_the_version_is_read_from_the_version_line_not_from_other_output():
    noisy = (0, "Python 3.13.1 warning: x\nhermitcrm 99.0.0\n", "")
    up = upgrade.Upgrader(run=Runner(noisy), version="0.8.0")
    finish(up.start(None, lambda: True))
    assert up.state == upgrade.RESTARTING and up.target == "99.0.0"


def test_an_install_that_changed_nothing_is_not_called_a_success():
    runner, restarted = Runner(OK, (0, "hermitcrm 0.8.0\n", "")), []
    up = upgrade.Upgrader(run=runner, version="0.8.0")
    finish(up.start(plan(), lambda: restarted.append(1) or True))
    assert up.state == upgrade.FAILED and restarted == []
    assert "not newer" in up.error and "Nothing was restarted" in up.error


@pytest.mark.parametrize("trouble, said", [
    (subprocess.TimeoutExpired("uv", 600), "did not finish"),
    (FileNotFoundError("no such file: uv"), "Could not run the installer"),
])
def test_an_installer_that_hangs_or_vanishes_says_so(trouble, said):
    up = upgrade.Upgrader(run=Runner(trouble), version="0.8.0")
    finish(up.start(plan(), lambda: True))
    assert up.state == upgrade.FAILED and said in up.error


def test_a_server_that_cannot_restart_says_so_rather_than_claiming_it_did():
    up = upgrade.Upgrader(run=Runner(OK, NEW_VERSION), version="0.8.0")
    finish(up.start(plan(), lambda: False))
    assert up.state == upgrade.FAILED and "cannot restart itself" in up.error


def test_restart_only_checks_the_files_then_restarts():
    runner, restarted = Runner(NEW_VERSION), []
    up = upgrade.Upgrader(run=runner, version="0.8.0")
    finish(up.start(None, lambda: restarted.append(1) or True))
    assert len(runner.calls) == 1 and "--version" in runner.calls[0][0]
    assert restarted == [1] and up.state == upgrade.RESTARTING


def test_a_second_click_while_one_is_running_does_nothing():
    gate = threading.Event()

    def slow(argv, **kw):
        gate.wait(5)
        return subprocess.CompletedProcess(argv, 0, "hermitcrm 99.0.0", "")

    up = upgrade.Upgrader(run=slow, version="0.8.0")
    first = up.start(plan(), lambda: True)
    assert up.busy and up.status()["detail"] and up.start(plan(), lambda: True) is None
    gate.set()
    finish(first)


def test_the_status_carries_what_a_tab_needs_to_tell_servers_apart():
    one, two = upgrade.Upgrader(), upgrade.Upgrader()
    assert one.boot != two.boot and one.status()["version"] == __version__
    assert set(one.status()) == {"boot", "version", "state", "target", "detail", "error"}


# ---------------------------------------------------------------- the web routes


def test_nothing_is_started_without_the_token_or_without_a_newer_version(app, client):
    app.state.restart_server = lambda: True
    assert client.post("/upgrade", data={}, headers=JSON).status_code == 403
    refused = client.post("/upgrade", data={"csrf_token": app.state.csrf_token}, headers=JSON)
    assert refused.status_code == 409 and "no newer version" in refused.json()["error"]
    assert app.state.upgrader.state == upgrade.IDLE


def test_a_click_runs_the_upgrade_and_reports_progress(app, client, monkeypatch):
    restarted = []
    runner = Runner(OK, NEW_VERSION)
    app.state.upgrader = upgrade.Upgrader(run=runner, version=__version__)
    app.state.restart_server = lambda: restarted.append(1) or True
    app.state.update_notice.available = NEWER
    monkeypatch.setattr("hermitcrm.web.upgrading.install_plan",
                        lambda config, can: plan("/bin/uv", "tool", "install", "hermitcrm@latest"))

    started = client.post("/upgrade", data={"csrf_token": app.state.csrf_token}, headers=JSON)
    assert started.status_code == 202 and started.json()["boot"] == app.state.upgrader.boot
    deadline = threading.Event()
    for _ in range(100):
        if restarted:
            break
        deadline.wait(0.05)
    assert restarted == [1]
    status = client.get("/upgrade/status").json()
    assert status["state"] == upgrade.RESTARTING and status["target"] == NEWER
    assert runner.calls[0][0] == ["/bin/uv", "tool", "install", "hermitcrm@latest"]


def test_without_javascript_the_form_lands_on_a_plain_status_page(app, client, monkeypatch):
    app.state.restart_server = lambda: True
    app.state.update_notice.available = NEWER
    monkeypatch.setattr("hermitcrm.web.upgrading.install_plan", lambda config, can: plan())
    app.state.upgrader = upgrade.Upgrader(run=Runner(OK, (1, "", "boom")), version=__version__)
    sent = client.post("/upgrade", data={"csrf_token": app.state.csrf_token},
                       follow_redirects=False)
    assert sent.status_code in (302, 303) and sent.headers["location"] == "/upgrade"
    for _ in range(100):
        if app.state.upgrader.state == upgrade.FAILED:
            break
        threading.Event().wait(0.05)
    page = client.get("/upgrade")
    assert page.status_code == 200 and "did not finish" in page.text and "boom" in page.text


def test_where_the_click_cannot_run_the_reason_comes_back_not_a_crash(app, client):
    app.state.update_notice.available = NEWER      # no restart hook: not under `serve`
    refused = client.post("/upgrade", data={"csrf_token": app.state.csrf_token}, headers=JSON)
    assert refused.status_code == 409 and "hermitcrm serve" in refused.json()["error"]
    page = client.get("/upgrade").text
    assert "is available" in page and updates.upgrade_command() in page
    assert "<form" not in page


def test_the_nav_offers_the_button_only_where_it_can_work(app, client):
    app.state.update_notice.available = NEWER
    page = client.get("/companies").text
    assert f"v{NEWER} available: <code>" in page and "data-upgrade" not in page
    app.state.restart_server = lambda: True
    page = client.get("/companies").text
    assert f"Upgrade to v{NEWER}" in page and 'action="/upgrade"' in page
    assert f'name="csrf_token" value="{app.state.csrf_token}"' in page
    assert "/static/upgrade.js" in page and f'data-boot="{app.state.upgrader.boot}"' in page
    assert f"Upgrade to v{NEWER}" in client.get("/settings").text
    app.state.config["host"] = "0.0.0.0"           # on a network: the command, never the button
    page = client.get("/companies").text
    assert "data-upgrade" not in page and "no password" in page


# ---------------------------------------------------------------- while files are replaced


def test_pages_are_held_back_while_the_files_change(app, client):
    app.state.upgrader.state = upgrade.INSTALLING
    held = client.get("/companies")
    assert held.status_code == 503 and "upgrading" in held.text
    assert 'http-equiv="refresh"' in held.text and held.headers["retry-after"] == "2"
    assert "Content-Security-Policy" in held.headers
    assert client.post("/reload").status_code == 503
    # What the panel and the plain page need stays open.
    assert client.get("/upgrade/status").status_code == 200
    assert client.get("/upgrade").status_code == 200
    assert client.get("/static/upgrade.js").status_code == 200
    app.state.upgrader.state = upgrade.FAILED       # a failure is not "busy": pages return
    assert client.get("/companies").status_code == 200


# ---------------------------------------------------------------- files newer than the server


def stale(app, on_disk=NEWER):
    app.state.disk_watch = updates.DiskWatch(read=lambda: on_disk)


def test_a_server_older_than_its_files_says_so_and_offers_a_restart(app, client):
    stale(app)
    app.state.restart_server = lambda: True
    page = client.get("/companies").text
    assert "Restart needed" in page and f"v{NEWER} is installed" in page
    assert 'action="/upgrade/restart"' in page
    status = client.get("/upgrade/status").json()
    assert status["stale"] == NEWER
    assert f"v{NEWER} is installed" in client.get("/settings").text


def test_a_broken_page_on_a_stale_server_explains_itself_without_a_template(app, client):
    @app.get("/boom")
    def boom():
        raise RuntimeError("a template wanted playbook_status")

    plain = client.get("/boom")
    assert plain.status_code == 500 and plain.text == "Internal Server Error"

    stale(app)
    app.state.restart_server = lambda: True
    fixed = client.get("/boom")
    assert fixed.status_code == 500
    assert f"upgraded to v{NEWER} while this server was still running v{__version__}" in fixed.text
    assert 'action="/upgrade/restart"' in fixed.text and app.state.csrf_token in fixed.text
    assert "Content-Security-Policy" in fixed.headers and "sidebar" not in fixed.text

    app.state.restart_server = None                 # cannot restart itself: no button, a reason
    assert "<form" not in client.get("/boom").text


def test_restart_runs_the_check_then_restarts(app, client):
    stale(app)
    restarted = []
    runner = Runner(NEW_VERSION)
    app.state.upgrader = upgrade.Upgrader(run=runner, version=__version__)
    app.state.restart_server = lambda: restarted.append(1) or True
    assert client.post("/upgrade/restart", data={}, headers=JSON).status_code == 403
    sent = client.post("/upgrade/restart", data={"csrf_token": app.state.csrf_token},
                       headers=JSON)
    assert sent.status_code == 202
    for _ in range(100):
        if restarted:
            break
        threading.Event().wait(0.05)
    assert restarted == [1] and "--version" in runner.calls[0][0]


def test_restart_is_refused_where_the_server_cannot_do_it(app, client):
    refused = client.post("/upgrade/restart", data={"csrf_token": app.state.csrf_token},
                          headers=JSON)
    assert refused.status_code == 409 and "hermitcrm serve" in refused.json()["error"]


# ---------------------------------------------------------------- detecting


def dist_info(root: Path, name: str, version: str, folder: str = None):
    info = root / (folder or f"{name}-{version}.dist-info")
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n"
                                   f"Version: not-this-one\n", encoding="utf-8")


def test_installed_version_reads_the_newest_hermit_on_the_path(tmp_path):
    old, new, other = tmp_path / "old", tmp_path / "new", tmp_path / "other"
    dist_info(old, "hermitcrm", "0.8.0")
    dist_info(new, "hermitcrm", "0.10.0")
    dist_info(other, "hermitcrm-extra", "7.0.0")      # a different package that matches the glob
    assert updates.installed_version([str(old), str(new)]) == "0.10.0"
    assert updates.installed_version([str(other)]) == ""
    assert updates.installed_version(["", str(tmp_path / "missing")]) == ""
    assert updates.installed_version([str(old)]) == "0.8.0"


def test_the_disk_watch_is_memoised_and_only_cares_about_newer():
    reads, now = [], [0.0]

    def read():
        reads.append(1)
        return "0.9.0"

    watch = updates.DiskWatch(running="0.8.0", read=read, ttl=5, clock=lambda: now[0])
    assert watch.newer() == "0.9.0" and watch.newer() == "0.9.0" and len(reads) == 1
    now[0] = 6.0
    assert watch.newer() == "0.9.0" and len(reads) == 2
    assert updates.DiskWatch(running="0.9.0", read=read).newer() == ""   # same: not stale
    assert updates.DiskWatch(running="1.0.0", read=read).newer() == ""   # older: a dev tree
    assert updates.DiskWatch(running="0.8.0", read=lambda: 1 / 0).newer() == ""


def test_this_checkout_is_not_reported_stale_by_its_own_install():
    assert updates.DiskWatch().newer() == ""


def test_a_long_running_server_asks_again_but_only_when_an_hour_has_passed(tmp_path):
    """`start` runs once at boot; a server up for weeks would never hear of a release."""
    calls = []

    def fetch():
        calls.append(1)
        return NEWER

    cache = tmp_path / "u.json"
    notice = updates.UpdateNotice()
    assert notice.tick({}, now=0.0) is None            # never started: tests stay offline
    first = notice.start({}, fetcher=fetch, cache=cache)
    first.join(5)
    assert notice.available == NEWER and len(calls) == 1
    started = notice._last
    assert notice.tick({}, now=started + 60) is None
    again = notice.tick({}, now=started + updates.RETRY_INTERVAL + 1)
    assert again is not None
    again.join(5)
    assert len(calls) == 1                              # the cache still held: no new request
    assert notice.tick({"update_check": False}, now=started + 10 * updates.INTERVAL) is None


# ---------------------------------------------------------------- the serve loop


def test_serve_stops_gracefully_then_re_executes(tmp_path, monkeypatch):
    from hermitcrm import cli
    from test_cli import stub_app, stub_uvicorn

    seen, execs = {}, []
    app = stub_app()
    monkeypatch.setattr(cli, "load_config", lambda root: {"port": 8765, "host": "127.0.0.1"})
    monkeypatch.setattr("hermitcrm.web.create_app", lambda root, config: app)
    monkeypatch.setattr(upgrade, "exec_restart", lambda: execs.append(1))

    def while_serving(server):
        seen["server"] = server
        assert app.state.restart_server() is True       # what the upgrade thread calls

    monkeypatch.setitem(sys.modules, "uvicorn", stub_uvicorn({}, on_run=while_serving))
    cli.cmd_serve(tmp_path)
    assert seen["server"].should_exit is True
    assert seen["server"].config.timeout_graceful_shutdown == upgrade.GRACE_SECONDS
    assert execs == [1]


def test_serve_without_a_restart_request_just_returns(tmp_path, monkeypatch):
    from hermitcrm import cli
    from test_cli import stub_app, stub_uvicorn

    execs = []
    monkeypatch.setattr(cli, "load_config", lambda root: {"port": 8765, "host": "127.0.0.1"})
    monkeypatch.setattr("hermitcrm.web.create_app", lambda root, config: stub_app())
    monkeypatch.setattr(upgrade, "exec_restart", lambda: execs.append(1))
    monkeypatch.setitem(sys.modules, "uvicorn", stub_uvicorn({}))
    cli.cmd_serve(tmp_path)
    assert execs == []


def test_a_restart_that_cannot_exec_exits_so_a_supervisor_starts_it_again(tmp_path, monkeypatch,
                                                                         capsys):
    from hermitcrm import cli
    from test_cli import stub_app, stub_uvicorn

    app = stub_app()
    monkeypatch.setattr(cli, "load_config", lambda root: {"port": 8765, "host": "127.0.0.1"})
    monkeypatch.setattr("hermitcrm.web.create_app", lambda root, config: app)

    def cannot(*a, **kw):
        raise OSError("no such interpreter")

    monkeypatch.setattr(upgrade, "exec_restart", cannot)
    monkeypatch.setitem(sys.modules, "uvicorn",
                        stub_uvicorn({}, on_run=lambda server: app.state.restart_server()))
    with pytest.raises(SystemExit) as stopped:
        cli.cmd_serve(tmp_path)
    assert stopped.value.code == 1 and "could not restart itself" in capsys.readouterr().err


# ---------------------------------------------------------------- the browser half


def test_the_script_never_writes_markup_from_the_server():
    js = (Path(upgrade.__file__).parent / "static" / "upgrade.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "eval(" not in js
    assert "/upgrade/status" in js and "location.reload" in js
