# -*- coding: utf-8 -*-
"""Stage-0: anti-lookahead invariants for Path-A-style signals & sleeve proxy."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paper_sleeves import (  # noqa: E402
    donchian_signal_series,
    mr_signal_series,
    path_a_momentum_signal_series,
    xs_mom_weights_on_day,
)


def _bars(n: int = 80, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    open_ = close + rng.normal(0, 0.2, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1e6},
        index=idx,
    )


def test_path_a_signal_stable_when_future_bars_appended():
    bars = _bars(90)
    early = bars.iloc[:60]
    s_early = path_a_momentum_signal_series(early)
    s_full = path_a_momentum_signal_series(bars)
    assert s_early.index[-1] in s_full.index
    a = float(s_early.iloc[-1])
    b = float(s_full.loc[s_early.index[-1]])
    if math.isnan(a) and math.isnan(b):
        return
    assert a == b


def test_donchian_uses_prior_window_not_same_day_high():
    idx = pd.date_range("2024-01-01", periods=25, freq="B")
    close = np.full(25, 100.0)
    high = np.full(25, 101.0)
    low = np.full(25, 99.0)
    close[20] = 101.5
    high[20] = 102.0
    bars = pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": 1.0},
        index=idx,
    )
    sig = donchian_signal_series(bars, window=20)
    assert int(sig.iloc[20]) == 1
    assert int(sig.iloc[19]) == 0


def test_mr_signal_length_matches_bars():
    bars = _bars(50)
    s = mr_signal_series(bars)
    assert len(s) == len(bars)


def test_xs_mom_weights_sum_near_zero_when_balanced():
    day = pd.Timestamp("2024-06-03")
    panel = {
        "A": pd.Series([0.10], index=[day]),
        "B": pd.Series([-0.10], index=[day]),
        "C": pd.Series([0.01], index=[day]),
        "D": pd.Series([-0.01], index=[day]),
    }
    w = xs_mom_weights_on_day(panel, day, top_n=1)
    assert abs(sum(w.values())) < 1e-9
    assert set(w) <= {"A", "B", "C", "D"}
