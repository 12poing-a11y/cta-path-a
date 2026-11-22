# -*- coding: utf-8 -*-
from __future__ import annotations

from research.gemini_tvs_per_symbol import calibrate_to_book, run_per_symbol_tvs


def test_calibrate_scales_to_book_pnl():
    day_code = {"2026-01-02": {"M": 10.0, "L": -5.0}}
    curve = [{"date": "2026-01-02", "pnl": 20.0, "equity": 100020.0, "codes": ["M", "L"]}]
    out = calibrate_to_book(day_code, curve)
    assert abs(sum(out["2026-01-02"].values()) - 20.0) < 1e-9


def test_per_symbol_tvs_smoke(tmp_path):
    # Minimal synthetic curve with calibrated symbol pnls
    from datetime import date, timedelta

    start = date(2026, 1, 1)
    curve = []
    sym = {}
    eq = 200000.0
    for i in range(50):
        day = (start + timedelta(days=i)).isoformat()
        pnl = 100.0 if i % 2 == 0 else -60.0
        eq += pnl
        curve.append({"date": day, "pnl": pnl, "equity": eq, "codes": ["M"]})
        sym[day] = {"M": pnl}
    out = run_per_symbol_tvs(curve, sym, root=tmp_path, target_vol=0.15)
    # Without local bars HV may stay 1.0 — still ok structure
    assert out["ok"]
    assert "delta" in out
