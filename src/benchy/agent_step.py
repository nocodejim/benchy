"""Run one harness against one workspace (benchy-agent image, stdlib only).

Mounts (set up by ./bench):
  /work/repo                   the run's workspace (rw)
  /raw                         out/runs/<id>/raw (rw) - harness artifacts land here, redacted
  /run/benchy/run.json         run description (ro)
  /run/benchy/prompt.md        full prompt (ro)
  /auth                        named volume with stored logins (ro)
  /run/benchy/solution.patch   ONLY for the mock harness
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

from . import harness as harnesses
from .harness.base import AgentContext
from .redact import redact, redact_file
from .util import utc_iso


def main() -> int:
    run = json.loads(Path("/run/benchy/run.json").read_text())
    prompt = Path("/run/benchy/prompt.md").read_text()
    raw = Path("/raw")
    home = Path(os.environ.get("HOME", "/tmp/home"))
    scratch = Path("/tmp/benchy")
    for d in (home, scratch, raw):
        d.mkdir(parents=True, exist_ok=True)

    h = harnesses.get(run["contender"]["harness"])
    ctx = AgentContext(run=run, prompt=prompt, workspace=Path("/work/repo"), raw_dir=raw,
                       home=home, auth_dir=Path("/auth"), scratch=scratch)
    env = {k: v for k, v in os.environ.items()
           if k not in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY")}
    env.update(h.prepare(ctx))
    cmd = h.command(ctx)
    timeout = int(run["timeout_s"])

    started = utc_iso()
    t0 = time.monotonic()
    timed_out = False
    out_tmp, err_tmp = scratch / "stdout.txt", scratch / "stderr.txt"
    with open(out_tmp, "wb") as out, open(err_tmp, "wb") as err:
        proc = subprocess.Popen(cmd, cwd=ctx.workspace, env=env, stdout=out, stderr=err,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                code = proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                code = proc.wait()
    wall = time.monotonic() - t0
    ended = utc_iso()

    # Kill anything the agent left running (dev servers, watchers).
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    redact_file(out_tmp, raw / "stdout.txt")
    redact_file(err_tmp, raw / "stderr.txt")
    try:
        h.harvest(ctx)
    except Exception as e:  # harvesting must never lose the run
        ctx.extra.setdefault("warnings", []).append(f"harvest failed: {e!r}")

    if code != 0 or timed_out:
        lines = [ln.strip() for ln in (raw / "stderr.txt").read_text(errors="replace").splitlines() if ln.strip()]
        if lines:
            ctx.extra.setdefault("warnings", []).append(f"harness exit {code}: {lines[0][:200]}")
    shown = [a if a != prompt else "<prompt.md>" for a in cmd]
    info = {
        "harness": h.name,
        "harness_version": h.version(),
        "command": [redact(a) for a in shown],
        "exit_code": code,
        "timed_out": timed_out,
        "exit_status": "timeout" if timed_out else ("ok" if code == 0 else "error"),
        "wall_s": round(wall, 2),
        "started": started,
        "ended": ended,
        "warnings": ctx.extra.get("warnings", []),
    }
    (raw / "agent.json").write_text(json.dumps(info, indent=2) + "\n")
    print(f"[agent] {h.name} exit={code} status={info['exit_status']} wall={wall:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
