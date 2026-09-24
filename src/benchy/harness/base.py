"""Harness adapter interface.

A harness is anything that takes a prompt + a working tree and edits it
(Copilot CLI, Claude Code, ...). Adapters split into two halves:

* agent-side (runs in benchy-agent, stdlib only): prepare / command / harvest
* grader-side (runs in benchy-grader): parse raw artifacts -> partial metrics

Adding a harness = one module here + its CLI in docker/agent.Dockerfile.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..redact import redact_file


@dataclass
class AgentContext:
    run: dict                 # run.json written by the setup step
    prompt: str
    workspace: Path           # /work/repo
    raw_dir: Path             # /raw  (host: out/runs/<id>/raw)
    home: Path                # tmpfs HOME for this run only
    auth_dir: Path            # /auth (read-only named volume)
    scratch: Path             # tmpfs scratch for harness state before redaction
    extra: dict = field(default_factory=dict)

    @property
    def model(self) -> str | None:
        return self.run["contender"].get("model")

    @property
    def effort(self) -> str | None:
        return self.run["contender"].get("effort")


class Harness:
    name = "base"
    auth_subdir: str | None = None   # subdirectory of the auth volume holding creds

    # --- agent side -------------------------------------------------------
    def version(self) -> str | None:
        return None

    def prepare(self, ctx: AgentContext) -> dict:
        """Return extra environment for the harness process."""
        return {}

    def command(self, ctx: AgentContext) -> list[str]:
        raise NotImplementedError

    def harvest(self, ctx: AgentContext) -> None:
        """Copy harness artifacts into ctx.raw_dir (always via redaction)."""

    def login_command(self, auth_dir: Path) -> tuple[list[str], dict]:
        raise NotImplementedError(f"{self.name} has no interactive login")

    # --- grader side ------------------------------------------------------
    @staticmethod
    def parse(raw_dir: Path) -> dict:
        """Return a partial metrics dict (see metrics.schema) from raw artifacts."""
        return {}


def copy_auth(src: Path, dst: Path, skip=("session-state", "logs", "history", "projects", "otel")) -> bool:
    """Copy stored credentials from the read-only auth volume into a per-run dir."""
    if not src.is_dir():
        return False
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in skip:
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
    return True


def harvest_tree(src: Path, dst: Path, patterns=("*",)) -> list[Path]:
    """Redact-copy files matching patterns from src (recursively) into dst."""
    out = []
    if not src.exists():
        return out
    for pat in patterns:
        for f in sorted(src.rglob(pat)):
            if f.is_file():
                target = dst / f.relative_to(src)
                redact_file(f, target)
                out.append(target)
    return out
