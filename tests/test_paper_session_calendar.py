# -*- coding: utf-8 -*-
"""R3 step0: paper_book session calendar excludes weekend / null-open bars."""
from __future__ import annotations

import json
from pathlib import Path

from minute_data import trading_day_of
from paper_book import _is_session_bar, _local_daily_bar, _session_dates


def _write_history(tmp_path: Path, code: str, rows: list[dict]) -> None:
    folder = tmp_path / ".cache" / "history"
    folder.mkdir(parents=True)
    (folder / f"{code}0.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8"
    )


def test_session_dates_exclude_weekend_and_null_open(tmp_path: Path):
    rows = [
        {"date": "2026-10-23", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
        {"date": "2026-10-24", "high": 100.5, "low": 100.5, "close": 100.5},  # Sat, no open
        {"date": "2026-10-25", "high": 100.5, "low": 100.5, "close": 100.5},  # Sun
        {"date": "2026-10-27", "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5},
        {"date": "2026-10-28", "open": None, "high": 101.5, "low": 101.5, "close": 101.5},
    ]
    _write_history(tmp_path, "FU", rows)
    sessions = _session_dates(tmp_path, "FU")
    assert sessions == ["2026-10-23", "2026-10-27"]
    assert _local_daily_bar(tmp_path, "FU", "2026-10-24") is None
    assert _local_daily_bar(tmp_path, "FU", "2026-10-27")["open"] == 101.0
    assert _is_session_bar(rows[0]) is True
    assert _is_session_bar(rows[1]) is False


def test_friday_night_maps_to_monday_with_filtered_calendar(tmp_path: Path):
    rows = [
        {"date": "2026-10-23", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},  # Fri
        {"date": "2026-10-24", "high": 1.0, "low": 1.0, "close": 1.0},  # Sat junk
        {"date": "2026-10-25", "high": 1.0, "low": 1.0, "close": 1.0},  # Sun junk
        {"date": "2026-10-27", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},  # Mon
    ]
    _write_history(tmp_path, "FU", rows)
    sessions = _session_dates(tmp_path, "FU")
    session_set = set(sessions)
    assert "2026-10-24" not in sessions
    assert trading_day_of("2026-10-23 21:15:00", sessions, session_set) == "2026-10-27"
