from datetime import datetime
from pathlib import Path

import pandas as pd

from desk.freshness import TZ, desk_freshness, expected_cutoffs
from desk.hv_panel import hv_stats

ROOT = Path(__file__).resolve().parents[1]


def _t(s):
    return datetime.fromisoformat(s).replace(tzinfo=TZ)


def test_cutoffs_weekend_and_intraday():
    assert expected_cutoffs(_t("2026-10-31 09:00"))["day_ymd"] == "20261030"
    assert expected_cutoffs(_t("2026-10-30 10:00"))["day_ymd"] == "20261029"
    assert expected_cutoffs(_t("2026-10-30 16:00"))["day_ymd"] == "20261030"
    assert expected_cutoffs(_t("2026-11-02 08:00"))["night_ymd"] == "20261030"


def test_freshness_never_claims_night(tmp_path):
    (tmp_path / "l1_report.json").write_text('{"asof":"20261029","signals":[{"code":"CU"}]}', encoding="utf-8")
    f = desk_freshness(tmp_path, now=_t("2026-10-30 22:00"))
    assert f["includes_night"] is False
    assert f["stale"] and f["status"] == "待核"
    f2 = desk_freshness(tmp_path, now=_t("2026-10-30 10:00"))
    assert not f2["stale"]


def test_hv_stats_constant_vol():
    import numpy as np

    rng = np.random.default_rng(0)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 800))))
    st = hv_stats(close)
    assert 10 < st["HV20%"] < 25 and 0 <= st["HV20分位"] <= 100
