"""HV panel must not use future bars (roadmap §2.3 / P0-03)."""
import numpy as np
import pandas as pd

from desk.hv_panel import hv_stats


def test_hv_percentile_no_lookahead():
    rng = np.random.default_rng(1)
    idx = pd.date_range("2022-01-03", periods=900, freq="B").strftime("%Y-%m-%d")
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 900))), index=idx)
    cut = idx[700]
    a = hv_stats(close.loc[:cut])
    fut = close.copy()
    fut.iloc[701:] = fut.iloc[701:] * np.exp(np.cumsum(rng.normal(0, 0.08, 199)))  # wild future
    b = hv_stats(fut, asof=cut)
    assert a == b and a["bar_date"] == cut
