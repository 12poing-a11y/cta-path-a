# -*- coding: utf-8 -*-
"""R2: night-session bars belong to the next trading day."""
from __future__ import annotations

import json
from pathlib import Path

from minute_data import load_minute_bars_on_trading_day, trading_day_of

# Fri 2026-09-25 → Mon 2026-09-28 spans National Day? Use a plain weekend + Oct holiday.
SESSIONS = [
    "2026-09-23",  # Wed
    "2026-09-24",  # Thu
    "2026-09-25",  # Fri
    "2026-09-28",  # Mon
    "2026-09-29",  # Tue
    "2026-09-30",  # Wed — last before National Day holiday
    "2026-10-09",  # first after National Day
    "2026-10-12",  # Mon
]
SESSION_SET = set(SESSIONS)


def test_friday_night_to_monday():
    assert trading_day_of("2026-09-25 21:15:00", SESSIONS, SESSION_SET) == "2026-09-28"


def test_saturday_early_to_monday():
    assert trading_day_of("2026-09-26 01:30:00", SESSIONS, SESSION_SET) == "2026-09-28"


def test_wednesday_day_session():
    assert trading_day_of("2026-09-23 14:45:00", SESSIONS, SESSION_SET) == "2026-09-23"


def test_tuesday_early_morning():
    # Tue 00:30 belongs to Tuesday trading day (after Mon night)
    assert trading_day_of("2026-09-29 00:30:00", SESSIONS, SESSION_SET) == "2026-09-29"


def test_pre_holiday_night_to_post_holiday():
    assert trading_day_of("2026-09-30 21:15:00", SESSIONS, SESSION_SET) == "2026-10-09"


def test_day_session_outside_calendar_returns_none():
    assert trading_day_of("2026-10-01 14:45:00", SESSIONS, SESSION_SET) is None


def test_load_minute_bars_on_trading_day_tmp(tmp_path: Path):
    """Prev-evening 21:15 → today; same-calendar-evening 21:15 → not today."""
    cache = tmp_path / ".cache" / "akshare" / "minute"
    cache.mkdir(parents=True)
    payload = {
        "symbol": "XX2601",
        "period": "15",
        "fetched_at": 1.0,
        "bars": [
            {
                "datetime": "2026-09-24 21:15:00",
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
            },
            {
                "datetime": "2026-09-25 14:45:00",
                "open": 2,
                "high": 2,
                "low": 2,
                "close": 2,
            },
            {
                "datetime": "2026-09-25 21:15:00",
                "open": 3,
                "high": 3,
                "low": 3,
                "close": 3,
            },
        ],
    }
    (cache / "XX2601_15_sina.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    sessions = ["2026-09-24", "2026-09-25", "2026-09-28"]
    bars = load_minute_bars_on_trading_day(
        tmp_path, "XX", "2026-09-25", period="15", sessions=sessions
    )
    dts = [str(b.get("datetime")) for b in bars]
    assert "2026-09-24 21:15:00" in dts
    assert "2026-09-25 14:45:00" in dts
    assert "2026-09-25 21:15:00" not in dts
