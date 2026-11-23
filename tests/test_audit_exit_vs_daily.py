# -*- coding: utf-8 -*-
"""Unit tests for scripts/audit_exit_vs_daily.py (no real snapshot/cache)."""
from __future__ import annotations

from scripts.audit_exit_vs_daily import audit_bt, exit_touches_daily


def test_stop_not_touched_reports_mismatch():
    """Recorded stop but daily low never hits stop → mismatch."""
    bt = {
        "closed_pnls": [
            {
                "date": "2026-09-28",
                "code": "FU",
                "direction": "多",
                "lots": 2,
                "reason": "stop",
                "stop": 3951.8,
                "target": 4456.5,
                "fill_price_basis": "continuous_proxy",
                "fill_contract": "FU2701",
            }
        ]
    }
    snap = {
        "bars": {
            "FU": [
                {
                    "date": "2026-09-28",
                    "open": 4363.0,
                    "high": 4463.0,
                    "low": 4293.0,
                    "close": 4418.0,
                }
            ]
        }
    }
    report = audit_bt(bt, root=None, snap=snap, tick_by_code={"FU": 1.0})  # type: ignore[arg-type]
    # root unused when snap has bars
    assert report["checked"] == 1
    assert report["mismatches"] == 1
    assert report["mismatch_trades"][0]["code"] == "FU"
    assert report["mismatch_trades"][0]["reason"] == "stop"


def test_target_touched_no_mismatch():
    """Recorded target and daily high reaches target → no mismatch."""
    bt = {
        "closed_pnls": [
            {
                "date": "2026-09-28",
                "code": "FU",
                "direction": "多",
                "lots": 2,
                "reason": "target",
                "stop": 3951.8,
                "target": 4456.5,
                "fill_price_basis": "continuous_proxy",
                "fill_contract": "FU2701",
            }
        ]
    }
    snap = {
        "bars": {
            "FU": [
                {
                    "date": "2026-09-28",
                    "open": 4363.0,
                    "high": 4463.0,
                    "low": 4293.0,
                    "close": 4418.0,
                }
            ]
        }
    }
    report = audit_bt(bt, root=None, snap=snap, tick_by_code={"FU": 1.0})  # type: ignore[arg-type]
    assert report["checked"] == 1
    assert report["mismatches"] == 0


def test_exit_touches_helpers():
    assert exit_touches_daily(
        direction="多", reason="stop", stop=100.0, target=120.0, high=110.0, low=99.0, tol=0.0
    )
    assert not exit_touches_daily(
        direction="多", reason="stop", stop=100.0, target=120.0, high=110.0, low=101.0, tol=0.0
    )
    assert exit_touches_daily(
        direction="空", reason="stop", stop=100.0, target=80.0, high=101.0, low=90.0, tol=0.0
    )
