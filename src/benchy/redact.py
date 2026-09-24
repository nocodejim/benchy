"""Scrub credentials from anything benchy writes to the host.

Applied to every raw harness artifact (stdout/stderr, telemetry, session logs,
transcripts) before it lands in out/. Patterns are deliberately broad: a false
positive costs a few characters of log, a false negative leaks a token.
"""

from __future__ import annotations

import re
from pathlib import Path

REDACTED = "[REDACTED]"

PATTERNS = [
    re.compile(r"\b(gh[opusr]_[A-Za-z0-9]{20,})"),            # GitHub OAuth/user/server/refresh tokens
    re.compile(r"\b(github_pat_[A-Za-z0-9_]{20,})"),         # fine-grained PATs
    re.compile(r"\b(sk-ant-[A-Za-z0-9_\-]{20,})"),           # Anthropic API / OAuth tokens
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{32,})"),               # OpenAI-style keys
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),                   # AWS access key id
    re.compile(r"\b(xox[abpr]-[A-Za-z0-9\-]{10,})"),         # Slack
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-~+/]{16,}=*)"),
    # key = value pairs; the value must mix letters and digits so code such as
    # `password = form.password.data` is left alone.
    re.compile(r"(?i)((?:\"|')?(?:access_?token|refresh_?token|api_?key|oauth_?token|client_?secret|"
               r"authorization|password|passwd|secret)(?:\"|')?\s*[:=]\s*(?:\"|')?)"
               r"((?=[^\s\"',}]*\d)(?=[^\s\"',}]*[A-Za-z])[^\s\"',}]{8,})"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWTs
]


def redact(text: str) -> str:
    for pat in PATTERNS:
        if pat.groups >= 2:
            text = pat.sub(lambda m: m.group(1) + REDACTED, text)
        else:
            text = pat.sub(REDACTED, text)
    return text


def redact_file(src: Path, dst: Path | None = None, max_bytes: int = 50 * 1024 * 1024) -> None:
    """Redact src into dst (default: in place). Binary/huge files are skipped."""
    dst = dst or src
    data = Path(src).read_bytes()[:max_bytes]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_text(redact(text))


def contains_secret(text: str) -> bool:
    return redact(text) != text
