"""Assertions for `./bench selftest` (mock + noop harnesses, zero AI cost).

Proves, for every task in the batch:
  * the starting state FAILS its checks (noop harness)          -> task isn't pre-solved
  * the golden solution PASSES every check (mock harness)       -> task is solvable
and, for the pipeline:
  * every run got its own branch: upstream -> task setup -> agent result
  * screenshots are real PNGs; the report was built
  * nothing credential-shaped leaked into out/
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .redact import contains_secret
from .setup_ws import OUT
from .util import read_json

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _git(bare: Path, *args) -> str:
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(bare), *args],
                          capture_output=True, text=True).stdout.strip()


def verify_probe(batch: str) -> list[str]:
    """The agent sandbox, as seen from inside it."""
    fails = []
    plan = read_json(OUT / "batches" / f"{batch}.json") or {"runs": []}
    for r in plan["runs"]:
        p = read_json(OUT / "runs" / r["run_id"] / "raw" / "probe.json")
        if not p:
            fails.append(f"probe {r['run_id']}: no probe.json")
            continue
        if p["uid"] == 0:
            fails.append("agent runs as root")
        if int(p["cap_eff"], 16) != 0:
            fails.append(f"agent has capabilities (CapEff={p['cap_eff']})")
        if p["rootfs_writable"]:
            fails.append("agent root filesystem is writable")
        if p["hidden_files_visible"]:
            fails.append(f"agent can see grader files: {p['hidden_files_visible']}")
        if p["token_env"]:
            fails.append(f"credential env vars leaked into agent: {p['token_env']}")
        if p["git_commits"] != 1:
            fails.append(f"agent sees {p['git_commits']} commits; expected only the baseline")
        if p["work_entries"] != ["repo"]:
            fails.append(f"agent sees other entries in /work: {p['work_entries']}")
        if p["auth_mounted"]:
            fails.append("auth volume mounted for a harness that needs no login")
    return fails


def verify(batch: str, probe_batch: str | None = None) -> int:
    plan = read_json(OUT / "batches" / f"{batch}.json")
    if not plan:
        print(f"[selftest] no batch {batch}")
        return 1
    fails: list[str] = verify_probe(probe_batch) if probe_batch else []
    commits = set()
    for r in plan["runs"]:
        rid, harness = r["run_id"], r["contender"]["harness"]
        rdir = OUT / "runs" / rid
        m = read_json(rdir / "metrics.json")
        run = read_json(rdir / "run.json")
        if not m or not run:
            fails.append(f"{rid}: missing metrics.json/run.json")
            continue
        o = m["outcome"]
        if harness == "mock" and not (o["resolved"] and o["score"] == 1.0):
            g = read_json(rdir / "grade.json") or {}
            bad = [c["id"] for c in g.get("checks", []) if not c["passed"]]
            fails.append(f"{rid}: golden solution did not pass (failed: {bad})")
        if harness == "noop" and o["resolved"]:
            fails.append(f"{rid}: starting state already passes - task is not a real test")
        bare = OUT / "repos" / f"{run['repo']['id']}.git"
        head = _git(bare, "rev-parse", "--verify", f"refs/heads/{run['branch']}")
        if not head:
            fails.append(f"{rid}: branch {run['branch']} missing")
        else:
            commits.add(head)
            parent2 = _git(bare, "rev-parse", f"{head}~2")
            if parent2 != run["repo"]["sha"]:
                fails.append(f"{rid}: branch is not rooted at the pinned upstream commit")
        if harness == "mock":
            shots = sorted((rdir / "screenshots").glob("*.png"))
            if len(shots) < 2:
                fails.append(f"{rid}: expected summary + per-file screenshots, got {len(shots)}")
            for s in shots:
                data = s.read_bytes()
                if not data.startswith(PNG_MAGIC) or len(data) < 2000:
                    fails.append(f"{rid}: bad screenshot {s.name}")
        if (OUT / "work" / rid / "repo").exists():
            fails.append(f"{rid}: workspace was not cleaned up")
    if len(commits) != len([r for r in plan["runs"]]):
        fails.append("run branches are not all distinct commits")
    report = OUT / "report" / batch / "index.html"
    if not report.exists() or not (OUT / "report" / batch / "summary.png").exists():
        fails.append("report or report screenshot missing")
    for f in (OUT / "runs").glob(f"{batch}-*/**/*"):
        if f.is_file() and f.suffix in (".txt", ".json", ".jsonl", ".md", ".log") and f.stat().st_size < 5_000_000:
            if contains_secret(f.read_text(errors="replace")):
                fails.append(f"credential-shaped string in {f.relative_to(OUT)}")
    for line in fails:
        print(f"[selftest] FAIL {line}")
    n = len(plan["runs"])
    print(f"[selftest] {n} runs checked, {len(fails)} problem(s)")
    return 1 if fails else 0
