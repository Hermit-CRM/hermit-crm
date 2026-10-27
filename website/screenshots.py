#!/usr/bin/env python3
"""Take the website's screenshots from a fresh demo folder (dev only).

    python3 screenshots.py                       # every shot, from the release in [links].download
    python3 screenshots.py --only pipeline-board outreach-card
    python3 screenshots.py --source ../dist/hermitcrm-1.0.0.tar.gz
    python3 screenshots.py --source ~/Code/HermitCRM   # a checkout: what main looks like
    python3 screenshots.py --list

What it does, every time from nothing:

1. unpacks the version to show (a tarball, or a checkout's `src/`) into a temp
   folder; by default the release the site links to, because the site shows
   what people can download,
2. makes a new demo folder with `hermitcrm init --demo` (made-up companies on
   example.com and example.org, never your own data),
3. serves it on a spare port with `screenshots_app.py`, which swaps the AI CLI
   and the web for scripted answers (made-up words, the app's own pages),
4. takes each shot in `shots.toml` with Playwright at 2x, crops it, quantises it
   to 256 colours and writes it to `site/img/`, plus the overview's thumbnails
   in `site/img/thumbs/`.

Needs Playwright and Pillow for this Python (the same Playwright `build.py
--share` uses), and a Python with the app's own dependencies for the server
(`--python`; by default the repository's `.venv`). Nothing here is part of the
package or its downloads: `website/` is export-ignored.

`shots.toml` is the one list of screenshots. The build reads each shot's file,
alt text and address from it (`content.toml` and `features/*.toml` point at a
shot by its key); this script reads where to point the browser and how to crop.
"""

from __future__ import annotations

import argparse
import io
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE / "site"
IMG = SITE / "img"
LIMIT = 200_000          # bytes: the most one image should weigh
SCALE = 2
THUMB = (720, 480)       # the overview's pictures: the top of a page's first shot at 3:2


# ── The version to show and the folder to show it with ───────────────
def source_src(source: str | None, work: Path) -> Path:
    """The `src/` folder of the version to show."""
    if source is None:
        content = tomllib.loads((HERE / "content.toml").read_text(encoding="utf-8"))
        source = str(SITE / content["links"]["download"])
    path = Path(source).expanduser().resolve()
    if path.is_dir():
        if (path / "src" / "hermitcrm").is_dir():
            return path / "src"
        sys.exit(f"{path} has no src/hermitcrm: pass a checkout, an unpacked release or a .tar.gz")
    if not path.is_file():
        sys.exit(f"{path} does not exist. Pass --source with a release tarball or a checkout "
                 "(the site's own download is not in git: see README, Publishing a build).")
    with tarfile.open(path) as tar:
        tar.extractall(work / "release", filter="data")
    found = sorted((work / "release").glob("*/src/hermitcrm"))
    if not found:
        sys.exit(f"{path} has no src/hermitcrm inside")
    return found[0].parent


def app_python(given: str | None) -> str:
    """A Python that has the app's dependencies (fastapi, uvicorn, jinja2 ...)."""
    if given:
        return given
    here = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=HERE, capture_output=True,
                          text=True).stdout.strip()
    for root in (HERE.parent, (HERE / here).resolve().parent if here else HERE.parent):
        python = root / ".venv" / "bin" / "python"
        if python.exists():
            return str(python)
    return sys.executable


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_demo(python: str, src: Path, folder: Path) -> None:
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from hermitcrm.cli import main; "
            "sys.argv = ['hermitcrm', 'init', sys.argv[2], '--demo']; main()")
    subprocess.run([python, "-c", code, str(src), str(folder)], check=True, capture_output=True)


class Server:
    """The demo folder served by screenshots_app.py on a spare port."""

    def __init__(self, python: str, src: Path, folder: Path, *extra: str) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.folder = folder
        self.done: set[str] = set()      # what has been done in this folder (see "Getting the demo ...")
        args = [python, str(HERE / "screenshots_app.py"), str(src), str(folder), str(self.port), *extra]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            if self.proc.poll() is not None:
                sys.exit("the demo server stopped: " + self.proc.stderr.read().decode()[-1500:])
            try:
                urllib.request.urlopen(self.base + "/health", timeout=1)
                return
            except OSError:
                time.sleep(0.2)
        sys.exit("the demo server did not start")

    def stop(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=10)


# ── Getting the demo into the state a shot needs ─────────────────────
# Each step is idempotent: it looks at what this server's folder already holds,
# so one shot can be taken alone (`--only`) and the order of the shots does not
# matter. A shot with a `scene` gets a fresh copy of the demo and a server of
# its own (below), so what it changes never reaches the other shots.
CONTACTS = ["lindenhof-data/mara-keller", "kestrel-metrics/daan-visser", "tallpine-software/oliver-hart"]
NOTE = "Met Mara at a demo day in Leipzig; she asked how others hired their first seller."
QUESTION = "Which prospects have I not written to yet?"


def settle(pg) -> None:
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(250)


