# -*- coding: utf-8 -*-
"""TqSdk fallback for commodity options missing on sina (e.g. palm P)."""
from __future__ import annotations

from option_compare import (
    _TQ_CHAIN_CACHE,
    _pick_tq_leg,
    compare_protective,
    compare_protective_tqsdk,
)


def test_pick_tq_leg_nearest_put():
    rows = [
        {"期权类型": "C", "行权价": 8700, "最新价": 100, "合约代码": "p2701-C-8700"},
        {"期权类型": "P", "行权价": 8600, "最新价": 80, "合约代码": "p2701-P-8600"},
        {"期权类型": "P", "行权价": 8800, "最新价": 120, "合约代码": "p2701-P-8800"},
    ]
    leg = _pick_tq_leg(rows, want_put=True, strike_target=8650)
    assert leg is not None
    assert leg["symbol"] == "p2701-P-8600"
    assert leg["strike"] == 8600


def test_compare_protective_falls_back_to_tqsdk_for_P(monkeypatch):
    _TQ_CHAIN_CACHE.clear()
    fake = {
        "rows": [
            {
                "期权类型": "P",
                "行权价": 8700.0,
                "最新价": 55.0,
                "合约代码": "p2701-P-8700",
                "持仓量": 1000,
                "隐含波动率": 22.5,
            }
        ],
        "notes": [],
        "source": "tqsdk",
        "underlying_symbol": "DCE.p2701",
    }
    monkeypatch.setattr(
        "option_compare._tq_chain",
        lambda und, root=None: fake,
    )
    monkeypatch.setattr(
        "option_compare._underlying_contract",
        lambda code, root=None: "P2701",
    )
    out = compare_protective(
        "P",
        direction="多",
        strike=8680.0,
        lots=1,
        mult=10,
        synth_premium=1000.0,
        prefer="auto",
    )
    assert out["ok"] is True
    assert out["source"] == "tqsdk"
    assert out["option_symbol"] == "p2701-P-8700"
    assert out["listed_premium"] == 55.0 * 10
    assert "天勤" in (out.get("note") or "")


def test_compare_protective_tqsdk_empty_notes():
    _TQ_CHAIN_CACHE.clear()
    out = compare_protective_tqsdk(
        "P",
        direction="多",
        strike=None,
        lots=1,
        mult=10,
        synth_premium=1.0,
    )
    assert out["ok"] is False
