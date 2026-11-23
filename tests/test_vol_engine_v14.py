# -*- coding: utf-8 -*-
"""Vol-V1.4: IV surface / Greeks / Shadow Greeks (shadow only)."""
from __future__ import annotations

from pathlib import Path

import pytest

from research.options.volatility.daily_vol_report import build_daily_vol_report
from research.options.volatility.greeks_engine import vanilla_greeks
from research.options.volatility.iv_surface import build_iv_surface, leg_premium
from research.options.volatility.shadow_greeks import shadow_greeks_for_point

ROOT = Path(__file__).resolve().parents[1]


def _synth_snap(
    *,
    asof: str = "2026-11-20",
    expiry: str = "2026-12-15",
    F: float = 15000.0,
    bid_ask: bool = True,
) -> dict:
    legs = []
    for side in ("C", "P"):
        for K in (14000.0, 15000.0, 16000.0):
            # Rough Black-ish premiums for positive IV solve
            if side == "C":
                mid = max(50.0, F - K + 200.0)
            else:
                mid = max(50.0, K - F + 200.0)
            leg = {
                "symbol": f"CF701{side}{int(K)}",
                "side": side,
                "strike": K,
                "settle": mid,
                "close": mid,
                "bid": mid - 5 if bid_ask else None,
                "ask": mid + 5 if bid_ask else None,
                "oi": 10.0,
            }
            legs.append(leg)
    return {
        "schema": "cta-options-chain-v1",
        "code": "CF",
        "asof": asof,
        "expiry": expiry,
        "underlying_settle": F,
        "futures_contract": "CF2701",
        "quality": {
            "status": "OK" if bid_ask else "WARN",
            "n_with_bid_ask": 6 if bid_ask else 0,
            "n_legs": 6,
        },
        "legs": legs,
    }


def test_leg_premium_rejects_bid_gt_ask():
    prem, reason = leg_premium({"bid": 10.0, "ask": 9.0, "settle": 9.5})
    assert prem is None
    assert reason == "bid_gt_ask"


def test_leg_premium_falls_back_to_settle():
    prem, src = leg_premium({"bid": None, "ask": None, "settle": 120.0})
    assert prem == 120.0
    assert src == "settle"


def test_iv_surface_no_zero_fill_on_bad_premium():
    snap = _synth_snap()
    # Force one leg below intrinsic so solver fails
    for leg in snap["legs"]:
        if leg["side"] == "C" and leg["strike"] == 14000.0:
            leg["bid"] = 1.0
            leg["ask"] = 2.0
            leg["settle"] = 1.5
            break
    surf = build_iv_surface(snap)
    assert surf["ok"] is True  # other legs still OK
    failed = [p for p in surf["points"] if p.get("status") == "FAIL"]
    assert failed
    for p in failed:
        assert p.get("iv") is None  # never 0-fill


def test_iv_surface_uses_asof_not_future_tenor():
    """years_to_expiry must use snap asof; expired tenor → reject."""
    snap = _synth_snap(asof="2026-12-20", expiry="2026-12-15")
    surf = build_iv_surface(snap)
    assert surf["ok"] is False
    assert surf["error"] == "bad_or_expired_tenor"


def test_vanilla_greeks_signs():
    g = vanilla_greeks(
        futures=15000, strike=15000, years=30 / 365, rate=0.02, iv=0.2, side="C"
    )
    assert g["delta"] > 0
    assert g["gamma"] > 0
    assert g["vega"] > 0
    gp = vanilla_greeks(
        futures=15000, strike=15000, years=30 / 365, rate=0.02, iv=0.2, side="P"
    )
    assert gp["delta"] < 0


def test_shadow_paths_diverge_or_match_by_construction():
    snap = _synth_snap()
    surf = build_iv_surface(snap)
    assert surf["ok"]
    pts = [p for p in surf["points"] if p["status"] == "OK"]
    atm = min(pts, key=lambda p: abs(p["strike"] - surf["futures"]))
    sg = shadow_greeks_for_point(
        futures=float(surf["futures"]),
        strike=float(atm["strike"]),
        years=float(surf["years"]),
        rate=0.02,
        side=str(atm["side"]),
        iv=float(atm["iv"]),
        surface_points=surf["points"],
    )
    assert "sticky_strike" in sg and "sticky_delta" in sg
    assert "delta" in sg["sticky_strike"] and "delta" in sg["sticky_delta"]
    assert "gamma_up" in sg["sticky_strike"] and "gamma_dn" in sg["sticky_strike"]
    assert sg["note"] == "monitor_only_not_trade_signal"


def test_daily_report_flags_and_cf_snapshot(tmp_path: Path):
    """Unit path with synth + optional live CF snapshot when present."""
    # synth via monkeypatch of load is heavy; call build_report_for_snapshot directly
    from research.options.volatility.daily_vol_report import build_report_for_snapshot

    rep = build_report_for_snapshot(_synth_snap())
    assert rep["ok"] is True
    assert rep["live_trading"] is False
    assert rep["promote_path_a"] is False
    assert rep["n_shadow_legs"] > 0

    cf_dir = ROOT / "data" / "options" / "snapshots" / "CF"
    if not cf_dir.is_dir() or not any(cf_dir.glob("*.json")):
        pytest.skip("no CF snapshots on disk")
    out = build_daily_vol_report(
        ROOT, codes=["CF"], write=True
    )
    assert out["ok"] is True
    assert out["live_trading"] is False
    assert out["promote_path_a"] is False
    assert out["model_version"] == "vol_engine_v1.4"
    path = ROOT / "lab" / "research" / "volatility" / "vol_engine_daily_latest.json"
    assert path.is_file()
    prod = out["products"][0]
    assert prod["code"] == "CF"
    assert prod.get("ok") is True
    assert (prod.get("n_surface_ok") or 0) > 0
