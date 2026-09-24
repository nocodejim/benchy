"""Turn Claude Code `--output-format stream-json --verbose` output into metrics."""

from __future__ import annotations

from pathlib import Path

from .copilot_parse import read_jsonl
from .schema import count_tool_kinds, finish_tokens, new


def parse(raw: Path) -> dict:
    events = read_jsonl(Path(raw) / "stdout.txt")
    m = new()
    if not events:
        m["warnings"].append("no Claude stream-json output found")
        return m

    tool_ids, tool_names, models = set(), [], set()
    result = None
    for ev in events:
        if not isinstance(ev, dict):
            continue
        typ = ev.get("type")
        if typ == "system" and ev.get("subtype") == "init" and ev.get("model"):
            models.add(ev["model"])
        elif typ == "assistant":
            msg = ev.get("message") or {}
            if msg.get("model"):
                models.add(msg["model"])
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") in ("tool_use", "server_tool_use"):
                    bid = block.get("id")
                    if bid and bid not in tool_ids:
                        tool_ids.add(bid)
                        tool_names.append(block.get("name") or "unknown")
        elif typ == "result":
            result = ev

    m["activity"]["tool_calls"] = len(tool_names)
    m["activity"]["tool_calls_by_kind"] = count_tool_kinds(tool_names)
    m["sources"]["tool_calls"] = "stream-json"

    if result is None:
        m["warnings"].append("stream ended without a result message (killed or timed out?)")
        m["models_reported"] = sorted(models)
        return m

    m["activity"]["turns"] = result.get("num_turns")
    if result.get("duration_api_ms") is not None:
        m["time"]["api_s"] = round(result["duration_api_ms"] / 1000, 2)
    if result.get("duration_ms") is not None:
        m["time"]["session_s"] = round(result["duration_ms"] / 1000, 2)

    # modelUsage covers subagents too; `usage` is main-loop only.
    mu = result.get("modelUsage") or {}
    if mu or result.get("is_error"):
        t = {"input_fresh": 0, "cache_read": 0, "cache_write": 0, "output": 0, "reasoning": None}
        for model, u in mu.items():
            models.add(model)
            t["input_fresh"] += u.get("inputTokens") or 0
            t["cache_read"] += u.get("cacheReadInputTokens") or 0
            t["cache_write"] += u.get("cacheCreationInputTokens") or 0
            t["output"] += u.get("outputTokens") or 0          # already includes thinking
            if u.get("thinkingTokens") is not None:
                t["reasoning"] = (t["reasoning"] or 0) + u["thinkingTokens"]
        m["sources"]["tokens"] = "result.modelUsage"
    else:
        u = result.get("usage") or {}
        t = {"input_fresh": u.get("input_tokens"), "cache_read": u.get("cache_read_input_tokens"),
             "cache_write": u.get("cache_creation_input_tokens"), "output": u.get("output_tokens"),
             "reasoning": None}
        m["sources"]["tokens"] = "result.usage"
        m["warnings"].append("modelUsage missing; token counts exclude subagents")
    m["tokens"] = finish_tokens({**t, "total": None})

    if result.get("total_cost_usd") is not None:
        m["cost"]["usd"] = round(result["total_cost_usd"], 4)
        m["cost"]["usd_source"] = "reported"
        m["sources"]["usd"] = "result.total_cost_usd (client-side estimate)"
    if result.get("is_error"):
        reason = result.get("terminal_reason") or result.get("subtype")
        m["warnings"].append(f"claude reported an error ({reason}): {str(result.get('result', ''))[:200]}")
    m["models_reported"] = sorted(models)
    return m
