"""Turn raw Copilot CLI artifacts into a partial metrics record.

Copilot CLI exposes the same numbers `/usage` shows through several channels,
none of which has a published schema. We read all of them defensively and take
each field from the most authoritative source that has it:

  usage.json      --usage-output-file (final usage statistics)
  session-state   $COPILOT_HOME/session-state/<id>/events.jsonl (session.shutdown)
  stdout.txt      --output-format json event stream
  otel.jsonl      OpenTelemetry file exporter (GenAI semantic conventions)
  stderr/stdout   the human exit summary ("Total usage est", "API time spent", ...)

Every field records which source it came from in metrics["sources"].
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .schema import count_tool_kinds, finish_tokens, new

# --- generic helpers ---------------------------------------------------------

TOKEN_KEYS = {
    "input": ("inputTokens", "input_tokens", "promptTokens", "prompt_tokens",
              "gen_ai.usage.input_tokens"),
    "output": ("outputTokens", "output_tokens", "completionTokens", "completion_tokens",
               "gen_ai.usage.output_tokens"),
    "cache_read": ("cacheReadTokens", "cache_read_tokens", "cacheReadInputTokens",
                   "cache_read_input_tokens", "cachedTokens", "cached_tokens",
                   "gen_ai.usage.cache_read.input_tokens", "gen_ai.usage.cache_read_input_tokens"),
    "cache_write": ("cacheWriteTokens", "cache_write_tokens", "cacheCreationTokens",
                    "cacheCreationInputTokens", "cache_creation_input_tokens",
                    "gen_ai.usage.cache_creation.input_tokens",
                    "gen_ai.usage.cache_creation_input_tokens"),
    "reasoning": ("reasoningTokens", "reasoning_tokens", "gen_ai.usage.reasoning.output_tokens",
                  "gen_ai.usage.reasoning_tokens"),
}


def read_jsonl(path: Path) -> list:
    out = []
    try:
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except FileNotFoundError:
        pass
    return out


def walk(obj):
    """Yield every dict nested anywhere inside obj."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v) if "." in v else int(v)
        except ValueError:
            return None
    if isinstance(v, dict):  # OTLP AnyValue
        for k in ("intValue", "doubleValue", "stringValue"):
            if k in v:
                return num(v[k])
    return None


def tokens_from(d: dict) -> dict | None:
    """Extract Copilot-convention token counts (input INCLUDES cached) from one dict."""
    found = {}
    for field, keys in TOKEN_KEYS.items():
        for k in keys:
            if k in d and num(d[k]) is not None:
                found[field] = num(d[k])
                break
    if "input" not in found and "output" not in found:
        return None
    return found


def to_schema_tokens(t: dict, input_includes_cache=True) -> dict:
    cr, cw = t.get("cache_read"), t.get("cache_write")
    inp = t.get("input")
    fresh = inp
    if inp is not None and input_includes_cache:
        fresh = max(0, inp - (cr or 0) - (cw or 0))
    out = {"input_fresh": fresh, "cache_read": cr, "cache_write": cw,
           "output": t.get("output"), "reasoning": t.get("reasoning")}
    return finish_tokens({**out, "total": None})


def add_tokens(acc: dict, t: dict) -> dict:
    for k, v in t.items():
        if v is not None:
            acc[k] = (acc.get(k) or 0) + v
    return acc


def model_metrics_blocks(obj):
    """Find {"modelMetrics": {model: {usage: {...}, requests: {...}}}} anywhere."""
    for d in walk(obj):
        mm = d.get("modelMetrics") or d.get("model_metrics")
        if isinstance(mm, dict) and mm:
            yield d, mm


def from_model_metrics(mm: dict) -> dict:
    tokens, models, requests, req_cost = {}, [], 0, 0.0
    for model, data in mm.items():
        if not isinstance(data, dict):
            continue
        models.append(model)
        t = tokens_from(data.get("usage", data)) or {}
        add_tokens(tokens, t)
        r = data.get("requests") or {}
        requests += num(r.get("count")) or 0
        req_cost += num(r.get("cost")) or 0
    return {"tokens": tokens, "models": models, "requests": requests or None,
            "request_cost": req_cost or None}


