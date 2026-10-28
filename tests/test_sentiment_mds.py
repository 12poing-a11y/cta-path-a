# -*- coding: utf-8 -*-
from sentiment_mds import blend_p3, build_snapshot, ehi_from_row, mds_from_row


def test_mds_agree_and_diverge():
    assert mds_from_row(100, 10, 0.01) == 1.0
    assert mds_from_row(100, 10, -0.01) == -1.0
    assert mds_from_row(0, 0, 0.01) == 0.0


def test_ehi_uses_oi_then_vol():
    assert ehi_from_row(100, 1000, None) == 0.1
    assert ehi_from_row(50, None, 500) == 0.1
    assert ehi_from_row(50, 0, 0) == 0.0


def test_blend_p3_bounded():
    assert -1.0 <= blend_p3(1.0, 0.2) <= 1.0
    assert -1.0 <= blend_p3(-1.0, 0.2) <= 1.0


def test_build_snapshot_paper_only():
    rows = [
        {"code": "CU", "net": 5000, "net_chg": 200, "ret_1d": 0.01, "oi": 80000},
        {"code": "RB", "net": -3000, "net_chg": -100, "ret_1d": -0.008, "oi": 50000},
        {"code": "MA", "net": 100, "net_chg": 10, "ret_1d": -0.02, "oi": 200000},
    ]
    snap = build_snapshot(rows, asof="20261027")
    assert snap["live"] is False
    assert snap["sleeve"] == "sentiment_mds_paper"
    assert snap["n"] == 3
    assert "portfolio_p3" in snap
    assert snap["stance"] in ("risk_on", "risk_off", "neutral")
