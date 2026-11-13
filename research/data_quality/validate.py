# -*- coding: utf-8 -*-
"""Batch helpers that compose research_quality + mask classification."""
from __future__ import annotations

from typing import Any

from research.data_quality.masks import classify_bar
from research_quality import validate_signals


def classify_bars(
    bars: list[dict[str, Any]],
    *,
    asof: str | None = None,
) -> dict[str, Any]:
    rows = [classify_bar(b, asof=asof) for b in bars if isinstance(b, dict)]
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    formal_ok = all(r["status"] in ("PASS", "VALID_ONLY", "DEGRADED") for r in rows)
    # Formal backtest fills require PASS (or explicit override elsewhere)
    fillable = [r for r in rows if r["status"] == "PASS"]
    return {
        "ok": formal_ok and not any(r["status"] == "REJECT" for r in rows),
        "n": len(rows),
        "by_status": by_status,
        "fillable_n": len(fillable),
        "rows": rows,
        "asof": asof,
    }


def validate_signals_with_quality(
    signals: list[dict[str, Any]],
    *,
    asof: str | None = None,
    universe: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Existing hard gate + per-row classify for audit trails."""
    gate = validate_signals(signals, asof=asof, universe=universe)
    classified = classify_bars(signals, asof=asof)
    return {
        **gate,
        "bar_quality": classified,
        "quality_protocol": "cta-data-quality-v1",
    }