# --- individual sources ------------------------------------------------------

CREDIT_KEYS = ("aiCredits", "ai_credits", "totalAiCredits", "aiCreditsUsed", "credits")
NANO_KEYS = ("totalNanoAiu", "nanoAiu", "nano_aiu", "github.copilot.nano_aiu")
PREMIUM_KEYS = ("totalPremiumRequests", "premiumRequests", "total_premium_requests",
                "totalPremiumRequestCost")


def first_num(d: dict, keys):
    for k in keys:
        if k in d and num(d[k]) is not None:
            return num(d[k])
    return None


def parse_usage_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    res: dict = {}
    for _, mm in model_metrics_blocks(data):
        res.update(from_model_metrics(mm))
        break
    if "tokens" not in res:  # flat totals
        for d in walk(data):
            t = tokens_from(d)
            if t:
                res["tokens"] = t
                break
    for d in walk(data):
        if res.get("ai_credits") is None:
            v = first_num(d, CREDIT_KEYS)
            if v is None and (n := first_num(d, NANO_KEYS)) is not None:
                v = n / 1e9
            if v is not None:
                res["ai_credits"] = v
        if res.get("premium_requests") is None and (v := first_num(d, PREMIUM_KEYS)) is not None:
            res["premium_requests"] = v
        if res.get("api_s") is None and (v := first_num(d, ("apiDurationMs", "totalApiDurationMs"))) is not None:
            res["api_s"] = v / 1000
        if res.get("session_s") is None and (v := first_num(d, ("sessionDurationMs", "totalSessionDurationMs",
                                                                  "durationMs"))) is not None:
            res["session_s"] = v / 1000
    return res


def parse_events(events: list) -> dict:
    """session-state events.jsonl or the --output-format json stdout stream."""
    res: dict = {}
    for ev in events:
        typ = str(ev.get("type", "")) if isinstance(ev, dict) else ""
        if "shutdown" in typ or "session.end" in typ or "result" == typ:
            for _, mm in model_metrics_blocks(ev):
                res.update(from_model_metrics(mm))
                break
    tool_ids, tool_names, turn_starts, messages = set(), [], 0, 0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        typ = str(ev.get("type", ""))
        turn_starts += typ == "assistant.turn_start"
        messages += typ == "assistant.message"
        for d in walk(ev):
            cid = d.get("toolCallId") or d.get("tool_call_id") or d.get("callId")
            if isinstance(cid, str) and cid not in tool_ids:
                name = d.get("toolName") or d.get("tool_name") or d.get("name")
                tool_ids.add(cid)
                tool_names.append(name if isinstance(name, str) else "unknown")
    if tool_ids:
        res["tools"] = tool_names
    if turn_starts or messages:
        res["turns"] = turn_starts or messages
    return res


def _str(v):
    if isinstance(v, dict):
        v = v.get("stringValue", v.get("intValue"))
    return None if v is None else str(v)


def _attrs(span: dict) -> dict:
    a = span.get("attributes") or {}
    if isinstance(a, list):
        return {kv.get("key"): kv.get("value") for kv in a if isinstance(kv, dict)}
    return a if isinstance(a, dict) else {}


def _is_span(d: dict) -> bool:
    return "name" in d and "attributes" in d and any(
        k in d for k in ("spanId", "span_id", "traceId", "trace_id", "parentSpanId",
                         "parent_span_id", "parentId", "startTimeUnixNano", "kind", "spanContext"))


def _parent(d: dict):
    for k in ("parentSpanId", "parent_span_id", "parentId"):
        if k in d:
            return d[k]
    ctx = d.get("parentSpanContext")
    return ctx.get("spanId") if isinstance(ctx, dict) else None


