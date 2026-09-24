from conftest import FIXTURES

from benchy.metrics import claude_parse, copilot_parse, pricing
from benchy.metrics.schema import count_tool_kinds, tool_kind


def test_copilot_otlp_otel_only():
    m = copilot_parse.parse(FIXTURES / "copilot-otlp")
    t = m["tokens"]
    # input includes cache reads/writes in Copilot's convention -> fresh = 110000 - 85000 - 5000
    assert t["input_fresh"] == 20000
    assert t["cache_read"] == 85000
    assert t["cache_write"] == 5000
    assert t["output"] == 3000
    assert t["reasoning"] == 800
    assert t["total"] == 20000 + 85000 + 5000 + 3000
    # only the ROOT invoke_agent span counts (the nested sub-agent span would double count)
    assert m["cost"]["ai_credits"] == 12.5
    assert m["cost"]["usd"] == 0.125
    assert m["activity"]["tool_calls"] == 3
    assert m["activity"]["tool_calls_by_kind"] == {"read": 1, "shell": 1, "edit": 1}
    assert m["activity"]["turns"] == 2
    assert m["models_reported"] == ["claude-sonnet-5"]
    assert m["sources"]["tokens"] == "otel"
    assert any("nano_aiu" in w for w in m["warnings"])


def test_copilot_usage_file_preferred_and_events_tools():
    m = copilot_parse.parse(FIXTURES / "copilot-flat")
    assert m["sources"]["tokens"] == "usage.json"
    assert m["tokens"]["input_fresh"] == 5000
    assert m["tokens"]["output"] == 700
    assert m["cost"]["ai_credits"] == 7.0
    assert m["sources"]["ai_credits"] == "usage.json"
    assert m["time"]["api_s"] == 61.23
    assert m["time"]["session_s"] is None      # real usage.json has only a start time; wall_s covers it
    # OTel had no execute_tool spans -> tool calls come from session events, deduped by id
    assert m["activity"]["tool_calls"] == 2
    assert m["sources"]["tool_calls"] == "session-events"


def test_copilot_exit_summary_fallback():
    m = copilot_parse.parse(FIXTURES / "copilot-summary")
    assert m["cost"]["ai_credits"] == 14.2
    assert m["time"]["api_s"] == 179.6
    assert m["time"]["session_s"] == 735.7
    assert m["tokens"]["output"] == 12300
    assert m["tokens"]["reasoning"] == 4100
    assert m["tokens"]["cache_read"] == 1_100_000
    assert m["tokens"]["input_fresh"] == 100_000
    assert m["models_reported"] == ["claude-sonnet-5"]
    assert m["activity"]["tool_calls"] is None  # unknown, not zero


def test_copilot_nothing_found(tmp_path):
    m = copilot_parse.parse(tmp_path)
    assert m["tokens"]["total"] is None
    assert m["cost"]["ai_credits"] is None
    assert any("no Copilot usage" in w for w in m["warnings"])


def test_summary_premium_requests_legacy():
    r = copilot_parse.parse_summary("Total usage est:  3 Premium requests\nAPI time spent: 45s\n")
    assert r["premium_requests"] == 3
    assert r["api_s"] == 45


def test_claude_stream():
    m = claude_parse.parse(FIXTURES / "claude")
    assert m["activity"]["tool_calls"] == 3          # toolu_1 deduped across repeated message blocks
    assert m["activity"]["tool_calls_by_kind"] == {"read": 1, "shell": 1, "edit": 1}
    assert m["activity"]["turns"] == 4
    t = m["tokens"]
    assert t["input_fresh"] == 325 and t["output"] == 1550 and t["cache_read"] == 52000
    assert t["cache_write"] == 7000 and t["reasoning"] == 400
    assert m["cost"]["usd"] == 0.4213 and m["cost"]["usd_source"] == "reported"
    assert m["time"]["api_s"] == 61.0
    assert "claude-haiku-4-5" in m["models_reported"]


def test_claude_killed_run(tmp_path):
    (tmp_path / "stdout.txt").write_text('{"type":"assistant","message":{"content":[{"type":"tool_use","id":"a","name":"Bash"}]}}\n')
    m = claude_parse.parse(tmp_path)
    assert m["activity"]["tool_calls"] == 1
    assert m["tokens"]["total"] is None
    assert any("without a result" in w for w in m["warnings"])


def test_pricing_estimate_and_prefix_match():
    table = {"models": {"claude-sonnet-5": {"input": 2.0, "cached_input": 0.2, "cache_write": 2.5, "output": 10.0}}}
    tokens = {"input_fresh": 1_000_000, "cache_read": 1_000_000, "cache_write": 0, "output": 100_000}
    assert pricing.estimate_usd(tokens, "claude-sonnet-5", table) == 3.2
    assert pricing.estimate_usd(tokens, "Claude-Sonnet-5-20260901", table) == 3.2
    assert pricing.estimate_usd(tokens, "gpt-5.6-luna", table) is None
    assert pricing.estimate_usd({"output": None}, "claude-sonnet-5", table) is None


def test_tool_kinds():
    assert tool_kind("str_replace_editor") == "edit"
    assert tool_kind("Bash") == "shell"
    assert tool_kind("WebFetch") == "web"
    assert tool_kind("WebSearch") == "web"
    assert tool_kind("Grep") == "search"
    assert tool_kind("view") == "read"
    assert tool_kind("report_intent") == "other"
    assert count_tool_kinds(["Read", "Read", "Edit"]) == {"read": 2, "edit": 1}


def test_copilot_real_failed_run_usage_file(tmp_path):
    """Shape captured from Copilot CLI 1.0.88 when login is missing: zero usage, not unknown."""
    (tmp_path / "usage.json").write_text(
        '{"totalPremiumRequestCost":0,"totalUserRequests":0,"totalNanoAiu":0,"totalApiDurationMs":0,'
        '"sessionStartTime":"2026-09-24T02:36:53.756Z","codeChanges":{"linesAdded":0,"linesRemoved":0,'
        '"filesModifiedCount":0,"filesModified":[]},"modelMetrics":{},"agentMetrics":{},'
        '"lastCallInputTokens":0,"lastCallOutputTokens":0}')
    m = copilot_parse.parse(tmp_path)
    assert m["cost"]["ai_credits"] == 0.0
    assert m["time"]["api_s"] == 0.0
    assert m["tokens"]["total"] is None


def test_claude_auth_failure(tmp_path):
    (tmp_path / "stdout.txt").write_text(
        '{"type":"result","subtype":"success","is_error":true,"terminal_reason":"api_error",'
        '"result":"Not logged in","num_turns":1,"total_cost_usd":0,"usage":{"input_tokens":0,"output_tokens":0},'
        '"modelUsage":{}}\n')
    m = claude_parse.parse(tmp_path)
    assert any("Not logged in" in w for w in m["warnings"])
    assert m["tokens"]["total"] == 0
