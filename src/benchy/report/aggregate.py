"""Aggregate per-run metrics into a per-contender comparison.

Design choices (see README "Reading the results"):
* medians with min-max, never means of a handful of runs
* cost per RESOLVED task = everything spent (failed attempts included) / tasks solved
* pass^k = share of tasks a contender solved in EVERY repeat (consistency)
* unknown (None) values are excluded from aggregates, never treated as 0
"""

from __future__ import annotations

import statistics
from collections import defaultdict


def _vals(runs, path):
    out = []
    for r in runs:
        v = r
        for k in path.split("."):
            v = v.get(k) if isinstance(v, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(v)
    return out


def spread(values):
    if not values:
        return {"median": None, "min": None, "max": None, "n": 0}
    return {"median": statistics.median(values), "min": min(values), "max": max(values), "n": len(values)}


def failure_mode(m: dict) -> str | None:
    o = m.get("outcome", {})
    if o.get("resolved"):
        return None
    if o.get("exit_status") == "timeout":
        return "timeout"
    if o.get("exit_status") in ("error", "not_run"):
        return "harness error"
    if o.get("secrets_found"):
        return "secret introduced"
    if o.get("regression_ok") is False:
        return "broke existing tests"
    if o.get("scope_violations"):
        return "out of scope"
    return "checks failed"


def contender_stats(runs: list[dict]) -> dict:
    n = len(runs)
    resolved = [r for r in runs if r["outcome"].get("resolved")]
    by_task = defaultdict(list)
    for r in runs:
        by_task[r["task"]].append(bool(r["outcome"].get("resolved")))
    usd = _vals(runs, "cost.usd")
    credits = _vals(runs, "cost.ai_credits")
    tokens = _vals(runs, "tokens.total")
    failures = defaultdict(int)
    for r in runs:
        if fm := failure_mode(r):
            failures[fm] += 1
    usd_complete = len(usd) == n
    return {
        "runs": n,
        "resolved": len(resolved),
        "resolve_rate": len(resolved) / n if n else None,
        "pass_all_k": (sum(all(v) for v in by_task.values()) / len(by_task)) if by_task else None,
        "tasks": len(by_task),
        "mean_score": statistics.fmean(_vals(runs, "outcome.score")) if runs else None,
        "usd_total": sum(usd) if usd else None,
        "usd_complete": usd_complete,
        "credits_total": sum(credits) if credits else None,
        "usd_per_resolved": (sum(usd) / len(resolved)) if usd and resolved else None,
        "credits_per_resolved": (sum(credits) / len(resolved)) if credits and resolved else None,
        "tokens_per_resolved": (sum(tokens) / len(resolved)) if tokens and resolved else None,
        "wall_s": spread(_vals(runs, "time.wall_s")),
        "api_s": spread(_vals(runs, "time.api_s")),
        "usd": spread(usd),
        "credits": spread(credits),
        "tokens": spread(tokens),
        "output_tokens": spread(_vals(runs, "tokens.output")),
        "cache_read": spread(_vals(runs, "tokens.cache_read")),
        "tool_calls": spread(_vals(runs, "activity.tool_calls")),
        "turns": spread(_vals(runs, "activity.turns")),
        "churn_resolved": spread(_vals(resolved, "diff.churn")),
        "failures": dict(sorted(failures.items(), key=lambda kv: -kv[1])),
        "models_reported": sorted({m for r in runs for m in r.get("models_reported") or []}),
        "harness_versions": sorted({r.get("harness_version") for r in runs if r.get("harness_version")}),
    }


def aggregate(runs: list[dict], contender_order: list[str] | None = None) -> dict:
    by_c = defaultdict(list)
    for r in runs:
        by_c[r["contender"]].append(r)
    order = [c for c in (contender_order or []) if c in by_c] + sorted(c for c in by_c if c not in (contender_order or []))
    tasks = sorted({r["task"] for r in runs})
    matrix = {}
    for t in tasks:
        for c in order:
            cell = [r for r in by_c[c] if r["task"] == t]
            if cell:
                matrix[(t, c)] = {
                    "runs": len(cell),
                    "resolved": sum(bool(r["outcome"].get("resolved")) for r in cell),
                    "credits": spread(_vals(cell, "cost.ai_credits")),
                    "usd": spread(_vals(cell, "cost.usd")),
                    "wall_s": spread(_vals(cell, "time.wall_s")),
                    "score": spread(_vals(cell, "outcome.score")),
                }
    return {
        "contenders": order,
        "stats": {c: contender_stats(by_c[c]) for c in order},
        "tasks": tasks,
        "matrix": matrix,
        "total_runs": len(runs),
    }
