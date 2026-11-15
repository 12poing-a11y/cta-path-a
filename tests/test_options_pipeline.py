# -*- coding: utf-8 -*-
"""Options research C–E pipeline: chain → credit BT → paper → risk (offline)."""
from __future__ import annotations

from pathlib import Path

from research.options.chain_store import build_snapshot, load_chain_series, write_snapshot
from research.options.backtest.engine import run_credit_vertical_bt
from research.options.paper.ledger import ingest_bt_closed, load_ledger
from research.options.quality import assess_chain_quality
from research.options.risk_report import build_risk_report
from research.options.strategies.credit_vertical import (
    expiry_pnl_points,
    select_credit_vertical,
)
from option_compare import _cache_fresh


def _czce_rows(month: str = "CF701", *, F: float = 15000.0) -> list[dict]:
    """Synthetic CZCE day rows; strikes fixed so multi-day MTM can match legs."""
    rows = []
    for k in range(14400, 15601, 200):
        call_settle = max(5.0, F - k + 80)
        put_settle = max(5.0, k - F + 80)
        rows.append(
            {
                "合约代码": f"{month}C{k}",
                "今结算": call_settle,
                "今收盘": call_settle,
                "持仓量": 100,
                "成交量(手)": 10,
                "隐含波动率": 20.0,
                "DELTA": 0.5,
            }
        )
        rows.append(
            {
                "合约代码": f"{month}P{k}",
                "今结算": put_settle,
                "今收盘": put_settle,
                "持仓量": 120,
                "成交量(手)": 12,
                "隐含波动率": 21.0,
                "DELTA": -0.5,
            }
        )
    return rows


def test_quality_no_bid_ask_is_warn(tmp_path: Path) -> None:
    snap = build_snapshot(
        code="CF",
        asof="2026-11-10",
        futures_contract="CF2701",
        underlying_settle=15000.0,
        option_rows=_czce_rows(),
        futures_date="2026-11-10",
    )
    q = snap["quality"]
    assert q["status"] == "WARN"
    assert "no_bid_ask" in q["warnings"]
    assert q["n_legs"] >= 8


def test_quality_reject_missing_settle() -> None:
    q = assess_chain_quality([], asof="2026-11-10", underlying_settle=None)
    assert q["status"] == "REJECT"
    assert "underlying_settle_missing" in q["reasons"]


def test_chain_write_load_and_credit_select(tmp_path: Path) -> None:
    root = tmp_path
    for i, asof in enumerate(["2026-11-10", "2026-11-11", "2026-11-12"]):
        F = 15000.0 + i * 50
        snap = build_snapshot(
            code="CF",
            asof=asof,
            futures_contract="CF2701",
            underlying_settle=F,
            option_rows=_czce_rows(F=F),
            futures_date=asof,
            source="fixture",
        )
        write_snapshot(root, snap)
    series = load_chain_series(root, "CF")
    assert len(series) == 3
    sel = select_credit_vertical(series[0], kind="put_credit", width_points=200, slip_ticks=1)
    assert sel is not None
    assert sel["credit_points"] > 0
    assert sel["pricing_mode"] == "settle_discount"
    assert sel["short"]["side"] == "P"


def test_credit_bt_no_lookahead_and_metrics(tmp_path: Path) -> None:
    root = tmp_path
    for i, asof in enumerate(["2026-11-10", "2026-11-11", "2026-11-12"]):
        F = 15000.0 + i * 100
        snap = build_snapshot(
            code="CF",
            asof=asof,
            futures_contract="CF2701",
            underlying_settle=F,
            option_rows=_czce_rows(F=F),
            futures_date=asof,
        )
        write_snapshot(root, snap)
    # Also empty SR so skip path covered
    bt = run_credit_vertical_bt(
        root,
        codes=["CF", "SR"],
        kind="put_credit",
        width_points=200,
        slip_ticks=1,
        exit_mode="next_snap",
        write=True,
    )
    assert bt["strategy_state"] == "WARN"
    closed = [t for t in bt["trades"] if t["status"] == "closed"]
    assert len(closed) >= 1
    for t in closed:
        assert str(t["exit_asof"]) > str(t["entry_asof"] or t["asof"])
        assert t["pricing_mode"] == "settle_discount"
    m = bt["metrics"]
    assert m["n_closed"] >= 1
    assert (root / "data/options/backtests/credit_vertical_latest.json").is_file()


def test_expiry_pnl_put_credit_max_loss() -> None:
    # Short 15000 / long 14800, credit 50, F deep ITM → max loss ≈ width - credit
    pnl = expiry_pnl_points(
        kind="put_credit",
        short_strike=15000,
        long_strike=14800,
        credit_points=50,
        futures_settle=14000,
    )
    assert abs(pnl - (50 - 200)) < 1e-9


def test_paper_idempotent_and_risk(tmp_path: Path) -> None:
    root = tmp_path
    for i, asof in enumerate(["2026-11-10", "2026-11-11"]):
        F = 15000.0 + i * 80
        write_snapshot(
            root,
            build_snapshot(
                code="CF",
                asof=asof,
                futures_contract="CF2701",
                underlying_settle=F,
                option_rows=_czce_rows(F=F),
                futures_date=asof,
            ),
        )
    bt = run_credit_vertical_bt(root, codes=["CF"], write=True)
    a = ingest_bt_closed(root, bt)
    b = ingest_bt_closed(root, bt)
    assert a["n_new"] >= 1
    assert b["n_new"] == 0
    assert b["n_dup"] >= 1
    assert len(load_ledger(root)) == a["n_new"]
    risk = build_risk_report(root, write=True)
    assert risk["ledger_n"] >= 1
    assert (root / "data/options/risk_reports/latest.json").is_file()


def test_append_trade_status() -> None:
    # unit smoke for fingerprint
    from research.options.paper.ledger import trade_fingerprint

    t = {
        "strategy_id": "credit_vertical",
        "code": "CF",
        "asof": "2026-11-10",
        "kind": "put_credit",
        "short": {"strike": 15000},
        "long": {"strike": 14800},
        "credit_points": 40,
    }
    assert len(trade_fingerprint(t)) == 16


def test_option_compare_cache_freshness() -> None:
    assert _cache_fresh("2099-01-01T00:00:00+00:00") is True
    assert _cache_fresh(None) is False
    assert _cache_fresh("2000-01-01T00:00:00+00:00") is False


def test_reject_day_skipped(tmp_path: Path) -> None:
    # Day1 REJECT (no settle), day2 OK-ish WARN
    bad = build_snapshot(
        code="CF",
        asof="2026-11-10",
        futures_contract="CF2701",
        underlying_settle=None,
        option_rows=_czce_rows(),
        futures_date="2026-11-10",
    )
    write_snapshot(tmp_path, bad)
    good = build_snapshot(
        code="CF",
        asof="2026-11-11",
        futures_contract="CF2701",
        underlying_settle=15000.0,
        option_rows=_czce_rows(),
        futures_date="2026-11-11",
    )
    write_snapshot(tmp_path, good)
    # need third for close of day2
    good2 = build_snapshot(
        code="CF",
        asof="2026-11-12",
        futures_contract="CF2701",
        underlying_settle=15050.0,
        option_rows=_czce_rows(F=15050),
        futures_date="2026-11-12",
    )
    write_snapshot(tmp_path, good2)
    bt = run_credit_vertical_bt(tmp_path, codes=["CF"], write=False)
    skipped = [t for t in bt["trades"] if t.get("reason") == "quality_reject"]
    assert len(skipped) >= 1
