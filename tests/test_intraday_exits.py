# -*- coding: utf-8 -*-
"""Path-A intraday stop/target (15m first-touch) + exit_condition text."""
from __future__ import annotations

import json
from pathlib import Path

from paper_book import exit_condition_text
from wyckoff_pullback import (
    apply_stop_target,
    apply_stop_target_intraday,
    minute_bars_aligned_with_entry,
)

ROOT = Path(__file__).resolve().parents[1]


def test_intraday_target_before_later_stop_same_day():
    """Earlier 15m hits target; a later bar probing stop must not win."""
    bars = [
        {
            "datetime": "2026-11-11 09:45:00",
            "high": 101.0,
            "low": 99.5,
            "close": 100.8,
        },
        {
            "datetime": "2026-11-11 10:00:00",
            "high": 102.5,  # target 102
            "low": 100.0,
            "close": 102.2,
        },
        {
            "datetime": "2026-11-11 14:00:00",
            "high": 101.0,
            "low": 97.0,  # would be stop 98 if checked alone
            "close": 97.5,
        },
    ]
    reason, px = apply_stop_target_intraday("多", 100.0, 98.0, 102.0, bars)
    assert reason == "target" and px == 102.0


def test_intraday_stop_before_target_on_same_bar():
    bars = [
        {
            "datetime": "2026-11-11 10:00:00",
            "high": 103.0,  # also touches target
            "low": 97.0,  # touches stop first within bar
            "close": 99.0,
        }
    ]
    reason, px = apply_stop_target_intraday("多", 100.0, 98.0, 102.0, bars)
    assert reason == "stop" and px == 98.0


def test_daily_fallback_matches_apply_stop_target():
    bar = {"high": 103.0, "low": 97.0, "close": 99.0}
    a = apply_stop_target("多", 100.0, 98.0, 102.0, bar)
    # Empty minute list → no intraday hit (caller falls back to daily).
    b = apply_stop_target_intraday("多", 100.0, 98.0, 102.0, [])
    assert b == (None, None)
    assert a[0] == "stop"


def test_load_minute_bars_on_date_from_cache(tmp_path: Path):
    from minute_data import load_minute_bars_on_date

    folder = tmp_path / ".cache" / "akshare" / "minute"
    folder.mkdir(parents=True)
    payload = {
        "symbol": "RB2701",
        "period": "15",
        "fetched_at": 1.0,
        "n": 2,
        "bars": [
            {
                "datetime": "2026-11-10 10:00:00",
                "high": 1,
                "low": 1,
                "close": 1,
            },
            {
                "datetime": "2026-11-11 10:00:00",
                "high": 2,
                "low": 2,
                "close": 2,
            },
        ],
    }
    (folder / "RB2701_15_sina.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    rows = load_minute_bars_on_date(tmp_path, "RB", "2026-11-11", period="15")
    assert len(rows) == 1 and rows[0]["close"] == 2
    assert load_minute_bars_on_date(tmp_path, "RB", "2026-11-09") == []


def test_exit_condition_text_mentions_prices_and_intraday():
    text = exit_condition_text(
        {"stop": 8950.77, "target": 8378.85, "atr": 190.0},
        stop_atr_mult=1.2,
        reward_rr=1.5,
    )
    assert "平仓条件" in text
    assert "止损价=" in text and "止盈价=" in text
    assert "15m" in text
    assert "1.2×ATR" in text


def test_minute_bars_reject_month_vs_continuous_mismatch():
    """EG2701 ~5000 must not gate stops computed on EG0 ~5780."""
    bars = [
        {
            "datetime": "2026-09-03 09:15:00",
            "high": 5051.0,
            "low": 4986.0,
            "close": 5012.0,
        },
        {
            "datetime": "2026-09-03 10:00:00",
            "high": 5020.0,
            "low": 4826.0,
            "close": 4900.0,
        },
    ]
    assert minute_bars_aligned_with_entry(5780.0, bars) is False
    # Same scale as entry → accept.
    aligned = [
        {
            "datetime": "2026-09-03 09:15:00",
            "high": 5800.0,
            "low": 5760.0,
            "close": 5785.0,
        }
    ]
    assert minute_bars_aligned_with_entry(5780.0, aligned) is True
