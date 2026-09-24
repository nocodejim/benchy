"""The normalized, harness-independent metrics record (metrics.json).

Rule: a value a harness cannot report is None ("unknown"), never 0. The report
renders None as a dash and excludes it from aggregates.
"""

from __future__ import annotations

import copy

SCHEMA_VERSION = 1

TEMPLATE = {
    "schema": SCHEMA_VERSION,
    "run_id": None,
    "batch": None,
    "task": None,
    "contender": None,
    "harness": None,
    "harness_version": None,
    "model_requested": None,
    "models_reported": [],
    "effort": None,
    "outcome": {
        "resolved": None,          # every required check passed
        "score": None,             # weighted fraction of checks passed, 0..1
        "checks_passed": None,
        "checks_total": None,
        "regression_ok": None,
        "scope_violations": None,  # count of files changed outside allowed_paths
        "secrets_found": None,
        "exit_status": None,       # ok | timeout | error | not_run
    },
    "time": {
        "wall_s": None,            # measured by benchy around the harness process
        "api_s": None,             # harness-reported time waiting on the model API
        "session_s": None,         # harness-reported session length
    },
    "activity": {
        "turns": None,             # model round-trips / chat requests
        "tool_calls": None,
        "tool_calls_by_kind": {},  # read / edit / shell / search / web / other
    },
    "tokens": {
        "input_fresh": None,       # uncached prompt tokens
        "cache_read": None,
        "cache_write": None,
        "output": None,            # includes reasoning tokens
        "reasoning": None,         # subset of output, when reported
        "total": None,             # input_fresh + cache_read + cache_write + output
    },
    "cost": {
        "ai_credits": None,        # GitHub Copilot AI Credits (1 credit = $0.01)
        "premium_requests": None,  # legacy request-based plans only
        "usd": None,
        "usd_source": None,        # reported | credits | estimated-from-tokens
    },
    "diff": {
        "files_changed": None,
        "added": None,
        "deleted": None,
        "churn": None,
    },
    "sources": {},                 # which raw artifact each section came from
    "warnings": [],
}

TOOL_KINDS = ("read", "edit", "shell", "search", "web", "other")

_KIND_HINTS = [
    ("edit", ("edit", "write", "create", "str_replace", "apply_patch", "patch", "insert", "notebook")),
    ("shell", ("bash", "shell", "powershell", "terminal", "exec", "command")),
    ("web", ("fetch", "web", "url", "http", "browse")),
    ("search", ("grep", "glob", "search", "find", "rg", "ls", "list")),
    ("read", ("read", "view", "cat", "open", "get_file")),
]


def new() -> dict:
    return copy.deepcopy(TEMPLATE)


def tool_kind(name: str | None) -> str:
    n = (name or "").lower()
    for kind, hints in _KIND_HINTS:
        if any(h in n for h in hints):
            return kind
    return "other"


def count_tool_kinds(names) -> dict:
    out: dict[str, int] = {}
    for n in names:
        k = tool_kind(n)
        out[k] = out.get(k, 0) + 1
    return out


def finish_tokens(tokens: dict) -> dict:
    parts = [tokens.get(k) for k in ("input_fresh", "cache_read", "cache_write", "output")]
    if any(p is not None for p in parts):
        tokens["total"] = sum(p or 0 for p in parts)
    return tokens
