"""After the agent exits: snapshot, diff, screenshot, grade, measure, branch.

Runs in the grader image with --network none. Produces, in out/runs/<id>/:
  diff.patch, numstat.tsv, diff.html, screenshots/*.png, grade.json, metrics.json
and pushes branch bench/<id> into out/repos/<repo>.git as
  <upstream sha> -> "benchy: task setup" -> "benchy: agent result"
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import config
from . import harness as harnesses
from .grade.engine import grade
from .metrics import pricing
from .metrics.schema import new
from .setup_ws import OUT, WORK
from .util import git, read_json, utc_iso, write_json


def snapshot(ws: Path, baseline: str) -> str:
    """Commit whatever the agent left in the working tree (it may have committed too)."""
    git("add", "-A", cwd=ws)
    git("commit", "--quiet", "--no-verify", "--allow-empty", "-m", "benchy: agent result", cwd=ws)
    return git("rev-parse", "HEAD", cwd=ws).strip()


def restore_venv(run: dict, ws: Path) -> None:
    """Grade against pristine dependencies, not a .venv the agent may have modified."""
    key = run.get("venv_cache_key")
    if not key:
        return
    cached = OUT / "cache" / "venvs" / f"{run['repo']['id']}-{key}" / ".venv"
    if cached.exists():
        shutil.rmtree(ws / ".venv", ignore_errors=True)
        shutil.copytree(cached, ws / ".venv", symlinks=True)


def diffstat(ws: Path, a: str, b: str) -> dict:
    files, added, deleted, rows = [], 0, 0, []
    for line in git("diff", "--numstat", "--no-renames", a, b, cwd=ws).splitlines():
        ad, de, path = line.split("\t", 2)
        files.append(path)
        rows.append(line)
        if ad != "-":
            added += int(ad)
            deleted += int(de)
    return {"files": files, "added": added, "deleted": deleted, "numstat": "\n".join(rows)}


def push_branch(run: dict, ws: Path, baseline: str, agent: str, summary: str) -> str:
    repo_id = run["repo"]["id"]
    bare = OUT / "repos" / f"{repo_id}.git"
    mirror = OUT / "cache" / "repos" / f"{repo_id}.git"
    if not bare.exists():
        bare.parent.mkdir(parents=True, exist_ok=True)
        git("init", "--quiet", "--bare", str(bare), cwd=bare.parent)
    upstream = run["repo"]["sha"]
    have = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(bare), "cat-file", "-e",
                           f"{upstream}^{{commit}}"], capture_output=True).returncode == 0
    if not have:
        git("fetch", "--quiet", "--no-tags",
            "--upload-pack=git -c uploadpack.allowAnySHA1InWant=true upload-pack",
            str(mirror), upstream, cwd=bare)
    tmp_ref = f"refs/benchy/tmp/{run['run_id']}"
    git("fetch", "--quiet", "--no-tags", str(ws), f"+{agent}:{tmp_ref}", cwd=bare)
    base_tree = git("rev-parse", f"{baseline}^{{tree}}", cwd=bare).strip()
    agent_tree = git("rev-parse", f"{agent}^{{tree}}", cwd=bare).strip()
    c = run["contender"]
    setup_msg = (f"benchy: task setup ({run['task']})\n\n"
                 f"Known starting state for run {run['run_id']}.\n"
                 f"Upstream: {run['repo']['url']} @ {upstream}\n")
    agent_msg = (f"benchy: agent result ({c['name']})\n\n{summary}\n\n"
                 f"Benchy-Run: {run['run_id']}\nBenchy-Harness: {c['harness']}\n"
                 f"Benchy-Model: {c.get('model')}\nBenchy-Effort: {c.get('effort')}\n")
    setup_commit = git("commit-tree", base_tree, "-p", upstream, "-m", setup_msg, cwd=bare).strip()
    agent_commit = git("commit-tree", agent_tree, "-p", setup_commit, "-m", agent_msg, cwd=bare).strip()
    branch = f"refs/heads/{run['branch']}"
    # Empty old-value: fail rather than ever overwrite an existing run branch.
    git("update-ref", branch, agent_commit, "", cwd=bare)
    git("update-ref", "-d", tmp_ref, cwd=bare)
    return agent_commit


def build_metrics(run: dict, agent: dict, parsed: dict, grade_res: dict, ds: dict, table: dict) -> dict:
    m = new()
    m.update({k: parsed[k] for k in ("tokens", "activity", "cost", "sources", "models_reported")
              if parsed.get(k)})
    m["time"].update({k: v for k, v in (parsed.get("time") or {}).items() if v is not None})
    m["warnings"] = list(agent.get("warnings", [])) + list(parsed.get("warnings", []))
    c = run["contender"]
    m.update({
        "run_id": run["run_id"], "batch": run["batch"], "task": run["task"],
        "contender": c["name"], "harness": c["harness"],
        "harness_version": agent.get("harness_version"),
        "model_requested": c.get("model"), "effort": c.get("effort"),
    })
    m["time"]["wall_s"] = agent.get("wall_s")
    m["outcome"].update({
        "resolved": grade_res["resolved"], "score": grade_res["score"],
        "checks_passed": grade_res["checks_passed"], "checks_total": grade_res["checks_total"],
        "regression_ok": grade_res["regression_ok"],
        "scope_violations": len(grade_res["scope_violations"]),
        "secrets_found": grade_res["secrets_found"],
        "exit_status": agent.get("exit_status", "not_run"),
    })
    m["diff"].update({"files_changed": len(ds["files"]), "added": ds["added"],
                      "deleted": ds["deleted"], "churn": ds["added"] + ds["deleted"]})
    if m["cost"].get("usd") is None and m["cost"].get("ai_credits") is not None:
        m["cost"]["usd"] = round(m["cost"]["ai_credits"] * float(table.get("credit_usd", 0.01)), 4)
        m["cost"]["usd_source"] = "credits"
    if m["cost"].get("usd") is None:
        model = (m["models_reported"] or [c.get("model")])[0]
        est = pricing.estimate_usd(m["tokens"], model, table)
        if est is not None:
            m["cost"]["usd"] = est
            m["cost"]["usd_source"] = "estimated-from-tokens"
    return m


def finalize(run_id: str, keep_workspace: bool = False, screenshots: bool = True) -> dict:
    run_dir = OUT / "runs" / run_id
    run = read_json(run_dir / "run.json")
    if not run:
        raise SystemExit(f"no run.json for {run_id}")
    agent = read_json(run_dir / "raw" / "agent.json", {"exit_status": "not_run", "warnings":
                                                      ["agent step produced no agent.json"]})
    task = config.load_task(run["task"])
    repo = config.load_repo(run["repo"]["id"])
    ws = WORK / "repo"
    baseline = run["baseline_commit"]

    agent_commit = snapshot(ws, baseline)
    restore_venv(run, ws)
    ds = diffstat(ws, baseline, agent_commit)
    patch = git("diff", "--no-color", "--no-renames", baseline, agent_commit, cwd=ws)
    (run_dir / "diff.patch").write_text(patch)
    (run_dir / "numstat.tsv").write_text(ds["numstat"] + "\n")

    grade_res = grade(task, repo, ws, baseline, agent_commit, ds["files"], run_dir / "aux")
    grade_res["graded_at"] = utc_iso()
    write_json(run_dir / "grade.json", grade_res)

    parsed = harnesses.get(run["contender"]["harness"]).parse(run_dir / "raw")
    metrics = build_metrics(run, agent, parsed, grade_res, ds, config.load_pricing())

    summary = (f"resolved={metrics['outcome']['resolved']} score={metrics['outcome']['score']} "
               f"files={len(ds['files'])} +{ds['added']} -{ds['deleted']} "
               f"wall={metrics['time']['wall_s']}s credits={metrics['cost']['ai_credits']} "
               f"usd={metrics['cost']['usd']} tokens={metrics['tokens']['total']}")
    metrics["branch"] = run["branch"]
    metrics["branch_commit"] = push_branch(run, ws, baseline, agent_commit, summary)
    write_json(run_dir / "metrics.json", metrics)

    if screenshots:
        from .report.screenshots import render_run
        _reset_to(ws, agent_commit)
        try:
            render_run(run_dir, ws, baseline, agent_commit, ds, run, metrics, grade_res)
        except Exception as e:  # a rendering failure must not lose the graded run
            metrics["warnings"].append(f"screenshots failed: {e!r}")
            write_json(run_dir / "metrics.json", metrics)

    if not keep_workspace:
        shutil.rmtree(ws, ignore_errors=True)
    print(f"[finalize] {run_id}: {summary}")
    return metrics


def _reset_to(ws: Path, commit: str) -> None:
    git("reset", "--quiet", "--hard", commit, cwd=ws)
    git("clean", "-q", "-ffdx", "-e", ".venv", cwd=ws)