def parse_otel(path: Path) -> dict:
    lines = read_jsonl(path)
    spans = [d for line in lines for d in walk(line) if _is_span(d)]
    if not spans:
        return {}
    res: dict = {}
    chat_tokens, models, turns, tools = {}, set(), 0, []
    nano_root, nano_any = 0.0, 0.0
    shutdown = {}
    for s in spans:
        name = str(s.get("name", ""))
        a = _attrs(s)
        if name.startswith("chat"):
            turns += 1
            t = tokens_from(a)
            if t:
                add_tokens(chat_tokens, t)
            model = _str(a.get("gen_ai.response.model") or a.get("gen_ai.request.model"))
            if model:
                models.add(model)
        elif name.startswith("execute_tool"):
            tn = _str(a.get("gen_ai.tool.name"))
            tools.append(tn or name.removeprefix("execute_tool").strip() or "unknown")
        if name.startswith("invoke_agent"):
            n = num(a.get("github.copilot.nano_aiu"))
            if n is not None:
                nano_any += n
                if not _parent(s):
                    nano_root += n
        for ev in s.get("events") or []:
            if "shutdown" in str(ev.get("name", "")):
                shutdown = _attrs(ev)
    if chat_tokens:
        res["tokens"] = chat_tokens
    if models:
        res["models"] = sorted(models)
    if turns:
        res["turns"] = turns
    if tools:
        res["tools"] = tools
    if nano_root or nano_any:
        # Only the root invoke_agent span carries the session total; nested
        # agent spans would double count. Fall back to the sum if no root found.
        res["ai_credits"] = (nano_root or nano_any) / 1e9
    if shutdown:
        pr = num(shutdown.get("total_premium_requests"))
        if pr is not None:
            res["premium_requests"] = pr
    return res


_UNIT = {"": 1, "k": 1e3, "m": 1e6, "b": 1e9}


def _qty(s: str | None):
    if not s:
        return None
    m = re.fullmatch(r"([\d.,]+)\s*([kKmMbB]?)", s.strip())
    if not m:
        return None
    return int(round(float(m.group(1).replace(",", "")) * _UNIT[m.group(2).lower()]))


def _duration(s: str) -> float | None:
    total, found = 0.0, False
    for val, unit in re.findall(r"([\d.]+)\s*(h|ms|m|s)\b", s):
        found = True
        total += float(val) * {"h": 3600, "m": 60, "s": 1, "ms": 0.001}[unit]
    return total if found else None


def parse_summary(text: str) -> dict:
    """The human exit summary, e.g.
    Total usage est:        12.4 AI Credits      (or: 3 Premium requests)
    API time spent:         2m 59.6s
    Total session time:     12m 15.7s
    Total code changes:     +206 -77
    Breakdown by AI model:
     claude-sonnet-5   1.2m in, 12.3k out, 1.1m cached (4.1k reasoning) (Est. 12.4 AI Credits)
    """
    res: dict = {}
    if m := re.search(r"([\d.,]+)\s*(?:AI\s*Credits?|AIC\b|AI\s*Units?)", text, re.I):
        res["ai_credits"] = float(m.group(1).replace(",", ""))
    if m := re.search(r"([\d.,]+)\s*Premium\s+requests?", text, re.I):
        res["premium_requests"] = float(m.group(1).replace(",", ""))
    if m := re.search(r"API time spent:\s*([^\n]+)", text, re.I):
        res["api_s"] = _duration(m.group(1))
    if m := re.search(r"(?:Total )?session time:\s*([^\n]+)", text, re.I):
        res["session_s"] = _duration(m.group(1))
    if m := re.search(r"code changes:\s*\+(\d+)\s*-(\d+)", text, re.I):
        res["lines"] = (int(m.group(1)), int(m.group(2)))
    tokens, models = {}, []
    row = re.compile(
        r"^\s*([\w./:\-]+)\s+([\d.,]+[kKmMbB]?)\s+in,\s*([\d.,]+[kKmMbB]?)\s+out"
        r"(?:\s*\[\s*([\d.,]+[kKmMbB]?)\s*reasoning\s*\])?"
        r"(?:,\s*([\d.,]+[kKmMbB]?)\s+cached)?"
        r"(?:,\s*([\d.,]+[kKmMbB]?)\s+cache[ -]?write)?"
        r"(?:\s*\(\s*([\d.,]+[kKmMbB]?)\s*reasoning\s*\))?", re.M)
    for m in row.finditer(text):
        models.append(m.group(1))
        add_tokens(tokens, {"input": _qty(m.group(2)), "output": _qty(m.group(3)),
                            "cache_read": _qty(m.group(5)), "cache_write": _qty(m.group(6)),
                            "reasoning": _qty(m.group(4) or m.group(7))})
    if tokens:
        res["tokens"] = tokens
        res["models"] = models
    return res


