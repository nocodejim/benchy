"""Zero-cost harnesses for testing benchy itself.

* mock: applies the task's golden solution patch and emits deterministic,
  plausible-looking metrics, so the whole pipeline (branches, grading,
  screenshots, report) can be exercised in CI without an AI subscription.
* noop: changes nothing. Used to prove each task's starting state FAILS its checks.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from ..metrics.schema import finish_tokens, new
from .base import Harness

SOLUTION = Path("/run/benchy/solution.patch")


class MockHarness(Harness):
    name = "mock"

    def version(self):
        return "mock 1"

    def command(self, ctx):
        return ["git", "apply", "--whitespace=nowarn", str(SOLUTION)] if SOLUTION.exists() else ["true"]

    def harvest(self, ctx):
        seed = int(hashlib.sha256(ctx.run["run_id"].encode()).hexdigest()[:8], 16)
        scale = 1.0 + (seed % 100) / 100.0            # 1.0 .. 2.0, stable per run
        tools = ["view", "view", "bash", "edit", "bash", "grep"]
        synthetic = {
            "tokens": {"input_fresh": int(40000 * scale), "cache_read": int(120000 * scale),
                       "cache_write": int(8000 * scale), "output": int(6000 * scale),
                       "reasoning": int(2500 * scale)},
            "turns": int(8 * scale),
            "tools": tools * int(1 + scale),
            "api_s": round(45 * scale, 1),
            "ai_credits": round(30 * scale, 2),
            "model": ctx.model or "mock-model",
        }
        (ctx.raw_dir / "mock.json").write_text(json.dumps(synthetic, indent=2))
        time.sleep(0.2)

    @staticmethod
    def parse(raw_dir):
        p = Path(raw_dir) / "mock.json"
        if not p.exists():
            return {}
        s = json.loads(p.read_text())
        m = new()
        m["tokens"].update(s["tokens"])
        finish_tokens(m["tokens"])
        m["activity"]["turns"] = s["turns"]
        m["activity"]["tool_calls"] = len(s["tools"])
        from ..metrics.schema import count_tool_kinds
        m["activity"]["tool_calls_by_kind"] = count_tool_kinds(s["tools"])
        m["time"]["api_s"] = s["api_s"]
        m["cost"]["ai_credits"] = s["ai_credits"]
        m["models_reported"] = [s["model"]]
        m["sources"] = {"all": "mock.json"}
        return m


class NoopHarness(Harness):
    name = "noop"

    def version(self):
        return "noop 1"

    def command(self, ctx):
        return ["true"]


PROBE = r'''
import json, os, subprocess
from pathlib import Path
r = {}
r["uid"] = os.getuid()
status = Path("/proc/self/status").read_text()
r["cap_eff"] = next(l.split()[1] for l in status.splitlines() if l.startswith("CapEff"))
try:
    Path("/usr/benchy-probe").write_text("x"); r["rootfs_writable"] = True
except OSError:
    r["rootfs_writable"] = False
hidden = []
for root, dirs, files in os.walk("/"):
    dirs[:] = [d for d in dirs if os.path.join(root, d) not in ("/proc", "/sys", "/dev")]
    for f in files:
        if f in ("checklib.py", "test_hidden_tokens.py", "solution.patch", "task.yaml"):
            hidden.append(os.path.join(root, f))
r["hidden_files_visible"] = hidden
r["token_env"] = [k for k in os.environ if k in ("GH_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN", "ANTHROPIC_API_KEY")]
r["git_commits"] = int(subprocess.run(["git", "-c", "safe.directory=*", "rev-list", "--count", "HEAD"],
                                      capture_output=True, text=True).stdout.strip() or 0)
r["work_entries"] = sorted(os.listdir("/work"))
r["auth_mounted"] = os.path.exists("/auth")
Path("/raw/probe.json").write_text(json.dumps(r, indent=2))
'''


class ProbeHarness(Harness):
    """Reports what an agent can see/do from inside the agent container (selftest only)."""
    name = "probe"

    def version(self):
        return "probe 1"

    def command(self, ctx):
        return ["python3", "-c", PROBE]
