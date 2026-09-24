"""Render diffs and a run summary to PNG, fully headless and offline.

diff2html-cli turns `git diff` into a self-contained side-by-side HTML page
(line numbers on both sides, word-level highlights); Playwright's headless
Chromium screenshots each file block. No display, no network.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from ..util import git, slug
from .render import render_template

MAX_FILES = 40
MAX_HEIGHT = 12000     # px; taller diffs are clipped (full diff stays in diff.html)
VIEWPORT = {"width": 1600, "height": 900}
CHROMIUM_ARGS = ["--disable-dev-shm-usage", "--disable-gpu", "--no-first-run",
                 "--disable-extensions", "--disable-background-networking"]


def diff2html(patch_file: Path, out_html: Path, title: str) -> None:
    subprocess.run(
        ["diff2html", "-s", "side", "-f", "html", "-d", "word", "--su", "open", "--fct", "false",
         "--cs", "light", "--hc", "true", "-t", title, "-i", "file", "-F", str(out_html),
         "--", str(patch_file)],
        check=True, capture_output=True, text=True, timeout=120)


def _browser():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True, chromium_sandbox=False, args=CHROMIUM_ARGS)
    return pw, browser


def screenshot_page(page, html: Path, out_png: Path, selector: str | None = None) -> bool:
    page.goto(html.as_uri(), wait_until="load")
    target = page.locator(selector).first if selector else None
    if target is not None and target.count() == 0:
        return False
    if target is not None:
        box = target.bounding_box()
        if box and box["height"] > MAX_HEIGHT:
            page.screenshot(path=str(out_png), clip={"x": box["x"], "y": box["y"],
                                                     "width": box["width"], "height": MAX_HEIGHT},
                            full_page=True)
        else:
            target.screenshot(path=str(out_png))
    else:
        page.screenshot(path=str(out_png), full_page=True)
    return True


def render_run(run_dir: Path, ws: Path, baseline: str, agent: str, ds: dict,
               run: dict, metrics: dict, grade_res: dict) -> list[Path]:
    shots = run_dir / "screenshots"
    shots.mkdir(exist_ok=True)
    made: list[Path] = []
    title = f"{run['task']} — {run['contender']['name']} (r{run['repeat']})"

    card = run_dir / "summary.html"
    card.write_text(render_template("run_card.html", run=run, m=metrics, grade=grade_res, ds=ds))

    has_diff = (run_dir / "diff.patch").stat().st_size > 0
    if has_diff:
        diff2html(run_dir / "diff.patch", run_dir / "diff.html", title)

    pw, browser = _browser()
    try:
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        png = shots / "00-summary.png"
        screenshot_page(page, card, png, ".card")
        made.append(png)
        with tempfile.TemporaryDirectory() as tmp:
            for i, path in enumerate(ds["files"][:MAX_FILES], start=1):
                patch = Path(tmp) / f"{i}.patch"
                patch.write_text(git("diff", "--no-color", "--no-renames", baseline, agent, "--", path, cwd=ws))
                if not patch.read_text().strip():
                    continue
                html = Path(tmp) / f"{i}.html"
                diff2html(patch, html, path)
                png = shots / f"{i:02d}-{slug(path, 80)}.png"
                if screenshot_page(page, html, png, ".d2h-file-wrapper"):
                    made.append(png)
    finally:
        browser.close()
        pw.stop()
    return made
