# -*- coding: utf-8 -*-
"""Unit tests for Volatility Engine V1 (pure functions, no network)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vol_engine import (  # noqa: E402
    calendar_candidate,
    iv_percentile_series,
    iv_velocity,
    percentile_rank,
    realized_vol_series,
    rv_percentile_at,
    select_strategy,
    sentiment_tier,
    trend_score_pack,
    vol_pricing_score,
    vol_state_score,
    vrp_value,
)
from desk.vol_engine_panel import board_conclusion  # noqa: E402


def _synth_closes(n: int = 300, *, vol: float = 0.01, seed: float = 100.0) -> list[float]:
    """Deterministic geometric path with constant vol (approx)."""
    closes = [seed]
    x = seed
    for i in range(1, n):
        # Alternate small moves → stable RV; later amplify for percentile contrast.
        shock = vol * (1.0 if (i % 2 == 0) else -0.8)
        if i > 250:
            shock *= 2.5
        x = x * (1.0 + shock)
        closes.append(x)
    return closes


def test_percentile_rank_basic():
    assert percentile_rank([1.0, 2.0, 3.0, 4.0], 3.0) == 75.0
    assert percentile_rank([], 1.0) is None
    pct = percentile_rank([1.0, 2.0, 3.0], 1.0)
    assert pct is not None
    assert abs(pct - 100.0 / 3.0) < 1e-9


def test_realized_vol_and_rv_percentile():
    closes = _synth_closes(320)
    series = realized_vol_series(closes, win=20)
    assert series[19] is None
    assert series[20] is not None
    assert series[20] > 0
    pack = rv_percentile_at(closes, win=20, lookback=250)
    assert pack["ok"] is True
    assert pack["rv20"] is not None
    assert 0.0 <= float(pack["rv_pct"]) <= 100.0
    # Late amplified vol → elevated percentile
    assert float(pack["rv_pct"]) >= 50.0


def test_iv_percentile_and_thin():
    dates = [f"202601{i:02d}" for i in range(1, 16)]  # 15 days → thin
    iv = {d: 0.20 + i * 0.001 for i, d in enumerate(dates)}
    pack = iv_percentile_series(iv, dates, thin_n=20)
    assert pack["ok"] is True
    assert pack["iv_thin"] is True
    assert pack["iv_pct"] == 100.0  # latest is max


def test_vrp_and_velocity():
    assert vrp_value(0.25, 0.20) == 0.05
    assert vrp_value(None, 0.2) is None
    dates = [f"202602{i:02d}" for i in range(1, 25)]
    iv = {d: 0.20 + (0.01 if i > 20 else 0.0) for i, d in enumerate(dates)}
    # Rising into last days → positive delta
    iv[dates[-1]] = 0.28
    iv[dates[-2]] = 0.22
    vel = iv_velocity(iv, dates, z_win=20)
    assert vel["ok"] is True
    assert vel["delta_iv"] is not None
    assert vel["delta_iv"] > 0


def test_vol_state_and_pricing():
    st = vol_state_score(20.0, 25.0)
    assert st["label"] == "low"
    st2 = vol_state_score(80.0, 75.0)
    assert st2["label"] == "high"
    pr = vol_pricing_score(vrp=0.06, iv_pct=80.0, vrp_sell_min=0.03)
    assert pr["label"] == "rich"
    pr2 = vol_pricing_score(vrp=-0.04, iv_pct=20.0, vrp_sell_min=0.03)
    assert pr2["label"] == "cheap"


def test_select_buy_vol_breakout():
    m = select_strategy(
        rv_pct=20.0,
        iv_pct=25.0,
        vrp=-0.01,
        iv_z=0.2,
        delta_iv=0.002,
        breakout_side=1,
        breakout_iv_tag="true_candidate",
        iv_thin=False,
    )
    assert m["tag"] in ("buy_vol_breakout", "buy_call_or_put")
    assert m["buy_vol"] is True


def test_select_sell_vol_credit_spread():
    m = select_strategy(
        rv_pct=55.0,
        iv_pct=85.0,
        vrp=0.05,
        iv_z=-1.2,
        delta_iv=-0.01,
        breakout_side=0,
        breakout_iv_tag="iv_missing",
        iv_thin=False,
    )
    assert m["tag"] == "sell_vol_credit_spread"
    assert m["sell_vol"] is True


def test_select_false_breakout_no_trade():
    m = select_strategy(
        rv_pct=15.0,
        iv_pct=20.0,
        vrp=0.0,
        iv_z=-0.1,
        delta_iv=-0.006,
        breakout_side=1,
        breakout_iv_tag="false_suspect",
        iv_thin=False,
    )
    assert m["tag"] == "no_trade"
    assert m["false_breakout"] is True


def test_select_conflict_buy_sell_no_trade():
    # Strong true breakout + high IV: buy suppressed (iv_high), sell blocked (strong_bo).
    m = select_strategy(
        rv_pct=10.0,
        iv_pct=90.0,
        vrp=0.08,
        iv_z=-1.0,
        delta_iv=-0.02,
        breakout_side=1,
        breakout_iv_tag="true_candidate",
        iv_thin=False,
    )
    assert m["tag"] == "no_trade"

    # Low IV + true breakout → buy wins.
    m2 = select_strategy(
        rv_pct=10.0,
        iv_pct=25.0,
        vrp=0.08,
        iv_z=-1.0,
        delta_iv=-0.02,
        breakout_side=1,
        breakout_iv_tag="true_candidate",
        iv_thin=False,
    )
    assert m2["buy_vol"] is True

    # Conflict: low RV (buy) + high IV falling without strong true breakout (sell).
    # buy uses rv_low + iv_missing breakout; sell uses iv_high — both fire → no_trade.
    m3 = select_strategy(
        rv_pct=15.0,
        iv_pct=85.0,
        vrp=0.08,
        iv_z=-1.0,
        delta_iv=-0.02,
        breakout_side=1,
        breakout_iv_tag="iv_missing",
        iv_thin=False,
    )
    # iv_high suppresses buy tags; sell alone.
    assert m3["tag"] == "sell_vol_credit_spread"


def test_calendar_candidate():
    hit = calendar_candidate(0.35, 0.25, ratio_min=1.15)
    assert hit["tag"] == "calendar_candidate"
    miss = calendar_candidate(0.26, 0.25, ratio_min=1.15)
    assert miss["tag"] is None


def test_trend_score_pack():
    t = trend_score_pack(path_a_side=1, path_a_selected=True, mom_side=1, breakout_side=1)
    assert t["side"] == 1
    assert t["score"] > 50
    t2 = trend_score_pack(path_a_side=-1, path_a_selected=False, mom_side=0, breakout_side=0)
    assert t2["side"] == -1


def test_board_conclusion_priority():
    # 1) TP alert
    c = board_conclusion(
        final_action="止盈预警",
        matrix_tag="buy_vol_breakout",
        false_breakout=False,
        path_a_selected=True,
        path_a_side="多",
        breakout_side=1,
        buy_vol=True,
        sell_vol=False,
        trend_side=1,
    )
    assert c["结论"] == "止盈预警"
    assert c["优先级"] == 1

    # 2) no_trade / false breakout
    c2 = board_conclusion(
        final_action="观望",
        matrix_tag="no_trade",
        false_breakout=True,
        path_a_selected=False,
        path_a_side=None,
        breakout_side=1,
        buy_vol=False,
        sell_vol=False,
        trend_side=0,
    )
    assert c2["结论"] == "观望"
    assert c2["优先级"] == 2

    # 3) Path-A + same breakout + buy
    c3 = board_conclusion(
        final_action="建议开",
        matrix_tag="buy_vol_breakout",
        false_breakout=False,
        path_a_selected=True,
        path_a_side="多",
        breakout_side=1,
        buy_vol=True,
        sell_vol=False,
        trend_side=1,
    )
    assert c3["结论"] == "偏多研究"
    assert c3["优先级"] == 3

    # 4) sell vol annotate
    c4 = board_conclusion(
        final_action="观望",
        matrix_tag="sell_vol_credit_spread",
        false_breakout=False,
        path_a_selected=False,
        path_a_side=None,
        breakout_side=0,
        buy_vol=False,
        sell_vol=True,
        trend_side=0,
    )
    assert c4["结论"] == "波动率卖方研究"
    assert c4.get("annotate_only") is True


def test_no_math_nan_in_rv():
    closes = [100.0 + i * 0.1 for i in range(100)]
    series = realized_vol_series(closes, win=20)
    vals = [v for v in series if v is not None]
    assert vals
    assert all(math.isfinite(v) for v in vals)


def test_sentiment_tier_buckets():
    assert sentiment_tier(direction="多", conviction_pct=20, ref_side=1)["tier"] == "neutral"
    assert sentiment_tier(direction="多", conviction_pct=50, ref_side=1)["tier"] == "aligned"
    assert (
        sentiment_tier(direction="多", conviction_pct=80, ref_side=1)["tier"] == "extreme_crowd"
    )
    assert (
        sentiment_tier(direction="空", conviction_pct=65, ref_side=1)["tier"] == "opposed_hard"
    )
    assert (
        sentiment_tier(direction="空", conviction_pct=45, ref_side=1)["tier"] == "opposed_soft"
    )


def test_select_opposed_hard_kills_buy_vol():
    sent = sentiment_tier(direction="空", conviction_pct=70, ref_side=1)
    m = select_strategy(
        rv_pct=20.0,
        iv_pct=25.0,
        vrp=-0.01,
        iv_z=0.2,
        delta_iv=0.002,
        breakout_side=1,
        breakout_iv_tag="true_candidate",
        iv_thin=False,
        sentiment=sent,
    )
    assert m["buy_vol"] is False
    assert m["tag"] == "no_trade"
    assert m["sentiment_tier"] == "opposed_hard"


def test_select_extreme_crowd_rich_kills_buy():
    sent = sentiment_tier(direction="多", conviction_pct=80, ref_side=1)
    m = select_strategy(
        rv_pct=20.0,
        iv_pct=25.0,
        vrp=-0.01,
        iv_z=0.2,
        delta_iv=0.002,
        breakout_side=1,
        breakout_iv_tag="true_candidate",
        iv_thin=False,
        sentiment=sent,
        pricing_label="rich",
    )
    assert m["buy_vol"] is False


def test_board_opposed_hard_priority():
    c = board_conclusion(
        final_action="建议开",
        matrix_tag="buy_vol_breakout",
        false_breakout=False,
        path_a_selected=True,
        path_a_side="多",
        breakout_side=1,
        buy_vol=True,
        sell_vol=False,
        trend_side=1,
        sentiment_tier="opposed_hard",
    )
    assert c["结论"] == "观望"
    assert "情绪硬反向" in str(c.get("note") or "")