def open_app(pg, srv: Server) -> None:
    """The one-time disclaimer, and Home as the dashboard instead of the walkthrough."""
    if "open" in srv.done:
        return
    pg.goto(srv.base + "/")
    if pg.locator("input[name=accepted]").count():
        pg.check("input[name=accepted]")
        pg.click("button:has-text('Continue')")
        settle(pg)
    pg.goto(srv.base + "/")
    button = pg.locator("button:has-text('open this at startup')")
    if button.count():
        button.first.click()
        settle(pg)
    srv.done.add("open")


def generate(pg, srv: Server, contact: str, note: str = "") -> None:
    """Draft one contact through the Generate panel, as a person would."""
    if contact in srv.done:
        return
    pg.goto(f"{srv.base}/outreach?contact={contact}")
    settle(pg)
    if note:
        pg.fill("#gen-note", note)
    pg.click("#generate button:has-text('Generate')")
    # The page posts, builds and comes back to the card.
    pg.wait_for_function("() => !location.search.includes('contact=')", timeout=60000)
    settle(pg)
    srv.done.add(contact)


def mark_ready(pg, srv: Server) -> None:
    """Approve the last contact's card, so the Ready tab has one."""
    if "ready" in srv.done:
        return
    generate(pg, srv, CONTACTS[2])
    pg.goto(f"{srv.base}/outreach?tab=drafts")
    card = pg.locator(".outreach-card, article, li").filter(has_text="Oliver Hart").last
    card.get_by_role("button", name="Mark ready").first.click()
    settle(pg)
    srv.done.add("ready")


# What a shot's `prep` does instead of opening its `path`. Each gets (page, server).
def prep_batch_preview(pg, srv: Server) -> None:
    pg.goto(f"{srv.base}/outreach?preview=1&where=stage%3Dprospect&kind=first-touch&channel=email&limit=10&research=scrape")
    settle(pg)


def prep_generate_panel(pg, srv: Server) -> None:
    pg.goto(f"{srv.base}/outreach?contact={CONTACTS[0]}#generate")
    settle(pg)
    pg.fill("#gen-note", NOTE)


def prep_card(pg, srv: Server) -> None:
    generate(pg, srv, CONTACTS[0], NOTE)
    pg.goto(f"{srv.base}/outreach?tab=drafts")
    settle(pg)


def prep_ready(pg, srv: Server) -> None:
    mark_ready(pg, srv)
    pg.goto(f"{srv.base}/outreach?tab=ready")
    settle(pg)


def prep_ask(pg, srv: Server) -> None:
    """The Ask panel, with a question saved so the panel offers it as a button."""
    if "ask" not in srv.done:
        pg.goto(srv.base + "/pipeline")
        settle(pg)
        pg.click("text=Ask · Adjust")
        pg.fill("#ask-question", QUESTION)
        pg.click("#ask-form button:has-text('Save')")
        settle(pg)
        srv.done.add("ask")
    pg.goto(srv.base + "/pipeline")
    settle(pg)
    pg.click("text=Ask · Adjust")
    pg.wait_for_timeout(300)


PREPS = {"batch-preview": prep_batch_preview, "generate-panel": prep_generate_panel,
         "card": prep_card, "ready": prep_ready, "ask": prep_ask}


# A `scene` is a fresh copy of the demo, changed the way a person would change it,
# and a server of its own. It returns what to change before the server starts and
# the options to start it with.
def scene_field(folder: Path, python: str, src: Path) -> list[str]:
    """The `contract_renewal` date field from `hermitcrm help adjust-fields`, filled in."""
    with (folder / "fields.toml").open("a", encoding="utf-8") as f:
        f.write('\n[[field]]\nkey = "contract_renewal"\nlabel = "contract renewal"\ntype = "date"\n'
                'applies_to = "company"\nhelp = "when their current contract ends"\n'
                'show_in = ["detail", "companies"]\n')
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from hermitcrm.cli import main; "
            "sys.argv = ['hermitcrm', '--data', sys.argv[2], *sys.argv[3:]]; main()")
    subprocess.run([python, "-c", code, str(src), str(folder), "set", "companies", "--where",
                    "name=Northwind Robotics", "--set", "contract_renewal=2027-03-31", "--apply",
                    "--message", "ai: adjust: contract renewal for Northwind"], check=True, capture_output=True)
    return []


def scene_routine(folder: Path, python: str, src: Path) -> list[str]:
    return ["--routine", "nudge-quiet-threads"]


def scene_upgrade(folder: Path, python: str, src: Path) -> list[str]:
    """A newer release, made up, so the app shows its Upgrade button."""
    return ["--newer", "1.0.1"]


SCENES = {"field": scene_field, "routine": scene_routine, "upgrade": scene_upgrade}


# ── Taking a shot ────────────────────────────────────────────────────
def page_span(pg, selector: str) -> tuple[float, float]:
    """Top and bottom of an element, in page pixels."""
    return pg.evaluate("""sel => { const r = document.querySelector(sel).getBoundingClientRect();
                            return [r.top + scrollY, r.bottom + scrollY]; }""", selector)


