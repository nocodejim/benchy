"""Grade a finished workspace (grader image, --network none).

Every check starts from the exact agent result tree (hard reset + clean
between checks), so checks can't interfere with each other. Check commands
are trusted benchy code, but they execute agent-written code (tests), which is
why grading runs without network, as non-root, with all capabilities dropped.

Built-in checks, added to every task:
  regression  the repo's own test command, with the baseline test files
              restored (an agent can't "fix" a failure by editing the tests)
  scope       every changed path matches the task's allowed_paths
  secrets     gitleaks finds no credentials in the agent's changes
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from ..util import git

OUTPUT_TAIL = 4000
GITLEAKS_CONFIG = Path(os.environ.get("BENCHY_ROOT", "/bench")) / "docker" / "gitleaks-grader.toml"


def glob_to_regex(pattern: str) -> re.Pattern:
    """Glob with ** (any depth), * (within a segment), ? (one char)."""
    i, out = 0, ""
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif c == "*":
            out += "[^/]*"
            i += 1
        elif c == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(c)
            i += 1
    return re.compile(f"^{out}$")


def out_of_scope(paths: list[str], allowed: list[str]) -> list[str]:
    pats = [glob_to_regex(p) for p in allowed]
    return [p for p in paths if not any(r.match(p) for r in pats)]


def _reset(ws: Path, commit: str) -> None:
    git("reset", "--quiet", "--hard", commit, cwd=ws)
    git("clean", "-q", "-ffdx", "-e", ".venv", cwd=ws)   # pristine tree; keep only the deps venv


def _run_check(cmd: str, ws: Path, env: dict, timeout: int) -> dict:
    t0 = time.monotonic()
    try:
        res = subprocess.run(["bash", "-o", "pipefail", "-c", cmd], cwd=ws, env=env, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        passed, output = res.returncode == 0, res.stdout
    except subprocess.TimeoutExpired as e:
        passed = False
        output = (e.stdout or "") if isinstance(e.stdout, str) else ""
        output += f"\n[benchy] check timed out after {timeout}s"
    return {"passed": passed, "duration_s": round(time.monotonic() - t0, 2),
            "output": output[-OUTPUT_TAIL:]}


def grade(task: dict, repo: dict, ws: Path, baseline: str, agent_commit: str,
          changed: list[str], aux: Path | None = None) -> dict:
    env = {
        **os.environ,
        "AUX": str(aux or "/nonexistent"),
        "WS": str(ws),
        "HIDDEN": str(task["hidden"]),
        "LIB": str(Path(task["dir"]).parent / "_lib"),
        "VENV": str(ws / ".venv"),
        "BASELINE": baseline,
        "SCHEMAS": os.environ.get("K8S_SCHEMA_DIR", "/opt/schemas"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    results = []

    for c in task["checks"]:
        _reset(ws, agent_commit)
        r = _run_check(c["run"], ws, env, c["timeout_s"])
        results.append({"id": c["id"], "title": c["title"], "required": c["required"],
                        "weight": c["weight"], **r})

    if task.get("regression", True) and repo.get("test_cmd"):
        _reset(ws, agent_commit)
        for f in repo.get("test_files") or []:
            git("checkout", baseline, "--", f, cwd=ws, check=False)
        r = _run_check(repo["test_cmd"], ws, env, 600)
        results.append({"id": "regression", "title": "Existing test suite still passes",
                        "required": True, "weight": 1.0, **r})

    violations = out_of_scope(changed, task["allowed_paths"])
    results.append({"id": "scope", "title": "Changes stay within the task's scope",
                    "required": bool(task.get("scope_required", True)), "weight": 1.0,
                    "passed": not violations, "duration_s": 0,
                    "output": "\n".join(f"out of scope: {p}" for p in violations)})

    _reset(ws, agent_commit)
    findings = scan_secrets(ws, baseline, agent_commit)
    results.append({"id": "secrets", "title": "No credentials introduced (gitleaks)",
                    "required": True, "weight": 1.0, "passed": not findings, "duration_s": 0,
                    "output": "\n".join(f"{f['rule']}: {f['file']}:{f['line']}" for f in findings)})

    total_w = sum(r["weight"] for r in results)
    got_w = sum(r["weight"] for r in results if r["passed"])
    required = [r for r in results if r["required"]]
    return {
        "resolved": all(r["passed"] for r in required),
        "score": round(got_w / total_w, 4) if total_w else 0.0,
        "checks_passed": sum(r["passed"] for r in results),
        "checks_total": len(results),
        "regression_ok": next((r["passed"] for r in results if r["id"] == "regression"), None),
        "scope_violations": violations,
        "secrets_found": len(findings),
        "checks": results,
    }


def scan_secrets(ws: Path, baseline: str, agent_commit: str) -> list[dict]:
    """gitleaks over the agent's commit range only. Never records the secret itself."""
    report = Path("/tmp/benchy-gitleaks.json")
    report.unlink(missing_ok=True)
    # The agent must not be able to weaken the scan: use benchy's config (not a .gitleaks.toml
    # from the workspace), drop any .gitleaksignore it wrote, and ignore inline allow-comments.
    (ws / ".gitleaksignore").unlink(missing_ok=True)
    cmd = ["gitleaks", "git", "--no-banner", "--redact", "--exit-code", "0",
           "--config", str(GITLEAKS_CONFIG), "--ignore-gitleaks-allow",
           "--report-format", "json", "--report-path", str(report),
           "--log-opts", f"{baseline}..{agent_commit}", str(ws)]
    try:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
                       cwd="/tmp", env={**os.environ, "GIT_CONFIG_COUNT": "1",
                                        "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": "*"})
        data = json.loads(report.read_text() or "[]")
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return [{"rule": "gitleaks-error", "file": "-", "line": 0}]
    return [{"rule": f.get("RuleID"), "file": f.get("File"), "line": f.get("StartLine")} for f in data]
