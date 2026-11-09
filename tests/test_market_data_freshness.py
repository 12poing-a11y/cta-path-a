# -*- coding: utf-8 -*-
"""Market-data freshness and chart-cache persistence regression tests."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from market_data import latest_expected_session_date, save_chart_history, series_sufficient, filter_bars_asof


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


def test_save_chart_history_purges_previously_cached_future_rows(tmp_path: Path, monkeypatch):
    import market_data

    monkeypatch.setattr(
        market_data,
        "latest_expected_session_date",
        lambda: date(2026, 11, 5),
    )
    path = tmp_path / ".cache" / "history" / "SA0.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps([
            {"date": "2026-11-04", "close": 980, "high": 990, "low": 970},
            {"date": "2026-11-30", "close": 989, "high": 989, "low": 989},
        ]),
        encoding="utf-8",
    )
    market_data.save_chart_history(
        "SA",
        [{"date": "2026-11-05", "close": 985, "high": 990, "low": 980}],
        root=tmp_path,
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [row["date"] for row in saved] == ["2026-11-04", "2026-11-05"]




def test_filter_bars_asof_rejects_future_and_invalid_ohlc():
    rows = [
        {"date": "2026-11-04", "high": 990, "low": 970, "close": 985},
        {"date": "2026-11-30", "high": 989, "low": 989, "close": 989},
        {"date": "2026-11-03", "high": 990, "low": 970, "close": 995},
    ]
    assert filter_bars_asof(rows, max_date=date(2026, 11, 5)) == [rows[0]]


def test_filter_bars_asof_caps_future_dates_by_default(monkeypatch):
    import market_data

    monkeypatch.setattr(
        market_data,
        "latest_expected_session_date",
        lambda: date(2026, 11, 5),
    )
    rows = [
        {"date": "2026-11-04", "high": 990, "low": 970, "close": 985},
        {"date": "2026-11-30", "high": 989, "low": 989, "close": 989},
    ]
    assert filter_bars_asof(rows) == [rows[0]]


def test_load_local_bars_ignores_future_sina_and_prefers_history(tmp_path: Path, monkeypatch):
    import market_data
    from desk.regime_board import load_local_bars

    monkeypatch.setattr(
        market_data,
        "latest_expected_session_date",
        lambda: date(2026, 11, 5),
    )
    sina_day = tmp_path / ".cache" / "sina" / "2026-11-06"
    sina_day.mkdir(parents=True)
    (sina_day / "RB0.json").write_text(
        json.dumps(
            [
                {"date": "2026-11-04", "open": 100, "high": 101, "low": 99, "close": 100},
                {"date": "2026-11-30", "open": 110, "high": 111, "low": 109, "close": 110},
            ]
        ),
        encoding="utf-8",
    )
    hist = tmp_path / ".cache" / "history"
    hist.mkdir(parents=True)
    (hist / "RB0.json").write_text(
        json.dumps(
            [
                {"date": "2026-11-04", "open": 100, "high": 101, "low": 99, "close": 100},
                {"date": "2026-11-05", "open": 101, "high": 102, "low": 100, "close": 101},
            ]
        ),
        encoding="utf-8",
    )
    bars, source = load_local_bars(tmp_path, "RB")
    assert [b["date"] for b in bars] == ["2026-11-04", "2026-11-05"]
    assert "history" in source