# --- merge ---------------------------------------------------------------------

def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except FileNotFoundError:
        return ""


def parse(raw: Path) -> dict:
    sources = {
        "usage.json": parse_usage_file(raw / "usage.json"),
        "session-events": parse_events([e for f in sorted((raw / "session-state").rglob("*.jsonl"))
                                        for e in read_jsonl(f)] if (raw / "session-state").exists() else []),
        "stdout-json": parse_events(read_jsonl(raw / "stdout.txt")),
        "otel": parse_otel(raw / "otel.jsonl"),
        "summary": parse_summary(_read(raw / "stderr.txt") + "\n" + _read(raw / "stdout.txt")),
    }

    def pick(field, order):
        for src in order:
            v = sources[src].get(field)
            if v not in (None, {}, []):
                return v, src
        return None, None

    m = new()
    t, src = pick("tokens", ["usage.json", "session-events", "stdout-json", "otel", "summary"])
    if t:
        m["tokens"] = to_schema_tokens(t, input_includes_cache=True)
        m["sources"]["tokens"] = src
    v, src = pick("ai_credits", ["usage.json", "summary", "session-events", "stdout-json", "otel"])
    if v is not None:
        m["cost"]["ai_credits"] = round(float(v), 4)
        m["cost"]["usd"] = round(float(v) * 0.01, 4)
        m["cost"]["usd_source"] = "credits"
        m["sources"]["ai_credits"] = src
        if src == "otel":
            m["warnings"].append("AI credits derived from OTel nano_aiu assuming 1e9 nano-AIU = 1 credit")
    v, src = pick("premium_requests", ["usage.json", "summary", "otel"])
    if v is None:
        v, src = pick("requests", ["usage.json", "session-events", "stdout-json"])
        if v is not None:
            m["warnings"].append("premium_requests taken from model request count")
    if v is not None:
        m["cost"]["premium_requests"] = v
        m["sources"]["premium_requests"] = src
    tools, src = pick("tools", ["otel", "session-events", "stdout-json"])
    if tools:
        m["activity"]["tool_calls"] = len(tools)
        m["activity"]["tool_calls_by_kind"] = count_tool_kinds(tools)
        m["sources"]["tool_calls"] = src
    v, src = pick("turns", ["otel", "session-events", "stdout-json"])
    if v:
        m["activity"]["turns"] = v
        m["sources"]["turns"] = src
    for field in ("api_s", "session_s"):
        v, src = pick(field, ["usage.json", "summary"])
        if v is not None:
            m["time"][field] = round(v, 2)
            m["sources"][field] = src
    models, _ = pick("models", ["usage.json", "session-events", "stdout-json", "otel", "summary"])
    m["models_reported"] = sorted(set(models or []))

    # Cross-check: two independent token sources should roughly agree.
    totals = {k: (s["tokens"].get("input") or 0) + (s["tokens"].get("output") or 0)
              for k, s in sources.items() if s.get("tokens")}
    if len(totals) >= 2:
        lo, hi = min(totals.values()), max(totals.values())
        if hi and (hi - lo) / hi > 0.05:
            m["warnings"].append(f"token totals disagree across sources: {totals}")
    if not any(sources.values()):
        m["warnings"].append("no Copilot usage artifacts found (did the CLI run?)")
    return m
