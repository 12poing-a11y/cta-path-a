# -*- coding: utf-8 -*-
from __future__ import annotations

from lab.ml.labels import lsp_reversal_rows
from lab.ml.train import train_binary_task


def test_lsp_rows_no_leakage_keys():
    events = [
        {
            "outcome": "fake_break_reversal",
            "timestamp": "2026-09-04 21:15:00",
            "break_size_atr": 0.5,
            "volume_ratio": 1.2,
            "distance_to_level": 0.1,
            "atr": 30.0,
            "htf_resonance": False,
            "break_direction": "up",
            "level_type": "swing_high",
            "mfe": 9.9,  # must not become a feature
            "mae": 9.9,
            "post_sweep_return_1": 0.01,
        },
        {
            "outcome": "true_break_continuation",
            "timestamp": "2026-09-05 10:00:00",
            "break_size_atr": 0.8,
            "volume_ratio": 0.9,
            "distance_to_level": -0.2,
            "atr": 28.0,
            "htf_resonance": True,
            "break_direction": "down",
            "level_type": "swing_low",
        },
    ]
    rows = lsp_reversal_rows(events)
    assert len(rows) == 2
    assert rows[0]["y"] == 1 and rows[1]["y"] == 0
    assert "mfe" not in rows[0]["features"]
    assert "post_sweep_return_1" not in rows[0]["features"]


def test_train_binary_synthetic():
    from datetime import date, timedelta

    rows = []
    d0 = date(2026, 1, 1)
    for i in range(80):
        y = 1 if i % 3 == 0 else 0
        rows.append(
            {
                "task": "t",
                "timestamp": (d0 + timedelta(days=i)).isoformat(),
                "y": y,
                "features": {"a": float(y) + 0.01 * i, "b": float(i % 5), "c": 1.0},
            }
        )
    out = train_binary_task(rows, task="synthetic", oos_frac=0.25, purge=5, embargo=3)
    assert out["ok"]
    assert out["oos"]["n"] >= 10
    assert out.get("purge") == 5
    assert out.get("embargo") == 3
