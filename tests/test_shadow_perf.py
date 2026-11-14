# -*- coding: utf-8 -*-
"""Shadow attribution ledger + category win-rate aggregation."""
from __future__ import annotations

import json
from pathlib import Path

from research.shadow_perf.ledger import (
    HORIZONS,
    MIN_SAMPLE,
    SCHEMA,
    aggregate_summary,
    backfill_row,
    extract_l1_candidates,
    extract_sentiment_candidates,
    refresh_shadow_perf,
    upsert_candidates,
)


def _closes_trend() -> dict[str, float]:
    # 10 sessions; asof day0 = 2026-11-03
    days = [
        "2026-11-03",
        "2026-11-04",
        "2026-11-05",
        "2026-11-06",
        "2026-11-07",
        "2026-11-10",
        "2026-11-11",
        "2026-11-12",
        "2026-11-13",
        "2026-11-14",
    ]
    px = 100.0
    out = {}
    for i, d in enumerate(days):
        px *= 1.01  # +1%/day → long wins
        out[d] = round(px, 4)
    return out


def test_extract_l1_and_selected():
    report = {
        "asof": "20261113",
        "signals": [
            {
                "code": "MA",
                "name": "甲醇",
                "bucket": "能化",
                "direction": "多",
                "align": "同向",
                "close": 3000,
                "stop": 2900,
                "target": 3200,
                "atr": 100,
                "selected": True,
            },
            {
                "code": "V",
                "name": "PVC",
                "bucket": "能化",
                "direction": "空仓",
                "align": "冲突/不足",
                "close": 5000,
                "selected": False,
            },
            {
                "code": "RB",
                "name": "螺纹",
                "bucket": "黑色",
                "direction": "空",
                "align": "同向",
                "close": 3500,
                "stop": 3600,
                "atr": 80,
                "selected": False,
            },
        ],
    }
    rows = extract_l1_candidates(report)
    ids = {r["id"] for r in rows}
    assert "path_a|MA|2026-11-13|long" in ids
    assert "path_a_selected|MA|2026-11-13|long" in ids
    assert "path_a|RB|2026-11-13|short" in ids
    assert not any(r["code"] == "V" for r in rows)
    assert all(r["schema"] == SCHEMA for r in rows)
    assert all(r["live_trading"] is False for r in rows)


def test_extract_sentiment():
    snap = {
        "asof": "20261113",
        "symbols": [
            {"code": "MA", "signal": 1, "w_norm": 0.1},
            {"code": "SP", "signal": -1, "w_norm": 0.05},
            {"code": "AU", "signal": 0, "w_norm": 0.1},
        ],
    }
    uni = {"MA": {"bucket": "能化", "name": "甲醇"}, "SP": {"bucket": "能化", "name": "纸浆"}}
    rows = extract_sentiment_candidates(snap, universe=uni)
    assert len(rows) == 2
    assert rows[0]["strategy_id"] == "sentiment_mds"
    assert {r["code"] for r in rows} == {"MA", "SP"}


def test_backfill_and_aggregate():
    closes = _closes_trend()
    row = {
        "schema": SCHEMA,
        "id": "path_a|MA|2026-11-03|long",
        "asof": "2026-11-03",
        "code": "MA",
        "bucket": "能化",
        "strategy_id": "path_a",
        "side": 1,
        "entry_px": closes["2026-11-03"],
        "stop": closes["2026-11-03"] * 0.99,
        "atr": 1.0,
        "fwd": {},
        "status": "open",
        "live_trading": False,
    }
    filled = backfill_row(row, closes)
    assert filled["status"] == "closed"
    assert filled["fwd"]["1"]["hit"] is True
    assert filled["fwd"]["1"]["ret"] > 0
    assert filled["fwd"]["3"]["r_mult"] is not None

    short = {
        **row,
        "id": "path_a|MA|2026-11-03|short",
        "side": -1,
        "stop": closes["2026-11-03"] * 1.01,
    }
    filled_s = backfill_row(short, closes)
    assert filled_s["fwd"]["1"]["hit"] is False

    summary = aggregate_summary([filled, filled_s], horizon=1)
    assert summary["min_sample"] == MIN_SAMPLE
    assert summary["horizon"] == 1
    bucket = summary["by_bucket"]
    assert len(bucket) == 1
    assert bucket[0]["n"] == 2
    assert bucket[0]["win_rate_pct"] == 50.0
    assert bucket[0]["enough"] is False  # n < 20


