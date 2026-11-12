from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from cotton_npd import event_study

TZ = ZoneInfo("Asia/Shanghai")


def bars(n=40):
    return [
        {"date": date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + i),
         "open": 100.0 + i, "close": 101.0 + i, "volume": 1000, "oi": 2000}
        for i in range(n)
    ]


def event(day= date(2026, 1, 5), score=2):
    return {
        "event_id": "e1",
        "published_at": datetime(2026, 1, 5, 10, 0, tzinfo=TZ),
        "event_date": day,
        "category": "weather",
        "headline": "test event",
        "score": score,
        "source": "test",
    }


def test_entry_is_strictly_after_event_date_and_no_same_day_fill():
    rows, _ = event_study(bars(), [event()])
    assert rows[0]["entry_date"] == "2026-01-06"
    assert rows[0]["entry_open"] == 105.0


def test_positive_news_with_falling_market_is_divergence():
    data = bars()
    # Entry 2026-01-06 open = 105; one-session exit close is set below entry.
    data[5]["close"] = 100.0
    rows, summary = event_study(data, [event(score=3)])
    assert rows[0]["divergence_1d"] is True
    assert rows[0]["directional_1d"] < 0
    assert summary["horizons"]["1"]["divergence_rate"] == 1.0


def test_negative_news_with_rising_market_is_divergence():
    rows, _ = event_study(bars(), [event(score=-2)])
    assert rows[0]["divergence_1d"] is True


def test_cost_reduces_both_directional_and_contrarian_returns():
    gross, _ = event_study(bars(), [event()], round_trip_cost_bps=0)
    net, _ = event_study(bars(), [event()], round_trip_cost_bps=10)
    assert net[0]["directional_1d"] == pytest.approx(gross[0]["directional_1d"] - 0.001)
    assert net[0]["contrarian_1d"] == pytest.approx(gross[0]["contrarian_1d"] - 0.001)


def test_neutral_event_is_not_tradable():
    rows, _ = event_study(bars(), [event(score=0)])
    assert rows[0]["directional_1d"] is None
    assert rows[0]["divergence_1d"] is None
