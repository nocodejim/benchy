"""GitHub Copilot CLI adapter (`copilot -p`)."""

from __future__ import annotations

from pathlib import Path

from ..metrics import copilot_parse
from ..util import run
from .base import AgentContext, Harness, copy_auth, harvest_tree


class CopilotHarness(Harness):
    name = "copilot"
    auth_subdir = "copilot"

    def version(self):
        try:
            return run(["copilot", "--version"], check=False).stdout.split("\n")[0].strip()
        except FileNotFoundError:
            return None

    def _home(self, ctx: AgentContext) -> Path:
        return ctx.scratch / "copilot-home"

    def prepare(self, ctx):
        home = self._home(ctx)
        if not copy_auth(ctx.auth_dir / self.auth_subdir, home):
            ctx.extra.setdefault("warnings", []).append(
                "no stored Copilot login found; run `./bench login copilot` first")
        home.mkdir(parents=True, exist_ok=True)
        return {
            "COPILOT_HOME": str(home),
            "COPILOT_AUTO_UPDATE": "false",
            "COPILOT_OTEL_FILE_EXPORTER_PATH": str(ctx.scratch / "otel.jsonl"),
            "NO_COLOR": "1",
        }

    def command(self, ctx):
        c = ctx.run["contender"]
        cmd = [
            "copilot", "-p", ctx.prompt,
            "--allow-all",                   # the container is the sandbox
            "--no-ask-user",                 # nobody is there to answer
            "--no-custom-instructions",      # identical context for every contender
            "--disable-builtin-mcps",
            "--no-auto-update",
            "--no-color",
            "--stream", "off",
            "--output-format", "json",
            "--log-dir", str(ctx.scratch / "logs"),
            "--log-level", "info",
            "--share", str(ctx.scratch / "transcript.md"),
            "--usage-output-file", str(ctx.scratch / "usage.json"),
        ]
        if c.get("model"):
            cmd += ["--model", c["model"]]
        if c.get("effort"):
            cmd += ["--reasoning-effort", c["effort"]]
        if c.get("max_ai_credits"):
            cmd += ["--max-ai-credits", str(c["max_ai_credits"])]
        cmd += [str(a) for a in c.get("extra_args", [])]
        return cmd

    def harvest(self, ctx):
        s = ctx.scratch
        harvest_tree(s, ctx.raw_dir, ("otel.jsonl", "transcript.md", "usage.json"))
        harvest_tree(s / "logs", ctx.raw_dir / "logs")
        harvest_tree(self._home(ctx) / "session-state", ctx.raw_dir / "session-state", ("*.jsonl", "*.json"))

    def login_command(self, auth_dir):
        return ["copilot", "login", "--device-code"], {"COPILOT_HOME": str(auth_dir / self.auth_subdir)}

    @staticmethod
    def parse(raw_dir):
        return copilot_parse.parse(Path(raw_dir))
