# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from research.arbitrage_volatility import (
    evaluate_risk_gate,
    pair_correlation,
    rolling_spread,
    size_pair_position,
    spread_volatility,
)


def _pair_rows(n=100):
    rows = []
    for i in range(n):
        b = 100.0 + i * 0.25 + math.sin(i / 4.0)
        a = 15.0 + 1.8 * b + math.sin(i / 5.0) * 0.4
        rows.append({"date": f"2026-01-{i+1:02d}" if i < 28 else f"2026-02-{i-27:02d}",
                     "leg_a_close": a, "leg_b_close": b})
    return rows


def test_rolling_spread_uses_prior_rows_only():
    rows = _pair_rows()
    out = rolling_spread(rows, lookback=40, min_observations=20)
    assert not out[0]["ok"]
    assert out[20]["ok"]
    assert out[20]["fit_n"] == 20
    # Perturb current A close: current hedge fit must remain unchanged.
    changed = [dict(x) for x in rows]
    changed[20]["leg_a_close"] *= 1.2
    out2 = rolling_spread(changed, lookback=40, min_observations=20)
    assert out2[20]["hedge_ratio"] == out[20]["hedge_ratio"]
    assert out2[20]["intercept"] == out[20]["intercept"]


def test_invalid_or_unsorted_bars_are_not_filled():
    rows = _pair_rows(50)
    rows[30]["leg_a_close"] = None
    out = rolling_spread(rows, lookback=20, min_observations=10)
    assert out[30]["ok"] is False
    assert out[30]["reason"] == "invalid_or_unsorted_bar"


def test_spread_volatility_and_regime():
    rows = rolling_spread(_pair_rows(), lookback=40, min_observations=20)
    vol = spread_volatility(rows, short_window=5, long_window=30)
    assert vol["n_changes"] > 30
    assert vol["vol_ewma"] is not None
    assert vol["regime"] in {"expand", "compress", "normal", "unknown"}


def test_pair_correlation():
    a = [100 + i for i in range(80)]
    b = [50 + 0.5 * i for i in range(80)]
    corr = pair_correlation(a, b, window=30)
    # Constant proportional returns are highly correlated.
    assert corr is not None and corr > 0.99


def test_gate_fails_closed_on_missing_inputs():
    gate = evaluate_risk_gate(volatility={}, correlation=None, hedge_ratio=None)
    assert gate["allow_new_risk"] is False
    assert gate["status"] == "BLOCK"
    assert len(gate["reasons"]) >= 4


def test_gate_blocks_correlation_breakdown_and_vol_spike():
    vol = {"ok": True, "vol_expansion_ratio": 3.2}
    gate = evaluate_risk_gate(volatility=vol, correlation=0.1, hedge_ratio=1.2)
    assert gate["allow_new_risk"] is False
    assert "correlation_breakdown" in gate["reasons"]
    assert "extreme_spread_volatility" in gate["reasons"]


def test_position_sizing_requires_pass_gate():
    blocked = size_pair_position(
        risk_budget_yuan=2000, spread_vol_points=10,
        multiplier_a=5, multiplier_b=10, hedge_ratio=1.5,
        gate={"allow_new_risk": False},
    )
    assert blocked["contracts_a"] == 0
    assert blocked["contracts_b"] == 0
    passed = size_pair_position(
        risk_budget_yuan=2000, spread_vol_points=10,
        multiplier_a=5, multiplier_b=10, hedge_ratio=1.5,
        gate={"allow_new_risk": True},
    )
    assert passed["contracts_a"] == 10
    assert passed["contracts_b"] == 8
    assert passed["estimated_risk_yuan"] == 500
