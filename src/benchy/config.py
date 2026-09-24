"""Load and validate benchmark definitions (grader side; needs PyYAML).

Layout (relative to the benchy root, mounted at /bench in the grader):
  repos/<id>.yaml              target repository at a pinned commit
  tasks/<id>/task.yaml         one task: setup, prompt, checks
  tasks/<id>/hidden/           checks + golden solution (never mounted into the agent)
  tasks/_preamble.md           text prepended to every task prompt
  suites/<name>.yaml           ordered list of task ids
  contenders*.yaml             who competes (harness + model + effort)
  pricing.yaml                 $/1M-token fallback rates
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from .util import slug

ROOT = Path(os.environ.get("BENCHY_ROOT", "/bench"))
ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")
ARG_RE = re.compile(r"^[A-Za-z0-9._:/@+=\-]{1,128}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultracode"}


class ConfigError(SystemExit):
    pass


def _load(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"missing file: {path}")
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at top level")
    return data


def _req(d: dict, key: str, where: str):
    if key not in d or d[key] in (None, ""):
        raise ConfigError(f"{where}: missing required key '{key}'")
    return d[key]


def _check_id(value: str, where: str) -> str:
    if not isinstance(value, str) or not ID_RE.match(value):
        raise ConfigError(f"{where}: invalid id {value!r} (lowercase letters, digits, '.', '-')")
    return value


def _check_rel(path: str, base: Path, where: str) -> Path:
    """Resolve a path that must stay inside base (no ../ escapes)."""
    p = (base / path).resolve()
    if base.resolve() not in p.parents and p != base.resolve():
        raise ConfigError(f"{where}: path escapes its directory: {path}")
    return p


def load_repo(repo_id: str, root: Path = ROOT) -> dict:
    _check_id(repo_id, "repo")
    where = f"repos/{repo_id}.yaml"
    r = _load(root / "repos" / f"{repo_id}.yaml")
    r["id"] = repo_id
    url = _req(r, "url", where)
    if not re.match(r"^(https://|file:///)[^\s]+$", url):
        raise ConfigError(f"{where}: url must be https:// (or file:/// for local mirrors)")
    if not SHA_RE.match(str(_req(r, "sha", where))):
        raise ConfigError(f"{where}: sha must be a full 40-char commit id (pin, don't float)")
    r["prepare"] = [_step(s, root / "repos", where) for s in r.get("prepare") or []]
    r.setdefault("deps", "")
    r.setdefault("deps_files", [])
    r.setdefault("test_cmd", None)
    r.setdefault("test_files", [])
    return r


def _step(s: dict, base: Path, where: str) -> dict:
    if not isinstance(s, dict) or len(s) != 1:
        raise ConfigError(f"{where}: each setup step must be one of patch:/script:/copy:")
    kind, val = next(iter(s.items()))
    if kind not in ("patch", "script", "copy"):
        raise ConfigError(f"{where}: unknown setup step '{kind}'")
    if kind == "copy":
        src = _check_rel(_req(val, "from", where), base, where)
        return {"kind": "copy", "src": src, "dest": val.get("to", ".")}
    return {"kind": kind, "path": _check_rel(val, base, where)}


def load_task(task_id: str, root: Path = ROOT) -> dict:
    _check_id(task_id, "task")
    tdir = root / "tasks" / task_id
    where = f"tasks/{task_id}/task.yaml"
    t = _load(tdir / "task.yaml")
    if t.get("id", task_id) != task_id:
        raise ConfigError(f"{where}: id must match directory name")
    t["id"] = task_id
    t["dir"] = tdir
    t["hidden"] = tdir / "hidden"
    _req(t, "title", where)
    t["repo"] = _check_id(_req(t, "repo", where), where)
    t.setdefault("category", "general")
    t["timeout_s"] = int(t.get("timeout_s", 900))
    if not 30 <= t["timeout_s"] <= 7200:
        raise ConfigError(f"{where}: timeout_s must be between 30 and 7200")
    t["prompt_path"] = _check_rel(t.get("prompt", "prompt.md"), tdir, where)
    t["setup"] = [_step(s, tdir, where) for s in t.get("setup") or []]
    t["allowed_paths"] = list(t.get("allowed_paths") or ["**"])
    t.setdefault("scope_required", True)
    t.setdefault("regression", True)
    t["prefetch"] = _check_rel(t["prefetch"], tdir, where) if t.get("prefetch") else None
    t["solution_path"] = _check_rel(t.get("solution", "hidden/solution.patch"), tdir, where)
    checks = t.get("checks") or []
    if not checks:
        raise ConfigError(f"{where}: at least one check is required")
    seen = set()
    for c in checks:
        cid = _check_id(_req(c, "id", where), where)
        if cid in seen or cid in ("regression", "scope", "secrets"):
            raise ConfigError(f"{where}: duplicate or reserved check id '{cid}'")
        seen.add(cid)
        _req(c, "run", where)
        c.setdefault("title", cid)
        c["weight"] = float(c.get("weight", 1))
        if c["weight"] <= 0:
            raise ConfigError(f"{where}: check '{cid}' weight must be > 0")
        c.setdefault("required", True)
        c["timeout_s"] = int(c.get("timeout_s", 300))
    t["checks"] = checks
    return t


def load_suite(name: str, root: Path = ROOT) -> list[str]:
    _check_id(name, "suite")
    s = _load(root / "suites" / f"{name}.yaml")
    tasks = s.get("tasks") or []
    for tid in tasks:
        _check_id(tid, f"suites/{name}.yaml")
    return tasks


def load_contenders(path: Path) -> list[dict]:
    from .harness import HARNESSES

    data = _load(Path(path))
    items = data.get("contenders") or []
    if not items:
        raise ConfigError(f"{path}: no contenders defined")
    out, names = [], set()
    for i, c in enumerate(items):
        where = f"{path} contender #{i + 1}"
        name = str(_req(c, "name", where))
        if name in names:
            raise ConfigError(f"{where}: duplicate name {name!r}")
        names.add(name)
        harness = _req(c, "harness", where)
        if harness not in HARNESSES:
            raise ConfigError(f"{where}: unknown harness {harness!r}")
        for key in ("model", "effort"):
            v = c.get(key)
            if v is not None and not ARG_RE.match(str(v)):
                raise ConfigError(f"{where}: {key} contains unsupported characters")
        if c.get("effort") and str(c["effort"]) not in EFFORTS:
            raise ConfigError(f"{where}: effort must be one of {sorted(EFFORTS)}")
        extra = c.get("extra_args") or []
        if not isinstance(extra, list) or not all(ARG_RE.match(str(a)) for a in extra):
            raise ConfigError(f"{where}: extra_args must be a list of simple flags")
        c = {**c, "name": name, "extra_args": [str(a) for a in extra]}
        c["slug"] = slug("-".join(str(x) for x in (harness, c.get("model") or "default",
                                                   c.get("effort") or "default")), 60)
        out.append(c)
    slugs = [c["slug"] for c in out]
    if len(set(slugs)) != len(slugs):
        raise ConfigError(f"{path}: two contenders share harness+model+effort")
    return out


def load_pricing(root: Path = ROOT) -> dict:
    try:
        return _load(root / "pricing.yaml")
    except ConfigError:
        return {"models": {}}


def preamble(root: Path = ROOT) -> str:
    p = root / "tasks" / "_preamble.md"
    return p.read_text() if p.exists() else ""


def build_prompt(task: dict, root: Path = ROOT) -> str:
    body = task["prompt_path"].read_text().strip()
    pre = preamble(root).strip()
    return f"{pre}\n\n{body}\n" if pre else body + "\n"


def all_task_ids(root: Path = ROOT) -> list[str]:
    return sorted(p.parent.name for p in (root / "tasks").glob("*/task.yaml"))
