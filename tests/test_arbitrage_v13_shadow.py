# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

from research.arbitrage_shadow_monitor import (
    append_decision_ledger,
    assess_bar_data_quality,
    monitor_pair,
    summarize_universe,
)
from research.arbitrage_volatility import align_pair_bars


def _legs(n=180, noise=0.2):
    a_rows, b_rows = [], []
    start = date(2025, 1, 1)
    for i in range(n):
        day = (start + timedelta(days=i)).isoformat()
        b = 100.0 + i * 0.15
        a = 10.0 + 1.5 * b + math.sin(i / 3.0) * noise * (1 + (i % 17 == 0) * 3)
        a_rows.append({
            "date": day, "close": a, "open": a,
            "volume": 1000, "open_interest": 5000,
        })
        b_rows.append({
            "date": day, "close": b, "open": b,
            "volume": 1000, "open_interest": 5000,
        })
    return a_rows, b_rows


def test_data_quality_flags_gap_and_missing():
    prev = {"leg_a_close": 100.0, "leg_b_close": 200.0, "leg_a_volume": 1, "leg_b_volume": 1,
            "leg_a_oi": 1, "leg_b_oi": 1}
    row = {"leg_a_close": 108.0, "leg_b_close": 200.0, "leg_a_volume": 1, "leg_b_volume": 1,
           "leg_a_oi": 1, "leg_b_oi": 1}
    dq = assess_bar_data_quality(row, prev_row=prev, roll_gap_pct=0.05)
    assert "suspected_roll_or_gap" in dq["reasons"]
    bad = assess_bar_data_quality({"leg_a_close": None, "leg_b_close": 1.0})
    assert bad["status"] == "BLOCK_DQ"


def test_monitor_pair_emits_dual_path_fields():
    a, b = _legs()
    rows = align_pair_bars(a, b)["rows"]
    sa = {"code": "A", "mult": 10.0, "tick": 1.0, "fee_yuan": 1.0, "fee_rate": 0.0,
          "margin_rate": 0.12, "limit_pct": 0.07}
    sb = {"code": "B", "mult": 10.0, "tick": 1.0, "fee_yuan": 1.0, "fee_rate": 0.0,
          "margin_rate": 0.12, "limit_pct": 0.07}
    out = monitor_pair(
        rows, pair_id="A/B", spec_a=sa, spec_b=sb,
        require_cointegration=False, start=rows[90]["date"],
    )
    assert out["ok"]
    assert "dual_path" in out
    assert out["decisions"]
    sample = out["decisions"][-1]
    for key in (
        "timestamp", "symbol", "strategy_id", "gate_status", "block_reason",
        "suggested_lots", "data_quality_status", "model_version", "counterfactual_pnl",
    ):
        assert key in sample
    assert sample["mode"] == "shadow_only"


def test_ledger_append_only(tmp_path: Path):
    path = tmp_path / "ledger.jsonl"
    n1 = append_decision_ledger(path, [{"timestamp": "2026-01-01", "x": 1}])
    n2 = append_decision_ledger(path, [{"timestamp": "2026-01-02", "x": 2}])
    assert n1 == 1 and n2 == 1
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_summarize_universe_aggregates():
    fake = [{
        "pair": "A/B",
        "n_signal": 2,
        "n_pass": 1,
        "n_block": 1,
        "block_reason_counts": {"cointegration_failed": 3},
        "data_quality_counts": {"missing_volume": 1},
        "dual_path": {
            "gated_signal_pnl_sum": 10.0,
            "counterfactual_all_signal_pnl_sum": 20.0,
            "blocked_only_counterfactual_pnl_sum": 5.0,
        },
        "decisions": [{"timestamp": "x"}],
    }]
    s = summarize_universe(fake)
    assert s["mode"] == "shadow_v1_3_monitor"
    assert s["block_reason_counts"]["cointegration_failed"] == 3
    assert s["dual_path_totals"]["n_signal"] == 2
    assert "decisions" not in s["pairs"][0]
