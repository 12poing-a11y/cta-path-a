# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from datetime import date, timedelta

from research.arbitrage_backtest import (
    allocate_mrc_budgets,
    backtest_pair,
    round_trip_cost_yuan,
)
from research.arbitrage_volatility import (
    adf_tstat,
    align_pair_bars,
    engle_granger,
    evaluate_risk_gate,
    half_life_ou,
    rolling_cointegration,
    rolling_spread,
)


def _legs(n=150, noise=0.05):
    a_rows, b_rows = [], []
    start = date(2025, 1, 1)
    for i in range(n):
        day = (start + timedelta(days=i)).isoformat()
        b = 100.0 + i * 0.2
        a = 10.0 + 1.5 * b + math.sin(i / 7.0) * noise
        a_rows.append({"date": day, "close": a, "volume": 1000, "open_interest": 5000, "open": a})
        b_rows.append({"date": day, "close": b, "volume": 1000, "open_interest": 5000, "open": b})
    return a_rows, b_rows


def test_align_pair_bars_inner_join_no_ffill():
    a, b = _legs(40)
    del a[10]  # missing A day — must not ffill
    out = align_pair_bars(a, b)
    assert out["ok"]
    assert out["fill_policy"] == "inner_join_no_ffill"
    assert out["n"] == 39
    assert out["dropped_b_only"] == 1


def test_adf_rejects_mean_reverting_noise():
    # stationary-ish series
    xs = [math.sin(i / 3.0) for i in range(120)]
    adf = adf_tstat(xs)
    assert adf["ok"]
    assert adf["tstat"] is not None


def test_engle_granger_on_synthetic_coint():
    a, b = _legs(160, noise=0.02)
    ca = [r["close"] for r in a]
    cb = [r["close"] for r in b]
    eg = engle_granger(ca, cb, max_half_life=120.0)
    assert eg["hedge_ratio"] is not None
    assert abs(eg["hedge_ratio"] - 1.5) < 0.2


def test_half_life_ou_mean_reverting():
    # Clean AR(1): r_t = 0.8 r_{t-1} + eps → hl = -ln2/ln(0.8) ≈ 3.1
    r = [1.0]
    for i in range(120):
        eps = 0.02 * math.sin(i)
        r.append(0.8 * r[-1] + eps)
    hl = half_life_ou(r)
    assert hl["ok"], hl
    assert 1.0 < hl["half_life"] < 12.0


def test_gate_requires_cointegration_when_enabled():
    vol = {"ok": True, "vol_expansion_ratio": 1.0}
    blocked = evaluate_risk_gate(
        volatility=vol, correlation=0.9, hedge_ratio=1.2,
        require_cointegration=True, cointegration=None,
    )
    assert blocked["allow_new_risk"] is False
    assert "cointegration_unavailable" in blocked["reasons"]
    passed = evaluate_risk_gate(
        volatility=vol, correlation=0.9, hedge_ratio=1.2,
        require_cointegration=True,
        cointegration={"ok": True, "half_life": 10.0, "break_flag": False},
    )
    assert passed["allow_new_risk"] is True


def test_rolling_cointegration_no_lookahead_shape():
    a, b = _legs(100)
    rows = align_pair_bars(a, b)["rows"]
    out = rolling_cointegration(rows, lookback=60, min_observations=40)
    assert len(out) == len(rows)
    assert out[0]["ok"] is False


def test_round_trip_cost_positive():
    sa = {"fee_yuan": 5.0, "fee_rate": 0.0, "tick": 1.0, "mult": 10.0}
    sb = {"fee_yuan": 0.0, "fee_rate": 0.0001, "tick": 0.5, "mult": 100.0}
    c = round_trip_cost_yuan(
        spec_a=sa, spec_b=sb, contracts_a=1, contracts_b=2,
        px_a=3500, px_b=800, slip_ticks=1.0,
    )
    assert c > 0


def test_mrc_budget_sums_to_total():
    rets = {"A": [0.01, -0.02, 0.0] * 20, "B": [0.05, -0.05, 0.01] * 20}
    bud = allocate_mrc_budgets(["A", "B"], rets, total_budget=1000.0)
    assert abs(sum(bud.values()) - 1000.0) < 1e-6
    assert bud["A"] > bud["B"]  # lower vol → higher budget


def test_backtest_pair_smoke_tplus1():
    a, b = _legs(200, noise=0.15)
    rows = align_pair_bars(a, b)["rows"]
    sa = {"code": "A", "mult": 10.0, "tick": 1.0, "fee_yuan": 5.0, "fee_rate": 0.0,
          "margin_rate": 0.12, "limit_pct": 0.07}
    sb = {"code": "B", "mult": 10.0, "tick": 1.0, "fee_yuan": 5.0, "fee_rate": 0.0,
          "margin_rate": 0.12, "limit_pct": 0.07}
    # Without coint requirement so synthetic noise can still trade
    out = backtest_pair(
        rows, spec_a=sa, spec_b=sb, mode="spread_vol",
        require_cointegration=False, start=rows[80]["date"],
    )
    assert out["ok"]
    assert out["fill_policy"] == "next_open_else_close"
    assert "net_pnl_yuan" in out
