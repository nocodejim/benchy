"""Jinja2 rendering + the batch report (HTML, Markdown, CSV)."""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..util import read_json, utc_iso, write_json
from .aggregate import aggregate

TEMPLATES = Path(__file__).parent / "templates"

# Categorical slots (validated reference palette, light / dark). Contenders take
# slots in batch order; color follows the contender, never its rank.
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]


def fmt_num(v, digits=0):
    if v is None:
        return "—"
    if isinstance(v, float) and digits == 0 and abs(v) < 10 and v != int(v):
        digits = 1
    return f"{v:,.{digits}f}"


def fmt_k(v):
    if v is None:
        return "—"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(v) >= div:
            return f"{v / div:.1f}{suf}"
    return f"{v:.0f}"


def fmt_s(v):
    if v is None:
        return "—"
    v = float(v)
    if v < 60:
        return f"{v:.0f}s"
    if v < 3600:
        return f"{int(v // 60)}m {int(v % 60):02d}s"
    return f"{int(v // 3600)}h {int(v % 3600 // 60):02d}m"


def fmt_pct(v):
    return "—" if v is None else f"{v * 100:.0f}%"


def fmt_usd(v):
    if v is None:
        return "—"
    return f"${v:,.2f}" if v >= 1 else f"${v:,.3f}"


def env() -> Environment:
    e = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                    autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    e.filters.update(num=fmt_num, k=fmt_k, dur=fmt_s, pct=fmt_pct, usd=fmt_usd)
    return e


def render_template(name: str, **ctx) -> str:
    return env().get_template(name).render(**ctx, series=SERIES_LIGHT)


def load_runs(out: Path, batch: str | None) -> tuple[list[dict], dict | None]:
    runs, plan = [], None
    if batch == "latest":
        batches = sorted((out / "batches").glob("*.json"))
        batch = batches[-1].stem if batches else None
    if batch and batch != "all":
        plan = read_json(out / "batches" / f"{batch}.json")
    for mfile in sorted((out / "runs").glob("*/metrics.json")):
        m = read_json(mfile)
        if not m or (batch not in (None, "all") and m.get("batch") != batch):
            continue
        run = read_json(mfile.parent / "run.json") or {}
        m["_repeat"] = run.get("repeat")
        m["_title"] = run.get("task_title")
        m["_category"] = run.get("category")
        runs.append(m)
    return runs, plan


def bar_rows(agg, key, fmt, lower_is_better=False):
    """Rows for one single-measure horizontal bar chart."""
    vals = []
    for i, c in enumerate(agg["contenders"]):
        s = agg["stats"][c]
        v = s[key]["median"] if isinstance(s.get(key), dict) else s.get(key)
        vals.append((i, c, v))
    top = max((v for _, _, v in vals if v is not None), default=0) or 1
    return [{"slot": i % len(SERIES_LIGHT), "name": c, "value": v, "label": fmt(v),
             "frac": (v / top) if v is not None else 0} for i, c, v in vals]


def to_csv(runs: list[dict]) -> str:
    cols = ["run_id", "batch", "task", "contender", "harness", "harness_version", "model_requested",
            "models_reported", "effort", "_repeat", "outcome.resolved", "outcome.score",
            "outcome.exit_status", "outcome.regression_ok", "outcome.scope_violations",
            "outcome.secrets_found", "time.wall_s", "time.api_s", "activity.turns",
            "activity.tool_calls", "tokens.input_fresh", "tokens.cache_read", "tokens.cache_write",
            "tokens.output", "tokens.reasoning", "tokens.total", "cost.ai_credits",
            "cost.premium_requests", "cost.usd", "cost.usd_source", "diff.files_changed",
            "diff.added", "diff.deleted", "branch"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.replace("_repeat", "repeat") for c in cols])
    for r in runs:
        row = []
        for c in cols:
            v = r
            for k in c.split("."):
                v = v.get(k) if isinstance(v, dict) else None
            row.append(";".join(v) if isinstance(v, list) else ("" if v is None else v))
        w.writerow(row)
    return buf.getvalue()


def build_report(out: Path, batch: str = "latest", screenshot: bool = True) -> Path:
    runs, plan = load_runs(out, batch)
    if not runs:
        raise SystemExit(f"no finished runs found for batch '{batch}'")
    order = [c["name"] for c in (plan or {}).get("contenders", [])]
    agg = aggregate(runs, order)
    label = runs[0]["batch"] if batch not in ("all",) else "all"
    rdir = out / "report" / label
    rdir.mkdir(parents=True, exist_ok=True)
    ctx = {
        "agg": agg, "runs": sorted(runs, key=lambda r: (r["task"], r["contender"], r.get("_repeat") or 0)),
        "plan": plan, "batch": label, "generated": utc_iso(),
        "charts": [
            ("Resolve rate", "share of runs where every required check passed", "higher is better",
             bar_rows(agg, "resolve_rate", fmt_pct)),
            ("Cost per resolved task", "all spend (incl. failed attempts) ÷ tasks resolved", "lower is better",
             bar_rows(agg, "usd_per_resolved", fmt_usd, True)),
            ("Median wall time per run", "time from agent start to exit", "lower is better",
             bar_rows(agg, "wall_s", fmt_s, True)),
            ("Median tokens per run", "input (incl. cached) + output", "lower is better",
             bar_rows(agg, "tokens", fmt_k, True)),
        ],
        "series_light": SERIES_LIGHT, "series_dark": SERIES_DARK,
        "rel_runs": os.path.relpath(out / "runs", rdir),
    }
    e = env()
    (rdir / "index.html").write_text(e.get_template("report.html").render(**ctx))
    (rdir / "summary.md").write_text(e.get_template("summary.md.j2").render(**ctx))
    (rdir / "results.csv").write_text(to_csv(runs))
    write_json(rdir / "aggregate.json", {
        "batch": label, "generated": ctx["generated"], "contenders": agg["contenders"],
        "stats": agg["stats"],
        "matrix": [{"task": t, "contender": c, **v} for (t, c), v in agg["matrix"].items()]})
    (out / "report" / "latest.html").write_text(
        f'<!doctype html><meta http-equiv="refresh" content="0; url={label}/index.html">'
        f'<title>benchy report</title><a href="{label}/index.html">latest report</a>\n')
    if screenshot:
        from .screenshots import _browser
        pw, browser = _browser()
        try:
            page = browser.new_page(viewport={"width": 1760, "height": 900}, color_scheme="light")
            page.goto((rdir / "index.html").as_uri(), wait_until="load")
            # For the shareable PNG, let the scorecard grow instead of scrolling horizontally.
            page.add_style_tag(content="main{max-width:none} .scroll{overflow:visible}")
            page.locator("#headline").screenshot(path=str(rdir / "summary.png"))
        finally:
            browser.close()
            pw.stop()
    return rdir
