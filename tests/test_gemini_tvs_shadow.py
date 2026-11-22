# -*- coding: utf-8 -*-
from __future__ import annotations

from research.gemini_tvs_shadow import (
    apply_tolerance,
    downside_hv_ann,
    run_independent_oos,
    run_tvs_overlay,
    split_equity_curve,
)


def test_downside_hv_positive():
    rets = [0.01, -0.02, -0.01, 0.005, -0.015] * 6
    hv = downside_hv_ann(rets, window=20)
    assert hv is not None and hv > 0


def test_tolerance_band():
    assert apply_tolerance(1.0, 1.03, band=0.05) == 1.0
    assert apply_tolerance(1.0, 1.10, band=0.05) == 1.10


def test_overlay_no_lookahead_smoke():
    from datetime import date, timedelta

    start = date(2026, 1, 1)
    curve = []
    eq = 200000.0
    for i in range(60):
        pnl = 120.0 if i % 3 else -90.0
        eq += pnl
        curve.append({
            "date": (start + timedelta(days=i)).isoformat(),
            "equity": eq,
            "pnl": pnl,
            "codes": ["RB"],
        })
    out = run_tvs_overlay(curve, target_vol=0.15, tolerance_band=0.05)
    assert out["ok"]
    assert "baseline" in out and "tvs_shadow" in out


def _synth_curve(n=120):
    from datetime import date, timedelta

    start = date(2025, 1, 1)
    curve = []
    eq = 200000.0
    for i in range(n):
        # mild positive drift with drawdowns
        pnl = 150.0 if i % 5 else -200.0
        eq += pnl
        curve.append({
            "date": (start + timedelta(days=i)).isoformat(),
            "equity": eq,
            "pnl": pnl,
            "codes": ["M"],
        })
    return curve


def test_split_no_overlap():
    curve = _synth_curve()
    is_rows, oos_rows, meta = split_equity_curve(curve, is_frac=0.6)
    assert meta["ok"]
    is_dates = {r["date"] for r in is_rows}
    oos_dates = {r["date"] for r in oos_rows}
    assert not (is_dates & oos_dates)
    assert max(is_dates) < min(oos_dates)


def test_independent_oos_freezes_is_params(tmp_path):
    curve = _synth_curve(100)
    out = run_independent_oos(curve, root=tmp_path, is_frac=0.6)
    assert out["ok"]
    assert out["frozen_params"]["target_vol"] in (0.10, 0.15, 0.20)
    assert out["oos_acceptance"]["promote_path_a"] is False
    assert out["split"]["n_is"] + out["split"]["n_oos"] == 100
