# -*- coding: utf-8 -*-
"""LSP event lifecycle schema + empty event factory."""
from __future__ import annotations

from typing import Any

EVENT_PHASES = (
    "level_formed",
    "price_approach",
    "break_pierce",
    "liquidity_release",
    "post_confirm",
)

SWEEP_OUTCOMES = ("fake_break_reversal", "true_break_continuation", "invalid_sweep")


def empty_event(*, symbol: str = "CF", timeframe: str = "15m") -> dict[str, Any]:
    return {
        "schema": "cta-lsp-event-v1",
        "symbol": symbol,
        "contract": None,
        "timestamp": None,
        "timeframe": timeframe,
        "bar_index": None,
        "level_type": None,
        "level_price": None,
        "distance_to_level": None,
        "break_direction": None,
        "break_size_atr": None,
        "volume_ratio": None,
        "oi_change": None,
        "vwap_deviation": None,
        "reclaim_bars": None,
        "post_sweep_return_1": None,
        "post_sweep_return_3": None,
        "post_sweep_return_5": None,
        "post_sweep_return_10": None,
        "mfe": None,
        "mae": None,
        "outcome": None,
        "status": "Research",
        "note": "",
    }
