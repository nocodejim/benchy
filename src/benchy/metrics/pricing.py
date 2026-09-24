"""Estimate USD from tokens when a harness does not report cost itself."""

from __future__ import annotations

import re


def _norm(model: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", model.lower()).strip("-")


def rates_for(model: str | None, table: dict) -> dict | None:
    if not model:
        return None
    models = {_norm(k): v for k, v in (table.get("models") or {}).items()}
    key = _norm(model)
    if key in models:
        return models[key]
    # longest known id that prefixes the reported one (e.g. dated snapshots)
    hits = [k for k in models if key.startswith(k)]
    return models[max(hits, key=len)] if hits else None


def estimate_usd(tokens: dict, model: str | None, table: dict) -> float | None:
    r = rates_for(model, table)
    if not r or tokens.get("output") is None:
        return None
    per = 1_000_000
    usd = ((tokens.get("input_fresh") or 0) * r["input"]
           + (tokens.get("cache_read") or 0) * r.get("cached_input", r["input"])
           + (tokens.get("cache_write") or 0) * r.get("cache_write", r["input"])
           + (tokens.get("output") or 0) * r["output"]) / per
    return round(usd, 4)
