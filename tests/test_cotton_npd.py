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


def event(day=date(2026, 1, 5), score=2, *, family="USDA", category="USDA_OTHER", status="accepted"):
    return {
        "event_id": "e1",
        "published_at": datetime(2026, 1, 5, 10, 0, tzinfo=TZ),
        "event_date": day,
        "category": category,
        "family": family,
        "headline": "test event",
        "score": score,
        "source": "https://example.official.test/release",
        "official_url": "https://example.official.test/release",
        "official_excerpt": "official excerpt for test event",
        "status": status,
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


def test_entry_day_reminders_only_on_entry_session():
    from cotton_npd import entry_day_reminders

    data = bars()
    ev = event(day=date(2026, 1, 5), score=2)
    on = entry_day_reminders(data, [ev], asof="2026-01-06")
    assert on["is_entry_day"] is True
    assert on["counts_toward_score"] is False
    assert on["shadow"] is True
    assert on["n"] == 1
    assert on["reminders"][0]["lean"] == "利多"
    assert on["reminders"][0]["entry_open"] == 105.0

    off = entry_day_reminders(data, [ev], asof="2026-01-07")
    assert off["is_entry_day"] is False
    assert off["n"] == 0
    assert off["reminders"] == []


def test_publish_calendar_day_is_not_entry_day():
    from cotton_npd import entry_day_reminders

    # Same-day publish must not fire a reminder (no look-ahead fill).
    pack = entry_day_reminders(bars(), [event(day=date(2026, 1, 5), score=-1)], asof="2026-01-05")
    assert pack["is_entry_day"] is False


def test_pending_events_excluded_from_stats_and_reminders(tmp_path):
    from cotton_npd import entry_day_reminders, event_study, load_events

    path = tmp_path / "events.csv"
    path.write_text(
        "\n".join(
            [
                "event_id,published_at,family,category,headline,score,official_url,official_excerpt,status",
                "ok,2026-01-05T10:00:00+08:00,CN,CN_CASDE,has provenance,1,https://www.agri.cn/x,本月产量调增官方原文,accepted",
                "bad,,CN,CN_RESERVE,missing provenance,1,,,待核",
                "",
            ]
        ),
        encoding="utf-8",
    )
    events = load_events(path)
    by_id = {e["event_id"]: e for e in events}
    assert by_id["ok"]["status"] == "accepted"
    assert by_id["bad"]["status"] == "待核"
    rows, summary = event_study(bars(), events)
    assert summary["accepted_count"] == 1
    assert summary["pending_count"] == 1
    assert "CN" in summary["by_family"]
    assert "USDA" in summary["by_family"]
    assert "combined" in summary["by_family"]
    assert summary["by_family"]["CN"]["horizons"]["1"]["n"] == 1
    assert summary["by_family"]["USDA"]["horizons"]["1"]["n"] == 0
    # Pending must not create an entry-day reminder even if dates were filled later.
    rem = entry_day_reminders(bars(), events, asof="2026-01-06")
    assert rem["n"] == 1
    assert rem["reminders"][0]["event_id"] == "ok"


def test_family_split_china_vs_usda():
    cn = event(score=1, family="CN", category="CN_CASDE")
    cn["event_id"] = "cn1"
    us = event(score=-1, family="USDA", category="USDA_WASDE")
    us["event_id"] = "us1"
    data = bars()
    data[5]["close"] = 110.0  # up day after entry → CN directional win, USDA loss
    _rows, summary = event_study(data, [cn, us])
    assert summary["by_family"]["CN"]["horizons"]["1"]["n"] == 1
    assert summary["by_family"]["USDA"]["horizons"]["1"]["n"] == 1
    assert summary["by_family"]["combined"]["horizons"]["1"]["n"] == 2
    assert summary["by_family"]["CN"]["horizons"]["1"]["news_direction_win_rate"] == 1.0
    assert summary["by_family"]["USDA"]["horizons"]["1"]["news_direction_win_rate"] == 0.0
