# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.sentiment_history import _close_series, shadow_history_frame  # noqa: E402


def test_close_series_extends_stale_history_with_newer_sina(tmp_path: Path):
    hist = tmp_path / ".cache" / "history"
    hist.mkdir(parents=True)
    (hist / "RB0.json").write_text(
        json.dumps(
            [
                {"date": "2026-11-12", "close": 100.0},
                {"date": "2026-11-13", "close": 101.0},
            ]
        ),
        encoding="utf-8",
    )
    day = tmp_path / ".cache" / "sina" / "2026-11-20"
    day.mkdir(parents=True)
    (day / "RB0.json").write_text(
        json.dumps(
            [
                {"date": "2026-11-13", "close": 101.5},
                {"date": "2026-11-16", "close": 102.0},
                {"date": "2026-11-17", "close": 103.0},
            ]
        ),
        encoding="utf-8",
    )
    closes = _close_series(tmp_path)
    s = closes["RB"]
    assert list(s.index) == ["20261112", "20261113", "20261116", "20261117"]
    assert float(s["20261113"]) == 101.5  # newer sina wins on overlap
    assert float(s["20261117"]) == 103.0


def test_shadow_frame_fills_next_day_when_sina_extends(tmp_path: Path):
    shadow = tmp_path / "data" / "sentiment_mds" / "shadow"
    shadow.mkdir(parents=True)
    (shadow / "sentiment_20261116.json").write_text(
        json.dumps(
            {
                "asof": "20261116",
                "portfolio_p3": 0.1,
                "stance": "risk_on",
                "n": 1,
                "longs": ["RB"],
                "shorts": [],
                "live": False,
                "symbols": [
                    {"code": "RB", "signal": 1, "w_norm": 1.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    day = tmp_path / ".cache" / "sina" / "2026-11-20"
    day.mkdir(parents=True)
    (day / "RB0.json").write_text(
        json.dumps(
            [
                {"date": "2026-11-16", "close": 100.0},
                {"date": "2026-11-17", "close": 101.0},
            ]
        ),
        encoding="utf-8",
    )
    df = shadow_history_frame(tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["次日覆盖"] == 1
    assert abs(float(df.iloc[0]["次日等权%"]) - 1.0) < 1e-6
    assert abs(float(df.iloc[0]["次日影子组合%"]) - 1.0) < 1e-6
