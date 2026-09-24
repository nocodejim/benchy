"""Small stdlib-only helpers shared by every step (the agent image has no pip deps)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

SLUG_RE = re.compile(r"[^a-z0-9.]+")


def slug(text: str, maxlen: int = 40) -> str:
    """Lowercase, [a-z0-9.-] only, no leading/trailing dashes or dots."""
    s = SLUG_RE.sub("-", text.lower()).strip("-.")
    s = re.sub(r"\.{2,}", ".", s)
    return s[:maxlen].strip("-.") or "x"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=False, default=str) + "\n")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_tree(root: Path) -> str:
    """Stable hash of a directory's file names + contents."""
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(sha256_file(p).encode())
    return h.hexdigest()


def run(cmd, cwd=None, env=None, check=True, timeout=None, capture=True, input=None):
    """subprocess.run wrapper; returns CompletedProcess with text output."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        check=check,
        timeout=timeout,
        text=True,
        input=input,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def git(*args, cwd, check=True, env=None) -> str:
    base = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "benchy",
        "GIT_AUTHOR_EMAIL": "benchy@example.invalid",
        "GIT_COMMITTER_NAME": "benchy",
        "GIT_COMMITTER_EMAIL": "benchy@example.invalid",
    }
    full_env = {**os.environ, **base, **(env or {})}
    return run(["git", "-c", "safe.directory=*", "-c", "core.hooksPath=/dev/null", *args],
               cwd=cwd, env=full_env, check=check).stdout


class Stopwatch:
    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.elapsed = time.monotonic() - self.start
        return False
