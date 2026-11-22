# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from research.shadow_perf.attribution import (
    build_attribution_tables,
    build_shadow_attribution,
    enrich_trades,
)


def test_enrich_and_tables_basic(tmp_path: Path):
    (tmp_path / "universe.json").write_text(
        json.dumps({"symbols": [{"code": "CF", "bucket": "农产品", "name": "棉花", "mult": 5}]}),
        encoding="utf-8",
    )
    closed = [
        {
            "code": "CF",
            "direction": "多",
            "entry_date": "2026-01-02",
            "date": "2026-01-05",
            "entry": 100.0,
            "exit": 102.0,
            "reason": "target",
            "sleeve": "path_a_rr2",
            "fill_price_basis": "contract",
            "R": 1.0,
            "lots": 1,
        },
        {
            "code": "CF",
            "direction": "空",
            "entry_date": "2026-01-02",
            "date": "2026-01-03",
            "entry": 100.0,
            "exit": 101.0,
            "reason": "stop",
            "sleeve": "path_a_rr2",
            "fill_price_basis": "continuous_proxy",
            "R": -1.0,
            "lots": 1,
        },
    ]
    trades = enrich_trades(closed, root=tmp_path)
    assert len(trades) == 2
    assert trades[0]["bucket"] == "农产品"
    assert trades[0]["hold_bucket"] in {"2-3d", "4-7d", "0-1d"}
    tables = build_attribution_tables(trades)
    assert tables["by_exit_reason"]
    assert tables["regime_x_sleeve"]


def test_build_from_bt_file(tmp_path: Path):
    (tmp_path / "universe.json").write_text(
        json.dumps({"symbols": [{"code": "RB", "bucket": "黑色", "mult": 10}]}),
        encoding="utf-8",
    )
    bt = {
        "start": "2025-01-01",
        "end": "2026-01-01",
        "proxy_entry_share": 0.1,
        "cost_yuan": 100,
        "closed_pnls": [
            {
                "code": "RB",
                "direction": "多",
                "entry_date": "2025-06-01",
                "date": "2025-06-10",
                "entry": 3500,
                "exit": 3550,
                "reason": "target",
                "R": 0.5,
                "fill_price_basis": "contract",
                "sleeve": "path_a_rr2",
            }
        ],
    }
    bt_path = tmp_path / "historical_backtest_latest.json"
    bt_path.write_text(json.dumps(bt), encoding="utf-8")
    rep = build_shadow_attribution(tmp_path, write=True)
    assert rep["ok"] is True
    assert rep["n_trades"] == 1
    out = tmp_path / "lab" / "research" / "validation" / "shadow_attribution_latest.json"
    assert out.is_file()