def test_upsert_preserves_fwd():
    a = {
        "id": "path_a|MA|2026-11-13|long",
        "asof": "2026-11-13",
        "code": "MA",
        "strategy_id": "path_a",
        "side": 1,
        "entry_px": 100,
        "fwd": {"1": {"ret": 0.01, "hit": True}},
        "status": "partial",
    }
    b = {
        "id": "path_a|MA|2026-11-13|long",
        "asof": "2026-11-13",
        "code": "MA",
        "strategy_id": "path_a",
        "side": 1,
        "entry_px": 101,
        "fwd": {},
        "status": "open",
    }
    merged = upsert_candidates([a], [b])
    assert len(merged) == 1
    assert merged[0]["entry_px"] == 101
    assert merged[0]["fwd"]["1"]["hit"] is True
    assert merged[0]["status"] == "partial"


def test_refresh_writes(tmp_path: Path):
    # Minimal universe + L1 + history closes
    (tmp_path / "universe.json").write_text(
        json.dumps(
            {
                "symbols": [
                    {"code": "MA", "name": "甲醇", "bucket": "能化", "mult": 10},
                    {"code": "RB", "name": "螺纹", "bucket": "黑色", "mult": 10},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    closes = _closes_trend()
    bars = [{"date": d, "close": px} for d, px in closes.items()]
    hist = tmp_path / ".cache" / "history"
    hist.mkdir(parents=True)
    (hist / "MA0.json").write_text(json.dumps(bars), encoding="utf-8")
    (hist / "RB0.json").write_text(json.dumps(bars), encoding="utf-8")

    asof = "2026-11-03"
    report = {
        "asof": "20261103",
        "signals": [
            {
                "code": "MA",
                "name": "甲醇",
                "bucket": "能化",
                "direction": "多",
                "align": "同向",
                "close": closes[asof],
                "stop": closes[asof] * 0.99,
                "atr": 1.0,
                "selected": True,
            },
            {
                "code": "RB",
                "name": "螺纹",
                "bucket": "黑色",
                "direction": "空",
                "align": "同向",
                "close": closes[asof],
                "stop": closes[asof] * 1.01,
                "atr": 1.0,
                "selected": False,
            },
        ],
    }
    (tmp_path / "l1_report_risk15.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )
    shadow = tmp_path / "data" / "sentiment_mds" / "shadow"
    shadow.mkdir(parents=True)
    (shadow / "sentiment_20261103.json").write_text(
        json.dumps(
            {
                "asof": "20261103",
                "live": False,
                "symbols": [
                    {"code": "MA", "signal": 1, "w_norm": 0.1},
                    {"code": "RB", "signal": -1, "w_norm": 0.1},
                ],
            }
        ),
        encoding="utf-8",
    )

    # Avoid writing into real experiments ledger
    exp = tmp_path / "data" / "experiments"
    exp.mkdir(parents=True)

    out = refresh_shadow_perf(tmp_path, asof=asof, write=True)
    assert out["ok"] is True
    assert out["n_ledger"] >= 4  # path_a×2 + selected×1 + sentiment×2 = 5
    summary_path = tmp_path / "data" / "shadow_perf" / "summary_latest.json"
    ledger_path = tmp_path / "data" / "shadow_perf" / "ledger.jsonl"
    assert summary_path.is_file()
    assert ledger_path.is_file()
    pack = json.loads(summary_path.read_text(encoding="utf-8"))
    assert pack["schema"] == SCHEMA
    assert pack["live_trading"] is False
    assert str(HORIZONS[0]) in pack["summaries"]
    by_bucket = pack["summary"]["by_bucket"]
    assert any(r["bucket"] == "能化" for r in by_bucket)
