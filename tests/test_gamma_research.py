# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from lab.gamma.iv_oi import summarize_raw_day, iv_oi_joint_series
from lab.gamma.migration import classify_wall_migration
from lab.gamma.touch_study import touch_event_study
from lab.gamma.pipeline import run_gamma_research, save_gamma_research


def test_migration_on_real_or_skip():
    root = Path(__file__).resolve().parents[1]
    hist = root / "data" / "gamma_wall" / "CF2701"
    if not hist.exists() or len(list(hist.glob("*.json"))) < 2:
        return
    out = classify_wall_migration("CF2701", root=root)
    assert out["ok"]
    assert out["n_events"] >= 1


def test_iv_oi_summarize_tmp(tmp_path):
    rows = [
        {"合约代码": "CF701C15000", "持仓量": 100, "隐含波动率": 25.0},
        {"合约代码": "CF701P15000", "持仓量": 80, "隐含波动率": 30.0},
    ]
    p = tmp_path / "CF_2026-11-01.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    s = summarize_raw_day(p, product="CF")
    assert s and s["oi_total"] == 180
    assert 0.2 < s["iv_oi_weighted"] < 0.4


def test_touch_study_synthetic(tmp_path, monkeypatch):
    # Build minimal history via monkeypatch load_history
    snaps = [
        {
            "asof": "2026-01-20",
            "futures_price": 100.0,
            "call_wall": 102.0,
            "put_wall": 95.0,
            "data_quality": {"status": "PASS"},
        },
        {
            "asof": "2026-01-21",
            "futures_price": 101.5,
            "call_wall": 102.0,
            "put_wall": 95.0,
            "data_quality": {"status": "PASS"},
        },
    ]
    import lab.gamma.touch_study as ts

    monkeypatch.setattr(ts, "load_history", lambda contract, root=None: snaps)
    bars = []
    px = 100.0
    from datetime import date, timedelta

    d0 = date(2026, 1, 1)
    for i in range(40):
        d = d0 + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        bars.append({"date": d.isoformat(), "open": px, "high": px + 1, "low": px - 1, "close": px})
        px += 0.1
    # ensure touch dates exist
    bars.append({"date": "2026-01-20", "open": 100, "high": 101, "low": 99, "close": 100})
    bars.append({"date": "2026-01-21", "open": 101, "high": 102.5, "low": 100.5, "close": 101.5})
    bars.append({"date": "2026-01-22", "open": 101, "high": 101.2, "low": 99.5, "close": 100})
    bars.append({"date": "2026-01-23", "open": 100, "high": 100.5, "low": 99, "close": 99.5})
    bars.append({"date": "2026-01-24", "open": 99.5, "high": 100, "low": 98.5, "close": 99})
    out = touch_event_study("CF2701", bars, touch_atr=2.0)
    assert out["ok"]


def test_pipeline_save(tmp_path):
    root = Path(__file__).resolve().parents[1]
    if not (root / "data" / "gamma_wall" / "CF2701").exists():
        return
    payload = run_gamma_research("CF2701", root=root)
    assert payload["ok"]
    path = save_gamma_research(payload, root=tmp_path)
    assert (tmp_path / path).is_file()
