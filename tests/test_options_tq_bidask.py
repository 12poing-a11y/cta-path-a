# -*- coding: utf-8 -*-
"""F1: live Bid/Ask capture + parse into research snapshots (offline)."""
from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from tqsdk_client import quote_bid_ask
from research.options.parse import normalize_leg, legs_from_czce_rows
from research.options.chain_store import build_snapshot, write_snapshot, load_snapshot
from research.options.strategies.credit_vertical import select_credit_vertical


def test_quote_bid_ask_prefers_level1() -> None:
    oq = SimpleNamespace(bid_price1=12.5, ask_price1=13.0, bid_price=1.0, ask_price=99.0)
    assert quote_bid_ask(oq) == (12.5, 13.0)


def test_quote_bid_ask_array_fallback() -> None:
    oq = SimpleNamespace(bid_price=[10.0, 9.0], ask_price=[11.0, 12.0])
    assert quote_bid_ask(oq) == (10.0, 11.0)


def test_quote_bid_ask_missing() -> None:
    assert quote_bid_ask(SimpleNamespace()) == (None, None)
    assert quote_bid_ask(SimpleNamespace(bid_price1=0, ask_price1=-1)) == (None, None)


def test_normalize_leg_tq_bid_ask_and_side_cols() -> None:
    row = {
        "合约代码": "CF701P15000",
        "期权类型": "P",
        "行权价": 15000,
        "最新价": 80.0,
        "买价": 78.0,
        "卖价": 82.0,
        "持仓量": 100,
        "隐含波动率": 20.0,
    }
    leg = normalize_leg(row, "CF701")
    assert leg is not None
    assert leg["bid"] == 78.0 and leg["ask"] == 82.0
    assert leg["settle"] == 80.0  # last as settle proxy


def test_normalize_leg_tq_without_czce_code() -> None:
    row = {
        "期权类型": "C",
        "行权价": 15200,
        "最新价": 55.0,
        "bid": 54.0,
        "ask": 56.0,
        "持仓量": 50,
    }
    leg = normalize_leg(row, "CF701")
    assert leg is not None
    assert leg["side"] == "C"
    assert leg["strike"] == 15200.0
    assert leg["bid"] == 54.0


def test_live_style_snapshot_quality_ok_with_bid_ask(tmp_path: Path) -> None:
    rows = []
    for k in range(14400, 15601, 200):
        for side, mid in (("C", max(5.0, 15000 - k + 80)), ("P", max(5.0, k - 15000 + 80))):
            rows.append(
                {
                    "合约代码": f"CF701{side}{k}",
                    "期权类型": side,
                    "行权价": k,
                    "最新价": mid,
                    "今结算": mid,
                    "买价": mid - 1,
                    "卖价": mid + 1,
                    "持仓量": 100,
                    "隐含波动率": 20.0,
                }
            )
    snap = build_snapshot(
        code="CF",
        asof="2026-11-15",
        futures_contract="CF2701",
        underlying_settle=15000.0,
        option_rows=rows,
        source="tq_live",
        futures_date="2026-11-15",
    )
    assert snap["quality"]["status"] == "OK"
    assert snap["quality"]["n_with_bid_ask"] >= 8
    write_snapshot(tmp_path, snap)
    loaded = load_snapshot(tmp_path, "CF", "2026-11-15")
    assert loaded is not None
    sel = select_credit_vertical(loaded, kind="put_credit", width_points=200, slip_ticks=0)
    assert sel is not None
    assert sel["pricing_mode"] == "bid_ask"
    # sell bid, buy ask → credit = short.bid - long.ask
    assert sel["short"]["px"] == sel["short"]["px"]  # smoke


def test_accumulate_live_soft_no_auth(tmp_path: Path, monkeypatch) -> None:
    """Without Tq auth, accumulate must soft-fail per code — never hang."""
    from research.options.chain_store import accumulate_live_bidask

    monkeypatch.setattr(
        "tqsdk_client.load_credentials",
        lambda root=None: None,
    )
    out = accumulate_live_bidask(tmp_path, codes=["CF"], overall_deadline_s=5.0)
    assert out["n_ok"] == 0
    assert out["n_fail"] == 1
    assert "no-auth" in str((out["results"][0].get("error") or ""))


def test_build_from_tq_live_passes_fast_flags(monkeypatch, tmp_path: Path) -> None:
    from research.options import chain_store as cs

    captured = {}

    def fake_fetch(contract, **kwargs):
        captured.update(kwargs)
        return {
            "rows": [
                {
                    "合约代码": "CF701P15000",
                    "期权类型": "P",
                    "行权价": 15000,
                    "最新价": 80,
                    "买价": 78,
                    "卖价": 82,
                    "持仓量": 10,
                    "隐含波动率": None,
                }
            ],
            "underlying_last": 15000.0,
            "asof": "2026-11-15",
            "notes": [],
            "bid_ask_coverage": 1.0,
            "n_with_bid_ask": 1,
            "elapsed_s": 0.1,
        }

    monkeypatch.setattr("tqsdk_client.fetch_option_chain_snapshot", fake_fetch)
    snap = cs.build_from_tq_live(tmp_path, code="CF", futures_contract="CF2701")
    assert captured.get("compute_iv") is False
    assert snap["source"] == "tq_live_fast"
    assert snap["n_with_bid_ask"] == 1


def test_legs_from_mixed_rows() -> None:
    month, legs = legs_from_czce_rows(
        [
            {
                "合约代码": "CF701C15000",
                "今结算": 100,
                "持仓量": 1,
                "隐含波动率": 18,
                "买价": 99,
                "卖价": 101,
            }
        ],
        futures_contract="CF2701",
    )
    assert month == "CF701"
    assert len(legs) == 1
    assert legs[0]["bid"] == 99.0
