# -*- coding: utf-8 -*-
"""Market-data freshness and chart-cache persistence regression tests."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from market_data import latest_expected_session_date, save_chart_history, series_sufficient\nfrom historical_backtest import _parse_zl_history


TZ = ZoneInfo("Asia/Shanghai")


def _bars(last_day: date, n: int = 80) -> list[dict]:
    rows = []
    for offset in range(n - 1, -1, -1):
        day = last_day - timedelta(days=offset)
        rows.append(
            {
                "date": day.isoformat(),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 10,
            }
        )
    return rows


def test_latest_expected_session_respects_shanghai_1500_cutoff():
    assert latest_expected_session_date(datetime(2026, 11, 6, 14, 59, tzinfo=TZ)) == date(2026, 11, 5)
    assert latest_expected_session_date(datetime(2026, 11, 6, 15, 0, tzinfo=TZ)) == date(2026, 11, 6)


def test_latest_expected_session_skips_weekends():
    assert latest_expected_session_date(datetime(2026, 11, 7, 12, 0, tzinfo=TZ)) == date(2026, 11, 6)
    assert latest_expected_session_date(datetime(2026, 11, 9, 8, 0, tzinfo=TZ)) == date(2026, 11, 6)


def test_series_sufficient_rejects_missing_expected_session():
    today = date.today()
    stale = _bars(today - timedelta(days=1))
    fresh = _bars(today)
    assert not series_sufficient(stale, 80, expected_date=today)
    assert series_sufficient(fresh, 80, expected_date=today)
    # Existing callers without an expected date retain the legacy age/shape check.
    assert series_sufficient(stale, 80)


def test_save_chart_history_merges_without_dropping_prior_bars(tmp_path: Path):
    first = [{"date": "2026-11-04", "close": 100, "high": 101, "low": 99}]
    second = [{"date": "2026-11-05", "close": 102, "high": 103, "low": 101}]
    path = save_chart_history("CF", first, root=tmp_path)
    assert path == tmp_path / ".cache" / "history" / "CF0.json"
    save_chart_history("CF", second, root=tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [row["date"] for row in saved] == ["2026-11-04", "2026-11-05"]
    assert saved[-1]["close"] == 102

\n\ndef test_ifind_parser_rejects_future_rows_and_invalid_ohlc():
    answer = """| 日期 | 开盘价 | 最高价 | 最低价 | 收盘价 | 成交量 |
|---|---:|---:|---:|---:|---:|
| 2026-11-04 | 980 | 990 | 970 | 985 | 1200 |
| 2026-11-30 | 989 | 989 | 989 | 989 | |
| 2026-11-03 | 980 | 990 | 970 | 995 | 800 |
"""
    rows = _parse_zl_history(answer, max_date=date(2026, 11, 5))
    assert [row["date"] for row in rows] == ["2026-11-04"]
    assert rows[0]["close"] == 985


def test_ifind_parser_caps_future_dates_by_default(monkeypatch):
    import market_data

    monkeypatch.setattr(
        market_data,
        "latest_expected_session_date",
        lambda: date(2026, 11, 5),
    )
    answer = """| 日期 | 开盘价 | 最高价 | 最低价 | 收盘价 |
|---|---:|---:|---:|---:|
| 2026-11-04 | 980 | 990 | 970 | 985 |
| 2026-11-30 | 989 | 989 | 989 | 989 |
"""
    rows = _parse_zl_history(answer)
    assert [row["date"] for row in rows] == ["2026-11-04"]
