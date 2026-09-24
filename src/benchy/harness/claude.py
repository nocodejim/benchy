"""Claude Code adapter (`claude -p --output-format stream-json`)."""

from __future__ import annotations

from pathlib import Path

from ..metrics import claude_parse
from ..util import run
from .base import AgentContext, Harness, copy_auth


class ClaudeHarness(Harness):
    name = "claude"
    auth_subdir = "claude"
    stdout_name = "stream.jsonl"

    def version(self):
        try:
            return "Claude Code " + run(["claude", "--version"], check=False).stdout.split()[0]
        except (FileNotFoundError, IndexError):
            return None

    def _config(self, ctx: AgentContext) -> Path:
        return ctx.scratch / "claude-config"

    def prepare(self, ctx):
        cfg = self._config(ctx)
        if not copy_auth(ctx.auth_dir / self.auth_subdir, cfg):
            ctx.extra.setdefault("warnings", []).append(
                "no stored Claude login found; run `./bench login claude` first")
        cfg.mkdir(parents=True, exist_ok=True)
        return {
            "CLAUDE_CONFIG_DIR": str(cfg),
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_COST_WARNINGS": "1",
            "CLAUDE_CODE_EFFORT_LEVEL": "",   # must not override --effort
        }

    def command(self, ctx):
        c = ctx.run["contender"]
        cmd = [
            "claude", "-p", ctx.prompt,
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "bypassPermissions",   # the container is the sandbox
            "--setting-sources", "user",                # ignore project CLAUDE.md/settings
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        if c.get("model"):
            cmd += ["--model", c["model"]]
        if c.get("effort"):
            cmd += ["--effort", c["effort"]]
        if c.get("max_budget_usd"):
            cmd += ["--max-budget-usd", str(c["max_budget_usd"])]
        cmd += [str(a) for a in c.get("extra_args", [])]
        return cmd

    def login_command(self, auth_dir):
        return ["claude", "auth", "login"], {"CLAUDE_CONFIG_DIR": str(auth_dir / self.auth_subdir)}

    @staticmethod
    def parse(raw_dir):
        return claude_parse.parse(Path(raw_dir))
