"""R1: minute bars must match same-basis daily OHLC (reject false stops)."""
from __future__ import annotations

from minute_data import day_session_bars
from wyckoff_pullback import apply_stop_target_intraday, minute_bars_match_daily

FU0_DAY = {"open": 4363.0, "high": 4463.0, "low": 4293.0, "close": 4418.0}
FU2701_MINUTE = [
    {
        "datetime": "2026-09-28 09:15:00",
        "open": 3990.0,
        "high": 3994.0,
        "low": 3916.0,
        "close": 3951.0,
    },
    {
        "datetime": "2026-09-28 15:00:00",
        "open": 3997.0,
        "high": 3999.0,
        "low": 3967.0,
        "close": 3972.0,
    },
]


def test_fu2701_rejected_against_fu0():
    assert minute_bars_match_daily(FU2701_MINUTE, FU0_DAY, tick=1) is False


def test_dominant_month_contract_accepted():
    day = {"open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0}
    bars = [
        {"datetime": "2026-01-02 09:15:00", "open": 100.0, "high": 108.0, "low": 96.0, "close": 107.0},
        {"datetime": "2026-01-02 15:00:00", "open": 104.0, "high": 106.0, "low": 103.0, "close": 105.0},
    ]
    assert minute_bars_match_daily(bars, day, tick=1) is True


def test_close_mismatch_rejected():
    day = {"open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0}
    bars = [
        {"datetime": "2026-01-02 09:15:00", "open": 100.0, "high": 108.0, "low": 96.0, "close": 107.0},
        {"datetime": "2026-01-02 15:00:00", "open": 104.0, "high": 106.0, "low": 103.0, "close": 108.0},
    ]
    # close 108 vs day 105, tick=1, tol_ticks=2 → diff 3 > 2
    assert minute_bars_match_daily(bars, day, tick=1) is False


def test_day_session_bars_drops_night():
    bars = [
        {"datetime": "2026-01-02 21:15:00", "open": 1, "high": 1, "low": 1, "close": 1},
        {"datetime": "2026-01-02 14:45:00", "open": 2, "high": 2, "low": 2, "close": 2},
        {"date": "2026-01-02", "open": 3, "high": 3, "low": 3, "close": 3},
    ]
    out = day_session_bars(bars)
    assert len(out) == 2
    assert out[0]["datetime"] == "2026-01-02 14:45:00"
    assert out[1].get("date") == "2026-01-02"


def test_old_path_would_false_stop():
    reason, _px = apply_stop_target_intraday(
        "多", 4120.0, 3951.77, 4456.46, FU2701_MINUTE
    )
    assert reason == "stop"
