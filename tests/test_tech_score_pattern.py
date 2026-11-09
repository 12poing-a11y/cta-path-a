# -*- coding: utf-8 -*-
"""K-line structure labels: 上升 / 下降 / 箱体震荡."""
from __future__ import annotations

import pandas as pd

from desk.tech_score_panel import _kline_pattern


def _df(closes: list[float]) -> pd.DataFrame:
    rows = []
    for i, c in enumerate(closes):
        rows.append(
            {
                "date": f"2026-01-{i+1:02d}" if i < 28 else f"2026-02-{i-27:02d}",
                "open": c * 0.999,
                "high": c * 1.004,
                "low": c * 0.996,
                "close": c,
            }
        )
    return pd.DataFrame(rows)


def test_uptrend_label():
    base = [100 + i * 0.8 for i in range(20)]
    assert _kline_pattern(_df(base)) == "上升"


def test_downtrend_label():
    base = [120 - i * 0.8 for i in range(20)]
    assert _kline_pattern(_df(base)) == "下降"


def test_box_label():
    # Oscillate in a tight band
    base = [100 + (1.2 if i % 2 == 0 else -1.0) for i in range(20)]
    assert _kline_pattern(_df(base)) == "箱体震荡"


def test_short_sample():
    assert _kline_pattern(_df([100.0, 101.0, 102.0])) == "样本不足"