def crop_box(pg, shot: dict, width: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) in device pixels."""
    top, height = shot.get("top", 0), shot.get("height", 800)
    if "from" in shot:
        top = max(0, page_span(pg, shot["from"])[0] - 16)
    if "until" in shot:
        height = page_span(pg, shot["until"])[1] + 16 - top
    left = shot.get("left", 0)
    return (round(left * SCALE), round(top * SCALE), round(width * SCALE), round((top + height) * SCALE))


def quantise(img, colours: int = 256):
    """256 colours, no dithering: flat user-interface colours stay crisp and small."""
    from PIL import Image
    return img.convert("RGB").quantize(colors=colours, method=Image.Quantize.MEDIANCUT,
                                       dither=Image.Dither.NONE)


def save(img, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    quantise(img).save(path, optimize=True)
    return path.stat().st_size


def tidy(pg, folder: Path) -> None:
    """Show the data folder as ~/crm, the usual place, instead of the temp folder the demo lives in."""
    pg.evaluate("""folders => {
        const swap = text => folders.reduce((t, f) => t.split(f).join('~/crm'), text);
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        for (let n; (n = walker.nextNode());) n.nodeValue = swap(n.nodeValue);
        document.querySelectorAll('input, textarea').forEach(e => { e.value = swap(e.value); });
    }""", [str(folder), str(folder.resolve())])


def shoot(pg, srv: Server, shot: dict) -> list[str]:
    from PIL import Image
    width = shot.get("width", 1200)
    # As tall as the crop, so the sidebar runs down the whole picture.
    pg.set_viewport_size({"width": width, "height": max(900, shot.get("top", 0) + shot.get("height", 1000))})
    open_app(pg, srv)
    prep = PREPS.get(shot.get("prep", ""))
    if prep:
        prep(pg, srv)
    else:
        pg.goto(srv.base + shot["path"])
        settle(pg)
    for selector in shot.get("click", []):
        pg.click(selector)
        settle(pg)
    tidy(pg, srv.folder)
    box = crop_box(pg, shot, width)
    png = pg.screenshot(full_page=True, animations="disabled", caret="hide")
    img = Image.open(io.BytesIO(png)).crop(box)
    out = IMG / shot["file"]
    size = save(img, out)
    notes = [f"{shot['file']}: {img.width}x{img.height}, {size // 1000} KB"
             + ("   <-- over the 200 KB the site allows" if size > LIMIT else "")]
    if shot.get("thumb"):
        # The top of the shot at 3:2: what the overview shows for the page.
        h = round(img.width * THUMB[1] / THUMB[0])
        thumb = img.crop((0, 0, img.width, min(h, img.height))).resize(THUMB, Image.LANCZOS)
        size = save(thumb, IMG / "thumbs" / f"{shot['thumb']}.png")
        notes.append(f"thumbs/{shot['thumb']}.png: {size // 1000} KB")
    return notes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", help="a release tarball, an unpacked release or a checkout "
                                     "(default: the download in content.toml [links])")
    ap.add_argument("--only", nargs="+", metavar="KEY", help="take only these shots")
    ap.add_argument("--python", help="a Python with the app's dependencies (default: the repo's .venv)")
    ap.add_argument("--keep", action="store_true", help="keep the temp folder and say where it is")
    ap.add_argument("--list", action="store_true", help="list the shots and stop")
    args = ap.parse_args()

    shots = tomllib.loads((HERE / "shots.toml").read_text(encoding="utf-8"))
    if args.list:
        for key, shot in shots.items():
            print(f"{key:28} {shot['file']:34} {shot.get('path') or shot.get('prep')}")
        return
    wanted = args.only or list(shots)
    unknown = [k for k in wanted if k not in shots]
    if unknown:
        sys.exit("no such shot: " + ", ".join(unknown) + " (see --list)")

    from playwright.sync_api import sync_playwright

    work = Path(tempfile.mkdtemp(prefix="hermit-shots-"))
    servers: dict[str, Server] = {}
    try:
        src, python = source_src(args.source, work), app_python(args.python)
        pristine = work / "pristine"
        make_demo(python, src, pristine)
        print(f"demo folder from {src.parent.name}, in {work}")

        def server_for(shot: dict) -> Server:
            scene = shot.get("scene", "")
            if scene not in servers:
                folder = work / (scene or "demo")
                shutil.copytree(pristine, folder)
                extra = SCENES[scene](folder, python, src) if scene else []
                servers[scene] = Server(python, src, folder, *extra)
            return servers[scene]

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 1200, "height": 900}, device_scale_factor=SCALE,
                                          color_scheme="light")
            pg = context.new_page()
            for key in wanted:
                print(key)
                for line in shoot(pg, server_for(shots[key]), shots[key]):
                    print("   ", line)
            browser.close()
    finally:
        for server in servers.values():
            server.stop()
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
