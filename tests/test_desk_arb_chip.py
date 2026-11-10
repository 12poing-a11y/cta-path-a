# -*- coding: utf-8 -*-
import pandas as pd

from desk.arb_panel import (
    calendar_side_hint,
    cross_side_hint,
    rank_by_abs_z,
    top_opportunities,
)
from desk.chart_flow import volume_profile, vp_title
from desk.curve_lag import curve_end_date, curve_lag


def test_side_hints():
    assert calendar_side_hint(2.0) == "近贵·观察卖近买远"
    assert calendar_side_hint(-2.0) == "近便宜·观察买近卖远"
    assert calendar_side_hint(0.3) == "—"
    assert cross_side_hint(1.8, "RB", "I") == "A/B偏高·观察卖RB买I"
    assert cross_side_hint(-1.8, "螺纹钢 RB", "铁矿石 I") == "A/B偏低·观察买螺纹钢 RB卖铁矿石 I"


def test_zh_front_label():
    from desk.arb_panel import zh_front_label

    assert zh_front_label("CF", {"CF": "棉花"}) == "棉花 CF"
    assert zh_front_label("MA", {"MA": "甲醇"}) == "甲醇 MA"
    assert zh_front_label("XX", {}) == "XX"


def test_rank_and_top():
    cal = pd.DataFrame(
        {
            "品种": ["A", "B", "C"],
            "Z(60)": [0.2, -2.5, None],
            "方向提示": ["—", calendar_side_hint(-2.5), "—"],
        }
    )
    cross = pd.DataFrame(
        {"配对": ["X/Y"], "Z(60)": [1.9], "方向提示": [cross_side_hint(1.9, "X", "Y")]}
    )
    r = rank_by_abs_z(cal)
    assert list(r["品种"]) == ["B", "A", "C"]
    assert r.loc[0, "潜在机会"] != "" and r.loc[1, "潜在机会"] == ""
    top = top_opportunities(r, rank_by_abs_z(cross))
    assert list(top["标的"]) == ["B", "X/Y"]


def test_vp_lookback_changes_window():
    bars = [
        {"high": 10 + i, "low": 9 + i, "close": 9.5 + i, "volume": 100} for i in range(300)
    ]
    short = volume_profile(bars, lookback=20)
    long_ = volume_profile(bars, lookback=250)
    assert short["price"].min() > 280  # last 20 bars only
    assert long_["price"].min() < 100  # last 250 bars reach back further
    assert vp_title(120, 300) == "近120日成交量分布（价轴）"
    assert "实际仅30日" in vp_title(60, 30)


def test_curve_lag_no_future_bars():
    payload = {"equity_curve": [{"date": "2026-11-02", "equity": 1.0}, {"date": "2026-11-06", "equity": 1.1}]}
    assert curve_end_date(payload) == "2026-11-06"
    info = curve_lag("2026-11-06", "2026-11-10")
    assert info["lag_days"] == 4 and info["lag_busdays"] == 2 and info["stale"]
    assert not curve_lag("2026-11-10", "2026-11-10")["stale"]
    assert curve_lag(None, "2026-11-10")["lag_days"] is None
