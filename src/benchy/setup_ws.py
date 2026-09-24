"""Batch planning and per-run workspace setup (grader image, network on).

Every run starts from scratch: a fresh working tree built from the pinned
upstream commit + the repo's `prepare` steps + the task's `setup` steps,
committed as a single orphan "baseline" commit. The agent never sees upstream
history (so `git log`/`git show` can't reveal what the setup injected) and
never sees another run's work.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

from . import config
from .util import git, read_json, run, sha256_file, sha256_tree, utc_iso, utc_stamp, write_json

OUT = Path(os.environ.get("BENCHY_OUT", "/out"))
WORK = Path(os.environ.get("BENCHY_WORK", "/work"))

VENV_EXCLUDES = [".venv/", "__pycache__/", "*.pyc", ".pytest_cache/"]


# --- planning ------------------------------------------------------------------

def plan(contenders_path: Path, suite: str | None, tasks: list[str] | None, repeats: int,
         timeout_scale: float = 1.0) -> dict:
    contenders = config.load_contenders(contenders_path)
    task_ids = tasks or config.load_suite(suite or "starter")
    loaded = [config.load_task(t) for t in task_ids]
    if not 1 <= repeats <= 50:
        raise config.ConfigError("repeats must be between 1 and 50")
    batch = utc_stamp()
    runs = []
    # Interleave: every contender attempts a task before anyone repeats it, and
    # the contender order rotates each repeat so nobody always goes first.
    for r in range(1, repeats + 1):
        for task in loaded:
            k = (r - 1) % len(contenders)
            for c in contenders[k:] + contenders[:k]:
                rid = f"{batch}-{task['id']}-{c['slug']}-r{r}"
                runs.append({
                    "run_id": rid,
                    "batch": batch,
                    "task": task["id"],
                    "contender": c,
                    "repeat": r,
                    "timeout_s": int(task["timeout_s"] * timeout_scale),
                })
    data = {
        "batch": batch,
        "created": utc_iso(),
        "contenders": contenders,
        "tasks": task_ids,
        "repeats": repeats,
        "runs": runs,
    }
    write_json(OUT / "batches" / f"{batch}.json", data)
    return data


def find_run(run_id: str) -> dict:
    batch = run_id.split("-", 1)[0]
    data = read_json(OUT / "batches" / f"{batch}.json")
    if not data:
        raise SystemExit(f"no batch plan for {run_id}")
    for r in data["runs"]:
        if r["run_id"] == run_id:
            return r
    raise SystemExit(f"run {run_id} not in batch {batch}")


# --- upstream mirror -------------------------------------------------------------

def ensure_mirror(repo: dict) -> Path:
    mirror = OUT / "cache" / "repos" / f"{repo['id']}.git"
    if not mirror.exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        tmp = mirror.with_suffix(".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        git("clone", "--mirror", "--quiet", repo["url"], str(tmp), cwd=mirror.parent)
        tmp.rename(mirror)
    if run(["git", "-c", "safe.directory=*", "-C", str(mirror), "cat-file", "-e",
            f"{repo['sha']}^{{commit}}"], check=False).returncode != 0:
        git("fetch", "--quiet", "origin", repo["sha"], cwd=mirror)
    return mirror


def export_tree(mirror: Path, sha: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    raw = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(mirror), "archive", "--format=tar", sha],
                         check=True, stdout=subprocess.PIPE).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        tf.extractall(dest, filter="data")


# --- setup steps -------------------------------------------------------------------

def apply_steps(steps: list[dict], ws: Path, label: str) -> None:
    for s in steps:
        if s["kind"] == "patch":
            git("apply", "--whitespace=nowarn", str(s["path"]), cwd=ws)
        elif s["kind"] == "script":
            env = {**os.environ, "BENCHY_WS": str(ws)}
            res = run(["bash", str(s["path"])], cwd=ws, env=env, check=False, timeout=600)
            if res.returncode != 0:
                raise SystemExit(f"{label} setup script {s['path'].name} failed:\n{res.stdout}\n{res.stderr}")
        elif s["kind"] == "copy":
            dest = (ws / s["dest"]).resolve()
            if ws.resolve() not in dest.parents and dest != ws.resolve():
                raise SystemExit(f"{label}: copy destination escapes workspace")
            shutil.copytree(s["src"], dest, dirs_exist_ok=True)


def install_deps(repo: dict, ws: Path) -> str | None:
    """Create ws/.venv, reusing a cache keyed on everything that affects it."""
    if not repo.get("deps"):
        return None
    h = [repo["deps"], repo["sha"]]
    for f in repo.get("deps_files") or []:
        p = ws / f
        h.append(sha256_file(p) if p.exists() else "-")
    key = hashlib.sha256("\n".join(h).encode()).hexdigest()[:16]
    cached = OUT / "cache" / "venvs" / f"{repo['id']}-{key}"
    target = ws / ".venv"
    if (cached / ".venv").exists():
        shutil.copytree(cached / ".venv", target, symlinks=True)
        return key
    env = {**os.environ, "PIP_CACHE_DIR": str(OUT / "cache" / "pip"), "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    res = run(["bash", "-euo", "pipefail", "-c", repo["deps"]], cwd=ws, env=env, check=False, timeout=1200)
    if res.returncode != 0:
        raise SystemExit(f"dependency install failed:\n{res.stdout[-4000:]}\n{res.stderr[-4000:]}")
    tmp = cached.with_name(cached.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    shutil.copytree(target, tmp / ".venv", symlinks=True)
    shutil.rmtree(cached, ignore_errors=True)
    tmp.rename(cached)
    return key


def setup(run_id: str) -> dict:
    entry = find_run(run_id)
    task = config.load_task(entry["task"])
    repo = config.load_repo(task["repo"])
    run_dir = OUT / "runs" / run_id
    if (run_dir / "run.json").exists():
        raise SystemExit(f"run {run_id} already exists; runs are never reused")
    ws = WORK / "repo"
    if ws.exists() and any(ws.iterdir()):
        raise SystemExit(f"workspace {ws} is not empty; refusing to reuse it")

    mirror = ensure_mirror(repo)
    export_tree(mirror, repo["sha"], ws)
    git("init", "--quiet", "-b", "main", cwd=ws)
    apply_steps(repo["prepare"], ws, f"repo {repo['id']}")
    apply_steps(task["setup"], ws, f"task {task['id']}")
    excl = ws / ".git" / "info" / "exclude"
    excl.write_text(excl.read_text() + "\n# benchy\n" + "\n".join(VENV_EXCLUDES) + "\n")
    venv_key = install_deps(repo, ws)
    git("add", "-A", cwd=ws)
    git("commit", "--quiet", "--no-verify", "-m", f"benchy baseline: {task['id']}", cwd=ws)
    baseline = git("rev-parse", "HEAD", cwd=ws).strip()

    prompt = config.build_prompt(task)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "raw").mkdir(exist_ok=True)
    if task["prefetch"]:
        # Grader-only reference data fetched while the network is available
        # (e.g. real release SHAs). Lives in aux/, which the agent never mounts.
        aux = run_dir / "aux"
        aux.mkdir(exist_ok=True)
        res = run(["bash", str(task["prefetch"])], cwd=aux, env={**os.environ, "AUX": str(aux)},
                  check=False, timeout=300)
        (aux / "prefetch.log").write_text(f"exit={res.returncode}\n{res.stdout[-4000:]}\n{res.stderr[-4000:]}")
    (run_dir / "prompt.md").write_text(prompt)
    info = {
        "run_id": run_id,
        "batch": entry["batch"],
        "task": task["id"],
        "task_title": task["title"],
        "category": task["category"],
        "repeat": entry["repeat"],
        "contender": entry["contender"],
        "timeout_s": entry["timeout_s"],
        "repo": {"id": repo["id"], "url": repo["url"], "sha": repo["sha"]},
        "baseline_commit": baseline,
        "branch": f"bench/{run_id}",
        "prompt_sha256": sha256_file(run_dir / "prompt.md"),
        "task_sha256": sha256_tree(task["dir"]),
        "venv_cache_key": venv_key,
        "images": {"agent": os.environ.get("BENCHY_AGENT_IMAGE"), "grader": os.environ.get("BENCHY_GRADER_IMAGE")},
        "benchy_version": __import__("benchy").__version__,
        "setup_at": utc_iso(),
    }
    write_json(run_dir / "run.json", info)
    return info

