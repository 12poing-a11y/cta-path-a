# -*- coding: utf-8 -*-
"""Daily bias × 60m LSP filter — causal prior-session rule."""
from __future__ import annotations

from signals.lsp_mtf import (
    DailyBiasParams,
    daily_bias_map,
    filter_signals_by_daily_bias,
    prior_session_bias,
)
from signals.lsp_profile import LspSignal


def _sig(day: str, direction: str, i: int = 10) -> LspSignal:
    return LspSignal(
        signal_id=f"t-{day}-{direction}",
        direction=direction,  # type: ignore[arg-type]
        signal_index=i,
        signal_date=day,
        pierce_price=98.5,
        reclaim_close=100.2,
        edge=99.0,
        poc=100.0,
        vah=101.0,
        val=99.0,
        stop_price=98.0,
        timeframe="60",
    )


def test_daily_bias_sma_and_prior_session():
    bars = [{"date": f"2024-01-{d:02d}", "close": 100.0 + d} for d in range(1, 25)]
    bias = daily_bias_map(bars, DailyBiasParams(sma_len=5))
    assert bias["2024-01-04"] == "flat"  # need 5 closes
    assert bias["2024-01-10"] == "long"  # rising series above SMA
    assert prior_session_bias(bias, "2024-01-11") == bias["2024-01-10"]
    assert prior_session_bias(bias, "2024-01-01") is None


def test_filter_keeps_only_aligned():
    bias = {
        "2024-01-09": "long",
        "2024-01-10": "short",
        "2024-01-11": "flat",
    }
    # Signal on 01-11 uses prior 01-10 → short
    long_on_11 = _sig("2024-01-11", "long")
    short_on_11 = _sig("2024-01-11", "short")
    # Signal on 01-12 uses prior 01-11 → flat → reject
    long_on_12 = _sig("2024-01-12", "long")
    kept, rejected = filter_signals_by_daily_bias(
        [long_on_11, short_on_11, long_on_12],
        bias,  # type: ignore[arg-type]
    )
    assert [s.signal_id for s in kept] == [short_on_11.signal_id]
    reasons = {r["reason"] for r in rejected}
    assert "against_daily" in reasons
    assert "daily_flat" in reasons
