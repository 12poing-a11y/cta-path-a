# -*- coding: utf-8 -*-
"""Weekly KPI must use historical simulate — not paper_book overlay."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "ifind_call" not in sys.modules:
    stub = types.ModuleType("ifind_call")
    stub.active_slot = lambda *a, **k: None
    stub.call = lambda *a, **k: {}
    stub.usage_report = lambda: {"count": 0, "calls": []}
    sys.modules["ifind_call"] = stub

import historical_backtest as hb  # noqa: E402
import weekly_backtest as wb  # noqa: E402


def test_slice_curve_kpis():
    curve = [
        {"date": "2026-01-01", "equity": 100_000},
        {"date": "2026-01-02", "equity": 101_000},
        {"date": "2026-01-03", "equity": 99_000},
        {"date": "2026-01-04", "equity": 102_000},
    ]
    win = wb._slice_curve_kpis(curve, 2)
    assert win["window_start"] == "2026-01-02"
    assert win["window_end"] == "2026-01-04"
    assert win["window_trade_days"] == 2
    assert win["window_ret_pct"] == pytest.approx((102_000 / 101_000 - 1) * 100, rel=1e-3)


def test_weekly_run_uses_simulate_not_paper_overlay(monkeypatch, tmp_path):
    fake_sim = {
        "ok": True,
        "schema_version": hb.SCHEMA_VERSION,
        "start": "2025-12-01",
        "end": "2026-11-01",
        "trade_days": 200,
        "equity_end": 210_000.0,
        "ret_pct": 5.0,
        "max_dd_pct": 3.0,
        "gross_ret_pct": 6.0,
        "gross_max_dd_pct": 2.5,
        "cost_yuan": 1000.0,
        "win_rate": 45.0,
        "trade_win_rate": 42.0,
        "avg_held": 1.2,
        "closed_trades": 40,
        "conclusion": "继续L1",
        "fill_price": "next_open",
        "slippage_ticks": 1.0,
        "availability_lag": 1,
        "git_sha": "abc",
        "universe_sha256": "u",
        "execution_rules_sha256": "e",
        "mode": "seats",
        "exits": {"stop": 1},
        "equity_curve": [
            {"date": "2026-10-01", "equity": 200_000},
            {"date": "2026-10-02", "equity": 201_000},
            {"date": "2026-10-03", "equity": 202_000},
        ],
        "summary": "ok",
    }

    monkeypatch.setattr(
        hb,
        "_load_cfg",
        lambda: {
            "equity0": 200_000,
            "entry_filter": "seats",
            "fill_price": "next_open",
            "slippage_ticks": 1.0,
        },
    )
    monkeypatch.setattr(hb, "_simulate_cfg", lambda p, mode, **kw: dict(fake_sim))
    monkeypatch.setattr(wb, "_paper_book_equity", lambda: 999_999.0)
    monkeypatch.setattr(wb, "ROOT", tmp_path)

    # skip member backfill
    import member_rank

    monkeypatch.setattr(
        member_rank,
        "backfill_member_lookback",
        lambda **kw: {"days": 0, "dce": False, "eastmoney": False, "coverage_ok": True},
    )

    out = wb.run(7)
    assert out["ok"] is True
    assert out["engine"] == "historical_simulate"
    assert out["fill_price"] == "next_open"
    assert out["ret_pct"] == 5.0
    assert out["equity_end"] == 210_000.0
    assert out["paper_book_equity"] == 999_999.0
    assert out["cost_yuan"] == 1000.0
    assert out["ledger"] == "historical_simulate"
    # paper book must not overwrite headline return
    assert out["ret_pct"] != pytest.approx((999_999 / 200_000 - 1) * 100)
    written = json.loads((tmp_path / "weekly_backtest_latest.json").read_text(encoding="utf-8"))
    assert written["ret_pct"] == 5.0
